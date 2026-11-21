from __future__ import annotations

import gc
import time
from datetime import datetime

from PyQt6.QtCore import QByteArray, QCoreApplication, QEvent, QPoint, QTimer, QUrl, Qt
from PyQt6.QtGui import QColor, QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import Settings, data_root, normalize_domain
from ..prompts import compaction_prompt, resume_prompt
from ..sessions import (
    STATE_BLOCKED,
    STATE_EXHAUSTED,
    STATE_LIMITED,
    STATE_OK,
    STATE_TITLES,
    STATE_WARN,
    Session,
    SessionStore,
    human_age,
    human_tokens,
    today_str,
)
from ..theme import STATE_COLORS
from ..transfer import AutoTransfer
from ..web import (
    ERROR_LIMIT_RE,
    SessionRuntime,
    WebPage,
    dir_size_bytes,
    make_view,
    purge_trash,
    retire_dir,
)
from .cards import SessionCard
from .dialogs import SessionManagerDialog, SettingsDialog, TransferDialog

PLACEHOLDER_TEXT = (
    "Выбери сессию слева\n\n"
    "Каждая сессия — отдельный профиль браузера:\n"
    "свои cookies и хранилище, поэтому аккаунты не пересекаются."
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.root = data_root()
        (self.root / "profiles").mkdir(parents=True, exist_ok=True)
        (self.root / "trash").mkdir(parents=True, exist_ok=True)
        purge_trash(self.root / "trash")

        self.settings = Settings.load(self.root / "settings.json")
        self.store = SessionStore(self.root / "sessions.json")
        self.store.load()

        self.views: dict[str, QWebEngineView] = {}
        self.runtimes: dict[str, SessionRuntime] = {}
        self.runtimes_by_sid = self.runtimes
        self.cards: dict[str, SessionCard] = {}
        self._card_order: list[str] = []
        self._js_seen: dict[str, int] = {}
        self._banner_dismissed: set[tuple[str, str]] = set()
        self._popups: list[QWebEngineView] = []
        self._fullscreen_view: QWebEngineView | None = None
        self._transfer: AutoTransfer | None = None
        self.current_sid: str | None = None

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(self.settings.poll_seconds * 1000)
        self.poll_timer.timeout.connect(self._poll_current)
        self.poll_timer.start()

        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(1200)
        self.save_timer.timeout.connect(self._flush)

        self.setWindowTitle("BigSeek Desktop")
        self.resize(1360, 900)
        if self.settings.window_geometry:
            try:
                self.restoreGeometry(QByteArray.fromBase64(self.settings.window_geometry.encode()))
            except Exception:
                pass

        self._build_ui()
        self._install_shortcuts()

        if not self.store.sessions:
            self.store.create("Основная")
            self.store.save()

        self.refresh_cards()
        QTimer.singleShot(0, self._startup_load)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.sidebar = self._build_sidebar()
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)
        right_lay.addWidget(self._build_toolbar())
        right_lay.addWidget(self._build_banner())
        right_lay.addWidget(self._build_transfer_panel())

        self.stack = QStackedWidget()
        self.placeholder = QLabel(PLACEHOLDER_TEXT)
        self.placeholder.setObjectName("placeholder")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.stack.addWidget(self.placeholder)
        right_lay.addWidget(self.stack, 1)

        # Draggable divider: the session list can be resized and hidden.
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("mainSplit")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(5)
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        lay.addWidget(self.splitter, 1)

        self._side_save_timer = QTimer(self)
        self._side_save_timer.setSingleShot(True)
        self._side_save_timer.setInterval(400)
        self._side_save_timer.timeout.connect(
            lambda: self.settings.save(self.root / "settings.json")
        )
        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        self._apply_sidebar_state()

        self.statusBar().showMessage("Готово", 3000)

    def _apply_sidebar_state(self) -> None:
        visible = bool(self.settings.sidebar_visible)
        self._set_sidebar_visible(visible)
        self._sync_sidebar_button(visible)

    def _set_sidebar_visible(self, visible: bool) -> None:
        total = max(self.splitter.width(), 900)
        width = max(200, min(560, int(self.settings.sidebar_width)))
        if visible:
            self.sidebar.setMinimumWidth(200)
            self.sidebar.setMaximumWidth(560)
            self.sidebar.setVisible(True)
            self.splitter.setHandleWidth(5)
            self.splitter.setSizes([width, max(400, total - width)])
        else:
            self.sidebar.setMinimumWidth(0)
            self.sidebar.setMaximumWidth(0)
            self.sidebar.setVisible(False)
            self.splitter.setHandleWidth(0)
            self.splitter.setSizes([0, total])

    def _sync_sidebar_button(self, visible: bool) -> None:
        self.sidebar_btn.setText("☰")
        self.sidebar_btn.setToolTip(
            "Скрыть панель сессий (Ctrl+B)"
            if visible
            else "Показать панель сессий (Ctrl+B)"
        )

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        sizes = self.splitter.sizes()
        if len(sizes) >= 2 and sizes[0] >= 200:
            self.settings.sidebar_width = sizes[0]
            self.settings.sidebar_visible = True
            self._side_save_timer.start()

    def toggle_sidebar(self) -> None:
        visible = not self.sidebar.isVisible()
        if not visible:
            sizes = self.splitter.sizes()
            if sizes and sizes[0] >= 200:
                self.settings.sidebar_width = sizes[0]
        self.settings.sidebar_visible = visible
        self._set_sidebar_visible(visible)
        self._sync_sidebar_button(visible)
        self.settings.save(self.root / "settings.json")
        self.statusBar().showMessage(
            "Панель сессий показана" if visible else "Панель сессий скрыта", 2500
        )

    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("sidebar")
        side.setMinimumWidth(200)
        side.setMaximumWidth(560)
        v = QVBoxLayout(side)
        v.setContentsMargins(12, 14, 12, 12)
        v.setSpacing(10)

        brand_box = QVBoxLayout()
        brand_box.setSpacing(1)
        brand = QLabel("BigSeek Desktop")
        brand.setObjectName("brand")
        brand_sub = QLabel("изолированные профили")
        brand_sub.setObjectName("brandSub")
        brand_box.addWidget(brand)
        brand_box.addWidget(brand_sub)
        v.addLayout(brand_box)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        self.cards_layout = QVBoxLayout(host)
        self.cards_layout.setContentsMargins(0, 4, 0, 4)
        self.cards_layout.setSpacing(7)
        self.cards_layout.addStretch(1)
        self.scroll.setWidget(host)
        v.addWidget(self.scroll, 1)

        self.new_btn = QPushButton("＋  Новая сессия")
        self.new_btn.setObjectName("primary")
        self.new_btn.clicked.connect(lambda: self.create_session())
        v.addWidget(self.new_btn)

        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        manager_btn = QPushButton("Сессии")
        manager_btn.clicked.connect(self.open_manager)
        settings_btn = QPushButton("Настройки")
        settings_btn.clicked.connect(self.open_settings)
        bottom.addWidget(manager_btn)
        bottom.addWidget(settings_btn)
        v.addLayout(bottom)
        return side

    def _build_toolbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("toolbar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(10, 8, 10, 8)
        h.setSpacing(4)

        def nav_btn(text: str, tip: str) -> QPushButton:
            b = QPushButton(text)
            b.setObjectName("nav")
            b.setFixedSize(30, 30)
            b.setToolTip(tip)
            return b

        self.back_btn = nav_btn("←", "Назад")
        self.fwd_btn = nav_btn("→", "Вперёд")
        self.reload_btn = nav_btn("⟳", "Обновить (Ctrl+R)")
        self.home_btn = nav_btn("⌂", "На главную")
        self.back_btn.clicked.connect(lambda: self._nav("back"))
        self.fwd_btn.clicked.connect(lambda: self._nav("forward"))
        self.reload_btn.clicked.connect(lambda: self._nav("reload"))
        self.home_btn.clicked.connect(lambda: self._nav("home"))

        self.sidebar_btn = nav_btn("☰", "Скрыть панель сессий (Ctrl+B)")
        self.sidebar_btn.clicked.connect(self.toggle_sidebar)
        h.addWidget(self.sidebar_btn)
        for b in (self.back_btn, self.fwd_btn, self.reload_btn, self.home_btn):
            h.addWidget(b)

        self.url_bar = QLineEdit()
        self.url_bar.setObjectName("urlbar")
        self.url_bar.setPlaceholderText("адрес…")
        self.url_bar.returnPressed.connect(self._navigate_from_bar)
        h.addWidget(self.url_bar, 1)

        self.usage_chip = QLabel("— / —")
        self.usage_chip.setObjectName("chip")
        h.addWidget(self.usage_chip)

        self.transfer_btn = QPushButton("⇄ Перенос")
        self.transfer_btn.setToolTip("Автоперенос контекста в другую сессию (Ctrl+T)")
        self.transfer_btn.clicked.connect(lambda: self.open_transfer_dialog())
        h.addWidget(self.transfer_btn)

        self.menu_btn = QPushButton("⋯")
        self.menu_btn.setObjectName("nav")
        self.menu_btn.setFixedSize(30, 30)
        self.menu_btn.clicked.connect(self._show_toolbar_menu)
        h.addWidget(self.menu_btn)

        self._sync_nav_buttons()
        return bar

    def _build_banner(self) -> QWidget:
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        self.banner.setProperty("state", "warn")
        self.banner.hide()
        lay = QHBoxLayout(self.banner)
        lay.setContentsMargins(14, 10, 10, 10)
        lay.setSpacing(10)

        icon = QLabel("⚠")
        icon.setStyleSheet("font-size: 16px;")
        lay.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        text_box = QVBoxLayout()
        text_box.setSpacing(1)
        self.banner_title = QLabel("Лимит близко")
        self.banner_title.setObjectName("bannerTitle")
        self.banner_text = QLabel("")
        self.banner_text.setObjectName("bannerText")
        self.banner_text.setWordWrap(True)
        text_box.addWidget(self.banner_title)
        text_box.addWidget(self.banner_text)
        lay.addLayout(text_box, 1)

        self.banner_copy = QPushButton("Промт сжатия")
        self.banner_copy.clicked.connect(self._banner_copy_compact)
        self.banner_transfer = QPushButton("Перенести")
        self.banner_transfer.setObjectName("primary")
        self.banner_transfer.clicked.connect(lambda: self.open_transfer_dialog())
        self.banner_reset = QPushButton("Сбросить")
        self.banner_reset.setObjectName("ghost")
        self.banner_reset.setToolTip("Сбросить состояние сессии")
        self.banner_reset.clicked.connect(self._banner_reset_clicked)
        close_btn = QPushButton("✕")
        close_btn.setObjectName("ghost")
        close_btn.setFixedWidth(28)
        close_btn.clicked.connect(self._dismiss_banner)
        for b in (self.banner_copy, self.banner_transfer, self.banner_reset, close_btn):
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        return self.banner

    def _build_transfer_panel(self) -> QWidget:
        self.transfer_panel = QFrame()
        self.transfer_panel.setObjectName("banner")
        self.transfer_panel.setProperty("state", "warn")
        self.transfer_panel.hide()
        lay = QHBoxLayout(self.transfer_panel)
        lay.setContentsMargins(14, 10, 10, 10)
        lay.setSpacing(10)

        icon = QLabel("⇄")
        icon.setStyleSheet("font-size: 16px;")
        lay.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        text_box = QVBoxLayout()
        text_box.setSpacing(1)
        self.transfer_title = QLabel("Автоперенос")
        self.transfer_title.setObjectName("bannerTitle")
        self.transfer_text = QLabel("")
        self.transfer_text.setObjectName("bannerText")
        self.transfer_text.setWordWrap(True)
        text_box.addWidget(self.transfer_title)
        text_box.addWidget(self.transfer_text)
        lay.addLayout(text_box, 1)

        self.transfer_progress = QProgressBar()
        self.transfer_progress.setRange(0, 0)
        self.transfer_progress.setTextVisible(False)
        self.transfer_progress.setFixedSize(130, 6)
        lay.addWidget(self.transfer_progress, 0, Qt.AlignmentFlag.AlignVCenter)

        self.transfer_cancel = QPushButton("Отмена")
        self.transfer_cancel.setObjectName("ghost")
        self.transfer_cancel.clicked.connect(self._transfer_cancel_clicked)
        lay.addWidget(self.transfer_cancel, 0, Qt.AlignmentFlag.AlignVCenter)
        return self.transfer_panel

    def _install_shortcuts(self) -> None:
        def add(seq: str, fn) -> None:
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(fn)

        add("Ctrl+N", lambda: self.create_session())
        add("Ctrl+R", lambda: self._nav("reload"))
        add("F5", lambda: self._nav("reload"))
        add("Ctrl+,", self.open_settings)
        add("Ctrl+Shift+M", self.open_manager)
        add("Ctrl+T", lambda: self.open_transfer_dialog())
        add("Ctrl+B", self.toggle_sidebar)
        add("Ctrl+L", self._focus_url)
        add("Ctrl+Tab", self._cycle_session)
        add("Ctrl+=", lambda: self._zoom(+0.1))
        add("Ctrl+-", lambda: self._zoom(-0.1))
        add("Ctrl+0", lambda: self._zoom(0))
        for i in range(1, 10):
            add(f"Ctrl+{i}", lambda idx=i - 1: self._activate_index(idx))

    def _focus_url(self) -> None:
        self.url_bar.setFocus()
        self.url_bar.selectAll()

    def _activate_index(self, idx: int) -> None:
        if 0 <= idx < len(self.store.sessions):
            self.activate_session(self.store.sessions[idx].id)

    def _cycle_session(self) -> None:
        if not self.store.sessions:
            return
        idx = self.store.index_of(self.current_sid or "")
        nxt = self.store.sessions[(idx + 1) % len(self.store.sessions)]
        self.activate_session(nxt.id)

    def _zoom(self, delta: float) -> None:
        view = self.current_view()
        if view is None:
            return
        z = 1.0 if delta == 0 else max(0.5, min(2.5, view.zoomFactor() + delta))
        view.setZoomFactor(z)
        self.statusBar().showMessage(f"Масштаб: {int(round(z * 100))}%", 2000)

    # ------------------------------------------------------------- startup
    def _startup_load(self) -> None:
        ids = [s.id for s in self.store.sessions]
        if not ids:
            self._show_placeholder()
            return
        target = self.settings.last_session_id if self.settings.last_session_id in ids else ids[-1]
        if self.settings.load_all_sessions:
            for i, sid in enumerate(ids):
                QTimer.singleShot(i * 250, lambda s=sid: self._ensure_runtime(s))
            self.activate_session(target)
        elif self.settings.load_last_session:
            self.activate_session(target)
        else:
            self._show_placeholder()

    def _show_placeholder(self) -> None:
        self.current_sid = None
        self.setWindowTitle("BigSeek Desktop")
        self.stack.setCurrentWidget(self.placeholder)
        self.url_bar.clear()
        self.usage_chip.setText("— / —")
        self.usage_chip.setProperty("tone", "")
        self._restyle(self.usage_chip)
        self.banner.hide()
        self._sync_nav_buttons()
        self.refresh_cards()

    # ------------------------------------------------------------- sessions
    def current_view(self) -> QWebEngineView | None:
        if not self.current_sid:
            return None
        return self.views.get(self.current_sid)

    def _session_start_url(self, session: Session) -> str:
        domain = self.settings.domain
        if session.last_url:
            last = QUrl(session.last_url)
            if last.host() and last.host() == QUrl(domain).host():
                return session.last_url
        return domain

    def _ensure_runtime(self, sid: str) -> QWebEngineView | None:
        view = self.views.get(sid)
        if view is not None:
            return view
        session = self.store.get(sid)
        if session is None:
            return None

        runtime = SessionRuntime(sid, self.root, self.settings, self)
        runtime.download_started.connect(
            lambda name: self.statusBar().showMessage(f"Скачивание: {name}", 6000)
        )
        view = make_view(runtime, owner=self)
        page = view.page()
        page.setBackgroundColor(QColor("#0f1117"))
        page.loadFinished.connect(lambda ok, s=sid: self._on_load_finished(s, ok))
        page.urlChanged.connect(lambda url, s=sid: self._on_url_changed(s, url))
        try:
            page.fullScreenRequested.connect(self._on_fullscreen)
        except Exception:
            pass

        self.stack.addWidget(view)
        self.views[sid] = view
        self.runtimes[sid] = runtime
        view.setUrl(QUrl(self._session_start_url(session)))
        return view

    def activate_session(self, sid: str) -> None:
        session = self.store.get(sid)
        if session is None:
            return
        view = self._ensure_runtime(sid)
        if view is None:
            return
        self.current_sid = sid
        self.stack.setCurrentWidget(view)
        self.setWindowTitle(f"BigSeek Desktop — {session.name}")
        self.settings.last_session_id = sid
        session.last_used = datetime.now().isoformat(timespec="seconds")
        session.roll_day()
        self.refresh_cards()
        self._sync_nav_buttons()
        self._sync_url_bar()
        self._sync_header()
        self._update_banner()
        self._schedule_save()
        QTimer.singleShot(700, self._poll_current)
        self.statusBar().showMessage(f"Сессия: {session.name}", 2500)

    def create_session(self) -> Session:
        s = self.store.create()
        self.store.save()
        self.refresh_cards()
        self.activate_session(s.id)
        return s

    def rename_session(self, sid: str | None = None) -> None:
        sid = sid or self.current_sid
        if not sid:
            return
        session = self.store.get(sid)
        if session is None:
            return
        name, ok = QInputDialog.getText(
            self, "Переименовать сессию", "Название:", QLineEdit.EchoMode.Normal, session.name
        )
        if ok and name.strip():
            session.name = name.strip()[:60]
            self.store.save()
            self.refresh_cards()
            self._update_banner()
            if sid == self.current_sid:
                self.setWindowTitle(f"BigSeek Desktop — {session.name}")

    def reset_usage(self, sid: str) -> None:
        session = self.store.get(sid)
        if session is None:
            return
        session.reset_usage()
        self.store.save()
        self.refresh_cards()
        self._sync_header()

    def reset_context(self, sid: str) -> None:
        """Zero the token counter without touching the browser profile."""
        session = self.store.get(sid)
        if session is None:
            return
        session.reset_context()
        self.store.save()
        self.refresh_cards()
        self._sync_header()
        self._update_banner()
        if sid == self.current_sid:
            self.statusBar().showMessage("Счётчик токенов сброшен", 3000)

    def reset_status(self, sid: str) -> None:
        session = self.store.get(sid)
        if session is None:
            return
        session.status = STATE_OK
        session.status_reason = ""
        session.status_reset_at = time.time()
        session.limit_reset_at = 0.0
        session.limit_reset_text = ""
        self.store.save()
        self.refresh_cards()
        self._update_banner()
        self._sync_header()
        self.statusBar().showMessage("Статус сессии сброшен", 3000)

    def _reset_current_status(self) -> None:
        if self.current_sid:
            self.reset_status(self.current_sid)

    def _banner_reset_clicked(self) -> None:
        sid = self.current_sid
        if not sid:
            return
        session = self.store.get(sid)
        if session is None:
            return
        if self.effective_state(session) == STATE_WARN:
            self.reset_context(sid)
        else:
            self.reset_status(sid)

    def _auto_reset_limit(self, session: Session, notify: bool = False) -> None:
        """The site announced a reset time and it has passed — clear the block."""
        session.status = STATE_OK
        session.status_reason = ""
        session.status_reset_at = time.time()
        session.limit_reset_at = 0.0
        session.limit_reset_text = ""
        session.reset_usage()
        session.reset_context()
        self.store.save()
        if notify and session.id == self.current_sid:
            self.statusBar().showMessage(
                f"Лимит сессии «{session.name}» обновлён, счётчик сброшен", 6000
            )

    def _check_limit_resets(self) -> bool:
        now = time.time()
        changed = False
        for session in self.store.sessions:
            if session.status not in (STATE_BLOCKED, STATE_LIMITED):
                continue
            due = session.limit_reset_at > 0 and session.limit_reset_at <= now
            new_day = session.limit_reset_at <= 0 and session.usage_date != today_str()
            if due or new_day:
                self._auto_reset_limit(
                    session, notify=session.id == self.current_sid
                )
                changed = True
        return changed

    def _reset_hint(self, session: Session) -> str:
        if session.limit_reset_at <= 0:
            return ""
        when = datetime.fromtimestamp(session.limit_reset_at)
        now = datetime.now()
        if when.date() == now.date():
            text = f"в {when:%H:%M}"
        else:
            text = f"{when:%d.%m в %H:%M}"
        return f" Ожидаемый сброс лимита: {text}."

    def mark_transferred(self, sid: str) -> None:
        session = self.store.get(sid)
        if session is None:
            return
        session.status = STATE_EXHAUSTED
        session.status_reason = "контекст перенесён"
        session.status_at = time.time()
        self.store.save()
        self.refresh_cards()
        self._update_banner()
        self._sync_header()

    def _set_status(self, sid: str, status: str, reason: str = "") -> None:
        session = self.store.get(sid)
        if session is None:
            return
        if session.status == status and session.status_reason == reason:
            return
        session.status = status
        session.status_reason = reason
        session.status_at = time.time()
        self.store.save()
        self.refresh_cards()
        if sid == self.current_sid:
            self._update_banner()
            self._sync_header()

    def effective_state(self, session: Session) -> str:
        if (
            session.status in (STATE_BLOCKED, STATE_LIMITED)
            and session.limit_reset_at > 0
            and session.limit_reset_at <= time.time()
        ):
            self._auto_reset_limit(session)
        if session.status == STATE_BLOCKED:
            return STATE_BLOCKED
        if session.status == STATE_EXHAUSTED:
            return STATE_EXHAUSTED
        if session.status == STATE_LIMITED:
            if time.time() - session.status_at > 600:
                session.status = STATE_OK
                session.status_reason = ""
                self._schedule_save()
            else:
                return STATE_LIMITED
        limit = self.settings.context_limit
        if limit > 0 and session.used_context_tokens >= limit * self.settings.context_warn:
            return STATE_WARN
        return STATE_OK

    def profile_size_bytes(self, sid: str) -> int:
        return dir_size_bytes(self.root / "profiles" / sid)

    def clear_session_data(self, sid: str) -> None:
        session = self.store.get(sid)
        if session is None:
            return
        answer = QMessageBox.question(
            self,
            "Очистить данные сессии",
            f"Удалить cookies, вход и хранилище сайта для сессии «{session.name}»?\n\n"
            "Сама сессия останется в списке, но сайт откроется как для нового пользователя.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        was_current = sid == self.current_sid
        self._dispose_runtime(sid)
        ok = retire_dir(self.root / "profiles" / sid, self.root / "trash")
        QApplication.restoreOverrideCursor()

        session.last_url = None
        if session.status in (STATE_BLOCKED, STATE_LIMITED):
            session.status = STATE_OK
            session.status_reason = ""
            session.status_reset_at = time.time()
        self.store.save()
        self.refresh_cards()
        if was_current:
            self.activate_session(sid)
        if ok:
            self.statusBar().showMessage(f"Данные сессии «{session.name}» очищены", 5000)
        else:
            QMessageBox.warning(
                self,
                "Не всё удалилось",
                "Часть файлов профиля занята. Остатки будут удалены при следующем запуске.",
            )

    def delete_session(self, sid: str) -> None:
        session = self.store.get(sid)
        if session is None:
            return
        answer = QMessageBox.question(
            self,
            "Удалить сессию",
            f"Удалить сессию «{session.name}» вместе со всеми её данными?\n"
            "Это действие нельзя отменить.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        was_current = sid == self.current_sid
        self._dispose_runtime(sid)
        retire_dir(self.root / "profiles" / sid, self.root / "trash")
        self.store.remove(sid)
        if self.settings.last_session_id == sid:
            self.settings.last_session_id = None
        self.store.save()
        QApplication.restoreOverrideCursor()

        if was_current:
            if self.store.sessions:
                self.activate_session(self.store.sessions[-1].id)
            else:
                self._show_placeholder()
        self.refresh_cards()
        self._update_banner()

    def _dispose_runtime(self, sid: str) -> None:
        view = self.views.pop(sid, None)
        runtime = self.runtimes.pop(sid, None)
        self._js_seen.pop(sid, None)
        if view is not None:
            self.stack.removeWidget(view)
            view.setParent(None)
            view.deleteLater()
        if runtime is not None:
            runtime.dispose()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()
        gc.collect()
        QCoreApplication.processEvents()

    # ---------------------------------------------------------------- cards
    def refresh_cards(self) -> None:
        ids = [s.id for s in self.store.sessions]
        if ids != self._card_order:
            while self.cards_layout.count():
                item = self.cards_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            self.cards.clear()
            for sid in ids:
                card = SessionCard(sid)
                card.activated.connect(self.activate_session)
                card.menu_requested.connect(self._show_session_menu)
                self.cards_layout.addWidget(card)
                self.cards[sid] = card
            self.cards_layout.addStretch(1)
            self._card_order = ids

        for session in self.store.sessions:
            card = self.cards.get(session.id)
            if card is None:
                continue
            card.bind(
                session,
                self.effective_state(session),
                self.settings.context_limit,
                session.id == self.current_sid,
            )

    @staticmethod
    def _restyle(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    # ------------------------------------------------------------ navigation
    def _nav(self, action: str) -> None:
        view = self.current_view()
        if view is None:
            return
        if action == "back":
            view.back()
        elif action == "forward":
            view.forward()
        elif action == "reload":
            view.reload()
        elif action == "home":
            view.setUrl(QUrl(self.settings.domain))

    def _navigate_from_bar(self) -> None:
        view = self.current_view()
        if view is None:
            return
        text = self.url_bar.text().strip()
        if not text:
            return
        if "://" not in text:
            text = "https://" + text
        url = QUrl(text)
        if not url.isValid() or not url.host():
            self.statusBar().showMessage("Некорректный адрес", 4000)
            return
        view.setUrl(url)
        view.setFocus()

    def _sync_nav_buttons(self) -> None:
        view = self.current_view()
        can_back = can_fwd = False
        if view is not None:
            try:
                can_back = view.history().canGoBack()
                can_fwd = view.history().canGoForward()
            except Exception:
                pass
        self.back_btn.setEnabled(bool(can_back))
        self.fwd_btn.setEnabled(bool(can_fwd))
        enabled = view is not None
        self.reload_btn.setEnabled(enabled)
        self.home_btn.setEnabled(enabled)
        self.transfer_btn.setEnabled(enabled)

    def _sync_url_bar(self) -> None:
        view = self.current_view()
        if view is None:
            return
        if not self.url_bar.hasFocus():
            url = view.url().toString()
            if url and url != "about:blank":
                self.url_bar.setText(url)

    def _on_url_changed(self, sid: str, url: QUrl) -> None:
        session = self.store.get(sid)
        if session is not None:
            text = url.toString()
            if text.startswith("http"):
                session.last_url = text
                self._schedule_save()
        if sid == self.current_sid:
            self._sync_url_bar()
            self._sync_nav_buttons()

    def _on_load_finished(self, sid: str, ok: bool) -> None:
        if sid == self.current_sid:
            self._sync_nav_buttons()
            self._sync_url_bar()
            QTimer.singleShot(1200, self._poll_current)

    def _on_fullscreen(self, request) -> None:
        try:
            request.accept()
        except Exception:
            pass

    def create_popup_page(self, profile):
        view = QWebEngineView()
        page = WebPage(profile, view, owner=self)
        view.setPage(page)
        view.setWindowTitle("BigSeek Desktop")
        view.resize(1000, 780)
        view.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        view.show()
        self._popups.append(view)

        def _drop(*_args) -> None:
            if view in self._popups:
                self._popups.remove(view)

        view.destroyed.connect(_drop)
        return page

    @property
    def allowed_host(self) -> str:
        return (QUrl(self.settings.domain).host() or "").lower()

    # ------------------------------------------------------------- monitoring
    def _poll_current(self) -> None:
        # Scheduled quota resets happen even when no page is loaded.
        if self._check_limit_resets():
            self.refresh_cards()
            self._sync_header()
            self._update_banner()
        # Poll every loaded profile: preloaded ("load all") sessions should
        # notice limits too, not only the visible one.
        for sid in list(self.views.keys()):
            self._poll_session(sid)

    def _poll_session(self, sid: str) -> None:
        view = self.views.get(sid)
        if view is None:
            return
        page = view.page()
        if page is None:
            return
        page.runJavaScript(
            "window.__dsmScan ? window.__dsmScan() : null",
            lambda result, s=sid: self._on_scan(s, result),
        )

    def _on_scan(self, sid: str, result) -> None:
        if not isinstance(result, dict):
            return
        session = self.store.get(sid)
        if session is None:
            return
        session.roll_day()

        api = int(result.get("sentApi") or 0)
        key = int(result.get("sentKey") or 0)
        count = max(api, key)
        prev = self._js_seen.get(sid, 0)
        if count > prev:
            session.add_usage(count - prev)
            self._schedule_save()
            if sid == self.current_sid:
                QTimer.singleShot(2500, lambda s=sid: self._poll_session(s))
        self._js_seen[sid] = count

        now = time.time()

        # Context size is the real limit of a chat: tokens grow with every
        # message, while a message counter says nothing about the 128K window.
        ctx_tokens = int(result.get("ctxTokens") or 0)
        ctx_chars = int(result.get("ctxChars") or 0)
        if ctx_tokens > 0 and (
            abs(ctx_tokens - session.context_tokens) > 40
            or now - session.context_at > 60
        ):
            session.measure_context(ctx_chars, ctx_tokens)
            self._schedule_save()

        last429 = float(result.get("last429At") or 0) / 1000.0
        phrase = str(result.get("phrase") or "").strip()
        phrase_at = float(result.get("phraseAt") or 0) / 1000.0
        error = str(result.get("lastError") or "")
        error_at = float(result.get("lastErrorAt") or 0) / 1000.0
        recent_429 = bool(last429) and now - last429 < 180

        # The site tells when the quota comes back ("сброс в 03:00",
        # "resets in 2 hours"). Remember it and clear the block automatically.
        reset_at = float(result.get("resetAt") or 0) / 1000.0
        reset_text = str(result.get("resetText") or "").strip()
        if reset_at and reset_at > now - 5 and reset_at < now + 8 * 86400:
            if not session.limit_reset_at or abs(reset_at - session.limit_reset_at) > 600:
                session.limit_reset_at = reset_at
                session.limit_reset_text = reset_text[:200]
                self._schedule_save()

        # Priority: an explicit "limit reached" notice beats a temporary 429.
        if self.settings.detect_limits and phrase and phrase_at > session.status_reset_at:
            if session.status != STATE_BLOCKED:
                self._set_status(sid, STATE_BLOCKED, f"«{phrase[:70]}»")
        elif recent_429:
            if session.status == STATE_OK:
                self._set_status(sid, STATE_LIMITED, "HTTP 429 — слишком много запросов")
        elif (
            self.settings.detect_limits
            and error
            and error_at > now - 120
            and ERROR_LIMIT_RE.search(error)
        ):
            if session.status == STATE_OK:
                self._set_status(sid, STATE_BLOCKED, "ответ сервера: лимит исчерпан")
        elif session.status == STATE_LIMITED and now - session.status_at > 600:
            self._set_status(sid, STATE_OK, "")

        if sid == self.current_sid:
            self.refresh_cards()
            self._sync_header()
            self._update_banner()

    def _sync_header(self) -> None:
        session = self.store.get(self.current_sid or "")
        if session is None:
            self.usage_chip.setText("— / —")
            self.usage_chip.setProperty("tone", "")
            self._restyle(self.usage_chip)
            return
        limit = self.settings.context_limit
        used = session.used_context_tokens
        if session.context_chars > 0:
            self.usage_chip.setText(
                f"{human_tokens(used)}/{human_tokens(limit)}"
            )
        else:
            self.usage_chip.setText(f"—/{human_tokens(limit)}")
        state = self.effective_state(session)
        tone = "danger" if state == STATE_BLOCKED else ("warn" if state in (STATE_WARN, STATE_LIMITED) else "")
        self.usage_chip.setProperty("tone", tone)
        measured = (
            f"Контекст: ~{used} из {limit} токенов "
            f"(после последнего сброса счётчика). "
            if session.context_chars > 0
            else "Контекст ещё не измерен. "
        )
        self.usage_chip.setToolTip(
            f"Сессия «{session.name}»: {STATE_TITLES.get(state, state)}. "
            + measured
            + f"Отправлено сегодня: {session.usage_count} сообщ."
        )
        self.usage_chip.setMinimumWidth(self.usage_chip.sizeHint().width() + 2)
        self._restyle(self.usage_chip)

    def _update_banner(self) -> None:
        session = self.store.get(self.current_sid or "")
        if session is None:
            self.banner.hide()
            return
        state = self.effective_state(session)
        key = (session.id, state)
        if state not in (STATE_WARN, STATE_LIMITED, STATE_BLOCKED) or key in self._banner_dismissed:
            self.banner.hide()
            return

        limit = self.settings.context_limit
        if state == STATE_BLOCKED:
            self.banner.setProperty("state", "danger")
            self.banner_title.setText("Сессия недоступна — лимит исчерпан")
            reason = f" Причина: {session.status_reason}." if session.status_reason else ""
            self.banner_text.setText(
                f"«{session.name}» больше не может отправлять сообщения.{reason} "
                "Сожми контекст и перенеси работу в другую сессию."
                + self._reset_hint(session)
            )
            self.banner_reset.setText("Сбросить статус")
            self.banner_reset.setToolTip("Сбросить состояние сессии")
            self.banner_reset.show()
        elif state == STATE_LIMITED:
            self.banner.setProperty("state", "warn")
            self.banner_title.setText("Временное ограничение запросов")
            self.banner_text.setText(
                f"«{session.name}»: сервер ответил 429 (слишком много запросов). "
                "Подожди пару минут или перенеси контекст в другую сессию."
                + self._reset_hint(session)
            )
            self.banner_reset.setText("Сбросить статус")
            self.banner_reset.setToolTip("Сбросить состояние сессии")
            self.banner_reset.show()
        else:
            self.banner.setProperty("state", "warn")
            self.banner_title.setText("Контекст подходит к концу")
            self.banner_text.setText(
                f"«{session.name}»: ~{human_tokens(session.used_context_tokens)} из "
                f"{human_tokens(limit)} токенов "
                f"({session.usage_count} сообщений сегодня). "
                "Самое время упаковать контекст, пока сессия ещё отвечает."
            )
            self.banner_reset.setText("Сбросить счётчик")
            self.banner_reset.setToolTip("Обнулить счётчик токенов этой сессии")
            self.banner_reset.show()

        self._restyle(self.banner)
        self.banner.show()

    def _dismiss_banner(self) -> None:
        session = self.store.get(self.current_sid or "")
        if session is not None:
            self._banner_dismissed.add((session.id, self.effective_state(session)))
        self.banner.hide()

    def _banner_copy_compact(self) -> None:
        sid = self.current_sid
        if not sid:
            return
        compact, _resume = self.prompts_for(sid)
        QGuiApplication.clipboard().setText(compact)
        self.statusBar().showMessage(
            "Промт сжатия скопирован — отправь его в текущей сессии", 6000
        )

    # --------------------------------------------------------------- dialogs
    def prompts_for(self, sid: str) -> tuple[str, str]:
        session = self.store.get(sid)
        if session is None:
            return "", ""
        date = datetime.now().strftime("%d.%m.%Y")
        compact = compaction_prompt(
            session.name,
            session.used_context_tokens or 0,
            self.settings.context_limit,
            date,
        )
        resume = resume_prompt(session.name, date)
        return compact, resume

    def available_targets(self, source_sid: str) -> list[tuple[str, str]]:
        rows: list[tuple[int, str, str]] = []
        for s in self.store.sessions:
            if s.id == source_sid:
                continue
            if self.effective_state(s) in (STATE_BLOCKED, STATE_EXHAUSTED):
                continue
            used = s.used_context_tokens or 0
            label = f"{s.name} — ≈{human_tokens(used)} токенов"
            rows.append((used, s.id, label))
        rows.sort(key=lambda r: r[0])
        return [(sid, label) for _used, sid, label in rows]

    def open_transfer_dialog(self, sid: str | None = None) -> None:
        sid = sid or self.current_sid
        if not sid or self.store.get(sid) is None:
            self.statusBar().showMessage("Сначала выбери сессию", 4000)
            return
        if self._transfer is not None:
            self.statusBar().showMessage("Перенос уже выполняется", 4000)
            return
        dialog = TransferDialog(self, sid, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.auto_mode:
            self.start_auto_transfer(sid, dialog.final_target_sid, dialog.mark_source.isChecked())

    # ----------------------------------------------------------- auto transfer
    def start_auto_transfer(
        self, source_sid: str, target_sid: str | None, mark_source: bool = True
    ) -> None:
        if self._transfer is not None:
            return
        source = self.store.get(source_sid)
        if source is None:
            return
        if target_sid is None:
            target_sid = self.create_session().id
        target = self.store.get(target_sid)
        if target is None:
            return
        if target_sid == source_sid:
            self.statusBar().showMessage("Нельзя перенести сессию в неё же", 4000)
            return

        compact, resume = self.prompts_for(source_sid)
        transfer = AutoTransfer(
            self, source_sid, target_sid, compact, resume, mark_source, self
        )
        transfer.progress.connect(self._transfer_on_progress)
        transfer.finished.connect(self._transfer_on_finished)

        self._transfer = transfer
        self.transfer_title.setText(f"Автоперенос: «{source.name}» → «{target.name}»")
        self.transfer_text.setText("Подготовка…")
        self.transfer_progress.show()
        self.transfer_cancel.setText("Отмена")
        self.transfer_cancel.setToolTip("Прервать автоперенос")
        self.transfer_panel.show()
        transfer.start()

    def _transfer_on_progress(self, text: str) -> None:
        self.transfer_text.setText(text)
        self.statusBar().showMessage(text, 5000)

    def _transfer_on_finished(self, ok: bool, message: str, payload: dict) -> None:
        transfer = self._transfer
        self._transfer = None
        if transfer is not None:
            transfer.deleteLater()

        source_sid = getattr(transfer, "source_sid", None)
        target_sid = payload.get("target_sid") or getattr(transfer, "target_sid", None)
        summary = str(payload.get("summary") or "")
        resume_text = str(payload.get("resume_text") or "")

        self.transfer_progress.hide()
        self.transfer_cancel.setText("Закрыть")
        self.transfer_cancel.setToolTip("Скрыть панель")

        if ok:
            self.transfer_title.setText("Автоперенос завершён")
            self.transfer_text.setText(message)
            if source_sid and getattr(transfer, "mark_source", False):
                self.mark_transferred(source_sid)
            if resume_text:
                QGuiApplication.clipboard().setText(resume_text)
            if target_sid:
                self.activate_session(target_sid)
            self.statusBar().showMessage(message, 8000)
            QTimer.singleShot(9000, self._auto_hide_transfer_panel)
            return

        self.transfer_title.setText("Автоперенос не завершён")
        hint = message
        if summary:
            fallback = resume_text or summary
            QGuiApplication.clipboard().setText(fallback)
            hint += "\nГотовый конспект скопирован в буфер обмена."
        elif getattr(transfer, "compact_text", None):
            QGuiApplication.clipboard().setText(transfer.compact_text)
            hint += "\nПромт сжатия скопирован в буфер обмена."
        self.transfer_text.setText(hint)
        self.statusBar().showMessage("Автоперенос не завершён", 8000)

    def _transfer_cancel_clicked(self) -> None:
        if self._transfer is not None:
            self._transfer.cancel()
            return
        self.transfer_panel.hide()

    def _auto_hide_transfer_panel(self) -> None:
        if self._transfer is None and self.transfer_panel.isVisible():
            self.transfer_panel.hide()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self.root, self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self.apply_settings(dialog.result_settings())

    def apply_settings(self, new_settings: Settings) -> None:
        old_domain = self.settings.domain
        self.settings = new_settings
        self.settings.save(self.root / "settings.json")
        self.poll_timer.setInterval(self.settings.poll_seconds * 1000)

        if normalize_domain(old_domain) != self.settings.domain:
            for sid, view in self.views.items():
                view.setUrl(QUrl(self.settings.domain))
                session = self.store.get(sid)
                if session is not None:
                    session.last_url = self.settings.domain
            self.store.save()
            self.statusBar().showMessage("Домен изменён, сессии перезагружены", 5000)

        if self.settings.load_all_sessions:
            for session in self.store.sessions:
                if session.id not in self.views:
                    QTimer.singleShot(0, lambda s=session.id: self._ensure_runtime(s))

        self.refresh_cards()
        self._sync_header()
        self._update_banner()

    def open_manager(self) -> None:
        dialog = SessionManagerDialog(self, self)
        dialog.exec()
        self.refresh_cards()
        self._sync_header()
        self._update_banner()

    def _show_session_menu(self, sid: str, pos: QPoint) -> None:
        session = self.store.get(sid)
        if session is None:
            return
        menu = QMenu(self)
        open_act = menu.addAction("Открыть")
        open_act.triggered.connect(lambda: self.activate_session(sid))
        rename_act = menu.addAction("Переименовать…")
        rename_act.triggered.connect(lambda: self.rename_session(sid))
        menu.addSeparator()
        transfer_act = menu.addAction("Перенести контекст…")
        transfer_act.triggered.connect(lambda: self.open_transfer_dialog(sid))
        if session.status == STATE_BLOCKED:
            reset_act = menu.addAction("Сбросить статус «недоступна»")
            reset_act.triggered.connect(lambda: self.reset_status(sid))
        else:
            block_act = menu.addAction("Отметить как недоступную")
            block_act.triggered.connect(lambda: self._set_status(sid, STATE_BLOCKED, "отмечено вручную"))
        exhausted_act = menu.addAction("Отметить как перенесённую")
        exhausted_act.triggered.connect(lambda: self.mark_transferred(sid))
        menu.addSeparator()
        tokens_act = menu.addAction("Сбросить счётчик токенов")
        tokens_act.triggered.connect(lambda: self.reset_context(sid))
        usage_act = menu.addAction("Сбросить счётчик сообщений")
        usage_act.triggered.connect(lambda: self.reset_usage(sid))
        clear_act = menu.addAction("Очистить данные сайта…")
        clear_act.triggered.connect(lambda: self.clear_session_data(sid))
        folder_act = menu.addAction("Открыть папку профиля")
        folder_act.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.root / "profiles" / sid)))
        )
        menu.addSeparator()
        delete_act = menu.addAction("Удалить сессию…")
        delete_act.triggered.connect(lambda: self.delete_session(sid))
        menu.exec(pos)

    def _show_toolbar_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction("Новая сессия").triggered.connect(lambda: self.create_session())
        menu.addAction("Менеджер сессий…").triggered.connect(self.open_manager)
        menu.addAction("Настройки…").triggered.connect(self.open_settings)
        menu.addSeparator()
        menu.addAction("Обновить страницу").triggered.connect(lambda: self._nav("reload"))
        menu.addAction("На главную").triggered.connect(lambda: self._nav("home"))
        menu.addSeparator()
        menu.addAction("Открыть папку данных").triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.root)))
        )
        menu.exec(self.menu_btn.mapToGlobal(QPoint(0, self.menu_btn.height() + 4)))

    # ---------------------------------------------------------------- saving
    def _schedule_save(self) -> None:
        self.save_timer.start()

    def _flush(self) -> None:
        try:
            self.store.save()
            self.settings.save(self.root / "settings.json")
        except OSError:
            pass

    def closeEvent(self, event) -> None:
        if self._transfer is not None:
            try:
                self._transfer.cancel()
            except Exception:
                pass
            self._transfer = None
        self.settings.window_geometry = bytes(self.saveGeometry().toBase64()).decode()
        self.poll_timer.stop()
        self._flush()
        for view in list(self._popups):
            try:
                view.close()
            except Exception:
                pass
        super().closeEvent(event)

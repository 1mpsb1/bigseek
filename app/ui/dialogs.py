from __future__ import annotations

from dataclasses import replace

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import APP_AUTHOR, Settings, app_version, normalize_domain
from ..sessions import STATE_BLOCKED, STATE_EXHAUSTED, STATE_TITLES, Session, human_age, human_tokens
from ..web import human_size


def _copy(text: str, button: QPushButton, hint: QLabel) -> None:
    QGuiApplication.clipboard().setText(text)
    hint.setText("Скопировано в буфер обмена")
    button.setText("Скопировано ✓")


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, data_dir, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._data_dir = data_dir
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        site = QGroupBox("Сайт")
        site_form = QFormLayout(site)
        self.domain = QLineEdit(settings.domain)
        self.domain.setPlaceholderText("chat.deepseek.com")
        site_form.addRow("Домен", self.domain)
        site_hint = QLabel(
            "Можно указать без https:// — адрес нормализуется автоматически. "
            "При смене домена уже загруженные сессии будут перезагружены."
        )
        site_hint.setObjectName("sectionHint")
        site_hint.setWordWrap(True)
        site_form.addRow(site_hint)
        root.addWidget(site)

        startup = QGroupBox("Запуск")
        startup_box = QVBoxLayout(startup)
        self.load_last = QCheckBox("Открывать последнюю сессию при запуске")
        self.load_last.setChecked(settings.load_last_session)
        self.load_all = QCheckBox("Загружать все сессии при запуске (больше ОЗУ)")
        self.load_all.setChecked(settings.load_all_sessions)
        self.load_all.toggled.connect(self._sync_startup_checks)
        startup_box.addWidget(self.load_last)
        startup_box.addWidget(self.load_all)
        root.addWidget(startup)

        limits = QGroupBox("Лимиты и предупреждения")
        lim_form = QFormLayout(limits)
        self.context_limit = QSpinBox()
        self.context_limit.setRange(8, 1000)
        self.context_limit.setValue(max(8, int(round(settings.context_limit / 1000))))
        self.context_limit.setSuffix(" тыс. токенов")
        lim_form.addRow("Контекстное окно", self.context_limit)

        self.threshold = QSpinBox()
        self.threshold.setRange(30, 99)
        self.threshold.setValue(int(round(settings.context_warn * 100)))
        self.threshold.setSuffix(" %")
        lim_form.addRow("Порог предупреждения", self.threshold)

        self.poll = QSpinBox()
        self.poll.setRange(3, 120)
        self.poll.setValue(settings.poll_seconds)
        self.poll.setSuffix(" с")
        lim_form.addRow("Проверять страницу каждые", self.poll)

        self.detect = QCheckBox("Распознавать сообщения сайта о лимите и ошибки 429")
        self.detect.setChecked(settings.detect_limits)
        lim_form.addRow(self.detect)

        lim_hint = QLabel(
            "Объём контекста оценивается по тексту переписки (≈2,5 символа на токен) "
            "и сравнивается с контекстным окном модели. Когда порог достигнут, "
            "сессия помечается ⚠ и предлагается перенос. "
            "Настоящие лимиты сайта (сообщение о квоте, сброс, HTTP 429) "
            "приложение читает со страницы само."
        )
        lim_hint.setObjectName("sectionHint")
        lim_hint.setWordWrap(True)
        lim_form.addRow(lim_hint)
        root.addWidget(limits)

        data_row = QHBoxLayout()
        path_label = QLabel(str(data_dir))
        path_label.setObjectName("sectionHint")
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        open_btn = QPushButton("Открыть папку данных")
        open_btn.setObjectName("ghost")
        open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir)))
        )
        data_row.addWidget(path_label, 1)
        data_row.addWidget(open_btn)
        root.addLayout(data_row)

        about = QGroupBox("О программе")
        about_box = QVBoxLayout(about)
        about_text = QLabel(
            f"BigSeek Desktop {app_version()} — обёртка браузера для chat.deepseek.com "
            f"с изолированными профилями, переносом контекста и счётчиком токенов.\n"
            f"Разработчик: {APP_AUTHOR}"
        )
        about_text.setObjectName("sectionHint")
        about_text.setWordWrap(True)
        about_box.addWidget(about_text)
        root.addWidget(about)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._sync_startup_checks(self.load_all.isChecked())

    def _sync_startup_checks(self, all_checked: bool) -> None:
        self.load_last.setEnabled(not all_checked)

    def result_settings(self) -> Settings:
        return replace(
            self._settings,
            domain=normalize_domain(self.domain.text()),
            load_last_session=self.load_last.isChecked(),
            load_all_sessions=self.load_all.isChecked(),
            context_limit=self.context_limit.value() * 1000,
            context_warn=self.threshold.value() / 100.0,
            detect_limits=self.detect.isChecked(),
            poll_seconds=self.poll.value(),
        )


class SessionManagerDialog(QDialog):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.setWindowTitle("Менеджер сессий")
        self.resize(880, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        intro = QLabel(
            "Каждая сессия — полностью изолированный профиль браузера: свои cookies, "
            "localStorage и кэш. Поэтому в разных сессиях можно держать разные аккаунты."
        )
        intro.setObjectName("sectionHint")
        intro.setWordWrap(True)
        root.addWidget(intro)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Сессия", "Статус", "Контекст", "Сегодня", "Данные", "Активность"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 6):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.doubleClicked.connect(lambda _idx: self._open_selected())
        root.addWidget(self.table, 1)

        grid = QHBoxLayout()
        grid.setSpacing(8)
        for text, handler in (
            ("Перейти", self._open_selected),
            ("Переименовать", self._rename_selected),
            ("Очистить данные сайта", self._clear_selected),
            ("Сбросить счётчик токенов", self._reset_tokens_selected),
            ("Сбросить статус", self._reset_status_selected),
        ):
            btn = QPushButton(text)
            btn.clicked.connect(handler)
            grid.addWidget(btn)
        grid.addStretch(1)
        delete_btn = QPushButton("Удалить сессию")
        delete_btn.setObjectName("danger")
        delete_btn.clicked.connect(self._delete_selected)
        grid.addWidget(delete_btn)
        root.addLayout(grid)

        bottom = QHBoxLayout()
        new_btn = QPushButton("＋ Новая сессия")
        new_btn.setObjectName("primary")
        new_btn.clicked.connect(self._create_session)
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(new_btn)
        bottom.addStretch(1)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

        self.refresh()

    def _selected_session(self) -> Session | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        return self.window.store.get(item.data(Qt.ItemDataRole.UserRole))

    def refresh(self) -> None:
        current = self._selected_session()
        keep_id = current.id if current else None
        sessions = self.window.store.sessions
        self.table.setRowCount(len(sessions))
        for row, s in enumerate(sessions):
            state = self.window.effective_state(s)
            name_item = QTableWidgetItem(s.name)
            name_item.setData(Qt.ItemDataRole.UserRole, s.id)
            self.table.setItem(row, 0, name_item)
            status_text = STATE_TITLES.get(state, state)
            if state == STATE_BLOCKED and s.status_reason:
                status_text += f" — {s.status_reason}"
            self.table.setItem(row, 1, QTableWidgetItem(status_text))
            context_limit = self.window.settings.context_limit
            context_text = (
                f"≈{human_tokens(s.used_context_tokens)} / {human_tokens(context_limit)}"
                if s.context_chars > 0
                else "—"
            )
            self.table.setItem(row, 2, QTableWidgetItem(context_text))
            self.table.setItem(row, 3, QTableWidgetItem(f"{s.usage_count} сообщ."))
            size = human_size(self.window.profile_size_bytes(s.id))
            self.table.setItem(row, 4, QTableWidgetItem(size))
            self.table.setItem(row, 5, QTableWidgetItem(human_age(s.last_used)))
            if s.id == keep_id:
                self.table.selectRow(row)
        if self.table.currentRow() < 0 and self.table.rowCount() > 0:
            self.table.selectRow(0)

    def _create_session(self) -> None:
        self.window.create_session()
        self.refresh()

    def _open_selected(self) -> None:
        s = self._selected_session()
        if s:
            self.window.activate_session(s.id)
            self.accept()

    def _rename_selected(self) -> None:
        s = self._selected_session()
        if not s:
            return
        self.window.rename_session(s.id)
        self.refresh()

    def _clear_selected(self) -> None:
        s = self._selected_session()
        if s:
            self.window.clear_session_data(s.id)
            self.refresh()

    def _reset_tokens_selected(self) -> None:
        s = self._selected_session()
        if s:
            self.window.reset_context(s.id)
            self.refresh()

    def _reset_status_selected(self) -> None:
        s = self._selected_session()
        if s:
            self.window.reset_status(s.id)
            self.refresh()

    def _delete_selected(self) -> None:
        s = self._selected_session()
        if s:
            self.window.delete_session(s.id)
            self.refresh()
            if self.table.rowCount() == 0:
                self.accept()


class TransferDialog(QDialog):
    """Chooses where to move the context. The actual move is automatic."""

    def __init__(self, window, source_sid: str, parent=None):
        super().__init__(parent)
        self.window = window
        self.source_sid = source_sid
        self.auto_mode = False
        self.final_target_sid: str | None = None
        session = window.store.get(source_sid)
        if session is None:
            session = Session(id=source_sid, name=source_sid)
        self.source = session
        self.setWindowTitle("Автоперенос контекста")
        self.resize(780, 480)

        compact, resume = window.prompts_for(source_sid)
        self._compact_text = compact
        self._resume_text = resume

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel(f"Перенос из сессии «{session.name}»")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        root.addWidget(title)
        status = QLabel(
            f"Статус: {STATE_TITLES.get(window.effective_state(session), '')} · "
            f"≈{human_tokens(session.used_context_tokens)} из "
            f"{human_tokens(window.settings.context_limit)} токенов · "
            f"{session.usage_count} сообщений сегодня"
        )
        status.setObjectName("sectionHint")
        status.setWordWrap(True)
        root.addWidget(status)

        info = QLabel(
            "Приложение само отправит промт сжатия в эту сессию, дождётся ответа ассистента, "
            "вырежет блок между строками ===КОНСПЕКТ=== и ===КОНЕЦ=== и отправит его первым "
            "сообщением в новый чат выбранной сессии. Руками ничего копировать не нужно."
        )
        info.setObjectName("bannerText")
        info.setWordWrap(True)
        root.addWidget(info)

        warn = QLabel(
            "В целевой сессии всегда открывается новый чат, поэтому конспект не попадёт "
            "в старую переписку. Будет отправлено по одному сообщению в каждой сессии — "
            "это расходует лимит. Обе сессии должны быть открыты и с выполненным входом; "
            "если сайт попросит капчу, решите её в открывшемся окне."
        )
        warn.setObjectName("sectionHint")
        warn.setWordWrap(True)
        root.addWidget(warn)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Куда переносим:"))
        self.target = QComboBox()
        for sid, label in window.available_targets(source_sid):
            self.target.addItem(label, sid)
        self.target.addItem("＋ Создать новую сессию", None)
        target_row.addWidget(self.target, 1)
        self.mark_source = QCheckBox("Пометить старую как «перенесена»")
        self.mark_source.setChecked(True)
        target_row.addWidget(self.mark_source)
        root.addLayout(target_row)

        self.show_prompts = QCheckBox("Показать промты для ручного переноса")
        self.show_prompts.toggled.connect(self._toggle_prompts)
        root.addWidget(self.show_prompts)

        self.manual_box = self._build_manual_box()
        self.manual_box.hide()
        root.addWidget(self.manual_box, 1)

        self.hint = QLabel("")
        self.hint.setObjectName("sectionHint")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        buttons = QHBoxLayout()
        close = QPushButton("Закрыть")
        close.clicked.connect(self.reject)
        go = QPushButton("Перенести автоматически")
        go.setObjectName("primary")
        go.clicked.connect(self._go)
        buttons.addStretch(1)
        buttons.addWidget(close)
        buttons.addWidget(go)
        root.addLayout(buttons)

    def _build_manual_box(self) -> QWidget:
        box = QGroupBox("Ручной перенос")
        lay = QVBoxLayout(box)

        actions = QHBoxLayout()
        copy_compact = QPushButton("Копировать промт сжатия")
        copy_compact.clicked.connect(self._copy_compact)
        copy_resume = QPushButton("Копировать промт продолжения")
        copy_resume.clicked.connect(self._copy_resume)
        open_target = QPushButton("Открыть целевую сессию")
        open_target.clicked.connect(self._manual_go)
        actions.addWidget(copy_compact)
        actions.addWidget(copy_resume)
        actions.addStretch(1)
        actions.addWidget(open_target)
        lay.addLayout(actions)

        for title, text in (
            ("Промт сжатия — отправить в старой сессии", self._compact_text),
            ("Промт продолжения — отправить в новой сессии", self._resume_text),
        ):
            label = QLabel(title)
            label.setObjectName("sectionHint")
            lay.addWidget(label)
            edit = QPlainTextEdit()
            edit.setPlainText(text)
            edit.setReadOnly(True)
            edit.setMinimumHeight(90)
            lay.addWidget(edit)
        return box

    def _toggle_prompts(self, visible: bool) -> None:
        self.manual_box.setVisible(visible)
        if visible:
            self.resize(self.width(), 760)
        else:
            self.resize(self.width(), 480)

    def _copy_compact(self) -> None:
        QGuiApplication.clipboard().setText(self._compact_text)
        self.hint.setText("Промт сжатия скопирован. Отправьте его в старой сессии.")

    def _copy_resume(self) -> None:
        QGuiApplication.clipboard().setText(self._resume_text)
        self.hint.setText("Промт продолжения скопирован. Вставьте его в новой сессии.")

    def _go(self) -> None:
        self.final_target_sid = self.target.currentData()
        self.auto_mode = True
        self.accept()

    def _manual_go(self) -> None:
        target_sid = self.target.currentData()
        QGuiApplication.clipboard().setText(self._resume_text)
        if self.mark_source.isChecked():
            self.window.mark_transferred(self.source_sid)
        if target_sid is None:
            target_sid = self.window.create_session().id
        self.window.activate_session(target_sid)
        self.accept()

from __future__ import annotations

import zlib
from datetime import datetime

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QStyleOption,
    QVBoxLayout,
    QWidget,
)

from ..sessions import Session, human_tokens
from ..theme import STATE_COLORS

AVATAR_COLORS = [
    "#ffffff",
    "#dcdcdc",
    "#c2c2c2",
    "#a8a8a8",
    "#efefef",
    "#cfcfcf",
    "#b5b5b5",
    "#e6e6e6",
]

BADGES = {
    "blocked": ("НЕДОСТУПНА", "danger"),
    "limited": ("ОГРАНИЧЕНИЕ", "warn"),
    "warn": ("⚠", "triangle"),
    "exhausted": ("ПЕРЕНЕСЕНА", "muted"),
    "ok": ("", "muted"),
}

# Long badges steal the whole name row when the sidebar is narrow, so short
# variants are used there. The full text stays in the tooltip.
COMPACT_BADGES = {
    "blocked": ("ЛИМИТ", "danger"),
    "limited": ("429", "warn"),
    "exhausted": ("АРХИВ", "muted"),
}

BADGE_COMPACT_WIDTH = 220

BLOCKED_OPACITY = 0.55


class ElidedLabel(QLabel):
    """A label that shortens its text when painted instead of in resizeEvent.

    Eliding at paint time keeps the widget's size hint constant, so a card
    never triggers a layout round-trip (text -> size hint -> resize -> new
    text) when the sidebar is narrowed or a badge appears.
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        option = QStyleOption()
        option.initFrom(self)
        text = self.fontMetrics().elidedText(
            self.text(), Qt.TextElideMode.ElideRight, self.contentsRect().width()
        )
        self.style().drawItemText(
            painter,
            self.contentsRect(),
            int(self.alignment()) | int(Qt.TextFlag.TextSingleLine),
            option.palette,
            self.isEnabled(),
            text,
            self.foregroundRole(),
        )


class SessionCard(QFrame):
    activated = pyqtSignal(str)
    menu_requested = pyqtSignal(str, QPoint)

    def __init__(self, session_id: str, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self._bar_color = ""
        self._glow_key: tuple | None = None
        self.setObjectName("sessionCard")
        self.setProperty("active", "false")
        self.setProperty("state", "ok")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(74)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.inner = QWidget(self)
        outer.addWidget(self.inner)

        root = QHBoxLayout(self.inner)
        root.setContentsMargins(10, 9, 10, 9)
        root.setSpacing(10)

        color = AVATAR_COLORS[zlib.crc32(session_id.encode("utf-8")) % len(AVATAR_COLORS)]
        self.avatar = QLabel("?")
        self.avatar.setFixedSize(30, 30)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar.setStyleSheet(
            f"background: {color}; color: #000000; border-radius: 15px; "
            "font-weight: 800; font-size: 13px;"
        )
        root.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        self.name_label = ElidedLabel("Сессия")
        self.name_label.setObjectName("cardName")
        self.name_label.setMinimumWidth(48)
        self.badge = QLabel("")
        self.badge.setObjectName("badge")
        self.badge.hide()
        top.addWidget(self.name_label, 1)
        top.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignRight)

        self.sub_label = ElidedLabel("")
        self.sub_label.setObjectName("cardSub")
        self.sub_label.setMinimumWidth(0)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        self.bar.setMaximumWidth(400)

        col.addLayout(top)
        col.addWidget(self.sub_label)
        col.addWidget(self.bar)
        root.addLayout(col, 1)

        # Graphics effects are created once and only toggled afterwards:
        # reinstalling them on every refresh (the poll runs every few seconds)
        # eventually corrupts the card painting in Qt.
        self._glow = QGraphicsDropShadowEffect(self)
        self._glow.setOffset(0, 0)
        self._glow.setEnabled(False)
        self.setGraphicsEffect(self._glow)

        self._opacity = QGraphicsOpacityEffect(self.inner)
        self._opacity.setOpacity(BLOCKED_OPACITY)
        self._opacity.setEnabled(False)
        self.inner.setGraphicsEffect(self._opacity)

    def bind(self, session: Session, state: str, limit: int, active: bool) -> None:
        self.avatar.setText((session.name.strip()[:1] or "?").upper())
        self.name_label.setText(session.name)
        self.name_label.setToolTip(session.name)

        limit = max(0, int(limit))
        used = session.used_context_tokens or 0
        measured = session.context_chars > 0
        if limit > 0 and measured:
            text = f"{human_tokens(used)}/{human_tokens(limit)} · {session.usage_count} сообщ."
        elif limit > 0:
            text = f"—/{human_tokens(limit)} · {session.usage_count} сообщ."
        else:
            text = f"{session.usage_count} сообщ. сегодня"
        reset_txt = ""
        if state in ("blocked", "limited") and session.limit_reset_at > 0:
            reset_dt = datetime.fromtimestamp(session.limit_reset_at)
            if reset_dt > datetime.now():
                reset_txt = (
                    f"сброс {reset_dt:%H:%M}"
                    if reset_dt.date() == datetime.now().date()
                    else f"сброс {reset_dt:%d.%m %H:%M}"
                )
                text = f"{text} · {reset_txt}"
        self.sub_label.setText(text)
        self.sub_label.setToolTip(text)

        pct = 0 if limit <= 0 else int(round(min(1.0, (used or 0) / limit) * 100))
        if self.bar.value() != pct:
            self.bar.setValue(pct)
        color = STATE_COLORS.get(state, "#4d6bfe")
        if color != self._bar_color:
            self._bar_color = color
            self.bar.setStyleSheet(
                f"QProgressBar::chunk {{ background: {color}; border-radius: 2px; }}"
            )

        tone = BADGES.get(state, ("", "muted"))[1]
        if self.badge.property("tone") != tone:
            self.badge.setProperty("tone", tone)
            self.badge.style().unpolish(self.badge)
            self.badge.style().polish(self.badge)

        active_value = "true" if active else "false"
        changed = self.property("state") != state or self.property("active") != active_value
        if changed:
            self.setProperty("state", state)
            self.setProperty("active", active_value)
            self.style().unpolish(self)
            self.style().polish(self)
        self._fit_badge()
        self.badge.setToolTip(
            "Контекст почти заполнен" if state == "warn"
            else "Временное ограничение запросов" if state == "limited"
            else "Лимит исчерпан" if state == "blocked"
            else ""
        )

        if state == "blocked":
            tip = "Лимит исчерпан, но открыть сессию можно — нажмите на карточку."
            if reset_txt:
                tip += f" Ожидаемый сброс: {reset_txt.replace('сброс ', '')}."
            self.setToolTip(tip)
        elif limit > 0 and measured:
            self.setToolTip(
                f"Контекст: ~{used} из {limit} токенов "
                "(после последнего сброса счётчика)."
                + (" Пора перенести работу." if state == "warn" else "")
            )
        else:
            self.setToolTip("")
        self._apply_glow(state, active_value == "true")
        self._apply_opacity(state)

    def _fit_badge(self) -> None:
        """Use a short badge when the card is too narrow for the full one."""
        state = str(self.property("state") or "ok")
        full = BADGES.get(state, ("", "muted"))[0]
        compact = COMPACT_BADGES.get(state, (full, ""))[0]
        # Before the first layout pass the width is 0: pick the short badge so
        # the card's minimum width does not grow and the sidebar can still be
        # dragged down to 200 px.
        use_compact = self.width() <= 0 or self.width() < BADGE_COMPACT_WIDTH
        text = compact if (full and use_compact) else full
        if self.badge.text() != text:
            self.badge.setText(text)
        self.badge.setVisible(bool(text))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_badge()

    def _apply_glow(self, state: str, active: bool) -> None:
        color = None
        blur = 0
        if state == "blocked":
            # Unavailable session: red glow, but it stays clickable.
            color, blur = QColor(255, 74, 74, 205), 34
        elif state in ("warn", "limited"):
            color, blur = QColor(255, 255, 255, 80), 16
        if color is None:
            if self._glow.isEnabled():
                self._glow.setEnabled(False)
            self._glow_key = None
            return
        key = (state, active, color.rgba(), blur)
        if key == self._glow_key and self._glow.isEnabled():
            return
        self._glow.setBlurRadius(blur)
        self._glow.setColor(color)
        self._glow.setEnabled(True)
        self._glow_key = key

    def _apply_opacity(self, state: str) -> None:
        blocked = state == "blocked"
        if self._opacity.isEnabled() != blocked:
            self._opacity.setEnabled(blocked)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.session_id)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        self.menu_requested.emit(self.session_id, event.globalPos())

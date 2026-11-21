from __future__ import annotations

import zlib
from datetime import datetime

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
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


class SessionCard(QFrame):
    activated = pyqtSignal(str)
    menu_requested = pyqtSignal(str, QPoint)

    def __init__(self, session_id: str, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self._full_name = "Сессия"
        self._sub_text = ""
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
        self.name_label = QLabel("Сессия")
        self.name_label.setObjectName("cardName")
        self.badge = QLabel("")
        self.badge.setObjectName("badge")
        self.badge.hide()
        top.addWidget(self.name_label, 1)
        top.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignRight)

        self.sub_label = QLabel("")
        self.sub_label.setObjectName("cardSub")
        self.sub_label.setMinimumWidth(0)
        self.sub_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        self.bar.setMaximumWidth(400)

        col.addLayout(top)
        col.addWidget(self.sub_label)
        col.addWidget(self.bar)
        root.addLayout(col, 1)

    def bind(self, session: Session, state: str, limit: int, active: bool) -> None:
        self.avatar.setText((session.name.strip()[:1] or "?").upper())
        self._full_name = session.name
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
        self._sub_text = text
        pct = 0 if limit <= 0 else int(round(min(1.0, (used or 0) / limit) * 100))
        self.bar.setValue(pct)
        color = STATE_COLORS.get(state, "#4d6bfe")
        self.bar.setStyleSheet(f"QProgressBar::chunk {{ background: {color}; border-radius: 2px; }}")

        text, tone = BADGES.get(state, ("", "muted"))
        self.badge.setText(text)
        self.badge.setProperty("tone", tone)
        self.badge.setToolTip(
            "Контекст почти заполнен" if state == "warn"
            else "Временное ограничение запросов" if state == "limited"
            else "Лимит исчерпан" if state == "blocked"
            else ""
        )
        self.badge.setVisible(bool(text))
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        self._relayout_text()

        self.setProperty("state", state)
        self.setProperty("active", "true" if active else "false")
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
        self.style().unpolish(self)
        self.style().polish(self)
        self._apply_glow(state, active)
        self._apply_opacity(state)

    def _relayout_text(self) -> None:
        """Keep the name and the metrics line inside the draggable sidebar."""
        name_metrics = QFontMetrics(self.name_label.font())
        reserved = 30 + 10 + 20 + 12  # avatar, spacing, margins, breathing room
        if self.badge.isVisible() and self.badge.text():
            reserved += self.badge.sizeHint().width() + 6
        name_width = max(70, self.width() - reserved)
        self.name_label.setText(
            name_metrics.elidedText(
                self._full_name, Qt.TextElideMode.ElideRight, name_width
            )
        )
        sub_metrics = QFontMetrics(self.sub_label.font())
        sub_width = max(40, self.width() - 60)
        self.sub_label.setText(
            sub_metrics.elidedText(
                self._sub_text, Qt.TextElideMode.ElideRight, sub_width
            )
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout_text()

    def _apply_glow(self, state: str, active: bool) -> None:
        color = None
        blur = 0
        if state == "blocked":
            # Unavailable session: red glow, but it stays clickable.
            color, blur = QColor(255, 74, 74, 205), 34
        elif state in ("warn", "limited"):
            color, blur = QColor(255, 255, 255, 80), 16
        if color is None:
            self.setGraphicsEffect(None)
            return
        effect = QGraphicsDropShadowEffect(self)
        effect.setBlurRadius(blur)
        effect.setOffset(0, 0)
        effect.setColor(color)
        self.setGraphicsEffect(effect)

    def _apply_opacity(self, state: str) -> None:
        if state == "blocked":
            effect = self.inner.graphicsEffect()
            if not isinstance(effect, QGraphicsOpacityEffect):
                effect = QGraphicsOpacityEffect(self.inner)
                self.inner.setGraphicsEffect(effect)
            effect.setOpacity(0.55)
        elif self.inner.graphicsEffect() is not None:
            self.inner.setGraphicsEffect(None)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.session_id)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        self.menu_requested.emit(self.session_id, event.globalPos())

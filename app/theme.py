from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPalette, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import QApplication

from .config import data_root

# AMOLED-friendly monochrome palette: pure black, white text, gray shades.
BG = "#000000"
PANEL = "#070707"
PANEL_2 = "#0b0b0b"
BORDER = "#1d1d1d"
TEXT = "#ffffff"
MUTED = "#8a8a8a"
DIM = "#565656"
ACCENT = "#ffffff"

STATE_COLORS = {
    "ok": "#d9d9d9",
    "warn": "#9a9a9a",
    "limited": "#9a9a9a",
    "blocked": "#ff4d4d",
    "exhausted": "#4d4d4d",
}

QSS = """
* { font-family: "Segoe UI", "Inter", "Noto Sans", sans-serif; }
QMainWindow, QWidget#root { background: #000000; }
QWidget { color: #ffffff; font-size: 13px; }

QFrame#sidebar { background: #070707; border-right: 1px solid #1d1d1d; }
QSplitter#mainSplit::handle { background: #141414; }
QSplitter#mainSplit::handle:hover { background: #4a4a4a; }
QFrame#toolbar { background: #070707; border-bottom: 1px solid #1d1d1d; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }

QScrollBar:vertical { background: transparent; width: 9px; margin: 2px; }
QScrollBar::handle:vertical { background: #2b2b2b; border-radius: 4px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: #3d3d3d; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 9px; }
QScrollBar::handle:horizontal { background: #2b2b2b; border-radius: 4px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QLabel#brand { font-size: 17px; font-weight: 800; color: #ffffff; letter-spacing: 0.6px; }
QLabel#brandSub { color: #6f6f6f; font-size: 11px; letter-spacing: 0.4px; }
QLabel#sectionHint { color: #6f6f6f; font-size: 11px; }
QLabel#placeholder { color: #6f6f6f; font-size: 15px; }
QLabel#bannerText { color: #d6d6d6; }
QLabel#bannerTitle { color: #ffffff; font-weight: 700; }
QLabel#cardName { font-weight: 600; color: #f5f5f5; }
QLabel#cardSub { color: #7a7a7a; font-size: 11px; }
QLabel#badge { font-size: 9px; font-weight: 800; letter-spacing: 0.6px; padding: 1px 5px; border-radius: 4px; }
QLabel#badge[tone="danger"] { color: #000000; background: #ff5a5a; }
QLabel#badge[tone="warn"] { color: #e6e6e6; background: #262626; }
QLabel#badge[tone="triangle"] { color: #ffffff; background: #262626; font-size: 13px; padding: 0 5px; }
QLabel#badge[tone="muted"] { color: #9a9a9a; background: #1a1a1a; }

QLabel#chip {
    background: #0d0d0d; border: 1px solid #262626; border-radius: 11px;
    padding: 3px 10px; color: #d0d0d0; font-weight: 600; font-size: 11px;
}
QLabel#chip[tone="warn"] { background: #141414; border-color: #4a4a4a; color: #ffffff; }
QLabel#chip[tone="danger"] { background: #ffffff; border-color: #ffffff; color: #000000; }

QPushButton {
    background: #0d0d0d; border: 1px solid #262626; border-radius: 8px;
    padding: 7px 12px; color: #f0f0f0;
}
QPushButton:hover { background: #161616; border-color: #3a3a3a; }
QPushButton:pressed { background: #0a0a0a; }
QPushButton:disabled { color: #4d4d4d; background: #080808; border-color: #161616; }
QPushButton#primary { background: #ffffff; border: 1px solid #ffffff; color: #000000; font-weight: 700; }
QPushButton#primary:hover { background: #e4e4e4; border-color: #e4e4e4; }
QPushButton#primary:disabled { background: #2a2a2a; border-color: #2a2a2a; color: #7a7a7a; }
QPushButton#ghost { background: transparent; border: none; color: #9a9a9a; padding: 5px 8px; }
QPushButton#ghost:hover { background: #161616; color: #ffffff; }
QPushButton#nav { background: transparent; border: none; color: #c4c4c4; font-size: 16px; padding: 2px 6px; border-radius: 7px; }
QPushButton#nav:hover { background: #171717; color: #ffffff; }
QPushButton#nav:disabled { color: #3f3f3f; }
QPushButton#danger { background: #0d0d0d; border: 1px solid #4a4a4a; color: #ffffff; font-weight: 600; }
QPushButton#danger:hover { background: #1a1a1a; border-color: #ffffff; }

QFrame#sessionCard { background: #0b0b0b; border: 1px solid #1c1c1c; border-radius: 10px; }
QFrame#sessionCard:hover { background: #101010; border-color: #2a2a2a; }
QFrame#sessionCard[active="true"] { border: 1px solid #4d4d4d; border-left: 4px solid #ffffff; background: #141414; }
QFrame#sessionCard[state="blocked"] { border: 2px solid #ff4d4d; background: #1a0b0b; }
QFrame#sessionCard[state="blocked"]:hover { background: #241010; border-color: #ff6b6b; }
QFrame#sessionCard[state="limited"], QFrame#sessionCard[state="warn"] { border-color: #6e6e6e; background: #0d0d0d; }
QFrame#sessionCard[state="exhausted"] { background: #050505; border-color: #141414; }

QProgressBar { background: #1a1a1a; border: none; border-radius: 2px; }
QProgressBar::chunk { background: #ffffff; border-radius: 2px; }

QFrame#banner { background: #0d0d0d; border: 1px solid #4a4a4a; border-radius: 10px; }
QFrame#banner[state="danger"] { background: #111111; border: 2px solid #ffffff; }

QLineEdit, QPlainTextEdit, QTextEdit {
    background: #0b0b0b; border: 1px solid #242424; border-radius: 8px;
    padding: 7px 10px; selection-background-color: #ffffff; selection-color: #000000;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus { border-color: #ffffff; }
QLineEdit#urlbar { background: #050505; color: #bdbdbd; }
QPlainTextEdit { font-family: "Cascadia Mono", "Consolas", monospace; font-size: 12px; }

QComboBox, QSpinBox {
    background: #0b0b0b; border: 1px solid #242424; border-radius: 8px;
    padding: 5px 9px; min-height: 18px;
}
QComboBox { padding-right: 22px; }
QSpinBox { padding-right: 20px; }
QComboBox:hover, QSpinBox:hover { border-color: #3a3a3a; }
QComboBox QAbstractItemView {
    background: #0d0d0d; border: 1px solid #2b2b2b; border-radius: 8px;
    selection-background-color: #ffffff; selection-color: #000000; outline: none; padding: 4px;
}
QSpinBox::up-button, QSpinBox::down-button {
    subcontrol-origin: border; width: 18px; background: transparent; border: none;
}
QSpinBox::up-button { subcontrol-position: top right; margin: 3px 3px 0 0; }
QSpinBox::down-button { subcontrol-position: bottom right; margin: 0 3px 3px 0; }
QSpinBox::up-arrow { image: url("__ASSETS__/chevron-up.png"); width: 10px; height: 10px; }
QSpinBox::down-arrow { image: url("__ASSETS__/chevron-down.png"); width: 10px; height: 10px; }

QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid #333333; background: #0b0b0b;
}
QCheckBox::indicator:checked { background: #ffffff; border-color: #ffffff; }

QGroupBox {
    border: 1px solid #242424; border-radius: 10px;
    margin-top: 15px; padding: 16px 12px 10px 12px; font-weight: 600; color: #e6e6e6;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #9a9a9a; }

QTableWidget {
    background: #070707; alternate-background-color: #0b0b0b;
    border: 1px solid #242424; border-radius: 8px; gridline-color: #171717;
}
QHeaderView::section {
    background: #0d0d0d; border: none; border-bottom: 1px solid #242424;
    padding: 6px 8px; color: #9a9a9a; font-weight: 600;
}
QTableWidget::item { padding: 4px 6px; }
QTableWidget::item:selected { background: #ffffff; color: #000000; }

QMenu { background: #0d0d0d; border: 1px solid #2b2b2b; border-radius: 8px; padding: 5px; }
QMenu::item { padding: 6px 20px 6px 14px; border-radius: 6px; }
QMenu::item:selected { background: #ffffff; color: #000000; }
QMenu::separator { height: 1px; background: #242424; margin: 4px 8px; }

QDialog { background: #000000; }
QToolTip { background: #101010; color: #f0f0f0; border: 1px solid #333333; padding: 4px 6px; }

QMessageBox { background: #000000; }
QMessageBox QLabel { color: #f0f0f0; }

QStatusBar { background: #070707; color: #7a7a7a; border-top: 1px solid #1d1d1d; }
QStatusBar::item { border: none; }
"""


def _assets_dir() -> Path:
    folder = data_root() / "assets"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _write_chevrons(folder: Path) -> None:
    """Tiny white chevrons for spin boxes (Qt can't draw CSS triangles)."""
    shapes = {
        "chevron-up.png": [QPointF(4.0, 10.0), QPointF(8.0, 6.0), QPointF(12.0, 10.0)],
        "chevron-down.png": [QPointF(4.0, 6.0), QPointF(8.0, 10.0), QPointF(12.0, 6.0)],
    }
    for name, points in shapes.items():
        pm = QPixmap(16, 16)
        pm.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor("#c8c8c8"))
        pen.setWidthF(1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline(QPolygonF(points))
        painter.end()
        pm.save(str(folder / name), "PNG")


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(BG))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Base, QColor(PANEL_2))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#101010"))
    pal.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Button, QColor("#0d0d0d"))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#000000"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor("#101010"))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    app.setPalette(pal)

    assets = _assets_dir()
    try:
        _write_chevrons(assets)
    except Exception:
        pass
    app.setStyleSheet(QSS.replace("__ASSETS__", str(assets).replace("\\", "/")))

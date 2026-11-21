"""BigSeek Desktop — a tiny browser with fully isolated profiles.

Usage:
    python main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt6.QtCore import QCoreApplication, QLockFile, Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

# Importing QtWebEngineWidgets before QApplication is created is required.
from PyQt6 import QtWebEngineWidgets  # noqa: F401

from app.config import data_root
from app.theme import apply_theme
from app.ui.main_window import MainWindow


def main() -> int:
    QCoreApplication.setOrganizationName("local")
    QCoreApplication.setApplicationName("BigSeek Desktop")
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

    app = QApplication(sys.argv)
    apply_theme(app)

    # Two instances sharing the same browser profiles would corrupt them.
    lock = QLockFile(str(data_root() / "app.lock"))
    lock.setStaleLockTime(30000)
    if not lock.tryLock(200):
        QMessageBox.warning(
            None,
            "BigSeek Desktop",
            "BigSeek Desktop уже запущен.\nЗакройте предыдущее окно и попробуйте снова.",
        )
        return 0
    app._single_instance_lock = lock  # type: ignore[attr-defined]

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # keep a trace even in windowed (.exe) mode
        import traceback

        try:
            from app.config import data_root

            (data_root() / "crash.log").write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
        raise

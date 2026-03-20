#!/usr/bin/env python3
"""AI 語音筆記 - macOS / Windows"""
import sys
import os
import traceback
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from PyQt6.QtWidgets import QApplication, QMessageBox
from src.ui.main_window import MainWindow

SETUP_FLAG = Path(__file__).parent / ".setup_done"


def _exception_hook(exc_type, exc_value, exc_tb):
    """Prevent PyQt6 from calling abort() on unhandled slot exceptions."""
    msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    print(msg, file=sys.stderr)
    # Show a dialog so the user sees the error rather than a silent crash
    try:
        dlg = QMessageBox()
        dlg.setWindowTitle("程式錯誤")
        dlg.setText("發生錯誤，請回報以下訊息：")
        dlg.setDetailedText(msg)
        dlg.exec()
    except Exception:
        pass


def main():
    sys.excepthook = _exception_hook

    app = QApplication(sys.argv)
    app.setApplicationName("Transcribe")

    window = MainWindow()

    if not SETUP_FLAG.exists():
        from src.ui.setup_dialog import SetupDialog
        dlg = SetupDialog()
        dlg.exec()
        SETUP_FLAG.touch()

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

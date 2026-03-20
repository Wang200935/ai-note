"""
首次啟動設定畫面 - 自動下載模型，完成後進入主畫面
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont
from .styles import DARK_STYLE


class SetupThread(QThread):
    step = pyqtSignal(str, int)   # message, progress 0-100
    done = pyqtSignal()
    failed = pyqtSignal(str)

    def run(self):
        try:
            # Step 1: pre-load Whisper model
            self.step.emit("下載語音識別模型（Whisper small）...", 10)
            from faster_whisper import WhisperModel
            import os
            models_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'models')
            WhisperModel('small', device='cpu', compute_type='int8', download_root=models_dir)
            self.step.emit("語音識別模型已就緒", 50)

            # Step 2: pre-load simple-diarizer embedding model
            self.step.emit("下載說話人辨識模型...", 60)
            try:
                from resemblyzer import VoiceEncoder
                VoiceEncoder()  # triggers download if needed
            except ImportError:
                pass  # will install later
            self.step.emit("說話人辨識模型已就緒", 85)

            # Step 3: Check Ollama
            self.step.emit("檢查 AI 筆記服務...", 90)
            try:
                import ollama
                models = ollama.list().get('models', [])
                if not models:
                    # try to pull smallest model
                    import subprocess
                    subprocess.Popen(['ollama', 'pull', 'qwen2.5:3b'],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass  # Ollama optional

            self.step.emit("準備完成", 100)
            self.done.emit()

        except Exception as e:
            self.failed.emit(str(e))


class SetupDialog(QDialog):
    """Shown on first run to download all models automatically."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("首次啟動設定")
        self.setFixedSize(480, 260)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint |
                            Qt.WindowType.WindowTitleHint)
        self.setStyleSheet(DARK_STYLE)
        self._setup_ui()
        self._thread = SetupThread()
        self._thread.step.connect(self._on_step)
        self._thread.done.connect(self._on_done)
        self._thread.failed.connect(self._on_failed)
        QTimer.singleShot(300, self._thread.start)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(32, 32, 32, 32)

        title = QLabel("AI 語音筆記")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #cba6f7;")
        layout.addWidget(title)

        subtitle = QLabel("首次啟動，正在準備所需模型...")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #6c7086; font-size: 13px;")
        layout.addWidget(subtitle)

        self.status_label = QLabel("初始化中...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #cdd6f4; font-size: 13px;")
        layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setMaximum(100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(8)
        layout.addWidget(self.progress)

        note = QLabel("模型將快取在本機，之後啟動無需下載")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setStyleSheet("color: #45475a; font-size: 11px;")
        layout.addWidget(note)

        self.close_btn = QPushButton("進入應用")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        layout.addWidget(self.close_btn)

    def _on_step(self, msg: str, pct: int):
        self.status_label.setText(msg)
        self.progress.setValue(pct)

    def _on_done(self):
        self.status_label.setText("準備完成，進入應用")
        self.progress.setValue(100)
        self.close_btn.setEnabled(True)
        # Auto-close after 1 second
        QTimer.singleShot(1000, self.accept)

    def _on_failed(self, err: str):
        self.status_label.setText(f"部分模型載入失敗（{err[:60]}...），繼續使用基本功能")
        self.progress.setValue(100)
        self.close_btn.setEnabled(True)
        QTimer.singleShot(2000, self.accept)

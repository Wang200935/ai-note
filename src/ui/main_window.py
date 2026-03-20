"""
Main window
- Real-time streaming transcription during recording
- Final refinement pass (full Whisper + diarization) after stop
- Clear labeled controls, device selector, multi-model notes
"""
import subprocess
import shutil
import time
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QLabel, QPushButton, QComboBox, QListWidget,
    QListWidgetItem, QTextEdit, QProgressBar, QLineEdit,
    QFileDialog, QMessageBox, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot, QThread, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QBrush

from .styles import STYLE
from .transcript_view import TranscriptView
from ..audio.recorder import AudioRecorder
from ..transcription.engine import TranscriptionEngine
from ..transcription.streaming import StreamingTranscriber
from ..transcription.diarizer import SpeakerDiarizer, merge_transcript_with_diarization
from ..notes.organizer import NoteOrganizer
from ..storage.database import Database
from ..export.exporter import export_txt, export_docx, export_pdf

BASE_DIR       = Path(__file__).parent.parent.parent
RECORDINGS_DIR = BASE_DIR / "recordings"


def _valid_model(name: str) -> bool:
    bad = {"", "偵測中...", "下載中...", "未安裝 Ollama", "模型載入失敗", "無可用模型"}
    return name.strip() not in bad


# ── OllamaManager (module-level: pyqtSignal needs this) ─────────────────────

class OllamaManager(QThread):
    status  = pyqtSignal(str)
    ready   = pyqtSignal(list)   # list[str] of model names
    missing = pyqtSignal()

    DEFAULT = "qwen2.5:3b"

    def run(self):
        if not shutil.which("ollama"):
            self.missing.emit()
            return

        try:
            import ollama as _ol
            _ol.list()
        except Exception:
            self.status.emit("啟動 Ollama 服務...")
            subprocess.Popen(["ollama", "serve"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(3)

        try:
            import ollama as _ol
            result = _ol.list()
            # ollama >= 0.2 returns ListResponse with .models (list of Model objects)
            # older versions return a dict with "models" key
            raw = result.models if hasattr(result, "models") else result.get("models", [])
            names = []
            for m in raw:
                # Model object has .model field; older dict has "name" key
                n = m.model if hasattr(m, "model") else m.get("name", "")
                if n:
                    names.append(n)
            if names:
                self.ready.emit(names)
                return
        except Exception as e:
            self.status.emit(f"Ollama 錯誤: {e}")
            return

        self.status.emit(f"下載預設模型 {self.DEFAULT}（約 2 GB）...")
        try:
            r = subprocess.run(["ollama", "pull", self.DEFAULT],
                               capture_output=True, text=True, timeout=600)
            if r.returncode == 0:
                self.ready.emit([self.DEFAULT])
            else:
                self.status.emit("下載失敗，請執行: ollama pull qwen2.5:3b")
        except subprocess.TimeoutExpired:
            self.status.emit("下載超時，請檢查網路")
        except Exception as e:
            self.status.emit(str(e))


# ── VU meter ──────────────────────────────────────────────────────────────────

class LevelMeter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(70, 6)
        self._level = 0.0

    def set_level(self, rms: float):
        self._level = min(1.0, rms * 8)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#1e1e1e"))
        fw = int(w * self._level)
        if fw > 0:
            g = QLinearGradient(0, 0, w, 0)
            g.setColorAt(0.0, QColor("#22c55e"))
            g.setColorAt(0.7, QColor("#f59e0b"))
            g.setColorAt(1.0, QColor("#ef4444"))
            p.fillRect(0, 0, fw, h, QBrush(g))


# ── States ────────────────────────────────────────────────────────────────────

class S:
    IDLE     = "idle"
    LOADING  = "loading"    # model loading
    LIVE     = "live"       # recording + streaming transcription
    REFINING = "refining"   # final pass
    DONE     = "done"


# ── Small helpers ─────────────────────────────────────────────────────────────

def _labeled(label_text: str, widget, tip: str = "") -> QWidget:
    """Wrap a widget with a label above it."""
    container = QWidget()
    container.setStyleSheet("background: transparent;")
    lay = QVBoxLayout(container)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    lbl = QLabel(label_text)
    lbl.setStyleSheet("color: #555; font-size: 10px; text-transform: uppercase;")
    lay.addWidget(lbl)
    lay.addWidget(widget)
    if tip:
        widget.setToolTip(tip)
        lbl.setToolTip(tip)
    return container


def _vsep() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.VLine)
    sep.setStyleSheet("color: #222; max-width: 1px;")
    return sep


# ── Main Window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Transcribe")
        self.setMinimumSize(920, 580)
        self.resize(1200, 720)
        self.setStyleSheet(STYLE)

        self._state      = S.IDLE
        self._live_segs  = []
        self._final_segs = []
        self._audio_path: str | None = None
        self._rec_id:     int | None = None
        self._rec_start:  datetime | None = None
        self._ollama_mgr: OllamaManager | None = None
        self._notes_counter   = 0
        self._notes_running   = False
        self._pending_record  = False   # waiting for model load

        self.recorder  = AudioRecorder(str(RECORDINGS_DIR))
        self.tx_engine = TranscriptionEngine(model_size="small")
        self.streamer:  StreamingTranscriber | None = None
        self.diarizer  = SpeakerDiarizer()
        self.notes_org = NoteOrganizer()
        self.db        = Database()

        # Timers
        self._clock = QTimer()
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._tick_clock)

        self._decay = QTimer()
        self._decay.setInterval(50)
        self._decay.timeout.connect(
            lambda: self.vu.set_level(self.vu._level * 0.75)
        )
        self._decay.start()

        self._prog_timer  = QTimer()
        self._prog_timer.setInterval(250)
        self._prog_timer.timeout.connect(self._tick_progress)
        self._prog_target = 0

        self._build_ui()
        self._connect_signals()
        self._load_history()
        self._start_ollama()

        # Pre-load default model in background
        self.tx_engine.load_model_async("small")

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        rl = QHBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        rl.addWidget(self._make_sidebar())

        right = QWidget()
        right.setStyleSheet("background: #0d0d0d;")
        rl2 = QVBoxLayout(right)
        rl2.setContentsMargins(0, 0, 0, 0)
        rl2.setSpacing(0)
        rl2.addWidget(self._make_topbar())
        rl2.addWidget(self._make_progress_strip())
        rl2.addWidget(self._make_content(), stretch=1)
        rl2.addWidget(self._make_bottombar())
        rl.addWidget(right, stretch=1)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color: #555; font-size: 11px; padding: 0 4px;")
        self.statusBar().addWidget(self._status_lbl)
        self.statusBar().setStyleSheet(
            "QStatusBar { background:#0a0a0a; border-top:1px solid #1a1a1a; }"
        )

    def _make_sidebar(self):
        sb = QWidget()
        sb.setObjectName("sidebar")
        sl = QVBoxLayout(sb)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)

        hdr = QLabel("記錄")
        hdr.setStyleSheet(
            "font-size:11px; color:#444; padding:12px 14px 8px 14px;"
            "border-bottom:1px solid #1a1a1a; text-transform:uppercase; letter-spacing:1px;"
        )
        sl.addWidget(hdr)

        self.history_list = QListWidget()
        sl.addWidget(self.history_list, stretch=1)

        del_btn = QPushButton("刪除")
        del_btn.clicked.connect(self._delete_history)
        del_btn.setStyleSheet("margin:6px 10px; padding:4px;")
        sl.addWidget(del_btn)
        return sb

    def _make_topbar(self):
        bar = QWidget()
        bar.setObjectName("topbar")
        bar.setFixedHeight(46)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 0, 12, 0)
        bl.setSpacing(10)

        self.title_edit = QLineEdit("新的記錄")
        self.title_edit.setObjectName("title")
        self.title_edit.setMaximumWidth(360)
        bl.addWidget(self.title_edit)
        bl.addStretch()

        self.export_btn = QPushButton("匯出")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._show_export_menu)
        bl.addWidget(self.export_btn)
        return bar

    def _make_progress_strip(self):
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(2)
        self.progress_bar.setStyleSheet(
            "QProgressBar{background:#111;border:none;}"
            "QProgressBar::chunk{background:#3b82f6;}"
        )
        return self.progress_bar

    def _make_content(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        # ── Transcript pane ──
        tx = QWidget()
        tl = QVBoxLayout(tx)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)

        tx_hdr = QWidget()
        tx_hdr.setFixedHeight(34)
        tx_hdr.setStyleSheet("border-bottom:1px solid #1a1a1a;")
        th = QHBoxLayout(tx_hdr)
        th.setContentsMargins(16, 0, 16, 0)
        lbl = QLabel("逐字稿")
        lbl.setStyleSheet("font-size:12px;color:#555;font-weight:500;")
        self.live_badge = QLabel("")
        self.live_badge.setStyleSheet("font-size:10px;color:#f59e0b;")
        th.addWidget(lbl)
        th.addStretch()
        th.addWidget(self.live_badge)
        tl.addWidget(tx_hdr)

        self.transcript_view = TranscriptView()
        tl.addWidget(self.transcript_view, stretch=1)
        splitter.addWidget(tx)

        # ── Notes pane ──
        nt = QWidget()
        nl = QVBoxLayout(nt)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(0)

        nt_hdr = QWidget()
        nt_hdr.setFixedHeight(34)
        nt_hdr.setStyleSheet("border-bottom:1px solid #1a1a1a;")
        nh = QHBoxLayout(nt_hdr)
        nh.setContentsMargins(16, 0, 16, 0)
        nlbl = QLabel("整理筆記")
        nlbl.setStyleSheet("font-size:12px;color:#555;font-weight:500;")
        self.notes_badge = QLabel("")
        self.notes_badge.setStyleSheet("font-size:10px;color:#f59e0b;")
        nh.addWidget(nlbl)
        nh.addStretch()
        nh.addWidget(self.notes_badge)
        nl.addWidget(nt_hdr)

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("錄音開始後自動生成...")
        nl.addWidget(self.notes_edit, stretch=1)
        splitter.addWidget(nt)

        splitter.setSizes([580, 420])
        return splitter

    def _make_bottombar(self):
        bar = QWidget()
        bar.setObjectName("bottombar")
        bar.setFixedHeight(60)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 0, 16, 0)
        bl.setSpacing(12)

        # ── Record button ──────────────────────────────────────────────────
        self.rec_btn = QPushButton("開始錄音")
        self.rec_btn.setFixedSize(110, 34)
        self._style_rec(False)
        self.rec_btn.clicked.connect(self._on_rec_btn)
        bl.addWidget(self.rec_btn)

        bl.addWidget(_vsep())

        # ── 麥克風 / 系統聲音 ──────────────────────────────────────────────
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(140)
        self.device_combo.setMaximumWidth(180)
        self._populate_devices()

        self.sys_audio_btn = QPushButton("電腦聲音")
        self.sys_audio_btn.setFixedHeight(26)
        self.sys_audio_btn.setCheckable(True)
        self.sys_audio_btn.setToolTip(
            "錄製電腦正在播放的聲音（使用 ScreenCaptureKit）\n"
            "需要：系統設定 → 隱私與安全 → 螢幕錄製 → 允許 Terminal"
        )
        self._style_sys_btn(False)
        self.sys_audio_btn.toggled.connect(self._on_sys_audio_toggled)

        mic_group = QWidget()
        mic_group.setStyleSheet("background:transparent;")
        mg = QVBoxLayout(mic_group)
        mg.setContentsMargins(0, 0, 0, 0)
        mg.setSpacing(2)
        mg_hdr = QHBoxLayout()
        mg_lbl = QLabel("音訊來源")
        mg_lbl.setStyleSheet("color:#555; font-size:10px; text-transform:uppercase;")
        mg_hdr.addWidget(mg_lbl)
        mg_hdr.addStretch()
        mg_hdr.addWidget(self.sys_audio_btn)
        mg.addLayout(mg_hdr)
        mg.addWidget(self.device_combo)
        bl.addWidget(mic_group)

        # ── 語言 ───────────────────────────────────────────────────────────
        self.lang_combo = QComboBox()
        self.lang_combo.setFixedWidth(90)
        self.lang_combo.addItem("自動偵測", None)
        self.lang_combo.addItem("繁體中文", "zh")
        self.lang_combo.addItem("簡體中文", "zh")
        self.lang_combo.addItem("英文", "en")
        self.lang_combo.addItem("日文", "ja")
        self.lang_combo.addItem("韓文", "ko")
        self.lang_combo.addItem("法文", "fr")
        self.lang_combo.addItem("德文", "de")
        self.lang_combo.addItem("西班牙文", "es")
        self.lang_combo.setCurrentIndex(1)   # 預設：繁體中文
        bl.addWidget(_labeled(
            "語言",
            self.lang_combo,
            "指定語音語言可大幅提升辨識準確度\n"
            "中文容易被誤判為日文，建議手動選擇"
        ))

        # ── 模式 ───────────────────────────────────────────────────────────
        self.mode_combo = QComboBox()
        self.mode_combo.setFixedWidth(80)
        self.mode_combo.addItems(["課堂", "會議"])
        bl.addWidget(_labeled("模式", self.mode_combo, "課堂: 整理成筆記重點\n會議: 產生會議記錄"))

        # ── 轉錄模型 ────────────────────────────────────────────────────────
        self.model_combo = QComboBox()
        self.model_combo.setFixedWidth(90)
        self.model_combo.addItems(["tiny", "base", "small", "medium", "large-v3"])
        self.model_combo.setCurrentText("small")
        bl.addWidget(_labeled(
            "轉錄模型",
            self.model_combo,
            "Whisper 語音轉文字模型\n"
            "tiny/base: 較快，精確度較低\n"
            "small: 推薦，速度與精確度平衡\n"
            "medium/large-v3: 最準確，速度較慢\n"
            "（首次使用會自動下載）"
        ))

        bl.addWidget(_vsep())

        # ── 筆記模型 ─────────────────────────────────────────────────────
        self.llm_combo = QComboBox()
        self.llm_combo.setMinimumWidth(130)
        self.llm_combo.setMaximumWidth(180)

        refresh_btn = QPushButton("重新整理")
        refresh_btn.setFixedHeight(26)
        refresh_btn.setStyleSheet("padding: 2px 8px; font-size:11px;")
        refresh_btn.setToolTip("重新掃描 Ollama 模型清單")
        refresh_btn.clicked.connect(self._start_ollama)

        notes_row = QWidget()
        notes_row.setStyleSheet("background:transparent;")
        nr = QVBoxLayout(notes_row)
        nr.setContentsMargins(0, 0, 0, 0)
        nr.setSpacing(2)
        nr_hdr = QHBoxLayout()
        nr_lbl = QLabel("筆記 AI 模型")
        nr_lbl.setStyleSheet("color:#555; font-size:10px; text-transform:uppercase;")
        nr_lbl.setToolTip(
            "Ollama 本地 AI 模型，用於整理逐字稿成筆記\n"
            "安裝更多模型: ollama pull <模型名稱>\n"
            "推薦: qwen2.5:7b（中文）, llama3.2, mistral"
        )
        nr_hdr.addWidget(nr_lbl)
        nr_hdr.addStretch()
        nr_hdr.addWidget(refresh_btn)
        nr.addLayout(nr_hdr)

        llm_row = QHBoxLayout()
        llm_row.setSpacing(4)
        llm_row.addWidget(self.llm_combo)
        nr.addLayout(llm_row)
        bl.addWidget(notes_row)

        self.llm_status = QLabel("")
        self.llm_status.setStyleSheet("color:#555; font-size:11px; max-width:120px;")
        self.llm_status.setWordWrap(True)
        bl.addWidget(self.llm_status)

        bl.addWidget(_vsep())

        # ── 開啟檔案 ───────────────────────────────────────────────────────
        open_btn = QPushButton("開啟檔案")
        open_btn.setFixedHeight(34)
        open_btn.setToolTip("開啟已有的音訊檔案進行轉錄")
        open_btn.clicked.connect(self._open_file)
        bl.addWidget(open_btn)

        bl.addStretch()

        # ── 計時 + VU ──────────────────────────────────────────────────────
        self.timer_lbl = QLabel("00:00")
        self.timer_lbl.setStyleSheet("color:#444; font-size:12px; min-width:42px;")
        bl.addWidget(self.timer_lbl)

        self.vu = LevelMeter()
        self.vu.setToolTip("麥克風音量（如果沒有反應請確認麥克風選擇是否正確）")
        bl.addWidget(self.vu)

        # ── Model loading status ───────────────────────────────────────────
        self.model_load_lbl = QLabel("")
        self.model_load_lbl.setStyleSheet("color:#3b82f6; font-size:11px;")
        bl.addWidget(self.model_load_lbl)

        return bar

    def _style_rec(self, recording: bool):
        if recording:
            self.rec_btn.setStyleSheet("""
                QPushButton {
                    background:#160808; color:#ef4444;
                    border:1px solid #ef4444; border-radius:3px; font-weight:600;
                }
                QPushButton:hover { background:#1e0a0a; }
            """)
        else:
            self.rec_btn.setStyleSheet("""
                QPushButton {
                    background:#080e1a; color:#3b82f6;
                    border:1px solid #3b82f6; border-radius:3px; font-weight:600;
                }
                QPushButton:hover { background:#0a1220; }
                QPushButton:disabled { background:#111; color:#333; border-color:#222; }
            """)

    # ── Signals ───────────────────────────────────────────────────────────────

    def _connect_signals(self):
        self.history_list.itemClicked.connect(self._load_history_item)
        self.recorder.level_updated.connect(self.vu.set_level)
        self.recorder.recording_stopped.connect(self._on_recording_stopped)
        self.recorder.error_occurred.connect(self._on_recorder_error)

        # Model loading
        self.tx_engine.model_loading.connect(
            lambda s: self.model_load_lbl.setText(f"載入 {s}...")
        )
        self.tx_engine.model_loaded.connect(self._on_model_loaded)
        self.tx_engine.model_error.connect(
            lambda e: self.model_load_lbl.setText(f"模型載入失敗: {e[:40]}")
        )

        # Final transcription
        self.tx_engine.segment_ready.connect(self._on_final_seg)
        self.tx_engine.progress.connect(
            lambda p: self.progress_bar.setValue(int(p * 0.6))
        )
        self.tx_engine.finished.connect(self._on_final_tx_done)
        self.tx_engine.error.connect(self._on_error)

        # Diarization
        self.diarizer.finished.connect(self._on_diarization_done)
        self.diarizer.error.connect(self._on_error)
        self.diarizer.progress.connect(self._set_status)

        # Notes
        self.notes_org.chunk_ready.connect(self._on_notes_chunk)
        self.notes_org.finished.connect(self._on_notes_done)
        self.notes_org.error.connect(self._on_notes_error)

        self.transcript_view.segment_edited.connect(
            lambda sid, txt: self.db.update_segment(sid, txt)
        )

    # ── Ollama ────────────────────────────────────────────────────────────────

    def _start_ollama(self):
        if self._ollama_mgr and self._ollama_mgr.isRunning():
            return
        self.llm_combo.clear()
        self.llm_combo.addItem("偵測中...")
        self.llm_status.setText("")
        self._ollama_mgr = OllamaManager()
        self._ollama_mgr.status.connect(self.llm_status.setText)
        self._ollama_mgr.ready.connect(self._on_ollama_ready)
        self._ollama_mgr.missing.connect(self._on_ollama_missing)
        self._ollama_mgr.start()

    @pyqtSlot(list)
    def _on_ollama_ready(self, names: list):
        self.llm_combo.clear()
        for n in names:
            self.llm_combo.addItem(n)
        self.llm_status.setText(f"{len(names)} 個模型")

    @pyqtSlot()
    def _on_ollama_missing(self):
        self.llm_combo.clear()
        self.llm_status.setText("未安裝 Ollama\nhttps://ollama.com")

    # ── Model loading ─────────────────────────────────────────────────────────

    @pyqtSlot(str)
    def _on_model_loaded(self, size: str):
        self.model_load_lbl.setText("")
        self.rec_btn.setEnabled(True)
        self._style_rec(False)
        if self._pending_record:
            self._pending_record = False
            self._do_start_recording()

    # ── Recording ─────────────────────────────────────────────────────────────

    def _on_rec_btn(self):
        if self._state in (S.IDLE, S.DONE):
            self._begin_recording()
        elif self._state == S.LIVE:
            self._end_recording()

    def _begin_recording(self):
        model_name = self.model_combo.currentText()

        # If model not ready: load first, then auto-start
        if not self.tx_engine.is_loaded or self.tx_engine.model_size != model_name:
            self._pending_record = True
            self.rec_btn.setEnabled(False)
            self.rec_btn.setText("載入中...")
            self.tx_engine.load_model_async(model_name)
            return

        self._do_start_recording()

    def _do_start_recording(self):
        self._state = S.LIVE
        self._live_segs.clear()
        self._final_segs.clear()
        self._notes_counter = 0
        self._notes_running = False
        self.transcript_view.clear()
        self.notes_edit.clear()
        self.export_btn.setEnabled(False)
        self._reset_progress()
        self._rec_start = datetime.now()

        ts   = self._rec_start.strftime("%Y-%m-%d %H:%M")
        mode = "課堂" if self.mode_combo.currentIndex() == 0 else "會議"
        self.title_edit.setText(f"{mode} {ts}")

        device = self.device_combo.currentData()   # full dict or None
        self._audio_path = self.recorder.start(device)

        lang = self.lang_combo.currentData()   # str code or None

        # Start streaming transcriber with already-loaded model
        self.streamer = StreamingTranscriber(
            self.tx_engine._model,
            self.recorder.get_buffer,
        )
        self.streamer.new_segment.connect(self._on_live_seg)
        self.streamer.language_detected.connect(
            lambda l: self._set_status(f"語言: {l}")
        )
        self.streamer.begin(language=lang)

        self.rec_btn.setText("停止錄音")
        self.rec_btn.setEnabled(True)
        self._style_rec(True)
        self.live_badge.setText("即時")
        self._clock.start()
        self._set_status("錄音中")

    def _end_recording(self):
        self._state = S.REFINING
        self.rec_btn.setEnabled(False)
        self.rec_btn.setText("精修中...")
        self._clock.stop()
        self.live_badge.setText("精修中")

        if self.streamer:
            self.streamer.halt()
            self.streamer = None

        self.recorder.stop()

    @pyqtSlot(str)
    def _on_recording_stopped(self, path: str):
        self._audio_path = path
        self._begin_final_pass()

    def _open_file(self):
        if self._state in (S.LIVE, S.REFINING, S.LOADING):
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "開啟音訊檔案", str(RECORDINGS_DIR),
            "Audio Files (*.wav *.mp3 *.m4a *.ogg *.flac *.aac)"
        )
        if not path:
            return
        self._audio_path = path
        self._live_segs.clear()
        self._final_segs.clear()
        self.transcript_view.clear()
        self.notes_edit.clear()
        self.export_btn.setEnabled(False)
        self.title_edit.setText(Path(path).stem)
        self._state = S.REFINING
        self._reset_progress()
        self._begin_final_pass()

    # ── Live transcription ────────────────────────────────────────────────────

    @pyqtSlot(object)
    def _on_live_seg(self, seg):
        self._live_segs.append(seg)
        self.transcript_view.add_live_segment(seg)
        self._notes_counter += 1
        if self._notes_counter >= 6 and not self._notes_running:
            self._notes_counter = 0
            self._run_notes(self._live_segs, final=False)

    # ── Final pass ────────────────────────────────────────────────────────────

    def _begin_final_pass(self):
        self._final_segs = []
        self._animate_to(60)
        self._set_status("重新轉錄（精修中）")
        model_name = self.model_combo.currentText()
        lang = self.lang_combo.currentData()
        if not self.tx_engine.is_loaded or self.tx_engine.model_size != model_name:
            self.tx_engine.load_model_async(model_name)
            self.tx_engine.model_loaded.connect(
                lambda _: self.tx_engine.transcribe(self._audio_path, lang)
            )
        else:
            self.tx_engine.transcribe(self._audio_path, lang)

    @pyqtSlot(object)
    def _on_final_seg(self, seg):
        self._final_segs.append(seg)

    @pyqtSlot(list, str)
    def _on_final_tx_done(self, segments, language):
        self._final_segs = segments
        # Show transcript immediately — don't wait for diarization
        self.transcript_view.replace_with_final(self._final_segs)
        self.progress_bar.setValue(62)
        self._set_status(f"說話人辨識  [{language}]")
        self._animate_to(82)
        self.diarizer.set_backend("simple")
        self.diarizer.diarize(self._audio_path)

    @pyqtSlot(list)
    def _on_diarization_done(self, diar_segs):
        self._final_segs = merge_transcript_with_diarization(
            self._final_segs, diar_segs
        )
        # Re-render with speaker labels
        self.transcript_view.replace_with_final(self._final_segs)
        self.progress_bar.setValue(84)
        self._save_session()
        self._run_notes(self._final_segs, final=True)

    # ── Notes ─────────────────────────────────────────────────────────────────

    def _run_notes(self, segments, final: bool):
        if not segments:
            if final:
                self._finish()
            return
        llm = self.llm_combo.currentText()
        if not _valid_model(llm):
            if final:
                self._finish()
            return
        self._notes_running = True
        if final:
            self.notes_edit.clear()
        self.notes_badge.setText("更新中")
        self.notes_org.set_model(llm)
        mode = "class" if self.mode_combo.currentIndex() == 0 else "meeting"
        self.notes_org.organize(segments, mode=mode)

    @pyqtSlot(str)
    def _on_notes_chunk(self, chunk):
        c = self.notes_edit.textCursor()
        c.movePosition(c.MoveOperation.End)
        c.insertText(chunk)
        self.notes_edit.setTextCursor(c)

    @pyqtSlot(str)
    def _on_notes_done(self, notes):
        self._notes_running = False
        self.notes_badge.setText("")
        if self._rec_id:
            self.db.update_notes(self._rec_id, notes)
        if self._state == S.REFINING:
            self._load_history()
            self._finish()

    @pyqtSlot(str)
    def _on_recorder_error(self, msg: str):
        self._set_status("錄音錯誤")
        QMessageBox.warning(self, "錄音問題", msg)

    @pyqtSlot(str)
    def _on_notes_error(self, msg: str):
        self._notes_running = False
        self.notes_badge.setText("")
        self._set_status(f"筆記錯誤: {msg[:60]}")
        if self._state == S.REFINING:
            self._load_history()
            self._finish()

    # ── Finish ────────────────────────────────────────────────────────────────

    def _finish(self):
        self._prog_timer.stop()
        self._state = S.DONE
        self.progress_bar.setValue(100)
        QTimer.singleShot(600, lambda: self.progress_bar.setValue(0))
        self._set_status("完成")
        self.live_badge.setText("")
        self.rec_btn.setText("開始錄音")
        self.rec_btn.setEnabled(True)
        self._style_rec(False)
        self.export_btn.setEnabled(True)

    @pyqtSlot(str)
    def _on_error(self, msg: str):
        self._set_status(f"警告: {msg[:80]}")
        self._notes_running = False
        if self._state == S.REFINING:
            # Diarization may have failed but transcript is already shown;
            # save and finish without speaker labels
            if self._final_segs and not self._rec_id:
                self._save_session()
            self._run_notes(self._final_segs, final=True)

    # ── DB ────────────────────────────────────────────────────────────────────

    def _save_session(self):
        if not self._final_segs:
            return
        mode = "class" if self.mode_combo.currentIndex() == 0 else "meeting"
        lang = self._final_segs[0].language if self._final_segs else ""
        self._rec_id = self.db.save_recording(
            title=self.title_edit.text() or "未命名",
            audio_path=self._audio_path or "",
            mode=mode, language=lang,
            duration=self._final_segs[-1].end,
            segments=self._final_segs,
        )
        self._load_history()

    # ── History ───────────────────────────────────────────────────────────────

    def _load_history(self):
        self.history_list.clear()
        for rec in self.db.get_all_recordings():
            ts   = rec.created_at.strftime("%m/%d %H:%M") if rec.created_at else ""
            mode = "課堂" if rec.mode == "class" else "會議"
            item = QListWidgetItem(f"{rec.title}\n{mode}  {ts}")
            item.setData(Qt.ItemDataRole.UserRole, rec.id)
            self.history_list.addItem(item)

    def _load_history_item(self, item: QListWidgetItem):
        if self._state in (S.LIVE, S.REFINING, S.LOADING):
            return
        rec = self.db.get_recording(item.data(Qt.ItemDataRole.UserRole))
        if not rec:
            return
        self._rec_id     = rec.id
        self._audio_path = rec.audio_path

        from ..transcription.engine import TranscriptSegment
        self._final_segs = [
            TranscriptSegment(start=s.start, end=s.end, text=s.text,
                              language=rec.language or "", speaker=s.speaker)
            for s in rec.segments
        ]
        self.transcript_view.load_segments(self._final_segs)
        self.notes_edit.setPlainText(rec.notes or "")
        self.title_edit.setText(rec.title)
        self.export_btn.setEnabled(True)
        self._state = S.DONE
        self._reset_progress()
        self.rec_btn.setText("開始錄音")
        self.rec_btn.setEnabled(True)
        self._style_rec(False)
        self._set_status("")

    def _delete_history(self):
        item = self.history_list.currentItem()
        if not item:
            return
        if QMessageBox.question(
            self, "確認", "刪除此記錄？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.db.delete_recording(item.data(Qt.ItemDataRole.UserRole))
            self._load_history()

    # ── Export ────────────────────────────────────────────────────────────────

    def _show_export_menu(self):
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.addAction("TXT",  lambda: self._export("txt"))
        menu.addAction("Word", lambda: self._export("docx"))
        menu.addAction("PDF",  lambda: self._export("pdf"))
        menu.exec(self.export_btn.mapToGlobal(self.export_btn.rect().bottomLeft()))

    def _export(self, fmt):
        segs = self._final_segs or self._live_segs
        if not segs:
            return
        title = self.title_edit.text() or "transcript"
        safe  = "".join(c for c in title if c.isalnum() or c in " _-").strip()
        path, _ = QFileDialog.getSaveFileName(
            self, "儲存",
            str(Path.home() / "Desktop" / f"{safe}.{fmt}"),
            f"*.{fmt}",
        )
        if not path:
            return
        try:
            {"txt": export_txt, "docx": export_docx, "pdf": export_pdf}[fmt](
                segs, self.notes_edit.toPlainText(), title, path
            )
            QMessageBox.information(self, "匯出成功", f"已儲存：\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "匯出失敗", str(e))

    # ── Progress ──────────────────────────────────────────────────────────────

    def _reset_progress(self):
        self._prog_timer.stop()
        self._prog_target = 0
        self.progress_bar.setValue(0)

    def _animate_to(self, target: int):
        self._prog_target = target
        if not self._prog_timer.isActive():
            self._prog_timer.start()

    def _tick_progress(self):
        cur = self.progress_bar.value()
        if cur < self._prog_target:
            self.progress_bar.setValue(cur + 1)
        else:
            self._prog_timer.stop()

    # ── Clock ─────────────────────────────────────────────────────────────────

    def _tick_clock(self):
        if self._rec_start:
            s = int((datetime.now() - self._rec_start).total_seconds())
            m, s = divmod(s, 60)
            self.timer_lbl.setText(f"{m:02d}:{s:02d}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _populate_devices(self):
        self.device_combo.clear()
        self.device_combo.addItem("系統預設", None)
        best_idx = 0   # default to first item ("系統預設")
        for i, d in enumerate(self.recorder.get_devices()):
            self.device_combo.addItem(d["label"], d)
            # Auto-select the built-in mic if present
            name_lower = d["name"].lower()
            if d["type"] == "mic" and any(k in name_lower for k in
                    ("macbook", "built-in", "internal", "內建", "麥克風")):
                best_idx = i + 1   # +1 because "系統預設" is index 0
        self.device_combo.setCurrentIndex(best_idx)

    def _style_sys_btn(self, active: bool):
        if active:
            self.sys_audio_btn.setStyleSheet(
                "QPushButton { background:#0e1e10; color:#22c55e; "
                "border:1px solid #22c55e; border-radius:3px; padding:2px 8px; font-size:11px; }"
                "QPushButton:hover { background:#122516; }"
            )
        else:
            self.sys_audio_btn.setStyleSheet(
                "QPushButton { background:transparent; color:#555; "
                "border:1px solid #333; border-radius:3px; padding:2px 8px; font-size:11px; }"
                "QPushButton:hover { color:#888; border-color:#555; }"
            )

    def _on_sys_audio_toggled(self, checked: bool):
        if not checked:
            self._style_sys_btn(False)
            self.device_combo.setEnabled(True)
            self._set_status("")
            return

        from ..audio.system_audio import find_system_audio_device, get_sck_device, BLACKHOLE_GUIDE

        # 1. Prefer an already-installed virtual driver (BlackHole etc.)
        dev = find_system_audio_device()

        # 2. Fall back to ScreenCaptureKit (macOS 12.3+ — no driver needed)
        if dev is None:
            dev = get_sck_device()

        if dev:
            if dev.get("backend") == "sck":
                # SCK device is not in the sounddevice combo — store as special item
                # Find or insert it
                sck_idx = -1
                for i in range(self.device_combo.count()):
                    d = self.device_combo.itemData(i)
                    if d and d.get("backend") == "sck":
                        sck_idx = i
                        break
                if sck_idx == -1:
                    self.device_combo.addItem(dev["label"], dev)
                    sck_idx = self.device_combo.count() - 1
                self.device_combo.setCurrentIndex(sck_idx)
            else:
                # Virtual driver — find in existing combo items
                for i in range(self.device_combo.count()):
                    d = self.device_combo.itemData(i)
                    if d and d.get("name") == dev["name"]:
                        self.device_combo.setCurrentIndex(i)
                        break
                else:
                    self._populate_devices()
                    for i in range(self.device_combo.count()):
                        d = self.device_combo.itemData(i)
                        if d and d.get("type") == "system":
                            self.device_combo.setCurrentIndex(i)
                            break

            self.device_combo.setEnabled(False)
            self._style_sys_btn(True)
            self._set_status(f"電腦聲音：{dev['name']}")
        else:
            # Neither virtual driver nor SCK available
            self.sys_audio_btn.setChecked(False)   # revert toggle
            QMessageBox.information(self, "電腦聲音設定", BLACKHOLE_GUIDE)

    def _show_system_audio_guide(self):
        available, msg = AudioRecorder.has_system_audio_support()
        if available:
            QMessageBox.information(
                self, "系統聲音設定",
                "已偵測到系統聲音擷取裝置（BlackHole / Background Music）。\n\n"
                "使用步驟：\n"
                "1. 在「音訊來源」選單選擇標有 [系統聲音] 的裝置\n"
                "2. 在 macOS「系統設定 → 聲音 → 輸出」選擇同一個裝置\n"
                "   （或選擇包含它的「聚集裝置」以同時保留喇叭聲音）\n"
                "3. 點「開始錄音」即可錄到電腦播放的聲音\n\n"
                "提示：「Background Music」app 可同時從喇叭播出並讓本應用錄到聲音，\n"
                "安裝後選「[系統聲音] Background Music」即可，無需額外設定。"
            )
        else:
            QMessageBox.information(self, "系統聲音設定", msg)

    def _set_status(self, msg: str):
        self._status_lbl.setText(msg)

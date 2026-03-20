"""
Whisper transcription engine
"""
import os
from faster_whisper import WhisperModel
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from dataclasses import dataclass
from typing import Optional

MODELS_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'models')


@dataclass
class TranscriptSegment:
    start:    float
    end:      float
    text:     str
    language: str
    speaker:  Optional[str] = None
    id:       Optional[int] = None   # set after DB save


# ── Background model loader (module-level so pyqtSignal works) ───────────────

class ModelLoadThread(QThread):
    ready = pyqtSignal(object, str)   # (WhisperModel, model_size)
    error = pyqtSignal(str)

    def __init__(self, size: str, device: str, compute_type: str):
        super().__init__()
        self._size         = size
        self._device       = device
        self._compute_type = compute_type

    def run(self):
        try:
            model = WhisperModel(
                self._size,
                device=self._device,
                compute_type=self._compute_type,
                download_root=MODELS_DIR,
            )
            self.ready.emit(model, self._size)
        except Exception as e:
            self.error.emit(str(e))


# ── Transcription thread ──────────────────────────────────────────────────────

class TranscriptionThread(QThread):
    segment_ready = pyqtSignal(object)
    progress      = pyqtSignal(int)
    finished      = pyqtSignal(list, str)
    error         = pyqtSignal(str)

    def __init__(self, model: WhisperModel, audio_path: str, language: str | None = None):
        super().__init__()
        self.model      = model
        self.audio_path = audio_path
        self.language   = language

    def run(self):
        try:
            segs_gen, info = self.model.transcribe(
                self.audio_path,
                beam_size=5,
                language=self.language,
                task="transcribe",
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
                word_timestamps=True,
            )
            lang     = info.language
            duration = info.duration
            segments = []

            for seg in segs_gen:
                s = TranscriptSegment(
                    start=seg.start, end=seg.end,
                    text=seg.text.strip(), language=lang,
                )
                segments.append(s)
                self.segment_ready.emit(s)
                if duration > 0:
                    self.progress.emit(min(int(seg.end / duration * 100), 99))

            self.progress.emit(100)
            self.finished.emit(segments, lang)
        except Exception as e:
            self.error.emit(str(e))


# ── Public engine ─────────────────────────────────────────────────────────────

class TranscriptionEngine(QObject):
    model_loading = pyqtSignal(str)    # model size being loaded
    model_loaded  = pyqtSignal(str)    # model size ready
    model_error   = pyqtSignal(str)
    segment_ready = pyqtSignal(object)
    progress      = pyqtSignal(int)
    finished      = pyqtSignal(list, str)
    error         = pyqtSignal(str)

    def __init__(self, model_size: str = 'small', device: str = 'auto'):
        super().__init__()
        self._model:       WhisperModel | None = None
        self._model_size   = model_size
        self._device, self._compute_type = self._resolve(device)
        self._load_thread: ModelLoadThread | None = None
        self._tx_thread:   TranscriptionThread | None = None

    def _resolve(self, device: str) -> tuple[str, str]:
        if device != 'auto':
            return device, 'int8'
        try:
            import torch
            if torch.backends.mps.is_available():
                return 'cpu', 'int8'
            if torch.cuda.is_available():
                return 'cuda', 'float16'
        except ImportError:
            pass
        return 'cpu', 'int8'

    # ── Loading ───────────────────────────────────────────────────────────────

    def load_model_async(self, size: str | None = None):
        """Load Whisper model in background thread. Emits model_loaded when done."""
        target = size or self._model_size
        if self._model and self._model_size == target:
            self.model_loaded.emit(target)
            return
        if self._load_thread and self._load_thread.isRunning():
            return
        self._model_size = target
        self.model_loading.emit(target)
        self._load_thread = ModelLoadThread(target, self._device, self._compute_type)
        self._load_thread.ready.connect(self._on_model_ready)
        self._load_thread.error.connect(self.model_error)
        self._load_thread.start()

    def _on_model_ready(self, model: WhisperModel, size: str):
        self._model      = model
        self._model_size = size
        self.model_loaded.emit(size)

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def model_size(self) -> str:
        return self._model_size

    # ── Transcription ─────────────────────────────────────────────────────────

    def transcribe(self, audio_path: str, language: str | None = None):
        if not self._model:
            self.error.emit("模型尚未載入")
            return
        if self._tx_thread and self._tx_thread.isRunning():
            return
        self._tx_thread = TranscriptionThread(self._model, audio_path, language)
        self._tx_thread.segment_ready.connect(self.segment_ready)
        self._tx_thread.progress.connect(self.progress)
        self._tx_thread.finished.connect(self.finished)
        self._tx_thread.error.connect(self.error)
        self._tx_thread.start()

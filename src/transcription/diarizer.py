"""
Speaker diarization - identifies who said what.

Backend options (選擇其一):
  1. simple-diarizer  ← 預設，完全本地，不需要任何 token
  2. pyannote.audio   ← 高精度，需一次性 HuggingFace token 下載模型
"""
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Backend 1: simple-diarizer（完全本地，無需 token）
# ─────────────────────────────────────────────────────────────────────────────

class SimpleDiarizationThread(QThread):
    finished = pyqtSignal(list)   # [(start, end, speaker_label), ...]
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, audio_path: str, num_speakers: Optional[int], embed_model: str):
        super().__init__()
        self.audio_path = audio_path
        self.num_speakers = num_speakers
        self.embed_model = embed_model   # 'ecapa' or 'xvec'

    def run(self):
        try:
            from simple_diarizer.diarizer import Diarizer

            self.progress.emit("初始化說話人辨識...")
            diar = Diarizer(
                embed_model=self.embed_model,   # ecapa = 更準確, xvec = 更快
                cluster_method='sc',            # spectral clustering
            )

            self.progress.emit("分析音訊中...")
            kwargs = {}
            if self.num_speakers and self.num_speakers > 0:
                kwargs['num_speakers'] = self.num_speakers
            else:
                # 自動偵測說話人數
                kwargs['threshold'] = 0.8

            raw_segments = diar.diarize(self.audio_path, **kwargs)

            # Convert to unified format: (start, end, speaker_label)
            segments = [
                (seg['start'], seg['end'], f"SPEAKER_{seg['label']:02d}")
                for seg in raw_segments
            ]
            self.finished.emit(segments)

        except ImportError:
            self.error.emit(
                "請安裝 simple-diarizer：\npip install simple-diarizer"
            )
        except Exception as e:
            self.error.emit(f"說話人辨識失敗：{e}")


# ─────────────────────────────────────────────────────────────────────────────
# Backend 2: pyannote.audio（高精度，需一次性 HF token 下載模型）
# ─────────────────────────────────────────────────────────────────────────────

class PyannoteDiarizationThread(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, audio_path: str, pipeline, num_speakers: Optional[int]):
        super().__init__()
        self.audio_path = audio_path
        self.pipeline = pipeline
        self.num_speakers = num_speakers

    def run(self):
        try:
            self.progress.emit("執行 pyannote 說話人辨識...")
            kwargs = {}
            if self.num_speakers and self.num_speakers > 0:
                kwargs['num_speakers'] = self.num_speakers

            diarization = self.pipeline(self.audio_path, **kwargs)
            segments = [
                (turn.start, turn.end, speaker)
                for turn, _, speaker in diarization.itertracks(yield_label=True)
            ]
            self.finished.emit(segments)
        except Exception as e:
            self.error.emit(f"pyannote 辨識失敗：{e}")


# ─────────────────────────────────────────────────────────────────────────────
# 統一控制器
# ─────────────────────────────────────────────────────────────────────────────

class SpeakerDiarizer(QObject):
    """
    Speaker diarization controller.
    預設使用 simple-diarizer（本地，無需 token）。
    如提供 HF token 則使用 pyannote（更高精度）。
    """
    ready = pyqtSignal()
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    BACKENDS = {
        'simple': '本地辨識（無需 token）',
        'pyannote': '高精度（需 HuggingFace token）',
    }

    def __init__(self):
        super().__init__()
        self._backend = 'simple'
        self._embed_model = 'ecapa'   # 'ecapa'（準確）或 'xvec'（快）
        self._pyannote_pipeline = None
        self._thread: QThread | None = None

    # ── Backend selection ────────────────────────────────────────────────────

    def set_backend(self, backend: str):
        """'simple' or 'pyannote'"""
        self._backend = backend

    def set_embed_model(self, model: str):
        """'ecapa' or 'xvec' (simple-diarizer only)"""
        self._embed_model = model

    def load_pyannote(self, hf_token: str):
        """
        Download & cache pyannote pipeline (一次性，之後完全離線).
        """
        try:
            import torch
            from pyannote.audio import Pipeline
            self.progress.emit("下載 pyannote 模型（首次需要網路）...")
            self._pyannote_pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=hf_token,
            )
            # Move to best available device
            if torch.backends.mps.is_available():
                self._pyannote_pipeline.to(torch.device("mps"))
            elif torch.cuda.is_available():
                self._pyannote_pipeline.to(torch.device("cuda"))
            self._backend = 'pyannote'
            self.ready.emit()
        except Exception as e:
            self.error.emit(f"pyannote 載入失敗：{e}")

    @property
    def is_ready(self) -> bool:
        if self._backend == 'simple':
            try:
                import simple_diarizer  # noqa
                return True
            except ImportError:
                return False
        return self._pyannote_pipeline is not None

    # ── Diarization ──────────────────────────────────────────────────────────

    def diarize(self, audio_path: str, num_speakers: Optional[int] = None):
        """Run diarization in background thread."""
        if self._thread and self._thread.isRunning():
            return

        if self._backend == 'pyannote' and self._pyannote_pipeline:
            self._thread = PyannoteDiarizationThread(
                audio_path, self._pyannote_pipeline, num_speakers
            )
        else:
            self._thread = SimpleDiarizationThread(
                audio_path, num_speakers, self._embed_model
            )

        self._thread.finished.connect(self.finished)
        self._thread.error.connect(self.error)
        self._thread.progress.connect(self.progress)
        self._thread.start()


# ─────────────────────────────────────────────────────────────────────────────
# Merge helper
# ─────────────────────────────────────────────────────────────────────────────

def merge_transcript_with_diarization(
    transcript_segments: list,
    diarization_segments: list,
) -> list:
    """
    Assign speaker labels to Whisper segments by maximum time overlap
    with diarization segments.
    """
    for seg in transcript_segments:
        best_speaker = None
        best_overlap = 0.0

        for d_start, d_end, speaker in diarization_segments:
            overlap = max(0.0, min(seg.end, d_end) - max(seg.start, d_start))
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = speaker

        seg.speaker = best_speaker or "未知"

    return transcript_segments

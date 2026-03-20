"""
Real-time streaming transcription.

Processes the growing audio buffer in overlapping windows every N seconds.
Each run only emits segments that are new (past the last committed end time).
After recording stops, the caller should do a full final pass.
"""
import os
import time
import tempfile
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import soundfile as sf
from PyQt6.QtCore import QThread, pyqtSignal


STEP_SECS    = 3.0   # how often to process
OVERLAP_SECS = 1.5   # context overlap (helps Whisper accuracy at boundaries)
MIN_NEW_SECS = 1.5   # minimum new audio before we bother

# Whisper hallucination phrases (produced when there is silence / background noise)
_HALLUCINATIONS = {
    "thank you for watching",
    "thanks for watching",
    "please subscribe",
    "like and subscribe",
    "subtitles by",
    "subtitle by",
    "transcribed by",
    "www.",
    "http",
    "♪",
    "[music]",
    "(music)",
    "[applause]",
    "(applause)",
    "字幕",
    "翻譯",
    "訂閱",
    "謝謝收看",
    "感謝收看",
}


def _is_hallucination(text: str) -> bool:
    """Return True if this segment looks like a Whisper hallucination."""
    t = text.strip().lower()
    if not t:
        return True
    for h in _HALLUCINATIONS:
        if h in t:
            return True
    # Reject very short repeated segments (e.g. "." ".." "...")
    if len(t) <= 3 and all(c in ".。!！?？ " for c in t):
        return True
    return False


@dataclass
class LiveSegment:
    text:  str
    start: float
    end:   float
    final: bool = False   # True after the final full-audio pass


class StreamingTranscriber(QThread):
    """
    Runs in a background thread while recording.
    Calls get_buffer() every STEP_SECS, transcribes the new portion,
    and emits new_segment for each new piece of text.
    """
    new_segment      = pyqtSignal(object)   # LiveSegment
    language_detected = pyqtSignal(str)

    def __init__(self, model, get_buffer: Callable, language: str | None = None):
        super().__init__()
        self.model      = model
        self.get_buffer = get_buffer
        self._running   = False
        self._last_end  = 0.0
        self._forced_language = language   # None = auto-detect every window
        self._language  = None             # first confirmed detection

    def begin(self, language: str | None = None):
        self._running         = True
        self._last_end        = 0.0
        self._language        = None
        self._forced_language = language
        self.start()

    def halt(self):
        self._running = False

    def run(self):
        while self._running:
            time.sleep(STEP_SECS)
            if not self._running:
                break
            self._process_window()

    def _process_window(self):
        audio, sr = self.get_buffer()
        if audio is None:
            return

        total_dur    = len(audio) / sr
        window_start = max(0.0, self._last_end - OVERLAP_SECS)
        new_dur      = total_dur - self._last_end

        if new_dur < MIN_NEW_SECS:
            return

        start_sample = int(window_start * sr)
        chunk = audio[start_sample:]

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".wav")
        os.close(tmp_fd)
        try:
            sf.write(tmp_path, chunk, sr)

            # Use forced language if set; otherwise auto-detect every window
            # (don't lock in auto-detected language — short windows are unreliable)
            lang = self._forced_language

            segs_gen, info = self.model.transcribe(
                tmp_path,
                beam_size=2,            # fast mode for real-time
                language=lang,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=400),
                word_timestamps=False,
            )

            if self._language is None:
                self._language = info.language
                self.language_detected.emit(info.language)

            for seg in segs_gen:
                abs_start = window_start + seg.start
                abs_end   = window_start + seg.end

                # Only emit genuinely new, non-hallucinated content
                text = seg.text.strip()
                if (abs_start >= self._last_end - 0.2
                        and text
                        and not _is_hallucination(text)):
                    self.new_segment.emit(
                        LiveSegment(text=text, start=abs_start, end=abs_end)
                    )
                    self._last_end = abs_end

        except Exception as e:
            print(f"[StreamingTranscriber] error: {e}")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

"""
Audio recorder - microphone + system audio (WASAPI loopback on Windows,
BlackHole/Soundflower on macOS).
"""
import sys
import threading
import queue
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
import sounddevice as sd
import soundfile as sf
from PyQt6.QtCore import QObject, pyqtSignal, QThread

SAMPLE_RATE = 16000
CHANNELS    = 1
CHUNK_SECS  = 0.1

# Virtual audio driver names that indicate system audio capability (macOS/Linux)
_SYSTEM_AUDIO_NAMES = [
    "blackhole", "soundflower", "loopback", "vb-cable",
    "cable output", "virtual", "stereo mix", "what u hear",
    "background music",
]


def _is_system_device(name: str) -> bool:
    n = name.lower()
    return any(k in n for k in _SYSTEM_AUDIO_NAMES)


def _resample(audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr:
        return audio
    from scipy.signal import resample_poly
    import math
    g = math.gcd(src_sr, dst_sr)
    return resample_poly(audio, dst_sr // g, src_sr // g).astype(np.float32)


# ── Standard sounddevice recorder thread ─────────────────────────────────────

class _SDRecorderThread(QThread):
    level_updated = pyqtSignal(float)
    error_occurred = pyqtSignal(str)

    def __init__(self, output_path: str, device_index=None):
        super().__init__()
        self.output_path  = output_path
        self.device_index = device_index
        self._stop        = threading.Event()
        self._queue: queue.Queue = queue.Queue()
        self._frames: list[np.ndarray] = []
        self._lock        = threading.Lock()

    def get_buffer(self) -> tuple[np.ndarray | None, int]:
        with self._lock:
            if not self._frames:
                return None, SAMPLE_RATE
            return np.concatenate(self._frames, axis=0).copy(), SAMPLE_RATE

    def stop(self):
        self._stop.set()
        self.wait()

    def _detect_channels(self) -> int:
        """Return the number of input channels to use for this device."""
        try:
            info = sd.query_devices(self.device_index)
            native = int(info["max_input_channels"])
            return max(1, min(CHANNELS, native))
        except Exception:
            return CHANNELS

    def run(self):
        chunk    = int(SAMPLE_RATE * CHUNK_SECS)
        channels = self._detect_channels()
        _silent_chunks = 0   # count consecutive near-zero chunks

        def cb(indata, frames, t, status):
            nonlocal _silent_chunks
            data = indata.mean(axis=1, keepdims=True) if indata.shape[1] > 1 else indata.copy()
            rms  = float(np.sqrt(np.mean(data ** 2)))
            self._queue.put(data)
            self.level_updated.emit(rms)
            # If we get many consecutive silent chunks early in recording, warn once
            if rms < 1e-6:
                _silent_chunks += 1
                if _silent_chunks == 30:   # ~3 seconds of silence → likely permission issue
                    self.error_occurred.emit(
                        "沒有偵測到麥克風聲音。\n\n"
                        "可能原因：\n"
                        "1. macOS 未授予麥克風權限\n"
                        "   → 系統設定 → 隱私與安全 → 麥克風 → 允許 Terminal（或 Python）\n"
                        "2. 選擇了錯誤的音訊裝置\n"
                        "   → 在「音訊來源」選擇「MacBook Air的麥克風」或你的麥克風\n\n"
                        "授權後請重新啟動應用程式。"
                    )
            else:
                _silent_chunks = 0

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE, channels=channels, dtype="float32",
                blocksize=chunk, device=self.device_index, callback=cb,
            ):
                while not self._stop.is_set():
                    try:
                        chunk_data = self._queue.get(timeout=0.5)
                        with self._lock:
                            self._frames.append(chunk_data)
                    except queue.Empty:
                        continue
        except Exception as e:
            print(f"[Recorder] error: {e}")
            self.error_occurred.emit(f"錄音裝置開啟失敗：{e}")

        with self._lock:
            audio = np.concatenate(self._frames, axis=0) if self._frames else None
        if audio is not None:
            sf.write(self.output_path, audio, SAMPLE_RATE)


# ── Windows WASAPI loopback recorder thread ───────────────────────────────────

class _WASAPILoopbackThread(QThread):
    level_updated = pyqtSignal(float)

    def __init__(self, output_path: str, wasapi_device_index: int):
        super().__init__()
        self.output_path   = output_path
        self.wasapi_index  = wasapi_device_index
        self._stop         = threading.Event()
        self._frames: list[np.ndarray] = []
        self._lock         = threading.Lock()

    def get_buffer(self) -> tuple[np.ndarray | None, int]:
        with self._lock:
            if not self._frames:
                return None, SAMPLE_RATE
            return np.concatenate(self._frames, axis=0).copy(), SAMPLE_RATE

    def stop(self):
        self._stop.set()
        self.wait()

    def run(self):
        try:
            import pyaudiowpatch as pyaudio  # Windows only
        except ImportError:
            print("請安裝 pyaudiowpatch: pip install pyaudiowpatch")
            return

        pa = pyaudio.PyAudio()
        try:
            dev    = pa.get_device_info_by_index(self.wasapi_index)
            src_sr = int(dev["defaultSampleRate"])
            chs    = dev["maxInputChannels"]
            chunk  = int(src_sr * CHUNK_SECS)

            def cb(data, frame_count, time_info, status):
                arr = np.frombuffer(data, dtype=np.float32).reshape(-1, chs)
                if chs > 1:
                    arr = arr.mean(axis=1, keepdims=True)
                arr = _resample(arr.flatten(), src_sr, SAMPLE_RATE).reshape(-1, 1)
                with self._lock:
                    self._frames.append(arr)
                self.level_updated.emit(float(np.sqrt(np.mean(arr ** 2))))
                return (data, pyaudio.paContinue)

            stream = pa.open(
                format=pyaudio.paFloat32,
                channels=chs,
                rate=src_sr,
                input=True,
                input_device_index=self.wasapi_index,
                stream_callback=cb,
                frames_per_buffer=chunk,
            )
            stream.start_stream()
            while not self._stop.is_set():
                time.sleep(0.05)
            stream.stop_stream()
            stream.close()
        finally:
            pa.terminate()

        with self._lock:
            audio = np.concatenate(self._frames, axis=0) if self._frames else None
        if audio is not None:
            sf.write(self.output_path, audio, SAMPLE_RATE)


# ── ScreenCaptureKit recorder thread (macOS) ──────────────────────────────────

class _SCKRecorderThread(QThread):
    """Wraps SCKCapture so it fits the same QThread interface used by _SDRecorderThread."""
    level_updated  = pyqtSignal(float)
    error_occurred = pyqtSignal(str)

    def __init__(self, output_path: str):
        super().__init__()
        self.output_path = output_path
        self._stop       = threading.Event()
        self._capture    = None

    def get_buffer(self) -> tuple[np.ndarray | None, int]:
        if self._capture:
            return self._capture.get_buffer()
        return None, SAMPLE_RATE

    def stop(self):
        self._stop.set()
        self.wait()

    def run(self):
        try:
            from .system_audio import SCKCapture
        except ImportError:
            self.error_occurred.emit("ScreenCaptureKit 不可用，請確認 macOS 版本 ≥ 12.3")
            return

        self._capture = SCKCapture()
        try:
            self._capture.start()
        except Exception as e:
            self.error_occurred.emit(f"SCKCapture 啟動失敗：{e}")
            return

        # Poll buffer for level updates until stopped
        last_len = 0
        while not self._stop.is_set():
            time.sleep(0.1)
            audio, sr = self._capture.get_buffer()
            if audio is not None and len(audio) > last_len:
                new = audio[last_len:]
                rms = float(np.sqrt(np.mean(new ** 2)))
                self.level_updated.emit(rms)
                last_len = len(audio)

        self._capture.stop()

        audio, sr = self._capture.get_buffer()
        if audio is not None and len(audio) > 0:
            sf.write(self.output_path, audio, sr)


# ── Public AudioRecorder ──────────────────────────────────────────────────────

class AudioRecorder(QObject):
    recording_started = pyqtSignal(str)
    recording_stopped = pyqtSignal(str)
    level_updated     = pyqtSignal(float)
    error_occurred    = pyqtSignal(str)

    def __init__(self, recordings_dir: str):
        super().__init__()
        self.recordings_dir = Path(recordings_dir)
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        self._thread: _SDRecorderThread | _WASAPILoopbackThread | None = None
        self._current_path: str | None = None

    # ── Device enumeration ────────────────────────────────────────────────────

    def get_devices(self) -> list[dict]:
        """
        Returns all available audio input devices.
        Type field: 'mic' | 'system' | 'wasapi_loopback'
        """
        devices = []

        # sounddevice devices (works on all platforms)
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] < 1:
                continue
            is_sys = _is_system_device(d["name"])
            devices.append({
                "index":   i,
                "name":    d["name"],
                "label":   f"[系統聲音] {d['name']}" if is_sys else d["name"],
                "type":    "system" if is_sys else "mic",
                "backend": "sounddevice",
            })

        # Windows: WASAPI loopback devices (records what the speakers play)
        if sys.platform == "win32":
            devices.extend(_enum_wasapi_loopback())

        return devices

    @staticmethod
    def has_system_audio_support() -> tuple[bool, str]:
        """
        Returns (available, guide_message).
        available=True if at least one system audio device is found.
        """
        if sys.platform == "win32":
            loopback = _enum_wasapi_loopback()
            if loopback:
                return True, ""
            return False, (
                "請安裝 pyaudiowpatch 以啟用 Windows 系統聲音擷取：\n"
                "pip install pyaudiowpatch"
            )

        if sys.platform == "darwin":
            # Check if BlackHole or Soundflower is installed
            for d in sd.query_devices():
                if _is_system_device(d["name"]) and d["max_input_channels"] > 0:
                    return True, ""
            # Fall back: ScreenCaptureKit is available on macOS 12.3+
            try:
                import ScreenCaptureKit  # noqa: F401
                return True, ""
            except ImportError:
                pass
            return False, (
                "macOS 需要安裝虛擬音訊驅動才能擷取系統聲音。\n\n"
                "推薦方案（免費）：BlackHole\n"
                "1. 前往 https://existential.audio/blackhole/ 下載安裝\n"
                "2. 打開「Audio MIDI 設定」→ 建立「多重輸出裝置」\n"
                "   → 勾選 BlackHole 和您的喇叭\n"
                "3. 在系統音效輸出中選擇剛建立的「多重輸出裝置」\n"
                "4. 重新啟動本應用，在麥克風選單選擇 BlackHole"
            )

        return False, "目前的系統不支援系統聲音擷取"

    # ── Buffer access ─────────────────────────────────────────────────────────

    def get_buffer(self) -> tuple[np.ndarray | None, int]:
        if self._thread:
            return self._thread.get_buffer()
        return None, SAMPLE_RATE

    # ── Start / Stop ──────────────────────────────────────────────────────────

    def start(self, device: dict | None) -> str:
        if self._thread and self._thread.isRunning():
            return self._current_path

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._current_path = str(self.recordings_dir / f"rec_{ts}.wav")

        if device and device.get("backend") == "wasapi_loopback":
            self._thread = _WASAPILoopbackThread(
                self._current_path, device["wasapi_index"]
            )
        elif device and device.get("backend") == "sck":
            self._thread = _SCKRecorderThread(self._current_path)
        else:
            idx = device["index"] if device else None
            self._thread = _SDRecorderThread(self._current_path, idx)

        self._thread.level_updated.connect(self.level_updated)
        if hasattr(self._thread, "error_occurred"):
            self._thread.error_occurred.connect(self.error_occurred)
        self._thread.start()
        self.recording_started.emit(self._current_path)
        return self._current_path

    def stop(self) -> str | None:
        if not self._thread or not self._thread.isRunning():
            return None
        self._thread.stop()
        path = self._current_path
        self._thread = None
        self.recording_stopped.emit(path)
        return path

    @property
    def is_recording(self) -> bool:
        return self._thread is not None and self._thread.isRunning()


# ── WASAPI loopback enumeration (Windows) ─────────────────────────────────────

def _enum_wasapi_loopback() -> list[dict]:
    result = []
    try:
        import pyaudiowpatch as pyaudio
        pa = pyaudio.PyAudio()
        try:
            pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            for i in range(pa.get_device_count()):
                d = pa.get_device_info_by_index(i)
                if d.get("isLoopbackDevice", False):
                    result.append({
                        "index":        None,
                        "name":         d["name"],
                        "label":        f"[系統聲音] {d['name']}",
                        "type":         "wasapi_loopback",
                        "backend":      "wasapi_loopback",
                        "wasapi_index": i,
                    })
        finally:
            pa.terminate()
    except (ImportError, OSError):
        pass
    return result

"""
System audio capture helpers.

On macOS 12.3+, system audio is captured via ScreenCaptureKit — no extra
driver needed (requires Screen Recording permission in System Settings).

On older macOS or if SCK is unavailable, the user needs a virtual audio
driver like BlackHole (free).

On Windows, WASAPI loopback in recorder.py handles this natively.
"""
import sys
import threading
import time
from typing import Optional

import numpy as np
import sounddevice as sd


_VIRTUAL_DRIVER_NAMES = [
    "blackhole", "soundflower", "loopback", "vb-cable",
    "cable output", "virtual", "stereo mix", "what u hear",
    "background music",
]


def _is_virtual_driver(name: str) -> bool:
    n = name.lower()
    return any(k in n for k in _VIRTUAL_DRIVER_NAMES)


def find_system_audio_device() -> Optional[dict]:
    """Return the first virtual-driver device dict, or None."""
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and _is_virtual_driver(d["name"]):
            name = d["name"]
            return {
                "index":   i,
                "name":    name,
                "label":   f"[系統聲音] {name}",
                "type":    "system",
                "backend": "sounddevice",
            }
    return None


def _sck_available() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        import ScreenCaptureKit  # noqa: F401
        return True
    except ImportError:
        return False


def is_available() -> bool:
    return find_system_audio_device() is not None or _sck_available()


def get_sck_device() -> Optional[dict]:
    """Return a pseudo-device dict for ScreenCaptureKit, or None."""
    if not _sck_available():
        return None
    return {
        "index":   None,
        "name":    "ScreenCaptureKit",
        "label":   "[系統聲音] 電腦音訊 (ScreenCaptureKit)",
        "type":    "system",
        "backend": "sck",
    }


# ── Resample helper ───────────────────────────────────────────────────────────

def _resample(audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr:
        return audio
    from scipy.signal import resample_poly
    import math
    g = math.gcd(src_sr, dst_sr)
    return resample_poly(audio, dst_sr // g, src_sr // g).astype(np.float32)


# ── ScreenCaptureKit capture ──────────────────────────────────────────────────

class SCKCapture:
    """
    Captures macOS system audio via ScreenCaptureKit.

    Runs on its own daemon thread.  Call start() / stop(); get_buffer()
    returns (ndarray[N,1] float32, 16000) at any time.

    Requires: macOS 12.3+, Screen Recording permission granted.
    """

    # SCK only supports 44100 / 48000 — NOT 16000; resample after capture
    SCK_SR    = 44100
    TARGET_SR = 16000
    CHANNELS  = 2   # stereo capture; mixed to mono when storing

    def __init__(self):
        self._frames: list[np.ndarray] = []
        self._lock     = threading.Lock()
        self._stop_evt = threading.Event()
        self._thread:  Optional[threading.Thread] = None

    # ── Public ────────────────────────────────────────────────────────────────

    def start(self):
        self._frames.clear()
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="SCKCapture")
        self._thread.start()

    def stop(self):
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=8)

    def get_buffer(self) -> tuple[Optional[np.ndarray], int]:
        with self._lock:
            if not self._frames:
                return None, self.TARGET_SR
            return np.concatenate(self._frames, axis=0).copy(), self.TARGET_SR

    # ── Internal ──────────────────────────────────────────────────────────────

    def _append_sample_buffer(self, sbuf):
        """
        Extract float32 PCM from a CMSampleBuffer and append to _frames.
        Called from the Objective-C delegate on an arbitrary thread.
        """
        try:
            import objc
            from CoreMedia import (
                CMSampleBufferGetDataBuffer,
                CMBlockBufferGetDataLength,
            )

            block_buf = CMSampleBufferGetDataBuffer(sbuf)
            if block_buf is None:
                return
            length = CMBlockBufferGetDataLength(block_buf)
            if length == 0:
                return

            # Allocate a Python buffer and copy bytes from the CMBlockBuffer
            buf = objc.allocateBuffer(length)
            try:
                from CoreMedia import CMBlockBufferCopyDataBytes
                status = CMBlockBufferCopyDataBytes(block_buf, 0, length, buf)
                if status != 0:
                    return
            except (ImportError, AttributeError):
                # CMBlockBufferCopyDataBytes not available in this PyObjC version
                # Fall back to ctypes-based GetDataPointer
                try:
                    from CoreMedia import CMBlockBufferGetDataPointer
                    import ctypes
                    # Returns (OSStatus, lengthAtOffset, totalLength, dataPointer)
                    result = CMBlockBufferGetDataPointer(block_buf, 0, None, None, None)
                    # Different PyObjC versions return different tuple layouts
                    if isinstance(result, tuple):
                        # Find the pointer — it will be a non-zero integer
                        data_ptr = None
                        for val in result:
                            if isinstance(val, int) and val > 0x1000:
                                data_ptr = val
                                break
                        if data_ptr is None:
                            return
                        raw = (ctypes.c_byte * length).from_address(data_ptr)
                        buf = bytes(raw)
                    else:
                        return
                except Exception:
                    return

            arr = np.frombuffer(bytes(buf), dtype=np.float32).copy()
            chs = self.CHANNELS
            # Interleaved stereo → mono (N, 1)
            if arr.size >= chs and arr.size % chs == 0:
                arr = arr.reshape(-1, chs).mean(axis=1)
            # Resample to TARGET_SR
            arr = _resample(arr, self.SCK_SR, self.TARGET_SR).reshape(-1, 1)

            with self._lock:
                self._frames.append(arr)

        except Exception as ex:
            print(f"[SCKCapture] audio callback error: {ex}")

    def _run(self):
        try:
            import ScreenCaptureKit as SCK
            import objc
            from Foundation import NSRunLoop, NSDate
        except ImportError as e:
            print(f"[SCKCapture] import error: {e}")
            return

        # ── Build combined delegate (SCStreamOutput + SCStreamDelegate) ───────
        try:
            out_proto = objc.protocolNamed("SCStreamOutput")
            del_proto = objc.protocolNamed("SCStreamDelegate")
        except Exception as e:
            print(f"[SCKCapture] protocol lookup failed: {e}")
            return

        capture_self = self   # closure reference

        class _Delegate(
            objc.lookUpClass("NSObject"),
            protocols=[out_proto, del_proto],
        ):
            def stream_didOutputSampleBuffer_ofType_(self_d, stream, sbuf, out_type):
                if out_type == 1:   # SCStreamOutputTypeAudio = 1
                    capture_self._append_sample_buffer(sbuf)

            def stream_didStopWithError_(self_d, stream, error):
                if error:
                    print(f"[SCKCapture] stream stopped with error: {error}")

        delegate = _Delegate.alloc().init()

        rl = NSRunLoop.currentRunLoop()

        # ── Fetch shareable content (needed for SCContentFilter) ──────────────
        content_evt = threading.Event()
        content_res: list = [None, None]   # [content, error]

        def _content_cb(content, error):
            content_res[0] = content
            content_res[1] = error
            content_evt.set()

        SCK.SCShareableContent.getShareableContentWithCompletionHandler_(_content_cb)

        deadline = time.time() + 5.0
        while not content_evt.is_set() and time.time() < deadline:
            rl.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))

        if not content_evt.is_set() or content_res[1]:
            print(f"[SCKCapture] getShareableContent failed: {content_res[1]}")
            return

        content = content_res[0]
        if content is None:
            print("[SCKCapture] no shareable content returned")
            return

        displays = content.displays()
        if not displays or len(displays) == 0:
            print("[SCKCapture] no displays found")
            return
        display = displays[0]

        # ── SCContentFilter ───────────────────────────────────────────────────
        try:
            content_filter = (
                SCK.SCContentFilter.alloc()
                .initWithDisplay_excludingWindows_(display, [])
            )
        except Exception as e:
            print(f"[SCKCapture] SCContentFilter init error: {e}")
            return

        # ── SCStreamConfiguration ─────────────────────────────────────────────
        cfg = SCK.SCStreamConfiguration.alloc().init()
        cfg.setCapturesAudio_(True)
        cfg.setSampleRate_(self.SCK_SR)
        cfg.setChannelCount_(self.CHANNELS)
        try:
            cfg.setExcludesCurrentProcessAudio_(False)
        except AttributeError:
            pass   # not available on older SDKs

        # ── Create SCStream ───────────────────────────────────────────────────
        try:
            stream = SCK.SCStream.alloc().initWithFilter_configuration_delegate_(
                content_filter, cfg, delegate
            )
        except Exception as e:
            print(f"[SCKCapture] SCStream init error: {e}")
            return

        # ── Add audio output ──────────────────────────────────────────────────
        try:
            ok = stream.addStreamOutput_type_sampleHandlerQueue_error_(
                delegate,
                1,      # SCStreamOutputTypeAudio
                None,   # use default queue
                None,   # no error pointer needed (check return value)
            )
            if not ok:
                print("[SCKCapture] addStreamOutput returned False")
                return
        except Exception as e:
            print(f"[SCKCapture] addStreamOutput error: {e}")
            return

        # ── Start capture ─────────────────────────────────────────────────────
        started_evt = threading.Event()
        start_err: list = [None]

        def _start_cb(error):
            start_err[0] = error
            started_evt.set()

        stream.startCaptureWithCompletionHandler_(_start_cb)

        deadline = time.time() + 5.0
        while not started_evt.is_set() and time.time() < deadline:
            rl.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))

        if not started_evt.is_set():
            print("[SCKCapture] startCapture timed out")
            return
        if start_err[0]:
            print(f"[SCKCapture] startCapture error: {start_err[0]}")
            return

        print("[SCKCapture] capture started successfully")

        # ── Keep RunLoop alive while recording ────────────────────────────────
        while not self._stop_evt.is_set():
            rl.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))

        # ── Stop capture ──────────────────────────────────────────────────────
        stop_evt = threading.Event()
        stream.stopCaptureWithCompletionHandler_(lambda e: stop_evt.set())

        deadline = time.time() + 5.0
        while not stop_evt.is_set() and time.time() < deadline:
            rl.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))

        print("[SCKCapture] capture stopped")


# ── Guide text ────────────────────────────────────────────────────────────────

BLACKHOLE_GUIDE = """\
若要錄製電腦聲音，您有兩個選擇：

【方法一】使用 ScreenCaptureKit（macOS 12.3+，免安裝）
1. 前往「系統設定 → 隱私與安全 → 螢幕錄製」
2. 允許 Terminal（或本應用程式）
3. 重新啟動本應用程式
4. 點擊「電腦聲音」按鈕即可

【方法二】安裝免費虛擬音訊驅動 BlackHole
1. 前往 https://existential.audio/blackhole/ 下載 BlackHole 2ch
2. 執行安裝程式（不需重開機）
3. 重新啟動本應用程式
4. 在「音訊來源」選單選擇 [系統聲音] BlackHole 2ch

說明：方法一更簡便；方法二在舊版 macOS 更穩定。
"""

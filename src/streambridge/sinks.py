"""Outputs: virtual camera and audio sinks (real and fake for tests)."""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading

import numpy as np

log = logging.getLogger("streambridge")


class CameraSink:
    """pyvirtualcam camera fed NV12 (the OBS camera's native format; no RGB round trip). backend: 'obs' (Windows/macOS), 'v4l2loopback' (Linux) or None."""

    def __init__(self, width: int, height: int, fps: float, backend: str | None = None, device: str | None = None):
        import pyvirtualcam  # imported here so audio-only use works without it
        kw = {}
        if backend:
            kw["backend"] = backend
        if device:
            kw["device"] = device
        self.cam = pyvirtualcam.Camera(width=width, height=height, fps=fps, fmt=pyvirtualcam.PixelFormat.NV12, **kw)
        self.width, self.height, self.fps = width, height, fps
        self.device = self.cam.device

    def send(self, nv12: np.ndarray) -> None:
        self.cam.send(nv12)

    def close(self) -> None:
        try:
            self.cam.close()
        except Exception as e:  # pragma: no cover  (driver boundary; closing must never raise)
            log.debug("camera: close failed: %s", e)


class FakeCameraSink:
    instances: list["FakeCameraSink"] = []

    def __init__(self, width: int, height: int, fps: float, backend=None, device=None):
        self.width, self.height, self.fps, self.device = width, height, fps, "fake-camera"
        self.frames = 0
        self.last: np.ndarray | None = None
        self.closed = False
        FakeCameraSink.instances.append(self)

    def send(self, nv12: np.ndarray) -> None:
        assert nv12.shape == (self.height * 3 // 2, self.width) and nv12.dtype == np.uint8, nv12.shape
        self.frames += 1
        self.last = nv12.copy()

    def close(self) -> None:
        self.closed = True


class AudioSink:
    """Pull-style audio output: start(pull) and the device asks for audio on its own clock.

    pull(n) -> float32 (n, channels). The sink never blocks the decoder, so delay can't build up.
    """
    rate: int = 48000
    channels: int = 2
    name: str = ""
    latency_ms: float = 0.0      # device-side latency reported by the backend

    def start(self, pull) -> None: ...
    def close(self) -> None: ...


class _Pacer:
    """Calls pull() in small blocks on a real-time clock (for sinks without a callback API)."""

    def __init__(self, rate: int, block: int, pull, write, lead_s: float = 0.0):
        self.rate, self.block, self.pull, self.write, self.lead = rate, block, pull, write, lead_s
        self.stop = threading.Event()
        self.th = threading.Thread(target=self._run, name="sb-audio-out", daemon=True)
        self.th.start()

    def _run(self) -> None:
        import time
        t0 = time.monotonic()
        done = 0
        while not self.stop.is_set():
            self.write(self.pull(self.block))
            done += self.block
            d = t0 + done / self.rate - self.lead - time.monotonic()
            if d > 0:
                time.sleep(d)
            elif d < -0.2:                      # we were suspended: resync, don't burst
                t0, done = time.monotonic(), 0


class SoundDeviceSink(AudioSink):
    """Plays into a named output device (e.g. 'CABLE Input', 'BlackHole 2ch') via a PortAudio callback.

    Robust open: Windows uses the WASAPI device, with MME as the one fallback if WASAPI
    won't open (macOS: Core Audio). Opened with exactly the device's own
    default sample rate and <= 2 channels, blocksize 0 (driver chooses) and latency 'low'
    (WASAPI shared mode with auto-convert). The stream must actually become active, otherwise
    the next host API is tried. What was used is logged.
    """

    def __init__(self, device_match: str, latency: float | str = "low", hostapis: tuple[str, ...] | None = None):
        import sounddevice as sd
        self._sd = sd
        self.match, self.latency = device_match, latency
        if hostapis:   # e.g. ("MME",): PortAudio only as the Windows last fallback
            m = device_match.lower()
            devs = [d for d in _all_output_devices() if d["hostapi_name"] in hostapis]
            best = next((d for t in (lambda n: n == m, lambda n: n.startswith(m) or m.startswith(n), lambda n: m in n)
                         for d in devs if t(d["name"].lower())), None)
            if best is None:
                raise RuntimeError(f"Audio device '{device_match}' not found ({', '.join(hostapis)})")
            self.candidates = [best]
            self.stream = None
            self.warning = ""
            self.errors = 0
            self.last_error = ""
            self._use(best)
            return
        _, best = find_output_device(device_match)
        if best is None:
            raise RuntimeError(f"Audio device '{device_match}' not found")
        self.candidates = [best]
        if best["hostapi_name"] == "Windows WASAPI":     # one fallback: MME, only if WASAPI won't open
            twin = mme_twin(best["name"])
            if twin:
                self.candidates.append(twin)
        self._use(self.candidates[0])
        self.stream = None
        self.warning = ""
        self.errors = 0
        self.last_error = ""

    def _use(self, info: dict) -> None:
        self.info = info
        self.idx = info["index"]
        self.hostapi = info.get("hostapi_name", "")
        self.rate = int(round(info["default_samplerate"])) or 48000
        self.channels = 2 if int(info["max_output_channels"]) >= 2 else 1
        self.name = f"{info['name']} [{self.hostapi}]" if self.hostapi else info["name"]

    _open_streams: dict = {}     # device index -> sink, process-wide (never two streams on one device)

    def _open(self, pull):
        sd = self._sd
        # strict: the index must really be this host API's device
        apis = sd.query_hostapis()
        dev = sd.query_devices(self.idx)
        api_name = apis[dev["hostapi"]]["name"]
        if api_name != self.hostapi or dev["name"] != self.info["name"]:
            raise RuntimeError(f"device #{self.idx} is '{dev['name']}' on {api_name}, expected {self.hostapi}")
        other = SoundDeviceSink._open_streams.get(self.idx)
        if other is not None and other is not self:
            log.warning("audio output: closing an older stream still open on device #%d", self.idx)
            other.close()

        def cb(outdata, frames, _time, _status):
            try:
                outdata[:] = pull(frames)
            except Exception as e:  # never let the stream die silently
                outdata.fill(0)
                self.errors += 1
                self.last_error = repr(e)

        extra = None
        if "WASAPI" in self.hostapi and hasattr(sd, "WasapiSettings"):
            try:
                extra = sd.WasapiSettings(exclusive=False, auto_convert=True)
            except TypeError:       # older sounddevice without auto_convert
                extra = sd.WasapiSettings(exclusive=False)
        st = sd.OutputStream(device=self.idx, samplerate=self.rate, channels=self.channels, dtype="float32",
                             latency=self.latency, blocksize=0, callback=cb, extra_settings=extra)
        st.start()
        if not st.active:
            st.close()
            raise RuntimeError("stream did not start")
        return st

    def start(self, pull) -> None:
        import time
        self.close()                       # never two streams from one sink
        tried = []
        attempts = []
        for info in self.candidates:       # WASAPI twice (a just-closed stream may still be releasing), then MME
            attempts += [info, info] if info.get("hostapi_name") == "Windows WASAPI" else [info]
        for n, info in enumerate(attempts):
            self._use(info)
            try:
                self.stream = self._open(pull)
                SoundDeviceSink._open_streams[self.idx] = self
                break
            except Exception as e:
                if n + 1 < len(attempts) and attempts[n + 1] is info:
                    log.warning("audio output: %s busy or failed (%s); retrying once", self.name, e)
                    time.sleep(0.3)
                    continue
                tried.append(f"{self.name} {self.rate} Hz {self.channels} ch: {e}")
                log.warning("audio output: could not open %s (%s Hz, %s ch): %s; trying the next one",
                            self.name, self.rate, self.channels, e)
        if self.stream is None:
            raise RuntimeError("Could not open the audio output. Tried: " + " | ".join(tried))
        self.latency_ms = float(self.stream.latency) * 1000
        self.blocksize = self.stream.blocksize
        opened = self.stream.device
        api = self._sd.query_hostapis()[self._sd.query_devices(opened)["hostapi"]]["name"]
        self.hostapi = api
        self.warning = "Mic using the slower MME driver (~90 ms extra)" if api == "MME" else ""
        log.info("audio output: device #%s %s, host API %s, %d Hz, %d ch, float32, blocksize %s (0 = driver), "
                 "latency %.0f ms", opened, self.info["name"], api, self.rate, self.channels, self.blocksize,
                 self.latency_ms)

    def close(self) -> None:
        try:
            if self.stream:
                self.stream.stop(); self.stream.close()
        except Exception as e:  # PortAudio boundary; closing must never raise
            log.debug("audio output: close failed: %s", e)
        self.stream = None
        if SoundDeviceSink._open_streams.get(getattr(self, "idx", None)) is self:
            del SoundDeviceSink._open_streams[self.idx]


def _all_output_devices() -> list[dict]:
    """Output devices, built per host API from that host API's own device-index list
    (sd.query_hostapis()[i]['devices']), so an index can never belong to another host API."""
    try:
        import sounddevice as sd
        out = []
        for h in sd.query_hostapis():
            for idx in h.get("devices", []):
                d = sd.query_devices(idx)
                if d["max_output_channels"] > 0:
                    out.append(dict(d, index=idx, hostapi_name=h["name"]))
        return out
    except Exception as e:  # PortAudio missing/broken: no devices (callers show a hint)
        log.warning("audio output: cannot list devices: %s", e)
        return []


def list_output_devices() -> list[dict]:
    """Output devices of ONE host API: WASAPI on Windows (no MME duplicates or pseudo-devices),
    everything elsewhere (macOS has only Core Audio)."""
    devs = _all_output_devices()
    if any(d["hostapi_name"].startswith("Windows") or d["hostapi_name"] == "MME" for d in devs):
        # Windows: WASAPI shared mode only. Never WDM-KS (kernel streaming, exclusive; VB-CABLE fails
        # with "WdmSyncIoctl ... GLE = 0x00000492") and no MME/DirectSound duplicates.
        wasapi = [d for d in devs if d["hostapi_name"] == "Windows WASAPI"]
        return wasapi or [d for d in devs if d["hostapi_name"] == "MME"]
    return devs


def find_output_device(match: str):
    m = match.lower()
    devs = list_output_devices()
    for test in (lambda n: n == m, lambda n: n.startswith(m), lambda n: m in n):
        for d in devs:
            if test(d["name"].lower()):
                return d["index"], d
    return None, None


def mme_twin(name: str) -> dict | None:
    """Fallback only: the MME variant of a device (MME cuts names to 31 characters)."""
    for d in _all_output_devices():
        if d["hostapi_name"] == "MME" and name.startswith(d["name"]):
            return d
    return None


class PacatSink(AudioSink):
    """Linux: feed float32 PCM into a PipeWire/PulseAudio sink with pacat, paced in 5 ms blocks.

    We write on a real-time clock with ~20 ms lead, so the pipe and pacat's buffer stay tiny.
    """

    def __init__(self, sink_name: str, rate: int = 48000, channels: int = 2, latency_msec: int = 20):
        exe = shutil.which("pacat")
        if not exe:
            raise RuntimeError("pacat not found (install pulseaudio-utils / pipewire-pulse)")
        self.name, self.rate, self.channels = sink_name, rate, channels
        self.latency_ms = latency_msec
        self.proc = subprocess.Popen(
            [exe, "--playback", f"--device={sink_name}", "--format=float32le", f"--rate={rate}",
             f"--channels={channels}", f"--latency-msec={latency_msec}", "--client-name=StreamBridge",
             "--stream-name=StreamBridge Microphone"],
            stdin=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        self.pacer = None

    def _write(self, x: np.ndarray) -> None:
        if self.proc.poll() is not None:
            raise RuntimeError("audio output process ended")
        try:
            self.proc.stdin.write(np.ascontiguousarray(x, "<f4").tobytes())
        except (BrokenPipeError, ValueError):
            pass

    def start(self, pull) -> None:
        self.pacer = _Pacer(self.rate, self.rate // 200, pull, self._write, lead_s=self.latency_ms / 1000)

    def close(self) -> None:
        if self.pacer:
            self.pacer.stop.set(); self.pacer.th.join(0.2)
        try:
            self.proc.stdin.close()
        except (OSError, ValueError):  # pipe already broken/closed (the helper exited)
            pass
        self.proc.terminate()
        try:
            self.proc.wait(0.5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class FakeAudioSink(AudioSink):
    """Test device: pulls on a real-time clock like a sound card and counts what it 'plays'."""
    instances: list["FakeAudioSink"] = []

    def __init__(self, rate: int = 48000, channels: int = 2):
        self.rate, self.channels, self.name = rate, channels, "fake-mic"
        self.samples = 0
        self.peak = 0.0
        self.closed = False
        self.pacer = None
        FakeAudioSink.instances.append(self)

    def _write(self, x: np.ndarray) -> None:
        assert x.ndim == 2 and x.shape[1] == self.channels and x.dtype == np.float32
        self.samples += len(x)
        if len(x):
            self.peak = max(self.peak, float(np.abs(x).max()))

    def start(self, pull) -> None:
        self.pacer = _Pacer(self.rate, self.rate // 200, pull, self._write)

    def close(self) -> None:
        if self.pacer:
            self.pacer.stop.set()
        self.closed = True

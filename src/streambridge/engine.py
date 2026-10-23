"""OS-independent core: open URLs with PyAV, decode, scale/resample, reconnect."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Callable

import av
import numpy as np

from . import urls
from .fitter import FrameFitter, auto_size, black_nv12, even
from .jitter import JitterBuffer, mode as latency_mode
from .reconnect import Backoff, wait_or_stop

log = logging.getLogger("streambridge")


@dataclass
class Status:
    kind: str                 # "camera" | "mic"
    state: str = "idle"       # idle | connecting | live | retrying | error | stopped
    detail: str = ""
    source: str = ""          # e.g. "1280x720 30fps mjpeg" / "44100 Hz mono"
    output: str = ""          # e.g. "1280x720 -> StreamBridge Camera"
    fps: float = 0.0
    warning: str = ""         # shown in yellow (e.g. MME fallback)
    updated: float = field(default_factory=time.time)


StatusCb = Callable[[Status], None]

CONNECT_TIMEOUT_S = 10.0   # give up opening a URL after this
STALL_TIMEOUT_S = 5.0      # reconnect when no data arrives for this long


class _Worker:
    kind = ""

    def __init__(self, url: urls.StreamUrl, on_status: StatusCb | None, strict_tls: bool,
                 timeout_s: float | None, reconnect: bool):
        self.url, self.on_status = url, on_status or (lambda s: None)
        self.strict_tls, self.reconnect = strict_tls, reconnect
        self.connect_timeout = timeout_s or CONNECT_TIMEOUT_S
        self.stall_timeout = min(STALL_TIMEOUT_S, self.connect_timeout)
        self.input_format: str | None = None
        self.input_options: dict[str, str] = {}
        self.stop_ev = threading.Event()
        self.status = Status(self.kind)
        self.thread = threading.Thread(target=self._run, name=f"sb-{self.kind}", daemon=True)
        self.backoff = Backoff()

    def _emit(self, state: str, detail: str = "", **kw) -> None:
        self.status.state, self.status.detail = state, urls.mask(detail)
        for k, v in kw.items():
            setattr(self.status, k, v)
        self.status.updated = time.time()
        self.on_status(replace(self.status))  # a snapshot, safe to hand to other threads

    def start(self) -> None:
        self.thread.start()

    def stop(self, wait: float = 0.9) -> None:
        self.stop_ev.set()
        self.thread.join(wait)

    def _open(self):
        opts = urls.ffmpeg_options(self.url, self.strict_tls, self.stall_timeout)
        opts.update(self.input_options)
        return av.open(self.url.url, mode="r", format=self.input_format, options=opts,
                       timeout=(self.connect_timeout, self.stall_timeout))

    def _run(self) -> None:
        while not self.stop_ev.is_set():
            self._emit("connecting", f"Connecting to {self.url.display}")
            try:
                with self._open() as c:
                    self._pump(c)
                if self.stop_ev.is_set():
                    break
                msg = "Stream ended"
            except Exception as e:  # network/decoder errors
                if self.stop_ev.is_set():
                    break
                msg = friendly_error(e)
                log.warning("%s: %s", self.kind, urls.mask(str(e)))
            if not self.reconnect or getattr(self, "fatal", None):
                self._emit("error", getattr(self, "fatal", None) or msg)
                break
            delay = self.backoff.next_delay()
            self._emit("retrying", f"{msg}. Retrying in {delay:.1f}s")
            if wait_or_stop(self.stop_ev, delay):
                break
        self._close_output()
        self._emit("stopped", "")

    def _pump(self, c) -> None: ...
    def _close_output(self) -> None: ...


class VideoWorker(_Worker):
    """decode -> latest-frame slot (depth 1) -> one conversion to NV12 -> camera.

    The decoder never waits for the camera: if the camera side is slower, stale frames are
    replaced (dropped) before they are converted, so video delay can't build up. Frames are sent
    as soon as they arrive (no sleep_until_next_frame). In Auto size the camera matches the
    source exactly (no scaling); a size change reopens just the camera. Only a fixed Camera size
    scales/letterboxes. While reconnecting the camera stays open and shows black.
    """
    kind = "camera"

    def __init__(self, url, camera_factory, size: tuple[int, int] | None = None, fps: float = 30.0,
                 on_status=None, strict_tls=False, timeout_s=None, reconnect=True):
        super().__init__(url, on_status, strict_tls, timeout_s, reconnect)
        self.camera_factory, self.size, self.fps = camera_factory, size, fps
        self.input_options = {"fflags": "nobuffer", "flags": "low_delay", "probesize": "32768",
                              "analyzeduration": "0"}
        self.cam = None
        self.fitter: FrameFitter | None = None
        self._cv = threading.Condition()
        self._slot = None            # latest decoded frame not yet sent
        self.dropped = 0
        self.trace = None            # tests: list of (monotonic sent, frame) callbacks
        self._sender = threading.Thread(target=self._send_loop, name="sb-camera-out", daemon=True)

    def start(self) -> None:
        super().start()
        self._sender.start()

    # decoder thread
    def _pump(self, c) -> None:
        stream = c.streams.video[0]
        stream.thread_type = "AUTO"
        self.codec = stream.codec_context.name
        for frame in c.decode(stream):
            if self.stop_ev.is_set():
                return
            with self._cv:
                if self._slot is not None:
                    self.dropped += 1
                self._slot = frame
                self._cv.notify()

    # sender thread
    def _ensure_camera(self, w: int, h: int) -> None:
        want = (even(self.size[0]), even(self.size[1])) if self.size else auto_size(w, h)
        if self.cam is not None and (self.cam.width, self.cam.height) != want:
            old = f"{self.cam.width}x{self.cam.height}"
            self.cam.close(); self.cam = None
            log.info("camera: source size changed, reopening %s -> %dx%d", old, *want)
        if self.cam is None:
            self.cam = self.camera_factory(want[0], want[1], self.fps)
            self.fitter = FrameFitter(*want)

    def convert(self, frame) -> np.ndarray:
        """The single conversion step: to NV12 at the camera size."""
        if (frame.width, frame.height) == (self.cam.width, self.cam.height):
            return frame.reformat(format="nv12").to_ndarray()
        if self.size is None:   # Auto but odd/oversized source: same aspect, plain scale
            return frame.reformat(width=self.cam.width, height=self.cam.height, format="nv12").to_ndarray()
        x, y, w, h = self.fitter.geometry(frame.width, frame.height)
        return self.fitter.compose(frame.reformat(width=w, height=h, format="nv12").to_ndarray())

    def _send_loop(self) -> None:
        n, t0, last_sent = 0, time.monotonic(), 0.0
        black = None
        idle = 1.0 / max(1.0, min(self.fps, 15.0))
        while True:
            with self._cv:
                if self._slot is None and not self.stop_ev.is_set():
                    self._cv.wait(idle)
                frame, self._slot = self._slot, None
            if self.stop_ev.is_set():
                break
            try:
                if frame is None:
                    # reconnecting / stalled: keep the camera alive with black frames
                    if self.cam is not None and time.monotonic() - last_sent > 0.5:
                        if black is None or black.shape != (self.cam.height * 3 // 2, self.cam.width):
                            black = black_nv12(self.cam.width, self.cam.height)
                        self.cam.send(black)
                    continue
                self._ensure_camera(frame.width, frame.height)
                self.cam.send(self.convert(frame))
            except Exception as e:  # camera backend missing / failed
                log.warning("camera: %s", urls.mask(f'{type(e).__name__}: {e}'))
                self._emit("error", friendly_error(e))
                if self.cam is not None:
                    self.cam.close(); self.cam = None
                self.stop_ev.wait(2.0)
                continue
            last_sent = time.monotonic()
            if self.trace is not None:
                self.trace.append((last_sent, frame))
            n += 1
            if n == 1:
                self.backoff.reset()
            dt = last_sent - t0
            if n == 1 or dt >= 1.0:
                fps = n / dt if dt > 0 and n > 1 else 0.0
                self._emit("live", "", source=f"{frame.width}x{frame.height} {getattr(self, 'codec', '')}",
                           output=f"{self.cam.width}x{self.cam.height} on {self.cam.device}", fps=round(fps, 1))
                if dt >= 1.0:
                    n, t0 = 1, time.monotonic()
        if self.cam is not None:
            self.cam.close(); self.cam = None

    def stop(self, wait: float = 0.9) -> None:
        self.stop_ev.set()
        with self._cv:
            self._cv.notify_all()
        self.thread.join(wait / 2); self._sender.join(wait / 2)

    def _close_output(self) -> None:
        with self._cv:
            self._cv.notify_all()   # camera is closed by the sender thread


class AudioWorker(_Worker):
    """decode -> (one swresample step only if rate/layout/format differ) -> jitter buffer -> device.

    The device pulls on its own clock; the jitter buffer is the only queue (see jitter.py).
    """
    kind = "mic"

    def __init__(self, url, sink_factory, on_status=None, strict_tls=False, timeout_s=None, reconnect=True,
                 raw: tuple[int, int] | None = None, latency: str | None = None):
        super().__init__(url, on_status, strict_tls, timeout_s, reconnect)
        self.sink_factory = sink_factory
        self.latency = latency_mode(latency)
        # Same input behaviour as `ffplay -fflags nobuffer -flags low_delay`, plus a tiny probe.
        self.input_options = {"fflags": "nobuffer", "flags": "low_delay", "probesize": "32",
                              "analyzeduration": "0"}
        # Endless EZ-Cam WAV: small packets (<= 1024 bytes, ~10 ms) and ignore the fake length.
        self.input_options.update({"max_size": "1024", "ignore_length": "1"})
        if raw:  # headerless 16-bit PCM (--audio-raw RATE:CH)
            self.input_format = "s16le"
            for k in ("max_size", "ignore_length"):
                self.input_options.pop(k)
            self.input_options.update({"sample_rate": str(raw[0]), "ch_layout": f"{raw[1]}c" if raw[1] > 2
                                       else ("mono" if raw[1] == 1 else "stereo")})
        self.sink = None
        self.jitter: JitterBuffer | None = None
        self.trace = None   # tests: list of (monotonic arrival, first sample index) per decoded frame

    def _pump(self, c) -> None:
        stream = c.streams.audio[0]
        if self.sink is None:
            sink = self.sink_factory()
            self.jitter = None
            self.sink = sink
            try:
                sink.start(self._pull)       # the sink settles its final host API / rate / channels here
            except Exception as e:
                sink.close()                 # never keep a sink that isn't playing (it would give a silent mic)
                self.sink = None
                self.output_failures = getattr(self, "output_failures", 0) + 1
                log.error("mic output: open failed (%d/2): %s", self.output_failures, e)
                if self.output_failures >= 2:  # WASAPI and MME both failed twice: stop, say so clearly
                    self.fatal = (f"Could not open the audio output {getattr(sink, 'match', '')!r}: {e}. "
                                  "Check it in Sound settings, pick another Audio output, or run "
                                  "'streambridge --audio-selftest'.")
                raise
            self.output_failures = 0
            self.jitter = JitterBuffer(sink.rate, sink.channels, self.latency)
            self._watch_t = time.monotonic()
            self.status.warning = getattr(sink, "warning", "")
        swr = None
        swr_key = None
        first, last_emit, n_in = True, 0.0, 0
        for frame in c.decode(stream):
            if self.stop_ev.is_set():
                return
            if self.trace is not None:
                self.trace.append((time.monotonic(), n_in))
            n_in += frame.samples
            ch = len(frame.layout.channels)
            if frame.sample_rate == self.sink.rate and frame.format.name == "flt" and ch == self.sink.channels:
                self._push(frame.to_ndarray().reshape(-1, ch))          # passthrough, bit-exact
            else:
                # one swresample step: rate + sample format. Channel count is kept for mono/stereo
                # (mono is duplicated exactly below, no -3 dB pan law); >2 channels are downmixed.
                out_ch = ch if ch <= 2 else self.sink.channels
                key = (frame.sample_rate, frame.format.name, ch)
                if swr is None or key != swr_key:
                    swr_key = key
                    swr = av.AudioResampler(format="flt", layout="mono" if out_ch == 1 else "stereo",
                                            rate=self.sink.rate)
                for f in swr.resample(frame):
                    self._push(f.to_ndarray().reshape(-1, out_ch))
            now = time.monotonic()
            self._watchdog(now)
            if first or now - last_emit > 2:
                first, last_emit = False, now
                self.backoff.reset()
                self._emit("live", "", source=f"{frame.sample_rate} Hz {channels_name(ch)} {frame.format.name}",
                           output=f"{self.sink.rate} Hz {channels_name(self.sink.channels)} on {self.sink.name}, "
                                  f"delay ~{self.jitter.level_ms() + self.sink.latency_ms:.0f} ms ({self.latency.name})")

    def _pull(self, n: int) -> np.ndarray:
        jb = self.jitter
        return jb.pull(n) if jb is not None else np.zeros((n, self.sink.channels if self.sink else 2), np.float32)

    def _watchdog(self, now: float) -> None:
        """Log loudly if audio is arriving but the device plays only silence (or isn't pulling)."""
        if now - getattr(self, "_watch_t", now) < 2.0:
            return
        self._watch_t = now
        jb = self.jitter
        if jb.last_in_sound and now - jb.last_in_sound < 2.0:
            if not jb.last_pull or now - jb.last_pull > 2.0:
                msg = f"Mic output problem: audio is arriving but {self.sink.name} is not asking for audio"
            elif not jb.last_out_sound or now - jb.last_out_sound > 2.0:
                msg = f"Mic output problem: audio is arriving but {self.sink.name} has played only silence for 2 s"
            else:
                return
            err = getattr(self.sink, "last_error", "")
            log.warning("%s%s (buffer %.0f ms, underruns %d)", msg, f"; callback error {err}" if err else "",
                        jb.level_ms(), jb.underruns)
            self._emit("live", msg)

    def _push(self, x: np.ndarray) -> None:
        if x.shape[1] != self.sink.channels:            # mono source -> stereo device: exact copy
            x = np.repeat(x, self.sink.channels, axis=1) if x.shape[1] == 1 else x[:, :self.sink.channels].mean(1, keepdims=True)
        self.jitter.push(x)

    def _close_output(self) -> None:
        if self.sink is not None:
            self.sink.close()
            self.sink = None


def channels_name(n: int) -> str:
    return {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}.get(n, f"{n} ch")


def friendly_error(e: Exception) -> str:
    s = urls.mask(str(e))
    low = s.lower()
    if "loopback" in low or "obs virtual camera" in low or "virtual camera" in low or "'obs' backend" in low:
        return ("The virtual camera is not available: " + s.split(" See also")[0]
                + " (run 'streambridge --check' or see the setup panel)")
    if isinstance(e, av.error.HTTPUnauthorizedError) or "401" in low or "unauthorized" in low:
        return "Login failed (wrong username or password)"
    if "403" in low or "forbidden" in low:
        return "Access denied by the phone (403)"
    if "404" in low or "not found" in low:
        return "Address not found on the phone (404). Check the path, e.g. /video"
    if "refused" in low:
        return "Connection refused. Is the phone app streaming?"
    if "timed out" in low or "timeout" in low or isinstance(e, av.error.ExitError):
        return "No answer (timeout). Check the IP address and that both devices are on the same Wi-Fi"
    if "certificate" in low or "ssl" in low or "tls" in low:
        return "HTTPS certificate problem (turn off Strict HTTPS for a phone on your LAN)"
    if isinstance(e, IndexError):
        return "This URL has no stream of that type"
    return s[:200]


def probe(url: urls.StreamUrl, want: str, strict_tls=False, timeout_s=CONNECT_TIMEOUT_S,
          raw: tuple[int, int] | None = None) -> str:
    """Test URLs: open, read one frame, describe it. Creates no devices. Raises on failure."""
    opts = urls.ffmpeg_options(url, strict_tls, min(timeout_s, STALL_TIMEOUT_S))
    fmt = None
    if raw and want == "audio":
        fmt = "s16le"
        opts.update({"sample_rate": str(raw[0]), "ch_layout": "mono" if raw[1] == 1 else "stereo" if raw[1] == 2 else f"{raw[1]}c"})
    with av.open(url.url, format=fmt, options=opts, timeout=(timeout_s, min(timeout_s, STALL_TIMEOUT_S))) as c:
        if want == "video":
            s = c.streams.video[0]
            for f in c.decode(s):
                return f"OK: video {f.width}x{f.height} ({s.codec_context.name})"
        else:
            s = c.streams.audio[0]
            for f in c.decode(s):
                return f"OK: audio {f.sample_rate} Hz {channels_name(len(f.layout.channels))} ({s.codec_context.name})"
    raise RuntimeError("Stream opened but sent no data")

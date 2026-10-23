"""Measures mic latency: a fake *device* that consumes audio in real time and detects tone bursts.

Works with both sink styles:
  * push:  sink.write(x) blocks like a PortAudio blocking stream with a small device buffer
  * pull:  sink.start(pull) -> a thread pulls 5 ms blocks on the device clock
Latency of burst k = (time it is "played") - (time the fake phone captured it).
"""
from __future__ import annotations

import threading
import time

import numpy as np

BURST_HZ = [500 + 100 * k for k in range(8)]


class MeterSink:
    def __init__(self, rate=48000, channels=2, device_buffer_ms=20, block_ms=5):
        self.rate, self.channels, self.name = rate, channels, "meter"
        self.latency_ms = 0.0
        self.block = int(rate * block_ms / 1000)
        self.dev_buf = device_buffer_ms / 1000
        self.t_start = None
        self.played = 0
        self._stop = threading.Event()
        self.samples = 0
        self.peak = 0.0
        self.closed = False
        self._th = None
        self._chunks: list[np.ndarray] = []
        self._first_play = None

    # --- push style (old) ---
    def write(self, x: np.ndarray) -> None:
        if self.t_start is None:
            self.t_start = time.monotonic()
        self._consume(x)
        # block until the device would have room again (real-time pacing, small buffer)
        due = self.t_start + self.played / self.rate - self.dev_buf
        d = due - time.monotonic()
        if d > 0:
            time.sleep(d)

    # --- pull style (new) ---
    def start(self, pull) -> None:
        self.pull_mode = True
        def run():
            self.t_start = time.monotonic()
            while not self._stop.is_set():
                self._consume(pull(self.block))
                due = self.t_start + self.played / self.rate
                d = due - time.monotonic()
                if d > 0:
                    time.sleep(d)
        self._th = threading.Thread(target=run, daemon=True)
        self._th.start()

    def _consume(self, x: np.ndarray) -> None:
        mono = np.asarray(x[:, 0] if x.ndim == 2 else x, np.float32)
        if self._first_play is None:
            # wall-clock play time of sample 0 (push style adds the device buffer)
            self._first_play = self.t_start + (0 if getattr(self, 'pull_mode', False) else self.dev_buf)
        self.samples += len(mono)
        if len(mono):
            self.peak = max(self.peak, float(np.abs(mono).max()))
        self._chunks.append(mono.copy())
        self.played += len(mono)

    def onsets(self) -> list[tuple[float, int]]:
        """(monotonic play time, burst index mod 8) for every tone burst that was played."""
        y = np.concatenate(self._chunks) if self._chunks else np.zeros(0, np.float32)
        loud = np.abs(y) > 0.2
        out, i, n = [], 0, int(self.rate * 0.025)
        idx = np.flatnonzero(loud)
        if not len(idx):
            return out
        starts = idx[np.concatenate([[True], np.diff(idx) > self.rate * 0.2])]   # first loud sample per burst
        for j in starts:
            seg = y[j:j + n]
            if len(seg) < n:
                break
            spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), 8 * len(seg)))
            hz = np.argmax(spec) * self.rate / (8 * len(seg))
            k = int(np.argmin([abs(hz - b) for b in BURST_HZ]))
            out.append((self._first_play + j / self.rate, k))
        return out

    def latencies(self, t0_wall: float, mono_to_wall: float) -> list[float]:
        """Latency per burst. Burst n is captured at t0 + n s; n is matched by its tone (n % 8)."""
        res = []
        for t_play, k8 in self.onsets():
            approx = t_play + mono_to_wall - t0_wall
            cands = [m for m in range(max(0, int(approx) - 8), int(approx) + 1) if m % 8 == k8]
            if cands:
                res.append(approx - max(cands))
        return res

    def close(self) -> None:
        self._stop.set()
        self.closed = True


def measure(make_session, base_url: str, seconds: float = 8.0) -> list[float]:
    """make_session(url, sink_factory) -> started session with .stop(). Returns latencies in seconds."""
    import urllib.request
    sink = MeterSink()
    sess = make_session(base_url + "/bursts.wav", lambda: sink)
    time.sleep(seconds)
    sess.stop()
    t0 = float(urllib.request.urlopen(base_url + "/t0").read())
    mono_to_wall = time.time() - time.monotonic()
    return sink.latencies(t0, mono_to_wall)


class MeterCamera:
    """Fake camera that decodes the frame number drawn by /tsvideo and timestamps arrival."""
    instances: list["MeterCamera"] = []

    def __init__(self, width, height, fps, backend=None, device=None):
        self.width, self.height, self.fps, self.device = width, height, fps, "meter-camera"
        self.arrivals: list[tuple[float, int]] = []
        self.closed = False
        MeterCamera.instances.append(self)

    def send(self, nv12: np.ndarray) -> None:
        t = time.time()
        y = nv12[..., 0] if nv12.ndim == 3 else nv12[: self.height]   # RGB or NV12
        row = y[self.height // 2]
        bw = self.width / 16
        bits = [row[int(b * bw + bw / 2)] > 128 for b in range(16)]
        if y.mean() > 20:                       # skip black keep-alive frames
            self.arrivals.append((t, sum(1 << b for b, on in enumerate(bits) if on)))

    def close(self) -> None:
        self.closed = True

    def latencies(self, t0v: float, fps: float = 30.0) -> list[float]:
        return [t - (t0v + n / fps) for t, n in self.arrivals]

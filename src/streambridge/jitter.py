"""Low-latency jitter buffer between the network/decoder thread and the audio device.

push() is called by the decoder whenever audio arrives (in bursts, whatever the network does).
pull(n) is called on the *device* clock (PortAudio callback / pacer thread) and always returns
exactly n frames, so the device never blocks the decoder and delay can never pile up:

* start / after an underrun: output silence until `target` is buffered (pre-roll).
* level above `max`: the oldest audio is dropped down to `target` (a burst or a backlog
  from the phone costs one small skip instead of permanent delay).
* clock drift (phone vs. PC sound card): when the smoothed level stays above/below target,
  1-2 samples per block are skipped, or one repeated (<= 0.8 %). Inaudible, and keeps delay at target.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class LatencyMode:
    name: str
    target_ms: float     # aimed buffer level
    max_ms: float        # above this, drop oldest audio
    device_s: float | str  # PortAudio output latency


MODES = {
    "low": LatencyMode("low", 30, 120, "low"),
    "normal": LatencyMode("normal", 60, 200, "low"),
    "stable": LatencyMode("stable", 150, 400, 0.1),
}
DEFAULT_MODE = "low"


def mode(name: str | None) -> LatencyMode:
    m = MODES.get((name or DEFAULT_MODE).strip().lower())
    if m is None:
        raise ValueError(f"Mic delay must be one of: {', '.join(MODES)}")
    return m


class JitterBuffer:
    def __init__(self, rate: int, channels: int, latency: LatencyMode):
        self.rate, self.ch = rate, channels
        self.target = int(rate * latency.target_ms / 1000)
        self.max = int(rate * latency.max_ms / 1000)
        self._buf = np.zeros((max(self.max * 2, rate), channels), np.float32)  # ring
        self._r = self._w = 0          # absolute read/write counters
        self._lock = threading.Lock()
        self._primed = False
        self._avg = float(self.target)
        if self.target > self.max:          # start threshold must always be reachable
            self.target = self.max
        # stats / watchdog (monotonic times)
        self.dropped = self.underruns = self.adjusted = 0
        self.last_pull = self.last_out_sound = self.last_in_sound = 0.0

    @property
    def level(self) -> int:
        return self._w - self._r

    def level_ms(self) -> float:
        return 1000.0 * self.level / self.rate

    def push(self, x: np.ndarray) -> None:
        if not len(x):
            return
        x = np.asarray(x, np.float32).reshape(-1, self.ch)
        if np.abs(x).max() > 1e-4:
            self.last_in_sound = time.monotonic()
        with self._lock:
            size = len(self._buf)
            if len(x) >= size:
                x = x[-size + 1:]
            i = self._w % size
            n1 = min(len(x), size - i)
            self._buf[i:i + n1] = x[:n1]
            self._buf[:len(x) - n1] = x[n1:]
            self._w += len(x)
            if self.level > self.max:                     # too much delay: drop oldest
                drop = self.level - self.target
                self._r += drop
                self.dropped += drop
            elif self.level >= size:
                self._r = self._w - size + 1

    def pull(self, n: int) -> np.ndarray:
        out = self._pull(n)
        self.last_pull = time.monotonic()
        if len(out) and np.abs(out).max() > 1e-4:
            self.last_out_sound = self.last_pull
        return out

    def _pull(self, n: int) -> np.ndarray:
        out = np.zeros((n, self.ch), np.float32)
        with self._lock:
            lvl = self.level
            if not self._primed:
                if lvl < self.target:
                    return out
                self._primed = True
                self._r += lvl - self.target          # start exactly at target (skip connect backlog)
                self.dropped += lvl - self.target
                lvl = self.target
                self._avg = float(lvl)
            self._avg += (lvl - self._avg) * 0.02
            take = n
            if self._avg > self.target * 1.25 and lvl > n + 2:
                # phone clock fast / burst left us high: skip 1-2 samples per block (<= 0.8 %)
                take = n + (2 if self._avg > self.target * 2 else 1); self.adjusted += 1
            elif self._avg < self.target * 0.75:
                take = n - 1; self.adjusted += 1                 # phone clock slow: stretch by one
            k = min(take, lvl)
            size = len(self._buf)
            idx = (self._r + np.arange(k)) % size
            seg = self._buf[idx]
            self._r += k
            if k < take:                                          # underrun: re-prime
                self.underruns += 1
                self._primed = False
                out[:k] = seg[:n]
                return out
        if take == n:
            out[:] = seg
        elif take > n:
            out[:] = np.delete(seg, np.linspace(0, take - 1, take - n + 2)[1:-1].astype(int), axis=0)
        else:
            out[:] = np.insert(seg, n // 2, seg[n // 2 - 1], axis=0)
        return out

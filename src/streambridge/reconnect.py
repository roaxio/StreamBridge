"""Exponential backoff for auto-reconnect."""
from __future__ import annotations

import random
import threading


class Backoff:
    def __init__(self, base: float = 0.5, factor: float = 2.0, cap: float = 10.0, jitter: float = 0.1,
                 rng: random.Random | None = None):
        self.base, self.factor, self.cap, self.jitter = base, factor, cap, jitter
        self.attempt = 0
        self._rng = rng or random.Random()

    def next_delay(self) -> float:
        d = min(self.cap, self.base * (self.factor ** self.attempt))
        self.attempt += 1
        if self.jitter:
            d *= 1 + self._rng.uniform(-self.jitter, self.jitter)
        return max(0.0, min(d, self.cap))

    def reset(self) -> None:
        self.attempt = 0


def wait_or_stop(stop: threading.Event, seconds: float) -> bool:
    """Sleep up to seconds; return True if stop was requested (wakes immediately)."""
    return stop.wait(seconds)

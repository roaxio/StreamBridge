import random
import threading
import time

from streambridge.reconnect import Backoff, wait_or_stop


def test_backoff_grows_and_caps():
    b = Backoff(base=0.5, factor=2, cap=10, jitter=0)
    assert [b.next_delay() for _ in range(7)] == [0.5, 1, 2, 4, 8, 10, 10]
    b.reset()
    assert b.next_delay() == 0.5


def test_jitter_bounded():
    b = Backoff(base=1, factor=1, cap=5, jitter=0.2, rng=random.Random(1))
    assert all(0.8 <= b.next_delay() <= 1.2 for _ in range(100))


def test_wait_wakes_on_stop():
    ev = threading.Event()
    threading.Timer(0.1, ev.set).start()
    t = time.monotonic()
    assert wait_or_stop(ev, 30) is True
    assert time.monotonic() - t < 0.5

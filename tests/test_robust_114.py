"""Atomic settings save and bounded Session.stop."""
import json
import logging
import threading
import time
from types import SimpleNamespace

import pytest

from streambridge import settings
from streambridge.session import Options, Session


def test_save_atomic_content_and_no_temp(tmp_path):
    p = tmp_path / "cfg" / "settings.json"
    settings.save({"video_url": "http://a/v"}, p)
    assert json.loads(p.read_text("utf-8"))["video_url"] == "http://a/v"
    settings.save({"video_url": "http://b/v"}, p)
    assert json.loads(p.read_text("utf-8"))["video_url"] == "http://b/v"
    assert [f.name for f in p.parent.iterdir()] == ["settings.json"]


def test_save_failure_keeps_original(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    settings.save({"video_url": "http://a/v"}, p)
    before = p.read_bytes()

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr("os.replace", boom)
    with pytest.raises(OSError):
        settings.save({"video_url": "http://b/v"}, p)
    assert p.read_bytes() == before
    assert [f.name for f in tmp_path.iterdir()] == ["settings.json"]


def test_save_failure_during_write_cleans_temp(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    monkeypatch.setattr("os.fsync", lambda fd: (_ for _ in ()).throw(OSError("io")))
    with pytest.raises(OSError):
        settings.save({}, p)
    assert list(tmp_path.iterdir()) == []


class _Worker:
    """Fake worker whose thread is 'stuck in av.open' for `block` seconds, ignoring stop_ev."""
    def __init__(self, name, block, events):
        self.stop_ev = threading.Event()
        self.thread = threading.Thread(target=self._run, args=(block, events, name), name=name, daemon=True)

    def _run(self, block, events, name):
        time.sleep(block)
        events.append(("exit", name))

    def start(self):
        self.thread.start()


def _session(workers, events):
    plat = SimpleNamespace(camera_device=lambda: None, camera_backend=None,
                           mic_teardown=lambda: events.append(("teardown",)))
    s = Session(Options(video_url="http://x/v"), plat)
    s.workers = workers
    s._mic_ready = True
    for w in workers:
        w.start()
    return s


def test_stop_waits_for_threads_before_teardown(caplog):
    ev = []
    s = _session([_Worker("a", 0.2, ev), _Worker("b", 0.3, ev)], ev)
    with caplog.at_level(logging.WARNING, "streambridge"):
        s.stop(timeout=2.0)
    assert ev[-1] == ("teardown",) and ("exit", "a") in ev and ("exit", "b") in ev
    assert "still running" not in caplog.text


def test_stop_deadline_is_shared_and_warns(caplog):
    ev = []
    s = _session([_Worker("w1", 5, ev), _Worker("w2", 5, ev), _Worker("w3", 5, ev)], ev)
    t = time.monotonic()
    with caplog.at_level(logging.WARNING, "streambridge"):
        s.stop(timeout=0.5)
    took = time.monotonic() - t
    assert 0.45 < took < 0.9          # one shared deadline, not 3 x 0.5
    assert ev == [("teardown",)]      # torn down anyway
    assert "w1" in caplog.text and "still running" in caplog.text
    assert s._mic_ready is False

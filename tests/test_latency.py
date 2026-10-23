"""End-to-end latency with the fake EZ-Cam server (timestamped tone bursts / numbered video frames)."""
import statistics
import time
import urllib.request

import pytest

from latency_meter import MeterCamera, MeterSink
from streambridge.platform import LinuxPlatform
from streambridge.session import Options, Session


def audio_latency(ezcam_url, mode, seconds=6.0):
    sink = MeterSink()
    s = Session(Options(audio_url=ezcam_url + "/bursts.wav", audio_latency=mode), LinuxPlatform(), None, None,
                lambda: sink)
    s.start(); time.sleep(seconds); s.stop()
    t0 = float(urllib.request.urlopen(ezcam_url + "/t0").read())
    lat = sink.latencies(t0, time.time() - time.monotonic())
    assert len(lat) >= 3
    return statistics.median(lat[1:]) * 1000, sink


@pytest.mark.parametrize("mode,limit", [("low", 120), ("normal", 200), ("stable", 300)])
def test_audio_latency_modes(ezcam, mode, limit):
    ms, sink = audio_latency(ezcam(), mode)
    assert ms < limit, ms
    assert abs(sink.peak - 0.5) < 0.01          # no gain change: 0.5 tone arrives at 0.5


def test_audio_backlog_from_phone_is_not_kept(ezcam):
    """The phone sends 800 ms of old audio at connect; we must not keep that delay."""
    ms, _ = audio_latency(ezcam(backlog_ms=800), "normal")
    assert ms < 200, ms


def test_video_latency_and_backlog(ezcam):
    base = ezcam(backlog_ms=800)
    MeterCamera.instances.clear()
    s = Session(Options(video_url=base + "/tsvideo"), LinuxPlatform(), None, MeterCamera, None)
    s.start(); time.sleep(5); s.stop()
    t0v = float(urllib.request.urlopen(base + "/t0v").read())
    lat = [x * 1000 for x in MeterCamera.instances[0].latencies(t0v)]
    assert statistics.median(lat[len(lat) // 2:]) < 60

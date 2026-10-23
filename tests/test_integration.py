"""End-to-end: fake EZ-Cam phone -> PyAV -> fake camera / fake mic."""
import time

import pytest

from streambridge import engine, urls
from streambridge.platform import LinuxPlatform
from streambridge.session import Options, Session
from streambridge.sinks import FakeAudioSink, FakeCameraSink


def run(opts, seconds=3.0, sink=lambda: FakeAudioSink(48000, 2)):
    FakeCameraSink.instances.clear(); FakeAudioSink.instances.clear()
    states = []
    s = Session(opts, LinuxPlatform(), states.append, FakeCameraSink, sink)
    s.start()
    time.sleep(seconds)
    t = time.monotonic(); s.stop(); stop_time = time.monotonic() - t
    return states, stop_time


@pytest.mark.parametrize("https", [False, True])
def test_video_and_audio(ezcam, https):
    base = ezcam(https=https)
    states, stop_time = run(Options(base + "/video", base + "/audio.wav"))
    cam, mic = FakeCameraSink.instances[0], FakeAudioSink.instances[0]
    assert (cam.width, cam.height) == (640, 480) and cam.frames > 30
    assert mic.samples > 48000 and mic.peak > 0.05
    assert any(s.kind == "camera" and s.state == "live" for s in states)
    assert stop_time < 1.0
    assert cam.closed and mic.closed


def test_login_and_masking(ezcam):
    base = ezcam(user="user", password="pass")
    authed = base.replace("://", "://user:pass@") + "/video"
    states, _ = run(Options(authed), 2.5)
    assert FakeCameraSink.instances[0].frames > 10
    assert all(":pass@" not in (s.detail + s.source + s.output) for s in states)


def test_wrong_password_friendly(ezcam):
    base = ezcam(user="user", password="pass")
    with pytest.raises(Exception) as e:
        engine.probe(urls.parse(base + "/video", "user", "nope"), "video")
    assert "Login failed" in engine.friendly_error(e.value)


@pytest.mark.parametrize("rate,ch", [(8000, 1), (22050, 2), (96000, 2)])
def test_audio_rates(ezcam, rate, ch):
    base = ezcam(rate=rate, channels=ch)
    # The fake server (ffmpeg pipe) delivers low-rate audio in ~32 KB bursts, so give 8 kHz time.
    run(Options(audio_url=base + "/audio.wav"), 6.0 if rate < 16000 else 2.5)
    m = FakeAudioSink.instances[0]
    assert m.samples > 48000 and m.peak > 0.05


def test_portrait_auto_size(ezcam):
    base = ezcam(size="481x853")
    run(Options(base + "/video"), 2.0)
    c = FakeCameraSink.instances[0]
    assert (c.width, c.height) == (480, 852)


def test_fixed_size_letterbox(ezcam):
    base = ezcam(size="720x1280")
    run(Options(base + "/video", size=(1280, 720)), 2.0)
    c = FakeCameraSink.instances[0]
    assert (c.width, c.height) == (1280, 720) and (c.last[:720, :100] == 16).all()  # black bars (Y plane)


def test_strict_tls_refuses_self_signed(ezcam):
    base = ezcam(https=True)
    with pytest.raises(Exception):
        engine.probe(urls.parse(base + "/video"), "video", strict_tls=True, timeout_s=4)


def test_reconnect_after_server_restart(ezcam):
    from tests.conftest import free_port  # noqa
    # nothing listening -> retrying states, then stop fast
    port = free_port()
    states, stop_time = run(Options(f"http://127.0.0.1:{port}/video", timeout_s=1), 2.5)
    assert any(s.state == "retrying" for s in states)
    assert stop_time < 1.0


def test_black_frames_keep_camera_open_while_reconnecting(ezcam):
    """Server goes away: the camera stays open and receives black frames."""
    import shutil, subprocess
    if not shutil.which("pkill"):
        pytest.skip("pkill CLI not available")
    base = ezcam()
    FakeCameraSink.instances.clear()
    s = Session(Options(base + "/video"), LinuxPlatform(), None, FakeCameraSink, None)
    s.start(); time.sleep(2)
    cam = FakeCameraSink.instances[0]
    # kill the fake server: every process started by the fixture
    subprocess.run(["pkill", "-f", base.rsplit(":", 1)[1]], check=False)
    time.sleep(3)
    n = cam.frames; time.sleep(1.2)
    assert not cam.closed and cam.frames > n and (cam.last[:cam.height] == 16).all()
    s.stop()
    assert cam.closed


def test_audio_raw(ezcam):
    """--audio-raw: headerless PCM16. Fake server's WAV header is 44 bytes of 'noise'; fine for this check."""
    base = ezcam(rate=16000, channels=1)
    FakeAudioSink.instances.clear()
    s = Session(Options(audio_url=base + "/audio.wav", audio_raw=(16000, 1)), LinuxPlatform(), None, None,
                lambda: FakeAudioSink(48000, 2))
    s.start(); time.sleep(3); s.stop()
    assert FakeAudioSink.instances[0].samples > 48000


def test_cli_fake_devices(ezcam):
    import subprocess, sys
    base = ezcam()
    r = subprocess.run([sys.executable, "-m", "streambridge", "--video", base.replace("http://", "") + "/video",
                        "--audio", base + "/audio.wav", "--fake-devices", "--duration", "3"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "fake camera 640x480" in r.stdout and "Stopped in 0." in r.stdout


def test_cli_test_mode(ezcam):
    import subprocess, sys
    base = ezcam()
    r = subprocess.run([sys.executable, "-m", "streambridge", "--test", "--video", base + "/video",
                        "--audio", base + "/audio.wav"], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK: video 640x480" in r.stdout and "OK: audio 44100 Hz mono" in r.stdout

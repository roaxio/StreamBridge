import subprocess

import pytest

from streambridge.platform import LinuxPlatform, MacPlatform, WindowsPlatform, linux


@pytest.mark.parametrize("cls", [WindowsPlatform, MacPlatform, LinuxPlatform])
def test_check_runs_everywhere_and_links_are_official(cls):
    deps = cls().check()
    assert {d.needed_for for d in deps} == {"camera", "mic"}
    allowed = ("https://obsproject.com/download", "https://vb-audio.com/Cable/", "https://existential.audio/blackhole/",
               "https://github.com/umlaeute/v4l2loopback#distributions", "https://pipewire.org/")
    assert all(d.url in allowed for d in deps)


def test_windows_no_silent_fallback(monkeypatch):
    monkeypatch.setattr("streambridge.platform.windows.find_output_device", lambda _: (None, None))
    monkeypatch.setattr("streambridge.sdl_audio.find_device", lambda _: None)
    with pytest.raises(RuntimeError, match="CABLE Input"):
        WindowsPlatform().mic_setup("auto")


@pytest.mark.skipif(not linux.audio_server_ok(), reason="no PipeWire/PulseAudio server")
def test_linux_mic_created_and_removed():
    p = LinuxPlatform()
    factory = p.mic_setup()
    src = subprocess.run(["pactl", "list", "short", "sources"], capture_output=True, text=True).stdout
    assert linux.SOURCE in src
    import numpy as np, time
    sink = factory(); sink.start(lambda n: np.zeros((n, 2), np.float32)); time.sleep(0.2); sink.close()
    p.mic_teardown()
    mods = subprocess.run(["pactl", "list", "short", "modules"], capture_output=True, text=True).stdout
    assert "streambridge" not in mods

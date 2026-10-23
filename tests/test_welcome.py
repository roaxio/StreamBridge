"""Welcome / Setup check logic, with mocked requirement checks (no real devices needed)."""
import pytest

from streambridge import settings, welcome
from streambridge.platform import LinuxPlatform, MacPlatform, WindowsPlatform
from streambridge.platform.base import Dependency
from streambridge.platform.linux import MODPROBE

OFFICIAL = ("https://obsproject.com/", "https://vb-audio.com/", "https://existential.audio/",
            "https://github.com/umlaeute/v4l2loopback", "https://pipewire.org/")


def deps(cam_ok, mic_ok):
    return [Dependency("cam", "camera", cam_ok, "cam detail"), Dependency("mic", "mic", mic_ok, "mic detail")]


@pytest.mark.parametrize("cls,cam,mic", [
    (WindowsPlatform, "OBS Studio", "VB-CABLE"),
    (MacPlatform, "OBS Studio", "BlackHole"),
    (LinuxPlatform, "v4l2loopback", "PipeWire"),
])
@pytest.mark.parametrize("cam_ok,mic_ok", [(True, True), (False, True), (True, False), (False, False)])
def test_report_per_os(cls, cam, mic, cam_ok, mic_ok):
    rep = welcome.build(cls(), deps(cam_ok, mic_ok))
    assert "camera and microphone" in rep.intro and "never downloads or installs" in rep.intro
    assert [i.needed_for for i in rep.items] == ["camera", "mic"]
    assert cam in rep.items[0].title and mic in rep.items[1].title
    assert [i.ok for i in rep.items] == [cam_ok, mic_ok]
    assert rep.all_ok == (cam_ok and mic_ok)
    assert rep.items[0].status == "cam detail"
    for i in rep.items:
        assert i.url.startswith(OFFICIAL), i.url
        assert i.howto


def test_linux_shows_modprobe_command():
    rep = welcome.build(LinuxPlatform(), deps(False, False))
    assert rep.items[0].copy == MODPROBE and "modprobe v4l2loopback" in MODPROBE
    assert rep.items[1].copy == ""


def test_windows_mac_have_no_commands():
    for cls in (WindowsPlatform, MacPlatform):
        assert all(i.copy == "" for i in welcome.build(cls(), deps(False, False)).items)


def test_build_calls_platform_check(monkeypatch):
    p = LinuxPlatform()
    monkeypatch.setattr(p, "check", lambda: deps(True, False))
    rep = welcome.build(p)
    assert [i.ok for i in rep.items] == [True, False]


def test_missing_dependency_entry_is_red():
    rep = welcome.build(WindowsPlatform(), [Dependency("cam", "camera", True)])
    assert rep.items[1].ok is False and not rep.all_ok


def test_dont_show_again_saved_and_reset_brings_it_back(tmp_path):
    p = tmp_path / "StreamBridge" / "settings.json"
    assert welcome.should_show(settings.load(p))
    cfg = settings.load(p); cfg["welcome_dont_show"] = True; settings.save(cfg, p)
    assert not welcome.should_show(settings.load(p))
    settings.reset(path=p)
    assert welcome.should_show(settings.load(p))

"""platform/linux.py with pactl and sysfs faked (no real modules are loaded)."""
import subprocess
import types

import pytest

from streambridge.platform import linux


def cp(rc=0, out="", err=""):
    return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)


def test_loopback_devices_from_sysfs(monkeypatch, tmp_path):
    for n, name in (("video0", "Integrated Camera"), ("video10", "StreamBridge Camera"), ("video2", "bad")):
        d = tmp_path / n; d.mkdir(); (d / "name").write_text(name + "\n")
    (tmp_path / "video0" / "device").mkdir()                          # has a real driver
    (tmp_path / "video3").mkdir()                                    # unreadable name: skipped
    real = linux.os.path.realpath
    monkeypatch.setattr(linux.glob, "glob", lambda p: [str(tmp_path / x) for x in ("video0", "video10", "video2", "video3")])
    monkeypatch.setattr(linux.os.path, "realpath", lambda p: "/drv/uvcvideo" if "video0" in p else real(p))
    assert linux.loopback_devices() == ["/dev/video10", "/dev/video2"]


def test_audio_server_ok(monkeypatch):
    monkeypatch.setattr(linux.shutil, "which", lambda n: None)
    assert linux.audio_server_ok() is False
    monkeypatch.setattr(linux.shutil, "which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr(linux, "_pactl", lambda *a, **k: cp(0))
    assert linux.audio_server_ok() is True

    def timeout(*a, **k):
        raise subprocess.TimeoutExpired("pactl", 4)
    monkeypatch.setattr(linux, "_pactl", timeout)
    assert linux.audio_server_ok() is False


def test_check_and_camera_device(monkeypatch):
    monkeypatch.setattr(linux, "loopback_devices", lambda: [])
    monkeypatch.setattr(linux, "audio_server_ok", lambda: False)
    p = linux.LinuxPlatform()
    cam, mic = p.check()
    assert not cam.ok and not mic.ok and any("modprobe" in s for s in cam.steps)
    assert p.camera_device() is None
    monkeypatch.setattr(linux, "loopback_devices", lambda: ["/dev/video10"])
    assert p.check()[0].ok and p.camera_device() == "/dev/video10"
    p.video_device = "/dev/video7"
    assert p.camera_device() == "/dev/video7"


class FakePactl:
    def __init__(self, fail_at=None, modules=""):
        self.calls, self.fail_at, self.modules, self.n = [], fail_at, modules, 100

    def __call__(self, *args, timeout=4.0):
        self.calls.append(args)
        if args[:2] == ("list", "short"):
            return cp(0, self.modules)
        if args[0] == "load-module":
            if self.fail_at == args[1]:
                return cp(1, "", "denied")
            self.n += 1
            return cp(0, f"{self.n}\n")
        return cp(0)


def test_mic_setup_and_teardown(monkeypatch):
    f = FakePactl(modules=f"7\tmodule-null-sink\tsink_name={linux.SINK}\n8\tmodule-other\tx=y\n")
    monkeypatch.setattr(linux, "_pactl", f)
    p = linux.LinuxPlatform()
    factory = p.mic_setup(latency="stable")
    assert ("unload-module", "7") in f.calls and ("unload-module", "8") not in f.calls   # only our stale module
    assert p._modules == ["101", "102"] and callable(factory)
    p.mic_teardown()
    assert f.calls[-2:] == [("unload-module", "102"), ("unload-module", "101")] and p._modules == []
    p.mic_teardown()   # safe twice


@pytest.mark.parametrize("fail_at,msg", [("module-null-sink", "virtual audio sink"),
                                         ("module-remap-source", "virtual microphone")])
def test_mic_setup_failure_cleans_up(monkeypatch, fail_at, msg):
    f = FakePactl(fail_at=fail_at)
    monkeypatch.setattr(linux, "_pactl", f)
    p = linux.LinuxPlatform()
    with pytest.raises(RuntimeError, match=msg):
        p.mic_setup()
    assert p._modules == []


def test_cleanup_and_teardown_tolerate_missing_pactl(monkeypatch):
    def missing(*a, **k):
        raise OSError("pactl not found")
    monkeypatch.setattr(linux, "_pactl", missing)
    p = linux.LinuxPlatform()
    p._cleanup_stale()
    p._modules = ["5"]
    p.mic_teardown()
    assert p._modules == []

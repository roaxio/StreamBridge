"""The small functions cli.main() is made of (same outputs and exit codes)."""
import argparse
import types

import pytest

from streambridge import cli
from streambridge.platform.base import Platform


class FakePlat(Platform):
    name = "Windows"
    recommended_output = "CABLE Input"
    camera_name, mic_name = "Cam X", "Mic Y"

    def check(self):
        return []


def ns(**kw):
    a = cli.build_parser().parse_args([])
    for k, v in kw.items():
        setattr(a, k, v)
    return a


@pytest.mark.parametrize("text,want", [(None, None), ("", None), ("16000:1", (16000, 1)), ("48000", (48000, 1)),
                                       ("44100:2", (44100, 2))])
def test_parse_audio_raw_ok(text, want):
    assert cli.parse_audio_raw(text) == want


@pytest.mark.parametrize("text", ["abc", "100:1", "16000:9", "16000:0", "16000:x"])
def test_parse_audio_raw_bad(text):
    with pytest.raises(ValueError):
        cli.parse_audio_raw(text)


def test_bad_audio_raw_exit_code(capsys):
    assert cli.main(["--audio", "http://127.0.0.1:1/a", "--audio-raw", "nope", "--fake-devices"]) == 2
    assert "RATE:CHANNELS" in capsys.readouterr().err


def test_no_urls_exit_code(capsys):
    assert cli.main(["--fps", "30"]) == 2
    assert "Give --video URL" in capsys.readouterr().err


def test_bad_size_and_bad_url_exit_code(capsys):
    assert cli.main(["--video", "http://127.0.0.1:1/v", "--size", "huge"]) == 2
    assert cli.main(["--video", "ftp://x/v", "--test"]) == 2
    assert cli.main(["--video", "ftp://x/v", "--fake-devices", "--duration", "0.1"]) == 2


def test_read_password(monkeypatch):
    monkeypatch.setenv("SB_PW", "s3")
    assert cli.read_password(ns(password_env="SB_PW")) == "s3"
    assert cli.read_password(ns()) == ""
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "typed")
    assert cli.read_password(ns(password_env="SB_PW", ask_password=True)) == "typed"


def test_output_tag():
    p = FakePlat()
    assert cli.output_tag(p, "CABLE Input (VB-Audio)") == "recommended"
    assert cli.output_tag(p, "BlackHole 2ch") == "virtual"
    assert cli.output_tag(p, "Speakers (Realtek)") == "speakers"


def test_list_audio_outputs_windows_uses_sdl_names(monkeypatch, capsys):
    from streambridge import sdl_audio, sinks
    monkeypatch.setattr(sinks, "list_output_devices", lambda: [{"name": "PortAudio dev"}])
    monkeypatch.setattr(sdl_audio, "list_devices", lambda: ["CABLE Input (VB-Audio Virtual Cable)", "Speakers"])
    monkeypatch.setattr(sdl_audio, "driver", lambda: "wasapi")
    assert cli.list_audio_outputs(FakePlat(), verbose=True) == 0
    out = capsys.readouterr().out
    assert "AUDIO_OUTPUT recommended CABLE Input" in out and "AUDIO_OUTPUT speakers Speakers" in out
    assert "SDL2 wasapi #1, 48000 Hz, 2 ch" in out and "PortAudio dev" not in out


def test_list_audio_outputs_empty(monkeypatch, capsys):
    from streambridge import sinks
    monkeypatch.setattr(sinks, "list_output_devices", lambda: [])
    p = FakePlat(); p.name = "macOS"
    assert cli.list_audio_outputs(p) == 0
    assert "No playback devices found" in capsys.readouterr().out
    p.name = "Linux"
    cli.list_audio_outputs(p)
    assert "StreamBridge Microphone" in capsys.readouterr().out


def test_fake_device_factories():
    assert cli.fake_device_factories(False) == (None, None)
    cam, mic = cli.fake_device_factories(True)
    from streambridge.sinks import FakeAudioSink, FakeCameraSink
    assert cam is FakeCameraSink and isinstance(mic(), FakeAudioSink)


def test_status_printer_suppresses_repeats(capsys):
    on = cli.make_status_printer()
    st = lambda fps, state="live": types.SimpleNamespace(kind="video", state=state, warning="", detail="d",  # noqa: E731
                                                         source="640x480", output="Cam", fps=fps)
    on(st(29.0)); on(st(29.0)); on(st(0, "retrying")); on(st(0, "retrying"))
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2 and lines[0].endswith("29.0 fps") and lines[1].startswith("video: retrying")


class FakeSession:
    def __init__(self, fail=False, alive=False):
        self.fail, self._alive, self.stopped = fail, alive, 0

    def start(self):
        if self.fail:
            raise RuntimeError("CABLE Input not found")

    def alive(self):
        return self._alive

    def stop(self):
        self.stopped += 1


def test_run_session_start_failure_is_exit_3(capsys):
    s = FakeSession(fail=True)
    assert cli.run_session(s, FakePlat(), ns(video="v")) == 3 and s.stopped == 1
    assert "CABLE Input not found" in capsys.readouterr().err


def test_run_session_duration(monkeypatch, capsys):
    import signal
    monkeypatch.setattr(signal, "signal", lambda *a: None)
    s = FakeSession(alive=True)
    assert cli.run_session(s, FakePlat(), ns(video="v", audio="a", duration=0.3)) == 0
    out = capsys.readouterr().out
    assert "camera: Cam X" in out and "microphone: Mic Y" in out and "Stopped in" in out and s.stopped == 1


def test_probe_urls_reports_failures(monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError("connection refused")
    monkeypatch.setattr(cli, "probe", boom)
    assert cli.probe_urls(ns(video="http://127.0.0.1:9/v"), "", None) == 1
    assert "video: http://127.0.0.1:9/v: FAILED" in capsys.readouterr().out
    monkeypatch.setattr(cli, "probe", lambda *a, **k: "640x480 h264")
    assert cli.probe_urls(ns(video="http://127.0.0.1:9/v", audio="http://127.0.0.1:9/a"), "", None) == 0


def test_run_reset_declined_and_yes(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert cli.run_reset(False, False) == 1
    assert "Nothing was changed." in capsys.readouterr().out
    assert cli.run_reset(True, True) == 0
    assert "Nothing to remove" in capsys.readouterr().out


def test_main_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "setup_logging", lambda v=False: None)
    monkeypatch.setattr(cli.platform, "current", lambda: FakePlat())
    monkeypatch.setattr(cli, "run_reset", lambda logs, yes: calls.append(("reset", logs, yes)) or 0)
    monkeypatch.setattr(cli, "list_audio_outputs", lambda p, v: calls.append(("list", v)) or 0)
    monkeypatch.setattr(cli, "audio_selftest", lambda p, o, lat: calls.append(("self", o, lat)) or 0)
    monkeypatch.setattr(cli, "stream", lambda a, p: calls.append(("stream", a.video)) or 7)
    assert cli.main(["--reset", "--logs", "--yes"]) == 0
    assert cli.main(["--check"]) == 0                     # FakePlat.check() is empty -> all ok
    assert cli.main(["--list-audio-outputs", "-v"]) == 0
    assert cli.main(["--audio-selftest", "--audio-latency", "stable"]) == 0
    assert cli.main(["--video", "http://x/v"]) == 7
    assert calls == [("reset", True, True), ("list", True), ("self", "auto", "stable"), ("stream", "http://x/v")]


def test_main_without_args_opens_gui(monkeypatch):
    import streambridge.gui as g
    monkeypatch.setattr(g, "run_gui", lambda: 42)
    assert cli.main([]) == 42 and cli.main(["--gui"]) == 42


def test_parser_is_namespace():
    assert isinstance(ns(), argparse.Namespace)

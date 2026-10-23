import sys
import types

import pytest

from streambridge import cli, settings


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    kr = types.ModuleType("keyring"); store = {}
    kr.get_password = lambda s, u: store.get((s, u))
    kr.set_password = lambda s, u, p: store.__setitem__((s, u), p)
    kr.delete_password = lambda s, u: store.pop((s, u))
    monkeypatch.setitem(sys.modules, "keyring", kr)
    return tmp_path, store


def test_reset_removes_only_our_files(home):
    from pathlib import Path
    from streambridge.logging_setup import log_dir
    tmp, store = home
    other = tmp / "config" / "other-app.json"; other.parent.mkdir(parents=True); other.write_text("{}")
    store[("OtherApp", "admin")] = "keep"
    settings.save(dict(settings.DEFAULTS, username="admin", password="pw", remember_password=True,
                       audio_latency="stable", recent_video=["http://10.0.0.2/video"]))
    cli.setup_logging()
    import logging; logging.getLogger("streambridge").info("hello")
    neighbour = Path(log_dir()) / "notes.txt"; neighbour.write_text("mine")
    assert store[("StreamBridge", "admin")] == "pw"

    plan = settings.reset_plan(include_logs=True)
    assert len(plan) == 3 and "keychain" in plan[1]
    removed = settings.reset(include_logs=True)
    assert not settings.config_path().exists()
    assert ("StreamBridge", "admin") not in store and store[("OtherApp", "admin")] == "keep"
    assert other.exists() and neighbour.exists()            # never anything else
    assert not list(Path(log_dir()).glob("streambridge.log*"))
    assert any("settings.json" in r for r in removed)
    assert settings.load()["audio_latency"] == "low" and settings.load()["recent_video"] == []


def test_cli_reset_yes_and_cancel(home, capsys, monkeypatch):
    settings.save(dict(settings.DEFAULTS, audio_latency="normal"))
    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert cli.main(["--reset"]) == 1 and settings.config_path().exists()
    assert cli.main(["--reset", "--yes"]) == 0 and not settings.config_path().exists()
    assert "Removed:" in capsys.readouterr().out


def test_gui_reset_reloads_defaults(home):
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    from streambridge.gui import App
    settings.save(dict(settings.DEFAULTS, audio_latency="stable", video_url="http://10.0.0.2/video"))
    app = App(root); root.update()
    assert app.delay.get().startswith("Stable")
    new = app.do_reset(include_logs=False); root.update()
    assert new.delay.get().startswith("Low") and new.video.get() == ""   # defaults, no restart
    assert not settings.config_path().exists()
    root.destroy()

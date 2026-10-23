"""The Tk window (gui.App) and the Welcome dialog, driven headless (needs a display: real, Xvfb or xvfb-run)."""
import queue
import types

import pytest

tk = pytest.importorskip("tkinter")

from streambridge import gui, settings, urls  # noqa: E402
from streambridge.platform.base import Dependency, Platform  # noqa: E402


class FakePlat(Platform):
    name = "Windows"
    recommended_output = "CABLE Input"
    shows_output_choice = True
    camera_name, mic_name = "Cam X", "Mic Y"

    def __init__(self, ok=True, outputs=("CABLE Input (VB-Audio Virtual Cable)", "Speakers")):
        self.ok, self.outputs = ok, list(outputs)

    def check(self):
        return [Dependency("OBS", "camera", self.ok, "found" if self.ok else "missing", "https://obsproject.com",
                           ["Install OBS", "  winget install OBS"])]

    def audio_outputs(self):
        return self.outputs


@pytest.fixture
def root(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    r.withdraw()
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass


@pytest.fixture
def app(root, monkeypatch):
    monkeypatch.setattr(gui.platform, "current", lambda: FakePlat())
    monkeypatch.setattr(gui, "should_show", lambda c: False)
    msgs = []
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda *a: msgs.append(a[1]))
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a: msgs.append(a[1]) or False)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a: msgs.append(a[1]))
    a = gui.App(root)
    a.msgs = msgs
    return a


def test_outputs_list_recommended_first(app):
    assert app.output.cget("values")[0] == "CABLE Input" + gui.RECOMMENDED_SUFFIX
    assert app.output_value() == "auto"
    app.output.set("Speakers")
    assert app.output_value() == "Speakers"


def test_missing_recommended_output_shows_hint(root, monkeypatch):
    monkeypatch.setattr(gui.platform, "current", lambda: FakePlat(ok=False, outputs=["Speakers"]))
    monkeypatch.setattr(gui, "should_show", lambda c: False)
    a = gui.App(root)
    assert "was not found" in a.output_hint.cget("text")
    assert a.deps.winfo_children()            # setup panel shown for the missing dependency
    a.copy("x"); assert root.clipboard_get() == "x"


def test_collect_validates_and_moves_credentials(app):
    assert app.collect() is None and "Enter the phone's" in app.msgs[-1]
    app.video.set("ftp://x/v")
    assert app.collect() is None and "Video URL" in app.msgs[-1]
    app.video.set("http://bob:pw@192.168.1.5:8080/video")
    app.size.set("1280x720 (720p)")
    o = app.collect()
    assert o.video_url == "http://192.168.1.5:8080/video" and (o.username, o.password) == ("bob", "pw")
    assert o.size == (1280, 720) and app.v_user.get() == "bob"
    saved = settings.load()
    assert saved["video_url"] == "http://192.168.1.5:8080/video" and "pw" not in str(saved["recent_video"])
    app.size.set("huge")
    assert app.collect() is None


def test_fill_audio_and_delay(app):
    app.video.set("http://192.168.1.5:8080/video")
    app.fill_audio()
    assert app.audio.get()
    assert app.delay_value() in ("low", "normal", "stable")


def test_confirm_output_asks_for_speakers(app):
    app.audio.set("http://192.168.1.5:8080/audio.wav")
    app.output.set("Speakers")
    assert app.confirm_output() is False and "play out loud" in app.msgs[-1]
    app.output.set(app.output.cget("values")[0])
    assert app.confirm_output() is True


def test_connect_failure_is_shown_and_logged(app, monkeypatch, caplog):
    class Boom:
        def __init__(self, *a):
            pass

        def start(self):
            raise RuntimeError("CABLE Input not found")

        def stop(self):
            pass
    monkeypatch.setattr(gui, "Session", Boom)
    app.video.set("http://192.168.1.5:8080/video")
    with caplog.at_level("WARNING", logger="streambridge"):
        app.on_connect()
    assert app.session is None and app.msg.cget("text") == "CABLE Input not found"
    assert "connect failed" in caplog.text


def test_connect_disconnect_and_status_poll(app, monkeypatch):
    class Ok:
        def __init__(self, *a):
            self.stopped = False

        def start(self):
            pass

        def stop(self):
            self.stopped = True
    monkeypatch.setattr(gui, "Session", Ok)
    app.video.set("http://192.168.1.5:8080/video")
    app.on_connect()
    assert app.b_conn.cget("text") == "Disconnect"
    st = lambda **k: types.SimpleNamespace(**{"kind": "camera", "state": "live", "source": "640x480", "fps": 30.0,  # noqa: E731
                                              "output": "Cam X", "warning": "", "detail": "", **k})
    for item in (("status", st()), ("status", st(warning="late")), ("status", st(state="stopped")),
                 ("status", st(state="connecting", detail="Connecting")), ("msg", "hello"), ("log", "line"),
                 ("test_done", None)):
        app.q.put(item)
    app.poll()
    assert app.msg.cget("text") == "hello" and "Connecting" in app.status["camera"][1].cget("text")
    s = app.session
    app.on_connect()                  # second click = disconnect
    assert s.stopped and app.session is None and app.b_conn.cget("text") == "Connect"


def test_on_test_reports_each_url(app, monkeypatch):
    def fake_probe(u, kind, strict):
        if kind == "audio":
            raise OSError("refused")
        return "640x480"
    monkeypatch.setattr(gui, "probe", fake_probe)

    class NowThread:
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            self.target()
    monkeypatch.setattr(gui.threading, "Thread", NowThread)
    app.video.set("http://192.168.1.5:8080/video"); app.audio.set("http://192.168.1.5:8080/audio.wav")
    app.on_test()
    items = []
    while True:
        try:
            items.append(app.q.get_nowait())
        except queue.Empty:
            break
    text = dict(i for i in items if i[0] == "msg")["msg"]
    assert "Video: 640x480" in text and "Audio:" in text and ("test_done", None) in items


def test_log_box_toggle_and_copy_log(app, monkeypatch):
    app.v_details.set(True); app.toggle_details()
    app.v_details.set(False); app.toggle_details()
    for i in range(520):
        app.append_log(f"line {i}")
    app.copy_log()
    assert "No log yet" in app.msg.cget("text")
    import os
    os.makedirs(gui.log_dir(), exist_ok=True)
    with open(gui.log_file(), "w") as fh:
        fh.write("http://u:secret@h/x\n")
    app.copy_log()
    assert "secret" not in app.root.clipboard_get() and "Passwords are masked" in app.msg.cget("text")


def test_queue_log_handler_masks(app):
    import logging
    app.log.warning("open %s", "http://u:secret@h/x")
    items = [app.q.get_nowait() for _ in range(app.q.qsize())]
    assert any(k == "log" and "secret" not in v and "***" in v for k, v in items)
    assert all(not isinstance(h, gui._QueueLog) or h.q is app.q for h in logging.getLogger("streambridge").handlers)


def test_welcome_toggle_saved(app):
    app.set_welcome_dont_show(True)
    assert settings.load()["welcome_dont_show"] is True and app.cfg["welcome_dont_show"]


def test_do_reset_reloads_defaults(app):
    app.video.set("http://192.168.1.5:8080/video"); app.collect()
    new = app.do_reset(include_logs=True)
    assert new.video.get() == "" and new.msg.cget("text") == "Reset to defaults done."


def test_about(app):
    app.about()
    assert "Cam X" in app.msgs[-1] and "Mic Y" in app.msgs[-1]


# ---- Welcome / Setup check dialog -----------------------------------------
def test_welcome_dialog_states(root, monkeypatch):
    from streambridge.welcome import dialog
    opened, saved = [], []
    monkeypatch.setattr(dialog.webbrowser, "open", opened.append)
    from streambridge.platform.linux import LinuxPlatform
    plat = LinuxPlatform()
    state = {"ok": False}
    monkeypatch.setattr(plat, "check", lambda: [
        Dependency("v4l2loopback", "camera", state["ok"], "not loaded", "https://example.org/v4l2",
                   ["Load it:", "  sudo modprobe v4l2loopback"]),
        Dependency("pactl", "mic", state["ok"], "", "https://pipewire.org/")])
    d = dialog.WelcomeDialog(root, plat, False, saved.append)
    assert str(d.summary.cget("foreground")) == dialog.RED
    buttons = [w for w in d.win.winfo_children()[0].winfo_children()]  # outer frame exists
    assert buttons
    d._copy("sudo modprobe v4l2loopback")
    assert root.clipboard_get() == "sudo modprobe v4l2loopback" and "Copied" in d.summary.cget("text")

    def walk(w):
        yield w
        for c in w.winfo_children():
            yield from walk(c)
    for w in walk(d.win):
        if isinstance(w, tk.ttk.Button) and w.cget("text") == "Open official page":
            w.invoke()
        if isinstance(w, tk.ttk.Checkbutton):
            w.invoke()
    assert "https://example.org/v4l2" in opened and saved == [True]
    state["ok"] = True
    d.refresh()
    assert str(d.summary.cget("foreground")) == dialog.GREEN and "All set" in d.summary.cget("text")
    d.win.destroy()


def test_urls_mask_used_by_gui():
    assert "secret" not in urls.mask("http://u:secret@h/x")

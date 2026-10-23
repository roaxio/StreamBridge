"""streambridge.logging_setup: paths, masking, handlers; cli keeps the 1.1.1 names."""
import logging

import pytest

from streambridge import cli, gui, logging_setup, settings


def test_log_dir_per_os(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(logging_setup.sys, "platform", "linux")
    assert logging_setup.log_dir() == str(tmp_path / "streambridge")
    monkeypatch.setattr(logging_setup.sys, "platform", "darwin")
    assert logging_setup.log_dir().replace("\\", "/").endswith("Library/Logs/StreamBridge")
    monkeypatch.setattr(logging_setup.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "L"))
    assert logging_setup.log_dir().replace("\\", "/").endswith("L/StreamBridge")


def test_log_file_name(monkeypatch, tmp_path):
    monkeypatch.setattr(logging_setup.sys, "platform", "linux")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert logging_setup.log_file() == str(tmp_path / "streambridge" / "streambridge.log")


def test_mask_filter_masks_msg_and_args():
    r = logging.LogRecord("streambridge", logging.INFO, __file__, 1, "open http://u:secret@h/x %s %d",
                          ("rtsp://a:pw@10.0.0.1/s", 5), None)
    assert logging_setup.MaskFilter().filter(r)
    text = r.getMessage()
    assert "secret" not in text and "pw@" not in text and " 5" in text


def test_setup_logging_without_writable_dir_keeps_console(monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("XDG_STATE_HOME", str(blocker))   # a file, so makedirs fails with OSError
    monkeypatch.setenv("LOCALAPPDATA", str(blocker))
    logging_setup.setup_logging(verbose=True)
    lg = logging.getLogger("streambridge")
    assert len(lg.handlers) == 1 and lg.level == logging.DEBUG


@pytest.mark.parametrize("name", ["_MaskFilter", "log_dir", "log_file", "setup_logging"])
def test_backward_compatible_names_in_cli(name):
    assert getattr(cli, name) is getattr(logging_setup, name)


def test_settings_and_gui_no_longer_import_cli():
    import inspect
    for mod in (settings, gui):
        assert "from .cli" not in inspect.getsource(mod)

"""Logging: where the log file lives, credential masking and handler setup.

Shared by the CLI, the window and settings.reset(); kept separate so none of them
depends on the command-line module."""
from __future__ import annotations

import logging
import os
import sys

from . import urls

LOGGER_NAME = "streambridge"


class MaskFilter(logging.Filter):
    """Masks user:password@ in log messages and string arguments."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = urls.mask(str(record.msg))
        if record.args:
            record.args = tuple(urls.mask(a) if isinstance(a, str) else a for a in record.args)
        return True


_MaskFilter = MaskFilter   # 1.1.1 name


def log_dir() -> str:
    """Windows %LOCALAPPDATA%\\StreamBridge, Linux ~/.local/state/streambridge, macOS ~/Library/Logs/StreamBridge."""
    home = os.path.expanduser("~")
    if sys.platform.startswith("win"):
        return os.path.join(os.environ.get("LOCALAPPDATA", home), "StreamBridge")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Logs", "StreamBridge")
    return os.path.join(os.environ.get("XDG_STATE_HOME", os.path.join(home, ".local", "state")), "streambridge")


def log_file() -> str:
    return os.path.join(log_dir(), "streambridge.log")


def setup_logging(verbose: bool = False) -> None:
    from logging.handlers import RotatingFileHandler
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    h = logging.StreamHandler()
    h.addFilter(MaskFilter())
    h.setFormatter(fmt)
    handlers: list[logging.Handler] = [h]
    try:
        os.makedirs(log_dir(), exist_ok=True)
        fh = RotatingFileHandler(log_file(), maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        fh.addFilter(MaskFilter())   # credentials are masked in the file too
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        handlers.append(fh)
    except OSError:
        pass   # no writable log folder: console only
    root = logging.getLogger(LOGGER_NAME)
    root.handlers[:] = handlers
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    import av.logging
    av.logging.set_level(av.logging.ERROR)

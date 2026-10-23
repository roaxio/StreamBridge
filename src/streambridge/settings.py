"""Remembered settings (JSON). Passwords are never written to disk; with the
optional 'keyring' package and the user's opt-in they go to the OS keychain."""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from . import urls
from .logging_setup import log_dir

log = logging.getLogger("streambridge")
KEYRING_SERVICE = "StreamBridge"
DEFAULTS = {"video_url": "", "audio_url": "", "username": "", "size": "Auto", "fps": 30,
            "strict_tls": False, "remember_password": False, "autoconnect": False,
            "audio_output": "auto", "audio_latency": "low", "recent_video": [], "recent_audio": [],
            "welcome_dont_show": False}


def config_path() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "StreamBridge" / "settings.json"


def _strip_creds(u: str) -> str:
    try:
        p = urls.parse(u)
        return p.display.replace("***@", "") if p.display else u
    except urls.UrlError:
        return urls.mask(u).replace("***@", "")


def keyring_available() -> bool:
    try:
        import keyring  # noqa: F401
        return True
    except Exception as e:  # missing package or a broken keyring backend: just no keychain
        log.debug("keyring unavailable: %s", type(e).__name__)
        return False


def load(path: Path | None = None) -> dict:
    path = path or config_path()
    data = dict(DEFAULTS)
    try:
        data.update({k: v for k, v in json.loads(path.read_text("utf-8")).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    data["password"] = ""
    if data.get("remember_password") and data.get("username") and keyring_available():
        try:
            import keyring
            data["password"] = keyring.get_password(KEYRING_SERVICE, data["username"]) or ""
        except Exception as e:  # any keychain backend error: start without the saved password
            log.warning("keychain: could not read the saved password (%s)", type(e).__name__)
    return data


def save(values: dict, path: Path | None = None) -> None:
    path = path or config_path()
    data = {k: values.get(k, DEFAULTS[k]) for k in DEFAULTS}
    data["video_url"] = _strip_creds(data["video_url"]) if data["video_url"] else ""
    data["audio_url"] = _strip_creds(data["audio_url"]) if data["audio_url"] else ""
    data["recent_video"] = [_strip_creds(u) for u in data["recent_video"]][:8]
    data["recent_audio"] = [_strip_creds(u) for u in data["recent_audio"]][:8]
    if data["remember_password"] and data["username"] and values.get("password") and keyring_available():
        try:
            import keyring
            keyring.set_password(KEYRING_SERVICE, data["username"], values["password"])
        except Exception as e:  # any keychain backend error: don't claim it was remembered
            log.warning("keychain: could not save the password (%s)", type(e).__name__)
            data["remember_password"] = False
    else:
        data["remember_password"] = bool(data["remember_password"] and keyring_available())
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, json.dumps(data, indent=2))


def _atomic_write(path: Path, text: str) -> None:
    """Write via a sibling temp file + fsync + os.replace, so a crash never leaves a half file."""
    import os
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


SIZE_CHOICES = ["Auto (same as phone)", "1920x1080 (1080p)", "1280x720 (720p)", "640x480 (480p)"]


def parse_size(s: str) -> tuple[int, int] | None:
    """'Auto...' -> None; '1280x720 (720p)' / '1280x720' -> (1280, 720); '720p' -> (1280, 720)."""
    import re
    s = (s or "Auto").strip().lower()
    m = re.match(r"^(\d{2,5})\s*x\s*(\d{2,5})", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    named = {"1080p": (1920, 1080), "720p": (1280, 720), "480p": (640, 480)}
    if s in named:
        return named[s]
    if s.startswith("auto") or not s:
        return None
    raise ValueError(f"Camera size must be Auto or WxH, not '{s}'")


def reset_plan(include_logs: bool = False, path: Path | None = None) -> list[str]:
    """Human-readable list of exactly what reset() will remove."""
    path = path or config_path()
    items = [f"Saved settings and recent URLs: {path}"]
    user = load(path).get("username")
    if user and keyring_available():
        items.append(f"Saved password for '{user}' in the system keychain (service '{KEYRING_SERVICE}')")
    if include_logs:
        items.append(f"Log files: {os.path.join(log_dir(), 'streambridge.log*')}")
    return items


def reset(include_logs: bool = False, path: Path | None = None) -> list[str]:
    """Delete only StreamBridge's own data. Returns what was removed. Never touches anything else:
    one settings file, one keychain entry (our service + saved user), our streambridge.log* files,
    and their folders only if they end up empty."""
    import logging
    path = path or config_path()
    removed: list[str] = []
    user = ""
    try:
        user = json.loads(path.read_text("utf-8")).get("username", "")
    except (OSError, ValueError):
        pass
    if user and keyring_available():
        try:
            import keyring
            if keyring.get_password(KEYRING_SERVICE, user) is not None:
                keyring.delete_password(KEYRING_SERVICE, user)
                removed.append(f"keychain: {KEYRING_SERVICE}/{user}")
        except Exception as e:  # any keychain backend error: reset the rest anyway
            log.warning("keychain: could not remove the saved password (%s)", type(e).__name__)
    if path.name == "settings.json" and path.parent.name == "StreamBridge" and path.exists():
        path.unlink()
        removed.append(str(path))
        try:
            path.parent.rmdir()          # only if empty
        except OSError:
            pass
    if include_logs:
        d = Path(log_dir())
        lg = logging.getLogger("streambridge")
        for h in list(lg.handlers):      # close our log file first (Windows can't delete open files)
            if getattr(h, "baseFilename", "").startswith(str(d)):
                h.close(); lg.removeHandler(h)
        for f in sorted(d.glob("streambridge.log*")):
            try:
                f.unlink(); removed.append(str(f))
            except OSError:
                pass
        try:
            d.rmdir()
        except OSError:
            pass
    return removed

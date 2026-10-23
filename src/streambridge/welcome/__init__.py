"""First-run "Welcome / Setup check": plain-words intro + requirement status per OS.

Read-only: it only *checks* (via platform.check()) and shows official links and how-to text.
It never downloads, installs or runs anything with admin rights. One small module per OS.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field

from ..platform.base import Dependency, Platform


@dataclass
class Item:
    title: str                 # "OBS Studio (Virtual Camera)"
    needed_for: str            # "camera" | "mic"
    ok: bool
    status: str                # what was found / missing
    url: str                   # official page only
    howto: list[str] = field(default_factory=list)
    copy: str = ""             # a command the user may copy and run themselves (Linux)


@dataclass
class Report:
    intro: str
    items: list[Item]

    @property
    def all_ok(self) -> bool:
        return all(i.ok for i in self.items)


def _module(os_name: str):
    from . import linux, macos, windows
    return {"Windows": windows, "macOS": macos, "Linux": linux}.get(os_name, linux)


def build(plat: Platform, deps: list[Dependency] | None = None) -> Report:
    """Run the requirement check for this OS and turn it into a welcome report."""
    deps = plat.check() if deps is None else deps
    return _module(plat.name).build(plat, deps)


def os_name() -> str:
    return "Windows" if sys.platform.startswith("win") else "macOS" if sys.platform == "darwin" else "Linux"


def should_show(cfg: dict) -> bool:
    return not cfg.get("welcome_dont_show", False)


__all__ = ["Item", "Report", "build", "should_show", "os_name"]

from __future__ import annotations

from ..platform.base import Dependency
from . import Item

INTRO_BASE = (
    "StreamBridge turns your phone into this computer's camera and microphone.\n"
    "Paste the video and/or audio address that your phone app (for example EZ-Cam) shows, "
    "click Connect, and apps like Zoom, Teams, Discord, OBS or your browser can use it.\n\n"
    "To appear as a camera and a microphone, StreamBridge needs two free helpers that you install once "
    "from their official pages. StreamBridge never downloads or installs anything itself and never asks "
    "for administrator rights (the helpers' own installers may). You only need what you use: "
    "camera-only needs only the camera part."
)


def find(deps: list[Dependency], kind: str) -> Dependency | None:
    return next((d for d in deps if d.needed_for == kind), None)


def item(dep: Dependency | None, title: str, kind: str, url: str, howto: list[str], copy: str = "") -> Item:
    if dep is None:
        return Item(title, kind, False, "Not checked", url, howto, copy)
    return Item(title, kind, dep.ok, dep.detail, dep.url or url, howto, copy)

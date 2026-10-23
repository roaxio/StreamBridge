"""macOS: OBS Studio (Virtual Camera) + BlackHole 2ch."""
from __future__ import annotations

from ..platform.macos import BLACKHOLE_URL, OBS_URL
from . import Report
from .common import INTRO_BASE, find, item

INTRO = INTRO_BASE + "\n\nIn your apps pick camera “OBS Virtual Camera” and microphone “BlackHole 2ch”."


def build(plat, deps) -> Report:
    return Report(INTRO, [
        item(find(deps, "camera"), "OBS Studio (Virtual Camera)", "camera", OBS_URL, [
            "Download OBS for macOS from obsproject.com and move it to Applications.",
            "Open OBS once, click “Start Virtual Camera” and allow the system extension in "
            "System Settings > Privacy & Security. Then quit OBS.",
        ]),
        item(find(deps, "mic"), "BlackHole 2ch", "mic", BLACKHOLE_URL, [
            "Get BlackHole 2ch from existential.audio and run its installer.",
            "Then click Re-check.",
        ]),
    ])

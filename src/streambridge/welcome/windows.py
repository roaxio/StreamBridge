"""Windows: OBS Studio (Virtual Camera) + VB-CABLE."""
from __future__ import annotations

from ..platform.windows import OBS_URL, VBCABLE_URL
from . import Report
from .common import INTRO_BASE, find, item

INTRO = INTRO_BASE + "\n\nIn your apps pick camera “OBS Virtual Camera” and microphone “CABLE Output”."


def build(plat, deps) -> Report:
    return Report(INTRO, [
        item(find(deps, "camera"), "OBS Studio (Virtual Camera)", "camera", OBS_URL, [
            "Download the Windows installer from obsproject.com and run it.",
            "If the camera is still not found: open OBS once, click “Start Virtual Camera”, then “Stop”.",
            "You do not need to keep OBS open.",
        ]),
        item(find(deps, "mic"), "VB-CABLE Virtual Audio Device", "mic", VBCABLE_URL, [
            "Download the VB-CABLE zip from vb-audio.com and unzip it.",
            "Right-click VBCABLE_Setup_x64.exe > Run as administrator > Install Driver (the installer asks; "
            "StreamBridge does not).",
            "Restart the PC, then click Re-check.",
        ]),
    ])

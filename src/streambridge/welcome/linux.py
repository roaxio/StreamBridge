"""Linux: v4l2loopback (camera) + PipeWire/PulseAudio with pactl (microphone)."""
from __future__ import annotations

from ..platform.linux import MODPROBE, PIPEWIRE_URL, V4L2_URL
from . import Report
from .common import INTRO_BASE, find, item

INTRO = INTRO_BASE + ("\n\nIn your apps pick camera “StreamBridge Camera” and microphone "
                      "“StreamBridge Microphone”.")


def build(plat, deps) -> Report:
    return Report(INTRO, [
        item(find(deps, "camera"), "v4l2loopback (virtual camera)", "camera", V4L2_URL, [
            "Install it with your package manager, e.g. Debian/Ubuntu: sudo apt install v4l2loopback-dkms "
            "(Fedora: RPM Fusion v4l2loopback, Arch: v4l2loopback-dkms).",
            "Then load it in a terminal with the command below (copy it; StreamBridge never runs it for you):",
        ], copy=MODPROBE),
        item(find(deps, "mic"), "PipeWire / PulseAudio with pactl (virtual microphone)", "mic", PIPEWIRE_URL, [
            "Most desktops already have this. If not, install pulseaudio-utils and pipewire-pulse "
            "(Arch: libpulse, pipewire-pulse), log out and back in, then click Re-check.",
        ]),
    ])

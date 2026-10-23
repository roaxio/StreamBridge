"""macOS: OBS virtual camera (OBS 30+ camera extension, or 26+ DAL plugin) and BlackHole 2ch."""
from __future__ import annotations

import os

from ..sinks import SoundDeviceSink, find_output_device
from .base import Dependency, Platform

OBS_URL = "https://obsproject.com/download"
BLACKHOLE_URL = "https://existential.audio/blackhole/"
_OBS_PATHS = ("/Applications/OBS.app", os.path.expanduser("~/Applications/OBS.app"))
_DAL = "/Library/CoreMediaIO/Plug-Ins/DAL/obs-mac-virtualcam.plugin"


class MacPlatform(Platform):
    name = "macOS"
    camera_backend = "obs"
    camera_name = "OBS Virtual Camera"
    recommended_output = "BlackHole"
    shows_output_choice = True
    mic_name = "BlackHole 2ch"

    def check(self) -> list[Dependency]:
        obs = any(os.path.exists(p) for p in _OBS_PATHS) or os.path.exists(_DAL)
        cam = Dependency(
            "OBS Studio 26 or newer (provides the virtual camera)", "camera", obs,
            "OBS found" if obs else "OBS Studio is not installed", OBS_URL,
            ["Download OBS for macOS from the official page and move it to Applications.",
             "Open OBS once, click 'Start Virtual Camera' and approve the system extension "
             "(System Settings > Privacy & Security), then quit OBS.",
             "Apps will see the camera as 'OBS Virtual Camera'."])
        idx, _ = find_output_device("BlackHole")
        mic = Dependency(
            "BlackHole 2ch (provides the microphone)", "mic", idx is not None,
            "BlackHole found" if idx is not None else "BlackHole is not installed", BLACKHOLE_URL,
            ["Get BlackHole 2ch from the official Existential Audio page and run the installer.",
             "Pick 'BlackHole 2ch' as the microphone in your app."])
        return [cam, mic]

    def mic_setup(self, output: str | None = None, latency: str | None = None):
        target = output if output and output.lower() != "auto" else self.recommended_output
        idx, _ = find_output_device(target)
        if idx is None:  # no silent fallback to speakers
            raise RuntimeError('BlackHole was not found. Install BlackHole 2ch from https://existential.audio/blackhole/ .' if target == self.recommended_output
                               else f"Audio output '{target}' was not found. Click Refresh and pick again.")
        from ..jitter import mode
        dev_latency = mode(latency).device_s
        return lambda: SoundDeviceSink(target, latency=dev_latency)

    def mic_teardown(self) -> None:
        pass

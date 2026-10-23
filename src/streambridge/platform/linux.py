"""Linux: v4l2loopback for the camera, a PipeWire/PulseAudio virtual source for the mic.

Mic: we load a null sink 'streambridge_out' and remap its monitor into a source
named 'StreamBridge Microphone'. Both modules are unloaded on exit. Nothing else
in the audio setup is touched.
"""
from __future__ import annotations

import glob
import logging
import os
import shutil
import subprocess

from ..sinks import PacatSink
from .base import Dependency, Platform

log = logging.getLogger("streambridge")

SINK = "streambridge_out"
SOURCE = "streambridge_mic"
V4L2_URL = "https://github.com/umlaeute/v4l2loopback#distributions"
PIPEWIRE_URL = "https://pipewire.org/"
MODPROBE = 'sudo modprobe v4l2loopback devices=1 exclusive_caps=1 card_label="StreamBridge Camera"'


def loopback_devices() -> list[str]:
    out = []
    for d in sorted(glob.glob("/sys/class/video4linux/video*")):
        try:
            name = open(os.path.join(d, "name")).read().strip()
        except OSError:
            continue
        drv = os.path.realpath(os.path.join(d, "device", "driver")) if os.path.exists(os.path.join(d, "device")) else ""
        if "loopback" in name.lower() or "streambridge" in name.lower() or "v4l2loopback" in drv or not drv:
            out.append("/dev/" + os.path.basename(d))
    return out


def _pactl(*args: str, timeout: float = 4.0) -> subprocess.CompletedProcess:
    return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=timeout)


def audio_server_ok() -> bool:
    if not shutil.which("pactl") or not shutil.which("pacat"):
        return False
    try:
        return _pactl("info").returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class LinuxPlatform(Platform):
    name = "Linux"
    camera_backend = "v4l2loopback"
    camera_name = "StreamBridge Camera (v4l2loopback)"
    mic_name = "StreamBridge Microphone"

    def __init__(self):
        self._modules: list[str] = []
        self.video_device: str | None = None   # --video-device /dev/videoN

    def check(self) -> list[Dependency]:
        devs = loopback_devices()
        loaded = os.path.exists("/sys/module/v4l2loopback")
        cam = Dependency(
            "v4l2loopback (provides the camera)", "camera", bool(devs),
            f"Loopback camera: {', '.join(devs)}" if devs else
            ("v4l2loopback is loaded but has no device" if loaded else "v4l2loopback is not loaded"),
            V4L2_URL,
            ["Install it (StreamBridge never runs these for you):",
             "  Debian/Ubuntu/Mint:  sudo apt install v4l2loopback-dkms",
             "  Fedora:              sudo dnf install v4l2loopback   (RPM Fusion)",
             "  Arch:                sudo pacman -S v4l2loopback-dkms",
             "Then load it:",
             "  " + MODPROBE,
             "Secure Boot may require signing the module (your distro's DKMS guide)."])
        snd = audio_server_ok()
        mic = Dependency(
            "PipeWire or PulseAudio with pactl/pacat (provides the microphone)", "mic", snd,
            "Audio server reachable" if snd else "pactl/pacat missing or no audio server running",
            PIPEWIRE_URL,
            ["Most desktops already have this. If not:",
             "  Debian/Ubuntu:  sudo apt install pulseaudio-utils pipewire-pulse",
             "  Fedora:         sudo dnf install pulseaudio-utils",
             "  Arch:           sudo pacman -S libpulse pipewire-pulse"])
        return [cam, mic]

    def camera_device(self) -> str | None:
        if self.video_device:
            return self.video_device
        devs = loopback_devices()
        return devs[0] if devs else None

    def _cleanup_stale(self) -> None:
        """Unload our own modules left over from a crashed run (matched by our names only)."""
        try:
            r = _pactl("list", "short", "modules")
        except (OSError, subprocess.TimeoutExpired):
            return
        for line in r.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and (f"sink_name={SINK}" in parts[2] or f"source_name={SOURCE}" in parts[2]):
                _pactl("unload-module", parts[0])

    def mic_setup(self, output: str | None = None, latency: str | None = None):  # output choice is a Windows/macOS feature
        self._cleanup_stale()
        r1 = _pactl("load-module", "module-null-sink", f"sink_name={SINK}",
                    "sink_properties=device.description=StreamBridge-Output", "rate=48000", "channels=2")
        if r1.returncode != 0:
            raise RuntimeError("Could not create the virtual audio sink: " + (r1.stderr.strip() or r1.stdout.strip()))
        self._modules.append(r1.stdout.strip())
        r2 = _pactl("load-module", "module-remap-source", f"master={SINK}.monitor", f"source_name={SOURCE}",
                    'source_properties=device.description="StreamBridge Microphone"')
        if r2.returncode != 0:
            self.mic_teardown()
            raise RuntimeError("Could not create the virtual microphone: " + r2.stderr.strip())
        self._modules.append(r2.stdout.strip())
        log.info("Linux mic ready: source '%s' (modules %s)", SOURCE, self._modules)
        from ..jitter import mode
        ms = {"low": 10, "normal": 20, "stable": 60}[mode(latency).name]
        return lambda: PacatSink(SINK, 48000, 2, latency_msec=ms)

    def mic_teardown(self) -> None:
        for mod in reversed(self._modules):
            try:
                _pactl("unload-module", mod)
            except (OSError, subprocess.TimeoutExpired):
                pass
        self._modules.clear()

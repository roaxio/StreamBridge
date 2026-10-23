"""Windows: OBS Virtual Camera (OBS 26+) for video, VB-CABLE for the microphone."""
from __future__ import annotations

import os

from ..sinks import SoundDeviceSink, find_output_device
from .base import Dependency, Platform

OBS_URL = "https://obsproject.com/download"
VBCABLE_URL = "https://vb-audio.com/Cable/"
# CLSID registered by OBS 26+ for "OBS Virtual Camera" (DirectShow filter).
OBS_VCAM_CLSID = "{A3FCE0F5-3493-419F-958A-ABA1250EC20B}"


def _obs_vcam_registered() -> bool:
    try:
        import winreg
    except ImportError:
        return False
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{OBS_VCAM_CLSID}", 0,
                                           winreg.KEY_READ | view))
            return True
        except OSError:
            continue
    return False


def _obs_installed_path() -> str | None:
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
        p = os.path.join(base, "obs-studio", "bin", "64bit", "obs64.exe") if base else ""
        if p and os.path.exists(p):
            return p
    return None


class WindowsPlatform(Platform):
    name = "Windows"
    camera_backend = "obs"
    camera_name = "OBS Virtual Camera"
    recommended_output = "CABLE Input"
    shows_output_choice = True
    mic_name = "CABLE Output (VB-Audio Virtual Cable)"

    def check(self) -> list[Dependency]:
        vcam = _obs_vcam_registered()
        obs = _obs_installed_path()
        cam = Dependency(
            "OBS Studio 26 or newer (provides the virtual camera)", "camera", vcam,
            "OBS Virtual Camera is installed" if vcam else
            ("OBS found, but its virtual camera is not registered. Open OBS once and click "
             "'Start Virtual Camera', then 'Stop'." if obs else "OBS Studio is not installed"),
            OBS_URL,
            ["Download the Windows installer from the official OBS page and run it.",
             "You do not need to keep OBS open; StreamBridge uses only its virtual camera.",
             "Apps will see the camera as 'OBS Virtual Camera'."])
        idx, _ = find_output_device("CABLE Input")
        mic = Dependency(
            "VB-CABLE Virtual Audio Device (provides the microphone)", "mic", idx is not None,
            "VB-CABLE found ('CABLE Input')" if idx is not None else "VB-CABLE is not installed",
            VBCABLE_URL,
            ["Download the VB-CABLE zip from the official VB-Audio page.",
             "Unzip it, right-click VBCABLE_Setup_x64.exe > Run as administrator > Install Driver.",
             "Restart your PC, then pick 'CABLE Output' as the microphone in your app."])
        return [cam, mic]

    def mic_setup(self, output: str | None = None, latency: str | None = None):
        target = output if output and output.lower() != "auto" else self.recommended_output
        from .. import sdl_audio
        idx, _ = find_output_device(target)
        if idx is None and sdl_audio.find_device(target):
            idx = -1
        if idx is None:  # no silent fallback to speakers
            raise RuntimeError("VB-CABLE's 'CABLE Input' was not found. Install VB-CABLE from https://vb-audio.com/Cable/ (run setup as administrator, then restart), or enable 'CABLE Input' in Sound settings, then Refresh." if target == self.recommended_output
                               else f"Audio output '{target}' was not found. Click Refresh and pick again.")
        from ..jitter import mode
        dev_latency = mode(latency).device_s
        return lambda: open_output(target, dev_latency)

    def mic_teardown(self) -> None:
        pass  # nothing is created on Windows

    def audio_outputs(self) -> list[str]:
        from .. import sdl_audio
        return sdl_audio.list_devices() or super().audio_outputs()


def open_output(target: str, dev_latency):
    """Windows mic output: SDL2/WASAPI shared mode (like ffplay), then PortAudio MME as the last
    fallback (with a yellow warning). PortAudio's WASAPI is not used (fails with GLE 0x492)."""
    import logging
    from .. import sdl_audio
    log = logging.getLogger("streambridge")
    try:
        return _StartFallback(sdl_audio.SdlSink(target), target, dev_latency)
    except Exception as e:
        log.warning("audio output: SDL2 unavailable (%s); using PortAudio MME", e)
        return SoundDeviceSink(target, latency=dev_latency, hostapis=("MME",))


class _StartFallback:
    """Wraps the SDL sink: if SDL can't open/start the device, switch to PortAudio MME at start()."""

    def __init__(self, sink, target, dev_latency):
        self._s, self._target, self._lat = sink, target, dev_latency

    def __getattr__(self, k):
        return getattr(self._s, k)

    def start(self, pull) -> None:
        import logging
        try:
            self._s.start(pull)
        except Exception as e:
            logging.getLogger("streambridge").warning("audio output: SDL2 open failed (%s); using PortAudio MME", e)
            self._s.close()
            self._s = SoundDeviceSink(self._target, latency=self._lat, hostapis=("MME",))
            self._s.start(pull)

    def close(self) -> None:
        self._s.close()

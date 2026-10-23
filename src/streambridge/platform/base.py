"""The one interface every OS implements."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Dependency:
    name: str                 # "OBS Studio (virtual camera)"
    needed_for: str           # "camera" | "mic"
    ok: bool
    detail: str = ""          # what was found / what is missing
    url: str = ""             # official page only; we never download anything
    steps: list[str] = field(default_factory=list)   # manual instructions (commands are shown, never run)


class Platform:
    name = "generic"
    camera_backend: str | None = None     # pyvirtualcam backend
    camera_name = "virtual camera"        # what apps will see
    mic_name = "virtual microphone"       # what apps should pick as microphone

    recommended_output: str | None = None   # device the mic audio is played into ("CABLE Input")
    shows_output_choice = False             # GUI shows the "Audio output" dropdown

    def audio_outputs(self) -> list[str]:
        """Playback devices the mic audio could be sent to (Windows/macOS)."""
        from ..sinks import list_output_devices
        return [d["name"] for d in list_output_devices()]

    def check(self) -> list[Dependency]:
        raise NotImplementedError

    def camera_device(self) -> str | None:
        return None

    def mic_setup(self, output: str | None = None, latency: str | None = None):
        """Prepare the virtual mic and return a factory () -> AudioSink.

        output: None/'auto' = the recommended virtual cable. Never falls back
        silently to other devices: a missing device is an error."""
        raise NotImplementedError

    def mic_teardown(self) -> None:
        """Undo anything mic_setup created (safe to call twice)."""


VIRTUAL_HINTS = ("cable", "voicemeeter", "virtual", "blackhole", "streambridge", "loopback")


def is_virtual_output(name: str) -> bool:
    low = (name or "").lower()
    return any(k in low for k in VIRTUAL_HINTS)


def plays_out_loud(choice: str | None) -> bool:
    """True when the user picked (probably) real speakers/headphones -> ask before using it."""
    return bool(choice) and choice.lower() != "auto" and not is_virtual_output(choice)

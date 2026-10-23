"""SDL2 audio output (Windows: WASAPI shared mode, the same path ffplay uses).

Used on Windows instead of PortAudio's WASAPI, which fails on some PCs with
"WdmSyncIoctl GLE 0x492" for VB-CABLE. SDL opens the endpoint by its name
("CABLE Input (VB-Audio Virtual Cable)") in shared mode, converts our 48 kHz
float32 stereo to the device mix format itself, and pulls audio through a
callback with a small buffer (256 frames ~ 5 ms).
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading

import numpy as np

from .sinks import AudioSink

log = logging.getLogger("streambridge")

_init_lock = threading.Lock()
_sdl = None


def _load():
    """Import PySDL2 (bundled DLL from pysdl2-dll) and init the audio subsystem once."""
    global _sdl
    with _init_lock:
        if _sdl is not None:
            return _sdl
        if sys.platform.startswith("win"):
            os.environ.setdefault("SDL_AUDIODRIVER", "wasapi")
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import sdl2
        if sdl2.SDL_InitSubSystem(sdl2.SDL_INIT_AUDIO) != 0:
            raise RuntimeError("SDL audio init failed: " + sdl2.SDL_GetError().decode(errors="replace"))
        _sdl = sdl2
        return sdl2


def driver() -> str:
    sdl = _load()
    d = sdl.SDL_GetCurrentAudioDriver()
    return d.decode() if d else "?"


def list_devices() -> list[str]:
    try:
        sdl = _load()
    except Exception as e:  # pysdl2 / SDL2.dll missing or broken: no SDL device list
        log.warning("audio output: SDL2 unavailable: %s", e)
        return []
    out = []
    for i in range(sdl.SDL_GetNumAudioDevices(0)):
        n = sdl.SDL_GetAudioDeviceName(i, 0)
        if n:
            out.append(n.decode("utf-8", errors="replace"))
    return out


def find_device(match: str) -> str | None:
    m = match.lower()
    names = list_devices()
    for test in (lambda n: n == m, lambda n: n.startswith(m), lambda n: m in n):
        for n in names:
            if test(n.lower()):
                return n
    return None


class SdlSink(AudioSink):
    backend = "SDL2"

    def __init__(self, device_match: str, rate: int = 48000, channels: int = 2, frames: int = 256):
        self.sdl = _load()
        name = find_device(device_match)
        if name is None:
            raise RuntimeError(f"SDL ({driver()}): audio device '{device_match}' not found")
        self.device_name, self.rate, self.channels, self.frames = name, rate, channels, frames
        self.name = f"{name} [SDL2 {driver()}]"
        self.hostapi = f"SDL2 {driver()}"
        self.warning = ""
        self.dev = 0
        self.errors = 0
        self.last_error = ""
        self._cb = None

    def start(self, pull) -> None:
        sdl = self.sdl
        self.close()
        ch = self.channels
        bpf = 4 * ch

        def cb(_userdata, stream, length):
            n = length // bpf
            try:
                data = np.ascontiguousarray(pull(n), np.float32)
                if data.shape != (n, ch):
                    raise ValueError(f"pull returned {data.shape}, expected {(n, ch)}")
                ctypes.memmove(stream, data.ctypes.data, length)
            except Exception as e:  # never raise into SDL's audio thread
                ctypes.memset(stream, 0, length)
                self.errors += 1
                self.last_error = repr(e)

        self._cb = sdl.SDL_AudioCallback(cb)    # keep a reference: SDL calls it from its thread
        want = sdl.SDL_AudioSpec(self.rate, sdl.AUDIO_F32SYS, ch, self.frames, self._cb)
        have = sdl.SDL_AudioSpec(0, 0, 0, 0)
        dev = sdl.SDL_OpenAudioDevice(self.device_name.encode("utf-8"), 0, ctypes.byref(want),
                                      ctypes.byref(have), 0)   # 0 = no changes: SDL converts for us
        if dev == 0:
            raise RuntimeError("SDL_OpenAudioDevice failed: " + sdl.SDL_GetError().decode(errors="replace"))
        self.dev = dev
        sdl.SDL_PauseAudioDevice(dev, 0)
        self.blocksize = have.samples
        self.latency_ms = 1000.0 * have.samples / have.freq * 2   # SDL double-buffers
        log.info("audio output: backend SDL2 (%s), device '%s', %d Hz, %d ch, float32, buffer %d frames",
                 driver(), self.device_name, have.freq, have.channels, have.samples)

    def close(self) -> None:
        if self.dev:
            try:
                self.sdl.SDL_CloseAudioDevice(self.dev)
            except Exception as e:  # SDL boundary; closing must never raise
                log.debug("audio output: SDL close failed: %s", e)
            self.dev = 0

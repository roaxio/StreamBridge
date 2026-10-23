"""Windows mic output: SDL2 (WASAPI shared, like ffplay) first, PortAudio MME last (with warning)."""
import shutil
import subprocess
import sys
import time

import numpy as np
import pytest

from streambridge import sdl_audio
from streambridge.platform import windows
from streambridge.platform import linux as plinux
from test_windows_output import make_fake_sd


class FakeSDL:
    """Minimal fake of the PySDL2 calls SdlSink uses; drives the callback from a thread."""
    AUDIO_F32SYS = 0x8120
    SDL_INIT_AUDIO = 0x10

    def __init__(self, names=("Speakers (Realtek(R) Audio)", "CABLE Input (VB-Audio Virtual Cable)"), open_ok=True):
        import ctypes, threading
        self.ct, self.th, self.names, self.open_ok = ctypes, threading, list(names), open_ok
        self.opened, self.closed, self.got = [], [], []
        self.SDL_AudioCallback = cb_type = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8), ctypes.c_int)

        class SDL_AudioSpec(ctypes.Structure):
            """Same layout and constructor as sdl2.SDL_AudioSpec, so no real SDL2 is needed."""
            _fields_ = [("freq", ctypes.c_int), ("format", ctypes.c_uint16), ("channels", ctypes.c_uint8),
                        ("silence", ctypes.c_uint8), ("samples", ctypes.c_uint16), ("padding", ctypes.c_uint16),
                        ("size", ctypes.c_uint32), ("callback", cb_type), ("userdata", ctypes.c_void_p)]

            def __init__(self, freq, aformat, channels, samples, callback=cb_type(), userdata=None):
                super().__init__()
                self.freq, self.format, self.channels, self.samples = freq, aformat, channels, samples
                self.callback, self.userdata = callback, userdata

        self.SDL_AudioSpec = SDL_AudioSpec

    def SDL_GetCurrentAudioDriver(self): return b"wasapi"
    def SDL_GetNumAudioDevices(self, _cap): return len(self.names)
    def SDL_GetAudioDeviceName(self, i, _cap): return self.names[i].encode()
    def SDL_GetError(self): return b"WASAPI can't initialize audio client"

    def SDL_OpenAudioDevice(self, name, _cap, want, have, _allow):
        if not self.open_ok:
            return 0
        w = want._obj
        h = have._obj
        h.freq, h.channels, h.samples = w.freq, w.channels, w.samples
        self.opened.append((name.decode(), w.freq, w.channels, w.samples))
        self._cb, self._spec, self._run = w.callback, w, True
        return 7

    def SDL_PauseAudioDevice(self, dev, pause):
        if pause:
            return
        def run():
            n = self._spec.samples
            nbytes = n * 4 * self._spec.channels
            while self._run:
                buf = (self.ct.c_uint8 * nbytes)()
                self._cb(None, buf, nbytes)
                self.got.append(np.frombuffer(bytes(buf), np.float32).reshape(-1, self._spec.channels))
                time.sleep(n / self._spec.freq)
        self.th.Thread(target=run, daemon=True).start()

    def SDL_CloseAudioDevice(self, dev):
        self._run = False
        self.closed.append(dev)


@pytest.fixture
def fake_sdl(monkeypatch):
    def install(**kw):
        f = FakeSDL(**kw)
        monkeypatch.setattr(sdl_audio, "_sdl", f)
        return f
    return install


def tone(n, ch=2):
    return np.full((n, ch), 0.25, np.float32)


def test_sdl_used_first_and_logged(fake_sdl, monkeypatch, caplog):
    sdl = fake_sdl()
    monkeypatch.setitem(sys.modules, "sounddevice", make_fake_sd(wasapi_fails=True))
    with caplog.at_level("INFO", logger="streambridge"):
        sink = windows.open_output("CABLE Input", "low")
        sink.start(lambda n: tone(n)); time.sleep(0.05); sink.close()
    assert sdl.opened == [("CABLE Input (VB-Audio Virtual Cable)", 48000, 2, 256)]
    assert sink.warning == "" and "backend SDL2 (wasapi)" in caplog.text
    assert np.allclose(np.concatenate(sdl.got), 0.25) and sdl.closed == [7]


def test_sdl_open_fails_falls_back_to_mme_with_warning(fake_sdl, monkeypatch, caplog):
    fake_sdl(open_ok=False)
    sd = make_fake_sd(); monkeypatch.setitem(sys.modules, "sounddevice", sd)
    sink = windows.open_output("CABLE Input", "low")
    with caplog.at_level("WARNING", logger="streambridge"):
        sink.start(lambda n: tone(n)); sink.close()
    assert sd.opened[0].api == "MME" and "MME" in sink.warning
    assert "SDL2 open failed" in caplog.text


def test_sdl_missing_device_falls_back_to_mme(fake_sdl, monkeypatch):
    fake_sdl(names=["Speakers"])
    sd = make_fake_sd(); monkeypatch.setitem(sys.modules, "sounddevice", sd)
    sink = windows.open_output("CABLE Input", "low")
    sink.start(lambda n: tone(n)); sink.close()
    assert sd.opened[0].api == "MME"


def test_portaudio_wasapi_never_used_on_windows(fake_sdl, monkeypatch):
    fake_sdl(open_ok=False)
    sd = make_fake_sd(); monkeypatch.setitem(sys.modules, "sounddevice", sd)
    sink = windows.open_output("CABLE Input", "low"); sink.start(lambda n: tone(n)); sink.close()
    assert all(o.api != "Windows WASAPI" for o in sd.opened)


def test_sdl_callback_never_raises(fake_sdl):
    sdl = fake_sdl()
    s = sdl_audio.SdlSink("CABLE Input"); s.start(lambda n: np.zeros((n + 3, 5))); time.sleep(0.05); s.close()
    assert s.errors > 0 and not np.concatenate(sdl.got).any()


@pytest.mark.skipif(not plinux.audio_server_ok() or not shutil.which("parec"), reason="no PulseAudio/PipeWire")
def test_real_sdl_into_linux_virtual_mic(monkeypatch):
    """Real SDL2 (pulse driver) -> StreamBridge-Output null sink -> 'StreamBridge Microphone' -> parec."""
    monkeypatch.setenv("SDL_AUDIODRIVER", "pulse")
    try:
        sdl_audio._load()
    except Exception as e:
        pytest.skip(f"SDL2 not available: {e}")
    p = plinux.LinuxPlatform(); p.mic_setup(); time.sleep(0.3)
    try:
        s = sdl_audio.SdlSink("StreamBridge")
        s.start(lambda n: tone(n))
        rec = subprocess.Popen(["parec", "-d", plinux.SOURCE, "--format=float32le", "--rate=48000", "--channels=1",
                                "--latency-msec=10"], stdout=subprocess.PIPE)
        time.sleep(2); rec.terminate(); y = np.frombuffer(rec.stdout.read(), "<f4"); s.close()
    finally:
        p.mic_teardown()
    assert len(y) > 24000 and abs(float(np.abs(y).max()) - 0.25) < 0.01

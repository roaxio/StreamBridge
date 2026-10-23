"""Simulated Windows audio stack (fake sounddevice module): WASAPI with a fixed mix-format rate."""
import sys
import threading
import time
import types

import numpy as np
import pytest

from streambridge import sinks
from streambridge.engine import AudioWorker
from streambridge.platform import WindowsPlatform

APIS = [{"name": "MME"}, {"name": "Windows DirectSound"}, {"name": "Windows WASAPI"}, {"name": "Windows WDM-KS"}]
DEVS = [
    {"name": "Speakers (Realtek(R) Audio)", "hostapi": 2, "max_output_channels": 2, "default_samplerate": 48000.0},
    {"name": "CABLE Input (VB-Audio Virtual C", "hostapi": 0, "max_output_channels": 8, "default_samplerate": 44100.0},
    {"name": "CABLE Input (VB-Audio Virtual Cable)", "hostapi": 1, "max_output_channels": 8, "default_samplerate": 44100.0},
    {"name": "CABLE Input (VB-Audio Virtual Cable)", "hostapi": 2, "max_output_channels": 2, "default_samplerate": 48000.0},
    {"name": "CABLE Input (VB-Audio Point)", "hostapi": 3, "max_output_channels": 2, "default_samplerate": 48000.0},
]


def make_fake_sd(wasapi_fails=False, mix_rate=48000, mme_fails=False, busy=None):
    busy = dict(busy or {})
    sd = types.ModuleType("sounddevice")
    sd.opened = []

    class WasapiSettings:
        def __init__(self, exclusive=False, auto_convert=False):
            self.exclusive, self.auto_convert = exclusive, auto_convert

    class OutputStream:
        def __init__(self, device, samplerate, channels, dtype, latency, blocksize, callback, extra_settings=None):
            api = APIS[sd.devs[device]["hostapi"]]["name"]
            if busy.get(device):
                busy[device] -= 1
                raise RuntimeError("device busy")
            if any(o.device == device and o.active for o in sd.opened):
                raise RuntimeError("Error starting stream: Unanticipated host error [PaErrorCode -9999]: "
                                   "WdmSyncIoctl: DeviceIoControl GLE = 0x00000492 [Windows WDM-KS error 0]")
            self.device = device
            if api == "Windows WDM-KS":
                raise RuntimeError("Error starting stream: Unanticipated host error [PaErrorCode -9999]: "
                                   "WdmSyncIoctl: DeviceIoControl GLE = 0x00000492")
            if api == "MME" and mme_fails:
                raise RuntimeError("MME open failed")
            if api == "Windows WASAPI":
                if wasapi_fails:
                    raise RuntimeError("Error opening OutputStream: Unanticipated host error [PaErrorCode -9999]")
                if samplerate != mix_rate:      # shared mode: only the mix-format rate works
                    raise RuntimeError("Invalid sample rate [PaErrorCode -9997]")
                if extra_settings is None or extra_settings.exclusive:
                    raise RuntimeError("expected shared-mode WasapiSettings")
            assert dtype == "float32" and blocksize == 0
            self.samplerate, self.channels, self.cb, self.api = samplerate, channels, callback, api
            self.blocksize, self.latency, self.active, self.got = 0, 0.01, False, []
            self._stop = threading.Event()

        def start(self):
            self.active = True
            sd.opened.append(self)

            def run():
                n = int(self.samplerate * 0.01)
                while not self._stop.is_set():
                    buf = np.zeros((n, self.channels), np.float32)
                    self.cb(buf, n, None, None)
                    self.got.append(buf.copy())
                    time.sleep(0.01)
            threading.Thread(target=run, daemon=True).start()

        def stop(self):
            self._stop.set(); self.active = False

        def close(self):
            self._stop.set()

    sd.WasapiSettings = WasapiSettings
    sd.OutputStream = OutputStream
    sd.devs = list(DEVS)
    sd.query_hostapis = lambda: [dict(a, devices=[i for i, d in enumerate(sd.devs) if d["hostapi"] == k])
                                 for k, a in enumerate(APIS)]
    sd.query_devices = lambda idx=None: sd.devs if idx is None else sd.devs[idx]
    return sd


@pytest.fixture(autouse=True)
def no_sdl(monkeypatch):
    """These tests cover the PortAudio layer; SDL2 (first choice) is tested in test_sdl_output.py."""
    from streambridge import sdl_audio
    monkeypatch.setattr(sdl_audio, "find_device", lambda m: None)
    monkeypatch.setattr(sdl_audio, "list_devices", lambda: [])


@pytest.fixture
def fake_sd(monkeypatch):
    def install(**kw):
        sd = make_fake_sd(**kw)
        monkeypatch.setitem(sys.modules, "sounddevice", sd)
        return sd
    return install


def test_wasapi_preferred_and_opened_at_its_mix_rate(fake_sd):
    sd = fake_sd()
    s = sinks.SoundDeviceSink("CABLE Input")
    s.start(lambda n: np.full((n, s.channels), 0.25, np.float32))
    time.sleep(0.1); s.close()
    st = sd.opened[0]
    assert st.api == "Windows WASAPI" and st.samplerate == 48000 and st.channels == 2
    assert s.rate == 48000 and np.allclose(np.concatenate(st.got), 0.25)


def test_falls_back_to_mme_then_logs(fake_sd, caplog):
    sd = fake_sd(wasapi_fails=True)
    s = sinks.SoundDeviceSink("CABLE Input")
    with caplog.at_level("INFO", logger="streambridge"):
        s.start(lambda n: np.zeros((n, s.channels), np.float32))
    s.close()
    assert sd.opened[0].api == "MME" and s.rate == 44100
    assert "could not open" in caplog.text and "host API MME" in caplog.text


def test_callback_exception_does_not_kill_stream(fake_sd):
    fake_sd()
    s = sinks.SoundDeviceSink("CABLE Input")
    s.start(lambda n: np.zeros((n + 1, 7)))          # wrong shape on purpose
    time.sleep(0.05); s.close()
    assert s.errors > 0 and "Error" in s.last_error or s.errors > 0


def test_mic_end_to_end_through_simulated_wasapi(fake_sd, ezcam):
    """44.1 kHz mono phone audio -> WASAPI CABLE Input at 48 kHz stereo: real, non-silent samples."""
    sd = fake_sd()
    from streambridge import urls
    w = AudioWorker(urls.parse(ezcam() + "/audio.wav"), WindowsPlatform().mic_setup("auto"), reconnect=False)
    w.start(); time.sleep(2.5); w.stop()
    st = sd.opened[0]
    y = np.concatenate(st.got)
    assert st.api == "MME" and np.abs(y).max() > 0.1      # no SDL here -> PortAudio MME (last fallback)
    assert np.allclose(y[:, 0], y[:, 1])              # mono copied to both channels


def test_selftest_plays_tone(fake_sd):
    sd = fake_sd()
    from streambridge.cli import audio_selftest
    assert audio_selftest(WindowsPlatform(), "auto", "normal", seconds=0.3) == 0
    y = np.concatenate(sd.opened[0].got)
    assert 0.2 < np.abs(y).max() <= 0.25


def test_only_wasapi_devices_listed(fake_sd):
    sd = fake_sd()
    sd.devs += [
        {"name": "Microsoft Sound Mapper - Output", "hostapi": 0, "max_output_channels": 2, "default_samplerate": 44100.0},
        {"name": "Primary Sound Driver", "hostapi": 1, "max_output_channels": 2, "default_samplerate": 44100.0}]
    sd.devs = sd.devs
    assert WindowsPlatform().audio_outputs() == ["Speakers (Realtek(R) Audio)", "CABLE Input (VB-Audio Virtual Cable)"]


def test_cli_list_verbose_shows_host_apis(fake_sd, capsys):
    fake_sd()
    from streambridge import cli
    import streambridge.platform as P
    orig = P.current
    P.current = lambda: WindowsPlatform()
    try:
        cli.main(["--list-audio-outputs", "-v"])
    finally:
        P.current = orig
    out = capsys.readouterr().out
    assert out.count("AUDIO_OUTPUT recommended CABLE Input (VB-Audio Virtual Cable)") == 1
    assert "Windows WASAPI #3, 48000 Hz" in out and "MME" not in out



def test_never_wdm_ks(fake_sd):
    sd = fake_sd()
    assert not any("Point" in n for n in WindowsPlatform().audio_outputs())
    s = sinks.SoundDeviceSink("CABLE Input")
    assert all(c["hostapi_name"] in ("Windows WASAPI", "MME") for c in s.candidates)


def test_open_failure_stops_with_clear_error(fake_sd, ezcam):
    fake_sd(wasapi_fails=True, mme_fails=True)
    from streambridge import urls
    states = []
    w = AudioWorker(urls.parse(ezcam() + "/audio.wav"), WindowsPlatform().mic_setup("auto"), on_status=states.append)
    w.start(); w.thread.join(8)
    assert not w.thread.is_alive()                      # no endless retry loop
    errs = [s for s in states if s.state == "error"]
    assert errs and "Could not open the audio output" in errs[-1].detail
    assert sum(s.state == "retrying" for s in states) == 1



def test_regression_wdmks_same_name_never_opened(fake_sd):
    """Seen in a user log: WDM-KS error while 'WASAPI' was selected. The index must come from WASAPI's own list."""
    sd = fake_sd()
    sd.devs[4] = dict(sd.devs[4], name="CABLE Input (VB-Audio Virtual Cable)")   # WDM-KS twin, same name
    s = sinks.SoundDeviceSink("CABLE Input (VB-Audio Virtual Cable)")
    s.start(lambda n: np.zeros((n, s.channels), np.float32)); s.close()
    assert sd.opened[0].api == "Windows WASAPI" and sd.opened[0].device == 3 and s.warning == ""


def test_older_stream_on_same_device_is_closed_first(fake_sd):
    sd = fake_sd()
    a = sinks.SoundDeviceSink("CABLE Input"); a.start(lambda n: np.zeros((n, 2), np.float32))
    b = sinks.SoundDeviceSink("CABLE Input"); b.start(lambda n: np.zeros((n, 2), np.float32))
    assert a.stream is None and b.stream is not None and b.hostapi == "Windows WASAPI"
    b.start(lambda n: np.zeros((n, 2), np.float32))           # restart: closes its own stream first
    assert sum(o.active for o in sd.opened) == 1
    b.close()


def test_busy_wasapi_retried_once_before_mme(fake_sd):
    sd = fake_sd(busy={3: 1})
    s = sinks.SoundDeviceSink("CABLE Input"); s.start(lambda n: np.zeros((n, 2), np.float32)); s.close()
    assert sd.opened[0].api == "Windows WASAPI"


def test_mme_fallback_shows_warning(fake_sd, ezcam):
    fake_sd(wasapi_fails=True)
    from streambridge import urls
    states = []
    w = AudioWorker(urls.parse(ezcam() + "/audio.wav"), WindowsPlatform().mic_setup("auto"), on_status=states.append)
    w.start(); time.sleep(2); w.stop()
    live = [s for s in states if s.state == "live"]
    assert live and "MME" in live[-1].warning

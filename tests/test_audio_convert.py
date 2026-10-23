"""The single swresample step used by AudioWorker: any rate / layout -> device rate, float32."""
import av
import numpy as np
import pytest

RATES = [8000, 11025, 16000, 22050, 32000, 44100, 48000, 88200, 96000, 176400, 192000]
LAYOUTS = {"mono": 1, "stereo": 2, "5.1": 6}


def tone_frames(rate, layout, seconds=1.0, hz=440):
    n = int(rate * seconds)
    x = (0.5 * np.sin(2 * np.pi * hz * np.arange(n) / rate)).astype(np.float32)
    ch = LAYOUTS[layout]
    data = np.zeros((ch, n), np.float32)            # planar fltp; tone on the front L/R (or mono) only
    data[:min(ch, 2)] = x
    f = av.AudioFrame.from_ndarray(data, format="fltp", layout=layout)
    f.sample_rate = rate
    return f


@pytest.mark.parametrize("rate", RATES)
@pytest.mark.parametrize("layout", LAYOUTS)
def test_swr_any_rate_any_layout(rate, layout):
    swr = av.AudioResampler(format="flt", layout="stereo", rate=48000)
    out = [f.to_ndarray().reshape(-1, 2) for f in swr.resample(tone_frames(rate, layout))]
    out += [f.to_ndarray().reshape(-1, 2) for f in swr.resample(None)]
    y = np.concatenate(out)
    assert abs(len(y) - 48000) <= 64
    zc = np.count_nonzero(np.diff(np.signbit(y[2000:-2000, 0])))
    assert abs(zc / 2 / ((len(y) - 4000) / 48000) - 440) < 3        # pitch preserved
    assert np.abs(y).max() <= 0.51                  # no gain, no clipping


def test_s16_to_float_is_exact():
    x = np.array([[-32768, -1, 0, 1, 32767]], np.int16)
    f = av.AudioFrame.from_ndarray(x, format="s16", layout="mono"); f.sample_rate = 48000
    y = av.AudioResampler(format="flt", layout="mono", rate=48000).resample(f)[0].to_ndarray().ravel()
    assert np.array_equal(y, x.ravel() / 32768.0)

import numpy as np
import pytest

from streambridge.jitter import MODES, JitterBuffer, mode


def ramp(n, start=0):
    return (np.arange(start, start + n, dtype=np.float32)[:, None] / 1e6).repeat(2, axis=1)


def test_preroll_then_passthrough_bit_exact():
    jb = JitterBuffer(48000, 2, mode("normal"))      # target 2880 frames
    jb.push(ramp(1000))
    assert not jb.pull(240).any()                    # still pre-rolling: silence
    jb.push(ramp(5000, 1000))
    out = jb.pull(240)
    start = 6000 - 2880                              # playback starts exactly `target` behind live
    assert np.array_equal(out, ramp(240, start))     # untouched samples, in order


def test_backlog_is_dropped_to_target():
    jb = JitterBuffer(48000, 2, mode("normal"))
    jb.push(ramp(48000))                             # 1 s arrives at once (phone backlog)
    assert jb.level_ms() == pytest.approx(60, abs=1)
    assert jb.dropped >= 48000 - 2880 - 1


def test_underrun_reprimes():
    jb = JitterBuffer(48000, 2, mode("low"))
    jb.push(ramp(2000)); jb.pull(240)
    for _ in range(10):
        jb.pull(240)
    assert jb.underruns == 1 and not jb.pull(240).any()


@pytest.mark.parametrize("ppm", [-3000, 3000])
def test_drift_is_corrected(ppm):
    """Phone clock 0.3 % fast/slow: level stays near target instead of drifting off."""
    jb = JitterBuffer(48000, 2, mode("normal"))
    per_block = 240 * (1 + ppm / 1e6)
    acc = 0.0
    levels = []
    for i in range(20000):                           # 100 s of 5 ms blocks
        acc += per_block
        n = int(acc); acc -= n
        jb.push(np.full((n, 2), 0.1, np.float32))
        jb.pull(240)
        levels.append(jb.level_ms())
    late = levels[-2000:]
    assert 30 < min(late) and max(late) < 100
    assert jb.dropped <= 300 and jb.underruns <= 1    # only the start-up alignment


def test_modes():
    assert [MODES[m].target_ms for m in ("low", "normal", "stable")] == [30, 60, 150]
    with pytest.raises(ValueError):
        mode("huge")

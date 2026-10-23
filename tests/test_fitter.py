import numpy as np
import pytest

from streambridge.fitter import FrameFitter, auto_size, fit_rect


@pytest.mark.parametrize("src,exp", [((1280, 720), (1280, 720)), ((641, 479), (640, 478)),
                                     ((720, 1280), (720, 1280)), ((3840, 2160), (3840, 2160)),
                                     ((7680, 4320), (3840, 2160)), ((4320, 7680), (2160, 3840)),
                                     ((16, 9), (284, 160)), ((1, 1), (160, 160))])
def test_auto_size(src, exp):
    w, h = auto_size(*src)
    assert (w, h) == exp and w % 2 == 0 and h % 2 == 0


@pytest.mark.parametrize("src", [(1281, 721), (720, 1280), (3840, 2160), (33, 17), (1, 1000)])
@pytest.mark.parametrize("dst", [(1280, 720), (640, 480), (720, 1280)])
def test_fit_rect_inside_and_even(src, dst):
    x, y, w, h = fit_rect(*src, *dst)
    assert 0 <= x and 0 <= y and x + w <= dst[0] and y + h <= dst[1]
    assert w % 2 == 0 and h % 2 == 0
    assert abs(w / h - src[0] / src[1]) / (src[0] / src[1]) < 0.5 or min(w, h) <= 4


def nv12(w, h, y, uv=128):
    a = np.empty((h * 3 // 2, w), np.uint8); a[:h] = y; a[h:] = uv; return a


def test_portrait_in_landscape_pillarbox():
    f = FrameFitter(1280, 720)
    x, y, w, h = f.geometry(720, 1280)
    assert (y, h) == (0, 720) and w == 404 and x == 438 and x % 2 == 0
    out = f.compose(nv12(w, h, 235))
    assert out.shape == (1080, 1280)
    assert (out[:720, :x] == 16).all() and (out[:720, x:x + w] == 235).all() and (out[720:] == 128).all()


def test_rotation_midstream_clears_canvas():
    f = FrameFitter(1280, 720)
    f.geometry(1280, 720); f.compose(nv12(1280, 720, 200, 90))
    x, y, w, h = f.geometry(720, 1280)
    out = f.compose(nv12(w, h, 100))
    assert out[0, 0] == 16 and out[720, 0] == 128  # old landscape pixels gone from the bars


def test_odd_offsets_are_even():
    for src in [(33, 17), (721, 1281), (1, 1000)]:
        x, y, w, h = FrameFitter(642, 482).geometry(*src)
        assert x % 2 == 0 and y % 2 == 0

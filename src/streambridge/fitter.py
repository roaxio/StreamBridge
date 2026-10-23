"""Fit any input frame into the fixed camera size (aspect preserved, black bars)."""
from __future__ import annotations

import numpy as np

MIN_SIDE, MAX_W, MAX_H = 160, 3840, 2160


def even(n: int) -> int:
    return max(2, int(n) // 2 * 2)


def auto_size(src_w: int, src_h: int) -> tuple[int, int]:
    """Camera size for 'Auto': source size, even, clamped into [160, 3840x2160] keeping aspect."""
    w, h = max(1, src_w), max(1, src_h)
    portrait = h > w
    max_w, max_h = (MAX_H, MAX_W) if portrait else (MAX_W, MAX_H)
    scale = min(1.0, max_w / w, max_h / h)
    w, h = w * scale, h * scale
    up = max(1.0, MIN_SIDE / min(w, h))
    w, h = w * up, h * up
    return even(round(w)), even(round(h))


def fit_rect(src_w: int, src_h: int, dst_w: int, dst_h: int) -> tuple[int, int, int, int]:
    """(x, y, w, h): largest aspect-correct rect centred in dst; all values even (NV12 chroma is 2x2)."""
    s = min(dst_w / src_w, dst_h / src_h)
    w = min(dst_w, max(2, even(round(src_w * s))))
    h = min(dst_h, max(2, even(round(src_h * s))))
    return (dst_w - w) // 4 * 2, (dst_h - h) // 4 * 2, w, h


Y_BLACK, UV_NEUTRAL = 16, 128   # limited-range black, as FFmpeg's swscale produces


def black_nv12(w: int, h: int) -> np.ndarray:
    f = np.empty((h * 3 // 2, w), np.uint8)
    f[:h] = Y_BLACK
    f[h:] = UV_NEUTRAL
    return f


class FrameFitter:
    """Letterboxes NV12 frames into the camera size. Only used when the source size differs
    from the camera size; same-size frames go straight to the camera with no copy here.
    Rotation mid-stream (1280x720 -> 720x1280) just changes the rect and clears the bars.
    """

    def __init__(self, dst_w: int, dst_h: int):
        self.dst_w, self.dst_h = even(dst_w), even(dst_h)
        self.canvas = black_nv12(self.dst_w, self.dst_h)
        self._last_src: tuple[int, int] | None = None
        self.rect = (0, 0, self.dst_w, self.dst_h)

    def geometry(self, src_w: int, src_h: int) -> tuple[int, int, int, int]:
        if (src_w, src_h) != self._last_src:
            self._last_src = (src_w, src_h)
            self.rect = fit_rect(src_w, src_h, self.dst_w, self.dst_h)
            self.canvas[:] = black_nv12(self.dst_w, self.dst_h)
        return self.rect

    def compose(self, nv12: np.ndarray) -> np.ndarray:
        """nv12: (h*3/2, w) uint8 already scaled to the rect size from geometry()."""
        x, y, w, h = self.rect
        H = self.dst_h
        self.canvas[y:y + h, x:x + w] = nv12[:h]
        self.canvas[H + y // 2:H + y // 2 + h // 2, x:x + w] = nv12[h:h + h // 2]
        return self.canvas

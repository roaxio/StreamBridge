"""Auto size: a mid-stream size change reopens the camera at the new size (no letterbox)."""
import av
import numpy as np

from streambridge import urls
from streambridge.engine import VideoWorker
from streambridge.sinks import FakeCameraSink


class FakeContainer:
    def __init__(self, sizes):
        self.frames = [av.VideoFrame.from_ndarray(np.full((h, w, 3), 200, np.uint8), format="rgb24")
                       for w, h in sizes]

        class S:  # minimal stream object
            thread_type = None
            class codec_context: name = "fake"
        self.streams = type("Streams", (), {"video": [S()]})()

    def decode(self, _stream):
        return iter(self.frames)


def run(sizes, size=None):
    FakeCameraSink.instances.clear()
    w = VideoWorker(urls.parse("http://127.0.0.1:1/video"), FakeCameraSink, size=size)
    for f in FakeContainer(sizes).frames:          # drive the sender path synchronously
        w._ensure_camera(f.width, f.height)
        w.cam.send(w.convert(f))
    w.cam.close()
    return FakeCameraSink.instances


def test_auto_reopens_on_rotation():
    cams = run([(1280, 720)] * 3 + [(720, 1280)] * 3)
    assert [(c.width, c.height) for c in cams] == [(1280, 720), (720, 1280)]
    assert cams[0].closed and cams[0].frames == 3 and cams[1].frames == 3
    assert (cams[1].last[:1280] > 100).all()          # full picture, no bars


def test_fixed_size_letterboxes_instead():
    cams = run([(1280, 720), (720, 1280)], size=(1280, 720))
    assert len(cams) == 1 and (cams[0].last[:720, :100] == 16).all()

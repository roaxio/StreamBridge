"""A Session ties URLs + platform outputs + workers together (used by GUI and CLI)."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from . import urls
from .engine import AudioWorker, StatusCb, VideoWorker
from .platform import Platform
from .sinks import CameraSink

log = logging.getLogger("streambridge")

STOP_TIMEOUT_S = 2.0   # total time stop() waits for worker threads (shared, not per worker)


@dataclass
class Options:
    video_url: str = ""
    audio_url: str = ""
    username: str = ""
    password: str = ""
    size: tuple[int, int] | None = None   # None = Auto (source size)
    fps: float = 30.0
    strict_tls: bool = False
    timeout_s: float | None = None        # None = 10 s connect / 5 s stall
    reconnect: bool = True
    audio_output: str | None = None       # Windows/macOS: None = recommended virtual cable
    audio_raw: tuple[int, int] | None = None   # headerless PCM16 (rate, channels)
    audio_latency: str = "low"            # Mic delay: low (default) | normal | stable

    def __repr__(self) -> str:
        return (f"Options(video={urls.mask(self.video_url)!r}, audio={urls.mask(self.audio_url)!r}, "
                f"user={'set' if self.username else 'none'}, size={self.size}, fps={self.fps})")


class Session:
    def __init__(self, opts: Options, plat: Platform, on_status: StatusCb | None = None,
                 camera_factory=None, sink_factory=None):
        if not opts.video_url and not opts.audio_url:
            raise urls.UrlError("Enter a video URL, an audio URL, or both")
        self.opts, self.plat = opts, plat
        self.video = urls.parse(opts.video_url, opts.username, opts.password) if opts.video_url else None
        self.audio = urls.parse(opts.audio_url, opts.username, opts.password) if opts.audio_url else None
        self.on_status = on_status
        dev = plat.camera_device()
        self.camera_factory = camera_factory or (
            lambda w, h, fps: CameraSink(w, h, fps, backend=plat.camera_backend, device=dev))
        self._sink_factory = sink_factory
        self.workers = []
        self._mic_ready = False

    def start(self) -> None:
        o = self.opts
        if self.video:
            self.workers.append(VideoWorker(self.video, self.camera_factory, o.size, o.fps, self.on_status,
                                            o.strict_tls, o.timeout_s, o.reconnect))
        if self.audio:
            factory = self._sink_factory
            if factory is None:
                factory = self.plat.mic_setup(o.audio_output, o.audio_latency)
                self._mic_ready = True
            self.workers.append(AudioWorker(self.audio, factory, self.on_status, o.strict_tls,
                                            o.timeout_s, o.reconnect, o.audio_raw, o.audio_latency))
        for w in self.workers:
            w.start()

    def stop(self, timeout: float = STOP_TIMEOUT_S) -> None:
        """Signal all workers, wait for them with ONE shared deadline, then tear the mic down.

        A worker may still be inside av.open (up to its connect timeout); we don't hang the
        GUI for that: after `timeout` seconds total we log a warning and tear down anyway
        (the threads are daemons and exit on their own once av.open returns).
        """
        for w in self.workers:
            w.stop_ev.set()
        for w in self.workers:
            if hasattr(w, "_cv"):
                with w._cv:
                    w._cv.notify_all()
        deadline = time.monotonic() + timeout
        threads = [w.thread for w in self.workers]
        threads += [w._sender for w in self.workers if hasattr(w, "_sender")]
        for t in threads:
            t.join(max(0.0, deadline - time.monotonic()))
        stuck = [t.name for t in threads if t.is_alive()]
        if stuck:
            log.warning("stop: %s still running after %.1fs; continuing teardown", ", ".join(stuck), timeout)
        if self._mic_ready:
            self.plat.mic_teardown()
            self._mic_ready = False

    def alive(self) -> bool:
        return any(w.thread.is_alive() for w in self.workers)

"""Command line: streambridge --video URL --audio URL  (no args -> GUI)."""
from __future__ import annotations

import argparse
import getpass
import logging
import os
import signal
import sys
import threading
import time

from . import __version__, platform, urls
from .engine import probe
from .logging_setup import MaskFilter, _MaskFilter, log_dir, log_file, setup_logging  # noqa: F401 (1.1.1 API)
from .session import Options, Session
from .settings import parse_size


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="streambridge",
                                description="Use a phone's video/audio URL as this computer's camera and microphone.")
    p.add_argument("--version", action="version", version=f"StreamBridge {__version__}")
    p.add_argument("--video", metavar="URL", help="video stream URL, e.g. http://192.168.1.5:8080/video")
    p.add_argument("--audio", metavar="URL", help="audio stream URL, e.g. https://10.0.2.16:4747/audio.wav")
    p.add_argument("--user", default="", help="login name (or put it in the URL)")
    p.add_argument("--password-env", metavar="VAR", help="read the password from this environment variable")
    p.add_argument("--ask-password", action="store_true", help="prompt for the password")
    p.add_argument("--size", default="Auto", help="camera size WxH, 1080p/720p/480p or Auto (default: phone's size)")
    p.add_argument("--audio-output", metavar="NAME", default="auto",
                   help="Windows/macOS: playback device for the mic audio (default: CABLE Input / BlackHole)")
    p.add_argument("--audio-latency", choices=["low", "normal", "stable"], default="low",
                   help="mic delay: low (~30 ms buffer, default), normal (~60 ms), stable (~150 ms, for weak Wi-Fi)")
    p.add_argument("--audio-selftest", action="store_true",
                   help="play a 1 kHz tone into the mic output for 3 s (check the mic meter in Discord)")
    p.add_argument("--list-audio-outputs", action="store_true", help="list playback devices and exit")
    p.add_argument("--audio-raw", metavar="RATE:CH", help="the audio URL is headerless 16-bit PCM, e.g. 16000:1")
    p.add_argument("--video-device", metavar="PATH", help="Linux: v4l2loopback device, e.g. /dev/video10")
    p.add_argument("--fps", type=float, default=30.0)
    p.add_argument("--strict-tls", "--tls-verify", action="store_true", dest="strict_tls",
                   help="verify HTTPS certificates even on the LAN")
    p.add_argument("--timeout", type=float, default=None, help="connect timeout in seconds (default 10; stall 5)")
    p.add_argument("--no-reconnect", action="store_true")
    p.add_argument("--test", action="store_true", help="only test the URLs and exit")
    p.add_argument("--reset", action="store_true",
                   help="reset to defaults: delete saved settings, recent URLs and the saved keychain password")
    p.add_argument("--logs", action="store_true", help="with --reset: also delete StreamBridge's log files")
    p.add_argument("--yes", action="store_true", help="with --reset: don't ask")
    p.add_argument("--check", action="store_true", help="check camera/mic requirements and exit")
    p.add_argument("--duration", type=float, default=0, help="stop after N seconds (0 = until Ctrl+C)")
    p.add_argument("--fake-devices", action="store_true", help=argparse.SUPPRESS)  # tests/smoke runs
    p.add_argument("--gui", action="store_true", help="open the window")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def print_check(plat) -> bool:
    ok_all = True
    print(f"StreamBridge {__version__} on {plat.name}")
    for d in plat.check():
        ok_all &= d.ok
        print(f"  [{'ok' if d.ok else 'MISSING'}] {d.name}: {d.detail}")
        if not d.ok:
            print(f"      Official page: {d.url}")
            for s in d.steps:
                print(f"      {s}")
    return ok_all


def audio_selftest(plat, output: str = "auto", latency: str = "low", seconds: float = 3.0,
                   factory=None) -> int:
    """Plays a 1 kHz tone (-12 dBFS) through exactly the same output path the mic uses."""
    import numpy as np
    try:
        factory = factory or plat.mic_setup(output, latency)
        sink = factory()
    except Exception as e:  # driver/device boundary: report, never a traceback
        logging.getLogger("streambridge").warning("self-test: output open failed: %s", urls.mask(str(e)))
        print(f"Self-test FAILED: {e}", file=sys.stderr)
        plat.mic_teardown()
        return 3
    pos = [0]
    pulled = [0]

    def tone(n):
        t = (pos[0] + np.arange(n)) / sink.rate
        pos[0] += n; pulled[0] += n
        return np.repeat((0.25 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)[:, None], sink.channels, axis=1)
    try:
        sink.start(tone)
        print(f"Playing a 1 kHz tone for {seconds:g} s into: {sink.name} ({sink.rate} Hz, {sink.channels} ch, "
              f"blocksize {getattr(sink, 'blocksize', '?')}, latency {sink.latency_ms:.0f} ms)")
        print(f"Your app's microphone '{plat.mic_name}' should show input now.", flush=True)
        time.sleep(seconds)
    except Exception as e:  # driver/device boundary: report, never a traceback
        logging.getLogger("streambridge").warning("self-test: playback failed: %s", urls.mask(str(e)))
        print(f"Self-test FAILED: {e}", file=sys.stderr)
        return 3
    finally:
        sink.close()
        plat.mic_teardown()
    expected = sink.rate * seconds
    ok = pulled[0] > expected * 0.8
    err = getattr(sink, "last_error", "")
    print(f"Device took {pulled[0]} of ~{int(expected)} samples: {'OK' if ok else 'PROBLEM: the device is not playing'}"
          + (f"; callback error: {err}" if err else ""))
    return 0 if ok else 4


def run_reset(include_logs: bool, assume_yes: bool) -> int:
    """--reset: show exactly what will be removed, ask (unless --yes), remove it."""
    from . import settings
    print("Reset StreamBridge to defaults. This removes only:")
    for item in settings.reset_plan(include_logs):
        print("  - " + item)
    if not assume_yes and input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
        print("Nothing was changed.")
        return 1
    removed = settings.reset(include_logs)
    print("Removed:" if removed else "Nothing to remove (already at defaults).")
    for r in removed:
        print("  " + r)
    return 0


def output_devices(plat) -> list[dict]:
    """Playback devices as dicts; on Windows the SDL2 (WASAPI shared) names the mic really uses."""
    from .sinks import list_output_devices
    devs = list_output_devices()
    if plat.name == "Windows":     # the mic plays through SDL2 (WASAPI shared); list those names
        from . import sdl_audio
        sdl_names = sdl_audio.list_devices()
        if sdl_names:
            drv = sdl_audio.driver()
            devs = [{"name": n, "hostapi_name": f"SDL2 {drv}", "index": i, "default_samplerate": 48000,
                     "max_output_channels": 2} for i, n in enumerate(sdl_names)]
    return devs


def output_tag(plat, name: str) -> str:
    from .platform import is_virtual_output
    if plat.recommended_output and name.lower().startswith(plat.recommended_output.lower()):
        return "recommended"
    return "virtual" if is_virtual_output(name) else "speakers"


def list_audio_outputs(plat, verbose: bool = False) -> int:
    """--list-audio-outputs: one 'AUDIO_OUTPUT <tag> <name>' line per device (parsed by the window/tests)."""
    devs = output_devices(plat)
    for d in devs:
        print(f"AUDIO_OUTPUT {output_tag(plat, d['name'])} {d['name']}")
        if verbose:
            print(f"    {d['hostapi_name']} #{d['index']}, {int(d['default_samplerate'])} Hz, "
                  f"{d['max_output_channels']} ch")
    if not devs:
        print("No playback devices found (PortAudio unavailable?)." if plat.name != "Linux" else
              "Linux uses its own 'StreamBridge Microphone' source; no output choice is needed.")
    return 0


def parse_audio_raw(text: str | None) -> tuple[int, int] | None:
    """'16000:1' -> (16000, 1); None/'' -> None. Raises ValueError if malformed or out of range."""
    if not text:
        return None
    r_, _, c_ = text.partition(":")
    raw = (int(r_), int(c_ or 1))
    if not (4000 <= raw[0] <= 384000 and 1 <= raw[1] <= 8):
        raise ValueError(text)
    return raw


def read_password(a: argparse.Namespace) -> str:
    pwd = os.environ.get(a.password_env, "") if a.password_env else ""
    if a.ask_password:
        pwd = getpass.getpass("Password: ")
    return pwd


def probe_urls(a: argparse.Namespace, pwd: str, raw) -> int:
    """--test: probe each given URL once; 0 if all work, 1 otherwise (bad URL syntax raises UrlError)."""
    from .engine import friendly_error
    rc = 0
    for kind, text in (("video", a.video), ("audio", a.audio)):
        if text:
            u = urls.parse(text, a.user, pwd)
            try:
                print(f"{kind}: {u.display}: {probe(u, kind, a.strict_tls, a.timeout or 10.0, raw)}")
            except Exception as e:  # any network/decoder failure is reported per URL, never a traceback
                logging.getLogger("streambridge").warning("test %s: %s", kind, urls.mask(f'{type(e).__name__}: {e}'))
                print(f"{kind}: {u.display}: FAILED: {friendly_error(e)}")
                rc = 1
    return rc


def fake_device_factories(enabled: bool):
    """--fake-devices (tests/smoke runs): in-memory camera and mic instead of real drivers."""
    if not enabled:
        return None, None
    from .sinks import FakeAudioSink, FakeCameraSink
    return FakeCameraSink, (lambda: FakeAudioSink())


def print_fake_device_report() -> None:
    from .sinks import FakeAudioSink, FakeCameraSink
    for c in FakeCameraSink.instances:
        print(f"fake camera {c.width}x{c.height}: {c.frames} frames")
    for s in FakeAudioSink.instances:
        print(f"fake mic {s.rate} Hz: {s.samples} samples, peak {s.peak:.2f}")


def make_status_printer():
    """Prints each status line once; repeats that differ only in fps are suppressed."""
    last: dict[str, str] = {}

    def on_status(s):
        line = f"{s.kind}: {s.state}{' WARNING: ' + s.warning if s.warning else ''} {s.detail} {s.source} {('-> ' + s.output) if s.output else ''}" \
               f"{(' %.1f fps' % s.fps) if s.fps else ''}".strip()
        if last.get(s.kind) != line.split(" fps")[0]:
            last[s.kind] = line.split(" fps")[0]
            print(line, flush=True)
    return on_status


def run_session(sess, plat, a: argparse.Namespace) -> int:
    """Start, wait for Ctrl+C / SIGTERM / --duration / session end, stop."""
    stop = threading.Event()
    try:
        sess.start()
    except RuntimeError as e:  # e.g. VB-CABLE missing: never fall back silently
        print(f"Error: {e}", file=sys.stderr)
        sess.stop()
        return 3
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
    if a.video:
        print(f"Apps can now pick the camera: {plat.camera_name}")
    if a.audio:
        print(f"Apps can now pick the microphone: {plat.mic_name}")
    print("Press Ctrl+C to stop.", flush=True)
    t_end = time.monotonic() + a.duration if a.duration else None
    while not stop.is_set() and sess.alive():
        stop.wait(0.2)
        if t_end and time.monotonic() > t_end:
            break
    t0 = time.monotonic()
    sess.stop()
    print(f"Stopped in {time.monotonic() - t0:.2f}s.")
    return 0


def stream(a: argparse.Namespace, plat) -> int:
    """Validate the stream options, then --test the URLs or run a session."""
    try:
        raw = parse_audio_raw(a.audio_raw)
    except ValueError:
        print("--audio-raw must be RATE:CHANNELS, e.g. 16000:1", file=sys.stderr)
        return 2
    if a.video_device and hasattr(plat, "video_device"):
        plat.video_device = a.video_device
    from .platform import plays_out_loud
    if a.audio and plays_out_loud(a.audio_output):
        print(f"Note: '{a.audio_output}' looks like real speakers/headphones: the phone audio will play out loud "
              "there and will NOT become a microphone.", file=sys.stderr)
    if not a.video and not a.audio:
        print("Give --video URL and/or --audio URL (or run without arguments for the window).", file=sys.stderr)
        return 2
    pwd = read_password(a)
    try:
        size = parse_size(a.size)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    opts = Options(a.video or "", a.audio or "", a.user, pwd, size, a.fps, a.strict_tls,
                   a.timeout, not a.no_reconnect, a.audio_output, raw, a.audio_latency)
    try:
        if a.test:
            return probe_urls(a, pwd, raw)
        cam_f, sink_f = fake_device_factories(a.fake_devices)
        sess = Session(opts, plat, make_status_printer(), cam_f, sink_f)
    except urls.UrlError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    rc = run_session(sess, plat, a)
    if rc == 0 and a.fake_devices:
        print_fake_device_report()
    return rc


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv == ["--gui"]:
        from .gui import run_gui
        return run_gui()
    a = build_parser().parse_args(argv)
    setup_logging(a.verbose)
    logging.getLogger("streambridge").info("StreamBridge %s, Python %s, %s", __version__,
                                           sys.version.split()[0], sys.platform)
    plat = platform.current()
    if a.reset:
        return run_reset(a.logs, a.yes)
    if a.check:
        return 0 if print_check(plat) else 1
    if a.list_audio_outputs:
        return list_audio_outputs(plat, a.verbose)
    if a.audio_selftest:
        return audio_selftest(plat, a.audio_output, a.audio_latency)
    return stream(a, plat)

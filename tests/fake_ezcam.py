#!/usr/bin/env python3
"""Minimal EZ-Cam-like phone emulator for testing StreamBridge.

Serves, like the phone app does:
  /video      endless multipart MJPEG (multipart/x-mixed-replace)
  /audio.wav  endless WAV (PCM16, header length 0xFFFFFFFF)
Options: --https (self-signed certificate), --user/--password (HTTP Basic auth).
Requires the ffmpeg CLI (used only to generate test pictures/tones).
"""
from __future__ import annotations

import argparse
import base64
import os
import ssl
import struct
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def wav_header(rate: int, channels: int) -> bytes:
    byte_rate = rate * channels * 2
    return (b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + b"WAVE" + b"fmt " +
            struct.pack("<IHHIIHH", 16, 1, channels, rate, byte_rate, channels * 2, 16) +
            b"data" + struct.pack("<I", 0xFFFFFFFF))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    auth: str | None = None
    size = "640x480"
    rate = 44100
    channels = 1

    def log_message(self, *args) -> None:  # keep test output quiet
        pass

    def _authorized(self) -> bool:
        if not self.auth:
            return True
        if self.headers.get("Authorization", "") == "Basic " + self.auth:
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="EZ-Cam"')
        self.end_headers()
        return False

    def _pump(self, cmd: list[str], content_type: str, prefix: bytes = b"") -> None:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if prefix:
                self.wfile.write(prefix)
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass
        finally:
            proc.kill()
            proc.wait()

    t0 = 0.0          # wall-clock "capture" time of sample 0 of the latest /bursts.wav connection
    backlog_ms = 0
    drift_ppm = 0
    burst_rate = 48000

    def _bursts(self) -> None:
        """Latency probe: endless mono PCM16 WAV made in Python (no ffmpeg), real-time paced.

        Every 1 s of capture time there is a 30 ms tone; burst k uses 500 + 100*(k % 8) Hz so the
        receiver can tell bursts apart. --backlog-ms sends that much *old* audio at once on connect
        (like a phone app's own buffer); --drift-ppm makes the phone clock run fast.
        """
        import time
        import numpy as np
        rate = self.burst_rate
        speed = 1 + self.drift_ppm / 1e6                      # phone samples per PC-second / rate
        now = time.time()
        Handler.t0 = now - self.backlog_ms / 1000.0           # capture time of sample 0
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.end_headers()
        self.wfile.write(wav_header(rate, 1))
        sent = 0
        chunk = rate // 100                                   # 10 ms per write
        try:
            while True:
                # samples "captured" up to now on the phone's clock
                avail = int((time.time() - Handler.t0) * rate * speed)
                if avail - sent < chunk:
                    time.sleep(0.002); continue
                n = (avail - sent) // chunk * chunk
                i = np.arange(sent, sent + n)
                t = i / rate
                k = (i // rate)
                f = 500 + 100 * (k % 8)
                on = (i % rate) < int(0.03 * rate)
                x = np.where(on, 0.5 * np.sin(2 * np.pi * f * t), 0.0)
                self.wfile.write((x * 32767).astype("<i2").tobytes())
                self.wfile.flush()
                sent += n
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass

    t0v = 0.0

    def _tsvideo(self) -> None:
        """Latency probe: MJPEG at 30 fps, frame n shows n as 16 black/white blocks; frame n is
        'captured' at t0v + n/30. --backlog-ms sends that many old frames at once on connect."""
        import time
        import av
        import numpy as np
        fps, w, h = 30, 320, 240
        enc = av.CodecContext.create("mjpeg", "w")
        enc.width, enc.height, enc.pix_fmt = w, h, "yuvj420p"
        enc.time_base = __import__("fractions").Fraction(1, fps)
        Handler.t0v = time.time() - self.backlog_ms / 1000.0
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace;boundary=ffmpeg")
        self.end_headers()
        n = 0
        try:
            while True:
                due = Handler.t0v + n / fps
                d = due - time.time()
                if d > 0:
                    time.sleep(d)
                img = np.zeros((h, w, 3), np.uint8)
                for b in range(16):
                    if (n >> b) & 1:
                        img[40:200, b * 20:(b + 1) * 20] = 255
                f = av.VideoFrame.from_ndarray(img, format="rgb24").reformat(format="yuvj420p")
                for pkt in enc.encode(f):
                    data = bytes(pkt)
                    self.wfile.write(b"--ffmpeg\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n")
                    self.wfile.flush()
                n += 1
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass

    def do_GET(self) -> None:
        if not self._authorized():
            return
        if self.path.startswith("/video"):
            self._pump(["ffmpeg", "-loglevel", "error", "-re", "-f", "lavfi", "-i",
                        f"testsrc=size={self.size}:rate=30", "-f", "mpjpeg", "-q:v", "6", "pipe:1"],
                       "multipart/x-mixed-replace;boundary=ffmpeg")
        elif self.path.startswith("/audio.wav"):
            self._pump(["ffmpeg", "-loglevel", "error", "-re", "-f", "lavfi", "-i",
                        f"sine=frequency=440:sample_rate={self.rate}", "-ac", str(self.channels), "-flush_packets", "1", "-f", "s16le", "pipe:1"],
                       "audio/wav", wav_header(self.rate, self.channels))
        elif self.path.startswith("/bursts.wav"):
            self._bursts()
        elif self.path.startswith("/tsvideo"):
            self._tsvideo()
        elif self.path.startswith("/t0v"):
            body = repr(Handler.t0v).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/t0"):
            body = repr(Handler.t0).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4747)
    ap.add_argument("--https", action="store_true")
    ap.add_argument("--user")
    ap.add_argument("--password")
    ap.add_argument("--size", default="640x480")
    ap.add_argument("--rate", type=int, default=44100)
    ap.add_argument("--backlog-ms", type=int, default=0)
    ap.add_argument("--drift-ppm", type=int, default=0)
    ap.add_argument("--channels", type=int, default=1)
    args = ap.parse_args()
    if args.user is not None:
        Handler.auth = base64.b64encode(f"{args.user}:{args.password or ''}".encode()).decode()
    Handler.size = args.size
    Handler.rate, Handler.channels = args.rate, args.channels
    Handler.backlog_ms, Handler.drift_ppm = args.backlog_ms, args.drift_ppm
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    if args.https:
        tmp = tempfile.mkdtemp()
        cert, key = os.path.join(tmp, "c.pem"), os.path.join(tmp, "k.pem")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-subj", "/CN=ezcam-phone", "-keyout", key, "-out", cert],
                       check=True, capture_output=True)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
    print(f"fake EZ-Cam on {'https' if args.https else 'http'}://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

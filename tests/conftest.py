import os
import shutil
import socket
import subprocess
import sys
import time

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)  # latency_meter


def free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture(autouse=True)
def isolate_env(tmp_path_factory, monkeypatch):
    env_dir = tmp_path_factory.mktemp("env")
    cfg = env_dir / "config"
    state = env_dir / "state"
    cfg.mkdir(exist_ok=True)
    state.mkdir(exist_ok=True)
    monkeypatch.setenv("APPDATA", str(cfg))
    monkeypatch.setenv("LOCALAPPDATA", str(state))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    monkeypatch.setenv("XDG_STATE_HOME", str(state))


@pytest.fixture
def ezcam():
    """Start the fake EZ-Cam phone server: ezcam(**opts) -> base URL."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg CLI not available")
    procs = []

    def start(https=False, user=None, password=None, size="640x480", rate=44100, channels=1, backlog_ms=0):
        if https and not shutil.which("openssl"):
            pytest.skip("openssl CLI not available for HTTPS test")
        port = free_port()
        cmd = [sys.executable, os.path.join(HERE, "fake_ezcam.py"), "--port", str(port), "--size", size,
               "--rate", str(rate), "--channels", str(channels), "--backlog-ms", str(backlog_ms)]
        if https:
            cmd.append("--https")
        if user:
            cmd += ["--user", user, "--password", password or ""]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
        procs.append(p)
        p.stdout.readline()
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), 0.2).close(); break
            except OSError:
                time.sleep(0.1)
        return f"{'https' if https else 'http'}://127.0.0.1:{port}"
    yield start
    for p in procs:
        p.kill(); p.wait()

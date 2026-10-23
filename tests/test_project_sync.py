"""Guards for things written in more than one place: the version and the runtime dependencies.

The version lives only in src/streambridge/__init__.py. pyproject reads it (dynamic), the specs,
build scripts, GUI and CLI read __version__, and release.yml checks the tag against it. These tests
fail if a hardcoded StreamBridge version sneaks back into a tracked file.
"""
import re
import subprocess
from importlib import metadata
from pathlib import Path

import pytest

import streambridge

ROOT = Path(__file__).resolve().parent.parent
VERSION_RE = re.compile(r"StreamBridge[ -]v?(\d+\.\d+\.\d+)")


def tracked_text_files():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    for name in out.splitlines():
        p = ROOT / name
        if p.name != "CHANGELOG.md" and p.suffix not in {".png", ".ico", ".icns"} and p.is_file():
            yield p


def test_pyproject_reads_version_from_package():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^dynamic = \["version"\]', text, re.M)
    assert 'version = { attr = "streambridge.__version__" }' in text
    assert not re.search(r'^version = "', text, re.M), "version must not be hardcoded in pyproject.toml"


def test_installed_metadata_matches():
    try:
        assert metadata.version("streambridge") == streambridge.__version__
    except metadata.PackageNotFoundError:
        pytest.skip("streambridge is not installed")


def test_no_stale_version_in_tracked_files():
    stale = [f"{p.relative_to(ROOT)}: {m.group(0)}"
             for p in tracked_text_files()
             for m in VERSION_RE.finditer(p.read_text(encoding="utf-8", errors="ignore"))
             if m.group(1) != streambridge.__version__]
    assert not stale, f"hardcoded version differs from __version__ {streambridge.__version__}: {stale}"


def runtime_deps(lines):
    deps = set()
    for line in lines:
        line = line.split("#", 1)[0].strip().strip('",')
        if line:
            deps.add(line.replace(" ", ""))
    return deps


def test_requirements_txt_matches_pyproject():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"^dependencies = \[\n(.*?)^\]", text, re.M | re.S).group(1)
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert runtime_deps(req) == runtime_deps(block.splitlines()), "requirements.txt is out of sync with pyproject"

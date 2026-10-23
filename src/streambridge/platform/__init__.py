"""Per-OS integration. All modules are import-safe on every OS (static imports for PyInstaller)."""
from __future__ import annotations

import sys

from .base import Dependency, Platform, is_virtual_output, plays_out_loud
from .linux import LinuxPlatform
from .macos import MacPlatform
from .windows import WindowsPlatform


def current() -> Platform:
    if sys.platform.startswith("win"):
        return WindowsPlatform()
    if sys.platform == "darwin":
        return MacPlatform()
    return LinuxPlatform()


__all__ = ["Dependency", "Platform", "is_virtual_output", "plays_out_loud", "current", "LinuxPlatform", "MacPlatform", "WindowsPlatform"]

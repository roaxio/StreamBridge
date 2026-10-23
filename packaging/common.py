"""Shared PyInstaller settings, used by the per-OS spec files.

Collects the native libraries that ship inside the wheels:
  av            -> FFmpeg libs (av.libs / *.dll / *.dylib)
  sounddevice   -> PortAudio (_sounddevice_data on Windows/macOS)
  pyvirtualcam  -> its native OBS / v4l2loopback backends
  sdl2/sdl2dll  -> SDL2.dll for the Windows mic output (WASAPI shared mode)
"""
import os
import re
import sys
from PyInstaller.utils.hooks import collect_all

NAME = "StreamBridge"


def read_version():
    """__version__ from src/streambridge/__init__.py, the one place the version is written."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "streambridge", "__init__.py")
    with open(path, encoding="utf-8") as f:
        return re.search(r'^__version__ = "([^"]+)"', f.read(), re.M).group(1)


VERSION = read_version()


def windows_version_info():
    """Version resource for StreamBridge.exe (Properties -> Details), built from VERSION."""
    from PyInstaller.utils.win32 import versioninfo as vi
    nums = (tuple(int(n) for n in re.findall(r"\d+", VERSION)[:3]) + (0, 0, 0, 0))[:4]
    strings = [vi.StringStruct(k, v) for k, v in [
        ("CompanyName", "StreamBridge contributors"), ("FileDescription", NAME), ("FileVersion", VERSION),
        ("InternalName", NAME), ("LegalCopyright", "MIT License"), ("OriginalFilename", NAME + ".exe"),
        ("ProductName", NAME), ("ProductVersion", VERSION)]]
    return vi.VSVersionInfo(ffi=vi.FixedFileInfo(filevers=nums, prodvers=nums),
                            kids=[vi.StringFileInfo([vi.StringTable("040904B0", strings)]),
                                  vi.VarFileInfo([vi.VarStruct("Translation", [1033, 1200])])])


def collected():
    datas, binaries, hidden = [], [], []
    for pkg in ("av", "pyvirtualcam", "sounddevice", "_sounddevice_data", "numpy", "sdl2", "sdl2dll"):
        try:
            d, b, h = collect_all(pkg)
        except Exception:
            continue
        datas += d; binaries += b; hidden += h
    hidden += ["streambridge.platform.windows", "streambridge.platform.linux", "streambridge.platform.macos", "streambridge.sdl_audio",
               "streambridge.welcome.windows", "streambridge.welcome.linux", "streambridge.welcome.macos", "streambridge.welcome.dialog",
               "tkinter", "certifi", "keyring"]
    return datas, binaries, hidden


def onefile_requested():
    # `pyinstaller x.spec -- --onefile`: PyInstaller hands the args after "--" to the spec as sys.argv[1:]
    return "--onefile" in sys.argv[1:]

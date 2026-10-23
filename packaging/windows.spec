# -*- mode: python -*-
# PyInstaller spec for windows. Build from the venv:
#   pyinstaller packaging/windows.spec                (one-folder: dist/StreamBridge/)
#   pyinstaller packaging/windows.spec -- --onefile   (one-file:   dist/StreamBridge.exe)
import os, sys
sys.path.insert(0, os.path.join(SPECPATH))
from common import NAME, collected, onefile_requested, windows_version_info

datas, binaries, hidden = collected()
a = Analysis([os.path.join(SPECPATH, "entry.py")], pathex=[os.path.join(os.path.dirname(SPECPATH), "src")],
             datas=datas, binaries=binaries, hiddenimports=hidden,
             excludes=["pytest", "PyInstaller"], noarchive=False)
pyz = PYZ(a.pure)
CONSOLE = False   # Windows/macOS: windowed; CLI still works from a terminal
if onefile_requested():
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name=NAME, console=CONSOLE, upx=False,
              version=windows_version_info())
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=CONSOLE, upx=False,
              version=windows_version_info())
    coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)


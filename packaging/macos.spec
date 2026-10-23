# -*- mode: python -*-
# PyInstaller spec for macos. Build from the venv:
#   pyinstaller packaging/macos.spec                (one-folder: dist/StreamBridge/)
#   pyinstaller packaging/macos.spec -- --onefile   (one-file:   dist/StreamBridge)
import os, sys
sys.path.insert(0, os.path.join(SPECPATH))
from common import NAME, VERSION, collected, onefile_requested

datas, binaries, hidden = collected()
a = Analysis([os.path.join(SPECPATH, "entry.py")], pathex=[os.path.join(os.path.dirname(SPECPATH), "src")],
             datas=datas, binaries=binaries, hiddenimports=hidden,
             excludes=["pytest", "PyInstaller"], noarchive=False)
pyz = PYZ(a.pure)
CONSOLE = False   # Windows/macOS: windowed; CLI still works from a terminal
if onefile_requested():
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name=NAME, console=CONSOLE, upx=False)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=CONSOLE, upx=False)
    coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)
    app = BUNDLE(coll, name=NAME + ".app", bundle_identifier="io.github.roaxio.streambridge", version=VERSION,
                 info_plist={"NSMicrophoneUsageDescription": "StreamBridge does not record; it plays phone audio.",
                             "NSCameraUsageDescription": "StreamBridge publishes a virtual camera."})

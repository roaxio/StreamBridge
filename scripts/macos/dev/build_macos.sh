#!/usr/bin/env bash
# Build StreamBridge.app (and a one-file binary) on a Mac from the venv. Not tested on real macOS yet.
set -euo pipefail
cd "$(dirname "$0")/../../.."
pause_once() {
  if [ "${STREAMBRIDGE_NO_PAUSE:-}" = "1" ] || [ ! -t 0 ]; then return 0; fi
  read -r -p "Press Enter to continue (Ctrl+C to cancel)..." _
  echo
}
run() { echo "+ $*" >&2; "$@"; }
trap 'rc=$?; [ $rc -eq 0 ] || echo "BUILD FAILED (exit $rc). See the messages above."' EXIT
cat <<'TXT'
=== StreamBridge: build_macos.sh (developer build, folder + single file) ===
This script will:
  1. Go to the repo's top folder and create .venv if it doesn't exist.
  2. Install StreamBridge with its dev tools into .venv (pip install -e ".[dev,keyring]").
  3. Build the folder version with PyInstaller (packaging/macos.spec) into dist/onedir.
  4. Build the single-file version the same way into dist/onefile.
TXT
pause_once
echo "[1/3] Preparing .venv ..."
[ -x .venv/bin/python ] || run python3 -m venv .venv
run .venv/bin/python -m pip install -q -e ".[dev,keyring]"
echo "[2/3] Building folder version (onedir) ..."
run .venv/bin/pyinstaller --noconfirm --clean --distpath dist/onedir --workpath build/onedir packaging/macos.spec
echo "[3/3] Building single-file version (onefile) ..."
run .venv/bin/pyinstaller --noconfirm --clean --distpath dist/onefile --workpath build/onefile packaging/macos.spec -- --onefile
echo "BUILD OK. Built: dist/onedir/StreamBridge.app and dist/onefile/StreamBridge"

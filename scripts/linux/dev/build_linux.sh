#!/usr/bin/env bash
# Build a standalone Linux app from the venv: dist/StreamBridge/ (folder) and dist/StreamBridge (one file).
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
=== StreamBridge: build_linux.sh (developer build, folder + single file) ===
This script will:
  1. Go to the repo's top folder and create .venv if it doesn't exist.
  2. Install StreamBridge with its dev tools into .venv (pip install -e ".[dev,keyring]").
  3. Build the folder version with PyInstaller (packaging/linux.spec) into dist/onedir.
  4. Build the single-file version the same way into dist/onefile.
  5. Run both builds with --version to check they start.
TXT
pause_once
echo "[1/4] Preparing .venv ..."
[ -x .venv/bin/python ] || run python3 -m venv .venv
run .venv/bin/python -m pip install -q -e ".[dev,keyring]"
echo "[2/4] Building folder version (onedir) ..."
run .venv/bin/pyinstaller --noconfirm --clean --distpath dist/onedir --workpath build/onedir packaging/linux.spec
echo "[3/4] Building single-file version (onefile) ..."
run .venv/bin/pyinstaller --noconfirm --clean --distpath dist/onefile --workpath build/onefile packaging/linux.spec -- --onefile
echo "[4/4] Checking both builds start ..."
run dist/onefile/StreamBridge --version
run dist/onedir/StreamBridge/StreamBridge --version
echo "BUILD OK. Built: dist/onedir/StreamBridge/StreamBridge and dist/onefile/StreamBridge"

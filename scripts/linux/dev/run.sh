#!/usr/bin/env bash
# Linux/macOS: create/use ./.venv and start StreamBridge (window, or pass CLI flags).
set -euo pipefail
cd "$(dirname "$0")/../../.."
pause_once() {
  if [ "${STREAMBRIDGE_NO_PAUSE:-}" = "1" ] || [ ! -t 0 ]; then return 0; fi
  read -r -p "Press Enter to continue (Ctrl+C to cancel)..." _
  echo
}
run() { echo "+ $*" >&2; "$@"; }
cat <<'TXT'
=== StreamBridge: run.sh (start the app from source) ===
This script will:
  1. Go to the repo's top folder.
  2. If .venv doesn't exist yet: check Python is 3.10-3.13, create .venv,
     upgrade pip and install StreamBridge into it (pip install -e .).
  3. Start StreamBridge (the window, or the CLI if you passed flags).
TXT
pause_once
PY="${PYTHON:-python3}"
if [ ! -x .venv/bin/python ]; then
  echo "[1/2] Creating Python virtual environment in .venv ..."
  run "$PY" -c 'import sys; assert (3,10) <= sys.version_info[:2] <= (3,13), "Python 3.10-3.13 needed"'
  run "$PY" -m venv .venv
  run .venv/bin/python -m pip install --upgrade pip >/dev/null
  run .venv/bin/python -m pip install -e .
else
  echo "[1/2] .venv already exists, skipping setup."
fi
echo "[2/2] Starting StreamBridge ..."
echo "+ .venv/bin/python -m streambridge $*"
exec .venv/bin/python -m streambridge "$@"

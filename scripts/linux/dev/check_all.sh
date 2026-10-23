#!/usr/bin/env bash
# Lint, test and build the standalone app for this OS, before you push.
set -euo pipefail
cd "$(dirname "$0")/../../.."
pause_once() {
  if [ "${STREAMBRIDGE_NO_PAUSE:-}" = "1" ] || [ ! -t 0 ]; then return 0; fi
  read -r -p "Press Enter to continue (Ctrl+C to cancel)..." _
  echo
}
run() { echo "+ $*" >&2; "$@"; }
trap 'rc=$?; [ $rc -eq 0 ] || echo "CHECKS FAILED (exit $rc). See the messages above."' EXIT
cat <<'TXT'
=== StreamBridge: check_all.sh (lint + tests + build, before you push) ===
This script will:
  1. Go to the repo's top folder, create .venv if needed and install
     StreamBridge with its dev tools (pip install -e ".[dev,keyring]").
  2. Lint the code with ruff.
  3. Run the full test suite with pytest.
  4. Run this OS's dev build script (folder + single-file builds):
     scripts/linux/dev/build_linux.sh, or scripts/macos/dev/build_macos.sh on a Mac.
It stops at the first failure. You are asked to continue only once.
TXT
pause_once
export STREAMBRIDGE_NO_PAUSE=1
echo "[1/4] Preparing .venv ..."
[ -x .venv/bin/python ] || run python3 -m venv .venv
run .venv/bin/python -m pip install -q -e ".[dev,keyring]"
echo "[2/4] Linting (ruff) ..."
run .venv/bin/ruff check .
echo "[3/4] Running tests (pytest) ..."
run .venv/bin/python -m pytest -q
echo "[4/4] Building ..."
case "$(uname -s)" in
  Darwin) run scripts/macos/dev/build_macos.sh ;;
  *)      run scripts/linux/dev/build_linux.sh ;;
esac
echo "All checks passed."

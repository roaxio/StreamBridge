#!/usr/bin/env bash
# macOS entry point: delegates to the shared scripts/linux/dev/check_all.sh,
# which detects Darwin and runs scripts/macos/dev/build_macos.sh.
set -e
echo "macOS check_all: running the shared scripts/linux/dev/check_all.sh (it explains each step and asks once)."
exec "$(dirname "$0")/../../linux/dev/check_all.sh" "$@"

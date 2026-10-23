#!/usr/bin/env bash
# Single-file Linux build, same as .github/workflows/release.yml (reference for the GitHub release):
#   dist/StreamBridge  +  release_assets/StreamBridge-v<version>-linux-x64.tar.gz
# For the developer onedir+onefile build see scripts/linux/dev/build_linux.sh.
set -euo pipefail
cd "$(dirname "$0")/../.."
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install -q -e ".[dev,keyring]"
.venv/bin/pyinstaller --noconfirm --clean --distpath dist --workpath build packaging/linux.spec -- --onefile
dist/StreamBridge --version
TAG="v$(.venv/bin/python -c 'import streambridge; print(streambridge.__version__)')"
NAME="StreamBridge-${TAG}-linux-x64.tar.gz"
STAGE="stage/StreamBridge-${TAG}"
rm -rf stage && mkdir -p release_assets "$STAGE"
cp dist/StreamBridge packaging/user/linux/READ-ME-FIRST.txt packaging/user/linux/start-streambridge.sh "$STAGE/"
chmod +x "$STAGE/StreamBridge" "$STAGE/start-streambridge.sh"
tar -C stage -czf "release_assets/$NAME" "StreamBridge-${TAG}"
rm -rf stage
echo "Built: dist/StreamBridge and release_assets/$NAME"

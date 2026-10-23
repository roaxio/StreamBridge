#!/usr/bin/env bash
# macOS release build, same as .github/workflows/release.yml (reference for the GitHub release).
# On macOS CI builds the StreamBridge.app bundle (no -- --onefile), zipped with ditto:
#   dist/StreamBridge.app  +  release_assets/StreamBridge-v<version>-macos-arm64.zip
# For the developer onedir+onefile build see scripts/macos/dev/build_macos.sh. Not tested on real macOS yet.
set -euo pipefail
cd "$(dirname "$0")/../.."
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install -q -e ".[dev,keyring]"
.venv/bin/pyinstaller --noconfirm --clean --distpath dist --workpath build packaging/macos.spec
TAG="v$(.venv/bin/python -c 'import streambridge; print(streambridge.__version__)')"
NAME="StreamBridge-${TAG}-macos-arm64.zip"
STAGE="stage/StreamBridge-${TAG}"
rm -rf stage && mkdir -p release_assets "$STAGE"
cp -R dist/StreamBridge.app packaging/user/macos/READ-ME-FIRST.txt "$STAGE/"
ditto -c -k --keepParent "$STAGE" "release_assets/$NAME"
rm -rf stage
echo "Built: dist/StreamBridge.app and release_assets/$NAME"

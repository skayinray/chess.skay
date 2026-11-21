#!/usr/bin/env bash
# Build the chess.skay AppImage. Optional argument: path to appimagetool.
set -euo pipefail
cd "$(dirname "$0")"
TOOL="${1:-/tmp/opencode/appimagetool.AppImage}"
python3 tools/build_appimage.py "$TOOL"

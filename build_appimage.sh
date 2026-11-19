#!/usr/bin/env bash
# Сборкаchess.skay AppImage. Необязательный аргумент — путь к appimagetool.
set -euo pipefail
cd "$(dirname "$0")"
TOOL="${1:-/tmp/opencode/appimagetool.AppImage}"
python3 tools/build_appimage.py "$TOOL"

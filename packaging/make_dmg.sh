#!/usr/bin/env bash
# Build a drag-to-Applications DMG from dist/youtube-tools.app
# Requires: create-dmg (brew install create-dmg)
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP="$PROJECT_DIR/dist/youtube-tools.app"
OUT="$PROJECT_DIR/dist/youtube-tools-0.1.0-macos-arm64.dmg"

if [ ! -d "$APP" ]; then
    echo "Error: $APP not found. Run: pyinstaller packaging/youtube-tools.spec"
    exit 1
fi

if ! command -v create-dmg >/dev/null 2>&1; then
    echo "Error: create-dmg required. Install with: brew install create-dmg"
    exit 1
fi

rm -f "$OUT"
create-dmg \
    --volname "youtube-tools" \
    --window-size 540 320 \
    --icon-size 96 \
    --icon "youtube-tools.app" 150 160 \
    --app-drop-link 390 160 \
    "$OUT" \
    "$APP"

echo "DMG written to: $OUT"

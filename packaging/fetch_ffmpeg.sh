#!/usr/bin/env bash
# Download static ffmpeg + ffprobe for the current platform into
# packaging/bin/<os-arch>/. The PyInstaller spec bundles whatever lives there.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

OS="$(uname -s)"
ARCH="$(uname -m)"

if [ "$OS" = "Darwin" ] && [ "$ARCH" = "arm64" ]; then
    DEST="$SCRIPT_DIR/bin/macos-arm64"
    mkdir -p "$DEST"
    echo "Fetching static ffmpeg/ffprobe for macOS arm64 from evermeet.cx..."
    curl -L "https://evermeet.cx/ffmpeg/getrelease/zip" -o /tmp/ffmpeg.zip
    curl -L "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip" -o /tmp/ffprobe.zip
    (cd /tmp && unzip -o ffmpeg.zip -d "$DEST" && unzip -o ffprobe.zip -d "$DEST")
    chmod +x "$DEST/ffmpeg" "$DEST/ffprobe"
    rm -f /tmp/ffmpeg.zip /tmp/ffprobe.zip
    echo "Done: $DEST"
elif [ "$OS" = "Darwin" ] && [ "$ARCH" = "x86_64" ]; then
    echo "Intel Mac: same URL source as arm64 works; adjust DEST if you need Intel."
    exit 1
elif [ "$OS" = "Linux" ]; then
    echo "Linux build isn't a v1 target. Install ffmpeg via your package manager for dev use."
    exit 1
else
    echo "Windows: run packaging/fetch_ffmpeg.ps1 instead (not included — download"
    echo "static builds from https://www.gyan.dev/ffmpeg/builds/ and unzip into"
    echo "packaging/bin/windows-x86_64/)."
    exit 1
fi

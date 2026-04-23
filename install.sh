#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
OS="$(uname -s)"

find_python() {
    for cmd in python3.13 python3.12 python3.11 python3.10; do
        if command -v "$cmd" >/dev/null 2>&1; then
            echo "$cmd"
            return 0
        fi
    done
    if command -v python3 >/dev/null 2>&1; then
        v=$(python3 -c 'import sys; print(sys.version_info[0]*100 + sys.version_info[1])' 2>/dev/null || echo 0)
        if [ "$v" -ge 310 ]; then
            echo "python3"
            return 0
        fi
    fi
    return 1
}

install_macos() {
    if ! command -v brew >/dev/null 2>&1; then
        echo "Error: Homebrew is required. Install it from https://brew.sh and re-run."
        exit 1
    fi

    if ! find_python >/dev/null; then
        echo "Installing Python 3.13 via Homebrew..."
        brew install python@3.13
    else
        echo "Python 3.10+ already installed: $(find_python)"
    fi

    if ! command -v ffmpeg >/dev/null 2>&1; then
        echo "Installing ffmpeg via Homebrew..."
        brew install ffmpeg
    else
        echo "ffmpeg already installed."
    fi
}

install_linux() {
    if ! command -v apt-get >/dev/null 2>&1; then
        echo "Error: this installer supports apt-based Linux only."
        echo "Install Python 3.10+ and ffmpeg manually, then re-run this script."
        exit 1
    fi

    if ! find_python >/dev/null; then
        echo "Installing Python 3.13 via apt (requires sudo)..."
        sudo apt-get update
        sudo apt-get install -y python3.13 python3.13-venv
    else
        echo "Python 3.10+ already installed: $(find_python)"
    fi

    if ! command -v ffmpeg >/dev/null 2>&1; then
        echo "Installing ffmpeg via apt (requires sudo)..."
        sudo apt-get install -y ffmpeg
    else
        echo "ffmpeg already installed."
    fi
}

echo "=== Installing system dependencies ==="
case "$OS" in
    Darwin) install_macos ;;
    Linux)  install_linux ;;
    *) echo "Error: unsupported OS '$OS'. Manual install required."; exit 1 ;;
esac

PYTHON=$(find_python) || {
    echo "Error: Python 3.10+ still not found after install."
    exit 1
}

echo ""
echo "=== Setting up virtual environment ==="
if [ -d "$VENV_DIR" ]; then
    echo "Removing existing .venv to ensure clean install..."
    rm -rf "$VENV_DIR"
fi

echo "Creating .venv with $PYTHON..."
"$PYTHON" -m venv "$VENV_DIR"

echo "Upgrading pip..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip

echo "Installing Python dependencies from requirements.txt..."
"$VENV_DIR/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements.txt"

echo ""
echo "=== Installation complete ==="
echo ""
echo "Collect all links from a channel:"
echo "  ./parse.sh @channelname -o links.txt"
echo ""
echo "Download videos:"
echo "  ./download.sh links.txt -o ~/videos"
echo ""
echo "Transcribe a folder of downloaded media:"
echo "  ./transcribe.sh ~/videos"
echo ""
echo "Or run the full pipeline in one shot:"
echo "  ./pipeline.sh @channelname ~/videos/channelname"

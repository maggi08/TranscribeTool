#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Error: virtual environment not found."
    echo ""
    echo "First-time setup — run the installer:"
    echo "  ./install.sh"
    exit 1
fi

"$VENV_DIR/bin/python" "$SCRIPT_DIR/download.py" "$@"

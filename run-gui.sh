#!/usr/bin/env bash
# Launch the desktop GUI from source using the project venv.
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

if ! "$VENV_DIR/bin/python" -c "import PySide6" 2>/dev/null; then
    echo "PySide6 not installed. Installing GUI dependencies..."
    "$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements-gui.txt"
fi

exec "$VENV_DIR/bin/python" "$SCRIPT_DIR/app.py" "$@"

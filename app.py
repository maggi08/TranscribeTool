#!/usr/bin/env python3
"""Top-level entry point for the TranscribeTool desktop GUI (and PyInstaller).

Also acts as a CLI dispatcher when invoked with `--cli <script.py> [args...]`,
so the GUI can spawn parse/download/transcribe as subprocesses inside the
frozen `.app` (which has no separate `python` binary).
"""
from __future__ import annotations

import sys


def _run_cli_script() -> int:
    """Execute a bundled script as if it were the main module."""
    if len(sys.argv) < 3:
        print("usage: --cli <script.py> [args...]", file=sys.stderr)
        return 2
    script_path = sys.argv[2]
    script_args = sys.argv[3:]
    sys.argv = [script_path, *script_args]
    import runpy
    try:
        runpy.run_path(script_path, run_name="__main__")
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else (0 if e.code is None else 1)
    except Exception:
        import traceback
        traceback.print_exc()
        return 1
    return 0


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--cli":
        return _run_cli_script()
    from transcribe_tool.main import main as gui_main
    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())

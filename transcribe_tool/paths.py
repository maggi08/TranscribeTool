"""Resolve script and resource paths in dev and PyInstaller-frozen modes."""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path


def _frozen_root() -> Path | None:
    """PyInstaller's unpacked data dir, or None when running from source."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return None


def project_root() -> Path:
    frozen = _frozen_root()
    if frozen:
        return frozen
    return Path(__file__).resolve().parent.parent


def script_path(name: str) -> Path:
    """Locate a project script (parse.py / download.py / transcribe.py)."""
    return project_root() / name


def python_executable() -> str:
    """Python interpreter to launch subprocess scripts with (dev mode only).

    In frozen mode this isn't a real Python interpreter — use
    `cli_command()` instead, which re-execs the bundled .app with --cli.
    """
    if getattr(sys, "frozen", False):
        return sys.executable
    venv_python = project_root() / ".venv" / "bin" / "python"
    if platform.system() == "Windows":
        venv_python = project_root() / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def cli_command(script: str, script_args: list[str]) -> tuple[str, list[str]]:
    """Return (program, argv) to run a bundled CLI script as a subprocess.

    - Dev: invokes `.venv/bin/python script script_args…`
    - Frozen `.app`/.exe: re-execs the main bundle binary with `--cli script
      script_args…` so app.py's dispatcher routes to runpy. (PyInstaller
      bundles don't contain a standalone `python` binary, so we can't shell
      out to one.)
    """
    if getattr(sys, "frozen", False):
        return sys.executable, ["--cli", script, *script_args]
    return python_executable(), [script, *script_args]


def bundled_bin_dir() -> Path | None:
    """Directory containing bundled ffmpeg/ffprobe, or None in dev mode."""
    frozen = _frozen_root()
    if not frozen:
        return None
    candidate = frozen / "bin"
    return candidate if candidate.exists() else None


def environ_with_bundled_bins(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Return an env dict with bundled ffmpeg prepended to PATH.

    Falls back to common Homebrew locations on macOS when no bundled binary
    is present — important because GUI apps don't inherit terminal PATH and
    a brew-installed ffmpeg sits at /opt/homebrew/bin or /usr/local/bin.
    """
    env = dict(base_env if base_env is not None else os.environ)
    sep = ";" if platform.system() == "Windows" else ":"
    bdir = bundled_bin_dir()
    if bdir:
        env["PATH"] = f"{bdir}{sep}{env.get('PATH', '')}"
    if platform.system() == "Darwin":
        for p in ("/opt/homebrew/bin", "/usr/local/bin"):
            if Path(p).exists() and p not in env.get("PATH", "").split(sep):
                env["PATH"] = f"{p}{sep}{env.get('PATH', '')}"
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env

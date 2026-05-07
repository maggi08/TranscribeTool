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
    """Python interpreter to launch subprocess scripts with.

    Frozen: the bundled Python is `sys.executable`.
    Dev: prefer the project's .venv if present (so PySide6 dev users don't have
    to activate it manually); fall back to `sys.executable`.
    """
    if getattr(sys, "frozen", False):
        return sys.executable
    venv_python = project_root() / ".venv" / "bin" / "python"
    if platform.system() == "Windows":
        venv_python = project_root() / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def bundled_bin_dir() -> Path | None:
    """Directory containing bundled ffmpeg/ffprobe, or None in dev mode."""
    frozen = _frozen_root()
    if not frozen:
        return None
    candidate = frozen / "bin"
    return candidate if candidate.exists() else None


def environ_with_bundled_bins(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Return an env dict with bundled ffmpeg prepended to PATH."""
    env = dict(base_env if base_env is not None else os.environ)
    bdir = bundled_bin_dir()
    if bdir:
        sep = ";" if platform.system() == "Windows" else ":"
        env["PATH"] = f"{bdir}{sep}{env.get('PATH', '')}"
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env

"""Whisper-backend platform detection for the GUI.

Note: the actual transcription runs in a subprocess (`transcribe.py`). This
module only reports what's available so the UI can show the right label and
resolve "auto" into a concrete choice for display.
"""
from __future__ import annotations

import importlib.util
import platform
import shutil
from pathlib import Path


def is_apple_silicon() -> bool:
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def mlx_available() -> bool:
    if not is_apple_silicon():
        return False
    if importlib.util.find_spec("mlx_whisper") is not None:
        return True
    return shutil.which("mlx_whisper") is not None


def faster_whisper_available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def resolve_preference(preference: str) -> str:
    """Turn "auto" into the concrete backend name that will be used."""
    if preference == "auto":
        return "mlx" if mlx_available() else "faster-whisper"
    return preference


def human_label(backend_name: str) -> str:
    return {
        "mlx": "mlx-whisper (fast)",
        "faster-whisper": "faster-whisper (low power)",
    }.get(backend_name, backend_name)

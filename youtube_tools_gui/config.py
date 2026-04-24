"""Load/save persistent config from platform-appropriate user config dir."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

APP_NAME = "youtube-tools"
SCHEMA_VERSION = 1

DEFAULTS: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "default_output_dir": str(Path.home() / "Movies" / "youtube-tools"),
    "default_audio_only": True,
    "default_tabs": ["videos", "shorts", "streams"],
    "default_limit": None,
    "default_language": "ru",
    "transcribe_after_download": True,
    "whisper_backend": "auto",  # "auto" | "mlx" | "faster-whisper"
    "faster_whisper_model": "large-v3",
    "faster_whisper_compute_type": "int8",
    "window_geometry": None,
}


def config_dir() -> Path:
    d = Path(user_config_dir(APP_NAME, appauthor=False))
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return config_dir() / "config.json"


def load() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        save(DEFAULTS)
        return dict(DEFAULTS)
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULTS)

    # Forward-fill missing keys from defaults; write back if anything changed.
    merged = dict(DEFAULTS)
    merged.update(data)
    if merged != data:
        save(merged)
    return merged


def save(cfg: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic: write to tmp in same dir, then os.replace.
    fd, tmp = tempfile.mkstemp(prefix=".config.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def get(key: str, default: Any = None) -> Any:
    cfg = load()
    return cfg.get(key, default)


def set_value(key: str, value: Any) -> None:
    cfg = load()
    cfg[key] = value
    save(cfg)

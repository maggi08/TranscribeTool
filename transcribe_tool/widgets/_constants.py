"""Shared widget constants."""
from __future__ import annotations

LANGUAGES: list[tuple[str, str]] = [
    ("Auto-detect", ""),
    ("Russian", "ru"),
    ("English", "en"),
    ("Kazakh", "kk"),
    ("Spanish", "es"),
    ("French", "fr"),
    ("German", "de"),
    ("Ukrainian", "uk"),
    ("Turkish", "tr"),
]

MEDIA_EXTS = {
    ".mp3", ".mp4", ".m4a", ".wav", ".flac", ".ogg", ".opus",
    ".aac", ".wma", ".webm", ".mkv", ".avi", ".mov",
}

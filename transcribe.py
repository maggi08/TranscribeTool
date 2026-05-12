#!/usr/bin/env python3
"""Batch transcription with pluggable Whisper backends (mlx / faster-whisper)."""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

MEDIA_EXTENSIONS = (
    "mp3", "mp4", "m4a", "wav", "flac", "ogg", "opus",
    "aac", "wma", "webm", "mkv", "avi", "mov",
)
CHUNK_SECONDS = 600


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

class WhisperBackend:
    name: str = "base"

    def transcribe_file(self, audio: Path, out_dir: Path, language: str | None) -> Path:
        raise NotImplementedError


class MlxBackend(WhisperBackend):
    name = "mlx-whisper (fast)"

    def __init__(self, mlx_whisper_exe: str):
        self.exe = mlx_whisper_exe

    def transcribe_file(self, audio: Path, out_dir: Path, language: str | None) -> Path:
        cmd = [
            self.exe, str(audio),
            "--output-dir", str(out_dir),
            "--output-format", "txt",
            "--model", "mlx-community/whisper-large-v3-mlx",
            "--condition-on-previous-text", "False",
            "--compression-ratio-threshold", "1.8",
            "--temperature", "0",
            "--word-timestamps", "True",
            "--hallucination-silence-threshold", "2.0",
        ]
        if language:
            cmd += ["--language", language]
        subprocess.run(cmd, check=True)
        return out_dir / (audio.stem + ".txt")


class FasterWhisperBackend(WhisperBackend):
    name = "faster-whisper (low power)"

    def __init__(self, model_name: str = "large-v3", compute_type: str = "int8"):
        self.model_name = model_name
        self.compute_type = compute_type
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            print(f"  Loading faster-whisper model: {self.model_name} ({self.compute_type})...")
            self._model = WhisperModel(self.model_name, compute_type=self.compute_type)
        return self._model

    def transcribe_file(self, audio: Path, out_dir: Path, language: str | None) -> Path:
        model = self._load()
        segments, _info = model.transcribe(
            str(audio),
            language=language,
            condition_on_previous_text=False,
            compression_ratio_threshold=1.8,
            temperature=0.0,
            word_timestamps=True,
            hallucination_silence_threshold=2.0,
        )
        out_path = out_dir / (audio.stem + ".txt")
        with out_path.open("w", encoding="utf-8") as f:
            for seg in segments:
                text = seg.text.strip()
                if text:
                    f.write(text + "\n")
        return out_path


def _is_apple_silicon() -> bool:
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def _find_mlx_whisper() -> str | None:
    project_dir = Path(__file__).resolve().parent
    candidate = project_dir / ".venv" / "bin" / "mlx_whisper"
    if candidate.exists():
        return str(candidate)
    return shutil.which("mlx_whisper")


def select_backend(preference: str = "auto") -> WhisperBackend:
    """Choose a backend based on preference and available hardware/installs.

    preference: "auto" | "mlx" | "faster-whisper"
    """
    if preference == "mlx":
        exe = _find_mlx_whisper()
        if not exe:
            raise RuntimeError(
                "mlx-whisper not available. "
                "Switch to Low power mode (faster-whisper) or run ./install.sh on an Apple Silicon Mac."
            )
        return MlxBackend(exe)

    if preference == "faster-whisper":
        return FasterWhisperBackend()

    # auto
    if _is_apple_silicon():
        exe = _find_mlx_whisper()
        if exe:
            return MlxBackend(exe)
    return FasterWhisperBackend()


# ---------------------------------------------------------------------------
# Progress log (matches transcribe.sh .transcribe_done.log format)
# ---------------------------------------------------------------------------

class ProgressLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.touch(exist_ok=True)
        self._done: set[str] = set()
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if line:
                    self._done.add(line)

    def is_done(self, audio: Path) -> bool:
        return str(audio) in self._done

    def mark_done(self, audio: Path) -> None:
        s = str(audio)
        if s in self._done:
            return
        self._done.add(s)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(s + "\n")


# ---------------------------------------------------------------------------
# ffmpeg helpers
# ---------------------------------------------------------------------------

def _probe_duration(audio: Path) -> int:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(audio)],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        return int(float(out))
    except Exception:
        return 0


def _split_into_chunks(audio: Path, chunk_dir: Path, ext: str) -> list[Path]:
    chunk_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(chunk_dir.glob(f"chunk_*.{ext}"))
    if existing:
        print("  Chunks already exist, resuming...")
        return existing
    print(f"  Splitting into {CHUNK_SECONDS}s chunks...")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(audio),
         "-f", "segment", "-segment_time", str(CHUNK_SECONDS),
         "-c", "copy", "-reset_timestamps", "1",
         str(chunk_dir / f"chunk_%03d.{ext}")],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return sorted(chunk_dir.glob(f"chunk_*.{ext}"))


# ---------------------------------------------------------------------------
# Core flow (same output format as transcribe.sh so existing log parsers work)
# ---------------------------------------------------------------------------

def _transcribe_one(backend: WhisperBackend, audio: Path, out_dir: Path,
                    language: str | None) -> Path:
    txt = out_dir / (audio.stem + ".txt")
    if txt.exists():
        print(f"  Skipping (already done): {audio.name}")
        return txt
    print(f"  Transcribing: {audio.name}")
    return backend.transcribe_file(audio, out_dir, language)


def _transcribe_file(backend: WhisperBackend, audio: Path, language: str | None,
                     progress: ProgressLog) -> None:
    out_dir = audio.parent
    txt = out_dir / (audio.stem + ".txt")

    if progress.is_done(audio):
        print(f"Skipping (done in previous run): {audio.name}")
        return
    if txt.exists():
        print(f"Skipping (already transcribed): {audio.name}")
        progress.mark_done(audio)
        return

    duration = _probe_duration(audio)
    print("")
    print(f"=== {audio.name} ({duration}s) ===")

    if duration <= CHUNK_SECONDS:
        _transcribe_one(backend, audio, out_dir, language)
    else:
        ext = audio.suffix.lstrip(".")
        chunk_dir = out_dir / f".{audio.stem}_chunks"
        chunks = _split_into_chunks(audio, chunk_dir, ext)
        total = len(chunks)
        for i, chunk in enumerate(chunks, 1):
            print(f"  [{i}/{total}]")
            _transcribe_one(backend, chunk, chunk_dir, language)

        print("  Merging chunks...")
        with txt.open("w", encoding="utf-8") as out:
            for t in sorted(chunk_dir.glob("chunk_*.txt")):
                out.write(t.read_text(encoding="utf-8"))
        shutil.rmtree(chunk_dir, ignore_errors=True)
        print("  Chunks cleaned up.")

    progress.mark_done(audio)
    print("")
    print(f"=== Transcription: {audio.name} ===")
    try:
        print(txt.read_text(encoding="utf-8"))
    except Exception:
        pass
    print("")
    print(f"Output saved to: {txt}")


def _collect_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    files: list[Path] = []
    for ext in MEDIA_EXTENSIONS:
        files.extend(target.rglob(f"*.{ext}"))
        files.extend(target.rglob(f"*.{ext.upper()}"))
    # Dedupe case-insensitive matches on case-insensitive filesystems
    seen = set()
    unique: list[Path] = []
    for f in files:
        key = str(f.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(f)
    unique.sort()
    return unique


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch transcribe audio/video files with mlx-whisper or faster-whisper.",
    )
    parser.add_argument("inputs", nargs="+", help="One or more audio/video files OR folders (folders processed recursively)")
    parser.add_argument("--language", default=None, help="Language code (e.g. en, ru). Auto-detect if omitted.")
    parser.add_argument(
        "--backend", default="auto", choices=["auto", "mlx", "faster-whisper"],
        help="Whisper backend: auto (default), mlx (fast, Apple Silicon), "
             "faster-whisper (low power, cross-platform).",
    )
    parser.add_argument("--model", default=None, help="Override model for faster-whisper (e.g. large-v3, medium).")
    parser.add_argument("--compute-type", default=None, help="faster-whisper compute type (int8, float16, ...).")
    args = parser.parse_args()

    targets: list[Path] = []
    for inp in args.inputs:
        t = Path(inp).expanduser().resolve()
        if not t.exists():
            print(f"Error: not found: {t}", file=sys.stderr)
            sys.exit(1)
        targets.append(t)

    # Check ffmpeg presence early — we need it for probing + chunking
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("Error: ffmpeg and ffprobe are required.", file=sys.stderr)
        print("  macOS: brew install ffmpeg   Linux: apt-get install ffmpeg", file=sys.stderr)
        sys.exit(1)

    backend = select_backend(args.backend)
    if isinstance(backend, FasterWhisperBackend):
        if args.model:
            backend.model_name = args.model
        if args.compute_type:
            backend.compute_type = args.compute_type
    print(f"Using backend: {backend.name}")

    for target in targets:
        log_dir = target if target.is_dir() else target.parent
        progress = ProgressLog(log_dir / ".transcribe_done.log")

        files = _collect_files(target)
        if not files:
            if target.is_dir():
                print(f"No audio/video files found in: {target}")
            continue
        if target.is_dir():
            print(f"Found {len(files)} file(s) to transcribe in: {target}")

        for audio in files:
            _transcribe_file(backend, audio, args.language, progress)

    print("")
    print("=== All done ===")


if __name__ == "__main__":
    main()

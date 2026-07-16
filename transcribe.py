#!/usr/bin/env python3
"""Batch transcription with pluggable Whisper backends (mlx / faster-whisper).

SHARED FILE — kept byte-identical in two repos:
  - pako/.claude/skills/transcribe/scripts/transcribe.py   (the assistant's skill)
  - TranscribeTool/transcribe.py                           (mass transcription)
Fix bugs here and copy across; they were forked once already and drifted.
Must stay Python 3.9-compatible (pako's skill venv is the system 3.9).

Memory safety on an 8 GB Mac — why the guards below exist. Whisper large-v3 is
~2.9 GB of unified memory. Load two at once, OR load one while the disk is nearly
full, and the machine swaps; with no free disk macOS cannot grow swap, the kernel
stalls on VM allocation, watchdogd misses its 90 s check-in and the hardware
watchdog reboots the Mac. That happened three times on 2026-07-13..15, signature
`watchdog timeout: no checkins from watchdogd` + `LOW swap space`.

Two guards, each closing a different hole:
  1. whisper_lock() — a machine-wide inter-process lock, so pako's bot, the agent
     invoking this script directly, and TranscribeTool can never load two models at
     once. An in-process semaphore cannot see the other two.
     Held per mlx_whisper invocation, NOT per batch: a multi-hour mass run must not
     starve the bot's voice messages — they interleave between chunks. See
     MlxBackend.transcribe_file and the `hold_batch_lock` note in main().
  2. _require_disk() — refuses to start when the disk cannot back the swap the model
     will need. Checked before the batch and before every file, because a long run
     fills the disk itself (downloads, chunks, transcripts).
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

MEDIA_EXTENSIONS = (
    "mp3", "mp4", "m4a", "wav", "flac", "ogg", "opus",
    "aac", "wma", "webm", "mkv", "avi", "mov",
)
CHUNK_SECONDS = 600

DEFAULT_MLX_MODEL = "mlx-community/whisper-large-v3-mlx"
DEFAULT_FW_MODEL = "large-v3"

# Short names → mlx repo ids, so `--model tiny` works on Apple Silicon too.
_MLX_ALIASES = {
    "tiny": "mlx-community/whisper-tiny",
    "base": "mlx-community/whisper-base",
    "small": "mlx-community/whisper-small",
    "medium": "mlx-community/whisper-medium",
    "large": DEFAULT_MLX_MODEL,
    "large-v3": DEFAULT_MLX_MODEL,
}


def _resolve_mlx_model(name: str | None) -> str:
    if not name:
        return DEFAULT_MLX_MODEL
    if "/" in name:            # full repo id — pass through
        return name
    return _MLX_ALIASES.get(name, name)


def _resolve_fw_model(name: str | None) -> str:
    if not name:
        return DEFAULT_FW_MODEL
    if "/" in name:            # someone passed an mlx repo id — take the tail
        return name.rsplit("/", 1)[-1].replace("whisper-", "").replace("-mlx", "")
    return name


# ---------------------------------------------------------------------------
# Disk guard — the panics were a full disk, not just a big model
# ---------------------------------------------------------------------------

# Gate on DISK, not free RAM: macOS always reports little free RAM (this machine
# idles at memory pressure "warn"), so a RAM check would refuse everything. What
# actually killed it was swap having nowhere to grow.
MIN_DISK_GB = float(os.environ.get("WHISPER_MIN_DISK_GB", "8"))
DATA_VOLUME = os.environ.get("WHISPER_DATA_VOLUME", "/System/Volumes/Data")


def _disk_free_gb() -> float:
    for target in (DATA_VOLUME, "/"):
        try:
            return shutil.disk_usage(target).free / 1024 ** 3
        except OSError:
            continue
    return float("inf")  # can't tell → don't block the user


def _resource_line() -> str:
    """One-line resource snapshot for the run log."""
    parts = ["disk_free=%.1fG" % _disk_free_gb()]
    try:
        raw = subprocess.check_output(
            ["sysctl", "-n", "vm.swapusage"], stderr=subprocess.DEVNULL,
        ).decode()
        m = re.search(r"used\s*=\s*([\d.]+)M.*?free\s*=\s*([\d.]+)M", raw)
        if m:
            parts.append("swap_used=%sM swap_free=%sM" % (m.group(1), m.group(2)))
    except Exception:
        pass  # non-macOS or sysctl missing — disk figure is the one that matters
    return "  ".join(parts)


def _require_disk() -> None:
    """Refuse to load a ~3 GB model when the disk cannot back the swap it needs."""
    free = _disk_free_gb()
    if free >= MIN_DISK_GB:
        return
    print("", file=sys.stderr)
    print(f"Error: only {free:.1f} GB free on disk (need >= {MIN_DISK_GB:.0f} GB).",
          file=sys.stderr)
    print("  Whisper needs ~3 GB of memory. With a full disk macOS cannot grow swap,",
          file=sys.stderr)
    print("  the kernel stalls and the watchdog reboots the Mac (this already happened",
          file=sys.stderr)
    print("  three times on 2026-07-13..15). Free some space, then re-run.", file=sys.stderr)
    print("  Override at your own risk: WHISPER_MIN_DISK_GB=0", file=sys.stderr)
    sys.exit(3)


# ---------------------------------------------------------------------------
# Global inter-process lock — only ONE whisper process at a time, machine-wide
# ---------------------------------------------------------------------------

LOCK_TIMEOUT = int(os.environ.get("WHISPER_LOCK_TIMEOUT", "3600"))


def _lock_path() -> Path:
    raw = os.environ.get("WHISPER_LOCK")
    if raw:
        return Path(raw).expanduser()
    # Machine-wide, deliberately NOT under a repo name: pako's bot, the agent and
    # TranscribeTool must all contend for the SAME file or the lock protects nothing.
    return Path.home() / ".cache" / "whisper" / "transcribe.lock"


@contextmanager
def whisper_lock(timeout: int = LOCK_TIMEOUT):
    """Block until no other transcription is running (advisory flock).

    flock is released automatically when the process dies, so a crash can never
    leave a stale lock behind.
    """
    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("w")
    waited = 0
    while True:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if waited == 0:
                print("  Another transcription is running — waiting for the global lock...")
            if waited >= timeout:
                fh.close()
                print(
                    f"Error: another transcription is still running after {timeout}s. "
                    "Refusing to load a second model (8 GB machine).",
                    file=sys.stderr,
                )
                sys.exit(2)
            time.sleep(2)
            waited += 2
    try:
        fh.write(str(os.getpid()))
        fh.flush()
        yield
    finally:
        with contextlib.suppress(Exception):
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

class WhisperBackend:
    name: str = "base"

    def transcribe_file(self, audio: Path, out_dir: Path, language: str | None) -> Path:
        raise NotImplementedError


class MlxBackend(WhisperBackend):
    name = "mlx-whisper (fast)"

    def __init__(self, mlx_whisper_exe: str, model: str | None = None):
        self.exe = mlx_whisper_exe
        self.model = _resolve_mlx_model(model)

    @staticmethod
    def _buggy_output_path(audio: Path, out_dir: Path) -> Path:
        """mlx_whisper uses `pathlib.Path(stem).with_suffix('.txt')` which
        wrongly treats text after any `.` in the stem as an extension.
        Predict where it will actually write so we can rename afterwards.
        """
        return (out_dir / audio.stem).with_suffix(".txt")

    def transcribe_file(self, audio: Path, out_dir: Path, language: str | None) -> Path:
        cmd = [
            self.exe, str(audio),
            "--output-dir", str(out_dir),
            "--output-format", "txt",
            "--model", self.model,
            "--condition-on-previous-text", "False",
            "--compression-ratio-threshold", "1.8",
            "--temperature", "0",
            "--word-timestamps", "True",
            "--hallucination-silence-threshold", "2.0",
        ]
        if language:
            cmd += ["--language", language]
        # Lock scope = exactly the window where the 2.9 GB model is resident, i.e. this
        # subprocess. Deliberately NOT the whole batch: a multi-hour mass run would then
        # starve pako's bot, and a voice message would hang until the lock timeout instead
        # of slipping in between chunks. Per-invocation keeps the one-model-at-a-time
        # guarantee while letting the two callers interleave.
        with whisper_lock():
            subprocess.run(cmd, check=True)

        expected = out_dir / (audio.stem + ".txt")
        buggy = self._buggy_output_path(audio, out_dir)
        if expected != buggy and buggy.exists() and not expected.exists():
            buggy.rename(expected)
        return expected


class FasterWhisperBackend(WhisperBackend):
    name = "faster-whisper (low power)"

    def __init__(self, model_name: str | None = None, compute_type: str = "int8"):
        self.model_name = _resolve_fw_model(model_name)
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


def select_backend(preference: str = "auto", model: str | None = None) -> WhisperBackend:
    """Choose a backend based on preference and available hardware/installs.

    preference: "auto" | "mlx" | "faster-whisper"
    model: short name ("tiny", "medium") or full repo id; None = backend default.
    """
    if preference == "mlx":
        exe = _find_mlx_whisper()
        if not exe:
            raise RuntimeError(
                "mlx-whisper not available. "
                "Switch to Low power mode (faster-whisper) or run ./install.sh on an Apple Silicon Mac."
            )
        return MlxBackend(exe, model)

    if preference == "faster-whisper":
        return FasterWhisperBackend(model)

    # auto
    if _is_apple_silicon():
        exe = _find_mlx_whisper()
        if exe:
            return MlxBackend(exe, model)
    return FasterWhisperBackend(model)


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

def _probe_duration(audio: Path) -> int | None:
    """Duration in seconds, or None if ffprobe could not tell.

    None (not 0!) matters: a 0 used to satisfy `duration <= CHUNK_SECONDS`, which
    silently disabled chunking and fed the whole file to whisper — a 3h file is
    ~690 MB of PCM plus ~550 MB of mel spectrogram ON TOP of the 2.9 GB model.
    Unknown duration must mean "chunk it", never "swallow it whole".
    """
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(audio)],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        return int(float(out))
    except Exception:
        return None


def _split_into_chunks(audio: Path, chunk_dir: Path, ext: str) -> list[Path]:
    chunk_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(chunk_dir.glob(f"chunk_*.{ext}"))
    if existing:
        print("  Chunks already exist, resuming...")
        return existing
    print(f"  Splitting into {CHUNK_SECONDS}s chunks...")
    # check=False: a split failure must return [] so the caller can fall back to the
    # whole file, rather than aborting the run with CalledProcessError.
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(audio),
         "-f", "segment", "-segment_time", str(CHUNK_SECONDS),
         "-c", "copy", "-reset_timestamps", "1",
         str(chunk_dir / f"chunk_%03d.{ext}")],
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
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
                     progress: ProgressLog, delete_after: bool = False) -> None:
    out_dir = audio.parent
    txt = out_dir / (audio.stem + ".txt")

    def _cleanup_media():
        if not delete_after:
            return
        try:
            audio.unlink()
            print(f"  Deleted media: {audio.name}")
        except OSError as e:
            print(f"  Warning: could not delete {audio.name}: {e}")

    if progress.is_done(audio):
        if txt.exists():
            print(f"Skipping (done in previous run): {audio.name}")
            _cleanup_media()
            return
        # Stale log entry — log claims done but no .txt on disk.
        # Fall through and re-transcribe.
        print(f"Note: log says done but no .txt found — re-transcribing {audio.name}")
    if txt.exists():
        print(f"Skipping (already transcribed): {audio.name}")
        progress.mark_done(audio)
        _cleanup_media()
        return

    # Re-check per file: a long batch fills the disk itself (downloads, chunks, .txt),
    # so a run that was safe at the start can walk into the danger zone by file 200.
    _require_disk()

    duration = _probe_duration(audio)
    print("")
    print(f"=== {audio.name} ({duration if duration is not None else '?'}s) ===")
    print(f"  [resources] {_resource_line()}")

    # Unknown duration → chunk (memory-safe default). See _probe_duration.
    single = duration is not None and duration <= CHUNK_SECONDS
    chunks: list[Path] = []
    chunk_dir = out_dir / f".{audio.stem}_chunks"

    if not single:
        chunks = _split_into_chunks(audio, chunk_dir, audio.suffix.lstrip("."))
        if not chunks:
            # ffmpeg couldn't segment (typically a short voice note whose probe failed).
            # Falling back to the whole file is safe here precisely because it's short —
            # and it beats returning an empty transcript.
            print("  Could not split — falling back to the whole file.")
            shutil.rmtree(chunk_dir, ignore_errors=True)
            single = True

    if single:
        _transcribe_one(backend, audio, out_dir, language)
    else:
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
    _cleanup_media()


def _collect_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    files: list[Path] = []
    for ext in MEDIA_EXTENSIONS:
        files.extend(target.rglob(f"*.{ext}"))
        files.extend(target.rglob(f"*.{ext.upper()}"))
    # Skip files inside hidden directories (.duplicates, .chunks_*, .git, etc.)
    target_parts = len(target.parts)
    files = [
        f for f in files
        if not any(p.startswith(".") for p in f.parts[target_parts:-1])
    ]
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
    parser.add_argument(
        "--model", default=None,
        help="Model for EITHER backend: short name (tiny, base, small, medium, large-v3) "
             "or a full repo id. Default: large-v3. Env: WHISPER_MODEL.",
    )
    parser.add_argument("--compute-type", default=None, help="faster-whisper compute type (int8, float16, ...).")
    parser.add_argument(
        "--delete-after",
        action="store_true",
        help="Delete the media file after a successful transcription (saves disk space). "
             "Also cleans up already-transcribed files when found.",
    )
    parser.add_argument(
        "--cleanup-only",
        action="store_true",
        help="Don't transcribe anything. Only delete media files whose .txt transcript already exists. "
             "Safe to run on any folder — leaves untranscribed media untouched.",
    )
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

    if args.cleanup_only:
        total_removed = 0
        total_kept = 0
        for target in targets:
            files = _collect_files(target)
            log_dir = target if target.is_dir() else target.parent
            progress = ProgressLog(log_dir / ".transcribe_done.log")
            for audio in files:
                txt = audio.with_suffix(".txt")
                if txt.exists():
                    try:
                        audio.unlink()
                        print(f"  removed: {audio}")
                        progress.mark_done(audio)
                        total_removed += 1
                    except OSError as e:
                        print(f"  could not remove {audio}: {e}")
                else:
                    print(f"  kept (no transcript): {audio}")
                    total_kept += 1
        print(f"\nCleanup done — removed {total_removed} media file(s), "
              f"kept {total_kept} (no transcript yet).")
        return

    # Precedence: --model > WHISPER_MODEL env > backend default (large-v3).
    # Previously --model was applied ONLY to faster-whisper, so on Apple Silicon
    # (which always picks MlxBackend) it was silently ignored.
    model = args.model or os.environ.get("WHISPER_MODEL") or None
    backend = select_backend(args.backend, model)
    if args.compute_type and isinstance(backend, FasterWhisperBackend):
        backend.compute_type = args.compute_type
    print(f"Using backend: {backend.name}")
    print(f"Resources: {_resource_line()}")

    _require_disk()  # fail fast, before loading anything

    # Where the lock lives depends on how long the model stays resident:
    #   MlxBackend    — fresh mlx_whisper subprocess per file/chunk, nothing resident in
    #                   between, so it locks per invocation (see MlxBackend.transcribe_file)
    #                   and a long batch never blocks the other caller for more than a chunk.
    #   FasterWhisper — caches the model in-process until exit (transcribe.py `_load`), so
    #                   it has no choice but to hold the lock for the whole batch.
    hold_batch_lock = isinstance(backend, FasterWhisperBackend)
    with (whisper_lock() if hold_batch_lock else contextlib.nullcontext()):
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
                _transcribe_file(backend, audio, args.language, progress,
                                 delete_after=args.delete_after)

    print("")
    print("=== All done ===")


if __name__ == "__main__":
    main()

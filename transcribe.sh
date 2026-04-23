#!/usr/bin/env bash
# =============================================================================
# transcribe.sh — Batch audio/video transcription using mlx-whisper
#
# Features:
#   - Accepts a single file or a folder (recursively finds all media files)
#   - Splits files longer than 10 minutes into chunks to avoid memory crashes
#   - Maintains a progress log (.transcribe_done.log) so interrupted runs
#     can be resumed exactly where they stopped
#   - Already-transcribed chunks are skipped on retry (crash-safe)
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Directory where this script lives (used to locate the local Python venv)
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Local Python virtual environment with mlx-whisper installed
VENV="$PROJECT_DIR/.venv"

# All file extensions we recognise as audio or video
MEDIA_EXTENSIONS="mp3 mp4 m4a wav flac ogg opus aac wma webm mkv avi mov"

# Maximum duration (seconds) before a file is split into chunks.
# 10 minutes keeps peak memory low and prevents macOS kernel panics
# on machines with limited RAM/swap.
CHUNK_SECONDS=600

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
  echo "Usage: transcribe.sh <audio-file-or-folder> [extra-flags...]"
  echo ""
  echo "  If a folder is given, all audio/video files inside it are transcribed."
  echo "  Files longer than 10 minutes are automatically split into chunks."
  echo "  Progress is saved — re-run the same command to resume after a crash."
  echo "  Supported extensions: $MEDIA_EXTENSIONS"
  exit 1
}

if [ $# -lt 1 ]; then
  usage
fi

# First argument is the file or folder path; the rest are extra flags
# passed directly to mlx_whisper (e.g. --language en)
INPUT="$1"
shift
EXTRA_FLAGS="$*"

# ---------------------------------------------------------------------------
# Resolve the input to an absolute path
# ---------------------------------------------------------------------------
if [ -d "$INPUT" ]; then
  INPUT="$(cd "$INPUT" && pwd)"
elif [ -f "$INPUT" ]; then
  INPUT="$(cd "$(dirname "$INPUT")" && pwd)/$(basename "$INPUT")"
else
  echo "Error: not found: $INPUT"
  exit 1
fi

# ---------------------------------------------------------------------------
# Check shared venv (created by install.sh)
# ---------------------------------------------------------------------------
if [ ! -f "$VENV/bin/mlx_whisper" ]; then
  echo "Error: mlx-whisper not found in $VENV."
  echo ""
  echo "First-time setup — run the installer:"
  echo "  ./install.sh"
  exit 1
fi

# ---------------------------------------------------------------------------
# Verify that ffmpeg and ffprobe are installed (needed for splitting)
# ---------------------------------------------------------------------------
if ! command -v ffprobe &>/dev/null || ! command -v ffmpeg &>/dev/null; then
  echo "Error: ffmpeg and ffprobe are required. Install with: brew install ffmpeg"
  exit 1
fi

# ---------------------------------------------------------------------------
# Progress log helpers
#
# We keep a simple text file (.transcribe_done.log) in the target directory
# that lists absolute paths of files that have been fully transcribed.
# On re-run we check this log to skip completed files, so even if the
# computer crashes mid-batch we resume from the exact file that failed.
# ---------------------------------------------------------------------------

# Determine where to store the progress log
if [ -d "$INPUT" ]; then
  PROGRESS_LOG="$INPUT/.transcribe_done.log"
else
  PROGRESS_LOG="$(dirname "$INPUT")/.transcribe_done.log"
fi

# Create the log file if it doesn't exist yet
touch "$PROGRESS_LOG"

# Check whether a file path is already recorded in the progress log
is_done() {
  grep -qxF "$1" "$PROGRESS_LOG" 2>/dev/null
}

# Record a file path as completed in the progress log
mark_done() {
  echo "$1" >> "$PROGRESS_LOG"
}

# ---------------------------------------------------------------------------
# transcribe_one — transcribe a single audio file (short file or one chunk)
#
# Arguments:
#   $1 — path to the audio file
#   $2 — directory where the .txt output should be written
#
# Skips if the .txt already exists (handles chunk-level crash recovery).
# Uses the large-v3 Whisper model with settings tuned for quality:
#   --condition-on-previous-text False  → prevents repetition loops
#   --compression-ratio-threshold 1.8   → catches duplicated/garbled output
#   --temperature 0                     → deterministic decoding (no randomness)
#   --word-timestamps True              → enables hallucination detection
#   --hallucination-silence-threshold 2 → drops hallucinated text in silent gaps
# ---------------------------------------------------------------------------
transcribe_one() {
  local FILE="$1"
  local OUT_DIR="$2"
  local FNAME
  FNAME="$(basename "$FILE")"
  local TXT="$OUT_DIR/${FNAME%.*}.txt"

  # If this chunk/file was already transcribed, skip it
  if [ -f "$TXT" ]; then
    echo "  Skipping (already done): $FNAME"
    return 0
  fi

  echo "  Transcribing: $FNAME"

  # Run mlx_whisper. EXTRA_FLAGS is intentionally unquoted so that
  # multiple flags like "--language en" are split into separate arguments.
  # shellcheck disable=SC2086
  "$VENV/bin/mlx_whisper" "$FILE" \
    --output-dir "$OUT_DIR" \
    --output-format txt \
    --model mlx-community/whisper-large-v3-mlx \
    --condition-on-previous-text False \
    --compression-ratio-threshold 1.8 \
    --temperature 0 \
    --word-timestamps True \
    --hallucination-silence-threshold 2.0 \
    $EXTRA_FLAGS
}

# ---------------------------------------------------------------------------
# transcribe_file — handle one media file (split if needed, then transcribe)
#
# Flow:
#   1. Check progress log — skip if already fully done
#   2. Get duration via ffprobe
#   3. If <= 10 min: transcribe directly
#   4. If >  10 min: split into 10-min chunks with ffmpeg, transcribe each
#      chunk separately, merge .txt files, clean up chunks
#   5. Mark file as done in the progress log
# ---------------------------------------------------------------------------
transcribe_file() {
  local AUDIO_FILE="$1"
  local BASENAME
  BASENAME="$(basename "$AUDIO_FILE")"
  local OUTPUT_DIR
  OUTPUT_DIR="$(dirname "$AUDIO_FILE")"
  local TXT_FILE="$OUTPUT_DIR/${BASENAME%.*}.txt"

  # ── Skip if already recorded as completed in the progress log ──
  if is_done "$AUDIO_FILE"; then
    echo "Skipping (done in previous run): $BASENAME"
    return 0
  fi

  # ── Skip if the .txt output file already exists ──
  # This covers the case where the file was transcribed but the progress
  # log wasn't updated (e.g. crash right after transcription)
  if [ -f "$TXT_FILE" ]; then
    echo "Skipping (already transcribed): $BASENAME"
    mark_done "$AUDIO_FILE"
    return 0
  fi

  # ── Get file duration using ffprobe ──
  local DURATION
  DURATION=$(ffprobe -v error -show_entries format=duration \
    -of csv=p=0 "$AUDIO_FILE" 2>/dev/null | cut -d. -f1)

  # If duration can't be determined, fall back to direct transcription
  if [ -z "$DURATION" ] || [ "$DURATION" = "N/A" ]; then
    echo "Warning: could not determine duration of $BASENAME, transcribing directly"
    DURATION=0
  fi

  echo ""
  echo "=== $BASENAME (${DURATION}s) ==="

  if [ "$DURATION" -le "$CHUNK_SECONDS" ]; then
    # ── Short file: transcribe the whole thing at once ──
    transcribe_one "$AUDIO_FILE" "$OUTPUT_DIR"
  else
    # ── Long file: split → transcribe chunks → merge → clean up ──

    # Hidden directory next to the audio file to store temporary chunks
    # e.g. for "interview.mp4" → ".interview_chunks/"
    local CHUNK_DIR="$OUTPUT_DIR/.${BASENAME%.*}_chunks"
    local EXT="${BASENAME##*.}"

    # Only split if chunk files don't already exist (crash-resume: if we
    # crashed after splitting but before finishing transcription, the
    # chunks are still there and we can pick up where we left off)
    if [ ! -d "$CHUNK_DIR" ] || [ -z "$(ls "$CHUNK_DIR"/chunk_*."$EXT" 2>/dev/null)" ]; then
      mkdir -p "$CHUNK_DIR"
      echo "  Splitting into ${CHUNK_SECONDS}s chunks..."

      # -f segment: use ffmpeg's segment muxer to split at boundaries
      # -segment_time: target duration for each chunk
      # -c copy: copy codec (no re-encoding = instant + lossless)
      # -reset_timestamps 1: each chunk starts at 0:00
      ffmpeg -y -i "$AUDIO_FILE" -f segment -segment_time "$CHUNK_SECONDS" \
        -c copy -reset_timestamps 1 "$CHUNK_DIR/chunk_%03d.$EXT" 2>/dev/null
    else
      echo "  Chunks already exist, resuming..."
    fi

    # Count total chunks for progress display
    local CHUNK_COUNT=0
    local TOTAL_CHUNKS
    TOTAL_CHUNKS=$(ls "$CHUNK_DIR"/chunk_*."$EXT" 2>/dev/null | wc -l | tr -d ' ')

    # Transcribe each chunk one by one
    # If a chunk's .txt already exists (from a previous interrupted run),
    # transcribe_one will skip it automatically
    for CHUNK in "$CHUNK_DIR"/chunk_*."$EXT"; do
      CHUNK_COUNT=$((CHUNK_COUNT + 1))
      echo "  [$CHUNK_COUNT/$TOTAL_CHUNKS]"
      transcribe_one "$CHUNK" "$CHUNK_DIR"
    done

    # Merge all chunk .txt files (sorted by name: chunk_000, chunk_001, ...)
    # into the final output file
    echo "  Merging chunks..."
    cat "$CHUNK_DIR"/chunk_*.txt > "$TXT_FILE"

    # Remove the temporary chunks directory to free disk space
    rm -rf "$CHUNK_DIR"
    echo "  Chunks cleaned up."
  fi

  # ── Record this file as fully completed ──
  mark_done "$AUDIO_FILE"

  echo ""
  echo "=== Transcription: $BASENAME ==="
  cat "$TXT_FILE"
  echo ""
  echo "Output saved to: $TXT_FILE"
}

# ---------------------------------------------------------------------------
# Collect all media files to process
#
# - If INPUT is a directory: recursively find all files matching
#   MEDIA_EXTENSIONS, then sort them alphabetically for consistent order
# - If INPUT is a single file: just process that one file
# ---------------------------------------------------------------------------
FILES=()
if [ -d "$INPUT" ]; then
  # Loop through each supported extension and find matching files
  for ext in $MEDIA_EXTENSIONS; do
    while IFS= read -r -d '' f; do
      FILES+=("$f")
    done < <(find "$INPUT" -iname "*.$ext" -print0 2>/dev/null)
  done

  if [ ${#FILES[@]} -eq 0 ]; then
    echo "No audio/video files found in: $INPUT"
    exit 1
  fi

  # Sort file list alphabetically for predictable processing order
  IFS=$'\n' FILES=($(sort <<<"${FILES[*]}")); unset IFS
  echo "Found ${#FILES[@]} file(s) to transcribe in: $INPUT"
else
  FILES=("$INPUT")
fi

# ---------------------------------------------------------------------------
# Main loop: transcribe each collected file
# ---------------------------------------------------------------------------
for AUDIO_FILE in "${FILES[@]}"; do
  transcribe_file "$AUDIO_FILE"
done

echo ""
echo "=== All done ==="

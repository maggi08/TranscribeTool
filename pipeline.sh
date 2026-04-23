#!/usr/bin/env bash
# =============================================================================
# pipeline.sh — one-shot: channel → links.txt → MP4s → transcripts
#
# Usage:
#   ./pipeline.sh <channel> <output_dir> [--limit N] [--tabs videos,shorts,streams]
#
# Example:
#   ./pipeline.sh @ja_wizu ~/videos/ja_wizu
#   ./pipeline.sh @ja_wizu ~/videos/ja_wizu --limit 3        # smoke test
# =============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ $# -lt 2 ]; then
    echo "Usage: $0 <channel> <output_dir> [--limit N] [--tabs ...]"
    echo ""
    echo "Example:"
    echo "  $0 @channelname ~/videos/channelname"
    echo "  $0 @channelname ~/videos/channelname --limit 3"
    exit 1
fi

CHANNEL="$1"
OUTPUT_DIR="$2"
shift 2

mkdir -p "$OUTPUT_DIR"
LINKS="$OUTPUT_DIR/links.txt"

echo ""
echo "### [1/3] Parsing channel: $CHANNEL"
"$SCRIPT_DIR/parse.sh" "$CHANNEL" -o "$LINKS" "$@"

echo ""
echo "### [2/3] Downloading audio to: $OUTPUT_DIR"
"$SCRIPT_DIR/download.sh" --audio-only "$LINKS" -o "$OUTPUT_DIR"

echo ""
echo "### [3/3] Transcribing: $OUTPUT_DIR"
"$SCRIPT_DIR/transcribe.sh" "$OUTPUT_DIR"

echo ""
echo "### Pipeline complete."
echo "    Links:       $LINKS"
echo "    Media:       $OUTPUT_DIR"
echo "    Transcripts: $OUTPUT_DIR/*.txt"

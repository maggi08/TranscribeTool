# youtube-tools

Three composable tools for working with YouTube content, sharing a single `.venv`:

| Script | What it does |
|---|---|
| `parse.sh` | Scrape a channel → list every video URL (videos + shorts + streams) into `links.txt` |
| `download.sh` | Download YouTube URLs as MP4 via [yt-dlp](https://github.com/yt-dlp/yt-dlp) |
| `transcribe.sh` | Batch transcribe a folder of media via [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) |
| `pipeline.sh` | Convenience wrapper that runs all three back-to-back |

## Setup

```bash
chmod +x install.sh parse.sh download.sh transcribe.sh pipeline.sh
./install.sh
```

`install.sh` installs system deps (Python 3.10+, ffmpeg — via Homebrew on macOS, apt on Debian/Ubuntu) and creates a local `.venv/` with `yt-dlp` and `mlx-whisper`.

## Usage

### 1. Parse a channel

```bash
# All tabs (videos + shorts + streams), default output ./links.txt
./parse.sh @channelname

# Pick the output file
./parse.sh @channelname -o ~/videos/channel/links.txt

# Specific tabs
./parse.sh @channelname --tabs videos,shorts

# Single tab via URL
./parse.sh https://www.youtube.com/@channelname/videos

# Cap per tab (great for testing on big channels)
./parse.sh @channelname --limit 20
```

Accepts `@handle`, full channel URL, or a tab URL (`/videos`, `/shorts`, `/streams`). Output is one URL per line — exactly what `download.sh` expects. Duplicates across tabs are removed while preserving discovery order.

### 2. Download

```bash
./download.sh links.txt
./download.sh "URL1" "URL2" "URL3"
./download.sh -o ~/Downloads links.txt
./download.sh --audio-only links.txt     # m4a, ~10x smaller — ideal for transcription
```

Output folder defaults to the folder of the `.txt` file (or cwd). Files saved as `<video_title>.mp4` (or `.m4a` with `--audio-only`). See the per-video progress + summary at the end; exit code 1 if any download failed.

### 3. Transcribe

```bash
./transcribe.sh ~/videos/channel
./transcribe.sh ~/videos/channel/one_file.mp4
./transcribe.sh ~/videos/channel --language en     # flags pass through to mlx_whisper
```

Recursively finds media files, splits anything >10 min into 10-min chunks to keep RAM under control, writes a `.txt` transcript next to each media file. Progress is saved in `.transcribe_done.log` inside the target folder — re-run the same command to resume after a crash.

### 4. Full pipeline

```bash
./pipeline.sh @channelname ~/videos/channelname
./pipeline.sh @channelname ~/videos/channelname --limit 3    # smoke test
```

Writes `links.txt`, downloads audio-only (`.m4a`) by default since the next step transcribes them, then runs mlx-whisper over everything — all under `~/videos/channelname/`.

## Project layout

```
youtube-tools/
├── install.sh          # One-time setup: system deps + shared .venv
├── requirements.txt    # yt-dlp[default], mlx-whisper
├── parse.sh            # wrapper → parse.py
├── parse.py            # channel → links.txt (yt-dlp extract_flat)
├── download.sh         # wrapper → download.py
├── download.py         # links → MP4s (yt-dlp)
├── transcribe.sh       # media → .txt transcripts (mlx-whisper + ffmpeg)
├── pipeline.sh         # parse + download + transcribe in sequence
└── .gitignore
```

## Troubleshooting

**`Error: virtual environment not found` / `Error: mlx-whisper not found`** — Run `./install.sh` first.

**`HTTP Error 403: Forbidden` / `Requested format is not available`** — YouTube changed something. Refresh deps: `.venv/bin/pip install --upgrade -r requirements.txt`.

**Empty parser output** — Some channels hide tabs. Try `--tabs videos` alone, or pass a direct tab URL like `https://www.youtube.com/@name/videos`.

**Resuming a crashed transcription** — just re-run `./transcribe.sh <same folder>`. The `.transcribe_done.log` skips finished files; partially-chunked long files resume from the last completed chunk.

**Starting over** — Delete `.venv/` and re-run `./install.sh`.

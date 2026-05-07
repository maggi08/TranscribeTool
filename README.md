# TranscribeTool

A small toolkit for scraping, downloading, and transcribing YouTube content. Ships as:

- A **desktop GUI** (PySide6) — paste a channel / URLs / `.txt`, toggle options, watch live progress. `./run-gui.sh`
- Four **composable shell scripts** that share one `.venv`:

| Script | What it does |
|---|---|
| `parse.sh` | Scrape a channel → list every video URL (videos + shorts + streams) into `links.txt` |
| `download.sh` | Download YouTube URLs as MP4 (or `.m4a` with `--audio-only`) via [yt-dlp](https://github.com/yt-dlp/yt-dlp) |
| `transcribe.sh` | Batch transcribe a folder of media — uses [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) on Apple Silicon, [faster-whisper](https://github.com/SYSTRAN/faster-whisper) elsewhere |
| `pipeline.sh` | Convenience wrapper that runs all three back-to-back |

## Setup

```bash
chmod +x install.sh parse.sh download.sh transcribe.sh pipeline.sh
./install.sh
```

`install.sh` installs system deps (Python 3.10+, ffmpeg — via Homebrew on macOS, apt on Debian/Ubuntu) and creates a local `.venv/` with `yt-dlp`, `mlx-whisper` (on Apple Silicon), and `faster-whisper`.

To use the desktop GUI as well:

```bash
./.venv/bin/pip install -r requirements-gui.txt
./run-gui.sh
```

## Desktop GUI

Launch with `./run-gui.sh` (installs PySide6 on first run if missing). The window has four tabs:

- **Parse channel** — channel handle/URL, tab selection, per-tab limit, output file.
- **Download** — paste URLs or pick a `.txt`, toggle audio-only, pick destination.
- **Transcribe** — pick a file or folder, pick a language, toggle **Low power mode** (forces `faster-whisper` to save battery at the cost of speed).
- **Pipeline** — parse → download → transcribe chained in one click.

A shared log pane streams live subprocess output. `Cmd+,` opens Preferences (default save folder, default language, Performance: Fast vs Low power). Settings persist at `~/Library/Application Support/TranscribeTool/config.json` (macOS) or `%APPDATA%\TranscribeTool\config.json` (Windows).

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
transcribe-tool/
├── app.py                  # GUI entry point
├── run-gui.sh              # launches the desktop GUI from source
├── transcribe_tool/        # PySide6 GUI package
├── install.sh              # One-time setup: system deps + shared .venv
├── requirements.txt        # CLI runtime deps
├── requirements-gui.txt    # + PySide6 for the GUI
├── pyproject.toml          # project metadata, extras, PyInstaller entry
├── parse.sh / parse.py     # channel → links.txt (yt-dlp extract_flat)
├── download.sh / .py       # links → media files (yt-dlp, audio-only supported)
├── transcribe.sh / .py     # media → .txt transcripts (mlx / faster-whisper)
├── pipeline.sh             # parse + download + transcribe in sequence
├── packaging/              # PyInstaller spec, ffmpeg fetch, DMG builder
├── docs/                   # GitHub Pages landing page
└── .gitignore
```

## Troubleshooting

**`Error: virtual environment not found` / `Error: mlx-whisper not found`** — Run `./install.sh` first.

**`HTTP Error 403: Forbidden` / `Requested format is not available`** — YouTube changed something. Refresh deps: `.venv/bin/pip install --upgrade -r requirements.txt`.

**Empty parser output** — Some channels hide tabs. Try `--tabs videos` alone, or pass a direct tab URL like `https://www.youtube.com/@name/videos`.

**Resuming a crashed transcription** — just re-run `./transcribe.sh <same folder>`. The `.transcribe_done.log` skips finished files; partially-chunked long files resume from the last completed chunk.

**Starting over** — Delete `.venv/` and re-run `./install.sh`.

## Packaging (distributable installer — v1: macOS + Windows)

```bash
./.venv/bin/pip install -r requirements-gui.txt pyinstaller
./packaging/fetch_ffmpeg.sh                          # drops static ffmpeg into packaging/bin/
./.venv/bin/pyinstaller packaging/transcribe-tool.spec # builds dist/TranscribeTool.app (macOS) or .exe (Windows)
./packaging/make_dmg.sh                              # macOS only — wraps the .app into a .dmg
```

Known v1 caveats:
- No code signing / notarization yet — on macOS, the first launch will need a right-click → Open to bypass Gatekeeper.
- macOS build is arm64-only. Intel Macs fall back to the CLI install.
- Linux AppImage deferred to v2.

## Landing page

A static marketing page lives at [docs/index.html](docs/index.html). To publish it on GitHub Pages:

1. Push the repo to GitHub.
2. Search-replace `YOUR_USERNAME` in [docs/index.html](docs/index.html) with your GitHub handle.
3. GitHub → repo **Settings → Pages → Build and deployment → Source: Deploy from a branch**.
4. Pick branch `main`, folder `/docs`, Save.
5. Wait ~1 minute → site live at `https://<your-handle>.github.io/transcribe-tool/`.

The download button links to `releases/latest/download/TranscribeTool-macos-arm64.dmg`, so every new release just needs that exact asset name attached — no page edits required.

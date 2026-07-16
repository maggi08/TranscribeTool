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

Pick a smaller model when quality can suffer: `--model tiny|base|small|medium|large-v3`
(default `large-v3`, or set `WHISPER_MODEL`). `tiny` is 71 MB against 2.9 GB.

#### Memory safety — read this if the Mac ever reboots on you

`large-v3` holds **~2.9 GB** of unified memory. On an 8 GB Mac that survives on its own,
but **not** alongside a nearly-full disk: macOS swaps, cannot grow swap when the disk is
full, the kernel stalls on memory allocation and the hardware watchdog reboots the machine.
That produced three kernel panics on 2026-07-13..15 (`watchdog timeout` + `LOW swap space`).

Two guards live in `transcribe.py`:

- **Disk preflight** — refuses to start below 8 GB free, re-checked before every file
  (a long run fills the disk itself with downloads, chunks and transcripts). Tune with
  `WHISPER_MIN_DISK_GB`; `0` disables it.
- **Global lock** (`~/.cache/whisper/transcribe.lock`) — one whisper process per machine.
  Shared with the [pako](../pako) assistant, which also transcribes (Telegram voice
  messages): if its bot is mid-transcription your run waits instead of loading a second
  2.9 GB model. Seeing `waiting for the global lock` is normal, not a hang.

> `transcribe.py` is kept **byte-identical** with `pako/.claude/skills/transcribe/scripts/transcribe.py`.
> Fix a bug in one, copy to the other — they were forked once and silently drifted apart.
> It must stay Python 3.9-compatible (pako's skill venv is the system Python).

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

## Building the desktop installer (macOS)

### 1. Build the `.app` for yourself

For installing on your own machine, you can skip ffmpeg bundling — the GUI's `paths.py` adds `/opt/homebrew/bin` and `/usr/local/bin` to subprocess PATH automatically, so brew's `ffmpeg` is picked up:

```bash
.venv/bin/pip install pyinstaller
.venv/bin/pyinstaller packaging/transcribe-tool.spec --clean --noconfirm
cp -R dist/TranscribeTool.app /Applications/
xattr -dr com.apple.quarantine /Applications/TranscribeTool.app  # bypass Gatekeeper on first launch
open /Applications/TranscribeTool.app
```

Build takes 3–8 minutes; the resulting `.app` is ~900 MB.

### 2. Build a **distributable** `.dmg` for other users

Other users won't have your brew ffmpeg, so you must bundle a static `ffmpeg`/`ffprobe`. This requires internet — run from your **own terminal**, not a sandboxed shell:

```bash
./packaging/fetch_ffmpeg.sh                          # downloads from evermeet.cx into packaging/bin/macos-arm64/
.venv/bin/pyinstaller packaging/transcribe-tool.spec --clean --noconfirm
brew install create-dmg                              # one-time
./packaging/make_dmg.sh                              # writes dist/TranscribeTool-macos-arm64.dmg
```

### 3. Release

```bash
gh repo create TranscribeTool --public --source=. --push   # first time only
gh release create v0.1.0 dist/TranscribeTool-macos-arm64.dmg \
    --title "v0.1.0 — first public build" \
    --notes "Drag the app into Applications. On first launch macOS will block it — see https://maggi08.github.io/TranscribeTool/#first-launch for the 2 ways to bypass (System Settings or a one-line Terminal command)."
```

Users now download the DMG via the landing page download button (which points at `releases/latest/download/TranscribeTool-macos-arm64.dmg`) or by visiting `https://github.com/maggi08/TranscribeTool/releases`.

### v1 caveats
- **No code signing / notarization** — on macOS, the first launch shows a Gatekeeper warning (*"Apple could not verify TranscribeTool is free of malware"*). Recent macOS versions don't offer "Open Anyway" in the dialog itself — see [First launch on macOS](#first-launch-on-macos) below. Cost of fixing: $99/yr Apple Developer account; deferred to v2.
- **macOS build is arm64-only**. Intel Macs fall back to the CLI install (`./install.sh`).
- **Windows** build needs to be done on a Windows machine (PyInstaller can't cross-compile from macOS) — same spec file.
- **Linux** AppImage deferred to v2.

### First launch on macOS

Because we're not code-signed, macOS Gatekeeper blocks the app the first time. Two ways to bypass — pick whichever is easier:

**Option A — System Settings:**
1. Close the warning dialog.
2. Open **System Settings → Privacy & Security**.
3. Scroll to the **Security** section.
4. You'll see *"TranscribeTool was blocked from use…"* → click **Open Anyway**.
5. The warning reappears once with an **Open** button — click it. Done.

**Option B — Terminal (one command, no dialogs):**
```bash
xattr -dr com.apple.quarantine /Applications/TranscribeTool.app
```
Then double-click the app normally — no warning at all.

Either way, you only do this once. Subsequent launches are a normal double-click.

### What stays on disk after uninstall

Drag `TranscribeTool.app` to Trash and **two folders leak**:
- `~/Library/Application Support/TranscribeTool/` — your settings (a few KB).
- `~/.cache/huggingface/hub/models--Systran--faster-whisper-large-v3/` — the Whisper model (~3 GB; shared with any other Hugging Face app on the machine).

Delete those manually for a clean wipe.

## Landing page

A static marketing page lives at [docs/index.html](docs/index.html). To publish it on GitHub Pages:

1. Push the repo to GitHub.
2. Search-replace `YOUR_USERNAME` in [docs/index.html](docs/index.html) with your GitHub handle.
3. GitHub → repo **Settings → Pages → Build and deployment → Source: Deploy from a branch**.
4. Pick branch `main`, folder `/docs`, Save.
5. Wait ~1 minute → site live at `https://maggi08.github.io/TranscribeTool/`.

The download button links to `releases/latest/download/TranscribeTool-macos-arm64.dmg`, so every new release just needs that exact asset name attached — no page edits required.

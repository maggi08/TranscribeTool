#!/usr/bin/env python3
"""Migrate an old TranscribeTool folder to the new "[id]-suffixed" naming.

Old runs saved files as `<title>.m4a` / `<title>.txt`. The current version
saves them as `<title> [<youtube_id>].m4a` to avoid name collisions when a
channel reuses the same title across multiple videos. This script makes an
old folder compatible with the new scheme so re-running the pipeline on it
won't redownload or re-transcribe anything.

What it does:

1. Reads `links.txt` from the folder, extracts every YouTube ID, and adds
   them to `.yt-dlp-archive.txt`. yt-dlp will then skip every video it sees
   in the archive on future runs.

2. With `--rename`, also fetches each video's title via yt-dlp and renames
   matching local `.m4a` / `.mp4` / `.txt` files to `<title> [<id>].<ext>`.
   This way `transcribe.py` will skip them even after a force re-download,
   because the new media filename's stem matches the renamed transcript.

Usage:
    .venv/bin/python migrate_folder.py /path/to/channel-folder
    .venv/bin/python migrate_folder.py /path/to/channel-folder --rename
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ID_PATTERNS = re.compile(
    r"(?:watch\?v=|/shorts/|/live/|/embed/|youtu\.be/)([A-Za-z0-9_-]{11})"
)
ALREADY_TAGGED = re.compile(r"\[[A-Za-z0-9_-]{11}\]$")
MEDIA_EXTS = {".m4a", ".mp4", ".mp3", ".wav", ".webm", ".mkv", ".mov",
              ".flac", ".ogg", ".opus", ".aac", ".wma", ".avi"}


def extract_id(url: str) -> str | None:
    m = ID_PATTERNS.search(url)
    return m.group(1) if m else None


def normalise(s: str) -> str:
    """Title comparison key — strip trailing junk, lowercase, collapse spaces."""
    s = s.strip().rstrip(". ")
    s = re.sub(r"\s+", " ", s)
    return s.casefold()


def populate_archive(folder: Path) -> tuple[int, int]:
    """Add every video ID from links.txt to .yt-dlp-archive.txt.

    Returns (added, total).
    """
    links_file = folder / "links.txt"
    if not links_file.exists():
        print(f"  (skip archive population — no links.txt in {folder})")
        return (0, 0)

    archive = folder / ".yt-dlp-archive.txt"
    existing: set[str] = set()
    if archive.exists():
        existing = set(archive.read_text(encoding="utf-8").splitlines())

    urls = [u.strip() for u in links_file.read_text(encoding="utf-8").splitlines()
            if u.strip() and not u.strip().startswith("#")]

    added = 0
    with archive.open("a", encoding="utf-8") as f:
        for url in urls:
            vid = extract_id(url)
            if not vid:
                continue
            entry = f"youtube {vid}"
            if entry not in existing:
                f.write(entry + "\n")
                existing.add(entry)
                added += 1
    return (added, len(urls))


def fetch_title_id_map(urls: list[str]) -> dict[str, str]:
    """Returns ID → title using yt-dlp metadata-only extraction."""
    try:
        import yt_dlp
    except ImportError:
        print("Error: yt-dlp not installed. Run from the project venv.", file=sys.stderr)
        sys.exit(1)

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "extractor_args": {"youtube": {"player_client": ["android_vr", "web"]}},
    }
    id_to_title: dict[str, str] = {}
    with yt_dlp.YoutubeDL(opts) as ydl:
        for i, url in enumerate(urls, 1):
            print(f"  [{i}/{len(urls)}] fetching metadata...", end="\r")
            try:
                info = ydl.extract_info(url, download=False)
            except Exception as e:
                print(f"\n  skip {url}: {e}")
                continue
            if not info:
                continue
            title = (info.get("title") or "").strip()
            vid = info.get("id")
            if title and vid:
                id_to_title[vid] = title
    print()
    return id_to_title


def rename_pass(folder: Path, id_to_title: dict[str, str]) -> int:
    """Rename existing .m4a/.txt without [id] suffix to include it.

    Returns number of files renamed.
    """
    # Group IDs by normalised title so we can pick one per matching file
    title_groups: dict[str, list[str]] = {}
    for vid, title in id_to_title.items():
        title_groups.setdefault(normalise(title), []).append(vid)

    # Iterate files, attempt to match
    used: set[str] = set()
    renamed = 0
    for f in sorted(folder.iterdir()):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext != ".txt" and ext not in MEDIA_EXTS:
            continue
        if ALREADY_TAGGED.search(f.stem):
            continue  # already in new form
        key = normalise(f.stem)
        candidates = title_groups.get(key, [])
        # Pick first unused, else first overall (collisions documented in output)
        pick = next((vid for vid in candidates if vid not in used), None)
        if pick is None and candidates:
            pick = candidates[0]
        if pick is None:
            continue
        used.add(pick)
        new_name = f.with_name(f"{f.stem} [{pick}]{f.suffix}")
        if new_name.exists():
            print(f"  conflict (target exists): {f.name} → {new_name.name}")
            continue
        try:
            f.rename(new_name)
            print(f"  renamed: {f.name} → {new_name.name}")
            renamed += 1
        except OSError as e:
            print(f"  failed: {f.name}: {e}")
    return renamed


def find_existing_ids(folder: Path) -> set[str]:
    """Scan folder for any '*[<id>].<ext>' file (txt or media); return matched IDs."""
    found: set[str] = set()
    pat = re.compile(r"\[([A-Za-z0-9_-]{11})\]$")
    for f in folder.iterdir():
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext != ".txt" and ext not in MEDIA_EXTS:
            continue
        m = pat.search(f.stem)
        if m:
            found.add(m.group(1))
    return found


def rebuild_archive(folder: Path) -> tuple[int, int]:
    """Rewrite .yt-dlp-archive.txt so it lists only IDs that have a matching
    '[<id>].txt' transcript already on disk.

    Returns (kept, removed).
    """
    links_file = folder / "links.txt"
    if not links_file.exists():
        print("  no links.txt — skipping archive rebuild")
        return (0, 0)

    urls = [u.strip() for u in links_file.read_text(encoding="utf-8").splitlines()
            if u.strip() and not u.strip().startswith("#")]
    expected_ids = []
    for u in urls:
        vid = extract_id(u)
        if vid:
            expected_ids.append(vid)

    # Which IDs have a transcript on disk?
    have_transcript: set[str] = set()
    pat = re.compile(r"\[([A-Za-z0-9_-]{11})\]\.txt$")
    for f in folder.iterdir():
        if not f.is_file() or f.suffix.lower() != ".txt":
            continue
        m = pat.search(f.name)
        if m:
            have_transcript.add(m.group(1))

    archive = folder / ".yt-dlp-archive.txt"
    kept = 0
    removed = 0
    new_lines: list[str] = []
    for vid in expected_ids:
        if vid in have_transcript:
            new_lines.append(f"youtube {vid}")
            kept += 1
        else:
            removed += 1
    archive.write_text("\n".join(new_lines) + ("\n" if new_lines else ""),
                       encoding="utf-8")
    return (kept, removed)


def delete_tiny_transcripts(folder: Path, min_bytes: int = 50) -> int:
    """Remove .txt transcripts smaller than min_bytes (these are typically
    failed-transcription artefacts — empty or one-word output).

    Returns the number of files deleted.
    """
    deleted = 0
    for f in folder.iterdir():
        if not f.is_file() or f.suffix.lower() != ".txt":
            continue
        if f.name == "links.txt":
            continue
        try:
            if f.stat().st_size < min_bytes:
                f.unlink()
                deleted += 1
        except OSError:
            pass
    return deleted


def dedupe_pass(folder: Path) -> tuple[int, int]:
    """Find pairs where both '<stem>.<ext>' and '<stem> [<id>].<ext>' exist
    and move the un-tagged version into a '.duplicates' subfolder.

    Returns (txt_moved, media_moved).
    """
    duplicates_dir = folder / ".duplicates"
    txt_moved = 0
    media_moved = 0

    for f in sorted(folder.iterdir()):
        if not f.is_file():
            continue
        if not ALREADY_TAGGED.search(f.stem):
            continue
        ext = f.suffix.lower()
        if ext != ".txt" and ext not in MEDIA_EXTS:
            continue
        # Strip " [id]" from end of stem
        old_stem = re.sub(r" \[[A-Za-z0-9_-]{11}\]$", "", f.stem)
        old_file = f.with_name(f"{old_stem}{f.suffix}")
        if not old_file.exists() or old_file == f:
            continue
        duplicates_dir.mkdir(exist_ok=True)
        target = duplicates_dir / old_file.name
        # If something already at target (shouldn't normally), suffix it
        if target.exists():
            target = duplicates_dir / f"{old_file.stem}.dup{old_file.suffix}"
        try:
            old_file.rename(target)
            if ext == ".txt":
                txt_moved += 1
                print(f"  moved (txt): {old_file.name}")
            else:
                media_moved += 1
                print(f"  moved (media): {old_file.name}")
        except OSError as e:
            print(f"  failed to move {old_file.name}: {e}")

    return (txt_moved, media_moved)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", help="Channel output folder (the one containing links.txt)")
    parser.add_argument("--rename", action="store_true",
                        help="Also rename existing .m4a/.txt to include the YouTube ID. "
                             "Requires network access (fetches metadata for each URL).")
    parser.add_argument("--dedupe", action="store_true",
                        help="Move legacy-named files into a '.duplicates' subfolder when "
                             "an '[id]'-named counterpart already exists. Safe — moves, doesn't delete.")
    parser.add_argument("--rebuild-archive", action="store_true",
                        help="Rewrite .yt-dlp-archive.txt to contain only IDs whose "
                             "'[<id>].txt' transcript exists on disk. IDs without a transcript "
                             "get removed from the archive so the next pipeline run downloads them.")
    parser.add_argument("--delete-tiny", action="store_true",
                        help="Delete .txt files smaller than 50 bytes (likely failed transcribes "
                             "of very short shorts) so they're treated as missing.")
    args = parser.parse_args()

    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        print(f"Error: not a folder: {folder}", file=sys.stderr)
        return 1

    print(f"=== Migrating: {folder} ===\n")

    # Step 1 — populate archive
    print("[1/5] Populating .yt-dlp-archive.txt...")
    added, total = populate_archive(folder)
    print(f"  added {added} new entries (of {total} URLs in links.txt)")

    # Step 2 — dedupe pass
    if args.dedupe:
        print("\n[2/5] Deduping old-named files that already have [id]-tagged twins...")
        txt_moved, media_moved = dedupe_pass(folder)
        print(f"  moved {txt_moved} legacy .txt + {media_moved} legacy media files "
              f"to {folder / '.duplicates'}/")
    else:
        print("\n[2/5] (skipped — pass --dedupe)")

    # Step 3 — delete tiny / failed transcripts
    if args.delete_tiny:
        print("\n[3/5] Deleting tiny .txt files (<50 bytes — likely failed transcribes)...")
        n = delete_tiny_transcripts(folder)
        print(f"  deleted {n} tiny .txt file(s)")
    else:
        print("\n[3/5] (skipped — pass --delete-tiny)")

    # Step 4 — rename
    if args.rename:
        print("\n[4/5] Renaming remaining old files to include [id]...")
        links_file = folder / "links.txt"
        if not links_file.exists():
            print("  no links.txt — skipping rename")
        else:
            urls = [u.strip() for u in links_file.read_text(encoding="utf-8").splitlines()
                    if u.strip() and not u.strip().startswith("#")]
            id_to_title = fetch_title_id_map(urls)
            renamed = rename_pass(folder, id_to_title)
            print(f"  renamed {renamed} file(s)")
    else:
        print("\n[4/5] (skipped — pass --rename)")

    # Step 5 — rebuild archive
    if args.rebuild_archive:
        print("\n[5/5] Rebuilding .yt-dlp-archive.txt to match on-disk transcripts...")
        kept, removed = rebuild_archive(folder)
        print(f"  kept {kept} entries (have [id].txt on disk), "
              f"removed {removed} (no transcript — will be re-downloaded)")
    else:
        print("\n[5/5] (skipped — pass --rebuild-archive)")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

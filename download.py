import argparse
import json
import os
import re
import sys
from pathlib import Path

import yt_dlp


def _network_opts(output_dir, cookies_browser):
    """Shared yt-dlp options for talking to YouTube (client + JS runtime +
    cookies + output template). Used by inspection, subtitle fetch, and the
    media download so they behave identically."""
    # Pick yt-dlp YouTube clients depending on whether we have cookies:
    # - cookies present: 'android_vr' is skipped (it doesn't support cookies),
    #   so use 'mweb' + 'tv' + 'web' which all support cookies.
    # - no cookies:      keep 'android_vr' as the primary (best at bypassing
    #   anti-bot when unauthenticated), with 'web' as fallback.
    # YouTube now applies the n-challenge across all these clients, so a JS
    # runtime (see js_runtimes below) is required to unlock real formats.
    if cookies_browser:
        player_clients = ["mweb", "tv", "web"]
    else:
        player_clients = ["android_vr", "web"]
    opts = {
        "outtmpl": os.path.join(output_dir, "%(title).180B [%(id)s].%(ext)s"),
        "extractor_args": {"youtube": {"player_client": player_clients}},
        # Enable JS runtimes for YouTube's n-challenge. yt-dlp enables only
        # `deno` by default; include `node` (already installed, >=23.5.0) so
        # no extra install is required. deno stays first so it's preferred if
        # present. yt-dlp probes availability and skips runtimes not installed.
        "js_runtimes": {"deno": {}, "node": {}},
    }
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)
    return opts


def subtitle_to_text(path):
    """Convert a downloaded subtitle file to clean transcript text — one line
    per segment, matching transcribe.py's Whisper output format. Supports
    YouTube's json3 (preferred, discrete segments) and vtt/srt (fallback)."""
    p = Path(path)
    ext = p.suffix.lower()
    lines = []
    if ext == ".json3":
        data = json.loads(p.read_text(encoding="utf-8"))
        for ev in data.get("events") or []:
            segs = ev.get("segs") or []
            text = "".join(s.get("utf8", "") for s in segs).strip()
            if text:
                lines.append(text)
    else:
        # vtt / srt: drop cue metadata and inline tags, keep spoken text.
        tag_re = re.compile(r"<[^>]+>")
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or "-->" in line or line.isdigit():
                continue
            if line.startswith(("WEBVTT", "NOTE", "Kind:", "Language:")):
                continue
            line = tag_re.sub("", line).strip()
            if line:
                lines.append(line)
    # Collapse consecutive duplicate lines (auto-caption rolling repeats).
    out = []
    for line in lines:
        if not out or out[-1] != line:
            out.append(line)
    return "\n".join(out)


def _record_archive(archive, video_id, force):
    """Append a yt-dlp archive entry so future runs skip this video (we only
    grabbed its subtitle, so yt-dlp's own archive wouldn't record it)."""
    if force or not archive or not video_id:
        return
    line = f"youtube {video_id}\n"
    try:
        existing = ""
        if os.path.exists(archive):
            existing = Path(archive).read_text(encoding="utf-8")
        if line not in existing:
            with open(archive, "a", encoding="utf-8") as f:
                f.write(line)
    except OSError:
        pass


def _try_subtitle_first(url, output_dir, language, cookies_browser, archive, force):
    """If the video has *good* subtitles (human/manual, or the original-language
    auto-caption `<lang>-orig`), fetch only the subtitle, convert it to the
    transcript .txt, and return the title. Return None to fall back to a normal
    media download (no good subtitles, or anything went wrong)."""
    try:
        inspect = _network_opts(output_dir, cookies_browser)
        inspect.update({"skip_download": True, "quiet": True, "no_warnings": True})
        with yt_dlp.YoutubeDL(inspect) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None
            tl = language or info.get("language")
            if not tl:
                return None
            manual = info.get("subtitles") or {}
            auto = info.get("automatic_captions") or {}
            orig_key = f"{tl}-orig"
            if tl in manual:
                key, want_auto, kind = tl, False, "manual"
            elif orig_key in auto:
                key, want_auto, kind = orig_key, True, "auto-orig"
            else:
                return None  # translated auto-captions deliberately excluded
            txt_path = os.path.splitext(ydl.prepare_filename(info))[0] + ".txt"
            title = info.get("title") or url
            video_id = info.get("id")

        if os.path.exists(txt_path) and not force:
            print(f"  Skipping (transcript exists): {os.path.basename(txt_path)}")
            _record_archive(archive, video_id, force)
            return title

        sub_opts = _network_opts(output_dir, cookies_browser)
        sub_opts.update({
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "subtitleslangs": [key],
            "subtitlesformat": "json3/vtt/best",
            "writesubtitles": not want_auto,
            "writeautomaticsub": want_auto,
        })
        with yt_dlp.YoutubeDL(sub_opts) as ydl:
            info2 = ydl.extract_info(url, download=True)
        entry = ((info2 or {}).get("requested_subtitles") or {}).get(key)
        if not entry or not entry.get("filepath"):
            return None
        sub_path = Path(entry["filepath"])
        text = subtitle_to_text(sub_path)
        sub_path.unlink(missing_ok=True)
        if not text.strip():
            return None  # empty subtitle — let Whisper handle it
        Path(txt_path).write_text(text + "\n", encoding="utf-8")
        _record_archive(archive, video_id, force)
        print(f"  ✓ subtitle ({key}, {kind}) → wrote transcript, "
              f"skipped download + transcribe")
        return title
    except Exception as e:
        print(f"  (subtitle-first failed: {e} — falling back to download)")
        return None


def download(url, output_dir, audio_only=False, force=False, cookies_browser=None,
             language=None, prefer_subtitles=False):
    archive = os.path.join(output_dir, ".yt-dlp-archive.txt")

    if prefer_subtitles:
        title = _try_subtitle_first(url, output_dir, language, cookies_browser,
                                    archive, force)
        if title is not None:
            return title, "subtitle"

    opts = _network_opts(output_dir, cookies_browser)
    opts.update({"quiet": False, "no_warnings": False, "overwrites": False})
    if not force:
        opts["download_archive"] = archive
    if audio_only:
        opts["format"] = "bestaudio[ext=m4a]/bestaudio"
    else:
        opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        opts["merge_output_format"] = "mp4"
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if not info:
            return url, "media"  # archived / skipped — treated as success
        return info.get("title") or url, "media"


def read_links_from_file(filepath):
    links = []
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                links.append(line)
    return links


def parse_args():
    parser = argparse.ArgumentParser(
        prog="download.sh",
        description="Download YouTube videos via yt-dlp.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  ./download.sh "https://youtu.be/VIDEO_ID"
  ./download.sh "URL1" "URL2" "URL3"
  ./download.sh links.txt
  ./download.sh -o ~/Downloads "URL1" "URL2"
  ./download.sh --output /path/to/folder links.txt
  ./download.sh --audio-only links.txt
""",
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="YouTube URLs and/or paths to .txt files containing URLs",
    )
    parser.add_argument(
        "-o", "--output",
        help="Folder to save downloads. "
             "Defaults to the folder of the .txt file (if given) or current directory.",
    )
    parser.add_argument(
        "-a", "--audio-only",
        action="store_true",
        help="Download audio only (m4a). ~10x smaller; ideal for transcription.",
    )
    parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Re-download even if the video is already in the archive "
             "(<output_dir>/.yt-dlp-archive.txt).",
    )
    parser.add_argument(
        "--cookies-from-browser",
        default=None,
        choices=["chrome", "safari", "firefox", "brave", "edge", "chromium", "opera", "vivaldi"],
        help="Use cookies from a browser where you're signed into YouTube. "
             "Bypasses 'Sign in to confirm you're not a bot' errors and "
             "lets you download age-restricted videos.",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Target language code (e.g. ru, en) for --prefer-subtitles. "
             "If omitted, the video's own detected language is used.",
    )
    parser.add_argument(
        "--prefer-subtitles",
        action="store_true",
        help="If a video has good subtitles (human, or the original-language "
             "auto-caption), download only the subtitle and write it as the "
             "transcript .txt — skipping the media download and transcription.",
    )
    return parser.parse_args()


def resolve_inputs(inputs, output_override):
    links = []
    file_dir = None

    for arg in inputs:
        if os.path.isfile(arg):
            file_dir = os.path.dirname(os.path.abspath(arg))
            links.extend(read_links_from_file(arg))
        else:
            links.append(arg)

    if output_override:
        output_dir = os.path.abspath(os.path.expanduser(output_override))
    elif file_dir:
        output_dir = file_dir
    else:
        output_dir = os.getcwd()

    return links, output_dir


def main():
    args = parse_args()
    links, output_dir = resolve_inputs(args.inputs, args.output)

    if not links:
        print("No links found.")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    total = len(links)
    bar = "=" * 60
    mode = "audio-only (m4a)" if args.audio_only else "video (mp4)"

    print(bar)
    print(f"Downloading {total} item(s) — {mode}")
    if args.prefer_subtitles:
        print("Prefer subtitles: on (skip download + transcribe when good subs exist)")
    print(f"Destination: {output_dir}")
    print(bar + "\n")

    succeeded = []
    failed = []
    subtitle_count = 0

    for i, link in enumerate(links, 1):
        print(f"\n[{i}/{total}] {link}")
        print("-" * 60)
        try:
            title, source = download(
                link, output_dir, audio_only=args.audio_only,
                force=args.force, cookies_browser=args.cookies_from_browser,
                language=args.language, prefer_subtitles=args.prefer_subtitles,
            )
            succeeded.append((link, title))
            if source == "subtitle":
                subtitle_count += 1
            print(f"\n  ✓ [{i}/{total}] Done: {title}")
        except Exception as e:
            failed.append((link, str(e)))
            print(f"\n  ✗ [{i}/{total}] Failed: {e}")

    print("\n" + bar)
    summary = f"Summary: {len(succeeded)} succeeded, {len(failed)} failed (of {total})"
    if subtitle_count:
        summary += f" — {subtitle_count} via subtitles (no download/transcribe)"
    print(summary)
    print(bar)

    if failed:
        print("\nFailed downloads:")
        for link, err in failed:
            print(f"  - {link}")
            print(f"      {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()

import argparse
import os
import sys
import yt_dlp


def download(url, output_dir, audio_only=False, force=False, cookies_browser=None):
    archive = os.path.join(output_dir, ".yt-dlp-archive.txt")
    # Pick yt-dlp YouTube clients depending on whether we have cookies:
    # - cookies present: 'android_vr' is skipped (it doesn't support cookies),
    #   so use 'mweb' + 'tv' + 'web' which all support cookies and avoid the
    #   web-only n-challenge JS obfuscation.
    # - no cookies:      keep 'android_vr' as the primary (best at bypassing
    #   anti-bot when unauthenticated), with 'web' as fallback.
    if cookies_browser:
        player_clients = ["mweb", "tv", "web"]
    else:
        player_clients = ["android_vr", "web"]
    opts = {
        "outtmpl": os.path.join(output_dir, "%(title).180B [%(id)s].%(ext)s"),
        "quiet": False,
        "no_warnings": False,
        "overwrites": False,
        "extractor_args": {"youtube": {"player_client": player_clients}},
    }
    if not force:
        opts["download_archive"] = archive
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)
    if audio_only:
        opts["format"] = "bestaudio[ext=m4a]/bestaudio"
    else:
        opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        opts["merge_output_format"] = "mp4"
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if not info:
            return url  # archived / skipped — treated as success
        return info.get("title") or url


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
    print(f"Destination: {output_dir}")
    print(bar + "\n")

    succeeded = []
    failed = []

    for i, link in enumerate(links, 1):
        print(f"\n[{i}/{total}] {link}")
        print("-" * 60)
        try:
            title = download(link, output_dir, audio_only=args.audio_only,
                             force=args.force, cookies_browser=args.cookies_from_browser)
            succeeded.append((link, title))
            print(f"\n  ✓ [{i}/{total}] Done: {title}")
        except Exception as e:
            failed.append((link, str(e)))
            print(f"\n  ✗ [{i}/{total}] Failed: {e}")

    print("\n" + bar)
    print(f"Summary: {len(succeeded)} succeeded, {len(failed)} failed (of {total})")
    print(bar)

    if failed:
        print("\nFailed downloads:")
        for link, err in failed:
            print(f"  - {link}")
            print(f"      {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()

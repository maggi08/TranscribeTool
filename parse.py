import argparse
import os
import re
import sys
import yt_dlp


DEFAULT_TABS = ("videos", "shorts", "streams")
KNOWN_TABS = {"videos", "shorts", "streams", "live"}

PLAYLIST_ONLY_RE = re.compile(
    r"^https?://(?:www\.)?youtube\.com/playlist\?list=([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
WATCH_WITH_LIST_RE = re.compile(
    r"^https?://(?:www\.)?youtube\.com/watch\?[^#]*[?&]list=([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)


def extract_playlist_url(raw):
    """If `raw` is a YouTube playlist URL (either form), return a canonical
    /playlist?list=ID URL. Otherwise return None.
    """
    s = raw.strip()
    m = PLAYLIST_ONLY_RE.match(s)
    if m:
        return f"https://www.youtube.com/playlist?list={m.group(1)}"
    m = WATCH_WITH_LIST_RE.match(s)
    if m and not m.group(1).startswith("RD"):
        # Skip auto-generated radio mixes (RDxxx) — they're infinite
        return f"https://www.youtube.com/playlist?list={m.group(1)}"
    return None


def normalize_channel(raw):
    """
    Accepts any of:
      @handle
      channelname
      https://www.youtube.com/@handle
      https://www.youtube.com/@handle/videos
      https://www.youtube.com/c/name
      https://www.youtube.com/channel/UCxxxx

    Returns (base_url, explicit_tab_or_None).
    """
    s = raw.strip()

    if s.startswith("http://") or s.startswith("https://"):
        m = re.match(
            r"^(https?://(?:www\.)?youtube\.com/(?:@[^/]+|c/[^/]+|channel/[^/]+|user/[^/]+))(?:/([^/?#]+))?",
            s,
        )
        if not m:
            raise ValueError(f"Unrecognized YouTube channel URL: {raw}")
        base, tab = m.group(1), m.group(2)
        tab = tab if tab in KNOWN_TABS else None
        return base, tab

    if not s.startswith("@"):
        s = "@" + s
    return f"https://www.youtube.com/{s}", None


def normalize_video_url(url):
    """Convert /shorts/<id> URLs to canonical /watch?v=<id> form."""
    m = re.match(r"^https?://(?:www\.)?youtube\.com/shorts/([A-Za-z0-9_-]+)", url)
    if m:
        return f"https://www.youtube.com/watch?v={m.group(1)}"
    return url


def collect_tab(base_url, tab, limit=None, cookies_browser=None):
    """Return the list of video URLs listed on one channel tab."""
    url = f"{base_url}/{tab}"
    return _collect_from_url(url, label=tab, limit=limit, cookies_browser=cookies_browser)


def collect_playlist(playlist_url, limit=None, cookies_browser=None):
    """Return the list of video URLs from a YouTube playlist."""
    return _collect_from_url(playlist_url, label="playlist", limit=limit, cookies_browser=cookies_browser)


def _collect_from_url(url, label, limit=None, cookies_browser=None):
    opts = {
        "extract_flat": True,
        "quiet": True,
        "skip_download": True,
        "ignoreerrors": True,
    }
    if limit:
        opts["playlistend"] = int(limit)
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)

    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as e:
            print(f"  {label}: skipped ({e})")
            return []

    if not info:
        print(f"  {label}: skipped (no data)")
        return []

    entries = info.get("entries") or []
    # YouTube channel tabs sometimes wrap entries inside a sub-playlist level
    flat = []
    for e in entries:
        if not e:
            continue
        if e.get("_type") == "playlist" and e.get("entries"):
            flat.extend(x for x in e["entries"] if x)
        else:
            flat.append(e)

    urls = []
    for e in flat:
        u = e.get("url") or e.get("webpage_url")
        if not u:
            continue
        if not u.startswith("http"):
            u = f"https://www.youtube.com/watch?v={u}"
        urls.append(normalize_video_url(u))

    print(f"  {label}: {len(urls)} videos")
    return urls


def parse_args():
    parser = argparse.ArgumentParser(
        prog="parse.sh",
        description="Collect every video URL from a YouTube channel (videos/shorts/streams).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  ./parse.sh @channelname
  ./parse.sh @channelname -o ~/videos/channel/links.txt
  ./parse.sh https://www.youtube.com/@channelname --tabs videos,shorts
  ./parse.sh https://www.youtube.com/@channelname/videos     # single tab via URL
  ./parse.sh @channelname --limit 20                         # first 20 per tab (testing)
""",
    )
    parser.add_argument(
        "channel",
        help="Channel handle (@name), channel URL, channel tab URL, or playlist URL.",
    )
    parser.add_argument(
        "-o", "--output",
        default="links.txt",
        help="Output .txt path. Default: ./links.txt",
    )
    parser.add_argument(
        "--tabs",
        default=",".join(DEFAULT_TABS),
        help=f"Comma-separated tabs to scrape. Default: {','.join(DEFAULT_TABS)}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max videos per tab (passes playlistend to yt-dlp). Useful for testing.",
    )
    parser.add_argument(
        "--cookies-from-browser",
        default=None,
        choices=["chrome", "safari", "firefox", "brave", "edge", "chromium", "opera", "vivaldi"],
        help="Use cookies from a browser where you're signed into YouTube. "
             "Required for private playlists or when YouTube asks 'are you human?'.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    output_path = os.path.abspath(os.path.expanduser(args.output))
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    bar = "=" * 60

    # Playlist path — short-circuit; tabs / handle logic doesn't apply.
    playlist_url = extract_playlist_url(args.channel)
    if playlist_url:
        print(bar)
        print(f"Playlist: {playlist_url}")
        if args.limit:
            print(f"Limit:    {args.limit}")
        print(f"Output:   {output_path}")
        print(bar)
        all_urls = collect_playlist(playlist_url, limit=args.limit,
                                    cookies_browser=args.cookies_from_browser)
    else:
        try:
            base_url, explicit_tab = normalize_channel(args.channel)
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)

        if explicit_tab:
            tabs = [explicit_tab]
        else:
            tabs = [t.strip() for t in args.tabs.split(",") if t.strip()]
            unknown = [t for t in tabs if t not in KNOWN_TABS]
            if unknown:
                print(f"Warning: unknown tab(s) ignored: {', '.join(unknown)}")
                tabs = [t for t in tabs if t in KNOWN_TABS]
            if not tabs:
                print("Error: no valid tabs requested.")
                sys.exit(1)

        print(bar)
        print(f"Channel: {base_url}")
        print(f"Tabs:    {', '.join(tabs)}")
        if args.limit:
            print(f"Limit:   {args.limit} per tab")
        print(f"Output:  {output_path}")
        print(bar)

        all_urls = []
        for tab in tabs:
            all_urls.extend(collect_tab(base_url, tab, limit=args.limit,
                                        cookies_browser=args.cookies_from_browser))

    deduped = list(dict.fromkeys(all_urls))
    dup_count = len(all_urls) - len(deduped)

    with open(output_path, "w", encoding="utf-8") as f:
        for u in deduped:
            f.write(u + "\n")

    print(bar)
    print(f"Wrote {len(deduped)} URL(s) to {output_path}" +
          (f" ({dup_count} duplicate(s) removed)" if dup_count else ""))
    print(bar)

    if not deduped:
        sys.exit(1)


if __name__ == "__main__":
    main()

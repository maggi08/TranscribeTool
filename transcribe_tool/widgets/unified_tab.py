"""Single-pane UI: paste channel/URLs/files, toggle steps, run."""
from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from .. import backend, config
from ..jobs.pipeline_runner import PipelineRunner
from ..paths import script_path
from ._constants import BROWSERS, LANGUAGES, MEDIA_EXTS
from .drop_text_edit import DropTextEdit

try:
    from parse import normalize_channel
except ImportError:
    normalize_channel = None


# --------------------------------------------------------------- Input parsing

VIDEO_URL_RE = re.compile(
    r"^https?://(?:www\.)?(?:youtube\.com/(?:watch\?v=|shorts/|live/|embed/)|youtu\.be/)[\w-]+",
    re.IGNORECASE,
)
CHANNEL_URL_RE = re.compile(
    r"^https?://(?:www\.)?youtube\.com/(?:@[^/?#]+|c/[^/?#]+|channel/[^/?#]+|user/[^/?#]+)",
    re.IGNORECASE,
)
PLAYLIST_URL_RE = re.compile(
    r"^https?://(?:www\.)?youtube\.com/(?:playlist\?list=|watch\?[^#]*[?&]list=)([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)


@dataclass
class InputAnalysis:
    kind: str  # "channel" | "urls" | "files" | "empty" | "mixed" | "unknown"
    items: list[str]
    message: str  # human-readable status

    @property
    def is_runnable(self) -> bool:
        return self.kind in ("channel", "playlist", "urls", "files")


def _is_existing_path(s: str) -> tuple[bool, bool]:
    """Returns (is_file, is_dir). (False, False) if path doesn't exist."""
    try:
        p = Path(s).expanduser()
        return (p.is_file(), p.is_dir())
    except OSError:
        return (False, False)


HANDLE_RE = re.compile(r"^@?[A-Za-z0-9_.\-]{2,50}$")


def _looks_like_handle(s: str) -> bool:
    """Bare YouTube handle: @magzhan, magzhan, my.channel-1.

    Conservative: no slashes, no spaces, no scheme, must look like a handle
    rather than a random word. Anchor on @ prefix or plausible length.
    """
    if "/" in s or " " in s or "://" in s:
        return False
    return bool(HANDLE_RE.match(s))


def analyze_input(text: str) -> InputAnalysis:
    raw_items = [
        ln.strip() for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    if not raw_items:
        return InputAnalysis("empty", [], "")

    kinds: list[str] = []
    for it in raw_items:
        is_file, is_dir = _is_existing_path(it)
        if is_file or is_dir:
            kinds.append("local")
        elif PLAYLIST_URL_RE.match(it):
            # Order matters: playlist URLs often start with watch?v=..., so check
            # this BEFORE the generic video-URL pattern.
            m = PLAYLIST_URL_RE.match(it)
            if m and m.group(1).startswith("RD"):
                kinds.append("video")  # radio mixes aren't real playlists
            else:
                kinds.append("playlist")
        elif VIDEO_URL_RE.match(it):
            kinds.append("video")
        elif CHANNEL_URL_RE.match(it):
            kinds.append("channel")
        elif _looks_like_handle(it):
            kinds.append("channel")
        else:
            kinds.append("unknown")

    unique = set(kinds)

    if unique == {"local"}:
        # Files must look like media; folders are accepted as-is (transcribe.py
        # recurses through them and picks up every supported extension).
        valid: list[str] = []
        file_count = 0
        dir_count = 0
        for it in raw_items:
            p = Path(it).expanduser()
            if p.is_dir():
                valid.append(str(p))
                dir_count += 1
            elif p.is_file() and p.suffix.lower() in MEDIA_EXTS:
                valid.append(str(p))
                file_count += 1
        if not valid:
            return InputAnalysis(
                "unknown", raw_items,
                "Files don't look like media (try .mp4 / .m4a / .mp3 / .wav…) "
                "or folder is empty.",
            )
        parts = []
        if file_count:
            parts.append(f"{file_count} file{'s' if file_count != 1 else ''}")
        if dir_count:
            parts.append(f"{dir_count} folder{'s' if dir_count != 1 else ''} (will recurse)")
        return InputAnalysis(
            "files", valid,
            f"{' + '.join(parts)} — will transcribe directly",
        )

    if unique == {"video"}:
        return InputAnalysis("urls", raw_items, f"{len(raw_items)} YouTube video URL(s) — will download then transcribe")

    if unique == {"channel"} and len(raw_items) == 1:
        return InputAnalysis("channel", raw_items, "YouTube channel — will parse, download, then transcribe")

    if unique == {"playlist"} and len(raw_items) == 1:
        return InputAnalysis("playlist", raw_items, "YouTube playlist — will parse, download, then transcribe")

    if "unknown" in unique:
        return InputAnalysis("unknown", raw_items, "Some lines aren't recognised. Use a channel handle, video URLs, or local file paths.")

    return InputAnalysis(
        "mixed", raw_items,
        "Don't mix input types — paste either one channel, video URLs, or local files."
    )


# --------------------------------------------------------------------- Widget

class UnifiedTab(QWidget):
    output = Signal(str)
    finished = Signal(int)
    run_state_changed = Signal(bool)
    backend_label_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        cfg = config.load()

        self._pipeline = PipelineRunner(self)
        self._pipeline.output.connect(self.output.emit)
        self._pipeline.step_changed.connect(
            lambda step: self.output.emit(f"[pipeline] step: {step}\n")
        )
        self._pipeline.finished.connect(self._on_pipeline_finished)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        # ─────────────────────────── Input ──────────────────────────────
        input_box = QGroupBox("Input")
        ibox = QVBoxLayout(input_box)

        hint = QLabel(
            "Paste a channel (@name or URL), a playlist URL, one or more "
            "video URLs, or drag & drop audio/video files."
        )
        hint.setStyleSheet("color: #888;")
        hint.setWordWrap(True)
        ibox.addWidget(hint)

        self.input_text = DropTextEdit()
        self.input_text.setPlaceholderText(
            "@channelname\n"
            "https://www.youtube.com/playlist?list=...\n"
            "https://www.youtube.com/watch?v=...\n"
            "/path/to/your/file.mp4\n"
            "(or drop files here)"
        )
        self.input_text.setMinimumHeight(110)
        self.input_text.textChanged.connect(self._on_input_changed)
        ibox.addWidget(self.input_text)

        self.detect_label = QLabel("")
        self.detect_label.setStyleSheet("color: #888; padding: 4px 0;")
        ibox.addWidget(self.detect_label)

        root.addWidget(input_box)

        # ─────────────────────────── Steps ──────────────────────────────
        steps_box = QGroupBox("Steps to run")
        sbox = QHBoxLayout(steps_box)
        self.step_parse = QCheckBox("Parse channel")
        self.step_download = QCheckBox("Download")
        self.step_transcribe = QCheckBox("Transcribe")
        self.step_parse.setChecked(True)
        self.step_download.setChecked(True)
        self.step_transcribe.setChecked(True)
        for cb in (self.step_parse, self.step_download, self.step_transcribe):
            sbox.addWidget(cb)
        sbox.addStretch(1)
        root.addWidget(steps_box)

        # ─────────────────────────── Options ────────────────────────────
        opts_box = QGroupBox("Options")
        obox = QVBoxLayout(opts_box)

        # Save folder
        dest_row = QHBoxLayout()
        dest_row.addWidget(QLabel("Save to:"))
        self.dest_path = QLineEdit(str(Path(cfg["default_output_dir"]).expanduser()))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_dest)
        dest_row.addWidget(self.dest_path, 1)
        dest_row.addWidget(browse)
        obox.addLayout(dest_row)

        # Tabs + limit (channel-only)
        tabs_row = QHBoxLayout()
        self.tabs_label = QLabel("Channel tabs:")
        tabs_row.addWidget(self.tabs_label)
        self.tab_videos = QCheckBox("videos")
        self.tab_shorts = QCheckBox("shorts")
        self.tab_streams = QCheckBox("streams")
        selected = set(cfg.get("default_tabs") or ["videos", "shorts", "streams"])
        self.tab_videos.setChecked("videos" in selected)
        self.tab_shorts.setChecked("shorts" in selected)
        self.tab_streams.setChecked("streams" in selected)
        for w in (self.tab_videos, self.tab_shorts, self.tab_streams):
            tabs_row.addWidget(w)
        tabs_row.addSpacing(16)
        self.limit_label = QLabel("Limit / tab (0 = unlimited):")
        tabs_row.addWidget(self.limit_label)
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(0, 100000)
        self.limit_spin.setValue(cfg.get("default_limit") or 0)
        tabs_row.addWidget(self.limit_spin)
        tabs_row.addStretch(1)
        obox.addLayout(tabs_row)

        # Audio + force re-download
        dl_row = QHBoxLayout()
        self.audio_only = QCheckBox("Audio only (m4a — smaller)")
        self.audio_only.setChecked(bool(cfg.get("default_audio_only", True)))
        self.force_redownload = QCheckBox("Force re-download (ignore archive)")
        dl_row.addWidget(self.audio_only)
        dl_row.addWidget(self.force_redownload)
        dl_row.addStretch(1)
        obox.addLayout(dl_row)

        # Cookies from browser (bypass YouTube anti-bot / age restrictions)
        cookies_row = QHBoxLayout()
        cookies_row.addWidget(QLabel("YouTube cookies from:"))
        self.cookies_combo = QComboBox()
        for label, code in BROWSERS:
            self.cookies_combo.addItem(label, code)
        self._select_browser(cfg.get("cookies_from_browser", "none"))
        self.cookies_combo.currentIndexChanged.connect(
            lambda _: config.set_value("cookies_from_browser", self.cookies_combo.currentData())
        )
        cookies_row.addWidget(self.cookies_combo)
        cookies_hint = QLabel("(set if YouTube asks 'are you human?' or for age-restricted videos)")
        cookies_hint.setStyleSheet("color: #888;")
        cookies_row.addWidget(cookies_hint)
        cookies_row.addStretch(1)
        obox.addLayout(cookies_row)

        # Language + low-power
        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("Language:"))
        self.language_combo = QComboBox()
        for label, code in LANGUAGES:
            self.language_combo.addItem(label, code)
        self._select_language(cfg.get("default_language", "ru"))
        lang_row.addWidget(self.language_combo)
        lang_row.addSpacing(16)
        self.low_power = QCheckBox("Low power (faster-whisper, slower)")
        self.low_power.setChecked(cfg.get("whisper_backend") == "faster-whisper")
        self.low_power.toggled.connect(self._refresh_backend_label)
        lang_row.addWidget(self.low_power)
        lang_row.addStretch(1)
        obox.addLayout(lang_row)

        self.backend_label = QLabel("")
        self.backend_label.setStyleSheet("color: #888;")
        obox.addWidget(self.backend_label)
        self._refresh_backend_label()

        # Delete media after transcribe
        self.delete_after = QCheckBox(
            "Delete media after transcription (keep only .txt — saves disk space)"
        )
        self.delete_after.setChecked(bool(cfg.get("delete_media_after_transcribe", False)))
        obox.addWidget(self.delete_after)

        root.addWidget(opts_box)

        # ─────────────────────────── Run button ─────────────────────────
        self.run_btn = QPushButton("Run")
        self.run_btn.setStyleSheet("padding: 10px 18px; font-weight: 600;")
        self.run_btn.clicked.connect(self._toggle)
        root.addWidget(self.run_btn)

        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._toggle)
        QShortcut(QKeySequence("Meta+Return"), self, activated=self._toggle)

        root.addStretch(1)
        self._on_input_changed()

    # ---------------------------------------------------------- input handling

    def _select_language(self, code: str) -> None:
        for i in range(self.language_combo.count()):
            if self.language_combo.itemData(i) == code:
                self.language_combo.setCurrentIndex(i)
                return
        self.language_combo.setCurrentIndex(0)

    def _select_browser(self, code: str) -> None:
        for i in range(self.cookies_combo.count()):
            if self.cookies_combo.itemData(i) == code:
                self.cookies_combo.setCurrentIndex(i)
                return
        self.cookies_combo.setCurrentIndex(0)

    def _browse_dest(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Save to", self.dest_path.text())
        if path:
            self.dest_path.setText(path)

    def _refresh_backend_label(self) -> None:
        if self.low_power.isChecked():
            name = "faster-whisper"
        else:
            cfg_pref = config.load().get("whisper_backend", "auto")
            pref = cfg_pref if cfg_pref in ("mlx", "faster-whisper") else "auto"
            name = backend.resolve_preference(pref)
        text = f"Backend: {backend.human_label(name)}"
        self.backend_label.setText(text)
        self.backend_label_changed.emit(text)

    def _on_input_changed(self) -> None:
        analysis = analyze_input(self.input_text.toPlainText())
        # Update detection label
        if analysis.kind == "empty":
            self.detect_label.setText("")
            self._set_steps_for("empty")
            return
        if analysis.is_runnable:
            self.detect_label.setText(f"✓ {analysis.message}")
            self.detect_label.setStyleSheet("color: #4ade80; padding: 4px 0;")  # green
        else:
            self.detect_label.setText(f"⚠ {analysis.message}")
            self.detect_label.setStyleSheet("color: #fb923c; padding: 4px 0;")  # orange
        self._set_steps_for(analysis.kind)

    def _set_steps_for(self, kind: str) -> None:
        """Auto-enable / disable the step toggles based on input kind.

        - channel:  all three relevant; channel tabs + limit visible
        - playlist: all three relevant; limit visible (no channel tabs)
        - urls:     parse irrelevant (greyed off), download + transcribe stay
        - files:    parse + download irrelevant, only transcribe
        - empty/unknown: leave checked, but Run will reject
        """
        # Channel-tab checkboxes only apply to channels.
        channel_relevant = kind in ("channel", "empty")
        for w in (self.tabs_label, self.tab_videos, self.tab_shorts, self.tab_streams):
            w.setVisible(channel_relevant)
        # Limit applies to channels AND playlists (yt-dlp's playlistend).
        limit_relevant = kind in ("channel", "playlist", "empty")
        self.limit_label.setVisible(limit_relevant)
        self.limit_spin.setVisible(limit_relevant)

        if kind in ("channel", "playlist"):
            self._enable_step(self.step_parse, True, force_check=True)
            self._enable_step(self.step_download, True)
            self._enable_step(self.step_transcribe, True)
        elif kind == "urls":
            self._enable_step(self.step_parse, False, force_check=False)
            self._enable_step(self.step_download, True, force_check=True)
            self._enable_step(self.step_transcribe, True)
        elif kind == "files":
            self._enable_step(self.step_parse, False, force_check=False)
            self._enable_step(self.step_download, False, force_check=False)
            self._enable_step(self.step_transcribe, True, force_check=True)
        else:  # empty / unknown / mixed
            self._enable_step(self.step_parse, True)
            self._enable_step(self.step_download, True)
            self._enable_step(self.step_transcribe, True)

    @staticmethod
    def _enable_step(cb: QCheckBox, enabled: bool, *, force_check: bool | None = None) -> None:
        cb.setEnabled(enabled)
        if force_check is True and enabled:
            cb.setChecked(True)
        elif force_check is False:
            cb.setChecked(False)

    # ---------------------------------------------------------------- run flow

    def _set_running(self, running: bool) -> None:
        self.run_btn.setText("Cancel" if running else "Run")
        self.run_state_changed.emit(running)

    def _toggle(self) -> None:
        if self._pipeline.is_running():
            self._pipeline.cancel()
            return
        try:
            steps = self._build_steps()
        except ValueError as e:
            self.output.emit(f"[error] {e}\n")
            return
        if not steps:
            self.output.emit("[error] Nothing to do — turn on at least one step.\n")
            return
        self._set_running(True)
        self._pipeline.run(steps)

    def _on_pipeline_finished(self, exit_code: int) -> None:
        self._set_running(False)
        self.finished.emit(exit_code)

    def _build_steps(self) -> list[tuple[str, str, list[str]]]:
        analysis = analyze_input(self.input_text.toPlainText())
        if not analysis.is_runnable:
            raise ValueError(analysis.message or "Enter input first.")

        dest = self.dest_path.text().strip()
        if not dest:
            raise ValueError("Pick a destination folder.")
        dest_path = Path(dest).expanduser()
        dest_path.mkdir(parents=True, exist_ok=True)

        steps: list[tuple[str, str, list[str]]] = []

        # --- Parse step ---
        links_path = dest_path / "links.txt"
        if analysis.kind in ("channel", "playlist") and self.step_parse.isChecked():
            target = analysis.items[0]
            if analysis.kind == "channel" and normalize_channel is not None:
                normalize_channel(target)  # raises ValueError on bad input
            parse_args = [target, "-o", str(links_path)]
            if analysis.kind == "channel":
                tabs = [name for name, cb in (
                    ("videos", self.tab_videos), ("shorts", self.tab_shorts), ("streams", self.tab_streams),
                ) if cb.isChecked()]
                if not tabs:
                    raise ValueError("Select at least one channel tab.")
                parse_args += ["--tabs", ",".join(tabs)]
            limit = self.limit_spin.value()
            if limit > 0:
                parse_args += ["--limit", str(limit)]
            cookies = self.cookies_combo.currentData()
            if cookies and cookies != "none":
                parse_args += ["--cookies-from-browser", cookies]
            steps.append(("parse", str(script_path("parse.py")), parse_args))

        # --- Download step ---
        if self.step_download.isChecked() and analysis.kind in ("channel", "playlist", "urls"):
            download_args = ["-o", str(dest_path)]
            if self.audio_only.isChecked():
                download_args.append("--audio-only")
            if self.force_redownload.isChecked():
                download_args.append("--force")
            cookies = self.cookies_combo.currentData()
            if cookies and cookies != "none":
                download_args += ["--cookies-from-browser", cookies]
            if analysis.kind in ("channel", "playlist"):
                download_args.append(str(links_path))
            else:
                # write URLs to a temp file
                tmp = tempfile.NamedTemporaryFile(
                    "w", prefix="yt-urls-", suffix=".txt",
                    delete=False, encoding="utf-8",
                    dir=str(dest_path),
                )
                tmp.write("\n".join(analysis.items) + "\n")
                tmp.close()
                download_args.append(tmp.name)
            steps.append(("download", str(script_path("download.py")), download_args))

        # --- Transcribe step ---
        if self.step_transcribe.isChecked():
            t_args: list[str] = []
            if analysis.kind == "files":
                t_args = list(analysis.items)
            else:
                t_args = [str(dest_path)]

            lang = self.language_combo.currentData()
            if lang:
                t_args += ["--language", lang]
            if self.low_power.isChecked():
                t_args += ["--backend", "faster-whisper"]
            else:
                cfg_pref = config.load().get("whisper_backend", "auto")
                if cfg_pref in ("mlx", "faster-whisper", "auto"):
                    t_args += ["--backend", cfg_pref]
            cfg = config.load()
            if cfg.get("faster_whisper_model"):
                t_args += ["--model", cfg["faster_whisper_model"]]
            if cfg.get("faster_whisper_compute_type"):
                t_args += ["--compute-type", cfg["faster_whisper_compute_type"]]
            if self.delete_after.isChecked():
                t_args.append("--delete-after")

            steps.append(("transcribe", str(script_path("transcribe.py")), t_args))

        return steps

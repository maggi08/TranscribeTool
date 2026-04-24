"""Pipeline tab — parse → download → transcribe chained in one click."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from .. import config
from ..jobs.pipeline_runner import PipelineRunner
from ..paths import script_path
from .transcribe_tab import LANGUAGES

try:
    from parse import normalize_channel
except ImportError:
    normalize_channel = None


class PipelineTab(QWidget):
    output = Signal(str)
    finished = Signal(int)
    run_state_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        cfg = config.load()
        self._pipeline = PipelineRunner(self)
        self._pipeline.output.connect(self.output.emit)
        self._pipeline.finished.connect(self._on_finished)
        self._pipeline.step_changed.connect(
            lambda step: self.output.emit(f"[pipeline] step: {step}\n")
        )

        root = QVBoxLayout(self)

        root.addWidget(QLabel("Channel:"))
        self.channel_input = QLineEdit()
        self.channel_input.setPlaceholderText("@channelname or channel URL")
        root.addWidget(self.channel_input)

        dest_row = QHBoxLayout()
        dest_row.addWidget(QLabel("Save to folder:"))
        self.dest_path = QLineEdit(str(Path(cfg["default_output_dir"]).expanduser()))
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_dest)
        dest_row.addWidget(self.dest_path, 1)
        dest_row.addWidget(browse)
        root.addLayout(dest_row)

        limit_row = QHBoxLayout()
        limit_row.addWidget(QLabel("Limit per tab (0 = unlimited):"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(0, 100000)
        self.limit_spin.setValue(cfg.get("default_limit") or 0)
        limit_row.addWidget(self.limit_spin)
        limit_row.addStretch(1)
        root.addLayout(limit_row)

        opts = QVBoxLayout()
        tabs_row = QHBoxLayout()
        tabs_row.addWidget(QLabel("Tabs:"))
        self.tab_videos = QCheckBox("videos")
        self.tab_shorts = QCheckBox("shorts")
        self.tab_streams = QCheckBox("streams")
        selected = set(cfg.get("default_tabs") or ["videos", "shorts", "streams"])
        self.tab_videos.setChecked("videos" in selected)
        self.tab_shorts.setChecked("shorts" in selected)
        self.tab_streams.setChecked("streams" in selected)
        for w in (self.tab_videos, self.tab_shorts, self.tab_streams):
            tabs_row.addWidget(w)
        tabs_row.addStretch(1)
        opts.addLayout(tabs_row)

        self.audio_only = QCheckBox("Audio only (m4a)")
        self.audio_only.setChecked(bool(cfg.get("default_audio_only", True)))
        opts.addWidget(self.audio_only)

        self.force_redownload = QCheckBox("Force re-download (ignore archive)")
        self.force_redownload.setChecked(False)
        opts.addWidget(self.force_redownload)

        self.do_transcribe = QCheckBox("Transcribe after download")
        self.do_transcribe.setChecked(bool(cfg.get("transcribe_after_download", True)))
        opts.addWidget(self.do_transcribe)

        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("Language:"))
        self.language_combo = QComboBox()
        for label, code in LANGUAGES:
            self.language_combo.addItem(label, code)
        self._select_language(cfg.get("default_language", "ru"))
        lang_row.addWidget(self.language_combo)
        lang_row.addStretch(1)
        opts.addLayout(lang_row)

        self.low_power = QCheckBox("Low power mode (faster-whisper)")
        self.low_power.setChecked(cfg.get("whisper_backend") == "faster-whisper")
        opts.addWidget(self.low_power)

        root.addLayout(opts)

        self.run_btn = QPushButton("Run pipeline")
        self.run_btn.clicked.connect(self._toggle)
        root.addWidget(self.run_btn)
        root.addStretch(1)

    # ------------------------------------------------------------- helpers

    def _select_language(self, code: str) -> None:
        for i in range(self.language_combo.count()):
            if self.language_combo.itemData(i) == code:
                self.language_combo.setCurrentIndex(i)
                return
        self.language_combo.setCurrentIndex(0)

    def _browse_dest(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Save to", self.dest_path.text())
        if path:
            self.dest_path.setText(path)

    def _set_running(self, running: bool) -> None:
        self.run_btn.setText("Cancel" if running else "Run pipeline")
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
        self._set_running(True)
        self._pipeline.run(steps)

    def _build_steps(self) -> list[tuple[str, str, list[str]]]:
        channel = self.channel_input.text().strip()
        if not channel:
            raise ValueError("Enter a channel handle or URL.")
        if normalize_channel is not None:
            try:
                normalize_channel(channel)
            except ValueError as e:
                raise ValueError(str(e))

        dest = self.dest_path.text().strip()
        if not dest:
            raise ValueError("Pick a destination folder.")
        dest_path = Path(dest).expanduser()
        dest_path.mkdir(parents=True, exist_ok=True)
        links_path = dest_path / "links.txt"

        tabs = [
            name for name, cb in (
                ("videos", self.tab_videos),
                ("shorts", self.tab_shorts),
                ("streams", self.tab_streams),
            ) if cb.isChecked()
        ]
        if not tabs:
            raise ValueError("Select at least one tab.")

        parse_args = [channel, "-o", str(links_path), "--tabs", ",".join(tabs)]
        limit = self.limit_spin.value()
        if limit > 0:
            parse_args += ["--limit", str(limit)]

        download_args = ["-o", str(dest_path), str(links_path)]
        if self.audio_only.isChecked():
            download_args.append("--audio-only")
        if self.force_redownload.isChecked():
            download_args.append("--force")

        steps: list[tuple[str, str, list[str]]] = [
            ("parse", str(script_path("parse.py")), parse_args),
            ("download", str(script_path("download.py")), download_args),
        ]

        if self.do_transcribe.isChecked():
            t_args: list[str] = [str(dest_path)]
            lang = self.language_combo.currentData()
            if lang:
                t_args += ["--language", lang]
            if self.low_power.isChecked():
                t_args += ["--backend", "faster-whisper"]
            else:
                cfg_pref = config.load().get("whisper_backend", "auto")
                if cfg_pref in ("mlx", "faster-whisper", "auto"):
                    t_args += ["--backend", cfg_pref]
            steps.append(("transcribe", str(script_path("transcribe.py")), t_args))

        return steps

    def _on_finished(self, exit_code: int) -> None:
        self._set_running(False)
        self.finished.emit(exit_code)

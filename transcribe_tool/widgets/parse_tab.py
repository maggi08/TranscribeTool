"""Parse tab — channel → links.txt via parse.py."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from .. import config
from ..paths import script_path
from ._runnable import RunnableTab

try:
    from parse import normalize_channel  # direct import for input validation
except ImportError:
    normalize_channel = None


class ParseTab(RunnableTab):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        cfg = config.load()

        root = QVBoxLayout(self)

        root.addWidget(QLabel("Channel (handle, URL, or tab URL):"))
        self.channel_input = QLineEdit()
        self.channel_input.setPlaceholderText("@channelname  or  https://www.youtube.com/@channelname")
        self.channel_input.textChanged.connect(self._validate_channel)
        root.addWidget(self.channel_input)
        self.channel_error = QLabel("")
        self.channel_error.setStyleSheet("color: #c62828;")
        root.addWidget(self.channel_error)

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
        root.addLayout(tabs_row)

        limit_row = QHBoxLayout()
        limit_row.addWidget(QLabel("Limit per tab (0 = unlimited):"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(0, 100000)
        self.limit_spin.setValue(cfg.get("default_limit") or 0)
        limit_row.addWidget(self.limit_spin)
        limit_row.addStretch(1)
        root.addLayout(limit_row)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Output:"))
        default_dir = Path(cfg["default_output_dir"]).expanduser()
        self.output_path = QLineEdit(str(default_dir / "links.txt"))
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_output)
        out_row.addWidget(self.output_path, 1)
        out_row.addWidget(browse)
        root.addLayout(out_row)

        self.run_btn = QPushButton("Run")
        root.addWidget(self.run_btn)
        root.addStretch(1)

        self._wire_run_button(self.run_btn, self._build_args_impl)

    # --------------------------------------------------------------- events

    def _validate_channel(self) -> None:
        text = self.channel_input.text().strip()
        if not text:
            self.channel_error.setText("")
            self.channel_input.setStyleSheet("")
            return
        if normalize_channel is None:
            return
        try:
            normalize_channel(text)
            self.channel_error.setText("")
            self.channel_input.setStyleSheet("")
        except ValueError as e:
            self.channel_error.setText(str(e))
            self.channel_input.setStyleSheet("border: 1px solid #c62828;")

    def _browse_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save links to", self.output_path.text(), "Text files (*.txt)")
        if path:
            self.output_path.setText(path)

    def _build_args_impl(self) -> tuple[str, list[str]]:
        channel = self.channel_input.text().strip()
        if not channel:
            raise ValueError("Enter a channel handle or URL.")
        if normalize_channel is not None:
            try:
                normalize_channel(channel)
            except ValueError as e:
                raise ValueError(str(e))

        tabs = [
            name for name, cb in (
                ("videos", self.tab_videos),
                ("shorts", self.tab_shorts),
                ("streams", self.tab_streams),
            ) if cb.isChecked()
        ]
        if not tabs:
            raise ValueError("Select at least one tab.")

        output = self.output_path.text().strip()
        if not output:
            raise ValueError("Set an output path.")
        Path(output).parent.mkdir(parents=True, exist_ok=True)

        args = [channel, "-o", output, "--tabs", ",".join(tabs)]
        limit = self.limit_spin.value()
        if limit > 0:
            args += ["--limit", str(limit)]
        return str(script_path("parse.py")), args

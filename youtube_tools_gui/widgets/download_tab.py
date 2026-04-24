"""Download tab — URLs (textarea) or .txt file → media files via download.py."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QRadioButton, QVBoxLayout, QWidget,
)

from .. import config
from ..paths import script_path
from ._runnable import RunnableTab


class DownloadTab(RunnableTab):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        cfg = config.load()
        root = QVBoxLayout(self)

        # Source toggle
        src_row = QHBoxLayout()
        self.src_urls = QRadioButton("Paste URLs")
        self.src_file = QRadioButton("Use .txt file")
        self.src_urls.setChecked(True)
        self.src_urls.toggled.connect(self._update_source_visibility)
        src_row.addWidget(self.src_urls)
        src_row.addWidget(self.src_file)
        src_row.addStretch(1)
        root.addLayout(src_row)

        self.urls_edit = QPlainTextEdit()
        self.urls_edit.setPlaceholderText("One YouTube URL per line...")
        root.addWidget(self.urls_edit)

        self.file_row = QWidget()
        frow = QHBoxLayout(self.file_row)
        frow.setContentsMargins(0, 0, 0, 0)
        self.file_path = QLineEdit()
        self.file_path.setPlaceholderText("Path to links.txt")
        self.file_path.textChanged.connect(self._update_file_count_label)
        file_browse = QPushButton("Browse...")
        file_browse.clicked.connect(self._browse_file)
        frow.addWidget(self.file_path, 1)
        frow.addWidget(file_browse)
        root.addWidget(self.file_row)
        self.file_count_label = QLabel("")
        self.file_count_label.setStyleSheet("color: #666;")
        root.addWidget(self.file_count_label)

        # Options
        opts = QHBoxLayout()
        self.audio_only = QCheckBox("Audio only (m4a) — smaller, ideal for transcription")
        self.audio_only.setChecked(bool(cfg.get("default_audio_only", True)))
        opts.addWidget(self.audio_only)
        opts.addStretch(1)
        root.addLayout(opts)

        self.force_redownload = QCheckBox(
            "Force re-download (ignore .yt-dlp-archive.txt — download even if already present)"
        )
        self.force_redownload.setChecked(False)
        root.addWidget(self.force_redownload)

        # Destination
        dest_row = QHBoxLayout()
        dest_row.addWidget(QLabel("Save to:"))
        self.dest_path = QLineEdit(str(Path(cfg["default_output_dir"]).expanduser()))
        browse_dest = QPushButton("Browse...")
        browse_dest.clicked.connect(self._browse_dest)
        dest_row.addWidget(self.dest_path, 1)
        dest_row.addWidget(browse_dest)
        root.addLayout(dest_row)

        self.run_btn = QPushButton("Run")
        root.addWidget(self.run_btn)
        root.addStretch(1)

        self._wire_run_button(self.run_btn, self._build_args_impl)
        self._update_source_visibility()

    # ------------------------------------------------------------ helpers

    def _update_source_visibility(self) -> None:
        use_file = self.src_file.isChecked()
        self.file_row.setVisible(use_file)
        self.file_count_label.setVisible(use_file)
        self.urls_edit.setVisible(not use_file)

    def _browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Pick a links.txt file", "", "Text files (*.txt);;All files (*)")
        if path:
            self.file_path.setText(path)

    def _browse_dest(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Save downloads to", self.dest_path.text())
        if path:
            self.dest_path.setText(path)

    def _update_file_count_label(self) -> None:
        p = Path(self.file_path.text().strip() or "")
        if p.is_file():
            try:
                lines = [ln for ln in p.read_text(encoding="utf-8").splitlines()
                         if ln.strip() and not ln.strip().startswith("#")]
                self.file_count_label.setText(f"{len(lines)} URL(s) loaded")
            except Exception as e:
                self.file_count_label.setText(f"(could not read: {e})")
        else:
            self.file_count_label.setText("")

    def _build_args_impl(self) -> tuple[str, list[str]]:
        dest = self.dest_path.text().strip()
        if not dest:
            raise ValueError("Pick a destination folder.")
        Path(dest).mkdir(parents=True, exist_ok=True)

        args: list[str] = ["-o", dest]
        if self.audio_only.isChecked():
            args.append("--audio-only")
        if self.force_redownload.isChecked():
            args.append("--force")

        if self.src_file.isChecked():
            file_path = self.file_path.text().strip()
            if not file_path or not Path(file_path).is_file():
                raise ValueError("Pick a valid .txt file with URLs.")
            args.append(file_path)
        else:
            raw = self.urls_edit.toPlainText().strip()
            urls = [ln.strip() for ln in raw.splitlines()
                    if ln.strip() and not ln.strip().startswith("#")]
            if not urls:
                raise ValueError("Paste at least one URL.")
            # Write to a tempfile so we don't have a giant argv on huge lists.
            tmp = tempfile.NamedTemporaryFile(
                "w", prefix="yt-urls-", suffix=".txt", delete=False, encoding="utf-8"
            )
            tmp.write("\n".join(urls) + "\n")
            tmp.close()
            args.append(tmp.name)

        return str(script_path("download.py")), args

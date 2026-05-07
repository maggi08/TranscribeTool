"""Transcribe tab — folder/file → .txt transcripts via transcribe.py."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from .. import backend, config
from ..paths import script_path
from ._runnable import RunnableTab


LANGUAGES = [
    ("Auto-detect", ""),
    ("Russian", "ru"),
    ("English", "en"),
    ("Kazakh", "kk"),
    ("Spanish", "es"),
    ("French", "fr"),
    ("German", "de"),
    ("Ukrainian", "uk"),
    ("Turkish", "tr"),
]


class TranscribeTab(RunnableTab):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        cfg = config.load()
        root = QVBoxLayout(self)

        # Input picker
        in_row = QHBoxLayout()
        in_row.addWidget(QLabel("File or folder:"))
        self.input_path = QLineEdit(str(Path(cfg["default_output_dir"]).expanduser()))
        pick_folder = QPushButton("Folder...")
        pick_file = QPushButton("File...")
        pick_folder.clicked.connect(self._pick_folder)
        pick_file.clicked.connect(self._pick_file)
        in_row.addWidget(self.input_path, 1)
        in_row.addWidget(pick_folder)
        in_row.addWidget(pick_file)
        root.addLayout(in_row)

        # Language
        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("Language:"))
        self.language_combo = QComboBox()
        for label, code in LANGUAGES:
            self.language_combo.addItem(label, code)
        self._select_language(cfg.get("default_language", "ru"))
        lang_row.addWidget(self.language_combo)
        lang_row.addStretch(1)
        root.addLayout(lang_row)

        # Low power mode
        self.low_power = QCheckBox("Low power mode (use faster-whisper)")
        self.low_power.setChecked(cfg.get("whisper_backend") == "faster-whisper")
        self.low_power.toggled.connect(self._refresh_backend_label)
        root.addWidget(self.low_power)

        self.backend_label = QLabel("")
        self.backend_label.setStyleSheet("color: #666;")
        root.addWidget(self.backend_label)
        self._refresh_backend_label()

        self.run_btn = QPushButton("Run")
        root.addWidget(self.run_btn)
        root.addStretch(1)

        self._wire_run_button(self.run_btn, self._build_args_impl)

    # ------------------------------------------------------------ helpers

    def _select_language(self, code: str) -> None:
        for i in range(self.language_combo.count()):
            if self.language_combo.itemData(i) == code:
                self.language_combo.setCurrentIndex(i)
                return
        self.language_combo.setCurrentIndex(0)

    def _pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Pick a folder", self.input_path.text())
        if path:
            self.input_path.setText(path)

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Pick an audio/video file", self.input_path.text())
        if path:
            self.input_path.setText(path)

    def _refresh_backend_label(self) -> None:
        if self.low_power.isChecked():
            name = "faster-whisper"
        else:
            cfg_pref = config.load().get("whisper_backend", "auto")
            pref = cfg_pref if cfg_pref in ("mlx", "faster-whisper") else "auto"
            name = backend.resolve_preference(pref)
        self.backend_label.setText(f"Using {backend.human_label(name)}")

    def _build_args_impl(self) -> tuple[str, list[str]]:
        target = self.input_path.text().strip()
        if not target or not Path(target).exists():
            raise ValueError("Pick an existing file or folder.")

        args: list[str] = [target]
        lang = self.language_combo.currentData()
        if lang:
            args += ["--language", lang]

        if self.low_power.isChecked():
            args += ["--backend", "faster-whisper"]
        else:
            cfg_pref = config.load().get("whisper_backend", "auto")
            if cfg_pref in ("mlx", "faster-whisper", "auto"):
                args += ["--backend", cfg_pref]

        cfg = config.load()
        if cfg.get("faster_whisper_model"):
            args += ["--model", cfg["faster_whisper_model"]]
        if cfg.get("faster_whisper_compute_type"):
            args += ["--compute-type", cfg["faster_whisper_compute_type"]]

        return str(script_path("transcribe.py")), args

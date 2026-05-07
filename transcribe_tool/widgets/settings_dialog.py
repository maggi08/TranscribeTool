"""Preferences dialog — edits config.json through config.save()."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWidget,
)

from .. import backend, config
from .transcribe_tab import LANGUAGES


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(500)
        cfg = config.load()

        root = QVBoxLayout(self)

        # General
        general = QGroupBox("Defaults")
        form = QFormLayout(general)

        out_row = QHBoxLayout()
        self.default_output = QLineEdit(str(Path(cfg["default_output_dir"]).expanduser()))
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_output)
        out_row.addWidget(self.default_output, 1)
        out_row.addWidget(browse)
        out_wrapper = QWidget()
        out_wrapper.setLayout(out_row)
        form.addRow("Default save folder:", out_wrapper)

        self.language_combo = QComboBox()
        for label, code in LANGUAGES:
            self.language_combo.addItem(label, code)
        self._select_language(cfg.get("default_language", "ru"))
        form.addRow("Default language:", self.language_combo)

        self.audio_only = QCheckBox("Audio only by default")
        self.audio_only.setChecked(bool(cfg.get("default_audio_only", True)))
        form.addRow("", self.audio_only)

        self.transcribe_after = QCheckBox("Transcribe after download (pipeline default)")
        self.transcribe_after.setChecked(bool(cfg.get("transcribe_after_download", True)))
        form.addRow("", self.transcribe_after)

        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(0, 100000)
        self.limit_spin.setValue(cfg.get("default_limit") or 0)
        form.addRow("Default limit per tab (0 = unlimited):", self.limit_spin)

        root.addWidget(general)

        # Performance
        perf = QGroupBox("Performance")
        perf_layout = QVBoxLayout(perf)

        self.radio_fast = QRadioButton("Fast (auto — uses mlx-whisper on Apple Silicon, faster-whisper elsewhere)")
        self.radio_low = QRadioButton("Low power (always faster-whisper; slower but lighter on the GPU / battery)")
        group = QButtonGroup(self)
        group.addButton(self.radio_fast)
        group.addButton(self.radio_low)
        current = cfg.get("whisper_backend", "auto")
        self.radio_low.setChecked(current == "faster-whisper")
        self.radio_fast.setChecked(current != "faster-whisper")
        perf_layout.addWidget(self.radio_fast)
        perf_layout.addWidget(self.radio_low)

        availability_note = QLabel(self._availability_note())
        availability_note.setStyleSheet("color: #666;")
        availability_note.setWordWrap(True)
        perf_layout.addWidget(availability_note)

        root.addWidget(perf)

        # faster-whisper detail
        fw = QGroupBox("faster-whisper model")
        fw_form = QFormLayout(fw)
        self.fw_model = QLineEdit(cfg.get("faster_whisper_model") or "large-v3")
        fw_form.addRow("Model:", self.fw_model)
        self.fw_compute = QLineEdit(cfg.get("faster_whisper_compute_type") or "int8")
        fw_form.addRow("Compute type:", self.fw_compute)
        root.addWidget(fw)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ------------------------------------------------------------- helpers

    def _availability_note(self) -> str:
        has_mlx = backend.mlx_available()
        has_fw = backend.faster_whisper_available()
        bits = []
        bits.append(f"mlx-whisper: {'available' if has_mlx else 'not available on this machine'}")
        bits.append(f"faster-whisper: {'available' if has_fw else 'not installed'}")
        return "  ·  ".join(bits)

    def _select_language(self, code: str) -> None:
        for i in range(self.language_combo.count()):
            if self.language_combo.itemData(i) == code:
                self.language_combo.setCurrentIndex(i)
                return
        self.language_combo.setCurrentIndex(0)

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Default save folder", self.default_output.text())
        if path:
            self.default_output.setText(path)

    def _save(self) -> None:
        cfg = config.load()
        cfg["default_output_dir"] = self.default_output.text().strip()
        cfg["default_language"] = self.language_combo.currentData() or ""
        cfg["default_audio_only"] = self.audio_only.isChecked()
        cfg["transcribe_after_download"] = self.transcribe_after.isChecked()
        cfg["default_limit"] = self.limit_spin.value() or None
        cfg["whisper_backend"] = "faster-whisper" if self.radio_low.isChecked() else "auto"
        cfg["faster_whisper_model"] = self.fw_model.text().strip() or "large-v3"
        cfg["faster_whisper_compute_type"] = self.fw_compute.text().strip() or "int8"
        config.save(cfg)
        self.accept()

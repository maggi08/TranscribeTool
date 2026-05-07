"""Shared log pane: monospace text view with autoscroll pin + clear/copy."""
from __future__ import annotations

from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)


class LogPane(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.text = QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(10000)  # keep memory bounded
        font = QFont("Menlo, Consolas, monospace")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(11)
        self.text.setFont(font)
        layout.addWidget(self.text, 1)

        buttons = QHBoxLayout()
        self.clear_btn = QPushButton("Clear")
        self.copy_btn = QPushButton("Copy all")
        self.clear_btn.clicked.connect(self.text.clear)
        self.copy_btn.clicked.connect(self._copy_all)
        buttons.addWidget(self.clear_btn)
        buttons.addWidget(self.copy_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def append(self, chunk: str) -> None:
        """Append text, pin-to-bottom only if already scrolled to bottom."""
        scrollbar = self.text.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 2

        cursor = self.text.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(chunk)

        if at_bottom:
            scrollbar.setValue(scrollbar.maximum())

    def _copy_all(self) -> None:
        self.text.selectAll()
        self.text.copy()
        cursor = self.text.textCursor()
        cursor.clearSelection()
        self.text.setTextCursor(cursor)

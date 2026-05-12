"""QPlainTextEdit subclass that accepts file drag-and-drop.

Drops file paths (one per line) onto the existing text. URL/text drops
fall back to the default behaviour.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QPlainTextEdit


class DropTextEdit(QPlainTextEdit):
    files_dropped = Signal(list)  # list[str] of absolute paths

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasText():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        mime = event.mimeData()
        if mime.hasUrls():
            paths: list[str] = []
            for url in mime.urls():
                if url.isLocalFile():
                    paths.append(url.toLocalFile())
                else:
                    paths.append(url.toString())
            if paths:
                self._append_lines(paths)
                self.files_dropped.emit(paths)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    def _append_lines(self, lines: list[str]) -> None:
        existing = self.toPlainText().rstrip()
        prefix = (existing + "\n") if existing else ""
        self.setPlainText(prefix + "\n".join(lines))
        # Move cursor to end
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.setTextCursor(cursor)

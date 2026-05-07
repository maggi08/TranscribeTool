"""Tiny mixin for tabs that own a JobRunner with a Run/Cancel button."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPushButton, QWidget

from ..jobs.job_runner import JobRunner


class RunnableTab(QWidget):
    """Base class that exposes a JobRunner + Run/Cancel button wiring.

    Subclasses call self._wire_run_button(button, build_args) and forward
    self.output / self.finished to the shared log pane.
    """
    output = Signal(str)
    finished = Signal(int)
    run_state_changed = Signal(bool)  # True when running

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._runner = JobRunner(self)
        self._runner.output.connect(self.output.emit)
        self._runner.finished.connect(self._on_finished)
        self._run_btn: QPushButton | None = None
        self._build_args: Callable[[], tuple[str, list[str]]] | None = None

    def _wire_run_button(self, btn: QPushButton,
                         build: Callable[[], tuple[str, list[str]]]) -> None:
        """Bind a button to toggle Run/Cancel.

        `build` returns (script, args). Raise ValueError with a user-friendly
        message to block the run.
        """
        self._run_btn = btn
        self._build_args = build
        btn.clicked.connect(self._toggle)

    def _toggle(self) -> None:
        if self._runner.is_running():
            self._runner.cancel()
            return
        try:
            script, args = self._build_args()
        except ValueError as e:
            self.output.emit(f"[error] {e}\n")
            return
        self._set_running(True)
        self._runner.start(script, args)

    def _on_finished(self, exit_code: int) -> None:
        self._set_running(False)
        self.finished.emit(exit_code)

    def _set_running(self, running: bool) -> None:
        if self._run_btn is not None:
            self._run_btn.setText("Cancel" if running else "Run")
        self.run_state_changed.emit(running)

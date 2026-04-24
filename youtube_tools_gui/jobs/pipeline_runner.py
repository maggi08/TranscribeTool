"""Chain parse → download → transcribe runs, re-emitting signals."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from .job_runner import JobRunner


class PipelineRunner(QObject):
    output = Signal(str)
    started = Signal()
    step_changed = Signal(str)  # "parse" | "download" | "transcribe"
    finished = Signal(int)      # 0 on full success, else exit code of failing step

    # Steps that should continue the pipeline even if their exit code is non-zero.
    # Download partial failures shouldn't stop us from transcribing what did land.
    _CONTINUE_ON_ERROR = {"download"}

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._runner = JobRunner(self)
        self._runner.output.connect(self.output.emit)
        self._runner.finished.connect(self._on_step_finished)
        self._steps: list[tuple[str, str, list[str]]] = []  # (label, script, args)
        self._current_label: str | None = None
        self._last_nonzero: int = 0
        self._cancelled = False

    def is_running(self) -> bool:
        return self._runner.is_running() or bool(self._steps)

    def run(self, steps: list[tuple[str, str, list[str]]]) -> None:
        if self.is_running():
            return
        self._steps = list(steps)
        self._cancelled = False
        self._last_nonzero = 0
        self.started.emit()
        self._run_next()

    def cancel(self) -> None:
        self._cancelled = True
        self._steps.clear()
        self._runner.cancel()

    def _run_next(self) -> None:
        if not self._steps:
            self.finished.emit(self._last_nonzero)
            return
        label, script, args = self._steps.pop(0)
        self._current_label = label
        self.step_changed.emit(label)
        self.output.emit(f"\n=== [pipeline] step: {label} ===\n")
        self._runner.start(script, args)

    def _on_step_finished(self, exit_code: int) -> None:
        if self._cancelled:
            self._cancelled = False
            self.finished.emit(-1)
            return
        if exit_code != 0:
            self._last_nonzero = exit_code
            if self._current_label not in self._CONTINUE_ON_ERROR:
                self._steps.clear()
                self.finished.emit(exit_code)
                return
            self.output.emit(
                f"[pipeline] '{self._current_label}' exited {exit_code} — "
                "continuing anyway (transcribe will process whatever did land)\n"
            )
        self._run_next()

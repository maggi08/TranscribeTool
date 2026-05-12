"""QProcess wrapper that streams subprocess output to Qt signals."""
from __future__ import annotations

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from .. import paths


class JobRunner(QObject):
    """Runs one Python script as a subprocess, streaming merged stdout+stderr."""

    output = Signal(str)        # chunk of text (may contain multiple lines)
    started = Signal()
    finished = Signal(int)      # exit code (negative on crash)

    TERMINATE_GRACE_MS = 3000

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.timeout.connect(self._force_kill)

    # ------------------------------------------------------------------ API

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.state() != QProcess.NotRunning

    def start(self, script: str, args: list[str]) -> None:
        if self.is_running():
            self.output.emit("[runner] job already running — ignoring start\n")
            return

        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(self._on_stdout)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)

        env = QProcessEnvironment()
        for k, v in paths.environ_with_bundled_bins().items():
            env.insert(k, v)
        proc.setProcessEnvironment(env)
        proc.setWorkingDirectory(str(paths.project_root()))

        program, full_args = paths.cli_command(script, args)
        self._proc = proc
        self.started.emit()
        self.output.emit(f"$ {program} {' '.join(full_args)}\n")
        proc.start(program, full_args)

    def cancel(self) -> None:
        if not self.is_running():
            return
        self.output.emit("\n[runner] cancelling...\n")
        self._proc.terminate()
        self._kill_timer.start(self.TERMINATE_GRACE_MS)

    # -------------------------------------------------------------- Signals

    def _on_stdout(self) -> None:
        if not self._proc:
            return
        data = bytes(self._proc.readAllStandardOutput())
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            text = repr(data)
        # Normalise \r → \n so yt-dlp's in-place progress updates render as
        # successive lines rather than disappearing into a terminal CR.
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        self.output.emit(text)

    def _on_finished(self, exit_code: int, _status) -> None:
        self._kill_timer.stop()
        # Drain any remaining output
        self._on_stdout()
        self.output.emit(f"\n[runner] finished with exit code {exit_code}\n")
        self._proc = None
        self.finished.emit(exit_code)

    def _on_error(self, err) -> None:
        self.output.emit(f"[runner] process error: {err}\n")

    def _force_kill(self) -> None:
        if self.is_running():
            self.output.emit("[runner] terminate timed out — killing\n")
            self._proc.kill()

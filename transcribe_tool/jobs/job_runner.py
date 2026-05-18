"""In-process job runner.

Runs parse.py / download.py / transcribe.py inside the GUI's own process via
runpy. Stdout/stderr is captured and emitted as Qt signals. This avoids the
macOS dual-instance problem caused by spawning the bundled .app binary as a
subprocess (LaunchServices adds a second Dock icon for every subprocess).

Tradeoffs vs. subprocess:
+ no second Dock icon / second app launch on macOS
+ no PyInstaller bootloader overhead per job
+ no need for a bundled standalone Python
- a hard crash in yt-dlp / faster-whisper crashes the GUI too (rare, but possible)
- cancellation is cooperative — the worker thread reaches a checkpoint when
  it next prints (close enough for our use case)
"""
from __future__ import annotations

import os
import runpy
import sys
import threading
import traceback
from contextlib import redirect_stderr, redirect_stdout

from PySide6.QtCore import QObject, QThread, Signal

from .. import paths


class _CancelledByUser(BaseException):
    """Raised inside the worker thread on cancel — bypasses normal except blocks."""


class _SignalWriter:
    """File-like object: emits Qt signal on write, raises on cancellation."""

    def __init__(self, signal: Signal, cancel_event: threading.Event):
        self._signal = signal
        self._cancel_event = cancel_event
        self._buffer = ""

    def write(self, s: str) -> int:
        if self._cancel_event.is_set():
            raise _CancelledByUser
        if not isinstance(s, str):
            s = str(s)
        # Normalise \r → \n so yt-dlp's in-place progress lines render
        # one-per-line in the log pane.
        s = s.replace("\r\n", "\n").replace("\r", "\n")
        if s:
            self._signal.emit(s)
        return len(s)

    def writelines(self, lines) -> None:
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


class _ScriptThread(QThread):
    """Worker thread: runs a script as __main__ with redirected stdio."""

    output = Signal(str)
    finished_with_code = Signal(int)

    def __init__(self, script: str, args: list[str], cancel_event: threading.Event):
        super().__init__()
        self.script = script
        self.script_args = args
        self.cancel_event = cancel_event

    def run(self) -> None:
        writer = _SignalWriter(self.output, self.cancel_event)
        saved_argv = sys.argv[:]
        saved_cwd = os.getcwd()
        code = 0
        try:
            sys.argv = [self.script, *self.script_args]
            try:
                os.chdir(str(paths.project_root()))
            except OSError:
                pass

            with redirect_stdout(writer), redirect_stderr(writer):
                try:
                    runpy.run_path(self.script, run_name="__main__")
                except SystemExit as e:
                    if isinstance(e.code, int):
                        code = e.code
                    elif e.code is None:
                        code = 0
                    else:
                        writer.write(str(e.code) + "\n")
                        code = 1
                except _CancelledByUser:
                    code = -1
                    self.output.emit("\n[runner] cancelled by user\n")
                except BaseException:
                    code = 1
                    try:
                        writer.write(traceback.format_exc())
                    except _CancelledByUser:
                        pass
        finally:
            sys.argv = saved_argv
            try:
                os.chdir(saved_cwd)
            except OSError:
                pass
            self.finished_with_code.emit(code)


class JobRunner(QObject):
    """Public API kept compatible with the old subprocess-based runner."""

    output = Signal(str)
    started = Signal()
    finished = Signal(int)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._thread: _ScriptThread | None = None
        self._cancel_event: threading.Event | None = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(self, script: str, args: list[str]) -> None:
        if self.is_running():
            self.output.emit("[runner] job already running — ignoring start\n")
            return

        # Make sure PATH includes our bundled ffmpeg for the in-process script run too
        for k, v in paths.environ_with_bundled_bins().items():
            os.environ[k] = v

        self._cancel_event = threading.Event()
        thread = _ScriptThread(script, args, self._cancel_event)
        thread.output.connect(self.output.emit)
        thread.finished_with_code.connect(self._on_finished)
        self._thread = thread

        self.started.emit()
        self.output.emit(f"$ (in-process) {script} {' '.join(args)}\n")
        thread.start()

    def cancel(self) -> None:
        if not self.is_running():
            return
        self.output.emit("\n[runner] cancelling... (will stop at the next print boundary)\n")
        if self._cancel_event is not None:
            self._cancel_event.set()

    def _on_finished(self, exit_code: int) -> None:
        self.output.emit(f"\n[runner] finished with exit code {exit_code}\n")
        thread = self._thread
        self._thread = None
        self._cancel_event = None
        if thread is not None:
            thread.wait(2000)
            thread.deleteLater()
        self.finished.emit(exit_code)

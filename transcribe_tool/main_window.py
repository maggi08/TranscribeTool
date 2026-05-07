"""QMainWindow: tabs + shared log pane + Preferences menu."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QTabWidget, QWidget,
)

from . import config
from .widgets.download_tab import DownloadTab
from .widgets.log_pane import LogPane
from .widgets.parse_tab import ParseTab
from .widgets.pipeline_tab import PipelineTab
from .widgets.settings_dialog import SettingsDialog
from .widgets.transcribe_tab import TranscribeTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TranscribeTool")
        self.resize(1000, 720)

        self.log = LogPane(self)

        self.parse_tab = ParseTab(self)
        self.download_tab = DownloadTab(self)
        self.transcribe_tab = TranscribeTab(self)
        self.pipeline_tab = PipelineTab(self)

        for tab in (self.parse_tab, self.download_tab, self.transcribe_tab, self.pipeline_tab):
            tab.output.connect(self.log.append)
            tab.finished.connect(lambda code: self.statusBar().showMessage(
                f"Last run finished (exit {code})", 5000
            ))
            tab.run_state_changed.connect(self._on_run_state)

        tabs = QTabWidget(self)
        tabs.addTab(self.parse_tab, "Parse channel")
        tabs.addTab(self.download_tab, "Download")
        tabs.addTab(self.transcribe_tab, "Transcribe")
        tabs.addTab(self.pipeline_tab, "Pipeline")

        splitter = QSplitter(Qt.Vertical, self)
        splitter.addWidget(tabs)
        splitter.addWidget(self.log)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.setCentralWidget(splitter)

        self._build_menu()
        self._restore_geometry()
        self.statusBar().showMessage("Ready")

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        prefs = QAction("Preferences...", self)
        prefs.setShortcut(QKeySequence("Ctrl+,"))
        prefs.triggered.connect(self._open_settings)
        file_menu.addAction(prefs)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self)
        if dlg.exec():
            # Rebuild tabs so their defaults pick up the new config. Simplest
            # approach: re-show a "reload needed" hint rather than rewiring.
            self.statusBar().showMessage(
                "Settings saved. Restart or re-open a tab to apply new defaults.", 6000
            )
            # Refresh the live backend indicator on the Transcribe tab:
            self.transcribe_tab._refresh_backend_label()

    def _on_run_state(self, running: bool) -> None:
        msg = "Running..." if running else "Ready"
        self.statusBar().showMessage(msg)

    # --------------------------------------------------------- geometry

    def _restore_geometry(self) -> None:
        geom = config.get("window_geometry")
        if geom:
            try:
                self.restoreGeometry(QByteArray.fromHex(geom.encode("ascii")))
            except Exception:
                pass

    def closeEvent(self, event) -> None:
        try:
            geom_hex = bytes(self.saveGeometry().toHex()).decode("ascii")
            config.set_value("window_geometry", geom_hex)
        except Exception:
            pass
        super().closeEvent(event)

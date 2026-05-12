"""QMainWindow: unified input pane + shared log pane + Preferences menu."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMainWindow, QSplitter

from . import config
from .widgets.log_pane import LogPane
from .widgets.settings_dialog import SettingsDialog
from .widgets.unified_tab import UnifiedTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TranscribeTool")
        self.resize(960, 780)

        self.log = LogPane(self)
        self.unified = UnifiedTab(self)
        self.unified.output.connect(self.log.append)
        self.unified.finished.connect(
            lambda code: self.statusBar().showMessage(
                f"Last run finished (exit {code})", 5000
            )
        )
        self.unified.run_state_changed.connect(self._on_run_state)
        self.unified.backend_label_changed.connect(
            lambda text: self.statusBar().showMessage(text, 4000)
        )

        splitter = QSplitter(Qt.Vertical, self)
        splitter.addWidget(self.unified)
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
            self.statusBar().showMessage(
                "Settings saved. Restart to apply new defaults.", 6000
            )
            self.unified._refresh_backend_label()

    def _on_run_state(self, running: bool) -> None:
        self.statusBar().showMessage("Running..." if running else "Ready")

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
        # Explicit: when the user closes the window, fully quit the app
        # instead of leaving the dock icon active (default macOS Qt behaviour).
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.quit()

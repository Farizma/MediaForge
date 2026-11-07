from __future__ import annotations


from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QMessageBox, QPlainTextEdit, QSplitter, QTabWidget,
)

from .. import __version__
from ..core import binaries, updater
from ..core.jobs import JobManager
from ..core.presets import PresetStore
from ..core.settings import Settings
from ..core.update_service import UpdateService
from .ffmpeg_tab import FFmpegTab
from .join_tab import JoinTab
from .queue_panel import QueuePanel
from .settings_dialog import SettingsDialog
from .updates_dialog import UpdatesDialog
from .ytdlp_tab import YtDlpTab


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.setWindowTitle("MediaForge")
        self.resize(1200, 820)
        self.settings = settings
        data_dir = updater.default_data_dir()        # presets, queue, log, downloaded ffmpeg / yt-dlp
        self.data_dir = data_dir
        binaries.set_managed_dir(data_dir)
        self.updates = UpdateService(settings, data_dir)
        self.updates.installed.connect(self._on_tool_installed)
        self.updates.progress.connect(self._on_update_progress)
        self.updates.checked.connect(self._on_updates_checked)
        self.presets = PresetStore(data_dir / "presets.json")
        self.manager = JobManager(settings.max_parallel, settings.max_retries)
        self.manager.attach_store(data_dir / "queue.json")

        self.ffmpeg_tab = FFmpegTab(settings, self.manager, self.presets)
        self.ffmpeg_tab.status_message.connect(lambda m: self.statusBar().showMessage(m, 6000))

        self.join_tab = JoinTab(settings, self.manager)
        self.join_tab.status_message.connect(lambda m: self.statusBar().showMessage(m, 6000))

        self.ytdlp_tab = YtDlpTab(settings, self.manager, self.presets, self.updates)
        self.ytdlp_tab.status_message.connect(lambda m: self.statusBar().showMessage(m, 6000))

        self.tabs = QTabWidget()
        self.tabs.addTab(self.ffmpeg_tab, "FFmpeg")
        self.tabs.addTab(self.join_tab, "Join")
        self.tabs.addTab(self.ytdlp_tab, "yt-dlp")

        self.queue = QueuePanel(self.manager)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setStyleSheet("font-family: Menlo, Consolas, monospace; font-size: 11px;")
        self.manager.log.connect(self.log_view.appendPlainText)

        bottom = QTabWidget()
        bottom.addTab(self.queue, "Queue")
        bottom.addTab(self.log_view, "Log")
        self.bottom = bottom

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.tabs)
        split.addWidget(bottom)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)

        self._build_menu()
        for tab in (self.ffmpeg_tab, self.join_tab, self.ytdlp_tab):
            tab.jobs_added.connect(lambda: self.bottom.setCurrentWidget(self.queue))
        QTimer.singleShot(0, self._startup_check)
        QTimer.singleShot(0, self._restore_queue)
        QTimer.singleShot(2500, self.updates.startup_check)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        settings = QAction("&Settings...", self)
        settings.setShortcut(QKeySequence("Ctrl+,"))
        settings.triggered.connect(self.open_settings)
        quit_ = QAction("&Quit", self)
        quit_.setShortcut(QKeySequence.StandardKey.Quit)
        quit_.triggered.connect(self.close)
        file_menu.addAction(settings)
        file_menu.addSeparator()
        file_menu.addAction(quit_)

        help_menu = self.menuBar().addMenu("&Help")
        upd = QAction("Check for &updates...", self)
        upd.triggered.connect(self.open_updates)
        help_menu.addAction(upd)
        about = QAction("&About", self)
        about.triggered.connect(lambda: QMessageBox.about(
            self, "About MediaForge",
            f"MediaForge {__version__}\nA GUI for ffmpeg and yt-dlp.\nBuilt with PySide6."))
        data = QAction("Open &data folder", self)   # presets, saved queue, log file
        data.triggered.connect(self._open_data_folder)
        help_menu.addAction(data)
        help_menu.addAction(about)

    def open_updates(self) -> None:
        UpdatesDialog(self.updates, self.settings, self).exec()

    # -- update service signals (these must stay methods so they run on the UI thread)
    def _on_updates_checked(self, status: dict) -> None:
        due = [f"{st.name} {st.latest}" for st in status.values() if st.update_available and not st.error]
        if due:
            hint = "installing..." if self.settings.auto_install_updates else "see Help > Check for updates"
            self.statusBar().showMessage("Updates available: " + ", ".join(due) + f"  ({hint})", 15000)

    def _on_update_progress(self, key: str, done: int, total: int) -> None:
        name = "ffmpeg" if key == "ffmpeg" else "yt-dlp"
        pct = f" {done * 100 // total}%" if total else ""
        self.statusBar().showMessage(f"Downloading {name}{pct}")
        self.ytdlp_tab.on_update_progress(key, done, total)

    def _on_tool_installed(self, key: str, ok: bool, message: str) -> None:
        self.statusBar().showMessage(message, 15000)
        self.manager.log.emit(message)
        if ok and key == "ffmpeg":
            self.ffmpeg_tab.refresh_binaries()
            self.join_tab.refresh_binaries()
            self.ytdlp_tab.refresh_binaries()
        self.ytdlp_tab.on_tool_installed(key, ok, message)

    def _open_data_folder(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.data_dir)))

    def open_settings(self) -> None:
        if SettingsDialog(self.settings, self).exec():
            self.manager.set_max_parallel(self.settings.max_parallel)
            self.manager.max_retries = self.settings.max_retries
            self.ffmpeg_tab.refresh_binaries()
            self.join_tab.refresh_binaries()
            self.ytdlp_tab.refresh_binaries()
            self._update_status()

    def _update_status(self) -> None:
        ff = binaries.find("ffmpeg", self.settings.ffmpeg_path)
        self.statusBar().showMessage(binaries.version(ff) if ff else "ffmpeg not found - see File > Settings")

    def _startup_check(self) -> None:
        if binaries.find("ffmpeg", self.settings.ffmpeg_path):
            self._update_status()
            return
        can_download = updater.ffmpeg_install_supported()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("ffmpeg not found")
        box.setText("MediaForge couldn't find ffmpeg on your system.")
        if can_download:
            box.setInformativeText("ffmpeg does the actual converting. MediaForge can download it for you now "
                                   "(about 100 MB, from gyan.dev).")
            get_btn = box.addButton("Download ffmpeg", QMessageBox.ButtonRole.AcceptRole)
        else:
            box.setInformativeText("Install ffmpeg with your package manager (for example 'brew install ffmpeg' "
                                   "or 'sudo apt install ffmpeg'), or point to it in Settings.")
            get_btn = None
        settings_btn = box.addButton("Open Settings", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if get_btn is not None and clicked is get_btn:
            self.statusBar().showMessage("Downloading ffmpeg...")
            self.updates.install("ffmpeg")
        elif clicked is settings_btn:
            self.open_settings()
        self._update_status()

    def _restore_queue(self) -> None:
        n = self.manager.restore(lambda: binaries.find("ffmpeg", self.settings.ffmpeg_path))
        if n:
            self.bottom.setCurrentWidget(self.queue)
            self.statusBar().showMessage(
                f"Restored {n} job(s) from your last session - select one and press Resume "
                f"(or 'Resume all').", 12000)

    def closeEvent(self, event) -> None:
        keep = True
        if self.manager.active_count():
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle("Jobs still running")
            box.setText("There are running or waiting jobs.")
            box.setInformativeText(
                "Quit and keep them: they come back paused next time. Downloads continue where "
                "they stopped; a conversion that was running starts over from the beginning.")
            keep_btn = box.addButton("Quit, keep jobs", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Quit and cancel jobs", QMessageBox.ButtonRole.DestructiveRole)
            stay_btn = box.addButton("Stay open", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(keep_btn)
            box.exec()
            clicked = box.clickedButton()
            if clicked is stay_btn or clicked is None:
                event.ignore()
                return
            keep = clicked is keep_btn
        self.manager.shutdown(keep=keep)
        event.accept()

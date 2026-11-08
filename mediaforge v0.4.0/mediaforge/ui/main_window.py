"""Main window: a translucent sidebar (Mica on Windows 11) beside the content, toasts instead of a status bar."""
from __future__ import annotations

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QStackedWidget, QWidget

from .. import __version__
from ..core import binaries, updater
from ..core.jobs import JobManager, JobStatus
from ..core.presets import PresetStore
from ..core.settings import Settings
from ..core.update_service import UpdateService
from .kit import Toaster, alert, choose, enable_backdrop, fade_in, feedback, qc, theme

from .pages.convert import ConvertPage
from .pages.download import DownloadPage
from .pages.join import JoinPage
from .pages.log import LogPage
from .pages.queue import QueuePage
from .sheets import SettingsSheet, UpdatesSheet
from .sidebar import Sidebar


class Surface(QWidget):
    """Opaque content area (the grouped background)."""

    def paintEvent(self, _) -> None:
        QPainter(self).fillRect(self.rect(), qc(theme.p.bg))


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.setWindowTitle("MediaForge")
        self.resize(1280, 840)
        self.setMinimumSize(theme.px(720), theme.px(540))
        self.settings = settings
        self.data_dir = updater.default_data_dir()          # presets, queue, log, downloaded ffmpeg / yt-dlp
        binaries.set_managed_dir(self.data_dir)
        feedback.enabled = settings.sound_feedback
        self.presets = PresetStore(self.data_dir / "presets.json")
        self.manager = JobManager(settings.max_parallel, settings.max_retries)
        self.manager.attach_store(self.data_dir / "queue.json")
        self.updates = UpdateService(settings, self.data_dir)
        self._seen: dict[int, JobStatus] = {}

        self.pages = {
            "convert": ConvertPage(settings, self.manager, self.presets),
            "join": JoinPage(settings, self.manager),
            "download": DownloadPage(settings, self.manager, self.presets, self.updates),
            "queue": QueuePage(self.manager),
            "log": LogPage(),
        }
        self.stack = QStackedWidget()
        for page in self.pages.values():
            self.stack.addWidget(page)
        self.side = Sidebar(
            sections=[("Tools", [("convert", "Convert", "film"), ("join", "Join", "layers"), ("download", "Download", "cloud-down")]),
                      ("Activity", [("queue", "Queue", "list"), ("log", "Log", "terminal")])],
            footer=[("updates", "Updates", "refresh"), ("settings", "Settings", "sliders")],
            menu=[("About MediaForge", self._about), ("Open Data Folder", self._open_data_folder), None, ("Quit", self.close)])
        surface = Surface()
        QHBoxLayout(surface).setContentsMargins(0, 0, 0, 0)
        surface.layout().addWidget(self.stack)
        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.side)
        lay.addWidget(surface, 1)
        self.setCentralWidget(central)
        self.toaster = Toaster(central)
        self._wire()
        self.side.select("convert", animate=False)

        QTimer.singleShot(0, self._startup_check)
        QTimer.singleShot(0, self._restore_queue)
        QTimer.singleShot(2500, self.updates.startup_check)

    # ------------------------------------------------------------- wiring
    def _wire(self) -> None:
        self.side.navigate.connect(self._on_navigate)
        self.side.action.connect(self._on_action)
        for key in ("convert", "join", "download"):
            self.pages[key].jobs_added.connect(self._on_jobs_added)
            self.pages[key].notice.connect(self._toast)
        self.manager.log.connect(self.pages["log"].append)
        self.manager.job_added.connect(self._update_badge)
        self.manager.job_changed.connect(self._on_job_changed)
        self.updates.installed.connect(self._on_tool_installed)
        self.updates.progress.connect(self._on_update_progress)
        self.updates.checked.connect(self._on_updates_checked)
        theme.changed.connect(self._on_theme)
        for i, key in enumerate(self.pages, start=1):
            QShortcut(QKeySequence(f"Ctrl+{i}"), self).activated.connect(lambda k=key: self.side.select(k, animate=False))
        QShortcut(QKeySequence("Ctrl+,"), self).activated.connect(self.open_settings)
        QShortcut(QKeySequence("Ctrl+U"), self).activated.connect(self.open_updates)
        QShortcut(QKeySequence.StandardKey.Quit, self).activated.connect(self.close)

    # ------------------------------------------------------------- appearance
    def showEvent(self, e) -> None:
        super().showEvent(e)
        if not getattr(self, "_material_done", False):
            self._material_done = True
            theme.backdrop = enable_backdrop(self, theme.dark)
            if theme.backdrop:                              # let Mica show through the translucent sidebar
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                self.centralWidget().update()

    def _on_theme(self) -> None:
        if theme.backdrop:
            enable_backdrop(self, theme.dark)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.side.set_compact(self.width() < theme.px(900))
        self.toaster.reposition()

    # ------------------------------------------------------------- navigation
    def _on_navigate(self, key: str) -> None:
        page = self.pages[key]
        if self.stack.currentWidget() is not page:
            self.stack.setCurrentWidget(page)
            fade_in(page, 140)

    def _on_action(self, key: str) -> None:
        (self.open_updates if key == "updates" else self.open_settings)()

    def _toast(self, text: str, kind: str = "info", action=None) -> None:
        self.toaster.show(text, kind, action)

    def _on_jobs_added(self, n: int) -> None:
        self._update_badge()
        self._toast(f"Added {n} job{'s' if n != 1 else ''} to the queue.", "success", ("View Queue", lambda: self.side.select("queue")))

    # ------------------------------------------------------------- jobs
    def _update_badge(self, *_) -> None:
        self.side.set_badge("queue", self.manager.active_count())

    def _on_job_changed(self, job) -> None:
        self._update_badge()
        before, now = self._seen.get(job.id), job.status
        self._seen[job.id] = now
        if before is now:
            return
        if now is JobStatus.FAILED:
            feedback.error()
            self._toast(f"Failed: {job.title}. {job.detail}"[:160], "error", ("View Queue", lambda: self.side.select("queue")), )
        elif now is JobStatus.DONE and self.manager.active_count() == 0:
            feedback.confirm()
            self._toast("All jobs finished.", "success", ("Show Folder", lambda: self._open(job)))

    @staticmethod
    def _open(job) -> None:
        folder = job.open_path()
        if folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _restore_queue(self) -> None:
        n = self.manager.restore(lambda: binaries.find("ffmpeg", self.settings.ffmpeg_path))
        if n:
            self._update_badge()
            self._toast(f"Restored {n} job{'s' if n != 1 else ''} from your last session.", "info",
                        ("Open Queue", lambda: self.side.select("queue")), )

    # ------------------------------------------------------------- tools and updates
    def _refresh_tools(self) -> None:
        for key in ("convert", "join", "download"):
            self.pages[key].refresh_binaries()

    def _on_tool_installed(self, key: str, ok: bool, message: str) -> None:
        self._toast(message, "success" if ok else "error")
        self.manager.log.emit(message)
        if ok and key == "ffmpeg":
            self._refresh_tools()
        self.pages["download"].on_tool_installed(key, ok, message)

    def _on_update_progress(self, key: str, done: int, total: int) -> None:
        self.pages["download"].on_update_progress(key, done, total)

    def _on_updates_checked(self, status: dict) -> None:
        due = [f"{st.name} {st.latest}" for st in status.values() if st.update_available and not st.error]
        self.side.set_dot("updates", bool(due))
        if due:
            self._toast("Updates available: " + ", ".join(due), "info", ("Review", self.open_updates))

    def _startup_check(self) -> None:
        if binaries.find("ffmpeg", self.settings.ffmpeg_path):
            return
        if updater.ffmpeg_install_supported():
            i = choose(self, "ffmpeg not found", "ffmpeg does the actual converting. MediaForge can download it for you now "
                       "(about 100 MB, from gyan.dev).", [("Later", "plain"), ("Open Settings", "secondary"), ("Download ffmpeg", "primary")], default=2)
            if i == 2:
                self._toast("Downloading ffmpeg...", "info")
                self.updates.install("ffmpeg")
            elif i == 1:
                self.open_settings()
        else:
            i = choose(self, "ffmpeg not found", "Install ffmpeg with your package manager (for example 'brew install ffmpeg' or "
                       "'sudo apt install ffmpeg'), or point to it in Settings.", [("Later", "plain"), ("Open Settings", "primary")], default=1)
            if i == 1:
                self.open_settings()

    # ------------------------------------------------------------- sheets and menu
    def open_settings(self) -> None:
        if SettingsSheet(self.settings, self).exec():
            self.manager.set_max_parallel(self.settings.max_parallel)
            self.manager.max_retries = self.settings.max_retries
            self._refresh_tools()

    def open_updates(self) -> None:
        UpdatesSheet(self.updates, self.settings, self).exec()

    def _about(self) -> None:
        alert(self, "About MediaForge", f"MediaForge {__version__}\nA GUI for ffmpeg and yt-dlp.\nBuilt with PySide6.")

    def _open_data_folder(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.data_dir)))

    def closeEvent(self, event) -> None:
        keep = True
        if self.manager.active_count():
            i = choose(self, "Jobs are still running",
                       "Quit and keep them: they come back paused next time. Downloads continue where they stopped; "
                       "a conversion that was running starts over from the beginning.",
                       [("Stay Open", "secondary"), ("Quit and Cancel Jobs", "destructive"), ("Quit, Keep Jobs", "primary")], default=2)
            if i is None or i == 0:
                event.ignore()
                return
            keep = i == 2
        self.manager.shutdown(keep=keep)
        event.accept()

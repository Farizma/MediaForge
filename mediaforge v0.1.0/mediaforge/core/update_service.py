"""Background checking / installing of ffmpeg and yt-dlp updates for the UI.

All network work runs in daemon threads. Results come back as Qt signals; connect them
to methods of QObjects (not lambdas) so delivery is queued onto the UI thread.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import binaries, updater
from .updater import Cancelled, ToolStatus, UpdateError
from .ytdlp_runner import ytdlp_version

CHECK_EVERY_SECONDS = 20 * 3600


class UpdateService(QObject):
    checked = Signal(object)            # {"ffmpeg": ToolStatus, "ytdlp": ToolStatus}
    progress = Signal(str, int, int)    # key, bytes done, bytes total (0 = unknown)
    installed = Signal(str, bool, str)  # key, ok, message for the user

    def __init__(self, settings, data_dir: Path) -> None:
        super().__init__()
        self.settings = settings
        self.data_dir = Path(data_dir)
        self._busy: set[str] = set()
        self._auto = False
        self._cancel = threading.Event()
        self.checked.connect(self._after_check)

    # ------------------------------------------------------------- state
    def is_busy(self, what: str | None = None) -> bool:
        return bool(self._busy) if what is None else what in self._busy

    def cancel(self) -> None:
        self._cancel.set()

    # ------------------------------------------------------------- checking
    def check(self, auto: bool = False) -> None:
        """Look up the latest versions (in the background) and emit `checked`."""
        if "check" in self._busy:
            return
        self._busy.add("check")
        self._auto = auto
        installed_ytdlp = ytdlp_version()                       # cheap; done on the UI thread
        ffmpeg_exe = binaries.find("ffmpeg", self.settings.ffmpeg_path)
        custom = bool(self.settings.ffmpeg_path.strip())
        threading.Thread(target=self._check_worker, args=(installed_ytdlp, ffmpeg_exe, custom),
                         daemon=True).start()

    def startup_check(self) -> None:
        """Run the periodic check if the user enabled it and it's due."""
        if not self.settings.auto_check_updates:
            return
        if time.time() - self.settings.last_update_check < CHECK_EVERY_SECONDS:
            return
        self.check(auto=True)

    def _check_worker(self, installed_ytdlp, ffmpeg_exe, custom_path: bool) -> None:
        status = {"ffmpeg": self._check_ffmpeg(ffmpeg_exe, custom_path),
                  "ytdlp": self._check_ytdlp(installed_ytdlp)}
        self._busy.discard("check")
        self.checked.emit(status)

    def _check_ffmpeg(self, exe, custom_path: bool) -> ToolStatus:
        st = ToolStatus("ffmpeg", "ffmpeg", can_install=updater.ffmpeg_install_supported())
        if exe:
            st.installed = updater.ffmpeg_version_string(binaries.version(exe)) or "unknown version"
            st.source = exe
        if not st.can_install:
            st.note = "Install or update ffmpeg with your package manager (brew, apt, dnf...)."
            return st
        if custom_path:
            st.note = "File > Settings points at a specific ffmpeg; clear that to use downloaded updates."
        try:
            st.latest = updater.latest_ffmpeg_version()
        except UpdateError as exc:
            st.error = str(exc)
            return st
        if exe and updater.numeric_version(st.installed) is None:
            st.note = (st.note + " " if st.note else "") + "This is a development build, so versions can't be compared."
        else:
            st.update_available = updater.is_newer(st.latest, st.installed if exe else None)
        return st

    def _check_ytdlp(self, installed) -> ToolStatus:
        st = ToolStatus("ytdlp", "yt-dlp", installed=installed)
        mod = sys.modules.get("yt_dlp")
        origin = str(getattr(mod, "__file__", "") or "")
        if installed:
            st.source = ("downloaded update" if str(self.data_dir) in origin else origin) or "installed"
        try:
            st.latest = updater.latest_ytdlp_version()
        except UpdateError as exc:
            st.error = str(exc)
            return st
        st.update_available = updater.is_newer(st.latest, installed)
        return st

    def _after_check(self, status: dict) -> None:
        """(UI thread) remember when we checked; install updates by themselves if allowed."""
        if self._auto:
            self.settings.last_update_check = time.time()
            if self.settings.auto_install_updates:
                for key, st in status.items():
                    # only update tools that are already installed; a missing one needs the user's OK
                    if st.update_available and st.installed and st.can_install and not st.error:
                        self.install(key)
        self._auto = False

    # ------------------------------------------------------------- installing
    def install(self, key: str) -> None:
        if key in self._busy:
            return
        self._busy.add(key)
        self._cancel = threading.Event()
        threading.Thread(target=self._install_worker, args=(key, self._cancel), daemon=True).start()

    def _install_worker(self, key: str, cancel: threading.Event) -> None:
        def prog(done: int, total: int) -> None:
            self.progress.emit(key, done, total)

        try:
            if key == "ffmpeg":
                name = updater.install_ffmpeg(self.data_dir, prog, cancel)
                msg = f"ffmpeg {name} installed - new jobs will use it."
            else:
                version = updater.install_ytdlp(self.data_dir, prog, cancel)
                updater.activate_ytdlp(self.data_dir)
                loaded = sys.modules.get("yt_dlp")
                running = getattr(getattr(loaded, "version", None), "__version__", None) if loaded else None
                if loaded is not None and running != version:
                    msg = f"yt-dlp {version} downloaded. Restart MediaForge to start using it."
                else:
                    msg = f"yt-dlp {version} installed."
            updater.cleanup_old(self.data_dir)
            ok = True
        except Cancelled:
            ok, msg = False, "Cancelled."
        except UpdateError as exc:
            ok, msg = False, str(exc)
        except Exception as exc:                      # never let a worker die silently
            ok, msg = False, f"Unexpected error: {exc}"
        self._busy.discard(key)
        self.installed.emit(key, ok, msg)

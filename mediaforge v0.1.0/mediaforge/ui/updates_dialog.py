"""Help > Check for updates: shows ffmpeg / yt-dlp versions and installs newer ones."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout,
)

from ..core.fmt_helpers import fmt_mb
from ..core.update_service import UpdateService
from ..core.updater import ToolStatus

TOOLS = (("ffmpeg", "ffmpeg"), ("ytdlp", "yt-dlp"))
GREEN, AMBER, RED = "color: #2e9e4f;", "color: #d98e04;", "color: #d64545;"


class UpdatesDialog(QDialog):
    def __init__(self, service: UpdateService, settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Check for updates")
        self.setMinimumWidth(640)
        self.service, self.settings = service, settings
        self._status: dict[str, ToolStatus] = {}
        self._rows: dict[str, dict] = {}
        self._notes: dict[str, str] = {}

        grid = QGridLayout()
        for col, head in enumerate(("Tool", "Installed", "Latest", "Status", "")):
            lab = QLabel(f"<b>{head}</b>")
            grid.addWidget(lab, 0, col)
        for row, (key, label) in enumerate(TOOLS, start=1):
            w = {"installed": QLabel("..."), "latest": QLabel("..."), "status": QLabel("Checking..."),
                 "button": QPushButton("Update")}
            w["status"].setWordWrap(True)
            w["button"].setEnabled(False)
            w["button"].clicked.connect(lambda _=False, k=key: self.service.install(k))
            grid.addWidget(QLabel(label), row, 0)
            for col, name in enumerate(("installed", "latest", "status", "button"), start=1):
                grid.addWidget(w[name], row, col)
            self._rows[key] = w
        grid.setColumnStretch(3, 1)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setVisible(False)
        self.message = QLabel()
        self.message.setWordWrap(True)

        self.auto_check = QCheckBox("Check for updates when MediaForge starts (at most once a day)")
        self.auto_check.setChecked(settings.auto_check_updates)
        self.auto_install = QCheckBox("Install updates automatically (only for tools that are already installed)")
        self.auto_install.setChecked(settings.auto_install_updates)
        self.auto_check.toggled.connect(self._save_options)
        self.auto_install.toggled.connect(self._save_options)

        self.check_btn = QPushButton("Check now")
        self.all_btn = QPushButton("Update all")
        self.cancel_btn = QPushButton("Cancel download")
        self.cancel_btn.setVisible(False)
        close = QPushButton("Close")
        self.check_btn.clicked.connect(self._check)
        self.all_btn.clicked.connect(self._update_all)
        self.cancel_btn.clicked.connect(self.service.cancel)
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        for b in (self.check_btn, self.all_btn, self.cancel_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(close)

        lay = QVBoxLayout(self)
        lay.addLayout(grid)
        lay.addWidget(self.bar)
        lay.addWidget(self.message)
        lay.addSpacing(6)
        lay.addWidget(self.auto_check)
        lay.addWidget(self.auto_install)
        lay.addLayout(buttons)

        service.checked.connect(self._on_checked)
        service.progress.connect(self._on_progress)
        service.installed.connect(self._on_installed)
        self.finished.connect(self._disconnect)
        self._sync_buttons()
        self._check()

    # -- plumbing
    def _disconnect(self, *_) -> None:
        for sig, slot in ((self.service.checked, self._on_checked), (self.service.progress, self._on_progress),
                           (self.service.installed, self._on_installed)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def _save_options(self) -> None:
        self.settings.auto_check_updates = self.auto_check.isChecked()
        self.settings.auto_install_updates = self.auto_install.isChecked()

    def _check(self) -> None:
        self.message.setText("")
        for w in self._rows.values():
            w["status"].setText("Checking...")
            w["status"].setStyleSheet("")
        self.service.check()
        self._sync_buttons()

    def _wants_install(self, st: ToolStatus) -> bool:
        return st.can_install and not st.error and (st.update_available or not st.installed)

    def _update_all(self) -> None:
        for key, st in self._status.items():
            if self._wants_install(st):
                self.service.install(key)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        busy = self.service.is_busy()
        self.check_btn.setEnabled(not self.service.is_busy("check"))
        self.cancel_btn.setVisible(self.service.is_busy("ffmpeg") or self.service.is_busy("ytdlp"))
        self.all_btn.setEnabled(not busy and any(self._wants_install(s) for s in self._status.values()))
        for key, w in self._rows.items():
            st = self._status.get(key)
            w["button"].setEnabled(bool(st) and not self.service.is_busy(key) and self._wants_install(st))
            w["button"].setText("Install" if st and not st.installed else "Update")

    # -- service signals
    def _on_checked(self, status: dict) -> None:
        self._status = status
        for key, st in status.items():
            w = self._rows[key]
            w["installed"].setText(st.installed or "not installed")
            w["latest"].setText(st.latest or "?")
            note = self._notes.get(key) or st.note
            if st.error:
                text, style = f"Couldn't check: {st.error}", RED
            elif not st.can_install and not st.installed:
                text, style = "Not installed", RED
            elif st.update_available and not st.installed:
                text, style = "Not installed - can be installed now", AMBER
            elif st.update_available:
                text, style = "Update available", AMBER
            elif st.latest and st.installed:
                text, style = "Up to date", GREEN
            else:
                text, style = "", ""
            w["status"].setText((text + ("\n" + note if note else "")).strip())
            w["status"].setStyleSheet(style)
        self._sync_buttons()

    def _on_progress(self, key: str, done: int, total: int) -> None:
        self.bar.setVisible(True)
        if total:
            self.bar.setRange(0, 100)
            self.bar.setValue(int(done * 100 / total))
            self.message.setText(f"Downloading {dict(TOOLS)[key]}: {fmt_mb(done)} of {fmt_mb(total)}")
        else:
            self.bar.setRange(0, 0)
            self.message.setText(f"Downloading {dict(TOOLS)[key]}: {fmt_mb(done)}")
        self._sync_buttons()

    def _on_installed(self, key: str, ok: bool, message: str) -> None:
        if not self.service.is_busy("ffmpeg") and not self.service.is_busy("ytdlp"):
            self.bar.setVisible(False)
        self.message.setText(message)
        if ok and key == "ytdlp":
            self._notes["ytdlp"] = "Downloaded - restart MediaForge to use it." if "Restart" in message else ""
        if ok:
            self.service.check()
        self._sync_buttons()

"""Settings and Updates sheets."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..core import binaries
from ..core.fmt_helpers import fmt_mb
from ..core.update_service import UpdateService
from ..core.updater import ToolStatus
from .kit import Button, Group, Label, PathField, Picker, ProgressBar, Row, Sheet, Stepper, Switch, feedback
from .kit.theme import COLOURWAYS, SPACE, theme


def _note(label: Label) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(theme.px(SPACE["l"]), 0, theme.px(SPACE["l"]), theme.px(SPACE["s"]))
    lay.addWidget(label)
    return w


class SettingsSheet(Sheet):
    def __init__(self, settings, parent=None) -> None:
        super().__init__(parent, "Settings", 560)
        self.settings = settings
        self.ffmpeg, self.ffprobe = PathField("open", placeholder="Auto-detect"), PathField("open", placeholder="Auto-detect")
        self.outdir = PathField("dir", placeholder="Next to each input file")
        self.parallel, self.retries = Stepper(1, 8, settings.max_parallel), Stepper(0, 5, settings.max_retries)
        self.sound = Switch(settings.sound_feedback)
        self.colourway = Picker([(c[1], c[0]) for c in COLOURWAYS])
        self.colourway.setValue(theme.colourway)
        self.colourway.changed.connect(lambda: theme.apply(self.colourway.value()))     # previews live
        for field, value in ((self.ffmpeg, settings.ffmpeg_path), (self.ffprobe, settings.ffprobe_path), (self.outdir, settings.output_dir)):
            field.setValue(value)
        self.ff_status, self.fp_status = Label("", "footnote", wrap=True), Label("", "footnote", wrap=True)

        look = Group("Appearance", "Dark colourways. They apply right away.")
        look.add(Row("Colourway", self.colourway))
        tools = Group("Tools", "Leave empty to auto-detect: a copy MediaForge downloaded, then ./bin, then your PATH.")
        tools.add(Row("ffmpeg", self.ffmpeg, wide=True))
        tools.add(_note(self.ff_status))
        tools.add(Row("ffprobe", self.ffprobe, wide=True))
        tools.add(_note(self.fp_status))
        jobs = Group("Jobs")
        jobs.add(Row("Run at the same time", self.parallel, "How many jobs may run together."))
        jobs.add(Row("Retry failed jobs automatically", self.retries, "How many times (0 = never)."))
        files = Group("Files")
        files.add(Row("Default output folder", self.outdir, wide=True))
        feedback_group = Group("Feedback", "Windows desktop apps have no haptics, so this is a quiet system sound instead.")
        feedback_group.add(Row("Sound when jobs finish or fail", self.sound))
        for g in (look, tools, jobs, files, feedback_group):
            self.body.addWidget(g)

        cancel, done = Button("Cancel"), Button("Done", kind="primary")
        cancel.clicked.connect(self.reject)
        done.clicked.connect(self.accept)
        self.buttons(cancel, done, default=1)

        self._timer = QTimer(self)                      # typing in a path shouldn't launch ffmpeg on every key
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._status)
        self.ffmpeg.changed.connect(self._schedule)
        self.ffprobe.changed.connect(self._schedule)
        self._status()

    def _schedule(self) -> None:
        self._timer.start(400)

    def _status(self) -> None:
        for name, field, label in (("ffmpeg", self.ffmpeg, self.ff_status), ("ffprobe", self.ffprobe, self.fp_status)):
            exe = binaries.find(name, field.value().strip())
            label.setText(f"Found: {exe}\n{binaries.version(exe)}" if exe else "Not found")
            label.setTone("green" if exe else "red")

    def accept(self) -> None:
        s = self.settings
        s.ffmpeg_path, s.ffprobe_path = self.ffmpeg.value().strip(), self.ffprobe.value().strip()
        s.output_dir, s.max_parallel, s.max_retries = self.outdir.value().strip(), self.parallel.value(), self.retries.value()
        s.sound_feedback = feedback.enabled = self.sound.value()
        s.colourway = theme.colourway
        super().accept()

    def reject(self) -> None:
        theme.apply(self.settings.colourway)            # Cancel takes the preview back
        super().reject()


def _short(version: str | None, n: int = 24) -> str:
    """Dev builds name themselves like '2026-10-01-git-0b01ed76aa-full_build-www.gyan.dev': no spaces, so it
    cannot wrap and would push the sheet wider than its window. The full text stays in the tooltip."""
    v = version or ""
    return v if len(v) <= n else v[:n - 1].rstrip("-_.") + "\u2026"


class _ToolRow(QWidget):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = Label(name, "headline")
        self.meta = Label("Checking...", "footnote", "label2", wrap=True)
        self.status = Label("", "callout", "label2", wrap=True)
        self.button = Button("Update", "download")
        self.button.setEnabled(False)
        left = QVBoxLayout()
        left.setSpacing(theme.px(2))
        for w in (self.name, self.meta, self.status):
            left.addWidget(w)
        lay = QHBoxLayout(self)
        pad = theme.px(SPACE["l"])
        lay.setContentsMargins(pad, theme.px(SPACE["m"]), pad, theme.px(SPACE["m"]))
        lay.addLayout(left, 1)
        lay.addWidget(self.button)


class UpdatesSheet(Sheet):
    TOOLS = (("app", "MediaForge"), ("ffmpeg", "ffmpeg"), ("ytdlp", "yt-dlp"))

    def __init__(self, service: UpdateService, settings, parent=None) -> None:
        super().__init__(parent, "Updates", 600)
        self.service, self.settings = service, settings
        self._status: dict[str, ToolStatus] = {}
        self._notes: dict[str, str] = {}
        self.rows = {k: _ToolRow(label) for k, label in self.TOOLS}
        group = Group("MediaForge and tools")
        for k, row in self.rows.items():
            group.add(row)
            row.button.clicked.connect(lambda _=False, k=k: self.service.install(k))
        self.bar, self.message = ProgressBar(), Label("", "callout", "label2", wrap=True)
        self.bar.hide()
        self.auto_check, self.auto_install = Switch(settings.auto_check_updates), Switch(settings.auto_install_updates)
        auto = Group("Automatic updates", "Installing automatically covers ffmpeg and yt-dlp, and only if they are already "
                     "installed. MediaForge itself always asks first. Everything is checksum-verified.")
        auto.add(Row("Check when MediaForge starts", self.auto_check, "At most once a day."))
        auto.add(Row("Install updates automatically", self.auto_install))
        self.auto_check.changed.connect(self._save)
        self.auto_install.changed.connect(self._save)
        for w in (group, self.bar, self.message, auto):
            self.body.addWidget(w)

        self.check_btn, self.all_btn = Button("Check Now"), Button("Update All", "download", "primary")
        self.cancel_btn, close = Button("Cancel Download", kind="plain"), Button("Done")
        self.cancel_btn.hide()
        self.check_btn.clicked.connect(self._check)
        self.all_btn.clicked.connect(self._update_all)
        self.cancel_btn.clicked.connect(service.cancel)
        close.clicked.connect(self.accept)
        self.buttons(self.cancel_btn, self.check_btn, self.all_btn, close)

        service.checked.connect(self._on_checked)
        service.progress.connect(self._on_progress)
        service.installed.connect(self._on_installed)
        self.finished.connect(self._disconnect)
        self._check()

    def _disconnect(self, *_) -> None:
        for sig, slot in ((self.service.checked, self._on_checked), (self.service.progress, self._on_progress),
                           (self.service.installed, self._on_installed)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def _save(self) -> None:
        self.settings.auto_check_updates, self.settings.auto_install_updates = self.auto_check.value(), self.auto_install.value()

    def _check(self) -> None:
        self.message.setText("")
        for r in self.rows.values():
            r.status.setText("")
            r.meta.setText("Checking...")
        self.service.check()
        self._sync()

    @staticmethod
    def _wants(st: ToolStatus) -> bool:
        return st.can_install and not st.error and (st.update_available or not st.installed)

    def _update_all(self) -> None:
        for key, st in self._status.items():
            if key != "app" and self._wants(st):        # MediaForge has its own button: it closes to update
                self.service.install(key)
        self._sync()

    def _sync(self) -> None:
        downloading = any(self.service.is_busy(k) for k, _ in self.TOOLS)
        self.check_btn.setEnabled(not self.service.is_busy("check"))
        self.cancel_btn.setVisible(downloading)
        self.all_btn.setEnabled(not downloading and any(self._wants(s) for k, s in self._status.items() if k != "app"))
        for key, row in self.rows.items():
            st = self._status.get(key)
            row.button.setEnabled(bool(st) and not self.service.is_busy(key) and self._wants(st))
            row.button.setText("Install" if st and not st.installed else "Update")

    def _on_checked(self, status: dict) -> None:
        self._status = status
        for key, st in status.items():
            row = self.rows[key]
            row.meta.setText(f"Installed {_short(st.installed) or 'none'}   |   Latest {_short(st.latest) or '?'}")
            row.meta.setToolTip(f"Installed {st.installed or 'none'}\nLatest {st.latest or '?'}")
            note = self._notes.get(key) or st.note
            if st.error:
                text, tone = f"Couldn't check: {st.error}", "red"
            elif not st.can_install and not st.installed:
                text, tone = "Not installed", "red"
            elif st.update_available and not st.installed:
                text, tone = "Not installed. It can be installed now.", "orange"
            elif st.update_available:
                text, tone = "Update available", "orange"
            elif st.latest and st.installed:
                text, tone = "Up to date", "green"
            else:
                text, tone = "", "label2"
            row.status.setText((text + ("\n" + note if note else "")).strip())
            row.status.setTone(tone)
        self._sync()

    def _on_progress(self, key: str, done: int, total: int) -> None:
        self.bar.show()
        name = dict(self.TOOLS)[key]
        if total:
            self.bar.setValue(done * 100 / total)
            self.message.setText(f"Downloading {name}: {fmt_mb(done)} of {fmt_mb(total)}")
        else:
            self.message.setText(f"Downloading {name}: {fmt_mb(done)}")
        self._sync()

    def _on_installed(self, key: str, ok: bool, message: str) -> None:
        if not any(self.service.is_busy(k) for k, _ in self.TOOLS):
            self.bar.hide()
        self.message.setText(message)
        if ok and key == "ytdlp":
            self._notes["ytdlp"] = "Downloaded. Restart MediaForge to use it." if "Restart" in message else ""
        if ok:
            self.service.check()
        self._sync()

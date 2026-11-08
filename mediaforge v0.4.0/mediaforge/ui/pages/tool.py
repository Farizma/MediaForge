"""Shared shell for the two ffmpeg screens: file list on the left, options on the right, one action bar."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget

from ...core import binaries
from ..kit import ActionBar, AdaptiveSplit, Button, DropList, Label, Page
from ..kit.theme import SPACE, theme

MEDIA_FILTER = ("Media files (*.mp4 *.mkv *.webm *.mov *.avi *.flv *.wmv *.m4v *.ts *.mts *.3gp "
                "*.mp3 *.m4a *.aac *.flac *.wav *.ogg *.opus *.wma *.gif);;All files (*)")


class ToolPage(Page):
    notice = Signal(str, str)         # message, kind -> a toast
    jobs_added = Signal(int)
    encoder_fields = ("video_codec", "audio_codec")

    def __init__(self, title: str, subtitle: str, settings, manager, action: str, icon: str) -> None:
        super().__init__(title, subtitle)
        self.settings, self.manager = settings, manager
        self.actions = ActionBar(action, icon)
        self.actions.primary.clicked.connect(self.add_to_queue)
        self._encoders: frozenset = frozenset()

    def finish(self, left: QWidget, right: QWidget) -> None:
        self.add(AdaptiveSplit(left, right))
        self.add(self.actions)

    def file_panel(self, title: str, reorder: bool = False, extra_rows: tuple = ()) -> QWidget:
        """The input list with Add / Remove / Clear (and any extra button rows) and an info line."""
        self.files = DropList(reorder=reorder)
        self.files.files_dropped.connect(self.add_files)
        self.files.currentItemChanged.connect(lambda *_: self.files_changed())     # selecting a file updates info + preview
        self.info = Label("", "callout", "label2", wrap=True)
        rows = [(("Add files", "file-plus", "secondary", self._browse), ("Remove", "minus", "plain", self._remove),
                 ("Clear", "x", "plain", self._clear)), *extra_rows]
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.px(SPACE["s"]))
        lay.addWidget(Label(title, "footnote", "label2"))
        lay.addWidget(self.files)
        for spec in rows:
            row = QHBoxLayout()
            for text, icon, kind, slot in spec:
                b = Button(text, icon, kind)
                b.clicked.connect(slot)
                row.addWidget(b)
            row.addStretch(1)
            lay.addLayout(row)
        lay.addWidget(self.info)
        return panel

    # -- files
    def _paths(self) -> list[str]:
        from PySide6.QtCore import Qt
        return [self.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.files.count())]

    def _browse(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Select media files", "", MEDIA_FILTER)
        if paths:
            self.add_files(paths)

    def _remove(self) -> None:
        for item in self.files.selectedItems():
            self.files.takeItem(self.files.row(item))
        self.files_changed()

    def _clear(self) -> None:
        self.files.clear()
        self.files_changed()

    # -- binaries
    def _ffmpeg(self) -> str | None:
        return binaries.find("ffmpeg", self.settings.ffmpeg_path)

    def _ffprobe(self) -> str | None:
        return binaries.find("ffprobe", self.settings.ffprobe_path)

    def refresh_binaries(self) -> None:
        """Grey out encoders this ffmpeg build doesn't have."""
        ff = self._ffmpeg()
        self._encoders = binaries.encoders(ff) if ff else frozenset()
        for name in self.encoder_fields:
            picker = self.form.ctl[name]
            for i in range(picker.count()):
                code = picker.itemData(i)
                ok = not self._encoders or code in ("copy", "none") or code in self._encoders
                picker.setItemEnabled(i, ok, "" if ok else "Not available in your ffmpeg build")
        self.refresh()

    # -- to implement
    def add_files(self, paths: list) -> None: raise NotImplementedError
    def files_changed(self) -> None: raise NotImplementedError
    def refresh(self) -> None: raise NotImplementedError
    def add_to_queue(self) -> None: raise NotImplementedError

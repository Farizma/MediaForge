"""The Join tab: order several clips and merge them into one normalised video."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from ..core import binaries
from ..core.ffmpeg_builder import AUDIO_CODECS, CONTAINERS, VIDEO_CODECS, X26X_PRESETS, LOSSLESS_AUDIO, unique_path
from ..core.jobs import FFmpegJob, JobManager
from ..core.join_builder import (
    FIT_MODES, SIZE_PRESETS, Clip, JoinOptions, audio_enabled, build_join_command,
    check_join_options, clip_from_media, plan_summary, uses_x26x_presets,
)
from ..core.probe import probe
from ..core.settings import Settings
from ..core.util import display_cmd, fmt_duration
from .ffmpeg_tab import MEDIA_FILTER, set_combo

NO_AUDIO_COLOR = QColor("#d98e04")
JOIN_VIDEO_CODECS = [(l, d) for l, d in VIDEO_CODECS if d not in ("copy", "none")]
JOIN_AUDIO_CODECS = [(l, d) for l, d in AUDIO_CODECS if d not in ("copy", "none", "pcm_s16le")]
FRAMERATES = [("Match first clip", 0), ("60", 60), ("50", 50), ("30", 30), ("25", 25), ("24", 24)]


def natural_key(path: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", Path(path).name)]


class ClipList(QListWidget):
    """Reorderable by drag & drop; also accepts files dropped from the OS."""
    files_dropped = Signal(list)
    order_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def dragEnterEvent(self, e) -> None:
        e.acceptProposedAction() if e.mimeData().hasUrls() else super().dragEnterEvent(e)

    def dragMoveEvent(self, e) -> None:
        e.acceptProposedAction() if e.mimeData().hasUrls() else super().dragMoveEvent(e)

    def dropEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            if paths:
                self.files_dropped.emit(paths)
            e.acceptProposedAction()
        else:
            super().dropEvent(e)
            self.order_changed.emit()


class JoinTab(QWidget):
    status_message = Signal(str)
    jobs_added = Signal()

    def __init__(self, settings: Settings, manager: JobManager) -> None:
        super().__init__()
        self.settings = settings
        self.manager = manager
        self._cache: dict[str, Clip] = {}
        self._encoders: frozenset[str] = frozenset()
        self._loading = False
        self._prev_container = "mp4"
        self._build_ui()
        self.refresh_binaries()
        self._refresh()

    # ------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        self.list = ClipList()
        self.list.files_dropped.connect(self.add_files)
        self.list.order_changed.connect(self._list_changed)

        def btn(text, slot):
            b = QPushButton(text)
            b.clicked.connect(slot)
            return b

        row1 = QHBoxLayout()
        for b in (btn("Add clips...", self._browse), btn("Remove", self._remove), btn("Clear", self._clear)):
            row1.addWidget(b)
        row2 = QHBoxLayout()
        for b in (btn("Move up", lambda: self._move(-1)), btn("Move down", lambda: self._move(1)),
                  btn("Sort by name", self._sort), btn("Reverse", self._reverse)):
            row2.addWidget(b)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("padding: 6px;")

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("<b>Clips</b> - drag to reorder; the top clip plays first"))
        ll.addWidget(self.list, 1)
        ll.addLayout(row1)
        ll.addLayout(row2)
        ll.addWidget(self.summary)

        tabs = QTabWidget()
        tabs.addTab(self._video_page(), "Video")
        tabs.addTab(self._audio_page(), "Audio")
        tabs.addTab(self._output_page(), "Output")

        self.warnings = QLabel()
        self.warnings.setWordWrap(True)
        self.warnings.setStyleSheet("color: #d98e04;")
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(110)
        self.preview.setStyleSheet("font-family: Menlo, Consolas, monospace; font-size: 11px;")
        box = QGroupBox("Command preview")
        bl = QVBoxLayout(box)
        bl.addWidget(self.preview)
        bl.addWidget(self.warnings)

        self.go = QPushButton("Add join to queue")
        self.go.setMinimumHeight(36)
        self.go.clicked.connect(self.add_to_queue)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(tabs, 1)
        rl.addWidget(box)
        rl.addWidget(self.go)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        QVBoxLayout(self).addWidget(split)

        for w in (self.size_combo, self.fit, self.fps, self.vcodec, self.speed, self.srate,
                  self.channels, self.acodec):
            w.currentIndexChanged.connect(self._refresh)
        self.abitrate.currentTextChanged.connect(self._refresh)
        for w in (self.cw, self.ch, self.crf):
            w.valueChanged.connect(self._refresh)
        for w in (self.silence, self.normalize, self.overwrite):
            w.toggled.connect(self._refresh)
        for w in (self.outdir, self.name, self.extra):
            w.textChanged.connect(self._refresh)
        self.container.currentIndexChanged.connect(self._on_container)

    def _video_page(self) -> QWidget:
        self.size_combo = QComboBox()
        for label, data in SIZE_PRESETS:
            self.size_combo.addItem(label, data)
        set_combo(self.size_combo, "first")
        self.cw, self.ch = QSpinBox(), QSpinBox()
        for s, v in ((self.cw, 1920), (self.ch, 1080)):
            s.setRange(16, 8192)
            s.setSingleStep(2)
            s.setValue(v)
        custom = QWidget()
        cl = QHBoxLayout(custom)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.cw)
        cl.addWidget(QLabel("x"))
        cl.addWidget(self.ch)
        cl.addStretch(1)
        self.fit = QComboBox()
        for label, data in FIT_MODES:
            self.fit.addItem(label, data)
        self.fps = QComboBox()
        for label, data in FRAMERATES:
            self.fps.addItem(label, data)
        self.vcodec = QComboBox()
        for label, data in JOIN_VIDEO_CODECS:
            self.vcodec.addItem(label, data)
        self.crf = QSpinBox()
        self.crf.setRange(0, 63)
        self.crf.setValue(23)
        self.crf.setToolTip("Lower = better quality, bigger file. x264 ~23, x265 ~28, VP9 ~32.")
        self.speed = QComboBox()
        self.speed.addItems(X26X_PRESETS)
        self.speed.setCurrentText("medium")
        w = QWidget()
        f = QFormLayout(w)
        f.addRow("Output size:", self.size_combo)
        f.addRow("Custom size:", custom)
        f.addRow("Fit mode:", self.fit)
        f.addRow("Frame rate:", self.fps)
        f.addRow("Video codec:", self.vcodec)
        f.addRow("Quality (CRF):", self.crf)
        f.addRow("Encoding speed:", self.speed)
        return w

    def _audio_page(self) -> QWidget:
        self.silence = QCheckBox("Add silent audio to clips that have none")
        self.silence.setChecked(True)
        self.silence.setToolTip("Without this, a single clip lacking audio means the joined file has no audio.")
        self.normalize = QCheckBox("Even out loudness between clips (loudnorm)")
        self.srate = QComboBox()
        for label, data in (("48000 Hz", 48000), ("44100 Hz", 44100)):
            self.srate.addItem(label, data)
        self.channels = QComboBox()
        self.channels.addItem("Stereo", 2)
        self.channels.addItem("Mono", 1)
        self.acodec = QComboBox()
        for label, data in JOIN_AUDIO_CODECS:
            self.acodec.addItem(label, data)
        self.abitrate = QComboBox()
        self.abitrate.setEditable(True)
        self.abitrate.addItems(["96k", "128k", "160k", "192k", "256k", "320k"])
        self.abitrate.setCurrentText("192k")
        w = QWidget()
        f = QFormLayout(w)
        f.addRow(self.silence)
        f.addRow(self.normalize)
        f.addRow("Sample rate:", self.srate)
        f.addRow("Channels:", self.channels)
        f.addRow("Audio codec:", self.acodec)
        f.addRow("Bitrate:", self.abitrate)
        return w

    def _output_page(self) -> QWidget:
        self.container = QComboBox()
        for key, c in CONTAINERS.items():
            if c.kind == "video":
                self.container.addItem(c.label, key)
        self.outdir = QLineEdit()
        self.outdir.setPlaceholderText("Default folder from Settings, or next to the first clip")
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_outdir)
        row = QHBoxLayout()
        row.addWidget(self.outdir, 1)
        row.addWidget(browse)
        self.name = QLineEdit("joined")
        self.overwrite = QCheckBox("Overwrite if the file exists (otherwise add ' (1)')")
        self.extra = QLineEdit()
        self.extra.setPlaceholderText("Extra ffmpeg args, e.g. -metadata title=\"My movie\"")
        w = QWidget()
        f = QFormLayout(w)
        f.addRow("Format:", self.container)
        f.addRow("Output folder:", row)
        f.addRow("File name:", self.name)
        f.addRow("", self.overwrite)
        f.addRow("Extra args:", self.extra)
        return w

    # ------------------------------------------------------------- binaries
    def _ffmpeg(self) -> str | None:
        return binaries.find("ffmpeg", self.settings.ffmpeg_path)

    def _ffprobe(self) -> str | None:
        return binaries.find("ffprobe", self.settings.ffprobe_path)

    def refresh_binaries(self) -> None:
        ff = self._ffmpeg()
        self._encoders = binaries.encoders(ff) if ff else frozenset()
        for combo in (self.vcodec, self.acodec):
            model = combo.model()
            for i in range(combo.count()):
                ok = (not self._encoders) or combo.itemData(i) in self._encoders
                model.item(i).setEnabled(ok)
                combo.setItemData(i, "" if ok else "Not available in your ffmpeg build",
                                  Qt.ItemDataRole.ToolTipRole)

    # ------------------------------------------------------------- clips
    def _paths(self) -> list[str]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    def _clips(self) -> list[Clip]:
        return [self._cache[p] for p in self._paths()]

    def _append(self, path: str) -> None:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setToolTip(path)
        self.list.addItem(item)

    def _relabel(self) -> None:
        for i in range(self.list.count()):
            item = self.list.item(i)
            c = self._cache[item.data(Qt.ItemDataRole.UserRole)]
            audio = "audio" if c.has_audio else "NO AUDIO"
            item.setText(f"{i + 1}.  {c.name}    [{c.width}x{c.height}, {c.fps:.3g} fps, "
                         f"{fmt_duration(c.duration)}, {audio}]")
            item.setForeground(QBrush() if c.has_audio else QBrush(NO_AUDIO_COLOR))

    def _list_changed(self) -> None:
        self._relabel()
        self._refresh()

    def _set_order(self, paths: list[str]) -> None:
        current = self.list.currentRow()
        self.list.clear()
        for p in paths:
            self._append(p)
        if 0 <= current < self.list.count():
            self.list.setCurrentRow(current)
        self._list_changed()

    def _browse(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Select clips to join", "", MEDIA_FILTER)
        if paths:
            self.add_files(paths)

    def _browse_outdir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select output folder")
        if path:
            self.outdir.setText(path)

    def add_files(self, paths: list[str]) -> None:
        ffprobe = self._ffprobe()
        if not ffprobe:
            QMessageBox.warning(self, "ffprobe not found",
                                "Joining needs ffprobe to read each clip. Install it or set its path in File > Settings.")
            return
        rejected = []
        for raw in paths:
            p = str(Path(raw))
            if not Path(p).is_file():
                continue
            if p not in self._cache:
                info = probe(ffprobe, p)
                try:
                    if info is None:
                        raise ValueError("not a readable media file")
                    self._cache[p] = clip_from_media(info)
                except ValueError as exc:
                    rejected.append(f"{Path(p).name}: {exc}")
                    continue
            self._append(p)  # the same clip may appear more than once on purpose
        if rejected:
            QMessageBox.information(self, "Skipped files", "\n".join(rejected))
        self._list_changed()

    def _remove(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self._list_changed()

    def _clear(self) -> None:
        self.list.clear()
        self._list_changed()

    def _move(self, delta: int) -> None:
        row = self.list.currentRow()
        new = row + delta
        if row < 0 or not 0 <= new < self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(new, item)
        self.list.setCurrentRow(new)
        self._list_changed()

    def _sort(self) -> None:
        self._set_order(sorted(self._paths(), key=natural_key))

    def _reverse(self) -> None:
        self._set_order(self._paths()[::-1])

    # ------------------------------------------------------------- options
    def _on_container(self, *_) -> None:
        key = self.container.currentData()
        if key == "webm" or self._prev_container == "webm":
            c = CONTAINERS[key]
            self._loading = True
            set_combo(self.vcodec, c.video)
            set_combo(self.acodec, c.audio)
            self._loading = False
        self._prev_container = key
        self._refresh()

    def _collect(self) -> JoinOptions:
        return JoinOptions(
            container=self.container.currentData(),
            video_codec=self.vcodec.currentData(),
            crf=self.crf.value(),
            preset=self.speed.currentText(),
            audio_codec=self.acodec.currentData(),
            audio_bitrate=self.abitrate.currentText().strip(),
            size_mode=self.size_combo.currentData(),
            width=self.cw.value(),
            height=self.ch.value(),
            fit=self.fit.currentData(),
            fps=self.fps.currentData() or None,
            sample_rate=self.srate.currentData(),
            channels=self.channels.currentData(),
            fill_silence=self.silence.isChecked(),
            normalize_audio=self.normalize.isChecked(),
            extra_args=self.extra.text(),
        )

    def _output_path(self, o: JoinOptions, clips: list[Clip]) -> Path:
        ext = CONTAINERS[o.container].ext
        name = Path(self.name.text().strip() or "joined").name
        if name.lower().endswith("." + ext):
            name = name[: -(len(ext) + 1)]
        folder = self.outdir.text().strip() or self.settings.output_dir
        folder_p = Path(folder) if folder else Path(clips[0].path).parent
        return unique_path(folder_p, name, ext, self.overwrite.isChecked(),
                           avoid=[Path(c.path) for c in clips])

    def _refresh(self, *_) -> None:
        if self._loading:
            return
        o = self._collect()
        clips = self._clips()
        self.cw.setEnabled(o.size_mode == "custom")
        self.ch.setEnabled(o.size_mode == "custom")
        self.speed.setEnabled(uses_x26x_presets(o))
        self.abitrate.setEnabled(o.audio_codec not in LOSSLESS_AUDIO)
        self.acodec.setEnabled(audio_enabled(clips, o) if clips else True)
        self.summary.setText(plan_summary(clips, o))

        issues = check_join_options(clips, o) if clips else []
        self.warnings.setText("\n".join(f"{'Error' if s == 'error' else 'Warning'}: {m}" for s, m in issues))
        if clips:
            cmd = build_join_command(self._ffmpeg() or "ffmpeg", clips, str(self._output_path(o, clips)), o)
            self.preview.setPlainText(display_cmd(cmd))
        else:
            self.preview.setPlainText("Add two or more clips to see the command.")

    # ------------------------------------------------------------- queue
    def add_to_queue(self) -> None:
        ff = self._ffmpeg()
        if not ff:
            QMessageBox.warning(self, "ffmpeg not found",
                                "Install ffmpeg or set its location in File > Settings.")
            return
        clips, o = self._clips(), self._collect()
        errors = [m for s, m in check_join_options(clips, o) if s == "error"]
        if errors:
            QMessageBox.warning(self, "Can't join yet", "\n".join(errors))
            return
        dst = self._output_path(o, clips)
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "Output folder", f"Can't create {dst.parent}:\n{exc}")
            return
        job = FFmpegJob(f"Join {len(clips)} clips -> {dst.name}",
                        build_join_command(ff, clips, str(dst), o),
                        sum(c.duration for c in clips), str(dst))
        self.manager.add(job)
        self.status_message.emit(f"Queued join of {len(clips)} clips.")
        self.jobs_added.emit()
        self._refresh()  # preview now shows the next free file name

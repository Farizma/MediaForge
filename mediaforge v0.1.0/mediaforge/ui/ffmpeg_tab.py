"""The FFmpeg tab: pick files, choose settings, preview the command, queue jobs."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QSplitter, QTabWidget, QVBoxLayout, QWidget,
    QAbstractItemView,
)

from ..core import binaries
from ..core.ffmpeg_builder import (
    AUDIO_CODECS, CONTAINERS, DEFAULT_PRESET, LOSSLESS_AUDIO, PRESETS,
    VIDEO_CODECS, X26X, X26X_PRESETS, EncodeOptions, build_command,
    PRESET_FIELDS, check_options, effective_duration, make_output_path, preset_values,
)
from ..core.jobs import FFmpegJob, JobManager
from ..core.presets import PresetStore, build_options
from ..core.probe import MediaInfo, probe
from ..core.settings import Settings
from ..core.util import display_cmd
from .preset_bar import PresetBar

MEDIA_FILTER = ("Media files (*.mp4 *.mkv *.webm *.mov *.avi *.flv *.wmv *.m4v *.ts *.mts *.3gp "
                "*.mp3 *.m4a *.aac *.flac *.wav *.ogg *.opus *.wma *.gif);;All files (*)")
RESOLUTIONS = [("Original", 0), ("2160p (4K)", 2160), ("1440p", 1440), ("1080p", 1080),
               ("720p", 720), ("480p", 480), ("360p", 360)]
FRAMERATES = [("Original", 0), ("60", 60), ("30", 30), ("25", 25), ("24", 24), ("15", 15), ("10", 10)]
AUDIO_BITRATES = ["64k", "96k", "128k", "160k", "192k", "256k", "320k"]


def set_combo(combo: QComboBox, data) -> None:
    idx = combo.findData(data)
    if idx >= 0:
        combo.setCurrentIndex(idx)


class FileList(QListWidget):
    """List that accepts files dropped from the OS file manager."""
    files_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def dragEnterEvent(self, e) -> None:
        e.acceptProposedAction() if e.mimeData().hasUrls() else super().dragEnterEvent(e)

    def dragMoveEvent(self, e) -> None:
        e.acceptProposedAction() if e.mimeData().hasUrls() else super().dragMoveEvent(e)

    def dropEvent(self, e) -> None:
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
            e.acceptProposedAction()


class FFmpegTab(QWidget):
    status_message = Signal(str)
    jobs_added = Signal()

    def __init__(self, settings: Settings, manager: JobManager, presets: PresetStore) -> None:
        super().__init__()
        self.settings = settings
        self.presets = presets
        self.manager = manager
        self._info: dict[str, MediaInfo | None] = {}
        self._encoders: frozenset[str] = frozenset()
        self._loading = False
        self._kind = "video"
        self._build_ui()
        self.refresh_binaries()
        self.preset_bar.select(DEFAULT_PRESET)  # applies it via _on_preset

    # ------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        # Left: files
        self.files = FileList()
        self.files.files_dropped.connect(self.add_files)
        self.files.currentItemChanged.connect(self._on_selection)
        add = QPushButton("Add files...")
        remove = QPushButton("Remove")
        clear = QPushButton("Clear")
        add.clicked.connect(self._browse_files)
        remove.clicked.connect(self._remove_selected)
        clear.clicked.connect(self._clear_files)
        btns = QHBoxLayout()
        for b in (add, remove, clear):
            btns.addWidget(b)
        self.info = QPlainTextEdit()
        self.info.setReadOnly(True)
        self.info.setMaximumHeight(110)
        self.info.setPlaceholderText("Drop files onto the list above, or click 'Add files...'.\n"
                                     "Select a file to see its details.")
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("<b>Input files</b>"))
        ll.addWidget(self.files, 1)
        ll.addLayout(btns)
        ll.addWidget(self.info)

        # Right: options
        self.preset_bar = PresetBar(self.presets, "ffmpeg", PRESETS, self._preset_values)
        self.preset_bar.chosen.connect(self._on_preset)
        self.container = QComboBox()
        for key, c in CONTAINERS.items():
            self.container.addItem(c.label, key)
        self.container.currentIndexChanged.connect(self._on_container)

        top = QFormLayout()
        top.addRow("Preset:", self.preset_bar)
        top.addRow("Output format:", self.container)

        tabs = QTabWidget()
        tabs.addTab(self._video_page(), "Video")
        tabs.addTab(self._audio_page(), "Audio")
        tabs.addTab(self._trim_page(), "Trim")
        tabs.addTab(self._output_page(), "Output && Advanced")

        self.warnings = QLabel()
        self.warnings.setWordWrap(True)
        self.warnings.setStyleSheet("color: #d98e04;")
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(90)
        self.preview.setStyleSheet("font-family: Menlo, Consolas, monospace; font-size: 11px;")
        box = QGroupBox("Command preview")
        bl = QVBoxLayout(box)
        bl.addWidget(self.preview)
        bl.addWidget(self.warnings)

        self.add_btn = QPushButton("Add to queue")
        self.add_btn.setMinimumHeight(36)
        self.add_btn.clicked.connect(self.add_to_queue)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addLayout(top)
        rl.addWidget(tabs, 1)
        rl.addWidget(box)
        rl.addWidget(self.add_btn)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        lay = QVBoxLayout(self)
        lay.addWidget(split)

        # Widgets that define a "preset" -> editing them flips preset to Custom
        for w in (self.vcodec, self.res, self.fps, self.speed, self.acodec):
            w.currentIndexChanged.connect(self._opts_changed)
        self.abitrate.currentTextChanged.connect(self._opts_changed)
        self.crf.valueChanged.connect(self._opts_changed)
        # Everything else just refreshes the preview
        for w in (self.start, self.end, self.outdir, self.suffix):
            w.textChanged.connect(self._refresh)
        self.extra.textChanged.connect(self._opts_changed)
        self.overwrite.toggled.connect(self._refresh)

    def _video_page(self) -> QWidget:
        self.vcodec = QComboBox()
        for label, data in VIDEO_CODECS:
            self.vcodec.addItem(label, data)
        self.crf = QSpinBox()
        self.crf.setRange(0, 63)
        self.crf.setToolTip("Constant quality. Lower = better quality, bigger file.\n"
                            "Good starting points: x264 ~23, x265 ~28, VP9 ~32.")
        self.speed = QComboBox()
        self.speed.addItems(X26X_PRESETS)
        self.speed.setToolTip("Slower presets give smaller files at the same quality (x264/x265).")
        self.res = QComboBox()
        for label, data in RESOLUTIONS:
            self.res.addItem(label, data)
        self.fps = QComboBox()
        for label, data in FRAMERATES:
            self.fps.addItem(label, data)
        w = QWidget()
        f = QFormLayout(w)
        f.addRow("Video codec:", self.vcodec)
        f.addRow("Quality (CRF):", self.crf)
        f.addRow("Encoding speed:", self.speed)
        f.addRow("Resolution (max height):", self.res)
        f.addRow("Frame rate:", self.fps)
        return w

    def _audio_page(self) -> QWidget:
        self.acodec = QComboBox()
        for label, data in AUDIO_CODECS:
            self.acodec.addItem(label, data)
        self.abitrate = QComboBox()
        self.abitrate.setEditable(True)
        self.abitrate.addItems(AUDIO_BITRATES)
        w = QWidget()
        f = QFormLayout(w)
        f.addRow("Audio codec:", self.acodec)
        f.addRow("Bitrate:", self.abitrate)
        return w

    def _trim_page(self) -> QWidget:
        self.start = QLineEdit()
        self.end = QLineEdit()
        self.start.setPlaceholderText("0   (seconds, MM:SS or HH:MM:SS)")
        self.end.setPlaceholderText("end of file")
        w = QWidget()
        f = QFormLayout(w)
        f.addRow("Start at:", self.start)
        f.addRow("End at:", self.end)
        return w

    def _output_page(self) -> QWidget:
        self.outdir = QLineEdit()
        self.outdir.setPlaceholderText("Default folder from Settings, or next to each input file")
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_outdir)
        row = QHBoxLayout()
        row.addWidget(self.outdir, 1)
        row.addWidget(browse)
        self.suffix = QLineEdit("_converted")
        self.overwrite = QCheckBox("Overwrite existing files (otherwise add ' (1)', ' (2)'...)")
        self.extra = QLineEdit()
        self.extra.setPlaceholderText('e.g.  -af loudnorm  -metadata title="My video"')
        w = QWidget()
        f = QFormLayout(w)
        f.addRow("Output folder:", row)
        f.addRow("File name suffix:", self.suffix)
        f.addRow("", self.overwrite)
        f.addRow("Extra ffmpeg args:", self.extra)
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
                code = combo.itemData(i)
                ok = (not self._encoders) or code in ("copy", "none") or code in self._encoders
                model.item(i).setEnabled(ok)
                combo.setItemData(i, "" if ok else "Not available in your ffmpeg build",
                                  Qt.ItemDataRole.ToolTipRole)
        self._update_preview()

    # ------------------------------------------------------------- state handling
    def _preset_values(self) -> dict:
        return preset_values(self._collect())

    def _on_preset(self, name: str, values: dict) -> None:
        if self._loading:
            return
        o = build_options(EncodeOptions, values, PRESET_FIELDS)
        self._loading = True
        set_combo(self.container, o.container)
        set_combo(self.vcodec, o.video_codec)
        self.crf.setValue(o.crf)
        self.speed.setCurrentText(o.preset)
        set_combo(self.res, o.resolution or 0)
        set_combo(self.fps, int(o.fps) if o.fps else 0)
        set_combo(self.acodec, o.audio_codec)
        self.abitrate.setCurrentText(o.audio_bitrate)
        if "extra_args" in values:          # built-ins leave your extra args alone
            self.extra.setText(o.extra_args)
        self._loading = False
        self._kind = CONTAINERS[self.container.currentData()].kind
        self._refresh()

    def _mark_custom(self) -> None:
        self.preset_bar.select_custom()

    def _opts_changed(self, *_) -> None:
        if self._loading:
            return
        self._mark_custom()
        self._refresh()

    def _on_container(self, *_) -> None:
        if self._loading:
            return
        c = CONTAINERS[self.container.currentData()]
        if c.kind != self._kind or c.kind != "video" or c.ext == "webm":
            self._loading = True  # swap in codecs that suit the new container
            set_combo(self.vcodec, c.video)
            set_combo(self.acodec, c.audio)
            self._loading = False
        self._kind = c.kind
        self._mark_custom()
        self._refresh()

    def _refresh(self, *_) -> None:
        if self._loading:
            return
        self._update_widget_state()
        self._update_preview()

    def _update_widget_state(self) -> None:
        c = CONTAINERS[self.container.currentData()]
        vc, ac = self.vcodec.currentData(), self.acodec.currentData()
        reencode = c.kind == "video" and vc not in ("copy", "none")
        self.vcodec.setEnabled(c.kind == "video")
        self.crf.setEnabled(reencode)
        self.speed.setEnabled(reencode and vc in X26X)
        self.res.setEnabled(reencode or c.kind == "gif")
        self.fps.setEnabled(reencode or c.kind == "gif")
        self.acodec.setEnabled(c.kind in ("video", "audio"))
        self.abitrate.setEnabled(c.kind in ("video", "audio")
                                 and ac not in LOSSLESS_AUDIO | {"copy", "none"})

    def _collect(self) -> EncodeOptions:
        return EncodeOptions(
            container=self.container.currentData(),
            video_codec=self.vcodec.currentData(),
            crf=self.crf.value(),
            preset=self.speed.currentText(),
            resolution=self.res.currentData() or None,
            fps=self.fps.currentData() or None,
            audio_codec=self.acodec.currentData(),
            audio_bitrate=self.abitrate.currentText().strip(),
            start=self.start.text(),
            end=self.end.text(),
            extra_args=self.extra.text(),
        )

    # ------------------------------------------------------------- files
    def _paths(self) -> list[str]:
        return [self.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.files.count())]

    def _current_path(self) -> str | None:
        item = self.files.currentItem()
        if item:
            return item.data(Qt.ItemDataRole.UserRole)
        paths = self._paths()
        return paths[0] if paths else None

    def _browse_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Select media files", "", MEDIA_FILTER)
        if paths:
            self.add_files(paths)

    def _browse_outdir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select output folder")
        if path:
            self.outdir.setText(path)

    def add_files(self, paths: list[str]) -> None:
        existing = set(self._paths())
        ffprobe = self._ffprobe()
        rejected = []
        for raw in paths:
            p = str(Path(raw))
            if p in existing or not Path(p).is_file():
                continue
            info = probe(ffprobe, p)
            if ffprobe and info is None:
                rejected.append(Path(p).name)
                continue
            self._info[p] = info
            item = QListWidgetItem(Path(p).name)
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)
            self.files.addItem(item)
            existing.add(p)
        if rejected:
            QMessageBox.information(self, "Skipped files",
                                    "These files aren't recognised as media:\n\n" + "\n".join(rejected))
        if self.files.currentRow() < 0 and self.files.count():
            self.files.setCurrentRow(0)
        self._update_preview()

    def _remove_selected(self) -> None:
        for item in self.files.selectedItems():
            self.files.takeItem(self.files.row(item))
        self._update_preview()

    def _clear_files(self) -> None:
        self.files.clear()
        self.info.clear()
        self._update_preview()

    def _on_selection(self, item, _prev) -> None:
        if item is None:
            self.info.clear()
        else:
            info = self._info.get(item.data(Qt.ItemDataRole.UserRole))
            self.info.setPlainText(info.summary() if info else "(no details - ffprobe not available)")
        self._update_preview()

    # ------------------------------------------------------------- preview + queue
    def _out_dir(self) -> str:
        return self.outdir.text().strip() or self.settings.output_dir

    def _output_for(self, src: str, o: EncodeOptions, taken: set[str] | None = None) -> Path:
        return make_output_path(src, self._out_dir(), self.suffix.text(),
                                CONTAINERS[o.container].ext, self.overwrite.isChecked(), taken)

    def _update_preview(self) -> None:
        o = self._collect()
        src = self._current_path()
        ff = self._ffmpeg() or "ffmpeg"
        try:
            if src:
                dst = str(self._output_for(src, o))
            else:
                src, dst = "<input file>", f"<output file>.{CONTAINERS[o.container].ext}"
            self.preview.setPlainText(display_cmd(build_command(ff, src, dst, o)))
        except ValueError:
            self.preview.setPlainText("(fix the highlighted problems below)")
        warns = check_options(o)
        self.warnings.setText("\n".join("Warning: " + w for w in warns))

    def add_to_queue(self) -> None:
        ff = self._ffmpeg()
        if not ff:
            QMessageBox.warning(self, "ffmpeg not found",
                                "Install ffmpeg or set its location in File > Settings.")
            return
        paths = self._paths()
        if not paths:
            QMessageBox.information(self, "No files", "Add at least one input file first.")
            return
        o = self._collect()
        problems = [w for w in check_options(o) if w.startswith(("Invalid", "End time", "Audio is set"))]
        if problems:
            QMessageBox.warning(self, "Check your settings", "\n".join(problems))
            return

        taken: set[str] = set()
        for src in paths:
            dst = self._output_for(src, o, taken)
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                QMessageBox.warning(self, "Output folder", f"Can't create {dst.parent}:\n{exc}")
                return
            info = self._info.get(src)
            job = FFmpegJob(Path(src).name, build_command(ff, src, str(dst), o),
                            effective_duration(info.duration if info else None, o), str(dst))
            self.manager.add(job)
        self.status_message.emit(f"Added {len(paths)} job(s) to the queue.")
        self.jobs_added.emit()

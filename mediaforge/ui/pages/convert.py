"""Convert: batch re-encode / trim / resize / extract audio with ffmpeg."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt

from ...core import binaries
from ...core.ffmpeg_builder import (
    AUDIO_CODECS, CONTAINERS, DEFAULT_PRESET, LOSSLESS_AUDIO, PRESET_FIELDS, PRESETS, VIDEO_CODECS, X26X, X26X_PRESETS,
    EncodeOptions, build_command, check_options, effective_duration, make_output_path, preset_values,
)
from ...core.jobs import FFmpegJob
from ...core.presets import build_options
from ...core.probe import probe
from ...core.util import display_cmd
from ..form import F, Form
from ..kit import Field, Group, PathField, Row, Stack, Switch, Pager, alert, feedback
from ..preset_bar import PresetBar
from .tool import ToolPage

RES = (("Original", None), ("2160p (4K)", 2160), ("1440p", 1440), ("1080p", 1080), ("720p", 720), ("480p", 480), ("360p", 360))
FPS = (("Original", None), ("60", 60), ("30", 30), ("25", 25), ("24", 24), ("15", 15), ("10", 10))
SPECS = [
    F("container", "Format", "picker", tuple((c.label, k) for k, c in CONTAINERS.items())),
    F("video_codec", "Video codec", "picker", tuple(VIDEO_CODECS)),
    F("crf", "Quality (CRF)", "stepper", hint="Lower is better quality and a bigger file.", hi=63),
    F("preset", "Encoding speed", "picker", tuple((p, p) for p in X26X_PRESETS), hint="Slower gives smaller files (x264 / x265)."),
    F("resolution", "Maximum height", "picker", RES),
    F("fps", "Frame rate", "picker", FPS),
    F("audio_codec", "Audio codec", "picker", tuple(AUDIO_CODECS)),
    F("audio_bitrate", "Bitrate", "edit", ("64k", "96k", "128k", "160k", "192k", "256k", "320k")),
    F("start", "Start at", "text", placeholder="0   (seconds, MM:SS or HH:MM:SS)"),
    F("end", "End at", "text", placeholder="End of file"),
    F("extra_args", "Extra ffmpeg arguments", "text", placeholder='-af loudnorm   -metadata title="My video"'),
]


class ConvertPage(ToolPage):
    def __init__(self, settings, manager, presets) -> None:
        super().__init__("Convert", "Re-encode, trim, resize, or pull out the audio.", settings, manager, "Add to Queue", "play")
        self._info: dict = {}
        self._kind = "video"
        self.form = f = Form(EncodeOptions, SPECS)
        self.outdir = PathField("dir", placeholder="Settings default, or next to each file")
        self.suffix, self.overwrite = Field("_converted"), Switch()
        out = Group("Output")
        out.add(Row("Output folder", self.outdir, wide=True))
        out.add(Row("File name suffix", self.suffix, wide=True))
        out.add(Row("Overwrite existing files", self.overwrite, "Otherwise a number is added: name (1).mp4"))
        self.bar = PresetBar(presets, "ffmpeg", PRESETS, lambda: preset_values(self.options()))
        pager = Pager([
            ("Video", Stack(f.group("Format", "", "container"), f.group("Video", "", "video_codec", "crf", "preset", "resolution", "fps"))),
            ("Audio", Stack(f.group("Audio", "", "audio_codec", "audio_bitrate"))),
            ("Trim", Stack(f.group("Trim", "Leave both empty to convert the whole file.", "start", "end"))),
            ("Output", Stack(out, f.group("Advanced", "", "extra_args"))),
        ])
        self.finish(self.file_panel("Input files"), Stack(self.bar, pager, spacing="l"))
        f.changed.connect(self._on_form)
        self.bar.chosen.connect(self._on_preset)
        for w in (self.outdir, self.suffix, self.overwrite):
            w.changed.connect(self.refresh)
        self.refresh_binaries()
        self.bar.select(DEFAULT_PRESET)

    def options(self) -> EncodeOptions:
        return self.form.collect()

    # -- reacting to edits
    def _on_form(self, name: str) -> None:
        if name == "container":
            self._container_defaults()
        if name in PRESET_FIELDS:
            self.bar.select_custom()
        self.refresh()

    def _container_defaults(self) -> None:
        c = CONTAINERS[self.form.get("container")]
        if c.kind != self._kind or c.kind != "video" or c.ext == "webm":      # swap in codecs that suit the new container
            self.form.apply({"video_codec": c.video, "audio_codec": c.audio})
        self._kind = c.kind

    def _on_preset(self, name: str, values: dict) -> None:
        o = build_options(EncodeOptions, values, PRESET_FIELDS)
        self.form.apply({k: getattr(o, k) for k in PRESET_FIELDS if k != "extra_args" or "extra_args" in values})
        self._kind = CONTAINERS[self.form.get("container")].kind
        self.refresh()

    def _state(self, o: EncodeOptions) -> None:
        c, f = CONTAINERS[o.container], self.form
        reencode = c.kind == "video" and o.video_codec not in ("copy", "none")
        f.enable("video_codec", c.kind == "video")
        f.enable("crf", reencode)
        f.enable("preset", reencode and o.video_codec in X26X)
        f.enable("resolution", reencode or c.kind == "gif")
        f.enable("fps", reencode or c.kind == "gif")
        f.enable("audio_codec", c.kind in ("video", "audio"))
        f.enable("audio_bitrate", c.kind in ("video", "audio") and o.audio_codec not in LOSSLESS_AUDIO | {"copy", "none"})

    # -- files
    def _current_path(self) -> str | None:
        item = self.files.currentItem()
        if item:
            return item.data(Qt.ItemDataRole.UserRole)
        paths = self._paths()
        return paths[0] if paths else None

    def add_files(self, paths: list) -> None:
        from PySide6.QtWidgets import QListWidgetItem
        existing, ffprobe, rejected = set(self._paths()), self._ffprobe(), []
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
            alert(self, "Some files were skipped", "These aren't recognised as media:\n\n" + "\n".join(rejected))
        if self.files.currentRow() < 0 and self.files.count():
            self.files.setCurrentRow(0)
        self.files_changed()

    def files_changed(self) -> None:
        src = self._current_path()
        info = self._info.get(src) if src else None
        self.info.setText(info.summary() if info else ("" if src else "Drop files here, or choose Add files."))
        self.refresh()

    # -- preview + queue
    def _out_dir(self) -> str:
        return self.outdir.value().strip() or self.settings.output_dir

    def _output_for(self, src: str, o: EncodeOptions, taken: set | None = None) -> Path:
        return make_output_path(src, self._out_dir(), self.suffix.value(), CONTAINERS[o.container].ext,
                                self.overwrite.value(), taken)

    def refresh(self) -> None:
        o = self.options()
        self._state(o)
        src, ff = self._current_path(), self._ffmpeg() or "ffmpeg"
        try:
            if src:
                dst = str(self._output_for(src, o))
            else:
                src, dst = "<input file>", f"<output file>.{CONTAINERS[o.container].ext}"
            self.actions.set_preview(display_cmd(build_command(ff, src, dst, o)))
        except ValueError:
            self.actions.set_preview("(fix the problems shown above)")
        self.actions.set_warnings(check_options(o))

    def add_to_queue(self) -> None:
        ff = self._ffmpeg()
        if not ff:
            alert(self, "ffmpeg not found", "Install ffmpeg, or set its location in Settings.")
            return
        paths = self._paths()
        if not paths:
            alert(self, "No files", "Add at least one input file first.")
            return
        o = self.options()
        problems = [w for w in check_options(o) if w.startswith(("Invalid", "End time", "Audio is set"))]
        if problems:
            alert(self, "Check your settings", "\n".join(problems))
            return
        taken: set = set()
        for src in paths:
            dst = self._output_for(src, o, taken)
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                alert(self, "Output folder", f"Can't create {dst.parent}:\n{exc}")
                return
            info = self._info.get(src)
            self.manager.add(FFmpegJob(Path(src).name, build_command(ff, src, str(dst), o),
                                       effective_duration(info.duration if info else None, o), str(dst)))
        feedback.confirm()
        self.jobs_added.emit(len(paths))

"""Join: merge several clips into one file, matching size, frame rate and audio."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush

from ...core.ffmpeg_builder import AUDIO_CODECS, CONTAINERS, LOSSLESS_AUDIO, VIDEO_CODECS, X26X_PRESETS, unique_path
from ...core.jobs import FFmpegJob
from ...core.join_builder import (
    FIT_MODES, SIZE_PRESETS, JoinOptions, audio_enabled, build_join_command, check_join_options, clip_from_media,
    plan_summary, uses_x26x_presets,
)
from ...core.probe import probe
from ...core.util import display_cmd, fmt_duration
from ..form import F, Form
from ..kit import Field, Group, Pager, PathField, Row, Stack, Switch, alert, feedback
from ..kit.theme import qc, theme
from .tool import ToolPage

FPS = (("Match first clip", None), ("60", 60), ("50", 50), ("30", 30), ("25", 25), ("24", 24))
SPECS = [
    F("size_mode", "Output size", "picker", tuple(SIZE_PRESETS)),
    F("width", "Custom width", "stepper", lo=16, hi=8192),
    F("height", "Custom height", "stepper", lo=16, hi=8192),
    F("fit", "Fit mode", "picker", tuple(FIT_MODES)),
    F("fps", "Frame rate", "picker", FPS),
    F("video_codec", "Video codec", "picker", tuple((l, d) for l, d in VIDEO_CODECS if d not in ("copy", "none"))),
    F("crf", "Quality (CRF)", "stepper", hint="Lower is better quality and a bigger file.", hi=63),
    F("preset", "Encoding speed", "picker", tuple((p, p) for p in X26X_PRESETS)),
    F("fill_silence", "Add silent audio to clips without any", "switch", hint="Without it, one silent clip makes the whole result silent."),
    F("normalize_audio", "Even out loudness between clips", "switch"),
    F("sample_rate", "Sample rate", "picker", (("48000 Hz", 48000), ("44100 Hz", 44100))),
    F("channels", "Channels", "picker", (("Stereo", 2), ("Mono", 1))),
    F("audio_codec", "Audio codec", "picker", tuple((l, d) for l, d in AUDIO_CODECS if d not in ("copy", "none", "pcm_s16le"))),
    F("audio_bitrate", "Bitrate", "edit", ("96k", "128k", "160k", "192k", "256k", "320k")),
    F("container", "Format", "picker", tuple((c.label, k) for k, c in CONTAINERS.items() if c.kind == "video")),
    F("extra_args", "Extra ffmpeg arguments", "text", placeholder='-metadata title="My movie"'),
]


def natural_key(path: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", Path(path).name)]


class JoinPage(ToolPage):
    def __init__(self, settings, manager) -> None:
        super().__init__("Join", "Put clips in order and merge them into one video.", settings, manager, "Add Join to Queue", "layers")
        reorder_rows = ((("Move up", "arrow-up", "plain", lambda: self._move(-1)), ("Move down", "arrow-down", "plain", lambda: self._move(1)),
                         ("Sort by name", "sort", "plain", self._sort), ("Reverse", "reverse", "plain", self._reverse)),)
        self._cache: dict = {}
        self._prev_container = "mp4"
        self.form = f = Form(JoinOptions, SPECS)
        self.outdir = PathField("dir", placeholder="Settings default, or next to the first clip")
        self.name, self.overwrite = Field("joined"), Switch()
        out = Group("Output")
        out.add(Row("Format", f.ctl["container"]))
        out.add(Row("Output folder", self.outdir, wide=True))
        out.add(Row("File name", self.name, wide=True))
        out.add(Row("Overwrite if it exists", self.overwrite, "Otherwise a number is added: joined (1).mp4"))
        pager = Pager([
            ("Video", Stack(f.group("Size", "", "size_mode", "width", "height", "fit", "fps"), f.group("Encoding", "", "video_codec", "crf", "preset"))),
            ("Audio", Stack(f.group("Missing and uneven audio", "", "fill_silence", "normalize_audio"), f.group("Format", "", "sample_rate", "channels", "audio_codec", "audio_bitrate"))),
            ("Output", Stack(out, f.group("Advanced", "", "extra_args"))),
        ])
        self.finish(self.file_panel("Clips, in playback order (drag to reorder)", reorder=True, extra_rows=reorder_rows), pager)
        self.files.order_changed.connect(self.files_changed)
        f.changed.connect(self._on_form)
        for w in (self.outdir, self.name, self.overwrite):
            w.changed.connect(self.refresh)
        self.refresh_binaries()

    def options(self) -> JoinOptions:
        return self.form.collect()

    def _on_form(self, name: str) -> None:
        if name == "container":
            key = self.form.get("container")
            if key == "webm" or self._prev_container == "webm":
                c = CONTAINERS[key]
                self.form.apply({"video_codec": c.video, "audio_codec": c.audio})
            self._prev_container = key
        self.refresh()

    # -- clips
    def _clips(self) -> list:
        return [self._cache[p] for p in self._paths()]

    def _append(self, path: str) -> None:
        from PySide6.QtWidgets import QListWidgetItem
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setToolTip(path)
        self.files.addItem(item)

    def _relabel(self) -> None:
        for i in range(self.files.count()):
            item = self.files.item(i)
            c = self._cache[item.data(Qt.ItemDataRole.UserRole)]
            item.setText(f"{i + 1}.  {c.name}    [{c.width}x{c.height}, {c.fps:.3g} fps, {fmt_duration(c.duration)}, "
                         f"{'audio' if c.has_audio else 'NO AUDIO'}]")
            item.setForeground(QBrush() if c.has_audio else QBrush(qc(theme.p.orange)))

    def add_files(self, paths: list) -> None:
        ffprobe = self._ffprobe()
        if not ffprobe:
            alert(self, "ffprobe not found", "Joining needs ffprobe to read each clip. Install it, or set its path in Settings.")
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
            self._append(p)                      # the same clip may appear more than once on purpose
        if rejected:
            alert(self, "Some files were skipped", "\n".join(rejected))
        self.files_changed()

    def files_changed(self) -> None:
        self._relabel()
        self.refresh()

    def _set_order(self, paths: list) -> None:
        self.files.clear()
        for p in paths:
            self._append(p)
        self.files_changed()

    def _move(self, delta: int) -> None:
        row, new = self.files.currentRow(), self.files.currentRow() + delta
        if row < 0 or not 0 <= new < self.files.count():
            return
        item = self.files.takeItem(row)
        self.files.insertItem(new, item)
        self.files.setCurrentRow(new)
        self.files_changed()

    def _sort(self) -> None:
        self._set_order(sorted(self._paths(), key=natural_key))

    def _reverse(self) -> None:
        self._set_order(self._paths()[::-1])

    # -- preview + queue
    def _output_path(self, o: JoinOptions, clips: list) -> Path:
        ext = CONTAINERS[o.container].ext
        name = Path(self.name.value().strip() or "joined").name
        if name.lower().endswith("." + ext):
            name = name[: -(len(ext) + 1)]
        folder = self.outdir.value().strip() or self.settings.output_dir
        return unique_path(Path(folder) if folder else Path(clips[0].path).parent, name, ext,
                           self.overwrite.value(), avoid=[Path(c.path) for c in clips])

    def refresh(self) -> None:
        o, clips, f = self.options(), self._clips(), self.form
        f.enable("width", o.size_mode == "custom")
        f.enable("height", o.size_mode == "custom")
        f.enable("preset", uses_x26x_presets(o))
        f.enable("audio_bitrate", o.audio_codec not in LOSSLESS_AUDIO)
        f.enable("audio_codec", audio_enabled(clips, o) if clips else True)
        self.info.setText(plan_summary(clips, o))
        issues = check_join_options(clips, o) if clips else []
        self.actions.set_warnings([f"{'Error' if s == 'error' else 'Warning'}: {m}" for s, m in issues])
        self.actions.set_preview(display_cmd(build_join_command(self._ffmpeg() or "ffmpeg", clips, str(self._output_path(o, clips)), o))
                                 if clips else "Add two or more clips to see the command.")

    def add_to_queue(self) -> None:
        ff = self._ffmpeg()
        if not ff:
            alert(self, "ffmpeg not found", "Install ffmpeg, or set its location in Settings.")
            return
        clips, o = self._clips(), self.options()
        errors = [m for s, m in check_join_options(clips, o) if s == "error"]
        if errors:
            alert(self, "Can't join yet", "\n".join(errors))
            return
        dst = self._output_path(o, clips)
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            alert(self, "Output folder", f"Can't create {dst.parent}:\n{exc}")
            return
        self.manager.add(FFmpegJob(f"Join {len(clips)} clips -> {dst.name}", build_join_command(ff, clips, str(dst), o),
                                   sum(c.duration for c in clips), str(dst)))
        feedback.confirm()
        self.jobs_added.emit(1)
        self.refresh()

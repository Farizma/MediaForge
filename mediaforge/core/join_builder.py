"""Joining several clips into one file.

Clips can differ in resolution, frame rate, orientation, audio format, or have
no audio at all. We therefore decode everything and normalise it with ffmpeg's
filter graph before the `concat` filter, which means the result is always
re-encoded (a lossless "copy" join is only possible for identical clips).

Pure Python / no Qt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

from .ffmpeg_builder import (
    CONTAINERS, X26X, EncodeOptions, audio_encode_args, quality_args, split_extra,
)
from .util import fmt_duration

SIZE_PRESETS = [
    ("Match first clip", "first"),
    ("Match largest clip", "largest"),
    ("4K (3840x2160)", "3840x2160"),
    ("1080p (1920x1080)", "1920x1080"),
    ("720p (1280x720)", "1280x720"),
    ("480p (854x480)", "854x480"),
    ("Vertical 1080x1920", "1080x1920"),
    ("Square 1080x1080", "1080x1080"),
    ("Custom...", "custom"),
]
FIT_MODES = [
    ("Fit inside, add black bars", "pad"),
    ("Fill frame, crop the edges", "crop"),
    ("Stretch to fit (distorts)", "stretch"),
]


@dataclass
class Clip:
    path: str
    duration: float
    width: int            # display size (already swapped for rotated phone video)
    height: int
    fps_raw: str          # e.g. "30000/1001"
    has_audio: bool

    @property
    def fps(self) -> float:
        return float(_fraction(self.fps_raw) or 30)

    @property
    def name(self) -> str:
        return re.split(r"[\\/]", self.path)[-1]


@dataclass
class JoinOptions:
    container: str = "mp4"
    video_codec: str = "libx264"
    crf: int = 23
    preset: str = "medium"
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    size_mode: str = "first"      # first | largest | custom | "WxH"
    width: int = 1920             # used when size_mode == "custom"
    height: int = 1080
    fit: str = "pad"              # pad | crop | stretch
    fps: float | None = None      # None = match first clip
    sample_rate: int = 48000
    channels: int = 2
    fill_silence: bool = True     # give every clip an audio track (silent if needed)
    normalize_audio: bool = False  # loudness-normalise each clip
    extra_args: str = ""


# ---------------------------------------------------------------- probing

def _fraction(raw: str | None) -> Fraction | None:
    try:
        f = Fraction(raw)
        return f if f > 0 else None
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _rotation(video: dict) -> int:
    rot = (video.get("tags") or {}).get("rotate")
    for sd in video.get("side_data_list") or []:
        if "rotation" in sd:
            rot = sd["rotation"]
    try:
        return int(float(rot)) % 360
    except (TypeError, ValueError):
        return 0


def clip_from_media(info) -> Clip:
    """Build a Clip from a probe.MediaInfo. Raises ValueError if unusable."""
    v = info.video
    if not v:
        raise ValueError("no video stream")
    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    if not w or not h:
        raise ValueError("unknown frame size")
    if _rotation(v) in (90, 270):  # ffmpeg auto-rotates, so the real frame is swapped
        w, h = h, w
    try:
        dur = float(v.get("duration"))
    except (TypeError, ValueError):
        dur = info.duration
    if not dur or dur <= 0:
        dur = info.duration
    if not dur or dur <= 0:
        raise ValueError("unknown duration")
    raw = next((r for r in (v.get("avg_frame_rate"), v.get("r_frame_rate")) if _fraction(r)), "30")
    return Clip(info.path, dur, w, h, raw, bool(info.audio))


# ---------------------------------------------------------------- planning

def target_size(clips: list[Clip], o: JoinOptions) -> tuple[int, int]:
    if o.size_mode == "first":
        w, h = clips[0].width, clips[0].height
    elif o.size_mode == "largest":
        best = max(clips, key=lambda c: c.width * c.height)
        w, h = best.width, best.height
    elif o.size_mode == "custom":
        w, h = o.width, o.height
    else:
        w, h = (int(x) for x in o.size_mode.split("x"))
    return max(2, w - w % 2), max(2, h - h % 2)  # encoders want even dimensions


def target_fps(clips: list[Clip], o: JoinOptions) -> str:
    return f"{o.fps:g}" if o.fps else clips[0].fps_raw


def audio_enabled(clips: list[Clip], o: JoinOptions) -> bool:
    return o.fill_silence or all(c.has_audio for c in clips)


def plan_summary(clips: list[Clip], o: JoinOptions) -> str:
    if not clips:
        return "Add at least two clips."
    w, h = target_size(clips, o)
    fps = _fraction(target_fps(clips, o))
    lines = [
        f"{len(clips)} clips, {fmt_duration(sum(c.duration for c in clips))} total",
        f"Output: {w}x{h} @ {float(fps or 30):.3g} fps",
    ]
    if audio_enabled(clips, o):
        silent = sum(not c.has_audio for c in clips)
        ch = "stereo" if o.channels == 2 else "mono"
        extra = f", silence added to {silent} clip(s)" if silent else ""
        lines.append(f"Audio: {o.sample_rate // 1000 if o.sample_rate % 1000 == 0 else o.sample_rate / 1000:g} kHz {ch}{extra}")
    else:
        lines.append("Audio: none (some clips have no audio and silence is turned off)")
    rescaled = sum((c.width, c.height) != (w, h) for c in clips)
    if rescaled:
        lines.append(f"{rescaled} clip(s) will be resized")
    return "\n".join(lines)


def check_join_options(clips: list[Clip], o: JoinOptions) -> list[tuple[str, str]]:
    """Returns [(severity, message)] where severity is 'error' or 'warn'."""
    out: list[tuple[str, str]] = []
    if len(clips) < 2:
        out.append(("error", "Add at least two clips to join."))
    c = CONTAINERS.get(o.container)
    if c is None or c.kind != "video":
        out.append(("error", "Choose a video output format."))
        return out
    if o.video_codec in ("copy", "none"):
        out.append(("error", "Joining needs a real video codec (not copy / none)."))
    if o.audio_codec in ("copy", "none") and audio_enabled(clips, o):
        out.append(("error", "Joining needs a real audio codec (not copy / none)."))
    if o.container == "webm":
        if o.video_codec not in ("libvpx-vp9", "libsvtav1"):
            out.append(("error", "WebM only supports VP9 or AV1 video."))
        if o.audio_codec not in ("libopus", "libvorbis"):
            out.append(("error", "WebM only supports Opus or Vorbis audio."))
    if clips and not o.fill_silence and any(not c.has_audio for c in clips) and any(c.has_audio for c in clips):
        out.append(("warn", "Some clips have no audio and 'add silence' is off, so the joined file will have no audio at all."))
    if clips:
        w, h = target_size(clips, o)
        if any(c.width < w and c.height < h for c in clips):
            out.append(("warn", "Some clips are smaller than the output and will be upscaled."))
    try:
        import shlex
        shlex.split(o.extra_args or "")
    except ValueError:
        out.append(("warn", "Extra arguments have unbalanced quotes and will be ignored."))
    return out


# ---------------------------------------------------------------- command

def _video_chain(w: int, h: int, fps: str, fit: str) -> str:
    if fit == "crop":
        fit_f = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    elif fit == "stretch":
        fit_f = f"scale={w}:{h}"
    else:
        fit_f = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                 f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black")
    # setsar/format/fps must match across clips or concat refuses to run
    return f"fps={fps},{fit_f},setsar=1,format=yuv420p,setpts=PTS-STARTPTS"


def build_filter_graph(clips: list[Clip], o: JoinOptions) -> str:
    w, h = target_size(clips, o)
    fps = target_fps(clips, o)
    audio = audio_enabled(clips, o)
    layout = "stereo" if o.channels == 2 else "mono"
    parts: list[str] = []
    for i, clip in enumerate(clips):
        parts.append(f"[{i}:v:0]{_video_chain(w, h, fps, o.fit)}[v{i}]")
        if not audio:
            continue
        if clip.has_audio:
            chain = ["loudnorm=I=-16:TP=-1.5:LRA=11"] if o.normalize_audio else []
            chain += [
                f"aresample={o.sample_rate}",
                f"aformat=sample_fmts=fltp:channel_layouts={layout}",
                "apad",                          # pad short audio with silence...
                f"atrim=0:{clip.duration:.3f}",  # ...and cut long audio, so A/V stay in sync
                "asetpts=PTS-STARTPTS",
            ]
            parts.append(f"[{i}:a:0]{','.join(chain)}[a{i}]")
        else:
            parts.append(f"anullsrc=r={o.sample_rate}:cl={layout}:d={clip.duration:.3f},"
                         f"asetpts=PTS-STARTPTS[a{i}]")
    streams = "".join(f"[v{i}][a{i}]" if audio else f"[v{i}]" for i in range(len(clips)))
    parts.append(f"{streams}concat=n={len(clips)}:v=1:a={1 if audio else 0}[v]" + ("[a]" if audio else ""))
    return ";".join(parts)


def build_join_command(ffmpeg: str, clips: list[Clip], dst: str, o: JoinOptions) -> list[str]:
    c = CONTAINERS[o.container]
    eo = EncodeOptions(container=o.container, video_codec=o.video_codec, crf=o.crf,
                       preset=o.preset, audio_codec=o.audio_codec, audio_bitrate=o.audio_bitrate)
    audio = audio_enabled(clips, o)
    cmd = [ffmpeg, "-hide_banner", "-y"]
    for clip in clips:
        cmd += ["-i", clip.path]
    cmd += ["-filter_complex", build_filter_graph(clips, o), "-map", "[v]"]
    if audio:
        cmd += ["-map", "[a]"]
    cmd += ["-c:v", o.video_codec] + quality_args(eo, c)
    if audio:
        cmd += audio_encode_args(eo)
    if c.ext in ("mp4", "mov"):
        cmd += ["-movflags", "+faststart"]
    cmd += split_extra(o.extra_args)
    cmd.append(dst)
    return cmd


def uses_x26x_presets(o: JoinOptions) -> bool:
    return o.video_codec in X26X

"""Turns a set of user choices into an ffmpeg command line.

Pure Python (no Qt) so it can be unit-tested and reused by a CLI later.
"""
from __future__ import annotations

import math
import shlex
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ContainerInfo:
    ext: str
    label: str
    kind: str   # "video" | "audio" | "gif"
    video: str  # sensible default video codec
    audio: str  # sensible default audio codec


CONTAINERS: dict[str, ContainerInfo] = {
    "mp4":  ContainerInfo("mp4",  "MP4 (video)",        "video", "libx264",    "aac"),
    "mkv":  ContainerInfo("mkv",  "MKV (video)",        "video", "libx264",    "aac"),
    "webm": ContainerInfo("webm", "WebM (video)",       "video", "libvpx-vp9", "libopus"),
    "mov":  ContainerInfo("mov",  "MOV (video)",        "video", "libx264",    "aac"),
    "gif":  ContainerInfo("gif",  "GIF (animated)",     "gif",   "libx264",    "none"),
    "mp3":  ContainerInfo("mp3",  "MP3 (audio)",        "audio", "none",       "libmp3lame"),
    "m4a":  ContainerInfo("m4a",  "M4A / AAC (audio)",  "audio", "none",       "aac"),
    "flac": ContainerInfo("flac", "FLAC (audio)",       "audio", "none",       "flac"),
    "wav":  ContainerInfo("wav",  "WAV (audio)",        "audio", "none",       "pcm_s16le"),
    "opus": ContainerInfo("opus", "Opus (audio)",       "audio", "none",       "libopus"),
    "ogg":  ContainerInfo("ogg",  "Ogg Vorbis (audio)", "audio", "none",       "libvorbis"),
}

VIDEO_CODECS = [
    ("Copy (no re-encode)", "copy"),
    ("H.264 (x264)", "libx264"),
    ("H.265 / HEVC (x265)", "libx265"),
    ("VP9", "libvpx-vp9"),
    ("AV1 (SVT-AV1)", "libsvtav1"),
    ("H.264 - NVIDIA NVENC", "h264_nvenc"),
    ("H.265 - NVIDIA NVENC", "hevc_nvenc"),
    ("H.264 - Apple VideoToolbox", "h264_videotoolbox"),
    ("H.265 - Apple VideoToolbox", "hevc_videotoolbox"),
    ("No video", "none"),
]
AUDIO_CODECS = [
    ("Copy (no re-encode)", "copy"),
    ("AAC", "aac"),
    ("MP3", "libmp3lame"),
    ("Opus", "libopus"),
    ("Vorbis", "libvorbis"),
    ("FLAC (lossless)", "flac"),
    ("PCM 16-bit (WAV)", "pcm_s16le"),
    ("No audio", "none"),
]
X26X_PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast",
                "medium", "slow", "slower", "veryslow"]

X26X = {"libx264", "libx265"}
HEVC = {"libx265", "hevc_nvenc", "hevc_videotoolbox"}
LOSSLESS_AUDIO = {"flac", "pcm_s16le"}


@dataclass
class EncodeOptions:
    container: str = "mp4"
    video_codec: str = "libx264"
    crf: int = 23
    preset: str = "medium"
    resolution: int | None = None   # target height in px; None = original
    fps: float | None = None
    audio_codec: str = "aac"
    audio_bitrate: str = "160k"
    start: str = ""
    end: str = ""
    extra_args: str = ""


# Fields a preset stores (trim times are per-file, so they are not part of a preset).
PRESET_FIELDS = ("container", "video_codec", "crf", "preset", "resolution", "fps",
                 "audio_codec", "audio_bitrate", "extra_args")


def preset_values(o: EncodeOptions) -> dict:
    return {f: getattr(o, f) for f in PRESET_FIELDS}


PRESETS: dict[str, dict] = {
    "Web video - MP4 (H.264 + AAC)": dict(container="mp4", video_codec="libx264", crf=23,
                                           audio_codec="aac", audio_bitrate="160k"),
    "Small file - MP4 (H.265 + AAC)": dict(container="mp4", video_codec="libx265", crf=28,
                                            audio_codec="aac", audio_bitrate="128k"),
    "Share online - 720p MP4": dict(container="mp4", video_codec="libx264", crf=26, preset="fast",
                                     resolution=720, audio_codec="aac", audio_bitrate="128k"),
    "WebM (VP9 + Opus)": dict(container="webm", video_codec="libvpx-vp9", crf=32,
                               audio_codec="libopus", audio_bitrate="128k"),
    "Remux to MKV (no re-encode)": dict(container="mkv", video_codec="copy", audio_codec="copy"),
    "Remux to MP4 (no re-encode)": dict(container="mp4", video_codec="copy", audio_codec="copy"),
    "Extract audio - MP3 192k": dict(container="mp3", video_codec="none",
                                      audio_codec="libmp3lame", audio_bitrate="192k"),
    "Extract audio - M4A (AAC)": dict(container="m4a", video_codec="none",
                                       audio_codec="aac", audio_bitrate="192k"),
    "Extract audio - FLAC": dict(container="flac", video_codec="none", audio_codec="flac"),
    "Animated GIF (480px, 15 fps)": dict(container="gif", video_codec="libx264",
                                          audio_codec="none", fps=15),
}
DEFAULT_PRESET = "Web video - MP4 (H.264 + AAC)"


# ---------------------------------------------------------------- helpers

def parse_time(text: str) -> float | None:
    """'90', '1:30', '01:02:03.5' -> seconds. Empty -> None. Bad input -> ValueError."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        parts = [float(p) for p in text.split(":")]
    except ValueError:
        raise ValueError(f"Invalid time: {text!r}") from None
    if len(parts) > 3 or any(p < 0 or not math.isfinite(p) for p in parts):
        raise ValueError(f"Invalid time: {text!r}")
    secs = 0.0
    for p in parts:
        secs = secs * 60 + p
    return secs


def _t(sec: float) -> str:
    return f"{sec:.3f}"


def split_extra(text: str) -> list[str]:
    try:
        return shlex.split(text or "")
    except ValueError:
        return []


def effective_duration(total: float | None, o: EncodeOptions) -> float | None:
    """Length of the output in seconds (used for progress %), or None if unknown."""
    try:
        start = parse_time(o.start) or 0.0
        end = parse_time(o.end)
    except ValueError:
        return total
    if end is None:
        end = total
    elif total:
        end = min(end, total)
    if end is None:
        return None
    return max(end - start, 0.0) or None


def unique_path(folder: Path, stem: str, ext: str, overwrite: bool,
                taken: set[str] | None = None, avoid: list[Path] | None = None) -> Path:
    """folder/stem.ext, or 'stem (1).ext'... if that would hit an input, a batch
    sibling, or (when not overwriting) an existing file."""
    taken = taken if taken is not None else set()
    avoid_r = {p.resolve() for p in (avoid or [])}

    def clashes(p: Path) -> bool:
        if p.resolve() in avoid_r or str(p) in taken:
            return True
        return p.exists() and not overwrite

    target = folder / f"{stem}.{ext}"
    n = 1
    while clashes(target):
        target = folder / f"{stem} ({n}).{ext}"
        n += 1
    taken.add(str(target))
    return target


def make_output_path(src: str, out_dir: str, suffix: str, ext: str,
                     overwrite: bool, taken: set[str] | None = None) -> Path:
    """Pick an output path next to (or in out_dir for) src. Never clobbers the source."""
    src_p = Path(src)
    folder = Path(out_dir) if out_dir else src_p.parent
    return unique_path(folder, f"{src_p.stem}{suffix}", ext, overwrite, taken, [src_p])


# ---------------------------------------------------------------- builder

def _gif_filter(o: EncodeOptions) -> str:
    fps = f"{o.fps:g}" if o.fps else "15"
    if o.resolution:
        scale = f"scale=-1:'min({o.resolution},ih)':flags=lanczos"
    else:
        scale = "scale='min(480,iw)':-1:flags=lanczos"
    return f"fps={fps},{scale},split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"


def quality_args(o: EncodeOptions, c: ContainerInfo) -> list[str]:
    """Encoder-specific quality flags (everything that follows `-c:v <codec>`)."""
    vc = o.video_codec
    args: list[str] = []
    if vc in X26X:
        args += ["-crf", str(o.crf), "-preset", o.preset]
        if vc == "libx264":
            args += ["-pix_fmt", "yuv420p"]
    elif vc == "libvpx-vp9":
        args += ["-crf", str(o.crf), "-b:v", "0", "-row-mt", "1", "-pix_fmt", "yuv420p"]
    elif vc == "libsvtav1":
        args += ["-crf", str(o.crf), "-preset", "8"]
    elif vc.endswith("_nvenc"):
        args += ["-rc", "vbr", "-cq", str(o.crf), "-b:v", "0", "-preset", "p5"]
    elif vc.endswith("_videotoolbox"):
        # VideoToolbox has no CRF; -q:v is 1-100 (higher = better). Rough mapping.
        args += ["-q:v", str(max(1, min(100, 100 - o.crf * 2)))]
    if vc in HEVC and c.ext in ("mp4", "mov"):
        args += ["-tag:v", "hvc1"]  # lets Apple devices play HEVC-in-MP4
    return args


def _video_args(o: EncodeOptions, c: ContainerInfo) -> list[str]:
    vc = o.video_codec
    if c.kind == "audio" or vc == "none":
        return ["-vn"]
    args = ["-map", "0:v:0?", "-c:v", vc]
    if vc == "copy":
        return args
    vf = []
    if o.fps:
        vf.append(f"fps={o.fps:g}")
    if o.resolution:
        vf.append(f"scale=-2:'min({o.resolution},ih)'")
    if vf:
        args += ["-vf", ",".join(vf)]
    return args + quality_args(o, c)


def audio_encode_args(o: EncodeOptions) -> list[str]:
    """`-c:a <codec>` plus a bitrate where that makes sense."""
    args = ["-c:a", o.audio_codec]
    if o.audio_codec not in LOSSLESS_AUDIO and o.audio_codec != "copy" and o.audio_bitrate:
        args += ["-b:a", o.audio_bitrate]
    return args


def _audio_args(o: EncodeOptions, c: ContainerInfo) -> list[str]:
    ac = o.audio_codec
    if ac == "none":
        return ["-an"]
    args = audio_encode_args(o)
    if c.kind == "video":
        args = ["-map", "0:a?"] + args
    return args


def build_command(ffmpeg: str, src: str, dst: str, o: EncodeOptions) -> list[str]:
    c = CONTAINERS[o.container]
    cmd = [ffmpeg, "-hide_banner", "-y"]

    start = parse_time(o.start)
    end = parse_time(o.end)
    if start:
        cmd += ["-ss", _t(start)]     # before -i = fast seek
    cmd += ["-i", src]
    if end is not None:
        length = end - (start or 0.0)
        if length > 0:
            cmd += ["-t", _t(length)]

    if c.kind == "gif":
        cmd += ["-an", "-vf", _gif_filter(o), "-loop", "0"]
    else:
        cmd += _video_args(o, c) + _audio_args(o, c)
        if c.ext == "mkv" and c.kind == "video":
            cmd += ["-map", "0:s?", "-c:s", "copy"]
        if c.ext in ("mp4", "mov", "m4a"):
            cmd += ["-movflags", "+faststart"]

    cmd += split_extra(o.extra_args)
    cmd.append(dst)
    return cmd


def check_options(o: EncodeOptions) -> list[str]:
    """Human-readable warnings about questionable combinations."""
    c = CONTAINERS.get(o.container)
    if c is None:
        return ["Unknown container."]
    warn: list[str] = []
    times = {}
    for label, val in (("start", o.start), ("end", o.end)):
        try:
            times[label] = parse_time(val)
        except ValueError:
            warn.append(f"Invalid {label} time: {val!r} (use seconds or HH:MM:SS).")
    s, e = times.get("start"), times.get("end")
    if s is not None and e is not None and e <= s:
        warn.append("End time must be after the start time.")
    try:
        shlex.split(o.extra_args or "")
    except ValueError:
        warn.append("Extra arguments have unbalanced quotes and will be ignored.")

    if c.kind == "video":
        if o.container == "webm":
            if o.video_codec not in ("libvpx-vp9", "libsvtav1", "copy", "none"):
                warn.append("WebM only supports VP9 or AV1 video.")
            if o.audio_codec not in ("libopus", "libvorbis", "copy", "none"):
                warn.append("WebM only supports Opus or Vorbis audio.")
        if o.container in ("mp4", "mov") and o.video_codec == "libvpx-vp9":
            warn.append("VP9 in MP4/MOV has poor player support; consider WebM or MKV.")
        if o.video_codec == "copy" and (o.resolution or o.fps):
            warn.append("Resize / FPS are ignored when copying video.")
        if o.video_codec == "copy" and (o.start or o.end):
            warn.append("Trimming without re-encoding cuts on keyframes, so it may be imprecise.")
    elif c.kind == "audio":
        if o.audio_codec not in (c.audio, "copy"):
            warn.append(f"{c.label} normally uses the {c.audio} codec.")
        if o.audio_codec == "none":
            warn.append("Audio is set to 'No audio' - the output would be empty.")
    return warn

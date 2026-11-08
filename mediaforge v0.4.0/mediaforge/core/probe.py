"""ffprobe wrapper: read basic facts about a media file."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field

from .util import fmt_duration, fmt_size, hidden_kwargs


@dataclass
class MediaInfo:
    path: str
    duration: float | None = None
    size: int = 0
    format_name: str = ""
    video: dict | None = None
    audio: list[dict] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Duration: {fmt_duration(self.duration)}   Size: {fmt_size(self.size)}   "
            f"Container: {self.format_name}"
        ]
        if self.video:
            v = self.video
            fps = _fps(v.get("avg_frame_rate") or v.get("r_frame_rate"))
            fps_txt = f" @ {fps:g} fps" if fps else ""
            lines.append(f"Video: {v.get('codec_name', '?')} {v.get('width', '?')}x{v.get('height', '?')}{fps_txt}")
        for i, a in enumerate(self.audio, 1):
            ch = a.get("channel_layout") or f"{a.get('channels', '?')} ch"
            lines.append(f"Audio {i}: {a.get('codec_name', '?')}, {a.get('sample_rate', '?')} Hz, {ch}")
        if not self.video and not self.audio:
            lines.append("No audio or video streams found.")
        return "\n".join(lines)


def _fps(raw: str | None) -> float | None:
    try:
        num, den = raw.split("/")
        return round(int(num) / int(den), 3) if int(den) else None
    except (AttributeError, ValueError):
        return None


def probe(ffprobe: str | None, path: str) -> MediaInfo | None:
    """Return MediaInfo, or None if ffprobe is missing / can't read the file."""
    if not ffprobe:
        return None
    try:
        res = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, **hidden_kwargs(),
        )
        data = json.loads(res.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    if not streams:
        return None
    video = next(
        (s for s in streams if s.get("codec_type") == "video"
         and not (s.get("disposition") or {}).get("attached_pic")), None)
    try:
        duration = float(fmt.get("duration"))
    except (TypeError, ValueError):
        duration = None
    return MediaInfo(
        path=path,
        duration=duration,
        size=int(fmt.get("size") or 0),
        format_name=fmt.get("format_name", ""),
        video=video,
        audio=[s for s in streams if s.get("codec_type") == "audio"],
    )

"""Turns user choices into yt-dlp command-line arguments (and reads its info dicts).

We deliberately speak yt-dlp's *CLI* language: the runner hands these arguments
to `yt_dlp.parse_options()`, which gives post-processor ordering, option
validation and defaults exactly as the real command line would. It also means
the command preview in the UI is something you can paste into a terminal.

Pure Python / no Qt, so it is unit-testable.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import asdict, dataclass
from pathlib import Path

from .util import fmt_duration

RESOLUTIONS = [("Best available", 0), ("2160p (4K)", 2160), ("1440p", 1440), ("1080p", 1080),
               ("720p", 720), ("480p", 480), ("360p", 360), ("240p", 240)]
VIDEO_CONTAINERS = [("Automatic", "auto"), ("MP4", "mp4"), ("MKV", "mkv"), ("WebM", "webm")]
QUALITY_MODES = [("Best quality (any codec)", 0), ("Most compatible (H.264 + AAC)", 1)]
AUDIO_FORMATS = [("Best (keep original, no conversion)", "best"), ("MP3", "mp3"),
                 ("M4A (AAC)", "m4a"), ("Opus", "opus"), ("Vorbis (Ogg)", "vorbis"),
                 ("FLAC (lossless)", "flac"), ("WAV (lossless)", "wav")]
AUDIO_QUALITIES = [("Best (VBR 0)", "0"), ("320 kbps", "320K"), ("256 kbps", "256K"),
                   ("192 kbps", "192K"), ("128 kbps", "128K"), ("96 kbps", "96K")]
LOSSY_AUDIO = {"mp3", "aac", "m4a", "opus", "vorbis"}
BROWSERS = ["", "chrome", "firefox", "edge", "brave", "safari", "opera", "vivaldi", "chromium"]
SPONSORBLOCK = [("Off", "off"), ("Mark segments as chapters", "mark"), ("Remove sponsor segments", "remove")]
PLAYLIST_MODES = [("Automatic (yt-dlp default)", "auto"), ("Single video only", "single"),
                  ("Whole playlist", "playlist")]
TEMPLATES = [
    "%(title)s [%(id)s].%(ext)s",
    "%(title)s.%(ext)s",
    "%(uploader)s - %(title)s.%(ext)s",
    "%(upload_date>%Y-%m-%d)s - %(title)s.%(ext)s",
]
DEFAULT_TEMPLATE = TEMPLATES[0]
# Prepended when "own folder + numbering" is ticked. The `&{}...|` syntax outputs
# nothing for single videos, so this is safe to apply to every URL.
PLAYLIST_PREFIX = "%(playlist_title&{}/|)s%(playlist_index&{} - |)s"


@dataclass
class DownloadOptions:
    mode: str = "video"            # video | audio
    format_id: str = ""            # specific row picked from the format table
    format_kind: str = ""          # "video+audio" | "video" | "audio" (kind of that row)
    max_height: int = 0            # 0 = best
    compat: bool = False           # prefer H.264 + AAC
    container: str = "auto"        # auto | mp4 | mkv | webm
    audio_format: str = "mp3"
    audio_quality: str = "0"
    subs: bool = False
    auto_subs: bool = False
    sub_langs: str = "en"
    embed_subs: bool = False
    embed_thumbnail: bool = False
    embed_metadata: bool = True
    embed_chapters: bool = True
    sponsorblock: str = "off"      # off | mark | remove
    playlist_mode: str = "auto"    # auto | single | playlist
    playlist_items: str = ""
    playlist_folder: bool = False
    out_dir: str = ""
    template: str = DEFAULT_TEMPLATE
    restrict_filenames: bool = False
    use_upload_mtime: bool = False
    archive: str = ""
    cookies_browser: str = ""
    cookies_file: str = ""
    rate_limit: str = ""
    proxy: str = ""
    fragments: int = 4
    extra_args: str = ""
    ffmpeg_location: str = ""


# ---------------------------------------------------------------- URLs

def looks_like_url(token: str) -> bool:
    return bool(re.match(r"^[A-Za-z][\w+.-]*://\S+$", token))


def parse_urls(text: str) -> list[str]:
    """Whitespace/newline separated tokens, de-duplicated, order preserved."""
    seen: dict[str, None] = {}
    for tok in re.split(r"\s+", (text or "").strip()):
        if tok:
            seen.setdefault(tok)
    return list(seen)


# ---------------------------------------------------------------- args

def format_selector(o: DownloadOptions) -> str:
    if o.format_id:
        if o.mode == "video" and o.format_kind == "video":  # video-only row: add audio
            return f"{o.format_id}+bestaudio/{o.format_id}"
        return o.format_id
    if o.mode == "audio":
        return "bestaudio/best"
    h = f"[height<={o.max_height}]" if o.max_height else ""
    if o.compat:
        return (f"bv*[vcodec^=avc1]{h}+ba[acodec^=mp4a]/bv*[vcodec^=avc1]{h}+ba/"
                f"bv*{h}+ba/b{h}")
    return f"bv*{h}+ba/b{h}"


def _network_args(o: DownloadOptions) -> list[str]:
    a: list[str] = []
    if o.cookies_file.strip():
        a += ["--cookies", o.cookies_file.strip()]
    elif o.cookies_browser:
        a += ["--cookies-from-browser", o.cookies_browser]
    if o.proxy.strip():
        a += ["--proxy", o.proxy.strip()]
    return a


def _playlist_mode_args(o: DownloadOptions) -> list[str]:
    return {"single": ["--no-playlist"], "playlist": ["--yes-playlist"]}.get(o.playlist_mode, [])


def split_extra(text: str) -> list[str]:
    try:
        return shlex.split(text or "")
    except ValueError:
        return []


def build_info_args(o: DownloadOptions) -> list[str]:
    """Arguments for 'just look, don't download' (format list, title, playlist size)."""
    return (["--ignore-config", "--skip-download", "--flat-playlist"]
            + _network_args(o) + _playlist_mode_args(o))


def build_args(o: DownloadOptions) -> list[str]:
    a = ["--ignore-config"]
    if o.ffmpeg_location:
        a += ["--ffmpeg-location", o.ffmpeg_location]
    if o.out_dir:
        a += ["-P", o.out_dir]
    template = o.template.strip() or DEFAULT_TEMPLATE
    if o.playlist_folder:
        template = PLAYLIST_PREFIX + template
    a += ["-o", template, "-f", format_selector(o)]

    if o.mode == "audio":
        a += ["-x", "--audio-format", o.audio_format]
        if o.audio_format in LOSSY_AUDIO and o.audio_quality:
            a += ["--audio-quality", o.audio_quality]
    else:
        container = o.container
        if container == "auto" and o.compat:
            container = "mp4"
        if container != "auto":
            a += ["--merge-output-format", container, "--remux-video", container]

    if o.subs or o.auto_subs:
        if o.subs:
            a.append("--write-subs")
        if o.auto_subs:
            a.append("--write-auto-subs")
        a += ["--sub-langs", o.sub_langs.strip() or "en"]
        if o.embed_subs and o.mode == "video":
            a.append("--embed-subs")
    if o.embed_metadata:
        a.append("--embed-metadata")
    if o.embed_chapters:
        a.append("--embed-chapters")
    if o.embed_thumbnail:
        a.append("--embed-thumbnail")
    if o.sponsorblock == "mark":
        a += ["--sponsorblock-mark", "all"]
    elif o.sponsorblock == "remove":
        a += ["--sponsorblock-remove", "sponsor,selfpromo,interaction"]

    a += _playlist_mode_args(o)
    if o.playlist_items.strip():
        a += ["--playlist-items", o.playlist_items.strip()]
    if o.restrict_filenames:
        a.append("--restrict-filenames")
    if not o.use_upload_mtime:
        a.append("--no-mtime")
    if o.archive.strip():
        a += ["--download-archive", o.archive.strip()]

    a += _network_args(o)
    if o.rate_limit.strip():
        a += ["-r", o.rate_limit.strip()]
    if o.fragments > 1:
        a += ["-N", str(o.fragments)]
    return a + split_extra(o.extra_args)


def check_options(o: DownloadOptions, urls: list[str], has_ffmpeg: bool) -> list[tuple[str, str]]:
    """[(severity, message)] where severity is 'error' or 'warn'."""
    out: list[tuple[str, str]] = []
    if not urls:
        out.append(("error", "Paste at least one URL."))
    bad = [u for u in urls if not looks_like_url(u)]
    if bad:
        out.append(("warn", f"Doesn't look like a URL: {bad[0]}"))
    if not has_ffmpeg:
        out.append(("warn", "ffmpeg not found - merging video + audio, audio conversion and "
                            "embedding won't work. Set it in Settings."))
    if o.mode == "video" and o.container == "webm" and o.compat:
        out.append(("warn", "'Most compatible' uses H.264/AAC, which WebM can't hold; "
                            "choose MP4 or Automatic."))
    if o.rate_limit.strip() and not re.fullmatch(r"\d+(\.\d+)?[KkMmGg]?", o.rate_limit.strip()):
        out.append(("error", "Rate limit should look like 500K or 2M."))
    if o.playlist_items.strip() and not re.fullmatch(r"[\d\s,:\-]+", o.playlist_items.strip()):
        out.append(("error", "Playlist items should look like 1-5,8,10."))
    if o.cookies_file.strip() and not Path(o.cookies_file.strip()).is_file():
        out.append(("error", "The cookies file doesn't exist."))
    if o.mode == "audio" and o.embed_subs:
        out.append(("warn", "Embedding subtitles only applies to video downloads."))
    try:
        shlex.split(o.extra_args or "")
    except ValueError:
        out.append(("warn", "Extra arguments have unbalanced quotes and will be ignored."))
    return out


# ---------------------------------------------------------------- info dicts

@dataclass
class FormatRow:
    id: str
    kind: str        # "video+audio" | "video" | "audio"
    resolution: str
    fps: str
    vcodec: str
    acodec: str
    ext: str
    bitrate: str
    size: int | None
    note: str
    height: int


def _short_codec(c) -> str:
    return "" if not c or c == "none" else str(c).split(".")[0]


def format_rows(info: dict) -> list[FormatRow]:
    rows: list[tuple[tuple, FormatRow]] = []
    for f in info.get("formats") or []:
        v, a = f.get("vcodec"), f.get("acodec")
        has_v, has_a = v != "none", a != "none"
        if not has_v and not has_a:          # storyboards etc.
            continue
        kind = "video+audio" if has_v and has_a else ("video" if has_v else "audio")
        w, h = f.get("width"), f.get("height")
        if not has_v:
            res = "audio only"
        elif w and h:
            res = f"{w}x{h}"
        else:
            res = f"{h}p" if h else (f.get("resolution") or "")
        tbr = f.get("tbr") or f.get("abr")
        note = ", ".join(x for x in (f.get("format_note"), f.get("language")) if x)
        row = FormatRow(
            id=str(f.get("format_id")), kind=kind, resolution=res,
            fps=f"{f['fps']:g}" if f.get("fps") else "",
            vcodec=_short_codec(v) if has_v else "", acodec=_short_codec(a) if has_a else "",
            ext=f.get("ext") or "", bitrate=f"{tbr:.0f}k" if tbr else "",
            size=f.get("filesize") or f.get("filesize_approx"), note=note, height=h or 0)
        rows.append(((0 if has_v else 1, -(h or 0), -(tbr or 0)), row))
    return [r for _, r in sorted(rows, key=lambda x: x[0])]


@dataclass
class InfoSummary:
    title: str
    subtitle: str
    is_playlist: bool
    count: int


def summarize_info(info: dict) -> InfoSummary:
    is_pl = info.get("_type") == "playlist" or bool(info.get("entries"))
    who = info.get("uploader") or info.get("channel") or ""
    title = info.get("title") or info.get("id") or "(untitled)"
    if is_pl:
        n = info.get("playlist_count") or len(info.get("entries") or [])
        sub = " - ".join(x for x in (who, f"{n} videos") if x)
        return InfoSummary(title, sub, True, int(n or 0))
    date = str(info.get("upload_date") or "")
    if re.fullmatch(r"\d{8}", date):
        date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    else:
        date = ""
    dur = fmt_duration(info.get("duration")) if info.get("duration") else ""
    sub = " - ".join(x for x in (who, dur, date, info.get("extractor_key") or "") if x)
    return InfoSummary(title, sub, False, 1)


# ---------------------------------------------------------------- presets

# Per-download / per-machine values that are not part of a preset.
# Settings about *where/how you connect*, not about quality. A built-in preset leaves
# these alone unless it explicitly sets them; a saved user preset restores them all.
ENV_FIELDS = {"playlist_mode", "playlist_items", "playlist_folder", "out_dir", "template",
              "restrict_filenames", "use_upload_mtime", "archive", "cookies_browser",
              "cookies_file", "rate_limit", "proxy", "fragments", "extra_args"}

PRESET_EXCLUDE = {"format_id", "format_kind", "ffmpeg_location"}

YT_PRESETS: dict[str, dict] = {
    "Best quality (MP4 compatible)": dict(compat=True),
    "1080p max": dict(max_height=1080),
    "720p max (smaller files)": dict(max_height=720, compat=True),
    "Video + subtitles + cover (MKV)": dict(container="mkv", subs=True, embed_subs=True,
                                            embed_thumbnail=True),
    "Audio - MP3 192k": dict(mode="audio", audio_format="mp3", audio_quality="192K"),
    "Audio - best quality (no conversion)": dict(mode="audio", audio_format="best"),
    "Audio - FLAC": dict(mode="audio", audio_format="flac", embed_thumbnail=True),
}
DEFAULT_YT_PRESET = "Best quality (MP4 compatible)"


def preset_values(o: DownloadOptions) -> dict:
    return {k: v for k, v in asdict(o).items() if k not in PRESET_EXCLUDE}

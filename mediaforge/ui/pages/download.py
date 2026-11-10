"""Download: paste links, inspect formats, pick options, queue yt-dlp downloads."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QHBoxLayout, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...core import binaries
from ...core.presets import build_options
from ...core.util import display_cmd, fmt_size
from ...core.ytdlp_builder import (
    AUDIO_FORMATS, AUDIO_QUALITIES, BROWSERS, DEFAULT_YT_PRESET, ENV_FIELDS, LOSSY_AUDIO, PLAYLIST_MODES, RESOLUTIONS,
    SPONSORBLOCK, TEMPLATES, VIDEO_CONTAINERS, YT_PRESETS, DownloadOptions, FormatRow, build_args, build_info_args,
    check_options, format_rows, parse_urls, preset_values, summarize_info,
)
from ...core.ytdlp_runner import InfoSignals, YtDlpJob, start_info_fetch, ytdlp_version
from ..form import F, Form
from ..kit import ActionBar, AdaptiveSplit, Button, Label, Page, Pager, Stack, TextArea, alert, feedback
from ..kit.theme import SPACE, TARGET, css, theme
from ..preset_bar import PresetBar

COLUMNS = ["ID", "Type", "Resolution", "FPS", "Video", "Audio", "Container", "Bitrate", "Size", "Note"]
SPECS = [
    F("mode", "Download", "segmented", (("Video", "video"), ("Audio only", "audio"))),
    F("max_height", "Maximum resolution", "picker", tuple(RESOLUTIONS)),
    F("compat", "Codec preference", "picker", (("Best quality (any codec)", False), ("Most compatible (H.264 + AAC)", True)),
      hint="Most compatible prefers H.264 + AAC in an MP4, which plays almost everywhere."),
    F("container", "Video container", "picker", tuple(VIDEO_CONTAINERS)),
    F("audio_format", "Audio format", "picker", tuple(AUDIO_FORMATS)),
    F("audio_quality", "Audio quality", "picker", tuple(AUDIO_QUALITIES)),
    F("subs", "Download subtitles", "switch"),
    F("auto_subs", "Include auto-generated captions", "switch"),
    F("sub_langs", "Languages", "text", placeholder="en,es    or    en.*    or    all"),
    F("embed_subs", "Embed subtitles in the video", "switch"),
    F("embed_thumbnail", "Embed thumbnail as cover art", "switch"),
    F("embed_metadata", "Embed metadata (title, artist, date)", "switch"),
    F("embed_chapters", "Embed chapters", "switch"),
    F("sponsorblock", "SponsorBlock", "picker", tuple(SPONSORBLOCK), hint="Community data for YouTube. Removing segments re-cuts the file with ffmpeg."),
    F("playlist_mode", "If the link has a playlist", "picker", tuple(PLAYLIST_MODES)),
    F("playlist_items", "Items", "text", placeholder="All    (or for example 1-5,8,10)"),
    F("playlist_folder", "Own numbered folder per playlist", "switch"),
    F("archive", "Skip already downloaded", "path", mode="save", filter="Text (*.txt)", placeholder="Optional: a file that remembers what is done"),
    F("cookies_browser", "Cookies from browser", "picker", (("None", ""), *((b.capitalize(), b) for b in BROWSERS if b)),
      hint="Uses your logged-in session (age-restricted, members-only, private videos)."),
    F("cookies_file", "Cookies file", "path", mode="open", filter="Text (*.txt);;All files (*)", placeholder="Optional - overrides the browser"),
    F("rate_limit", "Speed limit", "text", placeholder="No limit    (for example 2M or 500K)"),
    F("proxy", "Proxy", "text", placeholder="socks5://127.0.0.1:1080"),
    F("fragments", "Parallel fragments", "stepper", lo=1, hi=16, hint="Download several pieces at once (HLS / DASH streams)."),
    F("out_dir", "Save to", "path", mode="dir"),
    F("template", "File name", "edit", tuple(TEMPLATES), hint="yt-dlp template: %(title)s  %(id)s  %(uploader)s  %(ext)s ..."),
    F("restrict_filenames", "Restrict to safe ASCII characters", "switch"),
    F("use_upload_mtime", "Set modified time to the upload date", "switch"),
    F("extra_args", "Extra yt-dlp arguments", "text", placeholder="--write-description"),
]


class DownloadPage(Page):
    notice = Signal(str, str)
    jobs_added = Signal(int)

    def __init__(self, settings, manager, presets, updates) -> None:
        super().__init__("Download", "Save video or audio from links with yt-dlp.")
        self.settings, self.manager, self.updates = settings, manager, updates
        self._rows: list[FormatRow] = []
        self._token, self._pending_url, self._info_url, self._available = 0, "", "", False
        self._info_sig = InfoSignals(self)
        self._info_sig.done.connect(self._on_info)
        self._info_sig.failed.connect(self._on_info_failed)

        self.urls = TextArea("Paste one or more video, playlist or channel links (one per line)")
        self.urls.setMaximumHeight(theme.px(TARGET * 2))
        paste, self.fetch_btn = Button("Paste", "clipboard"), Button("Fetch Info", "search")
        self.version = Label("", "footnote", "label2")
        self.update_btn = Button("", "download", "plain")
        paste.clicked.connect(self._paste)
        self.fetch_btn.clicked.connect(self._fetch)
        self.update_btn.clicked.connect(self._update_ytdlp)
        bar = QHBoxLayout()
        for w in (paste, self.fetch_btn):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(self.version)
        bar.addWidget(self.update_btn)

        self.thumb = QLabel()
        self.thumb.setFixedSize(theme.px(200), theme.px(113))
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet(f"background:{css(theme.p.fill)}; border-radius:{theme.px(10)}px;")
        self.title_lbl = Label("Paste a link and choose Fetch Info to see its details and formats.", "headline", wrap=True)
        self.meta_lbl = Label("", "callout", "label2", wrap=True)
        texts = QVBoxLayout()
        texts.addWidget(self.title_lbl)
        texts.addWidget(self.meta_lbl)
        texts.addStretch(1)
        info = QHBoxLayout()
        info.setSpacing(theme.px(SPACE["l"]))
        info.addWidget(self.thumb)
        info.addLayout(texts, 1)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(theme.px(TARGET))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(theme.px(TARGET * 5))
        self.table.itemSelectionChanged.connect(self.refresh)
        self.hint = Label("", "footnote", "label2", wrap=True)
        auto = Button("Automatic", None, "plain")
        auto.clicked.connect(self.table.clearSelection)
        hint_row = QHBoxLayout()
        hint_row.addWidget(self.hint, 1)
        hint_row.addWidget(auto)
        hint_wrap = QWidget()
        hint_wrap.setLayout(hint_row)
        left = Stack(Stack(self.urls, _row(bar), spacing="s"), _row(info),
                     Stack(Label("Available formats  (optional: select a row to pick one yourself)", "footnote", "label2"),
                           self.table, hint_wrap, spacing="s"), spacing="l")

        self.form = f = Form(DownloadOptions, SPECS)
        self.bar = PresetBar(presets, "ytdlp", YT_PRESETS, lambda: preset_values(self.options()))
        pager = Pager([
            ("Download", Stack(f.group("Source", "", "mode"), f.group("Video", "", "max_height", "compat", "container"),
                               f.group("Audio", "", "audio_format", "audio_quality"))),
            ("Extras", Stack(f.group("Subtitles", "", "subs", "auto_subs", "sub_langs", "embed_subs"),
                             f.group("Embed", "", "embed_thumbnail", "embed_metadata", "embed_chapters"), f.group("SponsorBlock", "", "sponsorblock"))),
            ("Playlist", Stack(f.group("Playlists", "", "playlist_mode", "playlist_items", "playlist_folder"), f.group("History", "", "archive"))),
            ("Network", Stack(f.group("Login", "", "cookies_browser", "cookies_file"), f.group("Connection", "", "rate_limit", "proxy", "fragments"))),
            ("Output", Stack(f.group("Files", "", "out_dir", "template", "restrict_filenames", "use_upload_mtime"), f.group("Advanced", "", "extra_args"))),
        ])
        self.actions = ActionBar("Add to Queue", "download")
        self.actions.primary.clicked.connect(self.add_to_queue)
        self.add(AdaptiveSplit(left, Stack(self.bar, pager, spacing="l"), breakpoint=1100))
        self.add(self.actions)

        f.ctl["out_dir"].setValue(settings.download_dir)
        f.changed.connect(self._on_form)
        self.bar.chosen.connect(self._on_preset)
        self.urls.changed.connect(self.refresh)
        self._update_version()
        self.bar.select(DEFAULT_YT_PRESET)

    def options(self) -> DownloadOptions:
        urls = parse_urls(self.urls.value())
        sel = self._selected_row() if len(urls) == 1 and urls[0] == self._info_url else None
        o = self.form.collect(format_id=sel.id if sel else "", format_kind=sel.kind if sel else "",
                              ffmpeg_location=binaries.find("ffmpeg", self.settings.ffmpeg_path) or "")
        o.out_dir = o.out_dir.strip() or self.settings.download_dir
        return o

    # -- presets
    def _on_form(self, _name: str) -> None:
        self.bar.select_custom()
        self.refresh()

    def _on_preset(self, _name: str, values: dict) -> None:
        o = build_options(DownloadOptions, values)
        # built-ins leave network/output settings alone unless they set them; a saved preset restores everything
        self.form.apply({n: getattr(o, n) for n in self.form.ctl if n in values or n not in ENV_FIELDS})
        self.refresh()

    # -- links and info
    def _paste(self) -> None:
        text = QApplication.clipboard().text().strip()
        if text:
            current = self.urls.value().rstrip()
            self.urls.setValue((current + "\n" if current else "") + text)

    def _fetch(self) -> None:
        urls = parse_urls(self.urls.value())
        if not urls:
            alert(self, "No link", "Paste a link first.")
            return
        self._token += 1
        self._pending_url = urls[0]
        self.fetch_btn.setEnabled(False)
        self.fetch_btn.setText("Fetching...")
        self.title_lbl.setText("Fetching information...")
        self.meta_lbl.setText(urls[0] + ("\n(only the first link is inspected)" if len(urls) > 1 else ""))
        start_info_fetch(build_info_args(self.options()), urls[0], self._info_sig, self._token)

    def _fetch_done(self) -> None:
        self.fetch_btn.setText("Fetch Info")
        self.fetch_btn.setEnabled(self._available)

    def _on_info_failed(self, token: int, message: str) -> None:
        if token != self._token:
            return
        self._fetch_done()
        self._fill_formats([])
        self.thumb.clear()
        self.title_lbl.setText("Couldn't fetch information")
        self.meta_lbl.setText(message[:500])
        self.manager.log.emit(f"Info fetch failed: {message}")
        self.refresh()

    def _on_info(self, token: int, info: dict, thumb) -> None:
        if token != self._token:
            return
        self._fetch_done()
        s = summarize_info(info)
        self.title_lbl.setText(("Playlist: " if s.is_playlist else "") + s.title)
        self.meta_lbl.setText(s.subtitle)
        self._info_url = self._pending_url
        self._fill_formats([] if s.is_playlist else format_rows(info))
        if s.is_playlist:
            self.hint.setText("Playlist: the options on the right apply to every item.")
        pm = QPixmap()
        if thumb and pm.loadFromData(thumb):
            self.thumb.setPixmap(pm.scaled(self.thumb.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self.thumb.clear()
        self.refresh()

    def _fill_formats(self, rows: list) -> None:
        self._rows = rows
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for r in rows:
            i = self.table.rowCount()
            self.table.insertRow(i)
            for col, text in enumerate([r.id, r.kind, r.resolution, r.fps, r.vcodec, r.acodec, r.ext, r.bitrate,
                                        fmt_size(r.size) if r.size else "", r.note]):
                self.table.setItem(i, col, QTableWidgetItem(text))
        self.table.blockSignals(False)

    def _selected_row(self) -> FormatRow | None:
        items = self.table.selectedItems()
        idx = items[0].row() if items else -1
        return self._rows[idx] if 0 <= idx < len(self._rows) else None

    # -- state + preview
    def refresh(self, *_) -> None:
        o, f, urls = self.options(), self.form, parse_urls(self.urls.value())
        audio, specific = o.mode == "audio", bool(o.format_id)
        f.enable("max_height", not audio and not specific)
        f.enable("compat", not audio and not specific)
        f.enable("container", not audio)
        f.enable("audio_format", audio)
        f.enable("audio_quality", audio and o.audio_format in LOSSY_AUDIO)
        f.enable("embed_subs", not audio)
        f.enable("sub_langs", o.subs or o.auto_subs)
        if specific:
            more = " + best audio" if o.mode == "video" and o.format_kind == "video" else ""
            self.hint.setText(f"Using format {o.format_id}{more}. Resolution and codec options are ignored.")
        elif self._rows and len(urls) > 1:
            self.hint.setText("A hand-picked format only applies when a single link is queued.")
        elif self._rows:
            self.hint.setText("Automatic: best quality within your Download options.")
        elif not self.hint.text().startswith("Playlist"):
            self.hint.setText("")
        text = display_cmd(["yt-dlp"] + build_args(o) + (urls[:1] or ["<URL>"]))
        if len(urls) > 1:
            text += f"\n# ...the same options apply to {len(urls) - 1} more link(s)"
        self.actions.set_preview(text)
        issues = check_options(o, urls, bool(o.ffmpeg_location)) if (urls or self.urls.value()) else []
        self.actions.set_warnings([f"{'Error' if s == 'error' else 'Warning'}: {m}" for s, m in issues])

    def refresh_binaries(self) -> None:
        self.refresh()

    # -- yt-dlp install / update (through the update service)
    def _update_version(self) -> None:
        v = ytdlp_version()
        self._available = v is not None
        self.version.setText(f"yt-dlp {v}" if v else "yt-dlp is not installed")
        self.version.setTone("green" if v else "red")
        self.update_btn.setText("Update yt-dlp" if v else "Install yt-dlp")
        self.fetch_btn.setEnabled(self._available)
        self.actions.primary.setEnabled(self._available)

    def _update_ytdlp(self) -> None:
        self.update_btn.setEnabled(False)
        self.update_btn.setText("Working...")
        self.updates.install("ytdlp")

    def on_update_progress(self, key: str, done: int, total: int) -> None:
        if key == "ytdlp" and total:
            self.update_btn.setText(f"Downloading {done * 100 // total}%")

    def on_tool_installed(self, key: str, ok: bool, message: str) -> None:
        if key != "ytdlp":
            return
        self.update_btn.setEnabled(True)
        self._update_version()
        if ok:
            self.notice.emit(message, "success")
        else:
            alert(self, "yt-dlp", f"The install or update failed:\n\n{message}")

    # -- queue
    def add_to_queue(self) -> None:
        urls, o = parse_urls(self.urls.value()), self.options()
        errors = [m for s, m in check_options(o, urls, bool(o.ffmpeg_location)) if s == "error"]
        if errors:
            alert(self, "Check your settings", "\n".join(errors))
            return
        args = build_args(o)
        for url in urls:
            self.manager.add(YtDlpJob(url, args, o.out_dir))
        self.settings.download_dir = o.out_dir
        feedback.confirm()
        self.jobs_added.emit(len(urls))


def _row(layout) -> QWidget:
    w = QWidget()
    w.setLayout(layout)
    return w

"""The yt-dlp tab: paste URLs, inspect formats, choose options, queue downloads."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

from ..core import binaries
from ..core.jobs import JobManager
from ..core.presets import PresetStore, build_options
from ..core.settings import Settings
from ..core.update_service import UpdateService
from ..core.util import display_cmd, fmt_size
from ..core.ytdlp_builder import (
    AUDIO_FORMATS, AUDIO_QUALITIES, BROWSERS, DEFAULT_YT_PRESET, ENV_FIELDS, LOSSY_AUDIO,
    PLAYLIST_MODES, QUALITY_MODES, YT_PRESETS, preset_values,
    RESOLUTIONS, SPONSORBLOCK, TEMPLATES, VIDEO_CONTAINERS, DownloadOptions, FormatRow,
    build_args, build_info_args, check_options, format_rows, parse_urls, summarize_info,
)
from .preset_bar import PresetBar
from .ffmpeg_tab import set_combo
from ..core.ytdlp_runner import InfoSignals, YtDlpJob, start_info_fetch, ytdlp_version

TABLE_COLUMNS = ["ID", "Type", "Resolution", "FPS", "Video", "Audio", "Container", "Bitrate", "Size", "Note"]


def _combo(items, editable: bool = False) -> QComboBox:
    c = QComboBox()
    c.setEditable(editable)
    for label, data in items:
        c.addItem(label, data)
    return c


def _row_widget(*widgets: QWidget) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    for i, x in enumerate(widgets):
        h.addWidget(x, 1 if i == 0 else 0)
    return w


class YtDlpTab(QWidget):
    status_message = Signal(str)
    jobs_added = Signal()

    def __init__(self, settings: Settings, manager: JobManager, presets: PresetStore,
                 updates: UpdateService) -> None:
        super().__init__()
        self.settings = settings
        self.manager = manager
        self.presets = presets
        self.updates = updates
        self._loading = False
        self._rows: list[FormatRow] = []
        self._token = 0
        self._pending_url = ""
        self._info_url = ""        # URL the format table belongs to
        self._available = False
        self._info_sig = InfoSignals(self)
        self._info_sig.done.connect(self._on_info)
        self._info_sig.failed.connect(self._on_info_failed)
        self._build_ui()
        self.outdir.setText(settings.download_dir)
        self._update_version()
        self.preset_bar.select(DEFAULT_YT_PRESET)
        self._refresh()

    # ------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        self.urls = QPlainTextEdit()
        self.urls.setPlaceholderText("Paste one or more video / playlist / channel URLs (one per line)...")
        self.urls.setMaximumHeight(78)

        paste = QPushButton("Paste")
        paste.clicked.connect(self._paste)
        self.fetch_btn = QPushButton("Fetch info")
        self.fetch_btn.clicked.connect(self._fetch)
        self.version_lbl = QLabel()
        self.update_btn = QPushButton()
        self.update_btn.clicked.connect(self._update_ytdlp)
        bar = QHBoxLayout()
        bar.addWidget(paste)
        bar.addWidget(self.fetch_btn)
        bar.addStretch(1)
        bar.addWidget(self.version_lbl)
        bar.addWidget(self.update_btn)

        # left: info + formats
        self.thumb = QLabel()
        self.thumb.setFixedSize(200, 113)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet("background: rgba(128,128,128,40); border-radius: 4px;")
        self.title_lbl = QLabel("Paste a URL and click 'Fetch info' to see titles and available formats.")
        self.title_lbl.setWordWrap(True)
        self.title_lbl.setStyleSheet("font-weight: bold;")
        self.meta_lbl = QLabel()
        self.meta_lbl.setWordWrap(True)
        text = QVBoxLayout()
        text.addWidget(self.title_lbl)
        text.addWidget(self.meta_lbl)
        text.addStretch(1)
        info_row = QHBoxLayout()
        info_row.addWidget(self.thumb)
        info_row.addLayout(text, 1)

        self.formats = QTableWidget(0, len(TABLE_COLUMNS))
        self.formats.setHorizontalHeaderLabels(TABLE_COLUMNS)
        self.formats.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.formats.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.formats.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.formats.verticalHeader().setVisible(False)
        self.formats.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.formats.horizontalHeader().setStretchLastSection(True)
        self.formats.itemSelectionChanged.connect(self._refresh)
        self.format_hint = QLabel()
        self.format_hint.setWordWrap(True)
        auto = QPushButton("Automatic")
        auto.setToolTip("Clear the selection and let the Download options choose the format")
        auto.clicked.connect(self.formats.clearSelection)
        hint_row = QHBoxLayout()
        hint_row.addWidget(self.format_hint, 1)
        hint_row.addWidget(auto)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addLayout(info_row)
        ll.addWidget(QLabel("<b>Available formats</b> (optional - select a row to pick one yourself)"))
        ll.addWidget(self.formats, 1)
        ll.addLayout(hint_row)

        # right: options
        tabs = QTabWidget()
        tabs.addTab(self._download_page(), "Download")
        tabs.addTab(self._extras_page(), "Extras")
        tabs.addTab(self._playlist_page(), "Playlist")
        tabs.addTab(self._network_page(), "Network && Login")
        tabs.addTab(self._output_page(), "Output")

        self.preset_bar = PresetBar(self.presets, "ytdlp", YT_PRESETS, self._preset_values)
        self.preset_bar.chosen.connect(self._on_preset)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("<b>Preset</b>"))
        rl.addWidget(self.preset_bar)
        rl.addWidget(tabs, 1)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        # bottom: preview + queue button
        self.warnings = QLabel()
        self.warnings.setWordWrap(True)
        self.warnings.setStyleSheet("color: #d98e04;")
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(72)
        self.preview.setStyleSheet("font-family: Menlo, Consolas, monospace; font-size: 11px;")
        self.add_btn = QPushButton("Add to queue")
        self.add_btn.setMinimumHeight(36)
        self.add_btn.clicked.connect(self.add_to_queue)

        lay = QVBoxLayout(self)
        lay.addWidget(self.urls)
        lay.addLayout(bar)
        lay.addWidget(split, 1)
        lay.addWidget(QLabel("<b>Command preview</b>"))
        lay.addWidget(self.preview)
        lay.addWidget(self.warnings)
        lay.addWidget(self.add_btn)

        # everything that changes the command refreshes the preview
        self.urls.textChanged.connect(self._refresh)
        for w in (self.mode, self.res, self.quality, self.container, self.afmt, self.aquality,
                  self.subs, self.auto_subs, self.sub_langs, self.embed_subs, self.embed_thumb,
                  self.embed_meta, self.embed_chap, self.sponsor, self.pl_mode, self.pl_items,
                  self.pl_folder, self.archive, self.browser, self.cookies_file, self.rate,
                  self.proxy, self.fragments, self.outdir, self.template, self.restrict,
                  self.upload_mtime, self.extra):
            self._on_change(w)

    def _on_change(self, w: QWidget) -> None:
        if isinstance(w, QComboBox):
            (w.currentTextChanged if w.isEditable() else w.currentIndexChanged).connect(self._user_changed)
        elif isinstance(w, QCheckBox):
            w.toggled.connect(self._user_changed)
        elif isinstance(w, QLineEdit):
            w.textChanged.connect(self._user_changed)
        elif isinstance(w, QSpinBox):
            w.valueChanged.connect(self._user_changed)

    def _user_changed(self, *_) -> None:
        if self._loading:
            return
        self.preset_bar.select_custom()
        self._refresh()

    # ------------------------------------------------------------- presets
    def _preset_values(self) -> dict:
        return preset_values(self._collect())

    def _on_preset(self, name: str, values: dict) -> None:
        o = build_options(DownloadOptions, values)

        def want(field: str) -> bool:       # built-ins don't touch network/output settings
            return field in values or field not in ENV_FIELDS

        self._loading = True
        if want("mode"):
            set_combo(self.mode, o.mode)
        set_combo(self.res, o.max_height)
        set_combo(self.quality, int(o.compat))
        set_combo(self.container, o.container)
        set_combo(self.afmt, o.audio_format)
        set_combo(self.aquality, o.audio_quality)
        for box, val in ((self.subs, o.subs), (self.auto_subs, o.auto_subs), (self.embed_subs, o.embed_subs),
                         (self.embed_thumb, o.embed_thumbnail), (self.embed_meta, o.embed_metadata),
                         (self.embed_chap, o.embed_chapters)):
            box.setChecked(val)
        self.sub_langs.setText(o.sub_langs)
        set_combo(self.sponsor, o.sponsorblock)
        if want("playlist_mode"):
            set_combo(self.pl_mode, o.playlist_mode)
        if want("playlist_items"):
            self.pl_items.setText(o.playlist_items)
        if want("playlist_folder"):
            self.pl_folder.setChecked(o.playlist_folder)
        if want("archive"):
            self.archive.setText(o.archive)
        if want("cookies_browser"):
            set_combo(self.browser, o.cookies_browser)
        if want("cookies_file"):
            self.cookies_file.setText(o.cookies_file)
        if want("rate_limit"):
            self.rate.setText(o.rate_limit)
        if want("proxy"):
            self.proxy.setText(o.proxy)
        if want("fragments"):
            self.fragments.setValue(o.fragments)
        if want("out_dir") and o.out_dir:
            self.outdir.setText(o.out_dir)
        if want("template"):
            self.template.setCurrentText(o.template)
        if want("restrict_filenames"):
            self.restrict.setChecked(o.restrict_filenames)
        if want("use_upload_mtime"):
            self.upload_mtime.setChecked(o.use_upload_mtime)
        if want("extra_args"):
            self.extra.setText(o.extra_args)
        self._loading = False
        self._refresh()

    def _download_page(self) -> QWidget:
        self.mode = _combo([("Video (with audio)", "video"), ("Audio only", "audio")])
        self.res = _combo(RESOLUTIONS)
        self.quality = _combo(QUALITY_MODES)
        self.quality.setToolTip("'Most compatible' prefers H.264 video + AAC audio in an MP4, "
                                "which plays almost everywhere.")
        self.container = _combo(VIDEO_CONTAINERS)
        self.afmt = _combo(AUDIO_FORMATS)
        self.afmt.setCurrentIndex(max(0, self.afmt.findData("mp3")))
        self.aquality = _combo(AUDIO_QUALITIES)
        w = QWidget()
        f = QFormLayout(w)
        f.addRow("Download:", self.mode)
        f.addRow("Max resolution:", self.res)
        f.addRow("Codec preference:", self.quality)
        f.addRow("Video container:", self.container)
        f.addRow("Audio format:", self.afmt)
        f.addRow("Audio quality:", self.aquality)
        return w

    def _extras_page(self) -> QWidget:
        self.subs = QCheckBox("Download subtitles")
        self.auto_subs = QCheckBox("Include auto-generated captions")
        self.sub_langs = QLineEdit("en")
        self.sub_langs.setToolTip("Comma separated, e.g.  en,es   or  en.*   or  all")
        self.embed_subs = QCheckBox("Embed subtitles in the video file")
        self.embed_thumb = QCheckBox("Embed thumbnail as cover art")
        self.embed_meta = QCheckBox("Embed metadata (title, artist, date...)")
        self.embed_meta.setChecked(True)
        self.embed_chap = QCheckBox("Embed chapters")
        self.embed_chap.setChecked(True)
        self.sponsor = _combo(SPONSORBLOCK)
        self.sponsor.setToolTip("SponsorBlock uses community data (YouTube). Removing segments re-cuts the file with ffmpeg.")
        w = QWidget()
        f = QFormLayout(w)
        for c in (self.subs, self.auto_subs):
            f.addRow(c)
        f.addRow("Languages:", self.sub_langs)
        f.addRow(self.embed_subs)
        f.addRow(self.embed_thumb)
        f.addRow(self.embed_meta)
        f.addRow(self.embed_chap)
        f.addRow("SponsorBlock:", self.sponsor)
        return w

    def _playlist_page(self) -> QWidget:
        self.pl_mode = _combo(PLAYLIST_MODES)
        self.pl_items = QLineEdit()
        self.pl_items.setPlaceholderText("all  (or e.g.  1-5,8,10)")
        self.pl_folder = QCheckBox("Put playlists in their own folder, numbered")
        self.archive = QLineEdit()
        self.archive.setPlaceholderText("Optional: file that remembers what's already downloaded")
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._pick_archive)
        w = QWidget()
        f = QFormLayout(w)
        f.addRow("If the URL has a playlist:", self.pl_mode)
        f.addRow("Items:", self.pl_items)
        f.addRow(self.pl_folder)
        f.addRow("Skip already downloaded:", _row_widget(self.archive, browse))
        return w

    def _network_page(self) -> QWidget:
        self.browser = _combo([("None", "")] + [(b.capitalize(), b) for b in BROWSERS if b])
        self.browser.setToolTip("Use your browser's logged-in session (age-restricted, members-only, private videos).")
        self.cookies_file = QLineEdit()
        self.cookies_file.setPlaceholderText("Optional: cookies.txt (overrides the browser choice)")
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._pick_cookies)
        self.rate = QLineEdit()
        self.rate.setPlaceholderText("No limit  (e.g. 2M or 500K)")
        self.proxy = QLineEdit()
        self.proxy.setPlaceholderText("e.g. socks5://127.0.0.1:1080")
        self.fragments = QSpinBox()
        self.fragments.setRange(1, 16)
        self.fragments.setValue(4)
        self.fragments.setToolTip("Download several fragments at once (HLS/DASH). Higher can be faster.")
        w = QWidget()
        f = QFormLayout(w)
        f.addRow("Cookies from browser:", self.browser)
        f.addRow("Cookies file:", _row_widget(self.cookies_file, browse))
        f.addRow("Speed limit:", self.rate)
        f.addRow("Proxy:", self.proxy)
        f.addRow("Parallel fragments:", self.fragments)
        return w

    def _output_page(self) -> QWidget:
        self.outdir = QLineEdit()
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._pick_outdir)
        self.template = _combo([(t, t) for t in TEMPLATES], editable=True)
        self.template.setToolTip("yt-dlp output template. %(title)s, %(id)s, %(uploader)s, %(ext)s ... are filled in.")
        self.restrict = QCheckBox("Restrict file names to safe ASCII characters")
        self.upload_mtime = QCheckBox("Set file modified time to the upload date")
        self.extra = QLineEdit()
        self.extra.setPlaceholderText("Extra yt-dlp arguments, e.g.  --write-description")
        w = QWidget()
        f = QFormLayout(w)
        f.addRow("Save to:", _row_widget(self.outdir, browse))
        f.addRow("File name:", self.template)
        f.addRow(self.restrict)
        f.addRow(self.upload_mtime)
        f.addRow("Extra args:", self.extra)
        return w

    # ------------------------------------------------------------- small actions
    def _paste(self) -> None:
        text = QApplication.clipboard().text().strip()
        if text:
            current = self.urls.toPlainText().rstrip()
            self.urls.setPlainText((current + "\n" if current else "") + text)

    def _pick_outdir(self) -> None:
        p = QFileDialog.getExistingDirectory(self, "Save downloads to", self.outdir.text())
        if p:
            self.outdir.setText(p)

    def _pick_archive(self) -> None:
        p, _ = QFileDialog.getSaveFileName(self, "Download archive file", "archive.txt", "Text (*.txt)")
        if p:
            self.archive.setText(p)

    def _pick_cookies(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Cookies file", "", "Text (*.txt);;All files (*)")
        if p:
            self.cookies_file.setText(p)

    # ------------------------------------------------------------- yt-dlp install / update
    def _update_version(self) -> None:
        v = ytdlp_version()
        self._available = v is not None
        self.version_lbl.setText(f"yt-dlp {v}" if v else "yt-dlp is not installed")
        self.version_lbl.setStyleSheet("color: #2e9e4f;" if v else "color: #d64545;")
        self.update_btn.setText("Update yt-dlp" if v else "Install yt-dlp")
        self.fetch_btn.setEnabled(self._available)
        self.add_btn.setEnabled(self._available)

    def _update_ytdlp(self) -> None:
        """Download the latest official yt-dlp (works from source and from the built .exe)."""
        self.update_btn.setEnabled(False)
        self.update_btn.setText("Working...")
        self.updates.install("ytdlp")

    def on_update_progress(self, key: str, done: int, total: int) -> None:
        if key == "ytdlp" and total:
            self.update_btn.setText(f"Downloading {done * 100 // total}%")

    def on_tool_installed(self, key: str, ok: bool, message: str) -> None:
        """Called by the main window when the update service finishes an install."""
        if key != "ytdlp":
            return
        self.update_btn.setEnabled(True)
        self._update_version()
        if ok:
            QMessageBox.information(self, "yt-dlp", message)
        else:
            QMessageBox.warning(self, "yt-dlp", f"The install/update failed:\n\n{message}")

    # ------------------------------------------------------------- info fetching
    def _fetch(self) -> None:
        urls = parse_urls(self.urls.toPlainText())
        if not urls:
            QMessageBox.information(self, "No URL", "Paste a URL first.")
            return
        self._token += 1
        self._pending_url = urls[0]
        self.fetch_btn.setEnabled(False)
        self.fetch_btn.setText("Fetching...")
        self.title_lbl.setText("Fetching information...")
        self.meta_lbl.setText(urls[0] + ("\n(only the first URL is inspected)" if len(urls) > 1 else ""))
        start_info_fetch(build_info_args(self._collect()), urls[0], self._info_sig, self._token)

    def _fetch_done(self) -> None:
        self.fetch_btn.setText("Fetch info")
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
        self._refresh()

    def _on_info(self, token: int, info: dict, thumb: bytes | None) -> None:
        if token != self._token:
            return
        self._fetch_done()
        s = summarize_info(info)
        self.title_lbl.setText(("Playlist: " if s.is_playlist else "") + s.title)
        self.meta_lbl.setText(s.subtitle)
        self._info_url = self._pending_url
        self._fill_formats([] if s.is_playlist else format_rows(info))
        if s.is_playlist:
            self.format_hint.setText("Playlist: the options on the right apply to every item.")
        pm = QPixmap()
        if thumb and pm.loadFromData(thumb):
            self.thumb.setPixmap(pm.scaled(self.thumb.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
        else:
            self.thumb.clear()
        self._refresh()

    def _fill_formats(self, rows: list[FormatRow]) -> None:
        self._rows = rows
        self.formats.blockSignals(True)
        self.formats.setRowCount(0)
        for r in rows:
            i = self.formats.rowCount()
            self.formats.insertRow(i)
            values = [r.id, r.kind, r.resolution, r.fps, r.vcodec, r.acodec, r.ext, r.bitrate,
                      fmt_size(r.size) if r.size else "", r.note]
            for col, text in enumerate(values):
                self.formats.setItem(i, col, QTableWidgetItem(text))
        self.formats.blockSignals(False)

    def _selected_row(self) -> FormatRow | None:
        items = self.formats.selectedItems()
        if not items:
            return None
        idx = items[0].row()
        return self._rows[idx] if 0 <= idx < len(self._rows) else None

    # ------------------------------------------------------------- options
    def _collect(self) -> DownloadOptions:
        urls = parse_urls(self.urls.toPlainText())
        sel = self._selected_row() if len(urls) == 1 and urls[0] == self._info_url else None
        return DownloadOptions(
            mode=self.mode.currentData(),
            format_id=sel.id if sel else "",
            format_kind=sel.kind if sel else "",
            max_height=self.res.currentData(),
            compat=bool(self.quality.currentData()),
            container=self.container.currentData(),
            audio_format=self.afmt.currentData(),
            audio_quality=self.aquality.currentData(),
            subs=self.subs.isChecked(),
            auto_subs=self.auto_subs.isChecked(),
            sub_langs=self.sub_langs.text(),
            embed_subs=self.embed_subs.isChecked(),
            embed_thumbnail=self.embed_thumb.isChecked(),
            embed_metadata=self.embed_meta.isChecked(),
            embed_chapters=self.embed_chap.isChecked(),
            sponsorblock=self.sponsor.currentData(),
            playlist_mode=self.pl_mode.currentData(),
            playlist_items=self.pl_items.text(),
            playlist_folder=self.pl_folder.isChecked(),
            out_dir=self.outdir.text().strip() or self.settings.download_dir,
            template=self.template.currentText(),
            restrict_filenames=self.restrict.isChecked(),
            use_upload_mtime=self.upload_mtime.isChecked(),
            archive=self.archive.text(),
            cookies_browser=self.browser.currentData() or "",
            cookies_file=self.cookies_file.text(),
            rate_limit=self.rate.text(),
            proxy=self.proxy.text(),
            fragments=self.fragments.value(),
            extra_args=self.extra.text(),
            ffmpeg_location=binaries.find("ffmpeg", self.settings.ffmpeg_path) or "",
        )

    def refresh_binaries(self) -> None:
        self._refresh()

    def _refresh(self, *_) -> None:
        if self._loading:
            return
        o = self._collect()
        urls = parse_urls(self.urls.toPlainText())
        audio = o.mode == "audio"
        specific = bool(o.format_id)
        self.res.setEnabled(not audio and not specific)
        self.quality.setEnabled(not audio and not specific)
        self.container.setEnabled(not audio)
        self.afmt.setEnabled(audio)
        self.aquality.setEnabled(audio and o.audio_format in LOSSY_AUDIO)
        self.embed_subs.setEnabled(not audio)
        self.sub_langs.setEnabled(o.subs or o.auto_subs)

        if specific:
            extra = " + best audio" if o.mode == "video" and o.format_kind == "video" else ""
            self.format_hint.setText(f"Using format {o.format_id}{extra}. Resolution and codec options are ignored.")
        elif self._rows and len(urls) > 1:
            self.format_hint.setText("A hand-picked format only applies when a single URL is queued.")
        elif self._rows:
            self.format_hint.setText("Automatic: best quality within your Download options.")
        elif not self.format_hint.text().startswith("Playlist"):
            self.format_hint.setText("")

        shown = ["yt-dlp"] + build_args(o) + (urls[:1] or ["<URL>"])
        text = display_cmd(shown)
        if len(urls) > 1:
            text += f"\n# ...the same options are applied to {len(urls) - 1} more URL(s)"
        self.preview.setPlainText(text)
        issues = check_options(o, urls, bool(o.ffmpeg_location)) if (urls or self.urls.toPlainText()) else []
        self.warnings.setText("\n".join(f"{'Error' if s == 'error' else 'Warning'}: {m}" for s, m in issues))

    # ------------------------------------------------------------- queue
    def add_to_queue(self) -> None:
        urls = parse_urls(self.urls.toPlainText())
        o = self._collect()
        errors = [m for s, m in check_options(o, urls, bool(o.ffmpeg_location)) if s == "error"]
        if errors:
            QMessageBox.warning(self, "Check your settings", "\n".join(errors))
            return
        args = build_args(o)
        for url in urls:
            self.manager.add(YtDlpJob(url, args, o.out_dir))
        self.settings.download_dir = o.out_dir
        self.status_message.emit(f"Added {len(urls)} download(s) to the queue.")
        self.jobs_added.emit()

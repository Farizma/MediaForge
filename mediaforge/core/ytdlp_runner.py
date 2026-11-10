"""Runs yt-dlp (as a Python library) off the UI thread.

Work happens in daemon threads; results come back to the UI thread through Qt
signals on QObjects that live there (queued connections), so the window never
blocks and quitting the app never waits on a stuck network call.
"""
from __future__ import annotations

import re
import threading
import urllib.request

from PySide6.QtCore import QObject, QTimer, Signal

from .jobs import Job, JobStatus
from .util import display_cmd, fmt_duration, fmt_size

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def ytdlp_version() -> str | None:
    """Installed yt-dlp version, or None if it can't be imported."""
    try:
        from yt_dlp.version import __version__
        return __version__
    except Exception:
        return None


def _parse(yt_dlp, argv: list[str]) -> dict:
    """CLI args -> YoutubeDL options (exactly what the real command line would use)."""
    parsed = yt_dlp.parse_options(argv)
    opts = getattr(parsed, "ydl_opts", None)
    if opts is None:          # very old yt-dlp returned a plain tuple
        opts = parsed[3]
    return dict(opts)


# ------------------------------------------------------------------ info fetch

class InfoSignals(QObject):
    done = Signal(int, object, object)   # token, info dict, thumbnail bytes | None
    failed = Signal(int, str)


def _thumb_url(info: dict) -> str | None:
    if info.get("thumbnail"):
        return info["thumbnail"]
    for e in info.get("entries") or []:
        if isinstance(e, dict):
            if e.get("thumbnail"):
                return e["thumbnail"]
            if e.get("thumbnails"):
                return e["thumbnails"][-1].get("url")
    thumbs = info.get("thumbnails") or []
    return thumbs[-1].get("url") if thumbs else None


def _fetch_bytes(url: str | None) -> bytes | None:
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.read(3_000_000)
    except Exception:
        return None


def _info_worker(args: list[str], url: str, sig: InfoSignals, token: int) -> None:
    try:
        import yt_dlp
    except ImportError:
        sig.failed.emit(token, "yt-dlp is not installed.")
        return
    try:
        opts = _parse(yt_dlp, args + ["--", url])
        opts.update(quiet=True, no_warnings=True, noprogress=True)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            info = ydl.sanitize_info(info) if info else None
    except SystemExit:
        sig.failed.emit(token, "yt-dlp rejected the options.")
        return
    except Exception as exc:
        sig.failed.emit(token, ANSI.sub("", str(exc)).strip())
        return
    if not info:
        sig.failed.emit(token, "No information was returned for this URL.")
        return
    sig.done.emit(token, info, _fetch_bytes(_thumb_url(info)))


def start_info_fetch(args: list[str], url: str, sig: InfoSignals, token: int) -> None:
    threading.Thread(target=_info_worker, args=(args, url, sig, token), daemon=True).start()


# ------------------------------------------------------------------ download

class _Sig(QObject):
    progress = Signal(int, object)           # run_id, dict
    message = Signal(int, str)
    result = Signal(int, str, str, object)   # run_id, outcome(ok|failed|cancelled), message, files


def _reduce(d: dict) -> dict:
    """Keep only plain values the UI needs from a yt-dlp progress-hook dict."""
    info = d.get("info_dict") or {}
    return {
        "status": d.get("status"),
        "filename": d.get("filename") or "",
        "downloaded": d.get("downloaded_bytes"),
        "total": d.get("total_bytes") or d.get("total_bytes_estimate"),
        "speed": d.get("speed"),
        "eta": d.get("eta"),
        "frag_i": d.get("fragment_index"),
        "frag_n": d.get("fragment_count"),
        "id": info.get("id"),
        "title": info.get("title"),
        "n_entries": info.get("n_entries") or info.get("playlist_count"),
        "n_streams": len(info.get("requested_formats") or []) or 1,
    }


def _download_worker(run_id: int, args: list[str], url: str, sig: _Sig,
                     cancel: threading.Event) -> None:
    def finish(outcome: str, msg: str = "", files: list | None = None) -> None:
        sig.result.emit(run_id, outcome, msg, files or [])

    try:
        import yt_dlp
        import yt_dlp.utils
    except ImportError:
        finish("failed", "yt-dlp is not installed - use 'Install yt-dlp' on the yt-dlp tab.")
        return

    cancelled_exc = getattr(yt_dlp.utils, "DownloadCancelled", None)
    if cancelled_exc is None:
        class cancelled_exc(Exception):  # noqa: N801
            pass

    def say(msg) -> None:
        sig.message.emit(run_id, ANSI.sub("", str(msg)))

    class Log:
        def debug(self, msg):
            if cancel.is_set():
                raise cancelled_exc()  # lets us stop even while only extracting info
            say(msg)

        info = debug

        def warning(self, msg):
            say(msg if str(msg).startswith("WARNING") else f"WARNING: {msg}")

        def error(self, msg):
            say(msg if str(msg).startswith("ERROR") else f"ERROR: {msg}")

    files: list[str] = []

    def hook(d):
        if cancel.is_set():
            raise cancelled_exc()
        sig.progress.emit(run_id, _reduce(d))

    def pp_hook(d):
        sig.progress.emit(run_id, {"status": f"pp_{d.get('status')}", "pp": d.get("postprocessor")})

    try:
        opts = _parse(yt_dlp, args + ["--", url])
        opts["progress_hooks"] = list(opts.get("progress_hooks") or []) + [hook]
        opts["postprocessor_hooks"] = list(opts.get("postprocessor_hooks") or []) + [pp_hook]
        opts["post_hooks"] = list(opts.get("post_hooks") or []) + [files.append]
        opts.update(logger=Log(), noprogress=True, consoletitle=False)
        with yt_dlp.YoutubeDL(opts) as ydl:
            code = ydl.download([url])
    except SystemExit:
        finish("failed", "yt-dlp rejected the options - check the command preview.")
        return
    except Exception as exc:
        if cancel.is_set() or isinstance(exc, cancelled_exc):
            finish("cancelled")
        else:
            finish("failed", ANSI.sub("", str(exc)).strip())
        return

    if cancel.is_set():
        finish("cancelled")
    elif code and not files:
        finish("failed", "Download failed - see the Log tab for details.")
    else:
        finish("ok", "Some items failed - see the Log tab." if code else "", files)


class YtDlpJob(Job):
    kind = "yt-dlp"

    def __init__(self, url: str, args: list[str], out_dir: str) -> None:
        super().__init__(url)
        self.url = url
        self.args = list(args)
        self.out_dir = out_dir
        self._run_id = 0
        self._cancel = threading.Event()
        self._sig: _Sig | None = None
        self._thread: threading.Thread | None = None
        self._detached = False
        self._paused_pct = 0.0   # progress to continue from after a pause
        self._reset_tracking()

    def _reset_tracking(self) -> None:
        self._items: list = []        # distinct video ids seen (playlist position)
        self._files: list[str] = []   # distinct streams of the current video
        self._cur_id = object()
        self._cur_title = ""
        self._pct = 0.0

    def open_path(self) -> str | None:
        from pathlib import Path
        return str(Path(self.output_path).parent) if self.output_path else self.out_dir

    # -- saving
    def data(self) -> dict:
        return {"url": self.url, "args": self.args, "out_dir": self.out_dir,
                "output_path": self.output_path}

    @classmethod
    def from_data(cls, title: str, data: dict) -> "YtDlpJob":
        url, args, out = data.get("url"), data.get("args"), data.get("out_dir")
        if not (isinstance(url, str) and url and isinstance(args, list)
                and all(isinstance(a, str) for a in args) and isinstance(out, str)):
            raise ValueError("bad yt-dlp job")
        job = cls(url, args, out)
        job.title = str(title)
        job.output_path = data.get("output_path") or None
        return job

    def restore_state(self, status_value, progress, detail) -> None:
        super().restore_state(status_value, progress, detail)
        if self.status is JobStatus.PAUSED:
            self._paused_pct = self.progress  # yt-dlp continues from the .part file

    # -- lifecycle
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(3)          # let a just-paused worker finish releasing its files
        floor, self._paused_pct = self._paused_pct, 0.0
        self._run_id += 1
        self._detached = False
        self._cancel = threading.Event()
        self._reset_tracking()
        self._pct = floor
        self.set_state(JobStatus.RUNNING, floor, "Resuming..." if floor else "Fetching info...")
        self.log.emit("$ " + display_cmd(["yt-dlp"] + self.args + [self.url]))
        self._sig = _Sig(self)
        self._sig.progress.connect(self._on_progress)
        self._sig.message.connect(self._on_message)
        self._sig.result.connect(self._on_result)
        self._thread = threading.Thread(
            target=_download_worker,
            args=(self._run_id, self.args, self.url, self._sig, self._cancel),
            daemon=True,
        )
        self._thread.start()

    def _pause_running(self) -> None:
        # yt-dlp can't be frozen mid-request, so "pause" stops cleanly and keeps the
        # partial files; Resume starts again and yt-dlp continues from where it stopped.
        self._paused_pct = self._pct
        self._run_id += 1        # ignore anything the old worker still reports
        self._cancel.set()
        self.set_state(JobStatus.PAUSED, detail=f"Paused at {self._pct:.0f}%  |  resumes from the partial file")

    def abort(self) -> None:
        self._cancel.set()

    def _cancel_running(self) -> None:
        self._cancel.set()
        self.set_state(detail="Cancelling...")
        QTimer.singleShot(8000, self._force_cancel)

    def _force_cancel(self) -> None:
        # A thread stuck in a network call can't be interrupted; stop waiting for it.
        if self.status is JobStatus.RUNNING and self._cancel.is_set():
            self._detached = True
            self.set_state(JobStatus.CANCELLED, detail="Cancelled")

    # -- worker callbacks (run on the UI thread)
    def _on_message(self, run_id: int, msg: str) -> None:
        if run_id == self._run_id and not self._detached:
            self.log.emit(msg)

    def _on_progress(self, run_id: int, d: dict) -> None:
        if run_id != self._run_id or self._detached or self._cancel.is_set():
            return
        status = d.get("status", "")
        if status.startswith("pp_"):
            if status != "pp_finished" and d.get("pp"):
                self.set_state(detail=f"Post-processing: {d['pp']}")
            return

        vid = d.get("id")
        if vid != self._cur_id:
            self._cur_id = vid
            if vid not in self._items:
                self._items.append(vid)
            self._files = []
            self._cur_title = d.get("title") or ""
        fn = d.get("filename") or ""
        if fn and fn not in self._files:
            self._files.append(fn)

        n_items = max(int(d.get("n_entries") or 1), len(self._items))
        item_idx = self._items.index(vid) if vid in self._items else 0
        n_streams = max(int(d.get("n_streams") or 1), len(self._files), 1)
        stream_idx = self._files.index(fn) if fn in self._files else 0

        frac = None
        if status == "finished":
            frac = 1.0
        elif d.get("total") and d.get("downloaded") is not None:
            frac = min(1.0, d["downloaded"] / d["total"])
        elif d.get("frag_n") and d.get("frag_i"):
            frac = min(1.0, d["frag_i"] / d["frag_n"])
        if frac is not None:
            overall = (item_idx + (stream_idx + frac) / n_streams) / n_items * 100
            self._pct = max(self._pct, min(99.0, overall))  # never go backwards

        parts = []
        if n_items > 1:
            parts.append(f"{item_idx + 1}/{n_items}")
        if frac is not None:
            parts.append(f"{frac * 100:.0f}%")
        if d.get("speed"):
            parts.append(f"{fmt_size(d['speed'])}/s")
        if d.get("eta") is not None:
            parts.append(f"ETA {fmt_duration(d['eta'])}")
        if self._cur_title:
            self.title = (f"[{item_idx + 1}/{n_items}] " if n_items > 1 else "") + self._cur_title
        self.set_state(progress=self._pct, detail="  |  ".join(parts) or "Downloading...")

    def _on_result(self, run_id: int, outcome: str, message: str, files: list) -> None:
        if run_id != self._run_id or self._detached:
            return
        if outcome == "ok":
            if files:
                self.output_path = files[-1]
            extra = f" ({len(files)} files)" if len(files) > 1 else ""
            self.set_state(JobStatus.DONE, 100.0, (message or "Finished") + extra)
        elif outcome == "cancelled":
            self.set_state(JobStatus.CANCELLED, detail="Cancelled")
        else:
            self.set_state(JobStatus.FAILED, detail=message or "Failed")

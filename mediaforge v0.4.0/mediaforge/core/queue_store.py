"""Save / load the job queue as JSON so it survives closing the app."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .jobs import FFmpegJob, Job, JobStatus
from .ytdlp_runner import YtDlpJob

VERSION = 1
KINDS = {FFmpegJob.kind: FFmpegJob, YtDlpJob.kind: YtDlpJob}


def save(path: str | Path, jobs: list[Job]) -> None:
    """Write every unfinished/failed/cancelled job (finished ones are dropped)."""
    payload = {"version": VERSION,
               "jobs": [j.to_record() for j in jobs if j.status is not JobStatus.DONE]}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".queue-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=1)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load(path: str | Path, ffmpeg_resolver=None) -> list[Job]:
    """Rebuild jobs from a saved file. Bad records are skipped, never fatal.

    ffmpeg_resolver() -> current ffmpeg path; saved ffmpeg commands are re-pointed at it,
    and a record whose command doesn't start with ffmpeg is refused (the file is user data,
    so it must not be able to launch arbitrary programs).
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        records = raw["jobs"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    jobs: list[Job] = []
    for rec in records if isinstance(records, list) else []:
        try:
            cls = KINDS[rec["kind"]]
            data = rec["data"]
            if cls is FFmpegJob:
                cmd = data["cmd"]
                if not os.path.basename(str(cmd[0])).lower().startswith("ffmpeg"):
                    raise ValueError("not an ffmpeg command")
                current = ffmpeg_resolver() if ffmpeg_resolver else None
                if current:
                    cmd[0] = current
            job = cls.from_data(rec["title"], data)
            job.restore_state(rec.get("status", ""), rec.get("progress"), rec.get("detail", ""))
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        jobs.append(job)
    return jobs

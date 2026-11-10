"""Background job engine: a queue of jobs, each running as an external process or thread.

`Job` is the base class. FFmpegJob wraps QProcess; YtDlpJob (ytdlp_runner.py) wraps
a worker thread. The queue UI and manager only talk to the `Job` interface:

    start / pause / resume / cancel / abort + data()/from_data() for saving.
"""
from __future__ import annotations

import itertools
import os
import re
import sys
from collections import deque
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from . import procctl
from .util import display_cmd, fmt_duration


class JobStatus(Enum):
    QUEUED = "Queued"
    RUNNING = "Running"
    PAUSED = "Paused"
    DONE = "Done"
    FAILED = "Failed"
    CANCELLED = "Cancelled"

    @property
    def finished(self) -> bool:
        return self in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED)


class Job(QObject):
    changed = Signal(object)  # job
    log = Signal(str)
    done = Signal(object)     # job reached a finished state (done / failed / cancelled)

    kind = "job"
    _ids = itertools.count(1)

    def __init__(self, title: str, output_path: str | None = None) -> None:
        super().__init__()
        self.id = next(Job._ids)
        self.title = title
        self.output_path = output_path
        self.status = JobStatus.QUEUED
        self.progress = 0.0
        self.detail = ""
        self.attempts = 0  # automatic retries used so far

    def set_state(self, status: JobStatus | None = None,
                  progress: float | None = None, detail: str | None = None) -> None:
        if status is not None:
            self.status = status
        if progress is not None:
            self.progress = progress
        if detail is not None:
            self.detail = detail
        self.changed.emit(self)
        if status is not None and status.finished:
            self.done.emit(self)

    # -- to implement
    def start(self) -> None:
        """Begin running - or continue, if this job was paused."""
        raise NotImplementedError

    def _pause_running(self) -> None:
        self.set_state(detail="Pausing isn't supported for this job")

    def _cancel_running(self) -> None:
        raise NotImplementedError

    def _alive(self) -> bool:
        """True if there is live work (e.g. a suspended process) behind a non-running job."""
        return False

    def abort(self) -> None:
        """App is exiting: stop any live work immediately (state is saved before this)."""

    def data(self) -> dict:
        """Everything (besides title/status) needed to rebuild this job from a saved file."""
        return {}

    @classmethod
    def from_data(cls, title: str, data: dict) -> "Job":
        raise NotImplementedError

    # -- common behaviour
    def pause(self) -> None:
        if self.status is JobStatus.RUNNING:
            self._pause_running()
        elif self.status is JobStatus.QUEUED:
            self.set_state(JobStatus.PAUSED, detail="Paused")

    def resume(self) -> None:
        """Put a paused job back in line; the manager starts it when there is a free slot."""
        if self.status is JobStatus.PAUSED:
            self.set_state(JobStatus.QUEUED, detail="Waiting to resume...")

    def cancel(self) -> None:
        if self.status is JobStatus.RUNNING or (
                self.status in (JobStatus.QUEUED, JobStatus.PAUSED) and self._alive()):
            self._cancel_running()
        elif self.status in (JobStatus.QUEUED, JobStatus.PAUSED):
            self.set_state(JobStatus.CANCELLED, detail="Cancelled")

    def open_path(self) -> str | None:
        """Folder to show for 'Show output folder'."""
        return str(Path(self.output_path).parent) if self.output_path else None

    def reset(self) -> None:
        self.status, self.progress, self.detail = JobStatus.QUEUED, 0.0, ""
        self.changed.emit(self)

    # -- saving / restoring
    def to_record(self) -> dict:
        return {"kind": self.kind, "title": self.title, "status": self.status.value,
                "progress": self.progress, "detail": self.detail, "data": self.data()}

    def restore_state(self, status_value: str, progress, detail: str) -> None:
        """Re-apply saved state. Unfinished work comes back Paused so nothing starts by surprise."""
        try:
            st = JobStatus(status_value)
        except ValueError:
            st = JobStatus.FAILED
        if st is JobStatus.DONE:
            raise ValueError("finished jobs are not restored")
        if st in (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.PAUSED):
            self.status, self.detail = JobStatus.PAUSED, "Restored from last session - press Resume"
        else:
            self.status, self.detail = st, str(detail or "")
        self.progress = float(progress or 0.0)


class FFmpegJob(Job):
    kind = "ffmpeg"

    def __init__(self, title: str, cmd: list[str], duration: float | None = None,
                 output_path: str | None = None) -> None:
        super().__init__(title, output_path)
        self.cmd = list(cmd)
        self.duration = duration
        self._proc: QProcess | None = None
        self._buf = ""
        self._tail: deque[str] = deque(maxlen=15)
        self._cancelled = False
        self._suspended = False
        self._cur = 0.0
        self._speed = ""
        self._existed = False

    # -- saving
    def data(self) -> dict:
        return {"cmd": self.cmd, "duration": self.duration, "output_path": self.output_path}

    @classmethod
    def from_data(cls, title: str, data: dict) -> "FFmpegJob":
        cmd = data.get("cmd")
        if not (isinstance(cmd, list) and cmd and all(isinstance(c, str) for c in cmd)):
            raise ValueError("bad ffmpeg command")
        dur = data.get("duration")
        out = data.get("output_path")
        return cls(str(title), cmd, float(dur) if dur else None, str(out) if out else None)

    # -- lifecycle
    def _alive(self) -> bool:
        return self._proc is not None and self._proc.state() != QProcess.ProcessState.NotRunning

    def start(self) -> None:
        if self._suspended and self._alive():       # continue a paused encode
            procctl.resume(int(self._proc.processId()))
            self._suspended = False
            self.set_state(JobStatus.RUNNING, detail="Resuming...")
            return
        self._cancelled = False
        self._buf, self._cur, self._speed = "", 0.0, ""
        self._tail.clear()
        self._existed = bool(self.output_path and os.path.exists(self.output_path))
        self.set_state(JobStatus.RUNNING, 0.0, "Starting...")
        self.log.emit("$ " + display_cmd(self.cmd))

        args = ["-progress", "pipe:1", "-nostats"] + self.cmd[1:]
        self._proc = QProcess(self)
        self._proc.setProgram(self.cmd[0])
        self._proc.setArguments(args)
        self._proc.readyReadStandardOutput.connect(self._on_stdout)
        self._proc.readyReadStandardError.connect(self._on_stderr)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_error)
        self._proc.start()

    def _pause_running(self) -> None:
        if not self._alive():
            return
        if procctl.suspend(int(self._proc.processId())):
            self._suspended = True
            self.set_state(JobStatus.PAUSED, detail=f"Paused  |  {self.detail}" if self.detail else "Paused")
        else:
            self.set_state(detail="Couldn't pause this process on this system")

    def _cancel_running(self) -> None:
        self._cancelled = True
        self.set_state(detail="Cancelling...")
        if not self._alive():
            return
        if self._suspended:                          # a stopped process can't act on SIGTERM
            procctl.resume(int(self._proc.processId()))
            self._suspended = False
        if sys.platform == "win32":
            self._proc.kill()  # terminate() can't signal console apps on Windows
        else:
            self._proc.terminate()
            QTimer.singleShot(3000, self._force_kill)

    def _force_kill(self) -> None:
        if self._alive():
            self._proc.kill()

    def abort(self) -> None:
        if self._alive():
            self._cancelled = True
            self._proc.kill()
            self._proc.waitForFinished(1500)
            self._remove_partial()

    # -- process callbacks
    def _on_stdout(self) -> None:
        self._buf += bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        *lines, self._buf = self._buf.split("\n")
        for line in lines:
            self._handle_progress(line.strip())

    def _on_stderr(self) -> None:
        text = bytes(self._proc.readAllStandardError()).decode("utf-8", "replace")
        for line in text.replace("\r", "\n").split("\n"):
            if line.strip():
                self._tail.append(line.strip())
                self.log.emit(line.rstrip())

    def _handle_progress(self, line: str) -> None:
        if "=" not in line:
            return
        key, val = line.split("=", 1)
        if key in ("out_time_us", "out_time_ms"):  # both are microseconds
            try:
                self._cur = max(0.0, int(val) / 1_000_000)
            except ValueError:
                pass
        elif key == "speed":
            self._speed = val.strip()
        elif key == "progress":
            self._publish()

    def _publish(self) -> None:
        if self._cancelled or self.status is JobStatus.PAUSED:
            return
        parts = [f"{fmt_duration(self._cur)}"]
        pct = None
        if self.duration:
            pct = min(99.9, self._cur / self.duration * 100)
            parts[0] += f" / {fmt_duration(self.duration)}"
        if self._speed and self._speed != "N/A":
            parts.append(self._speed)
            m = re.match(r"([\d.]+)x", self._speed)
            if m and self.duration and float(m.group(1)) > 0:
                eta = max(0.0, (self.duration - self._cur) / float(m.group(1)))
                parts.append(f"ETA {fmt_duration(eta)}")
        self.set_state(progress=pct, detail="  |  ".join(parts))

    def _on_finished(self, code: int, status: QProcess.ExitStatus) -> None:
        self._suspended = False
        if self._cancelled:
            self._remove_partial()
            self.set_state(JobStatus.CANCELLED, detail="Cancelled")
        elif code == 0 and status == QProcess.ExitStatus.NormalExit:
            self.set_state(JobStatus.DONE, 100.0, "Finished")
        else:
            last = self._tail[-1] if self._tail else f"ffmpeg exited with code {code}"
            self.set_state(JobStatus.FAILED, detail=last)

    def _on_error(self, err: QProcess.ProcessError) -> None:
        if err == QProcess.ProcessError.FailedToStart:
            self.set_state(JobStatus.FAILED, detail="Could not start ffmpeg - check Settings.")

    def _remove_partial(self) -> None:
        if self.output_path and not self._existed and os.path.exists(self.output_path):
            try:
                os.remove(self.output_path)
            except OSError:
                pass


class JobManager(QObject):
    job_added = Signal(object)
    job_changed = Signal(object)
    jobs_cleared = Signal()
    log = Signal(str)

    def __init__(self, max_parallel: int = 1, max_retries: int = 0) -> None:
        super().__init__()
        self.max_parallel = max(1, max_parallel)
        self.max_retries = max(0, max_retries)
        self.jobs: list[Job] = []
        self._pumping = False
        self._again = False
        self._store_path: Path | None = None
        self._save_timer: QTimer | None = None

    # -- queue
    def add(self, job: Job) -> None:
        self.jobs.append(job)
        job.changed.connect(self.job_changed)
        job.changed.connect(self._schedule_save)
        job.log.connect(self.log)
        job.done.connect(self._on_done)
        self.job_added.emit(job)
        self._pump()
        self._schedule_save()

    def _on_done(self, job: Job) -> None:
        if job.status is JobStatus.FAILED and job.attempts < self.max_retries:
            delay = 1.5 * (job.attempts + 1)
            job.set_state(detail=f"{job.detail}  |  retrying in {delay:g}s "
                                 f"({job.attempts + 1}/{self.max_retries})")
            QTimer.singleShot(int(delay * 1000), lambda j=job: self._auto_retry(j))
        self._pump()
        self._schedule_save()

    def _auto_retry(self, job: Job) -> None:
        if job in self.jobs and job.status is JobStatus.FAILED:
            job.attempts += 1
            job.reset()
            self._pump()

    def _pump(self, *_) -> None:
        """Start queued jobs while there is free capacity (re-entrancy safe).
        Paused jobs don't hold a slot, so the next job can run while one is paused."""
        if self._pumping:
            self._again = True
            return
        self._pumping = True
        try:
            while True:
                self._again = False
                running = sum(j.status is JobStatus.RUNNING for j in self.jobs)
                for job in self.jobs:
                    if running >= self.max_parallel:
                        break
                    if job.status is JobStatus.QUEUED:
                        job.start()
                        running += 1
                if not self._again:
                    break
        finally:
            self._pumping = False

    def set_max_parallel(self, n: int) -> None:
        self.max_parallel = max(1, n)
        self._pump()

    # -- user actions
    def pause(self, job: Job) -> None:
        job.pause()
        self._pump()          # its slot is free now

    def resume(self, job: Job) -> None:
        job.resume()
        self._pump()

    def retry(self, job: Job) -> None:
        if job.status in (JobStatus.FAILED, JobStatus.CANCELLED):
            job.attempts = 0
            job.reset()
            self._pump()

    def pause_all(self) -> None:
        for job in self.jobs:
            if job.status in (JobStatus.RUNNING, JobStatus.QUEUED):
                job.pause()
        self._pump()

    def resume_all(self) -> None:
        for job in self.jobs:
            job.resume()
        self._pump()

    def retry_failed(self) -> int:
        failed = [j for j in self.jobs if j.status is JobStatus.FAILED]
        for job in failed:
            job.attempts = 0
            job.reset()
        self._pump()
        return len(failed)

    def cancel_all(self) -> None:
        for job in list(self.jobs):
            job.cancel()

    def active_count(self) -> int:
        """Jobs that are running or waiting to run (paused ones don't count)."""
        return sum(j.status in (JobStatus.QUEUED, JobStatus.RUNNING) for j in self.jobs)

    def clear_finished(self) -> None:
        self.jobs = [j for j in self.jobs if not j.status.finished]
        self.jobs_cleared.emit()
        self._schedule_save()

    # -- saving the queue between sessions
    def attach_store(self, path: str | Path) -> None:
        self._store_path = Path(path)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self.save_now)

    def _schedule_save(self, *_) -> None:
        if self._save_timer is not None and not self._save_timer.isActive():
            self._save_timer.start()

    def save_now(self) -> None:
        if self._store_path is None:
            return
        from . import queue_store
        try:
            queue_store.save(self._store_path, self.jobs)
        except OSError as exc:
            self.log.emit(f"Couldn't save the queue: {exc}")

    def restore(self, ffmpeg_resolver=None) -> int:
        """Load jobs from the last session (paused / failed / cancelled). Returns how many."""
        if self._store_path is None:
            return 0
        from . import queue_store
        jobs = queue_store.load(self._store_path, ffmpeg_resolver)
        for job in jobs:
            self.add(job)
        return len(jobs)

    def shutdown(self, keep: bool = True) -> None:
        """Call as the app exits. keep=True saves the queue first (unfinished jobs come back
        paused next time); keep=False discards it. Either way, live work is stopped."""
        jobs = list(self.jobs)
        if not keep:
            self.jobs = []
        self.save_now()
        for job in jobs:
            job.abort()

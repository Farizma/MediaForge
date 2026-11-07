import json


def _imports():
    try:
        from mediaforge.core import queue_store
        from mediaforge.core.jobs import FFmpegJob, JobStatus
        from mediaforge.core.ytdlp_runner import YtDlpJob
    except ImportError:          # PySide6 not installed: nothing to test here
        return None
    return queue_store, FFmpegJob, JobStatus, YtDlpJob


def test_unfinished_jobs_come_back_paused_and_finished_ones_are_dropped(tmp_path):
    mods = _imports()
    if not mods:
        return
    qs, FFmpegJob, S, YtDlpJob = mods
    running = FFmpegJob("enc", ["/old/ffmpeg", "-i", "a.mp4", "b.mp4"], 12.5, "b.mp4"); running.status = S.RUNNING; running.progress = 40
    failed = FFmpegJob("bad", ["ffmpeg", "-i", "x", "y"]); failed.status = S.FAILED; failed.detail = "boom"
    done = FFmpegJob("ok", ["ffmpeg", "-version"]); done.status = S.DONE
    dl = YtDlpJob("https://x.y/v", ["--ignore-config"], "/out"); dl.title = "My video"; dl.status = S.QUEUED; dl.progress = 33
    path = tmp_path / "q.json"
    qs.save(path, [running, failed, done, dl])

    jobs = {j.title: j for j in qs.load(path, ffmpeg_resolver=lambda: "/new/ffmpeg")}
    assert set(jobs) == {"enc", "bad", "My video"}
    assert jobs["enc"].status is S.PAUSED and jobs["enc"].cmd[0] == "/new/ffmpeg" and jobs["enc"].duration == 12.5
    assert jobs["enc"].progress == 40
    assert jobs["bad"].status is S.FAILED and jobs["bad"].detail == "boom"
    assert jobs["My video"].status is S.PAUSED and jobs["My video"].url == "https://x.y/v"


def test_hostile_or_corrupt_files_are_safe(tmp_path):
    mods = _imports()
    if not mods:
        return
    qs = mods[0]
    path = tmp_path / "q.json"
    path.write_text(json.dumps({"version": 1, "jobs": [
        {"kind": "ffmpeg", "title": "x", "status": "Paused", "data": {"cmd": ["/bin/sh", "-c", "evil"]}},
        {"kind": "ffmpeg", "title": "y", "status": "Paused", "data": {"cmd": "nope"}},
        {"kind": "mystery", "title": "z", "status": "Paused", "data": {}}, 7, {"kind": "yt-dlp"}]}))
    assert qs.load(path) == []
    path.write_text("{{{ not json")
    assert qs.load(path) == []
    assert qs.load(tmp_path / "missing.json") == []

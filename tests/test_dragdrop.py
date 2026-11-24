import os
import tempfile
import time
import uuid
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from mediaforge.core.jobs import FFmpegJob, JobManager, JobStatus as S  # noqa: E402
from mediaforge.ui import dropzone  # noqa: E402
from mediaforge.ui.kit import motion  # noqa: E402

motion.reduced_motion = lambda: True               # fades are short and springs snap


def pump(seconds=0.2):
    end = time.time() + seconds
    while time.time() < end:
        APP.processEvents()
        time.sleep(0.01)


# ----------------------------------------------------------------- what was dragged
def test_classify_files_links_and_text():
    local = QUrl.fromLocalFile(str(Path(tempfile.gettempdir()) / "a.mp4"))
    assert dropzone.classify([local, QUrl("https://x.com/v")]) == ("files", [local.toLocalFile()])
    assert dropzone.classify([QUrl("https://y.com/1"), QUrl("https://y.com/1"), QUrl("ftp://z")]) == ("links", ["https://y.com/1"])
    assert dropzone.classify([], "watch this https://youtu.be/abc please") == ("links", ["https://youtu.be/abc"])
    assert dropzone.classify([], "just words") == (None, [])


def test_expand_folders_to_media_files_only(tmp_path):
    (tmp_path / "sub").mkdir()
    for name in ("b.MP4", "a.mkv", "notes.txt", "sub/c.mp3", "sub/d.jpg"):
        (tmp_path / name).write_bytes(b"x")
    loose = tmp_path / "loose.bin"
    loose.write_bytes(b"x")
    got = dropzone.expand([str(tmp_path), str(loose), str(loose)])
    names = [Path(p).name for p in got]
    assert names == ["a.mkv", "b.MP4", "c.mp3", "loose.bin"], "folders give media files; dropped files pass through once"
    assert dropzone.describe("files", [str(tmp_path), str(loose)]) == "1 file, 1 folder"
    assert dropzone.describe("links", ["a", "b"]) == "2 links"


# ----------------------------------------------------------------- the window
def _window():
    os.environ["APPDATA"] = os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp()
    from mediaforge.core.settings import Settings
    from mediaforge.ui import main_window as mw
    mw.MainWindow._startup_check = lambda self: None
    mw.UpdateService.startup_check = lambda self: None
    w = mw.MainWindow(Settings())
    w.resize(1100, 700)
    w.show()
    pump(0.1)
    return w


def _drag(w, target, mime, pos):
    """An outside drag (no source widget) entering `target`, then moving and dropping on the overlay."""
    actions, btn, mod = Qt.DropAction.CopyAction, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    enter = QDragEnterEvent(QPoint(5, 5), actions, mime, btn, mod)
    QApplication.sendEvent(target, enter)
    assert enter.isAccepted() and w.drop.isVisible(), "the overlay takes over any outside drag"
    QApplication.sendEvent(w.drop, QDragMoveEvent(pos, actions, mime, btn, mod))
    drop = QDropEvent(QPointF(pos), actions, mime, btn, mod)
    QApplication.sendEvent(w.drop, drop)
    pump(0.3)
    return drop


def test_dropping_files_anywhere_goes_to_the_page_under_the_pointer(tmp_path):
    w = _window()
    got = {}
    for key in ("convert", "join"):
        w.pages[key].add_files = lambda paths, k=key: got.setdefault(k, paths)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(clip))])

    w.side.select("queue", animate=False)               # not on Convert / Join: two zones, Convert | Join
    _drag(w, w.pages["queue"], mime, QPoint(w.centralWidget().width() - 60, w.centralWidget().height() // 2))
    assert w.drop.zones == ["convert", "join"] and got == {"join": [str(clip)]}
    assert w.side.current() == "join" and not w.drop.isVisible()

    got.clear()                                          # on Convert: the whole window is Convert
    w.side.select("convert", animate=False)
    _drag(w, w.pages["convert"].files.viewport(), mime, QPoint(w.centralWidget().width() - 60, 80))
    assert w.drop.zones == ["convert"] and got == {"convert": [str(clip)]}
    w.close()


def test_dropping_a_link_fills_the_download_box():
    w = _window()
    mime = QMimeData()
    mime.setUrls([QUrl("https://example.com/watch?v=1")])
    _drag(w, w.pages["log"], mime, QPoint(200, 200))
    assert w.side.current() == "download"
    assert "https://example.com/watch?v=1" in w.pages["download"].urls.value()
    assert w.pages["download"].add_links(["https://example.com/watch?v=1"]) == 0, "no duplicates"
    w.close()


def test_in_app_drags_are_left_alone():
    w = _window()
    mime = QMimeData()
    mime.setUrls([QUrl("https://example.com/v")])

    class Inside(QDragEnterEvent):
        def source(self):
            return w                                     # a drag that started inside MediaForge (list reordering)

    e = Inside(QPoint(5, 5), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(w.pages["log"], e)
    assert not w.drop.isVisible()
    w.close()


# ----------------------------------------------------------------- queue reordering
def test_queue_drag_reorders_waiting_jobs_and_saves(tmp_path):
    from mediaforge.ui.pages.queue import MIME, JobModel
    m = JobManager(max_parallel=1)
    m._pump = lambda *_: None                           # keep them all waiting
    m.attach_store(tmp_path / "queue.json")
    jobs = [FFmpegJob(n, ["ffmpeg", "-version"]) for n in "abcd"]
    for j in jobs:
        m.add(j)
    jobs[3].status = S.DONE
    model = JobModel(m)
    flags = [model.flags(model.index(i)) for i in range(4)]
    assert all(f & Qt.ItemFlag.ItemIsDragEnabled for f in flags[:3]) and not flags[3] & Qt.ItemFlag.ItemIsDragEnabled

    data = model.mimeData([model.index(2)])             # drag "c" to the top
    assert data.hasFormat(MIME)
    model.dropMimeData(data, Qt.DropAction.MoveAction, 0, 0, model.index(-1))
    assert [j.title for j in m.jobs] == ["c", "a", "b", "d"]
    model.move(m.jobs[0], 3)                             # and "c" back down, into the gap before "d"
    assert [j.title for j in m.jobs] == ["a", "b", "c", "d"]
    assert not model.canDropMimeData(data, Qt.DropAction.MoveAction, -1, 0, model.index(1)), "between rows only"
    m.save_now()
    assert (tmp_path / "queue.json").exists()


# ----------------------------------------------------------------- Open with / a second launch
def test_second_launch_hands_its_files_to_the_first():
    from mediaforge.ui.instance import Listener, hand_over
    name = f"mf-test-{uuid.uuid4().hex[:8]}"
    assert not hand_over(["x"], name), "nothing running yet"
    listener, got = Listener(name), []
    listener.opened.connect(got.append)
    assert hand_over([r"C:\Videos\a b.mp4", "/tmp/c.mkv"], name)
    pump(0.5)
    assert got == [[r"C:\Videos\a b.mp4", "/tmp/c.mkv"]]
    assert hand_over([], name)                           # a plain second launch just brings the window forward
    pump(0.5)
    assert got[-1] == []
    listener.server.close()

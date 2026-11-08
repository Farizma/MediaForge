"""UI logic + smoke tests. Needs PySide6 (runs headless via the 'offscreen' platform); skipped without it."""
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication
    APP = QApplication.instance() or QApplication([])
except ImportError:
    APP = None

FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
if APP is not None:                                 # springs snap, so tests see final states
    from mediaforge.ui.kit import motion as _motion
    _motion.reduced_motion = lambda: True


def qt(fn):
    def run(*a, **k):
        if APP is None:
            return
        return fn(*a, **k)
    run.__name__ = fn.__name__
    run.__signature__ = __import__("inspect").signature(fn)
    return run


class Settings:                                     # the few attributes the pages read, as plain Python
    ffmpeg_path = ffprobe_path = output_dir = ""
    download_dir = tempfile.mkdtemp()
    max_parallel, max_retries = 1, 0
    auto_check_updates, auto_install_updates, last_update_check, sound_feedback = False, False, 0.0, False


class Manager:                                      # records what the pages queue
    def __init__(self):
        self.jobs = []

    def add(self, job):
        self.jobs.append(job)

    class _Sig:
        def connect(self, *a): pass
        def emit(self, *a): pass
    log = _Sig()


def media(tmp, name, size="320x180", rate=25, audio=True):
    out = str(Path(tmp) / name)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"testsrc=duration=1:size={size}:rate={rate}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1"]
    subprocess.run(cmd + ["-pix_fmt", "yuv420p", out], check=True)
    return out


class Spy:
    """Replaces a dialog function so tests never block on a modal sheet."""
    def __init__(self):
        self.calls = []

    def __call__(self, *a, **k):
        self.calls.append(a[1:] if a else ())
        return k.get("ret", None)


# ------------------------------------------------------------------ kit
@qt
def test_symbols_are_valid_svg():
    from mediaforge.ui.kit import icons
    for name, body in icons.SYMBOLS.items():
        ET.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg">{body}</svg>')     # raises on a typo
    assert {"play", "pause", "folder", "retry", "check-circle"} <= set(icons.SYMBOLS)


@qt
def test_picker_contract():
    from mediaforge.ui.kit import Picker
    p = Picker((("Original", None), ("720p", 720), ("30 fps", 30), ("Yes", True)))
    hits = []
    p.changed.connect(lambda: hits.append(1))
    assert p.value() is None and p.currentText() == "Original" and p.count() == 4
    p.setValue(720)
    assert p.value() == 720 and p.currentText() == "720p" and hits == [1]
    assert p.findData(30.0) == 2, "30 and 30.0 must match (presets come back from JSON)"
    assert p.findData(1) == -1 and p.findData(True) == 3, "1 must not match True"
    p.setValue(720)
    assert hits == [1], "setting the same value must not re-emit"
    p.addSeparator(); p.addItem("After", "x")
    assert p.itemData(4) == "x" and p.findData("x") == 4, "separators must not shift indices"
    p.setItemEnabled(1, False, "nope")
    p.clear()
    assert p.count() == 0 and p.value() is None


@qt
def test_switch_stepper_field_paths():
    from mediaforge.ui.kit import Field, PathField, Stepper, Switch
    s, hits = Switch(), []
    s.changed.connect(lambda: hits.append(1))
    s.setValue(True)
    assert s.value() is True and hits == [1]
    st = Stepper(0, 63, 23)
    st.setValue(500)
    assert st.value() == 63
    st.setValue(-4)
    assert st.value() == 0
    f = Field(placeholder="x")
    f.setValue(None)
    assert f.value() == ""
    f.setValue(12)
    assert f.value() == "12"
    p = PathField("dir")
    p.setValue("/tmp/x")
    assert p.value() == "/tmp/x"


@qt
def test_form_collect_apply_and_quiet():
    from dataclasses import dataclass
    from mediaforge.ui.form import F, Form

    @dataclass
    class O:
        mode: str = "a"
        n: int = 5
        on: bool = False
        note: str = ""
        extra: str = "keep"

    form = Form(O, [F("mode", "Mode", "picker", (("A", "a"), ("B", "b"))), F("n", "N", "stepper", hi=9),
                    F("on", "On", "switch"), F("note", "Note", "text")])
    seen = []
    form.changed.connect(seen.append)
    form.apply({"mode": "b", "n": 7, "on": True})
    assert seen == [], "programmatic apply must be silent"
    assert form.collect(extra="x") == O("b", 7, True, "", "x")
    form.ctl["mode"].setValue("a")
    assert seen == ["mode"]
    form.enable("n", False)
    assert form.rows["n"].isEnabled() is False


@qt
def test_spring_snaps_when_motion_reduced():
    from mediaforge.ui.kit import motion
    hits = []
    s = motion.Spring(0, on_change=lambda: hits.append(s.value))
    s.to(1.0)
    assert s.value == 1.0 and hits == [1.0]


# ------------------------------------------------------------------ pages
@qt
def test_forms_start_from_the_dataclass_defaults_not_widget_defaults():
    from mediaforge.core.join_builder import JoinOptions
    from mediaforge.ui.pages.join import JoinPage
    o = JoinPage(Settings(), Manager()).options()
    assert o == JoinOptions(), "a fresh Join page must match JoinOptions() (CRF 23, silence on, 48 kHz...)"
    assert o.crf == 23 and o.fill_silence is True and o.sample_rate == 48000


@qt
def test_convert_defaults_container_switch_and_preview():
    from mediaforge.core.ffmpeg_builder import DEFAULT_PRESET, PRESETS
    from mediaforge.core.presets import PresetStore
    from mediaforge.ui.pages.convert import ConvertPage
    page = ConvertPage(Settings(), Manager(), PresetStore(Path(tempfile.mkdtemp()) / "p.json"))
    o = page.options()
    want = PRESETS[DEFAULT_PRESET]
    assert (o.container, o.video_codec, o.crf, o.audio_codec) == (want["container"], want["video_codec"], want["crf"], want["audio_codec"])
    assert page.bar.picker.currentText() == DEFAULT_PRESET
    page.form.ctl["container"].setValue("mp3")                   # a user edit
    o = page.options()
    assert (o.container, o.video_codec, o.audio_codec) == ("mp3", "none", "libmp3lame"), "codecs must follow the container"
    assert page.bar.picker.currentText() == "Custom", "editing must flip the preset to Custom"
    page.form.ctl["container"].setValue("gif")
    assert page.options().audio_codec == "none"
    page.form.ctl["start"].setValue("10"); page.form.ctl["end"].setValue("5")
    assert any("End time" in w for w in __import__("mediaforge.core.ffmpeg_builder", fromlist=["x"]).check_options(page.options()))


@qt
def test_convert_queues_files_without_overwriting():
    if not FFMPEG:
        return
    from mediaforge.core.jobs import FFmpegJob
    from mediaforge.core.presets import PresetStore
    from mediaforge.ui.pages import convert
    tmp = tempfile.mkdtemp()
    a, b = media(tmp, "a.mp4"), media(tmp, "b.mp4")
    m, page = Manager(), None
    page = convert.ConvertPage(Settings(), m, PresetStore(Path(tmp) / "p.json"))
    page.add_files([a, b, a, str(Path(tmp) / "missing.mp4")])            # a duplicate and a missing file are ignored
    assert len(page._paths()) == 2 and "Video:" in page.info.text()
    page.files.setCurrentRow(1)
    assert "b.mp4" in page.actions.cmd.toPlainText() and "a.mp4" not in page.actions.cmd.toPlainText().split("-i")[1], \
        "selecting another file must update the command preview"
    spy = Spy(); convert.alert = spy
    page.add_to_queue()
    assert [type(j) for j in m.jobs] == [FFmpegJob, FFmpegJob] and not spy.calls
    outs = [j.output_path for j in m.jobs]
    assert len(set(outs)) == 2 and all(o.endswith("_converted.mp4") for o in outs) and a not in outs
    page.add_to_queue()                                                    # same again: (1) suffixes would apply only after files exist
    page._clear()
    page.add_to_queue()
    assert spy.calls and "No files" in spy.calls[-1][0]


@qt
def test_join_reorder_sort_and_command():
    if not FFMPEG:
        return
    from mediaforge.core.jobs import FFmpegJob
    from mediaforge.ui.pages import join
    tmp = tempfile.mkdtemp()
    paths = [media(tmp, n, s, r, aud) for n, s, r, aud in (("clip10.mp4", "320x180", 25, True), ("clip2.mp4", "640x360", 30, False), ("clip1.mp4", "320x180", 25, True))]
    m = Manager(); page = join.JoinPage(Settings(), m)
    page.add_files(paths)
    names = lambda: [Path(p).name for p in page._paths()]       # noqa: E731
    assert names() == ["clip10.mp4", "clip2.mp4", "clip1.mp4"]
    page._sort()
    assert names() == ["clip1.mp4", "clip2.mp4", "clip10.mp4"], "natural sort: clip2 before clip10"
    page._reverse()
    assert names() == ["clip10.mp4", "clip2.mp4", "clip1.mp4"]
    page.files.setCurrentRow(2); page._move(-1)
    assert names() == ["clip10.mp4", "clip1.mp4", "clip2.mp4"]
    assert "NO AUDIO" in page.files.item(2).text() and page.files.item(0).text().startswith("1.")
    assert "anullsrc" in page.actions.cmd.toPlainText(), "silence must be generated for the clip without audio"
    spy = Spy(); join.alert = spy
    page.add_to_queue()
    assert len(m.jobs) == 1 and isinstance(m.jobs[0], FFmpegJob) and not spy.calls
    assert m.jobs[0].duration and m.jobs[0].output_path.endswith("joined.mp4")
    page._clear(); page.add_files(paths[:1]); page.add_to_queue()
    assert spy.calls and "Can't join" in spy.calls[-1][0]


@qt
def test_download_presets_respect_network_settings_and_queue():
    from mediaforge.core.presets import PresetStore
    from mediaforge.core.ytdlp_builder import YT_PRESETS
    from mediaforge.ui.pages import download

    class Updates:
        def install(self, key): pass
    m, store = Manager(), PresetStore(Path(tempfile.mkdtemp()) / "p.json")
    page = download.DownloadPage(Settings(), m, store, Updates())
    f = page.form
    assert f.get("fragments") == 4 and f.get("embed_metadata") is True and f.get("out_dir") == Settings.download_dir
    f.ctl["proxy"].setValue("http://p:1"); f.ctl["cookies_browser"].setValue("firefox")
    page.bar.select("720p max (smaller files)")
    assert f.get("max_height") == 720 and f.get("compat") is True
    assert f.get("proxy") == "http://p:1" and f.get("cookies_browser") == "firefox", "a built-in preset must not wipe network settings"
    page.bar.select("Audio - MP3 192k")
    assert f.get("mode") == "audio" and f.get("audio_format") == "mp3" and f.get("audio_quality") == "192K"
    assert f.get("proxy") == "http://p:1"
    page.bar.store.save("ytdlp", "Mine", page.bar.get_values())
    f.ctl["proxy"].setValue("")
    page.bar.select("Mine")
    assert f.get("proxy") == "http://p:1", "a saved preset restores everything it holds"
    assert "format_id" not in page.bar.get_values()

    spy = Spy(); download.alert = spy
    page.urls.setValue("https://a.example/1\nhttps://b.example/2\nhttps://a.example/1")
    assert "yt-dlp" in page.actions.cmd.toPlainText() and "https://a.example/1" in page.actions.cmd.toPlainText()
    page.add_to_queue()
    assert [j.url for j in m.jobs] == ["https://a.example/1", "https://b.example/2"] and not spy.calls
    f.ctl["rate_limit"].setValue("fast")
    page.add_to_queue()
    assert spy.calls and "Check your settings" in spy.calls[-1][0] and len(m.jobs) == 2


@qt
def test_download_selected_format_overrides_quality():
    from mediaforge.core.presets import PresetStore
    from mediaforge.core.ytdlp_builder import FormatRow
    from mediaforge.ui.pages import download

    class Updates:
        def install(self, key): pass
    page = download.DownloadPage(Settings(), Manager(), PresetStore(Path(tempfile.mkdtemp()) / "p.json"), Updates())
    page.urls.setValue("https://x.example/v")
    row = FormatRow("137", "video", "1920x1080", "30", "avc1", "", "mp4", "4000k", None, "", 1080)
    page._info_url, page._rows = "https://x.example/v", [row]
    page._selected_row = lambda: row
    page.refresh()
    assert "137+bestaudio" in page.actions.cmd.toPlainText() and "Using format 137" in page.hint.text()
    assert page.form.rows["max_height"].isEnabled() is False
    page.urls.setValue("https://x.example/v\nhttps://y.example/w")        # two links: a hand-picked format can't apply
    assert "137" not in page.actions.cmd.toPlainText()


@qt
def test_preset_bar_save_replace_delete():
    from mediaforge.core.presets import PresetStore
    from mediaforge.ui import preset_bar
    store = PresetStore(Path(tempfile.mkdtemp()) / "p.json")
    chosen, bar = [], None
    bar = preset_bar.PresetBar(store, "ffmpeg", {"Built-in": {"crf": 20}}, lambda: {"crf": 31})
    bar.chosen.connect(lambda n, v: chosen.append((n, v)))
    preset_bar.prompt = lambda *a, **k: "  My   fast "
    preset_bar.confirm, preset_bar.alert = lambda *a, **k: True, Spy()
    bar._save()
    assert store.get("ffmpeg", "My fast") == {"crf": 31} and bar.picker.currentText() == "\u2605 My fast"
    assert chosen == [], "saving must not re-apply the preset"
    bar.select("Built-in")
    assert chosen[-1] == ("Built-in", {"crf": 20}) and not bar.del_btn.isEnabled()
    bar.select("My fast")
    assert chosen[-1] == ("My fast", {"crf": 31}) and bar.del_btn.isEnabled()
    preset_bar.prompt = lambda *a, **k: "Built-in"
    bar._save()
    assert preset_bar.alert.calls and "built-in" in preset_bar.alert.calls[-1][1].lower(), "built-in names are protected"
    bar.select("My fast")
    bar._delete()
    assert store.names("ffmpeg") == [] and bar.picker.currentText() == "Custom"


@qt
def test_sidebar_selection_badges_and_compact():
    from mediaforge.ui.sidebar import Sidebar
    side = Sidebar([("Tools", [("a", "A", "film"), ("b", "B", "layers")]), ("Activity", [("q", "Queue", "list")])],
                   [("u", "Updates", "refresh")], [])
    nav, acts = [], []
    side.navigate.connect(nav.append); side.action.connect(acts.append)
    side.select("b", animate=False)
    assert side.current() == "b" and nav == ["b"]
    side._step("b", 1)
    assert side.current() == "q" and nav[-1] == "q"
    side._step("q", 1)
    assert side.current() == "q", "stepping past the end stays put"
    side.set_badge("q", 3); side.set_dot("u", True)
    assert side.buttons["q"].badge == 3 and side.buttons["u"].dot
    side.buttons["u"].click()
    assert acts == ["u"] and side.current() == "q", "footer actions don't change the page"


@qt
def test_main_window_builds_navigates_and_paints_every_page():
    tmp = tempfile.mkdtemp()
    for var in ("XDG_DATA_HOME", "APPDATA"):
        os.environ[var] = tmp
    errors = []
    old_hook, sys.excepthook = sys.excepthook, lambda t, v, tb: errors.append(v)
    try:
        from mediaforge.ui.main_window import MainWindow
        win = MainWindow(Settings())
        for key in ("queue", "log", "download", "join", "convert"):
            win.side.select(key, animate=False)
            assert win.stack.currentWidget() is win.pages[key]
            win.pages[key].grab()                                  # runs every paintEvent on the page
        win.side.grab()
        win.pages["queue"].model.rowCount()
        win._on_jobs_added(2)
        win._toast("hello", "info")
        win.resize(700, 600)
        win.resize(1280, 840)
        win.grab()
    finally:
        sys.excepthook = old_hook
    assert not errors, f"exceptions while building/painting: {errors[:3]}"

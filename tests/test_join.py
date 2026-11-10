import shutil
import subprocess

from mediaforge.core.join_builder import (
    Clip, JoinOptions, audio_enabled, build_filter_graph, build_join_command,
    check_join_options, clip_from_media, target_size,
)
from mediaforge.core.probe import MediaInfo, probe

A = Clip("a.mp4", 2.0, 640, 360, "25", True)
B = Clip("b.mp4", 1.5, 1280, 720, "30000/1001", False)
C = Clip("c.mp4", 1.0, 361, 641, "25", True)


def test_target_size_modes():
    assert target_size([A, B], JoinOptions(size_mode="first")) == (640, 360)
    assert target_size([A, B], JoinOptions(size_mode="largest")) == (1280, 720)
    assert target_size([A, B], JoinOptions(size_mode="1920x1080")) == (1920, 1080)
    assert target_size([C], JoinOptions(size_mode="first")) == (360, 640)  # forced even


def test_graph_adds_silence_only_where_missing():
    g = build_filter_graph([A, B], JoinOptions())
    assert "[0:a:0]" in g and "[1:a:0]" not in g
    assert "anullsrc=r=48000:cl=stereo:d=1.500" in g
    assert g.endswith("[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]")


def test_fps_defaults_to_first_clip_exact_fraction():
    g = build_filter_graph([B, A], JoinOptions())
    assert g.count("fps=30000/1001") == 2
    assert build_filter_graph([A, B], JoinOptions(fps=24)).count("fps=24,") == 2


def test_fit_modes():
    assert "pad=640:360" in build_filter_graph([A, B], JoinOptions(fit="pad"))
    assert "crop=640:360" in build_filter_graph([A, B], JoinOptions(fit="crop"))
    g = build_filter_graph([A, B], JoinOptions(fit="stretch"))
    assert "pad=" not in g and "crop=" not in g


def test_silence_off_drops_audio_and_warns():
    o = JoinOptions(fill_silence=False)
    assert not audio_enabled([A, B], o) and audio_enabled([A, A], o)
    cmd = build_join_command("ffmpeg", [A, B], "o.mp4", o)
    assert "[a]" not in cmd and "-c:a" not in cmd
    assert any(sev == "warn" for sev, _ in check_join_options([A, B], o))


def test_loudnorm_and_mono():
    g = build_filter_graph([A, A], JoinOptions(normalize_audio=True, channels=1, sample_rate=44100))
    assert "loudnorm" in g and "channel_layouts=mono" in g and "aresample=44100" in g


def test_errors():
    assert any(s == "error" for s, _ in check_join_options([A], JoinOptions()))
    assert any(s == "error" for s, _ in check_join_options([A, B], JoinOptions(container="webm")))
    assert not [x for x in check_join_options([A, B], JoinOptions()) if x[0] == "error"]


def test_rotated_phone_video_is_swapped():
    info = MediaInfo("p.mp4", duration=3, video={"width": 1920, "height": 1080, "avg_frame_rate": "30/1",
                     "side_data_list": [{"rotation": -90}]}, audio=[{}])
    c = clip_from_media(info)
    assert (c.width, c.height) == (1080, 1920) and c.has_audio


def test_clip_from_media_rejects_audio_only():
    try:
        clip_from_media(MediaInfo("x.mp3", duration=3, video=None, audio=[{}]))
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_real_ffmpeg_join(tmp_path):
    """End-to-end: mixed size / fps / orientation / audio formats / missing audio."""
    ff, fp = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ff or not fp:
        return

    def make(name, size, rate, audio):
        out = str(tmp_path / name)
        cmd = [ff, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
               f"testsrc=duration=2:size={size}:rate={rate}"]
        if audio:
            cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration=2:sample_rate={audio[0]}",
                    "-ac", str(audio[1])]
        cmd += ["-pix_fmt", "yuv420p", out]
        subprocess.run(cmd, check=True)
        return out

    paths = [make("a.mp4", "640x360", 25, (44100, 1)),
             make("b.mp4", "1280x720", 30, None),
             make("c.mp4", "360x640", 24, (48000, 2))]
    clips = [clip_from_media(probe(fp, p)) for p in paths]
    assert [c.has_audio for c in clips] == [True, False, True]

    for mode, size in (("first", (640, 360)), ("largest", (1280, 720)), ("1080x1920", (1080, 1920))):
        dst = str(tmp_path / f"out_{mode}.mp4")
        o = JoinOptions(size_mode=mode, normalize_audio=(mode == "largest"))
        r = subprocess.run(build_join_command(ff, clips, dst, o), capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-800:]
        info = probe(fp, dst)
        assert (info.video["width"], info.video["height"]) == size
        assert len(info.audio) == 1 and info.audio[0]["sample_rate"] == "48000"
        assert abs(info.duration - 6.0) < 0.35, info.duration

    # no-silence mode -> video only
    dst = str(tmp_path / "noaudio.mp4")
    r = subprocess.run(build_join_command(ff, clips, dst, JoinOptions(fill_silence=False)),
                       capture_output=True, text=True)
    assert r.returncode == 0 and not probe(fp, dst).audio

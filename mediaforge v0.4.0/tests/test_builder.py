
import pytest

from mediaforge.core.ffmpeg_builder import (
    PRESETS, EncodeOptions, build_command, check_options, effective_duration,
    make_output_path, parse_time,
)


def cmd(**kw):
    return build_command("ffmpeg", "in.mkv", "out.x", EncodeOptions(**kw))


def pair(c, flag, value):
    i = c.index(flag)
    return c[i + 1] == value


def test_default_mp4():
    c = cmd()
    assert pair(c, "-c:v", "libx264") and pair(c, "-crf", "23") and pair(c, "-c:a", "aac")
    assert "-movflags" in c and c[-1] == "out.x"


def test_trim_uses_fast_seek_and_length():
    c = cmd(start="10", end="0:25")
    assert c.index("-ss") < c.index("-i")
    assert pair(c, "-ss", "10.000") and pair(c, "-t", "15.000")


def test_resolution_and_fps_filters():
    c = cmd(resolution=720, fps=30)
    vf = c[c.index("-vf") + 1]
    assert vf.startswith("fps=30,") and "min(720,ih)" in vf


def test_copy_ignores_filters():
    c = cmd(video_codec="copy", audio_codec="copy", resolution=720)
    assert "-vf" not in c and "-b:a" not in c
    assert any("ignored" in w for w in check_options(EncodeOptions(video_codec="copy", resolution=720)))


def test_audio_only_mp3():
    c = cmd(container="mp3", video_codec="none", audio_codec="libmp3lame", audio_bitrate="192k")
    assert "-vn" in c and pair(c, "-b:a", "192k") and "-map" not in c


def test_flac_has_no_bitrate():
    assert "-b:a" not in cmd(container="flac", video_codec="none", audio_codec="flac")


def test_gif():
    c = cmd(container="gif", fps=12)
    assert "-an" in c and "palettegen" in c[c.index("-vf") + 1] and c[c.index("-vf") + 1].startswith("fps=12,")


def test_hevc_mp4_gets_hvc1_tag():
    assert pair(cmd(video_codec="libx265", crf=28), "-tag:v", "hvc1")
    assert "-tag:v" not in cmd(container="mkv", video_codec="libx265")


def test_extra_args_inserted_before_output():
    c = cmd(extra_args='-metadata title="My Film"')
    assert c[-3:] == ["-metadata", "title=My Film", "out.x"]


def test_mkv_keeps_subtitles():
    assert pair(cmd(container="mkv"), "-c:s", "copy")


@pytest.mark.parametrize("text,expected", [("", None), ("90", 90), ("1:30", 90), ("01:02:03.5", 3723.5)])
def test_parse_time(text, expected):
    assert parse_time(text) == expected


@pytest.mark.parametrize("bad", ["abc", "1:2:3:4", "-5", "nan"])
def test_parse_time_rejects_garbage(bad):
    with pytest.raises(ValueError):
        parse_time(bad)


def test_effective_duration():
    assert effective_duration(100, EncodeOptions()) == 100
    assert effective_duration(100, EncodeOptions(start="10", end="40")) == 30
    assert effective_duration(100, EncodeOptions(start="10", end="500")) == 90
    assert effective_duration(None, EncodeOptions()) is None


def test_output_path_never_overwrites_source(tmp_path):
    src = tmp_path / "a.mp4"
    src.write_text("x")
    out = make_output_path(str(src), "", "", "mp4", overwrite=True)
    assert out != src and out.name == "a (1).mp4"


def test_output_path_batch_clash_and_existing(tmp_path):
    (tmp_path / "a_c.mp4").write_text("x")
    taken: set[str] = set()
    first = make_output_path(str(tmp_path / "a.mkv"), "", "_c", "mp4", False, taken)
    second = make_output_path(str(tmp_path / "a.mov"), "", "_c", "mp4", False, taken)
    assert first.name == "a_c (1).mp4" and second.name == "a_c (2).mp4"


def test_every_preset_builds_without_warnings():
    for name, fields in PRESETS.items():
        assert check_options(EncodeOptions(**fields)) == [], name
        build_command("ffmpeg", "i", "o", EncodeOptions(**fields))


def test_webm_codec_warning():
    assert check_options(EncodeOptions(container="webm", video_codec="libx264"))

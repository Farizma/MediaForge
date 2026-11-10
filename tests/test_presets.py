import json

from mediaforge.core.presets import PresetStore, clean_name, risky_reason


def test_save_get_delete_roundtrip(tmp_path):
    p = tmp_path / "presets.json"
    s = PresetStore(p)
    assert s.names("ffmpeg") == []
    s.save("ffmpeg", "  My   fast\tone ", {"crf": 28, "container": "mp4", "bad": [1, 2], "x": None})
    assert s.names("ffmpeg") == ["My fast one"]
    assert s.get("ffmpeg", "My fast one") == {"crf": 28, "container": "mp4", "x": None}  # list dropped
    reopened = PresetStore(p)
    assert reopened.get("ffmpeg", "My fast one")["crf"] == 28
    assert reopened.delete("ffmpeg", "My fast one") and not reopened.delete("ffmpeg", "nope")
    assert PresetStore(p).names("ffmpeg") == []


def test_kinds_are_separate_and_sorted(tmp_path):
    s = PresetStore(tmp_path / "p.json")
    s.save("ytdlp", "b", {}); s.save("ytdlp", "A", {}); s.save("ffmpeg", "z", {})
    assert s.names("ytdlp") == ["A", "b"] and s.names("ffmpeg") == ["z"]


def test_bad_names_rejected():
    for bad in ("", "   ", "\x00\x01"):
        try:
            clean_name(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
    assert len(clean_name("x" * 200)) == 60


def test_corrupt_file_is_ignored(tmp_path):
    p = tmp_path / "p.json"
    p.write_text("{not json")
    assert PresetStore(p).names("ffmpeg") == []
    p.write_text(json.dumps({"ffmpeg": {"ok": {"crf": 20}, "bad": 5}, "ytdlp": "nope"}))
    s = PresetStore(p)
    assert s.names("ffmpeg") == ["ok"] and s.names("ytdlp") == []


def test_export_import_and_risky_refusal(tmp_path):
    a = PresetStore(tmp_path / "a.json")
    a.save("ffmpeg", "Mine", {"crf": 19})
    a.save("ytdlp", "Safe", {"extra_args": "--write-description"})
    a.save("ytdlp", "Evil", {"extra_args": "--exec 'calc.exe'"})
    a.save("ytdlp", "Evil2", {"extra_args": "--external-downloader=curl"})
    out = tmp_path / "share.json"
    assert a.export_to(out) == 4

    b = PresetStore(tmp_path / "b.json")
    n, skipped = b.import_from(out)
    assert n == 2 and len(skipped) == 2
    assert b.names("ytdlp") == ["Safe"] and b.names("ffmpeg") == ["Mine"]
    assert any("Evil" in s and "--exec" in s for s in skipped)


def test_import_rejects_foreign_files(tmp_path):
    f = tmp_path / "x.json"
    f.write_text(json.dumps({"hello": 1}))
    for path in (f, tmp_path / "missing.json"):
        try:
            PresetStore(tmp_path / "s.json").import_from(path)
        except ValueError:
            continue
        raise AssertionError("should have failed")


def test_risky_reason_only_for_ytdlp():
    assert risky_reason("ffmpeg", {"extra_args": "--exec x"}) is None
    assert risky_reason("ytdlp", {"extra_args": "--no-mtime"}) is None
    assert "--exec" in risky_reason("ytdlp", {"extra_args": "-x --exec=foo"})


def test_listeners_fire_on_change(tmp_path):
    s = PresetStore(tmp_path / "p.json")
    hits = []
    s.on_change(lambda: hits.append(1))
    s.save("ffmpeg", "a", {}); s.delete("ffmpeg", "a")
    assert len(hits) == 2


# ---- how presets map onto the two option classes -------------------------------------
from mediaforge.core.ffmpeg_builder import (  # noqa: E402
    PRESET_FIELDS, PRESETS, EncodeOptions, build_command, preset_values as ff_values,
)
from mediaforge.core.presets import build_options  # noqa: E402
from mediaforge.core.ytdlp_builder import (  # noqa: E402
    ENV_FIELDS, PRESET_EXCLUDE, YT_PRESETS, DownloadOptions, build_args, preset_values as yt_values,
)


def test_build_options_fixes_types_and_ignores_unknown_keys():
    o = build_options(EncodeOptions, {"crf": "30", "resolution": "tall", "fps": 24, "container": 5,
                                      "nonsense": 1, "start": "10"}, PRESET_FIELDS)
    assert o.crf == 30 and o.resolution is None and o.fps == 24
    assert o.container == "5" and o.start == ""            # 'start' isn't a preset field
    y = build_options(DownloadOptions, {"fragments": "x", "subs": 1, "compat": "yes", "max_height": 720.0})
    assert y.fragments == 4 and y.subs is True and y.compat is False and y.max_height == 720


def test_ffmpeg_preset_roundtrip():
    o = EncodeOptions(container="webm", video_codec="libvpx-vp9", crf=31, resolution=720, fps=30,
                      audio_codec="libopus", audio_bitrate="96k", extra_args="-af loudnorm",
                      start="5", end="9")
    saved = ff_values(o)
    assert "start" not in saved and "end" not in saved and saved["extra_args"] == "-af loudnorm"
    back = build_options(EncodeOptions, saved, PRESET_FIELDS)
    assert ff_values(back) == saved


def test_builtin_presets_produce_commands():
    for name, vals in PRESETS.items():
        o = build_options(EncodeOptions, vals, PRESET_FIELDS)
        assert build_command("ffmpeg", "in.mkv", "out.x", o)[0] == "ffmpeg", name


def test_ytdlp_preset_roundtrip_excludes_per_download_fields():
    o = DownloadOptions(format_id="137", format_kind="video", ffmpeg_location="/x/ffmpeg",
                        max_height=720, cookies_browser="firefox", proxy="http://p:1", subs=True)
    saved = yt_values(o)
    assert not (PRESET_EXCLUDE & set(saved))
    back = build_options(DownloadOptions, saved)
    assert back.format_id == "" and back.max_height == 720 and back.cookies_browser == "firefox"
    assert yt_values(back) == saved


def test_builtin_ytdlp_presets_build_args_and_dont_set_env_fields():
    for name, vals in YT_PRESETS.items():
        assert not (ENV_FIELDS & set(vals)), f"{name} would overwrite network/output settings"
        assert build_args(build_options(DownloadOptions, vals))[0] == "--ignore-config", name

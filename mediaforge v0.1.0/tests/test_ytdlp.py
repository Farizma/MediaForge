from mediaforge.core.ytdlp_builder import (
    PLAYLIST_PREFIX, DownloadOptions, build_args, build_info_args, check_options,
    format_rows, format_selector, looks_like_url, parse_urls, summarize_info,
)


def pair(a, flag, value=None):
    i = a.index(flag)
    return value is None or a[i + 1] == value


def test_parse_urls_dedupes_and_splits():
    text = "https://a.example/1\n  https://b.example/2 \nhttps://a.example/1\n"
    assert parse_urls(text) == ["https://a.example/1", "https://b.example/2"]
    assert parse_urls("   ") == []


def test_looks_like_url():
    assert looks_like_url("https://youtu.be/abc") and looks_like_url("http://x.y/z?a=1")
    assert not looks_like_url("hello") and not looks_like_url("www.example.com/x")


def test_default_video_selector():
    assert format_selector(DownloadOptions()) == "bv*+ba/b"
    assert format_selector(DownloadOptions(max_height=720)) == "bv*[height<=720]+ba/b[height<=720]"


def test_compat_selector_prefers_h264_aac_and_mp4():
    o = DownloadOptions(compat=True, max_height=1080)
    sel = format_selector(o)
    assert sel.startswith("bv*[vcodec^=avc1][height<=1080]+ba[acodec^=mp4a]/")
    assert sel.endswith("b[height<=1080]")
    a = build_args(o)
    assert pair(a, "--merge-output-format", "mp4") and pair(a, "--remux-video", "mp4")


def test_specific_format_overrides_quality_settings():
    video_only = DownloadOptions(format_id="137", format_kind="video", max_height=480, compat=True)
    assert format_selector(video_only) == "137+bestaudio/137"
    progressive = DownloadOptions(format_id="22", format_kind="video+audio")
    assert format_selector(progressive) == "22"
    audio_row = DownloadOptions(mode="video", format_id="140", format_kind="audio")
    assert format_selector(audio_row) == "140"


def test_audio_mode():
    a = build_args(DownloadOptions(mode="audio", audio_format="mp3", audio_quality="192K"))
    assert pair(a, "-f", "bestaudio/best") and "-x" in a
    assert pair(a, "--audio-format", "mp3") and pair(a, "--audio-quality", "192K")
    assert "--merge-output-format" not in a


def test_lossless_and_best_audio_skip_quality():
    for fmt in ("flac", "wav", "best"):
        assert "--audio-quality" not in build_args(DownloadOptions(mode="audio", audio_format=fmt))


def test_subtitles_flags():
    a = build_args(DownloadOptions(subs=True, auto_subs=True, sub_langs="en,es", embed_subs=True))
    assert "--write-subs" in a and "--write-auto-subs" in a and "--embed-subs" in a
    assert pair(a, "--sub-langs", "en,es")
    assert "--sub-langs" not in build_args(DownloadOptions())
    audio = build_args(DownloadOptions(mode="audio", subs=True, embed_subs=True))
    assert "--embed-subs" not in audio


def test_sponsorblock_modes():
    assert "--sponsorblock-mark" in build_args(DownloadOptions(sponsorblock="mark"))
    remove = build_args(DownloadOptions(sponsorblock="remove"))
    assert pair(remove, "--sponsorblock-remove", "sponsor,selfpromo,interaction")
    assert not any(x.startswith("--sponsorblock") for x in build_args(DownloadOptions()))


def test_output_and_paths():
    a = build_args(DownloadOptions(out_dir="/tmp/dl", template="%(title)s.%(ext)s", playlist_folder=True))
    assert pair(a, "-P", "/tmp/dl") and pair(a, "-o", PLAYLIST_PREFIX + "%(title)s.%(ext)s")
    assert "--no-mtime" in a
    assert "--no-mtime" not in build_args(DownloadOptions(use_upload_mtime=True))


def test_playlist_options():
    assert "--no-playlist" in build_args(DownloadOptions(playlist_mode="single"))
    assert "--yes-playlist" in build_args(DownloadOptions(playlist_mode="playlist"))
    assert pair(build_args(DownloadOptions(playlist_items="1-3,7")), "--playlist-items", "1-3,7")


def test_network_options():
    a = build_args(DownloadOptions(cookies_browser="firefox", rate_limit="2M", proxy="socks5://h:1", fragments=8))
    assert pair(a, "--cookies-from-browser", "firefox") and pair(a, "-r", "2M")
    assert pair(a, "--proxy", "socks5://h:1") and pair(a, "-N", "8")
    both = build_args(DownloadOptions(cookies_browser="firefox", cookies_file="c.txt"))
    assert "--cookies" in both and "--cookies-from-browser" not in both
    assert "-N" not in build_args(DownloadOptions(fragments=1))


def test_extra_args_and_ffmpeg_location():
    a = build_args(DownloadOptions(extra_args="--write-description --limit-rate '1M'", ffmpeg_location="/usr/bin/ffmpeg"))
    assert a[-3:] == ["--write-description", "--limit-rate", "1M"]
    assert pair(a, "--ffmpeg-location", "/usr/bin/ffmpeg")


def test_info_args_ignore_download_settings():
    a = build_info_args(DownloadOptions(cookies_browser="chrome", playlist_mode="single", format_id="137"))
    assert a[:3] == ["--ignore-config", "--skip-download", "--flat-playlist"]
    assert "--no-playlist" in a and pair(a, "--cookies-from-browser", "chrome") and "-f" not in a


def test_checks():
    sev = lambda issues: {s for s, _ in issues}  # noqa: E731
    assert "error" in sev(check_options(DownloadOptions(), [], True))
    assert not sev(check_options(DownloadOptions(), ["https://x.y/z"], True))
    assert "warn" in sev(check_options(DownloadOptions(), ["https://x.y/z"], False))
    assert "error" in sev(check_options(DownloadOptions(rate_limit="fast"), ["https://x.y/z"], True))
    assert "error" in sev(check_options(DownloadOptions(playlist_items="abc"), ["https://x.y/z"], True))
    assert "error" in sev(check_options(DownloadOptions(cookies_file="/nope/cookies.txt"), ["https://x.y/z"], True))
    assert "warn" in sev(check_options(DownloadOptions(container="webm", compat=True), ["https://x.y/z"], True))


SAMPLE_INFO = {
    "title": "Demo clip", "uploader": "Someone", "duration": 125, "upload_date": "20240131",
    "extractor_key": "Youtube",
    "formats": [
        {"format_id": "sb0", "ext": "mhtml", "vcodec": "none", "acodec": "none", "format_note": "storyboard"},
        {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.2", "abr": 129.5,
         "filesize": 2_000_000, "format_note": "medium", "language": "en"},
        {"format_id": "137", "ext": "mp4", "vcodec": "avc1.640028", "acodec": "none", "width": 1920,
         "height": 1080, "fps": 30, "tbr": 4200.4, "filesize_approx": 90_000_000},
        {"format_id": "22", "ext": "mp4", "vcodec": "avc1.64001F", "acodec": "mp4a.40.2", "width": 1280,
         "height": 720, "fps": 29.97, "tbr": 1500},
        {"format_id": "251", "ext": "webm", "vcodec": "none", "acodec": "opus", "abr": 135},
    ],
}


def test_format_rows_filter_classify_and_sort():
    rows = format_rows(SAMPLE_INFO)
    assert [r.id for r in rows] == ["137", "22", "251", "140"]      # video first, best first; audio by bitrate
    by_id = {r.id: r for r in rows}
    assert by_id["137"].kind == "video" and by_id["137"].vcodec == "avc1" and by_id["137"].resolution == "1920x1080"
    assert by_id["22"].kind == "video+audio" and by_id["22"].fps == "29.97" and by_id["22"].acodec == "mp4a"
    assert by_id["140"].kind == "audio" and by_id["140"].resolution == "audio only" and by_id["140"].note == "medium, en"
    assert by_id["137"].size == 90_000_000 and by_id["137"].bitrate == "4200k"


def test_summarize_single_and_playlist():
    s = summarize_info(SAMPLE_INFO)
    assert not s.is_playlist and s.title == "Demo clip"
    assert s.subtitle == "Someone - 2:05 - 2024-01-31 - Youtube"
    p = summarize_info({"_type": "playlist", "title": "Mix", "uploader": "Me", "entries": [{}, {}, {}]})
    assert p.is_playlist and p.count == 3 and p.subtitle == "Me - 3 videos"


def test_every_option_combo_is_accepted_by_real_ytdlp():
    """Runs only where yt-dlp is installed: the real parser must accept our arguments."""
    try:
        import yt_dlp
    except ImportError:
        return
    variants = [
        DownloadOptions(),
        DownloadOptions(compat=True, max_height=720, container="mkv"),
        DownloadOptions(mode="audio", audio_format="mp3", audio_quality="128K"),
        DownloadOptions(mode="audio", audio_format="flac", embed_thumbnail=True),
        DownloadOptions(format_id="137", format_kind="video", container="mp4"),
        DownloadOptions(subs=True, auto_subs=True, embed_subs=True, sub_langs="en.*"),
        DownloadOptions(sponsorblock="mark"), DownloadOptions(sponsorblock="remove"),
        DownloadOptions(playlist_mode="playlist", playlist_items="1-3,5", playlist_folder=True),
        DownloadOptions(cookies_browser="firefox", rate_limit="1M", proxy="http://localhost:8080",
                        archive="a.txt", restrict_filenames=True, use_upload_mtime=True,
                        out_dir="/tmp/x", ffmpeg_location="/usr/bin/ffmpeg"),
    ]
    for o in variants:
        for args in (build_args(o), build_info_args(o)):
            parsed = yt_dlp.parse_options(args + ["--", "https://example.com/v"])
            opts = getattr(parsed, "ydl_opts", None) or parsed[3]
            assert isinstance(opts, dict) and opts

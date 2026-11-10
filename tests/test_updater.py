import contextlib
import hashlib
import io
import json
import subprocess
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from mediaforge.core import updater as up


# ----------------------------------------------------------------- helpers
@contextlib.contextmanager
def served(routes):
    """Local HTTP server. routes: {"/path": bytes | (status, bytes)}. Yields base URL."""
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            r = routes.get(self.path)
            status, body = (r if isinstance(r, tuple) else (200, r)) if r is not None else (404, b"nope")
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass                       # client cancelled on purpose

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_port}"
    finally:
        srv.shutdown()


@contextlib.contextmanager
def patched(**names):
    old = {k: getattr(up, k) for k in names}
    for k, v in names.items():
        setattr(up, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(up, k, v)


def fake_ytdlp_zipapp(version):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("yt_dlp/__init__.py", f"MARK = 'zipapp-{version}'\n")
        z.writestr("yt_dlp/version.py", f"__version__ = '{version}'\n")
        z.writestr("__main__.py", "print('hi')\n")
    return b"#!/usr/bin/env python3\n" + buf.getvalue()      # real yt-dlp starts with a shebang


def fake_ffmpeg_zip(version="7.1.1", extra=None, banner="ffmpeg version"):
    script = f"#!/bin/sh\necho '{banner} {version}-essentials_build-www.gyan.dev Copyright'\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        top = f"ffmpeg-{version}-essentials_build"
        z.writestr(f"{top}/bin/ffmpeg", script)
        z.writestr(f"{top}/bin/ffprobe", script)
        z.writestr(f"{top}/bin/ffplay", "not wanted")
        z.writestr(f"{top}/LICENSE", "GPL text")
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


def sha(b):
    return hashlib.sha256(b).hexdigest()


def raises(fn, exc=up.UpdateError, contains=""):
    try:
        fn()
    except exc as e:
        assert contains in str(e), str(e)
        return str(e)
    raise AssertionError("expected " + exc.__name__)


# ----------------------------------------------------------------- pure functions
def test_numeric_version_and_is_newer():
    nv = up.numeric_version
    assert nv("7.1.1-essentials_build-www.gyan.dev") == (7, 1, 1) and nv("n7.0") == (7, 0)
    assert nv("2025.01.15") == (2025, 1, 15) and nv("N-118123-gabc") is None and nv(None) is None
    assert up.is_newer("7.1.1", "7.1") and up.is_newer("7.1.2", "7.1.1") and not up.is_newer("7.1", "7.1.0")
    assert up.is_newer("2025.02.01", "2025.01.15") and not up.is_newer("2025.01.15", "2025.01.15")
    assert up.is_newer("7.1.1", None) and up.is_newer("7.1.1", "")           # nothing installed
    assert not up.is_newer("7.1.1", "N-118123-gabc")                         # can't compare dev builds
    assert not up.is_newer("garbage", "7.0") and not up.is_newer(None, "7.0")


def test_ffmpeg_version_string():
    assert up.ffmpeg_version_string("ffmpeg version 7.1.1-essentials_build-www.gyan.dev Copyright") \
        == "7.1.1-essentials_build-www.gyan.dev"
    assert up.ffmpeg_version_string("nothing here") is None


def test_parse_sha256():
    h = "a" * 64
    assert up.parse_sha256(h + "\n") == h
    assert up.parse_sha256(f"{h}  ffmpeg-release-essentials.zip") == h
    sums = f"{'b' * 64}  yt-dlp.exe\n{'c' * 64} *yt-dlp\n{'d' * 64}  yt-dlp_linux\n"
    assert up.parse_sha256(sums, "yt-dlp") == "c" * 64 and up.parse_sha256(sums, "missing") is None
    assert up.parse_sha256("not a hash") is None and up.parse_sha256("") is None


def test_default_data_dir_matches_qt_layout():
    p = up.default_data_dir()
    assert p.parts[-2:] == ("MediaForge", "MediaForge")


def test_plain_http_to_the_internet_is_refused():
    raises(lambda: up.fetch_text("http://example.com/x"), contains="non-HTTPS")


# ----------------------------------------------------------------- downloads
def test_download_progress_and_errors(tmp_path):
    body = b"x" * 300_000
    with served({"/f": body, "/e": (500, b"boom")}) as base:
        seen = []
        dest = tmp_path / "f.bin"
        up.download(base + "/f", dest, lambda d, t: seen.append((d, t)))
        assert dest.read_bytes() == body and seen[-1] == (300_000, 300_000) and len(seen) > 1
        raises(lambda: up.download(base + "/missing", tmp_path / "m"), contains="404")
        raises(lambda: up.download(base + "/e", tmp_path / "e"), contains="500")
        ev = threading.Event(); ev.set()
        raises(lambda: up.download(base + "/f", tmp_path / "c", cancel=ev), exc=up.Cancelled)
    raises(lambda: up.fetch_text("http://127.0.0.1:9/x", timeout=3), contains="Couldn't reach")


# ----------------------------------------------------------------- yt-dlp
def test_ytdlp_install_and_zipapp_really_imports(tmp_path):
    app = fake_ytdlp_zipapp("2099.01.01")
    with served({"/yt-dlp": app, "/SHA2-256SUMS": f"{sha(app)}  yt-dlp\n{'0' * 64}  yt-dlp.exe\n".encode(),
                 "/api": json.dumps({"tag_name": "2099.01.01"}).encode()}) as base:
        with patched(YTDLP_URL=base + "/yt-dlp", YTDLP_SUMS_URL=base + "/SHA2-256SUMS", YTDLP_API=base + "/api"):
            assert up.latest_ytdlp_version() == "2099.01.01"
            assert up.install_ytdlp(tmp_path) == "2099.01.01"
    version, path = up.latest_managed_ytdlp(tmp_path)
    assert version == "2099.01.01" and path.is_file()
    assert not any(p.name.startswith(".dl-") for p in (tmp_path / "yt-dlp").iterdir()), "temp dir left behind"

    # An OLDER copy of yt_dlp sits on the normal path; the downloaded zipapp must win.
    old = tmp_path / "site"; (old / "yt_dlp").mkdir(parents=True)
    (old / "yt_dlp" / "__init__.py").write_text("MARK = 'site-packages-old'\n")
    code = (f"import sys; sys.path.append({str(old)!r}); "
            f"from mediaforge.core import updater as up; "
            f"up.bundled_ytdlp_version = lambda: '2020.01.01'; "
            f"print(up.activate_ytdlp(__import__('pathlib').Path({str(tmp_path)!r}))); "
            f"import yt_dlp; print(yt_dlp.MARK)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=str(Path(__file__).resolve().parents[1])).stdout.split()
    assert out[-1] == "zipapp-2099.01.01", out


def test_ytdlp_not_overridden_when_bundled_copy_is_newer_or_equal(tmp_path):
    d = tmp_path / "yt-dlp" / "2024.05.05"; d.mkdir(parents=True); (d / "yt-dlp").write_bytes(b"x")
    with patched(bundled_ytdlp_version=lambda: "2024.05.05"):
        assert up.activate_ytdlp(tmp_path) is None
    with patched(bundled_ytdlp_version=lambda: "2025.01.01"):
        assert up.activate_ytdlp(tmp_path) is None
    with patched(bundled_ytdlp_version=lambda: "2023.01.01"):
        before = list(sys.path)
        assert up.activate_ytdlp(tmp_path) == str(d / "yt-dlp")
        sys.path[:] = before


def test_ytdlp_bad_checksum_or_missing_sums_installs_nothing(tmp_path):
    app = fake_ytdlp_zipapp("2099.01.01")
    with served({"/yt-dlp": app, "/bad": f"{'0' * 64}  yt-dlp\n".encode(), "/empty": b"\n"}) as base:
        with patched(YTDLP_URL=base + "/yt-dlp", YTDLP_SUMS_URL=base + "/bad"):
            raises(lambda: up.install_ytdlp(tmp_path), contains="checksum")
        with patched(YTDLP_URL=base + "/yt-dlp", YTDLP_SUMS_URL=base + "/empty"):
            raises(lambda: up.install_ytdlp(tmp_path), contains="checksum")
    assert up.latest_managed_ytdlp(tmp_path) is None


def test_ytdlp_rejects_a_file_that_is_not_yt_dlp(tmp_path):
    junk = b"just some bytes"
    with served({"/yt-dlp": junk, "/s": f"{sha(junk)}  yt-dlp\n".encode()}) as base:
        with patched(YTDLP_URL=base + "/yt-dlp", YTDLP_SUMS_URL=base + "/s"):
            raises(lambda: up.install_ytdlp(tmp_path), contains="isn't a yt-dlp")
    assert up.latest_managed_ytdlp(tmp_path) is None


def test_latest_ytdlp_version_bad_replies():
    with served({"/a": b"<html>", "/b": json.dumps({"tag_name": "nightly"}).encode(), "/c": b"[]"}) as base:
        for path in ("/a", "/b", "/c"):
            with patched(YTDLP_API=base + path):
                raises(up.latest_ytdlp_version, contains="unexpected")


# ----------------------------------------------------------------- ffmpeg
def test_ffmpeg_install_end_to_end_and_zip_slip_is_harmless(tmp_path):
    if sys.platform == "win32":
        return                                   # uses shell-script stand-ins for ffmpeg
    evil = {"../../escaped.txt": "pwn", "ffmpeg-7.1.1-essentials_build/bin/../../escaped2.txt": "pwn"}
    z = fake_ffmpeg_zip("7.1.1", evil)
    data = tmp_path / "data"
    with served({"/z": z, "/z.sha256": (sha(z) + "  ffmpeg-release-essentials.zip\n").encode(),
                 "/v": b"7.1.1\n"}) as base:
        with patched(FFMPEG_ZIP_URL=base + "/z", FFMPEG_SHA_URL=base + "/z.sha256", FFMPEG_VERSION_URL=base + "/v"):
            assert up.latest_ffmpeg_version() == "7.1.1"
            seen = []
            assert up.install_ffmpeg(data, lambda d, t: seen.append(d), exe_suffix="") == "7.1.1"
            assert seen and seen[-1] == len(z)
    name, bin_dir = up.latest_managed_ffmpeg(data, "")
    assert name == "7.1.1"
    assert sorted(p.name for p in bin_dir.iterdir()) == ["FFMPEG-LICENSE.txt", "ffmpeg", "ffprobe"]   # no ffplay
    assert not (tmp_path / "escaped.txt").exists() and not (data / "escaped2.txt").exists()
    assert not list(tmp_path.rglob("escaped*")), "zip-slip wrote a file outside the target"
    assert not any(p.name.startswith(".new-") for p in (data / "ffmpeg").iterdir())


def test_ffmpeg_bad_checksum_and_broken_binary_install_nothing(tmp_path):
    if sys.platform == "win32":
        return
    z = fake_ffmpeg_zip("7.1.1")
    broken = fake_ffmpeg_zip("7.1.1", banner="garbage")            # runs, but isn't ffmpeg
    mangled = z[:60] + b"\x00" * 40 + z[100:]                      # corrupt archive that still "passes" its checksum
    with served({"/z": z, "/bad": ("0" * 64).encode(), "/none": b"", "/b": broken,
                 "/bsha": sha(broken).encode(), "/m": mangled, "/msha": sha(mangled).encode()}) as base:
        with patched(FFMPEG_ZIP_URL=base + "/z", FFMPEG_SHA_URL=base + "/bad"):
            raises(lambda: up.install_ffmpeg(tmp_path, exe_suffix=""), contains="checksum")
        with patched(FFMPEG_ZIP_URL=base + "/z", FFMPEG_SHA_URL=base + "/none"):
            raises(lambda: up.install_ffmpeg(tmp_path, exe_suffix=""), contains="checksum")
        with patched(FFMPEG_ZIP_URL=base + "/b", FFMPEG_SHA_URL=base + "/bsha"):
            raises(lambda: up.install_ffmpeg(tmp_path, exe_suffix=""), contains="identify")
        with patched(FFMPEG_ZIP_URL=base + "/m", FFMPEG_SHA_URL=base + "/msha"):
            raises(lambda: up.install_ffmpeg(tmp_path, exe_suffix=""))     # any friendly UpdateError, never a raw OSError
    assert up.latest_managed_ffmpeg(tmp_path, "") is None
    assert not any((tmp_path / "ffmpeg").iterdir()), "staging folder left behind"


def test_ffmpeg_zip_missing_binaries_or_corrupt(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x/bin/ffmpeg", "a")
    (tmp_path / "a.zip").write_bytes(buf.getvalue())
    raises(lambda: up.extract_ffmpeg_zip(tmp_path / "a.zip", tmp_path / "o", ""), contains="ffprobe")
    (tmp_path / "b.zip").write_bytes(b"not a zip")
    raises(lambda: up.extract_ffmpeg_zip(tmp_path / "b.zip", tmp_path / "o2", ""), contains="damaged")


def test_ffmpeg_install_refused_off_windows():
    if sys.platform != "win32":
        raises(lambda: up.install_ffmpeg(Path("/nonexistent")), contains="Windows-only")


# ----------------------------------------------------------------- housekeeping
def test_latest_managed_picks_highest_and_cleanup_keeps_two(tmp_path):
    for v in ("6.0", "7.0", "7.1.1", "7.1"):
        b = tmp_path / "ffmpeg" / v / "bin"; b.mkdir(parents=True); (b / "ffmpeg").write_text("x")
    (tmp_path / "ffmpeg" / ".new-abc").mkdir()
    (tmp_path / "ffmpeg" / "8.0").mkdir()                    # no binary inside -> ignored
    for v in ("2024.01.01", "2025.03.03", "2025.01.01"):
        d = tmp_path / "yt-dlp" / v; d.mkdir(parents=True); (d / "yt-dlp").write_text("x")
    assert up.latest_managed_ffmpeg(tmp_path, "")[0] == "7.1.1"
    assert up.latest_managed_ytdlp(tmp_path)[0] == "2025.03.03"
    up.cleanup_old(tmp_path, keep=2)
    assert sorted(p.name for p in (tmp_path / "ffmpeg").iterdir()) == ["7.1", "7.1.1", ] or \
        sorted(p.name for p in (tmp_path / "ffmpeg").iterdir()) == ["7.1.1", "8.0"]
    assert sorted(p.name for p in (tmp_path / "yt-dlp").iterdir()) == ["2025.01.01", "2025.03.03"]


# ----------------------------------------------------------------- MediaForge itself
def _release(base, version="1.2.0", sha=True, name=None):
    name = name or f"MediaForge_setup_v{version}.exe"
    assets = [{"name": name, "browser_download_url": f"{base}/dl/{name}"}]
    if sha:
        assets.append({"name": name + ".sha256", "browser_download_url": f"{base}/dl/{name}.sha256"})
    return {"tag_name": f"v{version}", "assets": assets}


def test_pick_app_release_fails_closed():
    base = "https://github.com/Farizma/MediaForge/releases/download/v1.2.0"
    rel = up.pick_app_release(_release(base))
    assert (rel.version, rel.name) == ("1.2.0", "MediaForge_setup_v1.2.0.exe")
    for bad, why in ((_release(base, sha=False), "checksum"), (_release("https://evil.example"), "unexpected"),
                     (_release(base, name="MediaForge_setup_v1.1.0.exe"), "no Windows installer"),
                     ({"tag_name": "latest", "assets": []}, "version"), ([], "unexpected")):
        try:
            up.pick_app_release(bad)
        except up.UpdateError as exc:
            assert why in str(exc), (why, exc)
        else:
            raise AssertionError(f"accepted a release with {why} problem")


def test_app_installer_download_is_verified(tmp_path):
    body = b"MZ fake installer"
    good = hashlib.sha256(body).hexdigest()
    name = "MediaForge_setup_v1.2.0.exe"
    for i, (sums, ok) in enumerate(((f"{good}  {name}\n", True), ("0" * 64 + f"  {name}\n", False), ("not a hash", False))):
        data = tmp_path / str(i)
        with served({f"/dl/{name}": body, f"/dl/{name}.sha256": sums.encode()}) as base:
            with patched(APP_DOWNLOAD_PREFIX=base + "/dl/"):
                rel = up.pick_app_release(_release(base))
                try:
                    path = up.download_app_installer(data, rel)
                except up.UpdateError:
                    assert not ok
                    assert not list(up.app_update_dir(data).glob("*")), "a failed download must leave nothing to run"
                else:
                    assert ok and path.read_bytes() == body
    up.cleanup_app_update(tmp_path / "0")
    assert not up.app_update_dir(tmp_path / "0").exists()


def test_auto_install_never_updates_mediaforge_itself(tmp_path):
    from types import SimpleNamespace
    from mediaforge.core.update_service import UpdateService
    svc = UpdateService(SimpleNamespace(auto_install_updates=True, last_update_check=0), tmp_path)
    started = []
    svc.install = started.append
    svc._auto = True
    svc._after_check({"app": up.ToolStatus("app", "MediaForge", installed="1.0.0", latest="1.1.0", update_available=True),
                      "ytdlp": up.ToolStatus("ytdlp", "yt-dlp", installed="2025.1.1", latest="2026.1.1", update_available=True)})
    assert started == ["ytdlp"], "MediaForge must ask before it closes to update"

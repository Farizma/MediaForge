import importlib.util
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location("build_exe", ROOT / "tools" / "build_exe.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_version_is_read_from_the_package():
    be = load()
    assert be.app_version() == __import__("re").search(r'"([^"]+)"', (ROOT / "mediaforge" / "__init__.py").read_text()).group(1)


def _fake_tree(tmp, onefile):
    (tmp / "README.md").write_text("readme")
    dist = tmp / "dist"; dist.mkdir()
    exe = "MediaForge.exe" if sys.platform == "win32" else "MediaForge"
    if onefile:
        (dist / exe).write_text("EXE")
    else:
        (dist / "MediaForge").mkdir(); (dist / "MediaForge" / exe).write_text("EXE")
        (dist / "MediaForge" / "_internal").mkdir(); (dist / "MediaForge" / "_internal" / "lib.dll").write_text("x")
    bin_ = tmp / "bin"; bin_.mkdir()
    (bin_ / "ffmpeg.exe").write_text("ff"); (bin_ / "FFMPEG-LICENSE.txt").write_text("gpl")
    return dist, bin_, exe


def _package(tmp, onefile, with_ffmpeg):
    be = load()
    be.ROOT, be.DIST, be.BIN = tmp, tmp / "dist", tmp / "bin"
    be.app_version = lambda: "9.9.9"
    return be.package(onefile, with_ffmpeg)


def test_package_folder_build_includes_ffmpeg_next_to_the_exe(tmp_path):
    _, _, exe = _fake_tree(tmp_path, onefile=False)
    names = set(zipfile.ZipFile(_package(tmp_path, False, True)).namelist())
    assert zipfile.ZipFile(next((tmp_path / "dist").glob("*.zip"))).filename.endswith("MediaForge-9.9.9-" + ("win64.zip" if sys.platform == "win32" else sys.platform + ".zip"))
    assert f"MediaForge/{exe}" in names and "MediaForge/bin/ffmpeg.exe" in names
    assert "MediaForge/bin/FFMPEG-LICENSE.txt" in names and "MediaForge/README.md" in names
    assert "MediaForge/_internal/lib.dll" in names


def test_package_without_ffmpeg_and_onefile_layout(tmp_path):
    _, _, exe = _fake_tree(tmp_path, onefile=True)
    names = set(zipfile.ZipFile(_package(tmp_path, True, False)).namelist())
    assert f"MediaForge/{exe}" in names and not any("/bin/" in n for n in names)


def test_record_versions_writes_json_the_updater_can_read(tmp_path):
    be = load()
    be.ROOT = tmp_path
    be.subprocess.check_output = lambda *a, **k: "2025.01.15\n"
    be.record_versions(Path("python"), "7.1.1-essentials_build")
    data = json.loads((tmp_path / "assets" / "bundled_versions.json").read_text())
    assert data == {"yt-dlp": "2025.01.15", "ffmpeg": "7.1.1-essentials_build"}


def test_check_mode_runs_and_reports(tmp_path):
    be = load()
    code = be.check()
    assert code in (0, 1)


def test_bat_file_has_windows_line_endings_and_calls_the_script():
    data = (ROOT / "BUILD_EXE.bat").read_bytes()
    assert data.count(b"\n") == data.count(b"\r\n"), "bare LF found: batch labels can break"
    assert b"tools\\build_exe.py" in data and b"winget" in data


def test_installer_name_matches_what_the_app_updater_looks_for(tmp_path):
    be = load()
    from mediaforge.core import updater
    name = be.installer_name("1.0.0")
    assert name == "MediaForge_setup_v1.0.0.exe" and updater.INSTALLER_RE.match(name)
    exe = tmp_path / name
    exe.write_bytes(b"MZ setup")
    sums = be.write_checksum(exe).read_text()
    assert updater.parse_sha256(sums, name) == updater.sha256_file(exe)
    iss = (ROOT / "packaging" / "installer.iss").read_text()
    assert "OutputBaseFilename=MediaForge_setup_v{#MyAppVersion}" in iss, "the .iss and build_exe.py must agree on the name"

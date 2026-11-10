#!/usr/bin/env python3
"""Builds MediaForge into a Windows program. Normally started by double-clicking BUILD_EXE.bat.

What it does (nothing here needs admin rights):
  1. makes a private build environment (.venv-build) and installs the dependencies + PyInstaller
  2. downloads ffmpeg into .\\bin   (skip with --no-ffmpeg)
  3. records the bundled yt-dlp / ffmpeg versions (the in-app updater compares against these)
  4. runs PyInstaller
  5. zips the result -> dist\\MediaForge-<version>-win64.zip
     (and dist\\MediaForge_setup_v<version>.exe + .sha256 with --installer)

Options: --onefile   one MediaForge.exe instead of a folder (slower to start)
         --no-ffmpeg don't bundle ffmpeg      --installer  also build Setup.exe (needs Inno Setup 6)
         --check     only verify the prerequisites      --clean  delete build leftovers first
Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mediaforge.core import updater  # noqa: E402  (standard-library-only module)

IS_WIN = sys.platform == "win32"
BUILD_VENV = ROOT / ".venv-build"
BIN = ROOT / "bin"
DIST = ROOT / "dist"


def step(msg: str) -> None:
    print(f"\n==> {msg}", flush=True)


def run(cmd, **kw) -> None:
    print("   $ " + " ".join(f'"{c}"' if " " in str(c) else str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, cwd=str(ROOT), **kw)


def venv_python() -> Path:
    return BUILD_VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")


def app_version() -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "mediaforge" / "__init__.py").read_text())
    return m.group(1) if m else "0.0.0"


def find_iscc() -> str | None:
    found = shutil.which("iscc")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        for sub in ("Inno Setup 6", "Programs/Inno Setup 6"):
            if base and (Path(base) / sub / "ISCC.exe").exists():
                return str(Path(base) / sub / "ISCC.exe")
    return None


def reachable(url: str) -> bool:
    try:
        urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers={"User-Agent": "MediaForge-build"}), timeout=10)
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ --check
def check() -> int:
    problems = 0

    def line(ok: bool, text: str, fatal: bool = True) -> None:
        nonlocal problems
        print(f"  [{'OK' if ok else ('FAIL' if fatal else 'warn')}] {text}")
        if not ok and fatal:
            problems += 1

    print("MediaForge build prerequisites")
    line(sys.version_info >= (3, 10), f"Python {sys.version.split()[0]} (needs 3.10+)")
    line(IS_WIN, f"Platform: {sys.platform}" + ("" if IS_WIN else "  - PyInstaller builds for the OS it runs on, "
                                                  "so this would NOT produce a Windows .exe"), fatal=False)
    try:
        import ensurepip  # noqa: F401
        line(True, "venv + ensurepip available")
    except ImportError:
        line(False, "the 'venv'/'ensurepip' module is missing (Debian/Ubuntu: sudo apt install python3-venv)")
    for rel in ("main.py", "requirements.txt", "packaging/mediaforge.spec", "mediaforge/__init__.py"):
        line((ROOT / rel).exists(), f"found {rel}")
    line((ROOT / "assets" / "icon.ico").exists() or (ROOT / "tools" / "make_icon.py").exists(), "icon (or its generator)")
    for name, url in (("PyPI", "https://pypi.org/simple/pip/"), ("ffmpeg download (gyan.dev)", updater.FFMPEG_VERSION_URL)):
        line(reachable(url), f"internet: {name}", fatal=False)
    print("\nAll good." if not problems else f"\n{problems} problem(s) found.")
    return 1 if problems else 0


# ------------------------------------------------------------------ build steps
def prepare_env() -> Path:
    step("Preparing the build environment (.venv-build)")
    py = venv_python()
    if not py.exists():
        venv.EnvBuilder(with_pip=True, symlinks=not IS_WIN).create(BUILD_VENV)
    run([py, "-m", "pip", "install", "--upgrade", "pip"])
    run([py, "-m", "pip", "install", "-r", ROOT / "requirements.txt", "pyinstaller"])
    return py


def ensure_icon(py: Path) -> None:
    if not (ROOT / "assets" / "icon.ico").exists():
        step("Generating the icon")
        run([py, ROOT / "tools" / "make_icon.py"])


def bundle_ffmpeg() -> str | None:
    """Download ffmpeg into .\\bin (kept next to the finished program). Returns its version."""
    exe = BIN / f"ffmpeg{updater.EXE}"
    if not exe.exists():
        if not updater.ffmpeg_install_supported():
            print("   (ffmpeg download is Windows-only; skipping)")
            return None
        step("Downloading ffmpeg (gyan.dev 'essentials' build - GPL licensed)")
        last = [0.0]

        def prog(done: int, total: int) -> None:
            if time.time() - last[0] > 0.5 or done == total:
                last[0] = time.time()
                print(f"\r   {done / 1e6:6.1f} / {total / 1e6:.1f} MB", end="", flush=True)

        updater.install_ffmpeg_into(BIN, prog)
        print()
    return updater.verify_ffmpeg(exe)


def record_versions(py: Path, ffmpeg_version: str | None) -> None:
    """Remember which yt-dlp / ffmpeg are inside this build, so the in-app updater can compare."""
    step("Recording bundled tool versions")
    ytdlp = subprocess.check_output([str(py), "-c", "import importlib.metadata as m; print(m.version('yt-dlp'))"],
                                    text=True).strip()
    data = {"yt-dlp": ytdlp, "ffmpeg": ffmpeg_version}
    (ROOT / "assets").mkdir(exist_ok=True)
    (ROOT / "assets" / "bundled_versions.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"   yt-dlp {ytdlp}, ffmpeg {ffmpeg_version or '(not bundled)'}")


def package(onefile: bool, with_ffmpeg: bool) -> Path:
    step("Packaging")
    stage = DIST / "MediaForge"
    exe_name = f"MediaForge{'.exe' if IS_WIN else ''}"
    if onefile:                                   # move the single exe into its own folder (via a temp name,
        tmp = DIST / (exe_name + ".onefile")      # because on Linux/macOS the file and folder share a name)
        shutil.move(str(DIST / exe_name), str(tmp))
        stage.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp), str(stage / exe_name))
    if with_ffmpeg and BIN.exists():              # ffmpeg sits in .\bin next to the exe, where the app looks first
        shutil.copytree(BIN, stage / "bin", dirs_exist_ok=True)
    shutil.copy2(ROOT / "README.md", stage / "README.md")
    zip_base = DIST / f"MediaForge-{app_version()}-{'win64' if IS_WIN else sys.platform}"
    archive = shutil.make_archive(str(zip_base), "zip", str(DIST), "MediaForge")
    return Path(archive)


def build_installer() -> Path | None:
    step("Building the installer (Inno Setup)")
    iscc = find_iscc()
    if not iscc:
        print("   Inno Setup 6 was not found - skipping the installer.\n"
              "   Install it from https://jrsoftware.org/isinfo.php and run this again with --installer.")
        return None
    run([iscc, f"/DMyAppVersion={app_version()}", ROOT / "packaging" / "installer.iss"])
    setup = DIST / installer_name(app_version())
    write_checksum(setup)
    return setup


def installer_name(version: str) -> str:
    return f"MediaForge_setup_v{version}.exe"


def write_checksum(path: Path) -> Path:
    """<file>.sha256 next to it: the in-app updater refuses an installer it can't verify."""
    out = path.with_name(path.name + ".sha256")
    out.write_text(f"{updater.sha256_file(path)}  {path.name}\n", encoding="utf-8")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build MediaForge for Windows.")
    ap.add_argument("--onefile", action="store_true")
    ap.add_argument("--no-ffmpeg", action="store_true")
    ap.add_argument("--installer", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--clean", action="store_true")
    ap.add_argument("--no-open", action="store_true", help="don't open the output folder when finished")
    args = ap.parse_args(argv)

    if args.check:
        return check()
    if sys.version_info < (3, 10):
        print("Python 3.10 or newer is required.")
        return 2
    if args.installer and args.onefile:
        print("--installer packages the folder build; don't combine it with --onefile.")
        return 2
    if not IS_WIN:
        print("NOTE: this isn't Windows. PyInstaller builds for the OS it runs on, so the result will not be a "
              "Windows .exe.")

    try:
        if args.clean:
            step("Cleaning")
            for p in (BUILD_VENV, ROOT / "build", DIST):
                shutil.rmtree(p, ignore_errors=True)
        py = prepare_env()
        ensure_icon(py)
        ffmpeg_version = None if args.no_ffmpeg else bundle_ffmpeg()
        record_versions(py, ffmpeg_version)

        step("Running PyInstaller (this takes a few minutes)")
        shutil.rmtree(DIST, ignore_errors=True)
        env = {**os.environ, "MEDIAFORGE_ONEFILE": "1" if args.onefile else "0"}
        run([py, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", DIST,
             "--workpath", ROOT / "build" / "pyinstaller", ROOT / "packaging" / "mediaforge.spec"], env=env)

        archive = package(args.onefile, not args.no_ffmpeg)
        installer = build_installer() if args.installer else None
    except subprocess.CalledProcessError as exc:
        print(f"\nA build step failed (exit code {exc.returncode}): {' '.join(map(str, exc.cmd))}")
        return 1
    except updater.UpdateError as exc:
        print(f"\n{exc}")
        return 1

    exe = DIST / "MediaForge" / f"MediaForge{'.exe' if IS_WIN else ''}"
    print("\n" + "=" * 60 + "\n  BUILD FINISHED\n" + "=" * 60)
    print(f"  Program : {exe}")
    print(f"  Zip     : {archive}")
    if installer:
        print(f"  Setup   : {installer}")
    if IS_WIN and not args.no_open:
        os.startfile(DIST)  # type: ignore[attr-defined]
    return 0


if __name__ == "__main__":
    sys.exit(main())

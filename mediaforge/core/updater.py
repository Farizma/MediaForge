"""Finding, checking and installing newer ffmpeg and yt-dlp builds.

Standard library ONLY: the launcher and the build script import this before any
dependency has been installed.

Design notes
* Everything is installed into the user's data folder, never into the program folder
  (which may be read-only, e.g. Program Files):
      <data>/ffmpeg/<version>/bin/ffmpeg(.exe), ffprobe(.exe)
      <data>/yt-dlp/<version>/yt-dlp            (the official single-file zipapp)
* Every update goes into a NEW versioned folder, so a running job never has its
  executable replaced underneath it (which Windows forbids anyway). The newest
  folder wins; old ones are tidied up later.
* Downloads are checksum-verified, and fail closed if no checksum can be fetched.
* yt-dlp: the zipapp is put first on sys.path before `import yt_dlp`, so it overrides
  whatever copy was installed or bundled - that is how a built .exe can update yt-dlp.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .util import hidden_kwargs, resource_path

USER_AGENT = "MediaForge-updater (+https://github.com/yt-dlp/yt-dlp)"
YTDLP_API = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
YTDLP_SUMS_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/SHA2-256SUMS"
FFMPEG_VERSION_URL = "https://www.gyan.dev/ffmpeg/builds/release-version"
FFMPEG_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
FFMPEG_SHA_URL = FFMPEG_ZIP_URL + ".sha256"
APP_RELEASES_API = "https://api.github.com/repos/Farizma/MediaForge/releases/latest"
APP_DOWNLOAD_PREFIX = "https://github.com/Farizma/MediaForge/releases/download/"   # installers only come from here
APP_RELEASES_PAGE = "https://github.com/Farizma/MediaForge/releases/latest"
INSTALLER_RE = re.compile(r"^MediaForge_setup_v(\d+(?:\.\d+)+)\.exe$")

EXE = ".exe" if sys.platform == "win32" else ""
MAX_ZIP_BYTES = 600 * 1024 * 1024

Progress = Callable[[int, int], None]        # (bytes_done, bytes_total or 0 if unknown)


class UpdateError(Exception):
    """A problem worth showing to the user as-is."""


class Cancelled(UpdateError):
    pass


@dataclass
class ToolStatus:
    key: str                          # "ffmpeg" | "ytdlp"
    name: str
    installed: Optional[str] = None   # version string, None = not installed
    source: str = ""                  # where it came from / lives
    latest: Optional[str] = None
    update_available: bool = False
    can_install: bool = True
    error: str = ""
    note: str = ""


# ---------------------------------------------------------------- locations

def default_data_dir() -> Path:
    """Same folder Qt's AppDataLocation gives for organisation/app 'MediaForge'."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "MediaForge" / "MediaForge"


def ffmpeg_root(data_dir: Path) -> Path:
    return Path(data_dir) / "ffmpeg"


def ytdlp_root(data_dir: Path) -> Path:
    return Path(data_dir) / "yt-dlp"


def ffmpeg_install_supported() -> bool:
    return sys.platform == "win32"


# ---------------------------------------------------------------- versions

def numeric_version(text: Optional[str]) -> Optional[tuple]:
    """'7.1.1-essentials_build' -> (7,1,1); '2025.01.15' -> (2025,1,15); 'N-118123-gabc' -> None."""
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)+)", str(text))
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def is_newer(latest: Optional[str], installed: Optional[str]) -> bool:
    """True if `latest` is a newer version than `installed` (or nothing is installed)."""
    new = numeric_version(latest)
    if new is None:
        return False
    old = numeric_version(installed)
    if old is None:
        return installed is None or not str(installed).strip()
    n = max(len(new), len(old))
    return new + (0,) * (n - len(new)) > old + (0,) * (n - len(old))


def ffmpeg_version_string(output: str) -> Optional[str]:
    m = re.search(r"ffmpeg version (\S+)", output or "")
    return m.group(1) if m else None


# ---------------------------------------------------------------- checksums

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_sha256(text: str, filename: Optional[str] = None) -> Optional[str]:
    """Pull a SHA-256 out of either a bare '<hash>' file or a '<hash>  <name>' sums list."""
    for line in (text or "").splitlines():
        line = line.strip()
        m = re.match(r"^([0-9a-fA-F]{64})(?:\s+\*?(.+))?$", line)
        if not m:
            continue
        name = (m.group(2) or "").strip()
        if filename is None or not name or Path(name).name == filename:
            return m.group(1).lower()
    return None


# ---------------------------------------------------------------- network

def _check_url(url: str) -> None:
    parts = urllib.parse.urlparse(url)
    local = parts.hostname in ("127.0.0.1", "localhost", "::1")
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise UpdateError(f"Refusing to use a non-HTTPS address: {url}")


def _open(url: str, timeout: float = 20):
    _check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"The server answered {exc.code} for {urllib.parse.urlparse(url).netloc}.") from None
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        raise UpdateError(f"Couldn't reach {urllib.parse.urlparse(url).netloc}: {reason}") from None


def fetch_text(url: str, timeout: float = 20, limit: int = 2_000_000) -> str:
    with _open(url, timeout) as resp:
        try:
            return resp.read(limit).decode("utf-8", "replace")
        except (OSError, TimeoutError) as exc:
            raise UpdateError(f"Download interrupted: {exc}") from None


def download(url: str, dest: Path, progress: Optional[Progress] = None,
             cancel: Optional[threading.Event] = None, timeout: float = 30) -> None:
    with _open(url, timeout) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        try:
            with open(dest, "wb") as out:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise Cancelled("Cancelled")
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        except (OSError, TimeoutError) as exc:
            raise UpdateError(f"Download interrupted: {exc}") from None
    if total and done != total:
        raise UpdateError("The download was cut short - try again.")


# ---------------------------------------------------------------- MediaForge itself

@dataclass
class AppRelease:
    version: str          # "1.0.1"
    name: str             # "MediaForge_setup_v1.0.1.exe"
    url: str
    sha_url: str


def app_install_supported() -> bool:
    """Only the installed Windows build updates itself; from source you git pull."""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def pick_app_release(data) -> AppRelease:
    """GitHub 'latest release' JSON -> the setup wizard and its .sha256. Fails closed on anything odd."""
    if not isinstance(data, dict):
        raise UpdateError("GitHub sent an unexpected reply.")
    tag = numeric_version(str(data.get("tag_name", "")))
    if tag is None:
        raise UpdateError("The latest MediaForge release has no version number.")
    assets = {str(a.get("name", "")): str(a.get("browser_download_url", ""))
              for a in data.get("assets") or [] if isinstance(a, dict)}
    for name, url in assets.items():
        m = INSTALLER_RE.match(name)
        if not m or tuple(int(x) for x in m.group(1).split(".")) != tag:
            continue
        sha_url = assets.get(name + ".sha256", "")
        if not sha_url:
            raise UpdateError("The latest MediaForge release has no checksum, so it won't be installed.")
        if not (url.startswith(APP_DOWNLOAD_PREFIX) and sha_url.startswith(APP_DOWNLOAD_PREFIX)):
            raise UpdateError("The latest MediaForge release points somewhere unexpected, so it won't be installed.")
        return AppRelease(m.group(1), name, url, sha_url)
    raise UpdateError("The latest MediaForge release has no Windows installer yet.")


def latest_app_release() -> AppRelease:
    try:
        data = json.loads(fetch_text(APP_RELEASES_API))
    except ValueError:
        raise UpdateError("GitHub sent an unexpected reply.") from None
    return pick_app_release(data)


def app_update_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "app-update"


def download_app_installer(data_dir: Path, release: AppRelease, progress: Optional[Progress] = None,
                           cancel: Optional[threading.Event] = None) -> Path:
    """Download the setup wizard and verify it against its published SHA-256. Returns its path."""
    expected = parse_sha256(fetch_text(release.sha_url), release.name)
    if not expected:
        raise UpdateError("Couldn't read the installer's checksum, so it won't be installed.")
    folder = app_update_dir(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    final, part = folder / release.name, folder / (release.name + ".part")
    try:
        download(release.url, part, progress, cancel)
        if sha256_file(part) != expected:
            raise UpdateError("The downloaded installer failed its checksum check and was deleted.")
        part.replace(final)
    finally:
        part.unlink(missing_ok=True)
    return final


def launch_installer(path: Path) -> None:
    """Start the setup wizard on its own; MediaForge then quits so the files can be replaced."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(path)], close_fds=True, creationflags=flags)


def cleanup_app_update(data_dir: Path) -> None:
    """At start-up: the installer has run (or was abandoned), so its download can go."""
    shutil.rmtree(app_update_dir(data_dir), ignore_errors=True)


# ---------------------------------------------------------------- yt-dlp

def latest_ytdlp_version() -> str:
    try:
        data = json.loads(fetch_text(YTDLP_API))
    except ValueError:
        raise UpdateError("GitHub sent an unexpected reply.") from None
    tag = str(data.get("tag_name", "")).strip() if isinstance(data, dict) else ""
    if not numeric_version(tag):
        raise UpdateError("GitHub sent an unexpected reply.")
    return tag


def read_zipapp_version(path: Path) -> str:
    """Version inside a yt-dlp zipapp (also proves it really is one)."""
    try:
        with zipfile.ZipFile(path) as z:
            src = z.read("yt_dlp/version.py").decode("utf-8", "replace")
    except (zipfile.BadZipFile, KeyError, OSError):
        raise UpdateError("That file isn't a yt-dlp download.") from None
    m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", src)
    if not m or not numeric_version(m.group(1)):
        raise UpdateError("Couldn't read the yt-dlp version from the download.")
    return m.group(1)


def install_ytdlp(data_dir: Path, progress: Optional[Progress] = None,
                  cancel: Optional[threading.Event] = None) -> str:
    """Download + verify the latest yt-dlp zipapp into <data>/yt-dlp/<version>/. Returns the version."""
    root = ytdlp_root(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix=".dl-") as tmp:
        part = Path(tmp) / "yt-dlp"
        download(YTDLP_URL, part, progress, cancel)
        want = parse_sha256(fetch_text(YTDLP_SUMS_URL), "yt-dlp")
        if not want:
            raise UpdateError("Couldn't get a checksum to verify the download - not installing.")
        if sha256_file(part) != want:
            raise UpdateError("The download failed its checksum test and was discarded.")
        version = read_zipapp_version(part)
        target = root / version
        target.mkdir(exist_ok=True)
        os.replace(part, target / "yt-dlp")
    return version


def latest_managed_ytdlp(data_dir: Path) -> Optional[tuple]:
    """(version, path-to-zipapp) of the newest downloaded yt-dlp, or None."""
    best, best_key = None, None
    root = ytdlp_root(data_dir)
    if not root.is_dir():
        return None
    for d in root.iterdir():
        key = numeric_version(d.name)
        f = d / "yt-dlp"
        if key and not d.name.startswith(".") and f.is_file() and (best_key is None or key > best_key):
            best, best_key = (d.name, f), key
    return best


def bundled_ytdlp_version() -> Optional[str]:
    """Version of the yt-dlp that came with the app/environment (without importing it)."""
    try:
        from importlib.metadata import version
        return version("yt-dlp")
    except Exception:
        pass
    try:
        data = json.loads(resource_path("assets/bundled_versions.json").read_text(encoding="utf-8"))
        return data.get("yt-dlp") or None
    except (OSError, ValueError):
        return None


def activate_ytdlp(data_dir: Path) -> Optional[str]:
    """Put the newest downloaded yt-dlp first on sys.path. Call BEFORE `import yt_dlp`.
    Returns the path used, or None if nothing newer than the bundled copy exists."""
    found = latest_managed_ytdlp(data_dir)
    if not found:
        return None
    version, path = found
    bundled = bundled_ytdlp_version()
    if bundled and not is_newer(version, bundled):
        return None
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
        importlib.invalidate_caches()
    return str(path)


# ---------------------------------------------------------------- ffmpeg

def latest_ffmpeg_version() -> str:
    line = (fetch_text(FFMPEG_VERSION_URL, limit=1000).strip().splitlines() or [""])[0].strip()
    if not numeric_version(line):
        raise UpdateError("gyan.dev sent an unexpected version reply.")
    return line


def _write_member(z: zipfile.ZipFile, info: zipfile.ZipInfo, dest: Path) -> None:
    if info.file_size > MAX_ZIP_BYTES:
        raise UpdateError("The ffmpeg archive contains an unexpectedly large file.")
    with z.open(info) as src, open(dest, "wb") as out:
        shutil.copyfileobj(src, out)
    if sys.platform != "win32":
        os.chmod(dest, 0o755)


def extract_ffmpeg_zip(zip_path: Path, bin_dir: Path, exe_suffix: str = EXE) -> None:
    """Take only ffmpeg, ffprobe and the licence out of the archive. Destination names are
    chosen here, never taken from the archive, so a hostile zip can't write elsewhere."""
    wanted = {f"ffmpeg{exe_suffix}", f"ffprobe{exe_suffix}"}
    found: set = set()
    bin_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                parts = info.filename.replace("\\", "/").split("/")
                name = parts[-1]
                if len(parts) >= 2 and parts[-2] == "bin" and name in wanted:
                    _write_member(z, info, bin_dir / name)
                    found.add(name)
                elif name == "LICENSE" and len(parts) == 2:
                    _write_member(z, info, bin_dir / "FFMPEG-LICENSE.txt")
    except zipfile.BadZipFile:
        raise UpdateError("The ffmpeg download was damaged.") from None
    except (OSError, EOFError, zlib.error) as exc:      # corrupt archive, or disk full / no permission
        raise UpdateError(f"Couldn't unpack the ffmpeg archive: {exc}") from None
    if wanted - found:
        raise UpdateError("The ffmpeg archive didn't contain " + ", ".join(sorted(wanted - found)) + ".")


def verify_ffmpeg(exe: Path) -> str:
    try:
        res = subprocess.run([str(exe), "-version"], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=30, **hidden_kwargs())
    except (OSError, subprocess.SubprocessError):
        raise UpdateError("The downloaded ffmpeg won't start.") from None
    version = ffmpeg_version_string(res.stdout)
    if not version:
        raise UpdateError("The downloaded ffmpeg didn't identify itself.")
    return version


def install_ffmpeg_into(bin_dir: Path, progress: Optional[Progress] = None,
                        cancel: Optional[threading.Event] = None, exe_suffix: str = EXE) -> str:
    """Download, verify and unpack ffmpeg + ffprobe into bin_dir. Returns ffmpeg's version string."""
    with tempfile.TemporaryDirectory(prefix="mf-ffmpeg-") as tmp:
        archive = Path(tmp) / "ffmpeg.zip"
        download(FFMPEG_ZIP_URL, archive, progress, cancel)
        want = parse_sha256(fetch_text(FFMPEG_SHA_URL, limit=10_000))
        if not want:
            raise UpdateError("Couldn't get a checksum to verify ffmpeg - not installing.")
        if sha256_file(archive) != want:
            raise UpdateError("The ffmpeg download failed its checksum test and was discarded.")
        extract_ffmpeg_zip(archive, bin_dir, exe_suffix)
    return verify_ffmpeg(bin_dir / f"ffmpeg{exe_suffix}")


def install_ffmpeg(data_dir: Path, progress: Optional[Progress] = None,
                   cancel: Optional[threading.Event] = None, exe_suffix: Optional[str] = None) -> str:
    """Install the newest ffmpeg into <data>/ffmpeg/<version>/bin. Returns the folder's version name."""
    if exe_suffix is None:
        if not ffmpeg_install_supported():
            raise UpdateError("Automatic ffmpeg installs are Windows-only. "
                              "Use your package manager (brew / apt / dnf ...).")
        exe_suffix = EXE
    root = ffmpeg_root(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=root, prefix=".new-"))
    try:
        reported = install_ffmpeg_into(staging / "bin", progress, cancel, exe_suffix)
        num = numeric_version(reported)
        name = ".".join(map(str, num)) if num else re.sub(r"[^\w.\-]", "_", reported)[:40]
        dest = root / name
        if dest.exists():
            shutil.rmtree(dest)
        os.replace(staging, dest)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return name


def latest_managed_ffmpeg(data_dir: Path, exe_suffix: str = EXE) -> Optional[tuple]:
    """(version-name, bin-dir) of the newest downloaded ffmpeg, or None."""
    root = ffmpeg_root(data_dir)
    best, best_key = None, None
    if not root.is_dir():
        return None
    for d in root.iterdir():
        key = numeric_version(d.name) or (0,)
        if d.name.startswith(".") or not (d / "bin" / f"ffmpeg{exe_suffix}").is_file():
            continue
        if best_key is None or key > best_key:
            best, best_key = (d.name, d / "bin"), key
    return best


# ---------------------------------------------------------------- housekeeping

def cleanup_old(data_dir: Path, keep: int = 2) -> None:
    """Delete all but the newest `keep` versions, and any half-finished downloads."""
    for root, keyfn in ((ffmpeg_root(data_dir), numeric_version), (ytdlp_root(data_dir), numeric_version)):
        if not root.is_dir():
            continue
        versions = []
        for d in root.iterdir():
            if d.name.startswith("."):
                shutil.rmtree(d, ignore_errors=True)       # leftovers from an interrupted install
            elif d.is_dir():
                versions.append((keyfn(d.name) or (0,), d))
        for _, d in sorted(versions, reverse=True)[keep:]:
            shutil.rmtree(d, ignore_errors=True)

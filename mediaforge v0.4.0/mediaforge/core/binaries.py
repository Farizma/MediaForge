"""Locating ffmpeg/ffprobe and asking them what they support."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from . import updater
from .util import hidden_kwargs


_managed_data_dir: Path | None = None


def set_managed_dir(data_dir: Path | None) -> None:
    """Tell find() where MediaForge keeps ffmpeg builds it downloaded itself."""
    global _managed_data_dir
    _managed_data_dir = Path(data_dir) if data_dir else None


def managed_bin_dir() -> str | None:
    if _managed_data_dir is None:
        return None
    found = updater.latest_managed_ffmpeg(_managed_data_dir)
    return str(found[1]) if found else None


def _bundled_dirs() -> str:
    """Folders searched for a bundled ffmpeg: next to the .exe, inside the bundle, ./bin."""
    dirs = []
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).parent / "bin")
        if getattr(sys, "_MEIPASS", None):
            dirs.append(Path(sys._MEIPASS) / "bin")
    dirs.append(Path(__file__).resolve().parents[2] / "bin")
    return os.pathsep.join(str(d) for d in dirs)


def find(name: str, custom: str = "") -> str | None:
    """Resolve a binary: user-set path > downloaded by MediaForge > ./bin next to the app > PATH."""
    if custom:
        p = Path(custom)
        if p.is_file():
            return str(p)
        if p.is_dir():
            hit = shutil.which(name, path=str(p))
            if hit:
                return hit
    managed = managed_bin_dir()
    if managed:
        hit = shutil.which(name, path=managed)
        if hit:
            return hit
    return shutil.which(name, path=_bundled_dirs()) or shutil.which(name)


def _run(args: list[str], timeout: int = 15) -> str:
    try:
        res = subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, **hidden_kwargs(),
        )
        return res.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def version(exe: str) -> str:
    out = _run([exe, "-version"], timeout=10)
    return out.splitlines()[0] if out else ""


@lru_cache(maxsize=8)
def encoders(ffmpeg: str) -> frozenset[str]:
    """Names of all encoders this ffmpeg build offers (e.g. libx264)."""
    names = set()
    for line in _run([ffmpeg, "-hide_banner", "-encoders"]).splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 6 and parts[1] != "=" and parts[0][0] in "VAS":
            names.add(parts[1])
    return frozenset(names)

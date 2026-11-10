"""Small helpers shared across the app (no Qt imports)."""
from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path


def hidden_kwargs() -> dict:
    """subprocess kwargs that stop a console window flashing up on Windows."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def fmt_duration(sec: float | None) -> str:
    if sec is None:
        return "?"
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def display_cmd(cmd: list[str]) -> str:
    """Render an argv list as a copy-pasteable shell command."""
    if sys.platform == "win32":
        return subprocess.list2cmdline(cmd)
    return shlex.join(cmd)


def resource_path(rel: str) -> Path:
    """Path to a bundled resource, both when run from source and from a PyInstaller build."""
    base = getattr(sys, "_MEIPASS", None) or Path(__file__).resolve().parents[2]
    return Path(base) / rel

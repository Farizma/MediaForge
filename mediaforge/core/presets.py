"""User-saved presets (ffmpeg, yt-dlp), stored as one small JSON file.

Qt-free. A preset is just a dict of option-field -> simple value; the tabs
decide which fields they save and how to apply them.
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Callable

KINDS = ("ffmpeg", "ytdlp")
MAX_NAME = 60
# yt-dlp options that run programs or load code/config. A preset someone else
# shares must not be able to smuggle these in, so imports containing them are refused.
RISKY_YTDLP = ("--exec", "--exec-before-download", "--netrc-cmd", "--plugin-dirs",
               "--config-location", "--config-locations", "--external-downloader",
               "--downloader", "--compat-options", "--use-extractors", "--alias")


def clean_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name or "")             # tabs/newlines become spaces
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()  # drop any other control chars
    if not name:
        raise ValueError("Give the preset a name.")
    return name[:MAX_NAME]


def sanitize_values(values) -> dict:
    """Keep only plain JSON scalars under string keys."""
    if not isinstance(values, dict):
        raise ValueError("A preset must be an object of settings.")
    return {str(k): v for k, v in values.items()
            if isinstance(v, (str, int, float, bool)) or v is None}


def coerce(value, default):
    """Make a loaded value match the type of the field's default (hand-edited files happen)."""
    try:
        if default is None:           # optional number such as resolution / fps
            ok = isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
            return value if ok else None
        if isinstance(default, bool):
            return bool(value) if isinstance(value, (bool, int)) else default
        if isinstance(default, int):
            return int(value)
        if isinstance(default, float):
            return float(value)
        return default if value is None else str(value)
    except (TypeError, ValueError):
        return default


def build_options(cls, values: dict, allowed=None):
    """cls(**values) that ignores unknown keys, skips fields not in `allowed`,
    and fixes wrong types. Missing fields take the dataclass defaults."""
    defaults = cls()
    kwargs = {}
    for f in dataclasses.fields(cls):
        if (allowed is None or f.name in allowed) and f.name in values:
            kwargs[f.name] = coerce(values[f.name], getattr(defaults, f.name))
    return cls(**kwargs)


def risky_reason(kind: str, values: dict) -> str | None:
    """Why this (imported) preset should be refused, or None if it looks fine."""
    if kind != "ytdlp":
        return None
    text = " ".join(str(values.get(k, "")) for k in ("extra_args", "template"))
    for token in re.split(r"\s+", text):
        flag = token.split("=", 1)[0]
        if flag in RISKY_YTDLP:
            return f"uses {flag}, which can run programs or load code"
    return None


class PresetStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._data: dict[str, dict[str, dict]] = {k: {} for k in KINDS}
        self._listeners: list[Callable[[], None]] = []
        self._load()

    # -- persistence
    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for kind in KINDS:
            section = raw.get(kind) if isinstance(raw, dict) else None
            if isinstance(section, dict):
                for name, values in section.items():
                    try:
                        self._data[kind][clean_name(name)] = sanitize_values(values)
                    except ValueError:
                        continue

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".presets-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=1, ensure_ascii=False)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        for cb in list(self._listeners):
            cb()

    def on_change(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    # -- access
    def names(self, kind: str) -> list[str]:
        return sorted(self._data[kind], key=str.lower)

    def get(self, kind: str, name: str) -> dict | None:
        values = self._data[kind].get(name)
        return dict(values) if values is not None else None

    def save(self, kind: str, name: str, values: dict) -> str:
        name = clean_name(name)
        self._data[kind][name] = sanitize_values(values)
        self._write()
        return name

    def delete(self, kind: str, name: str) -> bool:
        if name in self._data[kind]:
            del self._data[kind][name]
            self._write()
            return True
        return False

    # -- sharing
    def export_to(self, path: str | Path, kind: str | None = None) -> int:
        kinds = [kind] if kind else list(KINDS)
        payload = {"mediaforge_presets": 1, **{k: self._data[k] for k in kinds}}
        Path(path).write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
        return sum(len(self._data[k]) for k in kinds)

    def import_from(self, path: str | Path) -> tuple[int, list[str]]:
        """Merge presets from a file. Returns (imported_count, ["name: why skipped", ...])."""
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"Couldn't read that file: {exc}") from None
        if not isinstance(raw, dict) or "mediaforge_presets" not in raw:
            raise ValueError("That isn't a MediaForge presets file.")
        imported, skipped = 0, []
        for kind in KINDS:
            section = raw.get(kind)
            if not isinstance(section, dict):
                continue
            for name, values in section.items():
                try:
                    name, values = clean_name(name), sanitize_values(values)
                except ValueError as exc:
                    skipped.append(f"{name!r}: {exc}")
                    continue
                why = risky_reason(kind, values)
                if why:
                    skipped.append(f"{name}: {why}")
                    continue
                self._data[kind][name] = values
                imported += 1
        if imported:
            self._write()
        return imported, skipped

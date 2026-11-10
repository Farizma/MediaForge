"""Persistent user settings (thin wrapper over QSettings)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings


class Settings:
    def __init__(self) -> None:
        self._s = QSettings("MediaForge", "MediaForge")

    def _get(self, key: str, default: str = "") -> str:
        return str(self._s.value(key, default) or "")

    @property
    def ffmpeg_path(self) -> str:
        return self._get("ffmpeg_path")

    @ffmpeg_path.setter
    def ffmpeg_path(self, v: str) -> None:
        self._s.setValue("ffmpeg_path", v)

    @property
    def ffprobe_path(self) -> str:
        return self._get("ffprobe_path")

    @ffprobe_path.setter
    def ffprobe_path(self, v: str) -> None:
        self._s.setValue("ffprobe_path", v)

    @property
    def output_dir(self) -> str:
        return self._get("output_dir")

    @output_dir.setter
    def output_dir(self, v: str) -> None:
        self._s.setValue("output_dir", v)

    @property
    def max_parallel(self) -> int:
        return max(1, int(self._s.value("max_parallel", 1, type=int)))

    @max_parallel.setter
    def max_parallel(self, v: int) -> None:
        self._s.setValue("max_parallel", int(v))

    @property
    def download_dir(self) -> str:
        return self._get("download_dir") or str(Path.home() / "Downloads")

    @download_dir.setter
    def download_dir(self, v: str) -> None:
        self._s.setValue("download_dir", v)

    @property
    def max_retries(self) -> int:
        return max(0, int(self._s.value("max_retries", 0, type=int)))

    @max_retries.setter
    def max_retries(self, v: int) -> None:
        self._s.setValue("max_retries", int(v))

    @property
    def auto_check_updates(self) -> bool:
        return bool(self._s.value("auto_check_updates", True, type=bool))

    @auto_check_updates.setter
    def auto_check_updates(self, v: bool) -> None:
        self._s.setValue("auto_check_updates", bool(v))

    @property
    def auto_install_updates(self) -> bool:
        return bool(self._s.value("auto_install_updates", False, type=bool))

    @auto_install_updates.setter
    def auto_install_updates(self, v: bool) -> None:
        self._s.setValue("auto_install_updates", bool(v))

    @property
    def last_update_check(self) -> float:
        return float(self._s.value("last_update_check", 0.0, type=float))

    @last_update_check.setter
    def last_update_check(self, v: float) -> None:
        self._s.setValue("last_update_check", float(v))

    @property
    def colourway(self) -> str:
        return self._get("colourway", "midnight")

    @colourway.setter
    def colourway(self, v: str) -> None:
        self._s.setValue("colourway", v)

    @property
    def sound_feedback(self) -> bool:
        return bool(self._s.value("sound_feedback", False, type=bool))

    @sound_feedback.setter
    def sound_feedback(self, v: bool) -> None:
        self._s.setValue("sound_feedback", bool(v))

"""Windows 11 backdrop material (Mica) and optional sound feedback.

Windows has no haptics API for desktop apps, so 'haptic feedback' becomes an optional, very quiet system
sound on meaningful moments (a job queued / finished / failed). Off by default (Settings > Feedback)."""
from __future__ import annotations

import sys


def enable_backdrop(widget, dark: bool) -> bool:
    """Ask DWM for Mica behind the window. False on non-Windows or older Windows (callers then stay opaque)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        dwm = ctypes.windll.dwmapi
        hwnd = wintypes.HWND(int(widget.winId()))

        def attr(which: int, value: int) -> int:
            v = ctypes.c_int(value)
            return dwm.DwmSetWindowAttribute(hwnd, which, ctypes.byref(v), ctypes.sizeof(v))

        attr(20, 1 if dark else 0)                       # DWMWA_USE_IMMERSIVE_DARK_MODE
        ok = attr(38, 2) == 0                            # DWMWA_SYSTEMBACKDROP_TYPE = Mica
        if not ok:
            ok = attr(1029, 1) == 0                      # DWMWA_MICA_EFFECT (first Windows 11 builds)
        if ok:
            margins = (ctypes.c_int * 4)(-1, -1, -1, -1)  # extend the effect over the whole client area
            dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
        return ok
    except Exception:
        return False


class Feedback:
    enabled = False

    def _play(self, alias: str) -> None:
        if self.enabled and sys.platform == "win32":
            try:
                import winsound
                winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
            except Exception:
                pass

    def confirm(self) -> None:
        self._play("SystemAsterisk")

    def error(self) -> None:
        self._play("SystemExclamation")


feedback = Feedback()

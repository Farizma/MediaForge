"""Title bar that matches the window (Windows 11) and optional sound feedback.

Windows has no haptics API for desktop apps, so 'haptic feedback' becomes an optional, very quiet system
sound on meaningful moments (a job queued / finished / failed). Off by default (Settings > Feedback)."""
from __future__ import annotations

import sys


def title_bar(widget, rgb: tuple) -> bool:
    """Dark title bar in the sidebar colour, so the window reads as one dark slab like Media Vault.
    False on non-Windows; Windows 10 takes the dark mode but ignores the colour."""
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

        attr(20, 1)                                      # DWMWA_USE_IMMERSIVE_DARK_MODE
        r, g, b = rgb[:3]
        return attr(35, r | g << 8 | b << 16) == 0       # DWMWA_CAPTION_COLOR, a COLORREF (0x00BBGGRR)
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

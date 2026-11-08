"""Design tokens: Apple system colors, HIG 4-pt spacing, Dynamic-Type-style text, light/dark."""
from __future__ import annotations

import sys
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont

TARGET = 44                                       # HIG minimum hit target
SPACE = dict(xs=4, s=8, m=12, l=16, xl=24, xxl=32)
RADIUS = dict(s=8, m=10, l=14)
ROLES = {  # role: (pixel size, weight, tracking px). Large text tightens, small text loosens (apple-design)
    "largeTitle": (28, 700, -0.4), "title": (20, 600, -0.2), "headline": (14, 600, 0.0),
    "body": (14, 400, 0.0), "callout": (13, 400, 0.0), "footnote": (12, 400, 0.1),
    "caption": (11, 500, 0.2), "mono": (12, 400, 0.0),
}
WEIGHTS = {400: QFont.Weight.Normal, 500: QFont.Weight.Medium, 600: QFont.Weight.DemiBold, 700: QFont.Weight.Bold}
FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "SF Pro Text", "Helvetica Neue", "Arial"]
MONO = ["Cascadia Mono", "Consolas", "SF Mono", "Menlo", "monospace"]


@dataclass(frozen=True)
class Palette:                                    # RGBA tuples
    bg: tuple; card: tuple; sidebar: tuple; label: tuple; label2: tuple; label3: tuple
    sep: tuple; fill: tuple; accent: tuple; green: tuple; orange: tuple; red: tuple; thumb: tuple


LIGHT = Palette(bg=(242, 242, 247), card=(255, 255, 255), sidebar=(246, 246, 250, 175), label=(0, 0, 0),
                label2=(60, 60, 67, 153), label3=(60, 60, 67, 90), sep=(60, 60, 67, 41), fill=(120, 120, 128, 41),
                accent=(0, 122, 255), green=(52, 199, 89), orange=(255, 149, 0), red=(255, 59, 48), thumb=(255, 255, 255))
DARK = Palette(bg=(28, 28, 30), card=(44, 44, 46), sidebar=(44, 44, 46, 175), label=(255, 255, 255),
               label2=(235, 235, 245, 153), label3=(235, 235, 245, 90), sep=(84, 84, 88, 130), fill=(120, 120, 128, 91),
               accent=(10, 132, 255), green=(48, 209, 88), orange=(255, 159, 10), red=(255, 69, 58), thumb=(99, 99, 102))


def text_scale() -> float:
    """Windows 'Text size' accessibility slider (100-225 %), clamped. shortcut: read once at start-up."""
    if sys.platform != "win32":
        return 1.0
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Accessibility") as k:
            return max(1.0, min(1.5, winreg.QueryValueEx(k, "TextScaleFactor")[0] / 100))
    except OSError:
        return 1.0


def qc(t: tuple, alpha: float = 1.0) -> QColor:
    r, g, b, *a = t
    return QColor(r, g, b, round((a[0] if a else 255) * alpha))


def mix(a: tuple, b: tuple, t: float) -> QColor:
    a, b = (tuple(a) + (255,))[:4], (tuple(b) + (255,))[:4]
    return QColor(*(round(a[i] + (b[i] - a[i]) * t) for i in range(4)))


def css(t: tuple) -> str:
    r, g, b, *a = t
    return f"rgba({r},{g},{b},{a[0] if a else 255})"


class Theme(QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.dark, self.p, self.scale, self.backdrop = False, LIGHT, text_scale(), False
        self._fonts: dict = {}

    def install(self, app) -> None:
        hints = app.styleHints()
        self._set(hints.colorScheme() == Qt.ColorScheme.Dark)
        hints.colorSchemeChanged.connect(self._on_scheme)

    def _on_scheme(self, scheme) -> None:             # the signal carries the new scheme; the palette lags it
        self._set(scheme == Qt.ColorScheme.Dark)

    def _set(self, dark: bool) -> None:
        self.dark, self.p = dark, DARK if dark else LIGHT
        self.changed.emit()

    def px(self, n: float) -> int:
        return round(n * self.scale)

    def font(self, role: str = "body") -> QFont:
        if role not in self._fonts:
            size, weight, track = ROLES[role]
            f = QFont()
            f.setFamilies(MONO if role == "mono" else FAMILIES)
            f.setPixelSize(self.px(size))
            f.setWeight(WEIGHTS[weight])
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, track)
            self._fonts[role] = f
        return self._fonts[role]

    def stylesheet(self) -> str:
        p, px = self.p, self.px
        c = {k: css(getattr(p, k)) for k in ("bg", "card", "label", "label2", "label3", "sep", "fill", "accent")}
        return f"""
        QToolTip {{ background:{c['card']}; color:{c['label']}; border:1px solid {c['sep']}; border-radius:{px(8)}px; padding:{px(6)}px {px(10)}px; }}
        QScrollArea, QStackedWidget {{ background:transparent; border:none; }}
        QLineEdit, QPlainTextEdit {{ background:{c['fill']}; color:{c['label']}; border:2px solid transparent;
            border-radius:{px(10)}px; padding:{px(4)}px {px(10)}px; selection-background-color:{c['accent']}; selection-color:white; }}
        QLineEdit {{ min-height:{px(36)}px; }}
        QLineEdit:focus, QPlainTextEdit:focus {{ border:2px solid {c['accent']}; }}
        QLineEdit:disabled {{ color:{c['label3']}; }}
        QListWidget, QListView, QTableWidget {{ background:{c['card']}; color:{c['label']}; border:1px solid {c['sep']};
            border-radius:{px(14)}px; padding:{px(4)}px; outline:0; }}
        QListWidget::item {{ min-height:{px(44)}px; padding-left:{px(12)}px; border-radius:{px(8)}px; }}
        QListWidget::item:selected, QTableWidget::item:selected {{ background:{c['accent']}; color:white; }}
        QListWidget::item:hover:!selected {{ background:{c['fill']}; }}
        QTableWidget {{ gridline-color:transparent; }}
        QTableWidget::item {{ padding:0 {px(8)}px; border-radius:{px(6)}px; }}
        QHeaderView {{ background:transparent; }}
        QHeaderView::section {{ background:transparent; color:{c['label2']}; border:none; padding:{px(6)}px {px(8)}px; }}
        QScrollBar:vertical {{ background:transparent; width:{px(12)}px; margin:2px; }}
        QScrollBar::handle:vertical {{ background:{c['label3']}; border-radius:{px(4)}px; min-height:{px(36)}px; }}
        QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background:none; height:0; }}
        QScrollBar:horizontal {{ background:transparent; height:{px(12)}px; margin:2px; }}
        QScrollBar::handle:horizontal {{ background:{c['label3']}; border-radius:{px(4)}px; min-width:{px(36)}px; }}
        QMenu {{ background:{c['card']}; color:{c['label']}; border:1px solid {c['sep']}; border-radius:{px(12)}px; padding:{px(6)}px; }}
        QMenu::item {{ min-height:{px(36)}px; padding:0 {px(28)}px 0 {px(12)}px; border-radius:{px(8)}px; }}
        QMenu::item:selected {{ background:{c['accent']}; color:white; }}
        QMenu::item:disabled {{ color:{c['label3']}; }}
        QMenu::separator {{ height:1px; background:{c['sep']}; margin:{px(4)}px {px(8)}px; }}
        """


theme = Theme()

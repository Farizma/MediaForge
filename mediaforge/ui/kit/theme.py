"""Design tokens, matched to Media Vault: dark colourways on near-black, white-tint glass surfaces,
Plus Jakarta Sans + JetBrains Mono, HIG 4-pt spacing, Dynamic-Type-style text roles."""
from __future__ import annotations

import sys
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

TARGET = 44                                       # HIG minimum hit target
SPACE = dict(xs=4, s=8, m=12, l=16, xl=24, xxl=32)
RADIUS = dict(s=8, m=10, l=12, xl=16)
ROLES = {  # role: (pixel size, weight, tracking px). Large text tightens, small text loosens (apple-design)
    "largeTitle": (30, 800, -0.8), "brand": (16, 800, -0.3), "title": (18, 700, -0.3), "headline": (14, 700, -0.1),
    "body": (13, 400, 0.0), "callout": (12, 400, 0.0), "footnote": (12, 400, 0.0),
    "caption": (11, 700, 0.2), "mono": (12, 400, 0.0),
    "button": (13, 600, 0.0), "strong": (13, 800, 0.0), "nav": (13, 600, 0.0), "tab": (12, 700, 0.0),
    "kicker": (10, 600, 0.8),                     # mono, upper-case section labels ("THIS PC" in Media Vault)
}
MONO_ROLES = {"mono", "kicker"}
WEIGHTS = {400: QFont.Weight.Normal, 500: QFont.Weight.Medium, 600: QFont.Weight.DemiBold,
           700: QFont.Weight.Bold, 800: QFont.Weight.ExtraBold}
FAMILIES = ["Plus Jakarta Sans", "Segoe UI Variable Text", "Segoe UI", "Arial"]
MONO = ["JetBrains Mono", "Cascadia Mono", "Consolas", "monospace"]

# Media Vault's colourways: id, name, page, surface, accent (progress, switches, badges), highlight (focus, selection)
COLOURWAYS = [
    ("midnight", "Midnight Obsidian", "#000000", "#121214", "#34C759", "#007AFF"),
    ("cyberpunk", "Cyberpunk Neon", "#09090F", "#13131F", "#00F0FF", "#FF007F"),
    ("tokyo", "Tokyo Slate", "#0B0F19", "#141D2E", "#38BDF8", "#818CF8"),
    ("titanium", "OLED Titanium", "#101012", "#1C1C20", "#F59E0B", "#E2E8F0"),
    ("matrix", "Emerald Matrix", "#070B07", "#0E170E", "#10B981", "#84CC16"),
    ("crimson", "Crimson Noir", "#0C0607", "#1A0E10", "#FF9F0A", "#FF453A"),
    ("nebula", "Nebula", "#0A0814", "#16122A", "#64D2FF", "#BF5AF2"),
    ("graphite", "Graphite", "#161618", "#232326", "#30D158", "#0A84FF"),
]


@dataclass(frozen=True)
class Palette:                                    # RGBA tuples
    bg: tuple; sheet: tuple; card: tuple; sidebar: tuple; label: tuple; label2: tuple; label3: tuple
    sep: tuple; edge: tuple; fill: tuple; accent: tuple; on_accent: tuple; tint: tuple; on_tint: tuple; green: tuple
    orange: tuple; red: tuple; thumb: tuple


def _rgb(h: str) -> tuple:
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def _ink(c: tuple) -> tuple:
    """Black or white text, whichever reads better on c (WCAG relative luminance)."""
    lin = [(v / 255 / 12.92) if v <= 10 else ((v / 255 + 0.055) / 1.055) ** 2.4 for v in c[:3]]
    return (0, 0, 0) if 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2] > 0.4 else (255, 255, 255)


def palette(colourway: str) -> Palette:
    _, _, page, surface, accent, highlight = next((c for c in COLOURWAYS if c[0] == colourway), COLOURWAYS[0])
    page, surface, tint, blue = _rgb(page), _rgb(surface), _rgb(accent), _rgb(highlight)
    card = tuple(round(v + (255 - v) * 0.05) for v in surface)          # Media Vault's "slate": surface + 5 % white
    white = lambda a: (255, 255, 255, a)                                 # noqa: E731  Tailwind white/NN overlays
    return Palette(bg=page, sheet=surface, card=card, sidebar=surface, label=(245, 245, 247), label2=white(153),
                   label3=white(90), sep=white(26), edge=white(38), fill=white(26), accent=blue, on_accent=_ink(blue),
                   tint=tint, on_tint=_ink(tint), green=(48, 209, 88), orange=(255, 159, 10), red=(255, 69, 58),
                   thumb=(255, 255, 255))   # green / orange / red stay fixed: they mean ok / warning / error


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
        self.colourway, self.p, self.scale = "midnight", palette("midnight"), text_scale()
        self._fonts: dict = {}

    def install(self, app, colourway: str = "midnight") -> None:
        """Register the bundled fonts and pick the colourway. Dark only, like Media Vault."""
        from ...core.util import resource_path
        for f in sorted(resource_path("assets/fonts").glob("*.ttf")):
            QFontDatabase.addApplicationFont(str(f))
        self._fonts.clear()

        def restyle() -> None:
            app.setPalette(self.qpalette())             # Fusion's own parts (file dialogs, frames) go dark too
            app.setFont(self.font("body"))
            app.setStyleSheet(self.stylesheet())

        self.changed.connect(restyle)
        self.apply(colourway)

    def apply(self, colourway: str) -> None:
        self.colourway = colourway if any(c[0] == colourway for c in COLOURWAYS) else COLOURWAYS[0][0]
        self.p = palette(self.colourway)
        self.changed.emit()

    def px(self, n: float) -> int:
        return round(n * self.scale)

    def font(self, role: str = "body") -> QFont:
        if role not in self._fonts:
            size, weight, track = ROLES[role]
            f = QFont()
            f.setFamilies(MONO if role in MONO_ROLES else FAMILIES)
            f.setPixelSize(self.px(size))
            f.setWeight(WEIGHTS[weight])
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, track)
            f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)   # keeps the geometric shapes under ClearType
            if role == "kicker":
                f.setCapitalization(QFont.Capitalization.AllUppercase)
            self._fonts[role] = f
        return self._fonts[role]

    def qpalette(self) -> QPalette:
        p, R = self.p, QPalette.ColorRole
        pal = QPalette()
        for role, c in ((R.Window, p.bg), (R.Base, p.card), (R.AlternateBase, p.sheet), (R.Button, p.card),
                        (R.WindowText, p.label), (R.Text, p.label), (R.ButtonText, p.label), (R.ToolTipBase, p.card),
                        (R.ToolTipText, p.label), (R.Highlight, p.accent), (R.HighlightedText, p.on_accent),
                        (R.PlaceholderText, p.label3), (R.Link, p.accent), (R.Mid, p.sheet), (R.Dark, p.bg)):
            pal.setColor(role, qc(c[:3]))
        for role in (R.WindowText, R.Text, R.ButtonText):
            pal.setColor(QPalette.ColorGroup.Disabled, role, qc(p.label3[:3], 1).darker(150))
        return pal

    def stylesheet(self) -> str:
        p, px = self.p, self.px
        c = {k: css(getattr(p, k)) for k in ("bg", "sheet", "card", "label", "label2", "label3", "sep", "edge", "fill", "accent", "on_accent")}
        return f"""
        QToolTip {{ background:rgba(28,28,30,242); color:#FFFFFF; border:1px solid rgba(255,255,255,51); border-radius:{px(7)}px;
            padding:{px(5)}px {px(8)}px; font-size:{px(11)}px; font-weight:500; }}
        QScrollArea, QStackedWidget {{ background:transparent; border:none; }}
        QLineEdit, QPlainTextEdit {{ background:{c['card']}; color:{c['label']}; border:1px solid {c['sep']};
            border-radius:{px(10)}px; padding:{px(5)}px {px(11)}px; selection-background-color:{c['accent']}; selection-color:{c['on_accent']}; }}
        QLineEdit {{ min-height:{px(36)}px; }}
        QLineEdit:focus, QPlainTextEdit:focus {{ border:1px solid {c['accent']}; }}
        QLineEdit:disabled {{ color:{c['label3']}; }}
        QListWidget, QListView, QTableWidget {{ background:{c['card']}; color:{c['label']}; border:1px solid {c['sep']};
            border-radius:{px(12)}px; padding:{px(4)}px; outline:0; }}
        QListWidget::item {{ min-height:{px(40)}px; padding-left:{px(12)}px; border-radius:{px(8)}px; }}
        QListWidget::item:selected, QTableWidget::item:selected {{ background:{c['accent']}; color:{c['on_accent']}; }}
        QListWidget::item:hover:!selected {{ background:{c['fill']}; }}
        QTableWidget {{ gridline-color:transparent; }}
        QTableWidget::item {{ padding:0 {px(8)}px; border-radius:{px(6)}px; }}
        QHeaderView {{ background:transparent; }}
        QHeaderView::section {{ background:transparent; color:{c['label2']}; border:none; padding:{px(6)}px {px(8)}px; }}
        QScrollBar:vertical {{ background:transparent; width:{px(10)}px; margin:2px; }}
        QScrollBar::handle:vertical {{ background:{c['label3']}; border-radius:{px(3)}px; min-height:{px(36)}px; }}
        QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background:none; height:0; }}
        QScrollBar:horizontal {{ background:transparent; height:{px(10)}px; margin:2px; }}
        QScrollBar::handle:horizontal {{ background:{c['label3']}; border-radius:{px(3)}px; min-width:{px(36)}px; }}
        QMenu {{ background:{css(p.sheet[:3] + (242,))}; color:{c['label']}; border:1px solid rgba(255,255,255,51);
            border-radius:{px(12)}px; padding:{px(4)}px; }}
        QMenu::item {{ min-height:{px(32)}px; padding:0 {px(28)}px 0 {px(12)}px; border-radius:{px(8)}px; }}
        QMenu::item:selected {{ background:rgba(255,255,255,31); color:#FFFFFF; }}
        QMenu::item:disabled {{ color:{c['label3']}; }}
        QMenu::separator {{ height:1px; background:{c['sep']}; margin:{px(4)}px {px(8)}px; }}
        """


theme = Theme()

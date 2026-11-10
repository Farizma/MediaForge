"""Symbol set (SF-Symbols-style: 1.75 px round strokes on a 24 grid), rendered from SVG in any theme color."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

L = lambda x1, y1, x2, y2: f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>'          # noqa: E731
P = lambda pts: f'<polyline points="{pts}"/>'                                              # noqa: E731
SYMBOLS = {
    "play": '<polygon points="6 3 20 12 6 21 6 3"/>', "pause": '<rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>',
    "stop": '<rect x="5" y="5" width="14" height="14" rx="2"/>', "plus": L(12, 5, 12, 19) + L(5, 12, 19, 12), "minus": L(5, 12, 19, 12),
    "x": L(18, 6, 6, 18) + L(6, 6, 18, 18), "check": P("20 6 9 17 4 12"), "chevron-right": P("9 18 15 12 9 6"),
    "chevron-down": P("6 9 12 15 18 9"), "chevron-up": P("18 15 12 9 6 15"), "chevrons": P("7 9 12 4 17 9") + P("7 15 12 20 17 15"),
    "arrow-up": L(12, 19, 12, 5) + P("5 12 12 5 19 12"), "arrow-down": L(12, 5, 12, 19) + P("19 12 12 19 5 12"),
    "reverse": L(7, 4, 7, 20) + P("3 8 7 4 11 8") + L(17, 4, 17, 20) + P("13 16 17 20 21 16"),
    "sort": L(4, 6, 13, 6) + L(4, 12, 10, 12) + L(4, 18, 7, 18) + P("16 8 19 5 22 8") + L(19, 5, 19, 19),
    "trash": P("3 6 5 6 21 6") + '<path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>' + L(10, 11, 10, 17) + L(14, 11, 14, 17)
             + '<path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
    "folder": '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>' + P("7 10 12 15 17 10") + L(12, 15, 12, 3),
    "refresh": P("23 4 23 10 17 10") + P("1 20 1 14 7 14") + '<path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
    "retry": P("1 4 1 10 7 10") + '<path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>',
    "search": '<circle cx="11" cy="11" r="8"/>' + L(21, 21, 16.65, 16.65),
    "sliders": L(4, 21, 4, 14) + L(4, 10, 4, 3) + L(12, 21, 12, 12) + L(12, 8, 12, 3) + L(20, 21, 20, 16) + L(20, 12, 20, 3)
               + L(1, 14, 7, 14) + L(9, 8, 15, 8) + L(17, 16, 23, 16),
    "more": '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
    "film": '<rect x="2" y="2" width="20" height="20" rx="2.18"/>' + L(7, 2, 7, 22) + L(17, 2, 17, 22) + L(2, 12, 22, 12)
            + L(2, 7, 7, 7) + L(2, 17, 7, 17) + L(17, 17, 22, 17) + L(17, 7, 22, 7),
    "layers": '<polygon points="12 2 2 7 12 12 22 7 12 2"/>' + P("2 17 12 22 22 17") + P("2 12 12 17 22 12"),
    "cloud-down": P("8 17 12 21 16 17") + L(12, 12, 12, 21) + '<path d="M20.88 18.09A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.29"/>',
    "list": L(8, 6, 21, 6) + L(8, 12, 21, 12) + L(8, 18, 21, 18) + L(3, 6, 3.01, 6) + L(3, 12, 3.01, 12) + L(3, 18, 3.01, 18),
    "terminal": P("4 17 10 11 4 5") + L(12, 19, 20, 19),
    "alert": '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>' + L(12, 9, 12, 13) + L(12, 17, 12.01, 17),
    "info": '<circle cx="12" cy="12" r="10"/>' + L(12, 16, 12, 12) + L(12, 8, 12.01, 8),
    "star": '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
    "bookmark": '<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
    "clipboard": '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/>',
    "file-plus": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>' + P("14 2 14 8 20 8") + L(12, 18, 12, 12) + L(9, 15, 15, 15),
    "check-circle": '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>' + P("22 4 12 14.01 9 11.01"),
    "x-circle": '<circle cx="12" cy="12" r="10"/>' + L(15, 9, 9, 15) + L(9, 9, 15, 15),
    "clock": '<circle cx="12" cy="12" r="10"/>' + P("12 6 12 12 16 14"),
    "pause-circle": '<circle cx="12" cy="12" r="10"/>' + L(10, 15, 10, 9) + L(14, 15, 14, 9),
    "play-circle": '<circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8"/>',
    "mountain": P("2 20 9 8 14 15 17 11 22 20") + '<circle cx="17" cy="6" r="1.5"/>',
}


@lru_cache(maxsize=512)
def _render(name: str, rgba: tuple, size: int, dpr: float) -> QPixmap:
    r, g, b, a = (tuple(rgba) + (255,))[:4]
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="rgb({r},{g},{b})" '
           f'stroke-opacity="{a / 255:.3f}" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">{SYMBOLS[name]}</svg>')
    px = QPixmap(round(size * dpr), round(size * dpr))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(0, 0, size, size))
    p.end()
    return px


def pixmap(name: str, color: tuple, size: int = 18, dpr: float = 1.0) -> QPixmap:
    return _render(name, tuple(color), size, dpr)


def icon(name: str, color: tuple, size: int = 18) -> QIcon:
    return QIcon(pixmap(name, color, size, 2.0))


def draw(painter: QPainter, name: str, rect: QRectF, color: tuple) -> None:
    dpr = painter.device().devicePixelRatioF()
    painter.drawPixmap(rect.topLeft(), pixmap(name, color, round(rect.width()), dpr))

"""Drop anything anywhere: files go to Convert or Join, links go to Download.

While something is dragged over the window a dark wash fades in with labelled drop zones; the zone under the
pointer lights up. On Convert or Join there is one zone (that page); elsewhere files get two (Convert | Join).
"""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QCursor, QPainter, QPen
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from .kit import Spring, icons, qc, theme
from .kit.motion import tween
from .kit.theme import RADIUS, SPACE
from .pages.tool import MEDIA_EXT

MAX_FOUND = 500                                        # files taken from dropped folders
ZONES = {"convert": ("Convert", "film"), "join": ("Join", "layers"), "download": ("Download", "cloud-down")}


def classify(urls: list, text: str = "") -> tuple[str | None, list]:
    """What was dragged: ("files", local paths), ("links", http(s) addresses) or (None, [])."""
    local = [u.toLocalFile() for u in urls if u.isLocalFile() and u.toLocalFile()]
    if local:
        return "files", local
    links = [u.toString() for u in urls if u.scheme() in ("http", "https")]
    if not links:                                      # some browsers only offer the address as text
        links = re.findall(r"https?://\S+", text or "")
    return ("links", list(dict.fromkeys(links))) if links else (None, [])


def expand(paths: list) -> list[str]:
    """Files stay as they are (the page checks them); folders give their media files, sorted, recursively."""
    out: list[str] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            found = sorted(str(f) for f in p.rglob("*") if f.suffix.lower() in MEDIA_EXT and f.is_file())
            out += found[:MAX_FOUND - len(out)]
        elif p.is_file():
            out.append(str(p))
        if len(out) >= MAX_FOUND:
            break
    return list(dict.fromkeys(out))


def describe(kind: str, items: list) -> str:
    if kind == "links":
        return f"{len(items)} link{'s' if len(items) != 1 else ''}"
    folders = sum(Path(p).is_dir() for p in items)
    files = len(items) - folders
    parts = [f"{files} file{'s' if files != 1 else ''}"] if files else []
    parts += [f"{folders} folder{'s' if folders != 1 else ''}"] if folders else []
    return ", ".join(parts)


class DropOverlay(QWidget):
    """Covers the window while an outside drag is over it. dropped(zone, kind, items)."""
    dropped = Signal(str, str, list)

    def __init__(self, host: QWidget, current_page) -> None:
        super().__init__(host)
        self.current_page = current_page               # callable: the page key shown right now
        self.kind, self.items, self.zones = None, [], []
        self.level = 0.0
        self.hot: dict[str, Spring] = {}
        self._fade = None
        self.setAcceptDrops(True)
        self.hide()

    # -- the app-wide filter: the first time an outside drag touches any widget, take it over
    def eventFilter(self, obj: QObject, e: QEvent) -> bool:
        t, T = e.type(), QEvent.Type
        if t not in (T.DragEnter, T.DragMove, T.Drop, T.DragLeave) or obj is self:
            return False
        if not isinstance(obj, QWidget) or obj.window() is not self.window():
            return False
        if t == T.DragLeave:                           # the pointer left the window before reaching the overlay
            if self.isVisible() and not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
                self._close()
            return False
        if e.source() is not None:                     # in-app drags (reordering a list) are not ours
            return False
        if t == T.DragEnter:
            kind, items = classify(e.mimeData().urls(), e.mimeData().text())
            if kind is None:
                return False
            self._open(kind, items)
            e.acceptProposedAction()
            return True
        if not self.isVisible() or not self.kind:
            return False
        pos = QPointF(self.mapFrom(obj, e.position().toPoint()))   # still aimed at the widget underneath
        if t == T.DragMove:
            self._point(self.zone_at(pos))
            e.acceptProposedAction()
        else:
            self._drop(pos, e)
        return True

    def _open(self, kind: str, items: list) -> None:
        self.kind, self.items = kind, items
        page = self.current_page()
        if kind == "links":
            self.zones = ["download"]
        else:
            self.zones = [page] if page in ("convert", "join") else ["convert", "join"]
        self.hot = {z: Spring(0, 0.2, 1.0, on_change=self.update) for z in self.zones}
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self._animate(1.0, 150)                        # occasional, so a short ease-out fade; exits faster

    def _close(self) -> None:
        self._animate(0.0, 100, done=self.hide)

    def _animate(self, to: float, ms: int, done=None) -> None:
        if self._fade is not None and isValid(self._fade):   # a finished fade has already deleted itself
            self._fade.stop()

        def step(v: float) -> None:
            self.level = v
            self.update()
        self._fade = tween(self, self.level, to, ms, step, done=done)

    # -- geometry
    def _rects(self) -> dict[str, QRectF]:
        pad, gap = theme.px(SPACE["xl"]), theme.px(SPACE["l"])
        area = QRectF(self.rect()).adjusted(pad, pad, -pad, -pad)
        n = max(1, len(self.zones))
        w = (area.width() - gap * (n - 1)) / n
        return {z: QRectF(area.left() + i * (w + gap), area.top(), w, area.height()) for i, z in enumerate(self.zones)}

    def zone_at(self, pos) -> str | None:
        for z, r in self._rects().items():
            if r.contains(pos):
                return z
        return None

    def _point(self, z: str | None) -> None:
        for key, spring in self.hot.items():
            spring.to(1.0 if key == z else 0.0)

    # -- drag events (the overlay is under the pointer now)
    def dragEnterEvent(self, e) -> None:
        if e.source() is None and self.kind:
            e.acceptProposedAction()
            self._point(self.zone_at(e.position()))

    def dragMoveEvent(self, e) -> None:
        z = self.zone_at(e.position())
        self._point(z)
        e.acceptProposedAction() if z else e.ignore()

    def dragLeaveEvent(self, e) -> None:
        self._close()

    def dropEvent(self, e) -> None:
        self._drop(e.position(), e)

    def _drop(self, pos, e) -> None:
        z = self.zone_at(pos)
        if z:
            e.acceptProposedAction()
            self.dropped.emit(z, self.kind, list(self.items))
        self._close()

    # -- look
    def paintEvent(self, _) -> None:
        if self.level <= 0.001:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self.level)
        p.fillRect(self.rect(), qc((0, 0, 0, 165)))   # the same wash as behind a sheet
        rad, pal = theme.px(RADIUS["xl"]), theme.p
        detail = describe(self.kind, self.items) if self.kind else ""
        for z, r in self._rects().items():
            hot = max(0.0, min(1.0, self.hot[z].value))
            p.setBrush(qc((255, 255, 255, round(10 + 20 * hot))))
            pen = QPen(qc(pal.label3) if hot < 0.5 else qc(pal.accent), theme.px(2), Qt.PenStyle.DashLine)
            pen.setDashPattern([4, 3])
            p.setPen(pen)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), rad, rad)
            title, icon = ZONES[z]
            isz, cy = theme.px(44), r.center().y()
            icons.draw(p, icon, QRectF(r.center().x() - isz / 2, cy - isz - theme.px(12), isz, isz),
                       pal.accent if hot >= 0.5 else pal.label2)
            p.setFont(theme.font("title"))
            p.setPen(qc(pal.label))
            p.drawText(QRectF(r.left(), cy, r.width(), theme.px(28)), Qt.AlignmentFlag.AlignCenter, f"Drop to {title.lower()}")
            p.setFont(theme.font("callout"))
            p.setPen(qc(pal.label2))
            p.drawText(QRectF(r.left(), cy + theme.px(28), r.width(), theme.px(20)), Qt.AlignmentFlag.AlignCenter, detail)

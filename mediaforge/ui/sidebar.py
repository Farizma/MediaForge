"""Sidebar in Media Vault's settings-list style: colour icon tiles, a white/15 selection pill that slides on a
spring, mono section labels, icon-only when narrow."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QFontMetrics, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QVBoxLayout, QWidget

from ..core.util import resource_path
from .kit import Label, MenuButton, Spring, icons, qc
from .kit.controls import _KbFocus, _ring
from .kit.theme import RADIUS, SPACE, TARGET, mix, theme

# System-Settings-style tile colours, fixed across colourways like Media Vault's settings icons
TINTS = {"convert": (10, 132, 255), "join": (191, 90, 242), "download": (48, 209, 88), "queue": (255, 159, 10),
         "log": (94, 92, 230), "updates": (100, 210, 255), "settings": (142, 142, 147)}


def tile(p: QPainter, key: str, icon: str, r: QRectF) -> None:
    """White symbol on a tinted rounded square with a soft top-down sheen."""
    tint = TINTS.get(key, theme.p.accent)
    g = QLinearGradient(r.topLeft(), r.bottomLeft())
    g.setColorAt(0, mix(tint, (255, 255, 255), 0.18))
    g.setColorAt(1, qc(tint))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawRoundedRect(r, r.width() * 0.29, r.width() * 0.29)
    inset = r.width() * 0.2
    icons.draw(p, icon, r.adjusted(inset, inset, -inset, -inset), (255, 255, 255))


class NavButton(_KbFocus, QAbstractButton):
    stepped = Signal(int)                                    # Up / Down arrow: -1 / +1

    def __init__(self, key: str, label: str, icon: str, checkable: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.key, self.label, self.icon_name = key, label, icon
        self.badge, self.dot, self.compact = 0, False, False
        self.setCheckable(checkable)
        self.setText(label)
        self.setAccessibleName(label)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedHeight(theme.px(TARGET))
        self._hover = Spring(0, 0.2, 1.0, on_change=self.update)
        self.toggled.connect(self.update)
        theme.changed.connect(self.update)

    def enterEvent(self, e) -> None:
        self._hover.to(1)
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._hover.to(0)
        super().leaveEvent(e)

    def keyPressEvent(self, e) -> None:
        step = {Qt.Key.Key_Up: -1, Qt.Key.Key_Down: 1}.get(e.key())
        self.stepped.emit(step) if step else super().keyPressEvent(e)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        px, pal = theme.px, theme.p
        r, rad = QRectF(self.rect()).adjusted(px(10), px(3), -px(10), -px(3)), px(RADIUS["l"])
        p.setPen(Qt.PenStyle.NoPen)
        if self._hover.value > 0.01 and not self.isChecked():
            p.setBrush(qc((255, 255, 255, 13), self._hover.value))
            p.drawRoundedRect(r, rad, rad)
        on = self.isChecked()
        isz = px(24)
        ix = r.center().x() - isz / 2 if self.compact else r.left() + px(8)
        tile(p, self.key, self.icon_name, QRectF(ix, r.center().y() - isz / 2, isz, isz))
        if self.dot:
            p.setPen(QPen(qc(theme.p.sidebar), px(2)))
            p.setBrush(qc(pal.orange))
            p.drawEllipse(QRectF(ix + isz - px(6), r.center().y() - isz / 2 - px(3), px(10), px(10)))
        if self.compact:
            return
        p.setFont(theme.font("nav"))
        p.setPen(mix(pal.label2, (255, 255, 255), max(float(on), self._hover.value)))
        tx = ix + isz + px(10)
        p.drawText(QRectF(tx, r.top(), r.right() - tx - px(40), r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.label)
        if self.badge:
            text = str(self.badge)
            w = max(px(22), QFontMetrics(theme.font("caption")).horizontalAdvance(text) + px(14))
            pill = QRectF(r.right() - px(12) - w, r.center().y() - px(10), w, px(20))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qc(pal.tint))
            p.drawRoundedRect(pill, px(10), px(10))
            p.setFont(theme.font("caption"))
            p.setPen(qc(pal.on_tint))
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)
        if self._kb:
            _ring(p, r, rad)


class _Pill(QWidget):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(qc(theme.p.sep), 1))
        p.setBrush(qc((255, 255, 255, 38)))
        rad = theme.px(RADIUS["l"])
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)


class Brand(QWidget):
    """The app logo (assets/icon.png, made by tools/make_icon.py), drawn crisp at the screen's pixel ratio."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(theme.px(32), theme.px(32))
        self.logo = QImage(str(resource_path("assets/icon.png")))

    def paintEvent(self, _) -> None:
        if self.logo.isNull():
            return
        side = round(self.width() * self.devicePixelRatioF())
        if getattr(self, "_cache", QImage()).width() != side:      # one good downscale, not a blurry one per paint
            self._cache = self.logo.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self._cache.setDevicePixelRatio(self.devicePixelRatioF())
        QPainter(self).drawImage(0, 0, self._cache)


class Sidebar(QWidget):
    navigate = Signal(str)
    action = Signal(str)

    def __init__(self, sections: list, footer: list, menu: list, parent=None) -> None:
        super().__init__(parent)
        self.wide, self.narrow = theme.px(232), theme.px(72)
        self.setFixedWidth(self.wide)
        self.pill = _Pill(self)                              # created first, so it sits behind the buttons
        self._y = Spring(0, 0.30, 1.0, precision=0.05, on_change=self._place_pill)
        self._key: str | None = None
        self._nav: list[str] = []                           # pages (not footer actions), in order
        self.buttons: dict[str, NavButton] = {}
        self._titles: list[Label] = []
        lay = QVBoxLayout(self)
        pad = theme.px(SPACE["s"])
        lay.setContentsMargins(0, theme.px(SPACE["m"]), 0, pad)
        lay.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(theme.px(SPACE["l"]), 0, pad, theme.px(SPACE["s"]))
        head.setSpacing(theme.px(10))
        self.mark = Brand()
        head.addWidget(self.mark)
        self.brand = Label("MediaForge", "brand")
        head.addWidget(self.brand, 1)
        self.menu_btn = MenuButton(menu, tip="More")
        head.addWidget(self.menu_btn)
        lay.addLayout(head)
        for title, items in sections:
            t = Label(title, "kicker", "label3")
            t.setContentsMargins(theme.px(SPACE["l"] + 4), theme.px(SPACE["l"]), 0, theme.px(SPACE["xs"]))
            self._titles.append(t)
            lay.addWidget(t)
            for key, label, icon in items:
                b = self._add(lay, key, label, icon, True)
                self._nav.append(key)
                b.clicked.connect(lambda _=False, k=key: self.select(k, animate=True))
                b.stepped.connect(lambda d, k=key: self._step(k, d))
        lay.addStretch(1)
        for key, label, icon in footer:
            b = self._add(lay, key, label, icon, False)
            b.clicked.connect(lambda _=False, k=key: self.action.emit(k))
        theme.changed.connect(self.update)

    def _add(self, lay, key: str, label: str, icon: str, checkable: bool) -> NavButton:
        b = NavButton(key, label, icon, checkable)
        self.buttons[key] = b
        lay.addWidget(b)
        return b

    # -- selection
    def current(self) -> str | None:
        return self._key

    def select(self, key: str, animate: bool = True) -> None:
        self._key = key
        for k in self._nav:
            self.buttons[k].setChecked(k == key)
        self._move_pill(animate)
        self.navigate.emit(key)

    def _step(self, key: str, d: int) -> None:
        i = self._nav.index(key) + d
        if 0 <= i < len(self._nav):
            self.select(self._nav[i], animate=False)        # keyboard navigation never animates
            self.buttons[self._nav[i]].setFocus()

    def _move_pill(self, animate: bool) -> None:
        if self._key is None:
            return
        g = self.buttons[self._key].geometry().adjusted(theme.px(10), theme.px(3), -theme.px(10), -theme.px(3))
        self.pill.setFixedSize(g.width(), g.height())
        self._x = g.x()
        self._y.to(g.y(), snap=not animate)
        self._place_pill()

    def _place_pill(self) -> None:
        self.pill.move(getattr(self, "_x", 0), round(self._y.value))

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._move_pill(False)
        QTimer.singleShot(0, lambda: self._move_pill(False))      # once more after the first layout pass

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._move_pill(False)

    # -- state shown on buttons
    def set_badge(self, key: str, n: int) -> None:
        self.buttons[key].badge = n
        self.buttons[key].update()

    def set_dot(self, key: str, on: bool) -> None:
        self.buttons[key].dot = on
        self.buttons[key].update()

    def set_compact(self, compact: bool) -> None:
        if compact == (self.width() == self.narrow):
            return
        self.setFixedWidth(self.narrow if compact else self.wide)
        for b in self.buttons.values():
            b.compact = compact
            b.setToolTip(b.label if compact else "")
            b.update()
        self.brand.setVisible(not compact)
        self.mark.setVisible(not compact)                  # the More menu keeps the narrow column
        for t in self._titles:
            t.setVisible(not compact)
        QTimer.singleShot(0, lambda: self._move_pill(False))      # after the layout drops the hidden labels

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), qc(theme.p.sidebar))
        p.fillRect(QRectF(self.width() - 1, 0, 1, self.height()), qc(theme.p.sep))

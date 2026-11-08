"""macOS-style sidebar: translucent material, a selection pill that slides on a spring, icon-only when narrow."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QFontMetrics, QPainter
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QVBoxLayout, QWidget

from .kit import Label, MenuButton, Spring, icons, qc
from .kit.controls import _KbFocus, _ring
from .kit.theme import RADIUS, SPACE, TARGET, theme


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
        r, rad = QRectF(self.rect()).adjusted(px(8), px(2), -px(8), -px(2)), px(RADIUS["m"])
        p.setPen(Qt.PenStyle.NoPen)
        if self._hover.value > 0.01 and not self.isChecked():
            p.setBrush(qc(pal.fill, self._hover.value * 0.7))
            p.drawRoundedRect(r, rad, rad)
        on = self.isChecked()
        isz = px(20)
        ix = r.center().x() - isz / 2 if self.compact else r.left() + px(12)
        icons.draw(p, self.icon_name, QRectF(ix, r.center().y() - isz / 2, isz, isz), pal.accent if on else pal.label2)
        if self.dot:
            p.setBrush(qc(pal.orange))
            p.drawEllipse(QRectF(ix + isz - px(4), r.center().y() - isz / 2 - px(2), px(9), px(9)))
        if self.compact:
            return
        p.setFont(theme.font("headline" if on else "body"))
        p.setPen(qc(pal.label))
        tx = ix + isz + px(10)
        p.drawText(QRectF(tx, r.top(), r.right() - tx - px(40), r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.label)
        if self.badge:
            text = str(self.badge)
            w = max(px(22), QFontMetrics(theme.font("caption")).horizontalAdvance(text) + px(14))
            pill = QRectF(r.right() - px(12) - w, r.center().y() - px(10), w, px(20))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qc(pal.accent))
            p.drawRoundedRect(pill, px(10), px(10))
            p.setFont(theme.font("caption"))
            p.setPen(qc((255, 255, 255)))
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
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qc(theme.p.accent, 0.26 if theme.dark else 0.14))
        rad = theme.px(RADIUS["m"])
        p.drawRoundedRect(QRectF(self.rect()), rad, rad)


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
        self.brand = Label("MediaForge", "headline")
        head.addWidget(self.brand, 1)
        self.menu_btn = MenuButton(menu, tip="More")
        head.addWidget(self.menu_btn)
        lay.addLayout(head)
        for title, items in sections:
            t = Label(title, "footnote", "label2")
            t.setContentsMargins(theme.px(SPACE["l"] + 4), theme.px(SPACE["m"]), 0, theme.px(2))
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
        g = self.buttons[self._key].geometry().adjusted(theme.px(8), theme.px(2), -theme.px(8), -theme.px(2))
        self.pill.setFixedSize(g.width(), g.height())
        self._x = g.x()
        self._y.to(g.y(), snap=not animate)
        self._place_pill()

    def _place_pill(self) -> None:
        self.pill.move(getattr(self, "_x", 0), round(self._y.value))

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._move_pill(False)

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
        for t in self._titles:
            t.setVisible(not compact)
        self._move_pill(False)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        c = theme.p.sidebar
        p.fillRect(self.rect(), qc(c if theme.backdrop else c[:3]))        # translucent only over Mica
        p.fillRect(QRectF(self.width() - 1, 0, 1, self.height()), qc(theme.p.sep))

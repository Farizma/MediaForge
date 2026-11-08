"""Sheets (modal cards that fade + rise in), alerts, and toasts."""
from __future__ import annotations

from PySide6.QtCore import QObject, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QDialog, QGraphicsDropShadowEffect, QHBoxLayout, QVBoxLayout, QWidget

from . import icons
from .controls import Button, Field
from .layout import Card, Label
from .motion import Spring, reduced_motion
from .theme import SPACE, qc, theme


class Sheet(QDialog):
    """Frameless rounded card. Put content in `self.body`. Exits instantly (exits are faster than entrances)."""

    def __init__(self, parent=None, title: str = "", width: int = 520) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.default_button: Button | None = None
        room = theme.px(36)                                             # space around the card for its shadow
        outer = QVBoxLayout(self)
        outer.setContentsMargins(room, room, room, room)
        self.card = Card("l")
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(theme.px(48))
        shadow.setOffset(0, theme.px(12))
        shadow.setColor(QColor(0, 0, 0, 110 if theme.dark else 70))
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card)
        self.body = QVBoxLayout(self.card)
        pad = theme.px(SPACE["xl"])
        self.body.setContentsMargins(pad, pad, pad, pad)
        self.body.setSpacing(theme.px(SPACE["l"]))
        if title:
            self.body.addWidget(Label(title, "title"))
        self.setFixedWidth(theme.px(width) + 2 * room)
        self._home = None
        self._rise = Spring(0, 0.30, 1.0, on_change=self._on_rise)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._home = self.pos()
        self.setWindowOpacity(0.0)
        self._rise.to(1.0)

    def _on_rise(self) -> None:
        v = max(0.0, min(1.0, self._rise.value))
        self.setWindowOpacity(v)
        if self._home is not None and not reduced_motion():
            self.move(self._home.x(), self._home.y() + round((1 - v) * theme.px(14)))

    def buttons(self, *buttons: Button, default: int | None = None) -> None:
        row = QHBoxLayout()
        row.setSpacing(theme.px(SPACE["s"]))
        row.addStretch(1)
        for b in buttons:
            row.addWidget(b)
        self.body.addLayout(row)
        if default is not None:
            self.default_button = buttons[default]
            self.default_button.setFocus()

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.default_button is not None:
            self.default_button.click()
        else:
            super().keyPressEvent(e)


def choose(parent, title: str, text: str, buttons: list, default: int = 0) -> int | None:
    """Alert with N buttons [(label, kind)]. Returns the clicked index, or None if dismissed with Esc."""
    sheet = Sheet(parent, title, 440)
    if text:
        sheet.body.addWidget(Label(text, "body", "label2", wrap=True))
    result: dict = {"i": None}

    def pick(i: int) -> None:
        result["i"] = i
        sheet.accept()

    made = []
    for i, (label, kind) in enumerate(buttons):
        b = Button(label, kind=kind)
        b.clicked.connect(lambda _=False, i=i: pick(i))
        made.append(b)
    sheet.buttons(*made, default=default)
    sheet.exec()
    return result["i"]


def alert(parent, title: str, text: str = "") -> None:
    choose(parent, title, text, [("OK", "primary")])


def confirm(parent, title: str, text: str = "", yes: str = "OK", no: str = "Cancel", destructive: bool = False) -> bool:
    return choose(parent, title, text, [(no, "secondary"), (yes, "destructive" if destructive else "primary")], default=1) == 1


def prompt(parent, title: str, label: str, text: str = "") -> str | None:
    sheet = Sheet(parent, title, 440)
    sheet.body.addWidget(Label(label, "body", "label2"))
    field = Field(text)
    sheet.body.addWidget(field)
    ok, cancel = Button("Save", kind="primary"), Button("Cancel")
    ok.clicked.connect(sheet.accept)
    cancel.clicked.connect(sheet.reject)
    field.returnPressed.connect(sheet.accept)
    sheet.buttons(cancel, ok, default=1)
    field.setFocus()
    return field.text() if sheet.exec() else None


class _Toast(QWidget):
    KINDS = {"info": ("info", "accent"), "success": ("check-circle", "green"),
             "error": ("x-circle", "red"), "warning": ("alert", "orange")}

    def __init__(self, host: QWidget, text: str, kind: str, action, ms: int, on_gone) -> None:
        super().__init__(host)
        self.text, self.kind, self.action, self.on_gone = text, kind, action, on_gone
        fm = QFontMetrics(theme.font("body"))
        self.pad, self.isz = theme.px(16), theme.px(20)
        self.tw = min(fm.horizontalAdvance(text), theme.px(420))
        self.aw = QFontMetrics(theme.font("headline")).horizontalAdvance(action[0]) if action else 0
        self.resize(self.pad * 2 + self.isz + theme.px(10) + self.tw + (self.aw + theme.px(20) if action else 0), theme.px(52))
        self.base = (0, 0)
        self.enter = Spring(0, 0.34, 1.0, on_change=self._place)
        self.enter.to(1.0)
        self.setAccessibleName(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        QTimer.singleShot(ms, self.dismiss)
        try:                                                            # screen readers announce it
            from PySide6.QtGui import QAccessible, QAccessibleEvent
            QAccessible.updateAccessibility(QAccessibleEvent(self, QAccessible.Event.Alert))
        except Exception:
            pass

    def place(self, x: int, y: int) -> None:
        self.base = (x, y)
        self._place()

    def _place(self) -> None:
        self.move(self.base[0], self.base[1] + round((1 - self.enter.value) * theme.px(20)))
        self.update()

    def dismiss(self) -> None:
        self.enter.to(0.0)
        QTimer.singleShot(260, self._gone)

    def _gone(self) -> None:
        self.on_gone(self)
        self.deleteLater()

    def mousePressEvent(self, e) -> None:
        if self.action and e.position().x() > self.width() - self.aw - theme.px(24):
            self.action[1]()
        self.dismiss()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(max(0.0, min(1.0, self.enter.value)))
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        rad = r.height() / 2
        p.setBrush(qc((0, 0, 0, 40)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(r.translated(0, 2), rad, rad)
        p.setBrush(qc(theme.p.card))
        p.setPen(QPen(qc(theme.p.sep), 1))
        p.drawRoundedRect(r, rad, rad)
        sym, tone = self.KINDS.get(self.kind, self.KINDS["info"])
        icons.draw(p, sym, QRectF(self.pad, (self.height() - self.isz) / 2, self.isz, self.isz), getattr(theme.p, tone))
        p.setFont(theme.font("body"))
        p.setPen(qc(theme.p.label))
        x = self.pad + self.isz + theme.px(10)
        shown = QFontMetrics(theme.font("body")).elidedText(self.text, Qt.TextElideMode.ElideRight, self.tw)
        p.drawText(QRectF(x, 0, self.tw + 4, self.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, shown)
        if self.action:
            p.setFont(theme.font("headline"))
            p.setPen(qc(theme.p.accent))
            p.drawText(QRectF(self.width() - self.aw - self.pad, 0, self.aw + 2, self.height()), Qt.AlignmentFlag.AlignCenter, self.action[0])


class Toaster(QObject):
    """Transient messages at the bottom centre of the window (replaces the status bar)."""

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.host, self.toasts = host, []

    def show(self, text: str, kind: str = "info", action=None, ms: int = 4500) -> None:
        if len(self.toasts) >= 3:
            self.toasts[0].dismiss()
        t = _Toast(self.host, text, kind, action, ms, self._remove)
        self.toasts.append(t)
        t.show()
        t.raise_()
        self.reposition()

    def _remove(self, toast) -> None:
        if toast in self.toasts:
            self.toasts.remove(toast)
        self.reposition()

    def reposition(self) -> None:
        y = self.host.height() - theme.px(20)
        for t in reversed(self.toasts):
            y -= t.height()
            t.place((self.host.width() - t.width()) // 2, y)
            y -= theme.px(8)

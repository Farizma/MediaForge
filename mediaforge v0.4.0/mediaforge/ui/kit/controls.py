"""Controls sharing one contract: value() / setValue() / changed. 44-px hit targets, spring feedback."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QIntValidator, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QFileDialog, QHBoxLayout, QLineEdit, QMenu, QPlainTextEdit, QWidget,
)

from . import icons
from .motion import Spring
from .theme import RADIUS, TARGET, mix, qc, theme




class _KbFocus:
    """Remember whether focus arrived by keyboard, so the focus ring only shows then."""
    _kb = False

    def focusInEvent(self, e) -> None:
        self._kb = e.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason)
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e) -> None:
        self._kb = False
        super().focusOutEvent(e)
        self.update()


def _ring(p: QPainter, r: QRectF, radius: float) -> None:
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(qc(theme.p.accent, 0.65), 2))
    p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), radius + 2, radius + 2)


class Button(_KbFocus, QAbstractButton):
    """kind: primary (filled) | secondary (tinted) | plain (text only) | destructive."""

    def __init__(self, text: str = "", icon: str | None = None, kind: str = "secondary", parent=None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.icon_name, self.kind = icon, kind
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(theme.px(TARGET))
        self._press = Spring(0, 0.16, 1.0, on_change=self.update)     # responds on press-down, not on click
        self._hover = Spring(0, 0.20, 1.0, on_change=self.update)
        self.pressed.connect(lambda: self._press.to(1))
        self.released.connect(lambda: self._press.to(0))
        theme.changed.connect(self.update)

    def _font(self):
        return theme.font("headline" if self.kind == "primary" else "body")

    def _colors(self) -> tuple:
        p = theme.p
        return {"primary": (p.accent, (255, 255, 255)), "secondary": (p.fill, p.label),
                "plain": (None, p.accent), "destructive": (p.fill, p.red)}[self.kind]

    def sizeHint(self) -> QSize:
        text = self.text()
        w = QFontMetrics(self._font()).horizontalAdvance(text) + theme.px(32) if text else 0
        if self.icon_name:
            w += theme.px(24) if text else 0
        return QSize(max(w, theme.px(TARGET)), theme.px(TARGET))

    def enterEvent(self, e) -> None:
        self._hover.to(1)
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._hover.to(0)
        super().leaveEvent(e)

    def _content(self, p: QPainter, r: QRectF, fg: tuple) -> None:
        isz, text = theme.px(18), self.text()
        fm = QFontMetrics(self._font())
        tw = fm.horizontalAdvance(text) if text else 0
        gap = theme.px(6) if text and self.icon_name else 0
        x = r.center().x() - ((isz if self.icon_name else 0) + gap + tw) / 2
        if self.icon_name:
            icons.draw(p, self.icon_name, QRectF(x, r.center().y() - isz / 2, isz, isz), fg)
            x += isz + gap
        if text:
            p.setPen(qc(fg))
            p.setFont(self._font())
            p.drawText(QRectF(x, r.top(), tw + 2, r.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 4, -2, -4)          # drawn pill sits inside the 44-px hit area
        c, s = r.center(), 1 - 0.03 * self._press.value          # press = scale 0.97
        p.translate(c)
        p.scale(s, s)
        p.translate(-c.x(), -c.y())
        p.setOpacity(1.0 if self.isEnabled() else 0.4)
        fill, fg = self._colors()
        rad = theme.px(RADIUS["m"])
        p.setPen(Qt.PenStyle.NoPen)
        if fill:
            p.setBrush(qc(fill))
            p.drawRoundedRect(r, rad, rad)
        if self._hover.value > 0.01:
            p.setBrush(qc(theme.p.fill, self._hover.value))
            p.drawRoundedRect(r, rad, rad)
        self._content(p, r, fg)
        if self._kb:
            _ring(p, r, rad)


class IconButton(Button):
    def __init__(self, icon: str, tip: str = "", kind: str = "plain", parent=None) -> None:
        super().__init__("", icon, kind, parent)
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        self.setFixedSize(theme.px(TARGET), theme.px(TARGET))


class Switch(_KbFocus, QAbstractButton):
    changed = Signal()

    def __init__(self, checked: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(theme.px(56), theme.px(TARGET))
        self._pos = Spring(1.0 if checked else 0.0, 0.25, 1.0, on_change=self.update)
        self.toggled.connect(self._on_toggled)
        theme.changed.connect(self.update)

    def _on_toggled(self, on: bool) -> None:
        self._pos.to(1.0 if on else 0.0)
        self.changed.emit()

    def value(self) -> bool:
        return self.isChecked()

    def setValue(self, v) -> None:
        self.setChecked(bool(v))

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = theme.px(51), theme.px(31)
        track = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
        p.setOpacity(1.0 if self.isEnabled() else 0.4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(mix(theme.p.fill, theme.p.green, max(0.0, min(1.0, self._pos.value))))
        p.drawRoundedRect(track, h / 2, h / 2)
        d = h - theme.px(4)
        x = track.left() + theme.px(2) + (w - d - theme.px(4)) * self._pos.value
        p.setBrush(qc((0, 0, 0, 30)))
        p.drawEllipse(QRectF(x - 0.5, track.top() + theme.px(2) + 1, d + 1, d + 1))     # soft edge
        p.setBrush(qc((255, 255, 255)))
        p.drawEllipse(QRectF(x, track.top() + theme.px(2), d, d))
        if self._kb:
            _ring(p, track, h / 2)


class Segmented(_KbFocus, QWidget):
    """iOS segmented control; the thumb is a spring that can be redirected mid-flight."""
    changed = Signal()

    def __init__(self, items=(), parent=None) -> None:
        super().__init__(parent)
        self._items: list = []
        self._idx = 0
        self.animated = True                                     # last change came from the pointer
        self._thumb = Spring(0, 0.28, 1.0, on_change=self.update)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(theme.px(TARGET))
        for label, data in items:
            self.addItem(label, data)
        theme.changed.connect(self.update)

    def addItem(self, label: str, data=None) -> None:
        self._items.append((label, label if data is None else data))
        self.updateGeometry()

    def currentIndex(self) -> int:
        return self._idx

    def value(self):
        return self._items[self._idx][1] if self._items else None

    def setValue(self, v) -> None:
        for i, (_, d) in enumerate(self._items):
            if d == v:
                self.setCurrentIndex(i, animate=False)

    def setCurrentIndex(self, i: int, animate: bool = True) -> None:
        if not 0 <= i < len(self._items) or i == self._idx:
            return
        self._idx, self.animated = i, animate
        self._thumb.to(i, snap=not animate)
        self.update()
        self.changed.emit()

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(theme.font("headline"))
        widest = max((fm.horizontalAdvance(l) for l, _ in self._items), default=40)
        return QSize((widest + theme.px(32)) * max(1, len(self._items)), theme.px(TARGET))

    def mousePressEvent(self, e) -> None:                        # select on press-down
        if self._items:
            self.setCurrentIndex(min(len(self._items) - 1, int(e.position().x() / (self.width() / len(self._items)))))

    def keyPressEvent(self, e) -> None:
        step = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1}.get(e.key())
        if step:
            self.setCurrentIndex(self._idx + step, animate=False)     # keyboard changes never animate
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _) -> None:
        if not self._items:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n, h = len(self._items), theme.px(32)
        track = QRectF(0, (self.height() - h) / 2, self.width(), h)
        rad = theme.px(RADIUS["m"])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qc(theme.p.fill))
        p.drawRoundedRect(track, rad, rad)
        seg = track.width() / n
        thumb = QRectF(track.left() + 2 + seg * self._thumb.value, track.top() + 2, seg - 4, h - 4)
        p.setBrush(qc((0, 0, 0, 22)))
        p.drawRoundedRect(thumb.translated(0, 1), rad - 2, rad - 2)
        p.setBrush(qc(theme.p.thumb))
        p.drawRoundedRect(thumb, rad - 2, rad - 2)
        for i, (label, _) in enumerate(self._items):
            p.setFont(theme.font("headline" if i == self._idx else "body"))
            p.setPen(qc(theme.p.label if i == self._idx else theme.p.label2))
            p.drawText(QRectF(track.left() + seg * i, track.top(), seg, h), Qt.AlignmentFlag.AlignCenter, label)
        if self._kb:
            _ring(p, track, rad)


class Menu(QMenu):
    """Rounded pop-up (needs a translucent frameless window for the corners to show)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


class Picker(Button):
    """Pop-up button (macOS 'pop-up menu'). Items hold arbitrary Python data."""
    changed = Signal()
    currentIndexChanged = Signal(int)

    def __init__(self, items=(), parent=None) -> None:
        super().__init__("", None, "secondary", parent)
        self._items: list[dict] = []
        self._seps: set[int] = set()
        self._idx = -1
        self.setMinimumWidth(theme.px(160))
        for label, data in items:
            self.addItem(label, data)
        self.clicked.connect(self._popup)

    # -- model
    def addItem(self, label: str, data=None) -> None:
        self._items.append({"label": label, "data": data, "enabled": True, "tip": ""})
        if self._idx < 0:
            self._idx = 0
            self.setText(label)

    def addSeparator(self) -> None:
        self._seps.add(len(self._items))

    def clear(self) -> None:
        self._items, self._seps, self._idx = [], set(), -1
        self.setText("")

    def count(self) -> int:
        return len(self._items)

    def currentIndex(self) -> int:
        return self._idx

    def currentData(self):
        return self._items[self._idx]["data"] if self._idx >= 0 else None

    def currentText(self) -> str:
        return self._items[self._idx]["label"] if self._idx >= 0 else ""

    def itemData(self, i: int):
        return self._items[i]["data"]

    def findData(self, data) -> int:
        for i, it in enumerate(self._items):
            if it["data"] == data and isinstance(it["data"], bool) == isinstance(data, bool):   # 30 == 30.0, but 1 != True
                return i
        return -1

    def setItemEnabled(self, i: int, ok: bool, tip: str = "") -> None:
        self._items[i]["enabled"], self._items[i]["tip"] = ok, tip

    def setCurrentIndex(self, i: int, notify: bool = True) -> None:
        if not 0 <= i < len(self._items) or i == self._idx:
            return
        self._idx = i
        self.setText(self._items[i]["label"])
        self.update()
        if notify:
            self.currentIndexChanged.emit(i)
            self.changed.emit()

    def value(self):
        return self.currentData()

    def setValue(self, v) -> None:
        i = self.findData(v)
        if i >= 0:
            self.setCurrentIndex(i)

    # -- look
    def sizeHint(self) -> QSize:
        fm = QFontMetrics(theme.font("body"))
        widest = max((fm.horizontalAdvance(it["label"]) for it in self._items), default=60)
        return QSize(max(theme.px(160), widest + theme.px(56)), theme.px(TARGET))

    def _content(self, p: QPainter, r: QRectF, fg: tuple) -> None:
        pad, isz = theme.px(12), theme.px(16)
        p.setFont(theme.font("body"))
        p.setPen(qc(fg))
        room = r.width() - pad * 2 - isz - theme.px(4)
        text = QFontMetrics(theme.font("body")).elidedText(self.text(), Qt.TextElideMode.ElideRight, int(room))
        p.drawText(QRectF(r.left() + pad, r.top(), room, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        icons.draw(p, "chevrons", QRectF(r.right() - pad - isz, r.center().y() - isz / 2, isz, isz), theme.p.label2)

    def _popup(self) -> None:
        menu = Menu(self)
        for i, it in enumerate(self._items):
            if i in self._seps:
                menu.addSeparator()
            act = menu.addAction(("\u2713  " if i == self._idx else "\u2003  ") + it["label"])
            act.setEnabled(it["enabled"])
            if it["tip"]:
                act.setToolTip(it["tip"])
            act.triggered.connect(lambda _=False, i=i: self.setCurrentIndex(i))
        menu.exec(self.mapToGlobal(QPoint(0, self.height() - 4)))


class Field(QLineEdit):
    changed = Signal()

    def __init__(self, text: str = "", placeholder: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setPlaceholderText(placeholder)
        self.setMinimumHeight(theme.px(TARGET))
        self.textChanged.connect(lambda *_: self.changed.emit())

    def value(self) -> str:
        return self.text()

    def setValue(self, v) -> None:
        self.setText("" if v is None else str(v))


class TextArea(QPlainTextEdit):
    changed = Signal()

    def __init__(self, placeholder: str = "", readonly: bool = False, mono: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setReadOnly(readonly)
        if mono:
            self.setFont(theme.font("mono"))
        self.textChanged.connect(lambda: self.changed.emit())

    def value(self) -> str:
        return self.toPlainText()

    def setValue(self, v) -> None:
        self.setPlainText("" if v is None else str(v))


class EditPicker(QWidget):
    """Text field with a suggestion menu (bitrate, file-name template)."""
    changed = Signal()

    def __init__(self, items=(), placeholder: str = "", parent=None) -> None:
        super().__init__(parent)
        self.items = list(items)
        self.field = Field(placeholder=placeholder)
        self.btn = IconButton("chevron-down", "Suggestions")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.px(4))
        lay.addWidget(self.field, 1)
        lay.addWidget(self.btn)
        self.btn.clicked.connect(self._popup)
        self.field.changed.connect(self.changed.emit)

    def value(self) -> str:
        return self.field.text()

    def setValue(self, v) -> None:
        self.field.setText("" if v is None else str(v))

    def _popup(self) -> None:
        menu = Menu(self)
        for text in self.items:
            menu.addAction(text).triggered.connect(lambda _=False, t=text: self.field.setText(t))
        menu.exec(self.mapToGlobal(QPoint(0, self.height() - 4)))


class Stepper(QWidget):
    """[-] value [+]; the number is typeable. `changed` fires only for user edits."""
    changed = Signal()

    def __init__(self, lo: int = 0, hi: int = 99, value: int | None = None, parent=None) -> None:
        super().__init__(parent)
        self.lo, self.hi = lo, hi
        self._v = lo if value is None else value
        self.edit = Field(str(self._v))
        self.edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.edit.setFixedWidth(theme.px(72))
        self.edit.setValidator(QIntValidator(lo, hi))
        self.minus, self.plus = IconButton("minus", "Decrease"), IconButton("plus", "Increase")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.px(4))
        for w in (self.minus, self.edit, self.plus):
            lay.addWidget(w)
        self.minus.clicked.connect(lambda: self._bump(-1))
        self.plus.clicked.connect(lambda: self._bump(1))
        self.edit.textEdited.connect(self._typed)
        self.edit.editingFinished.connect(lambda: self.edit.setText(str(self._v)))

    def _clamp(self, v: int) -> int:
        return max(self.lo, min(self.hi, int(v)))

    def value(self) -> int:
        return self._v

    def setValue(self, v) -> None:
        self._v = self._clamp(v)
        self.edit.setText(str(self._v))

    def _bump(self, d: int) -> None:
        self.setValue(self._v + d)
        self.changed.emit()

    def _typed(self, text: str) -> None:
        try:
            self._v = self._clamp(int(text))
        except ValueError:
            return
        self.changed.emit()


class PathField(QWidget):
    """Text field + Browse button. mode: dir | open | save."""
    changed = Signal()

    def __init__(self, mode: str = "dir", filter: str = "", placeholder: str = "", parent=None) -> None:
        super().__init__(parent)
        self.mode, self.filter = mode, filter
        self.field = Field(placeholder=placeholder)
        self.btn = IconButton("folder", "Browse...")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.px(4))
        lay.addWidget(self.field, 1)
        lay.addWidget(self.btn)
        self.btn.clicked.connect(self._browse)
        self.field.changed.connect(self.changed.emit)

    def value(self) -> str:
        return self.field.text()

    def setValue(self, v) -> None:
        self.field.setText("" if v is None else str(v))

    def _browse(self) -> None:
        cur = self.field.text()
        if self.mode == "dir":
            path = QFileDialog.getExistingDirectory(self, "Choose a folder", cur)
        elif self.mode == "save":
            path, _ = QFileDialog.getSaveFileName(self, "Choose a file", cur, self.filter)
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Choose a file", cur, self.filter)
        if path:
            self.field.setText(path)


class MenuButton(IconButton):
    """Icon button that opens a menu. actions: [(label, callback) | None for a separator]."""

    def __init__(self, actions: list, icon: str = "more", tip: str = "More", parent=None) -> None:
        super().__init__(icon, tip, "plain", parent)
        self.actions_spec = actions
        self.clicked.connect(self._popup)

    def _popup(self) -> None:
        menu = Menu(self)
        for spec in self.actions_spec:
            if spec is None:
                menu.addSeparator()
            else:
                menu.addAction(spec[0]).triggered.connect(lambda _=False, cb=spec[1]: cb())
        menu.exec(self.mapToGlobal(QPoint(0, self.height() - 4)))


class ProgressBar(QWidget):
    """Thin pill whose fill eases toward the value; total=0 means 'unknown' (a gentle sweep)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(theme.px(8))
        self._v = Spring(0, 0.4, 1.0, precision=0.05, on_change=self.update)
        theme.changed.connect(self.update)

    def setValue(self, pct: float) -> None:
        self._v.to(max(0.0, min(100.0, pct)))

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qc(theme.p.fill))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setBrush(qc(theme.p.accent))
        p.drawRoundedRect(QRectF(0, 0, max(r.height(), r.width() * self._v.value / 100), r.height()), r.height() / 2, r.height() / 2)

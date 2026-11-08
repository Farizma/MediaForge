"""Reusable containers (the ViewModifier equivalents): every screen is built from these."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QBoxLayout, QFrame, QHBoxLayout, QLabel, QListWidget, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from . import icons
from .controls import Button, Segmented
from .motion import fade_in
from .theme import RADIUS, SPACE, TARGET, css, qc, theme


class Label(QLabel):
    """Text in a Dynamic-Type role and a semantic tone (label, label2, label3, accent, green, orange, red)."""

    def __init__(self, text: str = "", role: str = "body", tone: str = "label", wrap: bool = False, parent=None) -> None:
        super().__init__(text, parent)
        self.role, self.tone = role, tone
        self.setWordWrap(wrap)
        self._style()
        theme.changed.connect(self._style)

    def _style(self) -> None:
        self.setFont(theme.font(self.role))
        self.setStyleSheet(f"color:{css(getattr(theme.p, self.tone))}; background:transparent;")

    def setTone(self, tone: str) -> None:
        if tone != self.tone:
            self.tone = tone
            self._style()


class Card(QFrame):
    def __init__(self, radius: str = "l", parent=None) -> None:
        super().__init__(parent)
        self._radius = radius
        theme.changed.connect(self.update)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rad = theme.px(RADIUS[self._radius])
        p.setBrush(qc(theme.p.card))
        p.setPen(QPen(qc(theme.p.sep), 1))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)


class Hairline(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(1)

    def paintEvent(self, _) -> None:
        inset = theme.px(SPACE["l"])
        QPainter(self).fillRect(QRectF(inset, 0, self.width() - inset, 1), qc(theme.p.sep))


class Row(QWidget):
    """A form row, at least 44 px tall: label (+ hint) on the left, control on the right.
    wide=True stacks the control under the label (fields, paths) so narrow windows still work."""

    def __init__(self, label: str, control: QWidget | None = None, hint: str = "", wide: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.control = control
        self.label, self.hint = Label(label, "body"), Label(hint, "footnote", "label2", wrap=True)
        self.hint.setVisible(bool(hint))
        pad = theme.px(SPACE["l"])
        outer = QHBoxLayout(self) if not wide else QVBoxLayout(self)
        outer.setContentsMargins(pad, theme.px(SPACE["s"]), pad, theme.px(SPACE["s"]))
        outer.setSpacing(theme.px(SPACE["m"]) if not wide else theme.px(SPACE["xs"]))
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(self.label)
        text.addWidget(self.hint)
        outer.addLayout(text, 1) if not wide else outer.addLayout(text)
        if control is not None:
            outer.addWidget(control) if wide else outer.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setMinimumHeight(theme.px(TARGET))

    def setEnabled(self, on: bool) -> None:
        super().setEnabled(on)
        self.label.setTone("label" if on else "label3")


class Group(QWidget):
    """Inset grouped list: optional title above, rows inside a rounded card, optional footer below."""

    def __init__(self, title: str = "", footer: str = "", parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(theme.px(SPACE["s"]))
        if title:
            t = Label(title, "footnote", "label2")
            t.setContentsMargins(theme.px(SPACE["l"]), 0, 0, 0)
            outer.addWidget(t)
        self.card = Card()
        self.body = QVBoxLayout(self.card)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)
        outer.addWidget(self.card)
        if footer:
            f = Label(footer, "footnote", "label2", wrap=True)
            f.setContentsMargins(theme.px(SPACE["l"]), 0, theme.px(SPACE["l"]), 0)
            outer.addWidget(f)

    def add(self, widget: QWidget) -> QWidget:
        if self.body.count():
            self.body.addWidget(Hairline())
        self.body.addWidget(widget)
        return widget


class Stack(QWidget):
    """Vertical stack of widgets with HIG spacing."""

    def __init__(self, *widgets: QWidget, spacing: str = "xl", parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.px(SPACE[spacing]))
        for w in widgets:
            lay.addWidget(w)
        lay.addStretch(1)
        self.lay = lay


class Page(QScrollArea):
    """Scrolling screen with a large title."""

    def __init__(self, title: str, subtitle: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.viewport().setAutoFillBackground(False)
        root = QWidget()
        self.col = QVBoxLayout(root)
        m = theme.px(SPACE["xl"])
        self.col.setContentsMargins(m, theme.px(SPACE["l"]), m, m)
        self.col.setSpacing(theme.px(SPACE["xl"]))
        head = QVBoxLayout()
        head.setSpacing(theme.px(2))
        head.addWidget(Label(title, "largeTitle"))
        if subtitle:
            head.addWidget(Label(subtitle, "body", "label2"))
        self.col.addLayout(head)
        self.setWidget(root)

    def add(self, widget: QWidget | QBoxLayout, stretch: int = 0) -> None:
        self.col.addLayout(widget, stretch) if isinstance(widget, QBoxLayout) else self.col.addWidget(widget, stretch)


class AdaptiveSplit(QWidget):
    """Two panes side by side when there is room, stacked when there isn't (the 'Layout protocol' idea)."""

    def __init__(self, first: QWidget, second: QWidget, breakpoint: int = 1000, ratio: tuple = (2, 3), parent=None) -> None:
        super().__init__(parent)
        self.breakpoint = breakpoint
        self.lay = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(theme.px(SPACE["xl"]))
        self.lay.addWidget(first, ratio[0], Qt.AlignmentFlag.AlignTop)
        self.lay.addWidget(second, ratio[1], Qt.AlignmentFlag.AlignTop)

    def resizeEvent(self, e) -> None:
        want = QBoxLayout.Direction.LeftToRight if self.width() >= theme.px(self.breakpoint) else QBoxLayout.Direction.TopToBottom
        if self.lay.direction() != want:
            self.lay.setDirection(want)
        super().resizeEvent(e)


class Pager(QWidget):
    """Segmented control + pages. Pointer changes cross-fade; keyboard changes snap."""

    def __init__(self, pages: list, parent=None) -> None:
        super().__init__(parent)
        self.seg, self.stack = Segmented(), QStackedWidget()
        for title, widget in pages:
            self.seg.addItem(title)
            self.stack.addWidget(widget)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.px(SPACE["l"]))
        lay.addWidget(self.seg)
        lay.addWidget(self.stack)
        self.seg.changed.connect(self._switch)

    def _switch(self) -> None:
        i = self.seg.currentIndex()
        self.stack.setCurrentIndex(i)
        if self.seg.animated:
            fade_in(self.stack.widget(i), 150)


class ActionBar(QWidget):
    """Warnings, a collapsible command preview, and the screen's one primary action."""

    def __init__(self, action: str, icon: str, parent=None) -> None:
        super().__init__(parent)
        from .controls import TextArea
        self.warn = Label("", "callout", "orange", wrap=True)
        self.warn.hide()
        self.cmd = TextArea(readonly=True, mono=True)
        self.cmd.setMaximumHeight(theme.px(104))
        self.cmd.hide()
        self.toggle = Button("Show command", "chevron-right", "plain")
        self.primary = Button(action, icon, "primary")
        self.toggle.clicked.connect(self._toggle)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.px(SPACE["s"]))
        lay.addWidget(self.warn)
        lay.addWidget(self.cmd)
        row = QHBoxLayout()
        row.addWidget(self.toggle)
        row.addStretch(1)
        row.addWidget(self.primary)
        lay.addLayout(row)

    def _toggle(self) -> None:
        show = not self.cmd.isVisible()
        self.cmd.setVisible(show)
        self.toggle.setText("Hide command" if show else "Show command")
        self.toggle.icon_name = "chevron-down" if show else "chevron-right"
        self.toggle.update()

    def set_preview(self, text: str) -> None:
        self.cmd.setPlainText(text)

    def set_warnings(self, lines: list) -> None:
        self.warn.setText("\n".join(lines))
        self.warn.setVisible(bool(lines))


class DropList(QListWidget):
    """File list: accepts files dragged in from Explorer; optionally drag-to-reorder."""
    files_dropped = Signal(list)
    order_changed = Signal()

    def __init__(self, reorder: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.reorder = reorder
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.setMinimumHeight(theme.px(TARGET * 4))
        if reorder:
            self.setDragEnabled(True)
            self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
            self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, e) -> None:
        e.acceptProposedAction() if e.mimeData().hasUrls() else super().dragEnterEvent(e)

    def dragMoveEvent(self, e) -> None:
        e.acceptProposedAction() if e.mimeData().hasUrls() else super().dragMoveEvent(e)

    def dropEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            if paths:
                self.files_dropped.emit(paths)
            e.acceptProposedAction()
        else:
            super().dropEvent(e)
            self.order_changed.emit()


class EmptyState(QWidget):
    def __init__(self, icon: str, title: str, subtitle: str = "", parent=None) -> None:
        super().__init__(parent)
        self.icon_name, self.title, self.subtitle = icon, title, subtitle
        theme.changed.connect(self.update)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy, isz = self.width() / 2, self.height() / 2, theme.px(40)
        icons.draw(p, self.icon_name, QRectF(cx - isz / 2, cy - isz - theme.px(8), isz, isz), theme.p.label3)
        p.setFont(theme.font("headline"))
        p.setPen(qc(theme.p.label2))
        p.drawText(QRectF(0, cy, self.width(), theme.px(24)), Qt.AlignmentFlag.AlignCenter, self.title)
        if self.subtitle:
            p.setFont(theme.font("callout"))
            p.setPen(qc(theme.p.label3))
            p.drawText(QRectF(0, cy + theme.px(26), self.width(), theme.px(22)), Qt.AlignmentFlag.AlignCenter, self.subtitle)

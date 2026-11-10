from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..kit import Label, TextArea
from ..kit.theme import SPACE, theme


class LogPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        m = theme.px(SPACE["xl"])
        lay.setContentsMargins(m, theme.px(SPACE["l"]), m, m)
        lay.setSpacing(theme.px(SPACE["m"]))
        lay.addWidget(Label("Log", "largeTitle"))
        lay.addWidget(Label("The commands that ran and everything the tools said.", "body", "label2"))
        self.text = TextArea(readonly=True, mono=True)
        self.text.setMaximumBlockCount(5000)
        lay.addWidget(self.text, 1)

    def append(self, line: str) -> None:
        self.text.appendPlainText(line)

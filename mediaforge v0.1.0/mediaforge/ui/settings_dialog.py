from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ..core import binaries
from ..core.settings import Settings


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(560)
        self.settings = settings

        self.ffmpeg = QLineEdit(settings.ffmpeg_path)
        self.ffprobe = QLineEdit(settings.ffprobe_path)
        self.outdir = QLineEdit(settings.output_dir)
        for le, ph in ((self.ffmpeg, "Leave empty to auto-detect (PATH or ./bin)"),
                       (self.ffprobe, "Leave empty to auto-detect"),
                       (self.outdir, "Leave empty to save next to each input file")):
            le.setPlaceholderText(ph)
        self.ffmpeg_status = QLabel()
        self.ffprobe_status = QLabel()
        self.parallel = QSpinBox()
        self.parallel.setRange(1, 8)
        self.parallel.setValue(settings.max_parallel)
        self.parallel.setToolTip("How many jobs may run at the same time")
        self.retries = QSpinBox()
        self.retries.setRange(0, 5)
        self.retries.setValue(settings.max_retries)
        self.retries.setToolTip("Run a failed job again automatically this many times (0 = never)")

        form = QFormLayout()
        form.addRow("ffmpeg:", self._row(self.ffmpeg, self._pick_file))
        form.addRow("", self.ffmpeg_status)
        form.addRow("ffprobe:", self._row(self.ffprobe, self._pick_file))
        form.addRow("", self.ffprobe_status)
        form.addRow("Default output folder:", self._row(self.outdir, self._pick_dir))
        form.addRow("Parallel jobs:", self.parallel)
        form.addRow("Auto-retry failed jobs:", self.retries)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)

        self.ffmpeg.editingFinished.connect(self._refresh_status)
        self.ffprobe.editingFinished.connect(self._refresh_status)
        self._refresh_status()

    def _row(self, edit: QLineEdit, picker) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        btn = QPushButton("Browse...")
        btn.clicked.connect(lambda: picker(edit))
        h.addWidget(edit, 1)
        h.addWidget(btn)
        return w

    def _pick_file(self, edit: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select executable")
        if path:
            edit.setText(path)
            self._refresh_status()

    def _pick_dir(self, edit: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select folder")
        if path:
            edit.setText(path)

    def _refresh_status(self) -> None:
        for name, edit, label in (("ffmpeg", self.ffmpeg, self.ffmpeg_status),
                                  ("ffprobe", self.ffprobe, self.ffprobe_status)):
            exe = binaries.find(name, edit.text().strip())
            if exe:
                label.setText(f"Found: {exe}\n{binaries.version(exe)}")
                label.setStyleSheet("color: #2e9e4f;")
            else:
                label.setText("Not found")
                label.setStyleSheet("color: #d64545;")

    def accept(self) -> None:
        self.settings.ffmpeg_path = self.ffmpeg.text().strip()
        self.settings.ffprobe_path = self.ffprobe.text().strip()
        self.settings.output_dir = self.outdir.text().strip()
        self.settings.max_parallel = self.parallel.value()
        self.settings.max_retries = self.retries.value()
        super().accept()

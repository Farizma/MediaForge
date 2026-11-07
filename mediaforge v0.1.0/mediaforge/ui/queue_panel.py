"""Table showing every job (ffmpeg, join, yt-dlp) with progress and controls."""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QMessageBox, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core.jobs import Job, JobManager, JobStatus


class QueuePanel(QWidget):
    COLUMNS = ["Name", "Type", "Status", "Progress", "Details"]

    def __init__(self, manager: JobManager) -> None:
        super().__init__()
        self.manager = manager
        self._rows: list[Job] = []

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 160)
        self.table.itemSelectionChanged.connect(self._sync_buttons)

        def button(text, slot, tip=""):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            return b

        self.pause_btn = button("Pause", self._toggle_pause,
                                "Pause the selected job. Conversions freeze in place; downloads stop and "
                                "continue from the partial file when resumed.")
        self.cancel_btn = button("Cancel", lambda: self._with_selected(lambda j: j.cancel()))
        self.retry_btn = button("Retry", lambda: self._with_selected(self.manager.retry),
                                "Start a failed or cancelled job again")
        self.folder_btn = button("Show output folder", lambda: self._with_selected(self._open_folder))
        self.pause_all_btn = button("Pause all", self.manager.pause_all)
        self.resume_all_btn = button("Resume all", self.manager.resume_all)
        self.retry_failed_btn = button("Retry failed", self._retry_failed)
        self.clear_btn = button("Clear finished", self.manager.clear_finished)

        row = QHBoxLayout()
        for b in (self.pause_btn, self.cancel_btn, self.retry_btn, self.folder_btn):
            row.addWidget(b)
        row.addStretch(1)
        for b in (self.pause_all_btn, self.resume_all_btn, self.retry_failed_btn, self.clear_btn):
            row.addWidget(b)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.table)
        lay.addLayout(row)

        manager.job_added.connect(self._add_row)
        manager.job_changed.connect(self._update_job)
        manager.jobs_cleared.connect(self._rebuild)
        self._sync_buttons()

    # -- helpers
    def _selected(self) -> Job | None:
        r = self.table.currentRow()
        return self._rows[r] if 0 <= r < len(self._rows) and self.table.selectedItems() else None

    def _with_selected(self, fn) -> None:
        job = self._selected()
        if job:
            fn(job)

    def _toggle_pause(self) -> None:
        job = self._selected()
        if job is None:
            return
        if job.status is JobStatus.PAUSED:
            self.manager.resume(job)
        else:
            self.manager.pause(job)

    def _retry_failed(self) -> None:
        if self.manager.retry_failed() == 0:
            QMessageBox.information(self, "Retry failed", "There are no failed jobs.")

    @staticmethod
    def _open_folder(job: Job) -> None:
        folder = job.open_path()
        if folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _sync_buttons(self) -> None:
        job = self._selected()
        st = job.status if job else None
        self.pause_btn.setText("Resume" if st is JobStatus.PAUSED else "Pause")
        self.pause_btn.setEnabled(st in (JobStatus.RUNNING, JobStatus.QUEUED, JobStatus.PAUSED))
        self.cancel_btn.setEnabled(st is not None and not st.finished)
        self.retry_btn.setEnabled(st in (JobStatus.FAILED, JobStatus.CANCELLED))
        self.folder_btn.setEnabled(job is not None)

    # -- table
    def _add_row(self, job: Job) -> None:
        row = len(self._rows)
        self._rows.append(job)
        self.table.insertRow(row)
        for col, text in enumerate((job.title, job.kind, "", None, "")):
            if text is not None:
                self.table.setItem(row, col, QTableWidgetItem(text))
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setCellWidget(row, 3, bar)
        self._update_row(row, job)

    def _update_job(self, job: Job) -> None:
        if job in self._rows:
            self._update_row(self._rows.index(job), job)
            if job is self._selected():
                self._sync_buttons()

    def _update_row(self, row: int, job: Job) -> None:
        self.table.item(row, 0).setText(job.title)
        self.table.item(row, 2).setText(job.status.value)
        self.table.item(row, 4).setText(job.detail)
        self.table.item(row, 4).setToolTip(job.detail)
        self.table.cellWidget(row, 3).setValue(int(job.progress))

    def _rebuild(self) -> None:
        self.table.setRowCount(0)
        self._rows = []
        for job in self.manager.jobs:
            self._add_row(job)
        self._sync_buttons()

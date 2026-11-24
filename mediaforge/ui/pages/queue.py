"""Queue: every job (convert, join, download) in one virtualised list with spring-smoothed progress."""
from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QMimeData, QModelIndex, QRectF, QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFontMetrics, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QListView, QStackedWidget, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from ...core.jobs import Job, JobManager, JobStatus
from ..kit import Button, EmptyState, Label, MenuButton, Spring, alert, qc
from ..kit import icons
from ..kit.theme import RADIUS, SPACE, theme

S = JobStatus
MIME = "application/x-mediaforge-job"
MOVABLE = (S.QUEUED, S.PAUSED)                     # jobs that haven't run yet (or are on hold) can be reordered
LOOK = {S.QUEUED: ("clock", "label3"), S.RUNNING: ("play-circle", "accent"), S.PAUSED: ("pause-circle", "orange"),
        S.DONE: ("check-circle", "green"), S.FAILED: ("x-circle", "red"), S.CANCELLED: ("x-circle", "label3")}


class JobModel(QAbstractListModel):
    def __init__(self, manager: JobManager) -> None:
        super().__init__()
        self.m = manager
        self._shown: dict[int, Spring] = {}
        manager.job_added.connect(self._added)
        manager.job_changed.connect(self._changed)
        manager.jobs_cleared.connect(self._reset)

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.m.jobs)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.UserRole and 0 <= index.row() < len(self.m.jobs):
            return self.m.jobs[index.row()]
        return None

    # -- drag to reorder: only waiting / paused jobs move; order decides what starts next
    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        job = self.data(index, Qt.ItemDataRole.UserRole)
        return f | Qt.ItemFlag.ItemIsDragEnabled if job is not None and job.status in MOVABLE else f

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction

    def mimeTypes(self) -> list:
        return [MIME]

    def mimeData(self, indexes) -> QMimeData:
        data = QMimeData()
        jobs = [self.data(i, Qt.ItemDataRole.UserRole) for i in indexes if i.isValid()]
        data.setData(MIME, str(jobs[0].id).encode() if jobs else b"")
        return data

    def canDropMimeData(self, data, action, row, column, parent) -> bool:
        return data.hasFormat(MIME) and not parent.isValid()      # between rows, not onto one

    def dropMimeData(self, data, action, row, column, parent) -> bool:
        if not self.canDropMimeData(data, action, row, column, parent):
            return False
        job_id = bytes(data.data(MIME)).decode()
        job = next((j for j in self.m.jobs if str(j.id) == job_id), None)
        if job is None:
            return False
        self.move(job, len(self.m.jobs) if row < 0 else row)
        return False        # the move is done; False stops the view removing the dragged row afterwards

    def move(self, job: Job, row: int) -> None:
        """row: the gap to drop into, 0..len (as Qt counts it, before the job is taken out)."""
        src = self.m.jobs.index(job)
        if row in (src, src + 1):
            return
        self.beginMoveRows(QModelIndex(), src, src, QModelIndex(), row)
        self.m.move(job, row if row < src else row - 1)
        self.endMoveRows()

    def display(self, job: Job) -> Spring:
        """The progress value actually drawn: it eases toward the real one instead of jumping."""
        s = self._shown.get(job.id)
        if s is None:
            s = self._shown[job.id] = Spring(job.progress, 0.4, 1.0, precision=0.05, on_change=lambda j=job: self._touch(j))
        return s

    def _touch(self, job: Job) -> None:
        if job in self.m.jobs:
            i = self.index(self.m.jobs.index(job))
            self.dataChanged.emit(i, i)

    def _added(self, job: Job) -> None:
        n = len(self.m.jobs) - 1
        self.beginInsertRows(QModelIndex(), n, n)
        self.endInsertRows()

    def _changed(self, job: Job) -> None:
        s = self.display(job)
        s.to(job.progress, snap=job.progress < s.value)           # a restart snaps back instead of animating backwards
        self._touch(job)

    def _reset(self) -> None:
        self.beginResetModel()
        self.endResetModel()


class JobDelegate(QStyledItemDelegate):
    def __init__(self, model: JobModel, parent=None) -> None:
        super().__init__(parent)
        self.model = model

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, theme.px(76))

    def paint(self, p: QPainter, option, index) -> None:
        job = index.data(Qt.ItemDataRole.UserRole)
        if job is None:
            return
        px, pal = theme.px, theme.p
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r, rad = QRectF(option.rect).adjusted(4, 2, -4, -2), px(RADIUS["m"])
        p.setPen(Qt.PenStyle.NoPen)
        if option.state & QStyle.StateFlag.State_Selected:
            p.setPen(QPen(qc(pal.sep), 1))
            p.setBrush(qc((255, 255, 255, 38)))             # Media Vault's selected row: white/15 with an edge
            p.drawRoundedRect(r, rad, rad)
            p.setPen(Qt.PenStyle.NoPen)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            p.setBrush(qc((255, 255, 255, 13)))
            p.drawRoundedRect(r, rad, rad)
        symbol, tone = LOOK[job.status]
        col = getattr(pal, tone)
        isz, x, right = px(22), r.left() + px(12), r.right() - px(12)
        icons.draw(p, symbol, QRectF(x, r.top() + px(12), isz, isz), col)
        tx = x + isz + px(12)
        word, fm_w = job.status.value, QFontMetrics(theme.font("callout"))
        ww = fm_w.horizontalAdvance(word)
        p.setFont(theme.font("callout"))
        p.setPen(qc(col))
        p.drawText(QRectF(right - ww, r.top() + px(10), ww + 2, px(20)), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, word)
        avail = int(right - ww - px(12) - tx)
        p.setFont(theme.font("headline"))
        p.setPen(qc(pal.label))
        p.drawText(QRectF(tx, r.top() + px(8), avail, px(22)), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   QFontMetrics(theme.font("headline")).elidedText(job.title, Qt.TextElideMode.ElideRight, avail))
        full = int(right - tx)
        p.setFont(theme.font("footnote"))
        p.setPen(qc(pal.label2))
        p.drawText(QRectF(tx, r.top() + px(30), full, px(18)), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   QFontMetrics(theme.font("footnote")).elidedText(job.detail, Qt.TextElideMode.ElideRight, full))
        by, bw = r.bottom() - px(14), right - tx
        p.setBrush(qc(pal.sep))
        p.drawRoundedRect(QRectF(tx, by, bw, px(4)), px(2), px(2))
        fraction = max(0.0, min(1.0, self.model.display(job).value / 100))
        if fraction > 0:
            p.setBrush(qc(col if job.status is not S.QUEUED else pal.label3))
            p.drawRoundedRect(QRectF(tx, by, max(px(4), bw * fraction), px(4)), px(2), px(2))
        p.restore()


class QueuePage(QWidget):
    def __init__(self, manager: JobManager) -> None:
        super().__init__()
        self.manager, self.model = manager, JobModel(manager)
        lay = QVBoxLayout(self)
        m = theme.px(SPACE["xl"])
        lay.setContentsMargins(m, theme.px(SPACE["l"]), m, m)
        lay.setSpacing(theme.px(SPACE["m"]))
        lay.addWidget(Label("Queue", "largeTitle"))
        lay.addWidget(Label("Everything that is waiting, running or finished.", "body", "label2"))

        def button(text, icon, slot, kind="plain", tip=""):
            b = Button(text, icon, kind)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            return b

        self.pause_btn = button("Pause", "pause", self._toggle_pause, tip="Conversions freeze in place; downloads stop and continue from the partial file.")
        self.cancel_btn = button("Cancel", "stop", lambda: self._with(lambda j: j.cancel()))
        self.retry_btn = button("Retry", "retry", lambda: self._with(manager.retry), tip="Start a failed or cancelled job again")
        self.folder_btn = button("Show in Folder", "folder", lambda: self._with(self._open_folder))
        bar = QHBoxLayout()
        for b in (self.pause_btn, self.cancel_btn, self.retry_btn, self.folder_btn):
            bar.addWidget(b)
        bar.addStretch(1)
        bar.addWidget(MenuButton([("Pause all", manager.pause_all), ("Resume all", manager.resume_all), None,
                                  ("Retry failed", self._retry_failed), ("Clear finished", manager.clear_finished)],
                                 tip="More actions for all jobs"))
        lay.addLayout(bar)

        self.view = QListView()
        self.view.setModel(self.model)
        self.view.setItemDelegate(JobDelegate(self.model, self.view))
        self.view.setUniformItemSizes(True)
        self.view.setMouseTracking(True)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.view.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)   # drag waiting jobs to reorder
        self.view.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.view.setDropIndicatorShown(True)
        for keys, step in (("Alt+Up", -1), ("Alt+Down", 1)):                     # the same without a mouse
            QShortcut(QKeySequence(keys), self.view).activated.connect(lambda d=step: self._nudge(d))
        self.empty = EmptyState("list", "No jobs yet", "Add something from Convert, Join or Download.")
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.view)
        lay.addWidget(self.stack, 1)

        for sig in (self.model.rowsInserted, self.model.rowsRemoved, self.model.modelReset):
            sig.connect(self._sync_empty)
        self.view.selectionModel().selectionChanged.connect(self._sync_buttons)
        manager.job_changed.connect(self._sync_buttons)
        self._sync_empty()
        self._sync_buttons()

    def _selected(self) -> Job | None:
        i = self.view.currentIndex()
        return i.data(Qt.ItemDataRole.UserRole) if i.isValid() and self.view.selectionModel().isSelected(i) else None

    def _with(self, fn) -> None:
        job = self._selected()
        if job:
            fn(job)

    def _toggle_pause(self) -> None:
        job = self._selected()
        if job is not None:
            (self.manager.resume if job.status is S.PAUSED else self.manager.pause)(job)

    def _nudge(self, d: int) -> None:
        job = self._selected()
        if job is None or job.status not in MOVABLE:
            return
        src = self.manager.jobs.index(job)
        if 0 <= src + d < len(self.manager.jobs):
            self.model.move(job, src + d if d < 0 else src + 2)
            self.view.setCurrentIndex(self.model.index(self.manager.jobs.index(job)))

    def _retry_failed(self) -> None:
        if self.manager.retry_failed() == 0:
            alert(self, "Retry failed", "There are no failed jobs.")

    @staticmethod
    def _open_folder(job: Job) -> None:
        folder = job.open_path()
        if folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _sync_empty(self, *_) -> None:
        self.stack.setCurrentIndex(1 if self.model.rowCount() else 0)

    def _sync_buttons(self, *_) -> None:
        job = self._selected()
        st = job.status if job else None
        self.pause_btn.setText("Resume" if st is S.PAUSED else "Pause")
        self.pause_btn.icon_name = "play" if st is S.PAUSED else "pause"
        self.pause_btn.setEnabled(st in (S.RUNNING, S.QUEUED, S.PAUSED))
        self.cancel_btn.setEnabled(st is not None and not st.finished)
        self.retry_btn.setEnabled(st in (S.FAILED, S.CANCELLED))
        self.folder_btn.setEnabled(job is not None)
        self.pause_btn.update()

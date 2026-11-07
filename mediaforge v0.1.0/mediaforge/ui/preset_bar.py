"""Preset picker: built-in presets + the user's own, with Save as / Delete / Import / Export."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QMenu, QMessageBox,
    QPushButton, QToolButton, QWidget,
)

from ..core.presets import PresetStore, clean_name


class PresetBar(QWidget):
    chosen = Signal(str, dict)   # preset name, its values (built-ins may be partial)

    def __init__(self, store: PresetStore, kind: str, builtins: dict[str, dict],
                 get_values: Callable[[], dict], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store, self.kind, self.builtins, self.get_values = store, kind, builtins, get_values
        self._last_user = ""

        self.combo = QComboBox()
        self.combo.setMinimumWidth(200)
        self.save_btn = QPushButton("Save as...")
        self.save_btn.setToolTip("Save the current settings as a preset of your own")
        self.del_btn = QPushButton("Delete")
        self.more = QToolButton()
        self.more.setText("...")
        self.more.setToolTip("Import / export your presets")
        self.more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.more)
        for text, slot in (("Export my presets...", self._export), ("Import presets...", self._import)):
            act = QAction(text, self)
            act.triggered.connect(slot)
            menu.addAction(act)
        self.more.setMenu(menu)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.combo, 1)
        lay.addWidget(self.save_btn)
        lay.addWidget(self.del_btn)
        lay.addWidget(self.more)

        self.combo.currentIndexChanged.connect(self._on_index)
        self.save_btn.clicked.connect(self._save)
        self.del_btn.clicked.connect(self._delete)
        store.on_change(self.refresh)
        self.refresh()

    # -- helpers
    def _key(self, i: int):
        d = self.combo.itemData(i)
        return tuple(d) if d else None

    def _find(self, key) -> int:
        for i in range(self.combo.count()):
            if key is not None and self._key(i) == key:
                return i
        return -1

    def _sync_buttons(self) -> None:
        key = self._key(self.combo.currentIndex())
        self.del_btn.setEnabled(bool(key and key[0] == "user"))

    def _set_silently(self, index: int) -> None:
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(max(0, index))
        self.combo.blockSignals(False)
        self._sync_buttons()

    # -- public
    def refresh(self) -> None:
        keep = self._key(self.combo.currentIndex()) if self.combo.count() else None
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem("Custom", None)
        for name in self.builtins:
            self.combo.addItem(name, ("builtin", name))
        users = self.store.names(self.kind)
        if users:
            self.combo.insertSeparator(self.combo.count())
            for name in users:
                self.combo.addItem(f"\u2605 {name}", ("user", name))
        self.combo.blockSignals(False)
        self._set_silently(self._find(keep))

    def select(self, name: str) -> None:
        """Choose a preset by name and apply it (emits `chosen`)."""
        i = self._find(("builtin", name))
        if i < 0:
            i = self._find(("user", name))
        if i >= 0:
            self.combo.setCurrentIndex(i)

    def select_custom(self) -> None:
        self._set_silently(0)

    # -- slots
    def _on_index(self, i: int) -> None:
        key = self._key(i)
        self._sync_buttons()
        if not key:
            return
        src, name = key
        values = self.builtins.get(name) if src == "builtin" else self.store.get(self.kind, name)
        if values is None:
            return
        if src == "user":
            self._last_user = name
        self.chosen.emit(name, dict(values))

    def _save(self) -> None:
        text, ok = QInputDialog.getText(self, "Save preset", "Name for this preset:", text=self._last_user)
        if not ok:
            return
        try:
            name = clean_name(text)
        except ValueError as exc:
            QMessageBox.warning(self, "Save preset", str(exc))
            return
        if name in self.builtins:
            QMessageBox.warning(self, "Save preset", "That name belongs to a built-in preset. Pick another.")
            return
        if name in self.store.names(self.kind):
            if QMessageBox.question(self, "Save preset", f"Replace your preset '{name}'?") \
                    != QMessageBox.StandardButton.Yes:
                return
        try:
            self.store.save(self.kind, name, self.get_values())
        except OSError as exc:
            QMessageBox.warning(self, "Save preset", f"Couldn't write the presets file:\n{exc}")
            return
        self._last_user = name
        self._set_silently(self._find(("user", name)))

    def _delete(self) -> None:
        key = self._key(self.combo.currentIndex())
        if not key or key[0] != "user":
            return
        if QMessageBox.question(self, "Delete preset", f"Delete your preset '{key[1]}'?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.store.delete(self.kind, key[1])
        self._last_user = ""

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export presets", "mediaforge-presets.json",
                                              "Preset files (*.json)")
        if not path:
            return
        try:
            n = self.store.export_to(path, self.kind)
        except OSError as exc:
            QMessageBox.warning(self, "Export presets", str(exc))
            return
        QMessageBox.information(self, "Export presets", f"Exported {n} preset(s).")

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import presets", "", "Preset files (*.json)")
        if not path:
            return
        try:
            n, skipped = self.store.import_from(path)
        except ValueError as exc:
            QMessageBox.warning(self, "Import presets", str(exc))
            return
        msg = f"Imported {n} preset(s)."
        if skipped:
            msg += "\n\nSkipped:\n" + "\n".join(skipped[:10])
        QMessageBox.information(self, "Import presets", msg)

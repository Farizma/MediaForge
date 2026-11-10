"""Preset picker: built-in presets + the user's own, with Save as / Delete / Import / Export."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QWidget

from ..core.presets import PresetStore, clean_name
from .kit import Button, IconButton, MenuButton, Picker, alert, confirm, prompt
from .kit.theme import SPACE, theme


class PresetBar(QWidget):
    chosen = Signal(str, dict)   # preset name, its values (built-ins may be partial)

    def __init__(self, store: PresetStore, kind: str, builtins: dict, get_values: Callable[[], dict], parent=None) -> None:
        super().__init__(parent)
        self.store, self.kind, self.builtins, self.get_values = store, kind, builtins, get_values
        self._last_user = ""
        self.picker = Picker()
        self.save_btn = Button("Save as...", "bookmark")
        self.del_btn = IconButton("trash", "Delete this preset", "destructive")
        self.more = MenuButton([("Export my presets...", self._export), ("Import presets...", self._import)],
                               tip="Import / export presets")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.px(SPACE["s"]))
        lay.addWidget(self.picker, 1)
        for w in (self.save_btn, self.del_btn, self.more):
            lay.addWidget(w)
        self.picker.currentIndexChanged.connect(self._on_index)
        self.save_btn.clicked.connect(self._save)
        self.del_btn.clicked.connect(self._delete)
        store.on_change(self.refresh)
        self.refresh()

    # -- helpers
    def _key(self):
        return self.picker.currentData()

    def _sync(self) -> None:
        key = self._key()
        self.del_btn.setEnabled(bool(key and key[0] == "user"))

    def _set_silently(self, index: int) -> None:
        self.picker.setCurrentIndex(max(0, index), notify=False)
        self._sync()

    # -- public
    def refresh(self) -> None:
        keep = self._key() if self.picker.count() else None
        self.picker.clear()
        self.picker.addItem("Custom", None)
        for name in self.builtins:
            self.picker.addItem(name, ("builtin", name))
        users = self.store.names(self.kind)
        if users:
            self.picker.addSeparator()
            for name in users:
                self.picker.addItem(f"\u2605 {name}", ("user", name))
        self._set_silently(self.picker.findData(keep) if keep else 0)

    def select(self, name: str) -> None:
        """Choose a preset by name and apply it (emits `chosen`)."""
        i = self.picker.findData(("builtin", name))
        if i < 0:
            i = self.picker.findData(("user", name))
        if i >= 0:
            self.picker.setCurrentIndex(i)

    def select_custom(self) -> None:
        self._set_silently(0)

    # -- actions
    def _on_index(self, _i: int) -> None:
        key = self._key()
        self._sync()
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
        text = prompt(self, "Save preset", "Name for this preset", self._last_user)
        if text is None:
            return
        try:
            name = clean_name(text)
        except ValueError as exc:
            alert(self, "Save preset", str(exc))
            return
        if name in self.builtins:
            alert(self, "Save preset", "That name belongs to a built-in preset. Pick another.")
            return
        if name in self.store.names(self.kind) and not confirm(self, "Replace preset?", f"Replace your preset '{name}'?", "Replace"):
            return
        try:
            self.store.save(self.kind, name, self.get_values())
        except OSError as exc:
            alert(self, "Save preset", f"Couldn't write the presets file:\n{exc}")
            return
        self._last_user = name
        self._set_silently(self.picker.findData(("user", name)))

    def _delete(self) -> None:
        key = self._key()
        if key and key[0] == "user" and confirm(self, "Delete preset?", f"Delete your preset '{key[1]}'?", "Delete", destructive=True):
            self.store.delete(self.kind, key[1])
            self._last_user = ""

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export presets", "mediaforge-presets.json", "Preset files (*.json)")
        if not path:
            return
        try:
            n = self.store.export_to(path, self.kind)
        except OSError as exc:
            alert(self, "Export presets", str(exc))
            return
        alert(self, "Export presets", f"Exported {n} preset(s).")

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import presets", "", "Preset files (*.json)")
        if not path:
            return
        try:
            n, skipped = self.store.import_from(path)
        except ValueError as exc:
            alert(self, "Import presets", str(exc))
            return
        alert(self, "Import presets", f"Imported {n} preset(s)." + ("\n\nSkipped:\n" + "\n".join(skipped[:10]) if skipped else ""))

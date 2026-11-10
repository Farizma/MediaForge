"""One declarative field list drives widgets, change tracking, collecting and presets for an options dataclass."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Callable

from PySide6.QtCore import QObject, Signal

from .kit import EditPicker, Field, Group, PathField, Picker, Row, Segmented, Stepper, Switch


@dataclass
class F:
    """One option: which dataclass field, how to label it, and which control edits it."""
    name: str
    label: str
    kind: str = "text"            # picker | segmented | switch | stepper | text | edit | path
    choices: tuple = ()           # [(label, data)] for picker/segmented; [str] for edit
    hint: str = ""
    placeholder: str = ""
    lo: int = 0
    hi: int = 99
    mode: str = "dir"             # path: dir | open | save
    filter: str = ""
    wide: bool | None = None      # stack the control under its label (default for text / path / edit / segmented)


_MAKERS: dict[str, Callable] = {
    "picker": lambda f: Picker(f.choices),
    "segmented": lambda f: Segmented(f.choices),
    "switch": lambda f: Switch(),
    "stepper": lambda f: Stepper(f.lo, f.hi),
    "text": lambda f: Field(placeholder=f.placeholder),
    "edit": lambda f: EditPicker(f.choices, f.placeholder),
    "path": lambda f: PathField(f.mode, f.filter, f.placeholder),
}


class Form(QObject):
    changed = Signal(str)         # name of the field the user changed

    def __init__(self, cls, specs: list[F]) -> None:
        super().__init__()
        self.cls, self.specs = cls, {s.name: s for s in specs}
        self.ctl, self.rows, self._quiet = {}, {}, 0
        for s in specs:
            c = self.ctl[s.name] = _MAKERS[s.kind](s)
            wide = s.wide if s.wide is not None else s.kind in ("text", "path", "edit", "segmented")
            self.rows[s.name] = Row(s.label, c, s.hint, wide)
            c.changed.connect(lambda n=s.name: self._emit(n))
        self.apply(asdict(cls()))                         # start from the dataclass defaults, never from widget defaults

    def _emit(self, name: str) -> None:
        if not self._quiet:
            self.changed.emit(name)

    @contextmanager
    def quiet(self):
        """Programmatic edits (presets, defaults) must not look like user edits."""
        self._quiet += 1
        try:
            yield
        finally:
            self._quiet -= 1

    def group(self, title: str, footer: str, *names: str) -> Group:
        g = Group(title, footer)
        for n in names:
            g.add(self.rows[n])
        return g

    def get(self, name: str):
        return self.ctl[name].value()

    def values(self) -> dict:
        return {n: c.value() for n, c in self.ctl.items()}

    def collect(self, **extra):
        return self.cls(**self.values(), **extra)

    def apply(self, values: dict) -> None:
        with self.quiet():
            for n, c in self.ctl.items():
                if n in values:
                    c.setValue(values[n])

    def enable(self, name: str, on: bool) -> None:
        self.rows[name].setEnabled(bool(on))

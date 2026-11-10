"""Spring physics on one shared frame clock. Interruptible: re-targeting keeps the current velocity."""
from __future__ import annotations

import math
import sys
import time

from PySide6.QtCore import QEasingCurve, QObject, QPointF, QTimer, QVariantAnimation, Qt
from PySide6.QtGui import QGuiApplication

_cache = [0.0, False]


def reduced_motion() -> bool:
    """Windows 'Animation effects' switched off. Springs then snap; short fades remain."""
    if sys.platform != "win32":
        return False
    if time.monotonic() - _cache[0] > 2.0:
        try:
            import ctypes
            on = ctypes.c_int(1)
            ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(on), 0)   # SPI_GETCLIENTAREAANIMATION
            _cache[1] = not on.value
        except Exception:
            _cache[1] = False
        _cache[0] = time.monotonic()
    return _cache[1]


def ease_out() -> QEasingCurve:                   # cubic-bezier(0.23, 1, 0.32, 1): the strong UI ease-out
    c = QEasingCurve(QEasingCurve.Type.BezierSpline)
    c.addCubicBezierSegment(QPointF(0.23, 1.0), QPointF(0.32, 1.0), QPointF(1.0, 1.0))
    return c


class _Driver:
    """One timer for every running spring, ticking at the screen's refresh rate; idle when nothing moves."""

    def __init__(self) -> None:
        self.active: set = set()
        self.timer: QTimer | None = None
        self.last = 0.0

    def add(self, spring) -> None:
        self.active.add(spring)
        if self.timer is None:
            self.timer = QTimer()
            self.timer.setTimerType(Qt.TimerType.PreciseTimer)
            screen = QGuiApplication.primaryScreen()
            hz = (screen.refreshRate() if screen else 60.0) or 60.0
            self.timer.setInterval(max(4, min(17, round(1000 / hz))))
            self.timer.timeout.connect(self._tick)
        if not self.timer.isActive():
            self.last = time.perf_counter()
            self.timer.start()

    def _tick(self) -> None:
        now = time.perf_counter()
        dt, self.last = min(now - self.last, 0.05), now
        for s in list(self.active):
            if not s.step(dt):
                self.active.discard(s)
        if not self.active:
            self.timer.stop()


driver = _Driver()


class Spring:
    """SwiftUI-style spring: `response` (seconds to ~settle) and `damping` (1.0 = no overshoot)."""

    def __init__(self, value: float = 0.0, response: float = 0.35, damping: float = 1.0,
                 precision: float = 0.002, on_change=None) -> None:
        self.value = self.target = float(value)
        self.velocity = 0.0
        w = 2 * math.pi / response
        self.k, self.c = w * w, 2 * damping * w
        self.precision, self.on_change = precision, on_change

    def to(self, target: float, snap: bool = False) -> None:
        self.target = float(target)
        if snap or reduced_motion():
            self.value, self.velocity = self.target, 0.0
            driver.active.discard(self)
            if self.on_change:
                self.on_change()
        elif abs(self.value - self.target) > self.precision or abs(self.velocity) > self.precision:
            driver.add(self)

    def step(self, dt: float) -> bool:
        n = max(1, math.ceil(dt / 0.004))        # sub-steps keep stiff springs stable on slow frames
        h = dt / n
        for _ in range(n):
            self.velocity += (-self.k * (self.value - self.target) - self.c * self.velocity) * h
            self.value += self.velocity * h
        settled = abs(self.value - self.target) < self.precision and abs(self.velocity) < self.precision * 10
        if settled:
            self.value, self.velocity = self.target, 0.0
        if self.on_change:
            self.on_change()
        return not settled


def tween(owner: QObject, start: float, end: float, ms: int, apply, done=None) -> QVariantAnimation:
    """Short eased value animation (fades). Reduced motion keeps it, but shortens it."""
    anim = QVariantAnimation(owner)
    anim.setStartValue(float(start))
    anim.setEndValue(float(end))
    anim.setDuration(min(ms, 90) if reduced_motion() else ms)
    anim.setEasingCurve(ease_out())
    anim.valueChanged.connect(lambda v: apply(float(v)))
    if done:
        anim.finished.connect(done)
    anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)
    return anim


def fade_in(widget, ms: int = 150) -> None:
    """Cross-fade a page in (opacity only, so nothing re-lays-out). The effect is dropped afterwards."""
    from PySide6.QtWidgets import QGraphicsOpacityEffect
    fx = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(fx)
    fx.setOpacity(0.0)
    tween(widget, 0.0, 1.0, ms, fx.setOpacity, done=lambda: widget.setGraphicsEffect(None))

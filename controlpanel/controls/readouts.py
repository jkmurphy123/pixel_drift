# controlpanel/controls/readouts.py
#
# Readout controls: glowing numbers over a sprite window — 7-seg digital
# readouts, odometer counters, and nixie tubes (all drawn with the shared
# 7-seg primitives, decision D4).

from .. import seven_seg
from ..signals import build_signal
from .base import Control


class DigitalReadoutControl(Control):
    """
    7-seg readout showing a signal mapped to [min, max]. Refreshed at
    `refresh_hz` so the digits are readable instead of a blur.

    Layout overrides: signal, min, max, digits, decimals, refresh_hz,
    color_rgb, window.
    """

    def __init__(self, placed, ctx):
        super().__init__(placed, ctx)
        self.signal = build_signal(self.spec.get("signal"), ctx.rng,
                                   default_kind="random_walk")
        self.lo = float(self.spec.get("min", 0.0))
        self.hi = float(self.spec.get("max", 999.0))
        self.decimals = int(self.spec.get("decimals", 0))
        self.refresh = 1.0 / float(self.spec.get("refresh_hz", 4.0))
        self.color = self._color("color_rgb", ctx.trace_rgb)
        self.dim = tuple(int(c * 0.12) for c in self.color)
        self.window = self._window(default=(0.06, 0.15, 0.88, 0.70))
        self._acc = 0.0
        self.text = ""

    def update(self, dt: float):
        self.signal.update(dt)
        self._acc += dt
        if self._acc >= self.refresh:
            self._acc = 0.0
            value = self.lo + (self.hi - self.lo) * self.signal.value
            self.text = f"{value:.{self.decimals}f}".replace(".", "")

    def draw_overlay(self, surface):
        if self.text:
            seven_seg.draw_text(surface, self.text, self.window,
                                self.color, self.dim)


class CounterControl(Control):
    """
    Odometer-style counter: increments at `per_sec` and never goes back.
    Layout overrides: digits, per_sec, start, color_rgb, window.
    """

    def __init__(self, placed, ctx):
        super().__init__(placed, ctx)
        self.digits = int(self.spec.get("digits", 5))
        self.per_sec = float(self.spec.get("per_sec", 2.0)) * ctx.rng.uniform(0.6, 1.6)
        self.value = float(self.spec.get("start", ctx.rng.uniform(0, 5000)))
        self.color = self._color("color_rgb", ctx.accent_rgb)
        self.dim = tuple(int(c * 0.12) for c in self.color)
        self.window = self._window(default=(0.06, 0.18, 0.88, 0.64))

    def update(self, dt: float):
        self.value += self.per_sec * dt

    def draw_overlay(self, surface):
        text = str(int(self.value))[-self.digits:].zfill(self.digits)
        seven_seg.draw_text(surface, text, self.window, self.color, self.dim)


class NixieControl(Control):
    """
    Nixie pair: two big warm-glow digits drifting slowly (step signal),
    with occasional brightness flicker. Layout overrides: signal, window,
    color_rgb.
    """

    def __init__(self, placed, ctx):
        super().__init__(placed, ctx)
        self.signal = build_signal(self.spec.get("signal"), ctx.rng,
                                   default_kind="step",
                                   )
        self.color = self._color("color_rgb", (255, 150, 60))
        self.window = self._window(default=(0.08, 0.08, 0.84, 0.84))
        self.rng = ctx.rng
        self.flicker = 1.0

    def update(self, dt: float):
        self.signal.update(dt)
        # rare faint flicker dips, quickly recovering
        if self.rng.random() < 0.4 * dt:
            self.flicker = self.rng.uniform(0.55, 0.85)
        self.flicker += (1.0 - self.flicker) * min(1.0, 8.0 * dt)

    def draw_overlay(self, surface):
        value = int(self.signal.value * 99 + 0.5)
        color = tuple(int(c * self.flicker) for c in self.color)
        dim = tuple(int(c * 0.10) for c in color)
        seven_seg.draw_text(surface, f"{value:02d}", self.window, color, dim)

# controlpanel/controls/stateful.py
#
# Stateful controls: things with discrete positions that change on their own
# — toggle switches, rotary knobs, selector switches, self-pressing buttons.
# Movement between states is eased so nothing snaps.

import math

import pygame

from .base import Control


class _DiscreteStateControl(Control):
    """
    Base: a control with N discrete states. Picks a new random state every
    `dwell_range` seconds and eases self.position toward it.
    """

    def __init__(self, placed, ctx, states, dwell_range=(2.0, 7.0), ease=6.0):
        super().__init__(placed, ctx)
        self.states = states
        self.rng = ctx.rng
        self.dwell_range = dwell_range
        self.ease = ease
        self.state = self.rng.randrange(states)
        self.position = float(self.state)  # eased, fractional while moving
        self.dwell = self.rng.uniform(*dwell_range)

    def update(self, dt: float):
        self.dwell -= dt
        if self.dwell <= 0.0:
            self.state = self.rng.randrange(self.states)
            self.dwell = self.rng.uniform(*self.dwell_range)
        self.position += (self.state - self.position) * min(1.0, self.ease * dt)


class ToggleSwitchControl(_DiscreteStateControl):
    """
    Toggle switch: a lever line from the pivot to an up/down (or 3-position)
    angle. Layout overrides: positions (2 or 3), dwell_range, lever_rgb.
    """

    def __init__(self, placed, ctx):
        positions = int(placed.raw.get("positions", 2))
        super().__init__(placed, ctx, states=max(2, min(3, positions)),
                         dwell_range=tuple(placed.raw.get("dwell_range", [3.0, 9.0])))
        self.lever_rgb = self._color("lever_rgb", ctx.accent_rgb)
        self.pivot = self._anchor("pivot", (0.5, 0.62))
        _, _, w, h = self.rect
        self.lever_len = 0.30 * min(w, h)

    def draw_overlay(self, surface):
        # state 0 = down (-35° from vertical), last = up (+35°)
        span = 70.0
        frac = self.position / (self.states - 1)
        angle_deg = 90.0 - span / 2 + span * frac  # y-down: 90° is straight up
        a = math.radians(angle_deg)
        tip = (self.pivot[0] + self.lever_len * math.cos(a),
               self.pivot[1] - self.lever_len * math.sin(a))
        pygame.draw.line(surface, self.lever_rgb, self.pivot, tip, 5)
        pygame.draw.circle(surface, self.lever_rgb,
                           (int(tip[0]), int(tip[1])), 5)


class RotaryKnobControl(_DiscreteStateControl):
    """
    Rotary knob: a pointer tick easing between `detents` positions spread
    across a 270° arc (gap at the bottom, like a real knob).
    Layout overrides: detents, dwell_range, pointer_rgb.
    """

    def __init__(self, placed, ctx):
        super().__init__(placed, ctx,
                         states=int(placed.raw.get("detents", 5)),
                         dwell_range=tuple(placed.raw.get("dwell_range", [2.5, 8.0])),
                         ease=4.0)
        self.pointer_rgb = self._color("pointer_rgb", ctx.accent_rgb)
        self.center = self._anchor("center", (0.5, 0.5))
        _, _, w, h = self.rect
        self.radius = 0.30 * min(w, h)

    def draw_overlay(self, surface):
        frac = self.position / max(1, self.states - 1)
        # 270° arc starting at 135° (down-left), y-down coords
        angle_deg = 135.0 + 270.0 * frac
        a = math.radians(angle_deg)
        inner = (self.center[0] + self.radius * 0.45 * math.cos(a),
                 self.center[1] + self.radius * 0.45 * math.sin(a))
        outer = (self.center[0] + self.radius * math.cos(a),
                 self.center[1] + self.radius * math.sin(a))
        pygame.draw.line(surface, self.pointer_rgb, inner, outer, 4)


class SelectorSwitchControl(RotaryKnobControl):
    """A rotary knob with more detents and shorter dwell (busier)."""

    def __init__(self, placed, ctx):
        placed.raw.setdefault("detents", 6)
        placed.raw.setdefault("dwell_range", [1.5, 4.0])
        super().__init__(placed, ctx)


class PushButtonControl(Control):
    """
    Push button that occasionally presses itself: a brief highlight ring +
    dimmed cap, then release. Layout overrides: press_interval, ring_rgb.
    """

    def __init__(self, placed, ctx):
        super().__init__(placed, ctx)
        self.rng = ctx.rng
        self.ring_rgb = self._color("ring_rgb", ctx.accent_rgb)
        lo, hi = self.spec.get("press_interval", [3.0, 9.0])
        self.interval = (float(lo), float(hi))
        self.timer = self.rng.uniform(*self.interval)
        self.pressed = 0.0  # seconds remaining in the press
        self.center = self._anchor("center", (0.5, 0.5))
        _, _, w, h = self.rect
        self.radius = 0.26 * min(w, h)

    def update(self, dt: float):
        if self.pressed > 0.0:
            self.pressed -= dt
            return
        self.timer -= dt
        if self.timer <= 0.0:
            self.pressed = 0.35
            self.timer = self.rng.uniform(*self.interval)

    def draw_overlay(self, surface):
        if self.pressed <= 0.0:
            return
        cx, cy = int(self.center[0]), int(self.center[1])
        r = int(self.radius)
        # highlight ring + darkened cap = "button is in"
        pygame.draw.circle(surface, self.ring_rgb, (cx, cy), r + 4, 3)
        dim = tuple(int(c * 0.35) for c in self.ring_rgb)
        pygame.draw.circle(surface, dim, (cx, cy), r - 2)

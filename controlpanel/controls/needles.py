# controlpanel/controls/needles.py
#
# Needle controls: a line pivoting on a dial face. Phase 2 ships the round
# gauge; meter/compass variants reuse the same sweep math later.

import math

import pygame

from ..signals import build_signal
from .base import Control


class GaugeControl(Control):
    """
    Round gauge: a needle line + hub dot over the static dial sprite.

    The needle sweeps `sweep_deg` degrees centered on straight-up, driven by
    a unipolar signal (default: random_walk — the classic wandering gauge).

    Layout overrides: signal, pivot, sweep_deg, color, needle_rgb, hub_rgb,
    needle_width.
    """

    pivot_default = (0.5, 0.62)
    sweep_default = 120.0

    def __init__(self, placed, ctx):
        super().__init__(placed, ctx)
        self.signal = build_signal(self.spec.get("signal"), ctx.rng,
                                   default_kind="random_walk")
        self.sweep_deg = float(self.spec.get("sweep_deg", self.sweep_default))
        self.needle_rgb = self._color("needle_rgb", ctx.accent_rgb)
        self.hub_rgb = tuple(self.spec.get("hub_rgb", (30, 32, 36)))

        x, y, w, h = self.rect
        self.pivot = self._anchor("pivot", self.pivot_default)
        self.needle_len = 0.40 * min(w, h)
        self.hub_r = max(3, int(0.035 * min(w, h)))
        # needle thickness scales with the dial so big gauges stay bold;
        # layout "needle_width" (px) overrides
        self.needle_w = int(self.spec.get(
            "needle_width", max(4, round(0.028 * min(w, h)))))

    def update(self, dt: float):
        self.signal.update(dt)

    def draw_overlay(self, surface):
        # 0.0 -> up-left, 0.5 -> straight up, 1.0 -> up-right (y-down coords)
        straight_up = 270.0
        angle_deg = straight_up - self.sweep_deg / 2 + self.sweep_deg * self.signal.value
        a = math.radians(angle_deg)
        tip = (self.pivot[0] + self.needle_len * math.cos(a),
               self.pivot[1] + self.needle_len * math.sin(a))
        pygame.draw.line(surface, self.needle_rgb, self.pivot, tip,
                         self.needle_w)
        pygame.draw.circle(surface, self.needle_rgb,
                           (int(self.pivot[0]), int(self.pivot[1])), self.hub_r)
        pygame.draw.circle(surface, self.hub_rgb,
                           (int(self.pivot[0]), int(self.pivot[1])),
                           max(1, self.hub_r - 2))


class MeterControl(GaugeControl):
    """
    VU/edgewise meter: a damped needle with a bottom pivot and a narrower
    sweep; the needle shifts green -> amber -> red as the level climbs
    (classic meter coloring). Works for both METER_VU_H and METER_VU_V
    sprites. Layout overrides: same as gauge, plus damping.
    """

    pivot_default = (0.5, 0.85)
    sweep_default = 80.0

    def __init__(self, placed, ctx):
        super().__init__(placed, ctx)
        self.level = self.signal.value
        _, _, w, h = self.rect
        self.needle_len = 0.62 * h  # bottom pivot -> longer reach
        # explicit layout color disables the green->amber->red coloring
        self._fixed_color = "color" in self.spec or "needle_rgb" in self.spec

    def update(self, dt: float):
        self.signal.update(dt)
        # fast attack, slow release — like real VU ballistics
        target = self.signal.value
        rate = 16.0 if target > self.level else 4.0
        self.level += (target - self.level) * min(1.0, rate * dt)

    def draw_overlay(self, surface):
        v = self.level
        if not self._fixed_color:
            if v < 0.65:
                self.needle_rgb = (70, 255, 110)
            elif v < 0.85:
                self.needle_rgb = (255, 176, 64)
            else:
                self.needle_rgb = (255, 60, 50)
        saved = self.signal.value
        self.signal.value = v  # reuse the gauge sweep math on the damped level
        super().draw_overlay(surface)
        self.signal.value = saved

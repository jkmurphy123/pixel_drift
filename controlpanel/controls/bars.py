# controlpanel/controls/bars.py
#
# Bar controls: filled level bars (bar_graph) and segmented LED bars
# (led_bar). Orientation comes from the sprite footprint: taller than wide
# fills bottom-up, wider than tall fills left-to-right.

import pygame

from ..signals import build_signal
from .base import Control


def _level_color(value, base_rgb=None, thresholds=True):
    """Green -> amber -> red as the level climbs (classic meter coloring)."""
    if not thresholds:
        return base_rgb
    if value < 0.65:
        return (70, 255, 110)
    if value < 0.85:
        return (255, 176, 64)
    return (255, 60, 50)


class BarGraphControl(Control):
    """
    Smooth fill bar driven by a unipolar signal (default random_walk).
    Layout overrides: signal, window, color_rgb, thresholds.
    """

    def __init__(self, placed, ctx):
        super().__init__(placed, ctx)
        self.signal = build_signal(self.spec.get("signal"), ctx.rng,
                                   default_kind="random_walk")
        self.base_rgb = self._color("color_rgb", ctx.accent_rgb)
        self.thresholds = bool(self.spec.get("thresholds", True))
        self.window = self._window(default=(0.15, 0.08, 0.70, 0.84))

    def update(self, dt: float):
        self.signal.update(dt)

    def draw_overlay(self, surface):
        v = max(0.0, min(1.0, self.signal.value))
        wx, wy, ww, wh = self.window
        vertical = wh >= ww
        color = _level_color(v, self.base_rgb, self.thresholds)
        if vertical:
            fill_h = wh * v
            rect = pygame.Rect(wx, wy + wh - fill_h, ww, fill_h)
        else:
            rect = pygame.Rect(wx, wy, ww * v, wh)
        if rect.width > 0 and rect.height > 0:
            pygame.draw.rect(surface, color, rect)


class LedBarControl(Control):
    """
    Segmented LED bar: N discrete cells, lit up to the signal level, with
    threshold coloring on the top cells (default pulse signal — bouncy
    activity-meter feel). Layout overrides: signal, window, segments.
    """

    def __init__(self, placed, ctx):
        super().__init__(placed, ctx)
        self.signal = build_signal(self.spec.get("signal"), ctx.rng,
                                   default_kind="pulse")
        self.segments = int(self.spec.get("segments", 16))
        self.window = self._window(default=(0.06, 0.20, 0.88, 0.60))
        self.off_rgb = (40, 44, 48)
        # smoothed level so the bar doesn't strobe
        self.level = 0.0

    def update(self, dt: float):
        self.signal.update(dt)
        target = self.signal.value
        rate = 14.0 if target > self.level else 5.0
        self.level += (target - self.level) * min(1.0, rate * dt)

    def draw_overlay(self, surface):
        wx, wy, ww, wh = self.window
        n = max(2, self.segments)
        gap = max(2, int(min(ww, wh) * 0.06))
        horizontal = ww >= wh
        lit = int(self.level * n + 0.5)
        for i in range(n):
            frac = i / (n - 1)
            if horizontal:
                seg_w = (ww - (n - 1) * gap) / n
                rect = pygame.Rect(wx + i * (seg_w + gap), wy, seg_w, wh)
            else:
                seg_h = (wh - (n - 1) * gap) / n
                # segment 0 at the bottom
                rect = pygame.Rect(wx, wy + wh - (i + 1) * seg_h - i * gap,
                                   ww, seg_h)
            color = _level_color(frac, None) if i < lit else self.off_rgb
            pygame.draw.rect(surface, color, rect)

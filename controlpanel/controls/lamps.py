# controlpanel/controls/lamps.py
#
# Lamp controls: blinking indicator lights drawn as primitive glows
# (decision D3 — no "lit" sprites required from skins).

import pygame

from ..signals import build_signal
from .base import Control

# Lamp color is inferred from the sprite ID when the layout doesn't give
# one: LED_LAMP_RED -> red, etc. Falls back to the mode's lamp_rgb.
_SPRITE_COLORS = {
    "RED": (255, 60, 50),
    "GREEN": (70, 255, 110),
    "AMBER": (255, 176, 64),
    "BLUE": (80, 170, 255),
}


class LampControl(Control):
    """
    Blinking indicator lamp: an outer halo + bright core whose intensity
    follows a signal (default: square wave — a steady blink). Intensity is
    smoothed so lamps fade in/out instead of popping.

    Layout overrides: signal, color_rgb, center, radius.
    """

    def __init__(self, placed, ctx):
        super().__init__(placed, ctx)
        self.signal = build_signal(self.spec.get("signal"), ctx.rng,
                                   default_kind="square")
        self.color = self._resolve_color(ctx)
        self.center = self._anchor("center", (0.5, 0.5))
        _, _, w, h = self.rect
        self.radius = float(self.spec.get("radius", 0.20)) * min(w, h)
        self.level = 0.0  # smoothed 0..1 intensity

    def _resolve_color(self, ctx):
        # generic "color" wins, then the lamp-specific "color_rgb",
        # then the color named by the sprite ID, then the mode default
        if "color" in self.spec:
            return tuple(self.spec["color"])
        if "color_rgb" in self.spec:
            return tuple(self.spec["color_rgb"])
        for key, rgb in _SPRITE_COLORS.items():
            if key in self.sprite_id:
                return rgb
        return ctx.lamp_rgb

    def update(self, dt: float):
        self.signal.update(dt)
        # attack is fast, release slower — looks like a real filament/LED
        target = self.signal.value
        rate = 18.0 if target > self.level else 7.0
        self.level += (target - self.level) * min(1.0, rate * dt)

    def draw_overlay(self, surface):
        if self.level < 0.02:
            return
        cx, cy = int(self.center[0]), int(self.center[1])
        lv = self.level
        r_core = max(1, int(self.radius))
        r_halo = int(self.radius * 1.8)
        halo = tuple(int(c * 0.35 * lv) for c in self.color)
        core = tuple(int(c * lv) for c in self.color)
        pygame.draw.circle(surface, halo, (cx, cy), r_halo)
        pygame.draw.circle(surface, core, (cx, cy), r_core)

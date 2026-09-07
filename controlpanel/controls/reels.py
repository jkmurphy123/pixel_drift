# controlpanel/controls/reels.py
#
# Rotating things: tape reels, the radar sweep, and the clock.

import math
import time

import pygame

from .base import Control


class TapeReelControl(Control):
    """
    Two tape reels counter-rotating at slightly different speeds (like a
    reel-to-reel deck). Each reel: 3 spokes + hub. Layout overrides:
    speed, centers, spoke_rgb.
    """

    def __init__(self, placed, ctx):
        super().__init__(placed, ctx)
        self.spoke_rgb = self._color("spoke_rgb", ctx.accent_rgb)
        x, y, w, h = self.rect
        # two reels side by side in the sprite
        self.reels = [
            {"center": (x + 0.28 * w, y + 0.5 * h), "r": 0.20 * min(w, h),
             "speed": 0.9, "angle": ctx.rng.uniform(0, math.tau)},
            {"center": (x + 0.72 * w, y + 0.5 * h), "r": 0.20 * min(w, h),
             "speed": -0.7, "angle": ctx.rng.uniform(0, math.tau)},
        ]
        speed_scale = float(self.spec.get("speed", 1.0))
        for reel in self.reels:
            reel["speed"] *= speed_scale

    def update(self, dt: float):
        for reel in self.reels:
            reel["angle"] += reel["speed"] * math.tau * 0.25 * dt

    def draw_overlay(self, surface):
        for reel in self.reels:
            cx, cy = reel["center"]
            for k in range(3):
                a = reel["angle"] + k * math.tau / 3
                tip = (cx + reel["r"] * math.cos(a), cy + reel["r"] * math.sin(a))
                pygame.draw.line(surface, self.spoke_rgb, (cx, cy), tip, 3)
                pygame.draw.circle(surface, self.spoke_rgb,
                                   (int(tip[0]), int(tip[1])), 3)
            pygame.draw.circle(surface, self.spoke_rgb, (int(cx), int(cy)), 4)


class RadarControl(Control):
    """
    Radar/sonar: a sweep line rotating at `period` seconds per revolution;
    blips spawn at random bearings, glow when the sweep passes, then fade.
    Layout overrides: period, blip_rate, trace_rgb.
    """

    def __init__(self, placed, ctx):
        super().__init__(placed, ctx)
        self.period = float(self.spec.get("period", 4.0))
        self.blip_rate = float(self.spec.get("blip_rate", 0.8))  # spawns/sec
        self.color = self._color("trace_rgb", ctx.trace_rgb)
        self.rng = ctx.rng
        x, y, w, h = self.rect
        self.center = (x + w / 2, y + h / 2)
        self.radius = 0.44 * min(w, h)
        self.angle = self.rng.uniform(0, math.tau)
        # blips: (angle, dist_frac, brightness)
        self.blips = []

    def update(self, dt: float):
        prev = self.angle
        self.angle = (self.angle + math.tau * dt / self.period) % math.tau
        if self.rng.random() < self.blip_rate * dt and len(self.blips) < 12:
            self.blips.append([self.rng.uniform(0, math.tau),
                               self.rng.uniform(0.15, 0.95), 0.0])
        for blip in self.blips:
            # sweep crossed the blip this frame (handles wraparound)
            crossed = (prev <= blip[0] < self.angle) or \
                      (self.angle < prev and (blip[0] >= prev or blip[0] < self.angle))
            if crossed:
                blip[2] = 1.0
            blip[2] *= math.exp(-0.5 * dt)
        self.blips = [b for b in self.blips if b[2] > 0.03]

    def draw_overlay(self, surface):
        cx, cy = self.center
        tip = (cx + self.radius * math.cos(self.angle),
               cy + self.radius * math.sin(self.angle))
        pygame.draw.line(surface, self.color, (cx, cy), tip, 2)
        for ang, dist, bright in self.blips:
            bx = cx + self.radius * dist * math.cos(ang)
            by = cy + self.radius * dist * math.sin(ang)
            color = tuple(int(c * bright) for c in self.color)
            pygame.draw.circle(surface, color, (int(bx), int(by)), 4)


class ClockControl(Control):
    """
    Analog clock: real wall-clock time by default, or fast-forward with
    "speed" (e.g. 60 = one minute per second). Layout overrides: speed,
    hand_rgb.
    """

    def __init__(self, placed, ctx):
        super().__init__(placed, ctx)
        self.speed = float(self.spec.get("speed", 1.0))
        now = time.localtime()
        self.t = now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec
        self.hand_rgb = self._color("hand_rgb", (220, 224, 228))
        self.accent = ctx.accent_rgb
        x, y, w, h = self.rect
        self.center = (x + w / 2, y + h / 2)
        self.radius = 0.42 * min(w, h)

    def update(self, dt: float):
        self.t = (self.t + dt * self.speed) % 86400.0

    def _hand(self, surface, frac, length, width, color):
        a = math.tau * frac - math.pi / 2  # 12 o'clock is up
        tip = (self.center[0] + self.radius * length * math.cos(a),
               self.center[1] + self.radius * length * math.sin(a))
        pygame.draw.line(surface, color, self.center, tip, width)

    def draw_overlay(self, surface):
        seconds = self.t % 60
        minutes = (self.t / 60) % 60
        hours = (self.t / 3600) % 12
        self._hand(surface, hours / 12, 0.50, 5, self.hand_rgb)
        self._hand(surface, minutes / 60, 0.75, 3, self.hand_rgb)
        self._hand(surface, seconds / 60, 0.85, 1, self.accent)
        pygame.draw.circle(surface, self.hand_rgb,
                           (int(self.center[0]), int(self.center[1])), 4)

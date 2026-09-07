# controlpanel/controls/traces.py
#
# Trace controls: waveform drawings inside the scope sprite's screen window.
# Phase 2 ships the oscilloscope; the strip chart reuses the scrolling
# sample buffer later.

import math
from collections import deque

import pygame

from ..signals import build_signal
from .base import Control


class ScopeControl(Control):
    """
    Oscilloscope: draws a live waveform into the sprite's window.

    wave kinds (layout "wave": {"kind": ...}):
      sine      — scrolling trace of a bipolar signal (default)
      noise     — scrolling sample-and-hold noise
      lissajous — full parametric figure redrawn each frame (freq_a/freq_b)

    Layout overrides: wave, window, trace_rgb, samples.
    Orientation (SCOPE_H vs SCOPE_V) needs no code: the window fraction
    default fits both footprints.
    """

    def __init__(self, placed, ctx):
        super().__init__(placed, ctx)
        wave = dict(self.spec.get("wave") or {})
        self.wave_kind = str(wave.pop("kind", "sine")).strip().lower()

        self.signal = build_signal(
            wave, ctx.rng,
            default_kind="noise" if self.wave_kind == "noise" else "sine",
            bipolar=True)

        self.trace_rgb = self._color("trace_rgb", ctx.trace_rgb)
        self.window = self._window()
        self.max_samples = int(self.spec.get("samples", 220))
        self.samples = deque(maxlen=self.max_samples)

        # lissajous parameters get a per-instance detune so two scopes
        # never draw the same figure
        self.freq_a = float(wave.get("freq_a", 0.21)) * ctx.rng.uniform(0.9, 1.1)
        self.freq_b = float(wave.get("freq_b", 0.13)) * ctx.rng.uniform(0.9, 1.1)
        self.t = ctx.rng.uniform(0.0, 100.0)

    def update(self, dt: float):
        self.t += dt
        if self.wave_kind != "lissajous":
            self.signal.update(dt)
            self.samples.append(self.signal.value)

    def draw_overlay(self, surface):
        wx, wy, ww, wh = self.window
        if ww < 8 or wh < 8:
            return
        clip = surface.get_clip()
        surface.set_clip(pygame.Rect(wx, wy, ww, wh))
        if self.wave_kind == "lissajous":
            self._draw_lissajous(surface, wx, wy, ww, wh)
        else:
            self._draw_trace(surface, wx, wy, ww, wh)
        surface.set_clip(clip)

    def _draw_trace(self, surface, wx, wy, ww, wh):
        n = len(self.samples)
        if n < 2:
            return
        mid_y = wy + wh / 2
        amp = wh * 0.42
        pts = []
        for i, v in enumerate(self.samples):
            x = wx + ww * i / (self.max_samples - 1)
            pts.append((x, mid_y - amp * v))
        pygame.draw.lines(surface, self.trace_rgb, False, pts, 2)

    def _draw_lissajous(self, surface, wx, wy, ww, wh):
        cx, cy = wx + ww / 2, wy + wh / 2
        ax, ay = ww * 0.44, wh * 0.42
        pts = []
        steps = 160
        for i in range(steps + 1):
            u = self.t + (i / steps) * 2.0  # trailing 2-second window
            pts.append((cx + ax * math.sin(math.tau * self.freq_a * u),
                        cy + ay * math.sin(math.tau * self.freq_b * u + 1.1)))
        pygame.draw.lines(surface, self.trace_rgb, False, pts, 1)


class StripChartControl(ScopeControl):
    """
    Pen recorder: a slow scrolling trace (sine signal by default) with a
    pen dot at the leading edge. Layout overrides: same as scope.
    """

    def __init__(self, placed, ctx):
        super().__init__(placed, ctx)
        self.max_samples = int(self.spec.get("samples", 400))

    def draw_overlay(self, surface):
        super().draw_overlay(surface)
        if not self.samples:
            return
        wx, wy, ww, wh = self.window
        mid_y = wy + wh / 2
        amp = wh * 0.42
        i = len(self.samples) - 1
        x = wx + ww * i / (self.max_samples - 1)
        y = mid_y - amp * self.samples[-1]
        pygame.draw.circle(surface, self.trace_rgb, (int(x), int(y)), 3)

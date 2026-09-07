# controlpanel/controls/lampgroups.py
#
# Multi-lamp controls: several lamps inside one sprite — the lamp bank
# (a row of indicator lights with patterns) and the LED matrix (a grid of
# dots running chases and random bitmaps).

import pygame

from .base import Control
from .lamps import _SPRITE_COLORS


class LampBankControl(Control):
    """
    A row of N lamps in one sprite. Patterns:
      chaser — a single lit lamp sweeps back and forth
      random — each lamp blinks independently
    Layout overrides: lamps, pattern, rate, colors (list of rgb), window.
    """

    def __init__(self, placed, ctx):
        super().__init__(placed, ctx)
        self.rng = ctx.rng
        self.count = int(self.spec.get("lamps", 4))
        self.pattern = str(self.spec.get("pattern", "chaser")).strip().lower()
        self.rate = float(self.spec.get("rate", 2.0))  # chaser steps/sec
        palette = [tuple(c) for c in self.spec.get("colors", [])]
        if "color" in self.spec:      # generic override: one color for all
            palette = [tuple(self.spec["color"])]
        if not palette:
            palette = list(_SPRITE_COLORS.values())
        self.colors = [palette[i % len(palette)] for i in range(self.count)]
        self.window = self._window(default=(0.08, 0.25, 0.84, 0.50))

        self.levels = [0.0] * self.count
        self.targets = [0.0] * self.count
        self.t = self.rng.uniform(0, 10)
        self._step_acc = 0.0
        self._chaser_pos = self.rng.randrange(self.count)
        self._chaser_dir = 1

    def update(self, dt: float):
        self.t += dt
        if self.pattern == "random":
            for i in range(self.count):
                if self.rng.random() < self.rate * 0.35 * dt:
                    self.targets[i] = 1.0 - self.targets[i]
        else:  # chaser
            self._step_acc += dt
            if self._step_acc >= 1.0 / max(0.1, self.rate):
                self._step_acc = 0.0
                self._chaser_pos += self._chaser_dir
                if self._chaser_pos >= self.count - 1 or self._chaser_pos <= 0:
                    self._chaser_dir *= -1
                    self._chaser_pos = max(0, min(self.count - 1, self._chaser_pos))
            self.targets = [1.0 if i == self._chaser_pos else 0.0
                            for i in range(self.count)]
        for i in range(self.count):
            rate = 16.0 if self.targets[i] > self.levels[i] else 6.0
            self.levels[i] += (self.targets[i] - self.levels[i]) * min(1.0, rate * dt)

    def draw_overlay(self, surface):
        wx, wy, ww, wh = self.window
        r = max(3, int(min(ww / self.count, wh) * 0.30))
        for i in range(self.count):
            cx = int(wx + ww * (i + 0.5) / self.count)
            cy = int(wy + wh / 2)
            lv = self.levels[i]
            if lv < 0.03:
                continue
            color = self.colors[i]
            halo = tuple(int(c * 0.35 * lv) for c in color)
            core = tuple(int(c * lv) for c in color)
            pygame.draw.circle(surface, halo, (cx, cy), int(r * 1.7))
            pygame.draw.circle(surface, core, (cx, cy), r)


class LedMatrixControl(Control):
    """
    A grid of LED dots. Modes cycle slowly between:
      random  — cells flip on/off independently (static-ish sparkle)
      rows    — a lit row sweeps downward
    Layout overrides: grid [cols, rows], window, color_rgb, rate.
    """

    def __init__(self, placed, ctx):
        super().__init__(placed, ctx)
        self.rng = ctx.rng
        cols, rows = self.spec.get("grid", [10, 10])
        self.cols, self.rows = int(cols), int(rows)
        self.color = self._color("color_rgb", (70, 255, 110))
        self.rate = float(self.spec.get("rate", 6.0))
        self.window = self._window(default=(0.12, 0.12, 0.76, 0.76))
        self.cells = [[self.rng.random() < 0.25 for _ in range(self.cols)]
                      for _ in range(self.rows)]
        self.mode = "random"
        self.mode_timer = self.rng.uniform(8.0, 16.0)
        self.sweep_row = 0
        self._acc = 0.0

    def update(self, dt: float):
        self.mode_timer -= dt
        if self.mode_timer <= 0.0:
            self.mode = "rows" if self.mode == "random" else "random"
            self.mode_timer = self.rng.uniform(8.0, 16.0)
        self._acc += dt
        step = 1.0 / max(0.5, self.rate)
        while self._acc >= step:
            self._acc -= step
            if self.mode == "random":
                for _ in range(3):
                    r = self.rng.randrange(self.rows)
                    c = self.rng.randrange(self.cols)
                    self.cells[r][c] = not self.cells[r][c]
            else:
                self.sweep_row = (self.sweep_row + 1) % self.rows
                for c in range(self.cols):
                    self.cells[self.sweep_row][c] = True
                    self.cells[(self.sweep_row - 2) % self.rows][c] = False

    def draw_overlay(self, surface):
        wx, wy, ww, wh = self.window
        cw = ww / self.cols
        ch = wh / self.rows
        r = max(1, int(min(cw, ch) * 0.32))
        off = (int(self.color[0] * 0.10), int(self.color[1] * 0.10),
               int(self.color[2] * 0.10))
        for row in range(self.rows):
            for col in range(self.cols):
                cx = int(wx + (col + 0.5) * cw)
                cy = int(wy + (row + 0.5) * ch)
                pygame.draw.circle(surface, self.color if self.cells[row][col]
                                   else off, (cx, cy), r)

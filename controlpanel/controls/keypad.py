# controlpanel/controls/keypad.py
#
# Keypad control (decision D5): a 3x4 key grid that "types" by itself —
# a random key highlights, its digit appears on the entry line, and when
# the line fills it is accepted (green blink) or rejected (red flash).

import pygame

from .. import seven_seg
from .base import Control

_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"]

# state machine
_IDLE, _PRESS, _HOLD, _ACCEPT, _REJECT = range(5)


class KeypadControl(Control):
    """
    Layout overrides: code_len, press_interval, entry_rgb, accept_rgb,
    reject_rgb.
    """

    def __init__(self, placed, ctx):
        super().__init__(placed, ctx)
        self.rng = ctx.rng
        self.code_len = int(self.spec.get("code_len", 6))
        lo, hi = self.spec.get("press_interval", [0.4, 1.2])
        self.interval = (float(lo), float(hi))
        self.entry_rgb = self._color("entry_rgb", ctx.trace_rgb)
        self.accept_rgb = tuple(self.spec.get("accept_rgb", (70, 255, 110)))
        self.reject_rgb = tuple(self.spec.get("reject_rgb", (255, 60, 50)))

        x, y, w, h = self.rect
        self.entry_rect = (x + 0.10 * w, y + 0.06 * h, 0.80 * w, 0.16 * h)
        self.grid_origin = (x + 0.12 * w, y + 0.28 * h)
        self.grid_size = (0.76 * w, 0.66 * h)

        self.state = _IDLE
        self.timer = self.rng.uniform(*self.interval)
        self.entry = ""
        self.pressed_key = -1

    def _key_rect(self, index):
        col, row = index % 3, index // 3
        gx, gy = self.grid_origin
        gw, gh = self.grid_size
        cw, ch = gw / 3, gh / 4
        return pygame.Rect(gx + col * cw + cw * 0.12, gy + row * ch + ch * 0.12,
                           cw * 0.76, ch * 0.76)

    def update(self, dt: float):
        self.timer -= dt
        if self.timer > 0.0:
            return

        if self.state == _IDLE:
            self.pressed_key = self.rng.randrange(len(_KEYS))
            self.state = _PRESS
            self.timer = 0.30
        elif self.state == _PRESS:
            key = _KEYS[self.pressed_key]
            if key.isdigit():
                self.entry += key
            self.pressed_key = -1
            if len(self.entry) >= self.code_len:
                self.state = _HOLD
                self.timer = 0.8
            else:
                self.state = _IDLE
                self.timer = self.rng.uniform(*self.interval)
        elif self.state == _HOLD:
            self.state = _REJECT if self.rng.random() < 0.25 else _ACCEPT
            self.timer = 0.7
        else:  # ACCEPT / REJECT flash done -> clear and start over
            self.entry = ""
            self.state = _IDLE
            self.timer = self.rng.uniform(*self.interval)

    def draw_overlay(self, surface):
        # entry line (7-seg; '*' and '#' never reach it — digits only)
        if self.state == _ACCEPT:
            color = self.accept_rgb
        elif self.state == _REJECT:
            color = self.reject_rgb
        else:
            color = self.entry_rgb
        if self.entry:
            seven_seg.draw_text(surface, self.entry, self.entry_rect, color)
        if self.state in (_ACCEPT, _REJECT):
            pygame.draw.rect(surface, color, self.entry_rect, 2)

        # key grid outlines + the currently pressed key highlighted
        for i in range(len(_KEYS)):
            rect = self._key_rect(i)
            pygame.draw.rect(surface, (70, 74, 80), rect, 1)
            if i == self.pressed_key:
                pygame.draw.rect(surface, self.entry_rgb, rect)

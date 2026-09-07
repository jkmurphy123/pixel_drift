# status_ticker_mode.py

import os
import time
import random
from datetime import datetime

import pygame


class StatusTickerMode:
    """
    Scene-style fullscreen "boot log" ticker.

    Config:
      - file
      - pause (sec per logical line)
      - scroll_px_per_sec
      - font_name
      - font_size (optional)
      - cursor_blink_hz
      - accent_probability
      - blank_lines_between_loops
    """

    def __init__(self, config: dict):
        self.file_path = config.get("file", "")
        self.pause = float(config.get("pause", 0.35))
        self.scroll_px_per_sec = float(config.get("scroll_px_per_sec", 180.0))
        self.font_name = config.get("font_name", "dejavusansmono")
        self.font_size_cfg = config.get("font_size", None)

        self.cursor_blink_hz = float(config.get("cursor_blink_hz", 2.0))
        self.accent_probability = float(config.get("accent_probability", 0.35))
        self.blank_lines_between_loops = int(config.get("blank_lines_between_loops", 20))

        self.cursor_char = "█"

        # runtime
        self.manager = None
        self.w = 0
        self.h = 0
        self.is_portrait = False

        # font/layout
        self.font = None
        self.font_size = 16
        self.line_h = 18
        self.margin_x = 20
        self.margin_y = 20
        self.usable_w = 100
        self.usable_h = 100
        self.max_visible_lines = 10
        self.cursor_w = 10

        # colors
        self.bg = (0, 0, 0)
        self.fg = (120, 255, 140)
        self.dim = (90, 180, 110)
        self.ok_base = (80, 220, 140)
        self.warn_base = (255, 210, 90)
        self.err_base = (255, 120, 120)

        # content
        self.base_lines = []
        self.loop_lines = []
        self.line_idx = 0
        self.blanks_left = 0

        # rendered rows & scrolling
        self.rendered_rows = []  # list[Surface]
        self.scroll_offset = 0.0
        self.target_scroll = 0.0
        self.last_overflow = 0

        # timing
        self.last_add_time = 0.0
        self.blink_period = 0.5
        self.cursor_on = True
        self.last_blink = 0.0

    # ---------------- lifecycle ----------------

    def enter(self, manager):
        self.manager = manager
        self._recompute_layout()

        self.base_lines = self._read_lines()
        self.loop_lines = self._build_loop_lines()

        self.line_idx = 0
        self.blanks_left = 0

        self.rendered_rows = []
        self.scroll_offset = 0.0
        self.target_scroll = 0.0
        self.last_overflow = 0

        now = time.time()
        self.last_add_time = now
        self.last_blink = now
        self.blink_period = 1.0 / max(0.1, self.cursor_blink_hz)
        self.cursor_on = True

    def exit(self):
        self.rendered_rows = []
        self.manager = None

    def handle_event(self, event):
        pass

    def update(self, dt: float):
        # resolution change
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            # re-render all cached rows at new font size/width
            old_logical = self._reconstruct_logical_stream()
            self.rendered_rows = []
            self.scroll_offset = 0.0
            self.target_scroll = 0.0
            self.last_overflow = 0
            for logical in old_logical:
                for surf in self._wrap_and_render_line(logical):
                    self.rendered_rows.append(surf)

        now = time.time()

        # blink cursor
        if (now - self.last_blink) >= self.blink_period:
            self.cursor_on = not self.cursor_on
            self.last_blink = now

        # add next line
        if (now - self.last_add_time) >= self.pause:
            logical = self._next_logical_line()
            self.last_add_time = now

            for surf in self._wrap_and_render_line(logical):
                self.rendered_rows.append(surf)

            overflow = max(0, len(self.rendered_rows) - self.max_visible_lines)
            if overflow > self.last_overflow:
                self.target_scroll += (overflow - self.last_overflow) * self.line_h
                self.last_overflow = overflow

        # smooth scroll
        if self.scroll_offset < self.target_scroll:
            self.scroll_offset += self.scroll_px_per_sec * dt
            if self.scroll_offset > self.target_scroll:
                self.scroll_offset = self.target_scroll

    def render(self, screen: pygame.Surface):
        screen.fill(self.bg)

        top_row = int(self.scroll_offset // self.line_h)
        frac = self.scroll_offset - (top_row * self.line_h)

        start = max(0, top_row - 1)
        end = min(len(self.rendered_rows), top_row + self.max_visible_lines + 2)

        y = self.margin_y - frac + (start - top_row) * self.line_h

        for i in range(start, end):
            surf = self.rendered_rows[i]
            screen.blit(surf, (self.margin_x, y))
            y += self.line_h

        # cursor at end of last rendered row
        if self.cursor_on and self.rendered_rows:
            last_idx = len(self.rendered_rows) - 1
            y_cursor = self.margin_y + (last_idx - top_row) * self.line_h - frac
            if (self.margin_y - self.line_h) <= y_cursor <= (self.margin_y + self.usable_h):
                last_surf = self.rendered_rows[last_idx]
                x_cursor = self.margin_x + last_surf.get_width() + 10
                if x_cursor + self.cursor_w < self.w - self.margin_x:
                    cursor_surf = self.font.render(self.cursor_char, True, self.fg)
                    screen.blit(cursor_surf, (x_cursor, y_cursor))

    # ---------------- internals ----------------

    def _recompute_layout(self):
        self.w, self.h = self.manager.screen.get_size()
        self.is_portrait = self.h > self.w

        if self.font_size_cfg is not None:
            self.font_size = int(self.font_size_cfg)
        else:
            self.font_size = max(14, int(self.w * (0.040 if self.is_portrait else 0.030)))
        self.font_size = max(10, int(self.font_size * 0.75))

        # font via controller cache
        self.font = self.manager.cache.get_font(self.font_name, self.font_size, bold=False)
        self.line_h = self.font.get_linesize() + 3

        self.margin_x = int(self.w * 0.06)
        self.margin_y = int(self.h * 0.06)
        self.usable_w = self.w - 2 * self.margin_x
        self.usable_h = self.h - 2 * self.margin_y
        self.max_visible_lines = max(1, self.usable_h // self.line_h)

        self.cursor_w = self.font.size(self.cursor_char)[0]

    def _read_lines(self):
        if not self.file_path:
            return ["[StatusTicker] No file configured. Add 'file' to this mode's config."]
        if not os.path.exists(self.file_path):
            return [f"[StatusTicker] File not found: {self.file_path}"]
        try:
            with open(self.file_path, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read().splitlines()
            return raw if raw else ["[StatusTicker] File is empty."]
        except Exception as e:
            return [f"[StatusTicker] Error reading file: {e}"]

    def _build_loop_lines(self):
        prelude = f"[{datetime.now().strftime('%H:%M:%S')}] Initializing status feed..."
        return [prelude, ""] + self.base_lines

    def _next_logical_line(self):
        if self.blanks_left > 0:
            self.blanks_left -= 1
            return ""

        logical = self.loop_lines[self.line_idx]
        self.line_idx += 1

        if self.line_idx >= len(self.loop_lines):
            self.blanks_left = self.blank_lines_between_loops
            self.line_idx = 0
            self.loop_lines = self._build_loop_lines()

        return logical

    def _jitter(self, rgb, amount=25):
        r, g, b = rgb
        return (
            max(0, min(255, r + random.randint(-amount, amount))),
            max(0, min(255, g + random.randint(-amount, amount))),
            max(0, min(255, b + random.randint(-amount, amount))),
        )

    def _choose_line_color(self, text):
        t = (text or "").strip().lower()
        if not t:
            return self.dim
        if ("[ ok" in t) or (" ok " in t) or t.startswith("ok"):
            return self._jitter(self.ok_base, 18) if random.random() < self.accent_probability else self.fg
        if ("[ warn" in t) or (" warn " in t) or ("warning" in t):
            return self._jitter(self.warn_base, 20) if random.random() < self.accent_probability else self.fg
        if ("[ fail" in t) or ("[ err" in t) or ("error" in t) or ("failed" in t):
            return self._jitter(self.err_base, 20) if random.random() < self.accent_probability else self.fg
        return self.fg

    def _wrap_text(self, text, max_width):
        if not text:
            return [""]
        words = text.split(" ")
        lines = []
        current = ""

        def fits(s):
            return self.font.size(s)[0] <= max_width

        for w in words:
            cand = w if current == "" else (current + " " + w)
            if fits(cand):
                current = cand
            else:
                if current:
                    lines.append(current)
                    current = w
                else:
                    chunk = ""
                    for ch in w:
                        cand2 = chunk + ch
                        if fits(cand2):
                            chunk = cand2
                        else:
                            if chunk:
                                lines.append(chunk)
                            chunk = ch
                    current = chunk
        if current:
            lines.append(current)
        return lines

    def _wrap_and_render_line(self, logical):
        color = self._choose_line_color(logical)
        wrapped = self._wrap_text(logical, self.usable_w)
        return [self.font.render(part, True, color if part.strip() else self.dim) for part in wrapped]

    def _reconstruct_logical_stream(self):
        """
        Best-effort: used only on resolution changes to keep something on screen.
        We cannot perfectly un-wrap rendered surfaces, so we rebuild from current feed position.
        """
        # This just returns the last N logical-ish items by replaying the file from scratch
        # up to current progress. It’s fine for kiosk behavior.
        replay = []
        # approximate: show only the tail
        # (safe + simple; avoids trying to "reverse wrap" surfaces)
        replay.extend(self._build_loop_lines()[: min(50, len(self._build_loop_lines()))])
        return replay[-50:]

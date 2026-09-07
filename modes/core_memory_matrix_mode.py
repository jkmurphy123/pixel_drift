import math
import random
from dataclasses import dataclass
from datetime import datetime

import pygame


@dataclass
class Pulse:
    row: int
    col: int
    kind: str
    ttl: float
    age: float = 0.0


@dataclass
class EventLine:
    t_end: float
    kind: str
    text: str


class CoreMemoryMatrixMode:
    """
    Core Memory Matrix
    - Ferrite-core memory plane with X/Y wire lattice
    - Read/write/inhibit pulses traversing the matrix
    - Address register, sense amplifier, parity, and cycle-status panels
    - Portrait/landscape responsive layout with subtle CRT treatment

    Config (optional):
      - title
      - bank_name
      - accent_rgb
      - seed
      - refresh_hz
      - rows
      - cols
      - write_probability_per_sec
      - read_probability_per_sec
      - parity_fault_probability_per_min
      - pulse_ttl
      - scanline_alpha
      - noise_alpha
      - vignette_strength
      - portrait_layout
    """

    def __init__(self, config: dict):
        self.title = str(config.get("title", "CORE MEMORY MATRIX"))
        self.bank_name = str(config.get("bank_name", "BANK A // 4K WORD STORE"))
        self.accent_rgb = tuple(config.get("accent_rgb", [255, 176, 96]))
        self.seed = config.get("seed", None)
        self.refresh_hz = float(config.get("refresh_hz", 60.0))
        self.rows = max(8, min(32, int(config.get("rows", 16))))
        self.cols = max(8, min(32, int(config.get("cols", 16))))
        self.write_probability_per_sec = float(config.get("write_probability_per_sec", 1.2))
        self.read_probability_per_sec = float(config.get("read_probability_per_sec", 1.8))
        self.parity_fault_probability_per_min = float(config.get("parity_fault_probability_per_min", 0.35))
        self.pulse_ttl = max(0.25, float(config.get("pulse_ttl", 1.1)))
        self.scanline_alpha = int(config.get("scanline_alpha", 10))
        self.noise_alpha = int(config.get("noise_alpha", 9))
        self.vignette_strength = float(config.get("vignette_strength", 0.28))
        self.portrait_layout = bool(config.get("portrait_layout", False))

        self.manager = None
        self.w = 0
        self.h = 0
        self._is_portrait = False
        self._t = 0.0
        self._rng = random.Random()

        self._bg = (8, 7, 6)
        self._fg = (230, 224, 210)
        self._dim = (138, 126, 112)
        self._ok = (124, 255, 156)
        self._warn = (255, 212, 110)
        self._alert = (255, 115, 115)

        self._pad = 0
        self._header_h = 0
        self._footer_h = 0
        self._content_rect = pygame.Rect(0, 0, 0, 0)
        self._matrix_rect = pygame.Rect(0, 0, 0, 0)
        self._status_rect = pygame.Rect(0, 0, 0, 0)
        self._log_rect = pygame.Rect(0, 0, 0, 0)

        self._font_header = None
        self._font_body = None
        self._font_small = None
        self._font_tiny = None

        self._overlay = None
        self._vignette = None

        self._bits = []
        self._drive_rows = []
        self._drive_cols = []
        self._sense_level = 0.0
        self._inhibit_level = 0.0
        self._parity_ok = True
        self._cycle_phase = "IDLE"
        self._cycle_code = "0000"
        self._current_addr = 0
        self._current_word = 0
        self._last_op = "STANDBY"
        self._pulses: list[Pulse] = []
        self._events: list[EventLine] = []
        self._chart_history = [0.45] * 160
        self._last_fault_t = -999.0

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._init_plane()
        self._recompute_layout()
        self._build_overlays()
        self._push_event("INFO", "core plane energized")
        self._push_event("INFO", f"mapping {self.bank_name}")
        self._push_event("INFO", "sense amplifiers nominal")

    def exit(self):
        self.manager = None
        self._overlay = None
        self._vignette = None
        self._pulses = []
        self._events = []

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self._issue_cycle("WRITE", forced=True)

    def update(self, dt: float):
        self._t += dt

        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            self._build_overlays()

        self._events = [e for e in self._events if e.t_end > self._t][-12:]
        self._tick_pulses(dt)
        self._decay_drives(dt)

        if self._rng.random() < max(0.0, self.read_probability_per_sec) * dt:
            self._issue_cycle("READ")
        if self._rng.random() < max(0.0, self.write_probability_per_sec) * dt:
            self._issue_cycle("WRITE")

        p_fault = max(0.0, self.parity_fault_probability_per_min) / 60.0
        if self._rng.random() < p_fault * dt:
            self._trigger_fault()

        self._tick_status(dt)

    def render(self, screen: pygame.Surface):
        screen.fill(self._bg)
        self._draw_header(screen)
        self._draw_matrix_panel(screen)
        self._draw_status_panel(screen)
        self._draw_log_panel(screen)
        self._draw_footer(screen)

        if self._overlay is not None:
            screen.blit(self._overlay, (0, 0))
        if self._vignette is not None:
            screen.blit(self._vignette, (0, 0))
        if self.noise_alpha > 0:
            self._draw_noise(screen)

    def _reseed(self):
        if self.seed is None:
            self.seed = random.randrange(1, 2**31 - 1)
        self._rng.seed(int(self.seed))

    def _init_plane(self):
        self._bits = []
        for _ in range(self.rows):
            row = []
            for _ in range(self.cols):
                row.append(self._rng.random() > 0.52)
            self._bits.append(row)
        self._drive_rows = [0.0] * self.rows
        self._drive_cols = [0.0] * self.cols
        self._current_addr = self._rng.randrange(self.rows * self.cols)
        self._update_current_word()

    def _recompute_layout(self):
        self.w, self.h = self.manager.screen.get_size()
        self._is_portrait = self.h > self.w
        base = min(self.w, self.h)

        self._pad = int(base * 0.045)
        self._header_h = max(86, int(self.h * 0.14))
        self._footer_h = max(44, int(self.h * 0.06))
        self._content_rect = pygame.Rect(
            self._pad,
            self._header_h,
            self.w - 2 * self._pad,
            self.h - self._header_h - self._footer_h,
        )

        cr = self._content_rect
        if self._is_portrait or self.portrait_layout:
            matrix_h = int(cr.height * 0.52)
            status_h = int(cr.height * 0.24)
            log_h = cr.height - matrix_h - status_h - 16
            self._matrix_rect = pygame.Rect(cr.left, cr.top, cr.width, matrix_h)
            self._status_rect = pygame.Rect(cr.left, self._matrix_rect.bottom + 8, cr.width, status_h)
            self._log_rect = pygame.Rect(cr.left, self._status_rect.bottom + 8, cr.width, log_h)
        else:
            left_w = int(cr.width * 0.60)
            self._matrix_rect = pygame.Rect(cr.left, cr.top, left_w, cr.height)
            right = pygame.Rect(self._matrix_rect.right + 8, cr.top, cr.width - left_w - 8, cr.height)
            status_h = int(right.height * 0.56)
            self._status_rect = pygame.Rect(right.left, right.top, right.width, status_h)
            self._log_rect = pygame.Rect(right.left, self._status_rect.bottom + 8, right.width, right.height - status_h - 8)

        self._font_header = self.manager.cache.get_font("dejavusansmono", max(18, int(base * 0.046)), bold=True)
        self._font_body = self.manager.cache.get_font("dejavusansmono", max(13, int(base * 0.024)), bold=False)
        self._font_small = self.manager.cache.get_font("dejavusansmono", max(11, int(base * 0.018)), bold=False)
        self._font_tiny = self.manager.cache.get_font("dejavusansmono", max(10, int(base * 0.014)), bold=False)

    def _build_overlays(self):
        self._overlay = None
        self._vignette = None

    def _build_vignette(self, w: int, h: int, strength: float):
        strength = max(0.0, min(1.0, float(strength)))
        if strength <= 0.0:
            return None
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        layers = 68
        max_alpha = int(190 * strength)
        for i in range(layers):
            alpha = int(max_alpha * (i / layers) ** 1.8)
            pygame.draw.rect(surf, (0, 0, 0, alpha), pygame.Rect(i, i, w - 2 * i, h - 2 * i), 1)
        return surf

    def _issue_cycle(self, op: str, forced: bool = False):
        row = self._rng.randrange(self.rows)
        col = self._rng.randrange(self.cols)
        self._current_addr = row * self.cols + col

        self._drive_rows[row] = 1.0
        self._drive_cols[col] = 1.0
        self._pulses.append(Pulse(row=row, col=col, kind=op, ttl=self.pulse_ttl))

        bit = self._bits[row][col]
        if op == "WRITE":
            new_bit = not bit if self._rng.random() > 0.25 or forced else bit
            self._bits[row][col] = new_bit
            self._inhibit_level = 1.0 if not new_bit else 0.35
            self._sense_level = 0.65 if new_bit else 0.25
        else:
            self._sense_level = 0.88 if bit else 0.36
            self._inhibit_level = 0.18

        self._cycle_phase = self._rng.choice(["X DRIVE", "Y SELECT", "SENSE", "RESTORE"])
        self._cycle_code = f"{self._rng.randrange(0, 16):X}{self._rng.randrange(0, 16):X}{row:02d}{col:02d}"
        self._last_op = op
        self._update_current_word()

        if forced:
            self._push_event("WARN", f"manual {op.lower()} pulse at plane {row:02d}-{col:02d}")

    def _trigger_fault(self):
        if self._t - self._last_fault_t < 10.0:
            return
        self._last_fault_t = self._t
        self._parity_ok = False
        self._push_event("ALERT", "parity check mismatch on restore cycle")

    def _tick_pulses(self, dt: float):
        next_pulses = []
        for pulse in self._pulses:
            pulse.age += dt
            if pulse.age < pulse.ttl:
                next_pulses.append(pulse)
        self._pulses = next_pulses

    def _decay_drives(self, dt: float):
        decay = max(0.0, 1.75 * dt)
        for i, value in enumerate(self._drive_rows):
            self._drive_rows[i] = max(0.0, value - decay)
        for i, value in enumerate(self._drive_cols):
            self._drive_cols[i] = max(0.0, value - decay)
        self._sense_level = max(0.0, self._sense_level - decay * 0.8)
        self._inhibit_level = max(0.0, self._inhibit_level - decay * 0.7)

    def _tick_status(self, dt: float):
        self._chart_history.append(max(0.05, min(0.95, 0.44 + 0.22 * math.sin(self._t * 1.4) + self._sense_level * 0.22 + self._rng.uniform(-0.04, 0.04))))
        if len(self._chart_history) > 160:
            self._chart_history.pop(0)

        if not self._parity_ok and self._rng.random() < 0.75 * dt:
            self._parity_ok = True
            self._push_event("INFO", "parity latch reset; bank returned to service")

        if self._rng.random() < 0.55 * dt:
            self._cycle_phase = self._rng.choice(["IDLE", "X DRIVE", "Y SELECT", "SENSE", "RESTORE"])

    def _update_current_word(self):
        row = self._current_addr // self.cols
        base_col = (self._current_addr % self.cols)
        value = 0
        for bit_idx in range(min(8, self.cols)):
            col = (base_col + bit_idx) % self.cols
            if self._bits[row][col]:
                value |= (1 << (7 - bit_idx))
        self._current_word = value

    def _push_event(self, kind: str, text: str):
        ttl = 20.0 if kind != "ALERT" else 26.0
        self._events.append(EventLine(self._t + ttl, kind, text.upper()))

    def _panel_box(self, screen, rect: pygame.Rect, label: str):
        pygame.draw.rect(screen, (18, 17, 16), rect)
        pygame.draw.rect(screen, self.accent_rgb, rect, 2)
        surf = self._font_tiny.render(label, True, self.accent_rgb)
        screen.blit(surf, (rect.left + 10, rect.top + 8))

    def _draw_header(self, screen):
        title = self._font_header.render(self.title, True, self.accent_rgb)
        bank = self._font_body.render(self.bank_name, True, self._fg)
        screen.blit(title, (self._pad, int(self._header_h * 0.20)))
        screen.blit(bank, (self._pad, int(self._header_h * 0.60)))

        stamp = datetime.now().strftime("%H:%M:%S")
        rhs = self._font_body.render(f"CYCLE {self._cycle_phase}   {stamp}", True, self._fg)
        screen.blit(rhs, (self.w - self._pad - rhs.get_width(), int(self._header_h * 0.34)))

    def _draw_matrix_panel(self, screen):
        rect = self._matrix_rect
        self._panel_box(screen, rect, "FERRITE CORE PLANE")
        inner = rect.inflate(-20, -24)
        inner.y += 12

        chart_h = max(46, int(inner.height * 0.16))
        matrix_area = pygame.Rect(inner.left, inner.top, inner.width, inner.height - chart_h - 10)
        chart_rect = pygame.Rect(inner.left, matrix_area.bottom + 10, inner.width, chart_h)

        self._draw_core_plane(screen, matrix_area)
        self._draw_sense_chart(screen, chart_rect)

    def _draw_core_plane(self, screen, rect: pygame.Rect):
        pygame.draw.rect(screen, (10, 10, 10), rect)
        pygame.draw.rect(screen, (72, 66, 60), rect, 1)

        left_pad = 56
        top_pad = 32
        bottom_pad = 22
        right_pad = 22
        grid = pygame.Rect(rect.left + left_pad, rect.top + top_pad, rect.width - left_pad - right_pad, rect.height - top_pad - bottom_pad)
        dx = grid.width / max(1, self.cols - 1)
        dy = grid.height / max(1, self.rows - 1)

        for row in range(self.rows):
            y = int(grid.top + row * dy)
            drive = self._drive_rows[row]
            wire = self.accent_rgb if drive > 0.01 else (94, 82, 70)
            width = 2 if drive > 0.35 else 1
            pygame.draw.line(screen, wire, (grid.left, y), (grid.right, y), width)
            lbl = self._font_tiny.render(f"X{row:02d}", True, self._fg if drive > 0.1 else self._dim)
            screen.blit(lbl, (rect.left + 6, y - lbl.get_height() // 2))

        for col in range(self.cols):
            x = int(grid.left + col * dx)
            drive = self._drive_cols[col]
            wire = self._warn if drive > 0.01 else (94, 82, 70)
            width = 2 if drive > 0.35 else 1
            pygame.draw.line(screen, wire, (x, grid.top), (x, grid.bottom), width)
            lbl = self._font_tiny.render(f"Y{col:02d}", True, self._fg if drive > 0.1 else self._dim)
            label = pygame.transform.rotate(lbl, 90)
            screen.blit(label, (x - label.get_width() // 2, rect.top + 2))

        for row in range(self.rows):
            y = int(grid.top + row * dy)
            for col in range(self.cols):
                x = int(grid.left + col * dx)
                self._draw_core(screen, x, y, row, col)

    def _draw_core(self, screen, x: int, y: int, row: int, col: int):
        bit = self._bits[row][col]
        pulse_strength = 0.0
        pulse_kind = None
        for pulse in self._pulses:
            if pulse.row == row and pulse.col == col:
                pulse_strength = max(pulse_strength, 1.0 - (pulse.age / pulse.ttl))
                pulse_kind = pulse.kind

        core_color = self._ok if bit else (64, 58, 52)
        if pulse_kind == "WRITE":
            core_color = self._warn
        elif pulse_kind == "READ":
            core_color = self.accent_rgb

        outer = 8
        inner = 4
        pygame.draw.circle(screen, (42, 36, 30), (x, y), outer)
        pygame.draw.circle(screen, core_color, (x, y), outer - 1, 2)
        pygame.draw.circle(screen, self._bg, (x, y), inner)
        pygame.draw.line(screen, (116, 104, 92), (x - 9, y - 9), (x + 9, y + 9), 1)
        pygame.draw.line(screen, (116, 104, 92), (x - 9, y + 9), (x + 9, y - 9), 1)

        if pulse_strength > 0.0:
            radius = int(11 + 9 * pulse_strength)
            alpha = int(120 * pulse_strength)
            surf = pygame.Surface((radius * 2 + 4, radius * 2 + 4), pygame.SRCALPHA)
            pygame.draw.circle(surf, (*core_color, alpha), (radius + 2, radius + 2), radius, 2)
            screen.blit(surf, (x - radius - 2, y - radius - 2))

    def _draw_sense_chart(self, screen, rect: pygame.Rect):
        pygame.draw.rect(screen, (12, 12, 12), rect)
        pygame.draw.rect(screen, (80, 74, 68), rect, 1)
        label = self._font_tiny.render("SENSE LINE ENVELOPE", True, self.accent_rgb)
        screen.blit(label, (rect.left + 8, rect.top + 6))

        graph = rect.inflate(-10, -18)
        pts = []
        denom = max(1, len(self._chart_history) - 1)
        for i, value in enumerate(self._chart_history):
            gx = graph.left + int(graph.width * i / denom)
            gy = graph.bottom - int(graph.height * value)
            pts.append((gx, gy))
        if len(pts) > 1:
            pygame.draw.lines(screen, self.accent_rgb, False, pts, 2)

    def _draw_status_panel(self, screen):
        rect = self._status_rect
        self._panel_box(screen, rect, "DRIVE / REGISTER STATUS")
        inner = rect.inflate(-18, -22)
        inner.y += 12

        upper_h = int(inner.height * 0.54)
        upper = pygame.Rect(inner.left, inner.top, inner.width, upper_h)
        lower = pygame.Rect(inner.left, upper.bottom + 8, inner.width, inner.height - upper_h - 8)

        self._draw_registers(screen, upper)
        self._draw_levels(screen, lower)

    def _draw_registers(self, screen, rect: pygame.Rect):
        left_w = int(rect.width * 0.48)
        left = pygame.Rect(rect.left, rect.top, left_w, rect.height)
        right = pygame.Rect(left.right + 8, rect.top, rect.width - left_w - 8, rect.height)

        rows = [
            ("ADDR", f"{self._current_addr:04X}"),
            ("WORD", f"{self._current_word:02X}"),
            ("OP", self._last_op),
            ("CYCL", self._cycle_code),
        ]
        for idx, (k, v) in enumerate(rows):
            y = left.top + idx * (self._font_body.get_linesize() + 8)
            ks = self._font_small.render(k, True, self.accent_rgb)
            vs = self._font_body.render(v, True, self._fg)
            screen.blit(ks, (left.left, y))
            screen.blit(vs, (left.left + 64, y - 1))

        parity = "OK" if self._parity_ok else "FAULT"
        pcolor = self._ok if self._parity_ok else self._alert
        items = [
            ("SENSE AMP", f"{int(self._sense_level * 100):03d}%"),
            ("INHIBIT", f"{int(self._inhibit_level * 100):03d}%"),
            ("PARITY", parity),
            ("MARGIN", self._rng.choice(["GOOD", "TIGHT", "STABLE"])),
        ]
        for idx, (k, v) in enumerate(items):
            y = right.top + idx * (self._font_small.get_linesize() + 8)
            color = pcolor if k == "PARITY" else self._fg
            ks = self._font_small.render(k, True, self.accent_rgb)
            vs = self._font_small.render(v, True, color)
            screen.blit(ks, (right.left, y))
            screen.blit(vs, (right.left + 88, y))

    def _draw_levels(self, screen, rect: pygame.Rect):
        bar_gap = 10
        bar_h = max(12, (rect.height - bar_gap * 2) // 3)
        bars = [
            ("X DRIVE", max(self._drive_rows) if self._drive_rows else 0.0, self.accent_rgb),
            ("Y DRIVE", max(self._drive_cols) if self._drive_cols else 0.0, self._warn),
            ("SENSE", self._sense_level, self._ok if self._parity_ok else self._alert),
        ]
        for idx, (label, value, color) in enumerate(bars):
            y = rect.top + idx * (bar_h + bar_gap)
            bar = pygame.Rect(rect.left, y + 16, rect.width, bar_h)
            pygame.draw.rect(screen, (26, 24, 22), bar)
            pygame.draw.rect(screen, (90, 84, 76), bar, 1)
            fill = int(bar.width * max(0.0, min(1.0, value)))
            pygame.draw.rect(screen, color, pygame.Rect(bar.left, bar.top, fill, bar.height))
            surf = self._font_tiny.render(label, True, self._fg)
            screen.blit(surf, (bar.left, y))

    def _draw_log_panel(self, screen):
        rect = self._log_rect
        self._panel_box(screen, rect, "CYCLE LOG")
        inner = rect.inflate(-18, -20)
        inner.y += 14

        line_h = self._font_small.get_linesize() + 4
        visible = max(1, inner.height // line_h)
        lines = self._events[-visible:]
        if not lines:
            lines = [EventLine(self._t + 1.0, "INFO", "STANDBY - PLANE READY")]

        for idx, event in enumerate(lines):
            y = inner.top + idx * line_h
            color = self._fg
            if event.kind == "WARN":
                color = self._warn
            elif event.kind == "ALERT":
                color = self._alert

            stamp = self._font_tiny.render(f"T{int(self._t * 10):05d}", True, self._dim)
            kind = self._font_tiny.render(event.kind, True, color)
            text = self._font_small.render(event.text, True, self._fg)
            screen.blit(stamp, (inner.left, y + 2))
            screen.blit(kind, (inner.left + 58, y + 2))
            screen.blit(text, (inner.left + 118, y))

    def _draw_footer(self, screen):
        y = self.h - self._footer_h + 10
        left = self._font_small.render(f"ROWS {self.rows:02d}   COLS {self.cols:02d}   SEED {self.seed}", True, self._dim)
        right = self._font_small.render(f"MODE: {self._last_op}   REFRESH {int(self.refresh_hz)} HZ", True, self._dim)
        screen.blit(left, (self._pad, y))
        screen.blit(right, (self.w - self._pad - right.get_width(), y))

    def _draw_noise(self, screen):
        specks = max(18, (self.w * self.h) // 26000)
        for _ in range(specks):
            x = self._rng.randrange(0, self.w)
            y = self._rng.randrange(0, self.h)
            alpha = self._rng.randint(16, 16 + self.noise_alpha * 3)
            screen.fill((255, 255, 255, alpha), pygame.Rect(x, y, 1, 1), special_flags=pygame.BLEND_RGBA_ADD)

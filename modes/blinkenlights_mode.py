import math
import random
import time

import pygame


class BlinkenlightsPanelMode:
    """
    Scene-style blinkenlights panel.

    Backward compatible with the original config, with optional extras:
      - subtitle
      - ticker_text
      - panel_id
      - status_labels
      - frame_rgb
      - label_rgb
      - panel_fill_rgb
      - status_probability_per_sec
      - row_group_size
    """

    def __init__(self, config: dict):
        self.computer_name = config.get("computer_name", "UNKNOWN SYSTEM")
        self.subtitle = str(config.get("subtitle", "")).strip()
        self.ticker_text = str(config.get("ticker_text", "NO FAULTS // STANDBY")).strip()
        self.panel_id = str(config.get("panel_id", "PANEL A")).strip()

        self.columns = int(config.get("columns", 2))
        self.registers_per_column = int(config.get("registers_per_column", 6))

        self.register_labels = list(config.get("register_labels", [])) or [
            "CLK", "IPTR", "ACC", "IR", "SP", "TMP",
            "MAR", "MDR", "PC", "FLAG", "ALU", "MMIO"
        ]

        self.status_labels = list(config.get("status_labels", [])) or [
            "RUN", "MEM", "I/O", "TAPE", "SYNC", "CHK"
        ]

        self.title_font_scale = float(config.get("title_font_scale", 0.10))
        self.label_font_scale = float(config.get("label_font_scale", 0.045))
        self.led_radius_scale = float(config.get("led_radius_scale", 0.018))
        self.pulse_speed = float(config.get("pulse_speed", 0.6))
        self.status_probability_per_sec = float(config.get("status_probability_per_sec", 0.65))
        self.row_group_size = max(0, int(config.get("row_group_size", 0)))

        self.led_color = str(config.get("led_color", "Red")).strip()
        self.frame_rgb = tuple(config.get("frame_rgb", [208, 208, 198]))
        self.label_rgb = tuple(config.get("label_rgb", [220, 220, 220]))
        self.panel_fill_rgb = tuple(config.get("panel_fill_rgb", [12, 12, 12]))
        self._led_on_base = (255, 40, 40)
        self._led_off = (60, 0, 0)

        self.burst_probability_per_sec = float(config.get("burst_probability_per_sec", 0.18))
        self.burst_duration_range = config.get("burst_duration_range", [0.6, 1.4])
        self.burst_registers_range = config.get("burst_registers_range", [1, 3])
        self.burst_strength = float(config.get("burst_strength", 1.8))

        self.title_gap_shrink = float(config.get("title_gap_shrink", 0.35))
        self.col_pad_scale = float(config.get("col_pad_scale", 0.02))
        self.border_thickness = int(config.get("border_thickness", 2))

        self.manager = None
        self.w = 0
        self.h = 0
        self.t0 = 0.0

        self._phases = [
            random.uniform(0, math.tau)
            for _ in range(len(self.register_labels) * 8)
        ]
        self._register_bias = [random.uniform(0.75, 1.25) for _ in range(len(self.register_labels))]
        self._status_states = [random.random() > 0.45 for _ in range(len(self.status_labels))]
        self._status_phases = [random.uniform(0, math.tau) for _ in range(len(self.status_labels))]

        self._burst_active_until = 0.0
        self._burst_register_set = set()
        self._burst_mode = "sparkle"
        self._burst_walk_pos = 0

        self._title_font_px = 0
        self._subtitle_font_px = 0
        self._label_font_px = 0
        self._tiny_font_px = 0
        self._led_radius = 0

    def _resolve_led_colors(self):
        name = (self.led_color or "Red").strip().lower()
        palette = {
            "red": (255, 40, 40),
            "orange": (255, 140, 40),
            "yellow": (255, 230, 60),
            "green": (70, 255, 110),
            "blue": (80, 170, 255),
            "purple": (180, 90, 255),
            "pink": (255, 90, 190),
            "white": (245, 245, 245),
            "amber": (255, 176, 64),
        }
        on = palette.get(name, palette["red"])
        off = (
            max(10, int(on[0] * 0.18)),
            max(10, int(on[1] * 0.18)),
            max(10, int(on[2] * 0.18)),
        )
        self._led_on_base = on
        self._led_off = off

    def enter(self, manager):
        self.manager = manager
        self.w, self.h = manager.screen.get_size()
        self.t0 = time.time()
        self._recompute_scaled_metrics()
        self._resolve_led_colors()

    def exit(self):
        self.manager = None

    def handle_event(self, event):
        pass

    def update(self, dt: float):
        now = time.time()

        if now >= self._burst_active_until:
            if random.random() < (self.burst_probability_per_sec * dt):
                self._start_burst(now)

        if now < self._burst_active_until and self._burst_mode == "walk":
            if int((now * 1000) / 90) != int(((now - dt) * 1000) / 90):
                self._burst_walk_pos = (self._burst_walk_pos + 1) % 8

        for idx in range(len(self.status_states)):
            if random.random() < self.status_probability_per_sec * dt * 0.25:
                self._status_states[idx] = not self._status_states[idx]
            self._status_phases[idx] += dt * random.uniform(0.8, 1.6)

        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self.w, self.h = w2, h2
            self._recompute_scaled_metrics()

    def render(self, screen: pygame.Surface):
        bg = (4, 4, 4)
        led_off = self._led_off
        led_on_base = self._led_on_base
        label_color = self.label_rgb
        border_color = self.frame_rgb

        w, h = self.w, self.h
        screen.fill(bg)

        title_font = self.manager.cache.get_font("dejavusansmono", self._title_font_px, bold=True)
        subtitle_font = self.manager.cache.get_font("dejavusansmono", self._subtitle_font_px, bold=False)
        label_font = self.manager.cache.get_font("dejavusansmono", self._label_font_px, bold=False)
        tiny_font = self.manager.cache.get_font("dejavusansmono", self._tiny_font_px, bold=False)

        header_h = max(64, int(h * 0.12))
        footer_h = max(42, int(h * 0.07))
        outer_pad = int(min(w, h) * 0.035)
        status_h = max(38, int(h * 0.075))

        header_rect = pygame.Rect(outer_pad, outer_pad, w - outer_pad * 2, header_h)
        status_rect = pygame.Rect(outer_pad, header_rect.bottom + 8, w - outer_pad * 2, status_h)
        panel_rect = pygame.Rect(
            outer_pad,
            status_rect.bottom + 10,
            w - outer_pad * 2,
            h - outer_pad - footer_h - (status_rect.bottom + 10),
        )
        footer_rect = pygame.Rect(outer_pad, h - outer_pad - footer_h, w - outer_pad * 2, footer_h)

        pygame.draw.rect(screen, self.panel_fill_rgb, header_rect)
        pygame.draw.rect(screen, border_color, header_rect, max(1, self.border_thickness))
        pygame.draw.rect(screen, self.panel_fill_rgb, status_rect)
        pygame.draw.rect(screen, border_color, status_rect, max(1, self.border_thickness))
        pygame.draw.rect(screen, self.panel_fill_rgb, panel_rect)
        pygame.draw.rect(screen, border_color, panel_rect, max(1, self.border_thickness))
        pygame.draw.rect(screen, self.panel_fill_rgb, footer_rect)
        pygame.draw.rect(screen, border_color, footer_rect, max(1, self.border_thickness))

        title_surf = title_font.render(self.computer_name, True, label_color)
        screen.blit(title_surf, (header_rect.left + 18, header_rect.top + 12))
        if self.subtitle:
            subtitle_surf = subtitle_font.render(self.subtitle, True, border_color)
            screen.blit(subtitle_surf, (header_rect.left + 20, title_surf.get_rect().bottom + header_rect.top + 8))

        panel_id_surf = tiny_font.render(self.panel_id, True, border_color)
        screen.blit(panel_id_surf, (header_rect.right - panel_id_surf.get_width() - 16, header_rect.top + 12))

        self._draw_status_lamps(screen, status_rect, tiny_font)

        col_pad = int(panel_rect.width * self.col_pad_scale)
        inner_rect = panel_rect.inflate(-18, -18)
        col_width = max(1, inner_rect.width // max(1, self.columns))
        row_height = max(1, inner_rect.height // max(1, self.registers_per_column))
        led_radius = self._led_radius
        led_spacing = int(led_radius * 2.55)
        leds_total_w = 7 * led_spacing + 2 * led_radius
        border_thickness = max(1, self.border_thickness)

        for c in range(self.columns):
            x0 = inner_rect.left + c * col_width + col_pad // 2
            w0 = col_width - col_pad
            rect = pygame.Rect(x0, inner_rect.top, w0, inner_rect.height)
            pygame.draw.rect(screen, (16, 16, 16), rect)
            pygame.draw.rect(screen, border_color, rect, border_thickness)

            if c < self.columns - 1:
                bus_x = rect.right + (col_pad // 2)
                pygame.draw.line(screen, border_color, (bus_x, rect.top + 16), (bus_x, rect.bottom - 16), 1)

        now = time.time()
        t = now - self.t0
        phase_idx = 0

        for idx, label in enumerate(self.register_labels):
            col = idx // self.registers_per_column
            row = idx % self.registers_per_column
            if col >= self.columns:
                break

            col_left = inner_rect.left + col * col_width
            inner_left = col_left + col_pad
            inner_right = col_left + col_width - col_pad

            y = inner_rect.top + row * row_height
            cy = y + (row_height // 2)

            if self.row_group_size and row > 0 and (row % self.row_group_size == 0):
                sep_y = y - max(2, row_height // 10)
                pygame.draw.line(screen, border_color, (col_left + 10, sep_y), (col_left + col_width - 10, sep_y), 1)

            label_surf = label_font.render(label, True, label_color)
            label_y = cy - (label_surf.get_height() // 2)
            screen.blit(label_surf, (inner_left, label_y))

            right_inset = col_pad
            leds_x = inner_right - right_inset - leds_total_w
            min_leds_x = inner_left + int((inner_right - inner_left) * 0.24)
            leds_x = max(leds_x, min_leds_x)

            is_burst_reg = now < self._burst_active_until and idx in self._burst_register_set
            reg_bias = self._register_bias[idx % len(self._register_bias)]

            for bit in range(8):
                phase = self._phases[phase_idx]
                phase_idx += 1

                base_wave = (math.sin(t * self.pulse_speed + phase) + 1.0) / 2.0
                secondary = (math.sin(t * (self.pulse_speed * 0.45) + phase * 1.8 + idx * 0.2) + 1.0) / 2.0
                intensity = (0.08 + 0.72 * base_wave + 0.20 * secondary) * reg_bias

                if is_burst_reg:
                    if self._burst_mode == "sparkle":
                        flick = (math.sin(t * 9.0 + phase * 3.0) + 1.0) / 2.0
                        intensity *= (1.0 + 1.05 * flick) * self.burst_strength
                    else:
                        intensity *= 1.0 + 0.45 * ((math.sin(t * 6.0 + phase) + 1.0) / 2.0)
                        if bit == self._burst_walk_pos:
                            intensity *= 2.4 * self.burst_strength

                intensity = max(0.0, min(2.6, intensity))
                color = (
                    int(min(255, led_on_base[0] * intensity)),
                    int(min(255, led_on_base[1] * intensity)),
                    int(min(255, led_on_base[2] * intensity)),
                )

                cx = leds_x + bit * led_spacing
                self._draw_led(screen, cx, cy, led_radius, color, led_off)

        ticker = tiny_font.render(self.ticker_text, True, label_color)
        footer_left = tiny_font.render("ACTIVITY BUS", True, border_color)
        screen.blit(footer_left, (footer_rect.left + 14, footer_rect.top + 12))
        screen.blit(ticker, (footer_rect.right - ticker.get_width() - 14, footer_rect.top + 12))

    def _draw_led(self, screen, cx: int, cy: int, radius: int, color, off_color):
        glow_r = radius + max(2, radius // 2)
        glow = pygame.Surface((glow_r * 2 + 4, glow_r * 2 + 4), pygame.SRCALPHA)
        pygame.draw.circle(glow, (*color, 44), (glow_r + 2, glow_r + 2), glow_r)
        screen.blit(glow, (cx - glow_r - 2, cy - glow_r - 2))
        pygame.draw.circle(screen, color, (cx, cy), radius)
        pygame.draw.circle(screen, off_color, (cx, cy), radius, 1)

    def _draw_status_lamps(self, screen, rect: pygame.Rect, tiny_font):
        lamp_count = max(1, len(self.status_labels))
        gap = max(10, rect.width // (lamp_count * 10))
        total_gap = gap * (lamp_count - 1)
        lamp_w = max(36, (rect.width - 24 - total_gap) // lamp_count)
        lamp_h = max(18, rect.height - 18)
        x = rect.left + 12
        y = rect.top + (rect.height - lamp_h) // 2

        for idx, label in enumerate(self.status_labels):
            lamp_rect = pygame.Rect(x, y, lamp_w, lamp_h)
            state = self._status_states[idx]
            pulse = 0.65 + 0.35 * math.sin(self._status_phases[idx])
            on = self._led_on_base if state else self._led_off
            fill = (
                min(255, int(on[0] * (pulse if state else 0.55))),
                min(255, int(on[1] * (pulse if state else 0.55))),
                min(255, int(on[2] * (pulse if state else 0.55))),
            )

            pygame.draw.rect(screen, fill, lamp_rect, border_radius=3)
            pygame.draw.rect(screen, self.frame_rgb, lamp_rect, 1, border_radius=3)
            surf = tiny_font.render(label, True, (10, 10, 10) if state else self.label_rgb)
            screen.blit(
                surf,
                (
                    lamp_rect.centerx - surf.get_width() // 2,
                    lamp_rect.centery - surf.get_height() // 2,
                ),
            )
            x += lamp_w + gap

    def _recompute_scaled_metrics(self):
        base = min(self.w, self.h)
        self._title_font_px = max(22, int(base * self.title_font_scale))
        self._subtitle_font_px = max(11, int(base * 0.020))
        self._label_font_px = max(11, int(base * self.label_font_scale))
        self._tiny_font_px = max(10, int(base * 0.015))
        self._led_radius = max(5, int(base * self.led_radius_scale))

    def _start_burst(self, now: float):
        dur = random.uniform(float(self.burst_duration_range[0]), float(self.burst_duration_range[1]))
        n_regs = random.randint(int(self.burst_registers_range[0]), int(self.burst_registers_range[1]))
        n_regs = max(1, min(n_regs, len(self.register_labels)))
        self._burst_register_set = set(random.sample(range(len(self.register_labels)), n_regs))
        self._burst_active_until = now + dur
        self._burst_mode = random.choice(["sparkle", "walk"])
        self._burst_walk_pos = random.randint(0, 7)

import math
import random
from dataclasses import dataclass
from datetime import datetime

import pygame


@dataclass
class EventLine:
    t_end: float
    kind: str
    text: str


class RBMKReactorSimulationMode:
    """
    Stylized reactor-control simulation inspired by explanatory RBMK accident visualizations.

    This is not a physics-grade model. It is a kiosk visualization that communicates:
      - control rod insertion / withdrawal
      - power level changes
      - xenon buildup after low-power operation
      - rising void fraction during the test
      - a SCRAM sequence with an initial positive reactivity spike
    """

    def __init__(self, config: dict):
        self.title = str(config.get("title", "RBMK REACTOR CONTROL SIMULATION"))
        self.reactor_name = str(config.get("reactor_name", "UNIT 4 // TURBINE TEST"))
        self.accent_rgb = tuple(config.get("accent_rgb", [255, 164, 96]))
        self.seed = config.get("seed", None)
        self.refresh_hz = float(config.get("refresh_hz", 60.0))
        self.rows = max(8, min(20, int(config.get("rows", 12))))
        self.cols = max(8, min(20, int(config.get("cols", 12))))
        self.loop_duration_sec = max(24.0, float(config.get("loop_duration_sec", 38.0)))
        self.portrait_layout = bool(config.get("portrait_layout", True))

        self.manager = None
        self.w = 0
        self.h = 0
        self._is_portrait = False
        self._rng = random.Random()
        self._t = 0.0

        self._bg = (7, 8, 10)
        self._fg = (232, 226, 214)
        self._dim = (132, 128, 120)
        self._warn = (255, 206, 110)
        self._alert = (255, 112, 112)
        self._cool = (100, 210, 255)
        self._hot = (255, 148, 88)

        self._pad = 0
        self._header_h = 0
        self._footer_h = 0
        self._content_rect = pygame.Rect(0, 0, 0, 0)
        self._core_rect = pygame.Rect(0, 0, 0, 0)
        self._status_rect = pygame.Rect(0, 0, 0, 0)
        self._log_rect = pygame.Rect(0, 0, 0, 0)

        self._font_header = None
        self._font_body = None
        self._font_small = None
        self._font_tiny = None

        self._events: list[EventLine] = []
        self._core_bias = []
        self._power_history = []
        self._void_history = []
        self._rod_history = []

        self._phase_name = "NORMAL"
        self._phase_progress = 0.0
        self._power = 1.0
        self._power_target = 1.0
        self._void_fraction = 0.12
        self._xenon = 0.12
        self._rod_fraction = 0.62
        self._pump_flow = 0.84
        self._turbine_rpm = 3000
        self._scram = False
        self._spike = 0.0
        self._channel_temps = []

        self._phase_schedule = [
            (0.00, 0.18, "EVENT 1 // REACTOR NORMAL"),
            (0.18, 0.34, "EVENT 2 // POWER REDUCTION"),
            (0.34, 0.48, "EVENT 3 // POWER DROP"),
            (0.48, 0.64, "EVENT 4 // POWER RECOVERY"),
            (0.64, 0.82, "EVENT 5 // TEST STARTS"),
            (0.82, 1.00, "EVENT 6 // SCRAM"),
        ]

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._recompute_layout()
        self._build_initial_state()
        self._push_event("INFO", "simulation initialized")
        self._push_event("INFO", "control channels nominal")
        self._push_event("INFO", "reactor at steady state")

    def exit(self):
        self.manager = None
        self._events = []

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self._t = 0.0
            self._build_initial_state()
            self._push_event("WARN", "manual reset of simulation loop")

    def update(self, dt: float):
        self._t += dt
        if self._t >= self.loop_duration_sec:
            self._t -= self.loop_duration_sec
            self._build_initial_state()
            self._push_event("INFO", "simulation restarted")

        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()

        self._events = [e for e in self._events if e.t_end > self._t][-14:]
        self._tick_simulation(dt)
        self._append_history()

    def render(self, screen: pygame.Surface):
        screen.fill(self._bg)
        self._draw_header(screen)
        self._draw_core_panel(screen)
        self._draw_status_panel(screen)
        self._draw_log_panel(screen)
        self._draw_footer(screen)

    def _reseed(self):
        if self.seed is None:
            self.seed = random.randrange(1, 2**31 - 1)
        self._rng.seed(int(self.seed))

    def _recompute_layout(self):
        self.w, self.h = self.manager.screen.get_size()
        self._is_portrait = self.h > self.w
        base = min(self.w, self.h)

        self._pad = int(base * 0.04)
        self._header_h = max(84, int(self.h * 0.13))
        self._footer_h = max(40, int(self.h * 0.06))
        self._content_rect = pygame.Rect(
            self._pad,
            self._header_h,
            self.w - 2 * self._pad,
            self.h - self._header_h - self._footer_h,
        )

        cr = self._content_rect
        if self._is_portrait or self.portrait_layout:
            core_h = int(cr.height * 0.42)
            status_h = int(cr.height * 0.32)
            log_h = cr.height - core_h - status_h - 16
            self._core_rect = pygame.Rect(cr.left, cr.top, cr.width, core_h)
            self._status_rect = pygame.Rect(cr.left, self._core_rect.bottom + 8, cr.width, status_h)
            self._log_rect = pygame.Rect(cr.left, self._status_rect.bottom + 8, cr.width, log_h)
        else:
            left_w = int(cr.width * 0.56)
            self._core_rect = pygame.Rect(cr.left, cr.top, left_w, cr.height)
            right = pygame.Rect(self._core_rect.right + 8, cr.top, cr.width - left_w - 8, cr.height)
            status_h = int(right.height * 0.58)
            self._status_rect = pygame.Rect(right.left, right.top, right.width, status_h)
            self._log_rect = pygame.Rect(right.left, self._status_rect.bottom + 8, right.width, right.height - status_h - 8)

        self._font_header = self.manager.cache.get_font("dejavusansmono", max(18, int(base * 0.044)), bold=True)
        self._font_body = self.manager.cache.get_font("dejavusansmono", max(13, int(base * 0.024)), bold=False)
        self._font_small = self.manager.cache.get_font("dejavusansmono", max(11, int(base * 0.018)), bold=False)
        self._font_tiny = self.manager.cache.get_font("dejavusansmono", max(10, int(base * 0.014)), bold=False)

    def _build_initial_state(self):
        self._power = 1.0
        self._power_target = 1.0
        self._void_fraction = 0.12
        self._xenon = 0.12
        self._rod_fraction = 0.62
        self._pump_flow = 0.84
        self._turbine_rpm = 3000
        self._scram = False
        self._spike = 0.0
        self._phase_name = "EVENT 1 // REACTOR NORMAL"
        self._phase_progress = 0.0
        self._power_history = [0.65] * 180
        self._void_history = [0.12] * 180
        self._rod_history = [self._rod_fraction] * 180
        self._core_bias = []
        self._channel_temps = []
        for r in range(self.rows):
            row_bias = []
            row_temp = []
            for c in range(self.cols):
                dist = math.hypot((r / max(1, self.rows - 1)) - 0.5, (c / max(1, self.cols - 1)) - 0.5)
                row_bias.append(1.16 - dist * 0.78 + self._rng.uniform(-0.08, 0.08))
                row_temp.append(0.42 + self._rng.uniform(-0.03, 0.03))
            self._core_bias.append(row_bias)
            self._channel_temps.append(row_temp)

    def _push_event(self, kind: str, text: str):
        ttl = 24.0 if kind != "ALERT" else 30.0
        self._events.append(EventLine(self._t + ttl, kind, text.upper()))

    def _tick_simulation(self, dt: float):
        ratio = self._t / self.loop_duration_sec
        phase_name = self._phase_name
        for start, end, name in self._phase_schedule:
            if start <= ratio < end:
                phase_name = name
                self._phase_progress = (ratio - start) / max(0.0001, end - start)
                break
        self._phase_name = phase_name

        if "NORMAL" in phase_name:
            self._power_target = 1.0
            self._rod_fraction = self._approach(self._rod_fraction, 0.62, dt * 0.35)
            self._xenon = self._approach(self._xenon, 0.12, dt * 0.25)
            self._void_fraction = self._approach(self._void_fraction, 0.12, dt * 0.25)
            self._pump_flow = self._approach(self._pump_flow, 0.84, dt * 0.35)
            self._turbine_rpm = int(self._approach(self._turbine_rpm, 3000, dt * 700))

        elif "POWER REDUCTION" in phase_name:
            self._power_target = 0.52
            self._rod_fraction = self._approach(self._rod_fraction, 0.76, dt * 0.32)
            self._xenon = self._approach(self._xenon, 0.30, dt * 0.20)
            self._void_fraction = self._approach(self._void_fraction, 0.10, dt * 0.18)
            if self._phase_progress < 0.08:
                self._push_phase_once("INFO", "beginning controlled power reduction")

        elif "POWER DROP" in phase_name:
            self._power_target = 0.06
            self._rod_fraction = self._approach(self._rod_fraction, 0.84, dt * 0.32)
            self._xenon = self._approach(self._xenon, 0.82, dt * 0.38)
            self._void_fraction = self._approach(self._void_fraction, 0.08, dt * 0.15)
            if self._phase_progress < 0.08:
                self._push_phase_once("WARN", "xenon buildup suppresses reactivity")

        elif "POWER RECOVERY" in phase_name:
            self._power_target = 0.22
            self._rod_fraction = self._approach(self._rod_fraction, 0.12, dt * 0.40)
            self._xenon = self._approach(self._xenon, 0.68, dt * 0.12)
            self._void_fraction = self._approach(self._void_fraction, 0.18, dt * 0.16)
            self._pump_flow = self._approach(self._pump_flow, 0.90, dt * 0.18)
            if self._phase_progress < 0.08:
                self._push_phase_once("WARN", "control rods withdrawn to restore power")

        elif "TEST STARTS" in phase_name:
            self._power_target = 0.28
            self._rod_fraction = self._approach(self._rod_fraction, 0.10, dt * 0.15)
            self._xenon = self._approach(self._xenon, 0.54, dt * 0.08)
            self._void_fraction = self._approach(self._void_fraction, 0.54, dt * 0.25)
            self._pump_flow = self._approach(self._pump_flow, 0.62, dt * 0.22)
            self._turbine_rpm = int(self._approach(self._turbine_rpm, 1850, dt * 520))
            if self._phase_progress < 0.08:
                self._push_phase_once("WARN", "steam voids increase as flow conditions degrade")

        else:  # SCRAM
            if not self._scram:
                self._scram = True
                self._spike = 1.0
                self._push_event("ALERT", "az-5 scram initiated")
                self._push_event("ALERT", "graphite-tipped rod insertion briefly raises reactivity")
            self._rod_fraction = self._approach(self._rod_fraction, 1.0, dt * 0.75)
            self._void_fraction = self._approach(self._void_fraction, 0.84, dt * 0.24)
            self._xenon = self._approach(self._xenon, 0.30, dt * 0.08)
            self._pump_flow = self._approach(self._pump_flow, 0.42, dt * 0.25)
            self._turbine_rpm = int(self._approach(self._turbine_rpm, 900, dt * 460))

        positive_void_term = max(0.0, self._void_fraction - 0.18) * 1.35
        negative_rod_term = self._rod_fraction * 0.92
        xenon_term = self._xenon * 0.60
        desired = self._power_target + positive_void_term - negative_rod_term * 0.12 - xenon_term * 0.26
        desired = max(0.02, desired)
        if self._scram and self._spike > 0.0:
            desired += 2.8 * self._spike
            self._spike = max(0.0, self._spike - dt * 2.1)
        self._power = self._approach(self._power, desired, dt * 0.80)
        self._power = max(0.01, min(3.5, self._power))

        meltdown_zone = max(0.0, self._power - 1.08)
        for r in range(self.rows):
            for c in range(self.cols):
                base = self._core_bias[r][c]
                rod_local = self._rod_fraction * (0.78 + 0.22 * ((r + c) % 3) / 2.0)
                temp_target = (self._power * base * (1.0 + self._void_fraction * 0.45)) - rod_local * 0.38
                if self._scram and self._spike > 0.25 and r < self.rows // 3:
                    temp_target += 0.38
                temp_target += meltdown_zone * (0.30 + 0.25 * base)
                temp_target = max(0.04, min(2.3, temp_target))
                self._channel_temps[r][c] = self._approach(self._channel_temps[r][c], temp_target, dt * 0.95)

        if self._power > 2.0 and self._phase_progress > 0.35 and "SCRAM" in self._phase_name:
            self._push_phase_once("ALERT", "power excursion exceeds stable envelope")

    def _push_phase_once(self, kind: str, text: str):
        tag = f"{self._phase_name}::{text}"
        if not hasattr(self, "_phase_event_tag") or self._phase_event_tag != tag:
            self._phase_event_tag = tag
            self._push_event(kind, text)

    def _append_history(self):
        self._power_history.append(max(0.0, min(1.0, self._power / 3.0)))
        self._void_history.append(max(0.0, min(1.0, self._void_fraction)))
        self._rod_history.append(max(0.0, min(1.0, self._rod_fraction)))
        for seq in (self._power_history, self._void_history, self._rod_history):
            if len(seq) > 180:
                seq.pop(0)

    def _approach(self, value, target, rate):
        if value < target:
            return min(target, value + rate)
        return max(target, value - rate)

    def _panel_box(self, screen, rect: pygame.Rect, label: str):
        pygame.draw.rect(screen, (17, 18, 20), rect)
        pygame.draw.rect(screen, self.accent_rgb, rect, 2)
        surf = self._font_tiny.render(label, True, self.accent_rgb)
        screen.blit(surf, (rect.left + 10, rect.top + 8))

    def _draw_header(self, screen):
        title = self._font_header.render(self.title, True, self.accent_rgb)
        reactor = self._font_body.render(self.reactor_name, True, self._fg)
        screen.blit(title, (self._pad, int(self._header_h * 0.20)))
        screen.blit(reactor, (self._pad, int(self._header_h * 0.60)))

        phase = self._font_body.render(self._phase_name, True, self._fg)
        stamp = self._font_small.render(datetime.now().strftime("%H:%M:%S"), True, self._dim)
        screen.blit(phase, (self.w - self._pad - phase.get_width(), int(self._header_h * 0.18)))
        screen.blit(stamp, (self.w - self._pad - stamp.get_width(), int(self._header_h * 0.62)))

    def _draw_core_panel(self, screen):
        rect = self._core_rect
        self._panel_box(screen, rect, "CORE MAP / CONTROL RODS")
        inner = rect.inflate(-18, -22)
        inner.y += 14

        map_rect = pygame.Rect(inner.left, inner.top, inner.width, inner.height - 34)
        legend_y = map_rect.bottom + 8
        self._draw_core_map(screen, map_rect)

        labels = [
            ("POWER", self._hot),
            ("COOLANT/VOID", self._cool),
            ("ROD INSERTION", self._warn),
        ]
        x = inner.left
        for label, color in labels:
            pygame.draw.rect(screen, color, pygame.Rect(x, legend_y + 4, 16, 8))
            surf = self._font_tiny.render(label, True, self._fg)
            screen.blit(surf, (x + 22, legend_y))
            x += 22 + surf.get_width() + 26

    def _draw_core_map(self, screen, rect: pygame.Rect):
        pygame.draw.rect(screen, (10, 11, 13), rect)
        pygame.draw.rect(screen, (72, 76, 82), rect, 1)
        gap = 4
        cell_w = max(6, (rect.width - gap * (self.cols + 1)) // self.cols)
        cell_h = max(6, (rect.height - gap * (self.rows + 1)) // self.rows)
        rod_depth = self._rod_fraction
        scram_zone = self._scram and self._phase_progress > 0.08

        for r in range(self.rows):
            for c in range(self.cols):
                x = rect.left + gap + c * (cell_w + gap)
                y = rect.top + gap + r * (cell_h + gap)
                temp = self._channel_temps[r][c]
                base = int(max(24, min(255, 36 + temp * 96)))
                color = (
                    min(255, int(self._cool[0] * (1.1 - temp * 0.3) + self._hot[0] * (temp * 0.55))),
                    min(255, int(self._cool[1] * (1.0 - temp * 0.45) + self._hot[1] * (temp * 0.38))),
                    min(255, int(self._cool[2] * (1.0 - temp * 0.70) + self._hot[2] * (temp * 0.18))),
                )
                cell = pygame.Rect(x, y, cell_w, cell_h)
                pygame.draw.rect(screen, color, cell)
                pygame.draw.rect(screen, (18, 18, 18), cell, 1)

                rod_w = max(2, cell_w // 4)
                rod_x = x + cell_w // 2 - rod_w // 2
                rod_h = max(2, int(cell_h * (0.18 + 0.82 * rod_depth)))
                rod_rect = pygame.Rect(rod_x, y, rod_w, rod_h)
                rod_color = self._warn if not scram_zone else self._fg
                pygame.draw.rect(screen, rod_color, rod_rect)

                if self._scram and self._spike > 0.15 and rod_h < cell_h:
                    tip_h = max(2, cell_h // 5)
                    tip_rect = pygame.Rect(rod_x, rod_rect.bottom, rod_w, tip_h)
                    pygame.draw.rect(screen, (82, 82, 82), tip_rect)

    def _draw_status_panel(self, screen):
        rect = self._status_rect
        self._panel_box(screen, rect, "REACTIVITY / THERMAL STATE")
        inner = rect.inflate(-18, -20)
        inner.y += 12

        top_h = int(inner.height * 0.48)
        top = pygame.Rect(inner.left, inner.top, inner.width, top_h)
        bottom = pygame.Rect(inner.left, top.bottom + 8, inner.width, inner.height - top_h - 8)

        if self._is_portrait or self.portrait_layout:
            left = pygame.Rect(top.left, top.top, top.width, top.height)
            self._draw_metrics(screen, left)

            cols = 3
            gap = 8
            chart_w = (bottom.width - gap * (cols - 1)) // cols
            self._draw_chart(screen, pygame.Rect(bottom.left, bottom.top, chart_w, bottom.height), self._power_history, "POWER", self._hot)
            self._draw_chart(screen, pygame.Rect(bottom.left + chart_w + gap, bottom.top, chart_w, bottom.height), self._void_history, "VOID", self._cool)
            self._draw_chart(screen, pygame.Rect(bottom.left + (chart_w + gap) * 2, bottom.top, chart_w, bottom.height), self._rod_history, "RODS", self._warn)
        else:
            left_w = int(inner.width * 0.44)
            self._draw_metrics(screen, pygame.Rect(inner.left, inner.top, left_w, inner.height))
            right = pygame.Rect(inner.left + left_w + 8, inner.top, inner.width - left_w - 8, inner.height)
            chart_h = (right.height - 16) // 3
            self._draw_chart(screen, pygame.Rect(right.left, right.top, right.width, chart_h), self._power_history, "POWER", self._hot)
            self._draw_chart(screen, pygame.Rect(right.left, right.top + chart_h + 8, right.width, chart_h), self._void_history, "VOID", self._cool)
            self._draw_chart(screen, pygame.Rect(right.left, right.top + (chart_h + 8) * 2, right.width, chart_h), self._rod_history, "RODS", self._warn)

    def _draw_metrics(self, screen, rect: pygame.Rect):
        rows = [
            ("POWER", f"{self._power*100:5.0f} %", self._hot if self._power < 1.1 else self._alert),
            ("VOID", f"{self._void_fraction*100:5.0f} %", self._cool),
            ("XENON", f"{self._xenon*100:5.0f} %", self._warn),
            ("RODS", f"{self._rod_fraction*100:5.0f} %", self._fg),
            ("FLOW", f"{self._pump_flow*100:5.0f} %", self._cool),
            ("TURB", f"{self._turbine_rpm:5d} RPM", self._fg),
        ]
        for idx, (k, v, color) in enumerate(rows):
            y = rect.top + idx * (self._font_body.get_linesize() + 8)
            ks = self._font_small.render(k, True, self.accent_rgb)
            vs = self._font_body.render(v, True, color)
            screen.blit(ks, (rect.left, y))
            screen.blit(vs, (rect.left + 86, y - 1))

        state = "SCRAM ACTIVE" if self._scram else "SCRAM STANDBY"
        state_color = self._alert if self._scram else self._fg
        surf = self._font_body.render(state, True, state_color)
        screen.blit(surf, (rect.left, rect.bottom - surf.get_height() - 6))

    def _draw_chart(self, screen, rect: pygame.Rect, data, label: str, color):
        pygame.draw.rect(screen, (10, 12, 14), rect)
        pygame.draw.rect(screen, (82, 84, 88), rect, 1)
        lbl = self._font_tiny.render(label, True, self.accent_rgb)
        screen.blit(lbl, (rect.left + 8, rect.top + 6))

        graph = rect.inflate(-10, -18)
        for i in range(1, 4):
            gy = graph.top + int(graph.height * i / 4)
            pygame.draw.line(screen, (34, 36, 40), (graph.left, gy), (graph.right, gy), 1)

        pts = []
        denom = max(1, len(data) - 1)
        for i, value in enumerate(data):
            gx = graph.left + int(graph.width * i / denom)
            gy = graph.bottom - int(graph.height * value)
            pts.append((gx, gy))
        if len(pts) > 1:
            pygame.draw.lines(screen, color, False, pts, 2)

    def _draw_log_panel(self, screen):
        rect = self._log_rect
        self._panel_box(screen, rect, "EVENT LOG")
        inner = rect.inflate(-18, -20)
        inner.y += 14

        line_h = self._font_small.get_linesize() + 4
        visible = max(1, inner.height // line_h)
        lines = self._events[-visible:]
        if not lines:
            lines = [EventLine(self._t + 1.0, "INFO", "SIMULATION READY")]

        for idx, event in enumerate(lines):
            y = inner.top + idx * line_h
            color = self._fg
            if event.kind == "WARN":
                color = self._warn
            elif event.kind == "ALERT":
                color = self._alert
            stamp = self._font_tiny.render(f"T+{int(self._t):02d}.{int((self._t%1)*10)}", True, self._dim)
            kind = self._font_tiny.render(event.kind, True, color)
            text = self._font_small.render(event.text, True, self._fg)
            screen.blit(stamp, (inner.left, y + 2))
            screen.blit(kind, (inner.left + 58, y + 2))
            screen.blit(text, (inner.left + 116, y))

    def _draw_footer(self, screen):
        y = self.h - self._footer_h + 8
        left = self._font_small.render("SPACE: RESTART SIMULATION LOOP", True, self._dim)
        right = self._font_small.render(f"SEED {self.seed}", True, self._dim)
        screen.blit(left, (self._pad, y))
        screen.blit(right, (self.w - self._pad - right.get_width(), y))

import math
import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

import pygame

from core.mapdata import load_coastlines


def _load_coastlines():
    # Thin wrapper kept for this module's call sites; the actual loader
    # (with caching) now lives in core.mapdata so both map modes share it.
    lines = load_coastlines()
    if lines is None:
        print("[MissionControl] coastline data unavailable; using fallback shapes")
    return lines


@dataclass
class EventLine:
    t_end: float
    kind: str
    text: str


class MissionControlConsoleMode:
    """
    Mission Control Console
    - Retro 1960s/1970s NASA-style overview wall with world map, orbit trace,
      subsystem status tiles, strip charts, and scrolling event log.

    Config (all optional):
      - title
      - mission_name
      - accent_rgb
      - seed
      - refresh_hz
      - portrait_layout
      - scanline_alpha
      - noise_alpha
      - vignette_strength
      - console_rows
      - console_cols
      - anomaly_probability_per_min
      - event_interval_range
      - chart_count
      - orbit_period_sec
    """

    # Class-level coastline cache (shared across instances / mode switches).
    _coastlines = None
    _coastlines_failed = False

    def __init__(self, config: dict):
        self.title = str(config.get("title", "MISSION CONTROL CONSOLE"))
        self.mission_name = str(config.get("mission_name", "APOLLO-STYLE TEST FLIGHT"))
        self.accent_rgb = tuple(config.get("accent_rgb", [255, 205, 135]))
        self.seed = config.get("seed", None)
        self.refresh_hz = float(config.get("refresh_hz", 60.0))
        self.portrait_layout = bool(config.get("portrait_layout", False))
        self.scanline_alpha = int(config.get("scanline_alpha", 10))
        self.noise_alpha = int(config.get("noise_alpha", 10))
        self.vignette_strength = float(config.get("vignette_strength", 0.26))
        self.console_rows = max(2, min(6, int(config.get("console_rows", 4))))
        self.console_cols = max(4, min(10, int(config.get("console_cols", 7))))
        self.anomaly_probability_per_min = float(config.get("anomaly_probability_per_min", 0.55))
        self.event_interval_range = config.get("event_interval_range", [1.8, 3.8])
        self.chart_count = max(2, min(4, int(config.get("chart_count", 3))))
        self.orbit_period_sec = max(18.0, float(config.get("orbit_period_sec", 48.0)))

        self.manager = None
        self.w = 0
        self.h = 0
        self._is_portrait = False
        self._t = 0.0
        self._rng = random.Random()

        self._bg = (6, 7, 8)
        self._fg = (232, 226, 214)
        self._dim = (132, 128, 118)
        self._ok = (124, 255, 158)
        self._warn = (255, 210, 104)
        self._alert = (255, 112, 112)

        self._pad = 0
        self._header_h = 0
        self._footer_h = 0
        self._main_rect = pygame.Rect(0, 0, 0, 0)
        self._map_rect = pygame.Rect(0, 0, 0, 0)
        self._status_rect = pygame.Rect(0, 0, 0, 0)
        self._consoles_rect = pygame.Rect(0, 0, 0, 0)
        self._log_rect = pygame.Rect(0, 0, 0, 0)

        self._font_header = None
        self._font_body = None
        self._font_small = None
        self._font_tiny = None

        self._overlay = None
        self._vignette = None

        self._events: list[EventLine] = []
        self._next_event_t = 0.0

        self._mission_start = datetime(1969, 7, 16, 13, 32, 0)
        self._phase_index = 0
        self._phase_names = [
            "PRELAUNCH",
            "ASCENT",
            "EARTH ORBIT",
            "TLI WINDOW",
            "MIDCOURSE",
            "LUNAR APPROACH",
            "RETURN ARC",
            "RECOVERY",
        ]

        self._subsystems = []
        self._console_cells = []
        self._chart_labels = ["GUIDANCE ERR", "FUEL FLOW", "CABIN PSI", "LINK MARGIN"]
        self._chart_history = []
        self._chart_phase = []

        self._orbit_theta = 0.0
        self._ground_track = []
        self._stations = []
        self._capsule_lat = 0.0
        self._capsule_lon = 0.0
        self._downrange_km = 0
        self._velocity_fps = 25500
        self._altitude_nm = 101
        self._capsule_heading = 90.0
        self._comms_lock = True
        self._last_anomaly_t = -999.0

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._build_static_state()
        self._recompute_layout()
        self._build_overlays()
        self._schedule_event(initial=True)
        self._push_event("INFO", "flight directors to consoles")
        self._push_event("INFO", f"tracking mission {self.mission_name}")
        self._push_event("INFO", "all stations report go")

    def exit(self):
        self.manager = None
        self._events = []
        self._overlay = None
        self._vignette = None
        self._chart_history = []

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self._trigger_anomaly(force_kind="WARN")

    def update(self, dt: float):
        self._t += dt

        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            self._build_overlays()

        self._events = [e for e in self._events if e.t_end > self._t][-12:]

        if self._t >= self._next_event_t:
            self._generate_event()
            self._schedule_event(initial=False)

        p = max(0.0, self.anomaly_probability_per_min) / 60.0
        if self._rng.random() < p * dt:
            self._trigger_anomaly()

        self._tick_mission(dt)
        self._tick_subsystems(dt)
        self._tick_consoles(dt)
        self._tick_charts(dt)

    def render(self, screen: pygame.Surface):
        screen.fill(self._bg)

        self._draw_header(screen)
        self._draw_map_panel(screen)
        self._draw_status_panel(screen)
        self._draw_consoles_panel(screen)
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

    def _build_static_state(self):
        names = [
            "GUIDO", "RETRO", "EECOM", "BOOSTER", "FIDO", "TELMU",
            "GNC", "SURGEON", "INCO", "CAPCOM", "COMM", "TRACK",
        ]
        self._subsystems = []
        for i, name in enumerate(names):
            self._subsystems.append(
                {
                    "name": name,
                    "value": self._rng.uniform(0.62, 0.94),
                    "status": "GO",
                    "phase": self._rng.uniform(0.0, math.tau),
                    "trend": self._rng.choice([-1.0, 1.0]),
                    "detail": self._rng.choice(["NOMINAL", "TRACKING", "LOCKED", "STABLE"]),
                }
            )

        total_cells = self.console_rows * self.console_cols
        self._console_cells = []
        for _ in range(total_cells):
            self._console_cells.append(
                {
                    "lamp": self._rng.random() > 0.45,
                    "meter": self._rng.uniform(0.15, 0.82),
                    "phase": self._rng.uniform(0.0, math.tau),
                }
            )

        self._chart_history = []
        self._chart_phase = []
        for idx in range(self.chart_count):
            phase = self._rng.uniform(0.0, math.tau)
            self._chart_phase.append(phase)
            history = []
            for x in range(180):
                v = 0.52 + 0.18 * math.sin((x / 22.0) + phase + idx * 0.4)
                history.append(max(0.05, min(0.95, v)))
            self._chart_history.append(history)

        self._stations = [
            ("HOUSTON", 29.55, -95.09),
            ("CANARY", 28.46, -16.25),
            ("BERMUDA", 32.30, -64.78),
            ("MADRID", 40.42, -3.70),
            ("CARNARVON", -24.88, 113.66),
            ("HAWAII", 21.31, -157.86),
        ]

        self._ground_track = []
        for i in range(96):
            theta = (i / 96.0) * math.tau
            lat = 28.0 * math.sin(theta * 1.35)
            lon = ((theta / math.tau) * 360.0) - 180.0
            self._ground_track.append((lat, lon))

    def _recompute_layout(self):
        self.w, self.h = self.manager.screen.get_size()
        self._is_portrait = self.h > self.w

        self._pad = int(min(self.w, self.h) * 0.04)
        self._header_h = max(88, int(self.h * 0.14))
        self._footer_h = max(44, int(self.h * 0.06))
        self._main_rect = pygame.Rect(
            self._pad,
            self._header_h,
            self.w - 2 * self._pad,
            self.h - self._header_h - self._footer_h,
        )

        mr = self._main_rect
        if self._is_portrait or self.portrait_layout:
            map_h = int(mr.height * 0.31)
            status_h = int(mr.height * 0.29)
            consoles_h = int(mr.height * 0.18)
            log_h = mr.height - map_h - status_h - consoles_h - 24

            self._map_rect = pygame.Rect(mr.left, mr.top, mr.width, map_h)
            self._status_rect = pygame.Rect(mr.left, self._map_rect.bottom + 8, mr.width, status_h)
            self._consoles_rect = pygame.Rect(mr.left, self._status_rect.bottom + 8, mr.width, consoles_h)
            self._log_rect = pygame.Rect(mr.left, self._consoles_rect.bottom + 8, mr.width, log_h)
        else:
            left_w = int(mr.width * 0.58)
            top_h = int(mr.height * 0.58)
            bottom_h = mr.height - top_h - 8

            self._map_rect = pygame.Rect(mr.left, mr.top, left_w, top_h)
            self._status_rect = pygame.Rect(self._map_rect.right + 8, mr.top, mr.width - left_w - 8, top_h)
            self._consoles_rect = pygame.Rect(mr.left, self._map_rect.bottom + 8, left_w, bottom_h)
            self._log_rect = pygame.Rect(self._consoles_rect.right + 8, self._status_rect.bottom + 8, self._status_rect.width, bottom_h)

        base = min(self.w, self.h)
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

    def _schedule_event(self, initial: bool):
        low, high = self.event_interval_range
        if high < low:
            low, high = high, low
        if initial:
            self._next_event_t = self._t + 0.7
        else:
            self._next_event_t = self._t + self._rng.uniform(float(low), float(high))

    def _push_event(self, kind: str, text: str):
        ttl = 22.0 if kind != "ALERT" else 28.0
        self._events.append(EventLine(self._t + ttl, kind, text.upper()))

    def _generate_event(self):
        templates = [
            ("INFO", "tracking handoff to {station}"),
            ("INFO", "guidance residual {value:.1f} arc-sec"),
            ("INFO", "retro confirms trim burn plan {code}"),
            ("INFO", "telemetry frame sync verified"),
            ("INFO", "booster reports ullage pressure stable"),
            ("WARN", "minor dispersions on channel {code}"),
            ("WARN", "high gain antenna drift {value:.1f} deg"),
            ("WARN", "capsule cabin fan load at {value:.0f}%"),
        ]
        kind, template = self._rng.choice(templates)
        message = template.format(
            station=self._rng.choice([s[0] for s in self._stations]),
            value=self._rng.uniform(2.0, 97.0),
            code=self._rng.choice(["A", "B", "C", "D"]) + f"{self._rng.randint(1, 9)}",
        )
        self._push_event(kind, message)

    def _trigger_anomaly(self, force_kind: str | None = None):
        if self._t - self._last_anomaly_t < 8.0:
            return
        self._last_anomaly_t = self._t
        idx = self._rng.randrange(len(self._subsystems))
        subsystem = self._subsystems[idx]
        subsystem["status"] = "CHECK"
        subsystem["detail"] = self._rng.choice(["VERIFY", "MANUAL", "REROUTE", "TRACK"])
        subsystem["value"] = max(0.22, subsystem["value"] - self._rng.uniform(0.08, 0.18))
        self._comms_lock = self._rng.random() > 0.3

        text = self._rng.choice([
            f"{subsystem['name']} requests data review",
            f"{subsystem['name']} reports transient caution",
            "guidance console flags trajectory residual",
            "telemetry noise burst on deep-space loop",
        ])
        self._push_event(force_kind or "ALERT", text)

    def _tick_mission(self, dt: float):
        self._orbit_theta = (self._orbit_theta + (math.tau / self.orbit_period_sec) * dt) % math.tau
        self._capsule_lat = 29.0 * math.sin(self._orbit_theta * 1.15)
        self._capsule_lon = ((self._orbit_theta / math.tau) * 360.0) - 180.0
        self._capsule_heading = (90.0 + math.degrees(self._orbit_theta) * 0.7) % 360.0
        self._downrange_km = int(6400 + 155000 * ((self._orbit_theta / math.tau) % 1.0))
        self._velocity_fps = int(25500 + 4200 * math.sin(self._orbit_theta * 0.9))
        self._altitude_nm = int(96 + 24 * math.sin(self._orbit_theta * 2.0 + 0.6))
        self._phase_index = int(((self._orbit_theta / math.tau) * len(self._phase_names))) % len(self._phase_names)

    def _tick_subsystems(self, dt: float):
        for subsystem in self._subsystems:
            subsystem["phase"] += dt * self._rng.uniform(0.3, 1.1)
            drift = math.sin(subsystem["phase"]) * 0.05 + self._rng.uniform(-0.015, 0.015)
            subsystem["value"] = max(0.20, min(0.98, subsystem["value"] + drift * dt))

            if subsystem["value"] > 0.72:
                subsystem["status"] = "GO"
                subsystem["detail"] = self._rng.choice(["NOMINAL", "LOCKED", "TRACKING", "GREEN"])
            elif subsystem["value"] > 0.46:
                subsystem["status"] = "HOLD"
                subsystem["detail"] = self._rng.choice(["WATCH", "VERIFY", "REVIEW", "PENDING"])
            else:
                subsystem["status"] = "CHECK"
                subsystem["detail"] = self._rng.choice(["REROUTE", "MANUAL", "LIMIT", "CAUTION"])

    def _tick_consoles(self, dt: float):
        toggle_p = 1.8 * dt
        for cell in self._console_cells:
            cell["phase"] += dt * self._rng.uniform(1.1, 2.4)
            cell["meter"] = max(0.05, min(0.96, cell["meter"] + math.sin(cell["phase"]) * 0.018))
            if self._rng.random() < toggle_p:
                cell["lamp"] = not cell["lamp"]

    def _tick_charts(self, dt: float):
        for idx, history in enumerate(self._chart_history):
            phase = self._chart_phase[idx] + dt * (0.9 + idx * 0.23)
            self._chart_phase[idx] = phase
            amplitude = 0.17 + idx * 0.025
            base = 0.5 + 0.05 * math.sin(self._orbit_theta * (idx + 1))
            value = base + amplitude * math.sin(phase) + self._rng.uniform(-0.018, 0.018)
            if not self._comms_lock and idx == self.chart_count - 1:
                value -= 0.12
            history.append(max(0.05, min(0.95, value)))
            if len(history) > 180:
                history.pop(0)

    def _panel_box(self, screen, rect: pygame.Rect, label: str):
        pygame.draw.rect(screen, (18, 20, 22), rect)
        pygame.draw.rect(screen, (*self.accent_rgb,), rect, 2)
        tag = self._font_tiny.render(label, True, self.accent_rgb)
        screen.blit(tag, (rect.x + 10, rect.y + 8))

    def _draw_header(self, screen):
        title = self._font_header.render(self.title, True, self.accent_rgb)
        mission = self._font_body.render(self.mission_name, True, self._fg)
        screen.blit(title, (self._pad, int(self._header_h * 0.18)))
        screen.blit(mission, (self._pad, int(self._header_h * 0.58)))

        phase = self._phase_names[self._phase_index]
        phase_surf = self._font_body.render(f"PHASE {self._phase_index + 1}: {phase}", True, self._fg)
        phase_x = self.w - self._pad - phase_surf.get_width()
        screen.blit(phase_surf, (phase_x, int(self._header_h * 0.18)))

        elapsed = timedelta(seconds=int(self._t * 45))
        clock_text = f"MET {str(elapsed)}"
        clock_surf = self._font_body.render(clock_text, True, self._fg)
        screen.blit(clock_surf, (self.w - self._pad - clock_surf.get_width(), int(self._header_h * 0.58)))

    def _draw_map_panel(self, screen):
        rect = self._map_rect
        self._panel_box(screen, rect, "WORLD TRACK")

        inner = rect.inflate(-16, -22)
        map_rect = pygame.Rect(inner.x, inner.y + 14, inner.width, inner.height - 14)
        pygame.draw.rect(screen, (8, 10, 12), map_rect)
        pygame.draw.rect(screen, (70, 74, 78), map_rect, 1)

        self._draw_map_grid(screen, map_rect)
        self._draw_continents(screen, map_rect)
        self._draw_ground_track(screen, map_rect)
        self._draw_stations(screen, map_rect)
        self._draw_capsule(screen, map_rect)

    def _draw_map_grid(self, screen, rect: pygame.Rect):
        for i in range(1, 6):
            x = rect.left + int(rect.width * i / 6)
            pygame.draw.line(screen, (40, 45, 48), (x, rect.top), (x, rect.bottom), 1)
        for i in range(1, 4):
            y = rect.top + int(rect.height * i / 4)
            pygame.draw.line(screen, (40, 45, 48), (rect.left, y), (rect.right, y), 1)

    def _draw_continents(self, screen, rect: pygame.Rect):
        # Lazily load the real coastline data once per process (class-level
        # cache so repeated mode switches don't re-read the file).
        if MissionControlConsoleMode._coastlines is None and not MissionControlConsoleMode._coastlines_failed:
            lines = _load_coastlines()
            if lines is None:
                MissionControlConsoleMode._coastlines_failed = True
            else:
                MissionControlConsoleMode._coastlines = lines

        if MissionControlConsoleMode._coastlines is not None:
            self._draw_coastline_map(screen, rect, MissionControlConsoleMode._coastlines)
        else:
            self._draw_continents_fallback(screen, rect)

    def _draw_coastline_map(self, screen, rect: pygame.Rect, coastlines):
        # Line-drawing style: Natural Earth coastline polylines in the same
        # retro green palette. Width 1 keeps the crisp vector look.
        color = (96, 110, 98)
        for line in coastlines:
            screen_pts = [self._latlon_to_xy(lat, lon, rect) for lon, lat in line]
            if len(screen_pts) >= 2:
                pygame.draw.lines(screen, color, False, screen_pts, 1)

    def _draw_continents_fallback(self, screen, rect: pygame.Rect):
        # Legacy rough shapes — only used if the coastline data file is missing.
        shapes = [
            [(-165, 50), (-140, 62), (-110, 72), (-95, 55), (-125, 28), (-150, 25)],
            [(-82, 12), (-66, -8), (-60, -28), (-52, -52), (-78, -50), (-86, -16)],
            [(-10, 36), (14, 54), (48, 52), (58, 34), (32, 8), (4, 10)],
            [(18, 8), (42, 6), (78, 20), (100, 44), (122, 56), (144, 46), (124, 22), (86, 10), (48, -2)],
            [(12, -14), (24, -34), (36, -36), (46, -18), (36, 4), (22, 4)],
            [(112, -14), (130, -22), (148, -30), (160, -42), (150, -52), (126, -46), (110, -26)],
        ]
        for pts in shapes:
            screen_pts = [self._latlon_to_xy(lat, lon, rect) for lon, lat in pts]
            if len(screen_pts) >= 3:
                pygame.draw.polygon(screen, (46, 54, 48), screen_pts)
                pygame.draw.polygon(screen, (82, 92, 84), screen_pts, 1)

    def _draw_ground_track(self, screen, rect: pygame.Rect):
        pts = [self._latlon_to_xy(lat, lon, rect) for lat, lon in self._ground_track]
        if len(pts) > 2:
            pygame.draw.lines(screen, self.accent_rgb, False, pts, 2)

    def _draw_stations(self, screen, rect: pygame.Rect):
        for name, lat, lon in self._stations:
            x, y = self._latlon_to_xy(lat, lon, rect)
            pygame.draw.circle(screen, self._ok, (x, y), 4)
            pygame.draw.circle(screen, (0, 0, 0), (x, y), 4, 1)
            tag = self._font_tiny.render(name, True, self._fg)
            screen.blit(tag, (x + 6, y - tag.get_height() // 2))

    def _draw_capsule(self, screen, rect: pygame.Rect):
        x, y = self._latlon_to_xy(self._capsule_lat, self._capsule_lon, rect)
        pulse = 1.0 + 0.35 * math.sin(self._t * 4.2)
        r = int(6 * pulse)
        pygame.draw.circle(screen, self._warn if self._comms_lock else self._alert, (x, y), r, 2)
        pygame.draw.circle(screen, self._fg, (x, y), 3)

        hx = x + int(math.cos(math.radians(self._capsule_heading)) * 18)
        hy = y - int(math.sin(math.radians(self._capsule_heading)) * 18)
        pygame.draw.line(screen, self._fg, (x, y), (hx, hy), 2)

        text = self._font_tiny.render("CMC TRACK", True, self._fg)
        screen.blit(text, (x + 10, y - 18))

    def _draw_status_panel(self, screen):
        rect = self._status_rect
        self._panel_box(screen, rect, "SUBSYSTEMS / TELEMETRY")

        inner = rect.inflate(-16, -20)
        if self._is_portrait or self.portrait_layout:
            gap = 8
            left = pygame.Rect(inner.left, inner.top + 16, inner.width, int(inner.height * 0.52))
            lower = pygame.Rect(inner.left, left.bottom + gap, inner.width, inner.height - left.height - gap - 16)
            self._draw_telemetry_summary(screen, left)

            cols = 2 if self.chart_count > 1 else 1
            rows = math.ceil(self.chart_count / cols)
            chart_w = (lower.width - gap * (cols - 1)) // cols
            chart_h = (lower.height - gap * (rows - 1)) // rows
            for idx in range(self.chart_count):
                row = idx // cols
                col = idx % cols
                chart_rect = pygame.Rect(
                    lower.left + col * (chart_w + gap),
                    lower.top + row * (chart_h + gap),
                    chart_w,
                    chart_h,
                )
                self._draw_chart(screen, chart_rect, idx)
        else:
            left_w = int(inner.width * 0.54)
            left = pygame.Rect(inner.left, inner.top + 16, left_w, inner.height - 16)
            right = pygame.Rect(left.right + 8, inner.top + 16, inner.width - left_w - 8, inner.height - 16)
            self._draw_telemetry_summary(screen, left)

            gap = 8
            chart_h = (right.height - gap * (self.chart_count - 1)) // self.chart_count
            for idx in range(self.chart_count):
                chart_rect = pygame.Rect(right.left, right.top + idx * (chart_h + gap), right.width, chart_h)
                self._draw_chart(screen, chart_rect, idx)

    def _draw_telemetry_summary(self, screen, rect: pygame.Rect):
        left_w = int(rect.width * 0.48)
        gauge_rect = pygame.Rect(rect.left, rect.top, left_w, rect.height)
        list_rect = pygame.Rect(gauge_rect.right + 10, rect.top, rect.width - left_w - 10, rect.height)

        metrics = [
            ("VEL", f"{self._velocity_fps:05d} FPS"),
            ("ALT", f"{self._altitude_nm:03d} NM"),
            ("RNG", f"{self._downrange_km:06d} KM"),
            ("LINK", "LOCK" if self._comms_lock else "NOISY"),
        ]
        for idx, (label, value) in enumerate(metrics):
            y = gauge_rect.top + idx * (self._font_body.get_linesize() + 10)
            tag = self._font_small.render(label, True, self.accent_rgb)
            val = self._font_body.render(value, True, self._fg)
            screen.blit(tag, (gauge_rect.left, y))
            screen.blit(val, (gauge_rect.left + 60, y - 2))

        gauge_y = gauge_rect.bottom - 42
        self._draw_meter_bar(screen, pygame.Rect(gauge_rect.left, gauge_y, gauge_rect.width, 16), 0.76, "GUIDANCE")
        self._draw_meter_bar(screen, pygame.Rect(gauge_rect.left, gauge_y + 26, gauge_rect.width, 16), 0.61 if self._comms_lock else 0.33, "COMMS")

        items_per_col = math.ceil(len(self._subsystems) / 2)
        col_w = list_rect.width // 2
        for idx, subsystem in enumerate(self._subsystems):
            col = idx // items_per_col
            row = idx % items_per_col
            x = list_rect.left + col * col_w
            y = list_rect.top + row * (self._font_small.get_linesize() + 8)
            color = self._ok if subsystem["status"] == "GO" else self._warn if subsystem["status"] == "HOLD" else self._alert
            tag = self._font_small.render(subsystem["name"], True, self._fg)
            status = self._font_small.render(subsystem["status"], True, color)
            detail = self._font_tiny.render(subsystem["detail"], True, self._dim)
            screen.blit(tag, (x, y))
            screen.blit(status, (x + 86, y))
            screen.blit(detail, (x + 146, y + 2))

    def _draw_meter_bar(self, screen, rect: pygame.Rect, value: float, label: str):
        pygame.draw.rect(screen, (28, 30, 34), rect)
        pygame.draw.rect(screen, (92, 94, 96), rect, 1)
        fill_w = int(rect.width * max(0.0, min(1.0, value)))
        pygame.draw.rect(screen, self.accent_rgb, pygame.Rect(rect.left, rect.top, fill_w, rect.height))
        lbl = self._font_tiny.render(label, True, self._fg)
        screen.blit(lbl, (rect.left, rect.top - lbl.get_height() - 2))

    def _draw_chart(self, screen, rect: pygame.Rect, idx: int):
        if idx >= len(self._chart_history):
            return
        pygame.draw.rect(screen, (10, 12, 14), rect)
        pygame.draw.rect(screen, (84, 88, 92), rect, 1)

        history = self._chart_history[idx]
        label = self._chart_labels[idx]
        text = self._font_tiny.render(label, True, self.accent_rgb)
        screen.blit(text, (rect.left + 8, rect.top + 6))

        graph = rect.inflate(-12, -22)
        for i in range(1, 4):
            y = graph.top + int(graph.height * i / 4)
            pygame.draw.line(screen, (36, 38, 42), (graph.left, y), (graph.right, y), 1)

        pts = []
        denom = max(1, len(history) - 1)
        for i, value in enumerate(history):
            x = graph.left + int(graph.width * i / denom)
            y = graph.bottom - int(graph.height * value)
            pts.append((x, y))
        if len(pts) > 1:
            pygame.draw.lines(screen, self.accent_rgb, False, pts, 2)

    def _draw_consoles_panel(self, screen):
        rect = self._consoles_rect
        self._panel_box(screen, rect, "FLIGHT CONTROLLER ROW")

        inner = rect.inflate(-18, -22)
        inner.y += 12
        cell_gap = 8
        cell_w = max(38, (inner.width - (self.console_cols - 1) * cell_gap) // self.console_cols)
        cell_h = max(24, (inner.height - (self.console_rows - 1) * cell_gap) // self.console_rows)

        for row in range(self.console_rows):
            for col in range(self.console_cols):
                idx = row * self.console_cols + col
                if idx >= len(self._console_cells):
                    continue
                cell = self._console_cells[idx]
                x = inner.left + col * (cell_w + cell_gap)
                y = inner.top + row * (cell_h + cell_gap)
                r = pygame.Rect(x, y, cell_w, cell_h)
                pygame.draw.rect(screen, (18, 20, 22), r, border_radius=2)
                pygame.draw.rect(screen, (68, 70, 72), r, 1, border_radius=2)

                lamp_color = self._ok if cell["lamp"] else (54, 58, 60)
                pygame.draw.circle(screen, lamp_color, (r.left + 12, r.centery), 5)
                pygame.draw.circle(screen, (0, 0, 0), (r.left + 12, r.centery), 5, 1)

                meter = pygame.Rect(r.left + 24, r.centery - 5, r.width - 32, 10)
                pygame.draw.rect(screen, (26, 28, 30), meter)
                pygame.draw.rect(screen, (86, 88, 90), meter, 1)
                fill = int(meter.width * cell["meter"])
                pygame.draw.rect(screen, self.accent_rgb, pygame.Rect(meter.left, meter.top, fill, meter.height))

    def _draw_log_panel(self, screen):
        rect = self._log_rect
        self._panel_box(screen, rect, "EVENT LOOP")

        inner = rect.inflate(-18, -20)
        inner.y += 16
        line_h = self._font_small.get_linesize() + 4
        visible = max(1, inner.height // line_h)
        lines = self._events[-visible:]

        for idx, event in enumerate(lines):
            y = inner.top + idx * line_h
            color = self._fg
            if event.kind == "WARN":
                color = self._warn
            elif event.kind == "ALERT":
                color = self._alert

            stamp = self._font_tiny.render(f"T+{int(self._t * 45):05d}", True, self._dim)
            kind = self._font_tiny.render(event.kind, True, color)
            text = self._font_small.render(event.text, True, self._fg)
            screen.blit(stamp, (inner.left, y + 3))
            screen.blit(kind, (inner.left + 64, y + 3))
            screen.blit(text, (inner.left + 124, y))

    def _draw_footer(self, screen):
        footer_y = self.h - self._footer_h + 10
        now = self._mission_start + timedelta(seconds=int(self._t * 45))
        left = self._font_small.render(now.strftime("GMT %d %b %Y  %H:%M:%S"), True, self._dim)
        right = self._font_small.render(f"SEED {self.seed}   REFRESH {int(self.refresh_hz)} HZ", True, self._dim)
        screen.blit(left, (self._pad, footer_y))
        screen.blit(right, (self.w - self._pad - right.get_width(), footer_y))

    def _latlon_to_xy(self, lat: float, lon: float, rect: pygame.Rect):
        x = rect.left + int(((lon + 180.0) / 360.0) * rect.width)
        y = rect.top + int(((90.0 - lat) / 180.0) * rect.height)
        return x, y

    def _draw_noise(self, screen):
        specks = max(18, (self.w * self.h) // 26000)
        for _ in range(specks):
            x = self._rng.randrange(0, self.w)
            y = self._rng.randrange(0, self.h)
            alpha = self._rng.randint(16, 16 + self.noise_alpha * 3)
            screen.fill((255, 255, 255, alpha), pygame.Rect(x, y, 1, 1), special_flags=pygame.BLEND_RGBA_ADD)

# galactic_navigation_mode.py

import math
import random
import time
from dataclasses import dataclass
from datetime import datetime

import pygame


@dataclass
class Waypoint:
    name: str
    x: float   # normalized 0..1
    y: float   # normalized 0..1
    kind: str  # "RELAY", "GATE", "BEACON", etc.
    threat: float  # 0..1


class GalacticNavigationConsoleMode:
    """
    Galactic Navigation Console (sci-fi HUD / star chart).

    Config (all optional):
      - refresh_hz (float): target UI update rate (default 60)
      - seed (int): RNG seed for reproducible sectors (default random)
      - sector_name (str): label shown on HUD (default "SECTOR: UNKNOWN")
      - waypoint_count (int): number of waypoints (default 8)
      - star_count (int): number of background stars (default 240)
      - grid_alpha (int): 0..255 grid line opacity (default 70)
      - scanline_alpha (int): 0..255 scanline overlay opacity (default 16)
      - accent_rgb (list[int,int,int]): HUD accent color (default [80,200,255])
      - show_coordinates (bool): show crosshair coords (default True)
      - jump_interval_sec (float): how often to "jump" to a new sector (default 18.0)
      - waypoint_labels (list[str]): optional names used before auto-generated names

    Lifecycle matches your existing modes: enter/exit/update/render.
    """

    def __init__(self, config: dict):
        self.refresh_hz = float(config.get("refresh_hz", 60.0))
        self.seed = config.get("seed", None)
        self.sector_name = str(config.get("sector_name", "SECTOR: UNKNOWN"))
        self.waypoint_count = int(config.get("waypoint_count", 8))
        self.star_count = int(config.get("star_count", 240))
        self.grid_alpha = int(config.get("grid_alpha", 70))
        self.scanline_alpha = int(config.get("scanline_alpha", 16))
        self.accent_rgb = tuple(config.get("accent_rgb", [80, 200, 255]))
        self.show_coordinates = bool(config.get("show_coordinates", True))
        self.jump_interval_sec = float(config.get("jump_interval_sec", 18.0))
        self.waypoint_labels = config.get("waypoint_labels", None)

        # runtime
        self.manager = None
        self.w = 0
        self.h = 0
        self._is_portrait = False

        # layout
        self._side_margin = 0
        self._top_margin = 0
        self._hud_band_h = 0
        self._map_rect = pygame.Rect(0, 0, 0, 0)
        self._right_panel_rect = pygame.Rect(0, 0, 0, 0)

        # colors
        self._bg = (0, 0, 0)
        self._fg = (235, 235, 235)
        self._dim = (140, 140, 140)
        self._grid = (*self.accent_rgb, self.grid_alpha)

        # timing
        self._t = 0.0
        self._last_jump = 0.0
        self._next_jump = self.jump_interval_sec

        # procedural content
        self._rng = random.Random()
        self._stars = []      # list of (x,y,mag,twinkle_phase)
        self._waypoints = []  # list[Waypoint]
        self._route = []      # list[int] indices into waypoints

        # surfaces (scanlines, vignette)
        self._scanlines_surf = None

    # ---------- lifecycle ----------

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._recompute_layout()
        self._generate_sector()

    def exit(self):
        self.manager = None
        self._stars = []
        self._waypoints = []
        self._route = []
        self._scanlines_surf = None

    def handle_event(self, event):
        # Optional: tap SPACE to force a jump
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self._generate_sector(force_new_seed=True)

    def update(self, dt: float):
        self._t += dt

        # resolution hotplug/rotation changes
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            self._build_scanlines()

        # timed "sector jump"
        if self._t - self._last_jump >= self._next_jump:
            self._generate_sector(force_new_seed=True)

    def render(self, screen: pygame.Surface):
        screen.fill(self._bg)

        # --- MAP AREA ---
        self._draw_starfield(screen, self._map_rect)
        self._draw_grid(screen, self._map_rect)
        self._draw_waypoints(screen, self._map_rect)
        self._draw_route(screen, self._map_rect)
        self._draw_crosshair(screen, self._map_rect)

        # --- HUD + PANELS ---
        self._draw_hud_header(screen)
        self._draw_right_panel(screen)

    # ---------- sector generation ----------

    def _reseed(self):
        if self.seed is None:
            self.seed = random.randrange(1, 2**31 - 1)
        self._rng.seed(int(self.seed))

    def _generate_sector(self, force_new_seed: bool = False):
        if force_new_seed:
            # change seed for a new look each jump
            self.seed = self._rng.randrange(1, 2**31 - 1)
            self._rng.seed(int(self.seed))

        self._last_jump = self._t
        self._next_jump = max(8.0, self.jump_interval_sec + self._rng.uniform(-4.0, 6.0))

        # stars (normalized)
        self._stars = []
        for _ in range(max(50, self.star_count)):
            x = self._rng.random()
            y = self._rng.random()
            mag = self._rng.uniform(0.35, 1.0)
            ph = self._rng.uniform(0, math.tau)
            self._stars.append((x, y, mag, ph))

        # waypoints
        kinds = ["RELAY", "GATE", "BEACON", "OUTPOST", "RUIN", "BUOY"]
        self._waypoints = []

        labels = list(self.waypoint_labels) if isinstance(self.waypoint_labels, list) else []
        for i in range(max(3, self.waypoint_count)):
            name = labels[i] if i < len(labels) else self._make_waypoint_name(i)
            wp = Waypoint(
                name=name,
                x=self._rng.random(),
                y=self._rng.random(),
                kind=self._rng.choice(kinds),
                threat=self._rng.random() ** 1.7,  # bias towards low threat
            )
            self._waypoints.append(wp)

        # route: pick a simple Hamilton-ish path by nearest-neighbor
        self._route = self._build_route()

        # rebuild overlay assets
        self._build_scanlines()

    def _make_waypoint_name(self, i: int) -> str:
        syll_a = ["VE", "OR", "KA", "LY", "XI", "TA", "NO", "SA", "UR", "ZE", "AL", "ME"]
        syll_b = ["LA", "RIN", "DRA", "TOS", "VEX", "MIR", "QUA", "NIS", "BEX", "RHO", "NEX"]
        tag = f"{self._rng.choice(syll_a)}{self._rng.choice(syll_b)}"
        code = f"{self._rng.choice('ABCDEFGHJKLMNPQRSTUVWXYZ')}-{self._rng.randrange(10,99)}"
        return f"{tag} {code}"

    def _build_route(self):
        if not self._waypoints:
            return []
        remaining = set(range(len(self._waypoints)))
        # start near center to look intentional
        start = min(
            remaining,
            key=lambda idx: (self._waypoints[idx].x - 0.5) ** 2 + (self._waypoints[idx].y - 0.5) ** 2
        )
        route = [start]
        remaining.remove(start)

        while remaining:
            last = route[-1]
            nxt = min(
                remaining,
                key=lambda idx: (self._waypoints[idx].x - self._waypoints[last].x) ** 2
                              + (self._waypoints[idx].y - self._waypoints[last].y) ** 2
            )
            route.append(nxt)
            remaining.remove(nxt)
        return route

    # ---------- drawing ----------

    def _draw_starfield(self, screen, rect: pygame.Rect):
        # Slight parallax drift
        drift = 0.008 * math.sin(self._t * 0.25)

        for (nx, ny, mag, ph) in self._stars:
            # twinkle
            tw = 0.55 + 0.45 * math.sin(self._t * 1.7 + ph)
            a = int(120 * mag * tw) + 20
            a = max(25, min(200, a))

            x = rect.left + int(((nx + drift) % 1.0) * rect.width)
            y = rect.top + int(ny * rect.height)

            # tiny star
            col = (self.accent_rgb[0], self.accent_rgb[1], self.accent_rgb[2], a)
            # draw on temp surface to support alpha
            s = pygame.Surface((3, 3), pygame.SRCALPHA)
            pygame.draw.circle(s, col, (1, 1), 1)
            screen.blit(s, (x, y))

    def _draw_grid(self, screen, rect: pygame.Rect):
        if self.grid_alpha <= 0:
            return

        grid_surf = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        step = max(40, int(min(rect.width, rect.height) * 0.08))
        major = step * 2

        # minor lines
        for x in range(0, rect.width + 1, step):
            alpha = int(self.grid_alpha * 0.35)
            pygame.draw.line(grid_surf, (*self.accent_rgb, alpha), (x, 0), (x, rect.height), 1)
        for y in range(0, rect.height + 1, step):
            alpha = int(self.grid_alpha * 0.35)
            pygame.draw.line(grid_surf, (*self.accent_rgb, alpha), (0, y), (rect.width, y), 1)

        # major lines
        for x in range(0, rect.width + 1, major):
            pygame.draw.line(grid_surf, (*self.accent_rgb, self.grid_alpha), (x, 0), (x, rect.height), 2)
        for y in range(0, rect.height + 1, major):
            pygame.draw.line(grid_surf, (*self.accent_rgb, self.grid_alpha), (0, y), (rect.width, y), 2)

        # border
        pygame.draw.rect(grid_surf, (*self.accent_rgb, min(200, self.grid_alpha + 60)), grid_surf.get_rect(), 2)

        screen.blit(grid_surf, rect.topleft)

    def _draw_waypoints(self, screen, rect: pygame.Rect):
        if not self._waypoints:
            return

        for i, wp in enumerate(self._waypoints):
            x = rect.left + int(wp.x * rect.width)
            y = rect.top + int(wp.y * rect.height)

            # threat color shift: more threat => warmer tint
            r = int(self.accent_rgb[0] + 140 * wp.threat)
            g = int(self.accent_rgb[1] - 120 * wp.threat)
            b = int(self.accent_rgb[2] - 140 * wp.threat)
            r = max(0, min(255, r))
            g = max(0, min(255, g))
            b = max(0, min(255, b))

            pulse = 0.6 + 0.4 * math.sin(self._t * 2.2 + i * 0.7)
            radius = max(4, int(min(rect.width, rect.height) * (0.010 + 0.006 * pulse)))

            # ring + dot
            pygame.draw.circle(screen, (r, g, b), (x, y), radius, 2)
            pygame.draw.circle(screen, (r, g, b), (x, y), max(1, radius // 3))

    def _draw_route(self, screen, rect: pygame.Rect):
        if len(self._route) < 2:
            return

        # animated "flow" along the route
        phase = (self._t * 0.35) % 1.0
        pts = []
        for idx in self._route:
            wp = self._waypoints[idx]
            pts.append((rect.left + int(wp.x * rect.width), rect.top + int(wp.y * rect.height)))

        # base line
        pygame.draw.lines(screen, self.accent_rgb, False, pts, 2)

        # moving pips
        for k in range(10):
            t = (phase + k * 0.1) % 1.0
            p = self._point_on_polyline(pts, t)
            if p:
                pygame.draw.circle(screen, self.accent_rgb, p, 2)

    def _point_on_polyline(self, pts, t01):
        # t01 in [0..1] along total length
        if len(pts) < 2:
            return None
        seglens = []
        total = 0.0
        for a, b in zip(pts, pts[1:]):
            d = math.hypot(b[0] - a[0], b[1] - a[1])
            seglens.append(d)
            total += d
        if total <= 0:
            return pts[0]

        dist = t01 * total
        for (a, b), d in zip(zip(pts, pts[1:]), seglens):
            if dist <= d:
                u = dist / max(1e-6, d)
                x = int(a[0] + (b[0] - a[0]) * u)
                y = int(a[1] + (b[1] - a[1]) * u)
                return (x, y)
            dist -= d
        return pts[-1]

    def _draw_crosshair(self, screen, rect: pygame.Rect):
        cx = rect.left + rect.width // 2
        cy = rect.top + rect.height // 2

        # subtle breathing
        a = 100 + int(50 * (0.5 + 0.5 * math.sin(self._t * 0.9)))
        col = (*self.accent_rgb, a)
        s = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)

        pygame.draw.line(s, col, (cx - rect.left, 0), (cx - rect.left, rect.height), 1)
        pygame.draw.line(s, col, (0, cy - rect.top), (rect.width, cy - rect.top), 1)

        # center tick marks
        tick = max(10, int(min(rect.width, rect.height) * 0.03))
        pygame.draw.line(s, (*self.accent_rgb, a + 40), (cx - rect.left - tick, cy - rect.top),
                         (cx - rect.left + tick, cy - rect.top), 2)
        pygame.draw.line(s, (*self.accent_rgb, a + 40), (cx - rect.left, cy - rect.top - tick),
                         (cx - rect.left, cy - rect.top + tick), 2)

        screen.blit(s, rect.topleft)

    def _draw_hud_header(self, screen):
        # Fonts like your system info mode: use manager.cache
        title_size = max(18, int(min(self.w, self.h) * 0.045))
        small_size = max(14, int(min(self.w, self.h) * 0.026))

        title_font = self.manager.cache.get_font("dejavusansmono", title_size, bold=True)
        small_font = self.manager.cache.get_font("dejavusansmono", small_size, bold=False)

        # header band
        band = pygame.Rect(0, 0, self.w, self._hud_band_h)
        band_surf = pygame.Surface((band.width, band.height), pygame.SRCALPHA)
        band_surf.fill((0, 0, 0, 210))
        screen.blit(band_surf, band.topleft)

        # left: sector + timestamp
        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        line1 = self.sector_name
        line2 = f"STAR-CHART SEED {int(self.seed)}   |   UTC {ts}"

        t1 = title_font.render(line1, True, self.accent_rgb)
        t2 = small_font.render(line2, True, self._dim)
        screen.blit(t1, (self._side_margin, self._top_margin))
        screen.blit(t2, (self._side_margin, self._top_margin + t1.get_height() + 2))

        # right: jump status
        remaining = max(0.0, self._next_jump - (self._t - self._last_jump))
        jump_txt = f"JUMP IN {remaining:4.1f}s"
        jt = title_font.render(jump_txt, True, self._fg)
        screen.blit(jt, (self.w - self._side_margin - jt.get_width(), self._top_margin))

    def _draw_right_panel(self, screen):
        # Panel with waypoint list + fake telemetry
        panel = self._right_panel_rect
        if panel.width <= 10:
            return

        panel_bg = pygame.Surface((panel.width, panel.height), pygame.SRCALPHA)
        panel_bg.fill((0, 0, 0, 190))
        pygame.draw.rect(panel_bg, (*self.accent_rgb, 160), panel_bg.get_rect(), 2)
        screen.blit(panel_bg, panel.topleft)

        pad = max(10, int(panel.width * 0.06))
        x = panel.left + pad
        y = panel.top + pad

        head_size = max(16, int(min(self.w, self.h) * 0.030))
        body_size = max(13, int(min(self.w, self.h) * 0.022))

        head_font = self.manager.cache.get_font("dejavusansmono", head_size, bold=True)
        body_font = self.manager.cache.get_font("dejavusansmono", body_size, bold=False)

        # title
        hdr = head_font.render("WAYPOINTS", True, self.accent_rgb)
        screen.blit(hdr, (x, y))
        y += hdr.get_height() + 8

        # waypoint rows
        max_rows = max(3, int((panel.height - 4 * pad) / (body_font.get_linesize() + 6)) - 6)
        for i, wp in enumerate(self._waypoints[:max_rows]):
            threat_pct = int(wp.threat * 100)
            row = f"{i+1:02d}  {wp.kind:<7}  {wp.name:<14}  THR {threat_pct:02d}%"
            surf = body_font.render(row, True, self._fg if wp.threat < 0.6 else (255, 200, 120))
            screen.blit(surf, (x, y))
            y += body_font.get_linesize() + 4

        y += 10
        pygame.draw.line(screen, self._dim, (panel.left + pad, y), (panel.right - pad, y), 1)
        y += 10

        # fake telemetry (makes it feel "busy" but not random-noise)
        drift = 0.12 * math.sin(self._t * 0.35)
        vel = 27.4 + 1.6 * math.sin(self._t * 0.22)
        snr = 18.0 + 6.0 * (0.5 + 0.5 * math.sin(self._t * 0.9))
        lock = 0.65 + 0.25 * (0.5 + 0.5 * math.sin(self._t * 0.55))

        telemetry = [
            ("DRIFT", f"{drift:+.3f} AU"),
            ("VEL", f"{vel:.2f} km/s"),
            ("SNR", f"{snr:.1f} dB"),
            ("LOCK", f"{lock*100:5.1f}%"),
            ("MAP", "CALIBRATED"),
        ]

        for k, v in telemetry:
            line = f"{k:<6}: {v}"
            surf = body_font.render(line, True, self._dim)
            screen.blit(surf, (x, y))
            y += body_font.get_linesize() + 4

        if self.show_coordinates:
            # show crosshair coords (normalized)
            cx = 0.5 + 0.02 * math.sin(self._t * 0.4)
            cy = 0.5 + 0.02 * math.cos(self._t * 0.33)
            y += 6
            surf = body_font.render(f"CURSOR: X {cx:0.3f}  Y {cy:0.3f}", True, self._dim)
            screen.blit(surf, (x, y))

    # ---------- layout / overlays ----------

    def _recompute_layout(self):
        self.w, self.h = self.manager.screen.get_size()
        self._is_portrait = self.h > self.w

        self._side_margin = int(self.w * 0.05)
        self._top_margin = int(self.h * 0.02)

        self._hud_band_h = max(70, int(self.h * (0.13 if self._is_portrait else 0.11)))

        # Map area consumes most, right panel optional if landscape wide enough
        top = self._hud_band_h
        bottom_margin = int(self.h * 0.03)

        if (not self._is_portrait) and self.w >= 900:
            panel_w = int(self.w * 0.32)
            map_w = self.w - panel_w - self._side_margin
            self._map_rect = pygame.Rect(self._side_margin // 2, top, map_w, self.h - top - bottom_margin)
            self._right_panel_rect = pygame.Rect(self._map_rect.right + self._side_margin // 2, top, panel_w, self.h - top - bottom_margin)
        else:
            self._map_rect = pygame.Rect(self._side_margin // 2, top, self.w - self._side_margin, self.h - top - bottom_margin)
            self._right_panel_rect = pygame.Rect(0, 0, 0, 0)

    def _build_scanlines(self):
        self._scanlines_surf = None

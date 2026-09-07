# modes/satellite_tracker_mode.py
#
# Satellite Tracker — real-time tracking of real satellites.
#
# The mission-control aesthetic, but every number is real: positions come
# from TLE element sets (CelesTrak, no API key) propagated locally with
# SGP4 (core/orbit.py). One curated target per day (date-seeded rotation,
# no state file). Optional ground-station pass prediction when
# observer_lat/observer_lon are configured.
#
# Offline behavior: TLEs are cached on disk (data/tle_cache/) and reused
# with a visible staleness indicator; with no cache and no network the
# mode shows a "NO TRACKING DATA" panel instead of crashing.
#
# Controls: SPACE = skip to next target.

from datetime import datetime, timedelta, timezone

import pygame

from core import mapdraw
from core.mapdata import load_coastlines
from core.orbit import (
    Orbit, footprint_radius_deg, is_night, look_angles, predict_passes,
    subsolar_point, target_for_date,
)
from core.tle_store import TLEStore

# Curated list of famous satellites. NORAD ids and CelesTrak group
# membership verified live against celestrak.org on 2026-08-01.
DEFAULT_TARGETS = [
    {"name": "ISS (ZARYA)",        "norad": 25544, "group": "stations"},
    {"name": "CSS (TIANHE)",       "norad": 48274, "group": "stations"},
    {"name": "HST (HUBBLE)",       "norad": 20580, "group": "visual"},
    {"name": "ENVISAT",            "norad": 27386, "group": "visual"},
    {"name": "TERRA",              "norad": 25994, "group": "visual"},
    {"name": "AQUA",               "norad": 27424, "group": "visual"},
    {"name": "GOES 16",            "norad": 41866, "group": "weather"},
    {"name": "NOAA 20 (JPSS-1)",   "norad": 43013, "group": "weather"},
    {"name": "LANDSAT 8",          "norad": 39084, "group": "resource"},
    {"name": "RADFXSAT (FOX-1B)",  "norad": 43017, "group": "amateur"},
]


class SatelliteTrackerMode:
    """
    Config (all optional unless noted):
      - duration (per schema convention; enforced by the controller)
      - targets: list of {"name", "norad", "group"} (default: built-in list)
      - rotation: "daily" (default) | "first" | "random"
      - tle_max_age_hours: cache freshness window (default 24)
      - cache_dir: TLE cache location (default data/tle_cache)
      - update_hz: subpoint refresh rate (default 1.0)
      - observer_lat / observer_lon / observer_name: ground station for
        pass prediction; omit to disable that panel
      - title, accent_rgb, seed, scanline_alpha
    """

    def __init__(self, config: dict):
        self.title = str(config.get("title", "SATELLITE TRACKING NETWORK"))
        self.targets = list(config.get("targets", DEFAULT_TARGETS))
        self.rotation = str(config.get("rotation", "daily"))
        self.tle_max_age_hours = float(config.get("tle_max_age_hours", 24))
        self.cache_dir = str(config.get("cache_dir", "data/tle_cache"))
        self.update_hz = max(0.2, float(config.get("update_hz", 1.0)))
        self.accent_rgb = tuple(config.get("accent_rgb", [255, 205, 135]))
        self.scanline_alpha = int(config.get("scanline_alpha", 0))
        self.seed = config.get("seed", None)

        obs_lat = config.get("observer_lat", None)
        obs_lon = config.get("observer_lon", None)
        self.observer = None
        if obs_lat is not None and obs_lon is not None:
            self.observer = (float(obs_lat), float(obs_lon))
        self.observer_name = str(config.get("observer_name", "HOME QTH"))

        self.manager = None
        self.w = 0
        self.h = 0
        self._t = 0.0

        # Palette (matches mission control's retro phosphor look)
        self._bg = (6, 7, 8)
        self._fg = (232, 226, 214)
        self._dim = (132, 128, 118)
        self._ok = (124, 255, 158)
        self._warn = (255, 210, 104)
        self._alert = (255, 112, 112)
        self._panel_edge = (70, 74, 78)
        self._map_land = (96, 110, 98)
        self._map_grid = (40, 45, 48)

        # Layout
        self._pad = 0
        self._header_h = 0
        self._footer_h = 0
        self._map_rect = pygame.Rect(0, 0, 0, 0)
        self._tele_rect = pygame.Rect(0, 0, 0, 0)
        self._pass_rect = pygame.Rect(0, 0, 0, 0)
        self._log_rect = pygame.Rect(0, 0, 0, 0)

        self._font_header = None
        self._font_body = None
        self._font_small = None
        self._font_tiny = None
        self._scanlines = None

        # Tracking state (populated by _acquire_target)
        self.target = None
        self.target_index = -1
        self.record = None        # TLERecord or None
        self.orbit = None         # Orbit or None
        self.subpoint = None      # current SubPoint or None
        self.ground_track = []    # [(lat, lon), ...]
        self._gt_now_pos = 0      # index in ground_track nearest "now"
        self.footprint = []       # [(lat, lon), ...]
        self.passes = []          # upcoming Pass objects
        self.current_el = None    # elevation at observer right now
        self._was_visible = False

        self._next_subpoint_t = 0.0
        self._next_slow_t = 0.0   # ground track / terminator / passes refresh
        self._night_key = None
        self._night_surface = None
        self._events = []         # [(text, color)] newest last

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def enter(self, manager):
        self.manager = manager
        self._t = 0.0
        self._recompute_layout()
        self._build_scanlines()
        self._acquire_target(initial=True)

    def exit(self):
        self.manager = None
        self.orbit = None
        self.record = None
        self.ground_track = []
        self.footprint = []
        self.passes = []
        self._events = []
        self._night_surface = None
        self._scanlines = None

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            # Manual override: hop to the next target in the list.
            self.target_index = (self.target_index + 1) % len(self.targets)
            self._acquire_target(index=self.target_index)

    # ------------------------------------------------------------------
    # Target acquisition / data refresh
    # ------------------------------------------------------------------

    def _pick_target(self):
        if self.rotation == "first":
            return self.targets[0], 0
        if self.rotation == "random":
            import random
            rng = random.Random(self.seed)
            idx = rng.randrange(len(self.targets))
            return self.targets[idx], idx
        return target_for_date(self.targets, datetime.now(timezone.utc))

    def _acquire_target(self, initial=False, index=None):
        if index is not None:
            self.target = self.targets[index % len(self.targets)]
            self.target_index = index % len(self.targets)
        else:
            self.target, self.target_index = self._pick_target()

        self._log(f"TARGET ACQUIRED: {self.target['name']}", self._fg)
        self._log(f"NORAD {self.target['norad']} // GROUP {self.target['group'].upper()}", self._dim)

        store = TLEStore(self.cache_dir, max_age_hours=self.tle_max_age_hours)
        self.record = store.get_satellite(self.target["group"], self.target["norad"])
        self.orbit = None
        self.subpoint = None
        self.ground_track = []
        self.footprint = []
        self.passes = []
        self.current_el = None
        self._was_visible = False

        if self.record is None:
            self._log("NO TRACKING DATA — offline and no TLE cache", self._alert)
            return

        self.orbit = Orbit(self.record.name, self.record.norad_id,
                           self.record.line1, self.record.line2)
        if self.record.status == "refreshed":
            self._log(f"TLE DOWNLOADED ({self.record.group})", self._ok)
        elif self.record.status == "stale":
            self._log(f"USING STALE TLE — AGE {self.record.age_hours:.1f} H", self._warn)
        else:
            self._log(f"TLE FROM CACHE — AGE {self.record.age_hours:.1f} H", self._dim)

        self._refresh_tracking_data()

    def _refresh_tracking_data(self):
        """Slow-path recompute: ground track, passes. Runs ~once a minute."""
        if self.orbit is None:
            return
        now = datetime.now(timezone.utc)
        period = self.orbit.period_minutes
        # Half an orbit of history, a full orbit ahead — reads like the
        # classic NASA tracking wall.
        self.ground_track = self.orbit.ground_track(
            now, before_min=period * 0.5, after_min=period * 1.0)
        # Points are chronological; "now" sits before_min into the list.
        self._gt_now_pos = len(self.ground_track) // 3

        if self.observer is not None:
            try:
                self.passes = predict_passes(
                    self.orbit, self.observer[0], self.observer[1],
                    now, hours=24.0)
            except Exception as e:
                print(f"[Tracker] pass prediction failed: {e}")
                self.passes = []
        self._night_key = None  # force terminator overlay rebuild

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, dt: float):
        self._t += dt

        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            self._build_scanlines()
            self._night_key = None

        if self.orbit is not None and self._t >= self._next_subpoint_t:
            self._next_subpoint_t = self._t + 1.0 / self.update_hz
            self._update_subpoint()

        if self.orbit is not None and self._t >= self._next_slow_t:
            self._next_slow_t = self._t + 60.0
            self._refresh_tracking_data()

    def _update_subpoint(self):
        now = datetime.now(timezone.utc)
        self.subpoint = self.orbit.subpoint(now)
        if self.subpoint is None:
            self._log("PROPAGATION ERROR — TLE MAY BE DECAYED", self._alert)
            self.orbit = None
            return
        self.footprint = self.orbit.footprint_circle(
            self.subpoint.lat, self.subpoint.lon, self.subpoint.alt_km)

        if self.observer is not None:
            pos = self.orbit.ecef(now)
            if pos is not None:
                az, el, rng = look_angles(pos, self.observer[0], self.observer[1])
                self.current_el = el
                visible = el >= 0.0
                if visible and not self._was_visible:
                    self._log(f"AOS — {self.target['name']} ABOVE HORIZON", self._ok)
                elif not visible and self._was_visible:
                    self._log(f"LOS — {self.target['name']} BELOW HORIZON", self._warn)
                self._was_visible = visible

    # ------------------------------------------------------------------
    # Layout / fonts
    # ------------------------------------------------------------------

    def _recompute_layout(self):
        self.w, self.h = self.manager.screen.get_size()
        self._pad = max(10, int(min(self.w, self.h) * 0.02))
        self._header_h = max(40, int(self.h * 0.075))
        self._footer_h = max(28, int(self.h * 0.05))

        base = min(self.w, self.h)
        c = self.manager.cache
        self._font_header = c.get_font("dejavusansmono", max(18, int(base * 0.042)), bold=True)
        self._font_body = c.get_font("dejavusansmono", max(13, int(base * 0.023)), bold=False)
        self._font_small = c.get_font("dejavusansmono", max(11, int(base * 0.017)), bold=False)
        self._font_tiny = c.get_font("dejavusansmono", max(10, int(base * 0.014)), bold=False)

        mr = pygame.Rect(self._pad, self._header_h,
                         self.w - 2 * self._pad,
                         self.h - self._header_h - self._footer_h - self._pad)
        gap = 8
        portrait = self.h > self.w
        if portrait:
            map_h = int(mr.height * 0.44)
            tele_h = int(mr.height * 0.24)
            pass_h = int(mr.height * 0.16)
            self._map_rect = pygame.Rect(mr.left, mr.top, mr.width, map_h)
            self._tele_rect = pygame.Rect(mr.left, self._map_rect.bottom + gap, mr.width, tele_h)
            self._pass_rect = pygame.Rect(mr.left, self._tele_rect.bottom + gap, mr.width, pass_h)
            self._log_rect = pygame.Rect(mr.left, self._pass_rect.bottom + gap, mr.width,
                                         mr.bottom - self._pass_rect.bottom - gap)
        else:
            map_w = int(mr.width * 0.62)
            tele_h = int(mr.height * 0.52)
            pass_h = int(mr.height * 0.24)
            self._map_rect = pygame.Rect(mr.left, mr.top, map_w, mr.height)
            right_x = self._map_rect.right + gap
            right_w = mr.right - right_x
            self._tele_rect = pygame.Rect(right_x, mr.top, right_w, tele_h)
            self._pass_rect = pygame.Rect(right_x, self._tele_rect.bottom + gap, right_w, pass_h)
            self._log_rect = pygame.Rect(right_x, self._pass_rect.bottom + gap, right_w,
                                         mr.bottom - self._pass_rect.bottom - gap)

    def _build_scanlines(self):
        self._scanlines = None
        if self.scanline_alpha <= 0 or self.w <= 0:
            return
        s = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        for y in range(0, self.h, 3):
            pygame.draw.line(s, (0, 0, 0, self.scanline_alpha), (0, y), (self.w, y))
        self._scanlines = s

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, screen: pygame.Surface):
        screen.fill(self._bg)
        self._draw_header(screen)
        self._draw_map_panel(screen)
        self._draw_telemetry_panel(screen)
        self._draw_pass_panel(screen)
        self._draw_log_panel(screen)
        self._draw_footer(screen)
        if self._scanlines is not None:
            screen.blit(self._scanlines, (0, 0))

    def _panel_box(self, screen, rect, title):
        pygame.draw.rect(screen, (10, 12, 13), rect)
        pygame.draw.rect(screen, self._panel_edge, rect, 1)
        label = self._font_tiny.render(title, True, self.accent_rgb)
        # Title sits on the top edge, classic console-panel style.
        screen.blit(label, (rect.left + 10, rect.top - label.get_height() // 2))
        pygame.draw.rect(screen, (6, 7, 8),
                         (rect.left + 8, rect.top - label.get_height() // 2 - 1,
                          label.get_width() + 4, label.get_height() + 2))
        screen.blit(label, (rect.left + 10, rect.top - label.get_height() // 2))

    def _latlon_to_xy(self, lat, lon, rect):
        # Shared projection helper (kept as a thin wrapper for call sites).
        return mapdraw.latlon_to_xy(rect, lat, lon)

    def _draw_header(self, screen):
        y = self._pad // 2
        title = self._font_header.render(self.title, True, self._fg)
        screen.blit(title, (self._pad, y))
        if self.target is not None:
            tag = self._font_body.render(
                f"TARGET {self.target_index + 1}/{len(self.targets)}: {self.target['name']}",
                True, self.accent_rgb)
            screen.blit(tag, (self.w - self._pad - tag.get_width(),
                              y + (title.get_height() - tag.get_height()) // 2))
        line_y = self._header_h - 6
        pygame.draw.line(screen, self._panel_edge,
                         (self._pad, line_y), (self.w - self._pad, line_y), 1)

    # ----- map -----

    def _draw_map_panel(self, screen):
        rect = self._map_rect
        name = self.target["name"] if self.target else "—"
        self._panel_box(screen, rect, f"ORBITAL TRACK — {name}")

        inner = rect.inflate(-16, -14)
        inner.top += 8
        pygame.draw.rect(screen, (8, 10, 12), inner)
        pygame.draw.rect(screen, self._panel_edge, inner, 1)

        prev_clip = screen.get_clip()
        screen.set_clip(inner)

        self._draw_grid(screen, inner)
        self._draw_coastlines(screen, inner)
        self._draw_night(screen, inner)

        if self.orbit is None:
            msg = "NO TRACKING DATA" if self.record is None else "PROPAGATION ERROR"
            text = self._font_body.render(msg, True, self._alert)
            screen.blit(text, (inner.centerx - text.get_width() // 2,
                               inner.centery - text.get_height() // 2))
        else:
            self._draw_ground_track(screen, inner)
            self._draw_footprint(screen, inner)
            self._draw_subpoint(screen, inner)

        self._draw_observer(screen, inner)
        screen.set_clip(prev_clip)

    def _draw_grid(self, screen, rect):
        for i in range(1, 6):
            x = rect.left + int(rect.width * i / 6)
            pygame.draw.line(screen, self._map_grid, (x, rect.top), (x, rect.bottom), 1)
        for i in range(1, 4):
            y = rect.top + int(rect.height * i / 4)
            pygame.draw.line(screen, self._map_grid, (rect.left, y), (rect.right, y), 1)

    def _draw_coastlines(self, screen, rect):
        coastlines = load_coastlines()
        if not coastlines:
            return
        for line in coastlines:
            pts = [self._latlon_to_xy(lat, lon, rect) for lon, lat in line]
            if len(pts) >= 2:
                pygame.draw.lines(screen, self._map_land, False, pts, 1)

    def _draw_night(self, screen, rect):
        """Night-side shading, recomputed at most once a minute."""
        now = datetime.now(timezone.utc)
        key = (rect.width, rect.height, now.strftime("%Y%m%d%H%M"))
        if self._night_key != key or self._night_surface is None:
            sun_lat, sun_lon = subsolar_point(now)
            surf = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
            cell = 8
            for cy in range(0, rect.height, cell):
                lat = 90.0 - (cy + cell / 2) / rect.height * 180.0
                for cx in range(0, rect.width, cell):
                    lon = (cx + cell / 2) / rect.width * 360.0 - 180.0
                    if is_night(lat, lon, sun_lat, sun_lon):
                        surf.fill((2, 6, 18, 78), (cx, cy, cell, cell))
            self._night_surface = surf
            self._night_key = key
        screen.blit(self._night_surface, rect.topleft)

    def _draw_track_segments(self, screen, rect, latlons, color, width):
        # Antimeridian-safe polyline drawing, shared via core.mapdraw.
        mapdraw.draw_latlon_polyline(screen, rect, latlons, color, width)

    def _draw_ground_track(self, screen, rect):
        if len(self.ground_track) < 2:
            return
        split = max(1, min(self._gt_now_pos, len(self.ground_track) - 1))
        past = self.ground_track[:split + 1]
        future = self.ground_track[split:]
        dim_accent = tuple(c // 3 for c in self.accent_rgb)
        self._draw_track_segments(screen, rect, past, dim_accent, 1)
        self._draw_track_segments(screen, rect, future, self.accent_rgb, 2)

    def _draw_footprint(self, screen, rect):
        if len(self.footprint) >= 3:
            ring = tuple(min(255, c // 2 + 20) for c in self._ok)
            self._draw_track_segments(screen, rect, self.footprint + self.footprint[:1], ring, 1)

    def _draw_subpoint(self, screen, rect):
        sp = self.subpoint
        if sp is None:
            return
        x, y = self._latlon_to_xy(sp.lat, sp.lon, rect)
        import math
        pulse = 1.0 + 0.3 * math.sin(self._t * 4.0)
        r = int(7 * pulse)
        color = self._ok if self.current_el is None or self.current_el >= 0 else self.accent_rgb
        pygame.draw.circle(screen, color, (x, y), r, 2)
        pygame.draw.circle(screen, self._fg, (x, y), 2)
        pygame.draw.line(screen, color, (x - r - 4, y), (x + r + 4, y), 1)
        pygame.draw.line(screen, color, (x, y - r - 4), (x, y + r + 4), 1)
        label = self._font_tiny.render(self.target["name"], True, self._fg)
        lx = min(x + 10, rect.right - label.get_width() - 2)
        screen.blit(label, (lx, y - r - label.get_height() - 2))

    def _draw_observer(self, screen, rect):
        if self.observer is None:
            return
        x, y = self._latlon_to_xy(self.observer[0], self.observer[1], rect)
        pygame.draw.polygon(screen, self._warn,
                            [(x, y - 5), (x + 5, y), (x, y + 5), (x - 5, y)], 1)
        label = self._font_tiny.render(self.observer_name, True, self._warn)
        screen.blit(label, (x + 8, y - label.get_height() // 2))
        # Line to the satellite while it is above the horizon.
        if self.subpoint is not None and self.current_el is not None and self.current_el >= 0:
            sx, sy = self._latlon_to_xy(self.subpoint.lat, self.subpoint.lon, rect)
            if abs(sx - x) < rect.width // 2:  # don't draw across antimeridian
                pygame.draw.line(screen, self._ok, (x, y), (sx, sy), 1)

    # ----- telemetry -----

    def _draw_telemetry_panel(self, screen):
        rect = self._tele_rect
        self._panel_box(screen, rect, "VEHICLE TELEMETRY")
        inner = rect.inflate(-20, -18)
        y = inner.top + 10
        dy = self._font_body.get_linesize() + 8

        def row(label, value, color=None):
            nonlocal y
            if y + dy > inner.bottom:
                return
            tag = self._font_small.render(label, True, self.accent_rgb)
            val = self._font_body.render(value, True, color or self._fg)
            screen.blit(tag, (inner.left, y + 2))
            screen.blit(val, (inner.left + int(inner.width * 0.38), y))
            y += dy

        if self.target is None:
            return
        row("NAME", self.target["name"])
        row("NORAD", str(self.target["norad"]))

        if self.record is None:
            row("STATUS", "NO DATA", self._alert)
            return

        age_h = self.record.age_hours
        age_color = self._ok if age_h < 36 else self._warn if age_h < 168 else self._alert
        age_txt = f"{age_h:.1f} H" if age_h < 48 else f"{age_h / 24:.1f} DAYS"
        row("TLE AGE", age_txt, age_color)
        row("STATUS", {"refreshed": "LIVE", "cached": "LIVE (CACHED)",
                       "stale": "STALE TLE"}.get(self.record.status, "?"),
            age_color if self.record.status == "stale" else self._ok)

        if self.subpoint is not None:
            sp = self.subpoint
            row("LAT", f"{sp.lat:+.2f} DEG")
            row("LON", f"{sp.lon:+.2f} DEG")
            row("ALT", f"{sp.alt_km:,.0f} KM")
            row("VEL", f"{sp.vel_kmh:,.0f} KM/H")
        if self.orbit is not None:
            row("PERIOD", f"{self.orbit.period_minutes:.1f} MIN")
            row("INCL", f"{self.orbit.inclination_deg:.2f} DEG")
            row("REV/DAY", f"{self.orbit.mean_motion_rev_day:.2f}")

    # ----- passes -----

    def _draw_pass_panel(self, screen):
        rect = self._pass_rect
        self._panel_box(screen, rect, f"GROUND STATION — {self.observer_name}")
        inner = rect.inflate(-20, -18)
        y = inner.top + 10

        if self.observer is None:
            lines = [
                "OBSERVER NOT CONFIGURED",
                "set observer_lat / observer_lon",
                "in modes_config.local.json",
            ]
            for ln in lines:
                text = self._font_small.render(ln, True, self._dim)
                screen.blit(text, (inner.left, y))
                y += self._font_small.get_linesize() + 6
            return

        qth = self._font_small.render(
            f"QTH {self.observer[0]:+.2f} / {self.observer[1]:+.2f}", True, self._dim)
        screen.blit(qth, (inner.left, y))
        y += self._font_small.get_linesize() + 8

        now = datetime.now(timezone.utc)
        if self.current_el is not None and self.current_el >= 0:
            state = self._font_body.render(f"IN VIEW — EL {self.current_el:.0f} DEG", True, self._ok)
            screen.blit(state, (inner.left, y))
            y += self._font_body.get_linesize() + 8
        else:
            upcoming = [p for p in self.passes if p.los > now]
            if upcoming:
                delta = upcoming[0].aos - now
                if delta.total_seconds() < 0:
                    delta = timedelta(0)
                h, rem = divmod(int(delta.total_seconds()), 3600)
                m, s = divmod(rem, 60)
                state = self._font_body.render(f"NEXT AOS IN {h:02d}:{m:02d}:{s:02d}", True, self._fg)
            else:
                state = self._font_body.render("NO PASSES IN 24H", True, self._warn)
            screen.blit(state, (inner.left, y))
            y += self._font_body.get_linesize() + 8

        for p in [p for p in self.passes if p.los > now][:4]:
            line = (f"{p.aos:%H:%M}-{p.los:%H:%M} GMT  "
                    f"MAX {p.max_elev_deg:4.0f} DEG  {p.duration_s / 60:.0f} MIN")
            color = self._ok if p.aos <= now <= p.los else self._dim
            text = self._font_small.render(line, True, color)
            screen.blit(text, (inner.left, y))
            y += self._font_small.get_linesize() + 5

    # ----- log / footer -----

    def _log(self, text, color=None):
        stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self._events.append((f"{stamp}  {text}", color or self._fg))
        self._events = self._events[-30:]

    def _draw_log_panel(self, screen):
        rect = self._log_rect
        self._panel_box(screen, rect, "EVENT LOG")
        inner = rect.inflate(-20, -18)
        line_h = self._font_small.get_linesize() + 5
        max_lines = max(1, (inner.height - 8) // line_h)
        y = inner.bottom - line_h
        for text, color in reversed(self._events[-max_lines:]):
            surf = self._font_small.render(text, True, color)
            screen.blit(surf, (inner.left, y))
            y -= line_h

    def _draw_footer(self, screen):
        y = self.h - self._footer_h + (self._footer_h - self._font_small.get_linesize()) // 2
        now = datetime.now(timezone.utc)
        clock = self._font_small.render(now.strftime("GMT %d %b %Y  %H:%M:%S"), True, self._dim)
        screen.blit(clock, (self._pad, y))

        midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        rem = midnight - now
        h, r = divmod(int(rem.total_seconds()), 3600)
        m, _ = divmod(r, 60)
        right = self._font_small.render(
            f"DAILY ROTATION — NEXT TARGET IN {h:02d}:{m:02d}   [SPACE] SKIP",
            True, self._dim)
        screen.blit(right, (self.w - self._pad - right.get_width(), y))

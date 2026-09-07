# autonomous_drone_fleet_tracker_mode.py

import math
import random
from dataclasses import dataclass
from datetime import datetime

import pygame


@dataclass
class Drone:
    id: int
    x: float  # normalized 0..1 in map space
    y: float
    vx: float
    vy: float
    state: str  # PATROL / RETURN / CHARGE / OFFLINE
    battery: float  # 0..1
    phase: float
    target_x: float
    target_y: float
    timer: float  # generic timer


@dataclass
class EventMsg:
    t_end: float
    text: str
    kind: str  # INFO/WARN/ALERT


class AutonomousDroneFleetTrackerMode:
    """
    Autonomous Drone Fleet Tracker
    - Sector map with base station + drone icons + trails
    - Drones wander, occasionally return to base, charge, or go offline briefly
    - Portrait-friendly layout

    Config (optional):
      - title (str)
      - sector_name (str)
      - accent_rgb ([r,g,b])
      - refresh_hz (float)
      - seed (int)
      - drone_count (int)
      - show_event_log (bool)
      - map_margin_scale (float)
      - scanline_alpha (int 0..255)
      - noise_alpha (int 0..255)
      - crt_vignette (float 0..1)
      - offline_probability_per_min (float)
      - return_probability_per_min (float)
      - charge_time_range ([min,max] sec)
    """

    def __init__(self, config: dict):
        self.title = str(config.get("title", "AUTONOMOUS DRONE FLEET TRACKER"))
        self.sector_name = str(config.get("sector_name", "SECTOR: UNKNOWN"))
        self.accent_rgb = tuple(config.get("accent_rgb", [90, 220, 255]))

        self.refresh_hz = float(config.get("refresh_hz", 60.0))
        self.seed = config.get("seed", None)
        self.drone_count = int(config.get("drone_count", 24))
        self.show_event_log = bool(config.get("show_event_log", True))

        self.map_margin_scale = float(config.get("map_margin_scale", 0.05))

        self.scanline_alpha = int(config.get("scanline_alpha", 12))
        self.noise_alpha = int(config.get("noise_alpha", 10))
        self.crt_vignette = float(config.get("crt_vignette", 0.28))

        self.offline_probability_per_min = float(config.get("offline_probability_per_min", 0.5))
        self.return_probability_per_min = float(config.get("return_probability_per_min", 0.9))
        self.charge_time_range = config.get("charge_time_range", [6.0, 14.0])

        # runtime
        self.manager = None
        self.w = 0
        self.h = 0
        self._is_portrait = False

        # visuals
        self._bg = (0, 0, 0)
        self._fg = (235, 235, 235)
        self._dim = (150, 150, 150)

        # layout
        self._pad = 0
        self._header_h = 0
        self._footer_h = 0
        self._map_rect = pygame.Rect(0, 0, 0, 0)
        self._panel_rect = pygame.Rect(0, 0, 0, 0)

        # fonts
        self._font_header = None
        self._font_small = None
        self._font_body = None

        # state
        self._t = 0.0
        self._rng = random.Random()
        self._drones: list[Drone] = []
        self._events: list[EventMsg] = []

        # base station position (map space)
        self._base = (0.50, 0.86)  # slightly lower in portrait

        # rendering helpers
        self._trail_surface = None
        self._overlay = None
        self._vignette = None

    # ---------- lifecycle ----------

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._recompute_layout()
        self._build_overlays()
        self._init_drones()
        self._push_event("INFO", "fleet link established")

    def exit(self):
        self.manager = None
        self._drones = []
        self._events = []
        self._trail_surface = None
        self._overlay = None
        self._vignette = None

    def handle_event(self, event):
        # SPACE: force a “return to base” wave
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            for d in self._drones:
                if d.state == "PATROL":
                    self._set_state(d, "RETURN")

    def update(self, dt: float):
        self._t += dt

        # resize/hotplug
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            self._build_overlays()

        # event expiry
        now = self._t
        self._events = [e for e in self._events if e.t_end > now][-10:]

        # probabilistic state changes
        p_off = max(0.0, self.offline_probability_per_min) / 60.0
        p_ret = max(0.0, self.return_probability_per_min) / 60.0

        for d in self._drones:
            # battery drain / charge
            if d.state in ("PATROL", "RETURN"):
                d.battery = max(0.0, d.battery - dt * (0.010 + 0.010 * self._rng.random()))
            elif d.state == "CHARGE":
                d.battery = min(1.0, d.battery + dt * 0.08)

            # random return request if low battery
            if d.state == "PATROL" and d.battery < 0.30 and self._rng.random() < (0.6 * dt):
                self._set_state(d, "RETURN")

            # occasional return even if not low (gives life)
            if d.state == "PATROL" and self._rng.random() < p_ret * dt * 0.6:
                self._set_state(d, "RETURN")

            # occasional brief offline blip
            if d.state in ("PATROL", "RETURN") and self._rng.random() < p_off * dt * 0.7:
                self._set_state(d, "OFFLINE", duration=self._rng.uniform(1.5, 3.2))

        # physics + behavior
        self._tick_drones(dt)

        # fade trails
        if self._trail_surface is not None:
            fade = pygame.Surface((self._map_rect.width, self._map_rect.height), pygame.SRCALPHA)
            fade.fill((0, 0, 0, 18))
            self._trail_surface.blit(fade, (0, 0))

    def render(self, screen: pygame.Surface):
        screen.fill(self._bg)

        self._draw_header(screen)
        self._draw_map(screen)
        self._draw_footer(screen)

        if self._overlay is not None:
            screen.blit(self._overlay, (0, 0))
        if self._vignette is not None:
            screen.blit(self._vignette, (0, 0))

        if self.noise_alpha > 0:
            self._draw_noise(screen)

    # ---------- layout ----------

    def _recompute_layout(self):
        self.w, self.h = self.manager.screen.get_size()
        self._is_portrait = self.h > self.w

        self._pad = int(min(self.w, self.h) * self.map_margin_scale)
        self._header_h = max(84, int(self.h * 0.14))
        self._footer_h = max(46, int(self.h * 0.07))

        # portrait-first: big map, optional slim right panel only if wide enough
        usable_top = self._header_h
        usable_h = self.h - self._header_h - self._footer_h

        if (not self._is_portrait) and self.show_event_log and self.w >= 900:
            panel_w = int(self.w * 0.30)
            map_w = self.w - panel_w - 2 * self._pad
            self._map_rect = pygame.Rect(self._pad, usable_top, map_w, usable_h)
            self._panel_rect = pygame.Rect(self._map_rect.right + self._pad, usable_top, panel_w, usable_h)
        else:
            self._map_rect = pygame.Rect(self._pad, usable_top, self.w - 2 * self._pad, usable_h)
            self._panel_rect = pygame.Rect(0, 0, 0, 0)

        # fonts
        base = min(self.w, self.h)
        self._font_header = self.manager.cache.get_font("dejavusansmono", max(18, int(base * 0.050)), bold=True)
        self._font_body = self.manager.cache.get_font("dejavusansmono", max(14, int(base * 0.028)), bold=False)
        self._font_small = self.manager.cache.get_font("dejavusansmono", max(12, int(base * 0.020)), bold=False)

        # trail surface for map only
        self._trail_surface = pygame.Surface((max(1, self._map_rect.width), max(1, self._map_rect.height)), pygame.SRCALPHA)

    def _build_overlays(self):
        self._overlay = None
        self._vignette = None

    def _build_vignette(self, w: int, h: int, strength: float):
        strength = max(0.0, min(1.0, float(strength)))
        if strength <= 0.0:
            return None
        v = pygame.Surface((w, h), pygame.SRCALPHA)
        layers = 70
        max_a = int(200 * strength)
        for i in range(layers):
            a = int(max_a * (i / layers) ** 1.8)
            pygame.draw.rect(v, (0, 0, 0, a), pygame.Rect(i, i, w - 2 * i, h - 2 * i), 1)
        return v

    # ---------- simulation ----------

    def _init_drones(self):
        self._drones = []
        for i in range(self.drone_count):
            x = self._rng.random() * 0.95 + 0.025
            y = self._rng.random() * 0.80 + 0.05
            ang = self._rng.uniform(0, math.tau)
            sp = self._rng.uniform(0.06, 0.12)
            self._drones.append(
                Drone(
                    id=1000 + i,
                    x=x,
                    y=y,
                    vx=math.cos(ang) * sp,
                    vy=math.sin(ang) * sp,
                    state="PATROL",
                    battery=self._rng.uniform(0.45, 1.0),
                    phase=self._rng.uniform(0, math.tau),
                    target_x=self._rng.random(),
                    target_y=self._rng.random(),
                    timer=0.0,
                )
            )

    def _tick_drones(self, dt: float):
        bx, by = self._base

        for d in self._drones:
            d.phase += dt * 1.0
            d.timer -= dt

            if d.state == "OFFLINE":
                # drift a tiny bit, but mostly frozen
                d.vx *= 0.96
                d.vy *= 0.96
                if d.timer <= 0:
                    self._set_state(d, "PATROL")
                continue

            if d.state == "CHARGE":
                # hold at base; when charged, go back out
                d.x += (bx - d.x) * min(1.0, 6.0 * dt)
                d.y += (by - d.y) * min(1.0, 6.0 * dt)
                if d.battery >= 0.98 and d.timer <= 0:
                    self._set_state(d, "PATROL")
                continue

            if d.state == "RETURN":
                # steer toward base
                ax = (bx - d.x)
                ay = (by - d.y)
                dist = math.hypot(ax, ay) + 1e-6
                ax /= dist
                ay /= dist
                steer = 0.22
                d.vx += ax * steer * dt
                d.vy += ay * steer * dt
                # arrived?
                if dist < 0.045:
                    self._set_state(d, "CHARGE", duration=self._rng.uniform(float(self.charge_time_range[0]), float(self.charge_time_range[1])))
                # keep speed reasonable
                self._limit_speed(d, 0.16)
            else:
                # PATROL: slow wander with soft target attraction
                if self._rng.random() < 0.02:
                    d.target_x = self._rng.random()
                    d.target_y = self._rng.random()

                tx = d.target_x - d.x
                ty = d.target_y - d.y
                dist = math.hypot(tx, ty) + 1e-6
                tx /= dist
                ty /= dist

                wander = 0.09
                d.vx += tx * wander * dt
                d.vy += ty * wander * dt

                # tiny sinusoidal drift (makes it look like autopilots)
                d.vx += 0.02 * math.sin(self._t * 0.7 + d.phase) * dt
                d.vy += 0.02 * math.cos(self._t * 0.6 + d.phase) * dt

                self._limit_speed(d, 0.12)

            # integrate position
            d.x += d.vx * dt
            d.y += d.vy * dt

            # bounce off edges
            if d.x < 0.02 or d.x > 0.98:
                d.vx *= -0.9
                d.x = max(0.02, min(0.98, d.x))
            if d.y < 0.03 or d.y > 0.98:
                d.vy *= -0.9
                d.y = max(0.03, min(0.98, d.y))

    def _limit_speed(self, d: Drone, vmax: float):
        sp = math.hypot(d.vx, d.vy)
        if sp > vmax:
            s = vmax / max(1e-6, sp)
            d.vx *= s
            d.vy *= s

    def _set_state(self, d: Drone, state: str, duration: float = 0.0):
        if d.state == state:
            return
        d.state = state

        if state == "RETURN":
            self._push_event("INFO", f"DRN-{d.id} return-to-base")
        elif state == "CHARGE":
            d.timer = duration
            self._push_event("INFO", f"DRN-{d.id} docking for charge")
        elif state == "OFFLINE":
            d.timer = duration if duration > 0 else self._rng.uniform(1.5, 3.0)
            self._push_event("WARN", f"DRN-{d.id} telemetry lost")
        elif state == "PATROL":
            self._push_event("INFO", f"DRN-{d.id} patrol resumed")

    def _push_event(self, kind: str, text: str):
        ttl = 9.0 if kind == "INFO" else 12.0
        self._events.append(EventMsg(t_end=self._t + ttl, text=text, kind=kind))

    # ---------- drawing ----------

    def _draw_header(self, screen: pygame.Surface):
        band = pygame.Surface((self.w, self._header_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, 0))

        t1 = self._font_header.render(self.title, True, self.accent_rgb)
        screen.blit(t1, (self._pad, int(self._header_h * 0.18)))

        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        line = f"{self.sector_name}   |   UTC {ts}"
        t2 = self._font_small.render(line, True, self._dim)
        screen.blit(t2, (self._pad, int(self._header_h * 0.18) + t1.get_height() + 6))

        # fleet summary on right
        states = {"PATROL": 0, "RETURN": 0, "CHARGE": 0, "OFFLINE": 0}
        for d in self._drones:
            states[d.state] = states.get(d.state, 0) + 1
        s = f"P {states['PATROL']}  R {states['RETURN']}  C {states['CHARGE']}  X {states['OFFLINE']}"
        r = self._font_small.render(s, True, self._dim)
        screen.blit(r, (self.w - self._pad - r.get_width(), int(self._header_h * 0.18)))

        pygame.draw.line(screen, self._dim, (self._pad, self._header_h - 2), (self.w - self._pad, self._header_h - 2), 2)

    def _draw_footer(self, screen: pygame.Surface):
        y0 = self.h - self._footer_h
        band = pygame.Surface((self.w, self._footer_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, y0))

        hint = "SPACE: recall patrol units   |   turn knob: change modes"
        s = self._font_small.render(hint, True, self._dim)
        screen.blit(s, (self._pad, y0 + (self._footer_h - s.get_height()) // 2))

    def _draw_map(self, screen: pygame.Surface):
        r = self._map_rect

        # frame
        pygame.draw.rect(screen, (0, 0, 0), r)
        pygame.draw.rect(screen, (*self.accent_rgb, 150), r, 2)

        # draw faint grid in map
        step = max(40, int(min(r.width, r.height) * 0.14))
        for x in range(r.left, r.right, step):
            pygame.draw.line(screen, (*self.accent_rgb, 35), (x, r.top), (x, r.bottom), 1)
        for y in range(r.top, r.bottom, step):
            pygame.draw.line(screen, (*self.accent_rgb, 35), (r.left, y), (r.right, y), 1)

        # base station
        bx = r.left + int(self._base[0] * r.width)
        by = r.top + int(self._base[1] * r.height)
        pygame.draw.circle(screen, self.accent_rgb, (bx, by), 10, 2)
        pygame.draw.circle(screen, self.accent_rgb, (bx, by), 3, 0)
        lab = self._font_small.render("BASE", True, self._dim)
        screen.blit(lab, (bx - lab.get_width() // 2, by + 12))

        # trails on separate surface (map-local)
        if self._trail_surface is not None:
            # draw new trail dots
            for d in self._drones:
                x = int(d.x * r.width)
                y = int(d.y * r.height)
                a = 70 if d.state == "PATROL" else 95
                col = (*self.accent_rgb, a)
                pygame.draw.circle(self._trail_surface, col, (x, y), 1)

            screen.blit(self._trail_surface, r.topleft)

        # draw drones
        for d in self._drones:
            x = r.left + int(d.x * r.width)
            y = r.top + int(d.y * r.height)

            if d.state == "OFFLINE":
                col = (200, 120, 120)
                a = 160
            elif d.state == "RETURN":
                col = (255, 210, 140)
                a = 220
            elif d.state == "CHARGE":
                col = (180, 180, 180)
                a = 200
            else:
                col = self.accent_rgb
                a = 220

            # icon: small triangle facing velocity
            ang = math.atan2(d.vy, d.vx) if (abs(d.vx) + abs(d.vy)) > 1e-6 else 0.0
            size = 7
            p1 = (x + int(math.cos(ang) * size), y + int(math.sin(ang) * size))
            p2 = (x + int(math.cos(ang + 2.5) * size), y + int(math.sin(ang + 2.5) * size))
            p3 = (x + int(math.cos(ang - 2.5) * size), y + int(math.sin(ang - 2.5) * size))
            pygame.draw.polygon(screen, (*col, a), [p1, p2, p3])

            # battery bar
            bw = 26
            bh = 5
            bx0 = x - bw // 2
            by0 = y + 10
            pygame.draw.rect(screen, (*self.accent_rgb, 90), pygame.Rect(bx0, by0, bw, bh), 1)
            fill = int(bw * max(0.0, min(1.0, d.battery)))
            pygame.draw.rect(screen, (*self.accent_rgb, 140), pygame.Rect(bx0, by0, fill, bh))

        # optional event panel if present (landscape wide)
        if self._panel_rect.width > 10:
            self._draw_panel(screen)

    def _draw_panel(self, screen: pygame.Surface):
        p = self._panel_rect
        bg = pygame.Surface((p.width, p.height), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 190))
        pygame.draw.rect(bg, (*self.accent_rgb, 160), bg.get_rect(), 2)
        screen.blit(bg, p.topleft)

        x = p.left + 16
        y = p.top + 14
        hdr = self._font_body.render("EVENT LOG", True, self.accent_rgb)
        screen.blit(hdr, (x, y))
        y += hdr.get_height() + 10

        for e in self._events[::-1][:16]:
            col = self._dim if e.kind == "INFO" else (255, 200, 140) if e.kind == "WARN" else (255, 140, 140)
            s = self._font_small.render(f"[{e.kind}] {e.text}", True, col)
            screen.blit(s, (x, y))
            y += s.get_height() + 6

    def _draw_noise(self, screen: pygame.Surface):
        # cheap speckle
        n = max(160, (self.w * self.h) // 9000)
        s = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        for _ in range(n):
            x = self._rng.randrange(0, self.w)
            y = self._rng.randrange(0, self.h)
            a = self._rng.randrange(0, self.noise_alpha + 1)
            s.set_at((x, y), (255, 255, 255, a))
        screen.blit(s, (0, 0))

    # ---------- helpers ----------

    def _reseed(self):
        if self.seed is None:
            self.seed = random.randrange(1, 2**31 - 1)
        self._rng.seed(int(self.seed))

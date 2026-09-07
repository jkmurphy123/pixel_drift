# space_elevator_traffic_control_mode.py

import math
import random
from dataclasses import dataclass
from datetime import datetime

import pygame


@dataclass
class Car:
    car_id: str
    y: float          # 0..1 along tether (0 = Earth, 1 = Orbit)
    v: float          # signed speed in units/sec (fraction of tether per sec)
    state: str        # "ASCEND" / "DESCEND" / "DWELL"
    dwell_t: float    # remaining dwell seconds
    cargo: str
    eta_s: float      # derived


@dataclass
class LogLine:
    t_end: float
    kind: str   # INFO/WARN/ALERT
    text: str


class SpaceElevatorTrafficControlMode:
    """
    Space Elevator Traffic Control
    - Portrait-friendly tether visualization with moving elevator cars
    - Docking dwell at Earth Anchor and Orbital Hub
    - Queue rate simulates scheduled departures
    - Occasional weather/load alerts

    Config (optional):
      - title (str)
      - site_name (str)
      - accent_rgb ([r,g,b])
      - seed (int)
      - refresh_hz (float)
      - portrait_layout (bool)
      - car_count (int)
      - car_speed_range ([min,max]) in tether fraction per second
      - dwell_time_range ([min,max]) seconds
      - queue_rate_per_min (float)
      - weather_alert_probability_per_min (float)
      - scanline_alpha (int)
      - noise_alpha (int)
      - vignette_strength (float)
      - show_log (bool)
    """

    def __init__(self, config: dict):
        self.title = str(config.get("title", "SPACE ELEVATOR TRAFFIC CONTROL"))
        self.site_name = str(config.get("site_name", "SITE: UNKNOWN"))
        self.accent_rgb = tuple(config.get("accent_rgb", [170, 255, 230]))
        self.seed = config.get("seed", None)
        self.refresh_hz = float(config.get("refresh_hz", 60.0))

        self.portrait_layout = bool(config.get("portrait_layout", True))

        self.car_count = int(config.get("car_count", 5))
        self.car_count = max(1, min(10, self.car_count))

        self.car_speed_range = config.get("car_speed_range", [0.03, 0.10])
        self.dwell_time_range = config.get("dwell_time_range", [2.0, 6.0])

        self.queue_rate_per_min = float(config.get("queue_rate_per_min", 1.0))
        self.weather_alert_probability_per_min = float(config.get("weather_alert_probability_per_min", 0.5))

        self.scanline_alpha = int(config.get("scanline_alpha", 10))
        self.noise_alpha = int(config.get("noise_alpha", 10))
        self.vignette_strength = float(config.get("vignette_strength", 0.30))

        self.show_log = bool(config.get("show_log", True))

        # runtime
        self.manager = None
        self.w = 0
        self.h = 0
        self._t = 0.0
        self._rng = random.Random()

        # layout
        self._pad = 0
        self._header_h = 0
        self._footer_h = 0

        self._content_rect = pygame.Rect(0, 0, 0, 0)
        self._tether_rect = pygame.Rect(0, 0, 0, 0)
        self._side_rect = pygame.Rect(0, 0, 0, 0)
        self._log_rect = pygame.Rect(0, 0, 0, 0)
        self._stats_rect = pygame.Rect(0, 0, 0, 0)

        # fonts
        self._font_header = None
        self._font_body = None
        self._font_small = None
        self._font_tiny = None

        # state
        self._cars: list[Car] = []
        self._logs: list[LogLine] = []
        self._next_depart_t = 0.0
        self._queue = 0

        # environment / alerts
        self._wind_mps = 18.0
        self._load_pct = 42.0
        self._alert_banner = None
        self._alert_end_t = 0.0

        # overlays
        self._overlay = None
        self._vignette = None

        self._cargo_types = [
            "CARGO: SUPPLIES", "CARGO: CREW", "CARGO: ORE", "CARGO: RESEARCH",
            "CARGO: MEDICAL", "CARGO: SAT PARTS", "CARGO: CRYOPODS"
        ]

    # ---------- lifecycle ----------

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._recompute_layout()
        self._build_overlays()

        self._cars = []
        for i in range(self.car_count):
            # stagger initial positions
            y = (i + 1) / (self.car_count + 1)
            v = self._rng.uniform(float(self.car_speed_range[0]), float(self.car_speed_range[1]))
            state = "ASCEND" if self._rng.random() < 0.5 else "DESCEND"
            v = v if state == "ASCEND" else -v
            self._cars.append(self._make_car(i, y=y, v=v, state=state))

        self._queue = self._rng.randint(0, 4)
        self._schedule_departure()

        self._push_log("INFO", "traffic control online")
        self._push_log("INFO", f"tether lock: nominal | {self.site_name}")
        self._push_log("INFO", "orbital hub: receiving windows open")

    def exit(self):
        self.manager = None
        self._cars = []
        self._logs = []
        self._overlay = None
        self._vignette = None

    def handle_event(self, event):
        # SPACE: inject alert
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self._trigger_alert(force=True)

    def update(self, dt: float):
        self._t += dt

        # resize/hotplug
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            self._build_overlays()

        # expire logs
        self._logs = [l for l in self._logs if l.t_end > self._t][-14:]

        # environment drift
        self._wind_mps += dt * self._rng.uniform(-0.7, 0.7)
        self._load_pct += dt * self._rng.uniform(-1.0, 1.0)
        self._wind_mps = max(0.0, min(70.0, self._wind_mps))
        self._load_pct = max(0.0, min(100.0, self._load_pct))

        # random alert
        p = max(0.0, self.weather_alert_probability_per_min) / 60.0
        if self._rng.random() < p * dt:
            self._trigger_alert(force=False)

        if self._alert_banner and self._t >= self._alert_end_t:
            self._alert_banner = None

        # queue arrivals
        q_rate = max(0.0, self.queue_rate_per_min) / 60.0
        if self._rng.random() < q_rate * dt:
            self._queue += 1
            if self._rng.random() < 0.35:
                self._push_log("INFO", f"schedule update: +1 departure slot (queue={self._queue})")

        # departures: if a car is dwelling at Earth and queue > 0, launch it
        if self._t >= self._next_depart_t:
            launched = self._launch_from_earth()
            self._schedule_departure()
            if launched:
                self._queue = max(0, self._queue - 1)

        # update cars
        for c in self._cars:
            self._tick_car(c, dt)

    def render(self, screen: pygame.Surface):
        screen.fill((0, 0, 0))
        self._draw_header(screen)
        self._draw_tether(screen)
        self._draw_side(screen)
        self._draw_footer(screen)

        if self._overlay is not None:
            screen.blit(self._overlay, (0, 0))
        if self._vignette is not None:
            screen.blit(self._vignette, (0, 0))
        if self.noise_alpha > 0:
            self._draw_noise(screen)

    # ---------- car logic ----------

    def _make_car(self, idx: int, y: float, v: float, state: str) -> Car:
        car_id = f"CAR-{idx+1:02d}"
        cargo = self._rng.choice(self._cargo_types)
        return Car(car_id=car_id, y=y, v=v, state=state, dwell_t=0.0, cargo=cargo, eta_s=0.0)

    def _tick_car(self, c: Car, dt: float):
        if c.state == "DWELL":
            c.dwell_t -= dt
            if c.dwell_t <= 0:
                # leave dock in opposite direction
                if c.y <= 0.001:
                    c.state = "ASCEND"
                    c.v = abs(self._rng.uniform(float(self.car_speed_range[0]), float(self.car_speed_range[1])))
                    self._push_log("INFO", f"{c.car_id} depart: EARTH -> ORBIT ({c.cargo})")
                elif c.y >= 0.999:
                    c.state = "DESCEND"
                    c.v = -abs(self._rng.uniform(float(self.car_speed_range[0]), float(self.car_speed_range[1])))
                    self._push_log("INFO", f"{c.car_id} depart: ORBIT -> EARTH ({c.cargo})")
            return

        # speed modifiers from wind/load (purely for vibe)
        wind_factor = 1.0 - min(0.35, self._wind_mps / 200.0)
        load_factor = 1.0 - min(0.25, self._load_pct / 500.0)
        mod = max(0.55, wind_factor * load_factor)

        c.y += c.v * dt * mod

        # docking
        if c.y <= 0.0:
            c.y = 0.0
            c.state = "DWELL"
            c.dwell_t = self._rng.uniform(float(self.dwell_time_range[0]), float(self.dwell_time_range[1]))
            c.cargo = self._rng.choice(self._cargo_types)
            self._push_log("INFO", f"{c.car_id} dock: EARTH ANCHOR (dwell {c.dwell_t:0.1f}s)")
        elif c.y >= 1.0:
            c.y = 1.0
            c.state = "DWELL"
            c.dwell_t = self._rng.uniform(float(self.dwell_time_range[0]), float(self.dwell_time_range[1]))
            c.cargo = self._rng.choice(self._cargo_types)
            self._push_log("INFO", f"{c.car_id} dock: ORBITAL HUB (dwell {c.dwell_t:0.1f}s)")

        # ETA
        if c.state == "ASCEND":
            rem = max(0.0, 1.0 - c.y)
            c.eta_s = rem / max(1e-6, abs(c.v) * mod)
        elif c.state == "DESCEND":
            rem = max(0.0, c.y)
            c.eta_s = rem / max(1e-6, abs(c.v) * mod)
        else:
            c.eta_s = c.dwell_t

    def _launch_from_earth(self) -> bool:
        if self._queue <= 0:
            return False
        # find a car currently dwelling at Earth
        earth_dwellers = [c for c in self._cars if c.state == "DWELL" and c.y <= 0.001]
        if not earth_dwellers:
            return False
        c = self._rng.choice(earth_dwellers)
        c.dwell_t = 0.0  # will flip next tick
        self._push_log("INFO", f"dispatch: {c.car_id} queued for ascent (queue={self._queue})")
        return True

    # ---------- alerts/logs ----------

    def _schedule_departure(self):
        # departures are jittery, faster if queue is high
        base = 8.0
        if self._queue >= 4:
            base = 4.8
        self._next_depart_t = self._t + self._rng.uniform(base, base + 5.0)

    def _trigger_alert(self, force: bool):
        if not force and self._alert_banner is not None:
            return

        if self._wind_mps > 42 or force:
            msg = "WIND SHEAR WARNING: THROTTLING CLIMBS"
            kind = "WARN"
        elif self._load_pct > 80:
            msg = "LOAD SHEDDING: PRIORITY CARGO ONLY"
            kind = "WARN"
        else:
            msg = self._rng.choice([
                "MICROMETEOR TRACK: MINOR DEVIATION",
                "TETHER OSCILLATION: DAMPENERS ACTIVE",
                "COMM RELAY: SWITCHING TO BACKUP PATH",
                "DOCKING WINDOW SHIFT: ORBITAL HUB",
            ])
            kind = "INFO"

        self._alert_banner = msg
        self._alert_end_t = self._t + self._rng.uniform(3.0, 6.0)
        self._push_log(kind, msg)

    def _push_log(self, kind: str, text: str):
        ttl = 11.0 if kind == "INFO" else 14.0
        self._logs.append(LogLine(t_end=self._t + ttl, kind=kind, text=text))

    # ---------- drawing ----------

    def _recompute_layout(self):
        self.w, self.h = self.manager.screen.get_size()
        base = min(self.w, self.h)

        self._pad = int(base * 0.05)
        self._header_h = max(82, int(self.h * 0.14))
        self._footer_h = max(44, int(self.h * 0.06))

        content = pygame.Rect(
            self._pad,
            self._header_h,
            self.w - 2 * self._pad,
            self.h - self._header_h - self._footer_h
        )

        # Portrait: tether left (big), side panels right (narrow)
        if self.h > self.w or self.portrait_layout:
            tether_w = int(content.width * 0.62)
            self._tether_rect = pygame.Rect(content.left, content.top, tether_w, content.height)
            self._side_rect = pygame.Rect(self._tether_rect.right + 10, content.top, content.width - tether_w - 10, content.height)
        else:
            # Landscape: tether center, side below
            tether_h = int(content.height * 0.70)
            self._tether_rect = pygame.Rect(content.left, content.top, content.width, tether_h)
            self._side_rect = pygame.Rect(content.left, self._tether_rect.bottom + 10, content.width, content.height - tether_h - 10)

        # Side split into stats + log
        sr = self._side_rect
        stats_h = int(sr.height * 0.42)
        self._stats_rect = pygame.Rect(sr.left, sr.top, sr.width, stats_h)
        self._log_rect = pygame.Rect(sr.left, self._stats_rect.bottom + 10, sr.width, sr.height - stats_h - 10)

        self._font_header = self.manager.cache.get_font("dejavusansmono", max(18, int(base * 0.050)), bold=True)
        self._font_body = self.manager.cache.get_font("dejavusansmono", max(14, int(base * 0.028)), bold=False)
        self._font_small = self.manager.cache.get_font("dejavusansmono", max(12, int(base * 0.020)), bold=False)
        self._font_tiny = self.manager.cache.get_font("dejavusansmono", max(10, int(base * 0.017)), bold=False)

    def _build_overlays(self):
        self._overlay = None
        self._vignette = None

    def _build_vignette(self, w: int, h: int, strength: float):
        strength = max(0.0, min(1.0, float(strength)))
        if strength <= 0.0:
            return None
        v = pygame.Surface((w, h), pygame.SRCALPHA)
        layers = 70
        max_a = int(210 * strength)
        for i in range(layers):
            a = int(max_a * (i / layers) ** 1.85)
            pygame.draw.rect(v, (0, 0, 0, a), pygame.Rect(i, i, w - 2 * i, h - 2 * i), 1)
        return v

    def _draw_header(self, screen: pygame.Surface):
        band = pygame.Surface((self.w, self._header_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, 0))

        t1 = self._font_header.render(self.title, True, self.accent_rgb)
        screen.blit(t1, (self._pad, int(self._header_h * 0.20)))

        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        sub = self._font_small.render(f"{self.site_name}   |   UTC {ts}   |   QUEUE {self._queue:02d}", True, (150, 150, 150))
        screen.blit(sub, (self._pad, int(self._header_h * 0.20) + t1.get_height() + 6))

        pygame.draw.line(screen, (150, 150, 150), (self._pad, self._header_h - 2), (self.w - self._pad, self._header_h - 2), 2)

    def _draw_footer(self, screen: pygame.Surface):
        y0 = self.h - self._footer_h
        band = pygame.Surface((self.w, self._footer_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, y0))

        hint = "SPACE: inject advisory   |   turn knob: change modes"
        s = self._font_small.render(hint, True, (150, 150, 150))
        screen.blit(s, (self._pad, y0 + (self._footer_h - s.get_height()) // 2))

    def _draw_panel(self, screen: pygame.Surface, rect: pygame.Rect, label: str):
        pygame.draw.rect(screen, (0, 0, 0), rect)
        pygame.draw.rect(screen, (*self.accent_rgb, 150), rect, 2)
        lab = self._font_tiny.render(label, True, (150, 150, 150))
        screen.blit(lab, (rect.left + 10, rect.top + 8))

    def _draw_tether(self, screen: pygame.Surface):
        r = self._tether_rect
        self._draw_panel(screen, r, "TETHER / CAR TRACKING")

        inner = r.inflate(-18, -30)
        inner.top += 18

        # anchor + hub plates
        earth = pygame.Rect(inner.left, inner.bottom - 44, inner.width, 40)
        hub = pygame.Rect(inner.left, inner.top + 4, inner.width, 40)

        pygame.draw.rect(screen, (*self.accent_rgb, 40), hub, border_radius=10)
        pygame.draw.rect(screen, (*self.accent_rgb, 120), hub, 2, border_radius=10)
        pygame.draw.rect(screen, (*self.accent_rgb, 40), earth, border_radius=10)
        pygame.draw.rect(screen, (*self.accent_rgb, 120), earth, 2, border_radius=10)

        screen.blit(self._font_small.render("ORBITAL HUB", True, (220, 220, 220)), (hub.left + 12, hub.top + 10))
        screen.blit(self._font_small.render("EARTH ANCHOR", True, (220, 220, 220)), (earth.left + 12, earth.top + 10))

        # tether line
        x = inner.centerx
        pygame.draw.line(screen, (*self.accent_rgb, 110), (x, hub.bottom + 8), (x, earth.top - 8), 6)
        pygame.draw.line(screen, (*self.accent_rgb, 40), (x - 20, hub.bottom + 8), (x - 20, earth.top - 8), 2)
        pygame.draw.line(screen, (*self.accent_rgb, 40), (x + 20, hub.bottom + 8), (x + 20, earth.top - 8), 2)

        # tick marks
        for i in range(11):
            y = hub.bottom + 8 + int(i * (earth.top - 8 - (hub.bottom + 8)) / 10)
            pygame.draw.line(screen, (*self.accent_rgb, 35), (x - 36, y), (x + 36, y), 1)

        # cars
        track_top = hub.bottom + 10
        track_bot = earth.top - 10
        track_h = max(1, track_bot - track_top)

        for c in self._cars:
            cy = track_bot - int(c.y * track_h)
            car_w = 110 if inner.width > 260 else 86
            car_h = 22
            car = pygame.Rect(0, 0, car_w, car_h)
            car.center = (x, cy)

            # color by state
            if c.state == "DWELL":
                col = (255, 220, 150)
            elif c.state == "ASCEND":
                col = self.accent_rgb
            else:
                col = (200, 200, 200)

            # glow
            glow = pygame.Surface((car_w + 24, car_h + 18), pygame.SRCALPHA)
            pygame.draw.rect(glow, (*col, 36), glow.get_rect(), border_radius=10)
            screen.blit(glow, (car.left - 12, car.top - 9))

            pygame.draw.rect(screen, (*col, 90), car, border_radius=8)
            pygame.draw.rect(screen, (*col, 190), car, 2, border_radius=8)

            label = f"{c.car_id} {c.state}"
            txt = self._font_tiny.render(label, True, (20, 20, 20) if col != (200, 200, 200) else (0, 0, 0))
            screen.blit(txt, (car.left + 8, car.top + 4))

            eta = self._font_tiny.render(f"ETA {c.eta_s:0.0f}s", True, (150, 150, 150))
            screen.blit(eta, (car.right + 10, car.top + 4))

        # alert banner overlay
        if self._alert_banner:
            banner = pygame.Surface((inner.width, 34), pygame.SRCALPHA)
            banner.fill((0, 0, 0, 180))
            pygame.draw.rect(banner, (*self.accent_rgb, 120), banner.get_rect(), 2, border_radius=10)
            t = self._font_small.render(self._alert_banner, True, (255, 220, 150))
            banner.blit(t, (10, 7))
            screen.blit(banner, (inner.left, inner.top + 58))

    def _draw_side(self, screen: pygame.Surface):
        # STATS
        self._draw_panel(screen, self._stats_rect, "SYSTEM STATUS")
        r = self._stats_rect.inflate(-18, -30)
        r.top += 18

        lh = self._font_small.get_linesize() + 6
        x = r.left + 6
        y = r.top + 10

        def kv(k, v, col=(220, 220, 220)):
            nonlocal y
            ks = self._font_small.render(f"{k:12s}", True, (150, 150, 150))
            vs = self._font_small.render(str(v), True, col)
            screen.blit(ks, (x, y))
            screen.blit(vs, (x + 170, y))
            y += lh

        kv("WIND", f"{self._wind_mps:0.1f} m/s", (255, 220, 150) if self._wind_mps > 42 else (220, 220, 220))
        kv("LOAD", f"{self._load_pct:0.0f} %", (255, 220, 150) if self._load_pct > 80 else (220, 220, 220))
        kv("QUEUE", f"{self._queue:02d} slots", (220, 220, 220))
        kv("NEXT DEP", f"{max(0.0, self._next_depart_t - self._t):0.1f}s", (220, 220, 220))

        # LOG
        if self.show_log:
            self._draw_panel(screen, self._log_rect, "DISPATCH LOG")
            lr = self._log_rect.inflate(-18, -30)
            lr.top += 18

            x2 = lr.left + 6
            y2 = lr.top + 10
            for l in self._logs[::-1][:10]:
                if l.kind == "ALERT":
                    col = (255, 140, 140)
                elif l.kind == "WARN":
                    col = (255, 220, 150)
                else:
                    col = (150, 150, 150)
                s = self._font_tiny.render(f"[{l.kind}] {l.text}", True, col)
                screen.blit(s, (x2, y2))
                y2 += s.get_height() + 5
                if y2 > lr.bottom - 8:
                    break

    def _draw_noise(self, screen: pygame.Surface):
        n = max(160, (self.w * self.h) // 9000)
        s = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        for _ in range(n):
            x = self._rng.randrange(0, self.w)
            y = self._rng.randrange(0, self.h)
            a = self._rng.randrange(0, self.noise_alpha + 1)
            s.set_at((x, y), (255, 255, 255, a))
        screen.blit(s, (0, 0))

    def _reseed(self):
        if self.seed is None:
            self.seed = random.randrange(1, 2**31 - 1)
        self._rng.seed(int(self.seed))

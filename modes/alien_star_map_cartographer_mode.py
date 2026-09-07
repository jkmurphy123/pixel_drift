# modes/alien_star_map_cartographer_mode.py

import math
import random
from dataclasses import dataclass
from datetime import datetime
from typing import List, Tuple, Optional

import pygame


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _mix(a: Tuple[int, int, int], b: Tuple[int, int, int], t: float) -> Tuple[int, int, int]:
    t = _clamp(t, 0.0, 1.0)
    return (int(a[0] + (b[0] - a[0]) * t),
            int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


@dataclass
class Star:
    # world coords in a large plane, plus depth 0..1 (0=near,1=far)
    x: float
    y: float
    z: float
    mag: float       # brightness 0..1
    hue: float       # 0..1 color drift
    tw: float        # twinkle phase


@dataclass
class Constellation:
    indices: List[int]
    name: str


@dataclass
class Stamp:
    t_end: float
    text: str
    pos: Tuple[int, int]
    kind: str  # "LOCK", "NOTE", "WARN"


class AlienStarMapCartographerMode:
    """
    Alien Star Map Cartographer
    Procedural star map with:
      - Parallax star layers
      - Constellation solving lines
      - Sector rings + grid
      - Random annotation stamps

    Optional config:
      - title, subtitle
      - accent_rgb [r,g,b]
      - seed
      - refresh_hz

      - star_count (int)
      - near_star_frac (float 0..1) proportion of "near" (brighter, larger)
      - constellation_count (int)
      - constellation_links (int) links per constellation

      - drift_speed (float) world drift speed
      - parallax_strength (float)
      - twinkle_strength (float)
      - zoom_pulse_strength (float) subtle breathing zoom

      - grid_alpha (int)
      - ring_alpha (int)
      - label_density (float 0..1)
      - stamp_probability_per_min (float)

      - scanline_alpha (int)
      - noise_alpha (int)
      - vignette_strength (float 0..1)
    """

    def __init__(self, config: dict):
        self.title = str(config.get("title", "ALIEN STAR MAP CARTOGRAPHER"))
        self.subtitle = str(config.get("subtitle", "ARCHIVE CHART / AUTOSOLVE ENABLED"))

        self.accent_rgb = tuple(config.get("accent_rgb", [180, 255, 235]))
        self.seed = config.get("seed", None)
        self.refresh_hz = float(config.get("refresh_hz", 60.0))

        self.star_count = int(config.get("star_count", 850))
        self.star_count = max(200, min(2500, self.star_count))
        self.near_star_frac = float(config.get("near_star_frac", 0.18))
        self.near_star_frac = _clamp(self.near_star_frac, 0.02, 0.60)

        self.constellation_count = int(config.get("constellation_count", 10))
        self.constellation_count = max(3, min(24, self.constellation_count))
        self.constellation_links = int(config.get("constellation_links", 6))
        self.constellation_links = max(3, min(10, self.constellation_links))

        self.drift_speed = float(config.get("drift_speed", 0.020))
        self.parallax_strength = float(config.get("parallax_strength", 0.85))
        self.twinkle_strength = float(config.get("twinkle_strength", 0.55))
        self.zoom_pulse_strength = float(config.get("zoom_pulse_strength", 0.05))

        self.grid_alpha = int(config.get("grid_alpha", 28))
        self.ring_alpha = int(config.get("ring_alpha", 40))
        self.label_density = float(config.get("label_density", 0.35))
        self.label_density = _clamp(self.label_density, 0.0, 1.0)

        self.stamp_probability_per_min = float(config.get("stamp_probability_per_min", 0.45))

        self.scanline_alpha = int(config.get("scanline_alpha", 10))
        self.noise_alpha = int(config.get("noise_alpha", 8))
        self.vignette_strength = float(config.get("vignette_strength", 0.28))

        # runtime
        self.manager = None
        self.w = 0
        self.h = 0
        self._t = 0.0
        self._rng = random.Random()

        # fonts
        self._font_title = None
        self._font_small = None
        self._font_tiny = None

        # generated content
        self._stars: List[Star] = []
        self._constellations: List[Constellation] = []
        self._stamps: List[Stamp] = []

        # overlay surfaces
        self._overlay = None
        self._vignette = None

        # map drift / solve cursor
        self._ox = 0.0
        self._oy = 0.0
        self._solve_phase = 0.0

        self._glyphs = "⌁⌂⌄⌇⌑⌒⍜⍟⎔⎚⎋⏣⏧␀␛▣▥▧▨◬◭◮◯◇◆◈◉"
        self._syll = ["ka", "shi", "tor", "ven", "ul", "dra", "mi", "za", "qo", "rei", "han", "tek", "sa", "ly", "no"]

    # ---------- lifecycle ----------

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._recompute_layout()
        self._build_overlays()
        self._generate_catalog()

        self._ox = self._rng.uniform(-2000, 2000)
        self._oy = self._rng.uniform(-2000, 2000)
        self._solve_phase = self._rng.random() * 10.0

        self._stamps = []
        self._push_stamp("NOTE", "CHART ONLINE", (self.w // 2, int(self.h * 0.16)), ttl=2.4)

    def exit(self):
        self.manager = None
        self._stars = []
        self._constellations = []
        self._stamps = []
        self._overlay = None
        self._vignette = None

    def handle_event(self, event):
        # SPACE: force a stamp + reshuffle constellations
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self._generate_constellations()
            self._push_stamp("LOCK", "RE-SOLVE TRIGGERED", (self.w // 2, int(self.h * 0.20)), ttl=2.5)

    def update(self, dt: float):
        self._t += dt

        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            self._build_overlays()

        # drift the world
        sp = self.drift_speed * 1800.0  # world units/sec
        self._ox += dt * sp * math.cos(self._t * 0.10)
        self._oy += dt * sp * math.sin(self._t * 0.13)

        # constellation "solve" sweep
        self._solve_phase += dt * 0.45

        # stamp probability
        p = max(0.0, self.stamp_probability_per_min) / 60.0
        if self._rng.random() < p * dt:
            self._random_stamp()

        # expire stamps
        self._stamps = [s for s in self._stamps if s.t_end > self._t][-8:]

    def render(self, screen: pygame.Surface):
        screen.fill((0, 0, 0))

        # subtle zoom breathe
        zoom = 1.0 + self.zoom_pulse_strength * 0.5 * math.sin(self._t * 0.35)
        cx, cy = self.w * 0.5, self.h * 0.5

        # draw grid/rings first (under stars)
        self._draw_sector_grid(screen, zoom, cx, cy)
        self._draw_sector_rings(screen, zoom, cx, cy)

        # draw stars & constellations
        self._draw_stars(screen, zoom, cx, cy)
        self._draw_constellations(screen, zoom, cx, cy)

        # UI labels / stamps last
        self._draw_hud(screen)
        self._draw_stamps(screen)

        # overlays
        if self._overlay is not None:
            screen.blit(self._overlay, (0, 0))
        if self._vignette is not None:
            screen.blit(self._vignette, (0, 0))
        if self.noise_alpha > 0:
            self._draw_noise(screen)

    # ---------- generation ----------

    def _generate_catalog(self):
        # Large world plane; stars distributed in a disk-ish field
        self._stars = []
        world_radius = 5200.0

        for _ in range(self.star_count):
            # polar distribution with slight center bias
            ang = self._rng.random() * math.tau
            r = world_radius * (self._rng.random() ** 0.72)
            x = math.cos(ang) * r + self._rng.uniform(-250, 250)
            y = math.sin(ang) * r + self._rng.uniform(-250, 250)

            # depth: near stars are rarer
            if self._rng.random() < self.near_star_frac:
                z = self._rng.uniform(0.0, 0.35)
                mag = self._rng.uniform(0.65, 1.0)
            else:
                z = self._rng.uniform(0.35, 1.0)
                mag = self._rng.uniform(0.12, 0.70)

            hue = self._rng.random()
            tw = self._rng.random() * math.tau

            self._stars.append(Star(x=x, y=y, z=z, mag=mag, hue=hue, tw=tw))

        self._generate_constellations()

    def _generate_constellations(self):
        # choose constellations from the brightest near-ish stars
        candidates = sorted(range(len(self._stars)),
                            key=lambda i: (self._stars[i].z, -self._stars[i].mag))[: max(60, self.constellation_count * 10)]
        self._constellations = []
        self._rng.shuffle(candidates)

        for k in range(self.constellation_count):
            if len(candidates) < self.constellation_links:
                break
            group = candidates[: self.constellation_links]
            candidates = candidates[self.constellation_links :]
            name = self._alien_name()
            self._constellations.append(Constellation(indices=group, name=name))

    def _alien_name(self) -> str:
        # mix syllables with a glyph tail
        parts = [self._rng.choice(self._syll) for _ in range(self._rng.randint(2, 4))]
        base = "-".join(parts) if self._rng.random() < 0.35 else "".join(parts)
        tail = "".join(self._rng.choice(self._glyphs) for _ in range(self._rng.randint(1, 3)))
        return (base[:14] + " " + tail).upper()

    # ---------- drawing helpers ----------

    def _world_to_screen(self, x: float, y: float, z: float, zoom: float, cx: float, cy: float) -> Tuple[float, float]:
        # Parallax: nearer stars move more with drift.
        par = 1.0 + self.parallax_strength * (1.0 - z)  # 1..(1+parallax)
        wx = (x - self._ox * par)
        wy = (y - self._oy * par)

        # scale to screen
        scale = (min(self.w, self.h) / 5200.0) * zoom
        sx = cx + wx * scale
        sy = cy + wy * scale
        return sx, sy

    def _draw_stars(self, screen: pygame.Surface, zoom: float, cx: float, cy: float):
        base = min(self.w, self.h)
        # a few colors around accent: cool whites + mint + faint warm
        cool = (225, 235, 255)
        mint = self.accent_rgb
        warm = (255, 230, 200)

        for s in self._stars:
            sx, sy = self._world_to_screen(s.x, s.y, s.z, zoom, cx, cy)
            if sx < -20 or sy < -20 or sx > self.w + 20 or sy > self.h + 20:
                continue

            # twinkle
            tw = 0.5 + 0.5 * math.sin(self._t * (1.0 + 2.0 * (1.0 - s.z)) + s.tw)
            tw = 1.0 - self.twinkle_strength + self.twinkle_strength * tw

            # size by magnitude and depth
            r = (0.6 + 2.2 * s.mag) * (1.2 - 0.9 * s.z)
            r *= (1.0 + 0.10 * tw)
            r = _clamp(r, 0.6, 3.8)

            # brightness
            a = int(55 + 200 * (s.mag ** 1.15) * tw)
            a = int(_clamp(a, 25, 255))

            # hue blend
            c = _mix(cool, mint, s.hue * 0.65)
            if s.hue > 0.78:
                c = _mix(c, warm, (s.hue - 0.78) / 0.22)

            # glow for near bright stars
            if s.z < 0.40 and s.mag > 0.72:
                glow_r = int(r * 3.0)
                glow = pygame.Surface((glow_r * 2 + 2, glow_r * 2 + 2), pygame.SRCALPHA)
                pygame.draw.circle(glow, (*c, int(a * 0.16)), (glow_r + 1, glow_r + 1), glow_r)
                screen.blit(glow, (sx - glow_r - 1, sy - glow_r - 1))

            pygame.draw.circle(screen, (*c, a), (int(sx), int(sy)), int(r))

    def _draw_constellations(self, screen: pygame.Surface, zoom: float, cx: float, cy: float):
        # sweeping "solve" cursor from top to bottom
        sweep = (math.sin(self._solve_phase) * 0.5 + 0.5)  # 0..1
        sweep_y = self.h * (0.18 + 0.64 * sweep)

        for cons in self._constellations:
            pts = []
            for idx in cons.indices:
                st = self._stars[idx]
                sx, sy = self._world_to_screen(st.x, st.y, st.z, zoom, cx, cy)
                pts.append((sx, sy, st.z, st.mag))

            # connect points in a simple nearest-neighbor chain
            # sort by x to stabilize the line shape
            pts2 = sorted(pts, key=lambda p: p[0])

            # reveal factor based on sweep passing over y
            reveal = 0.0
            # use the average y to decide when it reveals
            avg_y = sum(p[1] for p in pts2) / max(1, len(pts2))
            reveal = _clamp((sweep_y - avg_y) / (self.h * 0.20), 0.0, 1.0)

            if reveal <= 0.01:
                continue

            col = self.accent_rgb
            a = int(25 + 110 * reveal)
            a2 = int(10 + 60 * reveal)

            # thin line chain
            for i in range(len(pts2) - 1):
                x1, y1, z1, m1 = pts2[i]
                x2, y2, z2, m2 = pts2[i + 1]
                if (x1 < -40 and x2 < -40) or (x1 > self.w + 40 and x2 > self.w + 40):
                    continue
                pygame.draw.line(screen, (*col, a), (x1, y1), (x2, y2), 2)
                pygame.draw.line(screen, (*col, a2), (x1, y1), (x2, y2), 1)

            # label near centroid (rare, density controlled)
            if self._rng.random() < self.label_density * 0.10:
                cx2 = sum(p[0] for p in pts2) / len(pts2)
                cy2 = sum(p[1] for p in pts2) / len(pts2)
                tag = self._font_tiny.render(cons.name, True, (140, 140, 140))
                screen.blit(tag, (int(cx2) + 8, int(cy2) - 8))

    def _draw_sector_grid(self, screen: pygame.Surface, zoom: float, cx: float, cy: float):
        a = int(_clamp(self.grid_alpha, 0, 255))
        if a <= 0:
            return

        # subtle polar grid, not a full square grid
        col = (*self.accent_rgb, a)

        # radial lines
        rays = 14
        rmax = int(min(self.w, self.h) * 0.55)
        for i in range(rays):
            ang = (i / rays) * math.tau + 0.15 * math.sin(self._t * 0.07)
            x2 = cx + math.cos(ang) * rmax
            y2 = cy + math.sin(ang) * rmax
            pygame.draw.line(screen, col, (cx, cy), (x2, y2), 1)

        # faint crosshair
        pygame.draw.line(screen, (*self.accent_rgb, int(a * 0.7)), (0, cy), (self.w, cy), 1)
        pygame.draw.line(screen, (*self.accent_rgb, int(a * 0.7)), (cx, 0), (cx, self.h), 1)

    def _draw_sector_rings(self, screen: pygame.Surface, zoom: float, cx: float, cy: float):
        a = int(_clamp(self.ring_alpha, 0, 255))
        if a <= 0:
            return

        col = (*self.accent_rgb, a)
        r0 = int(min(self.w, self.h) * 0.12)
        rmax = int(min(self.w, self.h) * 0.55)
        step = int((rmax - r0) / 5) if rmax > r0 else 50

        for r in range(r0, rmax, max(20, step)):
            pygame.draw.circle(screen, col, (int(cx), int(cy)), r, 1)

        # a “sector gate” arc
        arc_r = int(min(self.w, self.h) * 0.48)
        arc_rect = pygame.Rect(0, 0, arc_r * 2, arc_r * 2)
        arc_rect.center = (int(cx), int(cy))
        start = 0.35 + 0.15 * math.sin(self._t * 0.09)
        end = start + 0.85
        pygame.draw.arc(screen, (*self.accent_rgb, int(a * 1.15)), arc_rect, start, end, 2)

    def _draw_hud(self, screen: pygame.Surface):
        # minimalist top-left readout
        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        # pseudo-coordinates from drift
        qx = int((self._ox * 0.13) % 100000)
        qy = int((self._oy * 0.13) % 100000)
        coord = f"COORD {qx:05d}.{qy:05d}  |  PASS {int(self._solve_phase)%99:02d}  |  {ts}"

        t1 = self._font_small.render(self.title, True, (220, 220, 220))
        t2 = self._font_tiny.render(self.subtitle, True, (150, 150, 150))
        t3 = self._font_tiny.render(coord, True, (120, 120, 120))

        x = int(min(self.w, self.h) * 0.05)
        y = int(min(self.w, self.h) * 0.05)

        screen.blit(t1, (x, y))
        screen.blit(t2, (x, y + t1.get_height() + 4))
        screen.blit(t3, (x, y + t1.get_height() + t2.get_height() + 8))

    def _draw_stamps(self, screen: pygame.Surface):
        # floating center-ish stamps that fade out
        for s in self._stamps:
            # fade
            left = _clamp((s.t_end - self._t) / 2.2, 0.0, 1.0)
            a = int(30 + 170 * left)
            if s.kind == "LOCK":
                col = (255, 220, 150)
            elif s.kind == "WARN":
                col = (255, 160, 160)
            else:
                col = (180, 255, 235)

            text = self._font_small.render(s.text, True, col)
            pad = 10
            rect = text.get_rect()
            rect.center = s.pos
            plate = pygame.Surface((rect.width + pad * 2, rect.height + pad * 2), pygame.SRCALPHA)
            pygame.draw.rect(plate, (0, 0, 0, int(140 * left)), plate.get_rect(), border_radius=12)
            pygame.draw.rect(plate, (*col, int(a * 0.55)), plate.get_rect(), width=2, border_radius=12)
            plate.blit(text, (pad, pad))
            screen.blit(plate, (rect.left - pad, rect.top - pad))

    def _random_stamp(self):
        kind = self._rng.choice(["NOTE", "NOTE", "LOCK", "WARN"])
        if kind == "LOCK":
            txt = f"SOLUTION LOCK: {self._alien_name()}"
        elif kind == "WARN":
            txt = self._rng.choice([
                "INTERFERENCE: GRAV LENS",
                "NOISE SPIKE: ION STORM",
                "TRACK LOSS: REACQUIRE",
                "PARALLAX ERROR: RECALC"
            ])
        else:
            txt = self._rng.choice([
                f"ANNOTATE: {self._alien_name()}",
                "MARKER SET: NAV BEACON",
                "CATALOG UPDATE: OK",
                "PROBABLE ROUTE: STABLE"
            ])

        px = int(self.w * (0.35 + 0.30 * self._rng.random()))
        py = int(self.h * (0.18 + 0.60 * self._rng.random()))
        self._push_stamp(kind, txt, (px, py), ttl=self._rng.uniform(2.2, 4.0))

    def _push_stamp(self, kind: str, text: str, pos: Tuple[int, int], ttl: float = 3.0):
        self._stamps.append(Stamp(t_end=self._t + ttl, text=text, pos=pos, kind=kind))

    # ---------- overlays ----------

    def _build_overlays(self):
        self._overlay = None
        self._vignette = None

    def _build_vignette(self, w: int, h: int, strength: float):
        strength = _clamp(strength, 0.0, 1.0)
        if strength <= 0.0:
            return None
        v = pygame.Surface((w, h), pygame.SRCALPHA)
        layers = 70
        max_a = int(210 * strength)
        for i in range(layers):
            a = int(max_a * (i / layers) ** 1.85)
            pygame.draw.rect(v, (0, 0, 0, a), pygame.Rect(i, i, w - 2 * i, h - 2 * i), 1)
        return v

    def _draw_noise(self, screen: pygame.Surface):
        n = max(160, (self.w * self.h) // 12000)
        s = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        for _ in range(n):
            x = self._rng.randrange(0, self.w)
            y = self._rng.randrange(0, self.h)
            a = self._rng.randrange(0, max(1, self.noise_alpha) + 1)
            s.set_at((x, y), (255, 255, 255, a))
        screen.blit(s, (0, 0))

    # ---------- utils ----------

    def _recompute_layout(self):
        self.w, self.h = self.manager.screen.get_size()
        base = min(self.w, self.h)

        self._font_title = self.manager.cache.get_font("dejavusansmono", max(18, int(base * 0.048)), bold=True)
        self._font_small = self.manager.cache.get_font("dejavusansmono", max(12, int(base * 0.020)), bold=False)
        self._font_tiny = self.manager.cache.get_font("dejavusansmono", max(10, int(base * 0.017)), bold=False)

    def _reseed(self):
        if self.seed is None:
            self.seed = random.randrange(1, 2**31 - 1)
        self._rng.seed(int(self.seed))

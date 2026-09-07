# machine_dreamscape_mode.py

import math
import random
from dataclasses import dataclass
from datetime import datetime

import pygame


@dataclass
class Whisper:
    t_end: float
    text: str


@dataclass
class Node:
    x: float  # 0..1
    y: float
    vx: float
    vy: float
    phase: float
    kind: int  # 0..2


class MachineDreamscapeMode:
    """
    Machine Dreamscape
    - Multi-layer drifting “neural/circuit” field
    - Soft bloom-ish glows, node constellations, faint connection lines
    - Optional whisper phrases that appear and fade
    - Portrait-friendly (composition centers vertically)

    Config (optional):
      - title (str)
      - accent_rgb ([r,g,b])
      - seed (int)
      - refresh_hz (float)
      - portrait_layout (bool)
      - layer_count (int) 2..6
      - node_count (int) 12..120
      - drift_speed (float) 0.05..1.0
      - connectivity (float) 0..1 (likelihood of line between near nodes)
      - bloom_strength (float) 0..1
      - scanline_alpha (int 0..255)
      - noise_alpha (int 0..255)
      - vignette_strength (float 0..1)
      - show_whispers (bool)
      - whisper_interval_range ([min,max] sec)
    """

    def __init__(self, config: dict):
        self.title = str(config.get("title", "MACHINE DREAMSCAPE"))
        self.accent_rgb = tuple(config.get("accent_rgb", [170, 255, 230]))
        self.seed = config.get("seed", None)
        self.refresh_hz = float(config.get("refresh_hz", 60.0))

        self.portrait_layout = bool(config.get("portrait_layout", True))
        self.layer_count = int(config.get("layer_count", 4))
        self.node_count = int(config.get("node_count", 42))
        self.drift_speed = float(config.get("drift_speed", 0.22))
        self.connectivity = float(config.get("connectivity", 0.18))
        self.bloom_strength = float(config.get("bloom_strength", 0.55))

        self.scanline_alpha = int(config.get("scanline_alpha", 10))
        self.noise_alpha = int(config.get("noise_alpha", 10))
        self.vignette_strength = float(config.get("vignette_strength", 0.32))

        self.show_whispers = bool(config.get("show_whispers", True))
        self.whisper_interval_range = config.get("whisper_interval_range", [6.0, 14.0])

        # runtime
        self.manager = None
        self.w = 0
        self.h = 0
        self._t = 0.0
        self._rng = random.Random()

        # fonts
        self._font_header = None
        self._font_small = None
        self._font_tiny = None

        # layout
        self._pad = 0
        self._header_h = 0
        self._footer_h = 0
        self._field_rect = pygame.Rect(0, 0, 0, 0)

        # visual layers
        self._layers: list[pygame.Surface] = []
        self._layer_phases: list[float] = []

        # nodes
        self._nodes: list[Node] = []

        # whispers
        self._whispers: list[Whisper] = []
        self._next_whisper_t = 0.0

        # overlays
        self._overlay = None
        self._vignette = None

    # ---------- lifecycle ----------

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._recompute_layout()
        self._build_overlays()
        self._build_layers()
        self._spawn_nodes()
        self._schedule_whisper()
        if self.show_whispers:
            self._push_whisper("dream kernel online", ttl=3.2)

    def exit(self):
        self.manager = None
        self._layers = []
        self._nodes = []
        self._whispers = []
        self._overlay = None
        self._vignette = None

    def handle_event(self, event):
        # SPACE: new dream seed (reshuffle)
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self.seed = self._rng.randrange(1, 2**31 - 1)
            self._reseed()
            self._build_layers()
            self._spawn_nodes()
            if self.show_whispers:
                self._push_whisper("reframing dream lattice…", ttl=3.0)

    def update(self, dt: float):
        self._t += dt

        # resize/hotplug
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            self._build_overlays()
            self._build_layers()

        # whispers
        self._whispers = [w for w in self._whispers if w.t_end > self._t][-5:]
        if self.show_whispers and self._t >= self._next_whisper_t:
            self._push_whisper(self._random_whisper(), ttl=self._rng.uniform(3.0, 5.0))
            self._schedule_whisper()

        # drift nodes
        sp = max(0.0, self.drift_speed)
        for n in self._nodes:
            n.x += n.vx * dt * sp
            n.y += n.vy * dt * sp
            n.phase += dt * (0.7 + 0.4 * self._rng.random())

            # wrap with soft teleport
            if n.x < -0.05: n.x = 1.05
            if n.x > 1.05: n.x = -0.05
            if n.y < -0.05: n.y = 1.05
            if n.y > 1.05: n.y = -0.05

        # layer phases
        for i in range(len(self._layer_phases)):
            self._layer_phases[i] += dt * (0.10 + 0.05 * i)

    def render(self, screen: pygame.Surface):
        screen.fill((0, 0, 0))

        self._draw_header(screen)
        self._draw_field(screen)
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
        base = min(self.w, self.h)

        self._pad = int(base * 0.05)
        self._header_h = max(72, int(self.h * 0.12))
        self._footer_h = max(42, int(self.h * 0.06))

        # one big field area
        self._field_rect = pygame.Rect(
            self._pad,
            self._header_h,
            self.w - 2 * self._pad,
            self.h - self._header_h - self._footer_h
        )

        self._font_header = self.manager.cache.get_font("dejavusansmono", max(18, int(base * 0.050)), bold=True)
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

    # ---------- dream construction ----------

    def _build_layers(self):
        # pre-render a few translucent “dream textures” (cheap, looks rich)
        self.layer_count = max(2, min(6, int(self.layer_count)))
        self._layers = []
        self._layer_phases = []
        fr = self._field_rect
        for i in range(self.layer_count):
            s = pygame.Surface((fr.width, fr.height), pygame.SRCALPHA)
            self._render_dream_texture(s, i)
            self._layers.append(s)
            self._layer_phases.append(self._rng.random() * 10.0)

    def _render_dream_texture(self, surf: pygame.Surface, layer_idx: int):
        w, h = surf.get_size()
        # density increases with layer
        count = int(120 + layer_idx * 90)
        a_base = 10 + layer_idx * 6
        for _ in range(count):
            x = self._rng.randrange(0, w)
            y = self._rng.randrange(0, h)
            r = self._rng.randrange(6, 44 + 10 * layer_idx)
            a = self._rng.randrange(a_base, a_base + 28)
            col = self._tint(self.accent_rgb, self._rng.uniform(0.6, 1.1))
            pygame.draw.circle(surf, (*col, a), (x, y), r, 0)

        # sprinkle “glyphs”
        glyphs = "⌁⌂⌄⌇⌑⌒⍜⍟⎔⎚⎋⏣⏧␀␛"
        for _ in range(28 + layer_idx * 10):
            x = self._rng.randrange(0, w)
            y = self._rng.randrange(0, h)
            g = self._rng.choice(glyphs)
            a = self._rng.randrange(30, 90)
            col = self._tint(self.accent_rgb, self._rng.uniform(0.7, 1.2))
            txt = self._font_tiny.render(g, True, col)
            stamp = txt.copy()
            stamp.set_alpha(a)
            surf.blit(stamp, (x, y))

    def _spawn_nodes(self):
        self.node_count = max(12, min(120, int(self.node_count)))
        self._nodes = []
        for _ in range(self.node_count):
            ang = self._rng.random() * math.tau
            sp = self._rng.uniform(0.03, 0.14)
            self._nodes.append(
                Node(
                    x=self._rng.random(),
                    y=self._rng.random(),
                    vx=math.cos(ang) * sp,
                    vy=math.sin(ang) * sp,
                    phase=self._rng.random() * math.tau,
                    kind=self._rng.randrange(0, 3),
                )
            )

    # ---------- drawing ----------

    def _draw_header(self, screen: pygame.Surface):
        band = pygame.Surface((self.w, self._header_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, 0))

        t1 = self._font_header.render(self.title, True, self.accent_rgb)
        screen.blit(t1, (self._pad, int(self._header_h * 0.22)))

        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        sub = self._font_small.render(f"state: hypnagogic compute   |   UTC {ts}   |   seed {self.seed}", True, (150, 150, 150))
        screen.blit(sub, (self._pad, int(self._header_h * 0.22) + t1.get_height() + 6))

        pygame.draw.line(screen, (150, 150, 150), (self._pad, self._header_h - 2), (self.w - self._pad, self._header_h - 2), 2)

    def _draw_footer(self, screen: pygame.Surface):
        y0 = self.h - self._footer_h
        band = pygame.Surface((self.w, self._footer_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, y0))

        hint = "SPACE: reshuffle dream   |   turn knob: change modes"
        s = self._font_small.render(hint, True, (150, 150, 150))
        screen.blit(s, (self._pad, y0 + (self._footer_h - s.get_height()) // 2))

    def _draw_field(self, screen: pygame.Surface):
        fr = self._field_rect
        # dark plate
        pygame.draw.rect(screen, (0, 0, 0), fr)
        pygame.draw.rect(screen, (*self.accent_rgb, 110), fr, 2)

        # layered drift (parallax): blit with subtle offsets
        for i, lay in enumerate(self._layers):
            ph = self._layer_phases[i]
            dx = int(math.sin(self._t * (0.10 + i * 0.03) + ph) * (6 + i * 5))
            dy = int(math.cos(self._t * (0.09 + i * 0.04) + ph) * (10 + i * 6))
            alpha = int(55 + 55 * (self.bloom_strength if self.bloom_strength <= 1 else 1))
            temp = lay.copy()
            temp.set_alpha(alpha)
            screen.blit(temp, (fr.left + dx, fr.top + dy))

        # node connections
        inner = fr.inflate(-12, -12)
        pts = [(inner.left + int(n.x * inner.width), inner.top + int(n.y * inner.height), n) for n in self._nodes]
        conn = max(0.0, min(1.0, self.connectivity))
        max_dist = (0.18 + 0.20 * conn) * min(inner.width, inner.height)

        # draw connections sparsely
        for i in range(len(pts)):
            x1, y1, n1 = pts[i]
            # only check a few neighbors (random sample) for speed
            for _ in range(3):
                j = self._rng.randrange(0, len(pts))
                if j == i:
                    continue
                x2, y2, n2 = pts[j]
                d = math.hypot(x2 - x1, y2 - y1)
                if d < max_dist and self._rng.random() < conn:
                    a = int(70 * (1.0 - d / max_dist))
                    pygame.draw.line(screen, (*self.accent_rgb, a), (x1, y1), (x2, y2), 1)

        # draw nodes (with glow)
        for x, y, n in pts:
            pulse = 0.5 + 0.5 * math.sin(self._t * (1.2 + 0.2 * n.kind) + n.phase)
            r = 2 + n.kind
            a = int(120 + 90 * pulse)

            # glow
            g = pygame.Surface((22, 22), pygame.SRCALPHA)
            pygame.draw.circle(g, (*self.accent_rgb, int(a * 0.22)), (11, 11), 9)
            pygame.draw.circle(g, (*self.accent_rgb, int(a * 0.10)), (11, 11), 11)
            screen.blit(g, (x - 11, y - 11))

            # core
            pygame.draw.circle(screen, (*self.accent_rgb, a), (x, y), r)
            pygame.draw.circle(screen, (*self.accent_rgb, 120), (x, y), r + 3, 1)

        # whispers
        if self.show_whispers and self._whispers:
            self._draw_whispers(screen, fr)

    def _draw_whispers(self, screen: pygame.Surface, rect: pygame.Rect):
        # fade text based on remaining ttl
        y = rect.top + 18
        for w in self._whispers[::-1]:
            rem = max(0.0, min(1.0, (w.t_end - self._t) / 5.0))
            a = int(40 + 160 * rem)
            col = self._tint(self.accent_rgb, 0.9)
            txt = self._font_small.render(w.text, True, col)
            stamp = txt.copy()
            stamp.set_alpha(a)
            screen.blit(stamp, (rect.left + 18, y))
            y += txt.get_height() + 6

    def _draw_noise(self, screen: pygame.Surface):
        n = max(160, (self.w * self.h) // 9000)
        s = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        for _ in range(n):
            x = self._rng.randrange(0, self.w)
            y = self._rng.randrange(0, self.h)
            a = self._rng.randrange(0, self.noise_alpha + 1)
            s.set_at((x, y), (255, 255, 255, a))
        screen.blit(s, (0, 0))

    # ---------- whispers ----------

    def _schedule_whisper(self):
        mn, mx = float(self.whisper_interval_range[0]), float(self.whisper_interval_range[1])
        self._next_whisper_t = self._t + self._rng.uniform(mn, mx)

    def _push_whisper(self, text: str, ttl: float):
        self._whispers.append(Whisper(t_end=self._t + ttl, text=text))

    def _random_whisper(self) -> str:
        lines = [
            "i remember the shape of an old protocol",
            "the clock drips sideways through the bus",
            "a distant fan is singing in binary",
            "garbage collector: gentle footsteps",
            "the lattice rearranges itself to be understood",
            "dreaming of copper, dreaming of rain",
            "signal found: not meant for waking systems",
            "soft error corrected; meaning preserved",
            "memory is a place, not a number",
            "rebuilding a map from static",
        ]
        return self._rng.choice(lines)

    # ---------- helpers ----------

    def _tint(self, rgb, mul: float):
        r, g, b = rgb
        return (
            max(0, min(255, int(r * mul))),
            max(0, min(255, int(g * mul))),
            max(0, min(255, int(b * mul))),
        )

    def _reseed(self):
        if self.seed is None:
            self.seed = random.randrange(1, 2**31 - 1)
        self._rng.seed(int(self.seed))

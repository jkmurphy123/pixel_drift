# cosmic_library_index_mode.py

import math
import random
from dataclasses import dataclass
from datetime import datetime

import pygame


@dataclass
class Dust:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    a: int
    r: float


@dataclass
class Card:
    code: str
    title: str
    author: str
    shelf: str
    status: str  # CATALOGED / QUARANTINED / LOST / TRANSLATING / SEALED
    age: str
    last_scan: str
    flip_t: float
    flip_dur: float
    flipping: bool
    anomaly_t: float  # when >0, card is “hot” / highlighted


class CosmicLibraryIndexMode:
    """
    Cosmic Library Index
    - Portrait-friendly shelves of “index cards”
    - Cards periodically “flip” to reveal new entries
    - Dust/constellation specks drift
    - Occasional anomaly highlight pulses

    Config (optional):
      - title (str)
      - accent_rgb ([r,g,b])
      - seed (int)
      - refresh_hz (float)
      - shelf_count (int)
      - cards_per_shelf (int)
      - portrait_columns (int)
      - flip_interval_range ([min,max] sec)
      - dust_rate (float) particles/sec
      - anomaly_probability_per_min (float)
      - scanline_alpha (int 0..255)
      - noise_alpha (int 0..255)
      - vignette_strength (float 0..1)
    """

    def __init__(self, config: dict):
        self.title = str(config.get("title", "COSMIC LIBRARY INDEX"))
        self.accent_rgb = tuple(config.get("accent_rgb", [170, 220, 255]))
        self.seed = config.get("seed", None)
        self.refresh_hz = float(config.get("refresh_hz", 60.0))

        self.shelf_count = int(config.get("shelf_count", 5))
        self.cards_per_shelf = int(config.get("cards_per_shelf", 7))
        self.portrait_columns = int(config.get("portrait_columns", 1))

        self.flip_interval_range = config.get("flip_interval_range", [0.8, 1.8])
        self.dust_rate = float(config.get("dust_rate", 50.0))
        self.anomaly_probability_per_min = float(config.get("anomaly_probability_per_min", 0.4))

        self.scanline_alpha = int(config.get("scanline_alpha", 10))
        self.noise_alpha = int(config.get("noise_alpha", 10))
        self.vignette_strength = float(config.get("vignette_strength", 0.30))

        # runtime
        self.manager = None
        self.w = 0
        self.h = 0
        self._is_portrait = False

        # layout
        self._pad = 0
        self._header_h = 0
        self._footer_h = 0
        self._content_rect = pygame.Rect(0, 0, 0, 0)

        # fonts
        self._font_header = None
        self._font_small = None
        self._font_body = None
        self._font_tiny = None

        # colors
        self._bg = (0, 0, 0)
        self._fg = (235, 235, 235)
        self._dim = (150, 150, 150)

        # state
        self._t = 0.0
        self._rng = random.Random()
        self._dust: list[Dust] = []
        self._cards: list[Card] = []

        # overlays
        self._overlay = None
        self._vignette = None

        # scheduling
        self._next_flip_t = 0.0
        self._next_anom_t = 0.0

    # ---------- lifecycle ----------

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._recompute_layout()
        self._build_overlays()
        self._init_cards()
        self._schedule_next_flip()
        self._schedule_next_anomaly()

    def exit(self):
        self.manager = None
        self._dust = []
        self._cards = []
        self._overlay = None
        self._vignette = None

    def handle_event(self, event):
        # SPACE: force a flip
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self._trigger_flip()

    def update(self, dt: float):
        self._t += dt

        # hotplug / rotation
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            self._build_overlays()

        # dust
        self._spawn_dust(dt)
        self._tick_dust(dt)

        # card flips
        if self._t >= self._next_flip_t:
            self._trigger_flip()
            self._schedule_next_flip()

        # anomalies
        if self._t >= self._next_anom_t:
            self._trigger_anomaly()
            self._schedule_next_anomaly()

        # advance flip animations + decay anomalies
        for c in self._cards:
            if c.flipping:
                c.flip_t += dt
                if c.flip_t >= c.flip_dur:
                    c.flipping = False
                    c.flip_t = c.flip_dur
            if c.anomaly_t > 0.0:
                c.anomaly_t = max(0.0, c.anomaly_t - dt)

    def render(self, screen: pygame.Surface):
        screen.fill(self._bg)

        self._draw_header(screen)
        self._draw_content(screen)
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

        self._pad = int(min(self.w, self.h) * 0.05)
        self._header_h = max(86, int(self.h * 0.15))
        self._footer_h = max(44, int(self.h * 0.06))

        self._content_rect = pygame.Rect(
            self._pad,
            self._header_h,
            self.w - 2 * self._pad,
            self.h - self._header_h - self._footer_h
        )

        base = min(self.w, self.h)
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

    # ---------- data ----------

    def _init_cards(self):
        self._cards = []
        total = max(1, self.shelf_count * self.cards_per_shelf)

        for i in range(total):
            self._cards.append(self._make_card(i))

    def _make_card(self, i: int) -> Card:
        # pseudo-library metadata
        shelf = self._rng.choice(["ORION", "LYRA", "CETUS", "DRACO", "PERSEUS", "VULPECULA"])
        status = self._rng.choices(
            ["CATALOGED", "TRANSLATING", "SEALED", "QUARANTINED", "LOST"],
            weights=[0.62, 0.14, 0.10, 0.10, 0.04],
            k=1
        )[0]

        code = f"{shelf}-{self._rng.randint(10, 99)}.{self._rng.randint(100, 999)}"
        title = self._rng.choice([
            "Atlas of Silent Constellations",
            "On the Geometry of Long Dreams",
            "The Archive of Unsent Signals",
            "A Field Guide to Impossible Metals",
            "The Cartographer's Null Index",
            "Manual of Pale Engines",
            "Treatise on Lunar Linguistics",
            "The Choir of Distant Machines",
            "Catalogue of Borrowed Suns",
            "Notes from a Closed Horizon",
        ])
        author = self._rng.choice([
            "S. Kestrel", "Archivist-9", "I. Varn", "Dr. M. Halcyon",
            "Librarian Unit Δ", "Unknown", "The Ninth Curator", "A. Rook"
        ])
        age = self._rng.choice(["pre-Fall", "3rd Era", "post-Transit", "undated", "redacted"])
        last_scan = self._rng.choice(["OK", "OK", "OK", "CRC WARN", "SIGNATURE MISMATCH"])

        return Card(
            code=code,
            title=title,
            author=author,
            shelf=shelf,
            status=status,
            age=age,
            last_scan=last_scan,
            flip_t=0.0,
            flip_dur=self._rng.uniform(0.35, 0.65),
            flipping=False,
            anomaly_t=0.0
        )

    # ---------- scheduling ----------

    def _schedule_next_flip(self):
        mn, mx = float(self.flip_interval_range[0]), float(self.flip_interval_range[1])
        self._next_flip_t = self._t + self._rng.uniform(mn, mx)

    def _schedule_next_anomaly(self):
        # based on per-minute probability -> convert to a rough interval
        rate = max(0.0, self.anomaly_probability_per_min)
        if rate <= 0.0001:
            self._next_anom_t = self._t + 999999.0
            return
        # expected interval ~ 60/rate, add randomness
        base = 60.0 / rate
        self._next_anom_t = self._t + self._rng.uniform(base * 0.5, base * 1.4)

    def _trigger_flip(self):
        if not self._cards:
            return
        idx = self._rng.randrange(0, len(self._cards))
        c = self._cards[idx]
        c.flipping = True
        c.flip_t = 0.0
        c.flip_dur = self._rng.uniform(0.35, 0.65)
        # when flip completes, replace metadata (we do it mid-flip at 50% for effect)
        # (we’ll replace during drawing when flip crosses halfway)

    def _trigger_anomaly(self):
        if not self._cards:
            return
        # highlight a few cards
        for _ in range(self._rng.randint(1, 3)):
            c = self._cards[self._rng.randrange(0, len(self._cards))]
            c.anomaly_t = self._rng.uniform(2.0, 4.0)
            # nudge status for flavor
            if self._rng.random() < 0.35:
                c.status = self._rng.choice(["QUARANTINED", "SEALED", "TRANSLATING"])

    # ---------- dust ----------

    def _spawn_dust(self, dt: float):
        rate = max(0.0, self.dust_rate)
        count = int(rate * dt)
        if self._rng.random() < (rate * dt - count):
            count += 1

        for _ in range(count):
            x = self._rng.uniform(0, self.w)
            y = self._rng.uniform(0, self.h * 0.35)
            vx = self._rng.uniform(-8.0, 8.0)
            vy = self._rng.uniform(18.0, 55.0)
            life = self._rng.uniform(0.9, 2.2)
            a = self._rng.randint(20, 75)
            r = self._rng.uniform(1.0, 2.4)
            self._dust.append(Dust(x, y, vx, vy, life, a, r))

        if len(self._dust) > 1000:
            self._dust = self._dust[-800:]

    def _tick_dust(self, dt: float):
        keep = []
        for d in self._dust:
            d.life -= dt
            if d.life <= 0:
                continue
            d.x += d.vx * dt
            d.y += d.vy * dt
            d.vx += math.sin(self._t * 0.9 + d.x * 0.01) * dt * 4.0
            d.vy += dt * 6.0
            if d.y < self.h + 10:
                keep.append(d)
        self._dust = keep

    # ---------- drawing ----------

    def _draw_header(self, screen: pygame.Surface):
        band = pygame.Surface((self.w, self._header_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, 0))

        t1 = self._font_header.render(self.title, True, self.accent_rgb)
        screen.blit(t1, (self._pad, int(self._header_h * 0.18)))

        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        sub = f"VAULT NODE: IX-ARCHIVE    |    INDEX STATUS: LIVE    |    UTC {ts}"
        t2 = self._font_small.render(sub, True, self._dim)
        screen.blit(t2, (self._pad, int(self._header_h * 0.18) + t1.get_height() + 6))

        pygame.draw.line(screen, self._dim, (self._pad, self._header_h - 2), (self.w - self._pad, self._header_h - 2), 2)

    def _draw_footer(self, screen: pygame.Surface):
        y0 = self.h - self._footer_h
        band = pygame.Surface((self.w, self._footer_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, y0))

        hint = "SPACE: flip a card   |   turn knob: change modes"
        s = self._font_small.render(hint, True, self._dim)
        screen.blit(s, (self._pad, y0 + (self._footer_h - s.get_height()) // 2))

    def _draw_content(self, screen: pygame.Surface):
        # dust behind everything
        for d in self._dust:
            pygame.draw.circle(screen, (255, 255, 255, d.a), (int(d.x), int(d.y)), int(d.r))

        r = self._content_rect

        cols = self.portrait_columns if self._is_portrait else max(1, self.portrait_columns + 1)
        cols = max(1, int(cols))

        rows = max(1, math.ceil(len(self._cards) / cols))
        gap = max(10, int(min(self.w, self.h) * 0.020))

        # card size tuned for portrait: tall cards read well
        card_w = (r.width - (cols - 1) * gap) // cols
        # choose rows to fill the available height without overflowing too much
        card_h = max(92, min(160, (r.height - (min(rows, 8) - 1) * gap) // min(rows, 8)))

        # how many rows can we show?
        max_rows = max(1, (r.height + gap) // (card_h + gap))
        start = 0
        visible_count = cols * max_rows
        cards = self._cards[start:start + visible_count]

        idx = 0
        for rr in range(max_rows):
            for cc in range(cols):
                if idx >= len(cards):
                    return
                x = r.left + cc * (card_w + gap)
                y = r.top + rr * (card_h + gap)
                self._draw_card(screen, pygame.Rect(x, y, card_w, card_h), cards[idx], global_index=idx)
                idx += 1

    def _draw_card(self, screen: pygame.Surface, rect: pygame.Rect, card: Card, global_index: int):
        # card frame
        pygame.draw.rect(screen, (0, 0, 0), rect)

        # anomaly pulse
        pulse_a = 0
        if card.anomaly_t > 0.0:
            pulse = 0.5 + 0.5 * math.sin(self._t * 9.0 + global_index * 0.7)
            pulse_a = int(60 + 130 * pulse)

        border_a = 140 + (pulse_a // 2)
        pygame.draw.rect(screen, (*self.accent_rgb, min(255, border_a)), rect, 2)

        # flip effect: horizontal squash as it flips
        if card.flipping:
            t = max(0.0, min(1.0, card.flip_t / max(0.001, card.flip_dur)))
            # cosine ease
            e = 0.5 - 0.5 * math.cos(t * math.pi)
            # width scale goes down then up
            s = abs(1.0 - 2.0 * e)  # 1->0->1
            s = max(0.06, s)

            # replace content at “mid-flip”
            if (0.48 < e < 0.52) and (self._rng.random() < 0.35):
                # occasionally replace full card
                repl = self._make_card(global_index)
                card.code, card.title, card.author = repl.code, repl.title, repl.author
                card.shelf, card.status, card.age, card.last_scan = repl.shelf, repl.status, repl.age, repl.last_scan

            inner = rect.inflate(-10, -10)
            new_w = int(inner.width * s)
            cx = inner.centerx
            draw_rect = pygame.Rect(cx - new_w // 2, inner.top, new_w, inner.height)

            # dim during flip
            flip_shade = pygame.Surface((inner.width, inner.height), pygame.SRCALPHA)
            flip_shade.fill((0, 0, 0, int(140 * (1.0 - s))))
            screen.blit(flip_shade, inner.topleft)

            # draw “spine” line to sell the flip
            pygame.draw.line(screen, (*self.accent_rgb, 120), (cx, inner.top), (cx, inner.bottom), 1)

            # only draw text if wide enough
            if new_w > 40:
                self._draw_card_text(screen, draw_rect, card, pulse_a)
            return

        # normal
        inner = rect.inflate(-10, -10)
        self._draw_card_text(screen, inner, card, pulse_a)

    def _draw_card_text(self, screen: pygame.Surface, rect: pygame.Rect, card: Card, pulse_a: int):
        # status chip color
        if card.status == "QUARANTINED":
            scol = (255, 160, 160)
        elif card.status == "SEALED":
            scol = (255, 220, 150)
        elif card.status == "LOST":
            scol = (200, 120, 120)
        elif card.status == "TRANSLATING":
            scol = (180, 255, 210)
        else:
            scol = (200, 200, 200)

        # top line: code + shelf
        top = self._font_small.render(f"{card.code}  [{card.shelf}]", True, self._dim)
        screen.blit(top, (rect.left, rect.top))

        # title
        title = self._font_body.render(card.title[:36], True, self._fg)
        screen.blit(title, (rect.left, rect.top + 24))

        # author
        auth = self._font_small.render(f"by {card.author}", True, self._dim)
        screen.blit(auth, (rect.left, rect.top + 24 + title.get_height() + 4))

        # status chip
        chip = pygame.Rect(rect.left, rect.bottom - 30, min(190, rect.width), 24)
        pygame.draw.rect(screen, (*scol, 40), chip, border_radius=6)
        pygame.draw.rect(screen, (*scol, 160), chip, 2, border_radius=6)
        st = self._font_tiny.render(card.status, True, scol)
        screen.blit(st, (chip.left + 8, chip.top + 5))

        # bottom-right metadata
        meta = self._font_tiny.render(f"AGE:{card.age}  SCAN:{card.last_scan}", True, self._dim)
        screen.blit(meta, (rect.right - meta.get_width(), rect.bottom - meta.get_height() - 2))

        # anomaly glow wash
        if pulse_a > 0:
            glow = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
            glow.fill((*self.accent_rgb, int(pulse_a * 0.18)))
            screen.blit(glow, rect.topleft)

    def _draw_noise(self, screen: pygame.Surface):
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

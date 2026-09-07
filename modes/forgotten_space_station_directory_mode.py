# forgotten_space_station_directory_mode.py

import math
import random
from dataclasses import dataclass
from datetime import datetime

import pygame


@dataclass
class DirRow:
    deck: str
    sector: str
    service: str
    status: str   # ONLINE / OFFLINE / RESTRICTED / UNKNOWN
    code: str     # short locator code
    heat: float   # for highlight pulse
    glitch: float # for glitchy text moment


@dataclass
class BannerMsg:
    t_end: float
    text: str


class ForgottenSpaceStationDirectoryMode:
    """
    Forgotten Space Station Directory (portrait-friendly)
    - Vertical scrolling directory of decks/sectors/services
    - Status changes + occasional OFFLINE waves
    - Glitchy corruption events + station announcements ticker

    Config (optional):
      - title (str)
      - station_name (str)
      - accent_rgb ([r,g,b])
      - seed (int)
      - refresh_hz (float)
      - scanline_alpha (int)
      - noise_alpha (int)
      - vignette_strength (float)
      - rows_visible (int)
      - scroll_speed (float) rows/sec-ish
      - glitch_probability_per_min (float)
      - offline_probability_per_min (float)
      - announcement_interval_range ([min,max] sec)
      - portrait_mode (bool)
    """

    def __init__(self, config: dict):
        self.title = str(config.get("title", "FORGOTTEN STATION DIRECTORY"))
        self.station_name = str(config.get("station_name", "STATION: UNKNOWN"))
        self.accent_rgb = tuple(config.get("accent_rgb", [200, 255, 210]))
        self.seed = config.get("seed", None)
        self.refresh_hz = float(config.get("refresh_hz", 60.0))

        self.scanline_alpha = int(config.get("scanline_alpha", 10))
        self.noise_alpha = int(config.get("noise_alpha", 10))
        self.vignette_strength = float(config.get("vignette_strength", 0.30))

        self.rows_visible = int(config.get("rows_visible", 14))
        self.scroll_speed = float(config.get("scroll_speed", 0.30))
        self.glitch_probability_per_min = float(config.get("glitch_probability_per_min", 1.0))
        self.offline_probability_per_min = float(config.get("offline_probability_per_min", 0.6))
        self.announcement_interval_range = config.get("announcement_interval_range", [9.0, 18.0])

        self.font_scale = float(config.get("font_scale", 1.0))
        self.font_scale = max(0.6, min(1.5, self.font_scale))

        self.portrait_mode = bool(config.get("portrait_mode", True))

        # runtime
        self.manager = None
        self.w = 0
        self.h = 0

        # colors
        self._bg = (0, 0, 0)
        self._fg = (235, 235, 235)
        self._dim = (150, 150, 150)

        # layout
        self._pad = 0
        self._header_h = 0
        self._footer_h = 0
        self._content_rect = pygame.Rect(0, 0, 0, 0)
        self._ticker_rect = pygame.Rect(0, 0, 0, 0)

        # fonts
        self._font_header = None
        self._font_row = None
        self._font_small = None
        self._font_tiny = None

        # state
        self._t = 0.0
        self._rng = random.Random()
        self._rows: list[DirRow] = []
        self._scroll = 0.0  # fractional row scroll
        self._banner: BannerMsg | None = None
        self._next_announce_t = 0.0

        # overlays
        self._overlay = None
        self._vignette = None

    # ---------- lifecycle ----------

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._recompute_layout()
        self._build_overlays()

        self._rows = self._build_directory(60)
        self._scroll = 0.0
        self._banner = None
        self._schedule_announcement()

    def exit(self):
        self.manager = None
        self._rows = []
        self._overlay = None
        self._vignette = None

    def handle_event(self, event):
        # SPACE: force announcement
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self._post_announcement(force=True)

    def update(self, dt: float):
        self._t += dt

        # resize/hotplug
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            self._build_overlays()

        # scroll
        self._scroll += dt * self.scroll_speed
        while self._scroll >= 1.0:
            self._scroll -= 1.0
            # rotate directory like a kiosk loop
            if self._rows:
                self._rows.append(self._rows.pop(0))

        # decay effects
        for r in self._rows:
            if r.heat > 0:
                r.heat = max(0.0, r.heat - dt * 0.6)
            if r.glitch > 0:
                r.glitch = max(0.0, r.glitch - dt * 1.2)

        # glitch events
        p_g = max(0.0, self.glitch_probability_per_min) / 60.0
        if self._rng.random() < p_g * dt:
            self._trigger_glitch()

        # offline wave events
        p_o = max(0.0, self.offline_probability_per_min) / 60.0
        if self._rng.random() < p_o * dt:
            self._offline_wave()

        # announcements
        if self._t >= self._next_announce_t:
            self._post_announcement(force=False)
            self._schedule_announcement()

        # banner expiry
        if self._banner and self._banner.t_end <= self._t:
            self._banner = None

    def render(self, screen: pygame.Surface):
        screen.fill(self._bg)

        self._draw_header(screen)
        self._draw_directory(screen)
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
        self._header_h = max(86, int(self.h * 0.15))
        self._footer_h = max(56, int(self.h * 0.08))  # include ticker

        self._content_rect = pygame.Rect(
            self._pad,
            self._header_h,
            self.w - 2 * self._pad,
            self.h - self._header_h - self._footer_h
        )
        self._ticker_rect = pygame.Rect(
            self._pad,
            self.h - self._footer_h + 8,
            self.w - 2 * self._pad,
            self._footer_h - 16
        )

        fs = self.font_scale

        header_sz = max(16, int(base * 0.050 * fs))
        row_sz    = max(11, int(base * 0.026 * fs))
        small_sz  = max(10, int(base * 0.020 * fs))
        tiny_sz   = max(9,  int(base * 0.017 * fs))

        self._font_header = self.manager.cache.get_font("dejavusansmono", header_sz, bold=True)
        self._font_row    = self.manager.cache.get_font("dejavusansmono", row_sz,    bold=False)
        self._font_small  = self.manager.cache.get_font("dejavusansmono", small_sz,  bold=False)
        self._font_tiny   = self.manager.cache.get_font("dejavusansmono", tiny_sz,   bold=False)

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

    # ---------- directory data ----------

    def _build_directory(self, n: int) -> list[DirRow]:
        decks = ["DCK-01", "DCK-02", "DCK-03", "DCK-04", "DCK-05", "DCK-06", "DCK-07", "DCK-08", "DCK-09", "DCK-10"]
        sectors = ["ATR", "CON", "MED", "HAB", "CARGO", "ENG", "ARRAY", "VAULT", "AIRLOCK", "GARDEN"]
        services = [
            "Transit Hub", "Hydroponics", "Comms Relay", "Life Support",
            "Observation Gallery", "Cryo Annex", "Machine Chapel",
            "Archive Stacks", "Waste Reclaimer", "Dock Control",
            "Fabricator Bay", "Security Desk", "Medical Ward", "Sensor Spine"
        ]
        statuses = ["ONLINE", "OFFLINE", "RESTRICTED", "UNKNOWN"]

        out = []
        for i in range(n):
            d = self._rng.choice(decks)
            s = self._rng.choice(sectors)
            svc = self._rng.choice(services)
            st = self._rng.choices(statuses, weights=[0.62, 0.18, 0.12, 0.08], k=1)[0]
            code = f"{s}-{self._rng.randint(10,99)}.{self._rng.choice(list('ABCDEFGH'))}"
            out.append(DirRow(deck=d, sector=s, service=svc, status=st, code=code, heat=0.0, glitch=0.0))
        return out

    def _trigger_glitch(self):
        if not self._rows:
            return
        # corrupt a few lines briefly
        for _ in range(self._rng.randint(1, 4)):
            r = self._rows[self._rng.randrange(0, len(self._rows))]
            r.glitch = self._rng.uniform(0.6, 1.3)
            r.heat = max(r.heat, self._rng.uniform(0.6, 1.2))

        if self._rng.random() < 0.35:
            self._post_banner("DIRECTORY CRC WARN: attempting rebuild", ttl=2.6)

    def _offline_wave(self):
        if not self._rows:
            return
        # flip a small slice to OFFLINE
        k = self._rng.randint(2, 6)
        idxs = [self._rng.randrange(0, len(self._rows)) for _ in range(k)]
        for i in idxs:
            self._rows[i].status = self._rng.choice(["OFFLINE", "UNKNOWN", "RESTRICTED"])
            self._rows[i].heat = max(self._rows[i].heat, self._rng.uniform(0.9, 1.4))
        self._post_banner("POWER BUS FLUCTUATION: SECTORS DEGRADED", ttl=3.0)

    # ---------- announcements ----------

    def _schedule_announcement(self):
        mn, mx = float(self.announcement_interval_range[0]), float(self.announcement_interval_range[1])
        self._next_announce_t = self._t + self._rng.uniform(mn, mx)

    def _post_announcement(self, force: bool):
        lines = [
            "ATTN: transit service suspended until further notice.",
            "NOTICE: unverified access keys detected in DECK-07.",
            "PSA: keep helmets sealed beyond AIRLOCK-2.",
            "REMINDER: machine chapel is CLOSED (maintenance).",
            "ALERT: sensor spine reporting ghost pings.",
            "INFO: archive stacks require authorization seal.",
            "NOTICE: hydroponics water rationing in effect.",
            "ATTN: docking collars misaligned. do not attempt manual latch.",
            "REMINDER: medical ward is operating on backup power.",
        ]
        t = self._rng.choice(lines) if not force else "ATTN: emergency paging system offline. please remain calm."
        self._post_banner(t, ttl=self._rng.uniform(3.0, 5.0))

    def _post_banner(self, text: str, ttl: float):
        self._banner = BannerMsg(t_end=self._t + ttl, text=text)

    # ---------- drawing ----------

    def _draw_header(self, screen: pygame.Surface):
        band = pygame.Surface((self.w, self._header_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, 0))

        t1 = self._font_header.render(self.title, True, self.accent_rgb)
        screen.blit(t1, (self._pad, int(self._header_h * 0.18)))

        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        sub = self._font_small.render(f"{self.station_name}   |   DIRECTORY NODE: KIOSK-Δ   |   UTC {ts}", True, self._dim)
        screen.blit(sub, (self._pad, int(self._header_h * 0.18) + t1.get_height() + 6))

        pygame.draw.line(screen, self._dim, (self._pad, self._header_h - 2), (self.w - self._pad, self._header_h - 2), 2)

    def _draw_footer(self, screen: pygame.Surface):
        # ticker background
        pygame.draw.rect(screen, (0, 0, 0), pygame.Rect(0, self.h - self._footer_h, self.w, self._footer_h))
        pygame.draw.line(screen, self._dim, (self._pad, self.h - self._footer_h), (self.w - self._pad, self.h - self._footer_h), 2)

        # banner text
        if self._banner:
            txt = self._banner.text
        else:
            txt = "kiosk idle: tap to wake (not really)   |   routing to local cache"
        s = self._font_small.render(txt, True, self._dim)
        screen.blit(s, (self._ticker_rect.left + 6, self._ticker_rect.top + (self._ticker_rect.height - s.get_height()) // 2))

    def _draw_directory(self, screen: pygame.Surface):
        r = self._content_rect
        pygame.draw.rect(screen, (0, 0, 0), r)
        pygame.draw.rect(screen, (*self.accent_rgb, 150), r, 2)

        # column headers
        head_y = r.top + 10
        head = self._font_tiny.render("DECK     SECTOR   SERVICE                     STATUS       CODE", True, self._dim)
        screen.blit(head, (r.left + 12, head_y))
        pygame.draw.line(screen, (*self.accent_rgb, 80), (r.left + 12, head_y + 18), (r.right - 12, head_y + 18), 1)

        # rows
        line_h = self._font_row.get_linesize() + 6
        y0 = head_y + 26 - int(self._scroll * line_h)

        visible = max(6, int(self.rows_visible))
        rows = self._rows[:visible + 2]  # extra for scroll

        for i, row in enumerate(rows):
            y = y0 + i * line_h
            if y > r.bottom - 12:
                break
            if y < r.top + 28:
                continue

            # status color
            if row.status == "ONLINE":
                col = self.accent_rgb
            elif row.status == "OFFLINE":
                col = (255, 140, 140)
            elif row.status == "RESTRICTED":
                col = (255, 220, 150)
            else:
                col = (200, 200, 200)

            # highlight heat
            if row.heat > 0.0:
                a = int(40 + 120 * row.heat)
                glow = pygame.Surface((r.width - 24, line_h), pygame.SRCALPHA)
                glow.fill((*self.accent_rgb, int(a * 0.10)))
                screen.blit(glow, (r.left + 12, y - 2))

            deck = row.deck
            sector = row.sector
            service = row.service
            status = row.status
            code = row.code

            if row.glitch > 0.0:
                service = self._corrupt(service)
                code = self._corrupt(code)

            line = f"{deck:<8} {sector:<7} {service:<28} {status:<11} {code}"
            s = self._font_row.render(line[:80], True, col)
            screen.blit(s, (r.left + 12, y))

            # faint separator
            pygame.draw.line(screen, (*self.accent_rgb, 18), (r.left + 12, y + line_h - 2), (r.right - 12, y + line_h - 2), 1)

    def _corrupt(self, text: str) -> str:
        if not text:
            return text
        chars = list(text)
        n = self._rng.randint(1, min(4, len(chars)))
        for _ in range(n):
            i = self._rng.randrange(0, len(chars))
            chars[i] = self._rng.choice(list("▓▒░#/\\|{}[]<>"))
        if self._rng.random() < 0.25:
            # insert a fragment
            j = self._rng.randrange(0, len(chars))
            frag = "".join(chars[max(0, j - 2):j + 2])
            chars = chars[:j] + list(frag) + chars[j:]
        return "".join(chars)

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

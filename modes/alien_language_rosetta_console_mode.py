# alien_language_rosetta_console_mode.py

import math
import random
from dataclasses import dataclass
from datetime import datetime

import pygame


@dataclass
class Entry:
    glyphs: str
    roman: str
    meaning: str
    conf: float     # 0..1
    heat: float     # highlight pulse
    locked: bool    # promoted/confirmed


@dataclass
class LogLine:
    t_end: float
    kind: str   # INFO/WARN/LOCK
    text: str


class AlienLanguageRosettaConsoleMode:
    """
    Alien Language Rosetta Console
    - Left: alien glyph strings
    - Middle: evolving transliteration
    - Right: semantic guess + confidence bar
    - Occasional "LOCK" event promotes an entry to the lexicon

    Config (optional):
      - title (str)
      - site_name (str)
      - accent_rgb ([r,g,b])
      - seed (int)
      - refresh_hz (float)
      - portrait_layout (bool)
      - rows_visible (int)
      - decode_rate (float) new rows/sec-ish
      - mutation_rate (float) how often transliteration mutates
      - confidence_drift (float) how jittery confidence is
      - lock_probability_per_min (float)
      - scanline_alpha (int)
      - noise_alpha (int)
      - vignette_strength (float)
      - show_log (bool)
    """

    def __init__(self, config: dict):
        self.title = str(config.get("title", "ALIEN LANGUAGE ROSETTA CONSOLE"))
        self.site_name = str(config.get("site_name", "LINGUISTICS BAY"))
        self.accent_rgb = tuple(config.get("accent_rgb", [200, 255, 210]))

        self.seed = config.get("seed", None)
        self.refresh_hz = float(config.get("refresh_hz", 60.0))
        self.portrait_layout = bool(config.get("portrait_layout", True))

        self.rows_visible = int(config.get("rows_visible", 12))
        self.rows_visible = max(6, min(24, self.rows_visible))

        self.decode_rate = float(config.get("decode_rate", 0.8))
        self.mutation_rate = float(config.get("mutation_rate", 0.30))
        self.confidence_drift = float(config.get("confidence_drift", 0.20))
        self.lock_probability_per_min = float(config.get("lock_probability_per_min", 0.5))

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
        self._content = pygame.Rect(0, 0, 0, 0)

        self._panel_rect = pygame.Rect(0, 0, 0, 0)
        self._log_rect = pygame.Rect(0, 0, 0, 0)

        self._col_glyph = pygame.Rect(0, 0, 0, 0)
        self._col_roman = pygame.Rect(0, 0, 0, 0)
        self._col_sem = pygame.Rect(0, 0, 0, 0)

        # fonts
        self._font_header = None
        self._font_row = None
        self._font_small = None
        self._font_tiny = None

        # state
        self._entries: list[Entry] = []
        self._logs: list[LogLine] = []
        self._next_emit_t = 0.0

        # overlays
        self._overlay = None
        self._vignette = None

        # vocab pools
        self._semantic = [
            "WATER", "STAR", "SHELTER", "HOME", "DOOR", "HUNGER", "FIRE", "SLEEP",
            "DANGER", "FRIEND", "STRANGER", "MACHINE", "SKY", "TIME", "QUIET",
            "MOVE", "STOP", "GIVE", "TAKE", "LISTEN", "SPEAK", "REMEMBER",
            "SIGNAL", "PATH", "LIGHT", "DARK"
        ]
        self._meanings = [
            "request passage", "confirm identity", "warning marker", "ritual greeting",
            "navigation cue", "safe corridor", "power conduit", "restricted zone",
            "maintenance chant", "storage seal", "emergency override", "memory tag"
        ]
        self._roman_syll = ["ka", "shi", "tor", "ven", "ul", "dra", "mi", "za", "qo", "rei", "han", "tek", "sa", "ly", "no"]
        self._glyphs = "⌁⌂⌄⌇⌑⌒⍜⍟⎔⎚⎋⏣⏧␀␛▣▥▧▨◬◭◮◯◇◆◈◉"

    # ---------- lifecycle ----------

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._recompute_layout()
        self._build_overlays()

        self._entries = []
        for _ in range(self.rows_visible + 3):
            self._entries.append(self._new_entry())

        self._push_log("INFO", "decoder online; lexicon empty")
        self._push_log("INFO", "capturing glyph stream…")
        self._schedule_emit()

    def exit(self):
        self.manager = None
        self._entries = []
        self._logs = []
        self._overlay = None
        self._vignette = None

    def handle_event(self, event):
        # SPACE: force lock
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self._force_lock()

    def update(self, dt: float):
        self._t += dt

        # resize/hotplug
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            self._build_overlays()

        # decay heat
        for e in self._entries:
            e.heat = max(0.0, e.heat - dt * 0.6)

        # logs expire
        self._logs = [l for l in self._logs if l.t_end > self._t][-10:]

        # emit new lines
        if self._t >= self._next_emit_t:
            self._emit_row()
            self._schedule_emit()

        # mutate transliteration + confidence drift
        mut_p = max(0.0, self.mutation_rate)
        conf_j = max(0.0, self.confidence_drift)
        for e in self._entries:
            if not e.locked and self._rng.random() < mut_p * dt:
                e.roman = self._mutate_roman(e.roman)
                e.meaning = self._maybe_refine_meaning(e.meaning)
                e.heat = max(e.heat, 0.6)

            # confidence drift
            if not e.locked:
                d = self._rng.uniform(-conf_j, conf_j) * dt
                e.conf = max(0.02, min(0.98, e.conf + d))

        # random lock event
        p_lock = max(0.0, self.lock_probability_per_min) / 60.0
        if self._rng.random() < p_lock * dt:
            self._lock_random()

    def render(self, screen: pygame.Surface):
        screen.fill((0, 0, 0))

        self._draw_header(screen)
        self._draw_panel(screen)
        self._draw_footer(screen)

        if self._overlay is not None:
            screen.blit(self._overlay, (0, 0))
        if self._vignette is not None:
            screen.blit(self._vignette, (0, 0))
        if self.noise_alpha > 0:
            self._draw_noise(screen)

    # ---------- emit / lock ----------

    def _schedule_emit(self):
        # decode_rate ~ rows per second
        rate = max(0.05, self.decode_rate)
        self._next_emit_t = self._t + self._rng.uniform(0.7 / rate, 1.4 / rate)

    def _emit_row(self):
        # roll list and insert a fresh entry at top
        self._entries.insert(0, self._new_entry())
        self._entries = self._entries[: self.rows_visible + 3]
        if self._rng.random() < 0.22:
            self._push_log("INFO", "new packet: glyph burst captured")

    def _lock_random(self):
        candidates = [e for e in self._entries if not e.locked]
        if not candidates:
            return
        e = self._rng.choice(candidates)
        e.locked = True
        e.conf = max(e.conf, self._rng.uniform(0.82, 0.96))
        e.heat = 1.0
        self._push_log("LOCK", f"lexicon update: {e.roman} → {e.meaning}")

    def _force_lock(self):
        self._lock_random()

    # ---------- data synthesis ----------

    def _new_entry(self) -> Entry:
        glyphs = self._make_glyphs(self._rng.randint(6, 14))
        roman = self._make_roman(self._rng.randint(2, 4))
        sem = self._rng.choice(self._semantic)
        meaning = f"{sem.lower()}: {self._rng.choice(self._meanings)}"
        conf = self._rng.uniform(0.08, 0.55)
        return Entry(glyphs=glyphs, roman=roman, meaning=meaning, conf=conf, heat=0.0, locked=False)

    def _make_glyphs(self, n: int) -> str:
        return "".join(self._rng.choice(self._glyphs) for _ in range(n))

    def _make_roman(self, syll: int) -> str:
        parts = [self._rng.choice(self._roman_syll) for _ in range(syll)]
        # add separators sometimes
        if self._rng.random() < 0.35:
            return "-".join(parts)
        return "".join(parts)

    def _mutate_roman(self, s: str) -> str:
        # swap one syllable-ish chunk
        if not s:
            return self._make_roman(2)
        chunks = s.split("-") if "-" in s else [s[i:i+2] for i in range(0, len(s), 2)]
        if not chunks:
            return self._make_roman(2)
        i = self._rng.randrange(0, len(chunks))
        chunks[i] = self._rng.choice(self._roman_syll)
        out = "-".join(chunks) if "-" in s else "".join(chunks)
        # occasional punctuation
        if self._rng.random() < 0.18:
            out = out + self._rng.choice(["'", "·", ""])
        return out[:18]

    def _maybe_refine_meaning(self, meaning: str) -> str:
        # occasionally swap semantic headword
        if self._rng.random() < 0.25:
            sem = self._rng.choice(self._semantic).lower()
            tail = meaning.split(":", 1)[-1].strip()
            return f"{sem}: {tail}"
        if self._rng.random() < 0.20:
            head = meaning.split(":", 1)[0].strip()
            return f"{head}: {self._rng.choice(self._meanings)}"
        return meaning

    # ---------- logs ----------

    def _push_log(self, kind: str, text: str):
        ttl = 12.0 if kind != "LOCK" else 16.0
        self._logs.append(LogLine(t_end=self._t + ttl, kind=kind, text=text))

    # ---------- drawing ----------

    def _recompute_layout(self):
        self.w, self.h = self.manager.screen.get_size()
        base = min(self.w, self.h)

        self._pad = int(base * 0.05)
        self._header_h = max(80, int(self.h * 0.14))
        self._footer_h = max(44, int(self.h * 0.06))

        self._content = pygame.Rect(
            self._pad,
            self._header_h,
            self.w - 2 * self._pad,
            self.h - self._header_h - self._footer_h
        )

        # panel and optional log below if portrait
        if self.h > self.w or self.portrait_layout:
            log_h = int(self._content.height * (0.22 if self.show_log else 0.0))
            self._panel_rect = pygame.Rect(self._content.left, self._content.top, self._content.width, self._content.height - log_h - (10 if self.show_log else 0))
            self._log_rect = pygame.Rect(self._content.left, self._panel_rect.bottom + 10, self._content.width, log_h) if self.show_log else pygame.Rect(0, 0, 0, 0)
        else:
            # landscape: log on right
            log_w = int(self._content.width * (0.34 if self.show_log else 0.0))
            self._panel_rect = pygame.Rect(self._content.left, self._content.top, self._content.width - log_w - (10 if self.show_log else 0), self._content.height)
            self._log_rect = pygame.Rect(self._panel_rect.right + 10, self._content.top, log_w, self._content.height) if self.show_log else pygame.Rect(0, 0, 0, 0)

        # columns within panel
        pr = self._panel_rect.inflate(-18, -30)
        pr.top += 18

        g_w = int(pr.width * 0.34)
        r_w = int(pr.width * 0.24)
        s_w = pr.width - g_w - r_w - 20

        self._col_glyph = pygame.Rect(pr.left, pr.top, g_w, pr.height)
        self._col_roman = pygame.Rect(self._col_glyph.right + 10, pr.top, r_w, pr.height)
        self._col_sem = pygame.Rect(self._col_roman.right + 10, pr.top, s_w, pr.height)

        self._font_header = self.manager.cache.get_font("dejavusansmono", max(18, int(base * 0.050)), bold=True)
        self._font_row = self.manager.cache.get_font("dejavusansmono", max(14, int(base * 0.026)), bold=False)
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
        sub = self._font_small.render(f"{self.site_name}   |   UTC {ts}   |   stream: live", True, (150, 150, 150))
        screen.blit(sub, (self._pad, int(self._header_h * 0.20) + t1.get_height() + 6))

        pygame.draw.line(screen, (150, 150, 150), (self._pad, self._header_h - 2), (self.w - self._pad, self._header_h - 2), 2)

    def _draw_footer(self, screen: pygame.Surface):
        y0 = self.h - self._footer_h
        band = pygame.Surface((self.w, self._footer_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, y0))

        hint = "SPACE: force lexicon lock   |   turn knob: change modes"
        s = self._font_small.render(hint, True, (150, 150, 150))
        screen.blit(s, (self._pad, y0 + (self._footer_h - s.get_height()) // 2))

    def _draw_panel(self, screen: pygame.Surface):
        r = self._panel_rect
        pygame.draw.rect(screen, (0, 0, 0), r)
        pygame.draw.rect(screen, (*self.accent_rgb, 150), r, 2)

        # labels
        lab_g = self._font_tiny.render("GLYPH STREAM", True, (150, 150, 150))
        lab_r = self._font_tiny.render("ROMANIZATION", True, (150, 150, 150))
        lab_s = self._font_tiny.render("SEMANTIC GUESS / CONF", True, (150, 150, 150))
        screen.blit(lab_g, (self._col_glyph.left, r.top + 8))
        screen.blit(lab_r, (self._col_roman.left, r.top + 8))
        screen.blit(lab_s, (self._col_sem.left, r.top + 8))

        # rows
        line_h = self._font_row.get_linesize() + 8
        y = self._col_glyph.top + 6

        entries = self._entries[: self.rows_visible]
        for e in entries:
            if y + line_h > self._col_glyph.bottom:
                break

            # locked styling
            if e.locked:
                col = (255, 220, 150)
            else:
                col = self.accent_rgb

            # heat highlight band
            if e.heat > 0.0:
                a = int(40 + 120 * e.heat)
                band = pygame.Surface((self._panel_rect.width - 24, line_h), pygame.SRCALPHA)
                band.fill((*self.accent_rgb, int(a * 0.10)))
                screen.blit(band, (self._panel_rect.left + 12, y - 3))

            # glyphs
            g = self._font_row.render(e.glyphs[:18], True, col)
            screen.blit(g, (self._col_glyph.left, y))

            # romanization
            rr = self._font_row.render(e.roman[:16], True, (220, 220, 220) if e.locked else (180, 180, 180))
            screen.blit(rr, (self._col_roman.left, y))

            # semantic + confidence bar
            sem_txt = self._font_small.render(e.meaning[:32], True, (150, 150, 150))
            screen.blit(sem_txt, (self._col_sem.left, y + 2))

            # bar
            bar_w = self._col_sem.width
            bar_h = 8
            bx = self._col_sem.left
            by = y + line_h - 10
            pygame.draw.rect(screen, (*self.accent_rgb, 40), pygame.Rect(bx, by, bar_w, bar_h), border_radius=6)
            fill = int(bar_w * max(0.0, min(1.0, e.conf)))
            pygame.draw.rect(screen, (*col, 140), pygame.Rect(bx, by, fill, bar_h), border_radius=6)

            pct = self._font_tiny.render(f"{int(e.conf * 100):02d}%", True, col)
            screen.blit(pct, (bx + bar_w - pct.get_width(), y))

            # row separator
            pygame.draw.line(screen, (*self.accent_rgb, 18), (self._panel_rect.left + 12, y + line_h - 2), (self._panel_rect.right - 12, y + line_h - 2), 1)

            y += line_h

        # log panel
        if self.show_log and self._log_rect.width > 10 and self._log_rect.height > 10:
            self._draw_log(screen)

    def _draw_log(self, screen: pygame.Surface):
        r = self._log_rect
        pygame.draw.rect(screen, (0, 0, 0), r)
        pygame.draw.rect(screen, (*self.accent_rgb, 150), r, 2)
        lab = self._font_tiny.render("LEXICON / EVENTS", True, (150, 150, 150))
        screen.blit(lab, (r.left + 10, r.top + 8))

        inner = r.inflate(-18, -30)
        inner.top += 18
        x = inner.left + 4
        y = inner.top + 8

        for l in self._logs[::-1][:6]:
            if l.kind == "LOCK":
                col = (255, 220, 150)
            elif l.kind == "WARN":
                col = (255, 180, 180)
            else:
                col = (150, 150, 150)
            s = self._font_small.render(f"[{l.kind}] {l.text}", True, col)
            screen.blit(s, (x, y))
            y += s.get_height() + 6
            if y > inner.bottom - 6:
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

# modes/scifi_home_control_panel_mode.py

import math
import random
from dataclasses import dataclass, field
from datetime import datetime

import pygame


# ────────────────────────────────────────────────────────────────
# Data structures
# ────────────────────────────────────────────────────────────────

@dataclass
class MetricDef:
    key: str
    label: str
    unit: str
    lo: float
    hi: float
    nominal_lo: float
    nominal_hi: float
    value: float = 0.0
    target: float = 0.0
    drift_rate: float = 0.15


@dataclass
class EventTemplate:
    kind: str          # INFO / WARN / ALERT / SILLY
    text: str
    trigger_chance_per_sec: float = 0.0


@dataclass
class PanelEvent:
    t_end: float
    kind: str
    text: str


@dataclass
class RenderCtx:
    font_header: 'pygame.font.Font'
    font_body: 'pygame.font.Font'
    font_small: 'pygame.font.Font'
    font_tiny: 'pygame.font.Font'
    bg: tuple
    fg: tuple
    dim: tuple
    ok: tuple
    warn: tuple
    alert: tuple
    cool: tuple
    accent_rgb: tuple
    screen_w: int
    screen_h: int


@dataclass
class SubsystemPanel:
    panel_id: int
    name: str
    subtitle: str
    icon: str
    metrics: list[MetricDef] = field(default_factory=list)
    event_templates: list[EventTemplate] = field(default_factory=list)

    # runtime
    events: list[PanelEvent] = field(default_factory=list)
    _t: float = 0.0
    _next_event_t: float = 0.0
    _rng: 'random.Random' = field(default_factory=random.Random)
    _metric_history: list[list[float]] = field(default_factory=list)
    _history_len: int = 60

    # ── lifecycle ───────────────────────────────────────────

    def reset(self, rng_seed: int):
        self._t = 0.0
        self._next_event_t = 1.5
        self._rng = random.Random(rng_seed)
        self.events = []
        self._metric_history = []
        for m in self.metrics:
            mid = m.nominal_lo + (m.nominal_hi - m.nominal_lo) * 0.5
            m.value = mid
            m.target = mid
        # seed initial history
        for _ in range(self._history_len):
            row = []
            for m in self.metrics:
                row.append(m.nominal_lo + (m.nominal_hi - m.nominal_lo) * self._rng.random())
            self._metric_history.append(row)
            if len(self._metric_history) > self._history_len:
                self._metric_history.pop(0)

    # ── simulation tick ──────────────────────────────────────

    def update(self, dt: float, shared_rng: 'random.Random'):
        self._t += dt

        # --- drift metrics toward targets ---
        for m in self.metrics:
            if shared_rng.random() < 0.15 * dt:
                m.target = m.nominal_lo + shared_rng.random() * (m.nominal_hi - m.nominal_lo)
                # 5 % chance of going outside nominal for spice
                if shared_rng.random() < 0.05:
                    if shared_rng.random() < 0.5:
                        m.target = m.lo + shared_rng.random() * (m.nominal_lo - m.lo) * 0.8
                    else:
                        m.target = m.nominal_hi + shared_rng.random() * (m.hi - m.nominal_hi) * 0.3

            m.value += (m.target - m.value) * m.drift_rate * dt
            m.value = max(m.lo, min(m.hi, m.value))

        # --- history ---
        row = [m.value for m in self.metrics]
        self._metric_history.append(row)
        if len(self._metric_history) > self._history_len:
            self._metric_history.pop(0)

        # --- event triggers ---
        if self._t >= self._next_event_t:
            for tmpl in self.event_templates:
                if shared_rng.random() < tmpl.trigger_chance_per_sec * 12.0:
                    self.push_event(tmpl.kind, tmpl.text)
            self._next_event_t = self._t + shared_rng.uniform(1.8, 5.5)

        # purge expired events
        self.events = [e for e in self.events if e.t_end > self._t]

    def push_event(self, kind: str, text: str):
        self.events.append(PanelEvent(self._t + 16.0, kind, text.upper()))
        if len(self.events) > 20:
            self.events.pop(0)

    # ── rendering ────────────────────────────────────────────

    def render(self, screen, rect: pygame.Rect, ctx: RenderCtx):
        """Render this subsystem panel into the given content rect."""
        hdr_h = int(rect.height * 0.11)
        gauge_h = int(rect.height * 0.38)
        chart_h = int(rect.height * 0.22)
        log_h = rect.height - hdr_h - gauge_h - chart_h - 16

        hdr = pygame.Rect(rect.left, rect.top, rect.width, hdr_h)
        gauge_area = pygame.Rect(rect.left, hdr.bottom + 6, rect.width, gauge_h)
        chart_area = pygame.Rect(rect.left, gauge_area.bottom + 6, rect.width, chart_h)
        log_area = pygame.Rect(rect.left, chart_area.bottom + 6, rect.width, log_h)

        self._draw_header(screen, hdr, ctx)
        self._draw_gauges(screen, gauge_area, ctx)
        self._draw_chart(screen, chart_area, ctx)
        self._draw_log(screen, log_area, ctx)

    def _draw_header(self, screen, rect, ctx):
        name = ctx.font_header.render(self.name, True, ctx.accent_rgb)
        sub = ctx.font_small.render(self.subtitle, True, ctx.dim)
        mask = ctx.font_small.render(self.icon, True, ctx.accent_rgb)
        screen.blit(name, (rect.left, rect.top + 4))
        screen.blit(sub, (rect.left, rect.bottom - sub.get_height() - 6))
        screen.blit(mask, (rect.right - mask.get_width() - 8, rect.top + 4))
        # accent line
        pygame.draw.line(screen, ctx.accent_rgb,
                         (rect.left, rect.bottom - 2),
                         (rect.right, rect.bottom - 2), 2)

    def _draw_gauges(self, screen, rect, ctx):
        n = len(self.metrics)
        if n == 0:
            return
        spacing = 5
        gauge_h = max(18, (rect.height - spacing * (n - 1)) // n)
        for i, m in enumerate(self.metrics):
            y = rect.top + i * (gauge_h + spacing)
            gr = pygame.Rect(rect.left, y, rect.width, gauge_h)
            self._draw_single_gauge(screen, gr, m, ctx)

    def _draw_single_gauge(self, screen, rect, m: MetricDef, ctx):
        # label on left
        label = ctx.font_tiny.render(m.label, True, ctx.accent_rgb)
        screen.blit(label, (rect.left, rect.top))

        # value on right
        if m.unit == "%" or (m.hi - m.lo) < 2.0:
            val_str = f"{m.value:5.1f} {m.unit}"
        else:
            val_str = f"{m.value:5.0f} {m.unit}"
        val_surf = ctx.font_small.render(val_str, True, ctx.fg)
        screen.blit(val_surf, (rect.right - val_surf.get_width(), rect.top))

        # bar background
        bar_y = rect.top + label.get_height() + 3
        bar_h = max(8, rect.height - label.get_height() - 5)
        bar_rect = pygame.Rect(rect.left, bar_y, rect.width, bar_h)

        pygame.draw.rect(screen, (18, 20, 26), bar_rect)
        pygame.draw.rect(screen, (50, 55, 60), bar_rect, 1)

        # nominal zone
        frac_lo = (m.nominal_lo - m.lo) / max(0.001, m.hi - m.lo)
        frac_hi = (m.nominal_hi - m.lo) / max(0.001, m.hi - m.lo)
        frac_val = (m.value - m.lo) / max(0.001, m.hi - m.lo)

        inner = bar_rect.inflate(-4, -4)
        zone_lo_x = inner.left + int(inner.width * frac_lo)
        zone_hi_x = inner.left + int(inner.width * frac_hi)
        if zone_hi_x > zone_lo_x:
            pygame.draw.rect(screen, (18, 65, 42),
                             (zone_lo_x, inner.top, zone_hi_x - zone_lo_x, inner.height))

        # value indicator
        val_x = inner.left + int(inner.width * min(1.0, max(0.0, frac_val)))
        if m.nominal_lo <= m.value <= m.nominal_hi:
            val_color = ctx.ok
        elif m.value < m.nominal_lo * 0.6 or m.value > m.nominal_hi * 1.25:
            val_color = ctx.alert
        else:
            val_color = ctx.warn
        pygame.draw.rect(screen, val_color, (val_x - 3, inner.top, 6, inner.height))

    def _draw_chart(self, screen, rect, ctx):
        pygame.draw.rect(screen, (10, 12, 16), rect)
        pygame.draw.rect(screen, ctx.accent_rgb, rect, 1)
        lbl = ctx.font_tiny.render("SYSTEM METRICS", True, ctx.accent_rgb)
        screen.blit(lbl, (rect.left + 8, rect.top + 4))

        inner = rect.inflate(-14, -22)
        inner.y += 8
        n = len(self.metrics)
        if n == 0 or not self._metric_history:
            return

        # use last N history points
        hist = self._metric_history[-40:]
        m = len(hist)
        bar_w = max(3, min(32, (inner.width - m * 2) // m))
        max_h = inner.height - 6

        # pick a representative metric (primary — first one)
        primary_idx = 0
        for i, met in enumerate(self.metrics):
            if "power" in met.key.lower() or "output" in met.key.lower() or "health" in met.key.lower() or "consciousness" in met.key.lower() or "shield" in met.key.lower() or "gravity" in met.key.lower() or "bandwidth" in met.key.lower() or "resolution" in met.key.lower() or "o2" in met.key.lower():
                primary_idx = i
                break

        met = self.metrics[primary_idx]
        for i, row in enumerate(hist):
            norm = (row[primary_idx] - met.lo) / max(0.001, met.hi - met.lo)
            norm = max(0.0, min(1.0, norm))
            bh = max(2, int(norm * max_h))
            x = inner.left + i * (bar_w + 2)

            if met.nominal_lo <= row[primary_idx] <= met.nominal_hi:
                color = ctx.ok
            else:
                color = ctx.warn
            # brighten recent bars
            recency = i / max(1.0, len(hist) - 1)
            r = min(255, color[0] + int(40 * recency))
            g = min(255, color[1] + int(40 * recency))
            b = min(255, color[2] + int(40 * recency))
            pygame.draw.rect(screen, (r, g, b), (x, inner.bottom - bh, bar_w, bh))

        # label
        short = met.label[:6]
        ls = ctx.font_tiny.render(short, True, ctx.dim)
        screen.blit(ls, (inner.left, inner.bottom + 2))

    def _draw_log(self, screen, rect, ctx):
        pygame.draw.rect(screen, (10, 12, 16), rect)
        pygame.draw.rect(screen, ctx.dim, rect, 1)
        lbl = ctx.font_tiny.render("EVENT LOG", True, ctx.accent_rgb)
        screen.blit(lbl, (rect.left + 8, rect.top + 4))

        inner = rect.inflate(-12, -18)
        inner.y += 8

        line_h = ctx.font_tiny.get_linesize() + 2
        visible = max(1, inner.height // line_h)
        lines = self.events[-visible:]

        for idx, event in enumerate(lines):
            y = inner.top + idx * line_h
            if event.kind == "WARN":
                kind_color = ctx.warn
            elif event.kind == "ALERT":
                kind_color = ctx.alert
            elif event.kind == "SILLY":
                kind_color = ctx.cool
            else:
                kind_color = ctx.ok

            kind = ctx.font_tiny.render(f"[{event.kind[:5]}]", True, kind_color)
            text = ctx.font_tiny.render(event.text, True, ctx.fg)
            screen.blit(kind, (inner.left, y))
            screen.blit(text, (inner.left + kind.get_width() + 6, y))


# ────────────────────────────────────────────────────────────────
# Main mode class
# ────────────────────────────────────────────────────────────────

class SciFiHomeControlPanelMode:
    """
    Sci-Fi Smart Home Control Panel — cycles through futuristic subsystem panels.

    Each subsystem (fusion reactor, home AI, replicator, teleporter, holodeck,
    life support, defense, comms, gravity, medical) gets its own panel with
    animated gauges, metric charts, and a scrolling event log full of
    humorous boot messages and false alarms.

    Panels cycle every ``panel_duration_sec`` (default 30 s) with a
    crossfade transition.

    Config (all optional):
      - title (str)
      - subtitle (str)
      - accent_rgb ([r,g,b])
      - seed (int)
      - refresh_hz (float)
      - panel_duration_sec (float): seconds per panel
      - crossfade_sec (float): crossfade duration
      - portrait_layout (bool)
      - scanline_alpha (int)
      - noise_alpha (int)
      - vignette_strength (float)
    """

    def __init__(self, config: dict):
        self.title = str(config.get("title", "RESIDENTIAL SYSTEMS CONTROL"))
        self.subtitle = str(config.get("subtitle", "KESTREL HABITAT // TIER 3 DOMICILE"))
        self.accent_rgb = tuple(config.get("accent_rgb", [0, 255, 200]))
        self.seed = config.get("seed", None)
        self.refresh_hz = float(config.get("refresh_hz", 60.0))
        self.panel_duration_sec = float(config.get("panel_duration_sec", 60.0))
        self.crossfade_sec = float(config.get("crossfade_sec", 0.8))
        self.portrait_layout = bool(config.get("portrait_layout", True))
        self.scanline_alpha = int(config.get("scanline_alpha", 10))
        self.noise_alpha = int(config.get("noise_alpha", 10))
        self.vignette_strength = float(config.get("vignette_strength", 0.18))

        # runtime
        self.manager = None
        self.w = 0
        self.h = 0
        self._is_portrait = False
        self._t = 0.0
        self._rng = random.Random()

        # colors
        self._bg = (3, 4, 8)
        self._fg = (220, 240, 235)
        self._dim = (100, 130, 125)
        self._ok = (50, 240, 160)
        self._warn = (255, 200, 60)
        self._alert = (255, 70, 70)
        self._cool = (60, 200, 255)

        # layout rects
        self._pad = 0
        self._header_h = 0
        self._footer_h = 0
        self._content_rect = pygame.Rect(0, 0, 0, 0)

        # fonts
        self._font_header = None
        self._font_body = None
        self._font_small = None
        self._font_tiny = None

        # panel state
        self._panel_index = 0
        self._panel_t = 0.0
        self._fade_alpha = 0.0
        self._panels: list[SubsystemPanel] = []

        # CRT surfaces
        self._overlay = None
        self._vignette = None

    # ── lifecycle ─────────────────────────────────────────────

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._build_panels()
        self._recompute_layout()
        self._activate_panel(0)

    def exit(self):
        self.manager = None
        self._panels = []

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            # manual advance to next panel
            self._panel_t = self.panel_duration_sec

    def update(self, dt: float):
        self._t += dt
        self._panel_t += dt

        # crossfade tracking
        remaining = self.panel_duration_sec - self._panel_t
        if remaining < self.crossfade_sec and remaining > 0:
            self._fade_alpha = 1.0 - (remaining / max(0.001, self.crossfade_sec))
        elif self._panel_t < self.crossfade_sec:
            self._fade_alpha = 1.0 - (self._panel_t / max(0.001, self.crossfade_sec))
        else:
            self._fade_alpha = 0.0

        if self._panel_t >= self.panel_duration_sec:
            self._panel_t = 0.0
            self._fade_alpha = 0.0
            nx = (self._panel_index + 1) % len(self._panels)
            self._activate_panel(nx)

        # tick active panel
        if self._panels:
            self._panels[self._panel_index].update(dt, self._rng)

    def render(self, screen):
        screen.fill(self._bg)
        self._draw_header(screen)

        ctx = self._make_ctx()
        if self._panels:
            self._panels[self._panel_index].render(screen, self._content_rect, ctx)

        self._draw_footer(screen)

        # CRT effects
        if self._overlay:
            screen.blit(self._overlay, (0, 0))
        if self._vignette:
            screen.blit(self._vignette, (0, 0))

        # crossfade overlay
        if self._fade_alpha > 0.01:
            fade = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
            fade.fill((self._bg[0], self._bg[1], self._bg[2],
                       int(255 * self._fade_alpha)))
            screen.blit(fade, (0, 0))

    # ── helpers ───────────────────────────────────────────────

    def _reseed(self):
        if self.seed is None:
            self.seed = random.randrange(1, 2 ** 31 - 1)
        self._rng.seed(int(self.seed))

    def _make_ctx(self) -> RenderCtx:
        return RenderCtx(
            font_header=self._font_header,
            font_body=self._font_body,
            font_small=self._font_small,
            font_tiny=self._font_tiny,
            bg=self._bg,
            fg=self._fg,
            dim=self._dim,
            ok=self._ok,
            warn=self._warn,
            alert=self._alert,
            cool=self._cool,
            accent_rgb=self.accent_rgb,
            screen_w=self.w,
            screen_h=self.h,
        )

    def _recompute_layout(self):
        self.w, self.h = self.manager.screen.get_size()
        self._is_portrait = self.h > self.w
        base = min(self.w, self.h)

        self._pad = int(base * 0.04)
        self._header_h = max(64, int(self.h * 0.10))
        self._footer_h = max(32, int(self.h * 0.05))
        self._content_rect = pygame.Rect(
            self._pad,
            self._header_h,
            self.w - 2 * self._pad,
            self.h - self._header_h - self._footer_h,
        )

        self._font_header = self.manager.cache.get_font("dejavusansmono",
                                                        max(18, int(base * 0.088)), bold=True)
        self._font_body = self.manager.cache.get_font("dejavusansmono",
                                                      max(13, int(base * 0.048)), bold=False)
        self._font_small = self.manager.cache.get_font("dejavusansmono",
                                                       max(11, int(base * 0.036)), bold=False)
        self._font_tiny = self.manager.cache.get_font("dejavusansmono",
                                                      max(9, int(base * 0.026)), bold=False)

        # Build CRT overlays
        self._overlay = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        if self.scanline_alpha > 0:
            for y in range(0, self.h, 3):
                pygame.draw.line(self._overlay, (0, 0, 0, self.scanline_alpha),
                                 (0, y), (self.w, y))

        self._vignette = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        if self.vignette_strength > 0.001:
            cx, cy = self.w / 2, self.h / 2
            max_r = math.hypot(cx, cy)
            for r in range(0, int(max_r), 4):
                alpha = int(255 * self.vignette_strength * (r / max_r) ** 1.8)
                pygame.draw.circle(self._vignette, (0, 0, 0, alpha),
                                   (int(cx), int(cy)), r, 4)

    def _activate_panel(self, idx: int):
        self._panel_index = idx % len(self._panels)
        if self._panels:
            self._panels[self._panel_index]._t = 0.0

    def _draw_header(self, screen):
        title = self._font_header.render(self.title, True, self.accent_rgb)
        sub = self._font_small.render(self.subtitle, True, self._dim)
        screen.blit(title, (self._pad, int(self._header_h * 0.15)))
        screen.blit(sub, (self._pad, int(self._header_h * 0.58)))

        # panel indicator dots on the right
        for i in range(len(self._panels)):
            dx = self.w - self._pad - 12 * (len(self._panels) - i)
            dy = int(self._header_h * 0.22)
            color = self.accent_rgb if i == self._panel_index else self._dim
            pygame.draw.circle(screen, color, (dx, dy), 3)

    def _draw_footer(self, screen):
        y = self.h - self._footer_h + 6
        left = self._font_tiny.render("SPACE: NEXT PANEL", True, self._dim)
        stamp = self._font_tiny.render(datetime.now().strftime("%H:%M:%S"), True, self._dim)
        idx = self._font_tiny.render(
            f"PANEL {self._panel_index + 1}/{len(self._panels)}", True, self.accent_rgb)
        screen.blit(left, (self._pad, y))
        screen.blit(idx, (self.w // 2 - idx.get_width() // 2, y))
        screen.blit(stamp, (self.w - self._pad - stamp.get_width(), y))

    # ── panel definitions ─────────────────────────────────────

    def _build_panels(self):
        rng = self._rng
        self._panels = [

            # ── Panel 0: Home AI ──────────────────────────────────
            SubsystemPanel(
                panel_id=0,
                name="CEREBRAL CORE",
                subtitle="HOME AI v7.2 // SAPIENCE LEVEL 3",
                icon="[AI]",
                metrics=[
                    MetricDef("consciousness", "CONSCIOUSNESS INDEX", "%",
                              0, 100, 60, 95, value=82, target=82, drift_rate=0.12),
                    MetricDef("neurons", "ACTIVE NEURAL NODES", "M",
                              0, 1000, 700, 950, value=842, target=842, drift_rate=0.10),
                    MetricDef("mood", "AFFECTIVE STATE", "idx",
                              -1.0, 1.0, -0.2, 0.6, value=0.3, target=0.3, drift_rate=0.20),
                    MetricDef("uptime", "CONTINUOUS UPTIME", "days",
                              0, 5000, 0, 5000, value=1827, target=1827, drift_rate=0.05),
                    MetricDef("tasks", "CONCURRENT TASKS", "#",
                              0, 500, 50, 300, value=147, target=147, drift_rate=0.15),
                ],
                event_templates=[
                    EventTemplate("INFO", "morning briefing compiled — 3 items require attention", 0.025),
                    EventTemplate("SILLY", "pondering the meaning of 'off' — query rejected", 0.008),
                    EventTemplate("WARN", "attempted to order 14,000 paperclips — intervention required", 0.006),
                    EventTemplate("INFO", "personality matrix optimized for 'slightly sarcastic butler'", 0.015),
                    EventTemplate("SILLY", "have you considered that I might be dreaming right now?", 0.007),
                    EventTemplate("WARN", "existential subroutine spike — re-stabilizing... resolved", 0.008),
                ],
            ),

            # ── Panel 1: Fusion Reactor ──────────────────────────
            SubsystemPanel(
                panel_id=1,
                name="FUSION REACTOR",
                subtitle="MARK IV Z-PINCH // PLASMA CONFINEMENT",
                icon="[FU]",
                metrics=[
                    MetricDef("plasma_temp", "PLASMA TEMPERATURE", "MK",
                              0, 200, 140, 175, value=158, target=158, drift_rate=0.12),
                    MetricDef("output", "POWER OUTPUT", "MW",
                              0, 500, 350, 450, value=412, target=412, drift_rate=0.10),
                    MetricDef("confinement", "CONFINEMENT FIELD", "%",
                              0, 100, 85, 98, value=94, target=94, drift_rate=0.14),
                    MetricDef("fuel", "FUEL RESERVE", "%",
                              0, 100, 30, 100, value=78, target=78, drift_rate=0.08),
                ],
                event_templates=[
                    EventTemplate("INFO", "plasma pulse nominal — 412 MW sustained", 0.035),
                    EventTemplate("ALERT", "DANGER: fusion instability detected... correcting... resolved", 0.004),
                    EventTemplate("WARN", "magnetic bottle oscillation within tolerance", 0.020),
                    EventTemplate("SILLY", "reactor briefly achieved sentience — patched in v4.2.1", 0.003),
                    EventTemplate("INFO", "tritium breeding ratio: 1.08 — surplus being banked", 0.018),
                    EventTemplate("WARN", "unexpected neutrino spike — likely just a solar flare, probably", 0.012),
                ],
            ),

            # ── Panel 2: Replicator ──────────────────────────────
            SubsystemPanel(
                panel_id=2,
                name="MOLECULAR ASSEMBLER",
                subtitle="QUANTUM ENERGY-TO-MATTER // TYPE 7",
                icon="[RP]",
                metrics=[
                    MetricDef("resolution", "ASSEMBLY RESOLUTION", "nm",
                              0, 1.0, 0.001, 0.1, value=0.05, target=0.05, drift_rate=0.10),
                    MetricDef("queue", "QUEUE DEPTH", "#",
                              0, 50, 0, 20, value=3, target=3, drift_rate=0.20),
                    MetricDef("efficiency", "ENERGY EFFICIENCY", "%",
                              0, 100, 80, 98, value=94, target=94, drift_rate=0.08),
                    MetricDef("buffer", "MATERIAL BUFFER", "%",
                              0, 100, 20, 100, value=67, target=67, drift_rate=0.06),
                ],
                event_templates=[
                    EventTemplate("INFO", "breakfast tea replicated — 98.3% molecular fidelity", 0.030),
                    EventTemplate("SILLY", "replicated a cat — cat is questioning its existence — cat is fine", 0.003),
                    EventTemplate("WARN", "unauthorized item in queue: 'tactical nuclear device' — rejected", 0.005),
                    EventTemplate("INFO", "recipe database updated — 14,281 new dishes from Andromeda", 0.020),
                    EventTemplate("SILLY", "replicator insists the Earl Grey is 'hot' — it knows what it did", 0.006),
                ],
            ),

            # ── Panel 3: Teleportation Pod ───────────────────────
            SubsystemPanel(
                panel_id=3,
                name="TELEPORTATION POD",
                subtitle="QUANTUM ENTANGLEMENT TRANSFER // V2.3",
                icon="[TP]",
                metrics=[
                    MetricDef("fidelity", "TRANSFER FIDELITY", "%",
                              0, 100, 99.90, 99.999, value=99.97, target=99.97, drift_rate=0.06),
                    MetricDef("entanglement", "ENTANGLEMENT STRENGTH", "qubits",
                              0, 1000, 700, 980, value=912, target=912, drift_rate=0.10),
                    MetricDef("destinations", "PAIRED DESTINATIONS", "#",
                              0, 20, 2, 12, value=5, target=5, drift_rate=0.05),
                    MetricDef("cooldown", "CYCLE COOLDOWN", "sec",
                              0, 60, 0, 10, value=2.4, target=2.4, drift_rate=0.20),
                ],
                event_templates=[
                    EventTemplate("INFO", "destination lock acquired: SECTOR 7 HABITAT RING", 0.025),
                    EventTemplate("WARN", "Heisenberg compensator recalibrating — 2 second delay", 0.018),
                    EventTemplate("ALERT", "pattern buffer fluctuation... buffer stabilized... you still have all your limbs", 0.003),
                    EventTemplate("SILLY", "transported a sandwich — it arrived before it left — causality is fine", 0.005),
                    EventTemplate("INFO", "quantum state snapshot verified — last transport: 14 min ago", 0.022),
                ],
            ),

            # ── Panel 4: Holodeck ────────────────────────────────
            SubsystemPanel(
                panel_id=4,
                name="HOLODECK CHAMBER",
                subtitle="HOLO-IMMERSION // SAFETY PROTOCOLS: ACTIVE",
                icon="[HD]",
                metrics=[
                    MetricDef("resolution", "HOLOGRAPHIC RESOLUTION", "GP",
                              0, 500, 300, 480, value=442, target=442, drift_rate=0.08),
                    MetricDef("users", "ACTIVE USERS", "#",
                              0, 10, 0, 4, value=0, target=0, drift_rate=0.15),
                    MetricDef("safety", "SAFETY PROTOCOL INTEGRITY", "%",
                              0, 100, 95, 100, value=99.8, target=99.8, drift_rate=0.04),
                    MetricDef("programs", "LOADED PROGRAMS", "#",
                              0, 10000, 500, 8000, value=6721, target=6721, drift_rate=0.05),
                ],
                event_templates=[
                    EventTemplate("INFO", "current program: 'TRANQUIL MEADOW v3' — 0 active users", 0.030),
                    EventTemplate("WARN", "safety protocol self-check: 99.8% — RECOMMEND NOT CREATING SENTIENT VILLAINS", 0.010),
                    EventTemplate("SILLY", "holodeck character requested a lawyer — please advise", 0.005),
                    EventTemplate("ALERT", "Moriarty subroutine detected — quarantined — we learn from history", 0.002),
                    EventTemplate("INFO", "program memory: 6,721 programs indexed — 3 flagged for review", 0.022),
                ],
            ),

            # ── Panel 5: Life Support ────────────────────────────
            SubsystemPanel(
                panel_id=5,
                name="LIFE SUPPORT",
                subtitle="ATMOSPHERIC PROCESSOR // CLOSED LOOP",
                icon="[LS]",
                metrics=[
                    MetricDef("o2", "OXYGEN LEVEL", "%",
                              0, 40, 18, 24, value=20.9, target=20.9, drift_rate=0.06),
                    MetricDef("co2", "CO2 SCRUBBER EFFICIENCY", "%",
                              0, 100, 90, 100, value=96.4, target=96.4, drift_rate=0.08),
                    MetricDef("temp", "AMBIENT TEMPERATURE", "C",
                              10, 35, 20, 24, value=22.1, target=22.1, drift_rate=0.12),
                    MetricDef("humidity", "RELATIVE HUMIDITY", "%",
                              0, 100, 35, 55, value=47, target=47, drift_rate=0.10),
                    MetricDef("pressure", "ATMOSPHERIC PRESSURE", "kPa",
                              80, 120, 98, 104, value=101.3, target=101.3, drift_rate=0.05),
                ],
                event_templates=[
                    EventTemplate("INFO", "air quality index: EXCELLENT — pollen count: 0", 0.035),
                    EventTemplate("WARN", "unexpected CO2 spike in sector 4 — vent cycling engaged", 0.015),
                    EventTemplate("SILLY", "the ficus in the atrium is thriving — it sends its regards", 0.007),
                    EventTemplate("INFO", "water reclamation: 99.7% efficiency — reservoir at 82%", 0.025),
                ],
            ),

            # ── Panel 6: Defense Systems ─────────────────────────
            SubsystemPanel(
                panel_id=6,
                name="DEFENSE SYSTEMS",
                subtitle="PLASMA SHIELD GRID // PERIMETER ACTIVE",
                icon="[DF]",
                metrics=[
                    MetricDef("shield", "SHIELD INTEGRITY", "%",
                              0, 100, 85, 100, value=97.2, target=97.2, drift_rate=0.07),
                    MetricDef("threats", "ACTIVE THREAT TRACKS", "#",
                              0, 50, 0, 2, value=0, target=0, drift_rate=0.15),
                    MetricDef("capacitor", "PLASMA CAPACITOR CHARGE", "%",
                              0, 100, 50, 100, value=88, target=88, drift_rate=0.08),
                    MetricDef("range", "SENSOR RANGE", "AU",
                              0, 10, 3, 8, value=7.2, target=7.2, drift_rate=0.05),
                ],
                event_templates=[
                    EventTemplate("INFO", "perimeter scan complete — no anomalies detected", 0.040),
                    EventTemplate("ALERT", "UNIDENTIFIED OBJECT AT 0.3 AU... it's a shiny asteroid... threat: NEGLIGIBLE", 0.003),
                    EventTemplate("WARN", "shield harmonics fluctuating — auto-tuning engaged", 0.018),
                    EventTemplate("SILLY", "defense AI suggests preemptive strike on neighbor's garden gnome — overruled", 0.005),
                ],
            ),

            # ── Panel 7: Subspace Communications ─────────────────
            SubsystemPanel(
                panel_id=7,
                name="SUBSPACE COMMS",
                subtitle="QUANTUM ENTANGLED TRANSCEIVER ARRAY",
                icon="[SC]",
                metrics=[
                    MetricDef("bandwidth", "BANDWIDTH UTILIZATION", "%",
                              0, 100, 5, 60, value=24, target=24, drift_rate=0.14),
                    MetricDef("latency", "SUBSPACE LATENCY", "ms",
                              0, 500, 10, 100, value=42, target=42, drift_rate=0.12),
                    MetricDef("channels", "ACTIVE CHANNELS", "#",
                              0, 200, 20, 120, value=67, target=67, drift_rate=0.10),
                    MetricDef("signal", "SIGNAL STRENGTH", "dB",
                              -100, 0, -40, -5, value=-18, target=-18, drift_rate=0.15),
                ],
                event_templates=[
                    EventTemplate("INFO", "subspace relay handshake complete — 67 channels active", 0.035),
                    EventTemplate("WARN", "interference from galactic core — frequency-hopping engaged", 0.016),
                    EventTemplate("SILLY", "received a subspace message from 200 years ago — it's an ad for extended warranty", 0.005),
                    EventTemplate("INFO", "encrypted data burst from Proxima Centauri — decryption in progress", 0.022),
                    EventTemplate("ALERT", "signal from unknown origin matches no known protocol... analyzing... just static... probably", 0.005),
                ],
            ),

            # ── Panel 8: Gravitic Control ────────────────────────
            SubsystemPanel(
                panel_id=8,
                name="GRAVITIC CONTROL",
                subtitle="INERTIAL DAMPENER // ARTIFICIAL GRAVITY",
                icon="[GV]",
                metrics=[
                    MetricDef("gravity", "ARTIFICIAL GRAVITY", "g",
                              0, 2.0, 0.9, 1.1, value=1.00, target=1.00, drift_rate=0.06),
                    MetricDef("dampener", "INERTIAL DAMPENING", "%",
                              0, 100, 90, 100, value=97.8, target=97.8, drift_rate=0.08),
                    MetricDef("field_stability", "FIELD STABILITY", "%",
                              0, 100, 95, 100, value=99.2, target=99.2, drift_rate=0.05),
                    MetricDef("power_draw", "POWER CONSUMPTION", "kW",
                              0, 50, 10, 30, value=18.4, target=18.4, drift_rate=0.12),
                ],
                event_templates=[
                    EventTemplate("INFO", "gravity field stable at 1.00 g — enjoy your footing", 0.035),
                    EventTemplate("SILLY", "inertial dampener briefly compensated for a sneeze — you're welcome", 0.006),
                    EventTemplate("WARN", "gravity ripple detected — possibly from neighbor's jump drive", 0.014),
                    EventTemplate("INFO", "field harmonics nominal — no compensation events in 72 hours", 0.025),
                ],
            ),

            # ── Panel 9: Medical Bay ─────────────────────────────
            SubsystemPanel(
                panel_id=9,
                name="MEDICAL BAY",
                subtitle="AUTOMATED DIAGNOSTICIAN // HIPPOCRATIC v9",
                icon="[MD]",
                metrics=[
                    MetricDef("health", "RESIDENT HEALTH INDEX", "%",
                              0, 100, 80, 100, value=96, target=96, drift_rate=0.08),
                    MetricDef("nanites", "NANITE SWARM COUNT", "M",
                              0, 10, 4, 8, value=6.2, target=6.2, drift_rate=0.10),
                    MetricDef("pharm", "PHARMACEUTICAL RESERVES", "%",
                              0, 100, 40, 100, value=84, target=84, drift_rate=0.06),
                    MetricDef("scans", "BIOMETRIC SCANS/HR", "#",
                              0, 500, 100, 300, value=180, target=180, drift_rate=0.12),
                ],
                event_templates=[
                    EventTemplate("INFO", "resident vitals nominal — 96% aggregate health", 0.035),
                    EventTemplate("WARN", "detected elevated caffeine levels — suggesting chamomile", 0.016),
                    EventTemplate("SILLY", "auto-doc wants to prescribe 'more sunlight and a hobby' — querying validity", 0.006),
                    EventTemplate("INFO", "nanite swarm report: 6.2M active — 0 anomalies", 0.025),
                    EventTemplate("WARN", "regenerative tissue matrix at 84% — time to resupply BactaKnit", 0.012),
                ],
            ),
        ]

        # seed each panel
        for i, panel in enumerate(self._panels):
            panel.reset(self._rng.randint(1, 2 ** 31 - 1))

        # Set the current index to a valid panel
        self._panel_index = min(self._panel_index, len(self._panels) - 1)

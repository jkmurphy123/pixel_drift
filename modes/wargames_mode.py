# modes/wargames_mode.py
#
# WarGames — WOPR "big board" nuclear war scenario simulator.
#
# Explicitly make-believe: Cold-War-movie scenarios, round-number casualty
# fiction, and every run ends the same way — WINNER: NONE. The finale
# quote (after a full cycle through every scenario) is the movie's:
# "THE ONLY WINNING MOVE IS NOT TO PLAY."
#
# Content lives in data/wargames_scenarios.json; adding a scenario is
# pure JSON authoring (validated on load, invalid ones skipped with one
# log line — never crashes the kiosk).
#
# Controls: SPACE = fast-forward current scenario to its outcome.

import math
import os
from datetime import datetime, timezone

import pygame

from core import mapdraw
from core.mapdata import load_coastlines
from core.wargames_sim import Simulation, estimate_fatalities, load_scenarios

_DEFAULT_SCENARIO_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "wargames_scenarios.json")
)

QUOTE_LINES = ["THE ONLY WINNING MOVE", "IS NOT TO PLAY."]


class WarGamesMode:
    """
    Config (all optional):
      - title
      - scenario_file (default: bundled data/wargames_scenarios.json)
      - scenario_id (loop just this one scenario; default: cycle all)
      - speed: simulation time multiplier (default 1.0)
      - seed: jitter determinism (default 1983)
      - accent_rgb, scanline_alpha
      - hold_on_outcome_s (default 6), hold_on_quote_s (default 10)
    """

    # Phases of the per-scenario state machine.
    INTRO, RUN, OUTCOME, QUOTE = range(4)

    def __init__(self, config: dict):
        self.title = str(config.get("title", "WOPR // GLOBAL THERMONUCLEAR WAR"))
        self.scenario_file = str(config.get("scenario_file", _DEFAULT_SCENARIO_FILE))
        self.scenario_id = config.get("scenario_id", None)
        self.speed = max(0.25, float(config.get("speed", 1.0)))
        self.seed = config.get("seed", 1983)
        self.accent_rgb = tuple(config.get("accent_rgb", [255, 204, 132]))
        self.scanline_alpha = int(config.get("scanline_alpha", 0))
        self.hold_on_outcome_s = float(config.get("hold_on_outcome_s", 6.0))
        self.hold_on_quote_s = float(config.get("hold_on_quote_s", 10.0))

        self.manager = None
        self.w = 0
        self.h = 0

        # Palette — phosphor console, consistent with tracker/mission control
        self._bg = (6, 7, 8)
        self._fg = (232, 226, 214)
        self._dim = (132, 128, 118)
        self._ok = (124, 255, 158)
        self._warn = (255, 210, 104)
        self._alert = (255, 112, 112)
        self._panel_edge = (70, 74, 78)
        self._map_land = (96, 110, 98)
        self._map_grid = (40, 45, 48)
        self._fallout = (255, 170, 60)  # permanent post-impact marker

        # Layout
        self._pad = 0
        self._header_h = 0
        self._footer_h = 0
        self._map_rect = pygame.Rect(0, 0, 0, 0)
        self._scenario_rect = pygame.Rect(0, 0, 0, 0)
        self._stats_rect = pygame.Rect(0, 0, 0, 0)
        self._log_rect = pygame.Rect(0, 0, 0, 0)

        self._font_header = None
        self._font_big = None
        self._font_body = None
        self._font_small = None
        self._font_tiny = None
        self._scanlines = None

        # Scenario state
        self.scenarios = []
        self._scenario_index = 0
        self.sim = None
        self.phase = self.INTRO
        self._phase_t = 0.0     # wall-clock seconds in current phase
        self._sim_t = 0.0       # simulation seconds (advance by dt * speed)
        self._event_cursor = 0.0
        self._log = []          # [(text, color)]
        self._detonations = []  # [{lat, lon, t0, yield_kt, name}]
        self._impacted = set()  # missile ids already turned into detonations
        self._final_stats = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def enter(self, manager):
        self.manager = manager
        self._recompute_layout()
        self._build_scanlines()
        self._load_scenarios()
        self._start_scenario(0)

    def exit(self):
        self.manager = None
        self.sim = None
        self._detonations = []
        self._log = []
        self._scanlines = None

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            if self.phase == self.RUN and self.sim is not None:
                self._sim_t = self.sim.duration  # fast-forward to the end

    def _load_scenarios(self):
        try:
            scenarios, errors = load_scenarios(self.scenario_file)
        except Exception as e:
            print(f"[WarGames] scenario file unreadable: {e}")
            scenarios, errors = [], [str(e)]
        for err in errors:
            print(f"[WarGames] scenario skipped: {err}")
        if self.scenario_id is not None:
            scenarios = [s for s in scenarios if s["id"] == self.scenario_id]
            if not scenarios:
                print(f"[WarGames] scenario_id '{self.scenario_id}' not found")
        self.scenarios = scenarios

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def _start_scenario(self, index):
        if not self.scenarios:
            self.sim = None
            self.phase = self.RUN
            return
        self._scenario_index = index % len(self.scenarios)
        sc = self.scenarios[self._scenario_index]
        self.sim = Simulation(sc, seed=self.seed)
        self.phase = self.INTRO
        self._phase_t = 0.0
        self._sim_t = 0.0
        self._event_cursor = 0.0
        self._detonations = []
        self._impacted = set()
        self._final_stats = None
        self._log_event(f"SCENARIO LOADED: {sc['name']}", self.accent_rgb)

    def _advance_phase(self):
        if self.phase == self.INTRO:
            self.phase = self.RUN
            self._phase_t = 0.0
            self._log_event("SIMULATION RUNNING", self._dim)
        elif self.phase == self.RUN:
            self._final_stats = self.sim.state_at(self.sim.duration + 1)
            self.phase = self.OUTCOME
            self._phase_t = 0.0
            self._log_event(self.sim.outcome_text(), self._alert)
        elif self.phase == self.OUTCOME:
            if self._scenario_index + 1 >= len(self.scenarios):
                # Full cycle complete — the only place the quote appears.
                self.phase = self.QUOTE
                self._phase_t = 0.0
            else:
                self._start_scenario(self._scenario_index + 1)
        elif self.phase == self.QUOTE:
            self._start_scenario(0)

    def update(self, dt: float):
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            self._build_scanlines()

        self._phase_t += dt

        if self.phase == self.INTRO:
            # Typewriter: name then description, then auto-start.
            if self.sim is not None:
                full = self.sim.name + "|" + self.sim.description
                if self._typed_len(full) >= len(full) and self._phase_t > self._intro_hold():
                    self._advance_phase()
        elif self.phase == self.RUN:
            if self.sim is None:
                return
            prev = self._sim_t
            self._sim_t = min(self._sim_t + dt * self.speed, self.sim.duration + 0.5)
            for e in self.sim.events_between(self._event_cursor, self._sim_t):
                color = self._alert if e.kind == "impact" else self._warn
                self._log_event(e.text, color)
            self._event_cursor = self._sim_t
            self._spawn_detonations(prev, self._sim_t)
            if self._sim_t >= self.sim.duration:
                self._advance_phase()
        elif self.phase == self.OUTCOME:
            if self._phase_t >= self.hold_on_outcome_s:
                self._advance_phase()
        elif self.phase == self.QUOTE:
            if self._phase_t >= self.hold_on_quote_s:
                self._advance_phase()

    def _intro_hold(self):
        full = (self.sim.name + "|" + self.sim.description) if self.sim else ""
        return len(full) / 40.0 + 2.0  # typing time + dwell

    def _typed_len(self, text):
        return min(len(text), int(self._phase_t * 40.0))

    def _spawn_detonations(self, t0, t1):
        for i, m in enumerate(self.sim.missiles):
            if i in self._impacted or not (t0 < m.impact_t <= t1):
                continue
            self._impacted.add(i)
            lat, lon, _ = m.arc[-1]
            self._detonations.append({
                "lat": lat, "lon": lon, "t0": m.impact_t,
                "yield_kt": m.yield_kt, "name": m.target_name,
            })

    def _log_event(self, text, color=None):
        self._log.append((text, color or self._fg))
        self._log = self._log[-30:]

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
        self._font_big = c.get_font("dejavusansmono", max(24, int(base * 0.06)), bold=True)
        self._font_body = c.get_font("dejavusansmono", max(13, int(base * 0.023)), bold=False)
        self._font_small = c.get_font("dejavusansmono", max(11, int(base * 0.017)), bold=False)
        self._font_tiny = c.get_font("dejavusansmono", max(10, int(base * 0.014)), bold=False)

        mr = pygame.Rect(self._pad, self._header_h,
                         self.w - 2 * self._pad,
                         self.h - self._header_h - self._footer_h - self._pad)
        gap = 8
        if self.h > self.w:  # portrait: stacked
            map_h = int(mr.height * 0.46)
            sc_h = int(mr.height * 0.20)
            st_h = int(mr.height * 0.18)
            self._map_rect = pygame.Rect(mr.left, mr.top, mr.width, map_h)
            self._scenario_rect = pygame.Rect(mr.left, self._map_rect.bottom + gap, mr.width, sc_h)
            self._stats_rect = pygame.Rect(mr.left, self._scenario_rect.bottom + gap, mr.width, st_h)
            self._log_rect = pygame.Rect(mr.left, self._stats_rect.bottom + gap, mr.width,
                                         mr.bottom - self._stats_rect.bottom - gap)
        else:
            map_w = int(mr.width * 0.68)
            sc_h = int(mr.height * 0.30)
            st_h = int(mr.height * 0.34)
            self._map_rect = pygame.Rect(mr.left, mr.top, map_w, mr.height)
            rx = self._map_rect.right + gap
            rw = mr.right - rx
            self._scenario_rect = pygame.Rect(rx, mr.top, rw, sc_h)
            self._stats_rect = pygame.Rect(rx, self._scenario_rect.bottom + gap, rw, st_h)
            self._log_rect = pygame.Rect(rx, self._stats_rect.bottom + gap, rw,
                                         mr.bottom - self._stats_rect.bottom - gap)

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
        self._draw_scenario_panel(screen)
        self._draw_stats_panel(screen)
        self._draw_log_panel(screen)
        self._draw_footer(screen)
        if self.phase == self.OUTCOME:
            self._draw_outcome_card(screen)
        elif self.phase == self.QUOTE:
            self._draw_quote_card(screen)
        if self._scanlines is not None:
            screen.blit(self._scanlines, (0, 0))

    def _panel_box(self, screen, rect, title):
        pygame.draw.rect(screen, (10, 12, 13), rect)
        pygame.draw.rect(screen, self._panel_edge, rect, 1)
        label = self._font_tiny.render(title, True, self.accent_rgb)
        screen.blit(label, (rect.left + 10, rect.top - label.get_height() // 2))
        pygame.draw.rect(screen, (6, 7, 8),
                         (rect.left + 8, rect.top - label.get_height() // 2 - 1,
                          label.get_width() + 4, label.get_height() + 2))
        screen.blit(label, (rect.left + 10, rect.top - label.get_height() // 2))

    def _draw_header(self, screen):
        y = self._pad // 2
        title = self._font_header.render(self.title, True, self._fg)
        screen.blit(title, (self._pad, y))
        if self.scenarios:
            tag = self._font_body.render(
                f"SCENARIO {self._scenario_index + 1}/{len(self.scenarios)}",
                True, self.accent_rgb)
            screen.blit(tag, (self.w - self._pad - tag.get_width(),
                              y + (title.get_height() - tag.get_height()) // 2))
        line_y = self._header_h - 6
        pygame.draw.line(screen, self._panel_edge,
                         (self._pad, line_y), (self.w - self._pad, line_y), 1)

    # ----- map -----

    def _draw_map_panel(self, screen):
        rect = self._map_rect
        self._panel_box(screen, rect, "GLOBAL THREAT BOARD")
        inner = rect.inflate(-16, -14)
        inner.top += 8
        pygame.draw.rect(screen, (8, 10, 12), inner)
        pygame.draw.rect(screen, self._panel_edge, inner, 1)

        prev_clip = screen.get_clip()
        screen.set_clip(inner)

        for i in range(1, 6):
            x = inner.left + int(inner.width * i / 6)
            pygame.draw.line(screen, self._map_grid, (x, inner.top), (x, inner.bottom), 1)
        for i in range(1, 4):
            y = inner.top + int(inner.height * i / 4)
            pygame.draw.line(screen, self._map_grid, (inner.left, y), (inner.right, y), 1)

        coastlines = load_coastlines()
        if coastlines:
            for line in coastlines:
                pts = [mapdraw.latlon_to_xy(inner, lat, lon) for lon, lat in line]
                if len(pts) >= 2:
                    pygame.draw.lines(screen, self._map_land, False, pts, 1)

        if self.sim is None:
            msg = self._font_body.render("NO VALID SCENARIOS", True, self._alert)
            screen.blit(msg, (inner.centerx - msg.get_width() // 2,
                              inner.centery - msg.get_height() // 2))
        else:
            self._draw_missiles(screen, inner)
            self._draw_detonations(screen, inner)

        screen.set_clip(prev_clip)

    def _draw_missiles(self, screen, rect):
        if self.phase == self.INTRO:
            return
        for m in self.sim.missiles:
            p = m.progress(self._sim_t)
            if p is None:
                continue
            side_color = tuple(self.sim.sides[m.side]["color"])
            # Trail: the portion of the arc already traversed, dim.
            upto = max(2, int(p * (len(m.arc) - 1)) + 1)
            trail = [(pt[0], pt[1]) for pt in m.arc[:upto]]
            dim = tuple(c // 3 for c in side_color)
            mapdraw.draw_latlon_polyline(screen, rect, trail, dim, 1)
            # Head: bright dot + glow ring at current position.
            lat, lon, alt = m.arc[upto - 1]
            x, y = mapdraw.latlon_to_xy(rect, lat, lon)
            pygame.draw.circle(screen, side_color, (x, y), 4, 1)
            pygame.draw.circle(screen, self._fg, (x, y), 2)

    def _draw_detonations(self, screen, rect):
        for d in self._detonations:
            x, y = mapdraw.latlon_to_xy(rect, d["lat"], d["lon"])
            age = self._sim_t - d["t0"]
            max_r = 10 + d["yield_kt"] / 40.0

            if age < 0.25:
                # White flash
                r = int(6 + 14 * (age / 0.25))
                pygame.draw.circle(screen, (255, 255, 255), (x, y), r)
            elif age < 1.6:
                # Expanding ring with ease-out, fading
                k = (age - 0.25) / 1.35
                r = int(max_r * (1 - (1 - k) ** 2))
                fade = max(60, int(255 * (1 - k)))
                pygame.draw.circle(screen, (fade, fade, fade), (x, y), max(2, r), 1)
                pygame.draw.circle(screen, self._fallout, (x, y), 2)
            else:
                # Permanent fallout marker — the accumulating damage.
                pygame.draw.circle(screen, self._fallout, (x, y), 3)

            # City label pops briefly on impact.
            if 0 <= age < 2.5 and d["name"] != "IMPACT":
                tag = self._font_tiny.render(d["name"], True, self._fallout)
                screen.blit(tag, (x + 8, y - tag.get_height() // 2))

    # ----- side panels -----

    def _draw_scenario_panel(self, screen):
        rect = self._scenario_rect
        self._panel_box(screen, rect, "SCENARIO")
        inner = rect.inflate(-20, -18)
        y = inner.top + 8

        if self.sim is None:
            screen.blit(self._font_small.render("check data/wargames_scenarios.json",
                                                True, self._dim), (inner.left, y))
            return

        name = self.sim.name
        desc = self.sim.description
        if self.phase == self.INTRO:
            typed = self._typed_len(name + "|" + desc)
            name_len = min(len(name), typed)
            name = name[:name_len]
            desc = desc[:max(0, typed - len(self.sim.name) - 1)]

        surf = self._font_body.render(name, True, self.accent_rgb)
        screen.blit(surf, (inner.left, y))
        y += self._font_body.get_linesize() + 8

        # Word-wrap the description
        for line in self._wrap(desc, self._font_small, inner.width):
            if y + self._font_small.get_linesize() > inner.bottom - 30:
                break
            screen.blit(self._font_small.render(line, True, self._dim), (inner.left, y))
            y += self._font_small.get_linesize() + 4

        # DEFCON indicator pinned to the bottom of the panel.
        if self.phase in (self.RUN, self.OUTCOME):
            defcon = self.sim.defcon_at(self._sim_t)
        else:
            defcon = 5
        color = self._ok if defcon >= 4 else self._warn if defcon >= 2 else self._alert
        tag = self._font_big.render(f"DEFCON {defcon}", True, color)
        screen.blit(tag, (inner.left, inner.bottom - tag.get_height() - 4))

    def _draw_stats_panel(self, screen):
        rect = self._stats_rect
        self._panel_box(screen, rect, "STATISTICS")
        inner = rect.inflate(-20, -18)
        y = inner.top + 8
        dy = self._font_small.get_linesize() + 7

        stats = (self.sim.state_at(self._sim_t) if self.sim is not None
                 and self.phase != self.INTRO else None)

        def row(label, value, color=None):
            nonlocal y
            if y + dy > inner.bottom:
                return
            screen.blit(self._font_small.render(label, True, self.accent_rgb), (inner.left, y))
            screen.blit(self._font_small.render(value, True, color or self._fg),
                        (inner.left + int(inner.width * 0.52), y))
            y += dy

        if stats is None:
            row("STATUS", "STANDBY", self._dim)
            return

        for side, meta in self.sim.sides.items():
            n = stats.launched.get(side, 0)
            row(f"{meta['label']} LAUNCHED", str(n), tuple(meta["color"]))
        row("IN FLIGHT", str(stats.in_flight), self._warn if stats.in_flight else self._fg)
        row("DETONATIONS", str(stats.detonations),
            self._alert if stats.detonations else self._fg)
        row("CITIES HIT", str(len(stats.cities_hit)))
        row("EST. FATALITIES", f"{stats.fatalities:,}",
            self._alert if stats.fatalities else self._fg)

    def _draw_log_panel(self, screen):
        rect = self._log_rect
        self._panel_box(screen, rect, "EVENT LOG")
        inner = rect.inflate(-20, -18)
        line_h = self._font_small.get_linesize() + 5
        max_lines = max(1, (inner.height - 8) // line_h)
        y = inner.bottom - line_h
        for text, color in reversed(self._log[-max_lines:]):
            screen.blit(self._font_small.render(text, True, color), (inner.left, y))
            y -= line_h

    def _draw_footer(self, screen):
        y = self.h - self._footer_h + (self._footer_h - self._font_small.get_linesize()) // 2
        now = datetime.now(timezone.utc)
        clock = self._font_small.render(now.strftime("GMT %d %b %Y  %H:%M:%S"), True, self._dim)
        screen.blit(clock, (self._pad, y))
        right = self._font_small.render(
            "SIMULATION — ALL SCENARIOS FICTIONAL   [SPACE] FAST-FORWARD",
            True, self._dim)
        screen.blit(right, (self.w - self._pad - right.get_width(), y))

    # ----- cards -----

    def _draw_card(self, screen, lines, big_first=True):
        """Dimmed centered overlay card over the whole window."""
        overlay = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        screen.blit(overlay, (0, 0))

        card_w = int(self.w * 0.62)
        card_h = int(self.h * 0.42)
        card = pygame.Rect(0, 0, card_w, card_h)
        card.center = (self.w // 2, self.h // 2)
        pygame.draw.rect(screen, (10, 12, 13), card)
        pygame.draw.rect(screen, self._panel_edge, card, 2)

        total_h = sum(f.get_linesize() + 10 for f, _ in lines)
        y = card.centery - total_h // 2
        for font, (text, color) in lines:
            surf = font.render(text, True, color)
            screen.blit(surf, (card.centerx - surf.get_width() // 2, y))
            y += font.get_linesize() + 10

    def _draw_outcome_card(self, screen):
        stats = self._final_stats or self.sim.state_at(self.sim.duration + 1)
        name = self.sim.name
        # Typewriter effect on the verdict.
        verdict = self.sim.outcome_text()
        typed = verdict[:min(len(verdict), int(self._phase_t * 18))]
        self._draw_card(screen, [
            (self._font_body, (f"SCENARIO: {name}", self._dim)),
            (self._font_big, (typed, self._alert)),
            (self._font_body, (f"DETONATIONS {stats.detonations}   "
                               f"CITIES HIT {len(stats.cities_hit)}", self._fg)),
            (self._font_body, (f"EST. FATALITIES {stats.fatalities:,}", self._fg)),
        ])

    def _draw_quote_card(self, screen):
        # The quote appears only here — after every scenario has run.
        full = QUOTE_LINES[0] + "|" + QUOTE_LINES[1]
        typed = min(len(full), int(self._phase_t * 20))
        line1 = QUOTE_LINES[0][:min(len(QUOTE_LINES[0]), typed)]
        line2 = QUOTE_LINES[1][:max(0, typed - len(QUOTE_LINES[0]) - 1)]
        lines = [(self._font_big, (line1, self._fg))]
        if line2:
            lines.append((self._font_big, (line2, self.accent_rgb)))
        lines.append((self._font_small, ("— JOSHUA, WOPR (1983)", self._dim)))
        self._draw_card(screen, lines)

    # ----- helpers -----

    def _wrap(self, text, font, width):
        words = text.split()
        lines, cur = [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if font.size(trial)[0] <= width:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

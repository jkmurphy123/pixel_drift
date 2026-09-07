# cold_war_command_room_wall_mode.py

import math
import random
from dataclasses import dataclass
from datetime import datetime

import pygame


@dataclass
class Blip:
    x: float  # 0..1 in radar rect
    y: float
    ttl: float
    r: float


@dataclass
class LogLine:
    t_end: float
    text: str
    kind: str  # INFO/WARN/ALERT


class ColdWarCommandRoomWallMode:
    """
    Cold-War Command Room Wall
    - Portrait-friendly situation display: world grid + radar scopes
    - DEFCON ladder (1..5), occasional drift events
    - Indicator lamps + teletype log
    - Subtle scanlines/noise/vignette (no geometry bulge)

    Config (optional):
      - title (str)
      - room_name (str)
      - accent_rgb ([r,g,b])
      - seed (int)
      - refresh_hz (float)
      - portrait_layout (bool)
      - scanline_alpha (int 0..255)
      - noise_alpha (int 0..255)
      - vignette_strength (float 0..1)
      - defcon_start (int 1..5)
      - defcon_drift_probability_per_min (float)
      - radar_count (int 1..3)
      - blip_rate (float) blips/sec across all radars
      - lamp_count (int)
      - show_teletype (bool)
      - log_interval_range ([min,max] sec)
    """

    def __init__(self, config: dict):
        self.title = str(config.get("title", "COLD-WAR COMMAND ROOM WALL"))
        self.room_name = str(config.get("room_name", "SITUATION ROOM"))
        self.accent_rgb = tuple(config.get("accent_rgb", [255, 210, 140]))

        self.seed = config.get("seed", None)
        self.refresh_hz = float(config.get("refresh_hz", 60.0))
        self.portrait_layout = bool(config.get("portrait_layout", True))

        self.scanline_alpha = int(config.get("scanline_alpha", 10))
        self.noise_alpha = int(config.get("noise_alpha", 10))
        self.vignette_strength = float(config.get("vignette_strength", 0.30))

        self.defcon = int(config.get("defcon_start", 3))
        self.defcon = max(1, min(5, self.defcon))
        self.defcon_drift_probability_per_min = float(config.get("defcon_drift_probability_per_min", 0.5))

        self.radar_count = int(config.get("radar_count", 2))
        self.radar_count = max(1, min(3, self.radar_count))
        self.blip_rate = float(config.get("blip_rate", 0.8))

        self.lamp_count = int(config.get("lamp_count", 10))
        self.lamp_count = max(4, min(16, self.lamp_count))

        self.show_teletype = bool(config.get("show_teletype", True))
        self.log_interval_range = config.get("log_interval_range", [1.0, 2.2])

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
        self._map_rect = pygame.Rect(0, 0, 0, 0)
        self._right_rect = pygame.Rect(0, 0, 0, 0)
        self._defcon_rect = pygame.Rect(0, 0, 0, 0)
        self._radar_rects: list[pygame.Rect] = []
        self._lamp_rect = pygame.Rect(0, 0, 0, 0)
        self._log_rect = pygame.Rect(0, 0, 0, 0)

        # fonts
        self._font_header = None
        self._font_body = None
        self._font_small = None
        self._font_tiny = None

        # state
        self._blips: list[list[Blip]] = [[] for _ in range(self.radar_count)]
        self._logs: list[LogLine] = []
        self._next_log_t = 0.0
        self._lamp_states = [False] * self.lamp_count
        self._lamp_phases = [0.0] * self.lamp_count

        # overlay
        self._overlay = None
        self._vignette = None

    # ---------- lifecycle ----------

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._recompute_layout()
        self._build_overlays()
        self._schedule_log()
        self._push_log("INFO", "command wall online")
        self._push_log("INFO", "uplink: secure line established")
        self._push_log("INFO", f"defcon set to {self.defcon}")

    def exit(self):
        self.manager = None
        self._blips = [[] for _ in range(self.radar_count)]
        self._logs = []
        self._overlay = None
        self._vignette = None

    def handle_event(self, event):
        # SPACE: cycle DEFCON (demo)
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self.defcon = 1 if self.defcon == 5 else self.defcon + 1
            self._push_log("WARN", f"manual override: defcon -> {self.defcon}")

    def update(self, dt: float):
        self._t += dt

        # resize/hotplug
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            self._build_overlays()

        # teletype logs
        self._logs = [l for l in self._logs if l.t_end > self._t][-14:]
        if self.show_teletype and self._t >= self._next_log_t:
            self._generate_log_line()
            self._schedule_log()

        # DEFCON drift events
        p = max(0.0, self.defcon_drift_probability_per_min) / 60.0
        if self._rng.random() < p * dt:
            self._defcon_drift()

        # radar blips
        self._spawn_blips(dt)
        self._tick_blips(dt)

        # lamps
        self._tick_lamps(dt)

    def render(self, screen: pygame.Surface):
        screen.fill((0, 0, 0))

        self._draw_header(screen)
        self._draw_map(screen)
        self._draw_right_stack(screen)
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
        self._footer_h = max(44, int(self.h * 0.06))

        content = pygame.Rect(
            self._pad,
            self._header_h,
            self.w - 2 * self._pad,
            self.h - self._header_h - self._footer_h
        )

        # portrait: big map on top, right stack below (like a wall panel)
        if self.h > self.w or self.portrait_layout:
            map_h = int(content.height * 0.54)
            self._map_rect = pygame.Rect(content.left, content.top, content.width, map_h)
            self._right_rect = pygame.Rect(content.left, self._map_rect.bottom + 10, content.width, content.height - map_h - 10)
        else:
            # landscape: map left, stack right
            right_w = int(content.width * 0.38)
            self._map_rect = pygame.Rect(content.left, content.top, content.width - right_w - 10, content.height)
            self._right_rect = pygame.Rect(self._map_rect.right + 10, content.top, right_w, content.height)

        # right stack sections
        rr = self._right_rect
        def_h = int(rr.height * 0.30)
        lamp_h = int(rr.height * 0.18)
        radar_h = int(rr.height * (0.34 if self.show_teletype else 0.52))
        log_h = rr.height - def_h - lamp_h - radar_h - 20

        self._defcon_rect = pygame.Rect(rr.left, rr.top, rr.width, def_h)
        self._lamp_rect = pygame.Rect(rr.left, self._defcon_rect.bottom + 10, rr.width, lamp_h)

        radar_top = self._lamp_rect.bottom + 10
        self._radar_rects = []
        if self.radar_count == 1:
            self._radar_rects.append(pygame.Rect(rr.left, radar_top, rr.width, radar_h))
        else:
            gap = 10
            each = (radar_h - (self.radar_count - 1) * gap) // self.radar_count
            for i in range(self.radar_count):
                self._radar_rects.append(pygame.Rect(rr.left, radar_top + i * (each + gap), rr.width, each))

        self._log_rect = pygame.Rect(rr.left, self._radar_rects[-1].bottom + 10, rr.width, max(0, log_h))

        # fonts
        self._font_header = self.manager.cache.get_font("dejavusansmono", max(18, int(base * 0.050)), bold=True)
        self._font_body = self.manager.cache.get_font("dejavusansmono", max(14, int(base * 0.028)), bold=False)
        self._font_small = self.manager.cache.get_font("dejavusansmono", max(12, int(base * 0.020)), bold=False)
        self._font_tiny = self.manager.cache.get_font("dejavusansmono", max(10, int(base * 0.017)), bold=False)

        # ensure blip lists match radar_count
        if len(self._blips) != self.radar_count:
            self._blips = [[] for _ in range(self.radar_count)]

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

    # ---------- logs ----------

    def _schedule_log(self):
        mn, mx = float(self.log_interval_range[0]), float(self.log_interval_range[1])
        self._next_log_t = self._t + self._rng.uniform(mn, mx)

    def _push_log(self, kind: str, text: str):
        ttl = 11.0 if kind == "INFO" else 14.0
        self._logs.append(LogLine(t_end=self._t + ttl, text=text, kind=kind))

    def _generate_log_line(self):
        choices = [
            ("INFO", "satcom relay: stable"),
            ("INFO", "air filtration: nominal"),
            ("INFO", "tape deck: indexing"),
            ("INFO", "cipher wheel: advanced"),
            ("INFO", "sector scan: no contacts"),
            ("WARN", "burst noise detected on channel 3"),
            ("WARN", "checksum mismatch: packet discarded"),
            ("WARN", "operator console 2: idle timeout"),
            ("ALERT", "unknown transponder ping"),
            ("ALERT", "priority message: verify chain of command"),
        ]
        kind, msg = self._rng.choice(choices)
        if kind == "ALERT" and self._rng.random() < 0.55:
            msg += f" (defcon {self.defcon})"
        self._push_log(kind, msg)

    # ---------- defcon ----------

    def _defcon_drift(self):
        # drift by +-1 with bias toward calm, but sometimes… not.
        if self.defcon > 1 and self._rng.random() < 0.25:
            self.defcon -= 1
            self._push_log("ALERT", f"status escalation: defcon -> {self.defcon}")
        elif self.defcon < 5 and self._rng.random() < 0.55:
            self.defcon += 1
            self._push_log("WARN", f"status relaxation: defcon -> {self.defcon}")

    # ---------- radar blips ----------

    def _spawn_blips(self, dt: float):
        rate = max(0.0, self.blip_rate)
        n = int(rate * dt)
        if self._rng.random() < (rate * dt - n):
            n += 1

        for _ in range(n):
            rix = self._rng.randrange(0, self.radar_count)
            self._blips[rix].append(
                Blip(
                    x=self._rng.random(),
                    y=self._rng.random(),
                    ttl=self._rng.uniform(1.2, 3.2),
                    r=self._rng.uniform(1.0, 2.4),
                )
            )

    def _tick_blips(self, dt: float):
        for i in range(self.radar_count):
            keep = []
            for b in self._blips[i]:
                b.ttl -= dt
                if b.ttl > 0:
                    keep.append(b)
            self._blips[i] = keep

    # ---------- lamps ----------

    def _tick_lamps(self, dt: float):
        for i in range(self.lamp_count):
            self._lamp_phases[i] += dt * self._rng.uniform(0.8, 1.6)
            # blink probability depends on defcon (more tense -> more activity)
            base = 0.10 + (5 - self.defcon) * 0.06
            if self._rng.random() < base * dt:
                self._lamp_states[i] = not self._lamp_states[i]

    # ---------- drawing ----------

    def _draw_header(self, screen: pygame.Surface):
        band = pygame.Surface((self.w, self._header_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, 0))

        t1 = self._font_header.render(self.title, True, self.accent_rgb)
        screen.blit(t1, (self._pad, int(self._header_h * 0.18)))

        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        sub = self._font_small.render(f"{self.room_name}   |   UTC {ts}   |   SECURE MODE: ON", True, (150, 150, 150))
        screen.blit(sub, (self._pad, int(self._header_h * 0.18) + t1.get_height() + 6))

        pygame.draw.line(screen, (150, 150, 150), (self._pad, self._header_h - 2), (self.w - self._pad, self._header_h - 2), 2)

    def _draw_footer(self, screen: pygame.Surface):
        y0 = self.h - self._footer_h
        band = pygame.Surface((self.w, self._footer_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, y0))

        hint = "SPACE: cycle DEFCON (demo)   |   turn knob: change modes"
        s = self._font_small.render(hint, True, (150, 150, 150))
        screen.blit(s, (self._pad, y0 + (self._footer_h - s.get_height()) // 2))

    def _draw_panel_frame(self, screen: pygame.Surface, rect: pygame.Rect, label: str):
        pygame.draw.rect(screen, (0, 0, 0), rect)
        pygame.draw.rect(screen, (*self.accent_rgb, 150), rect, 2)
        lab = self._font_tiny.render(label, True, (150, 150, 150))
        screen.blit(lab, (rect.left + 10, rect.top + 8))

    def _draw_map(self, screen: pygame.Surface):
        r = self._map_rect
        self._draw_panel_frame(screen, r, "WORLD GRID / TRACKING OVERLAY")

        inner = r.inflate(-18, -30)
        inner.top += 18

        # grid
        step_x = max(28, int(inner.width * 0.10))
        step_y = max(28, int(inner.height * 0.10))
        for x in range(inner.left, inner.right, step_x):
            pygame.draw.line(screen, (*self.accent_rgb, 22), (x, inner.top), (x, inner.bottom), 1)
        for y in range(inner.top, inner.bottom, step_y):
            pygame.draw.line(screen, (*self.accent_rgb, 22), (inner.left, y), (inner.right, y), 1)

        # “lat/long” labels
        for i, lon in enumerate([-120, -60, 0, 60, 120]):
            x = inner.left + int((i / 4) * inner.width)
            s = self._font_tiny.render(f"{lon:+d}", True, (150, 150, 150))
            screen.blit(s, (x - s.get_width() // 2, inner.bottom - s.get_height()))

        # sweeping “search line”
        sweep = 0.5 + 0.5 * math.sin(self._t * 0.35)
        sx = inner.left + int(sweep * inner.width)
        pygame.draw.line(screen, (*self.accent_rgb, 90), (sx, inner.top), (sx, inner.bottom), 2)

        # pseudo “contacts” as tiny crosses based on defcon (higher tension -> more marks)
        marks = 4 + (5 - self.defcon) * 4
        for k in range(marks):
            u = (0.15 + 0.70 * ((k * 0.17 + 0.11 * math.sin(self._t * 0.4)) % 1.0))
            v = (0.20 + 0.60 * ((k * 0.29 + 0.07 * math.cos(self._t * 0.3)) % 1.0))
            x = inner.left + int(u * inner.width)
            y = inner.top + int(v * inner.height)
            pygame.draw.line(screen, (*self.accent_rgb, 140), (x - 5, y), (x + 5, y), 2)
            pygame.draw.line(screen, (*self.accent_rgb, 140), (x, y - 5), (x, y + 5), 2)

    def _draw_right_stack(self, screen: pygame.Surface):
        # DEFCON
        self._draw_panel_frame(screen, self._defcon_rect, "DEFCON STATUS")
        self._draw_defcon(screen, self._defcon_rect)

        # lamps
        self._draw_panel_frame(screen, self._lamp_rect, "INDICATOR LAMPS")
        self._draw_lamps(screen, self._lamp_rect)

        # radars
        for i, rr in enumerate(self._radar_rects):
            self._draw_panel_frame(screen, rr, f"RADAR SCOPE {i+1}")
            self._draw_radar(screen, rr, i)

        # teletype
        if self.show_teletype and self._log_rect.height > 20:
            self._draw_panel_frame(screen, self._log_rect, "TELETYPE")
            self._draw_log(screen, self._log_rect)

    def _draw_defcon(self, screen: pygame.Surface, rect: pygame.Rect):
        inner = rect.inflate(-18, -30)
        inner.top += 18

        # ladder: 5 rows, 1 at top (worst)
        row_h = inner.height // 5
        for i in range(5):
            level = i + 1
            y = inner.top + i * row_h
            box = pygame.Rect(inner.left, y + 2, inner.width, row_h - 4)

            active = (level == self.defcon)
            # colors: lower number -> more red
            if level <= 2:
                col = (255, 140, 140)
            elif level == 3:
                col = (255, 210, 140)
            else:
                col = (200, 255, 210)

            pygame.draw.rect(screen, (*col, 60 if not active else 120), box, border_radius=8)
            pygame.draw.rect(screen, (*col, 180), box, 2, border_radius=8)

            label = self._font_body.render(f"DEFCON {level}", True, col if active else (150, 150, 150))
            screen.blit(label, (box.left + 12, box.top + (box.height - label.get_height()) // 2))

            if active:
                # subtle pulse band
                a = int(80 + 60 * (0.5 + 0.5 * math.sin(self._t * 6.0)))
                band = pygame.Surface((box.width, box.height), pygame.SRCALPHA)
                band.fill((*col, int(a * 0.18)))
                screen.blit(band, box.topleft)

    def _draw_lamps(self, screen: pygame.Surface, rect: pygame.Rect):
        inner = rect.inflate(-18, -30)
        inner.top += 18

        cols = min(self.lamp_count, 8)
        rows = math.ceil(self.lamp_count / cols)
        gap = 10
        lamp_d = max(10, min(22, int(min(inner.width / max(1, cols), inner.height / max(1, rows)) * 0.55)))

        idx = 0
        for r in range(rows):
            for c in range(cols):
                if idx >= self.lamp_count:
                    return
                x = inner.left + c * ((inner.width - (cols - 1) * gap) / max(1, cols - 1)) if cols > 1 else inner.centerx
                y = inner.top + r * ((inner.height - (rows - 1) * gap) / max(1, rows - 1)) if rows > 1 else inner.centery
                x = int(x)
                y = int(y)

                on = self._lamp_states[idx]
                phase = self._lamp_phases[idx]
                pulse = 0.5 + 0.5 * math.sin(self._t * 5.0 + phase)

                if on:
                    col = self.accent_rgb
                    a = int(120 + 90 * pulse)
                else:
                    col = (90, 90, 90)
                    a = 80

                pygame.draw.circle(screen, (*col, a), (x, y), lamp_d)
                pygame.draw.circle(screen, (*self.accent_rgb, 120), (x, y), lamp_d, 2)

                idx += 1

    def _draw_radar(self, screen: pygame.Surface, rect: pygame.Rect, radar_index: int):
        inner = rect.inflate(-18, -30)
        inner.top += 18

        # make square-ish scope centered
        size = min(inner.width, inner.height)
        scope = pygame.Rect(0, 0, size, size)
        scope.center = inner.center

        # rings
        cx, cy = scope.center
        for i in range(1, 5):
            pygame.draw.circle(screen, (*self.accent_rgb, 28), (cx, cy), int((i / 5) * (size // 2)), 1)
        pygame.draw.line(screen, (*self.accent_rgb, 28), (cx, scope.top), (cx, scope.bottom), 1)
        pygame.draw.line(screen, (*self.accent_rgb, 28), (scope.left, cy), (scope.right, cy), 1)

        # sweep arm
        ang = (self._t * (0.7 + 0.12 * radar_index)) % math.tau
        x2 = cx + int(math.cos(ang) * (size * 0.48))
        y2 = cy + int(math.sin(ang) * (size * 0.48))
        pygame.draw.line(screen, (*self.accent_rgb, 140), (cx, cy), (x2, y2), 2)

        # sweep wedge fade
        wedge = pygame.Surface((scope.width, scope.height), pygame.SRCALPHA)
        for k in range(18):
            a = int(85 * (1.0 - k / 18))
            aa = ang - k * 0.06
            x3 = scope.centerx - scope.left + int(math.cos(aa) * (size * 0.48))
            y3 = scope.centery - scope.top + int(math.sin(aa) * (size * 0.48))
            pygame.draw.line(wedge, (*self.accent_rgb, a), (scope.centerx - scope.left, scope.centery - scope.top), (x3, y3), 2)
        screen.blit(wedge, scope.topleft)

        # blips
        for b in self._blips[radar_index]:
            bx = scope.left + int(b.x * scope.width)
            by = scope.top + int(b.y * scope.height)
            a = int(220 * max(0.0, min(1.0, b.ttl / 3.2)))
            pygame.draw.circle(screen, (*self.accent_rgb, a), (bx, by), int(b.r))
            pygame.draw.circle(screen, (*self.accent_rgb, min(255, a)), (bx, by), int(b.r + 3), 1)

        # label
        s = self._font_tiny.render("A-SCOPE / CONTACTS", True, (150, 150, 150))
        screen.blit(s, (inner.left + 4, inner.top + 4))

    def _draw_log(self, screen: pygame.Surface, rect: pygame.Rect):
        inner = rect.inflate(-18, -30)
        inner.top += 18

        x = inner.left + 4
        y = inner.top + 8

        for l in self._logs[::-1][:10]:
            if l.kind == "ALERT":
                col = (255, 140, 140)
            elif l.kind == "WARN":
                col = (255, 210, 140)
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

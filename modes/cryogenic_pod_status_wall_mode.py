# cryogenic_pod_status_wall_mode.py

import math
import random
from dataclasses import dataclass
from datetime import datetime

import pygame


@dataclass
class Pod:
    pod_id: int
    status: str  # STABLE / THAWING / ALERT / MAINT
    temp_c: float
    pressure_kpa: float
    o2_pct: float
    hr_bpm: float
    neural_mv: float
    frost: float  # 0..1
    phase: float  # animation phase


@dataclass
class FrostParticle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    size: float
    a: int


class CryogenicPodStatusWallMode:
    """
    Cryogenic Pod Status Wall (portrait-friendly)
    - Dense grid of pods with vitals, gauges, status chips
    - Frost particles drifting downward
    - Occasional alarm pulse on a random pod

    Config (optional):
      - title (str)
      - accent_rgb ([r,g,b])
      - refresh_hz (float): target fps-ish update cadence (used only for internal tuning)
      - num_pods (int): number of pods shown
      - columns_portrait (int)
      - columns_landscape (int)
      - pod_spacing_scale (float): spacing relative to min(w,h)
      - label_font_scale (float)
      - value_font_scale (float)
      - header_font_scale (float)
      - footer_font_scale (float)
      - frost_particle_rate (float): particles/sec
      - alarm_probability_per_min (float)
      - seed (int)
    """

    def __init__(self, config: dict):
        self.title = str(config.get("title", "CRYOGENIC POD STATUS WALL"))
        self.accent_rgb = tuple(config.get("accent_rgb", [90, 220, 255]))
        self.refresh_hz = float(config.get("refresh_hz", 60.0))

        self.num_pods = int(config.get("num_pods", 12))
        self.columns_portrait = int(config.get("columns_portrait", 2))
        self.columns_landscape = int(config.get("columns_landscape", 3))
        self.pod_spacing_scale = float(config.get("pod_spacing_scale", 0.030))

        self.label_font_scale = float(config.get("label_font_scale", 0.020))
        self.value_font_scale = float(config.get("value_font_scale", 0.028))
        self.header_font_scale = float(config.get("header_font_scale", 0.050))
        self.footer_font_scale = float(config.get("footer_font_scale", 0.018))

        self.frost_particle_rate = float(config.get("frost_particle_rate", 45.0))
        self.alarm_probability_per_min = float(config.get("alarm_probability_per_min", 0.7))

        self.seed = config.get("seed", None)

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
        self._grid_rect = pygame.Rect(0, 0, 0, 0)

        # fonts
        self._font_label = None
        self._font_value = None
        self._font_header = None
        self._font_footer = None

        # state
        self._t = 0.0
        self._rng = random.Random()
        self._pods: list[Pod] = []
        self._particles: list[FrostParticle] = []

        # alarm state
        self._alarm_pod = None
        self._alarm_t = 999.0
        self._alarm_dur = 0.0

        # cached overlay (grid lines / subtle rings)
        self._overlay = None

    # ---------- lifecycle ----------

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._recompute_layout()
        self._build_overlay()
        self._init_pods()

    def exit(self):
        self.manager = None
        self._pods = []
        self._particles = []
        self._overlay = None

    def handle_event(self, event):
        # SPACE: force an alarm (handy for testing)
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self._start_alarm(force=True)

    def update(self, dt: float):
        self._t += dt

        # Handle resolution changes (hotplug / rotation). Same approach as your other modes. :contentReference[oaicite:5]{index=5}
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            self._build_overlay()

        # Alarm events
        p = max(0.0, self.alarm_probability_per_min) / 60.0
        if (self._alarm_t >= self._alarm_dur) and (self._rng.random() < p * dt):
            self._start_alarm(force=False)

        self._alarm_t += dt
        if self._alarm_t >= self._alarm_dur:
            self._alarm_pod = None

        # Update pod vitals
        self._tick_pods(dt)

        # Frost particles
        self._spawn_particles(dt)
        self._tick_particles(dt)

    def render(self, screen: pygame.Surface):
        screen.fill(self._bg)

        self._draw_header(screen)
        self._draw_grid(screen)
        self._draw_footer(screen)

        if self._overlay is not None:
            screen.blit(self._overlay, (0, 0))

    # ---------- layout ----------

    def _recompute_layout(self):
        self.w, self.h = self.manager.screen.get_size()
        self._is_portrait = self.h > self.w

        self._pad = int(min(self.w, self.h) * 0.05)
        self._header_h = max(84, int(self.h * 0.14))   # portrait: taller header reads better
        self._footer_h = max(42, int(self.h * 0.06))

        self._grid_rect = pygame.Rect(
            self._pad,
            self._header_h,
            self.w - 2 * self._pad,
            self.h - self._header_h - self._footer_h
        )

        # Fonts scale off width in portrait for legibility (similar logic to your portrait handling). :contentReference[oaicite:6]{index=6}
        base = min(self.w, self.h)
        fs_label = max(12, int(base * self.label_font_scale))
        fs_value = max(14, int(base * self.value_font_scale))
        fs_head = max(18, int(base * self.header_font_scale))
        fs_foot = max(12, int(base * self.footer_font_scale))

        self._font_label = self.manager.cache.get_font("dejavusansmono", fs_label, bold=False)
        self._font_value = self.manager.cache.get_font("dejavusansmono", fs_value, bold=True)
        self._font_header = self.manager.cache.get_font("dejavusansmono", fs_head, bold=True)
        self._font_footer = self.manager.cache.get_font("dejavusansmono", fs_foot, bold=False)

    def _build_overlay(self):
        self._overlay = None
        return
        # subtle “facility glass” border rings + a faint vertical gradient feel
        self._overlay = pygame.Surface((self.w, self.h), pygame.SRCALPHA)

        rings = 60
        for i in range(rings):
            a = int(2.4 * i)
            pygame.draw.rect(self._overlay, (0, 0, 0, a), pygame.Rect(i, i, self.w - 2 * i, self.h - 2 * i), 1)

        # faint grid lines in the main grid region
        gx = self._grid_rect
        step_y = max(40, int(gx.height * 0.06))
        for y in range(gx.top, gx.bottom, step_y):
            pygame.draw.line(self._overlay, (*self.accent_rgb, 22), (gx.left, y), (gx.right, y), 1)

    # ---------- pods ----------

    def _init_pods(self):
        self._pods = []
        for i in range(self.num_pods):
            status = self._rng.choices(
                ["STABLE", "MAINT", "THAWING"],
                weights=[0.80, 0.12, 0.08],
                k=1
            )[0]
            self._pods.append(
                Pod(
                    pod_id=100 + i,
                    status=status,
                    temp_c=self._rng.uniform(-196.0, -140.0),
                    pressure_kpa=self._rng.uniform(92.0, 108.0),
                    o2_pct=self._rng.uniform(18.5, 21.0),
                    hr_bpm=self._rng.uniform(32.0, 58.0),
                    neural_mv=self._rng.uniform(0.3, 1.2),
                    frost=self._rng.uniform(0.35, 0.95),
                    phase=self._rng.uniform(0.0, math.tau),
                )
            )

    def _tick_pods(self, dt: float):
        for p in self._pods:
            # gentle drift
            p.phase += dt * self._rng.uniform(0.5, 1.2)

            # temp: stable pods hover colder; thawing creep upward
            if p.status == "THAWING":
                p.temp_c += dt * self._rng.uniform(0.6, 1.6)
                p.hr_bpm += dt * self._rng.uniform(0.6, 1.2)
                p.o2_pct += dt * self._rng.uniform(-0.10, 0.10)
                p.frost = max(0.05, p.frost - dt * 0.08)
            elif p.status == "MAINT":
                p.temp_c += dt * self._rng.uniform(-0.2, 0.2)
                p.hr_bpm += dt * self._rng.uniform(-0.3, 0.3)
                p.frost = max(0.05, p.frost - dt * 0.02)
            else:  # STABLE
                p.temp_c += dt * self._rng.uniform(-0.25, 0.25)
                p.hr_bpm += dt * self._rng.uniform(-0.25, 0.25)
                p.o2_pct += dt * self._rng.uniform(-0.05, 0.05)

            # pressure / neural micro jitter
            p.pressure_kpa += dt * self._rng.uniform(-0.20, 0.20)
            p.neural_mv += dt * self._rng.uniform(-0.04, 0.04)

            # clamp
            p.temp_c = max(-210.0, min(-20.0, p.temp_c))
            p.pressure_kpa = max(80.0, min(130.0, p.pressure_kpa))
            p.o2_pct = max(16.0, min(23.0, p.o2_pct))
            p.hr_bpm = max(18.0, min(120.0, p.hr_bpm))
            p.neural_mv = max(0.0, min(2.5, p.neural_mv))

            # if in alarm, a pod becomes ALERT
            if self._alarm_pod == p.pod_id:
                p.status = "ALERT"

            # recover after alarm
            if (self._alarm_pod is None) and p.status == "ALERT":
                p.status = "STABLE"

    def _start_alarm(self, force: bool):
        if not self._pods:
            return
        pick = self._rng.choice(self._pods)
        self._alarm_pod = pick.pod_id
        self._alarm_t = 0.0
        self._alarm_dur = self._rng.uniform(2.0, 4.0) if not force else 3.0

        # shove vitals slightly to look “real”
        pick.pressure_kpa += self._rng.uniform(-6.0, 6.0)
        pick.o2_pct += self._rng.uniform(-1.0, 0.6)
        pick.hr_bpm += self._rng.uniform(8.0, 22.0)

    # ---------- particles ----------

    def _spawn_particles(self, dt: float):
        # spawn more near top of grid, drifting down like cold vapor
        rate = max(0.0, self.frost_particle_rate)
        count = int(rate * dt)
        # fractional spawn
        if self._rng.random() < (rate * dt - count):
            count += 1

        for _ in range(count):
            x = self._rng.uniform(self._grid_rect.left, self._grid_rect.right)
            y = self._rng.uniform(self._grid_rect.top, self._grid_rect.top + self._grid_rect.height * 0.25)
            vx = self._rng.uniform(-12.0, 12.0)
            vy = self._rng.uniform(25.0, 65.0)
            life = self._rng.uniform(0.8, 1.8)
            size = self._rng.uniform(1.0, 2.8)
            a = self._rng.randint(25, 80)
            self._particles.append(FrostParticle(x, y, vx, vy, life, size, a))

        # cap
        if len(self._particles) > 900:
            self._particles = self._particles[-700:]

    def _tick_particles(self, dt: float):
        keep = []
        for p in self._particles:
            p.life -= dt
            if p.life <= 0:
                continue
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.vx += math.sin(self._t * 1.3 + p.x * 0.01) * dt * 8.0
            p.vy += dt * 6.0
            if p.y < self.h + 10:
                keep.append(p)
        self._particles = keep

    # ---------- drawing ----------

    def _draw_header(self, screen: pygame.Surface):
        band = pygame.Surface((self.w, self._header_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, 0))

        t1 = self._font_header.render(self.title, True, self.accent_rgb)
        screen.blit(t1, (self._pad, int(self._header_h * 0.18)))

        # small line of system text
        sub = self._font_footer.render(
            f"FACILITY: ORBITAL-12    SECTOR: CRYO BAY A    HEARTBEAT: {int(60 + 6*math.sin(self._t*0.9))} bpm",
            True,
            self._dim
        )
        screen.blit(sub, (self._pad, int(self._header_h * 0.18) + t1.get_height() + 6))

        # right-side timestamp
        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        r = self._font_footer.render(f"UTC {ts}", True, self._dim)
        screen.blit(r, (self.w - self._pad - r.get_width(), int(self._header_h * 0.18)))

        pygame.draw.line(screen, self._dim, (self._pad, self._header_h - 2), (self.w - self._pad, self._header_h - 2), 2)

    def _draw_footer(self, screen: pygame.Surface):
        y0 = self.h - self._footer_h
        band = pygame.Surface((self.w, self._footer_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, y0))

        hint = "SPACE: trigger alert   |   turn knob: change modes"
        s = self._font_footer.render(hint, True, self._dim)
        screen.blit(s, (self._pad, y0 + (self._footer_h - s.get_height()) // 2))

    def _draw_grid(self, screen: pygame.Surface):
        # particles behind pods
        for fp in self._particles:
            pygame.draw.circle(screen, (255, 255, 255, fp.a), (int(fp.x), int(fp.y)), int(fp.size))

        cols = self.columns_portrait if self._is_portrait else self.columns_landscape
        cols = max(1, int(cols))
        rows = max(1, math.ceil(self.num_pods / cols))

        gap = int(min(self.w, self.h) * self.pod_spacing_scale)
        gap = max(8, gap)

        cell_w = (self._grid_rect.width - (cols - 1) * gap) // cols
        cell_h = (self._grid_rect.height - (rows - 1) * gap) // rows

        idx = 0
        for r in range(rows):
            for c in range(cols):
                if idx >= self.num_pods:
                    break
                x = self._grid_rect.left + c * (cell_w + gap)
                y = self._grid_rect.top + r * (cell_h + gap)
                rect = pygame.Rect(x, y, cell_w, cell_h)

                self._draw_pod(screen, rect, self._pods[idx])
                idx += 1

    def _draw_pod(self, screen: pygame.Surface, rect: pygame.Rect, pod: Pod):
        # panel
        pygame.draw.rect(screen, (0, 0, 0), rect)
        pygame.draw.rect(screen, (*self.accent_rgb, 120), rect, 2)

        # frost overlay (simple alpha fog)
        frost_a = int(40 + 120 * pod.frost)
        fog = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        fog.fill((255, 255, 255, int(frost_a * 0.12)))
        # diagonal “ice streaks”
        for i in range(0, rect.width, max(18, rect.width // 12)):
            a = int(10 + 26 * pod.frost)
            pygame.draw.line(fog, (255, 255, 255, a), (i, 0), (i - rect.height // 2, rect.height), 1)
        screen.blit(fog, rect.topleft)

        # status chip
        status = pod.status
        if status == "ALERT":
            chip = (255, 120, 120)
        elif status == "THAWING":
            chip = (255, 210, 140)
        elif status == "MAINT":
            chip = (180, 180, 180)
        else:
            chip = (160, 255, 200)

        chip_rect = pygame.Rect(rect.left + 10, rect.top + 10, min(150, rect.width - 20), 26)
        pygame.draw.rect(screen, (*chip, 40), chip_rect, border_radius=6)
        pygame.draw.rect(screen, (*chip, 180), chip_rect, 2, border_radius=6)

        st = self._font_label.render(status, True, chip)
        screen.blit(st, (chip_rect.left + 8, chip_rect.top + 4))

        # pod id top-right
        pid = self._font_label.render(f"POD {pod.pod_id}", True, self._dim)
        screen.blit(pid, (rect.right - 10 - pid.get_width(), rect.top + 14))

        # vitals region
        left = rect.left + 12
        top = rect.top + 44
        line = self._font_label.get_linesize() + 3

        # values with subtle pulsing
        pulse = 0.5 + 0.5 * math.sin(self._t * 2.6 + pod.phase)

        def value_color(base):
            # brighten slightly with pulse
            return (
                min(255, int(base[0] * (0.92 + 0.16 * pulse))),
                min(255, int(base[1] * (0.92 + 0.16 * pulse))),
                min(255, int(base[2] * (0.92 + 0.16 * pulse))),
            )

        # labels + values
        self._draw_kv(screen, left, top + line * 0, "TEMP", f"{pod.temp_c:6.1f} C", value_color(self.accent_rgb))
        self._draw_kv(screen, left, top + line * 1, "PRESS", f"{pod.pressure_kpa:6.1f} kPa", self._fg)
        self._draw_kv(screen, left, top + line * 2, "O2", f"{pod.o2_pct:5.1f} %", self._fg)
        self._draw_kv(screen, left, top + line * 3, "HR", f"{pod.hr_bpm:5.0f} bpm", value_color((255, 210, 160)))
        self._draw_kv(screen, left, top + line * 4, "NEURAL", f"{pod.neural_mv:4.2f} mV", self._fg)

        # gauge bars at bottom
        g_h = 10
        g_y = rect.bottom - 14 - g_h
        g_w = rect.width - 24

        # temp gauge maps -200..-20 -> 0..1
        tnorm = (pod.temp_c - (-200.0)) / (180.0)
        tnorm = max(0.0, min(1.0, tnorm))
        self._draw_gauge(screen, rect.left + 12, g_y, g_w, g_h, tnorm, label="TEMP")

        # alarm pulse outline
        if self._alarm_pod == pod.pod_id and self._alarm_t < self._alarm_dur:
            a = int(120 + 90 * (0.5 + 0.5 * math.sin(self._alarm_t * 10.0)))
            pygame.draw.rect(screen, (255, 80, 80, a), rect, 4)

    def _draw_kv(self, screen, x, y, k, v, vcol):
        ks = self._font_label.render(f"{k:6s}", True, self._dim)
        vs = self._font_value.render(v, True, vcol)
        screen.blit(ks, (x, y))
        screen.blit(vs, (x + 92, y - 2))

    def _draw_gauge(self, screen, x, y, w, h, frac, label=""):
        pygame.draw.rect(screen, (*self.accent_rgb, 80), pygame.Rect(x, y, w, h), 1)
        fill = int(w * frac)
        pygame.draw.rect(screen, (*self.accent_rgb, 140), pygame.Rect(x, y, fill, h))
        if label:
            lab = self._font_label.render(label, True, self._dim)
            screen.blit(lab, (x, y - lab.get_height() - 2))

    # ---------- helpers ----------

    def _reseed(self):
        if self.seed is None:
            self.seed = random.randrange(1, 2**31 - 1)
        self._rng.seed(int(self.seed))

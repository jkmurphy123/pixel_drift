# alien_biometric_scanner_mode.py

import math
import random
from dataclasses import dataclass
from datetime import datetime

import pygame


@dataclass
class ScannerTarget:
    species: str
    specimen_id: str
    morphology: str
    status: str
    temp_c: float
    pulse_bpm: float
    o2_pct: float
    neural_mv: float
    enzyme_idx: float
    phase: float


@dataclass
class HudEvent:
    t_end: float
    kind: str   # INFO / WARN / ALERT
    text: str


class AlienBiometricScannerMode:
    """
    Alien Biometric Scanner (portrait-friendly)
    - Central silhouette “specimen” panel
    - Vertical scan beam + readout ticks
    - Floating biometric HUD + mini waveform (optional)
    - Occasional alert pulses and log lines

    Config (optional):
      - title (str)
      - accent_rgb ([r,g,b])
      - seed (int)
      - refresh_hz (float)
      - scanline_alpha (int 0..255)
      - noise_alpha (int 0..255)
      - vignette_strength (float 0..1)
      - scan_speed (float): beam cycles per second-ish (default 0.40)
      - scan_band_height (float): 0..0.3 (default 0.10)
      - target_switch_interval_range ([min,max] seconds)
      - alert_probability_per_min (float)
      - show_waveform (bool)
    """

    def __init__(self, config: dict):
        self.title = str(config.get("title", "ALIEN BIOMETRIC SCANNER"))
        self.accent_rgb = tuple(config.get("accent_rgb", [170, 255, 200]))
        self.seed = config.get("seed", None)
        self.refresh_hz = float(config.get("refresh_hz", 60.0))

        self.scanline_alpha = int(config.get("scanline_alpha", 12))
        self.noise_alpha = int(config.get("noise_alpha", 10))
        self.vignette_strength = float(config.get("vignette_strength", 0.30))

        self.scan_speed = float(config.get("scan_speed", 0.40))
        self.scan_band_height = float(config.get("scan_band_height", 0.10))
        self.target_switch_interval_range = config.get("target_switch_interval_range", [6.0, 14.0])
        self.alert_probability_per_min = float(config.get("alert_probability_per_min", 0.5))
        self.show_waveform = bool(config.get("show_waveform", True))

        # runtime
        self.manager = None
        self.w = 0
        self.h = 0
        self._is_portrait = False

        # layout
        self._pad = 0
        self._header_h = 0
        self._footer_h = 0
        self._main_rect = pygame.Rect(0, 0, 0, 0)
        self._scan_rect = pygame.Rect(0, 0, 0, 0)
        self._hud_rect = pygame.Rect(0, 0, 0, 0)
        self._log_rect = pygame.Rect(0, 0, 0, 0)
        self._wave_rect = pygame.Rect(0, 0, 0, 0)

        # fonts
        self._font_header = None
        self._font_body = None
        self._font_small = None
        self._font_tiny = None

        # colors
        self._bg = (0, 0, 0)
        self._fg = (235, 235, 235)
        self._dim = (150, 150, 150)

        # state
        self._t = 0.0
        self._rng = random.Random()
        self._target: ScannerTarget | None = None
        self._events: list[HudEvent] = []

        # animation state
        self._scan_phase = 0.0
        self._scan_dir = 1.0
        self._alert_t = 999.0
        self._alert_dur = 0.0

        # scheduling
        self._next_target_t = 0.0

        # overlays
        self._overlay = None
        self._vignette = None

    # ---------- lifecycle ----------

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._recompute_layout()
        self._build_overlays()
        self._new_target()
        self._push_event("INFO", "scanner online: optical + biofield arrays initialized")

    def exit(self):
        self.manager = None
        self._events = []
        self._overlay = None
        self._vignette = None

    def handle_event(self, event):
        # SPACE: force new target
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self._new_target()

    def update(self, dt: float):
        self._t += dt

        # resize/hotplug
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            self._build_overlays()

        # event expiry
        self._events = [e for e in self._events if e.t_end > self._t][-10:]

        # scan beam moves down then up (ping-pong)
        self._scan_phase += dt * self.scan_speed * self._scan_dir
        if self._scan_phase >= 1.0:
            self._scan_phase = 1.0
            self._scan_dir = -1.0
            self._on_scan_pass()
        elif self._scan_phase <= 0.0:
            self._scan_phase = 0.0
            self._scan_dir = 1.0
            self._on_scan_pass()

        # periodic target switch
        if self._t >= self._next_target_t:
            self._new_target()

        # random alerts
        p = max(0.0, self.alert_probability_per_min) / 60.0
        if self._alert_t >= self._alert_dur and self._rng.random() < p * dt:
            self._trigger_alert()

        self._alert_t += dt
        if self._alert_t >= self._alert_dur:
            self._alert_dur = 0.0

        # drift the biometrics slightly
        if self._target:
            self._tick_biometrics(self._target, dt)

    def render(self, screen: pygame.Surface):
        screen.fill(self._bg)

        self._draw_header(screen)
        self._draw_panels(screen)
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

        content = pygame.Rect(
            self._pad,
            self._header_h,
            self.w - 2 * self._pad,
            self.h - self._header_h - self._footer_h
        )

        # Portrait layout: big scan panel on top, HUD below, log at bottom
        scan_h = int(content.height * 0.52)
        hud_h = int(content.height * 0.28)
        log_h = content.height - scan_h - hud_h

        self._scan_rect = pygame.Rect(content.left, content.top, content.width, scan_h)
        self._hud_rect = pygame.Rect(content.left, self._scan_rect.bottom + 10, content.width, hud_h - 10)
        self._log_rect = pygame.Rect(content.left, self._hud_rect.bottom + 10, content.width, log_h - 10)

        # optional waveform inset in HUD
        self._wave_rect = pygame.Rect(self._hud_rect.right - int(self._hud_rect.width * 0.45),
                                      self._hud_rect.top + 8,
                                      int(self._hud_rect.width * 0.43),
                                      int(self._hud_rect.height * 0.46))

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

    # ---------- target + biometrics ----------

    def _new_target(self):
        self._target = self._make_target()
        mn, mx = float(self.target_switch_interval_range[0]), float(self.target_switch_interval_range[1])
        self._next_target_t = self._t + self._rng.uniform(mn, mx)

        self._push_event("INFO", f"specimen acquired: {self._target.specimen_id} ({self._target.species})")
        # small chance of immediate warning
        if self._rng.random() < 0.25:
            self._push_event("WARN", "biofield interference detected: recalibrating")

    def _make_target(self) -> ScannerTarget:
        species = self._rng.choice([
            "XEN-AMPHIB", "CEPHALOID", "SILICATE", "AVIFORM", "NOCTURNAL", "UNKNOWN"
        ])
        specimen_id = f"SPC-{self._rng.randint(100, 999)}-{self._rng.choice(list('ABCDEFGH'))}"
        morphology = self._rng.choice([
            "bipedal / cranial crest", "quadruped / ocular cluster",
            "serpentine / segmented", "avian / hollow-bone",
            "cephalic / tentacular", "gelid / translucent"
        ])
        status = self._rng.choices(
            ["CLEAR", "MONITOR", "RESTRICTED", "QUARANTINE"],
            weights=[0.62, 0.22, 0.10, 0.06],
            k=1
        )[0]

        return ScannerTarget(
            species=species,
            specimen_id=specimen_id,
            morphology=morphology,
            status=status,
            temp_c=self._rng.uniform(24.0, 42.0),
            pulse_bpm=self._rng.uniform(28.0, 96.0),
            o2_pct=self._rng.uniform(12.0, 22.0),
            neural_mv=self._rng.uniform(0.4, 2.2),
            enzyme_idx=self._rng.uniform(0.15, 0.95),
            phase=self._rng.uniform(0.0, math.tau)
        )

    def _tick_biometrics(self, t: ScannerTarget, dt: float):
        # slow drift with gentle periodicity
        t.phase += dt * self._rng.uniform(0.7, 1.3)
        wob = 0.5 + 0.5 * math.sin(self._t * 1.4 + t.phase)

        t.temp_c += dt * self._rng.uniform(-0.12, 0.12) + (wob - 0.5) * dt * 0.08
        t.pulse_bpm += dt * self._rng.uniform(-0.6, 0.6) + (wob - 0.5) * dt * 1.2
        t.o2_pct += dt * self._rng.uniform(-0.05, 0.05)
        t.neural_mv += dt * self._rng.uniform(-0.06, 0.06) + (wob - 0.5) * dt * 0.10
        t.enzyme_idx += dt * self._rng.uniform(-0.01, 0.01)

        # clamp
        t.temp_c = max(10.0, min(60.0, t.temp_c))
        t.pulse_bpm = max(10.0, min(180.0, t.pulse_bpm))
        t.o2_pct = max(6.0, min(30.0, t.o2_pct))
        t.neural_mv = max(0.0, min(6.0, t.neural_mv))
        t.enzyme_idx = max(0.0, min(1.2, t.enzyme_idx))

    def _on_scan_pass(self):
        # every full pass, log a line and maybe nudge status
        if not self._target:
            return
        msg = self._rng.choice([
            "dermal lattice sampled",
            "ocular resonance mapped",
            "neural harmonics resolved",
            "biofield phase aligned",
            "microflora signature cataloged"
        ])
        self._push_event("INFO", f"scan: {msg}")

        if self._rng.random() < 0.10:
            self._target.status = self._rng.choice(["CLEAR", "MONITOR", "RESTRICTED"])

    def _trigger_alert(self):
        self._alert_t = 0.0
        self._alert_dur = self._rng.uniform(2.0, 3.5)
        self._push_event("ALERT", self._rng.choice([
            "identity mismatch: template divergence",
            "unauthorized implant detected",
            "neural spike anomaly: isolate subject",
            "enzyme index exceeds safe threshold"
        ]))
        if self._target:
            self._target.status = self._rng.choice(["MONITOR", "RESTRICTED", "QUARANTINE"])

    def _push_event(self, kind: str, text: str):
        ttl = 9.0 if kind == "INFO" else 12.0
        self._events.append(HudEvent(t_end=self._t + ttl, kind=kind, text=text))

    # ---------- drawing ----------

    def _draw_header(self, screen: pygame.Surface):
        band = pygame.Surface((self.w, self._header_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, 0))

        t1 = self._font_header.render(self.title, True, self.accent_rgb)
        screen.blit(t1, (self._pad, int(self._header_h * 0.18)))

        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        sub = self._font_small.render(f"MEDBAY NODE: BX-07   |   UTC {ts}   |   MODE: PASSIVE SCAN", True, self._dim)
        screen.blit(sub, (self._pad, int(self._header_h * 0.18) + t1.get_height() + 6))

        pygame.draw.line(screen, self._dim, (self._pad, self._header_h - 2), (self.w - self._pad, self._header_h - 2), 2)

    def _draw_footer(self, screen: pygame.Surface):
        y0 = self.h - self._footer_h
        band = pygame.Surface((self.w, self._footer_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, y0))

        hint = "SPACE: new specimen   |   turn knob: change modes"
        s = self._font_small.render(hint, True, self._dim)
        screen.blit(s, (self._pad, y0 + (self._footer_h - s.get_height()) // 2))

    def _draw_panels(self, screen: pygame.Surface):
        # scan panel
        self._draw_panel_frame(screen, self._scan_rect, "SCAN FIELD")
        self._draw_scan_field(screen, self._scan_rect)

        # hud panel
        self._draw_panel_frame(screen, self._hud_rect, "BIOMETRIC HUD")
        self._draw_hud(screen, self._hud_rect)

        # log panel
        self._draw_panel_frame(screen, self._log_rect, "EVENT LOG")
        self._draw_log(screen, self._log_rect)

    def _draw_panel_frame(self, screen: pygame.Surface, rect: pygame.Rect, label: str):
        pygame.draw.rect(screen, (0, 0, 0), rect)
        pygame.draw.rect(screen, (*self.accent_rgb, 150), rect, 2)
        lab = self._font_tiny.render(label, True, self._dim)
        screen.blit(lab, (rect.left + 10, rect.top + 8))

    def _draw_scan_field(self, screen: pygame.Surface, rect: pygame.Rect):
        # center silhouette bounds
        inner = rect.inflate(-22, -26)
        cx, cy = inner.centerx, inner.centery

        # back grid
        step = max(34, int(min(inner.width, inner.height) * 0.16))
        for x in range(inner.left, inner.right, step):
            pygame.draw.line(screen, (*self.accent_rgb, 25), (x, inner.top), (x, inner.bottom), 1)
        for y in range(inner.top, inner.bottom, step):
            pygame.draw.line(screen, (*self.accent_rgb, 25), (inner.left, y), (inner.right, y), 1)

        # silhouette (stylized “alien” head/body)
        pulse = 0.5 + 0.5 * math.sin(self._t * 1.6 + (self._target.phase if self._target else 0.0))
        glow_a = int(30 + 50 * pulse)

        sil = pygame.Surface((inner.width, inner.height), pygame.SRCALPHA)

        # head
        head_w = int(inner.width * 0.36)
        head_h = int(inner.height * 0.38)
        head_rect = pygame.Rect(0, 0, head_w, head_h)
        head_rect.center = (inner.width // 2, int(inner.height * 0.36))
        pygame.draw.ellipse(sil, (*self.accent_rgb, 55), head_rect, 0)

        # eyes
        eye_w = int(head_w * 0.22)
        eye_h = int(head_h * 0.18)
        for sx in (-1, 1):
            er = pygame.Rect(0, 0, eye_w, eye_h)
            er.center = (head_rect.centerx + sx * int(head_w * 0.18), head_rect.centery + int(head_h * 0.05))
            pygame.draw.ellipse(sil, (0, 0, 0, 140), er, 0)
            pygame.draw.ellipse(sil, (*self.accent_rgb, 120), er, 2)

        # torso
        torso_w = int(inner.width * 0.30)
        torso_h = int(inner.height * 0.42)
        torso = pygame.Rect(0, 0, torso_w, torso_h)
        torso.center = (inner.width // 2, int(inner.height * 0.70))
        pygame.draw.rect(sil, (*self.accent_rgb, 45), torso, border_radius=16)

        # faint glow wash
        glow = pygame.Surface((inner.width, inner.height), pygame.SRCALPHA)
        glow.fill((*self.accent_rgb, int(glow_a * 0.18)))
        sil.blit(glow, (0, 0))

        screen.blit(sil, inner.topleft)

        # scan beam band
        band_h = int(inner.height * max(0.04, min(0.30, self.scan_band_height)))
        y = inner.top + int(self._scan_phase * (inner.height - band_h))
        band = pygame.Surface((inner.width, band_h), pygame.SRCALPHA)
        # gradient-ish: layered rects
        for i in range(band_h):
            a = int(120 * (1.0 - abs((i / max(1, band_h - 1)) - 0.5) * 2.0))
            pygame.draw.line(band, (*self.accent_rgb, a), (0, i), (inner.width, i), 1)
        screen.blit(band, (inner.left, y))

        # scan ticks and readout markers
        for i in range(6):
            yy = inner.top + int((i / 5) * inner.height)
            pygame.draw.line(screen, (*self.accent_rgb, 90), (inner.left - 8, yy), (inner.left, yy), 2)
            pygame.draw.line(screen, (*self.accent_rgb, 90), (inner.right, yy), (inner.right + 8, yy), 2)

        # alert pulse outline on scan panel
        if self._alert_t < self._alert_dur and self._alert_dur > 0:
            a = int(120 + 90 * (0.5 + 0.5 * math.sin(self._alert_t * 10.0)))
            pygame.draw.rect(screen, (255, 100, 100, a), rect, 4)

        # top-right identity blip
        if self._target:
            chip = self._font_small.render(f"{self._target.specimen_id}  [{self._target.species}]", True, self._dim)
            screen.blit(chip, (rect.right - 12 - chip.get_width(), rect.top + 10))

    def _draw_hud(self, screen: pygame.Surface, rect: pygame.Rect):
        if not self._target:
            return

        t = self._target
        left = rect.left + 14
        top = rect.top + 34
        lh = self._font_small.get_linesize() + 4

        # status color
        if t.status == "QUARANTINE":
            scol = (255, 140, 140)
        elif t.status == "RESTRICTED":
            scol = (255, 210, 150)
        elif t.status == "MONITOR":
            scol = (200, 255, 210)
        else:
            scol = (200, 200, 200)

        # left column readouts
        self._kv(screen, left, top + lh * 0, "STATUS", t.status, scol)
        self._kv(screen, left, top + lh * 1, "MORPH", t.morphology, self._fg)
        self._kv(screen, left, top + lh * 2, "TEMP", f"{t.temp_c:0.1f} C", self.accent_rgb)
        self._kv(screen, left, top + lh * 3, "PULSE", f"{t.pulse_bpm:0.0f} bpm", (255, 220, 170))
        self._kv(screen, left, top + lh * 4, "O2", f"{t.o2_pct:0.1f} %", self._fg)
        self._kv(screen, left, top + lh * 5, "NEURAL", f"{t.neural_mv:0.2f} mV", self._fg)
        self._kv(screen, left, top + lh * 6, "ENZYME", f"{t.enzyme_idx:0.2f}", self._fg)

        # waveform inset
        if self.show_waveform and self._wave_rect.width > 10:
            pygame.draw.rect(screen, (*self.accent_rgb, 120), self._wave_rect, 2)
            lab = self._font_tiny.render("NEURAL TRACE", True, self._dim)
            screen.blit(lab, (self._wave_rect.left + 8, self._wave_rect.top + 6))
            self._draw_waveform(screen, self._wave_rect.inflate(-10, -18), t)

    def _draw_waveform(self, screen: pygame.Surface, rect: pygame.Rect, t: ScannerTarget):
        mid = rect.centery
        amp = rect.height * (0.28 + 0.10 * (0.5 + 0.5 * math.sin(self._t * 1.7 + t.phase)))
        freq = 2.2 + 0.8 * t.enzyme_idx

        pts = []
        for x in range(rect.width):
            u = x / max(1, rect.width - 1)
            y = math.sin(u * math.tau * freq + self._t * 3.0)
            y += 0.45 * math.sin(u * math.tau * (freq * 2.8) + self._t * 1.7)
            y += 0.08 * (self._rng.random() - 0.5)
            yy = int(mid + y * amp)
            pts.append((rect.left + x, yy))

        pygame.draw.lines(screen, (*self.accent_rgb, 190), False, pts, 2)
        pygame.draw.line(screen, (*self.accent_rgb, 40), (rect.left, mid), (rect.right, mid), 1)

    def _draw_log(self, screen: pygame.Surface, rect: pygame.Rect):
        x = rect.left + 14
        y = rect.top + 34

        # newest first
        for e in self._events[::-1][:8]:
            if e.kind == "ALERT":
                col = (255, 140, 140)
            elif e.kind == "WARN":
                col = (255, 210, 150)
            else:
                col = self._dim

            line = self._font_small.render(f"[{e.kind}] {e.text}", True, col)
            screen.blit(line, (x, y))
            y += line.get_height() + 6
            if y > rect.bottom - 10:
                break

    def _kv(self, screen, x, y, k, v, vcol):
        ks = self._font_small.render(f"{k:7s}", True, self._dim)
        vs = self._font_small.render(str(v), True, vcol)
        screen.blit(ks, (x, y))
        screen.blit(vs, (x + 110, y))

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

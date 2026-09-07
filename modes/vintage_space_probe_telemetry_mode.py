# vintage_space_probe_telemetry_mode.py

import math
import random
from dataclasses import dataclass
from datetime import datetime

import pygame


@dataclass
class EventMsg:
    t_end: float
    kind: str   # INFO/WARN/ALERT
    text: str


class VintageSpaceProbeTelemetryMode:
    """
    Vintage Space Probe Telemetry
    - Portrait-friendly ground-station UI
    - Strip charts (rolling) + packet counters + link margin gauge
    - Occasional dropout + reacquire sequence

    Config (optional):
      - title (str)
      - probe_name (str)
      - accent_rgb ([r,g,b])
      - seed (int)
      - refresh_hz (float)
      - scanline_alpha (int 0..255)
      - noise_alpha (int 0..255)
      - vignette_strength (float 0..1)
      - show_stripcharts (bool)
      - chart_count (int) 1..4
      - dropout_probability_per_min (float)
      - reacquire_time_range ([min,max] sec)
      - packet_rate_range ([min,max] packets/sec)
      - portrait_layout (bool)
    """

    def __init__(self, config: dict):
        self.title = str(config.get("title", "VINTAGE SPACE PROBE TELEMETRY"))
        self.probe_name = str(config.get("probe_name", "PROBE: UNKNOWN"))
        self.accent_rgb = tuple(config.get("accent_rgb", [255, 210, 140]))
        self.seed = config.get("seed", None)
        self.refresh_hz = float(config.get("refresh_hz", 60.0))

        self.scanline_alpha = int(config.get("scanline_alpha", 10))
        self.noise_alpha = int(config.get("noise_alpha", 10))
        self.vignette_strength = float(config.get("vignette_strength", 0.28))

        self.show_stripcharts = bool(config.get("show_stripcharts", True))
        self.chart_count = int(config.get("chart_count", 3))
        self.dropout_probability_per_min = float(config.get("dropout_probability_per_min", 0.5))
        self.reacquire_time_range = config.get("reacquire_time_range", [2.0, 5.0])
        self.packet_rate_range = config.get("packet_rate_range", [16, 60])
        self.portrait_layout = bool(config.get("portrait_layout", True))

        # runtime
        self.manager = None
        self.w = 0
        self.h = 0
        self._is_portrait = False

        # colors
        self._bg = (0, 0, 0)
        self._fg = (235, 235, 235)
        self._dim = (150, 150, 150)

        # layout
        self._pad = 0
        self._header_h = 0
        self._footer_h = 0
        self._main_rect = pygame.Rect(0, 0, 0, 0)
        self._status_rect = pygame.Rect(0, 0, 0, 0)
        self._charts_rect = pygame.Rect(0, 0, 0, 0)
        self._log_rect = pygame.Rect(0, 0, 0, 0)

        # fonts
        self._font_header = None
        self._font_body = None
        self._font_small = None
        self._font_tiny = None

        # state
        self._t = 0.0
        self._rng = random.Random()
        self._events: list[EventMsg] = []

        # telemetry stats
        self._link_state = "LOCKED"  # LOCKED / DROPOUT / ACQUIRING
        self._link_margin_db = 12.0
        self._snr_db = 19.0
        self._doppler_hz = -148.0
        self._temp_c = -34.0
        self._bus_v = 27.8

        self._packets_ok = 0
        self._packets_err = 0
        self._packet_rate = 32.0
        self._frame_hex = "00 00 00 00 00 00 00 00"

        # dropout timing
        self._drop_t = 999.0
        self._drop_dur = 0.0
        self._reacq_t = 0.0

        # strip charts
        self._chart_surfs = []
        self._chart_data = []  # list[list[float]]
        self._chart_labels = ["SNR (dB)", "LINK MARGIN (dB)", "BUS V (V)", "TEMP (C)"]
        self._chart_phase = 0.0

        # overlays
        self._overlay = None
        self._vignette = None

    # ---------- lifecycle ----------

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._recompute_layout()
        self._build_overlays()
        self._init_charts()

        self._push_event("INFO", "ground station online")
        self._push_event("INFO", f"tracking {self.probe_name}")
        self._push_event("INFO", "carrier lock: nominal")

    def exit(self):
        self.manager = None
        self._events = []
        self._chart_surfs = []
        self._chart_data = []
        self._overlay = None
        self._vignette = None

    def handle_event(self, event):
        # SPACE: force dropout (test)
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self._trigger_dropout(force=True)

    def update(self, dt: float):
        self._t += dt

        # resize/hotplug
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            self._build_overlays()
            self._init_charts(keep_history=True)

        # expire events
        self._events = [e for e in self._events if e.t_end > self._t][-12:]

        # dropout probability
        p = max(0.0, self.dropout_probability_per_min) / 60.0
        if self._link_state == "LOCKED" and self._rng.random() < p * dt:
            self._trigger_dropout(force=False)

        # handle dropout / reacquire
        self._drop_t += dt
        if self._link_state == "DROPOUT":
            if self._drop_t >= self._drop_dur:
                self._start_reacquire()
        elif self._link_state == "ACQUIRING":
            self._reacq_t -= dt
            if self._reacq_t <= 0:
                self._finish_reacquire()

        # update telemetry values
        self._tick_telemetry(dt)

        # charts
        if self.show_stripcharts:
            self._tick_charts(dt)

    def render(self, screen: pygame.Surface):
        screen.fill(self._bg)

        self._draw_header(screen)
        self._draw_main(screen)
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

        self._main_rect = pygame.Rect(
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

        # Portrait stacking: STATUS (top), CHARTS (middle), LOG (bottom)
        mr = self._main_rect
        status_h = int(mr.height * 0.28)
        log_h = int(mr.height * 0.22)
        charts_h = mr.height - status_h - log_h - 20

        self._status_rect = pygame.Rect(mr.left, mr.top, mr.width, status_h)
        self._charts_rect = pygame.Rect(mr.left, self._status_rect.bottom + 10, mr.width, charts_h)
        self._log_rect = pygame.Rect(mr.left, self._charts_rect.bottom + 10, mr.width, log_h)

    def _build_overlays(self):
        self._overlay = pygame.Surface((self.w, self.h), pygame.SRCALPHA)

        # scanlines
        if self.scanline_alpha > 0:
            step = 3
            for y in range(0, self.h, step):
                a = self.scanline_alpha if ((y // step) % 2 == 0) else int(self.scanline_alpha * 0.45)
                pygame.draw.line(self._overlay, (0, 0, 0, a), (0, y), (self.w, y), 1)

        # border rings
        rings = 60
        for i in range(rings):
            a = int(2.6 * i)
            pygame.draw.rect(self._overlay, (0, 0, 0, a), pygame.Rect(i, i, self.w - 2 * i, self.h - 2 * i), 1)

        self._vignette = self._build_vignette(self.w, self.h, self.vignette_strength)

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

    # ---------- telemetry ----------

    def _tick_telemetry(self, dt: float):
        # base drift
        self._chart_phase += dt * 1.0
        wob = 0.5 + 0.5 * math.sin(self._t * 1.2 + self._chart_phase)

        if self._link_state == "LOCKED":
            self._snr_db += dt * self._rng.uniform(-0.25, 0.25) + (wob - 0.5) * dt * 0.8
            self._link_margin_db += dt * self._rng.uniform(-0.18, 0.18)
            self._doppler_hz += dt * self._rng.uniform(-0.8, 0.8)
            self._temp_c += dt * self._rng.uniform(-0.10, 0.10)
            self._bus_v += dt * self._rng.uniform(-0.03, 0.03)
        elif self._link_state == "DROPOUT":
            # collapse metrics quickly
            self._snr_db = max(0.0, self._snr_db - dt * 7.0)
            self._link_margin_db = max(-6.0, self._link_margin_db - dt * 4.0)
            self._packet_rate = 0.0
        elif self._link_state == "ACQUIRING":
            # recovering
            self._snr_db += dt * 2.6
            self._link_margin_db += dt * 1.8

        # clamp
        self._snr_db = max(0.0, min(40.0, self._snr_db))
        self._link_margin_db = max(-8.0, min(20.0, self._link_margin_db))
        self._doppler_hz = max(-1200.0, min(1200.0, self._doppler_hz))
        self._temp_c = max(-120.0, min(80.0, self._temp_c))
        self._bus_v = max(18.0, min(34.0, self._bus_v))

        # packets
        if self._link_state == "LOCKED":
            pr_min, pr_max = float(self.packet_rate_range[0]), float(self.packet_rate_range[1])
            target = self._rng.uniform(pr_min, pr_max)
            self._packet_rate += (target - self._packet_rate) * min(1.0, dt * 0.35)

            inc = int(self._packet_rate * dt)
            self._packets_ok += max(0, inc)
            if self._rng.random() < 0.02 * dt:
                self._packets_err += 1

        # update a faux hex frame
        if self._rng.random() < 0.18 * dt:
            self._frame_hex = " ".join(f"{self._rng.randrange(0,256):02X}" for _ in range(8))

    def _trigger_dropout(self, force: bool):
        if self._link_state != "LOCKED":
            return
        self._link_state = "DROPOUT"
        self._drop_t = 0.0
        self._drop_dur = self._rng.uniform(float(self.reacquire_time_range[0]), float(self.reacquire_time_range[1])) if not force else 3.0
        self._push_event("WARN", "carrier lock lost")
        self._push_event("WARN", "autotrack: sweeping")

    def _start_reacquire(self):
        self._link_state = "ACQUIRING"
        self._reacq_t = self._rng.uniform(1.0, 2.2)
        self._push_event("INFO", "acquire sequence: narrowband")

    def _finish_reacquire(self):
        self._link_state = "LOCKED"
        self._drop_t = 999.0
        self._drop_dur = 0.0
        # snap to plausible values
        self._snr_db = self._rng.uniform(15.0, 24.0)
        self._link_margin_db = self._rng.uniform(8.0, 14.0)
        self._packet_rate = self._rng.uniform(float(self.packet_rate_range[0]), float(self.packet_rate_range[1]))
        self._push_event("INFO", "carrier lock reacquired")
        if self._rng.random() < 0.20:
            self._push_event("WARN", "frame sync: intermittent (crc)")

    def _push_event(self, kind: str, text: str):
        ttl = 10.0 if kind == "INFO" else 13.0
        self._events.append(EventMsg(t_end=self._t + ttl, kind=kind, text=text))

    # ---------- charts ----------

    def _init_charts(self, keep_history: bool = False):
        count = max(1, min(4, int(self.chart_count)))
        self._chart_surfs = []
        old = self._chart_data if keep_history else []
        self._chart_data = []

        # allocate buffers per chart (width in pixels)
        w = max(1, self._charts_rect.width - 24)
        for i in range(count):
            self._chart_surfs.append(pygame.Surface((w, 1), pygame.SRCALPHA))  # placeholder; drawn manually
            if keep_history and i < len(old) and old[i]:
                # resize history to new width
                hist = old[i][-w:]
                if len(hist) < w:
                    hist = [hist[0]] * (w - len(hist)) + hist
                self._chart_data.append(hist)
            else:
                self._chart_data.append([0.5] * w)

    def _tick_charts(self, dt: float):
        if not self._chart_data:
            return
        # shift left by N pixels based on time
        px = max(1, int(60 * dt))
        for i in range(len(self._chart_data)):
            for _ in range(px):
                self._chart_data[i].pop(0)
                self._chart_data[i].append(self._sample_chart(i))

    def _sample_chart(self, idx: int) -> float:
        # normalize signals to 0..1
        if idx == 0:  # SNR
            v = self._snr_db / 40.0
        elif idx == 1:  # margin
            v = (self._link_margin_db + 8.0) / 28.0
        elif idx == 2:  # bus V
            v = (self._bus_v - 18.0) / 16.0
        else:  # temp
            v = (self._temp_c + 120.0) / 200.0
        return max(0.0, min(1.0, v))

    # ---------- drawing ----------

    def _draw_header(self, screen: pygame.Surface):
        band = pygame.Surface((self.w, self._header_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, 0))

        t1 = self._font_header.render(self.title, True, self.accent_rgb)
        screen.blit(t1, (self._pad, int(self._header_h * 0.18)))

        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        sub = self._font_small.render(f"{self.probe_name}   |   DSN NODE: STATION-7   |   UTC {ts}", True, self._dim)
        screen.blit(sub, (self._pad, int(self._header_h * 0.18) + t1.get_height() + 6))

        pygame.draw.line(screen, self._dim, (self._pad, self._header_h - 2), (self.w - self._pad, self._header_h - 2), 2)

    def _draw_footer(self, screen: pygame.Surface):
        y0 = self.h - self._footer_h
        band = pygame.Surface((self.w, self._footer_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, y0))

        hint = "SPACE: force dropout   |   turn knob: change modes"
        s = self._font_small.render(hint, True, self._dim)
        screen.blit(s, (self._pad, y0 + (self._footer_h - s.get_height()) // 2))

    def _draw_main(self, screen: pygame.Surface):
        self._draw_panel(screen, self._status_rect, "LINK STATUS", draw_fn=self._draw_status_panel)
        self._draw_panel(screen, self._charts_rect, "STRIP CHARTS", draw_fn=self._draw_charts_panel)
        self._draw_panel(screen, self._log_rect, "CONSOLE LOG", draw_fn=self._draw_log_panel)

    def _draw_panel(self, screen: pygame.Surface, rect: pygame.Rect, label: str, draw_fn):
        pygame.draw.rect(screen, (0, 0, 0), rect)
        pygame.draw.rect(screen, (*self.accent_rgb, 150), rect, 2)
        lab = self._font_tiny.render(label, True, self._dim)
        screen.blit(lab, (rect.left + 10, rect.top + 8))
        draw_fn(screen, rect)

    def _draw_status_panel(self, screen: pygame.Surface, rect: pygame.Rect):
        inner = rect.inflate(-18, -26)
        x = inner.left
        y = inner.top + 16

        # state chip
        if self._link_state == "LOCKED":
            col = (180, 255, 210)
        elif self._link_state == "ACQUIRING":
            col = (255, 220, 150)
        else:
            col = (255, 140, 140)

        chip = pygame.Rect(x, y, min(220, inner.width), 28)
        pygame.draw.rect(screen, (*col, 40), chip, border_radius=6)
        pygame.draw.rect(screen, (*col, 180), chip, 2, border_radius=6)
        screen.blit(self._font_small.render(self._link_state, True, col), (chip.left + 10, chip.top + 6))

        # link margin gauge
        gx = x
        gy = y + 46
        gw = min(inner.width, 520)
        gh = 12
        self._draw_gauge(screen, gx, gy, gw, gh, (self._link_margin_db + 8.0) / 28.0, "LINK MARGIN")

        # readouts
        y2 = gy + 30
        lh = self._font_small.get_linesize() + 4
        self._kv(screen, x, y2 + lh * 0, "SNR", f"{self._snr_db:5.1f} dB", self.accent_rgb)
        self._kv(screen, x, y2 + lh * 1, "DOPPLER", f"{self._doppler_hz:7.1f} Hz", self._fg)
        self._kv(screen, x, y2 + lh * 2, "BUS V", f"{self._bus_v:5.2f} V", self._fg)
        self._kv(screen, x, y2 + lh * 3, "TEMP", f"{self._temp_c:6.1f} C", self._fg)

        # packet counters + hex frame
        right = x + int(inner.width * 0.54)
        self._kv(screen, right, y2 + lh * 0, "PKT OK", f"{self._packets_ok:8d}", self._fg)
        self._kv(screen, right, y2 + lh * 1, "PKT ERR", f"{self._packets_err:8d}", (255, 180, 180))
        self._kv(screen, right, y2 + lh * 2, "RATE", f"{self._packet_rate:6.1f}/s", self._fg)
        hx = self._font_small.render(f"FRAME: {self._frame_hex}", True, self._dim)
        screen.blit(hx, (x, rect.bottom - 22 - hx.get_height()))

    def _draw_charts_panel(self, screen: pygame.Surface, rect: pygame.Rect):
        if not self.show_stripcharts or not self._chart_data:
            msg = self._font_small.render("charts disabled", True, self._dim)
            screen.blit(msg, (rect.left + 14, rect.top + 34))
            return

        inner = rect.inflate(-18, -32)
        count = len(self._chart_data)
        gap = 10
        h_each = (inner.height - (count - 1) * gap) // count

        for i in range(count):
            r = pygame.Rect(inner.left, inner.top + i * (h_each + gap), inner.width, h_each)
            self._draw_stripchart(screen, r, self._chart_data[i], self._chart_labels[i])

    def _draw_stripchart(self, screen: pygame.Surface, rect: pygame.Rect, data: list[float], label: str):
        pygame.draw.rect(screen, (*self.accent_rgb, 90), rect, 1)

        # faint grid
        for j in range(1, 4):
            yy = rect.top + int(j * rect.height / 4)
            pygame.draw.line(screen, (*self.accent_rgb, 25), (rect.left, yy), (rect.right, yy), 1)

        # draw line
        pts = []
        n = min(rect.width, len(data))
        start = len(data) - n
        for x in range(n):
            v = data[start + x]
            yy = rect.bottom - int(v * (rect.height - 2)) - 1
            pts.append((rect.left + x, yy))

        if len(pts) >= 2:
            pygame.draw.lines(screen, (*self.accent_rgb, 190), False, pts, 2)

        lab = self._font_tiny.render(label, True, self._dim)
        screen.blit(lab, (rect.left + 8, rect.top + 6))

        # “paper feed” perforation dots on left
        for yy in range(rect.top + 6, rect.bottom - 6, 10):
            pygame.draw.circle(screen, (*self.accent_rgb, 60), (rect.left - 6, yy), 1)

    def _draw_log_panel(self, screen: pygame.Surface, rect: pygame.Rect):
        x = rect.left + 14
        y = rect.top + 34

        for e in self._events[::-1][:8]:
            if e.kind == "ALERT":
                col = (255, 140, 140)
            elif e.kind == "WARN":
                col = (255, 220, 150)
            else:
                col = self._dim

            s = self._font_small.render(f"[{e.kind}] {e.text}", True, col)
            screen.blit(s, (x, y))
            y += s.get_height() + 6
            if y > rect.bottom - 8:
                break

    def _draw_gauge(self, screen, x, y, w, h, frac, label):
        frac = max(0.0, min(1.0, frac))
        pygame.draw.rect(screen, (*self.accent_rgb, 90), pygame.Rect(x, y, w, h), 1)
        pygame.draw.rect(screen, (*self.accent_rgb, 140), pygame.Rect(x, y, int(w * frac), h))
        lab = self._font_tiny.render(label, True, self._dim)
        screen.blit(lab, (x, y - lab.get_height() - 2))

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

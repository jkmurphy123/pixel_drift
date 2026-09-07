# deep_space_signal_decoder_mode.py

import math
import random
import time
from dataclasses import dataclass
from datetime import datetime

import pygame


@dataclass
class DecoderEvent:
    kind: str            # "LOCK", "DROP", "CAL"
    text: str
    t_start: float
    t_end: float


class DeepSpaceSignalDecoderMode:
    """
    Deep-Space Signal Decoder (waveforms + waterfall + scrolling decode + HUD).

    Config (all optional):
      - refresh_hz (float): target update rate (default 60)
      - seed (int): reproducible RNG (default random)
      - accent_rgb ([r,g,b]): HUD accent (default [80,200,255])
      - grid_alpha (int): 0..255 (default 70)
      - scanline_alpha (int): 0..255 overlay scanlines (default 16)
      - noise_alpha (int): 0..255 overlay noise speckle (default 18)
      - waterfall_bins (int): columns in waterfall (default 96)
      - waterfall_speed (float): pixels per sec scroll (default 240)
      - message_rate_cps (float): decode text chars per second (default 24)
      - lock_probability_per_min (float): expected lock events per minute (default 1.2)
      - lock_duration_range ([min,max]): seconds (default [7,16])
      - show_hex (bool): show hex dump panel (default True)
      - show_glyphs (bool): show alien glyph band (default True)
      - title (str): header title (default "DEEP-SPACE SIGNAL DECODER")
    """

    def __init__(self, config: dict):
        self.refresh_hz = float(config.get("refresh_hz", 60.0))
        self.seed = config.get("seed", None)

        self.accent_rgb = tuple(config.get("accent_rgb", [80, 200, 255]))
        self.grid_alpha = int(config.get("grid_alpha", 70))
        self.scanline_alpha = int(config.get("scanline_alpha", 16))
        self.noise_alpha = int(config.get("noise_alpha", 18))

        self.waterfall_bins = int(config.get("waterfall_bins", 96))
        self.waterfall_speed = float(config.get("waterfall_speed", 240.0))

        self.message_rate_cps = float(config.get("message_rate_cps", 24.0))
        self.lock_probability_per_min = float(config.get("lock_probability_per_min", 1.2))
        self.lock_duration_range = config.get("lock_duration_range", [7.0, 16.0])

        self.show_hex = bool(config.get("show_hex", True))
        self.show_glyphs = bool(config.get("show_glyphs", True))
        self.title = str(config.get("title", "DEEP-SPACE SIGNAL DECODER"))

        # runtime
        self.manager = None
        self.w = 0
        self.h = 0
        self._is_portrait = False

        # timing
        self._t = 0.0
        self._last_tick = 0.0

        # RNG / state
        self._rng = random.Random()
        self._events: list[DecoderEvent] = []
        self._lock_active = False
        self._lock_end_t = 0.0
        self._snr = 12.0
        self._snr_target = 14.0
        self._carrier_hz = 1420.4  # just a fun number
        self._drift_hz_per_s = 0.0

        # UI layout
        self._pad = 0
        self._header_h = 0
        self._footer_h = 0
        self._map_rect = pygame.Rect(0, 0, 0, 0)     # main area
        self._right_rect = pygame.Rect(0, 0, 0, 0)   # panels
        self._wave_rect = pygame.Rect(0, 0, 0, 0)    # waveform band
        self._water_rect = pygame.Rect(0, 0, 0, 0)   # waterfall band
        self._decode_rect = pygame.Rect(0, 0, 0, 0)  # decode text

        # Surfaces
        self._water_surf = None
        self._scan_surf = None

        # Waterfall bins (smoothed magnitudes 0..1)
        self._bins = [0.0 for _ in range(max(16, self.waterfall_bins))]

        # Decoder text buffers
        self._decode_stream = ""
        self._decode_visible_chars = 0.0
        self._hex_stream = ""
        self._hex_visible_chars = 0.0
        self._glyph_stream = ""
        self._glyph_visible_chars = 0.0

        # colors
        self._bg = (0, 0, 0)
        self._fg = (235, 235, 235)
        self._dim = (155, 155, 155)

    # ---------- lifecycle ----------

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._recompute_layout()
        self._build_overlays()
        self._reset_streams()

    def exit(self):
        self.manager = None
        self._events = []
        self._water_surf = None
        self._scan_surf = None

    def handle_event(self, event):
        # SPACE: force lock event (useful for testing)
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self._start_lock()

    def update(self, dt: float):
        self._t += dt

        # hotplug / rotation
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            self._build_overlays()

        # lock lifecycle
        if self._lock_active and self._t >= self._lock_end_t:
            self._lock_active = False
            self._push_event("DROP", "CARRIER LOST: returning to wideband scan")

        # probabilistic new lock (Poisson-ish)
        # p_per_sec = rate_per_min / 60
        p = max(0.0, self.lock_probability_per_min) / 60.0
        if (not self._lock_active) and (self._rng.random() < p * dt):
            self._start_lock()

        # slow parameters drift
        self._snr_target += self._rng.uniform(-0.18, 0.18) * dt
        self._snr_target = max(6.0, min(28.0, self._snr_target))
        self._snr += (self._snr_target - self._snr) * (0.8 * dt)

        self._drift_hz_per_s += self._rng.uniform(-0.008, 0.008) * dt
        self._drift_hz_per_s = max(-0.25, min(0.25, self._drift_hz_per_s))

        # update signal bins + waterfall
        self._tick_signal(dt)
        self._tick_waterfall(dt)

        # update scrolling text reveal
        self._decode_visible_chars += self.message_rate_cps * dt
        self._hex_visible_chars += (self.message_rate_cps * 1.3) * dt
        self._glyph_visible_chars += (self.message_rate_cps * 0.9) * dt

        # keep streams topped up
        self._top_up_streams()

    def render(self, screen: pygame.Surface):
        screen.fill(self._bg)

        self._draw_header(screen)
        self._draw_waveform(screen)
        self._draw_waterfall(screen)
        self._draw_decode_panels(screen)
        self._draw_footer(screen)

        # overlays
        if self._scan_surf is not None and self.scanline_alpha > 0:
            screen.blit(self._scan_surf, (0, 0))
        if self.noise_alpha > 0:
            self._draw_noise(screen)

    # ---------- layout ----------

    def _recompute_layout(self):
        self.w, self.h = self.manager.screen.get_size()
        self._is_portrait = self.h > self.w

        self._pad = int(min(self.w, self.h) * 0.04)
        self._header_h = max(64, int(self.h * 0.11))
        self._footer_h = max(34, int(self.h * 0.06))

        top = self._header_h
        bottom = self.h - self._footer_h

        # right panel only if landscape and wide enough
        if (not self._is_portrait) and self.w >= 900:
            right_w = int(self.w * 0.34)
            main_w = self.w - right_w - self._pad
            self._map_rect = pygame.Rect(self._pad // 2, top, main_w, bottom - top)
            self._right_rect = pygame.Rect(self._map_rect.right + self._pad // 2, top, right_w, bottom - top)
        else:
            self._map_rect = pygame.Rect(self._pad // 2, top, self.w - self._pad, bottom - top)
            self._right_rect = pygame.Rect(0, 0, 0, 0)

        # split main into wave + waterfall + decode
        mh = self._map_rect.height
        wave_h = max(90, int(mh * 0.22))
        water_h = max(120, int(mh * 0.48))
        decode_h = mh - wave_h - water_h

        self._wave_rect = pygame.Rect(self._map_rect.left, self._map_rect.top, self._map_rect.width, wave_h)
        self._water_rect = pygame.Rect(self._map_rect.left, self._wave_rect.bottom, self._map_rect.width, water_h)
        self._decode_rect = pygame.Rect(self._map_rect.left, self._water_rect.bottom, self._map_rect.width, decode_h)

        # rebuild waterfall surface sized to water rect
        self._water_surf = pygame.Surface((max(1, self._water_rect.width), max(1, self._water_rect.height)), pygame.SRCALPHA)

        # ensure bins length matches
        self.waterfall_bins = max(16, int(self.waterfall_bins))
        self._bins = [0.0 for _ in range(self.waterfall_bins)]

    def _build_overlays(self):
        self._scan_surf = None

    # ---------- signal synthesis ----------

    def _tick_signal(self, dt: float):
        # Update “spectral” bins with smoothing; lock mode creates a narrow bright band.
        # We fake it with a moving peak + noise floor.
        lock_boost = 1.0 if self._lock_active else 0.35

        # peak center drifts
        peak = (0.18 + 0.62 * (0.5 + 0.5 * math.sin(self._t * (0.22 if self._lock_active else 0.08))))  # 0..1
        peak_bin = int(peak * (self.waterfall_bins - 1))
        width = 3 if self._lock_active else 10

        for i in range(self.waterfall_bins):
            floor = 0.10 + 0.10 * self._rng.random()
            bump = 0.0
            d = abs(i - peak_bin)
            if d <= width:
                bump = (1.0 - (d / max(1, width))) ** 2
            target = floor + lock_boost * 0.85 * bump

            # occasional “chirp” spikes
            if self._rng.random() < 0.008 * dt * 60.0:
                target += self._rng.uniform(0.4, 1.0)

            target = max(0.0, min(1.0, target))
            self._bins[i] += (target - self._bins[i]) * (3.2 * dt)

    def _tick_waterfall(self, dt: float):
        # Scroll waterfall down and draw a new row at the top.
        if self._water_surf is None:
            return

        px = max(1, int(self.waterfall_speed * dt))
        if px > 0:
            self._water_surf.scroll(dy=px)
            # clear newly exposed top strip
            pygame.draw.rect(self._water_surf, (0, 0, 0, 0), pygame.Rect(0, 0, self._water_surf.get_width(), px))

        # draw newest row(s)
        rows = px if px > 0 else 1
        w = self._water_surf.get_width()
        bins = self.waterfall_bins
        col_w = max(1, w // bins)

        for r in range(rows):
            y = r
            for i, v in enumerate(self._bins):
                # intensity to color: accent tinted, brighter when higher
                a = int(40 + 190 * v)
                a = max(0, min(255, a))
                rr = int(self.accent_rgb[0] + 120 * v)
                gg = int(self.accent_rgb[1] + 80 * v)
                bb = int(self.accent_rgb[2] + 40 * v)
                rr = max(0, min(255, rr))
                gg = max(0, min(255, gg))
                bb = max(0, min(255, bb))

                x = i * col_w
                pygame.draw.rect(self._water_surf, (rr, gg, bb, a), pygame.Rect(x, y, col_w, 1))

        # optional faint grid overlay in waterfall
        if self.grid_alpha > 0:
            gsurf = pygame.Surface((self._water_surf.get_width(), self._water_surf.get_height()), pygame.SRCALPHA)
            step = max(32, int(self._water_surf.get_height() * 0.08))
            for y in range(0, gsurf.get_height(), step):
                pygame.draw.line(gsurf, (*self.accent_rgb, int(self.grid_alpha * 0.25)), (0, y), (gsurf.get_width(), y), 1)
            self._water_surf.blit(gsurf, (0, 0))

    # ---------- text streams ----------

    def _reset_streams(self):
        self._decode_stream = ""
        self._hex_stream = ""
        self._glyph_stream = ""
        self._decode_visible_chars = 0.0
        self._hex_visible_chars = 0.0
        self._glyph_visible_chars = 0.0

        self._push_event("CAL", "wideband scan initialized")
        self._top_up_streams()

    def _top_up_streams(self):
        # Keep these buffers ahead of the visible window so scrolling feels infinite.
        if len(self._decode_stream) < 4000:
            self._decode_stream += self._make_decode_chunk()
        if len(self._hex_stream) < 6000:
            self._hex_stream += self._make_hex_chunk()
        if len(self._glyph_stream) < 3000:
            self._glyph_stream += self._make_glyph_chunk()

    def _make_decode_chunk(self) -> str:
        fragments = [
            "phase coherence rising",
            "doppler compensated",
            "carrier stabilized",
            "unknown framing detected",
            "faint harmonics at +3.1 kHz",
            "parity mismatch tolerated",
            "error-corrected payload recovered",
            "nonhuman symbol table suspected",
            "spectral notch filtering engaged",
            "triangulation attempt aborted",
        ]
        tags = ["[SCAN]", "[DEMOD]", "[SYNC]", "[FEC]", "[PROTO]", "[WIDEBAND]"]
        line = f"{self._rng.choice(tags)} {self._rng.choice(fragments)}\n"
        # In lock mode, inject more “meaningful” lines
        if self._lock_active and (self._rng.random() < 0.35):
            line = f"[LOCK] PAYLOAD: {self._make_payload_fragment()}\n"
        return line

    def _make_payload_fragment(self) -> str:
        # stylized pseudo-message, like partial decode
        words = [
            "VECTOR", "ORIGIN", "LISTEN", "WAKE", "ECHO", "SILENCE",
            "BEACON", "RETURN", "MEMORY", "ARCHIVE", "LATENCY", "THRESHOLD"
        ]
        return " ".join(self._rng.choice(words) for _ in range(self._rng.randrange(4, 9)))

    def _make_hex_chunk(self) -> str:
        # Format like a hexdump line
        out = []
        for _ in range(18):
            addr = self._rng.randrange(0, 0xFFFF)
            bytes_ = [self._rng.randrange(0, 256) for _ in range(16)]
            hexs = " ".join(f"{b:02X}" for b in bytes_)
            ascii_ = "".join(chr(b) if 32 <= b < 127 else "." for b in bytes_)
            out.append(f"{addr:04X}: {hexs}  |{ascii_}|\n")
        return "".join(out)

    def _make_glyph_chunk(self) -> str:
        # Use safe unicode blocks and symbols (looks alien-ish without custom fonts)
        glyphs = "▣▢▤▥▦▧▨▩▲△▶▷▼▽◀◁◆◇○◌◍◉◐◑◒◓"
        line = "".join(self._rng.choice(glyphs) for _ in range(self._rng.randrange(22, 48)))
        return line + "\n"

    # ---------- events / lock ----------

    def _start_lock(self):
        dmin, dmax = self.lock_duration_range[0], self.lock_duration_range[1]
        dur = self._rng.uniform(float(dmin), float(dmax))
        self._lock_active = True
        self._lock_end_t = self._t + dur

        # lock improves SNR target and adds drift
        self._snr_target = min(28.0, self._snr_target + self._rng.uniform(4.0, 9.0))
        self._drift_hz_per_s += self._rng.uniform(-0.08, 0.08)

        self._push_event("LOCK", f"carrier lock acquired ({dur:0.1f}s)")

    def _push_event(self, kind: str, msg: str):
        now = self._t
        e = DecoderEvent(kind=kind, text=msg, t_start=now, t_end=now + 9.0)
        self._events.append(e)
        # keep only recent
        self._events = [x for x in self._events if x.t_end > self._t][-8:]

    # ---------- drawing ----------

    def _draw_header(self, screen: pygame.Surface):
        # header band
        band = pygame.Surface((self.w, self._header_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 210))
        screen.blit(band, (0, 0))

        title_size = max(18, int(min(self.w, self.h) * 0.043))
        small_size = max(14, int(min(self.w, self.h) * 0.024))

        title_font = self.manager.cache.get_font("dejavusansmono", title_size, bold=True)
        small_font = self.manager.cache.get_font("dejavusansmono", small_size, bold=False)

        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        line1 = self.title
        line2 = f"UTC {ts}   |   SNR {self._snr:0.1f} dB   |   CARRIER {self._carrier_hz:0.1f} MHz   |   DRIFT {self._drift_hz_per_s:+0.3f} Hz/s"

        t1 = title_font.render(line1, True, self.accent_rgb)
        t2 = small_font.render(line2, True, self._dim)

        screen.blit(t1, (self._pad, int(self._header_h * 0.18)))
        screen.blit(t2, (self._pad, int(self._header_h * 0.18) + t1.get_height() + 2))

        # status on right
        status = "LOCKED" if self._lock_active else "SCANNING"
        scol = (255, 210, 140) if self._lock_active else self._fg
        st = title_font.render(status, True, scol)
        screen.blit(st, (self.w - self._pad - st.get_width(), int(self._header_h * 0.18)))

        pygame.draw.line(screen, self._dim, (self._pad, self._header_h - 2), (self.w - self._pad, self._header_h - 2), 2)

    def _draw_waveform(self, screen: pygame.Surface):
        rect = self._wave_rect
        pygame.draw.rect(screen, (0, 0, 0), rect)

        # border
        pygame.draw.rect(screen, self.accent_rgb, rect, 2)

        # waveform line on alpha surface
        s = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)

        midy = rect.height // 2
        amp = rect.height * (0.33 if self._lock_active else 0.22)
        freq = 2.2 if self._lock_active else 1.2

        # draw grid ticks
        if self.grid_alpha > 0:
            for x in range(0, rect.width, max(40, rect.width // 10)):
                pygame.draw.line(s, (*self.accent_rgb, int(self.grid_alpha * 0.25)), (x, 0), (x, rect.height), 1)
            pygame.draw.line(s, (*self.accent_rgb, int(self.grid_alpha * 0.25)), (0, midy), (rect.width, midy), 1)

        pts = []
        for x in range(rect.width):
            t = (x / max(1, rect.width - 1))
            # composite signal
            y = math.sin((t * math.tau * freq) + self._t * (2.6 if self._lock_active else 1.3))
            y += 0.45 * math.sin((t * math.tau * (freq * 3.1)) + self._t * 1.8)
            y += 0.10 * (self._rng.random() - 0.5) * (2.0 if self._lock_active else 1.0)
            yy = int(midy + amp * y)
            pts.append((x, yy))

        pygame.draw.lines(s, (*self.accent_rgb, 220), False, pts, 2)
        screen.blit(s, rect.topleft)

        # label
        label_size = max(12, int(min(self.w, self.h) * 0.021))
        font = self.manager.cache.get_font("dejavusansmono", label_size, bold=False)
        lab = font.render("TIME DOMAIN", True, self._dim)
        screen.blit(lab, (rect.left + 10, rect.top + 8))

    def _draw_waterfall(self, screen: pygame.Surface):
        rect = self._water_rect
        pygame.draw.rect(screen, (0, 0, 0), rect)
        pygame.draw.rect(screen, self.accent_rgb, rect, 2)

        if self._water_surf is not None:
            screen.blit(self._water_surf, rect.topleft)

        # label
        label_size = max(12, int(min(self.w, self.h) * 0.021))
        font = self.manager.cache.get_font("dejavusansmono", label_size, bold=False)
        lab = font.render("FREQUENCY DOMAIN (WATERFALL)", True, self._dim)
        screen.blit(lab, (rect.left + 10, rect.top + 8))

    def _draw_decode_panels(self, screen: pygame.Surface):
        # bottom decode band in main area + (optional) right panel
        rect = self._decode_rect
        pygame.draw.rect(screen, (0, 0, 0), rect)
        pygame.draw.rect(screen, self.accent_rgb, rect, 2)

        small = max(12, int(min(self.w, self.h) * 0.020))
        font = self.manager.cache.get_font("dejavusansmono", small, bold=False)

        pad = 10
        x = rect.left + pad
        y = rect.top + pad

        # left: decoded text
        decoded = self._decode_stream[: int(self._decode_visible_chars)]
        lines = decoded.splitlines()[-9:]  # show last N lines
        for ln in lines:
            surf = font.render(ln, True, self._fg)
            screen.blit(surf, (x, y))
            y += font.get_linesize() + 2

        # optional glyph band
        if self.show_glyphs:
            gx = rect.left + int(rect.width * 0.55)
            gy = rect.top + pad
            pygame.draw.line(screen, self._dim, (gx - 10, rect.top + 6), (gx - 10, rect.bottom - 6), 1)
            glyphs = self._glyph_stream[: int(self._glyph_visible_chars)]
            glines = glyphs.splitlines()[-9:]
            for ln in glines:
                surf = font.render(ln, True, self._dim)
                screen.blit(surf, (gx, gy))
                gy += font.get_linesize() + 2

        # right side panel (hex + events)
        if self._right_rect.width > 10:
            self._draw_right_panel(screen)

    def _draw_right_panel(self, screen: pygame.Surface):
        panel = self._right_rect
        bg = pygame.Surface((panel.width, panel.height), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 190))
        pygame.draw.rect(bg, (*self.accent_rgb, 160), bg.get_rect(), 2)
        screen.blit(bg, panel.topleft)

        pad = max(10, int(panel.width * 0.06))
        x = panel.left + pad
        y = panel.top + pad

        head_size = max(16, int(min(self.w, self.h) * 0.028))
        body_size = max(12, int(min(self.w, self.h) * 0.020))
        head = self.manager.cache.get_font("dejavusansmono", head_size, bold=True)
        body = self.manager.cache.get_font("dejavusansmono", body_size, bold=False)

        # events
        hdr = head.render("EVENT LOG", True, self.accent_rgb)
        screen.blit(hdr, (x, y))
        y += hdr.get_height() + 8

        for e in self._events[-6:][::-1]:
            tag = f"[{e.kind}]"
            surf = body.render(f"{tag:<6} {e.text}", True, self._dim if e.kind == "CAL" else self._fg)
            screen.blit(surf, (x, y))
            y += body.get_linesize() + 4

        y += 10
        pygame.draw.line(screen, self._dim, (panel.left + pad, y), (panel.right - pad, y), 1)
        y += 10

        if self.show_hex:
            hdr2 = head.render("HEX VIEW", True, self.accent_rgb)
            screen.blit(hdr2, (x, y))
            y += hdr2.get_height() + 8

            hexv = self._hex_stream[: int(self._hex_visible_chars)]
            hl = hexv.splitlines()[-18:]
            for ln in hl:
                surf = body.render(ln, True, self._fg)
                screen.blit(surf, (x, y))
                y += body.get_linesize() + 2

    def _draw_footer(self, screen: pygame.Surface):
        y0 = self.h - self._footer_h
        band = pygame.Surface((self.w, self._footer_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 210))
        screen.blit(band, (0, y0))

        size = max(12, int(min(self.w, self.h) * 0.020))
        font = self.manager.cache.get_font("dejavusansmono", size, bold=False)

        hint = "SPACE: force lock   |   turn knob: change modes"
        surf = font.render(hint, True, self._dim)
        screen.blit(surf, (self._pad, y0 + (self._footer_h - surf.get_height()) // 2))

    # ---------- overlays ----------

    def _draw_noise(self, screen: pygame.Surface):
        # light speckle noise for “RF interference”
        # Keep it cheap: draw a few random pixels per frame.
        n = max(200, (self.w * self.h) // 7000)
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

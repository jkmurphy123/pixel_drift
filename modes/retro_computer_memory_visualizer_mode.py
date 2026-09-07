# retro_computer_memory_visualizer_mode.py

import math
import random
from dataclasses import dataclass
from datetime import datetime

import pygame


@dataclass
class EventMsg:
    t_end: float
    kind: str   # INFO/WARN
    text: str


class RetroComputerMemoryVisualizerMode:
    """
    Retro Computer Memory Visualizer
    - RAM blocks grid (used/free/locked)
    - Fragmentation builds as allocations/frees happen
    - Occasional GC sweep compacts memory (visual sweep bar)
    - Optional hex dump panel

    Config (optional):
      - title (str)
      - accent_rgb ([r,g,b])
      - seed (int)
      - refresh_hz (float)
      - memory_kb (int)
      - block_kb (int)
      - alloc_rate (float) allocations/sec-ish
      - free_rate (float) frees/sec-ish
      - gc_probability_per_min (float)
      - scanline_alpha (int 0..255)
      - noise_alpha (int 0..255)
      - vignette_strength (float 0..1)
      - show_hex_dump (bool)
      - portrait_columns (int) number of RAM panels side-by-side in portrait
    """

    def __init__(self, config: dict):
        self.title = str(config.get("title", "RETRO COMPUTER MEMORY VISUALIZER"))
        self.accent_rgb = tuple(config.get("accent_rgb", [90, 220, 255]))
        self.seed = config.get("seed", None)
        self.refresh_hz = float(config.get("refresh_hz", 60.0))

        self.memory_kb = int(config.get("memory_kb", 256))
        self.block_kb = int(config.get("block_kb", 4))

        self.alloc_rate = float(config.get("alloc_rate", 0.85))
        self.free_rate = float(config.get("free_rate", 0.50))
        self.gc_probability_per_min = float(config.get("gc_probability_per_min", 0.40))

        self.scanline_alpha = int(config.get("scanline_alpha", 10))
        self.noise_alpha = int(config.get("noise_alpha", 10))
        self.vignette_strength = float(config.get("vignette_strength", 0.30))

        self.show_hex_dump = bool(config.get("show_hex_dump", True))
        self.portrait_columns = int(config.get("portrait_columns", 2))

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
        self._ram_rect = pygame.Rect(0, 0, 0, 0)
        self._hex_rect = pygame.Rect(0, 0, 0, 0)

        # fonts
        self._font_header = None
        self._font_body = None
        self._font_small = None
        self._font_tiny = None

        # colors
        self._bg = (0, 0, 0)
        self._fg = (235, 235, 235)
        self._dim = (150, 150, 150)

        # memory model
        self._rng = random.Random()
        self._t = 0.0
        self._blocks = 0
        self._mem = []  # 0=free, 1=used, 2=locked
        self._alloc_owner = []  # small id per block (for fun rendering)
        self._next_owner = 1

        # GC animation
        self._gc_active = False
        self._gc_t = 0.0
        self._gc_dur = 1.4
        self._gc_phase = 0.0

        # events
        self._events: list[EventMsg] = []

        # overlays
        self._overlay = None
        self._vignette = None

        # cached hex dump bytes
        self._hex_bytes = bytearray()

    # ---------- lifecycle ----------

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._recompute_layout()
        self._build_overlays()
        self._init_memory()
        self._push_event("INFO", "memory map initialized")

    def exit(self):
        self.manager = None
        self._events = []
        self._overlay = None
        self._vignette = None

    def handle_event(self, event):
        # SPACE forces GC sweep
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self._start_gc(forced=True)

    def update(self, dt: float):
        self._t += dt

        # hotplug / resize
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            self._build_overlays()

        # expire events
        self._events = [e for e in self._events if e.t_end > self._t][-10:]

        # GC state
        if self._gc_active:
            self._gc_t += dt
            self._gc_phase = min(1.0, self._gc_t / max(0.001, self._gc_dur))
            if self._gc_t >= self._gc_dur:
                self._gc_active = False
                self._gc_t = 0.0
                self._gc_phase = 0.0
                self._compact_memory()
                self._push_event("INFO", "gc sweep complete: segments compacted")

        # random GC trigger
        p_gc = max(0.0, self.gc_probability_per_min) / 60.0
        if (not self._gc_active) and (self._rng.random() < p_gc * dt):
            self._start_gc(forced=False)

        # allocations / frees (pause heavy churn during GC to make sweep feel “authoritative”)
        if not self._gc_active:
            self._maybe_alloc(dt)
            self._maybe_free(dt)

        # update faux hex dump bytes from memory state
        if self.show_hex_dump:
            self._update_hex_bytes()

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
        base = min(self.w, self.h)

        self._pad = int(base * 0.05)
        self._header_h = max(86, int(self.h * 0.15))
        self._footer_h = max(44, int(self.h * 0.06))

        self._content_rect = pygame.Rect(
            self._pad,
            self._header_h,
            self.w - 2 * self._pad,
            self.h - self._header_h - self._footer_h
        )

        # layout: RAM big, HEX optional bottom (portrait) or right (landscape)
        cr = self._content_rect
        if self.show_hex_dump:
            if self._is_portrait:
                hex_h = int(cr.height * 0.30)
                self._ram_rect = pygame.Rect(cr.left, cr.top, cr.width, cr.height - hex_h - 10)
                self._hex_rect = pygame.Rect(cr.left, self._ram_rect.bottom + 10, cr.width, hex_h)
            else:
                hex_w = int(cr.width * 0.38)
                self._ram_rect = pygame.Rect(cr.left, cr.top, cr.width - hex_w - 10, cr.height)
                self._hex_rect = pygame.Rect(self._ram_rect.right + 10, cr.top, hex_w, cr.height)
        else:
            self._ram_rect = cr.copy()
            self._hex_rect = pygame.Rect(0, 0, 0, 0)

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

    # ---------- memory model ----------

    def _init_memory(self):
        blocks = max(8, self.memory_kb // max(1, self.block_kb))
        self._blocks = blocks
        self._mem = [0] * blocks
        self._alloc_owner = [0] * blocks

        # seed with a few used segments to make it interesting immediately
        for _ in range(max(2, blocks // 12)):
            self._alloc_random_segment(min_len=2, max_len=6)

        # some locked “ROM” region at top
        lock_len = max(1, blocks // 24)
        for i in range(lock_len):
            self._mem[i] = 2
            self._alloc_owner[i] = 0

    def _alloc_random_segment(self, min_len: int, max_len: int) -> bool:
        seg_len = self._rng.randint(min_len, max_len)
        # find a run of free blocks
        starts = list(range(0, self._blocks - seg_len))
        self._rng.shuffle(starts)
        for s in starts:
            ok = True
            for i in range(s, s + seg_len):
                if self._mem[i] != 0:
                    ok = False
                    break
            if ok:
                owner = self._next_owner
                self._next_owner = (self._next_owner + 1) % 256
                for i in range(s, s + seg_len):
                    self._mem[i] = 1
                    self._alloc_owner[i] = owner
                return True
        return False

    def _maybe_alloc(self, dt: float):
        rate = max(0.0, self.alloc_rate)
        # poisson-ish
        if self._rng.random() < rate * dt:
            ok = self._alloc_random_segment(min_len=1, max_len=max(2, self._blocks // 18))
            if ok and self._rng.random() < 0.18:
                self._push_event("INFO", "alloc: heap segment reserved")
            elif (not ok) and self._rng.random() < 0.35:
                self._push_event("WARN", "alloc failed: heap fragmented")

    def _maybe_free(self, dt: float):
        rate = max(0.0, self.free_rate)
        if self._rng.random() < rate * dt:
            # choose a used owner and free some of its blocks
            used_idxs = [i for i, v in enumerate(self._mem) if v == 1]
            if not used_idxs:
                return
            pick = self._rng.choice(used_idxs)
            owner = self._alloc_owner[pick]
            # free a run belonging to that owner
            run = [i for i in range(self._blocks) if self._mem[i] == 1 and self._alloc_owner[i] == owner]
            if not run:
                return
            # free contiguous portion around a random run element
            k = self._rng.choice(run)
            # expand left/right while same owner
            l = k
            r = k
            while l - 1 >= 0 and self._mem[l - 1] == 1 and self._alloc_owner[l - 1] == owner and self._rng.random() < 0.8:
                l -= 1
            while r + 1 < self._blocks and self._mem[r + 1] == 1 and self._alloc_owner[r + 1] == owner and self._rng.random() < 0.8:
                r += 1
            for i in range(l, r + 1):
                self._mem[i] = 0
                self._alloc_owner[i] = 0
            if self._rng.random() < 0.18:
                self._push_event("INFO", "free: segment released")

    def _start_gc(self, forced: bool):
        if self._gc_active:
            return
        self._gc_active = True
        self._gc_t = 0.0
        self._gc_dur = 1.25 if not forced else 1.55
        self._gc_phase = 0.0
        self._push_event("INFO", "gc sweep: scanning heap")

    def _compact_memory(self):
        # Keep locked region at start; pack used blocks toward the start after locks.
        lock_end = 0
        while lock_end < self._blocks and self._mem[lock_end] == 2:
            lock_end += 1

        used_pairs = [(v, o) for (v, o) in zip(self._mem[lock_end:], self._alloc_owner[lock_end:]) if v == 1]
        free_count = (self._blocks - lock_end) - len(used_pairs)

        new_mem = self._mem[:lock_end] + [1] * len(used_pairs) + [0] * free_count
        new_owner = self._alloc_owner[:lock_end] + [o for (_, o) in used_pairs] + [0] * free_count

        self._mem = new_mem
        self._alloc_owner = new_owner

    # ---------- hex dump ----------

    def _update_hex_bytes(self):
        # compress block states into bytes for a “dump” vibe
        # 00 free, 7F used, FF locked, plus some owner bits
        b = bytearray()
        for i in range(0, self._blocks, 2):
            v0 = self._mem[i]
            o0 = self._alloc_owner[i] & 0x0F
            v1 = self._mem[i + 1] if i + 1 < self._blocks else 0
            o1 = self._alloc_owner[i + 1] & 0x0F if i + 1 < self._blocks else 0

            def enc(v, o):
                if v == 2:
                    return 0xF0 | o
                if v == 1:
                    return 0x70 | o
                return 0x00 | o

            b.append(enc(v0, o0))
            b.append(enc(v1, o1))
        self._hex_bytes = b

    # ---------- drawing ----------

    def _draw_header(self, screen: pygame.Surface):
        band = pygame.Surface((self.w, self._header_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, 0))

        t1 = self._font_header.render(self.title, True, self.accent_rgb)
        screen.blit(t1, (self._pad, int(self._header_h * 0.18)))

        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        used = sum(1 for v in self._mem if v == 1)
        locked = sum(1 for v in self._mem if v == 2)
        free = self._blocks - used - locked
        frag = self._fragmentation_metric()
        sub = f"RAM: {self.memory_kb} KB   |   BLOCK: {self.block_kb} KB   |   USED:{used:3d}  FREE:{free:3d}  ROM:{locked:3d}   |   FRAG:{frag:0.2f}   |   UTC {ts}"
        t2 = self._font_tiny.render(sub, True, self._dim)
        screen.blit(t2, (self._pad, int(self._header_h * 0.18) + t1.get_height() + 8))

        pygame.draw.line(screen, self._dim, (self._pad, self._header_h - 2), (self.w - self._pad, self._header_h - 2), 2)

    def _draw_footer(self, screen: pygame.Surface):
        y0 = self.h - self._footer_h
        band = pygame.Surface((self.w, self._footer_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, y0))

        hint = "SPACE: force GC sweep   |   turn knob: change modes"
        s = self._font_small.render(hint, True, self._dim)
        screen.blit(s, (self._pad, y0 + (self._footer_h - s.get_height()) // 2))

    def _draw_panels(self, screen: pygame.Surface):
        self._draw_panel(screen, self._ram_rect, "MEMORY MAP", self._draw_ram_map)
        if self.show_hex_dump and self._hex_rect.width > 10:
            self._draw_panel(screen, self._hex_rect, "HEX DUMP", self._draw_hex_dump)

    def _draw_panel(self, screen: pygame.Surface, rect: pygame.Rect, label: str, draw_fn):
        pygame.draw.rect(screen, (0, 0, 0), rect)
        pygame.draw.rect(screen, (*self.accent_rgb, 150), rect, 2)
        lab = self._font_tiny.render(label, True, self._dim)
        screen.blit(lab, (rect.left + 10, rect.top + 8))
        draw_fn(screen, rect)

    def _draw_ram_map(self, screen: pygame.Surface, rect: pygame.Rect):
        inner = rect.inflate(-18, -30)
        inner.top += 18  # space for label already

        # optional multi-column RAM panels (portrait)
        cols = self.portrait_columns if self._is_portrait else max(2, self.portrait_columns)
        cols = max(1, int(cols))
        gap = 10
        panel_w = (inner.width - (cols - 1) * gap) // cols

        blocks_per_panel = math.ceil(self._blocks / cols)

        # decide grid inside each panel
        # use a near-square grid to look “RAM-chippy”
        for c in range(cols):
            pr = pygame.Rect(inner.left + c * (panel_w + gap), inner.top, panel_w, inner.height)
            pygame.draw.rect(screen, (*self.accent_rgb, 80), pr, 1)

            start = c * blocks_per_panel
            end = min(self._blocks, start + blocks_per_panel)
            count = max(1, end - start)

            # compute cell size
            # choose rows based on height: portrait likes tall columns
            rows = max(10, int(math.sqrt(count) * (1.3 if self._is_portrait else 1.0)))
            cols_cells = max(6, math.ceil(count / rows))
            cell_w = max(3, pr.width // cols_cells)
            cell_h = max(3, pr.height // rows)

            # draw cells
            idx = 0
            for r in range(rows):
                for cc in range(cols_cells):
                    i = start + idx
                    idx += 1
                    if i >= end:
                        break
                    v = self._mem[i]
                    owner = self._alloc_owner[i]

                    x = pr.left + cc * cell_w
                    y = pr.top + r * cell_h
                    cell = pygame.Rect(x + 1, y + 1, cell_w - 2, cell_h - 2)

                    if v == 2:  # locked
                        col = (200, 200, 200)
                        a = 140
                    elif v == 1:  # used
                        # slight owner-based shimmer
                        shimmer = 0.65 + 0.35 * math.sin(self._t * 2.2 + owner * 0.22)
                        col = self.accent_rgb
                        a = int(70 + 110 * shimmer)
                    else:
                        col = (60, 60, 60)
                        a = 60

                    pygame.draw.rect(screen, (*col, a), cell)

            # address markers down the left
            mark_every = max(8, rows // 6)
            for r in range(0, rows, mark_every):
                addr = (start + r * cols_cells) * self.block_kb * 1024
                s = self._font_tiny.render(f"{addr:06X}", True, self._dim)
                screen.blit(s, (pr.left + 6, pr.top + r * cell_h + 2))

        # GC sweep bar overlay
        if self._gc_active:
            sweep_y = inner.top + int(self._gc_phase * inner.height)
            bar_h = max(6, int(inner.height * 0.03))
            bar = pygame.Surface((inner.width, bar_h), pygame.SRCALPHA)
            for i in range(bar_h):
                a = int(140 * (1.0 - abs((i / max(1, bar_h - 1)) - 0.5) * 2.0))
                pygame.draw.line(bar, (*self.accent_rgb, a), (0, i), (inner.width, i), 1)
            screen.blit(bar, (inner.left, sweep_y - bar_h // 2))

    def _draw_hex_dump(self, screen: pygame.Surface, rect: pygame.Rect):
        inner = rect.inflate(-18, -30)
        inner.top += 18

        # draw frame
        pygame.draw.rect(screen, (*self.accent_rgb, 80), inner, 1)

        # rows of hex
        bytes_per_row = 16
        max_rows = max(1, inner.height // (self._font_tiny.get_linesize() + 4))

        # show the tail (recent-ish)
        data = self._hex_bytes
        total_rows = max(1, (len(data) + bytes_per_row - 1) // bytes_per_row)
        start_row = max(0, total_rows - max_rows)

        y = inner.top + 6
        for rr in range(start_row, min(total_rows, start_row + max_rows)):
            off = rr * bytes_per_row
            chunk = data[off:off + bytes_per_row]
            addr = off
            hexs = " ".join(f"{b:02X}" for b in chunk)
            # ascii-ish
            asc = "".join(chr(32 + (b & 0x3F)) if 32 <= (32 + (b & 0x3F)) < 127 else "." for b in chunk)
            line = f"{addr:04X}: {hexs:<47} |{asc}|"

            s = self._font_tiny.render(line[:86], True, self._dim)
            screen.blit(s, (inner.left + 8, y))
            y += self._font_tiny.get_linesize() + 4

        # event lines on bottom
        y2 = rect.bottom - 10 - (self._font_small.get_linesize() + 6) * min(3, len(self._events))
        for e in self._events[::-1][:3]:
            col = self._dim if e.kind == "INFO" else (255, 220, 150)
            s = self._font_small.render(f"[{e.kind}] {e.text}", True, col)
            screen.blit(s, (rect.left + 14, y2))
            y2 += s.get_height() + 4

    def _fragmentation_metric(self) -> float:
        # simple: count free runs vs free blocks
        free = [i for i, v in enumerate(self._mem) if v == 0]
        if not free:
            return 0.0
        runs = 0
        i = 0
        while i < self._blocks:
            if self._mem[i] == 0:
                runs += 1
                while i < self._blocks and self._mem[i] == 0:
                    i += 1
            else:
                i += 1
        return min(1.0, runs / max(1, len(free)))

    def _push_event(self, kind: str, text: str):
        ttl = 9.0 if kind == "INFO" else 12.0
        self._events.append(EventMsg(t_end=self._t + ttl, kind=kind, text=text))

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

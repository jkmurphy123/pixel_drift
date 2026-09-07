# retro_crt_hacker_terminal_mode.py

import math
import random
from datetime import datetime

import pygame


class RetroCRTHackerTerminalMode:
    """
    Retro CRT Hacker Terminal.
    A looping fake terminal session with typing, cursor blink, scanlines, CRT curvature, and glitches.

    Config (all optional):
      - title (str): header label (default "RETRO CRT TERMINAL")
      - palette (str): "green" | "amber" | "cyan" | "white" (default "green")
      - prompt (str): prompt prefix (default "root@node:/#")
      - typing_cps (float): characters per second (default 36)
      - cursor_blink_hz (float): cursor blink (default 2.0)
      - lines_on_screen (int): max visible lines (default auto)
      - max_lines (int): alias for lines_on_screen (default auto)
      - max_chars_per_line (int): max characters before wrapping (default auto)
      - glitch_probability_per_min (float): random glitch events (default 1.0)
      - jitter_px (int): max horizontal jitter during glitch (default 2)
      - scanline_alpha (int): 0..255 (default 16)
      - noise_alpha (int): 0..255 (default 12)
      - crt_curvature (float): 0..0.35 recommended (default 0.14)
      - crt_vignette (float): 0..1 (default 0.32)
      - crt_chroma (float): 0..0.3 (default 0.08)
      - seed (int): reproducible RNG seed (default random)
    """

    def __init__(self, config: dict):
        self.title = str(config.get("title", "RETRO CRT TERMINAL"))
        self.palette = str(config.get("palette", "green")).lower()
        self.prompt = str(config.get("prompt", "root@node:/#"))

        self.typing_cps = float(config.get("typing_cps", 36.0))
        self.cursor_blink_hz = float(config.get("cursor_blink_hz", 2.0))
        self.lines_on_screen_cfg = config.get("lines_on_screen", None)
        self.max_lines_cfg = config.get("max_lines", None)
        self.max_chars_per_line_cfg = config.get("max_chars_per_line", None)

        self.glitch_probability_per_min = float(config.get("glitch_probability_per_min", 1.0))
        self.jitter_px = int(config.get("jitter_px", 2))

        self.scanline_alpha = int(config.get("scanline_alpha", 16))
        self.noise_alpha = int(config.get("noise_alpha", 12))

        self.crt_curvature = float(config.get("crt_curvature", 0.14))
        self.crt_vignette = float(config.get("crt_vignette", 0.32))
        self.crt_chroma = float(config.get("crt_chroma", 0.08))

        self.seed = config.get("seed", None)

        # runtime
        self.manager = None
        self.w = 0
        self.h = 0

        # colors (set in enter)
        self._bg = (0, 0, 0)
        self._fg = (220, 255, 220)
        self._dim = (120, 160, 120)
        self._accent = (140, 255, 170)

        # layout
        self._pad = 0
        self._header_h = 0
        self._footer_h = 0
        self._term_rect = pygame.Rect(0, 0, 0, 0)

        # fonts
        self._font_size = 18
        self._font = None
        self._font_bold = None
        self._char_w = 10
        self._line_h = 18
        self._max_cols = 80
        self._max_lines = 28

        # terminal buffers
        self._scrollback = []  # list[str]
        self._current_line = ""
        self._typing_queue = ""  # text remaining to type (may include \n)
        self._typing_progress = 0.0

        # session script
        self._script_blocks = []
        self._script_i = 0

        # fx
        self._t = 0.0
        self._rng = random.Random()

        self._scan_surf = None
        self._frame_surf = None
        self._crt_warp_surf = None
        self._vignette_surf = None

        self._glitch_t = 999.0
        self._glitch_dur = 0.0
        self._glitch_jitter = 0

    # ---------- lifecycle ----------

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._set_palette()
        self._recompute_layout()
        self._build_overlays()

        self._build_script()
        self._scrollback = []
        self._current_line = ""
        self._script_i = 0
        self._typing_queue = ""
        self._typing_progress = 0.0

        self._enqueue_next_block(force_prompt=True)

    def exit(self):
        self.manager = None
        self._scrollback = []
        self._typing_queue = ""
        self._frame_surf = None
        self._crt_warp_surf = None
        self._scan_surf = None
        self._vignette_surf = None

    def handle_event(self, event):
        # SPACE: jump to next block (fun for demos)
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self._enqueue_next_block(force_prompt=True)

    def update(self, dt: float):
        self._t += dt

        # handle resolution changes (hotplug, rotation, etc.)
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            self._build_overlays()

        # probabilistic glitch trigger
        p = max(0.0, self.glitch_probability_per_min) / 60.0
        if self._glitch_t >= (self._glitch_dur if self._glitch_dur > 0 else 0.0):
            if self._rng.random() < p * dt:
                self._start_glitch()

        # advance glitch time
        self._glitch_t += dt
        if self._glitch_t < self._glitch_dur:
            self._glitch_jitter = self._rng.randint(-self.jitter_px, self.jitter_px) if self.jitter_px > 0 else 0
        else:
            self._glitch_jitter = 0

        # typing simulation
        if self._typing_queue:
            self._typing_progress += self.typing_cps * dt
            n = int(self._typing_progress)
            if n > 0:
                self._typing_progress -= n
                chunk = self._typing_queue[:n]
                self._typing_queue = self._typing_queue[n:]
                self._consume_typed_text(chunk)

        # if idle, enqueue next script chunk
        if (not self._typing_queue) and self._script_blocks:
            if self._rng.random() < 0.012:  # small pause randomness
                return
            self._enqueue_next_block(force_prompt=False)

    def render(self, screen: pygame.Surface):
        if self._frame_surf is None:
            self._frame_surf = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        fs = self._frame_surf
        fs.fill(self._bg)

        self._draw_header(fs)
        self._draw_terminal(fs)
        self._draw_footer(fs)

        if self._scan_surf is not None and self.scanline_alpha > 0:
            fs.blit(self._scan_surf, (0, 0))

        if self.noise_alpha > 0:
            self._draw_noise(fs)

        # CRT curvature postprocess -> blit to screen
        self._blit_crt(screen, fs, jitter_x=self._glitch_jitter)

    # ---------- layout / palette ----------

    def _set_palette(self):
        if self.palette == "amber":
            self._fg = (255, 220, 140)
            self._dim = (170, 130, 70)
            self._accent = (255, 200, 90)
        elif self.palette == "cyan":
            self._fg = (200, 255, 255)
            self._dim = (120, 170, 170)
            self._accent = (120, 240, 255)
        elif self.palette == "white":
            self._fg = (235, 235, 235)
            self._dim = (150, 150, 150)
            self._accent = (220, 255, 220)
        else:  # green default
            self._fg = (220, 255, 220)
            self._dim = (120, 160, 120)
            self._accent = (140, 255, 170)

    def _recompute_layout(self):
        self.w, self.h = self.manager.screen.get_size()

        self._pad = int(min(self.w, self.h) * 0.045)
        self._header_h = max(54, int(self.h * 0.10))
        self._footer_h = max(34, int(self.h * 0.06))

        self._term_rect = pygame.Rect(
            self._pad,
            self._header_h,
            self.w - 2 * self._pad,
            self.h - self._header_h - self._footer_h
        )

        # font sizing tuned for "wall art" readability
        self._font_size = max(16, int(min(self.w, self.h) * 0.030))
        self._font = self.manager.cache.get_font("dejavusansmono", self._font_size, bold=False)
        self._font_bold = self.manager.cache.get_font("dejavusansmono", int(self._font_size * 1.05), bold=True)

        # estimate character cell size (monospace)
        test = self._font.render("M", True, self._fg)
        self._char_w = max(6, test.get_width())
        self._line_h = max(12, self._font.get_linesize() + 2)

        auto_cols = max(32, self._term_rect.width // self._char_w)
        if self.max_chars_per_line_cfg is not None:
            self._max_cols = max(8, int(self.max_chars_per_line_cfg))
        else:
            self._max_cols = auto_cols

        auto_lines = max(10, self._term_rect.height // self._line_h)
        lines_cfg = self.max_lines_cfg if self.max_lines_cfg is not None else self.lines_on_screen_cfg
        if lines_cfg is not None:
            self._max_lines = max(1, int(lines_cfg))
        else:
            self._max_lines = auto_lines

        self._frame_surf = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        self._crt_warp_surf = pygame.Surface((self.w, self.h), pygame.SRCALPHA)

    def _build_overlays(self):
        self._scan_surf = None
        self._vignette_surf = None

    # ---------- terminal script + typing ----------

    def _build_script(self):
        # Think of these as “blocks” that will be typed in order.
        # Include pauses by adding empty strings or shorter blocks.
        now_tag = datetime.now().strftime("%Y.%m.%d-%H%M")
        banner = [
            "NEONHELIX SYSTEMS",
            f"build {now_tag}  kernel 6.x  tty/0",
            "----------------------------------------",
        ]
        ascii_skull = [
            "        .-.",
            "       (o o)  SIGNAL FOUND",
            "       | O \\  establishing link",
            "        \\   \\",
            "         `~~~'",
        ]

        self._script_blocks = [
            "\n".join(banner) + "\n",
            "boot: initializing i/o bus...\n",
            "boot: mounting /vault [OK]\n",
            "boot: entropy pool warmed\n",
            "\n",
            f"{self.prompt} whoami\n",
            "root\n",
            f"{self.prompt} ifconfig uplink0\n",
            "uplink0: flags=8843<UP,BROADCAST,RUNNING>  mtu 1500\n"
            "        inet 10.77.0.42  netmask 255.255.0.0\n"
            "        rx packets 34912  tx packets 22904\n",
            "\n",
            f"{self.prompt} scan --band=ku --mode=quiet\n",
            "[scan] sweeping...  (quiet)\n",
            "[scan] ping: 0xA7  0xA7  0x19  0xFF\n",
            "[scan] handshake window open\n",
            "\n",
            f"{self.prompt} decrypt relay://uplink/core --key=~/.keys/ghost\n",
            "loading key material... ok\n",
            "negotiating cipher suite... ok\n",
            "stream: █▒▒▒▒▒▒▒▒▒▒  12%\n",
            "stream: ████▒▒▒▒▒▒▒  41%\n",
            "stream: ███████▒▒▒▒  73%\n",
            "stream: ██████████  100%\n",
            "\n".join(ascii_skull) + "\n",
            "\n",
            f"{self.prompt} ls -la /vault/archive\n",
            "drwxr-xr-x  3 root root     4096 .\n"
            "drwxr-xr-x 12 root root     4096 ..\n"
            "-rw-------  1 root root   1048576 blackbox.bin\n"
            "-rw-r--r--  1 root root     22784 notes.txt\n"
            "-rw-r--r--  1 root root      4096 map.grid\n",
            "\n",
            f"{self.prompt} cat /vault/archive/notes.txt | head\n",
            "DO NOT TRUST THE TIMESTAMPS.\n"
            "If the console says 'LOCKED', it is only describing itself.\n"
            "Do not answer unknown prompts.\n"
            "Do not feed the echo.\n",
            "\n",
            f"{self.prompt} run intrusion --target relay --stealth\n",
            "[intrusion] stage 1/4: locate route... ok\n",
            "[intrusion] stage 2/4: mirror handshake... ok\n",
            "[intrusion] stage 3/4: inject token... ok\n",
            "[intrusion] stage 4/4: exfil stream... ok\n",
            "\n",
            f"{self.prompt} logout\n",
            "Connection closed.\n",
            "\n",
        ]

    def _enqueue_next_block(self, force_prompt: bool):
        if not self._script_blocks:
            return

        block = self._script_blocks[self._script_i % len(self._script_blocks)]
        self._script_i += 1

        # Occasionally insert a prompt line before blocks (adds realism)
        if force_prompt and block and not block.startswith(self.prompt):
            block = f"{self.prompt} " + block

        # Occasionally insert a “glitch” mutation right into the typing stream
        if self._rng.random() < 0.08:
            block = self._mutate_text(block)

        self._typing_queue += block

        # Hard cap scrollback memory
        if len(self._scrollback) > 2000:
            self._scrollback = self._scrollback[-1500:]

    def _consume_typed_text(self, chunk: str):
        for ch in chunk:
            if ch == "\n":
                self._push_line(self._current_line)
                self._current_line = ""
            else:
                self._current_line += ch
                # wrap long lines
                if len(self._current_line) >= self._max_cols:
                    self._push_line(self._current_line)
                    self._current_line = ""

    def _push_line(self, line: str):
        self._scrollback.append(line.rstrip("\r"))
        # keep screen scrollback bounded
        if len(self._scrollback) > 4000:
            self._scrollback = self._scrollback[-3000:]

    def _mutate_text(self, s: str) -> str:
        # quick “bitrot”: sprinkle a few weird chars and duplicated fragments
        if not s:
            return s
        chars = list(s)
        n = self._rng.randint(1, 4)
        for _ in range(n):
            i = self._rng.randrange(0, len(chars))
            chars[i] = self._rng.choice(list("▓▒░#/\\|{}[]<>"))
        if self._rng.random() < 0.35:
            j = self._rng.randrange(0, max(1, len(chars) - 10))
            frag = "".join(chars[j:j + self._rng.randint(4, 10)])
            chars = chars[:j] + list(frag) + chars[j:]
        return "".join(chars)

    # ---------- drawing ----------

    def _draw_header(self, screen: pygame.Surface):
        band = pygame.Surface((self.w, self._header_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 210))
        screen.blit(band, (0, 0))

        title_font = self.manager.cache.get_font("dejavusansmono", int(self._font_size * 1.15), bold=True)
        sub_font = self.manager.cache.get_font("dejavusansmono", int(self._font_size * 0.78), bold=False)

        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        t1 = title_font.render(self.title, True, self._accent)
        t2 = sub_font.render(f"UTC {ts}   |   tty0   |   phosphor=OK", True, self._dim)

        screen.blit(t1, (self._pad, int(self._header_h * 0.20)))
        screen.blit(t2, (self._pad, int(self._header_h * 0.20) + t1.get_height() + 2))

        pygame.draw.line(screen, self._dim, (self._pad, self._header_h - 2), (self.w - self._pad, self._header_h - 2), 2)

    def _draw_terminal(self, screen: pygame.Surface):
        r = self._term_rect

        # panel border
        pygame.draw.rect(screen, (0, 0, 0), r)
        pygame.draw.rect(screen, self._dim, r, 2)

        # visible lines
        visible = self._scrollback[-self._max_lines:]
        x = r.left + 12
        y = r.top + 10

        # faint “phosphor bloom” under text via alpha shadow
        glow = pygame.Surface((r.width, r.height), pygame.SRCALPHA)

        for ln in visible:
            # occasional transient line-level glitch
            draw_ln = ln
            if self._glitch_t < self._glitch_dur and self._rng.random() < 0.08:
                draw_ln = self._mutate_text(draw_ln)

            shadow = self._font.render(draw_ln, True, self._dim)
            text = self._font.render(draw_ln, True, self._fg)

            glow.blit(shadow, (x - r.left + 1, y - r.top + 1))
            screen.blit(text, (x + self._glitch_jitter, y))
            y += self._line_h
            if y > r.bottom - self._line_h * 2:
                break

        # draw current line (typing) + cursor
        cur = self._current_line
        cur_shadow = self._font.render(cur, True, self._dim)
        cur_text = self._font.render(cur, True, self._fg)
        glow.blit(cur_shadow, (x - r.left + 1, y - r.top + 1))
        screen.blit(cur_text, (x + self._glitch_jitter, y))

        # cursor blink
        blink = (math.sin(self._t * math.tau * self.cursor_blink_hz) > 0.0)
        if blink:
            cx = x + self._font.size(cur)[0] + self._glitch_jitter
            cy = y + 2
            pygame.draw.rect(screen, self._fg, pygame.Rect(cx, cy, max(10, self._char_w), self._line_h - 4), 0)

        # bloom overlay (soften)
        glow.set_alpha(70)
        screen.blit(glow, r.topleft)

        # little “status lights”
        sx = r.right - 120
        sy = r.top + 10
        for i in range(3):
            a = 120 if (i == 0 or (self._glitch_t < self._glitch_dur and i == 2)) else 40
            pygame.draw.circle(screen, (*self._accent, a), (sx + i * 18, sy + 8), 5, 0)

    def _draw_footer(self, screen: pygame.Surface):
        y0 = self.h - self._footer_h
        band = pygame.Surface((self.w, self._footer_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 210))
        screen.blit(band, (0, y0))

        font = self.manager.cache.get_font("dejavusansmono", int(self._font_size * 0.75), bold=False)
        hint = "SPACE: jump block   |   knob: change modes"
        surf = font.render(hint, True, self._dim)
        screen.blit(surf, (self._pad, y0 + (self._footer_h - surf.get_height()) // 2))

    # ---------- FX: glitch / noise / CRT ----------

    def _start_glitch(self):
        self._glitch_t = 0.0
        self._glitch_dur = self._rng.uniform(0.18, 0.55)
        # also inject a short “error burst” into the typing queue
        if self._rng.random() < 0.6:
            self._typing_queue = self._mutate_text(self._typing_queue[:80]) + self._typing_queue[80:]

    def _draw_noise(self, screen: pygame.Surface):
        n = max(200, (self.w * self.h) // 8000)
        s = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        for _ in range(n):
            x = self._rng.randrange(0, self.w)
            y = self._rng.randrange(0, self.h)
            a = self._rng.randrange(0, self.noise_alpha + 1)
            s.set_at((x, y), (255, 255, 255, a))
        screen.blit(s, (0, 0))

    def _build_vignette(self, w: int, h: int, strength: float):
        strength = max(0.0, min(1.0, float(strength)))
        if strength <= 0.0:
            return None
        v = pygame.Surface((w, h), pygame.SRCALPHA)
        layers = 70
        max_a = int(210 * strength)
        for i in range(layers):
            a = int(max_a * (i / layers) ** 1.9)
            pygame.draw.rect(v, (0, 0, 0, a), pygame.Rect(i, i, w - 2 * i, h - 2 * i), 1)
        return v

    def _blit_crt(self, screen: pygame.Surface, src: pygame.Surface, jitter_x: int = 0):
        curv = max(0.0, min(float(self.crt_curvature), 0.45))
        chroma = max(0.0, min(float(self.crt_chroma), 0.35))
        chroma_px = int(chroma * 10)

        if curv <= 0.001:
            screen.blit(src, (jitter_x, 0))
            if self._vignette_surf is not None:
                screen.blit(self._vignette_surf, (0, 0))
            return

        dst = self._crt_warp_surf
        dst.fill((0, 0, 0, 255))

        w = self.w
        h = self.h
        cy = h * 0.5
        cx = w * 0.5

        step = 2
        for y in range(0, h, step):
            yn = (y - cy) / max(1.0, cy)
            shrink = 1.0 - (curv * (yn * yn))
            shrink = max(0.78, min(1.0, shrink))

            new_w = int(w * shrink)
            x0 = int(cx - new_w * 0.5) + jitter_x

            sl = src.subsurface(pygame.Rect(0, y, w, min(step, h - y)))
            if new_w != w:
                sl = pygame.transform.smoothscale(sl, (new_w, sl.get_height()))
            dst.blit(sl, (x0, y))

        if chroma_px > 0:
            base = dst.copy()
            dst.fill((0, 0, 0, 255))
            dst.blit(base, (-chroma_px, 0), special_flags=pygame.BLEND_RGB_ADD)
            dst.blit(base, (chroma_px, 0), special_flags=pygame.BLEND_RGB_ADD)
            dst.blit(base, (0, 0))

        screen.blit(dst, (0, 0))
        if self._vignette_surf is not None:
            screen.blit(self._vignette_surf, (0, 0))

    # ---------- helpers ----------

    def _reseed(self):
        if self.seed is None:
            self.seed = random.randrange(1, 2**31 - 1)
        self._rng.seed(int(self.seed))

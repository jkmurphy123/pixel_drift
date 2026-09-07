# modes/quote_slideshow_mode.py
#
# Slideshow with centred quote overlay.  Images advance on a timer;
# each image change also advances to the next quote in the JSON file.
# Quotes loop back to the start after the last one.
#
# Optional audio: if a quote has a non-null "audio" path, the mode
# plays it via pygame.mixer when the quote appears — controlled by
# the `play_audio` config flag (default off).
#
# The quote is drawn centred (horizontally + vertically) inside a
# semi-transparent rounded panel so it remains readable over any
# background image.

import json
import os
import random
import time
from collections import OrderedDict

import pygame


class _LRU:
    """Tiny LRU cache for scaled image surfaces (avoids re-scaling)."""

    def __init__(self, max_items=3):
        self.max_items = max_items
        self._d = OrderedDict()

    def get(self, key):
        if key in self._d:
            self._d.move_to_end(key)
            return self._d[key]
        return None

    def put(self, key, value):
        self._d[key] = value
        self._d.move_to_end(key)
        while len(self._d) > self.max_items:
            _, old = self._d.popitem(last=False)
            del old


class QuoteSlideshowMode:
    """
    Slideshow with a centred dystopian quote overlay.

    Config keys:
      folder            (required) path to image directory
      duration          (required) seconds per image
      quote_file        (required) path to quotes JSON file

      play_audio        bool, default False — play quote audio if available
      scale_mode        'cover' (default) | 'contain'
      shuffle_images    bool, default True

      quote_panel_alpha int 0..255, default 160 — background panel opacity
      quote_panel_color [r,g,b], default [20,20,30]
      quote_text_color  [r,g,b], default [240,240,245]
      quote_author_color [r,g,b], default [180,180,200]
      quote_font_scale  float, default 0.035 — relative to screen height
      quote_max_width_frac float, default 0.72 — max text width fraction of screen
      quote_line_spacing  float, default 1.35
    """

    def __init__(self, config: dict):
        # ── core slideshow config ────────────────────────────
        self.folder = config.get("folder", ".")
        self.duration = float(config.get("duration", 10))
        self.name = config.get("name", "Quote Slideshow")
        self.scale_mode = str(config.get("scale_mode", "cover")).lower()
        self.shuffle_images = bool(config.get("shuffle_images", True))

        # ── quote config ─────────────────────────────────────
        self.quote_file = config.get("quote_file", "quotes_dystopian.json")
        self.play_audio = bool(config.get("play_audio", False))

        self.panel_alpha = int(config.get("quote_panel_alpha", 160))
        self.panel_color = tuple(config.get("quote_panel_color", [20, 20, 30]))
        self.quote_text_color = tuple(config.get("quote_text_color", [240, 240, 245]))
        self.author_color = tuple(config.get("quote_author_color", [180, 180, 200]))
        self.quote_font_scale = float(config.get("quote_font_scale", 0.035))
        self.quote_max_width_frac = float(config.get("quote_max_width_frac", 0.72))
        self.quote_line_spacing = float(config.get("quote_line_spacing", 1.35))

        # ── runtime state ────────────────────────────────────
        self.manager = None
        self.screen_w = 0
        self.screen_h = 0

        self._images = []          # list of image paths
        self._image_index = 0
        self._current_surf = None  # current scaled image Surface
        self._current_path = None
        self._next_swap_at = 0.0

        self._scaled_cache = _LRU(max_items=2)

        self._quotes = []          # list of quote dicts
        self._quote_index = 0
        self._current_quote = None

        # Audio state
        self._audio_initialized = False

    # ── lifecycle ────────────────────────────────────────────

    def enter(self, manager):
        self.manager = manager
        self.screen_w, self.screen_h = manager.screen.get_size()

        self._images = self._load_image_list()
        if self.shuffle_images:
            random.shuffle(self._images)
        self._image_index = 0

        self._quotes = self._load_quotes()
        if self.shuffle_images:          # shuffle quotes too so each run is fresh
            random.shuffle(self._quotes)
        self._quote_index = 0
        self._current_quote = None

        self._current_surf = None
        self._current_path = None
        self._next_swap_at = time.time()

        # Init audio mixer lazily
        if self.play_audio:
            self._init_audio()

    def exit(self):
        self._current_surf = None
        self._current_path = None
        self._images = []
        self._quotes = []
        self.manager = None

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_SPACE, pygame.K_RIGHT):
                # Manual advance
                self._advance_image(time.time())

    def update(self, dt: float):
        if not self._images:
            return
        now = time.time()
        if self._current_surf is None or now >= self._next_swap_at:
            self._advance_image(now)

    def render(self, screen: pygame.Surface):
        screen.fill((0, 0, 0))

        if not self._images:
            self._draw_no_images(screen)
            return

        # ── background image ─────────────────────────────────
        if self._current_surf:
            rect = self._current_surf.get_rect(center=screen.get_rect().center)
            screen.blit(self._current_surf, rect)

        # ── quote overlay ────────────────────────────────────
        if self._current_quote:
            self._draw_quote(screen, self._current_quote)

    # ── image management ─────────────────────────────────────

    def _advance_image(self, now: float):
        """Swap to the next image AND the next quote."""
        # Image
        self._current_path = self._images[self._image_index]
        self._image_index = (self._image_index + 1) % len(self._images)

        # Drop old
        if self._current_surf is not None:
            old = self._current_surf
            self._current_surf = None
            del old

        self._current_surf = self._load_and_scale(self._current_path)
        self._next_swap_at = now + self.duration

        # Quote — advance in lockstep
        if self._quotes:
            self._current_quote = self._quotes[self._quote_index]
            self._quote_index = (self._quote_index + 1) % len(self._quotes)

            # Optional audio
            if self.play_audio:
                audio_path = self._current_quote.get("audio")
                if audio_path:
                    self._play_audio_file(audio_path)
        else:
            self._current_quote = None

    def _load_image_list(self):
        if not os.path.isdir(self.folder):
            print(f"[QuoteSlideshow] folder does not exist: {self.folder}")
            return []
        exts = (".png", ".jpg", ".jpeg", ".bmp", ".gif")
        files = [
            os.path.join(self.folder, f)
            for f in os.listdir(self.folder)
            if f.lower().endswith(exts)
        ]
        files.sort()
        print(f"[QuoteSlideshow] found {len(files)} image(s) in {self.folder}")
        return files

    def _load_and_scale(self, path):
        tw, th = self.screen_w, self.screen_h

        # Check cache
        cached = self._scaled_cache.get(path)
        if cached is not None:
            return cached

        try:
            img = pygame.image.load(path)
            if path.lower().endswith(".png"):
                img = img.convert_alpha()
            else:
                img = img.convert()

            iw, ih = img.get_width(), img.get_height()
            if iw <= 0 or ih <= 0:
                return None

            if self.scale_mode == "contain":
                scale = min(tw / iw, th / ih)
            else:
                scale = max(tw / iw, th / ih)

            nw = max(1, int(iw * scale))
            nh = max(1, int(ih * scale))
            scaled = pygame.transform.smoothscale(img, (nw, nh))
            del img

            if self.scale_mode == "cover":
                out = pygame.Surface((tw, th))
                out.fill((0, 0, 0))
                src_rect = scaled.get_rect(center=(tw // 2, th // 2))
                out.blit(scaled, (0, 0), area=src_rect)
                del scaled
                self._scaled_cache.put(path, out)
                return out

            self._scaled_cache.put(path, scaled)
            return scaled

        except Exception as e:
            print(f"[QuoteSlideshow] Failed to load image '{path}': {e}")
            return None

    # ── quotes ───────────────────────────────────────────────

    def _load_quotes(self):
        path = self.quote_file
        # Resolve relative to project base if not absolute
        if not os.path.isabs(path):
            base = os.path.dirname(os.path.dirname(__file__))
            path = os.path.join(base, path)

        try:
            with open(path, "r") as f:
                data = json.load(f)
            quotes = data.get("quotes", [])
            print(f"[QuoteSlideshow] loaded {len(quotes)} quote(s) from {path}")
            return quotes
        except Exception as e:
            print(f"[QuoteSlideshow] Failed to load quotes '{path}': {e}")
            return []

    # ── drawing ──────────────────────────────────────────────

    def _draw_quote(self, screen: pygame.Surface, quote: dict):
        """Draw the quote centred on screen inside a semi-transparent panel."""
        text = quote.get("text", "")
        author = quote.get("author", "")
        if not text:
            return

        sw, sh = self.screen_w, self.screen_h

        # ── font ─────────────────────────────────────────────
        font_size = max(14, int(sh * self.quote_font_scale))
        author_size = max(12, int(font_size * 0.7))
        font = self.manager.cache.get_font(None, font_size, bold=False)
        author_font = self.manager.cache.get_font(None, author_size, bold=False)

        # ── word-wrap the quote text ─────────────────────────
        max_width = int(sw * self.quote_max_width_frac)
        lines = self._wrap_text(text, font, max_width)

        # ── measure ──────────────────────────────────────────
        line_height = int(font.get_linesize() * self.quote_line_spacing)
        text_block_h = len(lines) * line_height

        author_surf = author_font.render(author, True, self.author_color) if author else None
        author_h = author_surf.get_height() + (line_height // 3) if author_surf else 0

        total_h = text_block_h + author_h

        # ── panel background ─────────────────────────────────
        pad_x = int(sw * 0.04)
        pad_y = int(sh * 0.025)
        corner_radius = int(sh * 0.018)

        panel_w = min(sw - pad_x * 2, max_width + pad_x * 2 + 20)
        panel_h = total_h + pad_y * 2

        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 0))

        # Rounded rectangle
        bg_color = (*self.panel_color, self.panel_alpha)
        self._draw_rounded_rect(panel, bg_color,
                                pygame.Rect(0, 0, panel_w, panel_h),
                                corner_radius)

        # Blit panel centred on screen
        px = (sw - panel_w) // 2
        py = (sh - panel_h) // 2

        # ── draw text onto panel ─────────────────────────────
        text_start_y = pad_y
        for i, line in enumerate(lines):
            line_surf = font.render(line, True, self.quote_text_color)
            # Horizontal centre within panel
            lx = (panel_w - line_surf.get_width()) // 2
            ly = text_start_y + i * line_height
            panel.blit(line_surf, (lx, ly))

        # ── author ───────────────────────────────────────────
        if author_surf:
            ax = (panel_w - author_surf.get_width()) // 2
            ay = text_start_y + text_block_h + (line_height // 3)
            panel.blit(author_surf, (ax, ay))

        # ── blit panel to screen ─────────────────────────────
        # Shadow first
        shadow = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        shadow.fill((0, 0, 0, 60))
        self._draw_rounded_rect(shadow, (0, 0, 0, 60),
                                pygame.Rect(0, 0, panel_w, panel_h),
                                corner_radius)
        screen.blit(shadow, (px + 4, py + 4))
        screen.blit(panel, (px, py))

    def _wrap_text(self, text: str, font, max_width: int) -> list:
        """Word-wrap text to fit within max_width, returning list of lines."""
        words = text.split(" ")
        lines = []
        current = ""

        for word in words:
            test = word if not current else current + " " + word
            w = font.size(test)[0]
            if w <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word  # start new line (may itself exceed width)

        if current:
            lines.append(current)

        return lines

    @staticmethod
    def _draw_rounded_rect(surf, color, rect, radius):
        """Draw a filled rounded rectangle on a Surface."""
        x, y, w, h = rect
        r = min(radius, w // 2, h // 2)

        # Rectangles for the body (minus corners)
        # Main centre
        pygame.draw.rect(surf, color, (x + r, y, w - 2 * r, h))
        pygame.draw.rect(surf, color, (x, y + r, w, h - 2 * r))

        # Four corner circles
        for cx, cy in [(x + r, y + r), (x + w - r - 1, y + r),
                       (x + r, y + h - r - 1), (x + w - r - 1, y + h - r - 1)]:
            pygame.draw.circle(surf, color, (cx, cy), r)

    def _draw_no_images(self, screen):
        """Placeholder when no images are found."""
        screen.fill((10, 10, 20))
        if self.manager:
            font = self.manager.cache.get_font(None, 28, bold=False)
            msg = font.render("No images found", True, (200, 60, 60))
            rect = msg.get_rect(center=(self.screen_w // 2, self.screen_h // 2))
            screen.blit(msg, rect)

    # ── audio ────────────────────────────────────────────────

    def _init_audio(self):
        if self._audio_initialized:
            return
        try:
            pygame.mixer.init()
            self._audio_initialized = True
            print("[QuoteSlideshow] audio mixer initialized")
        except Exception as e:
            print(f"[QuoteSlideshow] audio init failed: {e}")

    def _play_audio_file(self, path: str):
        """Play an audio file (non-blocking)."""
        if not self._audio_initialized:
            return
        # Resolve relative paths
        if not os.path.isabs(path):
            base = os.path.dirname(os.path.dirname(__file__))
            path = os.path.join(base, path)
        if not os.path.isfile(path):
            print(f"[QuoteSlideshow] audio file not found: {path}")
            return
        try:
            sound = pygame.mixer.Sound(path)
            sound.play()
            print(f"[QuoteSlideshow] playing audio: {path}")
        except Exception as e:
            print(f"[QuoteSlideshow] audio play failed for '{path}': {e}")

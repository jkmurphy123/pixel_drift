# quote_generator_mode.py

import os
import time
import json
import re
import threading
import queue

import pygame

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


class QuoteGeneratorMode:
    """
    Scene-style AI quote generator.

    Shared / type-level:
      - openai_api_key (required if using API)
      - model (default "gpt-4o-mini")
      - max_api_calls_default (default 100)

    Instance-level:
      - theme: str
      - duration: seconds per quote
      - image_path: optional background image path
      - text_position: "top" | "middle" | "bottom"

    Presentation:
      - font_name (optional)
      - font_size (default 56)
      - text_color_rgb (default [240,240,240])
      - bg_color_rgb (default [0,0,0])
      - overlay_alpha (default 140) backing box alpha for readability
    """

    def __init__(self, config: dict):
        # behavior
        self.theme = str(config.get("theme", "Motivational"))
        self.duration = float(config.get("duration", 30))

        self.max_api_calls = int(config.get("max_api_calls", config.get("max_api_calls_default", 100)))

        # OpenAI
        self.api_key = config.get("openai_api_key")
        self.model = config.get("model", "gpt-4o-mini")

        self._client = None
        if OpenAI and self.api_key:
            try:
                self._client = OpenAI(api_key=self.api_key)
            except Exception:
                self._client = None

        # presentation
        self.font_name = config.get("font_name", None)
        self.font_size = int(config.get("font_size", 56))
        self.text_color = tuple(config.get("text_color_rgb", [240, 240, 240]))
        self.bg_color = tuple(config.get("bg_color_rgb", [0, 0, 0]))
        self.overlay_alpha = int(config.get("overlay_alpha", 140))

        self.image_path = config.get("image_path")
        self.text_position = str(config.get("text_position", "middle")).lower()

        # runtime
        self.manager = None
        self.w = 0
        self.h = 0

        self._api_calls = 0
        self._current_quote = "Thinking…"
        self._current_author = "Anonymous"

        self._next_refresh_at = 0.0

        # background image cache
        self._bg_path = None
        self._bg_surface = None
        self._bg_surface_size = (0, 0)

        # async fetch
        self._fetch_thread = None
        self._fetch_q = queue.Queue(maxsize=1)
        self._fetch_in_flight = False

        # cached layout
        self._cached_key = None
        self._cached_lines = None
        self._cached_box = None
        self._cached_y0 = 0

    # ---------------- lifecycle ----------------

    def enter(self, manager):
        self.manager = manager
        self.w, self.h = manager.screen.get_size()

        self._bg_surface = None
        self._bg_surface_size = (0, 0)
        self._load_background()

        self._current_quote = "Thinking…"
        self._current_author = "Anonymous"

        now = time.time()
        self._next_refresh_at = now  # fetch immediately
        self._invalidate_layout()

    def exit(self):
        self._bg_surface = None
        self._fetch_in_flight = False
        self._fetch_thread = None
        self._cached_lines = None
        self._cached_box = None
        self._cached_key = None
        self.manager = None

    def handle_event(self, event):
        pass

    def update(self, dt: float):
        # resolution change
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self.w, self.h = w2, h2
            self._load_background(force=True)
            self._invalidate_layout()

        # harvest async results
        try:
            quote, author = self._fetch_q.get_nowait()
            self._current_quote = quote
            self._current_author = author or "Anonymous"
            self._fetch_in_flight = False
            self._invalidate_layout()
        except queue.Empty:
            pass

        now = time.time()
        if now >= self._next_refresh_at:
            # schedule next tick regardless
            self._next_refresh_at = now + self.duration

            # kick off fetch if possible
            if not self._fetch_in_flight:
                self._start_fetch()

    def render(self, screen: pygame.Surface):
        # background
        if self._bg_surface:
            screen.blit(self._bg_surface, (0, 0))
        else:
            screen.fill(self.bg_color)

        # layout cache
        self._ensure_layout()

        if not self._cached_lines:
            return

        # backing box
        if self._cached_box:
            bx, by, bw, bh = self._cached_box
            overlay = pygame.Surface((bw, bh), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, max(0, min(255, self.overlay_alpha))))
            screen.blit(overlay, (bx, by))

        y = self._cached_y0
        for surf, pad in self._cached_lines:
            x = (self.w - surf.get_width()) // 2
            screen.blit(surf, (x, y))
            y += surf.get_height() + pad

    # ---------------- OpenAI / parsing ----------------

    def _start_fetch(self):
        self._fetch_in_flight = True
        t = threading.Thread(target=self._fetch_quote_worker, daemon=True)
        self._fetch_thread = t
        t.start()

    def _fetch_quote_worker(self):
        quote, author = self._fetch_quote()
        try:
            # if queue is full, drop the old value
            if self._fetch_q.full():
                try:
                    self._fetch_q.get_nowait()
                except Exception:
                    pass
            self._fetch_q.put_nowait((quote, author))
        except Exception:
            pass

    def _fetch_quote(self):
        if not self._client:
            return "No API key configured.", "Anonymous"

        if self._api_calls >= self.max_api_calls:
            return "Quote limit reached.", "Anonymous"

        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You generate short quotes and their attributed author. Return ONLY valid JSON.",
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Theme/tone: {self.theme}.\n"
                            "Create ONE quote (max 25 words) and an author name.\n"
                            "Respond as JSON like: {\"quote\": \"...\", \"author\": \"...\"}.\n"
                            "Rules:\n"
                            "- No emojis\n"
                            "- No surrounding quotation marks in the quote\n"
                            "- Author should be a short name (e.g., Maya Angelou)\n"
                            "- If unknown, use 'Anonymous'"
                        ),
                    },
                ],
                max_tokens=80,
                temperature=0.9,
            )
            self._api_calls += 1
            content = (resp.choices[0].message.content or "").strip()
            return self._parse_quote_and_author(content)
        except Exception as e:
            return f"API error: {e}", "Anonymous"

    def _parse_quote_and_author(self, content: str):
        # 1) strict JSON
        try:
            obj = json.loads(content)
            q = str(obj.get("quote", "")).strip()
            a = str(obj.get("author", "")).strip()
            if q:
                return q, (a or "Anonymous")
        except Exception:
            pass

        # 2) extract JSON blob
        m = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(0))
                q = str(obj.get("quote", "")).strip()
                a = str(obj.get("author", "")).strip()
                if q:
                    return q, (a or "Anonymous")
            except Exception:
                pass

        # 3) split attribution
        for sep in ["\n—", "\n-", " — ", " - "]:
            if sep in content:
                q, a = content.split(sep, 1)
                q = q.strip().strip('"')
                a = a.strip().lstrip("—-").strip()
                if q:
                    return q, (a or "Anonymous")

        cleaned = content.strip().strip('"')
        return (cleaned or "(empty quote)"), "Anonymous"

    # ---------------- rendering helpers ----------------

    def _load_background(self, force=False):
        if not self.image_path or not os.path.exists(self.image_path):
            self._bg_path = None
            self._bg_surface = None
            self._bg_surface_size = (0, 0)
            return

        if (not force) and self._bg_path == self.image_path and self._bg_surface is not None and self._bg_surface_size == (self.w, self.h):
            return

        self._bg_path = self.image_path
        # use controller cache and scale-cover
        img = self.manager.cache.get_image(self.image_path, convert_alpha=False)
        self._bg_surface = self._scale_cover(img, (self.w, self.h))
        self._bg_surface_size = (self.w, self.h)

    def _scale_cover(self, img, target_size):
        tw, th = target_size
        iw, ih = img.get_width(), img.get_height()
        if iw <= 0 or ih <= 0:
            return None
        scale = max(tw / iw, th / ih)
        nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
        scaled = pygame.transform.smoothscale(img, (nw, nh))
        out = pygame.Surface((tw, th))
        src = scaled.get_rect(center=(tw // 2, th // 2))
        out.blit(scaled, (0, 0), area=src)
        return out

    def _wrap_text(self, font, text, max_width):
        words = (text or "").split()
        if not words:
            return []
        lines, cur = [], ""
        for w in words:
            test = w if not cur else cur + " " + w
            if font.size(test)[0] <= max_width:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    def _invalidate_layout(self):
        self._cached_key = None
        self._cached_lines = None
        self._cached_box = None

    def _ensure_layout(self):
        key = (self.w, self.h, self._current_quote, self._current_author, self.font_name, self.font_size, self.text_position)
        if key == self._cached_key and self._cached_lines is not None:
            return

        w, h = self.w, self.h
        max_w = int(w * 0.82)
        margin = int(h * 0.08)

        # main font via manager cache
        main_font = self.manager.cache.get_font(self.font_name, self.font_size, bold=True) if self.font_name else self.manager.cache.get_font(None, self.font_size, bold=True)
        author_font_px = max(14, int(self.font_size * 0.65))
        author_font = self.manager.cache.get_font(self.font_name, author_font_px, bold=False) if self.font_name else self.manager.cache.get_font(None, author_font_px, bold=False)

        quote_lines = self._wrap_text(main_font, self._current_quote, max_w)
        author_line = f"— {self._current_author}" if self._current_author else ""

        line_surfs = []
        total_h = 0
        max_line_w = 0

        for ln in quote_lines:
            surf = main_font.render(ln, True, self.text_color)
            line_surfs.append((surf, 6))
            total_h += surf.get_height() + 6
            max_line_w = max(max_line_w, surf.get_width())

        if author_line:
            total_h += 10
            surf = author_font.render(author_line, True, self.text_color)
            line_surfs.append((surf, 0))
            total_h += surf.get_height()
            max_line_w = max(max_line_w, surf.get_width())

        if self.text_position == "top":
            y0 = margin
        elif self.text_position == "bottom":
            y0 = h - total_h - margin
        else:
            y0 = (h - total_h) // 2

        # backing box centered
        pad = 18
        box_w = min(w, max_line_w + pad * 2)
        box_h = min(h, total_h + pad * 2)
        box_x = max(0, (w - box_w) // 2)
        box_y = max(0, y0 - pad)

        self._cached_key = key
        self._cached_lines = line_surfs
        self._cached_box = (box_x, box_y, box_w, box_h)
        self._cached_y0 = y0

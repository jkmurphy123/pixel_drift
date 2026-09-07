# headlines_news_mode.py

import os
import time
import random
import re
import threading
import urllib.request
import xml.etree.ElementTree as ET

import pygame


class HeadlinesNewsMode:
    """
    Scene-style headlines/news-feed mode (RSS/Atom).

    Instance config:
      - feed_url (str)       : RSS/Atom feed URL (required)
      - image_folder (str)   : folder of background images (png/jpg/jpeg) (optional)
      - text_position (str)  : "top", "middle", or "bottom" (default "bottom")
      - duration (float)     : seconds per story (default 60)
      - show_time (bool)     : show centered clock at top (default False)

    Optional:
      - font_name (str)             : pygame font name/path or None for default
      - headline_font_scale (float) : relative to screen height (default 0.065)
      - body_font_scale (float)     : relative to screen height (default 0.035)
      - margin_scale (float)        : relative to screen width (default 0.08)
      - overlay_font_path (str)     : same as slideshow clock font path
      - font_size (int)             : same as slideshow centered clock size
      - overlay_font_size (int)     : kept for parity with slideshow config
      - overlay_margin (int)        : same as slideshow top margin
      - overlay_alpha (int 0-255)   : translucent backing box alpha (default 150)
      - refresh_every_stories (int) : refetch feed after N stories (default 20)
      - max_body_chars (int)        : cap body length (default 320)
      - max_body_lines (int)        : cap body lines rendered (default 8)

    "Network trouble" behavior:
      - If fetching fails and we have a previous story, keep showing it and add
        a small status line.
    """

    def __init__(self, config: dict):
        self.feed_url = (config.get("feed_url", "") or "").strip()
        self.image_folder = config.get("image_folder") or config.get("folder")
        self.text_position = (config.get("text_position") or "bottom").strip().lower()
        self.duration = float(config.get("duration", 60))
        self.show_time = bool(config.get("show_time", False))

        self.font_name = config.get("font_name", None)
        self.headline_font_scale = float(config.get("headline_font_scale", 0.065))
        self.body_font_scale = float(config.get("body_font_scale", 0.035))
        self.margin_scale = float(config.get("margin_scale", 0.08))
        self.overlay_font_path = config.get(
            "overlay_font_path",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        )
        self.font_size = int(config.get("font_size", 28))
        self.overlay_font_size = int(config.get("overlay_font_size", self.font_size))
        self.overlay_margin = int(config.get("overlay_margin", 12))
        self.overlay_alpha = int(config.get("overlay_alpha", 150))
        self.refresh_every_stories = int(config.get("refresh_every_stories", 20))
        self.max_body_chars = int(config.get("max_body_chars", 320))
        self.max_body_lines = int(config.get("max_body_lines", 8))

        self.bg_color = (0, 0, 0)
        self.fg_color = (255, 255, 255)

        # runtime / manager injected
        self.manager = None
        self.w = 0
        self.h = 0

        # story state
        self._stories = []
        self._story_index = 0
        self._stories_shown_since_refresh = 0

        self._current_headline = "Loading headlines…"
        self._current_body = ""
        self._current_source = ""

        # background
        self._bg_image_cache_path = None
        self._bg_surface = None
        self._bg_surface_size = (0, 0)

        # timers
        self._next_story_at = 0.0

        # network trouble
        self._network_trouble = False
        self._network_trouble_msg = ""

        # Background feed fetching. The HTTP fetch + XML parse run on a
        # one-shot daemon thread so a slow feed can't freeze the frame loop.
        # While a fetch is in flight the mode keeps showing existing stories.
        self._fetch_in_flight = False
        self._fetch_thread = None

        # cached fonts & layout
        self._headline_font_px = 0
        self._body_font_px = 0
        self._headline_font = None
        self._body_font = None

        # cached rendered lines (to avoid recomputing every frame)
        self._cached_layout_key = None
        self._cached_lines = None  # list of (kind, surface)
        self._cached_metrics = None  # (line_heights, max_line_w, box_rect, y0)

    # -------------------------
    # Scene lifecycle
    # -------------------------

    def enter(self, manager):
        if not self.feed_url:
            raise ValueError("feed_url is required for HeadlinesNewsMode")

        self.manager = manager
        self.w, self.h = manager.screen.get_size()

        self._recompute_fonts()

        self._load_stories()
        # pick initial bg and story
        self._pick_new_background()
        self._advance_story(force=True)

        self._next_story_at = time.time() + self.duration

    def exit(self):
        # release references
        self._headline_font = None
        self._body_font = None
        self._bg_surface = None
        self._stories = []
        self._cached_lines = None
        self._cached_metrics = None
        self._cached_layout_key = None
        self.manager = None

    def handle_event(self, event):
        # no special handling; controller handles quit
        pass

    def update(self, dt: float):
        # resolution changed?
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self.w, self.h = w2, h2
            self._recompute_fonts()
            # background needs rescale
            self._bg_surface = None
            self._bg_surface_size = (0, 0)
            self._pick_new_background(force_reload=True)
            self._invalidate_cached_layout()

        now = time.time()
        if now >= self._next_story_at:
            self._advance_story(force=False)
            self._next_story_at = now + self.duration

    def render(self, screen: pygame.Surface):
        # draw background
        if self._bg_surface:
            screen.blit(self._bg_surface, (0, 0))
        else:
            screen.fill(self.bg_color)

        if self.show_time:
            self._draw_centered_time(screen)

        # ensure story text layout is cached for current state
        self._ensure_cached_layout()

        if not self._cached_lines:
            return

        # backing box
        box_rect = self._cached_metrics[2]
        overlay = pygame.Surface((box_rect.width, box_rect.height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, max(0, min(255, self.overlay_alpha))))
        screen.blit(overlay, (box_rect.x, box_rect.y))

        # render lines centered
        y = self._cached_metrics[3]
        for kind, surf in self._cached_lines:
            x = int((self.w - surf.get_width()) / 2)
            screen.blit(surf, (x, y))
            y += surf.get_height() + (6 if kind == "headline" else 4)

    # -------------------------
    # Feed fetching / parsing
    # -------------------------

    def _fetch_feed_xml(self) -> bytes:
        req = urllib.request.Request(
            self.feed_url,
            headers={"User-Agent": "RotaryMode/1.0 (+HeadlinesNewsMode)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read()

    def _strip_html(self, s: str) -> str:
        if not s:
            return ""
        s = re.sub(r"<script\b[^>]*>.*?</script>", "", s, flags=re.I | re.S)
        s = re.sub(r"<style\b[^>]*>.*?</style>", "", s, flags=re.I | re.S)
        s = re.sub(r"<[^>]+>", "", s)
        s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"').replace("&apos;", "'")
        s = s.replace("&lt;", "<").replace("&gt;", ">")
        return re.sub(r"\s+", " ", s).strip()

    def _text_or_none(self, el):
        if el is None:
            return None
        txt = el.text or ""
        return txt.strip() if txt else None

    def _parse_rss(self, root: ET.Element):
        channel = root.find("channel")
        if channel is None:
            return []
        source = self._text_or_none(channel.find("title")) or ""

        items = []
        for item in channel.findall("item"):
            title = self._strip_html(self._text_or_none(item.find("title")) or "")
            desc = self._strip_html(self._text_or_none(item.find("description")) or "")
            content = None
            for child in list(item):
                if child.tag.endswith("encoded"):
                    content = self._strip_html((child.text or "").strip())
                    break
            body = content or desc
            if title:
                items.append({"headline": title, "body": body, "source": source})
        return items

    def _parse_atom(self, root: ET.Element):
        def find_first(parent, localname):
            for child in list(parent):
                if child.tag.endswith("}" + localname) or child.tag == localname:
                    return child
            return None

        source = ""
        feed_title = find_first(root, "title")
        if feed_title is not None:
            source = self._strip_html(feed_title.text or "")

        items = []
        for entry in [c for c in list(root) if c.tag.endswith("}entry") or c.tag == "entry"]:
            title_el = find_first(entry, "title")
            summary_el = find_first(entry, "summary")
            content_el = find_first(entry, "content")

            title = self._strip_html((title_el.text or "") if title_el is not None else "")
            body_raw = ""
            if content_el is not None and (content_el.text or "").strip():
                body_raw = content_el.text or ""
            elif summary_el is not None:
                body_raw = summary_el.text or ""

            body = self._strip_html(body_raw)
            if title:
                items.append({"headline": title, "body": body, "source": source})
        return items

    def _load_stories(self):
        """
        Kick off a background fetch. Returns immediately; existing stories
        keep displaying until the fetch completes. Safe to call from the
        frame loop — a second call while one is in flight is a no-op.
        """
        if self._fetch_in_flight:
            return
        self._fetch_in_flight = True
        self._fetch_thread = threading.Thread(
            target=self._fetch_stories_sync, daemon=True, name="headlines-fetch"
        )
        self._fetch_thread.start()

    def _fetch_stories_sync(self):
        """Runs on the fetch thread. Never call from the frame loop."""
        try:
            xml_bytes = self._fetch_feed_xml()
            root = ET.fromstring(xml_bytes)

            tag = root.tag.lower()
            if tag.endswith("rss") or tag == "rss":
                stories = self._parse_rss(root)
            elif tag.endswith("feed") or tag == "feed":
                stories = self._parse_atom(root)
            else:
                stories = self._parse_rss(root)

            # de-dup by headline
            seen = set()
            uniq = []
            for s in stories:
                key = (s.get("headline") or "").strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    uniq.append(s)

            self._stories = uniq
            self._story_index = 0
            self._stories_shown_since_refresh = 0

            self._network_trouble = False
            self._network_trouble_msg = ""

            if not self._stories:
                self._current_headline = "No stories found."
                self._current_body = "Feed returned no items."
                self._current_source = ""
        except Exception as e:
            self._network_trouble = True
            self._network_trouble_msg = f"{type(e).__name__}: {e}"

            if not self._stories:
                self._story_index = 0
                self._current_headline = "Network trouble."
                self._current_body = self._network_trouble_msg
                self._current_source = ""
        finally:
            self._fetch_in_flight = False

    # -------------------------
    # Story progression
    # -------------------------

    def _advance_story(self, force: bool):
        if not self._stories or self._story_index >= len(self._stories):
            self._load_stories()

        if self._stories:
            story = self._stories[self._story_index % len(self._stories)]
            self._story_index += 1
            self._stories_shown_since_refresh += 1

            self._current_headline = story.get("headline") or "Untitled"
            self._current_body = story.get("body") or ""
            self._current_source = story.get("source") or ""

            # swap background each story for variety
            self._pick_new_background(force_reload=True)

            if self.refresh_every_stories > 0 and self._stories_shown_since_refresh >= self.refresh_every_stories:
                self._load_stories()

            self._invalidate_cached_layout()
        else:
            # still show whatever message is set
            self._invalidate_cached_layout()

    # -------------------------
    # Background images
    # -------------------------

    def _pick_random_bg_path(self):
        if not self.image_folder or not os.path.isdir(self.image_folder):
            return None
        exts = (".png", ".jpg", ".jpeg", ".bmp")
        files = [f for f in os.listdir(self.image_folder) if f.lower().endswith(exts)]
        if not files:
            return None
        return os.path.join(self.image_folder, random.choice(files))

    def _pick_new_background(self, force_reload: bool = False):
        path = self._pick_random_bg_path()
        if not path:
            self._bg_image_cache_path = None
            self._bg_surface = None
            self._bg_surface_size = (0, 0)
            return

        if (not force_reload) and path == self._bg_image_cache_path and self._bg_surface is not None:
            return

        # load via manager cache, then scale/crop to cover screen
        self._bg_image_cache_path = path
        self._bg_surface = self._load_and_scale_cover(path, (self.w, self.h))
        self._bg_surface_size = (self.w, self.h)

    def _load_and_scale_cover(self, path: str, target_size):
        tw, th = target_size
        img = self.manager.cache.get_image(path, convert_alpha=False)
        iw, ih = img.get_width(), img.get_height()
        if iw <= 0 or ih <= 0:
            return None

        scale = max(tw / iw, th / ih)
        nw = max(1, int(iw * scale))
        nh = max(1, int(ih * scale))
        scaled = pygame.transform.smoothscale(img, (nw, nh))

        # crop center to exact target size
        out = pygame.Surface((tw, th))
        src_rect = scaled.get_rect(center=(tw // 2, th // 2))
        out.blit(scaled, (0, 0), area=src_rect)
        return out

    # -------------------------
    # Text layout & caching
    # -------------------------

    def _recompute_fonts(self):
        h = max(1, self.h)
        self._headline_font_px = max(18, int(h * self.headline_font_scale))
        self._body_font_px = max(14, int(h * self.body_font_scale))

        # Use manager cache if font_name is None (SysFont).
        # If font_name is a path, pygame.Font is needed; we keep it per-mode to avoid
        # mixing multiple file fonts into the global cache.
        if self.font_name:
            self._headline_font = pygame.font.Font(self.font_name, self._headline_font_px)
            self._body_font = pygame.font.Font(self.font_name, self._body_font_px)
        else:
            self._headline_font = self.manager.cache.get_font(None, self._headline_font_px, bold=True)
            self._body_font = self.manager.cache.get_font(None, self._body_font_px, bold=False)

        self._invalidate_cached_layout()

    def _invalidate_cached_layout(self):
        self._cached_layout_key = None
        self._cached_lines = None
        self._cached_metrics = None

    def _wrap_text(self, font, text, max_width):
        words = (text or "").split()
        if not words:
            return []
        lines = []
        cur = ""
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

    def _ensure_cached_layout(self):
        key = (
            self.w, self.h,
            self._current_headline, self._current_body, self._current_source,
            self._network_trouble, self._network_trouble_msg,
            self.text_position, self.max_body_chars, self.max_body_lines,
            self._headline_font_px, self._body_font_px,
        )
        if key == self._cached_layout_key and self._cached_lines is not None:
            return

        w, h = self.w, self.h
        margin_x = int(w * self.margin_scale)
        max_width = max(1, w - (margin_x * 2))

        headline_lines = self._wrap_text(self._headline_font, self._current_headline, max_width)

        body_text = (self._current_body or "").strip()
        if len(body_text) > self.max_body_chars:
            body_text = body_text[: self.max_body_chars].rstrip() + "…"
        body_lines = self._wrap_text(self._body_font, body_text, max_width)

        line_surfs = []
        line_heights = 0
        max_line_w = 0

        for ln in headline_lines:
            surf = self._headline_font.render(ln, True, self.fg_color)
            line_surfs.append(("headline", surf))
            line_heights += surf.get_height() + 6
            max_line_w = max(max_line_w, surf.get_width())

        if body_lines:
            line_heights += 10

        for ln in body_lines[: self.max_body_lines]:
            surf = self._body_font.render(ln, True, self.fg_color)
            line_surfs.append(("body", surf))
            line_heights += surf.get_height() + 4
            max_line_w = max(max_line_w, surf.get_width())

        if self._current_source:
            source_line = f"Source: {self._current_source}"
            surf = self._body_font.render(source_line, True, self.fg_color)
            line_surfs.append(("source", surf))
            line_heights += surf.get_height() + 2
            max_line_w = max(max_line_w, surf.get_width())

        if self._network_trouble and self._network_trouble_msg:
            status = f"Network trouble (showing last update): {self._network_trouble_msg}"
            status = status[:120].rstrip() + ("…" if len(status) > 120 else "")
            surf = self._body_font.render(status, True, self.fg_color)
            line_surfs.append(("status", surf))
            line_heights += surf.get_height() + 2
            max_line_w = max(max_line_w, surf.get_width())

        if self.text_position == "top":
            y0 = int(h * 0.08)
        elif self.text_position == "middle":
            y0 = int((h - line_heights) / 2)
        else:
            y0 = int(h * 0.70) - int(line_heights / 2)

        # centered backing box
        box_pad = 18
        box_w = min(w, max_line_w + box_pad * 2)
        box_h = min(h, line_heights + box_pad * 2)
        box_x = max(0, int((w - box_w) / 2))
        box_y = max(0, y0 - box_pad)
        box_rect = pygame.Rect(box_x, box_y, box_w, box_h)

        self._cached_layout_key = key
        self._cached_lines = line_surfs
        self._cached_metrics = (line_heights, max_line_w, box_rect, y0)

    # -------------------------
    # Clock overlay (slideshow parity)
    # -------------------------

    def _draw_centered_time(self, screen: pygame.Surface):
            # We use a larger font size for the centered clock if desired
            clock_font = self.manager.cache.get_font(
                self.overlay_font_path,
                int(self.font_size), # Slightly larger than corner text
                bold=True
            )

            time_str = self._format_time()

            # Render text with shadow
            surf = clock_font.render(time_str, True, (240, 240, 240))
            shadow = clock_font.render(time_str, True, (0, 0, 0))

            # Position: Centered horizontally, Margin distance from top
            x = screen.get_width() // 2
            y = self.overlay_margin + (surf.get_height() // 2)

            rect = surf.get_rect(center=(x, y))
            shadow_rect = rect.move(2, 2)

            screen.blit(shadow, shadow_rect)
            screen.blit(surf, rect)

    def _format_time(self) -> str:
        # Linux supports %-I; keep a fallback just in case.
        try:
            return time.strftime("%-I:%M %p")
        except Exception:
            s = time.strftime("%I:%M %p")
            return s[1:] if s.startswith("0") else s

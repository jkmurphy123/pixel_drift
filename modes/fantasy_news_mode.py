# fantasy_news_mode.py
#
# Displays generated fantasy/sci-fi news stories over background images.
# Each story is a JSON file with keys: headline, story (paragraph), image_prompt (optional), filename (optional)
# Images can be:
#   - same basename as the JSON in stories_folder (e.g., story_01.json + story_01.png/jpg)
#   - OR randomly chosen from image_folder as fallback
#
# Config:
#   required:
#     - stories_folder (str): folder containing *.json story files
#     - duration (float/int): seconds per story
#
#   optional:
#     - image_folder (str): folder of background images (fallback). If omitted, uses stories_folder.
#     - show_time (bool): show time centered at top (default True)
#     - show_seconds (bool): include seconds in time (default False)
#     - time_format (str): strftime format, default "%I:%M %p" (leading zero stripped)
#     - font_path (str): explicit TTF path (e.g. /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf)
#     - font_name (str): cache font name fallback (default "dejavusansmono")
#     - headline_font_scale (float): relative to screen width (default 0.060)
#     - body_font_scale (float): relative to screen width (default 0.030)
#     - time_font_scale (float): relative to screen width (default 0.040)
#     - margin_scale (float): screen margin (default 0.055)
#     - overlay_alpha (int): 0-255, panel alpha behind text (default 170)
#     - max_body_chars (int): trim story text to avoid wall-of-text (default 560)
#     - dim_bg (int): 0-200, darken background slightly for readability (default 40)
#
# Notes:
# - Cycles through all stories in stories_folder, looping forever.
# - If a story's matching image is missing, it falls back to a random image from image_folder.

import os
import time
import json
import random
from datetime import datetime
from typing import List, Dict, Optional, Tuple

import pygame


def _list_files(folder: str, exts: Tuple[str, ...]) -> List[str]:
    out: List[str] = []
    try:
        for name in os.listdir(folder):
            p = os.path.join(folder, name)
            if os.path.isfile(p) and name.lower().endswith(exts):
                out.append(p)
    except Exception:
        return []
    out.sort()
    return out


def _safe_read_json(path: str) -> Optional[Dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _basename_no_ext(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def _find_matching_image(stories_folder: str, json_path: str) -> Optional[str]:
    base = _basename_no_ext(json_path)
    candidates = [
        os.path.join(stories_folder, base + ".png"),
        os.path.join(stories_folder, base + ".jpg"),
        os.path.join(stories_folder, base + ".jpeg"),
        os.path.join(stories_folder, base + ".webp"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _wrap_text(font: pygame.font.Font, text: str, max_width: int) -> List[str]:
    """
    Simple word wrap returning a list of lines not exceeding max_width.
    """
    words = text.replace("\n", " ").split()
    if not words:
        return []

    lines: List[str] = []
    cur = words[0]
    for w in words[1:]:
        test = cur + " " + w
        if font.size(test)[0] <= max_width:
            cur = test
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def _format_time_no_leading_zero(now: datetime, fmt: str) -> str:
    s = now.strftime(fmt)
    if s.startswith("0"):
        s = s[1:]
    return s


class FantasyNewsMode:
    def __init__(self, config: dict):
        # required
        self.stories_folder = str(config.get("stories_folder", "")).strip()
        self.duration = float(config.get("duration", 30))

        # optional
        self.image_folder = str(config.get("image_folder", "")).strip() or self.stories_folder

        self.show_time = bool(config.get("show_time", True))
        self.show_seconds = bool(config.get("show_seconds", False))
        self.time_format = str(config.get("time_format", "%I:%M %p"))

        self.font_path = config.get("font_path")  # explicit TTF path if provided
        self.font_name = str(config.get("font_name", "dejavusansmono"))

        self.headline_font_scale = float(config.get("headline_font_scale", 0.060))
        self.body_font_scale = float(config.get("body_font_scale", 0.030))
        self.time_font_scale = float(config.get("time_font_scale", 0.040))

        self.margin_scale = float(config.get("margin_scale", 0.055))
        self.overlay_alpha = int(config.get("overlay_alpha", 170))
        self.max_body_chars = int(config.get("max_body_chars", 560))
        self.dim_bg = int(config.get("dim_bg", 40))

        self.ordered = bool(config.get("ordered", False))

        # runtime
        self.manager = None
        self.w = 0
        self.h = 0

        # state
        self._story_json_paths: List[str] = []
        self._fallback_images: List[str] = []
        self._idx = 0
        self._story_started_at = 0.0

        self._cur_story: Optional[Dict] = None
        self._cur_bg_path: Optional[str] = None
        self._cur_bg_scaled: Optional[pygame.Surface] = None
        self._cur_bg_scaled_size: Tuple[int, int] = (0, 0)

        # colors
        self._fg = (245, 245, 245)
        self._dim = (170, 170, 170)
        self._shadow = (0, 0, 0)

    # ---------- lifecycle ----------

    def enter(self, manager):
        self.manager = manager
        self._reload_assets()
        self._recompute_layout()
        self._load_story(0, force=True)

    def exit(self):
        self.manager = None
        self._cur_bg_scaled = None
        self._cur_story = None

    def handle_event(self, event):
        pass

    def update(self, dt: float):
        # handle resolution changes
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            self._cur_bg_scaled = None  # rescale background

        if not self._story_json_paths:
            return

        now = time.time()
        if (now - self._story_started_at) >= max(1.0, self.duration):
            self._load_story(self._idx + 1)

    def render(self, screen: pygame.Surface):
        screen.fill((0, 0, 0))

        if not self._story_json_paths:
            self._render_center_message(screen, "No story files found.", "Check stories_folder.")
            return

        if not self._cur_story:
            self._render_center_message(screen, "Loading story…", "")
            return

        # background (cover)
        self._draw_background(screen)

        # subtle dim overlay to improve readability
        if self.dim_bg > 0:
            dim = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
            dim.fill((0, 0, 0, max(0, min(200, self.dim_bg))))
            screen.blit(dim, (0, 0))

        # sizes
        headline_size = max(22, int(self.w * self.headline_font_scale))
        body_size = max(16, int(self.w * self.body_font_scale))
        time_size = max(18, int(self.w * self.time_font_scale))

        # font loader: prefer explicit TTF, else cache
        def load_font(size: int, bold: bool = False) -> pygame.font.Font:
            if self.font_path and isinstance(self.font_path, str) and os.path.isfile(self.font_path):
                f = pygame.font.Font(self.font_path, size)
                f.set_bold(bold)
                return f
            return self.manager.cache.get_font(self.font_name, size, bold=bold)

        headline_font = load_font(headline_size, bold=True)
        body_font = load_font(body_size, bold=False)
        time_font = load_font(time_size, bold=True)

        # margins/panel
        margin = int(self.w * self.margin_scale)
        panel_w = self.w - 2 * margin
        pad_x = int(panel_w * 0.04)
        pad_y = int(self.h * 0.02)

        # top offset
        top_y = margin

        # optional time at top center
        if self.show_time:
            now = datetime.now()
            if self.show_seconds:
                time_str = now.strftime("%H:%M:%S")
            else:
                time_str = _format_time_no_leading_zero(now, self.time_format)

            time_surf = time_font.render(time_str, True, self._fg)
            time_rect = time_surf.get_rect(midtop=(self.w // 2, top_y))

            sh = time_font.render(time_str, True, self._shadow)
            sh_rect = sh.get_rect(midtop=(self.w // 2 + 2, top_y + 2))
            screen.blit(sh, sh_rect)
            screen.blit(time_surf, time_rect)

            top_y = time_rect.bottom + int(self.h * 0.02)

        # story text
        headline = str(self._cur_story.get("headline", "Untitled")).strip()
        body = str(self._cur_story.get("story", "")).strip()

        if self.max_body_chars > 0 and len(body) > self.max_body_chars:
            body = body[: self.max_body_chars].rstrip() + "…"

        # wrap widths
        max_text_w = panel_w - int(panel_w * 0.08)

        headline_lines = _wrap_text(headline_font, headline, max_text_w)
        body_lines = _wrap_text(body_font, body, max_text_w)

        headline_line_h = headline_font.get_linesize() + 2
        body_line_h = body_font.get_linesize() + 2

        head_h = max(1, len(headline_lines)) * headline_line_h
        body_h = len(body_lines) * body_line_h

        gap = int(self.h * 0.012)

        panel_h = pad_y + head_h + gap + body_h + pad_y
        panel_x = margin
        panel_y = max(top_y, self.h - margin - panel_h)

        # draw semi-transparent panel
        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        panel.fill((0, 0, 0, max(0, min(255, self.overlay_alpha))))
        screen.blit(panel, (panel_x, panel_y))

        center_x = panel_x + (panel_w // 2)

        # draw headline (wrapped + centered)
        y = panel_y + pad_y
        for line in headline_lines if headline_lines else [headline]:
            surf = headline_font.render(line, True, self._fg)
            rect = surf.get_rect(midtop=(center_x, y))

            sh = headline_font.render(line, True, self._shadow)
            sh_rect = sh.get_rect(midtop=(center_x + 2, y + 2))

            screen.blit(sh, sh_rect)
            screen.blit(surf, rect)
            y += headline_line_h

        # body starts after headline + gap
        y = panel_y + pad_y + head_h + gap
        for line in body_lines:
            surf = body_font.render(line, True, self._fg)
            rect = surf.get_rect(midtop=(center_x, y))
            screen.blit(surf, rect)
            y += body_line_h

        # small footer index
        footer = f"{self._idx + 1}/{len(self._story_json_paths)}"
        foot_font = load_font(max(12, int(body_size * 0.72)), bold=False)
        foot_s = foot_font.render(footer, True, self._dim)
        screen.blit(
            foot_s,
            (panel_x + panel_w - foot_s.get_width() - pad_x,
             panel_y + panel_h - foot_s.get_height() - pad_y)
        )

    # ---------- helpers ----------

    def _recompute_layout(self):
        self.w, self.h = self.manager.screen.get_size()

    def _reload_assets(self):
        self._story_json_paths = _list_files(self.stories_folder, (".json",))

        if self.ordered:
            # Sort by filename for chronological playback
            self._story_json_paths.sort(key=lambda p: os.path.basename(p).lower())
        else:
            # Preserve previous behavior (filesystem order)
            random.shuffle(self._story_json_paths)

        self._fallback_images = _list_files(
            self.image_folder,
            (".png", ".jpg", ".jpeg", ".webp")
        )

        self._idx = 0
        self._story_started_at = time.time()

    def _pick_bg_for_story(self, json_path: str) -> Optional[str]:
        match = _find_matching_image(self.stories_folder, json_path)
        if match:
            return match
        if self._fallback_images:
            return random.choice(self._fallback_images)
        return None

    def _load_story(self, idx: int, force: bool = False):
        if not self._story_json_paths:
            return

        self._idx = idx % len(self._story_json_paths)
        story_path = self._story_json_paths[self._idx]

        story = _safe_read_json(story_path)
        if story is None:
            if force:
                self._cur_story = {"headline": "Invalid story JSON", "story": os.path.basename(story_path)}
                self._story_started_at = time.time()
            else:
                self._load_story(self._idx + 1)
            return

        self._cur_story = story
        self._story_started_at = time.time()

        bg_path = self._pick_bg_for_story(story_path)
        if bg_path != self._cur_bg_path:
            self._cur_bg_path = bg_path
            self._cur_bg_scaled = None

    def _draw_background(self, screen: pygame.Surface):
        if not self._cur_bg_path or not os.path.isfile(self._cur_bg_path):
            return

        if self._cur_bg_scaled and self._cur_bg_scaled_size == (self.w, self.h):
            screen.blit(self._cur_bg_scaled, (0, 0))
            return

        try:
            img = pygame.image.load(self._cur_bg_path).convert()
        except Exception:
            return

        iw, ih = img.get_width(), img.get_height()
        if iw <= 0 or ih <= 0:
            return

        scale = max(self.w / iw, self.h / ih)
        new_w = max(1, int(iw * scale))
        new_h = max(1, int(ih * scale))
        scaled = pygame.transform.smoothscale(img, (new_w, new_h))

        x = (new_w - self.w) // 2
        y = (new_h - self.h) // 2
        cropped = scaled.subsurface((x, y, self.w, self.h)).copy()

        self._cur_bg_scaled = cropped
        self._cur_bg_scaled_size = (self.w, self.h)
        screen.blit(self._cur_bg_scaled, (0, 0))

    def _render_center_message(self, screen: pygame.Surface, line1: str, line2: str):
        w, h = self.w, self.h

        def load_font(size: int, bold: bool = False) -> pygame.font.Font:
            if self.font_path and isinstance(self.font_path, str) and os.path.isfile(self.font_path):
                f = pygame.font.Font(self.font_path, size)
                f.set_bold(bold)
                return f
            return self.manager.cache.get_font(self.font_name, size, bold=bold)

        font1 = load_font(max(22, int(w * 0.050)), bold=True)
        font2 = load_font(max(16, int(w * 0.030)), bold=False)

        s1 = font1.render(line1, True, self._fg)
        r1 = s1.get_rect(center=(w // 2, h // 2 - 20))
        screen.blit(s1, r1)

        if line2:
            s2 = font2.render(line2, True, self._dim)
            r2 = s2.get_rect(center=(w // 2, h // 2 + 20))
            screen.blit(s2, r2)

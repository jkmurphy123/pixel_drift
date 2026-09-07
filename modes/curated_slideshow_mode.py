import json
import os
import random
import time
from typing import List, Dict

import pygame


class CuratedSlideshowMode:
    """
    Slideshow with per-image metadata (title + description) loaded from a JSON file.

    Config:
      - data_file (required): JSON file with {"items":[{file,title,description}, ...]}
      - image_folder (optional): base folder for image files (defaults to data_file folder)
      - duration (optional): seconds per slide (default 12)
      - scale_mode (optional): "cover" (default) or "contain"
      - shuffle (optional): true/false

      Text styling:
      - title_font_scale (optional): fraction of screen height (default 0.05)
      - desc_font_scale (optional): fraction of screen height (default 0.026)
      - text_rgb (optional): [r,g,b] (default [240,240,240])
      - panel_rgb (optional): [r,g,b] (default [0,0,0])
      - panel_alpha (optional): 0-255 (default 160)
      - margin_scale (optional): fraction of short side (default 0.03)
      - line_spacing (optional): multiplier for description line spacing (default 1.15)
      - show_title (optional): true/false (default true)
      - show_description (optional): true/false (default true)
    """

    def __init__(self, config: dict):
        self.data_file = config.get("data_file")
        self.image_folder = config.get("image_folder")
        self.duration = float(config.get("duration", 12.0))
        self.scale_mode = str(config.get("scale_mode", "cover")).lower()
        self.shuffle = bool(config.get("shuffle", False))

        self.title_font_scale = float(config.get("title_font_scale", 0.05))
        self.desc_font_scale = float(config.get("desc_font_scale", 0.026))
        self.text_rgb = tuple(config.get("text_rgb", [240, 240, 240]))
        self.panel_rgb = tuple(config.get("panel_rgb", [0, 0, 0]))
        self.panel_alpha = int(config.get("panel_alpha", 160))
        self.margin_scale = float(config.get("margin_scale", 0.03))
        self.line_spacing = float(config.get("line_spacing", 1.15))
        self.show_title = bool(config.get("show_title", True))
        self.show_description = bool(config.get("show_description", True))

        self.manager = None
        self.screen_size = (0, 0)

        self.items: List[Dict[str, str]] = []
        self._index = 0
        self._next_swap_at = 0.0

        self.current_surface = None
        self.current_path = None
        self.current_item = None

    def enter(self, manager):
        self.manager = manager
        self.screen_size = manager.screen.get_size()
        self.items = self._load_items()
        if self.shuffle:
            random.shuffle(self.items)
        self._index = 0
        self._next_swap_at = time.time()
        self.current_surface = None
        self.current_path = None
        self.current_item = None

    def exit(self):
        self.current_surface = None
        self.current_path = None
        self.current_item = None
        self.items = []
        self.manager = None

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_SPACE, pygame.K_RIGHT):
                self._advance()

    def update(self, dt: float):
        if not self.items:
            return
        if self.manager and self.manager.screen.get_size() != self.screen_size:
            self.screen_size = self.manager.screen.get_size()
            if self.current_path:
                self.current_surface = self._load_and_scale(self.current_path, self.screen_size)

        now = time.time()
        if self.current_surface is None or now >= self._next_swap_at:
            self._advance()

    def render(self, screen: pygame.Surface):
        screen.fill((0, 0, 0))

        if not self.items:
            return

        if self.current_surface:
            rect = self.current_surface.get_rect(center=screen.get_rect().center)
            screen.blit(self.current_surface, rect)

        if not self.current_item:
            return

        if not (self.show_title or self.show_description):
            return

        self._draw_text_panel(screen, self.current_item)

    # ---------- internals ----------

    def _advance(self):
        if not self.items:
            return
        self.current_item = self.items[self._index]
        self._index = (self._index + 1) % len(self.items)

        path = self._resolve_image_path(self.current_item.get("file"))
        self.current_path = path

        if self.current_surface is not None:
            old = self.current_surface
            self.current_surface = None
            del old

        self.current_surface = self._load_and_scale(path, self.screen_size)
        self._next_swap_at = time.time() + self.duration

    def _load_items(self) -> List[Dict[str, str]]:
        if not self.data_file:
            print("[CuratedSlideshow] No data_file configured.")
            return []

        if not os.path.isabs(self.data_file):
            data_path = os.path.join(os.path.dirname(__file__), "..", self.data_file)
            data_path = os.path.normpath(data_path)
        else:
            data_path = self.data_file

        try:
            with open(data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[CuratedSlideshow] Failed to load data file '{data_path}': {e}")
            return []

        items = data.get("items", [])
        out = []
        for item in items:
            file_name = str(item.get("file", "")).strip()
            title = str(item.get("title", "")).strip()
            desc = str(item.get("description", "")).strip()
            if not file_name:
                continue
            out.append({"file": file_name, "title": title, "description": desc})
        print(f"[CuratedSlideshow] Loaded {len(out)} item(s) from {data_path}")
        return out

    def _resolve_image_path(self, file_name: str) -> str:
        if not file_name:
            return ""
        if os.path.isabs(file_name):
            return file_name

        base = None
        if self.image_folder:
            base = self.image_folder
        elif self.data_file:
            base = os.path.dirname(self.data_file) if os.path.isabs(self.data_file) else os.path.dirname(
                os.path.normpath(os.path.join(os.path.dirname(__file__), "..", self.data_file))
            )
        else:
            base = os.getcwd()

        if not os.path.isabs(base):
            base = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", base))
        return os.path.join(base, file_name)

    def _load_and_scale(self, path, target_size):
        if not path:
            return None
        tw, th = target_size
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
                return out

            return scaled

        except Exception as e:
            print(f"[CuratedSlideshow] Failed to load image '{path}': {e}")
            return None

    def _draw_text_panel(self, screen: pygame.Surface, item: Dict[str, str]):
        w, h = screen.get_size()
        short_side = min(w, h)
        margin = int(short_side * self.margin_scale)

        title_size = max(16, int(h * self.title_font_scale))
        desc_size = max(12, int(h * self.desc_font_scale))

        title_font = self.manager.cache.get_font("dejavusansmono", title_size, bold=True)
        desc_font = self.manager.cache.get_font("dejavusansmono", desc_size, bold=False)

        title = item.get("title", "")
        desc = item.get("description", "")

        lines = []
        if self.show_title and title:
            lines.append(("title", title))
        if self.show_description and desc:
            wrapped = self._wrap_text(desc, desc_font, w - margin * 2)
            for line in wrapped:
                lines.append(("desc", line))

        if not lines:
            return

        line_surfs = []
        line_heights = []
        for kind, text in lines:
            font = title_font if kind == "title" else desc_font
            surf = font.render(text, True, self.text_rgb)
            line_surfs.append((kind, surf))
            line_heights.append(surf.get_height())

        total_height = 0
        for idx, (kind, surf) in enumerate(line_surfs):
            if idx > 0:
                total_height += int(line_heights[idx - 1] * (self.line_spacing - 1.0))
            total_height += surf.get_height()

        panel_height = total_height + margin * 2
        panel = pygame.Surface((w, panel_height), pygame.SRCALPHA)
        panel.fill((*self.panel_rgb, max(0, min(255, self.panel_alpha))))

        y = margin
        for idx, (kind, surf) in enumerate(line_surfs):
            x = (panel.get_width() - surf.get_width()) // 2
            panel.blit(surf, (x, y))
            if idx < len(line_surfs) - 1:
                y += int(surf.get_height() * self.line_spacing)
            else:
                y += surf.get_height()

        screen.blit(panel, (0, h - panel_height))

    def _wrap_text(self, text: str, font: pygame.font.Font, max_width: int) -> List[str]:
        words = text.split()
        if not words:
            return []
        lines = []
        current = words[0]
        for word in words[1:]:
            test = f"{current} {word}"
            if font.size(test)[0] <= max_width:
                current = test
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

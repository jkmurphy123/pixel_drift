import json
import math
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pygame


@dataclass
class ModelSpec:
    id: str
    name: str
    input: float | None
    output: float | None
    use_case: str


@dataclass
class ProviderSpec:
    name: str
    slug: str
    accent_rgb: tuple[int, int, int] | None
    models: list[ModelSpec] = field(default_factory=list)


@dataclass
class RecommendationCategory:
    name: str
    model: str
    provider: str
    input: float | None
    output: float | None
    why: str


@dataclass
class RecommendationsSpec:
    title: str
    accent_rgb: tuple[int, int, int] | None
    categories: list[RecommendationCategory] = field(default_factory=list)


@dataclass
class MetaInfo:
    currency: str
    unit: str
    last_updated: str
    source_note: str
    refresh_interval_days: int | None


class LLMPricingWallMode:
    """
    LLM Pricing Wall
    - Displays a grid of panels: a recommendations panel (best value picks) plus
      one provider panel per AI API provider, showing model names, token prices,
      and short use-case hints.
    - Reads prices from a local JSON file so the display works offline.
    - A companion script (scripts/refresh_llm_pricing.py) can update provider
      prices in the file; recommendations are preserved and edited by hand.

    Config:
      - data_file (str)
      - title (str)
      - subtitle (str)
      - accent_rgb ([r,g,b])
      - columns_portrait (int)
      - columns_landscape (int)
      - panel_spacing_scale (float)
      - scanline_alpha (int)
      - noise_alpha (int)
      - vignette_strength (float)
      - seed (int)
    """

    def __init__(self, config: dict):
        self.data_file = str(config.get("data_file", "data/llm_pricing.json"))
        self.title = str(config.get("title", "LLM API PRICING DASHBOARD"))
        self.subtitle = str(
            config.get("subtitle", "per-million-token input / output prices")
        )
        self.accent_rgb = tuple(config.get("accent_rgb", [100, 220, 180]))
        self.columns_portrait = max(1, int(config.get("columns_portrait", 1)))
        self.columns_landscape = max(1, int(config.get("columns_landscape", 2)))
        self.panel_spacing_scale = float(config.get("panel_spacing_scale", 0.025))
        self.scanline_alpha = int(config.get("scanline_alpha", 0))
        self.noise_alpha = int(config.get("noise_alpha", 0))
        self.vignette_strength = float(config.get("vignette_strength", 0.15))
        self.seed = config.get("seed")

        self.manager = None
        self.w = 0
        self.h = 0
        self._is_portrait = False
        self._t = 0.0
        self._rng = random.Random()

        self._bg = (6, 8, 12)
        self._fg = (235, 235, 235)
        self._dim = (150, 150, 160)
        self._warn = (255, 200, 100)
        self._cheap = (120, 255, 165)
        self._mid = (255, 220, 120)
        self._expensive = (255, 115, 115)

        self._pad = 0
        self._header_h = 0
        self._footer_h = 0
        self._grid_rect = pygame.Rect(0, 0, 0, 0)

        self._font_header = None
        self._font_subtitle = None
        self._font_provider = None
        self._font_model = None
        self._font_price = None
        self._font_small = None
        self._font_mono = None

        self._vignette = None
        self._scanlines = None

        self._meta: MetaInfo | None = None
        self._providers: list[ProviderSpec] = []
        self._recommendations: RecommendationsSpec | None = None
        self._scroll_offsets: dict[str, float] = {}
        self._scroll_speeds: dict[str, float] = {}

        self._load_data()

    def _load_data(self):
        path = self._resolve_path(self.data_file)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            print(f"[LLMPricingWall] data file not found: {path}")
            data = {"providers": []}
        except json.JSONDecodeError as exc:
            print(f"[LLMPricingWall] JSON error in {path}: {exc}")
            data = {"providers": []}

        meta = data.get("meta", {})
        self._meta = MetaInfo(
            currency=str(meta.get("currency", "USD")),
            unit=str(meta.get("unit", "per 1M tokens")),
            last_updated=str(meta.get("last_updated", "")),
            source_note=str(meta.get("source_note", "")),
            refresh_interval_days=meta.get("refresh_interval_days"),
        )

        self._providers = []
        for row in data.get("providers", []):
            provider = self._parse_provider(row)
            if provider.models:
                self._providers.append(provider)

        rec_data = data.get("recommendations")
        self._recommendations = (
            self._parse_recommendations(rec_data) if isinstance(rec_data, dict) else None
        )

    def _parse_recommendations(self, data: dict) -> RecommendationsSpec:
        title = str(data.get("title", "RECOMMENDED VALUE MODELS")).strip()
        accent = data.get("accent_rgb")
        accent_rgb = (
            tuple(accent)
            if isinstance(accent, (list, tuple)) and len(accent) == 3
            else None
        )
        categories = []
        for row in data.get("categories", []):
            categories.append(
                RecommendationCategory(
                    name=str(row.get("name", "")).strip() or "Category",
                    model=str(row.get("model", "")).strip() or "Unnamed",
                    provider=str(row.get("provider", "")).strip() or "Unknown",
                    input=self._parse_price(row.get("input")),
                    output=self._parse_price(row.get("output")),
                    why=str(row.get("why", "")).strip(),
                )
            )
        return RecommendationsSpec(title=title, accent_rgb=accent_rgb, categories=categories)

    def _resolve_path(self, path: str) -> str:
        if os.path.isabs(path):
            return path
        # Relative to project root (where pixel_drift.py lives).
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(root, path)

    def _parse_provider(self, row: dict) -> ProviderSpec:
        name = str(row.get("name", "")).strip() or "Unknown"
        slug = str(row.get("slug", "")).strip() or name.lower().replace(" ", "-")
        accent = row.get("accent_rgb")
        accent_rgb = tuple(accent) if isinstance(accent, (list, tuple)) and len(accent) == 3 else None

        models = []
        for m in row.get("models", []):
            models.append(
                ModelSpec(
                    id=str(m.get("id", "")).strip(),
                    name=str(m.get("name", "")).strip() or "Unnamed",
                    input=self._parse_price(m.get("input")),
                    output=self._parse_price(m.get("output")),
                    use_case=str(m.get("use_case", "")).strip(),
                )
            )

        return ProviderSpec(name=name, slug=slug, accent_rgb=accent_rgb, models=models)

    @staticmethod
    def _parse_price(value) -> float | None:
        if value is None:
            return None
        try:
            price = float(value)
            return price if price >= 0 else None
        except (TypeError, ValueError):
            return None

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._recompute_layout()
        self._build_overlays()

    def exit(self):
        self.manager = None
        self._vignette = None
        self._scanlines = None

    def handle_event(self, event):
        pass

    def update(self, dt: float):
        self._t += dt
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            self._build_overlays()

    def render(self, screen: pygame.Surface):
        screen.fill(self._bg)
        self._draw_header(screen)
        self._draw_grid(screen)
        self._draw_footer(screen)

        if self._scanlines is not None:
            screen.blit(self._scanlines, (0, 0))
        if self._vignette is not None:
            screen.blit(self._vignette, (0, 0))
        if self.noise_alpha > 0:
            self._draw_noise(screen)

    def _reseed(self):
        if self.seed is None:
            self.seed = random.randrange(1, 2**31 - 1)
        self._rng.seed(int(self.seed))

    def _recompute_layout(self):
        self.w, self.h = self.manager.screen.get_size()
        self._is_portrait = self.h > self.w

        self._pad = int(min(self.w, self.h) * 0.045)
        self._header_h = max(90, int(self.h * 0.14))
        self._footer_h = max(44, int(self.h * 0.07))
        self._grid_rect = pygame.Rect(
            self._pad,
            self._header_h,
            self.w - 2 * self._pad,
            self.h - self._header_h - self._footer_h,
        )

        base = min(self.w, self.h)
        self._font_header = self.manager.cache.get_font(
            "dejavusansmono", max(18, int(base * 0.050)), bold=True
        )
        self._font_subtitle = self.manager.cache.get_font(
            "dejavusansmono", max(12, int(base * 0.022)), bold=False
        )
        self._font_provider = self.manager.cache.get_font(
            "dejavusansmono", max(15, int(base * 0.032)), bold=True
        )
        self._font_model = self.manager.cache.get_font(
            "dejavusansmono", max(12, int(base * 0.024)), bold=True
        )
        self._font_price = self.manager.cache.get_font(
            "dejavusansmono", max(12, int(base * 0.024)), bold=False
        )
        self._font_small = self.manager.cache.get_font(
            "dejavusansmono", max(10, int(base * 0.018)), bold=False
        )
        self._font_mono = self.manager.cache.get_font(
            "dejavusansmono", max(10, int(base * 0.020)), bold=True
        )

    def _build_overlays(self):
        self._vignette = self._build_vignette(self.w, self.h, self.vignette_strength)
        self._scanlines = self._build_scanlines(self.w, self.h, self.scanline_alpha)

    def _build_vignette(self, w: int, h: int, strength: float):
        strength = max(0.0, min(1.0, float(strength)))
        if strength <= 0.0:
            return None
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        layers = 68
        max_a = int(190 * strength)
        for i in range(layers):
            a = int(max_a * (i / layers) ** 1.8)
            pygame.draw.rect(
                surf, (0, 0, 0, a), pygame.Rect(i, i, w - 2 * i, h - 2 * i), 1
            )
        return surf

    def _build_scanlines(self, w: int, h: int, alpha: int):
        alpha = max(0, min(255, int(alpha)))
        if alpha <= 0:
            return None
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        spacing = 4
        for y in range(0, h, spacing):
            pygame.draw.line(surf, (0, 0, 0, alpha), (0, y), (w, y), 1)
        return surf

    def _draw_header(self, screen: pygame.Surface):
        band = pygame.Surface((self.w, self._header_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, 0))

        title = self._font_header.render(self.title, True, self.accent_rgb)
        screen.blit(title, (self._pad, int(self._header_h * 0.18)))

        subtitle = self._font_subtitle.render(self.subtitle, True, self._dim)
        screen.blit(
            subtitle,
            (self._pad, int(self._header_h * 0.18) + title.get_height() + 6),
        )

        right_parts = []
        if self._meta:
            if self._meta.currency and self._meta.unit:
                right_parts.append(f"{self._meta.currency} • {self._meta.unit}")
            if self._meta.last_updated:
                right_parts.append(f"updated {self._meta.last_updated[:10]}")
        right_text = "   |   ".join(right_parts)
        if right_text:
            right = self._font_small.render(right_text, True, self._dim)
            screen.blit(
                right,
                (self.w - self._pad - right.get_width(), int(self._header_h * 0.18)),
            )

        pygame.draw.line(
            screen,
            self._dim,
            (self._pad, self._header_h - 2),
            (self.w - self._pad, self._header_h - 2),
            2,
        )

    def _draw_footer(self, screen: pygame.Surface):
        y0 = self.h - self._footer_h
        band = pygame.Surface((self.w, self._footer_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, y0))

        hint = "offline data file • edit data/llm_pricing.json or run scripts/refresh_llm_pricing.py"
        if self._meta and self._meta.source_note:
            hint += " • " + self._meta.source_note[:80]
        surf = self._font_small.render(hint, True, self._dim)
        screen.blit(surf, (self._pad, y0 + (self._footer_h - surf.get_height()) // 2))

    def _draw_grid(self, screen: pygame.Surface):
        panels: list[ProviderSpec | RecommendationsSpec] = []
        if self._recommendations and self._recommendations.categories:
            panels.append(self._recommendations)
        panels.extend(self._providers)

        if not panels:
            msg = self._font_model.render("No pricing data found.", True, self._warn)
            screen.blit(msg, (self._grid_rect.left + 20, self._grid_rect.top + 20))
            return

        cols = self.columns_portrait if self._is_portrait else self.columns_landscape
        cols = max(1, int(cols))
        rows = max(1, math.ceil(len(panels) / cols))
        gap = max(8, int(min(self.w, self.h) * self.panel_spacing_scale))
        cell_w = (self._grid_rect.width - (cols - 1) * gap) // cols
        cell_h = (self._grid_rect.height - (rows - 1) * gap) // rows

        idx = 0
        for row in range(rows):
            for col in range(cols):
                if idx >= len(panels):
                    return
                x = self._grid_rect.left + col * (cell_w + gap)
                y = self._grid_rect.top + row * (cell_h + gap)
                panel = panels[idx]
                rect = pygame.Rect(x, y, cell_w, cell_h)
                if isinstance(panel, RecommendationsSpec):
                    self._draw_recommendation_panel(screen, rect, panel)
                else:
                    self._draw_provider_panel(screen, rect, panel)
                idx += 1

    def _draw_provider_panel(
        self, screen: pygame.Surface, rect: pygame.Rect, provider: ProviderSpec
    ):
        accent = provider.accent_rgb or self.accent_rgb

        # Panel background.
        panel = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 210))
        screen.blit(panel, rect.topleft)

        # Border with gentle pulse.
        pulse = 0.75 + 0.25 * math.sin(self._t * 1.8 + rect.x * 0.01 + rect.y * 0.01)
        border_color = tuple(min(255, int(c * pulse)) for c in accent)
        pygame.draw.rect(screen, border_color, rect, 2)

        # Provider name.
        name_surf = self._font_provider.render(provider.name, True, accent)
        name_x = rect.left + 18
        name_y = rect.top + 14
        screen.blit(name_surf, (name_x, name_y))

        # Model list area (clipped).
        list_top = name_y + name_surf.get_height() + 12
        list_rect = pygame.Rect(
            rect.left + 2, list_top, rect.width - 4, rect.bottom - list_top - 4
        )
        screen.set_clip(list_rect)

        content_height = self._model_list_content_height(provider, list_rect.width - 28)
        scroll = self._scroll_for_provider(provider, list_rect, content_height)

        y = list_rect.top + 10 - scroll
        inner_x = rect.left + 14
        inner_w = rect.width - 28
        line_gap = self._font_small.get_linesize() + 3

        for model in provider.models:
            if y > list_rect.bottom:
                break

            model_h = self._draw_model_row(
                screen,
                inner_x,
                y,
                inner_w,
                model,
                accent,
            )
            y += model_h + 10

        screen.set_clip(None)

        # Bottom fade to obscure scrolled-off content.
        fade_h = min(34, list_rect.height // 5)
        if fade_h > 4:
            fade = pygame.Surface((list_rect.width, fade_h), pygame.SRCALPHA)
            for i in range(fade_h):
                alpha = int(210 * (i / fade_h))
                pygame.draw.line(
                    fade, (self._bg[0], self._bg[1], self._bg[2], alpha), (0, i), (list_rect.width, i)
                )
            screen.blit(fade, (list_rect.left, list_rect.bottom - fade_h))

    def _draw_recommendation_panel(
        self, screen: pygame.Surface, rect: pygame.Rect, recs: RecommendationsSpec
    ):
        accent = recs.accent_rgb or (255, 200, 100)

        # Panel background.
        panel = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 210))
        screen.blit(panel, rect.topleft)

        # Border with gentle pulse.
        pulse = 0.75 + 0.25 * math.sin(self._t * 1.8 + rect.x * 0.01 + rect.y * 0.01)
        border_color = tuple(min(255, int(c * pulse)) for c in accent)
        pygame.draw.rect(screen, border_color, rect, 2)

        # Title.
        title_surf = self._font_provider.render(recs.title, True, accent)
        name_x = rect.left + 18
        name_y = rect.top + 14
        screen.blit(title_surf, (name_x, name_y))

        # Category list area (clipped).
        list_top = name_y + title_surf.get_height() + 12
        list_rect = pygame.Rect(
            rect.left + 2, list_top, rect.width - 4, rect.bottom - list_top - 4
        )
        screen.set_clip(list_rect)

        content_height = self._recommendation_content_height(recs, list_rect.width - 28)
        scroll = self._scroll_for_recommendations(recs, list_rect, content_height)

        y = int(list_rect.top + 10 - scroll)
        inner_x = rect.left + 14
        inner_w = rect.width - 28

        for cat in recs.categories:
            if y > list_rect.bottom:
                break
            cat_h = self._draw_recommendation_row(
                screen, inner_x, y, inner_w, cat, accent
            )
            y += cat_h + 14

        screen.set_clip(None)

        # Bottom fade to obscure scrolled-off content.
        fade_h = min(34, list_rect.height // 5)
        if fade_h > 4:
            fade = pygame.Surface((list_rect.width, fade_h), pygame.SRCALPHA)
            for i in range(fade_h):
                alpha = int(210 * (i / fade_h))
                pygame.draw.line(
                    fade,
                    (self._bg[0], self._bg[1], self._bg[2], alpha),
                    (0, i),
                    (list_rect.width, i),
                )
            screen.blit(fade, (list_rect.left, list_rect.bottom - fade_h))

    def _recommendation_content_height(
        self, recs: RecommendationsSpec, width: int
    ) -> int:
        total = 0
        for cat in recs.categories:
            total += self._recommendation_row_height(cat, width)
            total += 14
        return max(0, total - 14)

    def _recommendation_row_height(
        self, cat: RecommendationCategory, width: int
    ) -> int:
        name_h = self._font_model.get_height()
        why_h = self._wrap_text_height(cat.why, self._font_small, width, line_spacing=1.25)
        return name_h + name_h + 4 + why_h

    def _draw_recommendation_row(
        self,
        screen: pygame.Surface,
        x: int,
        y: int,
        width: int,
        cat: RecommendationCategory,
        accent: tuple[int, int, int],
    ) -> int:
        clip = screen.get_clip()
        row_h = self._recommendation_row_height(cat, width)
        if clip and (y + row_h < clip.top or y > clip.bottom):
            return row_h

        # Category name.
        cat_surf = self._font_model.render(cat.name, True, accent)
        screen.blit(cat_surf, (x, y))

        # Model + provider.
        mp_text = f"{cat.model} — {cat.provider}"
        mp_surf = self._font_model.render(mp_text, True, self._fg)
        mp_y = y + cat_surf.get_height() + 2
        screen.blit(mp_surf, (x, mp_y))

        # Prices (right, aligned with category name).
        in_text = self._format_price(cat.input)
        out_text = self._format_price(cat.output)
        price_color = self._price_color(cat.input, cat.output)

        in_surf = self._font_price.render(f"in {in_text}", True, price_color)
        out_surf = self._font_price.render(f"out {out_text}", True, self._dim)

        out_x = x + width - out_surf.get_width()
        in_x = out_x - in_surf.get_width() - 12

        screen.blit(in_surf, (max(x + min(mp_surf.get_width(), int(width * 0.55)) + 10, in_x), y))
        screen.blit(out_surf, (out_x, y))

        # Why text.
        why_y = mp_y + mp_surf.get_height() + 2
        self._draw_wrapped_text(
            screen,
            cat.why,
            self._font_small,
            x,
            why_y,
            width,
            self._dim,
            line_spacing=1.25,
        )

        return row_h

    def _scroll_for_recommendations(
        self, recs: RecommendationsSpec, list_rect: pygame.Rect, content_height: int
    ) -> float:
        key = "__recommendations__"
        if key not in self._scroll_offsets:
            self._scroll_offsets[key] = 0.0
            self._scroll_speeds[key] = 12 + self._rng.random() * 6

        if content_height <= list_rect.height:
            self._scroll_offsets[key] = 0.0
            return 0.0

        max_scroll = content_height - list_rect.height
        self._scroll_offsets[key] += self._scroll_speeds[key] * (1.0 / 60.0)
        if self._scroll_offsets[key] > max_scroll + 24:
            self._scroll_offsets[key] = 0.0

        return min(max_scroll, self._scroll_offsets[key])

    def _model_list_content_height(self, provider: ProviderSpec, width: int) -> int:
        total = 0
        for model in provider.models:
            total += self._model_row_height(model, width)
            total += 10
        return max(0, total - 10)

    def _model_row_height(self, model: ModelSpec, width: int) -> int:
        price_h = self._font_price.get_height()
        use_case_h = self._wrap_text_height(
            model.use_case, self._font_small, width, line_spacing=1.25
        )
        return max(price_h + 2, price_h + use_case_h + 2)

    def _draw_model_row(
        self,
        screen: pygame.Surface,
        x: int,
        y: int,
        width: int,
        model: ModelSpec,
        accent: tuple[int, int, int],
    ) -> int:
        # Skip rows fully above the clip region; still compute height.
        clip = screen.get_clip()
        row_h = self._model_row_height(model, width)
        if clip and (y + row_h < clip.top or y > clip.bottom):
            return row_h

        # Model name (left).
        name_surf = self._font_model.render(model.name, True, self._fg)
        name_w = min(name_surf.get_width(), int(width * 0.55))
        screen.blit(name_surf, (x, y), area=pygame.Rect(0, 0, name_w, name_surf.get_height()))

        # Prices (right).
        in_text = self._format_price(model.input)
        out_text = self._format_price(model.output)
        price_color = self._price_color(model.input, model.output)

        in_surf = self._font_price.render(f"in {in_text}", True, price_color)
        out_surf = self._font_price.render(f"out {out_text}", True, self._dim)

        out_x = x + width - out_surf.get_width()
        in_x = out_x - in_surf.get_width() - 12

        screen.blit(in_surf, (max(x + name_w + 10, in_x), y))
        screen.blit(out_surf, (out_x, y))

        # Use case (small, below name).
        use_y = y + name_surf.get_height() + 2
        self._draw_wrapped_text(
            screen,
            model.use_case,
            self._font_small,
            x,
            use_y,
            width,
            self._dim,
            line_spacing=1.25,
        )

        return row_h

    def _format_price(self, price: float | None) -> str:
        if price is None:
            return "—"
        if price == 0.0:
            return "free"
        if price < 0.01:
            return f"${price:.4f}"
        if price < 1.0:
            return f"${price:.2f}"
        return f"${price:.2f}"

    def _price_color(self, input_price: float | None, output_price: float | None):
        price = input_price if input_price is not None else output_price
        if price is None:
            return self._dim
        if price <= 0.5:
            return self._cheap
        if price <= 3.0:
            return self._mid
        return self._expensive

    def _scroll_for_provider(
        self, provider: ProviderSpec, list_rect: pygame.Rect, content_height: int
    ) -> float:
        key = provider.slug
        if key not in self._scroll_offsets:
            self._scroll_offsets[key] = 0.0
            self._scroll_speeds[key] = 12 + self._rng.random() * 6

        if content_height <= list_rect.height:
            self._scroll_offsets[key] = 0.0
            return 0.0

        max_scroll = content_height - list_rect.height
        self._scroll_offsets[key] += self._scroll_speeds[key] * (1.0 / 60.0)
        if self._scroll_offsets[key] > max_scroll + 24:
            self._scroll_offsets[key] = 0.0

        return min(max_scroll, self._scroll_offsets[key])

    def _draw_wrapped_text(
        self,
        screen: pygame.Surface,
        text: str,
        font: pygame.font.Font,
        x: int,
        y: int,
        max_width: int,
        color: tuple,
        line_spacing: float = 1.2,
    ) -> int:
        if not text:
            return 0
        words = text.split(" ")
        lines = []
        current = ""
        for word in words:
            test = f"{current} {word}".strip()
            if font.size(test)[0] <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)

        line_h = int(font.get_height() * line_spacing)
        for i, line in enumerate(lines):
            surf = font.render(line, True, color)
            screen.blit(surf, (x, y + i * line_h))
        return len(lines) * line_h

    def _wrap_text_height(
        self,
        text: str,
        font: pygame.font.Font,
        max_width: int,
        line_spacing: float = 1.2,
    ) -> int:
        if not text:
            return 0
        words = text.split(" ")
        lines = []
        current = ""
        for word in words:
            test = f"{current} {word}".strip()
            if font.size(test)[0] <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return int(len(lines) * font.get_height() * line_spacing)

    def _draw_noise(self, screen: pygame.Surface):
        count = max(120, (self.w * self.h) // 10000)
        surf = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        for _ in range(count):
            x = self._rng.randrange(0, self.w)
            y = self._rng.randrange(0, self.h)
            a = self._rng.randrange(0, self.noise_alpha + 1)
            surf.set_at((x, y), (255, 255, 255, a))
        screen.blit(surf, (0, 0))

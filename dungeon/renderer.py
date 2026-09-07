# dungeon/renderer.py
#
# Draws the graph-paper dungeon map, drafting symbols, room numbers, party marker,
# expedition route, and the header/panel chrome. Everything is code-generated;
# no bitmap assets.

from __future__ import annotations

from typing import Callable

import pygame

from . import symbols
from .model import CHEST, DOOR, Dungeon, Expedition, FLOOR, Room, STAIRS_DOWN, TRAP, VOID, WALKABLE


_PALETTES = {
    "blue_green": {
        "background": (224, 235, 228),
        "grid_minor": (164, 195, 202),
        "grid_major": (115, 163, 176),
        "ink": (37, 53, 58),
        "pencil": (92, 103, 102),
        "route": (117, 62, 53),
        "party": (156, 42, 35),
        "floor": (208, 225, 218),
        "panel_fill": (28, 32, 36),
        "panel_text": (220, 225, 230),
    },
    "sepia": {
        "background": (232, 224, 208),
        "grid_minor": (188, 172, 148),
        "grid_major": (156, 138, 114),
        "ink": (58, 46, 36),
        "pencil": (108, 94, 78),
        "route": (130, 66, 46),
        "party": (152, 48, 32),
        "floor": (216, 206, 188),
        "panel_fill": (38, 32, 26),
        "panel_text": (230, 224, 214),
    },
}


class Renderer:
    def __init__(
        self,
        expedition: Expedition,
        config: dict,
        font_getter: Callable[[str, int], pygame.font.Font],
    ):
        self.expedition = expedition
        self.dungeon = expedition.dungeon
        self.config = config
        self._font_getter = font_getter
        self.layout = str(config.get("layout", "auto")).lower()
        self.show_room_numbers = bool(config.get("show_room_numbers", True))
        self.show_route = bool(config.get("show_expedition_route", True))
        self.major_interval = int(config.get("major_grid_interval", 5))
        self.paper_style = str(config.get("paper_style", "blue_green")).lower()
        self.font_name = str(config.get("font_name", "dejavusansmono")).strip()

        self.palette = _PALETTES.get(self.paper_style, _PALETTES["blue_green"])
        self._screen_w = 0
        self._screen_h = 0
        self._paper: pygame.Surface | None = None
        self._map_rect = pygame.Rect(0, 0, 0, 0)
        self._panel_rect = pygame.Rect(0, 0, 0, 0)
        self._header_rect = pygame.Rect(0, 0, 0, 0)
        self._tile_size = 1
        self._map_offset = (0, 0)

    def resize(self, width: int, height: int) -> None:
        if width == self._screen_w and height == self._screen_h:
            return
        self._screen_w = width
        self._screen_h = height
        self._paper = None
        self._compute_layout()

    def _compute_layout(self) -> None:
        w, h = self._screen_w, self._screen_h
        header_h = max(24, int(h * 0.10))
        portrait = self.layout == "portrait" or (
            self.layout == "auto" and h > w
        )
        if portrait:
            panel_h = max(40, int(h * 0.25))
            self._header_rect = pygame.Rect(0, 0, w, header_h)
            self._map_rect = pygame.Rect(0, header_h, w, h - header_h - panel_h)
            self._panel_rect = pygame.Rect(0, h - panel_h, w, panel_h)
        else:
            panel_w = max(120, int(w * 0.30))
            self._header_rect = pygame.Rect(0, 0, w, header_h)
            self._map_rect = pygame.Rect(0, header_h, w - panel_w, h - header_h)
            self._panel_rect = pygame.Rect(w - panel_w, header_h, panel_w, h - header_h)

        dw, dh = self.dungeon.width, self.dungeon.height
        ts_w = self._map_rect.width // dw
        ts_h = self._map_rect.height // dh
        self._tile_size = max(1, min(ts_w, ts_h))
        map_pixel_w = dw * self._tile_size
        map_pixel_h = dh * self._tile_size
        off_x = self._map_rect.x + (self._map_rect.width - map_pixel_w) // 2
        off_y = self._map_rect.y + (self._map_rect.height - map_pixel_h) // 2
        self._map_offset = (off_x, off_y)

    def _ensure_paper(self) -> pygame.Surface:
        if self._paper is not None:
            return self._paper
        paper = pygame.Surface((self._map_rect.width, self._map_rect.height))
        paper.fill(self.palette["background"])
        # Sparse speckles for a paper-like texture.
        seed_val = self.dungeon.seed or 0
        for i in range((self._map_rect.width * self._map_rect.height) // 400):
            x = ((i * 9301 + 49297 + seed_val) % self._map_rect.width)
            y = ((i * 49297 + 9301 + seed_val) % self._map_rect.height)
            paper.set_at((x, y), self.palette["grid_minor"])
        self._paper = paper
        return paper

    def render(self, screen: pygame.Surface) -> None:
        w, h = screen.get_size()
        self.resize(w, h)

        screen.fill(self.palette["panel_fill"])
        self._draw_header(screen)
        self._draw_map(screen)
        self._draw_panel(screen)

    def _tile_screen_rect(self, tx: int, ty: int) -> pygame.Rect:
        off_x, off_y = self._map_offset
        ts = self._tile_size
        return pygame.Rect(off_x + tx * ts, off_y + ty * ts, ts, ts)

    def _draw_header(self, surface: pygame.Surface) -> None:
        if self._header_rect.height < 10:
            return
        font = self._font_getter(self.font_name, max(12, self._header_rect.height // 2))
        title = "DUNGEON EXPEDITION"
        seed_text = f"seed {self.dungeon.seed}" if self.dungeon.seed is not None else "random"
        line = f"{title}  •  Floor {self.expedition.floor}  •  {seed_text}"
        text = font.render(line, True, self.palette["panel_text"])
        y = self._header_rect.centery - text.get_height() // 2
        surface.blit(text, (self._header_rect.x + 12, y))

    def _draw_map(self, surface: pygame.Surface) -> None:
        paper = self._ensure_paper()
        surface.blit(paper, self._map_rect.topleft)

        self._draw_grid(surface)
        self._draw_floor_and_walls(surface)
        self._draw_features(surface)
        if self.show_room_numbers:
            self._draw_room_numbers(surface)
        if self.show_route:
            self._draw_route(surface)
        self._draw_party_marker(surface)

    def _draw_grid(self, surface: pygame.Surface) -> None:
        off_x, off_y = self._map_offset
        dw, dh = self.dungeon.width, self.dungeon.height
        ts = self._tile_size
        minor = self.palette["grid_minor"]
        major = self.palette["grid_major"]

        # Vertical lines
        for tx in range(dw + 1):
            color = major if tx % self.major_interval == 0 else minor
            x = off_x + tx * ts
            pygame.draw.line(
                surface, color, (x, off_y), (x, off_y + dh * ts), 1 if color == minor else 2
            )
        # Horizontal lines
        for ty in range(dh + 1):
            color = major if ty % self.major_interval == 0 else minor
            y = off_y + ty * ts
            pygame.draw.line(
                surface, color, (off_x, y), (off_x + dw * ts, y), 1 if color == minor else 2
            )

    def _draw_floor_and_walls(self, surface: pygame.Surface) -> None:
        dungeon = self.dungeon
        knowledge = self.expedition.knowledge
        ts = self._tile_size
        if ts < 2:
            return
        ink = self.palette["ink"]
        floor_color = self.palette["floor"]

        for ty in range(dungeon.height):
            for tx in range(dungeon.width):
                tile = knowledge[ty][tx]
                if tile == VOID:
                    continue
                if tile not in WALKABLE:
                    # Draw solid wall cells inside rooms so rooms read as enclosed.
                    rect = self._tile_screen_rect(tx, ty)
                    pygame.draw.rect(surface, self.palette["pencil"], rect)
                    continue
                rect = self._tile_screen_rect(tx, ty)
                # Floor tint
                pygame.draw.rect(surface, floor_color, rect)
                # Wall segments along edges with non-walkable or undiscovered neighbors
                for dx, dy, edge in (
                    (0, -1, "top"),
                    (0, 1, "bottom"),
                    (-1, 0, "left"),
                    (1, 0, "right"),
                ):
                    nx, ny = tx + dx, ty + dy
                    if not dungeon.in_bounds(nx, ny):
                        self._draw_wall_edge(surface, rect, edge, ink)
                    elif knowledge[ny][nx] == VOID or dungeon.tiles[ny][nx] not in WALKABLE:
                        self._draw_wall_edge(surface, rect, edge, ink)

    def _draw_wall_edge(
        self, surface: pygame.Surface, rect: pygame.Rect, edge: str, color: tuple[int, int, int]
    ) -> None:
        if edge == "top":
            pygame.draw.line(surface, color, rect.topleft, rect.topright, max(1, rect.height // 8))
        elif edge == "bottom":
            pygame.draw.line(surface, color, rect.bottomleft, rect.bottomright, max(1, rect.height // 8))
        elif edge == "left":
            pygame.draw.line(surface, color, rect.topleft, rect.bottomleft, max(1, rect.width // 8))
        elif edge == "right":
            pygame.draw.line(surface, color, rect.topright, rect.bottomright, max(1, rect.width // 8))

    def _draw_features(self, surface: pygame.Surface) -> None:
        dungeon = self.dungeon
        knowledge = self.expedition.knowledge
        ink = self.palette["ink"]
        dw, dh = dungeon.width, dungeon.height
        ts = self._tile_size
        off_x, off_y = self._map_offset
        feature_rect = pygame.Rect(off_x, off_y, dw * ts, dh * ts)
        for ty in range(dungeon.height):
            for tx in range(dungeon.width):
                if knowledge[ty][tx] == VOID:
                    continue
                tile = dungeon.tiles[ty][tx]
                if tile == DOOR:
                    symbols.draw_closed_door(
                        surface, tx, ty, self._tile_size, feature_rect, ink
                    )
                elif tile == STAIRS_DOWN:
                    symbols.draw_stairs(
                        surface, tx, ty, self._tile_size, feature_rect, ink
                    )
                elif tile == TRAP:
                    symbols.draw_trap(
                        surface, tx, ty, self._tile_size, feature_rect, ink
                    )
                elif tile == CHEST:
                    symbols.draw_chest(
                        surface, tx, ty, self._tile_size, feature_rect, ink
                    )

    def _draw_room_numbers(self, surface: pygame.Surface) -> None:
        if self._tile_size < 10:
            return
        font = self._font_getter(self.font_name, max(8, self._tile_size // 2))
        ink = self.palette["ink"]
        for room in self.dungeon.rooms:
            if not room.discovered:
                continue
            cx, cy = room.center
            rect = self._tile_screen_rect(cx, cy)
            text = font.render(str(room.room_id), True, ink)
            x = rect.centerx - text.get_width() // 2
            y = rect.centery - text.get_height() // 2
            surface.blit(text, (x, y))

    def _draw_route(self, surface: pygame.Surface) -> None:
        if self._tile_size < 2:
            return
        route = self.expedition.route
        if len(route) < 2:
            return
        color = self.palette["route"]
        points = [
            self._tile_screen_rect(x, y).center
            for x, y in route
            if self.expedition.is_discovered(x, y)
        ]
        if len(points) > 1:
            pygame.draw.lines(surface, color, False, points, max(1, self._tile_size // 4))

    def _draw_party_marker(self, surface: pygame.Surface) -> None:
        ts = self._tile_size
        if ts < 4:
            return
        x, y = self.expedition.party.x, self.expedition.party.y
        rect = self._tile_screen_rect(x, y)
        color = self.palette["party"]
        # Compass diamond marker.
        mid_top = (rect.centerx, rect.top + ts // 4)
        mid_right = (rect.right - ts // 4, rect.centery)
        mid_bottom = (rect.centerx, rect.bottom - ts // 4)
        mid_left = (rect.left + ts // 4, rect.centery)
        pygame.draw.polygon(surface, color, [mid_top, mid_right, mid_bottom, mid_left])
        pygame.draw.circle(surface, self.palette["ink"], rect.center, max(1, ts // 6))

    def _draw_panel(self, surface: pygame.Surface) -> None:
        if self._panel_rect.height < 20 or self._panel_rect.width < 40:
            return
        pygame.draw.rect(surface, self.palette["panel_fill"], self._panel_rect)
        pygame.draw.line(
            surface,
            self.palette["grid_major"],
            self._panel_rect.topleft,
            self._panel_rect.topright,
            2,
        )

        # Keep the side panel text readable but not overwhelming on large displays.
        font_size = min(
            max(12, self._panel_rect.height // 10),
            max(12, self._panel_rect.width // 15),
        )
        font = self._font_getter(self.font_name, font_size)
        phase_label = self.expedition.phase.name.replace("_", " ")
        title = font.render(f"Phase: {phase_label}", True, self.palette["panel_text"])
        surface.blit(title, (self._panel_rect.x + 12, self._panel_rect.y + 10))

        stats_font = self._font_getter(self.font_name, max(10, font_size * 3 // 4))
        party = self.expedition.party
        total_health = sum(m.health for m in party.members)
        max_health = sum(m.max_health for m in party.members)
        stats = [
            f"party: {party.x},{party.y}  goal: {party.current_goal}",
            f"health: {total_health}/{max_health}  supplies: {party.supplies}  torches: {party.torches}",
            f"morale: {party.morale}  gold: {party.gold}  explored: {len(self.expedition.route)} tiles",
        ]
        y = self._panel_rect.y + 14 + title.get_height()
        for line in stats:
            surf = stats_font.render(line, True, self.palette["panel_text"])
            surface.blit(surf, (self._panel_rect.x + 12, y))
            y += surf.get_height() + 4

        # Show the most recent journal line.
        if self.expedition.journal:
            last = self.expedition.journal[-1]
            wrap_w = max(40, self._panel_rect.width - 24)
            wrapped = self._wrap_text(last, stats_font, wrap_w)
            for line in wrapped[:4]:
                surf = stats_font.render(line, True, self.palette["panel_text"])
                if y + surf.get_height() > self._panel_rect.bottom - 6:
                    break
                surface.blit(surf, (self._panel_rect.x + 12, y))
                y += surf.get_height() + 2

    @staticmethod
    def _wrap_text(text: str, font: pygame.font.Font, max_width: int) -> list[str]:
        words = text.split()
        lines: list[str] = []
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
        return lines or [""]

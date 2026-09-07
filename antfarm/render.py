from __future__ import annotations

import pygame

from .constants import ColonyPhase, QueenState, TileType


class AntFarmRenderer:
    def __init__(self, config):
        self.config = config

    def render(self, screen: pygame.Surface, world, manager=None):
        width, height = screen.get_size()
        tile_w = width / max(1, world.cols)
        tile_h = height / max(1, world.rows)

        screen.fill(self.config.sky_rgb)

        for row_idx, row in enumerate(world.tiles):
            y = int(row_idx * tile_h)
            h = max(1, int((row_idx + 1) * tile_h) - y)
            for col_idx, tile in enumerate(row):
                if tile == TileType.AIR:
                    continue
                x = int(col_idx * tile_w)
                w = max(1, int((col_idx + 1) * tile_w) - x)
                color = self._tile_color(tile, row_idx, world.rows)
                pygame.draw.rect(screen, color, (x, y, w, h))

        self._draw_entrance(screen, world, tile_w, tile_h)
        self._draw_ants(screen, world, tile_w, tile_h)
        self._draw_queen(screen, world, tile_w, tile_h)
        self._draw_labels(screen, world, manager, width, height)

        if self.config.debug_overlay:
            self._draw_debug_grid(screen, world, tile_w, tile_h)

    def _tile_color(self, tile, row_idx: int, rows: int):
        if tile == TileType.TUNNEL:
            return (26, 18, 12)
        if tile == TileType.CHAMBER:
            return (40, 28, 18)
        if tile == TileType.SURFACE:
            return self.config.surface_rgb
        if tile == TileType.SOIL:
            depth = row_idx / max(1, rows - 1)
            return tuple(
                int(self.config.soil_rgb[i] + (self.config.deep_soil_rgb[i] - self.config.soil_rgb[i]) * depth)
                for i in range(3)
            )
        return self.config.soil_rgb

    def _draw_entrance(self, screen, world, tile_w: float, tile_h: float):
        center_x = int((world.entrance_col + 0.5) * tile_w)
        surface_y = int(world.surface_row * tile_h)
        radius = max(4, int(min(tile_w, tile_h) * 0.8))
        pygame.draw.ellipse(
            screen,
            (52, 34, 20),
            (center_x - radius, surface_y - radius // 2, radius * 2, max(4, radius)),
        )

    def _draw_ants(self, screen, world, tile_w: float, tile_h: float):
        ant_w = max(4, int(tile_w * 0.7))
        ant_h = max(3, int(tile_h * 0.35))
        for ant in world.ants:
            px = int((ant.x + 0.5) * tile_w)
            py = int((ant.y + 0.5) * tile_h)
            body = pygame.Rect(0, 0, ant_w, ant_h)
            body.center = (px, py)
            pygame.draw.ellipse(screen, self.config.ant_rgb, body)

            head_radius = max(2, ant_h // 2)
            head_x = body.right - head_radius if ant.vx >= 0 else body.left + head_radius
            pygame.draw.circle(screen, self.config.ant_rgb, (head_x, py), head_radius)

            leg_span = max(2, ant_h)
            pygame.draw.line(screen, self.config.ant_rgb, (body.left + 1, py - 1), (body.left - leg_span, py - leg_span), 1)
            pygame.draw.line(screen, self.config.ant_rgb, (body.left + 1, py + 1), (body.left - leg_span, py + leg_span), 1)
            pygame.draw.line(screen, self.config.ant_rgb, (body.right - 1, py - 1), (body.right + leg_span, py - leg_span), 1)
            pygame.draw.line(screen, self.config.ant_rgb, (body.right - 1, py + 1), (body.right + leg_span, py + leg_span), 1)

    def _draw_queen(self, screen, world, tile_w: float, tile_h: float):
        px = int(world.queen.x * tile_w)
        py = int(world.queen.y * tile_h)
        body = pygame.Rect(0, 0, max(10, int(tile_w * 1.4)), max(7, int(tile_h * 0.8)))
        body.center = (px, py)
        pygame.draw.ellipse(screen, (82, 36, 24), body)
        pygame.draw.circle(screen, (70, 24, 18), (body.right - max(3, body.height // 4), py), max(3, body.height // 3))

    def _draw_labels(self, screen, world, manager, width: int, height: int):
        if manager is None:
            return
        title_font = manager.cache.get_font("dejavusansmono", max(16, int(height * 0.026)), bold=True)
        small_font = manager.cache.get_font("dejavusansmono", max(12, int(height * 0.017)), bold=False)

        title = title_font.render(self.config.title, True, (56, 34, 18))
        screen.blit(title, (16, 14))

        target = world.get_active_dig_target()
        phase_names = {
            ColonyPhase.FOUNDING: "Founding",
            ColonyPhase.QUEEN_CHAMBER: "Queen chamber",
            ColonyPhase.EXPANSION: "Expansion",
        }
        phase_label = phase_names.get(world.colony_phase, "Founding")
        if target is None:
            if world.queen.state == QueenState.RELOCATE_TO_CHAMBER:
                phase = "Queen relocating"
            elif world.queen.state == QueenState.SETTLED:
                phase = f"{phase_label}  Queen settled  Jobs {world.expansion_jobs_created}"
            else:
                phase = f"{phase_label}  Idle"
            status = f"Workers {len(world.ants)}  {phase}"
        else:
            if world.queen.state == QueenState.RELOCATE_TO_CHAMBER:
                phase = "Queen relocating"
            elif world.queen.state == QueenState.SETTLED:
                phase = f"{phase_label}"
            else:
                phase = "Digging"
            status = f"Workers {len(world.ants)}  {phase}  Target {target[0]},{target[1]}  Carved {world.dig_steps_completed}"
        stats = small_font.render(status, True, (72, 48, 28))
        screen.blit(stats, (16, 18 + title.get_height()))

    def _draw_debug_grid(self, screen, world, tile_w: float, tile_h: float):
        overlay = pygame.Color(255, 255, 255, 55)
        for col in range(world.cols + 1):
            x = int(col * tile_w)
            pygame.draw.line(screen, overlay, (x, 0), (x, screen.get_height()), 1)
        for row in range(world.rows + 1):
            y = int(row * tile_h)
            pygame.draw.line(screen, overlay, (0, y), (screen.get_width(), y), 1)

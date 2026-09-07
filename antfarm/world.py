from __future__ import annotations

import random

from .constants import ColonyPhase, QueenState, TileType
from .entities import QueenAnt, WorkerAnt


class World:
    def __init__(self, config):
        self.config = config
        self.rng = random.Random(config.seed)
        self.cols = 0
        self.rows = 0
        self.surface_row = 0
        self.entrance_col = 0
        self.entrance_width = 3
        self.tiles = []
        self.ants: list[WorkerAnt] = []
        self.queen = QueenAnt(0.0, 0.0)
        self.dig_plan: list[tuple[int, int]] = []
        self.current_dig_index = 0
        self.current_dig_progress = 0.0
        self.dig_steps_completed = 0
        self._tunnel_points: list[tuple[int, int]] = []
        self.main_route: list[tuple[int, int]] = []
        self.travel_route: list[tuple[int, int]] = []
        self.chamber_tiles: set[tuple[int, int]] = set()
        self.queen_chamber_center = (0.0, 0.0)
        self.expansion_chamber_center = (0.0, 0.0)
        self.colony_phase = ColonyPhase.FOUNDING
        self.planner_elapsed = 0.0
        self.expansion_jobs_created = 0
        self.expansion_frontier = (0, 0)
        self.expansion_direction = 1

    def rebuild(self, screen_width: int, screen_height: int):
        portrait = screen_height >= screen_width
        if self.config.orientation == "portrait":
            portrait = True
        elif self.config.orientation == "landscape":
            portrait = False

        self.cols = 48 if portrait else 80
        self.rows = 80 if portrait else 48
        self.surface_row = max(3, min(self.rows - 4, int(self.rows * self.config.surface_height_ratio)))
        self.entrance_col = self.cols // 2

        self.tiles = []
        for row in range(self.rows):
            tile_row = []
            for _col in range(self.cols):
                if row < self.surface_row:
                    tile_row.append(TileType.AIR)
                elif row == self.surface_row:
                    tile_row.append(TileType.SURFACE)
                else:
                    tile_row.append(TileType.SOIL)
            self.tiles.append(tile_row)

        self.dig_plan = self._build_dig_plan()
        self.current_dig_index = 0
        self.current_dig_progress = 0.0
        self.dig_steps_completed = 0
        self._tunnel_points = []
        self.queen = QueenAnt(self.entrance_col + 0.5, max(0.8, self.surface_row - 1.3))
        self.colony_phase = ColonyPhase.FOUNDING
        self.planner_elapsed = 0.0
        self.expansion_jobs_created = 0
        self._spawn_ants()

    def _spawn_ants(self):
        self.ants = []
        min_y = max(1.0, self.surface_row - 2.0)
        max_y = max(min_y + 0.1, self.surface_row - 0.35)
        for ant_id in range(self.config.worker_count):
            x = self.rng.uniform(2.0, self.cols - 3.0)
            y = self.rng.uniform(min_y, max_y)
            vx = self.rng.choice((-1.0, 1.0))
            vy = self.rng.uniform(-0.08, 0.08)
            self.ants.append(WorkerAnt(id=ant_id, x=x, y=y, vx=vx, vy=vy))

    def _build_dig_plan(self):
        plan: list[tuple[int, int]] = []
        shaft_depth = max(6, min(self.rows - self.surface_row - 6, int(self.rows * 0.18)))
        bottom_row = self.surface_row + shaft_depth
        self.main_route = []
        self.travel_route = []
        self.chamber_tiles = set()

        for row in range(self.surface_row + 1, bottom_row + 1):
            tile = (self.entrance_col, row)
            plan.append(tile)
            self.main_route.append(tile)
            self.travel_route.append(tile)

        branch_len = max(3, min(5, self.cols // 16))
        direction = -1 if self.rng.random() < 0.5 else 1
        self.expansion_direction = direction
        corridor_end = self.entrance_col
        for step in range(1, branch_len + 1):
            col = max(1, min(self.cols - 2, self.entrance_col + direction * step))
            tile = (col, bottom_row)
            plan.append(tile)
            self.main_route.append(tile)
            self.travel_route.append(tile)
            corridor_end = col

        chamber_width = 5
        chamber_half_height = 1
        if direction > 0:
            chamber_cols = range(corridor_end, min(self.cols - 1, corridor_end + chamber_width))
        else:
            chamber_cols = range(corridor_end, max(0, corridor_end - chamber_width), -1)

        chamber_rows = range(max(self.surface_row + 2, bottom_row - chamber_half_height), min(self.rows - 2, bottom_row + chamber_half_height) + 1)

        ordered_chamber_cols = list(chamber_cols)
        self.queen_chamber_center = (
            ordered_chamber_cols[len(ordered_chamber_cols) // 2] + 0.5,
            bottom_row + 0.5,
        )
        self.expansion_chamber_center = self.queen_chamber_center
        self.expansion_frontier = (corridor_end, bottom_row)

        for col in ordered_chamber_cols:
            for row in (bottom_row, bottom_row - 1, bottom_row + 1):
                if row not in chamber_rows:
                    continue
                tile = (col, row)
                if tile in self.main_route or tile in self.chamber_tiles:
                    continue
                self.chamber_tiles.add(tile)
                plan.append(tile)

        return plan

    def get_active_dig_target(self):
        if self.current_dig_index >= len(self.dig_plan):
            return None
        return self.dig_plan[self.current_dig_index]

    def get_active_support_point(self):
        target = self.get_active_dig_target()
        if target is not None:
            support = self._find_carved_neighbor(target[0], target[1])
            if support is not None:
                return (support[0] + 0.5, support[1] + 0.5)

        if self.current_dig_index <= 0:
            return (self.entrance_col + 0.5, self.surface_row - 0.15)

        prev_col, prev_row = self.dig_plan[self.current_dig_index - 1]
        return (prev_col + 0.5, prev_row + 0.5)

    def get_carved_route_points(self):
        points = [(self.entrance_col + 0.5, max(0.5, self.surface_row - 0.15))]
        for col, row in self.travel_route:
            if self.tiles[row][col] in (TileType.TUNNEL, TileType.CHAMBER):
                points.append((col + 0.5, row + 0.5))
        return self._dedupe_points(points)

    def get_route_to_active_face(self):
        points = self.get_carved_route_points()
        points.append(self.get_active_support_point())
        return self._dedupe_points(points)

    def get_queen_route_points(self):
        points = [(self.entrance_col + 0.5, max(0.5, self.surface_row - 0.15))]
        for col, row in self.main_route:
            if self.tiles[row][col] in (TileType.TUNNEL, TileType.CHAMBER):
                points.append((col + 0.5, row + 0.5))
        points.append(self.queen_chamber_center)
        return self._dedupe_points(points)

    def queen_chamber_ready(self):
        return bool(self.chamber_tiles) and all(self.tiles[row][col] == TileType.CHAMBER for col, row in self.chamber_tiles)

    def has_open_tunnel(self):
        return self.dig_steps_completed > 0

    def dig_work_needed(self):
        target = self.get_active_dig_target()
        if target is None:
            return 0.0
        col, row = target
        if self.tiles[row][col] in (TileType.TUNNEL, TileType.CHAMBER):
            return 0.0
        return 1.0

    def apply_dig_work(self, amount: float):
        target = self.get_active_dig_target()
        if target is None:
            return False

        col, row = target
        if self.tiles[row][col] in (TileType.TUNNEL, TileType.CHAMBER):
            self._advance_dig_target()
            return True

        self.current_dig_progress += amount
        threshold = 1.35
        if self.current_dig_progress < threshold:
            return False

        self.tiles[row][col] = TileType.CHAMBER if (col, row) in self.chamber_tiles else TileType.TUNNEL
        self._tunnel_points.append((col, row))
        self.current_dig_progress = 0.0
        self.dig_steps_completed += 1
        self._advance_dig_target()
        if self.queen.state == QueenState.SURFACE_WAIT and self.queen_chamber_ready():
            self.queen.state = QueenState.RELOCATE_TO_CHAMBER
        if self.queen.state == QueenState.SETTLED:
            self.expansion_frontier = (col, row)
        return True

    def _advance_dig_target(self):
        self.current_dig_index += 1
        self.current_dig_progress = 0.0

    def tunnel_tiles(self):
        return list(self._tunnel_points)

    def random_tunnel_point(self):
        if not self._tunnel_points:
            return None
        return self._tunnel_points[self.rng.randrange(len(self._tunnel_points))]

    def append_expansion_job(self):
        from .planner import build_expansion_tiles

        new_tunnel_tiles, new_chamber_tiles, chamber_center = build_expansion_tiles(self)
        if not new_tunnel_tiles and not new_chamber_tiles:
            self.expansion_direction *= -1
            return False

        for tile in new_tunnel_tiles:
            if tile not in self.dig_plan:
                self.dig_plan.append(tile)
            if tile not in self.travel_route:
                self.travel_route.append(tile)

        for tile in new_chamber_tiles:
            if tile in self.chamber_tiles:
                continue
            self.chamber_tiles.add(tile)
            if tile not in self.dig_plan:
                self.dig_plan.append(tile)

        if new_chamber_tiles:
            self.expansion_chamber_center = (chamber_center[0] + 0.5, chamber_center[1] + 0.5)

        if new_tunnel_tiles:
            self.expansion_frontier = new_tunnel_tiles[-1]
        elif new_chamber_tiles:
            anchor = new_chamber_tiles[len(new_chamber_tiles) // 2]
            self.expansion_frontier = anchor

        if self.rng.random() < 0.5 + self.config.branchiness * 0.3:
            self.expansion_direction *= -1

        self.expansion_jobs_created += 1
        self.planner_elapsed = 0.0
        return True

    def _dedupe_points(self, points):
        compact = []
        for point in points:
            if compact and compact[-1] == point:
                continue
            compact.append(point)
        return compact

    def _find_carved_neighbor(self, col: int, row: int):
        for dx, dy in ((1, 0), (-1, 0), (0, -1), (0, 1)):
            neighbor_col = col + dx
            neighbor_row = row + dy
            if neighbor_col < 0 or neighbor_col >= self.cols or neighbor_row < 0 or neighbor_row >= self.rows:
                continue
            if self.tiles[neighbor_row][neighbor_col] in (TileType.TUNNEL, TileType.CHAMBER):
                return (neighbor_col, neighbor_row)
        return None

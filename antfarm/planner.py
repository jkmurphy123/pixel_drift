from __future__ import annotations

from .constants import ColonyPhase, QueenState, TileType


def update_planner(world, dt: float):
    if world.queen.state == QueenState.SURFACE_WAIT:
        world.colony_phase = ColonyPhase.FOUNDING
        world.planner_elapsed = 0.0
        return

    if world.queen.state == QueenState.RELOCATE_TO_CHAMBER:
        world.colony_phase = ColonyPhase.QUEEN_CHAMBER
        world.planner_elapsed = 0.0
        return

    if world.queen.state == QueenState.SETTLED and world.expansion_jobs_created == 0:
        world.colony_phase = ColonyPhase.QUEEN_CHAMBER

    if world.queen.state != QueenState.SETTLED:
        return

    if world.get_active_dig_target() is not None:
        return

    world.planner_elapsed += dt
    if world.planner_elapsed < world.config.planner_interval_sec:
        return

    world.planner_elapsed = 0.0
    if world.append_expansion_job():
        world.colony_phase = ColonyPhase.EXPANSION


def build_expansion_tiles(world):
    start_col, start_row = world.expansion_frontier
    direction = world.expansion_direction
    length = world.rng.randint(3, 6 + int(world.config.branchiness * 2.0))
    min_row = world.surface_row + 4
    max_row = world.rows - 4

    tiles = []
    col = start_col
    row = start_row

    for _ in range(length):
        drift_roll = world.rng.random()
        if drift_roll < 0.20 * world.config.branchiness:
            next_row = max(min_row, min(max_row, row + world.rng.choice((-1, 1))))
            if next_row != row:
                vertical_tile = (col, next_row)
                if world.tiles[next_row][col] not in (TileType.TUNNEL, TileType.CHAMBER) and vertical_tile not in tiles:
                    tiles.append(vertical_tile)
                row = next_row

        next_col = max(1, min(world.cols - 2, col + direction))
        if next_col != col:
            horizontal_tile = (next_col, row)
            if world.tiles[row][next_col] not in (TileType.TUNNEL, TileType.CHAMBER) and horizontal_tile not in tiles:
                tiles.append(horizontal_tile)
            col = next_col

    chamber_tiles = []
    create_chamber = ((world.expansion_jobs_created + 1) % world.config.chamber_frequency) == 0
    chamber_center = (col, row)
    if create_chamber:
        chamber_tiles = _ordered_chamber_tiles(world, col, row, min_row, max_row, tiles)
        if chamber_tiles:
            xs = [tile[0] for tile in chamber_tiles]
            ys = [tile[1] for tile in chamber_tiles]
            chamber_center = (sum(xs) / len(xs), sum(ys) / len(ys))

    return tiles, chamber_tiles, chamber_center


def _ordered_chamber_tiles(world, center_col, center_row, min_row, max_row, existing_tiles):
    desired = set()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            chamber_col = max(1, min(world.cols - 2, center_col + dx))
            chamber_row = max(min_row, min(max_row, center_row + dy))
            tile = (chamber_col, chamber_row)
            if tile in existing_tiles or world.tiles[chamber_row][chamber_col] in (TileType.TUNNEL, TileType.CHAMBER):
                continue
            desired.add(tile)

    ordered = []
    carved = set(existing_tiles)
    carved.add((center_col, center_row))

    while desired:
        progress = False
        for tile in sorted(desired, key=lambda item: (abs(item[0] - center_col) + abs(item[1] - center_row), item[1], item[0])):
            if _has_cardinal_neighbor(tile, carved, world):
                ordered.append(tile)
                carved.add(tile)
                desired.remove(tile)
                progress = True
                break
        if not progress:
            break

    return ordered


def _has_cardinal_neighbor(tile, carved, world):
    col, row = tile
    for dx, dy in ((1, 0), (-1, 0), (0, -1), (0, 1)):
        neighbor = (col + dx, row + dy)
        if neighbor in carved:
            return True
        ncol, nrow = neighbor
        if 0 <= ncol < world.cols and 0 <= nrow < world.rows and world.tiles[nrow][ncol] in (TileType.TUNNEL, TileType.CHAMBER):
            return True
    return False

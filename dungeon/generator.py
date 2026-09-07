# dungeon/generator.py
#
# Room-and-corridor dungeon generator. Produces a connected floor with
# rectangular rooms, L-shaped corridors, doors, and a distant stairs tile.

from __future__ import annotations

import random
from collections import deque
from typing import List, Tuple

from .model import CHEST, DOOR, Dungeon, FLOOR, Room, STAIRS_DOWN, TRAP, VOID, WALKABLE
from .tables import load_tables


class GenerationError(Exception):
    pass


def generate_dungeon(
    width: int,
    height: int,
    min_rooms: int = 8,
    max_rooms: int = 15,
    seed: int | None = None,
    max_attempts: int = 100,
) -> Dungeon:
    """Generate a connected dungeon floor."""
    rng = random.Random(seed)

    for attempt in range(max_attempts):
        dungeon = _try_generate(width, height, min_rooms, max_rooms, rng)
        if dungeon is not None:
            dungeon.seed = seed
            return dungeon
        rng = random.Random(seed + attempt + 1 if seed is not None else None)

    raise GenerationError(
        f"failed to generate a connected dungeon after {max_attempts} attempts"
    )


def _try_generate(
    width: int, height: int, min_rooms: int, max_rooms: int, rng: random.Random
) -> Dungeon | None:
    tiles = [[VOID for _ in range(width)] for _ in range(height)]
    rooms: List[Room] = []

    min_size = 4
    max_size = max(min_size, min(width, height) // 3)
    target_count = rng.randint(min_rooms, max_rooms)

    margin = 2
    for room_id in range(target_count):
        placed = False
        for _ in range(200):
            rw = rng.randint(min_size, max_size)
            rh = rng.randint(min_size, max_size)
            rx = rng.randint(margin, width - rw - margin)
            ry = rng.randint(margin, height - rh - margin)

            if _overlaps(rooms, rx, ry, rw, rh):
                continue

            _carve_room(tiles, rx, ry, rw, rh)
            rooms.append(Room(room_id, rx, ry, rw, rh))
            placed = True
            break

        if not placed:
            return None

    if len(rooms) < min_rooms:
        return None

    # Connect each room to the nearest previously placed room.
    for i in range(1, len(rooms)):
        start = rooms[i].center
        target = rooms[rng.randrange(i)].center
        _carve_corridor(tiles, start, target, rng)

    # Add a few extra corridors to create loops.
    extra = rng.randint(1, max(1, len(rooms) // 3))
    for _ in range(extra):
        a, b = rng.sample(rooms, 2)
        _carve_corridor(tiles, a.center, b.center, rng)

    # Verify connectivity.
    if not _all_rooms_reachable(tiles, rooms):
        return None

    # Assign room types, features, traps, and treasure.
    tables = load_tables()
    _decorate_rooms(tiles, rooms, rng, tables)

    # Place doors where corridors meet rooms.
    _place_doors(tiles, rooms)

    # Pick stairs in the room farthest from the first room.
    entrance = rooms[0].center
    stairs_room = max(rooms, key=lambda r: _dist_sq(r.center, entrance))
    sx, sy = stairs_room.center
    tiles[sy][sx] = STAIRS_DOWN

    return Dungeon(width, height, tiles, rooms, (sx, sy))


def _overlaps(rooms: List[Room], x: int, y: int, w: int, h: int, padding: int = 1) -> bool:
    for r in rooms:
        if (
            x < r.x + r.width + padding
            and x + w + padding > r.x
            and y < r.y + r.height + padding
            and y + h + padding > r.y
        ):
            return True
    return False


def _carve_room(tiles: List[List[int]], x: int, y: int, w: int, h: int) -> None:
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            tiles[yy][xx] = FLOOR


def _carve_corridor(
    tiles: List[List[int]], a: Tuple[int, int], b: Tuple[int, int], rng: random.Random
) -> None:
    """Carve an L-shaped corridor between two points."""
    x1, y1 = a
    x2, y2 = b
    if rng.random() < 0.5:
        _carve_h_line(tiles, x1, x2, y1)
        _carve_v_line(tiles, y1, y2, x2)
    else:
        _carve_v_line(tiles, y1, y2, x1)
        _carve_h_line(tiles, x1, x2, y2)


def _carve_h_line(tiles: List[List[int]], x1: int, x2: int, y: int) -> None:
    for x in range(min(x1, x2), max(x1, x2) + 1):
        tiles[y][x] = FLOOR


def _carve_v_line(tiles: List[List[int]], y1: int, y2: int, x: int) -> None:
    for y in range(min(y1, y2), max(y1, y2) + 1):
        tiles[y][x] = FLOOR


def _all_rooms_reachable(tiles: List[List[int]], rooms: List[Room]) -> bool:
    if not rooms:
        return False
    start = rooms[0].center
    if tiles[start[1]][start[0]] not in WALKABLE:
        return False

    seen = {start}
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < len(tiles[0]) and 0 <= ny < len(tiles):
                if (nx, ny) not in seen and tiles[ny][nx] in WALKABLE:
                    seen.add((nx, ny))
                    queue.append((nx, ny))

    return all(r.center in seen for r in rooms)


def _place_doors(tiles: List[List[int]], rooms: List[Room]) -> None:
    """Mark floor tiles that sit just inside a room edge and touch a corridor."""
    for room in rooms:
        for x in range(room.x, room.x + room.width):
            for y in range(room.y, room.y + room.height):
                if tiles[y][x] != FLOOR:
                    continue
                # If this floor tile is on the room boundary and has a walkable
                # neighbor outside the room, it is a doorway.
                on_boundary = (
                    x == room.x or x == room.x + room.width - 1 or
                    y == room.y or y == room.y + room.height - 1
                )
                if not on_boundary:
                    continue
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if not (0 <= nx < len(tiles[0]) and 0 <= ny < len(tiles)):
                        continue
                    if (nx < room.x or nx >= room.x + room.width or
                            ny < room.y or ny >= room.y + room.height):
                        if tiles[ny][nx] == FLOOR:
                            tiles[y][x] = DOOR
                            break


def _decorate_rooms(
    tiles: List[List[int]],
    rooms: List[Room],
    rng: random.Random,
    tables,
) -> None:
    """Assign room types and place feature tiles (traps, chests)."""
    for idx, room in enumerate(rooms):
        # Keep the entrance plain.
        if idx == 0:
            room.room_type = "ordinary"
            continue

        room.room_type = tables.weighted_choice("room_types", rng) or "ordinary"
        feature_count = rng.randint(0, 2)
        for _ in range(feature_count):
            feature = tables.weighted_choice("features", rng)
            if not feature:
                continue
            room.features.append(feature)
            info = tables["features"].get(feature, {})
            tile_name = info.get("tile")
            if tile_name == "trap":
                _place_feature_tile(tiles, room, TRAP, rng)
            elif tile_name == "chest":
                _place_feature_tile(tiles, room, CHEST, rng)


def _place_feature_tile(
    tiles: List[List[int]], room: Room, value: int, rng: random.Random
) -> None:
    """Place a feature tile on an interior floor cell of the room."""
    candidates = [
        (x, y)
        for y in range(room.y + 1, room.y + room.height - 1)
        for x in range(room.x + 1, room.x + room.width - 1)
        if tiles[y][x] == FLOOR
    ]
    if not candidates:
        return
    x, y = rng.choice(candidates)
    tiles[y][x] = value


def _dist_sq(a: Tuple[int, int], b: Tuple[int, int]) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2

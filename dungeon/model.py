# dungeon/model.py
#
# Core data classes for the procedural dungeon expedition mode.
# The simulation mutates these objects; the renderer reads them.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple


# Tile values. VOID is the default background; walls are inferred from the
# boundary between walkable and non-walkable tiles rather than stored as WALL.
VOID = 0
FLOOR = 1
WALL = 2
DOOR = 3
STAIRS_DOWN = 4

WALKABLE = {FLOOR, DOOR, STAIRS_DOWN}


@dataclass
class Room:
    room_id: int
    x: int
    y: int
    width: int
    height: int
    room_type: str = "ordinary"
    discovered: bool = False
    visited: bool = False
    features: List[str] = field(default_factory=list)

    @property
    def center(self) -> Tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2


@dataclass
class Dungeon:
    width: int
    height: int
    tiles: List[List[int]]
    rooms: List[Room]
    stairs_down: Tuple[int, int]
    seed: int | None = None
    version: int = 1

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def is_walkable(self, x: int, y: int) -> bool:
        return self.in_bounds(x, y) and self.tiles[y][x] in WALKABLE

    def room_at(self, x: int, y: int) -> Room | None:
        for room in self.rooms:
            if room.x <= x < room.x + room.width and room.y <= y < room.y + room.height:
                return room
        return None

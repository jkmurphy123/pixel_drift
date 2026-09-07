# dungeon/model.py
#
# Core data classes for the procedural dungeon expedition mode.
# The simulation mutates these objects; the renderer reads them.

from __future__ import annotations

from dataclasses import dataclass, field
from enum import auto, Enum
from typing import List, Tuple


# Tile values. VOID is the default background; walls are inferred from the
# boundary between walkable and non-walkable tiles rather than stored as WALL.
VOID = 0
FLOOR = 1
WALL = 2
DOOR = 3
STAIRS_DOWN = 4
TRAP = 5
CHEST = 6

WALKABLE = {FLOOR, DOOR, STAIRS_DOWN, TRAP, CHEST}


class ExpeditionPhase(Enum):
    WAITING = auto()
    PLANNING = auto()
    MOVING = auto()
    REVEALING = auto()
    RESOLVING_EVENT = auto()
    SHOWING_JOURNAL = auto()
    RESTING = auto()
    RETURNING = auto()
    EXPEDITION_COMPLETE = auto()


@dataclass
class Explorer:
    name: str
    role: str
    health: int = 10
    max_health: int = 10
    condition: str = "healthy"


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
class Party:
    members: List[Explorer]
    x: int
    y: int
    supplies: int = 100
    torches: int = 12
    morale: int = 75
    gold: int = 0
    current_goal: str = "explore"


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


@dataclass
class Expedition:
    dungeon: Dungeon
    party: Party
    knowledge: List[List[int]]
    route: List[Tuple[int, int]]
    journal: List[str]
    phase: ExpeditionPhase
    current_path: List[Tuple[int, int]]
    path_index: int
    phase_timer: float
    step_timer: float
    seed: int | None = None
    floor: int = 1
    day: int = 1
    explored_event_ids: set = field(default_factory=set)

    def is_discovered(self, x: int, y: int) -> bool:
        return self.dungeon.in_bounds(x, y) and self.knowledge[y][x] != VOID

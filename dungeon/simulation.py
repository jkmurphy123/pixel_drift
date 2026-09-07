# dungeon/simulation.py
#
# Expedition state machine: party planning, movement, map revealing, and
# lightweight event pauses. All timing is dt-based so the kiosk stays responsive.

from __future__ import annotations

import math
import random
from typing import List, Tuple

from . import events, journal
from .generator import GenerationError, generate_dungeon
from .model import (
    CHEST,
    Dungeon,
    Expedition,
    ExpeditionPhase,
    Explorer,
    Party,
    Room,
    STAIRS_DOWN,
    TRAP,
    VOID,
    WALKABLE,
)
from .pathfinding import find_path


DEFAULT_NAMES = ["Aldric", "Brunhilde", "Cael", "Dara", "Elden", "Freya"]
DEFAULT_ROLES = ["fighter", "rogue", "cleric", "wizard", "ranger", "bard"]


def create_expedition(dungeon: Dungeon, seed: int | None = None) -> Expedition:
    """Create a new expedition starting in the entrance room."""
    rng = random.Random(seed)
    entrance_room = dungeon.rooms[0]
    sx, sy = entrance_room.center

    members = [
        Explorer(
            name=rng.choice(DEFAULT_NAMES),
            role=rng.choice(DEFAULT_ROLES),
        )
        for _ in range(rng.randint(3, 4))
    ]
    party = Party(members=members, x=sx, y=sy)

    knowledge = [[VOID for _ in range(dungeon.width)] for _ in range(dungeon.height)]

    expedition = Expedition(
        dungeon=dungeon,
        party=party,
        knowledge=knowledge,
        route=[(sx, sy)],
        journal=["The expedition enters the dungeon."],
        phase=ExpeditionPhase.WAITING,
        current_path=[],
        path_index=0,
        phase_timer=0.0,
        step_timer=0.0,
        seed=seed,
    )

    entrance_room.discovered = True
    entrance_room.visited = True
    _reveal_room(expedition, entrance_room)
    _reveal_around(expedition, sx, sy, radius=4)
    return expedition


def update_expedition(expedition: Expedition, dt: float, config: dict) -> None:
    """Advance the expedition by one frame."""
    speed = float(config.get("simulation_speed", 1.0))
    if speed <= 0:
        return

    step_interval = max(0.1, float(config.get("seconds_per_step", 2.0))) / speed
    journal_pause = max(0.5, float(config.get("journal_pause_seconds", 8.0))) / speed

    phase = expedition.phase

    if phase == ExpeditionPhase.SHOWING_JOURNAL:
        expedition.phase_timer += dt * speed
        if expedition.phase_timer >= journal_pause:
            expedition.phase = ExpeditionPhase.WAITING
            expedition.phase_timer = 0.0
        return

    if phase == ExpeditionPhase.EXPEDITION_COMPLETE:
        return

    if phase == ExpeditionPhase.WAITING:
        _choose_next_goal(expedition)
        if expedition.current_path:
            expedition.phase = ExpeditionPhase.MOVING
            expedition.step_timer = 0.0
        return

    if phase == ExpeditionPhase.MOVING:
        expedition.step_timer += dt * speed
        while expedition.step_timer >= step_interval:
            expedition.step_timer -= step_interval
            if not _advance_one_step(expedition, config):
                break


def _choose_next_goal(expedition: Expedition) -> None:
    dungeon = expedition.dungeon
    party = expedition.party

    if _should_retreat(expedition):
        party.current_goal = "retreat"
        goal = _retreat_goal(expedition)
    else:
        frontier = _frontier_tiles(expedition)
        if frontier:
            # Pick the frontier tile closest to the party.
            goal = min(frontier, key=lambda t: _dist(t, (party.x, party.y)))
            party.current_goal = "explore"
        else:
            goal = dungeon.stairs_down
            party.current_goal = "descend"

    path = find_path(dungeon, (party.x, party.y), goal)
    if not path:
        # Fallback: try the actual map without the discovered restriction.
        path = find_path(dungeon, (party.x, party.y), goal)
    expedition.current_path = path
    expedition.path_index = 0


def _advance_one_step(expedition: Expedition, config: dict) -> bool:
    """Move the party one tile along the current path. Returns True if moved."""
    if not expedition.current_path or expedition.path_index >= len(expedition.current_path) - 1:
        expedition.phase = ExpeditionPhase.WAITING
        return False

    expedition.path_index += 1
    x, y = expedition.current_path[expedition.path_index]
    expedition.party.x = x
    expedition.party.y = y
    if (x, y) != expedition.route[-1]:
        expedition.route.append((x, y))

    _reveal_around(expedition, x, y, radius=4)
    room = expedition.dungeon.room_at(x, y)
    if room and not room.visited:
        room.visited = True
        room.discovered = True
        _reveal_room(expedition, room)
        expedition.journal.append(events.resolve_room_entry(expedition, room))
        expedition.phase = ExpeditionPhase.SHOWING_JOURNAL
        expedition.phase_timer = 0.0
        return False

    tile_event_id = (x, y)
    tile = expedition.dungeon.tiles[y][x]
    if tile in (TRAP, CHEST) and tile_event_id not in expedition.explored_event_ids:
        expedition.explored_event_ids.add(tile_event_id)
        entry = events.resolve_tile_entry(expedition, x, y)
        if entry:
            expedition.journal.append(entry)

    move_entry = journal.entry_for_move(expedition, x, y)
    if move_entry and len(expedition.journal) < 1000:
        expedition.journal.append(move_entry)

    if expedition.party.current_goal == "retreat" and (x, y) == _retreat_goal(expedition):
        expedition.journal.append("The expedition retreats to the entrance.")
        expedition.phase = ExpeditionPhase.EXPEDITION_COMPLETE
        return False

    if (x, y) == expedition.dungeon.stairs_down and not _frontier_tiles(expedition):
        expedition.journal.append(journal.entry_for_completion(expedition))
        expedition.phase = ExpeditionPhase.EXPEDITION_COMPLETE
        return False

    return True


def _frontier_tiles(expedition: Expedition) -> List[Tuple[int, int]]:
    """Undiscovered walkable tiles adjacent to a discovered tile."""
    dungeon = expedition.dungeon
    result = []
    for y in range(dungeon.height):
        for x in range(dungeon.width):
            if expedition.is_discovered(x, y):
                continue
            if dungeon.tiles[y][x] not in WALKABLE:
                continue
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if dungeon.in_bounds(nx, ny) and expedition.is_discovered(nx, ny):
                    result.append((x, y))
                    break
    return result


def _reveal_around(expedition: Expedition, cx: int, cy: int, radius: int) -> None:
    dungeon = expedition.dungeon
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if abs(dx) + abs(dy) > radius + 1:
                continue
            x, y = cx + dx, cy + dy
            if dungeon.in_bounds(x, y):
                expedition.knowledge[y][x] = dungeon.tiles[y][x]


def _reveal_room(expedition: Expedition, room: Room) -> None:
    dungeon = expedition.dungeon
    for y in range(room.y, room.y + room.height):
        for x in range(room.x, room.x + room.width):
            if dungeon.in_bounds(x, y):
                expedition.knowledge[y][x] = dungeon.tiles[y][x]
    room.discovered = True


def _dist(a: Tuple[int, int], b: Tuple[int, int]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def descend_floor(expedition: Expedition, config: dict) -> bool:
    """Generate the next floor, preserving the party and cross-floor stats.

    Returns True if a new floor was generated and the expedition reset.
    """
    seed = expedition.seed
    floor = expedition.floor + 1
    width = expedition.dungeon.width
    height = expedition.dungeon.height
    min_rooms = int(config.get("minimum_rooms", 8))
    max_rooms = int(config.get("maximum_rooms", 15))

    try:
        dungeon = generate_dungeon(
            width=width,
            height=height,
            min_rooms=min_rooms,
            max_rooms=max_rooms,
            seed=(seed + floor * 1000) if seed is not None else None,
        )
    except GenerationError:
        return False

    entrance = dungeon.rooms[0]
    sx, sy = entrance.center

    # Heal each member slightly between floors.
    heal = int(config.get("heal_on_descend", 2))
    for member in expedition.party.members:
        member.health = min(member.max_health, member.health + heal)
        if member.health > 0:
            member.condition = "healthy"

    expedition.dungeon = dungeon
    expedition.party.x = sx
    expedition.party.y = sy
    expedition.party.current_goal = "explore"
    expedition.knowledge = [[VOID for _ in range(width)] for _ in range(height)]
    expedition.route = [(sx, sy)]
    expedition.current_path = []
    expedition.path_index = 0
    expedition.phase = ExpeditionPhase.WAITING
    expedition.phase_timer = 0.0
    expedition.step_timer = 0.0
    expedition.floor = floor
    expedition.explored_event_ids.clear()
    expedition.journal.append(f"The expedition descends to floor {floor}.")

    entrance.discovered = True
    entrance.visited = True
    _reveal_room(expedition, entrance)
    _reveal_around(expedition, sx, sy, radius=4)
    return True


def _should_retreat(expedition: Expedition) -> bool:
    party = expedition.party
    total = sum(m.health for m in party.members)
    max_total = sum(m.max_health for m in party.members)
    if max_total == 0:
        return False
    health_ratio = total / max_total
    return health_ratio < 0.25 or party.supplies < 15 or party.torches == 0 or party.morale < 15


def _retreat_goal(expedition: Expedition) -> Tuple[int, int]:
    return expedition.dungeon.rooms[0].center

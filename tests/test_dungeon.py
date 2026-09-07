# tests/test_dungeon.py
#
# Tests for the dungeon expedition mode:
#   - generator produces connected dungeons
#   - mode can be constructed, entered, rendered, and exited headlessly
#   - renderer handles portrait and landscape screen sizes
#   - expedition reveals fog-of-war, moves the party, and completes a floor

import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

from dungeon.generator import generate_dungeon  # noqa: E402
from dungeon.model import CHEST, ExpeditionPhase, TRAP, VOID, WALKABLE  # noqa: E402
from dungeon.pathfinding import find_path  # noqa: E402
from dungeon.renderer import Renderer  # noqa: E402
from dungeon.simulation import create_expedition, update_expedition  # noqa: E402
from modes.dungeon_mode import DungeonMode  # noqa: E402
from dungeon.tables import load_tables  # noqa: E402
from dungeon.events import resolve_room_entry, resolve_tile_entry  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def pygame_init():
    pygame.init()
    pygame.font.init()
    yield
    pygame.quit()


class _FakeCache:
    def get_font(self, name, size, bold=False):
        return pygame.font.Font(None, size)


class _FakeManager:
    def __init__(self, w, h):
        self.screen = pygame.Surface((w, h))
        self.cache = _FakeCache()
        self.width, self.height = w, h


def _all_rooms_reachable(dungeon):
    start = dungeon.rooms[0].center
    seen = {start}
    queue = [start]
    while queue:
        x, y = queue.pop()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if dungeon.is_walkable(nx, ny) and (nx, ny) not in seen:
                seen.add((nx, ny))
                queue.append((nx, ny))
    return all(r.center in seen for r in dungeon.rooms)


def test_generator_creates_connected_dungeon():
    dungeon = generate_dungeon(64, 40, min_rooms=8, max_rooms=12, seed=123)
    assert 8 <= len(dungeon.rooms) <= 12
    assert dungeon.stairs_down is not None
    assert _all_rooms_reachable(dungeon)


def test_generator_respects_dimensions():
    dungeon = generate_dungeon(48, 32, min_rooms=5, max_rooms=5, seed=7)
    assert dungeon.width == 48
    assert dungeon.height == 32


def test_pathfinding_finds_route_between_rooms():
    dungeon = generate_dungeon(64, 40, min_rooms=4, max_rooms=4, seed=99)
    start = dungeon.rooms[0].center
    goal = dungeon.rooms[-1].center
    path = find_path(dungeon, start, goal)
    assert path
    assert path[0] == start
    assert path[-1] == goal
    for x, y in path:
        assert dungeon.is_walkable(x, y)


def test_expedition_starts_at_entrance_and_reveals_it():
    dungeon = generate_dungeon(48, 32, min_rooms=4, max_rooms=4, seed=11)
    expedition = create_expedition(dungeon, seed=11)
    assert expedition.party.x == dungeon.rooms[0].center[0]
    assert expedition.party.y == dungeon.rooms[0].center[1]
    assert expedition.is_discovered(expedition.party.x, expedition.party.y)
    assert dungeon.rooms[0].visited


def test_expedition_reveals_dungeon_over_time():
    dungeon = generate_dungeon(48, 32, min_rooms=4, max_rooms=4, seed=22)
    expedition = create_expedition(dungeon, seed=22)
    initial_known = sum(
        1 for y in range(dungeon.height) for x in range(dungeon.width)
        if expedition.knowledge[y][x] != VOID
    )
    config = {
        "seconds_per_step": 0.05,
        "journal_pause_seconds": 0.0,
        "simulation_speed": 10.0,
    }
    for _ in range(200):
        update_expedition(expedition, 0.1, config)
        if expedition.phase == ExpeditionPhase.EXPEDITION_COMPLETE:
            break
    final_known = sum(
        1 for y in range(dungeon.height) for x in range(dungeon.width)
        if expedition.knowledge[y][x] != VOID
    )
    assert final_known > initial_known
    assert expedition.phase == ExpeditionPhase.EXPEDITION_COMPLETE


def test_renderer_uses_knowledge_grid():
    dungeon = generate_dungeon(48, 32, min_rooms=4, max_rooms=4, seed=33)
    expedition = create_expedition(dungeon, seed=33)
    renderer = Renderer(
        expedition=expedition,
        config={"seed": 33},
        font_getter=lambda name, size: pygame.font.Font(None, size),
    )
    screen = pygame.Surface((640, 480))
    renderer.render(screen)
    assert renderer._tile_size > 0


def test_mode_smoke_portrait(tmp_path):
    save = tmp_path / "save.json"
    mode = DungeonMode({"seed": 42, "dungeon_width": 48, "dungeon_height": 32, "save_path": str(save)})
    manager = _FakeManager(1080, 1920)
    mode.enter(manager)
    assert mode.renderer is not None
    mode.update(0.1)
    mode.render(manager.screen)
    mode.exit()


def test_mode_smoke_landscape(tmp_path):
    save = tmp_path / "save.json"
    mode = DungeonMode({"seed": 7, "dungeon_width": 64, "dungeon_height": 40, "save_path": str(save)})
    manager = _FakeManager(1920, 1080)
    mode.enter(manager)
    assert mode.renderer is not None
    mode.update(0.1)
    mode.render(manager.screen)
    mode.exit()


def test_mode_handles_generation_error_gracefully(tmp_path):
    save = tmp_path / "save.json"
    mode = DungeonMode({
        "seed": 1,
        "dungeon_width": 8,
        "dungeon_height": 8,
        "minimum_rooms": 20,
        "maximum_rooms": 25,
        "save_path": str(save),
    })
    manager = _FakeManager(320, 240)
    mode.enter(manager)
    assert mode.renderer is None
    assert mode._error is not None
    mode.render(manager.screen)
    mode.exit()


def test_save_and_load_round_trip(tmp_path):
    save = tmp_path / "save.json"
    mode = DungeonMode({"seed": 42, "dungeon_width": 48, "dungeon_height": 32, "save_path": str(save)})
    manager = _FakeManager(640, 480)
    mode.enter(manager)
    assert mode.renderer is not None
    expedition = mode.renderer.expedition
    original_seed = expedition.seed
    original_floor = expedition.floor
    mode.update(0.1)
    mode.exit()

    # Loading should resume the same expedition.
    mode2 = DungeonMode({"seed": 999, "dungeon_width": 24, "dungeon_height": 16, "save_path": str(save)})
    mode2.enter(manager)
    assert mode2.renderer is not None
    loaded = mode2.renderer.expedition
    assert loaded.seed == original_seed
    assert loaded.floor == original_floor
    mode2.exit()


def test_generator_assigns_room_types_and_features():
    dungeon = generate_dungeon(64, 40, min_rooms=6, max_rooms=10, seed=55)
    types = {r.room_type for r in dungeon.rooms}
    assert "ordinary" in types
    # Entrance is always ordinary; other rooms should pick from tables.
    assert len(types) >= 1
    assert any(r.features for r in dungeon.rooms)


def test_generator_places_traps_and_chests():
    dungeon = generate_dungeon(64, 40, min_rooms=8, max_rooms=12, seed=66)
    traps = sum(1 for y in range(dungeon.height) for x in range(dungeon.width) if dungeon.tiles[y][x] == TRAP)
    chests = sum(1 for y in range(dungeon.height) for x in range(dungeon.width) if dungeon.tiles[y][x] == CHEST)
    assert traps + chests > 0


def test_tables_load_with_defaults():
    tables = load_tables()
    assert "room_types" in tables._data
    assert tables.weighted_choice("room_types") is not None


def test_room_entry_event_changes_party_state():
    dungeon = generate_dungeon(48, 32, min_rooms=4, max_rooms=4, seed=77)
    expedition = create_expedition(dungeon, seed=77)
    room = dungeon.rooms[1]
    room.room_type = "tomb"
    room.features = ["trap"]
    before = sum(m.health for m in expedition.party.members)
    text = resolve_room_entry(expedition, room)
    after = sum(m.health for m in expedition.party.members)
    assert text
    assert "tomb" in text.lower()
    assert after <= before


def test_tile_trap_damages_party():
    dungeon = generate_dungeon(48, 32, min_rooms=4, max_rooms=4, seed=88)
    expedition = create_expedition(dungeon, seed=88)
    # Force a trap under the party's current location for deterministic testing.
    x, y = expedition.party.x, expedition.party.y
    dungeon.tiles[y][x] = TRAP
    before = sum(m.health for m in expedition.party.members)
    text = resolve_tile_entry(expedition, x, y)
    after = sum(m.health for m in expedition.party.members)
    assert text and "trap" in text.lower()
    assert after <= before

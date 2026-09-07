# dungeon/persistence.py
#
# Atomic save/load for the complete expedition state. Saves are written in a
# background thread so the frame loop never blocks on disk I/O.

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict

from .model import (
    Dungeon,
    Expedition,
    ExpeditionPhase,
    Explorer,
    Party,
    Room,
)


SAVE_VERSION = 1
_lock = threading.Lock()
_active_save_threads: list[threading.Thread] = []


def _expedition_to_dict(expedition: Expedition) -> Dict[str, Any]:
    return {
        "version": SAVE_VERSION,
        "seed": expedition.seed,
        "floor": expedition.floor,
        "day": expedition.day,
        "phase": expedition.phase.name,
        "phase_timer": expedition.phase_timer,
        "step_timer": expedition.step_timer,
        "path_index": expedition.path_index,
        "current_path": [list(p) for p in expedition.current_path],
        "route": [list(p) for p in expedition.route],
        "explored_event_ids": [list(p) for p in expedition.explored_event_ids],
        "journal": expedition.journal[:],
        "dungeon": _dungeon_to_dict(expedition.dungeon),
        "party": _party_to_dict(expedition.party),
        "knowledge": expedition.knowledge,
    }


def _dungeon_to_dict(dungeon: Dungeon) -> Dict[str, Any]:
    return {
        "version": dungeon.version,
        "seed": dungeon.seed,
        "width": dungeon.width,
        "height": dungeon.height,
        "tiles": dungeon.tiles,
        "stairs_down": list(dungeon.stairs_down),
        "rooms": [_room_to_dict(r) for r in dungeon.rooms],
    }


def _room_to_dict(room: Room) -> Dict[str, Any]:
    return {
        "room_id": room.room_id,
        "x": room.x,
        "y": room.y,
        "width": room.width,
        "height": room.height,
        "room_type": room.room_type,
        "discovered": room.discovered,
        "visited": room.visited,
        "features": room.features[:],
    }


def _party_to_dict(party: Party) -> Dict[str, Any]:
    return {
        "members": [_explorer_to_dict(m) for m in party.members],
        "x": party.x,
        "y": party.y,
        "supplies": party.supplies,
        "torches": party.torches,
        "morale": party.morale,
        "gold": party.gold,
        "current_goal": party.current_goal,
    }


def _explorer_to_dict(explorer: Explorer) -> Dict[str, Any]:
    return {
        "name": explorer.name,
        "role": explorer.role,
        "health": explorer.health,
        "max_health": explorer.max_health,
        "condition": explorer.condition,
    }


def _dict_to_expedition(data: Dict[str, Any]) -> Expedition:
    dungeon = _dict_to_dungeon(data["dungeon"])
    party = _dict_to_party(data["party"])
    return Expedition(
        dungeon=dungeon,
        party=party,
        knowledge=[row[:] for row in data["knowledge"]],
        route=[tuple(p) for p in data["route"]],
        journal=data["journal"][:],
        phase=ExpeditionPhase[data["phase"]],
        current_path=[tuple(p) for p in data["current_path"]],
        path_index=data["path_index"],
        phase_timer=data["phase_timer"],
        step_timer=data["step_timer"],
        seed=data.get("seed"),
        floor=data.get("floor", 1),
        day=data.get("day", 1),
        explored_event_ids={tuple(p) for p in data.get("explored_event_ids", [])},
    )


def _dict_to_dungeon(data: Dict[str, Any]) -> Dungeon:
    return Dungeon(
        width=data["width"],
        height=data["height"],
        tiles=[row[:] for row in data["tiles"]],
        rooms=[_dict_to_room(r) for r in data["rooms"]],
        stairs_down=tuple(data["stairs_down"]),
        seed=data.get("seed"),
        version=data.get("version", 1),
    )


def _dict_to_room(data: Dict[str, Any]) -> Room:
    return Room(
        room_id=data["room_id"],
        x=data["x"],
        y=data["y"],
        width=data["width"],
        height=data["height"],
        room_type=data.get("room_type", "ordinary"),
        discovered=data.get("discovered", False),
        visited=data.get("visited", False),
        features=data.get("features", [])[:],
    )


def _dict_to_party(data: Dict[str, Any]) -> Party:
    return Party(
        members=[_dict_to_explorer(m) for m in data["members"]],
        x=data["x"],
        y=data["y"],
        supplies=data.get("supplies", 100),
        torches=data.get("torches", 12),
        morale=data.get("morale", 75),
        gold=data.get("gold", 0),
        current_goal=data.get("current_goal", "explore"),
    )


def _dict_to_explorer(data: Dict[str, Any]) -> Explorer:
    return Explorer(
        name=data["name"],
        role=data["role"],
        health=data.get("health", 10),
        max_health=data.get("max_health", 10),
        condition=data.get("condition", "healthy"),
    )


def _atomic_write(path: str, data: Dict[str, Any]) -> None:
    """Write JSON atomically using a temp file in the same directory."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".dungeon_save_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        shutil.move(tmp, str(target))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_expedition(expedition: Expedition, path: str) -> None:
    """Persist an expedition snapshot in a background thread."""
    snapshot = _expedition_to_dict(expedition)

    def _write() -> None:
        try:
            _atomic_write(path, snapshot)
            print(f"[DungeonExpedition] saved to {path}")
        except Exception as e:
            print(f"[DungeonExpedition] save failed: {e}")

    t = threading.Thread(target=_write, daemon=True)
    with _lock:
        _active_save_threads.append(t)
    t.start()


def load_expedition(path: str) -> Expedition | None:
    """Load an expedition from disk if it exists and is valid."""
    target = Path(path)
    if not target.exists():
        return None
    try:
        with target.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version") != SAVE_VERSION:
            return None
        return _dict_to_expedition(data)
    except (OSError, json.JSONDecodeError, KeyError) as e:
        print(f"[DungeonExpedition] load failed: {e}")
        return None


def wait_for_saves(timeout: float = 2.0) -> None:
    """Join any in-flight background saves; useful before exit."""
    with _lock:
        threads = _active_save_threads[:]
    for t in threads:
        t.join(timeout)

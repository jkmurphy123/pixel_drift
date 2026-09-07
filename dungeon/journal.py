# dungeon/journal.py
#
# Template-based expedition journal entries. No LLM is used.

from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .model import Dungeon, Expedition, Room


_ROOM_ADJECTIVES = [
    "narrow", "vaulted", "cramped", "echoing", "dusty", "damp", "sunken",
    "tilted", "rough-hewn", "polished", "mossy", "crumbling",
]

_ROOM_NOUNS = [
    "chamber", "hall", "cell", "passage", "cave", "crypt", "antechamber",
    "gallery", "cistern", "shrine", "workroom",
]

_FEATURES = {
    "trap": ["a suspicious groove in the floor", "a sprung pressure plate", "tripwire hooks"],
    "chest": ["a locked iron chest", "a rotted wooden coffer", "a small stone strongbox"],
    "statue": ["a defaced statue", "a weathered idol", "a headless figure"],
    "fountain": ["a dry fountain", "a cracked basin", "a murky pool"],
    "inscription": ["faded runes", "a chalked warning", "carved initials"],
}


def entry_for_room_discovery(expedition: "Expedition", room: "Room") -> str:
    rng = random.Random(expedition.seed + room.room_id if expedition.seed is not None else room.room_id)
    adj = rng.choice(_ROOM_ADJECTIVES)
    noun = rng.choice(_ROOM_NOUNS)
    feature_text = ""
    if room.features:
        feature = rng.choice(room.features)
        feature_text = f" Noted {rng.choice(_FEATURES.get(feature, ['something odd']))}."
    return f"Discovered Room {room.room_id}: a {adj} {noun}.{feature_text}"


def entry_for_move(expedition: "Expedition", x: int, y: int) -> str | None:
    dungeon = expedition.dungeon
    tile = dungeon.tiles[y][x]
    if tile == 3:
        return "Opened a creaking door and advanced."
    if tile == 4:
        return "Found the stairs leading deeper."
    return None


def entry_for_completion(expedition: "Expedition") -> str:
    return f"Floor {expedition.floor} mapped. The expedition returns to camp."

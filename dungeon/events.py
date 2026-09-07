# dungeon/events.py
#
# Structured event resolution for the expedition. Reads from JSON tables and
# updates party state and journal. No LLM is used during normal operation.

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from .tables import load_tables

if TYPE_CHECKING:
    from .model import Expedition, Party, Room


_tables = load_tables()


def resolve_room_entry(expedition: "Expedition", room: "Room") -> str:
    """Resolve narrative and mechanical effects when the party enters a room."""
    rng = _room_rng(expedition, room)
    party = expedition.party
    lines = []

    # Room-type flavor.
    adj = rng.choice(_tables["room_adjectives"])
    noun = rng.choice(_tables["room_nouns"])
    lines.append(f"Entered a {adj} {room.room_type} {noun} (Room {room.room_id}).")

    # Feature effects.
    for feature in room.features:
        effect = _resolve_feature(feature, party, rng)
        if effect:
            lines.append(effect)

    # Random encounter for dangerous room types.
    bias = _tables["room_types"].get(room.room_type, {}).get("bias")
    if bias == "danger" and rng.random() < 0.6:
        lines.append(_resolve_creature(party, rng))
    elif bias == "loot" and rng.random() < 0.5:
        lines.append(_resolve_treasure(party, rng))

    return " ".join(lines)


def resolve_tile_entry(expedition: "Expedition", x: int, y: int) -> str | None:
    """Resolve stepping onto a special tile such as a trap or chest."""
    tile = expedition.dungeon.tiles[y][x]
    rng = _room_rng(expedition, None, salt=x * 73856093 + y)
    if tile == 5:  # TRAP
        damage = rng.randint(1, 3)
        _damage_party(expedition.party, damage)
        return f"A trap snaps shut! The party loses {damage} health."
    if tile == 6:  # CHEST
        treasure = _tables.random_entry("treasures", rng)
        if treasure:
            party = expedition.party
            party.gold += treasure.get("gold", 0)
            party.supplies += treasure.get("supplies", 0)
            party.torches += treasure.get("torches", 0)
            party.morale = min(100, party.morale + treasure.get("morale", 0))
            name = treasure["name"]
            return rng.choice(_tables["loot_outcomes"]).format(treasure=name)
    return None


def _resolve_feature(feature: str, party: "Party", rng: random.Random) -> str | None:
    info = _tables["features"].get(feature, {})
    desc = rng.choice(_tables["feature_descriptions"].get(feature, [f"a {feature}"]))

    if info.get("dangerous") and rng.random() < 0.4:
        damage = rng.randint(1, 2)
        _damage_party(party, damage)
        return f"{desc.capitalize()} proves dangerous; party loses {damage} health."

    if feature == "fountain":
        party.supplies = min(150, party.supplies + 5)
        return f"{desc.capitalize()} provides a little water."
    if feature == "statue":
        party.morale = min(100, party.morale + 2)
        return f"{desc.capitalize()} lends an unsettling presence."
    if feature == "inscription":
        return f"{desc.capitalize()} warns of deeper dangers."
    if feature == "altar":
        party.morale = max(0, party.morale - 3)
        return f"{desc.capitalize()} darkens the mood."
    return f"Noted {desc}."


def _resolve_creature(party: "Party", rng: random.Random) -> str:
    creature = _tables.random_entry("creatures", rng)
    if creature is None:
        return "Something scuttles away in the dark."
    name = creature["name"]
    _damage_party(party, creature.get("health", 1))
    party.morale = max(0, party.morale - creature.get("morale", 0))
    party.gold += creature.get("gold", 0)
    return rng.choice(_tables["encounter_outcomes"]).format(creature=name)


def _resolve_treasure(party: "Party", rng: random.Random) -> str:
    treasure = _tables.random_entry("treasures", rng)
    if treasure is None:
        return "The room holds nothing of value."
    party.gold += treasure.get("gold", 0)
    party.supplies += treasure.get("supplies", 0)
    party.torches += treasure.get("torches", 0)
    party.morale = min(100, party.morale + treasure.get("morale", 0))
    return rng.choice(_tables["loot_outcomes"]).format(treasure=treasure["name"])


def _damage_party(party: "Party", amount: int) -> None:
    if not party.members:
        return
    # Spread damage across members; weakest takes the first hits.
    members = sorted(party.members, key=lambda m: m.health)
    for member in members:
        if amount <= 0:
            break
        take = min(amount, member.health)
        member.health -= take
        amount -= take
        if member.health == 0:
            member.condition = "unconscious"


def _room_rng(
    expedition: "Expedition",
    room: "Room | None",
    salt: int = 0,
) -> random.Random:
    seed = expedition.seed or 0
    room_id = room.room_id if room else 0
    return random.Random(seed + room_id * 7919 + salt)

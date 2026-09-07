# dungeon/tables.py
#
# Loads JSON data tables for room types, features, creatures, treasures, and
# flavor text. Falls back to embedded defaults if the file is missing or broken.

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict


DEFAULT_TABLES: Dict[str, Any] = {
    "room_types": {"ordinary": {"weight": 1}},
    "features": {},
    "creatures": [],
    "treasures": [],
    "room_adjectives": ["dusty"],
    "room_nouns": ["chamber"],
    "feature_descriptions": {},
    "encounter_outcomes": ["A {creature} appears."],
    "loot_outcomes": ["Found {treasure}."],
}


class Tables:
    """Read-only container for expedition data tables."""

    def __init__(self, data: Dict[str, Any]):
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def weighted_choice(self, key: str, rng: random.Random | None = None) -> str | None:
        pool = self._data.get(key, {})
        if not pool:
            return None
        choices = list(pool.items())
        weights = [info.get("weight", 1) for info in pool.values()]
        if rng is None:
            return random.choices(choices, weights=weights, k=1)[0][0]
        # random.Random.choices accepts weights as named argument only.
        return rng.choices(choices, weights=weights, k=1)[0][0]

    def random_entry(self, key: str, rng: random.Random | None = None) -> Any | None:
        items = self._data.get(key, [])
        if not items:
            return None
        if rng is None:
            return random.choice(items)
        return rng.choice(items)


def _tables_path() -> Path:
    return Path(__file__).with_name("data") / "tables.json"


def load_tables(path: Path | None = None) -> Tables:
    target = path or _tables_path()
    try:
        with target.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = DEFAULT_TABLES
    # Merge defaults for any missing top-level keys so downstream code can
    # always read the expected shape.
    merged = dict(DEFAULT_TABLES)
    merged.update(data)
    return Tables(merged)

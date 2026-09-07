# dungeon/persistence.py
#
# Placeholder for atomic save/load of expedition state. Wired in Phase 4.

from __future__ import annotations

from .model import Dungeon


def save_dungeon(dungeon: Dungeon, path: str) -> None:
    """Persist a dungeon to disk (Phase 4)."""
    # TODO: implement atomic JSON save with background thread.
    pass


def load_dungeon(path: str) -> Dungeon | None:
    """Load a dungeon from disk if it exists (Phase 4)."""
    # TODO: implement JSON load and version migration.
    return None

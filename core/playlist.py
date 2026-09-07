# core/playlist.py
#
# Playlist: ordered (optionally shuffled) mode rotation.
# Replaces the global-variable state machine in the old auto_mode_controller.

import random


class Playlist:
    def __init__(self, max_modes: int, shuffle: bool = False, start_index: int = 0):
        self.shuffle = shuffle
        self.entries = self._build(max_modes, start_index)
        self.pos = 0

    def _build(self, max_modes: int, start_index: int) -> list:
        playlist = list(range(max_modes))
        if self.shuffle:
            random.shuffle(playlist)
            # Ensure requested start mode is first
            if start_index in playlist:
                playlist.remove(start_index)
            playlist.insert(0, start_index)
        else:
            # Sequential order starting at start_index
            playlist = playlist[start_index:] + playlist[:start_index]
        return playlist

    @classmethod
    def single(cls, mode_index: int) -> "Playlist":
        """A locked playlist containing exactly one mode (for --play)."""
        pl = cls.__new__(cls)
        pl.shuffle = False
        pl.entries = [mode_index]
        pl.pos = 0
        return pl

    @property
    def current(self) -> int:
        return self.entries[self.pos]

    def advance(self, delta: int) -> int:
        """
        Move forward/backward by delta steps, wrapping around.
        If shuffling and we wrap forward past the end, reshuffle for the
        next lap (keeping the selected target first for continuity).
        Returns the new current mode index.
        """
        if not self.entries:
            return 0

        old_pos = self.pos
        new_pos = (self.pos + delta) % len(self.entries)

        wrapped_forward = (delta > 0) and (old_pos + delta >= len(self.entries))
        if self.shuffle and wrapped_forward:
            current_target = self.entries[new_pos]
            random.shuffle(self.entries)
            if current_target in self.entries:
                self.entries.remove(current_target)
            self.entries.insert(0, current_target)
            new_pos = 0

        self.pos = new_pos
        return self.current

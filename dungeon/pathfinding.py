# dungeon/pathfinding.py
#
# Pathfinding helpers for the party simulator. A* on the dungeon grid with
# Manhattan distance and support for walkable-tile filtering.

from __future__ import annotations

import heapq
from typing import Callable, List, Optional, Tuple

from .model import Dungeon


Point = Tuple[int, int]


def find_path(
    dungeon: Dungeon,
    start: Point,
    goal: Point,
    passable: Callable[[int, int], bool] | None = None,
) -> List[Point]:
    """Return a shortest path from start to goal, or an empty list if none."""
    if passable is None:
        passable = dungeon.is_walkable

    if not passable(*start) or not passable(*goal):
        return []

    if start == goal:
        return [start]

    open_set: List[Tuple[int, int, Point]] = []
    heapq.heappush(open_set, (0, 0, start))
    came_from: dict[Point, Point] = {}
    g_score: dict[Point, int] = {start: 0}
    counter = 1

    while open_set:
        _, _, current = heapq.heappop(open_set)
        if current == goal:
            return _reconstruct(came_from, current)

        x, y = current
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if not passable(nx, ny):
                continue
            neighbor = (nx, ny)
            tentative = g_score[current] + 1
            if neighbor not in g_score or tentative < g_score[neighbor]:
                came_from[neighbor] = current
                g_score[neighbor] = tentative
                f = tentative + _heuristic(neighbor, goal)
                heapq.heappush(open_set, (f, counter, neighbor))
                counter += 1

    return []


def _heuristic(a: Point, b: Point) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _reconstruct(came_from: dict[Point, Point], current: Point) -> List[Point]:
    path = [current]
    while current in came_from:
        current = came_from[current]
        path.append(current)
    path.reverse()
    return path

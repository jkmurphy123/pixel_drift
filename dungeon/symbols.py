# dungeon/symbols.py
#
# Code-generated drafting symbols for doors, stairs, traps, chests, etc.
# All symbols are drawn with pygame primitives so the mode needs no artwork.

from __future__ import annotations

import math

import pygame


# Stable random-like helper for hand-drawn jitter. Uses a simple integer hash
# so the same tile always gets the same imperfection.
def _hash(x: int, y: int, salt: int) -> float:
    h = (x * 73856093) ^ (y * 19349663) ^ (salt * 83492791)
    h = h & 0x7FFFFFFF
    return h / 0x7FFFFFFF


def _jitter(x: int, y: int, salt: int, amount: float = 1.0) -> tuple[float, float]:
    return (
        (_hash(x, y, salt) - 0.5) * 2.0 * amount,
        (_hash(y, x, salt + 1) - 0.5) * 2.0 * amount,
    )


def _tile_rect(screen_rect: pygame.Rect, tx: int, ty: int, tile_size: int) -> pygame.Rect:
    return pygame.Rect(
        screen_rect.x + tx * tile_size,
        screen_rect.y + ty * tile_size,
        tile_size,
        tile_size,
    )


def draw_closed_door(
    surface: pygame.Surface,
    tx: int,
    ty: int,
    tile_size: int,
    screen_rect: pygame.Rect,
    color: tuple[int, int, int],
) -> None:
    rect = _tile_rect(screen_rect, tx, ty, tile_size)
    margin = max(2, tile_size // 6)
    # Draw a short bar across the center of the tile.
    if rect.width > rect.height:
        line_rect = pygame.Rect(
            rect.x + margin, rect.centery - 1, rect.width - margin * 2, 3
        )
    else:
        line_rect = pygame.Rect(
            rect.centerx - 1, rect.y + margin, 3, rect.height - margin * 2
        )
    pygame.draw.rect(surface, color, line_rect)


def draw_stairs(
    surface: pygame.Surface,
    tx: int,
    ty: int,
    tile_size: int,
    screen_rect: pygame.Rect,
    color: tuple[int, int, int],
) -> None:
    rect = _tile_rect(screen_rect, tx, ty, tile_size)
    pad = max(2, tile_size // 8)
    inner = rect.inflate(-pad * 2, -pad * 2)
    steps = max(3, tile_size // 5)
    step_h = inner.height // steps
    for i in range(steps):
        y = inner.bottom - (i + 1) * step_h
        width = inner.width - (i * inner.width // (steps * 2))
        x = inner.centerx - width // 2
        pygame.draw.line(surface, color, (x, y), (x + width, y), max(1, tile_size // 12))


def draw_trap(
    surface: pygame.Surface,
    tx: int,
    ty: int,
    tile_size: int,
    screen_rect: pygame.Rect,
    color: tuple[int, int, int],
) -> None:
    rect = _tile_rect(screen_rect, tx, ty, tile_size)
    pad = tile_size // 4
    points = [
        (rect.centerx, rect.top + pad),
        (rect.right - pad, rect.bottom - pad),
        (rect.left + pad, rect.bottom - pad),
    ]
    pygame.draw.polygon(surface, color, points, max(1, tile_size // 10))
    pygame.draw.circle(surface, color, rect.center, max(1, tile_size // 8))


def draw_chest(
    surface: pygame.Surface,
    tx: int,
    ty: int,
    tile_size: int,
    screen_rect: pygame.Rect,
    color: tuple[int, int, int],
) -> None:
    rect = _tile_rect(screen_rect, tx, ty, tile_size)
    pad = tile_size // 5
    body = pygame.Rect(rect.x + pad, rect.centery, rect.width - pad * 2, rect.height // 3)
    pygame.draw.rect(surface, color, body, max(1, tile_size // 10))
    # Curved lid suggested by an arc.
    arc_rect = pygame.Rect(body.x, body.y - body.height // 2, body.width, body.height)
    pygame.draw.arc(surface, color, arc_rect, math.pi, 0, max(1, tile_size // 10))

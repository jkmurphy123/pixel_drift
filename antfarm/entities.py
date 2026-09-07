from __future__ import annotations

from dataclasses import dataclass

from .constants import AntState, QueenState


@dataclass
class WorkerAnt:
    id: int
    x: float
    y: float
    vx: float
    vy: float
    state: AntState = AntState.WANDER
    wander_timer: float = 0.0
    dig_progress: float = 0.0
    route_target_index: int = -1


@dataclass
class QueenAnt:
    x: float
    y: float
    state: QueenState = QueenState.SURFACE_WAIT

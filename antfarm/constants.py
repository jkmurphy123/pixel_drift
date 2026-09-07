from enum import IntEnum


class TileType(IntEnum):
    AIR = 0
    SURFACE = 1
    SOIL = 2
    TUNNEL = 3
    CHAMBER = 4
    LOOSE_SOIL = 5
    SPOIL_PILE = 6


class AntState(IntEnum):
    WANDER = 0
    SEEK_DIG_SITE = 1
    DIG = 2
    IDLE = 3


class QueenState(IntEnum):
    SURFACE_WAIT = 0
    RELOCATE_TO_CHAMBER = 1
    SETTLED = 2


class ColonyPhase(IntEnum):
    FOUNDING = 0
    QUEEN_CHAMBER = 1
    EXPANSION = 2


DEFAULT_TITLE = "ANT FARM"
DEFAULT_SIM_TICKS_PER_SECOND = 8.0
DEFAULT_WORKER_COUNT = 18

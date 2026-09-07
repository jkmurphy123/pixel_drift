from __future__ import annotations

from dataclasses import dataclass

from .constants import DEFAULT_SIM_TICKS_PER_SECOND, DEFAULT_TITLE, DEFAULT_WORKER_COUNT


@dataclass(frozen=True)
class AntFarmConfig:
    title: str
    orientation: str
    worker_count: int
    seed: int
    sim_ticks_per_second: float
    ant_speed_tiles_per_sec: float
    surface_height_ratio: float
    planner_interval_sec: float
    branchiness: float
    chamber_frequency: int
    sky_rgb: tuple[int, int, int]
    surface_rgb: tuple[int, int, int]
    soil_rgb: tuple[int, int, int]
    deep_soil_rgb: tuple[int, int, int]
    ant_rgb: tuple[int, int, int]
    debug_overlay: bool


def _rgb(value, fallback):
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return (int(value[0]), int(value[1]), int(value[2]))
    return fallback


def load_config(raw: dict) -> AntFarmConfig:
    orientation = str(raw.get("orientation", "auto")).strip().lower()
    if orientation not in {"auto", "portrait", "landscape"}:
        orientation = "auto"

    seed = raw.get("seed", 104729)
    try:
        seed = int(seed)
    except Exception:
        seed = 104729

    return AntFarmConfig(
        title=str(raw.get("title", DEFAULT_TITLE)),
        orientation=orientation,
        worker_count=max(1, int(raw.get("worker_count", DEFAULT_WORKER_COUNT))),
        seed=seed,
        sim_ticks_per_second=max(1.0, float(raw.get("sim_ticks_per_second", DEFAULT_SIM_TICKS_PER_SECOND))),
        ant_speed_tiles_per_sec=max(0.2, float(raw.get("ant_speed_tiles_per_sec", 1.6))),
        surface_height_ratio=min(0.40, max(0.10, float(raw.get("surface_height_ratio", 0.20)))),
        planner_interval_sec=max(1.0, float(raw.get("planner_interval_sec", 4.0))),
        branchiness=min(1.0, max(0.0, float(raw.get("branchiness", 0.65)))),
        chamber_frequency=max(1, int(raw.get("chamber_frequency", 1))),
        sky_rgb=_rgb(raw.get("sky_rgb"), (244, 226, 182)),
        surface_rgb=_rgb(raw.get("surface_rgb"), (188, 146, 92)),
        soil_rgb=_rgb(raw.get("soil_rgb"), (110, 76, 42)),
        deep_soil_rgb=_rgb(raw.get("deep_soil_rgb"), (72, 46, 24)),
        ant_rgb=_rgb(raw.get("ant_rgb"), (28, 18, 12)),
        debug_overlay=bool(raw.get("debug_overlay", False)),
    )

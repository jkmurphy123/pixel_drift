# core/wargames_sim.py
#
# Pure simulation core for the WarGames mode — no pygame, fully
# deterministic per seed, unit-testable headless.
#
# Model: scenarios are timed waves of missile launches. Each missile
# follows a great-circle arc (slerp) with a parabolic altitude profile.
# The Simulation precomputes every launch/detonation time up front, so
# state at any sim-time t is derived on demand — no incremental drift.

import json
import math
import random
from dataclasses import dataclass, field

EARTH_RADIUS_KM = 6371.0
DEFAULT_APEX_KM = 1200.0  # ICBM apogee flavor


# ---------------------------------------------------------------------------
# Arc math (validated 2026-08-01: ND->Moscow routes over Greenland ~75 deg N)
# ---------------------------------------------------------------------------

def _to_vec(lat, lon):
    la, lo = math.radians(lat), math.radians(lon)
    return (math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la))


def great_circle_deg(lat1, lon1, lat2, lon2):
    a, b = _to_vec(lat1, lon1), _to_vec(lat2, lon2)
    dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]))
    return math.degrees(math.acos(dot))


def slerp_arc(lat1, lon1, lat2, lon2, n=64, apex_km=DEFAULT_APEX_KM):
    """
    Great-circle arc as [(lat, lon, alt_km), ...] with a parabolic
    altitude profile (0 at both ends, apex mid-flight).
    """
    a, b = _to_vec(lat1, lon1), _to_vec(lat2, lon2)
    omega = math.acos(max(-1.0, min(1.0,
        a[0] * b[0] + a[1] * b[1] + a[2] * b[2])))
    if omega < 1e-6:
        return [(lat1, lon1, 0.0), (lat2, lon2, 0.0)]
    so = math.sin(omega)
    pts = []
    for i in range(n + 1):
        t = i / n
        sa = math.sin((1 - t) * omega) / so
        sb = math.sin(t * omega) / so
        p = (sa * a[0] + sb * b[0], sa * a[1] + sb * b[1], sa * a[2] + sb * b[2])
        lat = math.degrees(math.asin(p[2]))
        lon = math.degrees(math.atan2(p[1], p[0]))
        alt = 4.0 * apex_km * t * (1.0 - t)
        pts.append((lat, lon, alt))
    return pts


def flight_seconds(lat1, lon1, lat2, lon2):
    """Default flight time from great-circle distance (compressed time)."""
    return max(6.0, min(18.0, 6.0 + great_circle_deg(lat1, lon1, lat2, lon2) * 0.08))


def jitter(lat, lon, spread_km, rng):
    """Randomly displace a lat/lon by up to spread_km (uniform in angle)."""
    if spread_km <= 0:
        return lat, lon
    max_deg = math.degrees(spread_km / EARTH_RADIUS_KM)
    d = rng.uniform(0, max_deg)
    bearing = rng.uniform(0, 2 * math.pi)
    lat2 = lat + d * math.cos(bearing)
    lon2 = lon + (d * math.sin(bearing)) / max(0.2, math.cos(math.radians(lat)))
    return max(-89.9, min(89.9, lat2)), ((lon2 + 180) % 360) - 180


# ---------------------------------------------------------------------------
# Scenario loading & validation
# ---------------------------------------------------------------------------

def validate_scenario(sc):
    """Return a list of human-readable errors ([] = valid)."""
    errors = []
    if not isinstance(sc, dict):
        return ["scenario is not an object"]
    if not sc.get("id"):
        errors.append("missing 'id'")
    if not sc.get("name"):
        errors.append("missing 'name'")
    sides = sc.get("sides")
    if not isinstance(sides, dict) or not sides:
        errors.append("missing/empty 'sides'")
    waves = sc.get("waves")
    if not isinstance(waves, list) or not waves:
        errors.append("missing/empty 'waves'")
        return errors
    for wi, wave in enumerate(waves):
        where = f"wave {wi}"
        if not isinstance(wave, dict):
            errors.append(f"{where}: not an object")
            continue
        if "at_s" not in wave:
            errors.append(f"{where}: missing 'at_s'")
        side = wave.get("side")
        if isinstance(sides, dict) and side not in sides:
            errors.append(f"{where}: unknown side '{side}'")
        launches = wave.get("launches")
        if not isinstance(launches, list) or not launches:
            errors.append(f"{where}: missing/empty 'launches'")
            continue
        for li, ln in enumerate(launches):
            w2 = f"{where} launch {li}"
            for key in ("from", "to"):
                pt = ln.get(key)
                if (not isinstance(pt, (list, tuple)) or len(pt) != 2
                        or not all(isinstance(v, (int, float)) for v in pt)):
                    errors.append(f"{w2}: bad '{key}' coordinate")
                    continue
                lat, lon = pt
                if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                    errors.append(f"{w2}: '{key}' out of range")
            if int(ln.get("count", 1)) < 1:
                errors.append(f"{w2}: count < 1")
    return errors


def load_scenarios(path):
    """
    Load and validate the scenario file. Returns (scenarios, errors);
    invalid scenarios are skipped (reported in errors), valid ones kept.
    """
    with open(path, "r") as f:
        data = json.load(f)
    scenarios, errors = [], []
    for sc in data.get("scenarios", []):
        errs = validate_scenario(sc)
        if errs:
            errors.append(f"{sc.get('id', '?')}: {'; '.join(errs)}")
        else:
            scenarios.append(sc)
    return scenarios, errors


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def estimate_fatalities(pop_m, yield_kt):
    """
    Round-number fiction: fraction of target population, weighted by
    yield, capped below total annihilation. Returned in whole people,
    rounded to two significant figures to stay obviously illustrative.
    """
    fraction = min(0.85, 0.30 + yield_kt / 2500.0)
    raw = pop_m * 1e6 * fraction
    if raw <= 0:
        return 0
    magnitude = 10 ** math.floor(math.log10(raw))
    return int(round(raw / magnitude, 1) * magnitude)


@dataclass
class Missile:
    launch_t: float
    flight_s: float
    side: str
    arc: list                # [(lat, lon, alt_km), ...]
    target_name: str
    pop_m: float
    yield_kt: float

    @property
    def impact_t(self):
        return self.launch_t + self.flight_s

    def progress(self, t):
        """0..1 along the arc, or None if not yet launched / already hit."""
        if t < self.launch_t or t >= self.impact_t:
            return None
        return (t - self.launch_t) / self.flight_s


@dataclass
class Event:
    t: float
    kind: str                # "wave" | "impact"
    text: str


@dataclass
class Stats:
    launched: dict = field(default_factory=dict)   # side -> count
    in_flight: int = 0
    detonations: int = 0
    cities_hit: set = field(default_factory=set)
    fatalities: int = 0


class Simulation:
    """
    One scenario run. Deterministic given the same scenario dict + seed.

    Timeline: waves fire at their at_s; missiles fly flight_s seconds;
    impacts are detonations. The run ends when the last missile impacts.
    """

    def __init__(self, scenario, seed=1983):
        self.scenario = scenario
        self.name = scenario["name"]
        self.description = scenario.get("description", "")
        self.sides = scenario["sides"]
        rng = random.Random(f"{seed}:{scenario['id']}")

        default_pop = float(scenario.get("default_pop_m", 5.0))
        default_yield = float(scenario.get("default_yield_kt", 500))

        self.missiles = []
        self.events = []
        for wave in sorted(scenario["waves"], key=lambda w: w["at_s"]):
            at = float(wave["at_s"])
            side = wave["side"]
            label = wave.get("label")
            side_label = self.sides[side]["label"]
            total = sum(int(ln.get("count", 1)) for ln in wave["launches"])
            text = label or f"{side_label} LAUNCH DETECTED"
            self.events.append(Event(at, "wave", f"{text} — {total} X MISSILES"))

            for ln in wave["launches"]:
                tgt = ln.get("target", {})
                tname = tgt.get("name", "IMPACT")
                pop = float(tgt.get("pop_m", default_pop))
                yld = float(tgt.get("yield_kt", default_yield))
                spread = float(ln.get("spread_km", 0))
                for _ in range(int(ln.get("count", 1))):
                    f = jitter(ln["from"][0], ln["from"][1], spread * 0.4, rng)
                    t2 = jitter(ln["to"][0], ln["to"][1], spread, rng)
                    fs = float(ln.get("flight_s") or flight_seconds(f[0], f[1], t2[0], t2[1]))
                    # stagger launches within a wave slightly
                    lt = at + rng.uniform(0, 1.5)
                    self.missiles.append(Missile(
                        launch_t=lt, flight_s=fs, side=side,
                        arc=slerp_arc(f[0], f[1], t2[0], t2[1]),
                        target_name=tname, pop_m=pop, yield_kt=yld))

        for m in self.missiles:
            label = m.target_name if m.target_name != "IMPACT" else "TARGET"
            self.events.append(Event(m.impact_t, "impact", f"IMPACT — {label}"))

        self.events.sort(key=lambda e: e.t)
        self.duration = max((m.impact_t for m in self.missiles), default=0.0)

    def state_at(self, t):
        """Statistics snapshot at sim-time t."""
        stats = Stats(launched={s: 0 for s in self.sides})
        for m in self.missiles:
            p = m.progress(t)
            if t >= m.impact_t:
                stats.launched[m.side] += 1
                stats.detonations += 1
                if m.target_name != "IMPACT":
                    stats.cities_hit.add(m.target_name)
                stats.fatalities += estimate_fatalities(m.pop_m, m.yield_kt)
            elif p is not None:
                stats.launched[m.side] += 1
                stats.in_flight += 1
        return stats

    def events_between(self, t0, t1):
        """Log events with t0 < event.t <= t1 (mode tracks its cursor)."""
        return [e for e in self.events if t0 < e.t <= t1]

    def defcon_at(self, t):
        """Starts at 5, drops toward 1 as waves fire."""
        fired = sum(1 for e in self.events if e.kind == "wave" and e.t <= t)
        return max(1, 5 - fired)

    def outcome_text(self):
        return self.scenario.get("outcome_override", "WINNER: NONE")

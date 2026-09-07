# tests/test_wargames.py
#
# Headless tests for the WarGames mode: arc math, scenario file content,
# simulation timeline/statistics, and mode smoke tests.

import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from core.wargames_sim import (
    Simulation, estimate_fatalities, flight_seconds, great_circle_deg,
    load_scenarios, slerp_arc, validate_scenario,
)

SCENARIO_FILE = os.path.join(
    os.path.dirname(__file__), "..", "data", "wargames_scenarios.json")

TINY_SCENARIO = {
    "id": "tiny",
    "name": "TINY TEST WAR",
    "description": "two missiles, no survivors",
    "sides": {
        "blue": {"label": "BLUE", "color": [90, 200, 255]},
        "red": {"label": "RED", "color": [255, 77, 77]},
    },
    "waves": [
        {"at_s": 1.0, "side": "blue", "launches": [
            {"from": [48.0, -100.0], "to": [55.0, 37.0], "count": 1,
             "target": {"name": "ALPHAVILLE", "pop_m": 10.0, "yield_kt": 500}},
        ]},
        {"at_s": 20.0, "side": "red", "label": "RETALIATION", "launches": [
            {"from": [55.0, 37.0], "to": [48.0, -100.0], "count": 1,
             "target": {"name": "BETAVILLE", "pop_m": 8.0, "yield_kt": 500}},
        ]},
    ],
}


# ---------------------------------------------------------------------------
# Arc math
# ---------------------------------------------------------------------------

def test_slerp_arc_polar_route():
    # North Dakota -> Moscow should route over the arctic, not across
    # the Atlantic — the classic ICBM polar path.
    arc = slerp_arc(48.4, -101.3, 55.75, 37.6)
    max_lat = max(p[0] for p in arc)
    assert max_lat > 70.0
    # Parabolic altitude: zero at both ends, apex mid-flight.
    assert arc[0][2] == pytest.approx(0.0)
    assert arc[-1][2] == pytest.approx(0.0, abs=1.0)
    assert max(p[2] for p in arc) == pytest.approx(1200.0, abs=20.0)


def test_slerp_arc_antimeridian_crossing():
    arc = slerp_arc(36.0, 140.0, 37.6, -122.4)
    wraps = sum(1 for i in range(1, len(arc))
                if abs(arc[i][1] - arc[i - 1][1]) > 180)
    assert wraps == 1  # exactly one crossing for the renderer to split


def test_great_circle_deg():
    assert great_circle_deg(0, 0, 0, 90) == pytest.approx(90.0)
    assert great_circle_deg(10, 20, 10, 20) == pytest.approx(0.0)


def test_flight_seconds_bounds():
    # Short hop: near-minimum flight time.
    assert 6.0 <= flight_seconds(39.0, 125.0, 37.5, 127.0) <= 6.5
    # Antipodal: clamped to the 18 s maximum.
    assert flight_seconds(0, 0, 0, 180) == 18.0


# ---------------------------------------------------------------------------
# Scenario file content (fails if a content edit breaks the schema)
# ---------------------------------------------------------------------------

def test_shipped_scenario_file_is_valid():
    scenarios, errors = load_scenarios(SCENARIO_FILE)
    assert errors == []
    assert len(scenarios) >= 6
    ids = [s["id"] for s in scenarios]
    assert "us_first_strike" in ids
    assert "full_escalation" in ids


def test_validate_scenario_catches_bad_content():
    assert validate_scenario({}) != []
    bad = dict(TINY_SCENARIO)
    bad["waves"] = [{"at_s": 1.0, "side": "green", "launches": [
        {"from": [0, 0], "to": [1, 1], "count": 1}]}]
    errors = validate_scenario(bad)
    assert any("unknown side" in e for e in errors)


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def test_simulation_timeline_and_stats():
    sim = Simulation(TINY_SCENARIO, seed=1983)
    assert len(sim.missiles) == 2
    assert sim.duration > 20.0  # second wave fires at t=20

    early = sim.state_at(0.5)
    assert early.launched["blue"] == 0 and early.detonations == 0

    mid = sim.state_at(2.0)
    assert mid.launched["blue"] == 1
    assert mid.in_flight >= 1 or mid.detonations == 1

    end = sim.state_at(sim.duration + 1)
    assert end.launched["blue"] == 1 and end.launched["red"] == 1
    assert end.detonations == 2
    assert end.cities_hit == {"ALPHAVILLE", "BETAVILLE"}
    assert end.fatalities > 0
    assert end.in_flight == 0


def test_simulation_is_deterministic():
    a = Simulation(TINY_SCENARIO, seed=1983)
    b = Simulation(TINY_SCENARIO, seed=1983)
    for ma, mb in zip(a.missiles, b.missiles):
        assert ma.launch_t == mb.launch_t
        assert ma.arc[0] == mb.arc[0] and ma.arc[-1] == mb.arc[-1]


def test_outcome_is_always_no_winner():
    scenarios, _ = load_scenarios(SCENARIO_FILE)
    for sc in scenarios:
        sim = Simulation(sc, seed=1983)
        assert sim.outcome_text() == "WINNER: NONE"


def test_events_ordered_and_logged():
    sim = Simulation(TINY_SCENARIO, seed=1983)
    times = [e.t for e in sim.events]
    assert times == sorted(times)
    evts = sim.events_between(0.0, 1.5)
    assert any("LAUNCH" in e.text for e in evts)
    impacts = sim.events_between(1.5, sim.duration + 1)
    assert any(e.kind == "impact" for e in impacts)


def test_defcon_drops_as_waves_fire():
    sim = Simulation(TINY_SCENARIO, seed=1983)
    assert sim.defcon_at(0.0) == 5
    assert sim.defcon_at(1.5) == 4
    assert sim.defcon_at(25.0) == 3


def test_estimate_fatalities_round_number_fiction():
    f = estimate_fatalities(10.0, 500)  # 10M pop, 500 kt -> 50% -> 5.0M
    assert f == 5_000_000
    assert estimate_fatalities(1.0, 100) < 1_000_000
    assert estimate_fatalities(20.0, 10000) <= int(20e6 * 0.85) + 1


# ---------------------------------------------------------------------------
# Mode smoke tests (headless)
# ---------------------------------------------------------------------------

def _fake_manager(screen):
    from core.cache import ResourceCache

    class FakeManager:
        def __init__(self, screen):
            self.screen = screen
            self.cache = ResourceCache()
    return FakeManager(screen)


def test_mode_full_cycle_headless():
    import pygame
    pygame.init()
    pygame.font.init()
    screen = pygame.display.set_mode((1280, 720))

    from modes.wargames_mode import WarGamesMode

    mode = WarGamesMode({
        "scenario_id": "us_first_strike",  # single scenario
        "hold_on_outcome_s": 0.5,
        "hold_on_quote_s": 0.5,
        "speed": 30.0,                     # fast-forward the war
    })
    mode.enter(_fake_manager(screen))
    assert mode.sim is not None
    assert mode.sim.name == "US LAUNCHES FIRST"

    phases = set()
    for _ in range(3000):
        mode.update(1 / 30)
        mode.render(screen)
        phases.add(mode.phase)
        if mode.phase == WarGamesMode.QUOTE and mode._phase_t > 0.4:
            break

    # Intro -> run -> outcome -> quote (single scenario = cycle complete)
    assert WarGamesMode.RUN in phases
    assert WarGamesMode.OUTCOME in phases
    assert WarGamesMode.QUOTE in phases
    assert len(mode._detonations) > 0
    mode.exit()


def test_mode_handles_missing_scenario_file():
    import pygame
    pygame.init()
    pygame.font.init()
    screen = pygame.display.set_mode((1280, 720))

    from modes.wargames_mode import WarGamesMode
    mode = WarGamesMode({"scenario_file": "/nonexistent/nope.json"})
    mode.enter(_fake_manager(screen))
    assert mode.scenarios == []
    mode.update(1 / 30)
    mode.render(screen)  # must not raise
    mode.exit()

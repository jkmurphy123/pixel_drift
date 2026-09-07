# tests/test_satellite_tracker.py
#
# Headless tests for the satellite tracker mode: orbit math (core/orbit.py),
# TLE cache behavior (core/tle_store.py), and a smoke test of the mode
# itself running against a seeded TLE cache (no network).

import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from core.orbit import (
    Orbit, footprint_radius_deg, is_night, predict_passes, subsolar_point,
    target_for_date,
)
from core.tle_store import TLEStore, parse_tle_text

# Real ISS TLE downloaded from CelesTrak on 2026-08-01 (fixture).
ISS_NAME = "ISS (ZARYA)"
ISS_L1 = "1 25544U 98067A   26213.08729591  .00007538  00000+0  14334-3 0  9995"
ISS_L2 = "2 25544  51.6316  77.8927 0007210 359.3033   0.7945 15.49292827578712"
ISS_TLE_TEXT = f"{ISS_NAME:<24}\n{ISS_L1}\n{ISS_L2}\n"

FIXED_NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def iss():
    return Orbit(ISS_NAME, 25544, ISS_L1, ISS_L2)


# ---------------------------------------------------------------------------
# Orbit propagation
# ---------------------------------------------------------------------------

def test_subpoint_matches_reference(iss):
    # Reference values computed from this TLE with the validated pipeline.
    sp = iss.subpoint(FIXED_NOW)
    assert sp.lat == pytest.approx(27.727, abs=0.5)
    assert sp.lon == pytest.approx(101.129, abs=0.5)
    assert sp.alt_km == pytest.approx(426.4, abs=10)
    assert 27000 < sp.vel_kmh < 28500


def test_orbital_elements(iss):
    assert iss.period_minutes == pytest.approx(92.9, abs=0.5)
    assert iss.inclination_deg == pytest.approx(51.63, abs=0.1)
    assert iss.mean_motion_rev_day == pytest.approx(15.49, abs=0.05)


def test_ground_track_latitude_extent_matches_inclination(iss):
    track = iss.ground_track(FIXED_NOW, before_min=0, after_min=93, step_s=30)
    assert len(track) > 100
    lats = [lat for lat, lon in track]
    assert max(lats) == pytest.approx(51.6, abs=1.0)
    assert min(lats) == pytest.approx(-51.6, abs=1.0)


def test_footprint_radius():
    # ISS at ~420 km sees a horizon ~20 deg away.
    assert footprint_radius_deg(420.0) == pytest.approx(20.3, abs=0.5)
    # GEO altitude footprint approaches (but never exceeds) 81.3 deg.
    assert footprint_radius_deg(35786.0) < 82.0


def test_footprint_circle_closes(iss):
    circle = iss.footprint_circle(10.0, 20.0, 420.0, n=48)
    assert len(circle) == 48
    # All points roughly the same angular distance from the center.
    for lat, lon in circle:
        assert abs(lat - 10.0) < 25.0


def test_subsolar_point_at_equinox_noon():
    lat, lon = subsolar_point(datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc))
    assert abs(lat) < 4.0   # near the equator at equinox
    assert abs(lon) < 6.0   # near the Greenwich meridian at noon UTC


def test_is_night_antipodal_to_sun():
    sun_lat, sun_lon = 18.0, -19.0
    assert is_night(-sun_lat, sun_lon + 180.0 if sun_lon <= 0 else sun_lon - 180.0,
                    sun_lat, sun_lon)
    assert not is_night(sun_lat, sun_lon, sun_lat, sun_lon)


# ---------------------------------------------------------------------------
# Pass prediction
# ---------------------------------------------------------------------------

def test_predict_passes_over_24h(iss):
    passes = predict_passes(iss, 40.7, -74.0, FIXED_NOW, hours=24)
    assert len(passes) >= 4
    for p in passes:
        assert p.los > p.aos
        assert 0.0 < p.max_elev_deg <= 90.0
        assert 60.0 < p.duration_s < 15.0 * 60.0


def test_observer_under_satellite_sees_it_near_zenith():
    # An observer at the sub-satellite point should see the satellite
    # almost exactly overhead. Not exactly 90 deg because Orbit.subpoint
    # is geocentric while look_angles expects geodetic latitude (~0.2 deg
    # difference at mid-latitudes) — acceptable at map scale.
    from core.orbit import look_angles
    iss = Orbit(ISS_NAME, 25544, ISS_L1, ISS_L2)
    sp = iss.subpoint(FIXED_NOW)
    az, el, rng = look_angles(iss.ecef(FIXED_NOW), sp.lat, sp.lon)
    assert el > 85.0
    assert rng == pytest.approx(sp.alt_km, abs=20.0)


# ---------------------------------------------------------------------------
# Target rotation
# ---------------------------------------------------------------------------

def test_target_rotation_daily():
    targets = [{"name": n} for n in "ABCDEFGHIJ"]
    d1 = datetime(2026, 8, 1, 3, 0, tzinfo=timezone.utc)
    d2 = datetime(2026, 8, 1, 23, 0, tzinfo=timezone.utc)
    d3 = datetime(2026, 8, 2, 1, 0, tzinfo=timezone.utc)
    t1, i1 = target_for_date(targets, d1)
    t2, i2 = target_for_date(targets, d2)
    t3, i3 = target_for_date(targets, d3)
    assert i1 == i2          # same target all day
    assert i3 == (i1 + 1) % len(targets)  # advances at midnight
    assert t1 == targets[i1] and t3 == targets[i3]


# ---------------------------------------------------------------------------
# TLE parsing & cache
# ---------------------------------------------------------------------------

def test_parse_tle_text_three_line():
    sats = parse_tle_text(ISS_TLE_TEXT)
    assert 25544 in sats
    name, l1, l2 = sats[25544]
    assert name.startswith("ISS")
    assert l1.startswith("1 25544") and l2.startswith("2 25544")


def test_parse_tle_text_two_line():
    sats = parse_tle_text(f"{ISS_L1}\n{ISS_L2}\n")
    assert sats[25544][1].startswith("1 25544")


def _fetch_ok(group, timeout):
    return ISS_TLE_TEXT


def _fetch_fail(group, timeout):
    raise ConnectionError("offline")


def test_store_fetches_and_caches(tmp_path):
    store = TLEStore(tmp_path, fetcher=_fetch_ok)
    rec = store.get_satellite("stations", 25544)
    assert rec is not None and rec.status == "refreshed"
    assert (tmp_path / "stations.tle").exists()
    assert (tmp_path / "stations.meta.json").exists()


def test_store_uses_fresh_cache_without_fetching(tmp_path):
    # Seed the cache by hand with a current timestamp.
    (tmp_path / "stations.tle").write_text(ISS_TLE_TEXT)
    (tmp_path / "stations.meta.json").write_text(json.dumps({"fetched_at": time.time()}))
    store = TLEStore(tmp_path, fetcher=_fetch_fail)  # network "down"
    rec = store.get_satellite("stations", 25544)
    assert rec is not None and rec.status == "cached"


def test_store_falls_back_to_stale_cache(tmp_path):
    (tmp_path / "stations.tle").write_text(ISS_TLE_TEXT)
    old = time.time() - 7 * 24 * 3600  # a week old
    (tmp_path / "stations.meta.json").write_text(json.dumps({"fetched_at": old}))
    store = TLEStore(tmp_path, fetcher=_fetch_fail)
    rec = store.get_satellite("stations", 25544)
    assert rec is not None and rec.status == "stale"
    assert rec.age_hours > 24 * 6


def test_store_returns_none_when_offline_and_uncached(tmp_path):
    store = TLEStore(tmp_path, fetcher=_fetch_fail)
    assert store.get_satellite("stations", 25544) is None


# ---------------------------------------------------------------------------
# Mode smoke test (headless, seeded cache — no network)
# ---------------------------------------------------------------------------

def test_mode_renders_headless(tmp_path):
    import pygame
    pygame.init()
    pygame.font.init()
    screen = pygame.display.set_mode((1280, 720))

    (tmp_path / "stations.tle").write_text(ISS_TLE_TEXT)
    (tmp_path / "stations.meta.json").write_text(json.dumps({"fetched_at": time.time()}))

    from modes.satellite_tracker_mode import SatelliteTrackerMode
    from core.cache import ResourceCache

    class FakeManager:
        def __init__(self, screen):
            self.screen = screen
            self.cache = ResourceCache()

    mode = SatelliteTrackerMode({
        "rotation": "first",          # ISS is first in the default list
        "cache_dir": str(tmp_path),
        "observer_lat": 40.7,
        "observer_lon": -74.0,
    })
    mode.enter(FakeManager(screen))
    assert mode.orbit is not None
    assert mode.record.status in ("cached", "refreshed")
    assert len(mode.ground_track) > 100
    assert len(mode.passes) >= 1

    for _ in range(5):
        mode.update(1 / 30)
    mode.render(screen)
    mode.exit()


def test_mode_handles_no_data_gracefully(tmp_path):
    import pygame
    pygame.init()
    pygame.font.init()
    screen = pygame.display.set_mode((1280, 720))

    from modes.satellite_tracker_mode import SatelliteTrackerMode
    from core.cache import ResourceCache

    class FakeManager:
        def __init__(self, screen):
            self.screen = screen
            self.cache = ResourceCache()

    # Point the cache at an empty dir and block CelesTrak via an
    # unroutable max_age of 0 + no network monkeypatching: the store's
    # fetch will fail quickly if offline; to keep the test hermetic we
    # seed nothing and set max_age 0, then monkeypatch the fetcher.
    import core.tle_store as tle_mod
    orig = tle_mod._default_fetch
    tle_mod._default_fetch = _fetch_fail
    try:
        mode = SatelliteTrackerMode({"rotation": "first", "cache_dir": str(tmp_path)})
        mode.enter(FakeManager(screen))
        assert mode.orbit is None
        assert mode.record is None
        mode.update(1 / 30)
        mode.render(screen)   # must not raise
        mode.exit()
    finally:
        tle_mod._default_fetch = orig

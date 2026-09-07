# TRACKER_DESIGN.md — Real Satellite Tracker Mode

Status: **implemented** (mode 25, `modes/satellite_tracker_mode.py`) — this
document is the original proposal, kept for reference. Review decisions:
curated 10-satellite list, one-target-per-day rotation, observer/pass
prediction included, shipped as a new mode alongside mission control.
Date: 2026-08-01

Goal: a new mode that reuses the Mission Control Console look (world map,
ground track, telemetry panels, event log) but tracks **real satellites in
real time**, rotating through a target list so each run shows a different one.

Everything in the "Research findings" section was verified live on 2026-08-01.


## Research findings (verified today)

### Data sources evaluated

| Source | What it provides | Key? | Verdict |
|---|---|---|---|
| **CelesTrak** (`celestrak.org/NORAD/elements/gp.php`) | TLE/GP element sets for the whole catalog, grouped (stations, visual, weather, amateur, ...) | No | **Recommended** — fetch occasionally, propagate locally |
| N2YO API (`api.n2yo.com`) | REST positions, pass predictions | Free key, ~1000 tx/hr | Unnecessary — local SGP4 does the same without a key or rate limit |
| Open Notify (`api.open-notify.org`) | ISS position only | No | Rejected: ISS-only, and **plain HTTP only** (security scan flags it) |
| wheretheiss.at | ISS position only | No | Rejected: ISS-only |

CelesTrak was tested live: `?GROUP=stations&FORMAT=tle` returns classic
3-line TLE text (22 objects today, epoch < 12h old). `FORMAT=json` returns GP
elements but without the TLE lines, so **TLE text format is the one to use**.

Etiquette: CelesTrak asks that you not poll more than once every ~2 hours per
file. Our design fetches at most once every 24h per group and caches to disk.

### Local propagation (the key architectural choice)

The `sgp4` pip package (v2.27 tested) propagates a TLE to a position entirely
locally — no per-frame network, no API key, works offline once TLEs are cached.

Validated pipeline (ran today against live CelesTrak data):

1. Parse TLE triples (name / line 1 / line 2) → `Satrec.twoline2rv()`
2. `sat.sgp4(jd, fr)` → TEME position in km
3. Rotate by GMST around the z-axis → subpoint lat/lon + altitude

Results: ISS at lat +25.5, lon -48.5, alt 419 km (cross-checked against
wheretheiss.at at 414 km a minute earlier — consistent). A full-orbit ground
track maxes out at exactly ±51.6° latitude, matching the ISS inclination.

Notes on accuracy:
- GMST-only rotation ignores polar motion/nutation: error is tens of meters
  to ~1 km. Invisible on a world map. No need for astropy/skyfield.
- `sgp4` is a pure wheel; numpy is optional (only needed for vectorized
  batch calls, which we don't need).

### What this means

**No live-position API is needed at all.** The kiosk fetches a small TLE file
once a day, then computes everything itself every frame. This is more robust
than any polling API (works through network outages) and can't hit rate limits.


## Recommended architecture

### New dependency
- `sgp4` (add to requirements.txt — no marker needed, pure Python everywhere)

### New mode: `modes/satellite_tracker_mode.py`
Same interface contract as every other mode (`__init__(config)`, `enter/update/render/exit`).
Heavily inspired by `mission_control_console_mode.py` — same retro aesthetic,
same panel layout — and reuses the already-bundled
`data/world_coastline_110m.json` for the map.

Where mission_control fakes its telemetry, this mode substitutes real numbers:

| Existing panel | Real-data equivalent |
|---|---|
| World map + coastlines | unchanged (already real) |
| Fake ground track | Real past-orbit + next-orbit ground track from SGP4 (30s steps) |
| Fake capsule marker | Real subpoint, updated ~1 Hz, with footprint circle |
| Fake telemetry (VEL/ALT/RNG) | Real lat, lon, altitude, velocity, orbital period, inclination |
| Fake event log | Real events: TLE refresh, AOS/LOS if pass prediction enabled |
| Fake subsystem list | Target info: name, NORAD ID, TLE epoch/age, catalog group |

### Target list & rotation

Config holds a curated list of named targets (NORAD IDs), e.g.:

- 25544 ISS (ZARYA)
- 48274 CSS (TIANHE)
- 20580 HST (Hubble)
- 33591 NOAA-19
- 39084 LANDSAT 8
- 43013 NUSAT / others from the "visual" (brightest) group

Rotation behavior: on each `enter()`, advance an index persisted in
`data/tracker_state.json` (`{"next_target": 3}`). This survives restarts and
guarantees a different satellite each run, in round-robin order. Alternative
(config flag): pick by day-of-year so the whole day shows one target.

Fetching strategy: each target maps to a CelesTrak group
(`stations`, `visual`, `noaa`, ...). Fetch per-group files, not per-satellite —
one fetch covers many targets.

### TLE caching (offline resilience)

```
data/tle_cache/<group>.tle      # raw TLE text as downloaded
data/tle_cache/<group>.meta.json  # {"fetched_at": "...", "url": "..."}
```

On mode enter:
1. If cache age < `tle_max_age_hours` (default 24): use cache, no network.
2. Else try to fetch (5s timeout); on success overwrite cache.
3. On failure: use stale cache and show `TLE AGE: 2.3 DAYS — STALE` warning
   in the telemetry panel (authentic mission-control flavor, honestly).
4. If no cache at all and offline: show a "NO TRACKING DATA" message panel
   and idle — never crash.

TLE staleness degrades accuracy gradually (ISS reboosts make >1-week-old TLEs
visibly wrong); the age indicator makes this self-explanatory.

### Per-frame cost (cheap)

- Subpoint: one SGP4 call per update tick (~1 Hz is plenty; interpolate marker
  motion between ticks if we want it smoother — the ISS moves ~460 px/hour on
  a kiosk-width map).
- Ground track: ~190 points x 2 orbits = 380 SGP4 calls — recompute once per
  minute or on target switch, not per frame.
- Everything is well under 1 ms of CPU per frame.

### Config additions

`modes_registry.json`:
```json
"satellite_tracker": {
  "entrypoint": "modes.satellite_tracker_mode:SatelliteTrackerMode",
  "type_config": {
    "tle_max_age_hours": 24,
    "update_hz": 1.0,
    "target_rotation": "round_robin"
  },
  "required": ["duration"],
  "optional": ["targets", "accent_rgb", "seed", "tle_max_age_hours",
               "target_rotation", "observer_lat", "observer_lon"]
}
```

`modes_config.json` instance: add mode 26 with a `targets` list. `validate_configs.py`
must pass 0 errors / 0 warnings afterward (per project convention).

Optional `observer_lat`/`observer_lon` (kiosk location): draws a home-station
marker and enables Phase 2 pass prediction.

### Phasing (each phase independently shippable)

**Phase 1 — core tracker**
- sgp4 dependency, TLE fetch + disk cache + staleness handling
- Target rotation with persisted state
- Map with real ground track, subpoint marker, footprint circle
- Telemetry panel: LAT / LON / ALT / VEL / PERIOD / INCL / TLE AGE
- Headless test: propagate known TLE, assert lat/lon within tolerance;
  screenshot ASCII check like the mission-control map validation

**Phase 2 — situation awareness**
- Day/night terminator on the map (subsolar point from date/time — simple
  astronomy, no library; reuse wheretheiss.at's `solar_lat` formula)
- Observer marker + next-pass prediction (AOS/LOS countdown in the event log):
  propagate ahead, compute elevation from observer, find zero crossings
- Eclipse indicator (satellite in Earth's shadow)

**Phase 3 — polish**
- Multi-satellite mode: track all stations-group objects simultaneously
- "Upcoming passes today" list panel
- Optional: fetch satellite metadata (names/categories) from CelesTrak SATCAT

### What to explicitly NOT do

- No N2YO key or per-position REST polling — local SGP4 supersedes it.
- No Open Notify (HTTP-only, flagged by the security scan).
- No astropy/skyfield — sgp4 + GMST rotation is accurate enough for a map
  and keeps the dependency footprint kiosk-friendly.
- Don't fetch TLEs more than once per 24h per group (CelesTrak etiquette).

### Testing strategy

- Deterministic: ship one small test fixture TLE in `tests/`, propagate at a
  fixed timestamp, assert subpoint within ~0.5° of expected (computing
  expected values once with the validated script).
- Offline path: point cache at a fixture, disable network, verify the mode
  renders with the STALE warning.
- All headless via `SDL_VIDEODRIVER=dummy`, matching the existing test setup.

### Open questions for review

1. Target list: curated ~8-12 famous satellites (my default), or "everything
   in the stations group", or user-configurable only?
2. Rotation semantics: round-robin per run (persisted state file) vs
   one-target-per-day (date-seeded, no state file)?
3. Do we want the observer/pass-prediction feature at all, or keep Phase 1
   purely "track from space"?
4. Should this replace mode 15 or live alongside it as a new mode number
   (recommendation: alongside — the fake one is still fun)?

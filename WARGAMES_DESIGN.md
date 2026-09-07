# WARGAMES_DESIGN.md — WarGames "Big Board" Simulation Mode

Status: **implemented** (mode 26, `modes/wargames_mode.py`) — this document
is the original proposal, kept for reference. Review decisions: round-number
fictional casualties, pacing scales with wave count, classic red-vs-blue
arcs, the quote appears only after the full scenario cycle (per-scenario
cards show just "WINNER: NONE").
Date: 2026-08-01
Inspired by: the WOPR finale in *WarGames* (1983) — the NORAD war room
board cycling through nuclear war scenarios that all end the same way.

## Concept & tone

A kiosk mode that looks like the WOPR's war-games board: the world map in
green line-art (the same Natural Earth coastline data the tracker and
mission control modes already use), colored arcs for missile trajectories,
expanding white circles for detonations, and cold running statistics.

The point of the piece is the movie's point: every scenario escalates,
every counter-attack is answered, and every outcome card reads
**WINNER: NONE**. After each scenario's simulation completes, the board
displays the outcome and the line:

> THE ONLY WINNING MOVE IS NOT TO PLAY.

Everything is explicitly make-believe: scenario names are Cold-War-movie
flavor ("US LAUNCHES FIRST", "SOVIET UNION LAUNCHES FIRST", "ROGUE NATION
LAUNCHES FIRST", ...), targets are generic cities with round-number
populations, and the casualty figures are illustrative fiction, not
analysis. No real current-events targeting, no classified-anything — this
is a movie prop with a message.

## Visual design

- **Palette** (phosphor-console, matching mission control / tracker):
  - background near-black, coastlines dim green (already bundled)
  - hostile arcs: red (#ff4d4d-ish); friendly/blue arcs: cyan — or simply
    color arcs per *side* defined in the scenario
  - detonations: white flash → expanding white ring → lingering amber
    fallout dot that never fades (accumulating damage is the story)
  - text: warm white / amber accents, monospace (dejavusansmono)
- **Layout** (landscape; portrait gets the stacked variant like tracker):
  - left ~70%: world map panel "GLOBAL THREAT BOARD"
  - right column, top: SCENARIO panel (name, description, elapsed time,
    DEFCON indicator counting *up* as things get worse)
  - right column, middle: STATISTICS panel (running counters)
  - right column, bottom: EVENT LOG (launches, impacts, retaliations)
  - footer: real GMT clock + "SIMULATION n/N"
- **Arc rendering**: great-circle path via spherical linear interpolation
  (slerp) with a parabolic altitude profile (apex ~1200 km for ICBMs).
  Validated today: North Dakota → Moscow passes over Greenland at ~75°N —
  the correct polar route. Altitude is shown visually by drawing the arc
  with a bright "bus" dot at the leading edge and a fading trail, plus
  the mid-flight segment slightly wider/brighter. Arcs crossing the
  antimeridian are split the same way the satellite tracker splits its
  ground track (already-proven technique).
- **Flight feel**: each missile is a bright dot travelling its arc over
  its flight time (ICBM ~30 min compressed to ~8-15 s at default speed).
  Trails fade behind the dot. On arrival: white flash (2 frames),
  expanding ring (max radius scaled by yield), permanent amber dot.
- **Escalation readability**: as the exchange grows, arcs overlap into a
  web — by design. The board should end up looking horrifyingly busy,
  then the outcome card drops over the top: dimmed board, centered
  "WINNER: NONE" + casualty total + the quote.

## Scenario file

`data/wargames_scenarios.json` — one JSON file, a list of scenario
objects. Ships with the starter set below; adding a scenario is pure
content authoring, no code changes.

```json
{
  "scenarios": [
    {
      "id": "us_first_strike",
      "name": "US LAUNCHES FIRST",
      "description": "Counterforce strike on silo fields; massive retaliation follows.",
      "sides": {
        "blue": {"label": "US", "color": [90, 200, 255]},
        "red":  {"label": "USSR", "color": [255, 77, 77]}
      },
      "waves": [
        {
          "at_s": 2.0, "side": "blue",
          "launches": [
            {"from": [48.4, -101.3], "to": [55.8, 37.6], "count": 12, "spread_km": 800},
            {"from": [41.1, -95.9],  "to": [56.0, 92.9],  "count": 8,  "spread_km": 600}
          ]
        },
        {
          "at_s": 14.0, "side": "red", "label": "RETALIATION",
          "launches": [
            {"from": [56.3, 44.0], "to": [40.7, -74.0], "count": 10, "spread_km": 500},
            {"from": [62.0, 129.7], "to": [41.9, -87.6], "count": 10, "spread_km": 700}
          ]
        }
      ]
    }
  ]
}
```

Schema (all times in seconds of simulation time; all coords lat/lon):

- `id`, `name`, `description`
- `sides`: named belligerents with display color; events reference `side`
- `waves[]`: timed launch events
  - `at_s`: when the wave fires
  - `side`: whose missiles
  - `label` (optional): shown in the event log ("RETALIATION", "SECOND STRIKE")
  - `launches[]`: `from`/`to` endpoints, `count` missiles, `spread_km`
    random scatter of both endpoints so arcs don't perfectly overlap,
    optional per-launch `flight_s` override (default derived from
    distance: 6 s + great-circle-degrees × 0.08 s, clamped 6-18 s)
  - optional `targets`: named target list for the statistics panel
    (`{"name": "MOSCOW", "pop_m": 12.5, "yield_kt": 500}`); if absent,
    the mode uses generic "IMPACT" counters with a per-scenario
    `default_pop_m`
- Optional `outcome_override`: custom outcome text (default:
  "WINNER: NONE")

**Starter scenario set** (file ships with these; #1 is the simple one we
build and tune against, the rest are drafted at the same schema but get
tuned later):

1. `us_first_strike` — US LAUNCHES FIRST (2 waves, ~30 missiles — the
   simple scenario we implement against)
2. `ussr_first_strike` — SOVIET UNION LAUNCHES FIRST (mirror image)
3. `rogue_nation` — ROGUE NATION LAUNCHES FIRST (small first wave,
   disproportionate response)
4. `accidental_launch` — ACCIDENTAL LAUNCH (single missile, fail-safe
   fails, escalation anyway)
5. `submarine_strike` — SUBMARINE FIRST STRIKE (short flight times from
   off-coast positions — fast, dense arcs)
6. `full_escalation` — GLOBAL THERMONUCLEAR WAR (everything, hundreds of
   arcs, the finale board)

## Simulation engine (per scenario run)

Timeline model — no physics beyond the arc paths:

1. **Intro card** (2.5 s): scenario name + description typed on,
   WOPR-style.
2. **Run**: waves fire at their `at_s`. Each launch spawns `count`
   missile objects (jittered endpoints). Per frame: advance each
   missile's `t` along its arc; draw dot + fading trail. On arrival:
   detonation event → flash, expanding ring, permanent amber marker,
   statistics update, log line.
3. **Statistics** accumulate live: MISSILES LAUNCHED (per side),
   IN FLIGHT, DETONATIONS, CITIES HIT, EST. FATALITIES (sum over targets
   × yield-weighted fraction, clearly labelled EST.). DEFCON display
   moves 5→1 as waves fire.
4. **Outcome card** (~6 s): board dims, "WINNER: NONE", total
   fatalities, and the quote. Then the next scenario's intro card.
5. After the last scenario: brief finale — all outcome names scroll like
   the movie's rapid-fire list — then loop back to scenario 1.

Deterministic per scenario: `seed` in config + scenario id, so every run
of a scenario is identical (testable). The randomness is only endpoint
jitter and trail sparkle.

## Implementation plan

- `modes/wargames_mode.py` — the mode (new number 26, type `wargames`).
  Reuses `core.mapdata.load_coastlines()` and the tracker's antimeridian
  splitting helper (extract `_draw_track_segments`-equivalent into
  `core/mapdraw.py` so tracker and wargames share it — small refactor).
- `core/wargames_sim.py` — pure simulation core (no pygame): scenario
  loading/validation, missile timeline, detonation events, statistics
  accumulation. Fully unit-testable headless. Arc math (`slerp_arc`)
  lives here too.
- `data/wargames_scenarios.json` — content, as above.
- Registry entry `wargames` (optional keys: `scenario_file`,
  `scenario_id`, `speed`, `seed`, `accent_rgb`, `scanline_alpha`,
  `hold_on_outcome_s`) + mode 26 in `modes_config.json`.
  `validate_configs.py` must pass 0/0.
- Scenario validation on load: unknown side refs, missing keys,
  out-of-range lat/lon → logged once, scenario skipped (never crash the
  kiosk on a content typo).

## Config sketch

```json
"26": {
  "type": "wargames",
  "title": "WOPR // GLOBAL THERMONUCLEAR WAR",
  "speed": 1.0,
  "seed": 1983,
  "accent_rgb": [255, 204, 132]
}
```

## Testing strategy

- Sim core: fixture scenario (tiny, 2 missiles); assert timeline event
  order, statistics totals, determinism (same seed → same impacts),
  outcome always "WINNER: NONE".
- Arc math: polar route max latitude, antimeridian detection, apex
  symmetry.
- Scenario file: the shipped JSON parses and passes validation (this
  test fails CI if a content edit breaks the schema).
- Headless render smoke test + ASCII screenshot check (map + arcs +
  outcome card), same as tracker/mission-control validation.

## Phasing

- **Phase 1**: engine + renderer + scenario #1 + outcome card + cycle.
- **Phase 2**: author scenarios 2-6, finale rapid-fire list.
- **Phase 3** (optional): DEFCON klaxon-ish screen flash on first
  detonation, trajectory "bus separation" MIRV split mid-flight,
  per-city labels popping on impact.

## Open questions for review

1. Casualty figures: keep round-number fiction (my default: per-target
   `pop_m` × yield factor, labelled "EST. FATALITIES"), or show only
   CITIES HIT / DETONATIONS and leave fatalities implied?
2. Scenario pacing: fixed ~45-60 s per scenario including cards, or
   scale with wave count?
3. Side colors: classic red-vs-blue, or single hostile-red for all arcs
   regardless of side (closer to the movie's board, where everything is
   a threat)?
4. Should the finale quote appear after every scenario, or only after
   the full cycle (with per-scenario cards just showing "WINNER: NONE")?

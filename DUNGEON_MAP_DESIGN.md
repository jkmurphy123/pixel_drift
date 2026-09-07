# Procedural Dungeon Expedition — Design

## 1. Purpose

Create a non-interactive kiosk mode that presents a persistent fantasy expedition exploring a procedurally generated dungeon. The display should resemble an old tabletop RPG dungeon map drawn in dark ink on faded graph paper.

The experience is not meant to play like a fast video game. It should unfold slowly enough that viewers can glance at it throughout the day and notice new rooms, routes, discoveries, hazards, and journal entries.

## 2. Core Design Goals

- Render the entire presentation in Python with `pygame-ce`.
- Use no bitmap artwork or sprite assets.
- Generate a connected, explorable dungeon.
- Reveal the map gradually as the expedition advances.
- Simulate a small adventuring party using lightweight rules.
- Record discoveries as short expedition-journal entries.
- Preserve the dungeon and expedition state between runs.
- Fit the existing kiosk mode/plugin architecture.
- Keep visual motion slow, readable, and suitable for an unattended display.

## 3. Recommended Technology

- Python 3
- `pygame` (the version already used by pixel_drift) for rendering, timing, input events, and fonts
- JSON for configuration and saved state
- Python standard library modules such as `dataclasses`, `enum`, `random`, `json`, `pathlib`, `threading`, `tempfile`, and `heapq`

No external graphics package is required. The map is rendered with Pygame lines, rectangles, circles, polygons, arcs, and text.

Because this is a pixel_drift mode, the code must follow the existing mode contract: a single class that accepts a config dict in `__init__`, then implements `enter(manager)`, `exit()`, `handle_event(event)`, `update(dt)`, and `render(screen)`. The controller owns the display; the mode must not call `pygame.display.set_mode`.

## 4. System Architecture

The mode should be divided into five cooperating systems:

1. **Dungeon generator** — Builds rooms, corridors, doors, stairs, and features.
2. **World state** — Stores the authoritative dungeon, discovered areas, party, events, and journal.
3. **Party simulator** — Selects goals, finds paths, advances the expedition, and resolves events.
4. **Renderer** — Draws the graph paper, discovered map, symbols, route, party, status, and journal.
5. **Persistence layer** — Loads and atomically saves the complete expedition.

The simulator should modify structured state rather than presentation objects. The renderer reads that state but does not control the simulation.

## 5. Dungeon Representation

Represent each floor as a two-dimensional tile grid. Suggested tile values include:

```python
VOID = 0
FLOOR = 1
WALL = 2
DOOR = 3
STAIRS_DOWN = 4
TRAP = 5
CHEST = 6
```

Store rooms as separate objects so descriptions, events, features, and discovery status can be attached without deriving everything from tiles.

```python
@dataclass
class Room:
    room_id: int
    x: int
    y: int
    width: int
    height: int
    room_type: str = "ordinary"
    discovered: bool = False
    visited: bool = False
    features: list[str] = field(default_factory=list)
```

Maintain two map layers:

- **Actual map:** The complete dungeon known to the simulation.
- **Knowledge map:** Only the tiles and features revealed to the viewer.

This separation makes fog of war, partial information, secret doors, and mistaken annotations possible.

## 6. Dungeon Generation

### Initial algorithm

Use a room-and-corridor generator for the first implementation:

1. Place 8–15 non-overlapping rectangular rooms.
2. Connect each room to at least one previously placed room.
3. Carve horizontal and vertical corridor segments.
4. Place doors where corridors enter rooms.
5. Verify that every required room is reachable.
6. Add a few extra connections to create loops.
7. Select an entrance room.
8. Select a distant reachable room for the stairs down.
9. Add room types, hazards, treasure, and decorative features only after connectivity is valid.

Room placement should use bounded retries. Connectivity should be verified with breadth-first search before accepting the floor.

### Future Wave Function Collapse use

Full-map Wave Function Collapse is not necessary for the first version. A better later use is generating local room shapes, decorations, or thematic zones while conventional graph algorithms guarantee overall connectivity.

## 7. Party Simulation

The party can use a deliberately lightweight model:

```python
@dataclass
class Explorer:
    name: str
    role: str
    health: int = 10
    max_health: int = 10
    condition: str = "healthy"

@dataclass
class Party:
    members: list[Explorer]
    x: int
    y: int
    supplies: int = 100
    torches: int = 12
    morale: int = 75
    gold: int = 0
    current_goal: str = "explore"
```

Suggested behavior:

- Search for unexplored frontier tiles.
- Prefer doors and rooms over already-traveled corridors.
- Avoid known hazards when health or morale is low.
- Return to the entrance when supplies, torches, or health become critical.
- Seek the stairs after a configurable percentage of the floor has been explored.
- Use A* or breadth-first search to plan paths.
- Move one tile at a time so the route can be animated.

An exploration frontier is a discovered walkable tile adjacent to at least one undiscovered tile.

## 8. Simulation State Machine

The expedition should advance through non-blocking phases inside the normal Pygame update loop:

```python
class ExpeditionPhase(Enum):
    WAITING = auto()
    PLANNING = auto()
    MOVING = auto()
    REVEALING = auto()
    RESOLVING_EVENT = auto()
    SHOWING_JOURNAL = auto()
    RESTING = auto()
    RETURNING = auto()
    EXPEDITION_COMPLETE = auto()
```

A typical sequence is:

1. Choose an unexplored destination.
2. Plan a route.
3. Move the party one tile at a time.
4. Reveal nearby map tiles.
5. Pause when entering a new room.
6. Generate and resolve an encounter or discovery.
7. Display a journal entry.
8. Resume exploration.

Avoid blocking sleeps. Accumulate `dt` in timers so the kiosk remains responsive to its normal quit or mode-change handling.

## 9. Events and Narrative

Use structured events with template-generated prose. An LLM should not be required for normal operation.

```python
@dataclass
class ExpeditionEvent:
    event_type: str
    title: str
    description: str
    health_change: int = 0
    supply_change: int = 0
    morale_change: int = 0
    gold_change: int = 0
```

Potential events include:

- Opening a sealed or trapped door
- Entering an unusual room
- Detecting or triggering a trap
- Encountering a creature
- Finding treasure or supplies
- Discovering an inscription, statue, altar, or abandoned camp
- Losing a torch
- Resting
- Retreating to the entrance
- Finding stairs to another floor

Construct descriptions from themed adjective, feature, creature, condition, and consequence tables. Keep the structured result authoritative so the prose always agrees with changes to party state.

## 10. Code-Only Graph-Paper Aesthetic

### Suggested palette

```python
BACKGROUND = (224, 235, 228)
GRID_MINOR = (164, 195, 202)
GRID_MAJOR = (115, 163, 176)
INK = (37, 53, 58)
PENCIL = (92, 103, 102)
ROUTE_INK = (117, 62, 53)
PARTY_COLOR = (156, 42, 35)
```

### Drawing order

Render layers in this order:

1. Procedural paper background
2. Minor graph-paper lines
3. Heavier line every fifth square
4. Discovered floor shading
5. Crosshatching and terrain markings
6. Dungeon walls
7. Doors, stairs, traps, and feature symbols
8. Expedition route
9. Party marker
10. Room numbers and annotations
11. Status and journal panels

### Walls

For every discovered walkable tile, inspect its four neighbors. Draw a wall segment along any edge whose neighbor is not walkable. This creates clean architectural outlines without wall images.

### Drafting symbols

Generate symbols with primitives:

- Closed door: short line crossing the opening
- Open door: door leaf plus quarter-circle swing arc
- Stairs: a sequence of progressively shorter parallel lines
- Trap: triangle with a centered dot
- Statue: circle on a rectangular base
- Chest: rectangle with a curved lid
- Fountain: concentric circles
- Secret door: dotted wall segment
- Pit: crosshatched or densely shaded rectangle
- Rubble: stable clusters of short lines and small polygons

### Stable imperfection

Perfect geometry can look too modern. Draw important wall and route lines more than once with one-pixel coordinate variations. Use a deterministic seed derived from tile coordinates and direction so the irregularities remain identical on every frame and after restarting.

Never generate random visual noise during each frame. Generate it once or reproduce it from stable seeds; otherwise the map will shimmer.

### Procedural paper

Create the paper background once when the mode starts. Fill a surface with the base paper color and add sparse, low-contrast speckles or fibers at deterministic positions. Cache and reuse the resulting surface.

### Crosshatching

Use clipped diagonal lines for water, pits, collapsed areas, dangerous rooms, and explored-region accents. Keep the contrast low enough that walls and annotations remain dominant.

## 11. Reveal Animation

New areas should look as though an explorer is sketching them:

- Queue newly visible tiles.
- Reveal them sequentially over a fraction of a second.
- Draw wall segments progressively from one endpoint to the other.
- Add room numbers and annotations only after the room outline is complete.
- Briefly pause the party while a room is being mapped.

Each wall segment may store a draw-progress value from `0.0` to `1.0`. Interpolate the current endpoint to animate the ink stroke without bitmaps.

For the first implementation, an instant or short fade-in reveal is acceptable. The full progressive wall-ink animation is polish that can be added once the static look and pacing are confirmed.

## 12. Expedition Route

Draw the traveled route through tile centers using a muted red-brown pencil or ink color. Add small deterministic offsets to route points so it appears hand-drawn without vibrating. Optional arrowheads can indicate the current direction of travel.

Older route segments can fade toward the pencil color, while the most recent path remains prominent.

## 13. Kiosk Layout

For a portrait display, a useful starting layout is:

- **Top 10%:** Expedition title, dungeon floor, expedition day, elapsed time
- **Middle 65%:** Graph-paper dungeon map
- **Bottom 25%:** Party condition, supplies, torches, current goal, and recent journal entries

The map should automatically calculate the largest tile size that fits the configured viewport. A size around 16–24 pixels per tile is a good starting range, depending on display resolution. The renderer also supports a landscape layout that places the journal panel on the right side of the map instead of below it.

Long journal text should be wrapped and limited to the most recent few entries. Older entries remain in the save file but do not need to remain on screen.

A `layout` config value of `"auto"` (default) picks portrait when the screen height is greater than its width and landscape otherwise. Explicit values of `"portrait"` or `"landscape"` override the choice.

## 14. Pacing

The kiosk should prioritize atmosphere over speed.

Recommended initial pacing:

- Party step: every 1–3 seconds
- Room reveal: 1–4 seconds
- Journal pause: 5–15 seconds
- Major discovery: approximately every 20–60 seconds
- Complete floor: approximately 2–6 hours

These values should be configurable. A simulation-speed multiplier is useful for development and testing.

## 15. Persistence

Save after every significant event, including:

- Room discovery
- Encounter resolution
- Rest or retreat decision
- Party condition change
- Floor transition
- Expedition completion

Use a background thread for the actual disk write so the frame loop never stalls on storage I/O. Keep the most recent `Expedition` object in memory, queue save requests, and write to a temporary file before atomically replacing the previous save. In `exit()`, stop and join the save thread after flushing any pending save.

The save should contain:

- Format version
- Generator version
- Random seed
- Complete dungeon grid
- Rooms and features
- Knowledge/discovery grid
- Party state and location
- Current route and goal
- Exploration statistics
- Resolved-event identifiers
- Expedition journal
- Current simulation phase when safe to restore

Save the complete grid rather than relying exclusively on seed regeneration. This prevents generator changes from altering an expedition already in progress.

Write to a temporary file and atomically replace the previous save to reduce the chance of corruption after power loss.

## 16. Recommended Project Structure

The mode lives inside the pixel_drift tree rather than as a standalone app, following the existing `controlpanel/` + `modes/control_panel_mode.py` pattern:

```text
dungeon/
    __init__.py
    model.py
    generator.py
    pathfinding.py
    simulation.py
    events.py
    journal.py
    renderer.py
    symbols.py
    persistence.py
    data/
        room_descriptions.json
        encounters.json
        treasures.json
modes/
    dungeon_mode.py          # pixel_drift mode entrypoint (DungeonMode)
```

`modes/dungeon_mode.py` is the only file the controller loads directly. It owns the mode lifecycle and delegates to the `dungeon` package for generation, simulation, rendering, and persistence. The save file path is configurable; a reasonable default is `dungeon_save.json` in the project root.

## 17. Configuration Example

A pixel_drift mode instance is declared in `modes_config.json` (or a per-host `modes_config.local.json` override). The registry type name is `dungeonexpedition`.

```json
"31": {
  "type": "dungeonexpedition",
  "seed": 42,
  "dungeon_width": 64,
  "dungeon_height": 40,
  "minimum_rooms": 8,
  "maximum_rooms": 15,
  "seconds_per_step": 2.0,
  "journal_pause_seconds": 8.0,
  "target_floor_duration_minutes": 180,
  "major_grid_interval": 5,
  "show_room_numbers": true,
  "show_expedition_route": true,
  "paper_style": "blue_green",
  "layout": "auto",
  "simulation_speed": 1.0,
  "save_path": "dungeon_save.json",
  "font_name": "dejavusansmono"
}
```

Remove `design_resolution`-style keys; the renderer derives the tile size and panel layout directly from `manager.width` and `manager.height` each frame.

## 18. Mode Integration

The kiosk mode loads an existing expedition or creates a new one during `enter(manager)`. Its `update(dt)` method advances timers, reveal animations, and the state machine. Its `render(screen)` method renders the current state. Its `exit()` method requests a clean shutdown, flushes any pending save, and joins the save thread.

The mode must continue processing the existing kiosk controller's quit and mode-change events. All animations and simulation delays must therefore be non-blocking. The mode's `handle_event(event)` method is present to satisfy the mode contract; it does not need to intercept events because the controller handles global input.

The mode reads the display size from `manager.width` and `manager.height` and obtains fonts through `manager.cache.get_font(name, size)`. It never calls `pygame.display.set_mode`.

## 19. Implementation Phases

### Phase 1 — Mode skeleton and static map

- Create `modes/dungeon_mode.py` implementing the pixel_drift mode contract.
- Create the `dungeon/` package with model dataclasses, generator, and renderer.
- Generate connected rectangular rooms and corridors.
- Render graph paper, walls, doors, and stairs entirely in code.
- Register the `dungeonexpedition` type in `modes_registry.json` and add a sample instance to `modes_config.json`.
- Add a smoke test that constructs the mode and renders one frame headlessly.
- Establish the final visual palette and layout.

### Phase 2 — Exploration and animation

- Add the party marker.
- Add frontier selection and pathfinding.
- Maintain actual and discovered maps.
- Animate movement and map revealing (instant reveal for MVP; optional wall-ink animation later).

### Phase 3 — Expedition simulation

- Add party statistics and supplies.
- Add room types, features, traps, creatures, and treasure.
- Generate structured events and journal entries from JSON tables.

### Phase 4 — Persistence and progression

- Add atomic saves and loading, including a background save thread.
- Add retreat, expedition completion, and multiple floors.
- Preserve historical journals and expedition statistics.

### Phase 5 — Advanced generation

- Add themed dungeon regions.
- Add irregular and WFC-generated room patterns.
- Add factions, rival expeditions, quests, secret areas, and long-running campaign history.

## 20. Minimum Viable Version

The first useful version should include:

- One connected dungeon floor
- Code-generated graph paper
- Code-generated walls, doors, and stairs
- A party marker that explores automatically
- Animated fog-of-war revealing
- A visible expedition route
- Template-generated room discoveries
- A short on-screen journal
- Persistent JSON state

This is enough to validate both the old-school D&D aesthetic and the slow kiosk pacing before adding detailed RPG mechanics.

## 21. Visual Principle

The display should look like a map being made, not a modern game level being uncovered. Small stable imperfections, restrained color, drafting symbols, room numbers, crosshatching, arrows, and margin notes will create more atmosphere than detailed graphics. The dungeon's persistent history should give viewers a reason to return and see what the expedition has discovered next.

## 22. Mode Registration and Testing Checklist

To make the mode available to pixel_drift:

1. Add a `dungeonexpedition` entry to `modes_registry.json` with:
   - `entrypoint`: `"modes.dungeon_mode:DungeonMode"`
   - `optional` keys: `seed`, `dungeon_width`, `dungeon_height`, `minimum_rooms`, `maximum_rooms`, `seconds_per_step`, `journal_pause_seconds`, `target_floor_duration_minutes`, `major_grid_interval`, `show_room_numbers`, `show_expedition_route`, `paper_style`, `layout`, `simulation_speed`, `save_path`, `font_name`
2. Add at least one instance to `modes_config.json`.
3. Run `python validate_configs.py --all` after any JSON edits.
4. Run `python pixel_drift.py --play N --windowed` to verify visually.
5. Add tests for generator connectivity, pathfinding, save/load round-trip, and headless render smoke.

## 23. Open Questions / Decision Log

| ID | Question | Recommended Default | Status |
|---|---|---|---|
| D1 | Save file default location | `dungeon_save.json` in the project root (overridable via `save_path`) | Locked |
| D2 | Multi-floor progression | Deferred to Phase 4; MVP is one floor with completion state | Locked |
| D3 | Wall-ink reveal animation | Instant tile reveal for MVP; per-segment ink animation is Phase 5 polish | Locked |
| D4 | Layout orientation | `layout: "auto"` chooses portrait/landscape from screen aspect | Locked |
| D5 | External data tables | JSON files under `dungeon/data/`, no LLM or network calls | Locked |

Lock any of these differently before code starts; changing them later will ripple through `model.py`, `renderer.py`, and `modes_registry.json`.

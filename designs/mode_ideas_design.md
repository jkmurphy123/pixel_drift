# Pixel Drift: New Mode Ideas — Design Document

Status: **DRAFT FOR REVIEW**  
Source: `mode_ideas.txt`  
Target architecture: `pixel_drift` mode controller (`pixel_drift.py` + `core/` + `modes/`)

---

## 1. Purpose

This document turns each idea from `mode_ideas.txt` into a concrete pixel_drift mode design. Every design is intentionally scoped to the existing contract:

- One Python file: `modes/<type>_mode.py`
- One registry entry in `modes_registry.json`
- One or more instance entries in `modes_config.json`
- Configurable paths and timing; no hardcoded absolute paths
- No network I/O on the frame loop (background thread + cache if needed)
- Clean `exit()` that releases surfaces, threads, and file handles

## 2. Design constraints

| Constraint | How it is applied |
|------------|-------------------|
| Display ownership | Controller owns `pygame.display.set_mode`; modes render to `manager.screen` |
| Shared resources | Fonts/images via `manager.cache` |
| State persistence | Modes that span real time write a small JSON save file under `data/<mode>/` (configurable) |
| Real weather / network | Fetch in a background thread; render cached or fallback synthetic data while loading |
| Secrets | API keys come from `secrets.json` or env vars, injected by `core/loader.py` |
| Validation | Every registry entry lists `required` and `optional` keys so `validate_configs.py --all` stays green |

## 3. Common defaults (locked)

| Parameter | Default | Notes |
|-----------|---------|-------|
| `transition_seconds` | `2.0` | Fade in/out handled by `core/manager.py` |
| `update_rate_hz` | `30` | Target simulation tick rate; rendering is still per-frame |
| `seed` | `null` | Use current timestamp when omitted |
| `save_dir` | `"data/<mode_type>"` | Per-mode persistent state directory |
| `font_name` | `"assets/fonts/pixel.ttf"` | Fallback to `pygame.font.Font(None)` if missing |
| `overlay_mode_number` | `true` | Honors manager’s mode-number watermark |

---

## 4. Mode designs

### 4.1 Impossible Museum

- **Registry type key:** `impossiblemuseum`
- **File:** `modes/impossible_museum_mode.py`
- **Summary:** A fullscreen gallery of invented artifacts. Each exhibit shows a generated or pre-authored image, a museum label, a catalog number, and a small plaque.
- **Visual treatment:** Neutral wall color, subtle frame border, label in the lower third, catalog number in the corner.
- **Config:**
  - `required`: none
  - `optional`:
    - `exhibit_file` — path to JSON list of exhibits; default `"data/impossible_museum/exhibits.json"`
    - `dwell_seconds` — time per exhibit; default `20`
    - `catalog_prefix` — e.g. `"PX-"`; default `"PX-"`
    - `use_generated` — generate exhibits on the fly if `true`; default `false`
- **Implementation:**
  - Load exhibit list in `enter()`.
  - Pre-render label surfaces via `manager.cache` font.
  - Cross-fade between exhibits using manager fade or internal alpha.
  - Generated branch uses a small procedural artifact renderer (shapes + label text).
- **Registry snippet:**
  ```json
  "impossiblemuseum": {
    "entrypoint": "modes.impossible_museum_mode:ImpossibleMuseumMode",
    "type_config": { "dwell_seconds": 20, "catalog_prefix": "PX-" },
    "required": [],
    "optional": ["exhibit_file", "dwell_seconds", "catalog_prefix", "use_generated"]
  }
  ```
- **Config snippet:**
  ```json
  "11": { "type": "impossiblemuseum", "dwell_seconds": 25 }
  ```

---

### 4.2 Slow-Building Civilization

- **Registry type key:** `slowciv`
- **File:** `modes/slow_civ_mode.py`
- **Summary:** A tiny settlement evolves over real days. Buildings appear, roads form, population changes, disasters strike, and discoveries are logged.
- **Visual treatment:** Top-down or isometric tile grid; warm lights at night; event ticker at the bottom.
- **Config:**
  - `required`: none
  - `optional`:
    - `save_file` — default `"data/slowciv/world.json"`
    - `seed` — default `null`
    - `speed_factor` — real-time multiplier; default `1.0`
    - `map_size` — tiles; default `[40, 30]`
    - `tile_size` — default `24`
- **Implementation:**
  - Deterministic generator seeded at first run.
  - Compute elapsed real seconds between now and last save timestamp; apply `speed_factor`.
  - Advance civilization in coarse ticks (e.g., one tick per simulated hour) to avoid per-frame drift.
  - Persist world JSON on each significant change.
- **Registry snippet:**
  ```json
  "slowciv": {
    "entrypoint": "modes.slow_civ_mode:SlowCivMode",
    "type_config": { "speed_factor": 1.0, "map_size": [40, 30], "tile_size": 24 },
    "required": [],
    "optional": ["save_file", "seed", "speed_factor", "map_size", "tile_size"]
  }
  ```
- **Config snippet:**
  ```json
  "12": { "type": "slowciv", "speed_factor": 2.0 }
  ```

---

### 4.3 Procedural Dungeon Expedition

- **Registry type key:** `dungeon`
- **File:** `modes/dungeon_mode.py`
- **Summary:** A graph-paper dungeon draws itself room by room while a party of adventurers explores. Short journal entries narrate discoveries, injuries, treasure, and retreats.
- **Visual treatment:** Grid paper background, hand-drawn room outlines, fog of war, party token, right-side journal panel.
- **Config:**
  - `optional`:
    - `seed` — default `null`
    - `grid_size` — default `[32, 24]`
    - `cell_pixels` — default `20`
    - `party_speed` — cells per second; default `2.0`
    - `journal_font` — default `"assets/fonts/handwritten.ttf"`
- **Implementation:**
  - Generate dungeon via binary-space-partitioning or random walk.
  - Party uses A* toward unexplored frontier; pauses in rooms to trigger journal entries.
  - Journal entries picked from templates filled with room contents.
  - No persistence needed; loop generates a new dungeon after completion.
- **Registry snippet:**
  ```json
  "dungeon": {
    "entrypoint": "modes.dungeon_mode:DungeonMode",
    "type_config": { "grid_size": [32, 24], "cell_pixels": 20, "party_speed": 2.0 },
    "required": [],
    "optional": ["seed", "grid_size", "cell_pixels", "party_speed", "journal_font"]
  }
  ```

---

### 4.4 Generative Transit Map

- **Registry type key:** `transitmap`
- **File:** `modes/transit_map_mode.py`
- **Summary:** An imaginary subway system operates in real time. Trains move between stations, delays occur, new lines occasionally open, and cryptic station names imply a larger world.
- **Visual treatment:** Schematic map with colored lines, pulsing station dots, train dots, and a status ticker.
- **Config:**
  - `optional`:
    - `seed` — default `null`
    - `num_lines` — default `4`
    - `stations_per_line` — default `8`
    - `train_speed` — default `0.3` (line fraction per second)
    - `delay_chance` — default `0.05`
- **Implementation:**
  - Generate a planar graph with lines as polylines; ensure at least one transfer per line.
  - Simulate trains on edges; schedule dwell times at stations.
  - Occasionally spawn a delay or open a new line branch.
- **Registry snippet:**
  ```json
  "transitmap": {
    "entrypoint": "modes.transit_map_mode:TransitMapMode",
    "type_config": { "num_lines": 4, "stations_per_line": 8, "train_speed": 0.3 },
    "required": [],
    "optional": ["seed", "num_lines", "stations_per_line", "train_speed", "delay_chance"]
  }
  ```

---

### 4.5 Alternate-History Newswire

- **Registry type key:** `newswire`
- **File:** `modes/newswire_mode.py`
- **Summary:** Periodic bulletins from fictional timelines: lunar colonies in 1978, Victorian computers, Martian diplomatic crises, etc.
- **Visual treatment:** Telegraph-style ticker at the bottom; headline card in the center; dateline with alternate year.
- **Config:**
  - `optional`:
    - `bulletin_file` — JSON array; default `"data/newswire/bulletins.json"`
    - `bulletin_interval` — seconds; default `15`
    - `eras` — list of alternate era names; default `["1978 Lunar", "1895 Steam", "2024 Martian"]`
- **Implementation:**
  - Load bulletins; shuffle; cycle.
  - Generated branch combines era + event template.
  - Use a background thread only if fetching from a remote corpus (not default).
- **Registry snippet:**
  ```json
  "newswire": {
    "entrypoint": "modes.newswire_mode:NewswireMode",
    "type_config": { "bulletin_interval": 15 },
    "required": [],
    "optional": ["bulletin_file", "bulletin_interval", "eras"]
  }
  ```

---

### 4.6 Machine Archaeology Feed

- **Registry type key:** `machinearcheology`
- **File:** `modes/machine_archeology_mode.py`
- **Summary:** The display “recovers” fragments from a damaged database: photographs, messages, diagrams, coordinates, corrupted text, partial reconstructions.
- **Visual treatment:** CRT scanlines, hex dump border, blocks with corruption artifacts, block-by-block reveal animation.
- **Config:**
  - `optional`:
    - `fragment_file` — default `"data/machine_archeology/fragments.json"`
    - `corruption_chance` — default `0.25`
    - `reveal_speed` — chars per second; default `18`
    - `glitch_interval` — seconds; default `4`
- **Implementation:**
  - Fragments contain type, text, and optional image path.
  - Render with a typewriter-style reveal and occasional character substitution.
  - Image fragments get a glitch shader via random rectangle overlays (no external libs).
- **Registry snippet:**
  ```json
  "machinearcheology": {
    "entrypoint": "modes.machine_archeology_mode:MachineArcheologyMode",
    "type_config": { "corruption_chance": 0.25, "reveal_speed": 18 },
    "required": [],
    "optional": ["fragment_file", "corruption_chance", "reveal_speed", "glitch_interval"]
  }
  ```

---

### 4.7 Artificial Ecosystem

- **Registry type key:** `ecosystem`
- **File:** `modes/ecosystem_mode.py`
- **Summary:** Plants or microorganisms grow, reproduce, compete, and die. Environmental values change slowly, making the display different every day.
- **Visual treatment:** Petri-dish or garden view; color-coded species; nutrient heatmap overlay optional.
- **Config:**
  - `optional`:
    - `seed` — default `null`
    - `grid_size` — default `[80, 60]`
    - `species_count` — default `4`
    - `env_change_rate` — default `0.001`
    - `save_file` — default `"data/ecosystem/world.json"`
- **Implementation:**
  - Multi-layer grid: soil moisture, sunlight, species presence.
  - Deterministic rules; persist state so growth spans days.
  - Render scaled cells with interpolation for smooth visuals.
- **Registry snippet:**
  ```json
  "ecosystem": {
    "entrypoint": "modes.ecosystem_mode:EcosystemMode",
    "type_config": { "grid_size": [80, 60], "species_count": 4 },
    "required": [],
    "optional": ["seed", "grid_size", "species_count", "env_change_rate", "save_file"]
  }
  ```

---

### 4.8 Cosmic Weather Station

- **Registry type key:** `cosmicweather`
- **File:** `modes/cosmic_weather_mode.py`
- **Summary:** Fictional reports from planets and moons: methane storms on Titan, solar radiation warnings, auroras, dust conditions, orbital sunrise times.
- **Visual treatment:** Dashboard with planet icon, current condition glyph, temperature/wind/radiation bars, and rotating "advisory" banner.
- **Config:**
  - `optional`:
    - `bodies_file` — default `"data/cosmic_weather/bodies.json"`
    - `body_interval` — seconds; default `20`
    - `units` — `"metric"` or `"imperial"`; default `"metric"`
- **Implementation:**
  - Load list of bodies and condition templates.
  - Generate report from seed + simulated orbital position.
  - Cycle through bodies; optionally include a 7-"sol" forecast.
- **Registry snippet:**
  ```json
  "cosmicweather": {
    "entrypoint": "modes.cosmic_weather_mode:CosmicWeatherMode",
    "type_config": { "body_interval": 20, "units": "metric" },
    "required": [],
    "optional": ["bodies_file", "body_interval", "units"]
  }
  ```

---

### 4.9 Dreaming Computer

- **Registry type key:** `dreamingcomputer`
- **File:** `modes/dreaming_computer_mode.py`
- **Summary:** Abstract imagery periodically emerges from scrolling associations, invented memories, diagrams, and fragments of generated prose.
- **Visual treatment:** Soft drifting shapes, faint grid, text fragments fading in/out, occasional diagram lines.
- **Config:**
  - `optional`:
    - `fragment_file` — default `"data/dreaming_computer/fragments.json"`
    - `dream_interval` — seconds between thematic shifts; default `30`
    - `shape_count` — default `12`
- **Implementation:**
  - Maintain a palette of drifting blobs and text particles.
  - Periodically pick a theme and spawn associated fragments.
  - Purely visual; no persistence required.
- **Registry snippet:**
  ```json
  "dreamingcomputer": {
    "entrypoint": "modes.dreaming_computer_mode:DreamingComputerMode",
    "type_config": { "dream_interval": 30, "shape_count": 12 },
    "required": [],
    "optional": ["fragment_file", "dream_interval", "shape_count"]
  }
  ```

---

### 4.10 World-in-a-Window

- **Registry type key:** `worldwindow`
- **File:** `modes/world_window_mode.py`
- **Summary:** A single illustrated scene changes with real time of day and weather: lights turn on, people pass, storms arrive, snow accumulates, unusual events occur.
- **Visual treatment:** Layered scene background, weather overlay, animated sprites, time-of-day tint.
- **Config:**
  - `optional`:
    - `scene_file` — default `"data/world_window/scene.json"`
    - `use_real_weather` — default `false`
    - `weather_api_key` — secret key name; default `"OPENWEATHER_API_KEY"`
    - `lat` / `lon` — default `null`
    - `weather_interval` — minutes; default `15`
- **Implementation:**
  - If `use_real_weather` is true, fetch weather in a background thread using the injected secret.
  - Otherwise simulate a weather cycle from seed.
  - Render layered scene with tint based on real time.
  - Cache weather result; fallback to synthetic if fetch fails.
- **Registry snippet:**
  ```json
  "worldwindow": {
    "entrypoint": "modes.world_window_mode:WorldWindowMode",
    "type_config": { "use_real_weather": false, "weather_interval": 15 },
    "required": [],
    "optional": ["scene_file", "use_real_weather", "weather_api_key", "lat", "lon", "weather_interval"]
  }
  ```
- **Secret dependency:** `OPENWEATHER_API_KEY` if real weather enabled.

---

### 4.11 Unsolved Mystery Board

- **Registry type key:** `mysteryboard`
- **File:** `modes/mystery_board_mode.py`
- **Summary:** Documents, photographs, maps, and evidence appear over time while the system proposes and rejects theories. A case may unfold across a week.
- **Visual treatment:** Corkboard background, pinned items connected by red string, theory list with strike-throughs.
- **Config:**
  - `optional`:
    - `case_file` — default `"data/mystery_board/cases.json"`
    - `evidence_interval` — hours of real time between new clues; default `4`
    - `save_file` — default `"data/mystery_board/state.json"`
- **Implementation:**
  - Load case with evidence list and theory timeline.
  - Reveal evidence based on real elapsed time since first run.
  - Persist revealed set and current theory.
- **Registry snippet:**
  ```json
  "mysteryboard": {
    "entrypoint": "modes.mystery_board_mode:MysteryBoardMode",
    "type_config": { "evidence_interval": 4 },
    "required": [],
    "optional": ["case_file", "evidence_interval", "save_file"]
  }
  ```

---

### 4.12 Living Bestiary

- **Registry type key:** `bestiary`
- **File:** `modes/bestiary_mode.py`
- **Summary:** Displays an imaginary creature with animated behavior, habitat information, field notes, anatomical sketches, and occasional camera-trap observations.
- **Visual treatment:** Split screen: creature enclosure on the left, field-note card on the right; occasional flash for camera trap.
- **Config:**
  - `optional`:
    - `creature_file` — default `"data/bestiary/creatures.json"`
    - `dwell_seconds` — default `30`
    - `camera_trap_interval` — default `8`
- **Implementation:**
  - Creatures described by silhouette shape, color, behavior type.
  - Simple procedural animation (breathing, pacing, perching).
  - Cycle creatures; camera trap captures a still frame with timestamp.
- **Registry snippet:**
  ```json
  "bestiary": {
    "entrypoint": "modes.bestiary_mode:BestiaryMode",
    "type_config": { "dwell_seconds": 30, "camera_trap_interval": 8 },
    "required": [],
    "optional": ["creature_file", "dwell_seconds", "camera_trap_interval"]
  }
  ```

---

### 4.13 Infinite Factory

- **Registry type key:** `infinitefactory`
- **File:** `modes/infinite_factory_mode.py`
- **Summary:** A visual production line assembles increasingly strange objects. Counters, quality inspections, failures, maintenance messages, and shift reports supply narrative.
- **Visual treatment:** Side-scrolling conveyor belt, robotic arms, objects on belt, status LEDs, shift report ticker.
- **Config:**
  - `optional`:
    - `product_file` — default `"data/infinite_factory/products.json"`
    - `belt_speed` — pixels per second; default `40`
    - `shift_length` — seconds; default `120`
- **Implementation:**
  - Maintain belt items with positions and quality states.
  - Spawn products from a list that grows progressively stranger.
  - Log shift summaries and occasional breakdown events.
- **Registry snippet:**
  ```json
  "infinitefactory": {
    "entrypoint": "modes.infinite_factory_mode:InfiniteFactoryMode",
    "type_config": { "belt_speed": 40, "shift_length": 120 },
    "required": [],
    "optional": ["product_file", "belt_speed", "shift_length"]
  }
  ```

---

### 4.14 Historical Daybook

- **Registry type key:** `daybook`
- **File:** `modes/daybook_mode.py`
- **Summary:** Reconstructs one particular historical day hour by hour using maps, weather, headlines, and contemporary diary excerpts.
- **Visual treatment:** Newspaper-style layout; hourly column; small map; weather icon; diary quote panel.
- **Config:**
  - `optional`:
    - `event_file` — default `"data/daybook/events.json"`
    - `date` — specific date; default `null` (picks today’s month/day historically)
    - `hour_advance` — seconds per simulated hour; default `5`
- **Implementation:**
  - Load events keyed by `MM-DD`; pick today if `date` omitted.
  - Advance simulated hour on a timer; render matching events.
  - Loop back to 00:00 after 24 hours.
- **Registry snippet:**
  ```json
  "daybook": {
    "entrypoint": "modes.daybook_mode:DaybookMode",
    "type_config": { "hour_advance": 5 },
    "required": [],
    "optional": ["event_file", "date", "hour_advance"]
  }
  ```

---

### 4.15 Language Evolution Simulator

- **Registry type key:** `languageevolution`
- **File:** `modes/language_evolution_mode.py`
- **Summary:** Begins with a small invented vocabulary and shows words changing across centuries, branching into dialects and appearing in translated inscriptions.
- **Visual treatment:** Word family tree / timeline; inscription card; sound-change rule ticker.
- **Config:**
  - `optional`:
    - `seed` — default `null`
    - `starting_vocab` — default `20`
    - `centuries` — default `10`
    - `words_file` — default `"data/language_evolution/roots.json"`
- **Implementation:**
  - Generate root words and apply deterministic sound-change rules each century.
  - Occasionally split a dialect branch.
  - Render tree horizontally with selected word highlighted.
- **Registry snippet:**
  ```json
  "languageevolution": {
    "entrypoint": "modes.language_evolution_mode:LanguageEvolutionMode",
    "type_config": { "starting_vocab": 20, "centuries": 10 },
    "required": [],
    "optional": ["seed", "starting_vocab", "centuries", "words_file"]
  }
  ```

---

### 4.16 Signal Observatory

- **Registry type key:** `signalobservatory`
- **File:** `modes/signal_observatory_mode.py`
- **Summary:** Monitors fictional radio signals. Most are ordinary noise, but occasionally it detects pulsars, spacecraft telemetry, number stations, or unexplained signals.
- **Visual treatment:** Waterfall/spectrum display, frequency dial, decoded text panel, signal class badge.
- **Config:**
  - `optional`:
    - `signal_file` — default `"data/signal_observatory/signals.json"`
    - `bands` — default `["HF", "VHF", "UHF"]`
    - `noise_density` — default `0.9`
    - `signal_chance` — default `0.03`
- **Implementation:**
  - Generate perlin-ish noise columns for the waterfall (simple sine/random mix).
  - Randomly inject signals with metadata; decode text via typewriter effect.
  - No persistence; continuous scan.
- **Registry snippet:**
  ```json
  "signalobservatory": {
    "entrypoint": "modes.signal_observatory_mode:SignalObservatoryMode",
    "type_config": { "bands": ["HF", "VHF", "UHF"], "noise_density": 0.9 },
    "required": [],
    "optional": ["signal_file", "bands", "noise_density", "signal_chance"]
  }
  ```

---

### 4.17 Generative Architecture

- **Registry type key:** `genarchitecture`
- **File:** `modes/gen_architecture_mode.py`
- **Summary:** A floor plan, castle, space station, or megastructure is designed step by step. The screen alternates between blueprints, construction views, and engineering notes.
- **Visual treatment:** Blueprint grid, walls drawn progressively, construction crane silhouette, note annotations.
- **Config:**
  - `optional`:
    - `seed` — default `null`
    - `structure_type` — `"floorplan"`, `"castle"`, `"spacestation"`, `"megastructure"`; default `"floorplan"`
    - `build_speed` — rooms/sections per second; default `0.5`
    - `annotation_interval` — default `3`
- **Implementation:**
  - Procedural generator per structure type; emit rooms/sections in build order.
  - Alternate render modes on a timer: blueprint -> construction -> finished -> next.
- **Registry snippet:**
  ```json
  "genarchitecture": {
    "entrypoint": "modes.gen_architecture_mode:GenArchitectureMode",
    "type_config": { "structure_type": "floorplan", "build_speed": 0.5 },
    "required": [],
    "optional": ["seed", "structure_type", "build_speed", "annotation_interval"]
  }
  ```

---

### 4.18 Autonomous Cartographer

- **Registry type key:** `cartographer`
- **File:** `modes/cartographer_mode.py`
- **Summary:** An unexplored map slowly fills in as simulated survey teams travel across it. Rivers, ruins, roads, settlements, and handwritten annotations appear.
- **Visual treatment:** Parchment background, fog of war, ink strokes revealing terrain, tiny surveyor icons, margin notes.
- **Config:**
  - `optional`:
    - `seed` — default `null`
    - `map_size` — default `[64, 48]`
    - `teams` — default `3`
    - `explore_speed` — tiles per second; default `2.0`
- **Implementation:**
  - Generate terrain grid once per seed.
  - Simulate multiple surveyors with simple goals; reveal tiles in a radius.
  - Periodically add a handwritten annotation near interesting features.
- **Registry snippet:**
  ```json
  "cartographer": {
    "entrypoint": "modes.cartographer_mode:CartographerMode",
    "type_config": { "map_size": [64, 48], "teams": 3, "explore_speed": 2.0 },
    "required": [],
    "optional": ["seed", "map_size", "teams", "explore_speed"]
  }
  ```

---

### 4.19 One-Year Spaceship Voyage

- **Registry type key:** `spaceshipvoyage`
- **File:** `modes/spaceship_voyage_mode.py`
- **Summary:** A persistent spacecraft travels toward a destination in real time. Each day brings navigation updates, crew logs, repairs, scientific observations, and rare emergencies.
- **Visual treatment:** Starfield with ship icon, progress bar, destination info, daily log panel, system status LEDs.
- **Config:**
  - `optional`:
    - `save_file` — default `"data/spaceship_voyage/voyage.json"`
    - `destination` — default `"Kepler-186f"`
    - `voyage_days` — default `365`
    - `start_date` — default `null` (today)
    - `ship_name` — default `"Pilgrim-7"`
- **Implementation:**
  - Compute voyage fraction from real elapsed days.
  - Generate deterministic daily event at midnight.
  - Persist minimal state: start date, last generated day, emergency flags.
- **Registry snippet:**
  ```json
  "spaceshipvoyage": {
    "entrypoint": "modes.spaceship_voyage_mode:SpaceshipVoyageMode",
    "type_config": { "destination": "Kepler-186f", "voyage_days": 365, "ship_name": "Pilgrim-7" },
    "required": [],
    "optional": ["save_file", "destination", "voyage_days", "start_date", "ship_name"]
  }
  ```

---

### 4.20 Library of Imaginary Books

- **Registry type key:** `imaginarylibrary`
- **File:** `modes/imaginary_library_mode.py`
- **Summary:** Each cycle presents a nonexistent book: cover, synopsis, author biography, publication history, review excerpts, and a short passage.
- **Visual treatment:** Book cover on the left, metadata on the right, decorative border, occasional review quote.
- **Config:**
  - `optional`:
    - `book_file` — default `"data/imaginary_library/books.json"`
    - `dwell_seconds` — default `20`
    - `use_generated` — default `false`
- **Implementation:**
  - Load or generate books; render cover as procedural rectangle + title.
  - Cycle with a gentle page-turn wipe.
- **Registry snippet:**
  ```json
  "imaginarylibrary": {
    "entrypoint": "modes.imaginary_library_mode:ImaginaryLibraryMode",
    "type_config": { "dwell_seconds": 20, "use_generated": false },
    "required": [],
    "optional": ["book_file", "dwell_seconds", "use_generated"]
  }
  ```

---

### 4.21 Ambient Biography

- **Registry type key:** `ambientbiography`
- **File:** `modes/ambient_biography_mode.py`
- **Summary:** Follows the entire fictional life of one person, one day at a time—from childhood through old age—using photographs, letters, milestones, and quiet ordinary events.
- **Visual treatment:** Scrapbook page with photo placeholder, date header, event text, small memorabilia icons.
- **Config:**
  - `optional`:
    - `save_file` — default `"data/ambient_biography/life.json"`
    - `lifespan_days` — default `29200` (~80 years)
    - `day_advance_seconds` — real seconds per simulated day; default `5`
    - `biography_file` — default `"data/ambient_biography/templates.json"`
- **Implementation:**
  - Generate life timeline from seed.
  - Advance one simulated day every `day_advance_seconds`.
  - Persist current day so the life resumes across sessions.
- **Registry snippet:**
  ```json
  "ambientbiography": {
    "entrypoint": "modes.ambient_biography_mode:AmbientBiographyMode",
    "type_config": { "lifespan_days": 29200, "day_advance_seconds": 5 },
    "required": [],
    "optional": ["save_file", "lifespan_days", "day_advance_seconds", "biography_file"]
  }
  ```

---

### 4.22 Procedural Cabinet of Curiosities

- **Registry type key:** `cabinetofcuriosities`
- **File:** `modes/cabinet_mode.py`
- **Summary:** The screen contains shelves of unusual objects. The camera periodically focuses on one and reveals its supposed history and provenance.
- **Visual treatment:** Wooden shelves, small object silhouettes, spotlight/zoom on selected object, label card.
- **Config:**
  - `optional`:
    - `object_file` — default `"data/cabinet/objects.json"`
    - `shelf_rows` — default `4`
    - `objects_per_row` — default `6`
    - `focus_interval` — default `12`
- **Implementation:**
  - Generate or load object pool; place on shelves.
  - Periodically pick one, zoom smoothly, show history/provenance.
  - Return to full shelf view afterward.
- **Registry snippet:**
  ```json
  "cabinetofcuriosities": {
    "entrypoint": "modes.cabinet_mode:CabinetMode",
    "type_config": { "shelf_rows": 4, "objects_per_row": 6, "focus_interval": 12 },
    "required": [],
    "optional": ["object_file", "shelf_rows", "objects_per_row", "focus_interval"]
  }
  ```

---

### 4.23 Deep-Time Clock

- **Registry type key:** `deeptimeclock`
- **File:** `modes/deep_time_clock_mode.py`
- **Summary:** Shows events on geological and astronomical timescales: continental drift, species evolution, stellar motion, and what Earth may look like millions of years from now.
- **Visual treatment:** Massive timeline with zoomed-in "now" marker; date display in mega-years; event card.
- **Config:**
  - `optional`:
    - `start_year` — default `-4600000000`
    - `speed` — million years per real second; default `1.0`
    - `event_file` — default `"data/deep_time_clock/events.json"`
    - `save_file` — default `"data/deep_time_clock/now.json"`
- **Implementation:**
  - Advance deep-time year based on real elapsed seconds.
  - Show nearest event and a simple visual (continental outline morphing optional; start with color/label).
  - Persist current year.
- **Registry snippet:**
  ```json
  "deeptimeclock": {
    "entrypoint": "modes.deep_time_clock_mode:DeepTimeClockMode",
    "type_config": { "start_year": -4600000000, "speed": 1.0 },
    "required": [],
    "optional": ["start_year", "speed", "event_file", "save_file"]
  }
  ```

---

### 4.24 Weather-Based Art Generator

- **Registry type key:** `weatherart`
- **File:** `modes/weather_art_mode.py`
- **Summary:** Actual temperature, clouds, wind, sunrise, and precipitation determine the palette, movement, density, and mood of a continuously generated artwork.
- **Visual treatment:** Abstract particle/flow field whose parameters are driven by current weather.
- **Config:**
  - `optional`:
    - `lat` / `lon` — default `null`
    - `weather_api_key` — secret key name; default `"OPENWEATHER_API_KEY"`
    - `fetch_interval_minutes` — default `15`
    - `fallback_mode` — `"synthetic"` or `"last"`; default `"synthetic"`
- **Implementation:**
  - Background thread fetches Open-Meteo or OpenWeather.
  - Map weather vars to particle count, color palette, wind force, gravity.
  - Use synthetic weather if no key or fetch fails.
- **Registry snippet:**
  ```json
  "weatherart": {
    "entrypoint": "modes.weather_art_mode:WeatherArtMode",
    "type_config": { "fetch_interval_minutes": 15, "fallback_mode": "synthetic" },
    "required": [],
    "optional": ["lat", "lon", "weather_api_key", "fetch_interval_minutes", "fallback_mode"]
  }
  ```
- **Secret dependency:** `OPENWEATHER_API_KEY` (optional; synthetic fallback works without it).

---

### 4.25 The Building Is Alive

- **Registry type key:** `buildingalive`
- **File:** `modes/building_alive_mode.py`
- **Summary:** Treats the kiosk host as a fictional organism or spaceship. CPU load becomes metabolism, network activity becomes neural traffic, uptime becomes age, disk usage becomes memory capacity.
- **Visual treatment:** Biomechanical cross-section or ship schematic; pulsing conduits; status readouts labeled as organs/systems.
- **Config:**
  - `optional`:
    - `poll_interval` — seconds; default `2`
    - `use_psutil` — default `true`
    - `organ_map` — mapping of metric -> organ; default provided
    - `theme` — `"organism"` or `"spaceship"`; default `"organism"`
- **Implementation:**
  - Use `psutil` (optional dependency) in a background thread to sample CPU, net, disk, uptime.
  - Map metrics to organ animation rates/colors.
  - If `psutil` unavailable, gracefully degrade to synthetic heartbeat.
- **Registry snippet:**
  ```json
  "buildingalive": {
    "entrypoint": "modes.building_alive_mode:BuildingAliveMode",
    "type_config": { "poll_interval": 2, "use_psutil": true, "theme": "organism" },
    "required": [],
    "optional": ["poll_interval", "use_psutil", "organ_map", "theme"]
  }
  ```
- **Optional dependency:** `psutil` for live system metrics.

---

## 5. Shared data layout

Proposed directory under repo root:

```
data/
  impossible_museum/
    exhibits.json
  slowciv/
    world.json
  dungeon/
    (no persistence by default)
  transit_map/
    (no persistence by default)
  newswire/
    bulletins.json
  machine_archeology/
    fragments.json
  ecosystem/
    world.json
  cosmic_weather/
    bodies.json
  dreaming_computer/
    fragments.json
  world_window/
    scene.json
  mystery_board/
    cases.json
    state.json
  bestiary/
    creatures.json
  infinite_factory/
    products.json
  daybook/
    events.json
  language_evolution/
    roots.json
  signal_observatory/
    signals.json
  gen_architecture/
    (no persistence by default)
  cartographer/
    (no persistence by default)
  spaceship_voyage/
    voyage.json
  imaginary_library/
    books.json
  ambient_biography/
    life.json
  cabinet/
    objects.json
  deep_time_clock/
    events.json
    now.json
  weather_art/
    (cache only)
  building_alive/
    (cache only)
```

Each data file is optional on first run; modes generate minimal fallback content when the file is missing.

## 6. Implementation priority suggestion

Phased order, balancing variety and complexity:

1. **Quick wins (pure procedural, no persistence):**
   - Dreaming Computer
   - Signal Observatory
   - Generative Transit Map
   - Impossible Museum (generated branch)
   - Cosmic Weather Station

2. **Medium complexity (persistent state or structured data):**
   - Slow-Building Civilization
   - World-in-a-Window
   - Infinite Factory
   - Library of Imaginary Books
   - Procedural Dungeon Expedition

3. **Long-running / narrative modes:**
   - One-Year Spaceship Voyage
   - Ambient Biography
   - Unsolved Mystery Board
   - Historical Daybook

4. **Specialty / external-data modes:**
   - Weather-Based Art Generator
   - The Building Is Alive

## 7. Open questions for review

1. Should persistent modes share a single `data/` root, or should each mode keep its save file next to its source file?
2. Do you want real weather support in `weatherart` and `worldwindow`, or should both default to purely synthetic weather to avoid API keys?
3. Should generated content (creatures, books, artifacts) be deterministic from `seed`, or do you want an LLM-driven generator with optional API key?
4. For `buildingalive`, is `psutil` acceptable as an optional dependency, or should it stay stdlib-only?
5. Which three modes should be implemented first in Phase 1?

---

End of design document.

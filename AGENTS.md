# AGENTS.md

pixel_drift is a Raspberry Pi / kiosk-style **mode controller** that runs one of many
visual "modes" (screen-saver style apps) fullscreen and lets the user switch modes
via keyboard or a rotary encoder.

The system is plugin-like:
- **Mode types** are declared in `modes_registry.json` (type -> Python entrypoint + defaults).
- **Mode instances** are declared in `modes_config.json` (mode number -> type + parameters).
- The **controller** (`pixel_drift.py`) loads registry + config, merges settings,
  instantiates the mode class, and runs it in a single pygame shell.

Typical goals in this repo:
- add new modes
- improve stability / memory usage
- unify config schema and validation
- tweak UI overlays (e.g., mode number watermark)
- harden error handling and logging


## Quick start (developer)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python pixel_drift.py --show_modes
python pixel_drift.py --play 1 --windowed
```

Always validate configs after editing them:

```bash
python validate_configs.py --all
```


## Repository map

Core (shared by everything — edit here, not in copies):
- `pixel_drift.py` — the ONE controller entrypoint (all run modes, all inputs)
- `core/config.py` — JSON loading, type normalization, local override merge, secrets
- `core/cache.py` — ResourceCache (shared fonts/images)
- `core/loader.py` — entrypoint import, config validation, mode instantiation
- `core/manager.py` — ModeManager: scene lifecycle, fades, mode-number overlay
- `core/playlist.py` — Playlist: sequential/shuffled rotation (no global state)
- `core/hardware.py` — RotaryHardware: lazy gpiozero wrapper (Pi only)
- `validate_configs.py` — static config validator (run it in CI / before commit)

Modes:
- `modes/<name>_mode.py` — one file per mode type
- `antfarm/` — the ant farm simulation (multi-file mode package)

Config & data:
- `modes_registry.json` — the ONLY registry (there is no "_new" variant)
- `modes_config.json` — canonical instance config
- `modes_config.local.json` — optional per-host override (gitignored)
- `configs/` — alternate variant configs (windows, jetson, narrow, etc.)
- `secrets.json` — API keys (gitignored; see `secrets.example.json`)


## Controller CLI

```
python pixel_drift.py --show_modes          # list configured modes
python pixel_drift.py --play N              # single mode, ESC quits
python pixel_drift.py                       # manual: LEFT/RIGHT switch, ESC quits
python pixel_drift.py --auto 30 [--shuffle] # auto-cycle every N seconds
python pixel_drift.py --input rotary        # Pi rotary encoder (tap=quit, hold=reboot)

Common flags: --windowed --width W --height H --start N --max-modes N
              --config FILE --gc-seconds N
```

Do not break existing flags. If a new flag is added, keep backward compatibility.


## Config schema

### `modes_registry.json`
Top-level object:
- `settings`: optional; `modes_config_file` picks the active instance config
- `types`: dict keyed by **normalized** type string (lowercase, no spaces/underscores)
- Each type entry:
  - `entrypoint`: `"package.module:ClassName"`
  - optional `type_config`: defaults merged under every instance
  - optional `required`: list of required config keys
  - optional `optional`: list of known optional config keys (used by the validator
    to catch typos — keep it in sync with what the mode actually reads)

### `modes_config.json`
Top-level object with a `modes` key:
```json
{
  "modes": {
    "1": { "type": "slideshow", "folder": "/path/to/images", "duration": 12 }
  }
}
```

### `modes_config.local.json` (gitignored)
Same shape. Shallow-merged per mode number on top of `modes_config.json`.
Use it for per-host paths (image folders, device names) so the versioned
config stays portable. See `modes_config.local.example.json`.

Merge order for a mode's effective config:
`registry type_config` -> `modes_config.json` instance -> `modes_config.local.json` instance


## Mode interface contract (important)

Each mode class must:
- accept a config dict: `__init__(self, config: dict)`
- `enter(manager)` — called once when the mode becomes active
- `exit()` — release references (surfaces, threads) so GC can reclaim
- `handle_event(event)`, `update(dt)`, `render(screen)`

The controller owns the display. Modes never call `pygame.display.set_mode`.
Modes access shared resources via `manager.screen` and `manager.cache`
(fonts/images), and `manager.width` / `manager.height`.

Threading rules:
- Never do network I/O on the frame loop. Use a background thread and have
  `update`/`render` read cached results (see `slideshow_mode` and
  `headlines_news_mode` for the pattern).
- Stop and join mode threads in `exit()`.


## Logging & errors

Kiosk-friendly logging:
- use `print()` with stable prefixes (e.g., `[Mode]`, `[Controller]`)
- never spam per-frame logs
- on exceptions: log once, then either retry or exit cleanly


## Security & secrets (MUST follow)

- **Never commit API keys** in JSON files.
- Secrets come from `secrets.json` (gitignored) or environment variables
  (e.g., `OPENAI_API_KEY`). The controller injects them into mode configs
  automatically when the config declares the key (see `core/loader.py`).
- If you see keys in `modes_registry.json` / `modes_config.json`, treat them
  as placeholders and refactor.


## Development checklist for new modes

1) create `modes/<name>_mode.py` implementing the interface contract
2) add a type entry to `modes_registry.json` (with `required`/`optional` key lists)
3) add at least one instance entry to `modes_config.json`
4) run `python validate_configs.py --all`
5) test via `python pixel_drift.py --play N --windowed`

Keep image / media paths configurable and never hardcode absolute paths in code.

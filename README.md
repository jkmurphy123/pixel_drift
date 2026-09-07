# pixel_drift

A screen saver / slideshow tool with plugin modules, built for Raspberry Pi
kiosks but runnable anywhere pygame runs.

One controller (`pixel_drift.py`), one registry (`modes_registry.json`), one
config (`modes_config.json`), 45 visual modes.

## Usage

```bash
pip install -r requirements.txt

python pixel_drift.py --show_modes          # list configured modes
python pixel_drift.py --play 1 --windowed   # run one mode in a window
python pixel_drift.py --auto 30             # auto-cycle every 30s, fullscreen
python pixel_drift.py --input rotary        # Raspberry Pi rotary encoder
```

Keys: LEFT/RIGHT switch modes, ESC quits.

## Configuration

- `modes_registry.json` — mode *types* (entrypoints + defaults)
- `modes_config.json` — mode *instances* (what actually plays)
- `modes_config.local.json` — optional per-host overrides (gitignored)
- `secrets.json` — API keys (gitignored, see `secrets.example.json`)
- `configs/` — alternate configs for other machines/displays

Validate everything after editing:

```bash
python validate_configs.py --all
```

See AGENTS.md for the full developer guide.

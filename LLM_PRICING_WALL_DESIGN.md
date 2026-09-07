# LLM PRICING WALL — Design Document

Status: IMPLEMENTED
Date: 2026-08-17

## 1. Concept

A pixel_drift mode that displays a wall of panels, one per AI API provider, showing
the provider's current model lineup, per-token input/output pricing, and a short
use-case hint. The goal is a quick at-a-glance reference for choosing a Hermes
model provider/ model by task and cost.

The display is **offline-first**: all prices live in a local JSON file that the
mode renders directly. A separate refresh script can update that file when the
network is available; if it can't find a price, the old value stays in place and
the user can edit the file by hand.

## 2. Fit with pixel_drift architecture

- New mode file: `modes/llm_pricing_wall_mode.py`, class `LLMPricingWallMode`.
- Registry type name (normalized): `llmpricingwall`
  -> entrypoint `modes.llm_pricing_wall_mode:LLMPricingWallMode`.
- Data file: `data/llm_pricing.json` (tracked in git with starter prices).
- Refresh script: `scripts/refresh_llm_pricing.py` (run manually or via cron).
- Instance config in `modes_config.json` points at the data file and theme knobs.
- No network I/O inside the mode; no threads.
- `python validate_configs.py --all` must still pass 0/0 after edits.

## 3. Mode configuration (`modes_config.json`)

```json
{
  "modes": {
    "31": {
      "type": "llmpricingwall",
      "title": "LLM API PRICING DASHBOARD",
      "subtitle": "per-million-token input / output prices in USD",
      "data_file": "data/llm_pricing.json",
      "accent_rgb": [100, 220, 180],
      "columns_portrait": 1,
      "columns_landscape": 2,
      "panel_spacing_scale": 0.025,
      "scanline_alpha": 0,
      "noise_alpha": 0,
      "vignette_strength": 0.15,
      "seed": 20260817
    }
  }
}
```

Keys:

| key                 | required | default                         | meaning                                      |
|---------------------|----------|---------------------------------|----------------------------------------------|
| data_file           | no       | `data/llm_pricing.json`         | path to the provider/model price JSON        |
| title               | no       | `LLM API PRICING DASHBOARD`     | header title                                 |
| subtitle            | no       | `per-million-token input/output`| header subtitle                              |
| accent_rgb          | no       | `[100, 220, 180]`               | panel border / provider accent color         |
| columns_portrait    | no       | `1`                             | provider columns when h > w                  |
| columns_landscape   | no       | `2`                             | provider columns when w >= h                 |
| panel_spacing_scale | no       | `0.025`                         | gap between panels as fraction of min(w,h)   |
| scanline_alpha      | no       | `0`                             | CRT scanline overlay alpha                   |
| noise_alpha         | no       | `0`                             | CRT noise overlay alpha                      |
| vignette_strength   | no       | `0.15`                          | screen-edge vignette (0.0–1.0)               |
| seed                | no       | random                          | deterministic "alive" micro-animations       |

`data_file` is the only required-ish key, but it has a default so the registry
will list it as optional. All keys are declared in `modes_registry.json` so the
validator catches typos.

## 4. Data file schema (`data/llm_pricing.json`)

```json
{
  "meta": {
    "currency": "USD",
    "unit": "per 1M tokens",
    "last_updated": "2026-08-17T00:00:00Z",
    "source_note": "starter set from public pricing pages; verify before use",
    "refresh_interval_days": 7
  },
  "recommendations": {
    "title": "RECOMMENDED VALUE MODELS",
    "accent_rgb": [255, 200, 100],
    "categories": [
      {
        "name": "Coding",
        "model": "GPT-4o mini",
        "provider": "OpenAI",
        "input": 0.15,
        "output": 0.60,
        "why": "fast and cheap for everyday code edits and small features"
      }
    ]
  },
  "providers": [
    ...
  ]
}
```

### 4.1 Meta

- `meta.currency`: always "USD" for v1.
- `meta.unit`: always "per 1M tokens" for v1.
- `meta.last_updated`: ISO-8601 UTC timestamp; shown in the footer.
- `meta.source_note`: optional provenance note.
- `meta.refresh_interval_days`: optional hint to the refresh script.

### 4.2 Recommendations (optional)

- `recommendations.title`: panel header text.
- `recommendations.accent_rgb`: optional panel accent color; falls back to a
  warm gold if omitted.
- `recommendations.categories`: ordered list of value picks.
  - `name`: short category label (e.g., "Coding", "Deep reasoning", "General purpose").
  - `model`: recommended model display name.
  - `provider`: provider display name.
  - `input` / `output`: prices (same rules as provider models).
  - `why`: one-sentence rationale.

The recommendation panel is rendered as the first panel in the grid so it is
visible immediately. If `recommendations` is omitted, the wall shows only
provider panels.

### 4.3 Providers

- `providers` is ordered; the mode renders panels in this order (after the
  recommendation panel, if present).
- `provider.slug`: lowercase identifier, used for stable panel coloring if no
  `accent_rgb` is supplied.
- `provider.accent_rgb`: optional per-provider color; falls back to the mode's
  global `accent_rgb`.
- `model.input` / `model.output`: float prices. `null` means "price unknown".
- `model.use_case`: one short sentence (recommended max ~80 chars; the renderer
  will wrap).
- Extra keys (e.g., `cached_input`) are preserved by the refresh script and can
  be referenced in `use_case` for now.

The file is plain JSON so it can be edited by hand, version-controlled, and
diffed.

## 5. Visual design

The layout borrows from `network_status_wall_mode`:

- Full-screen dark background.
- Header band: title, subtitle, last-updated timestamp, currency/unit note.
- Footer band: hint text (e.g., "prices are per 1M tokens — verify before use").
- Responsive grid of panels.
- The first panel is the optional **recommendations panel** (warm gold accent by
  default), listing the best value picks for Coding, Deep reasoning, and General
  purpose.
- Remaining panels are provider panels.
- Each provider panel:
  - Provider name in a large accent font.
  - A table-like list of models:
    - model name (left)
    - input price (right)
    - output price (right, dimmer)
    - use-case line below (small, dim).
  - Micro-animation: the price dots/bars gently pulse so the wall feels alive
    without changing the data.

Responsive rules:

- Landscape (w >= h): `columns_landscape` columns of provider panels.
- Portrait (h > w): `columns_portrait` columns.
- If a provider has more models than fit in its panel, the model list scrolls
  vertically inside that panel at a slow, readable speed (decision D3).
- If all providers don't fit horizontally, panels tile left-to-right,
  top-to-bottom; no horizontal scrolling.

## 6. Refresh script (`scripts/refresh_llm_pricing.py`)

A standalone, no-mode Python script that updates `data/llm_pricing.json`.

Behavior:

- Reads the existing `data/llm_pricing.json`.
- Fetches current per-token pricing from OpenRouter's API and converts it to
  per-1M-token prices.
- Prints a diff of what would change. **By default it does not write the file**
  so you can review first; pass `--apply` to update.
- If a fetch fails or a price can't be parsed, the existing value is preserved
  and a warning is printed.
- Updates `meta.last_updated` only if at least one price changed and `--apply`
  is used.
- Writes the JSON back with stable key ordering and 2-space indentation.
- Safe to run manually or from cron.

CLI:

```bash
python scripts/refresh_llm_pricing.py           # dry-run: print diff, don't write
python scripts/refresh_llm_pricing.py --apply   # apply fetched prices
python scripts/refresh_llm_pricing.py --data-file data/llm_pricing.json --apply
```

Because OpenRouter prices include router markup and may differ from provider-
direct pricing, the default dry-run behavior lets you inspect before updating.
The mode itself never depends on the script.

## 7. Cron / weekly refresh

The repository will not install a cron job automatically, but a suggested line
is documented in the script's docstring:

```cron
# refresh LLM pricing every Monday at 03:00 (review diffs periodically)
0 3 * * 1 cd /home/ubuntu/ai_projects/pixel_drift && .venv/bin/python scripts/refresh_llm_pricing.py --apply
```

If the user wants, I can also create a Hermes cron job via `cronjob` after the
mode is implemented; that is out of scope for the mode itself.

## 8. Decisions (locked)

1. **Mode name**: `llmpricingwall` / `LLMPricingWallMode`.
2. **Initial provider set**: OpenAI, Google Gemini, DeepSeek, Moonshot Kimi,
   Anthropic, xAI, Groq.
3. **Scroll long model lists inside panels**: yes.
4. **Fetch strategy for refresh script**: simple HTTP GET to OpenRouter API;
   dry-run by default; file remains hand-editable.
5. **Recommendation panel**: rendered as the first panel in the grid, sourced
   from `data/llm_pricing.json` under the `recommendations` key. It is
   independent of the provider list and can be edited by hand.

# CONTROL_PANEL_DESIGN.md

Design proposal for a new pixel_drift mode: **control_panel** — an old-fashioned,
make-believe control panel / console. Rows of gauges, switches, lamps, knobs,
oscilloscopes and readouts, all animating on their own. No user input; it is a
pure kiosk "living machine" display.

Status: DRAFT — reviewed, decisions locked (see section 10). No code written yet.

---

## 1. Goals

- Visually rich "wall of machinery" that is always doing something: needles
  wander, scopes trace waveforms, lamps blink, counters roll.
- **Layout is data, not code.** A JSON layout file defines panels and which
  controls sit where. Users can author their own consoles without touching
  Python.
- **Skinnable.** All static artwork comes from a sprite sheet. Every skin
  uses the *identical* to-the-pixel sprite layout, so swapping sheets re-themes
  every layout instantly (the buildscape tileset pattern).
- **Cheap to animate.** Sprites are static backgrounds; animation is simple
  primitives (lines, arcs, rects, dots) drawn on top each frame.
- Fits the pixel_drift mode contract and config conventions exactly.

Non-goals (v1): no interactivity, no sound, no per-pixel shader effects, no
network data feeds (a later variant could wire signals to real data).

---

## 2. Core concepts

### 2.1 The cell grid

Everything is measured in **cells** of 128x128 px. All sprite and control
footprints are whole multiples of one cell, so panels tile the screen with no
gaps or overlaps.

Design resolution: **1920x1080** -> 15 columns x 8 rows of cells
(1080 / 128 = 8.4375, so 8 full rows; handling of the leftover 56 px is
described in 2.4).

### 2.2 Allowed footprints (size classes)

A limited, fixed whitelist keeps layout validation simple:

| Name   | Cells (w x h) | Pixels    | Typical use                    |
|--------|---------------|-----------|--------------------------------|
| `1x1`  | 1 x 1         | 128x128   | button, lamp, small gauge, knob|
| `2x1`  | 2 x 1         | 256x128   | horizontal meter, label plate  |
| `1x2`  | 1 x 2         | 128x256   | vertical meter, switch bank    |
| `2x2`  | 2 x 2         | 256x256   | large round gauge, nixie pair  |
| `3x2`  | 3 x 2         | 384x256   | wide gauge cluster             |
| `4x1`  | 4 x 1         | 512x128   | LED bar, digital readout strip |
| `4x2`  | 4 x 2         | 512x256   | horizontal oscilloscope        |
| `2x4`  | 2 x 4         | 256x512   | vertical oscilloscope          |
| `4x4`  | 4 x 4         | 512x512   | master gauge / radar / big dial|

(The whitelist lives in one constant; adding a size later is a one-line change
plus new sprite slots.)

### 2.3 Sprites and sprite sheets

- One PNG sheet per skin. Canonical sheet size: **2048x2048** = 16x16 cells
  = 256 cell slots. Every sprite occupies a fixed rectangle of cells on that
  grid, identical across all skins.
- Each sprite has a stable string ID and footprint, e.g.:
  - `GAUGE_ROUND_SMALL` (1x1), `GAUGE_ROUND_LARGE` (2x2)
  - `METER_VU_H` (2x1), `METER_VU_V` (1x2)
  - `SCOPE_H` (4x2), `SCOPE_V` (2x4)
  - `PUSH_BUTTON`, `TOGGLE_SWITCH`, `ROTARY_KNOB`, `LED_LAMP` (all 1x1)
  - `READOUT_DIGITAL` (4x1), `PANEL_PLATE` (1x1, decorative filler), ...
- A **skin manifest** (`skin.json`, buildscape-style) sits next to the PNG and
  declares just `name`, `image`, and `background_rgb`. The sprite geometry
  lives in the shared, skin-independent `assets/control_panel/sprite_defs.json`
  (implemented in phase 1): identical to-the-pixel layout across skins is
  guaranteed *by construction* rather than by diffing manifests.
- Sprite IDs are fixed forever once published (like buildscape tile IDs).
  New controls get new IDs appended to empty sheet regions.

### 2.4 Rendering & scaling

- The whole console is composed onto one offscreen **canvas surface** at
  design resolution (1920x1080), then scaled once per frame to the actual
  screen with `pygame.transform.smoothscale` if resolutions differ (decision
  D2). This makes the mode resolution-independent for free (1366x768 laptop,
  4K TV, --windowed dev runs) and matches the "single pygame shell owns the
  display" contract.
- The 56 px vertical remainder at 1080p: the 8-row cell area (1024 px) is
  centered, giving a 28 px letterbox band top and bottom, painted with the
  skin's background color. Optional later: a "header strip" control type that
  lives in the margin.
- Two-layer redraw:
  1. **Static layer** — panel plates, control sprite backgrounds, decorative
     frames — composed once per mode entry (or skin/layout change) onto a
     cached surface.
  2. **Dynamic layer** — each control draws its animated primitives (needle
     line, scope trace, lamp glow) on top of the blitted static layer.
  No per-frame recomposition of bitmaps; CPU cost is a handful of line draws
  per control. No dirty-rect tracking needed at this scale.

---

## 3. Controls: taxonomy and OOP design

### 3.1 Signals (composition, not inheritance)

Every animated control is driven by one or more **Signal** objects that
produce a normalized float (usually 0.0–1.0, scopes use -1.0–1.0) as a
function of time. Signals are where the "life" comes from, and they are shared
across control types:

```
Signal (base)
├── SineSignal(freq, phase, amplitude, offset)
├── RandomWalkSignal(step_rate, smoothing, min, max)   # gauge drift
├── StepSignal(hold_range, values)                     # jumps, then holds
├── SquareSignal(freq, duty)                           # lamp blink
├── PulseTrainSignal(rate, jitter)                     # activity LEDs
├── NoiseSignal(rate)                                  # static / flicker
└── CompositeSignal(op, children)                      # sum, multiply, min/max
```

Benefits: a gauge, a bar graph, and a VU meter can all drink from the same
`RandomWalkSignal` recipe; a scope combines two sines for Lissajous; behavior
variety comes from config, not new classes. Each control instance gets its own
signal instances with randomized phase/seed so the panel never moves in
lockstep.

### 3.2 Control class hierarchy

```
Control (base)
│   rect (cells), sprite_id, signals[]
│   enter(), exit(), update(dt), draw_overlay(surface)
│
├── NeedleControl            # one or more needles pivoted on a dial
│   ├── GaugeControl         # round gauge: rotating needle line + hub dot
│   ├── MeterControl         # VU/edgewise meter: shorter sweep, colored arc
│   └── CompassControl       # 360° free-rotating needle
│
├── TraceControl             # waveform history buffer, drawn as polyline
│   ├── ScopeControl         # classic oscilloscope (H or V orientation)
│   └── StripChartControl    # slow scrolling pen-recorder
│
├── BarControl               # filled/segmented bar, H or V
│   ├── BarGraphControl
│   └── LedBarControl        # discrete LED segments w/ threshold colors
│
├── LampControl              # blinking indicator (glow circle/rect overlay)
│   ├── IndicatorLamp          # glow circle/rect primitive overlay (D3)
│   └── WarningLamp            # two-state + occasional "alarm" flash pattern
│
├── MultiLampControl         # N lamps in one sprite (LED matrix / bank)
│
├── KeypadControl            # 3x4 key grid; random "keypresses" (D5)
│                            # overlay: key highlight square + entry readout
│                            # line that types itself and clears
│
├── StateControl             # discrete positions, overlay indicator
│   ├── ToggleSwitchControl  # 2–3 positions, lever line
│   ├── RotaryKnobControl    # pointer tick rotates to detents
│   └── SelectorSwitchControl
│
├── ReadoutControl           # drawn numerals over a sprite window
│   ├── DigitalReadoutControl  # 7-seg segment primitives, value from signal (D4)
│   ├── CounterControl         # odometer-style rolling digits (7-seg too)
│   └── TextTickerControl      # short status strings cycling (pygame font)
│
├── ReelControl              # rotating tape-reel spokes / fan blades
│
└── PlateControl             # purely decorative sprite, no animation
```

`draw_overlay` is the only per-frame hook; everything drawn with
`pygame.draw` / `gfxdraw` primitives in a configurable accent color scheme.

### 3.3 Control catalog (initial set)

| Type key          | Sprite example       | Footprint | Animation                        |
|-------------------|----------------------|-----------|----------------------------------|
| `gauge_round`     | GAUGE_ROUND_SMALL/LARGE | 1x1 / 2x2 | needle on random-walk, occasional "kick" |
| `meter_vu`        | METER_VU_H / _V      | 2x1 / 1x2 | damped needle, green/yellow/red arc |
| `scope`           | SCOPE_H / SCOPE_V    | 4x2 / 2x4 | sine/Lissajous/noise trace, slow sweep |
| `strip_chart`     | STRIP_CHART          | 4x2       | scrolling pen line               |
| `bar_graph`       | BAR_GRAPH_V / _H     | 1x2 / 2x1 | smooth fill bar                  |
| `led_bar`         | LED_BAR              | 4x1       | segmented, threshold colors      |
| `lamp`            | LED_LAMP             | 1x1       | blink patterns, rare alarm burst |
| `lamp_bank`       | LAMP_BANK            | 2x1       | N lamps, chaser/random patterns  |
| `led_matrix`      | LED_MATRIX           | 2x2       | scrolling dots / random bitmap   |
| `push_button`     | PUSH_BUTTON          | 1x1       | occasionally "presses" itself    |
| `keypad`          | KEYPAD               | 2x2       | self-typing keypresses + entry line |
| `toggle_switch`   | TOGGLE_SWITCH        | 1x1       | flips state at random intervals  |
| `rotary_knob`     | ROTARY_KNOB          | 1x1       | pointer eases between detents    |
| `digital_readout` | READOUT_DIGITAL      | 4x1       | 7-seg primitives tied to a signal |
| `counter`         | COUNTER              | 2x1       | odometer digits roll up          |
| `nixie`           | NIXIE_PAIR           | 2x2       | warm-glow digits, ghosting flicker |
| `tape_reel`       | TAPE_REEL            | 2x2       | two reels counter-rotate         |
| `radar`           | RADAR_ROUND          | 4x4       | rotating sweep + fading blips    |
| `clock`           | CLOCK_FACE           | 2x2       | real or fast-forward hands       |
| `plate`           | PANEL_PLATE          | any       | static filler / label            |

This gives ~21 control types from ~9 behavioral base classes.

---

## 4. Layout file format

Two layout modes, selected by the `"mode"` key (decision D6):

- **`"grid"`** (default) — the original slot approach: panels + controls in
  128px cells on the 15x8 design grid, sprites from the skin.
- **`"freeform"`** — for complete control-panel artwork: a full-screen
  `background_image` plus controls at precise pixel coordinates, sized with
  `"size": [w, h]` or `"scale"` (multiplier on the sprite's natural
  footprint). No skin sprites are blitted; controls draw only their
  animation overlays on top of the art. All anchors (`pivot`, `center`,
  `window`) are fractions of the control rect, so every control type works
  unchanged in both modes. `design_resolution` should match the image
  (default 1920x1080); the compositor smoothscales to the screen as usual.

### 4a. Grid layouts

Placement is **explicit only**: every control must give `at: [col, row]`
(decision D1 — no auto-packing in v1).

```json
{
  "name": "reactor_console",
  "design_resolution": [1920, 1080],
  "background_rgb": [18, 20, 24],
  "panels": [
    {"id": "left",   "origin": [0, 0],  "size": [5, 8], "plate": "PANEL_DARK"},
    {"id": "center", "origin": [5, 0],  "size": [6, 8], "plate": "PANEL_DARK"},
    {"id": "right",  "origin": [11, 0], "size": [4, 8], "plate": "PANEL_LIGHT"}
  ],
  "controls": [
    {"type": "gauge_round", "panel": "left", "at": [1, 0],
     "signal": {"kind": "random_walk", "period": 6.0}},

    {"type": "scope", "panel": "center", "at": [1, 1],
     "wave": {"kind": "lissajous", "freq_a": 0.7, "freq_b": 1.1},
     "trace_rgb": [80, 255, 120]},

    {"type": "lamp_bank", "panel": "right", "at": [1, 2],
     "lamps": 4, "pattern": "chaser", "rate": 2.0},

    {"type": "plate", "panel": "right", "sprite": "PANEL_PLATE"}
  ]
}
```

Notes:
- Any key omitted from a control falls back to that control type's defaults
  (defined in code, documented in the layout schema).
- Colors: the generic `"color": [r, g, b]` key recolors any control's drawn
  overlay. Resolution order is `"color"` -> the type-specific key
  (`"needle_rgb"`, `"trace_rgb"`, `"color_rgb"`, ...) -> the control's
  built-in default. On `meter_vu` an explicit color also disables the
  automatic green->amber->red threshold coloring.
- Gauges: needle thickness scales with the control's size
  (~2.8% of the smaller dimension, min 4px); override with
  `"needle_width"` (px).
- Panels may overlap in the file but validation warns; controls must fit
  inside their panel; panels must fit inside the 15x8 design grid.
- A `"seed"` key (layout- or mode-level) makes the random choreography
  reproducible; default is a fresh seed each run for variety.
- Layout files live in `assets/control_panel/layouts/`. The mode config
  points at one by filename.

### 4b. Freeform layouts

```json
{
  "name": "freeform_demo",
  "mode": "freeform",
  "design_resolution": [1600, 900],
  "background_image": "freeform_demo.png",
  "controls": [
    {"type": "gauge_round", "at": [545, 105], "size": [190, 190],
     "pivot": [0.5, 0.5], "sweep_deg": 240},
    {"type": "lamp", "at": [565, 445], "scale": 0.55},
    {"type": "scope", "at": [1150, 105], "size": [380, 190],
     "window": [0.07, 0.12, 0.86, 0.76]}
  ]
}
```

- `background_image` resolves bare names under
  `assets/control_panel/backgrounds/`; absolute paths allowed (per-host
  overrides via `modes_config.local.json` still work).
- `at` is the top-left pixel of the control's rect. `"size"` is explicit
  pixels; `"scale"` multiplies the sprite's natural footprint (so `scale`
  on a 1x1 default sprite is 128px units — use `"size"` when in doubt).
- Validation errors on off-canvas rects and missing images; overlaps are
  allowed (only the author knows where the printed dials are).
- The skin config key is ignored in freeform mode.
- `scripts/make_freeform_demo.py` regenerates the demo background + layout
  from one shared spec so art and overlays can't drift apart — the
  recommended pattern when producing art programmatically.

---

## 5. File layout

Following the `antfarm/` precedent of a multi-file mode package:

```
modes/control_panel_mode.py      # thin pixel_drift mode wrapper (the contract)
controlpanel/
    __init__.py
    geometry.py                  # cell math, footprint whitelist, rect helpers
    skin.py                      # skin manifest load + sprite extraction/caching
    signals.py                   # Signal classes
    layout.py                    # layout file load + validation (explicit placement)
    compositor.py                # static-layer composition + canvas scaling
    seven_seg.py                 # 7-seg digit drawing primitives (D4)
    registry.py                  # control type key -> class + footprint check
    controls/
        __init__.py
        base.py                  # Control base
        needles.py               # Gauge/Meter/Compass
        traces.py                # Scope/StripChart
        bars.py                  # BarGraph/LedBar
        lamps.py                 # Lamp/Warning/MultiLamp/LedMatrix
        stateful.py              # Toggle/Knob/Selector/PushButton
        readouts.py              # Digital/Counter/Nixie/Ticker
        reels.py                 # TapeReel/Radar/Clock
assets/control_panel/
    skins/
        placeholder/skin.json + sheet.png
        <future skins>/
    layouts/
        demo_console.json
scripts/
    make_placeholder_skin.py     # generates flat-color labeled test sheet
tests/
    test_control_panel.py        # layout validation, packing, skin geometry,
                                 # headless smoke render (SDL_VIDEODRIVER=dummy)
```

The mode wrapper keeps the pixel_drift contract:
`__init__(config)`, `enter(manager)`, `exit()` (drop all surfaces), 
`handle_event`, `update(dt)`, `render(screen)`. It holds the compositor and
the control list; all heavy lifting lives in the package.

---

## 6. pixel_drift integration

### `modes_registry.json` entry

```json
"controlpanel": {
  "entrypoint": "modes.control_panel_mode:ControlPanelMode",
  "required": ["layout_file"],
  "optional": [
    "skin",
    "seed",
    "accent_rgb",
    "trace_rgb",
    "lamp_rgb",
    "overlay_alpha",
    "fps_cap"
  ]
}
```

### `modes_config.json` instance example

```json
"37": {
  "type": "controlpanel",
  "layout_file": "demo_console.json",
  "skin": "placeholder"
}
```

- `layout_file` / `skin` are names resolved under `assets/control_panel/`;
  absolute paths also accepted (per-host overrides via
  `modes_config.local.json` stay possible).
- `validate_configs.py --all` must keep passing; layout/skin file validation
  happens at mode load with clear one-line `[ControlPanel]` errors, plus
  unit tests cover the validators. (Option: add a `--check-assets` flag to
  the validator later — not required for v1.)

---

## 7. Skin/sprite-sheet details

### Canonical sheet plan (2048x2048, 16x16 cells)

Sprites are packed by footprint: large ones along the top rows, 1x1 controls
filling the bottom rows. The exact map is fixed in
`assets/control_panel/skins/placeholder/skin.json` and becomes the
published geometry every skin must match. Roughly:

- rows 0–1: SCOPE_H x2, SCOPE_V x2 (4x2 / 2x4 blocks along edges)
- rows 2–5: GAUGE_ROUND_LARGE x2, RADAR_ROUND, NIXIE_PAIR, TAPE_REEL,
  CLOCK_FACE, KEYPAD (2x2)
- rows 6–7: METER_VU_H, STRIP_CHART, READOUT_DIGITAL, LED_BAR (4x1/2x1 strip)
- rows 8–9: GAUGE_ROUND_SMALL row, BAR_GRAPH_V column, METER_VU_V column
- rows 10–15: the 1x1 army: PUSH_BUTTON x2, TOGGLE_SWITCH x2, ROTARY_KNOB x2,
  LED_LAMP x4 colors, LED_MATRIX, PANEL_PLATE x4 variants, LABEL_PLATEs...

Only ~60% of the sheet is allocated at first, leaving headroom for new
controls without moving existing sprites.

### Placeholder skin

`scripts/make_placeholder_skin.py` generates `sheet.png` with flat dark-gray
plates, a thin border, the sprite ID printed in the corner, and a marker dot
at each control's animation anchor (gauge pivot, lamp center). This lets all
code be built and reviewed before any real art exists — then real skins drop
in with zero code changes.

### Animation anchors

Each sprite entry may declare anchor metadata (in **fractions of the sprite
rect**, so it survives footprint reuse):
`"pivot": [0.5, 0.62]` for gauge needle origin, `"lamps": [[0.25,0.5], ...]`
for lamp banks, `"window": [0.08, 0.2, 0.84, 0.6]` for scope/readout drawing
areas. Because sheet geometry is fixed, these anchors live in a shared
`sprite_defs.json` (skin-independent), not per-skin.

---

## 8. Behavior/choreography notes

- Every control gets a randomized phase offset and slight rate jitter at
  `enter()` so the panel feels organic, not synchronized.
- Gauges: random-walk with per-gauge "temperament" (some sleepy, some busy);
  rare scripted events (all gauges kick at once) every 30–90 s for delight.
- Lamps: mixed periods and duties; one or two warning lamps flash an
  attention pattern every so often, then calm down.
- Scopes: alternate waveforms slowly (sine -> Lissajous -> noise bursts).
- Keypads: every few seconds a random key "presses" (highlight square fades),
  appending a digit to the entry line; when the line fills it holds, blinks
  once (accepted) or flashes red (rejected), clears, and starts over.
- Readouts: counters increment at varied rates; digital readouts track a
  signal so a nearby gauge and readout can be *visibly correlated* if the
  layout gives them the same signal spec with the same seed — a nice "the
  machine makes sense" touch.

---

## 9. Implementation phases

1. **Skeleton** ✅ DONE — mode wrapper, geometry, skin loader, placeholder-skin
   generator script, compositor blitting a static layout. Validate + smoke
   test headless.
2. **Signals + first controls** ✅ DONE — signals module; `gauge_round`,
   `lamp`, `scope` end-to-end with overlay animation.
3. **Layout engine** ✅ DONE (built during phase 1) — panels, explicit
   placement, validation errors, full layout-file schema.
4. **Remaining controls** ✅ DONE — all catalog types animated
   (needles/traces/bars, lamps/stateful/keypad, readouts/reels); only
   `plate` is static by design.
5. **Polish** — choreography events, correlated signals, docs
   (authoring-your-own-layout README section), performance check at 60 fps,
   real skin pass.

Each phase ends green on `python validate_configs.py --all` and a headless
`pytest tests/test_control_panel.py`.

---

## 10. Decisions (locked after review)

- **D1 — Placement**: explicit `at: [col, row]` only for v1. No flow/auto
  packing. (Revisit later if hand-placing controls proves tedious.)
- **D2 — Scaling**: compose at 1920x1080 design resolution, `smoothscale`
  the canvas to the actual screen each frame.
- **D3 — Lit states**: lamps/glows are primitive-drawn overlays (circles,
  rects, alpha pulses). No "lit" alternate sprites required from skins.
  (Can be added later as an optional per-sprite extra without breaking
  skins that don't provide them.)
- **D4 — Digital numerals**: 7-seg digits drawn as segment primitives
  (shared `seven_seg.py` helper used by digital readouts, counters, and the
  keypad entry line). Pygame font only for the text ticker.
- **D5 — Catalog additions**: keypad added (`keypad`, KEYPAD sprite, 2x2
  footprint, self-typing keypress animation).
- **D6 — Two layout modes**: `"grid"` (default, original 128px slots) and
  `"freeform"` (full background image + pixel-precise `at`/`size`/`scale`
  placement, overlays only). Selected per layout file via the `"mode"` key.

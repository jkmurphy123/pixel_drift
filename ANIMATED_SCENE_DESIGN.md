# ANIMATED SCENE MODE — Design Document

Status: APPROVED 2026-08-02 — all review questions resolved (section 10).
Date: 2026-08-02

## 1. Concept

A parallax "animated scene" mode inspired by old-school multi-plane cel
animation. A scene is a stack of 5 PNG layers drawn back-to-front. Each layer
moves according to a named motion type (slide, bob, sway, random drift, ...).
How FAR a layer moves is not stored in the scene file — it is computed by the
mode from the layer's depth index, so the back layer barely moves and the
front layer moves the most. That single rule is what produces the 3D parallax
feel, and it stays consistent across every scene.

Everything that varies per scene (images, positions, motion types) lives in a
JSON scene file, so new scenes and new artwork are added without touching
code.

Example target scene — "ship tossing on ocean waves":
  layer 0 (back) : night sky         motion: static
  layer 1        : distant waves     motion: slide_right (tiny amplitude)
  layer 2        : the boat          motion: bob (up/down, medium)
  layer 3        : mid waves         motion: slide_left
  layer 4 (front): near waves        motion: slide_right (largest amplitude)

## 2. Fit with pixel_drift architecture

Follows the existing mode contract exactly (see AGENTS.md):

- New file: `modes/animated_scene_mode.py`, class `AnimatedSceneMode`.
- Registry type name (normalized, lowercase, no separators): `animatedscene`
  -> entrypoint `modes.animated_scene_mode:AnimatedSceneMode`.
- Instance entries added to `modes_config.json` as usual; per-host image
  paths go in `modes_config.local.json`.
- `python validate_configs.py --all` must still pass 0/0 after the registry
  and config edits.
- No threads, no network. Pure local image loading + math on the frame loop.
  All images are loaded once in `enter()` and released in `exit()`.
- Images are loaded via `manager.cache.get_image(path, convert_alpha=True)`
  so repeated scenes don't re-read PNGs from disk.

## 3. Configuration layout (two files)

### 3.1 Mode instance config (`modes_config.json`)

The instance config is deliberately small — it points at the scene file and
sets global playback behavior:

```json
{
  "modes": {
    "9": {
      "type": "animatedscene",
      "scenes_file": "animated_scenes.json",
      "image_folder": "/path/to/parallax_art",
      "scene_duration": 60,
      "shuffle": true
    }
  }
}
```

Keys:

| key             | required | default        | meaning                                  |
|-----------------|----------|----------------|------------------------------------------|
| scenes_file     | yes      | —              | path to the scene definitions JSON       |
| image_folder    | yes      | —              | base folder for all layer PNGs           |
| scene_duration  | no       | 45             | seconds per scene before switching       |
| shuffle         | no       | true           | random scene order vs file order         |
| start_scene     | no       | null           | scene name to force (debugging)          |
| base_amplitude  | no       | 60             | px of travel for the FRONT layer (see 5) |
| layer_factors   | no       | see 5          | per-layer amplitude multipliers          |
| background_rgb  | no       | [0,0,0]        | fill color behind layer 0                |
| scale_layers    | no       | "none"         | "none" or "cover" (see 6)                |
| crossfade_sec   | no       | 1.0            | fade time between scenes                 |
| motion_period   | no       | 8.0            | seconds per oscillation cycle (front)    |
| base_pan_speed  | no       | 40             | px/sec scroll speed for the FRONT layer  |

`scenes_file` and `image_folder` are the `required` list in the registry
entry; the rest go in `optional` so the validator catches typos.

### 3.2 Scene definitions file (`animated_scenes.json`, project root)

NOTE: this file lives at the PROJECT ROOT, not in `configs/`. The
`configs/` directory is reserved for modes_config variants —
`validate_configs.py --all` treats every `configs/*.json` as a modes
config and would report the scenes file as an error.

```json
{
  "scenes": [
    {
      "name": "night_crossing",
      "comment": "Ship tossing on ocean waves",
      "base_amplitude": 80,
      "layers": [
        { "image": "sky_night.png",   "x": 0.50, "y": 0.50, "motion": "static" },
        { "image": "waves_far.png",   "x": 0.50, "y": 0.72, "motion": "pan_right" },
        { "image": "boat.png",        "x": 0.45, "y": 0.60, "motion": "bob",
          "speed": 0.7 },
        { "image": "waves_mid.png",   "x": 0.50, "y": 0.82, "motion": "pan_left" },
        { "image": "waves_near.png",  "x": 0.50, "y": 0.95, "motion": "pan_right",
          "amplitude_scale": 1.3 }
      ]
    }
  ]
}
```

Per-layer fields:

| field            | required | default | meaning                                    |
|------------------|----------|---------|--------------------------------------------|
| image            | yes      | —       | PNG filename, relative to `image_folder`   |
| x, y             | yes      | —       | anchor position of the image CENTER, as a  |
|                  |          |         | fraction of screen size (0.0–1.0)          |
| motion           | yes      | —       | one of the motion types in section 4       |
| speed            | no       | 1.0     | multiplier on the motion's cycle rate      |
| amplitude_scale  | no       | 1.0     | multiplier on the computed layer amplitude |
| phase            | no       | 0.0     | phase offset (0.0–1.0 of a cycle) so       |
|                  |          |         | multiple layers with the same motion       |
|                  |          |         | don't move in lockstep                     |

Design decisions baked in here:

- Exactly 5 layers per scene. Fewer is allowed (pad from the back: a 3-layer
  scene occupies depth slots 0/2/4 — see open question Q3); more is rejected
  at load with a clear error.
- Positions are FRACTIONS of screen size, not pixels, so the same scene file
  works on the Pi kiosk and a dev laptop without editing.
- Per-scene `base_amplitude` overrides the instance-level one (waves scene
  can be calm, storm scene violent) without new code.
- `layers` array order IS draw order: index 0 = back = drawn first.

## 4. Motion types

Two families. This distinction matters and should be called out in review:

### Oscillating motions (safe for any image)
The image moves around its anchor and comes back. Never leaves a gap, so any
PNG works regardless of size.

| motion        | behavior                                              |
|---------------|-------------------------------------------------------|
| static        | no movement                                           |
| bob           | sine wave on Y (up/down)                              |
| sway          | sine wave on X (left/right)                           |
| drift_circle  | slow circular path around anchor                      |
| random        | smooth wander (perlin-ish: sum of 2 incommensurate    |
|               | sines on X and Y — deterministic, no RNG state)       |

### Panning motions (image must be wider/taller than the screen)
The image slides continuously in one direction and wraps. To avoid visible
seams the mode blits the image TWICE, side by side (tile offset by image
width), and wraps the offset modulo the image width. The artwork must be
drawn as a horizontally (or vertically) tileable strip.

| motion        | behavior                                              |
|---------------|-------------------------------------------------------|
| pan_left      | continuous scroll left, wraps                         |
| pan_right     | continuous scroll right, wraps                        |
| pan_up        | continuous scroll up, wraps                           |
| pan_down      | continuous scroll down, wraps                         |

Aliases accepted for readability: NONE. Design decision (Q1, resolved):
one name, one behavior. Oscillating motions use `sway`/`bob`; wrapping
motions use `pan_*`. No `slide_*` aliases — the names are frozen once
scene files exist.

Speed semantics:
- Oscillating: `speed` = cycles per minute at speed 1.0 is one full cycle per
  `motion_period` seconds (proposed default period: 8 s, scaled by layer
  depth — front layers move faster as well as farther).
- Panning: speed expressed in px/sec = `base_pan_speed * layer_factor`.

## 5. Parallax amplitude model (the core rule)

Depth index d = 0 (back) .. 4 (front).

```
layer_factor[d]  = [0.10, 0.25, 0.50, 0.75, 1.00]     (default, overridable)
amplitude_px     = base_amplitude * layer_factor[d] * layer.amplitude_scale
period_sec       = motion_period / (0.5 + layer_factor[d])   # front = faster
```

So with the default `base_amplitude = 60`:
  layer 0 moves ±6 px, layer 4 moves ±60 px.

Back layer is not exactly 0 so even the sky has a hint of life; a scene can
still force true stillness with `motion: static`.

All offsets are computed from elapsed time (`self._t += dt`), never by
accumulating per-frame deltas into positions — this keeps motion deterministic
and immune to frame-rate hiccups, and makes headless tests exact.

## 6. Rendering

- `render()` fills with `background_rgb`, then blits layers 0..4 at
  `anchor + offset`, back to front. PNG alpha honored (`convert_alpha`).
- `scale_layers: "none"`: blit as-is; scene art is authored at target res.
- `scale_layers: "cover"`: at scene load, scale each layer to cover the
  screen (same center-crop math as `animated_city_rain_mode`), once, cache
  the scaled surface. Never scale per frame.
- Scene switching: when `scene_duration` elapses, crossfade to the next scene
  by drawing the new scene to an off-screen surface and ramping its alpha
  over `crossfade_sec`. All preloading of the next scene's images happens
  right after the current scene starts (they're shared via manager.cache
  anyway), so the switch itself never hits disk.
- No overlays, no text, no per-frame logging. One `[AnimatedScene]` print per
  scene change, kiosk-style.

## 7. Lifecycle sketch

```python
class AnimatedSceneMode:
    def __init__(self, config):        # store config; load nothing
    def enter(self, manager):          # read scenes_file, validate,
                                       # pick first scene, load its images
    def exit(self):                    # drop all surface refs
    def handle_event(self, event):     # pass
    def update(self, dt):              # advance self._t, maybe switch scene
    def render(self, screen):          # fill, blit 5 layers, handle fade
```

Scene-file validation at `enter()`: missing file / bad JSON / unknown motion
/ missing image / wrong layer count all print one `[AnimatedScene]` error and
skip to the next scene; if NO scene is usable, the mode renders the
background color and logs once (never crashes the controller).

## 8. Testing plan (headless, SDL_VIDEODRIVER=dummy)

New file `tests/test_animated_scene.py`:

- offset math: at t=0, t=period/4, t=period/2 a `bob` layer returns exactly
  0, +amp, 0 on Y (deterministic — no RNG).
- amplitude model: layer 4 amplitude == base_amplitude, layer 0 == 10%.
- pan wrap: offset modulo image width stays in [0, w).
- scene file validation: unknown motion name -> scene skipped, error logged.
- 3-layer scene maps to depth slots correctly (pending Q3).
- smoke: run mode 120 frames with dummy driver, assert no exception.

## 9. Files touched by the implementation

- Create `modes/animated_scene_mode.py`
- Create `animated_scenes.json` (project root; ship-on-waves + one more)
- Create `art/parallax/` placeholder PNGs (committed, tileable where needed)
- Create `tests/test_animated_scene.py`
- Edit `modes_registry.json` (add `animatedscene` type entry)
- Edit `modes_config.json` (add one instance)
- Run `python validate_configs.py --all` and `python pixel_drift.py --play N --windowed`

Art assets: 5+ PNGs per scene under a user-chosen `image_folder` (path via
`modes_config.local.json` on each host). Art creation is out of scope for the
code change; placeholder PNGs will be generated for tests.

## 10. Review decisions (resolved 2026-08-02)

D1. Motion naming: two families, explicit names. Oscillating: `sway`,
    `bob`, `drift_circle`, `random`. Wrapping: `pan_left/right/up/down`.
    No aliases.
D2. Front layers move FASTER as well as farther:
    `period_d = motion_period / (0.5 + layer_factor[d])`.
D3. Scenes with fewer than 5 layers SPREAD across depth slots
    (3 layers -> slots 0, 2, 4) via round(i * 4 / (n-1)).
D4. `random` is deterministic smooth pseudo-random (sum of two
    incommensurate sines per axis). No RNG state.
D5. No per-layer `scale` in v1. Global `scale_layers: "cover"` handles
    resolution mismatch.
D6. Scene switching is timer-only (`scene_duration`). Controller owns keys.

# PUPPET THEATRE MODE — Design Document

Status: APPROVED — review decisions locked (section 12). No code written yet.
Date: 2026-08-08

## 1. Concept

A **puppet theatre** mode that performs scripted scenes using bitmap art. Each
scene has a title, a description, four parallax layers, and a script of dialogue
lines. Characters are simple image sprites that enter, exit, change expression,
and "speak" their lines while the scene layers provide a staged backdrop.

The mode reads the script from top to bottom, advances through scenes in file
order, and loops back to the first scene when it reaches the end. The animation
is intentionally simple — slides, pops, and fades — so the focus stays on the
writing and the artwork.

Example scene flow:
1. Draw scene layers 0, 2, and 3 (the set).
2. Fade in the scene title + description, hold, fade out.
3. For each script line:
   - Update the named character (enter, exit, change face, etc.).
   - Load and display the matching sprite.
   - If the line has dialogue, show it in a subtitle bar, hold, then hide it.
4. Fade out the whole scene.
5. If this was the last scene in the config, fade to black and hold briefly
   before loading scene 0 again; otherwise load the next scene.

## 2. Fit with pixel_drift architecture

- New file: `modes/puppet_theatre_mode.py`, class `PuppetTheatreMode`.
- Registry type name (normalized): `puppettheatre`
  -> entrypoint `modes.puppet_theatre_mode:PuppetTheatreMode`.
- Instance entries in `modes_config.json` point at a `scenes_file` and an
  `image_folder`; per-host paths live in `modes_config.local.json`.
- `python validate_configs.py --all` must still pass 0/0 after edits.
- No threads, no network. All images are loaded once in `enter()` (or lazily on
  first use but cached) and released in `exit()`.
- Images load through `manager.cache.get_image(path, convert_alpha=True)`.
- No per-frame logging. One `[PuppetTheatre]` print per scene change.

## 3. Configuration layout (two files)

### 3.1 Mode instance config (`modes_config.json`)

```json
{
  "modes": {
    "38": {
      "type": "puppettheatre",
      "scenes_file": "assets/puppet_theatre/scene_files/puppet_scenes.json",
      "image_folder": "/path/to/puppet_assets"
    }
  }
}
```

Keys:

| key                           | required | default            | meaning                                      |
|-------------------------------|----------|--------------------|----------------------------------------------|
| scenes_file                   | yes      | —                  | path to the scene definitions JSON           |
| image_folder                  | yes      | —                  | base folder for layer PNGs and character dirs|
| scene_description_fade_in_sec | no       | 0.8                | fade-in time for title/description           |
| scene_description_hold_sec    | no       | 4.0                | time the description stays fully visible     |
| scene_description_fade_out_sec| no       | 0.8                | fade-out time for title/description          |
| dialogue_fade_in_sec          | no       | 0.3                | fade-in time for dialogue text               |
| dialogue_hold_sec             | no       | 3.0                | base time a dialogue line stays on screen    |
| dialogue_hold_extra_per_word  | no       | 0.18               | extra hold time per word of dialogue         |
| dialogue_fade_out_sec         | no       | 0.3                | fade-out time for dialogue text              |
| transition_duration_sec       | no       | 0.9                | duration of enter/move/exit animations       |
| pop_duration_sec              | no       | 0.25               | duration of the "pop up" bounce/scale snap   |
| scene_pause_before_script_sec | no       | 0.5                | brief pause after description, before script |
| scene_pause_after_script_sec  | no       | 0.5                | brief pause after script, before scene fade  |
| loop_fade_to_black_sec        | no       | 0.8                | fade-to-black duration at end of last scene  |
| loop_black_hold_sec           | no       | 0.5                | hold on black before looping back to scene 0 |
| default_transition_in         | no       | {"type":"fade"}    | scene open transition if scene omits it      |
| default_transition_out        | no       | {"type":"fade"}    | scene close transition if scene omits it     |
| background_rgb                | no       | [0,0,0]            | fill color behind layer 0                    |
| dialogue_bg_rgb               | no       | [0,0,0]            | subtitle bar background color                |
| dialogue_fg_rgb               | no       | [255,255,255]      | subtitle text color                          |
| dialogue_font_size            | no       | 42                 | subtitle font size (px)                      |
| dialogue_box_alpha            | no       | 180                | subtitle bar alpha (0-255)                   |
| dialogue_box_margin           | no       | 24                 | px margin between text and bar edge          |
| description_font_size         | no       | 52                 | title/description font size                  |
| stage_positions               | no       | see 6.1            | named stage positions used by transitions    |
| scale_characters              | no       | true               | scale characters to screen height if true    |

`scenes_file` and `image_folder` are the `required` list in the registry.
Everything else is `optional` so the validator catches typos.

### 3.2 Scene definitions file (`assets/puppet_theatre/scene_files/puppet_scenes.json`)

This file lives inside the mode's asset tree so scenes are kept with the artwork
that belongs to the puppet theatre mode.

```json
{
  "characters": {
    "ALICE": {
      "default_emotion": "CALM",
      "scale": 1.0,
      "origin": "bottom_center"
    },
    "BOB": {
      "default_emotion": "HAPPY",
      "scale": 0.95
    },
    "SLAM": {
      "default_emotion": "DEFAULT",
      "scale": 0.7
    }
  },
  "positions": {
    "stage_left":   {"x": 0.18, "y": 0.72},
    "stage_center": {"x": 0.50, "y": 0.72},
    "stage_right":  {"x": 0.82, "y": 0.72}
  },
  "scenes": [
    {
      "title": "The Argument",
      "description": "Alice confronts Bob about his plans.",
      "background_rgb": [12, 14, 24],
      "transition_in": {"type": "fade", "duration": 1.0},
      "transition_out": {"type": "fade", "duration": 1.0},
      "layers": [
        {"image": "living_room_bg.png", "motion": "static"},
        {"image": null, "motion": "static"},
        {"image": "table_overlay.png", "motion": "static"},
        {"image": "lamp_overlay.png", "motion": "static"}
      ],
      "script": [
        {"character": "ALICE", "transition": "ENTER_STAGE_LEFT",
         "emotion": "ANGRY", "mouth": "YELLING",
         "dialogue": "What are you talking about?!!!!"},
        {"character": "BOB", "transition": "ENTER_STAGE_RIGHT",
         "emotion": "CALM", "mouth": "SPEAKING",
         "dialogue": "I told you I had plans tonight."},
        {"character": "ALICE", "transition": "EXIT_STAGE_LEFT",
         "emotion": "ANGRY", "mouth": "SILENT"},
        {"character": "SLAM", "transition": "POPS_UP_STAGE_LEFT",
         "emotion": "DEFAULT", "mouth": "SILENT"}
      ]
    }
  ]
}
```

Top-level fields:

| field        | required | meaning                                              |
|--------------|----------|------------------------------------------------------|
| characters   | no       | character_id -> defaults (emotion, scale, origin)    |
| positions    | no       | named stage positions; overrides instance defaults   |
| scenes       | yes      | list of scene objects                                |

Character defaults (`characters`):

| field          | required | default         | meaning                                    |
|----------------|----------|-----------------|--------------------------------------------|
| default_emotion| no       | "DEFAULT"       | emotion used when a script line omits one  |
| scale          | no       | 1.0             | size multiplier relative to screen height  |
| origin         | no       | "bottom_center" | anchor point used when placing the sprite  |

Scene object fields:

| field            | required | default                          | meaning                                  |
|------------------|----------|----------------------------------|------------------------------------------|
| title            | no       | ""                               | displayed at scene start                 |
| description      | no       | ""                               | longer text displayed with title         |
| layers           | yes      | —                                | exactly 4 layer entries (0..3)           |
| script           | yes      | —                                | list of script-line objects              |
| background_rgb   | no       | from instance config             | fill color behind layer 0                |
| transition_in    | no       | instance `default_transition_in` | how the scene appears                    |
| transition_out   | no       | instance `default_transition_out`| how the scene disappears                 |

Layer entry fields:

| field   | required | default  | meaning                                           |
|---------|----------|----------|---------------------------------------------------|
| image   | yes*     | —        | PNG filename relative to `image_folder`; null = empty layer |
| motion  | no       | "static" | "static", "bob", "sway", "drift_circle", or "pan_*" |
| speed   | no       | 1.0      | motion rate multiplier                            |
| depth_factor | no  | 1.0      | extra amplitude multiplier for parallax           |

\* `image` may be `null` for layer 1 because layer 1 is reserved for
characters and never draws a static image. Layers 0, 2, and 3 usually have
images.

Script-line fields (all optional except `character`):

| field       | required | default                                  | meaning                                     |
|-------------|----------|------------------------------------------|---------------------------------------------|
| character   | yes      | —                                        | character_id; empty string = off-stage/no sprite |
| transition  | no       | none                                     | stage direction (see section 6)             |
| emotion     | no       | character's `default_emotion`            | emotional expression                        |
| mouth       | no       | "SPEAKING" if dialogue present, else "SILENT" | mouth state (see 4.3)                  |
| dialogue    | no       | ""                                       | text shown in the subtitle bar              |
| position    | no       | inferred from transition                 | explicit target position name               |
| duration    | no       | computed from dialogue + transitions     | overrides timing for this line only         |

A script line with `character: ""` (or omitted) is a **stage direction only**:
no character sprite changes, but a transition name like `FADE_TO_BLACK` could
be interpreted later as a global effect.

## 4. Character artwork and image lookup

### 4.1 Folder layout

```
image_folder/
  living_room_bg.png
  table_overlay.png
  lamp_overlay.png
  ALICE/
    ALICE_LEFT_ANGRY_SILENT.png
    ALICE_LEFT_ANGRY_SPEAKING.png
    ALICE_LEFT_ANGRY_YELLING.png
    ALICE_LEFT_CALM_SILENT.png
    ALICE_LEFT_CALM_SPEAKING.png
    ALICE_RIGHT_ANGRY_SILENT.png
    ...
  BOB/
    BOB_RIGHT_CALM_SPEAKING.png
    ...
  SLAM/
    SLAM_LEFT_DEFAULT_SILENT.png
    SLAM_RIGHT_DEFAULT_SILENT.png
```

Each character has a folder named after its `character_id`. Scene layer images
live at the root of `image_folder` (or in subdirectories if the filename
includes the path).

### 4.2 Required filename convention

For deterministic lookup, every character image MUST match:

```
<character_id>_<facing>_<emotion>_<mouth>.png
```

Where:
- `<character_id>` matches the script exactly (case-sensitive recommended).
- `<facing>` is `LEFT` or `RIGHT`.
- `<emotion>` is any uppercase token the artist chooses (e.g., `DEFAULT`,
  `CALM`, `HAPPY`, `SAD`, `ANGRY`, `SURPRISED`).
- `<mouth>` is one of: `SILENT`, `SPEAKING`, `YELLING`, `WHISPER`.

The mode scans each character folder at `enter()` and builds a lookup keyed by
`(facing, emotion, mouth)`. This avoids per-frame disk checks and makes
fallbacks fast.

### 4.3 Mouth states

| state    | meaning                                    |
|----------|--------------------------------------------|
| SILENT   | mouth closed, character not speaking       |
| SPEAKING | mouth open, normal speech                  |
| YELLING  | mouth open wide, shouting or strong emotion|
| WHISPER  | mouth slightly open, whispered line        |

Default mouth logic:
- If the line has dialogue and no `mouth` is given, use `SPEAKING`.
- If the line has no dialogue and no `mouth` is given, use `SILENT`.

### 4.4 Fallback chain

If the exact image is missing, the mode tries, in order:

1. Same facing + emotion + `SILENT` (for speaking variants that don't exist).
2. Same facing + character default emotion + requested mouth.
3. Same facing + character default emotion + `SILENT`.
4. Any image with the same facing.
5. Any image in the character folder.
6. A placeholder colored rectangle with the character ID printed on it.

The fallback is logged once per missing combination, not per frame.

## 5. Four-layer parallax model

Layer order is draw order: 0 is drawn first (back), 3 is drawn last (front).

| layer | purpose              | typical motion |
|-------|----------------------|----------------|
| 0     | static background    | static or very slow pan |
| 1     | character layer      | static (characters animate separately on this layer) |
| 2     | mid overlay          | static, bob, or slow sway |
| 3     | front overlay        | static or stronger sway for 3D depth |

Depth index `d = 0..3`. Default amplitude factors:

```
layer_factor[d] = [0.05, 0.0, 0.25, 0.60]
```

Layer 1 (characters) does not receive automatic parallax motion because
transitions handle character movement. Layers 0, 2, and 3 move by
`amplitude_px = base_amplitude * layer_factor[d] * depth_factor`.

`base_amplitude` defaults to 40 px and can be set per scene or per instance.

## 6. Stage positions and transitions

### 6.1 Named positions

Default positions (overridable in the scenes file or instance config):

```json
{
  "stage_left":   {"x": 0.18, "y": 0.72},
  "stage_center": {"x": 0.50, "y": 0.72},
  "stage_right":  {"x": 0.82, "y": 0.72}
}
```

Positions are fractions of the screen size, so the same scene works on the Pi
kiosk and a dev laptop.

Additional positions may be defined freely (`off_left`, `off_right`, `balcony`,
`foreground`, etc.). The only reserved names are the transition targets below.

### 6.2 Transition vocabulary

| transition             | behavior                                                   |
|------------------------|------------------------------------------------------------|
| ENTER_STAGE_LEFT       | Start off-screen left, slide to `stage_left`, face RIGHT   |
| ENTER_STAGE_RIGHT      | Start off-screen right, slide to `stage_right`, face LEFT  |
| ENTER_STAGE_CENTER     | Start below/beside center, slide to `stage_center`         |
| EXIT_STAGE_LEFT        | Slide off-screen left, face LEFT; hidden after transition  |
| EXIT_STAGE_RIGHT       | Slide off-screen right, face RIGHT; hidden after transition|
| EXIT_STAGE_DOWN        | Slide down off-screen; hidden after transition             |
| POPS_UP_STAGE_LEFT     | Snap to `stage_left` with a small scale bounce             |
| POPS_UP_STAGE_CENTER   | Snap to `stage_center` with a small scale bounce           |
| POPS_UP_STAGE_RIGHT    | Snap to `stage_right` with a small scale bounce            |
| MOVE_TO_STAGE_LEFT     | Slide from current position to `stage_left`, face RIGHT    |
| MOVE_TO_STAGE_CENTER   | Slide from current position to `stage_center`              |
| MOVE_TO_STAGE_RIGHT    | Slide from current position to `stage_right`, face LEFT    |
| MOVE_OFF_STAGE         | Slide off in the current facing direction; hidden after    |
| TURN_LEFT              | Flip to face LEFT without moving                           |
| TURN_RIGHT             | Flip to face RIGHT without moving                          |
| JUMP                   | Quick vertical bounce in place                             |
| SHAKE                  | Small horizontal wobble                                    |
| NONE                   | No movement; just update emotion/mouth                     |

A transition may also be written as a target position name alone, e.g.
`{"transition": "stage_left"}`, which behaves like `MOVE_TO_STAGE_LEFT` if the
character is already on stage, or `ENTER_STAGE_LEFT` if off-stage.

### 6.3 Facing rules

- Entering from the left -> face RIGHT (toward center).
- Entering from the right -> face LEFT (toward center).
- Exiting stage left -> face LEFT.
- Exiting stage right -> face RIGHT.
- `MOVE_TO_*` transitions face the direction of travel.
- `TURN_*` overrides the facing explicitly.
- If a transition does not imply a facing, the character keeps its current
  facing.

## 7. Rendering and scene flow

### 7.1 State machine

```
SCENE_LOAD -> INTRO (draw layers + scene transition in)
  -> DESCRIPTION_FADE_IN -> DESCRIPTION_HOLD -> DESCRIPTION_FADE_OUT
  -> SCRIPT_LINE (apply transition / update sprite)
  -> DIALOGUE_FADE_IN -> DIALOGUE_HOLD -> DIALOGUE_FADE_OUT (if dialogue)
  -> next SCRIPT_LINE, or OUTRO when script ends
  -> OUTRO (scene transition out)
  -> LOOP_FADE_TO_BLACK / LOOP_BLACK (only after the last scene)
  -> SCENE_LOAD (next scene, or scene 0 when looping)
```

All timing is driven by accumulated elapsed seconds, never by frame counts, so
the mode is deterministic and headless-testable.

### 7.2 Rendering order per frame

1. Fill with `background_rgb`.
2. Draw layer 0 (background).
3. Draw all visible characters at their current screen positions, sorted by
   their current Y so lower characters overlap higher ones naturally (optional,
   disabled if it causes unwanted popping).
4. Draw layer 2 (mid overlay) and layer 3 (front overlay). Overlay layers are
   anchored to the bottom of the screen so foreground props always sit on the
   "floor" of the scene, and they are drawn after characters so they cover the
   actors when appropriate.
5. Draw the scene description overlay if in the description phase.
6. Draw the dialogue bar if in a dialogue phase.
7. Apply scene-wide fade-in/fade-out alpha if a transition is active.

### 7.3 Dialogue bar

- A semi-transparent rectangle across the lower portion of the screen.
- Text is centered, wrapped to fit inside the bar margins.
- Fades in, holds, fades out.
- If a new line starts while the previous line is still visible, the old line
  fades out before the new one fades in.

### 7.4 Character scaling

When `scale_characters` is true, each character sprite is scaled so that its
height is roughly a configured fraction of the screen height (default ~45%),
then multiplied by the per-character `scale`. The scaled surface is cached per
unique `(character_id, facing, emotion, mouth)` combination.

## 8. Lifecycle sketch

```python
class PuppetTheatreMode:
    def __init__(self, config):      # store config; no I/O
    def enter(self, manager):        # load scenes_file, validate, load images
    def exit(self):                  # drop surface refs and caches
    def handle_event(self, event):   # pass
    def update(self, dt):            # advance state machine
    def render(self, screen):        # draw layers, characters, text, fades
```

Scene-file validation at `enter()`: missing file, bad JSON, missing required
fields, unknown transitions, missing layer images, or missing character
folders all log one `[PuppetTheatre]` error and skip the bad scene. If no
scene is usable, the mode fills the screen with `background_rgb` and logs once.

## 9. Testing plan (headless, SDL_VIDEODRIVER=dummy)

New file `tests/test_puppet_theatre.py`:

- Filename parsing: a tokenized filename is split into the correct
  `(facing, emotion, mouth)` tuple.
- Fallback chain: requesting a missing image returns the expected fallback.
- Transition facing rules: `ENTER_STAGE_LEFT` results in facing `RIGHT`;
  `EXIT_STAGE_LEFT` results in facing `LEFT`.
- State machine timing: with known durations, `update(dt)` advances from
  description fade-in -> hold -> fade-out correctly.
- Dialogue hold: a 6-word line holds longer than a 1-word line when
  `dialogue_hold_extra_per_word` is non-zero.
- Layer parallax: layer 3 moves more than layer 0 for the same `bob` motion.
- Smoke: run the mode for 120 frames with a test scene and assert no
  exception.

## 10. Files touched by the implementation

- Create `modes/puppet_theatre_mode.py`
- Create `assets/puppet_theatre/scene_files/puppet_scenes.json` (at least one demo scene)
- Create `assets/puppet_theatre/` placeholder PNGs and character folders
- Create `tests/test_puppet_theatre.py`
- Edit `modes_registry.json` (add `puppettheatre` type entry)
- Edit `modes_config.json` (add one instance)
- Run `python validate_configs.py --all` and
  `python pixel_drift.py --play N --windowed`

Art assets: placeholder PNGs will be generated for tests. Real artwork is out
of scope for the code change.

## 11. Decisions (to be locked at review)

- **D1 — Four layers, 0..3**: layer 0 = background, layer 1 = character layer,
  layers 2 and 3 = overlays. Layer 1 receives no automatic parallax motion.
- **D2 — Strict filename convention**: character images MUST match
  `<character_id>_<facing>_<emotion>_<mouth>.png`. The mode scans folders once
  at `enter()` and uses the fallback chain for missing variants.
- **D3 — Script lines as JSON objects**: readable key/value form rather than
  CSV strings. A compact string alias could be added later without breaking
  object-form scenes.
- **D4 — One active speaker per line**: each script line updates exactly one
  character. Other characters already on stage remain visible until explicitly
  exited.
- **D5 — Default mouth logic**: `SPEAKING` when dialogue is present,
  `SILENT` when absent.
- **D6 — Stage position names**: default set is `stage_left`, `stage_center`,
  `stage_right`. Users may define additional positions; transition names map
  to these positions.
- **D7 — Scene loop**: when the last scene ends, the mode fades to black
  (`loop_fade_to_black_sec`), holds on black (`loop_black_hold_sec`), then
  loads scene 0 again. No shuffle option in v1.
- **D8 — Character scaling**: sprites are scaled relative to screen height by
  default, with a per-character multiplier.

## 12. Review decisions (locked)

- **D9 — Layer 1 is character-only**: layer 1 holds no static image; the scene
  set is on layers 0, 2, and 3. The `image` field on layer 1 is ignored and
  may be set to `null`.
- **D10 — Script format**: JSON objects only. Compact CSV-style strings are
  not supported in v1.
- **D11 — Filename convention**: strict `<character_id>_<facing>_<emotion>_<mouth>.png`
  is the v1 contract.
- **D12 — Sound/music hooks**: out of scope for v1. No `sound` field is reserved
  in the script line schema.
- **D13 — Portrait layouts**: fraction-based stage positions are sufficient;
  no `portrait_positions` override in v1.

Remaining open questions (non-blocking):

1. Should the dialogue bar support a small "speaker portrait" thumbnail?
   (Proposed: out of scope for v1.)
2. Should transitions support easing curves (linear vs ease-out)? (Proposed:
   linear for v1; add an `easing` key later.)

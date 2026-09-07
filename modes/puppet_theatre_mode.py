# modes/puppet_theatre_mode.py
#
# Puppet theatre mode for pixel_drift. See PUPPET_THEATRE_DESIGN.md.
#
# A scene is a scripted performance: four parallax layers form the set,
# characters enter/exit/express/speak, and the mode loops through scenes
# indefinitely. All artwork is local bitmap; no network or threads.
#
# Config (instance, modes_config.json):
#   scenes_file                    (required) path to scene definitions JSON
#   image_folder                   (required) base folder for layer PNGs + chars
#   scene_description_fade_in_sec  (default 0.8)
#   scene_description_hold_sec     (default 4.0)
#   scene_description_fade_out_sec (default 0.8)
#   dialogue_fade_in_sec           (default 0.3)
#   dialogue_hold_sec              (default 3.0)
#   dialogue_hold_extra_per_word   (default 0.18)
#   dialogue_fade_out_sec          (default 0.3)
#   transition_duration_sec        (default 0.9)
#   pop_duration_sec               (default 0.25)
#   scene_pause_before_script_sec  (default 0.5)
#   scene_pause_after_script_sec   (default 0.5)
#   default_transition_in          (default {"type": "fade"})
#   default_transition_out         (default {"type": "fade"})
#   background_rgb                 (default [0,0,0])
#   dialogue_bg_rgb                (default [0,0,0])
#   dialogue_fg_rgb                (default [255,255,255])
#   dialogue_font_size             (default 42)
#   dialogue_box_alpha             (default 180)
#   dialogue_box_margin            (default 24)
#   description_font_size          (default 52)
#   stage_positions                (default set below)
#   scale_characters               (default true)
#   character_height_frac          (default 0.45)

import json
import math
import os
from typing import Optional

import pygame

# Repo root (this file lives in modes/). Relative config paths resolve here
# so the mode works regardless of the controller's cwd.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NUM_LAYERS = 4
CHARACTER_LAYER = 1
DEFAULT_LAYER_FACTORS = [0.05, 0.0, 0.25, 0.60]
DEFAULT_BASE_AMPLITUDE = 40.0
DEFAULT_STAGE_POSITIONS = {
    "stage_left": {"x": 0.18, "y": 0.72},
    "stage_center": {"x": 0.50, "y": 0.72},
    "stage_right": {"x": 0.82, "y": 0.72},
}

MOUTH_STATES = {"SILENT", "SPEAKING", "YELLING", "WHISPER"}
EMOTIONS = {"DEFAULT", "CALM", "HAPPY", "SAD", "ANGRY", "SURPRISED"}

# Transitions that imply a specific facing.
TRANSITION_FACING = {
    "ENTER_STAGE_LEFT": "RIGHT",
    "ENTER_STAGE_RIGHT": "LEFT",
    "ENTER_STAGE_CENTER": "RIGHT",
    "EXIT_STAGE_LEFT": "LEFT",
    "EXIT_STAGE_RIGHT": "RIGHT",
    "EXIT_STAGE_DOWN": None,
    "MOVE_TO_STAGE_LEFT": "RIGHT",
    "MOVE_TO_STAGE_RIGHT": "LEFT",
    "MOVE_TO_STAGE_CENTER": None,
    "MOVE_OFF_STAGE": None,
    "TURN_LEFT": "LEFT",
    "TURN_RIGHT": "RIGHT",
}

# Transitions that are movement-based (slide from current/off-screen to target).
MOVEMENT_TRANSITIONS = {
    "ENTER_STAGE_LEFT",
    "ENTER_STAGE_RIGHT",
    "ENTER_STAGE_CENTER",
    "EXIT_STAGE_LEFT",
    "EXIT_STAGE_RIGHT",
    "EXIT_STAGE_DOWN",
    "MOVE_TO_STAGE_LEFT",
    "MOVE_TO_STAGE_CENTER",
    "MOVE_TO_STAGE_RIGHT",
    "MOVE_OFF_STAGE",
}

# Pop transitions: appear at target with a quick scale bounce.
POP_TRANSITIONS = {
    "POPS_UP_STAGE_LEFT",
    "POPS_UP_STAGE_CENTER",
    "POPS_UP_STAGE_RIGHT",
}

# Transitions that remove the character from the stage once they finish.
EXIT_TRANSITIONS = {
    "EXIT_STAGE_LEFT",
    "EXIT_STAGE_RIGHT",
    "EXIT_STAGE_DOWN",
    "MOVE_OFF_STAGE",
}

# Simple in-place transitions.
INSTANT_TRANSITIONS = {
    "TURN_LEFT",
    "TURN_RIGHT",
    "JUMP",
    "SHAKE",
    "NONE",
}

ALL_TRANSITIONS = (
    MOVEMENT_TRANSITIONS
    | POP_TRANSITIONS
    | INSTANT_TRANSITIONS
    | set(DEFAULT_STAGE_POSITIONS.keys())
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_path(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(BASE_DIR, path)


def _as_rgb(value, default=(0, 0, 0)) -> tuple:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return (int(value[0]), int(value[1]), int(value[2]))
    return default


def _oscillate_offset(motion: str, t: float, period: float,
                      amplitude: float, speed: float = 1.0,
                      phase: float = 0.0) -> tuple[float, float]:
    """Deterministic (dx, dy) for oscillating layer motions."""
    if period <= 0 or amplitude == 0:
        return (0.0, 0.0)
    w = 2.0 * math.pi * speed / period
    p = 2.0 * math.pi * phase
    if motion == "bob":
        return (0.0, amplitude * math.sin(w * t + p))
    if motion == "sway":
        return (amplitude * math.sin(w * t + p), 0.0)
    if motion == "drift_circle":
        return (amplitude * math.cos(w * t + p), amplitude * math.sin(w * t + p))
    return (0.0, 0.0)


def _pan_offset(t: float, span: int, speed: float, phase: float = 0.0) -> float:
    """Wrapped pan offset in [0, span)."""
    if span <= 0:
        return 0.0
    return (speed * t + phase * span) % span


def _ease(t: float) -> float:
    """Smoothstep-ish ease for movement transitions."""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _word_count(text: str) -> int:
    return len(text.split()) if text else 0


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class _Layer:
    __slots__ = ("image", "path", "motion", "speed", "depth_factor",
                 "depth", "surface")

    def __init__(self, image: Optional[str], motion: str, speed: float,
                 depth_factor: float, depth: int, image_folder: str):
        self.image = image
        self.path = os.path.join(image_folder, image) if image else None
        self.motion = motion
        self.speed = speed
        self.depth_factor = depth_factor
        self.depth = depth
        self.surface = None


class _Scene:
    __slots__ = ("title", "description", "layers", "script",
                 "background_rgb", "transition_in", "transition_out")

    def __init__(self, title, description, layers, script,
                 background_rgb, transition_in, transition_out):
        self.title = title
        self.description = description
        self.layers = layers
        self.script = script
        self.background_rgb = background_rgb
        self.transition_in = transition_in
        self.transition_out = transition_out


class _CharacterState:
    __slots__ = ("character_id", "visible", "position_name", "facing",
                 "emotion", "mouth", "screen_x", "screen_y", "scale",
                 "transition", "transition_t", "transition_duration",
                 "start_x", "start_y", "target_x", "target_y", "pop_scale",
                 "jump_t")

    def __init__(self, character_id: str, default_emotion: str = "DEFAULT",
                 scale: float = 1.0):
        self.character_id = character_id
        self.visible = False
        self.position_name = ""
        self.facing = "RIGHT"
        self.emotion = default_emotion
        self.mouth = "SILENT"
        self.screen_x = 0.0
        self.screen_y = 0.0
        self.scale = scale
        self.transition = "NONE"
        self.transition_t = 0.0
        self.transition_duration = 0.0
        self.start_x = 0.0
        self.start_y = 0.0
        self.target_x = 0.0
        self.target_y = 0.0
        self.pop_scale = 1.0
        self.jump_t = 0.0


# ---------------------------------------------------------------------------
# Mode class
# ---------------------------------------------------------------------------

class PuppetTheatreMode:
    def __init__(self, config: dict):
        # __init__ does NO I/O. Everything loads in enter().
        self.scenes_file = config.get("scenes_file", "")
        self.image_folder = config.get("image_folder", "")

        self.scene_description_fade_in_sec = float(config.get("scene_description_fade_in_sec", 0.8))
        self.scene_description_hold_sec = float(config.get("scene_description_hold_sec", 4.0))
        self.scene_description_fade_out_sec = float(config.get("scene_description_fade_out_sec", 0.8))
        self.dialogue_fade_in_sec = float(config.get("dialogue_fade_in_sec", 0.3))
        self.dialogue_hold_sec = float(config.get("dialogue_hold_sec", 3.0))
        self.dialogue_hold_extra_per_word = float(config.get("dialogue_hold_extra_per_word", 0.18))
        self.dialogue_fade_out_sec = float(config.get("dialogue_fade_out_sec", 0.3))
        self.transition_duration_sec = float(config.get("transition_duration_sec", 0.9))
        self.pop_duration_sec = float(config.get("pop_duration_sec", 0.25))
        self.scene_pause_before_script_sec = float(config.get("scene_pause_before_script_sec", 0.5))
        self.scene_pause_after_script_sec = float(config.get("scene_pause_after_script_sec", 0.5))
        self.loop_fade_to_black_sec = float(config.get("loop_fade_to_black_sec", 0.8))
        self.loop_black_hold_sec = float(config.get("loop_black_hold_sec", 0.5))

        self.default_transition_in = config.get("default_transition_in", {"type": "fade"})
        self.default_transition_out = config.get("default_transition_out", {"type": "fade"})

        self.background_rgb = _as_rgb(config.get("background_rgb"), (0, 0, 0))
        self.dialogue_bg_rgb = _as_rgb(config.get("dialogue_bg_rgb"), (0, 0, 0))
        self.dialogue_fg_rgb = _as_rgb(config.get("dialogue_fg_rgb"), (255, 255, 255))
        self.dialogue_font_size = int(config.get("dialogue_font_size", 42))
        self.description_font_size = int(config.get("description_font_size", 52))
        self.dialogue_box_alpha = int(config.get("dialogue_box_alpha", 180))
        self.dialogue_box_margin = int(config.get("dialogue_box_margin", 24))
        self.scale_characters = bool(config.get("scale_characters", True))
        self.character_height_frac = float(config.get("character_height_frac", 0.45))

        positions = config.get("stage_positions", DEFAULT_STAGE_POSITIONS)
        if isinstance(positions, dict):
            self.stage_positions = dict(DEFAULT_STAGE_POSITIONS)
            self.stage_positions.update(positions)
        else:
            self.stage_positions = dict(DEFAULT_STAGE_POSITIONS)

        base_amp = config.get("base_amplitude", DEFAULT_BASE_AMPLITUDE)
        self.base_amplitude = float(base_amp)

        factors = config.get("layer_factors", DEFAULT_LAYER_FACTORS)
        if (not isinstance(factors, list) or len(factors) != NUM_LAYERS
                or not all(isinstance(f, (int, float)) for f in factors)):
            factors = DEFAULT_LAYER_FACTORS
        self.layer_factors = [float(f) for f in factors]

        self.manager = None
        self._scenes: list[_Scene] = []
        self._scene_index = 0
        self._scene_t = 0.0
        self._scene_state = "intro"  # intro, description_in, description_hold, description_out, pause_before_script, script_line, dialogue_in, dialogue_hold, dialogue_out, pause_after_script, outro
        self._line_index = 0
        self._characters: dict[str, _CharacterState] = {}
        self._character_defaults: dict[str, dict] = {}
        self._character_lookups: dict[str, dict] = {}
        self._missing_logged: set = set()
        self._dialogue_text = ""
        self._current_transition = "NONE"
        self._scene_alpha = 1.0  # for scene-wide fade in/out
        self._character_surface_cache: dict = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def enter(self, manager):
        self.manager = manager
        self._scenes = self._load_scenes()
        self._scene_index = 0
        self._line_index = 0
        self._characters.clear()
        self._missing_logged.clear()
        self._character_surface_cache.clear()

        if not self._scenes:
            print("[PuppetTheatre] no usable scenes — rendering background only")
            return

        self._start_scene(0)
        print(f"[PuppetTheatre] loaded {len(self._scenes)} scene(s)")

    def exit(self):
        self._scenes = []
        self._characters.clear()
        self._character_lookups.clear()
        self._missing_logged.clear()
        self._character_surface_cache.clear()
        self.manager = None

    def handle_event(self, event):
        pass

    # ------------------------------------------------------------------
    # Scene loading / validation
    # ------------------------------------------------------------------

    def _load_scenes(self) -> list[_Scene]:
        path = _resolve_path(self.scenes_file)
        image_folder = _resolve_path(self.image_folder)

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[PuppetTheatre] cannot read scenes file '{path}': {e}")
            return []

        if not isinstance(data, dict):
            print(f"[PuppetTheatre] '{path}' is not an object")
            return []

        self._character_defaults = {}
        raw_characters = data.get("characters", {})
        if isinstance(raw_characters, dict):
            for cid, cdef in raw_characters.items():
                if isinstance(cdef, dict):
                    self._character_defaults[str(cid)] = cdef
                else:
                    self._character_defaults[str(cid)] = {}

        raw_positions = data.get("positions", {})
        if isinstance(raw_positions, dict):
            for name, pos in raw_positions.items():
                if isinstance(pos, dict) and "x" in pos and "y" in pos:
                    self.stage_positions[str(name)] = {
                        "x": float(pos["x"]),
                        "y": float(pos["y"]),
                    }

        raw_scenes = data.get("scenes")
        if not isinstance(raw_scenes, list):
            print(f"[PuppetTheatre] '{path}' has no 'scenes' list")
            return []

        scenes = []
        for i, raw in enumerate(raw_scenes):
            scene = self._validate_scene(raw, i, image_folder)
            if scene is not None:
                scenes.append(scene)
        return scenes

    def _validate_scene(self, raw, index: int, image_folder: str) -> Optional[_Scene]:
        label = f"scene[{index}]"
        if not isinstance(raw, dict):
            print(f"[PuppetTheatre] {label}: not an object — skipped")
            return None

        title = str(raw.get("title", ""))
        description = str(raw.get("description", ""))
        label = f"scene '{title}'" if title else label

        raw_layers = raw.get("layers")
        if not isinstance(raw_layers, list) or len(raw_layers) != NUM_LAYERS:
            print(f"[PuppetTheatre] {label}: needs exactly {NUM_LAYERS} layers — skipped")
            return None

        layers = []
        for li, spec in enumerate(raw_layers):
            layer = self._validate_layer(spec, label, li, image_folder)
            if layer is None:
                return None
            layers.append(layer)

        script = self._validate_script(raw.get("script", []), label)
        if script is None:
            return None

        bg = _as_rgb(raw.get("background_rgb"), self.background_rgb)
        trans_in = raw.get("transition_in", self.default_transition_in)
        trans_out = raw.get("transition_out", self.default_transition_out)

        return _Scene(title, description, layers, script, bg, trans_in, trans_out)

    def _validate_layer(self, spec, scene_label: str, li: int,
                        image_folder: str) -> Optional[_Layer]:
        label = f"{scene_label} layer {li}"
        if not isinstance(spec, dict):
            print(f"[PuppetTheatre] {label}: not an object — scene skipped")
            return None

        image = spec.get("image")
        if image is not None and not isinstance(image, str):
            print(f"[PuppetTheatre] {label}: 'image' must be a string or null — scene skipped")
            return None

        # Layer 1 is character-only; ignore any image there.
        if li == CHARACTER_LAYER:
            image = None

        if image and not os.path.exists(os.path.join(image_folder, image)):
            print(f"[PuppetTheatre] {label}: image '{image}' not found — scene skipped")
            return None

        motion = str(spec.get("motion", "static"))
        if motion not in {"static", "bob", "sway", "drift_circle", "pan_left", "pan_right"}:
            print(f"[PuppetTheatre] {label}: unknown motion '{motion}' — scene skipped")
            return None

        return _Layer(
            image,
            motion,
            float(spec.get("speed", 1.0)),
            float(spec.get("depth_factor", 1.0)),
            li,
            image_folder,
        )

    def _validate_script(self, raw_script, scene_label: str) -> Optional[list[dict]]:
        if not isinstance(raw_script, list):
            print(f"[PuppetTheatre] {scene_label}: 'script' must be a list — scene skipped")
            return None

        script = []
        for i, line in enumerate(raw_script):
            if not isinstance(line, dict):
                print(f"[PuppetTheatre] {scene_label} script[{i}]: not an object — scene skipped")
                return None
            character = str(line.get("character", ""))
            transition = str(line.get("transition", "")).upper().replace(" ", "_")
            # Accept bare position names as transitions too.
            if not transition:
                transition = "NONE"

            # Normalize position-only transitions.
            if transition in self.stage_positions and transition not in ALL_TRANSITIONS:
                # It's a bare position name. Decide move vs enter based on
                # whether the character is currently on stage (handled at runtime).
                transition = f"MOVE_TO_{transition}"

            if transition not in ALL_TRANSITIONS:
                print(f"[PuppetTheatre] {scene_label} script[{i}]: unknown transition '{transition}' — scene skipped")
                return None

            emotion = str(line.get("emotion", "")).upper() or None
            mouth = str(line.get("mouth", "")).upper() or None
            dialogue = str(line.get("dialogue", ""))

            script.append({
                "character": character,
                "transition": transition,
                "emotion": emotion,
                "mouth": mouth,
                "dialogue": dialogue,
                "duration": line.get("duration"),
                "position": str(line.get("position", "")).lower() or None,
            })
        return script

    # ------------------------------------------------------------------
    # Character image loading
    # ------------------------------------------------------------------

    def _scan_character_folder(self, character_id: str) -> dict:
        """Build a lookup dict for a character's images."""
        if character_id in self._character_lookups:
            return self._character_lookups[character_id]

        image_folder = _resolve_path(self.image_folder)
        char_dir = os.path.join(image_folder, character_id)
        lookup: dict[tuple[str, str, str], str] = {}

        if os.path.isdir(char_dir):
            for name in os.listdir(char_dir):
                lower = name.lower()
                if not lower.endswith(".png"):
                    continue
                stem = name[:-4]
                parts = stem.split("_")
                if len(parts) >= 4 and parts[0].upper() == character_id.upper():
                    facing = parts[1].upper()
                    emotion = parts[2].upper()
                    mouth = parts[3].upper()
                    if facing in {"LEFT", "RIGHT"} and mouth in MOUTH_STATES:
                        lookup[(facing, emotion, mouth)] = os.path.join(char_dir, name)

        self._character_lookups[character_id] = lookup
        return lookup

    def _find_character_image(self, character_id: str, facing: str,
                              emotion: str, mouth: str) -> Optional[str]:
        lookup = self._scan_character_folder(character_id)
        facing = facing.upper()
        emotion = emotion.upper()
        mouth = mouth.upper()

        candidates = [
            (facing, emotion, mouth),
            (facing, emotion, "SILENT"),
            (facing, self._default_emotion(character_id), mouth),
            (facing, self._default_emotion(character_id), "SILENT"),
        ]
        for key in candidates:
            if key in lookup:
                return lookup[key]

        # Fallback to any image with same facing.
        for (f, e, m), path in lookup.items():
            if f == facing:
                return path

        # Fallback to any image at all.
        if lookup:
            return next(iter(lookup.values()))

        return None

    def _default_emotion(self, character_id: str) -> str:
        defaults = self._character_defaults.get(character_id, {})
        emotion = str(defaults.get("default_emotion", "DEFAULT")).upper()
        return emotion if emotion else "DEFAULT"

    def _character_scale(self, character_id: str) -> float:
        defaults = self._character_defaults.get(character_id, {})
        return float(defaults.get("scale", 1.0))

    def _load_character_surface(self, character_id: str, facing: str,
                                emotion: str, mouth: str) -> Optional[pygame.Surface]:
        if self.manager is None:
            return None

        scale = self._character_scale(character_id)
        cache_key = (character_id, facing, emotion, mouth, scale)
        cached = self._character_surface_cache.get(cache_key)
        if cached is not None:
            return cached

        path = self._find_character_image(character_id, facing, emotion, mouth)
        if path is None:
            key = (character_id, facing, emotion, mouth)
            if key not in self._missing_logged:
                print(f"[PuppetTheatre] no image for {character_id} {facing} {emotion} {mouth}")
                self._missing_logged.add(key)
            surf = self._placeholder_surface(character_id)
            self._character_surface_cache[cache_key] = surf
            return surf

        try:
            surf = self.manager.cache.get_image(path, convert_alpha=True)
        except Exception as e:
            print(f"[PuppetTheatre] failed to load '{path}': {e}")
            surf = self._placeholder_surface(character_id)
            self._character_surface_cache[cache_key] = surf
            return surf

        if self.scale_characters:
            h = self.manager.height
            target_h = int(h * self.character_height_frac * scale)
            ih = surf.get_height()
            if ih > 0 and target_h > 0 and target_h != ih:
                scale_ratio = target_h / ih
                new_size = (max(1, int(surf.get_width() * scale_ratio)), target_h)
                surf = pygame.transform.smoothscale(surf, new_size)

        self._character_surface_cache[cache_key] = surf
        return surf

    def _placeholder_surface(self, character_id: str) -> pygame.Surface:
        """Colored rectangle with the character name when art is missing."""
        w, h = 128, 256
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        color = (180, 60, 60, 200)
        surf.fill(color)
        if self.manager is not None and self.manager.cache is not None:
            font = self.manager.cache.get_font(None, 18, bold=True)
            text = font.render(character_id[:8], True, (255, 255, 255))
            rect = text.get_rect(center=(w // 2, h // 2))
            surf.blit(text, rect)
        return surf

    # ------------------------------------------------------------------
    # Scene state machine
    # ------------------------------------------------------------------

    def _start_scene(self, index: int):
        self._scene_index = index % len(self._scenes)
        self._line_index = 0
        self._scene_t = 0.0
        self._scene_alpha = 0.0
        self._scene_state = "intro"
        self._dialogue_text = ""
        self._characters.clear()
        self._activate_scene_layers(self._scenes[self._scene_index])
        print(f"[PuppetTheatre] scene '{self._scenes[self._scene_index].title}'")

    def _activate_scene_layers(self, scene: _Scene):
        if self.manager is None:
            return
        for layer in scene.layers:
            if layer.surface is not None or layer.path is None:
                continue
            try:
                layer.surface = self.manager.cache.get_image(layer.path, convert_alpha=True)
            except Exception as e:
                print(f"[PuppetTheatre] failed to load layer '{layer.image}': {e}")
                layer.surface = None

    def _position_screen_xy(self, position_name: str) -> tuple[float, float]:
        pos = self.stage_positions.get(position_name, DEFAULT_STAGE_POSITIONS["stage_center"])
        if self.manager is None:
            return (0.0, 0.0)
        return (pos["x"] * self.manager.width, pos["y"] * self.manager.height)

    def _offscreen_start(self, transition: str, target_x: float, target_y: float) -> tuple[float, float]:
        """Compute starting position for enter/exit movements."""
        if self.manager is None:
            return (target_x, target_y)
        w, h = self.manager.width, self.manager.height
        if "LEFT" in transition:
            return (-w * 0.25, target_y)
        if "RIGHT" in transition:
            return (w * 1.25, target_y)
        if "DOWN" in transition:
            return (target_x, h * 1.25)
        if "CENTER" in transition:
            return (target_x, h * 1.1)
        return (target_x, target_y)

    def _target_from_transition(self, transition: str, position_override: Optional[str]) -> tuple[str, tuple[float, float]]:
        """Return (position_name, target_xy) for a transition."""
        # Extract position name from transition if possible.
        pos_name = position_override
        if pos_name is None:
            for name in self.stage_positions:
                if name.upper() in transition:
                    pos_name = name
                    break
        if pos_name is None:
            pos_name = "stage_center"
        return pos_name, self._position_screen_xy(pos_name)

    def _apply_script_line(self, line: dict):
        character_id = line["character"]
        transition = line["transition"]

        if not character_id:
            # Stage direction with no character: nothing to update in v1.
            return

        if character_id not in self._characters:
            defaults = self._character_defaults.get(character_id, {})
            self._characters[character_id] = _CharacterState(
                character_id,
                default_emotion=str(defaults.get("default_emotion", "DEFAULT")).upper() or "DEFAULT",
                scale=float(defaults.get("scale", 1.0)),
            )

        char = self._characters[character_id]
        char.transition = transition

        # Update emotion.
        if line["emotion"]:
            char.emotion = line["emotion"]

        # Update mouth.
        mouth = line["mouth"]
        if not mouth:
            mouth = "SPEAKING" if line["dialogue"] else "SILENT"
        char.mouth = mouth if mouth in MOUTH_STATES else "SILENT"

        # Determine target position and facing.
        pos_name, target = self._target_from_transition(transition, line["position"])
        target_x, target_y = target

        if transition in POP_TRANSITIONS:
            char.visible = True
            char.position_name = pos_name
            char.screen_x = target_x
            char.screen_y = target_y
            char.target_x = target_x
            char.target_y = target_y
            char.transition_t = 0.0
            char.transition_duration = self.pop_duration_sec
            char.pop_scale = 0.0
            # Facing from transition.
            fac = TRANSITION_FACING.get(transition)
            if fac:
                char.facing = fac
        elif transition in MOVEMENT_TRANSITIONS:
            start = self._offscreen_start(transition, target_x, target_y)
            if transition.startswith("MOVE_") and char.visible:
                start = (char.screen_x, char.screen_y)
            char.visible = True
            char.position_name = pos_name
            char.start_x, char.start_y = start
            char.target_x, char.target_y = target_x, target_y
            char.screen_x, char.screen_y = start
            char.transition_t = 0.0
            char.transition_duration = self.transition_duration_sec
            fac = TRANSITION_FACING.get(transition)
            if fac:
                char.facing = fac
        elif transition in INSTANT_TRANSITIONS:
            if transition == "TURN_LEFT":
                char.facing = "LEFT"
            elif transition == "TURN_RIGHT":
                char.facing = "RIGHT"
            elif transition == "JUMP":
                char.jump_t = 0.3
            elif transition == "SHAKE":
                char.jump_t = 0.4
            # NONE: no movement.

    # ------------------------------------------------------------------
    # Update / frame loop
    # ------------------------------------------------------------------

    def update(self, dt: float):
        if not self._scenes or self.manager is None:
            return

        self._scene_t += dt
        scene = self._scenes[self._scene_index]

        # Update character transitions/animations.
        for char in self._characters.values():
            if char.transition_duration > 0 and char.transition_t < char.transition_duration:
                char.transition_t += dt
                t = min(1.0, char.transition_t / char.transition_duration)
                eased = _ease(t)
                char.screen_x = char.start_x + (char.target_x - char.start_x) * eased
                char.screen_y = char.start_y + (char.target_y - char.start_y) * eased
                if char.pop_scale < 1.0:
                    char.pop_scale = min(1.0, _ease(t * 1.5))
            if char.transition in EXIT_TRANSITIONS and char.transition_t >= char.transition_duration:
                char.visible = False
            if char.jump_t > 0:
                char.jump_t = max(0.0, char.jump_t - dt)

        # Scene-wide fade in/out handling.
        trans_in_dur = float(scene.transition_in.get("duration", 0.5)) if isinstance(scene.transition_in, dict) else 0.5
        trans_out_dur = float(scene.transition_out.get("duration", 0.5)) if isinstance(scene.transition_out, dict) else 0.5

        # When looping back to the start, the last scene always fades to black
        # using loop_fade_to_black_sec regardless of its configured transition_out.
        is_last_scene = self._scene_index == len(self._scenes) - 1
        if is_last_scene:
            trans_out_dur = self.loop_fade_to_black_sec

        if self._scene_state == "intro":
            self._scene_alpha = min(1.0, self._scene_t / max(trans_in_dur, 0.001))
            if self._scene_t >= trans_in_dur:
                self._scene_alpha = 1.0
                if scene.title or scene.description:
                    self._scene_state = "description_in"
                    self._scene_t = 0.0
                else:
                    self._scene_state = "pause_before_script"
                    self._scene_t = 0.0

        elif self._scene_state == "description_in":
            if self._scene_t >= self.scene_description_fade_in_sec:
                self._scene_state = "description_hold"
                self._scene_t = 0.0

        elif self._scene_state == "description_hold":
            if self._scene_t >= self.scene_description_hold_sec:
                self._scene_state = "description_out"
                self._scene_t = 0.0

        elif self._scene_state == "description_out":
            if self._scene_t >= self.scene_description_fade_out_sec:
                self._scene_state = "pause_before_script"
                self._scene_t = 0.0

        elif self._scene_state == "pause_before_script":
            if self._scene_t >= self.scene_pause_before_script_sec:
                self._scene_state = "script_line"
                self._scene_t = 0.0
                self._line_index = 0

        elif self._scene_state == "script_line":
            if self._line_index < len(scene.script):
                line = scene.script[self._line_index]
                self._apply_script_line(line)
                self._dialogue_text = line["dialogue"]
                self._line_index += 1
                if self._dialogue_text:
                    self._scene_state = "dialogue_in"
                else:
                    self._scene_state = "dialogue_hold"
                self._scene_t = 0.0
            else:
                self._scene_state = "pause_after_script"
                self._scene_t = 0.0

        elif self._scene_state == "dialogue_in":
            if self._scene_t >= self.dialogue_fade_in_sec:
                self._scene_state = "dialogue_hold"
                self._scene_t = 0.0

        elif self._scene_state == "dialogue_hold":
            hold = self.dialogue_hold_sec + self.dialogue_hold_extra_per_word * _word_count(self._dialogue_text)
            # If no dialogue, just a brief beat so transitions register visually.
            if not self._dialogue_text:
                hold = 0.4
            if self._scene_t >= hold:
                if self._dialogue_text:
                    self._scene_state = "dialogue_out"
                else:
                    self._scene_state = "script_line"
                self._scene_t = 0.0

        elif self._scene_state == "dialogue_out":
            if self._scene_t >= self.dialogue_fade_out_sec:
                self._scene_state = "script_line"
                self._scene_t = 0.0
                self._dialogue_text = ""

        elif self._scene_state == "pause_after_script":
            if self._scene_t >= self.scene_pause_after_script_sec:
                self._scene_state = "outro"
                self._scene_t = 0.0

        elif self._scene_state == "outro":
            self._scene_alpha = max(0.0, 1.0 - (self._scene_t / max(trans_out_dur, 0.001)))
            if self._scene_t >= trans_out_dur:
                if is_last_scene:
                    # End of config: hold on black, then loop to scene 0.
                    self._scene_state = "loop_black"
                    self._scene_t = 0.0
                    self._scene_alpha = 0.0
                else:
                    self._start_scene(self._scene_index + 1)

        elif self._scene_state == "loop_black":
            self._scene_alpha = 0.0
            if self._scene_t >= self.loop_black_hold_sec:
                self._start_scene(0)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, screen: pygame.Surface):
        if not self._scenes or self.manager is None:
            screen.fill(self.background_rgb)
            return

        scene = self._scenes[self._scene_index]
        screen.fill(scene.background_rgb)

        # Draw background layer(s) first, then characters, then overlay layers
        # on top so foreground props cover the actors.
        for layer in scene.layers:
            if layer.surface is None:
                continue
            if layer.depth == CHARACTER_LAYER or layer.depth > CHARACTER_LAYER:
                continue
            self._draw_layer(screen, layer)

        # Draw characters.
        self._draw_characters(screen)

        # Draw overlay layers on top of characters.
        for layer in scene.layers:
            if layer.surface is None:
                continue
            if layer.depth <= CHARACTER_LAYER:
                continue
            self._draw_layer(screen, layer)

        # Description overlay.
        if self._scene_state in ("description_in", "description_hold", "description_out"):
            self._draw_description(screen, scene)

        # Dialogue overlay.
        if self._scene_state in ("dialogue_in", "dialogue_hold", "dialogue_out"):
            self._draw_dialogue(screen)

        # Scene-wide fade.
        if self._scene_alpha < 1.0:
            alpha = int(255 * (1.0 - self._scene_alpha))
            overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, alpha))
            screen.blit(overlay, (0, 0))

    def _draw_layer(self, target: pygame.Surface, layer: _Layer):
        surf = layer.surface
        if surf is None:
            return
        w, h = target.get_size()
        ax = w * 0.5
        # Overlay layers (depth 2 and 3) are anchored to the bottom of the
        # screen so foreground props always sit on the "floor" of the scene.
        anchor_bottom = layer.depth > CHARACTER_LAYER

        if layer.motion in ("pan_left", "pan_right"):
            factor = self.layer_factors[layer.depth]
            speed = self.base_amplitude * factor * layer.speed * 2.0
            span = surf.get_width()
            shift = _pan_offset(self._scene_t, span, speed, 0.0)
            cx = ax - shift if layer.motion == "pan_left" else ax + shift
            second = cx + span if layer.motion == "pan_left" else cx - span
            if anchor_bottom:
                self._blit_bottom_centered(target, surf, cx, h)
                self._blit_bottom_centered(target, surf, second, h)
            else:
                self._blit_centered(target, surf, cx, h * 0.5)
                self._blit_centered(target, surf, second, h * 0.5)
        else:
            amp = self.base_amplitude * self.layer_factors[layer.depth] * layer.depth_factor
            period = 6.0 / max(0.1, self.layer_factors[layer.depth])
            dx, dy = _oscillate_offset(layer.motion, self._scene_t, period, amp, layer.speed)
            if anchor_bottom:
                self._blit_bottom_centered(target, surf, ax + dx, h + dy)
            else:
                self._blit_centered(target, surf, ax + dx, h * 0.5 + dy)

    @staticmethod
    def _blit_centered(target: pygame.Surface, surf: pygame.Surface, cx: float, cy: float):
        rect = surf.get_rect(center=(int(cx), int(cy)))
        target.blit(surf, rect)

    @staticmethod
    def _blit_bottom_centered(target: pygame.Surface, surf: pygame.Surface, cx: float, bottom: float):
        rect = surf.get_rect(midbottom=(int(cx), int(bottom)))
        target.blit(surf, rect)

    def _draw_characters(self, target: pygame.Surface):
        for char in self._characters.values():
            if not char.visible:
                continue

            # Compute sprite transform.
            x = char.screen_x
            y = char.screen_y
            if char.jump_t > 0:
                # Small vertical bounce for JUMP/SHAKE.
                bounce = abs(math.sin(char.jump_t * 20.0)) * 20.0
                y -= bounce
            if char.transition in POP_TRANSITIONS and char.pop_scale < 1.0:
                # Pop scale handled in draw by scaling surface.
                pass

            surf = self._load_character_surface(
                char.character_id, char.facing, char.emotion, char.mouth
            )
            if surf is None:
                continue

            # Apply pop scale if popping.
            if char.transition in POP_TRANSITIONS and char.pop_scale < 1.0:
                scale = max(0.1, char.pop_scale)
                size = (max(1, int(surf.get_width() * scale)), max(1, int(surf.get_height() * scale)))
                surf = pygame.transform.smoothscale(surf, size)

            rect = surf.get_rect(midbottom=(int(x), int(y)))
            target.blit(surf, rect)

    def _draw_description(self, target: pygame.Surface, scene: _Scene):
        if self.manager is None:
            return
        alpha = 1.0
        if self._scene_state == "description_in":
            dur = max(0.001, self.scene_description_fade_in_sec)
            alpha = min(1.0, self._scene_t / dur)
        elif self._scene_state == "description_out":
            dur = max(0.001, self.scene_description_fade_out_sec)
            alpha = max(0.0, 1.0 - (self._scene_t / dur))

        if alpha <= 0.0:
            return

        w, h = target.get_size()
        font = self.manager.cache.get_font(None, self.description_font_size, bold=True)
        title_surf = font.render(scene.title, True, self.dialogue_fg_rgb)
        title_surf.set_alpha(int(255 * alpha))
        title_rect = title_surf.get_rect(center=(w // 2, int(h * 0.35)))
        target.blit(title_surf, title_rect)

        if scene.description:
            desc_font = self.manager.cache.get_font(None, max(16, self.description_font_size - 12))
            desc_surf = desc_font.render(scene.description, True, self.dialogue_fg_rgb)
            desc_surf.set_alpha(int(255 * alpha))
            desc_rect = desc_surf.get_rect(center=(w // 2, int(h * 0.42)))
            target.blit(desc_surf, desc_rect)

    def _draw_dialogue(self, target: pygame.Surface):
        if self.manager is None:
            return
        alpha = 1.0
        if self._scene_state == "dialogue_in":
            dur = max(0.001, self.dialogue_fade_in_sec)
            alpha = min(1.0, self._scene_t / dur)
        elif self._scene_state == "dialogue_out":
            dur = max(0.001, self.dialogue_fade_out_sec)
            alpha = max(0.0, 1.0 - (self._scene_t / dur))

        if alpha <= 0.0 or not self._dialogue_text:
            return

        w, h = target.get_size()
        font = self.manager.cache.get_font(None, self.dialogue_font_size)
        margin = self.dialogue_box_margin
        max_width = w - margin * 4
        lines = self._wrap_text(self._dialogue_text, font, max_width)

        line_height = font.get_height()
        text_height = len(lines) * line_height
        box_height = text_height + margin * 2
        box_y = h - box_height - margin * 2

        bar = pygame.Surface((w, box_height), pygame.SRCALPHA)
        bg = self.dialogue_bg_rgb + (int(self.dialogue_box_alpha * alpha),)
        bar.fill(bg)
        target.blit(bar, (0, box_y))

        y = box_y + margin
        for line in lines:
            line_surf = font.render(line, True, self.dialogue_fg_rgb)
            line_surf.set_alpha(int(255 * alpha))
            line_rect = line_surf.get_rect(center=(w // 2, y + line_height // 2))
            target.blit(line_surf, line_rect)
            y += line_height

    @staticmethod
    def _wrap_text(text: str, font, max_width: int) -> list[str]:
        words = text.split()
        lines = []
        current = ""
        for word in words:
            test = f"{current} {word}".strip()
            if font.size(test)[0] <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines if lines else [text]

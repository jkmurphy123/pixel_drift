# modes/animated_scene_mode.py
#
# Multi-plane parallax "animated scene" mode. See ANIMATED_SCENE_DESIGN.md.
#
# A scene is a stack of up to 5 PNG layers drawn back-to-front. Each layer
# has a named motion; how FAR and how FAST it moves is derived from its
# depth index (back = small/slow, front = large/fast), which is what
# produces the parallax effect. Scenes are pure config — new artwork and
# new scenes are added in animated_scenes.json without touching code.
#
# Config (instance, modes_config.json):
#   scenes_file     (required) path to scene definitions JSON
#   image_folder    (required) base folder for all layer PNGs
#   scene_duration  seconds per scene (default 45)
#   shuffle         random scene order (default true)
#   start_scene     force a named scene first (debug; default null)
#   base_amplitude  px of travel for the FRONT layer (default 60)
#   layer_factors   per-depth amplitude multipliers (default below)
#   background_rgb  fill color behind layer 0 (default [0,0,0])
#   scale_layers    "none" (default) or "cover"
#   crossfade_sec   fade time between scenes (default 1.0)
#   motion_period   seconds per oscillation cycle at factor 1.0 (default 8)
#   base_pan_speed  px/sec scroll speed at factor 1.0 (default 40)

import json
import math
import os
import random

import pygame

# Repo root (this file lives in modes/). Relative config paths resolve here
# so the mode works regardless of the controller's cwd.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MAX_LAYERS = 5
DEFAULT_LAYER_FACTORS = [0.10, 0.25, 0.50, 0.75, 1.00]

OSCILLATING_MOTIONS = {"bob", "sway", "drift_circle", "random"}
PANNING_MOTIONS = {"pan_left", "pan_right", "pan_up", "pan_down"}
ALL_MOTIONS = OSCILLATING_MOTIONS | PANNING_MOTIONS | {"static"}

# Irrational-ish multipliers for the deterministic "random" wander (D4):
# two incommensurate sines per axis never repeat on any human timescale
# and need no RNG state, which keeps tests exact.
_RAND_X = ((1.000, 0.6, 1.7), (1.618, 0.4, 4.2))
_RAND_Y = ((1.310, 0.6, 2.9), (0.730, 0.4, 0.5))


def depth_slots(n_layers: int) -> list[int]:
    """Spread n layers across depth slots 0..MAX_LAYERS-1 (D3).

    5 -> [0,1,2,3,4], 3 -> [0,2,4], 2 -> [0,4], 1 -> [2].
    """
    if n_layers <= 0:
        return []
    if n_layers == 1:
        return [MAX_LAYERS // 2]
    top = MAX_LAYERS - 1
    return [round(i * top / (n_layers - 1)) for i in range(n_layers)]


def layer_amplitude(base_amplitude: float, factors: list[float],
                    depth: int, amplitude_scale: float = 1.0) -> float:
    """The core parallax rule: amplitude derives from depth, not config."""
    depth = max(0, min(depth, len(factors) - 1))
    return base_amplitude * factors[depth] * amplitude_scale


def layer_period(motion_period: float, factors: list[float], depth: int) -> float:
    """Front layers oscillate faster as well as farther (D2)."""
    depth = max(0, min(depth, len(factors) - 1))
    return motion_period / (0.5 + factors[depth])


def oscillate_offset(motion: str, t: float, period: float, amplitude: float,
                     speed: float = 1.0, phase: float = 0.0) -> tuple[float, float]:
    """(dx, dy) for oscillating motions at elapsed time t. Deterministic."""
    if period <= 0 or motion not in OSCILLATING_MOTIONS:
        return (0.0, 0.0)
    w = 2.0 * math.pi * speed / period
    p = 2.0 * math.pi * phase
    if motion == "bob":
        return (0.0, amplitude * math.sin(w * t + p))
    if motion == "sway":
        return (amplitude * math.sin(w * t + p), 0.0)
    if motion == "drift_circle":
        return (amplitude * math.cos(w * t + p), amplitude * math.sin(w * t + p))
    # "random": smooth wander, sum of two sines per axis
    dx = sum(a * math.sin(w * t * m + p + o) for m, a, o in _RAND_X)
    dy = sum(a * math.sin(w * t * m + p + o) for m, a, o in _RAND_Y)
    return (amplitude * dx, amplitude * dy)


def pan_shift(t: float, span: int, pan_speed: float, phase: float = 0.0) -> float:
    """Wrapped pan offset in [0, span). span is the image width/height."""
    if span <= 0:
        return 0.0
    return (pan_speed * t + phase * span) % span


def _resolve_path(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(BASE_DIR, path)


class _Layer:
    __slots__ = ("image", "path", "x", "y", "motion", "speed",
                 "amplitude_scale", "phase", "depth", "surface")

    def __init__(self, spec: dict, image_folder: str, depth: int):
        self.image = spec["image"]
        self.path = os.path.join(image_folder, self.image)
        self.x = float(spec["x"])
        self.y = float(spec["y"])
        self.motion = spec["motion"]
        self.speed = float(spec.get("speed", 1.0))
        self.amplitude_scale = float(spec.get("amplitude_scale", 1.0))
        self.phase = float(spec.get("phase", 0.0))
        self.depth = depth
        self.surface = None  # loaded on scene activation, dropped on exit


class _Scene:
    __slots__ = ("name", "base_amplitude", "layers")

    def __init__(self, name, base_amplitude, layers):
        self.name = name
        self.base_amplitude = base_amplitude
        self.layers = layers


class AnimatedSceneMode:
    def __init__(self, config: dict):
        # __init__ does NO I/O: the smoke tests construct every configured
        # mode without a display, and kiosk hosts may override paths via
        # modes_config.local.json. Everything loads in enter().
        self.scenes_file = config.get("scenes_file", "")
        self.image_folder = config.get("image_folder", "")
        self.scene_duration = float(config.get("scene_duration", 45))
        self.shuffle = bool(config.get("shuffle", True))
        self.start_scene = config.get("start_scene")
        self.base_amplitude = float(config.get("base_amplitude", 60))
        self.background_rgb = tuple(config.get("background_rgb", [0, 0, 0]))
        self.scale_layers = str(config.get("scale_layers", "none")).lower()
        self.crossfade_sec = float(config.get("crossfade_sec", 1.0))
        self.motion_period = float(config.get("motion_period", 8.0))
        self.base_pan_speed = float(config.get("base_pan_speed", 40))

        factors = config.get("layer_factors", DEFAULT_LAYER_FACTORS)
        if (not isinstance(factors, list) or len(factors) != MAX_LAYERS
                or not all(isinstance(f, (int, float)) for f in factors)):
            factors = DEFAULT_LAYER_FACTORS
        self.layer_factors = [float(f) for f in factors]

        self.manager = None
        self._scenes = []
        self._order = []          # indices into _scenes in playback order
        self._order_pos = 0
        self._scene = None        # current _Scene
        self._scene_t = 0.0
        self._upcoming = None     # pre-activated next _Scene
        self._incoming = None     # scene fading in right now
        self._fade_t = 0.0
        self._fade_surf = None

    # ---------- lifecycle ----------

    def enter(self, manager):
        self.manager = manager
        self._scenes = self._load_scenes()
        self._order = list(range(len(self._scenes)))
        if self.shuffle:
            random.shuffle(self._order)
        if self.start_scene:
            for pos, idx in enumerate(self._order):
                if self._scenes[idx].name == self.start_scene:
                    self._order.insert(0, self._order.pop(pos))
                    break
        self._order_pos = 0
        self._scene_t = 0.0
        self._incoming = None
        self._fade_t = 0.0

        if not self._scenes:
            print("[AnimatedScene] no usable scenes — rendering background only")
            return

        self._scene = self._scenes[self._order[0]]
        self._activate(self._scene)
        print(f"[AnimatedScene] scene '{self._scene.name}' "
              f"({len(self._scenes)} scene(s) loaded)")
        self._prepare_upcoming()

    def exit(self):
        # Drop every surface reference so the cache can reclaim memory.
        for scene in self._scenes:
            for layer in scene.layers:
                layer.surface = None
        self._scenes = []
        self._order = []
        self._scene = None
        self._upcoming = None
        self._incoming = None
        self._fade_surf = None
        self.manager = None

    def handle_event(self, event):
        pass

    # ---------- scene file loading / validation ----------

    def _load_scenes(self) -> list[_Scene]:
        path = _resolve_path(self.scenes_file)
        image_folder = _resolve_path(self.image_folder)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[AnimatedScene] cannot read scenes file '{path}': {e}")
            return []

        raw_scenes = data.get("scenes")
        if not isinstance(raw_scenes, list):
            print(f"[AnimatedScene] '{path}' has no 'scenes' list")
            return []

        scenes = []
        for i, raw in enumerate(raw_scenes):
            scene = self._validate_scene(raw, i, image_folder)
            if scene is not None:
                scenes.append(scene)
        return scenes

    def _validate_scene(self, raw, index: int, image_folder: str) -> _Scene | None:
        label = f"scene[{index}]"
        if not isinstance(raw, dict):
            print(f"[AnimatedScene] {label}: not an object — skipped")
            return None
        name = str(raw.get("name", f"scene_{index}"))
        label = f"scene '{name}'"

        raw_layers = raw.get("layers")
        if not isinstance(raw_layers, list) or not (1 <= len(raw_layers) <= MAX_LAYERS):
            print(f"[AnimatedScene] {label}: needs 1..{MAX_LAYERS} layers — skipped")
            return None

        slots = depth_slots(len(raw_layers))
        layers = []
        for li, spec in enumerate(raw_layers):
            layer = self._validate_layer(spec, label, li, image_folder, slots[li])
            if layer is None:
                return None  # one bad layer invalidates the scene
            layers.append(layer)

        base_amp = float(raw.get("base_amplitude", self.base_amplitude))
        return _Scene(name, base_amp, layers)

    def _validate_layer(self, spec, scene_label: str, li: int,
                        image_folder: str, depth: int) -> _Layer | None:
        label = f"{scene_label} layer {li}"
        if not isinstance(spec, dict):
            print(f"[AnimatedScene] {label}: not an object — scene skipped")
            return None
        image = spec.get("image")
        motion = spec.get("motion")
        if not image or not isinstance(image, str):
            print(f"[AnimatedScene] {label}: missing 'image' — scene skipped")
            return None
        if motion not in ALL_MOTIONS:
            print(f"[AnimatedScene] {label}: unknown motion '{motion}' "
                  f"(valid: {sorted(ALL_MOTIONS)}) — scene skipped")
            return None
        try:
            float(spec["x"]); float(spec["y"])
        except (KeyError, TypeError, ValueError):
            print(f"[AnimatedScene] {label}: 'x'/'y' must be numbers — scene skipped")
            return None
        if not os.path.exists(os.path.join(image_folder, image)):
            print(f"[AnimatedScene] {label}: image '{image}' not found "
                  f"in {image_folder} — scene skipped")
            return None
        try:
            return _Layer(spec, image_folder, depth)
        except Exception as e:
            print(f"[AnimatedScene] {label}: {e} — scene skipped")
            return None

    # ---------- activation (image loading) ----------

    def _activate(self, scene: _Scene):
        """Load layer surfaces. Called when a scene becomes current or is
        prepared as upcoming, so a scene switch never hits disk mid-fade."""
        if self.manager is None:
            return
        w, h = self.manager.screen.get_size()
        for layer in scene.layers:
            if layer.surface is not None:
                continue
            try:
                surf = self.manager.cache.get_image(layer.path, convert_alpha=True)
                if self.scale_layers == "cover":
                    surf = self._scale_cover(surf, w, h)
                layer.surface = surf
            except Exception as e:
                # Cache load can still fail (corrupt PNG etc.). Render skips
                # None surfaces, so one bad layer degrades instead of crashing.
                print(f"[AnimatedScene] failed to load '{layer.image}': {e}")
                layer.surface = None

    @staticmethod
    def _scale_cover(surf: pygame.Surface, w: int, h: int) -> pygame.Surface:
        iw, ih = surf.get_size()
        if iw <= 0 or ih <= 0:
            return surf
        scale = max(w / iw, h / ih)
        new_size = (max(1, int(iw * scale)), max(1, int(ih * scale)))
        if new_size == (iw, ih):
            return surf
        return pygame.transform.smoothscale(surf, new_size)

    def _prepare_upcoming(self):
        if len(self._scenes) < 2:
            self._upcoming = None
            return
        next_pos = (self._order_pos + 1) % len(self._order)
        self._upcoming = self._scenes[self._order[next_pos]]
        self._activate(self._upcoming)

    # ---------- frame loop ----------

    def update(self, dt: float):
        if self._scene is None:
            return
        self._scene_t += dt

        if self._incoming is not None:
            self._fade_t += dt
            if self._fade_t >= self.crossfade_sec:
                self._scene = self._incoming
                # Motion and the duration clock both keep the fade time
                # already elapsed, so the new scene doesn't "restart".
                self._scene_t = self._fade_t
                self._incoming = None
                self._order_pos = (self._order_pos + 1) % len(self._order)
                print(f"[AnimatedScene] scene '{self._scene.name}'")
                self._prepare_upcoming()
        elif self._upcoming is not None and self._scene_t >= self.scene_duration:
            self._incoming = self._upcoming
            self._upcoming = None
            self._fade_t = 0.0

    def render(self, screen: pygame.Surface):
        if self._scene is None:
            screen.fill(self.background_rgb)
            return

        self._draw_scene(screen, self._scene, self._scene_t)

        if self._incoming is not None:
            if self._fade_surf is None or self._fade_surf.get_size() != screen.get_size():
                self._fade_surf = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
            self._draw_scene(self._fade_surf, self._incoming, self._fade_t)
            alpha = int(255 * min(1.0, self._fade_t / max(self.crossfade_sec, 0.01)))
            self._fade_surf.set_alpha(alpha)
            screen.blit(self._fade_surf, (0, 0))

    # ---------- drawing ----------

    def _draw_scene(self, target: pygame.Surface, scene: _Scene, t: float):
        target.fill(self.background_rgb)
        w, h = target.get_size()
        for layer in scene.layers:
            if layer.surface is None:
                continue
            surf = layer.surface
            ax, ay = layer.x * w, layer.y * h

            if layer.motion in PANNING_MOTIONS:
                factor = self.layer_factors[layer.depth]
                pan_speed = self.base_pan_speed * factor * layer.speed
                if layer.motion in ("pan_left", "pan_right"):
                    span = surf.get_width()
                    shift = pan_shift(t, span, pan_speed, layer.phase)
                    cx = ax - shift if layer.motion == "pan_left" else ax + shift
                    # Two tiles always cover the screen when span >= screen
                    # width (pan artwork is authored as a wide strip).
                    second = cx + span if layer.motion == "pan_left" else cx - span
                    self._blit_centered(target, surf, cx, ay)
                    self._blit_centered(target, surf, second, ay)
                else:
                    span = surf.get_height()
                    shift = pan_shift(t, span, pan_speed, layer.phase)
                    cy = ay - shift if layer.motion == "pan_up" else ay + shift
                    second = cy + span if layer.motion == "pan_up" else cy - span
                    self._blit_centered(target, surf, ax, cy)
                    self._blit_centered(target, surf, ax, second)
            else:
                amp = layer_amplitude(scene.base_amplitude, self.layer_factors,
                                      layer.depth, layer.amplitude_scale)
                period = layer_period(self.motion_period, self.layer_factors,
                                      layer.depth)
                dx, dy = oscillate_offset(layer.motion, t, period, amp,
                                          layer.speed, layer.phase)
                self._blit_centered(target, surf, ax + dx, ay + dy)

    @staticmethod
    def _blit_centered(target: pygame.Surface, surf: pygame.Surface, cx: float, cy: float):
        rect = surf.get_rect(center=(int(cx), int(cy)))
        target.blit(surf, rect)

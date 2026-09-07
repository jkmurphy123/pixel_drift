# tests/test_animated_scene.py
#
# Headless tests for the multi-plane parallax mode (see ANIMATED_SCENE_DESIGN.md).
# Motion is computed from elapsed time, never accumulated per-frame, so every
# assertion here is exact — no RNG, no float drift beyond math.sin precision.
#
# Run headless:
#   SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests/test_animated_scene.py -q

import json
import math
import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

from core.cache import ResourceCache  # noqa: E402
from modes.animated_scene_mode import (  # noqa: E402
    ALL_MOTIONS,
    DEFAULT_LAYER_FACTORS,
    AnimatedSceneMode,
    depth_slots,
    layer_amplitude,
    layer_period,
    oscillate_offset,
    pan_shift,
)


@pytest.fixture(scope="session", autouse=True)
def pygame_init():
    pygame.init()
    # convert_alpha() needs a video mode; the dummy driver provides one.
    pygame.display.set_mode((1, 1))
    yield
    pygame.quit()


class FakeManager:
    """Minimal stand-in for ModeManager: screen + cache are all the mode touches."""

    def __init__(self, w=960, h=540):
        self.screen = pygame.Surface((w, h))
        self.cache = ResourceCache()
        self.width = w
        self.height = h


def _write_png(path, size=(64, 48), color=(200, 100, 50, 255)):
    surf = pygame.Surface(size, pygame.SRCALPHA)
    surf.fill(color)
    pygame.image.save(surf, str(path))


def _make_project(tmp_path, scenes, image_names=("a.png", "b.png", "c.png")):
    """Create a scenes file + dummy PNGs under tmp_path; return config dict."""
    img_dir = tmp_path / "art"
    img_dir.mkdir()
    for name in image_names:
        _write_png(img_dir / name)
    scenes_file = tmp_path / "scenes.json"
    scenes_file.write_text(json.dumps({"scenes": scenes}))
    return {
        "scenes_file": str(scenes_file),
        "image_folder": str(img_dir),
        "shuffle": False,
        "scene_duration": 10,
        "crossfade_sec": 1.0,
    }


# ---------- pure math: parallax model ----------

def test_depth_slots_spread():
    assert depth_slots(5) == [0, 1, 2, 3, 4]
    assert depth_slots(3) == [0, 2, 4]
    assert depth_slots(2) == [0, 4]
    assert depth_slots(1) == [2]
    assert depth_slots(0) == []


def test_amplitude_model_front_and_back():
    f = DEFAULT_LAYER_FACTORS
    # front layer gets the full base amplitude
    assert layer_amplitude(60, f, 4) == pytest.approx(60.0)
    # back layer gets 10%
    assert layer_amplitude(60, f, 0) == pytest.approx(6.0)
    # amplitude_scale multiplies on top
    assert layer_amplitude(60, f, 4, 1.3) == pytest.approx(78.0)


def test_amplitude_monotonic_with_depth():
    f = DEFAULT_LAYER_FACTORS
    amps = [layer_amplitude(60, f, d) for d in range(5)]
    assert amps == sorted(amps)


def test_front_layers_move_faster():
    f = DEFAULT_LAYER_FACTORS
    # shorter period = faster oscillation
    assert layer_period(8.0, f, 4) < layer_period(8.0, f, 0)


# ---------- pure math: motion functions ----------

def test_bob_is_exact_sine():
    period, amp = 8.0, 50.0
    assert oscillate_offset("bob", 0.0, period, amp) == (0.0, pytest.approx(0.0))
    dx, dy = oscillate_offset("bob", period / 4, period, amp)
    assert dx == 0.0
    assert dy == pytest.approx(amp)
    _, dy = oscillate_offset("bob", period / 2, period, amp)
    assert dy == pytest.approx(0.0, abs=1e-9)


def test_sway_only_moves_x():
    dx, dy = oscillate_offset("sway", 2.0, 8.0, 50.0)
    assert dy == 0.0
    assert dx == pytest.approx(50.0)  # t = period/4 -> sin(pi/2) = 1


def test_static_and_unknown_give_zero():
    assert oscillate_offset("static", 3.0, 8.0, 50.0) == (0.0, 0.0)
    assert oscillate_offset("nonsense", 3.0, 8.0, 50.0) == (0.0, 0.0)


def test_random_is_deterministic_and_bounded():
    a = oscillate_offset("random", 3.7, 8.0, 50.0)
    b = oscillate_offset("random", 3.7, 8.0, 50.0)
    assert a == b  # same t -> same offset, no RNG state
    for t in (0.1, 1.3, 5.9, 42.42):
        dx, dy = oscillate_offset("random", t, 8.0, 50.0)
        assert abs(dx) <= 50.0 + 1e-9
        assert abs(dy) <= 50.0 + 1e-9


def test_phase_shifts_cycle():
    # half-cycle phase flips the sign at t=0
    _, dy0 = oscillate_offset("bob", 0.0, 8.0, 50.0, phase=0.0)
    _, dy5 = oscillate_offset("bob", 0.0, 8.0, 50.0, phase=0.5)
    assert dy0 == pytest.approx(0.0)
    assert dy5 == pytest.approx(0.0, abs=1e-9) or dy5 == pytest.approx(0.0)
    dx0, _ = oscillate_offset("sway", 0.0, 8.0, 50.0, phase=0.25)
    assert dx0 == pytest.approx(50.0)


def test_pan_shift_wraps():
    assert 0.0 <= pan_shift(3.0, 200, 40.0) < 200
    assert pan_shift(0.0, 200, 40.0) == 0.0
    assert pan_shift(5.0, 200, 40.0) == pytest.approx(0.0)  # exactly one wrap
    assert pan_shift(2.5, 200, 40.0) == pytest.approx(100.0)
    assert pan_shift(1.0, 0, 40.0) == 0.0  # degenerate span guard


# ---------- scene file validation ----------

def test_unknown_motion_skips_scene(tmp_path, capsys):
    cfg = _make_project(tmp_path, [{
        "name": "bad",
        "layers": [{"image": "a.png", "x": 0.5, "y": 0.5, "motion": "teleport"}],
    }])
    mode = AnimatedSceneMode(cfg)
    mode.enter(FakeManager())
    assert mode._scenes == []
    assert "unknown motion" in capsys.readouterr().out


def test_missing_image_skips_scene(tmp_path, capsys):
    cfg = _make_project(tmp_path, [{
        "name": "ghost",
        "layers": [{"image": "not_there.png", "x": 0.5, "y": 0.5, "motion": "bob"}],
    }])
    mode = AnimatedSceneMode(cfg)
    mode.enter(FakeManager())
    assert mode._scenes == []
    assert "not found" in capsys.readouterr().out


def test_too_many_layers_skips_scene(tmp_path, capsys):
    layers = [{"image": "a.png", "x": 0.5, "y": 0.5, "motion": "sway"} for _ in range(6)]
    cfg = _make_project(tmp_path, [{"name": "fat", "layers": layers}])
    mode = AnimatedSceneMode(cfg)
    mode.enter(FakeManager())
    assert mode._scenes == []
    assert "1..5" in capsys.readouterr().out


def test_missing_scenes_file_renders_background(tmp_path, capsys):
    cfg = {"scenes_file": str(tmp_path / "nope.json"), "image_folder": str(tmp_path)}
    mode = AnimatedSceneMode(cfg)
    mgr = FakeManager()
    mode.enter(mgr)
    mode.render(mgr.screen)  # must not raise
    assert mode._scenes == []


def test_three_layer_scene_spreads_depth(tmp_path):
    cfg = _make_project(tmp_path, [{
        "name": "trio",
        "layers": [
            {"image": "a.png", "x": 0.5, "y": 0.3, "motion": "static"},
            {"image": "b.png", "x": 0.5, "y": 0.6, "motion": "bob"},
            {"image": "c.png", "x": 0.5, "y": 0.9, "motion": "sway"},
        ],
    }])
    mode = AnimatedSceneMode(cfg)
    mode.enter(FakeManager())
    assert [l.depth for l in mode._scenes[0].layers] == [0, 2, 4]


# ---------- integration: lifecycle + frames ----------

def test_full_lifecycle_120_frames(tmp_path):
    cfg = _make_project(tmp_path, [{
        "name": "demo",
        "layers": [
            {"image": "a.png", "x": 0.5, "y": 0.4, "motion": "static"},
            {"image": "b.png", "x": 0.5, "y": 0.6, "motion": "bob"},
            {"image": "c.png", "x": 0.5, "y": 0.8, "motion": "pan_left"},
        ],
    }])
    mode = AnimatedSceneMode(cfg)
    mgr = FakeManager()
    mode.enter(mgr)
    assert mode._scene is not None
    assert all(l.surface is not None for l in mode._scene.layers)

    for _ in range(120):
        mode.update(1 / 60)
        mode.render(mgr.screen)

    mode.exit()
    assert mode._scene is None
    assert mode._scenes == []


def test_scene_rotation_with_crossfade(tmp_path):
    scenes = [
        {"name": "one", "layers": [{"image": "a.png", "x": 0.5, "y": 0.5, "motion": "bob"}]},
        {"name": "two", "layers": [{"image": "b.png", "x": 0.5, "y": 0.5, "motion": "sway"}]},
    ]
    cfg = _make_project(tmp_path, scenes)
    cfg["scene_duration"] = 2.0
    cfg["crossfade_sec"] = 0.5
    mode = AnimatedSceneMode(cfg)
    mgr = FakeManager()
    mode.enter(mgr)
    assert mode._scene.name == "one"
    assert mode._upcoming.name == "two"

    # run past scene_duration: fade should begin
    for _ in range(int(2.2 * 60)):
        mode.update(1 / 60)
    assert mode._incoming is not None

    # run past the crossfade: new scene is current
    for _ in range(int(0.6 * 60)):
        mode.update(1 / 60)
        mode.render(mgr.screen)
    assert mode._scene.name == "two"
    assert mode._incoming is None
    # and the cycle wraps: upcoming is "one" again
    assert mode._upcoming.name == "one"


def test_update_without_scenes_is_noop(tmp_path):
    cfg = _make_project(tmp_path, [])
    cfg["scenes_file"] = str(tmp_path / "scenes.json")
    (tmp_path / "scenes.json").write_text(json.dumps({"scenes": []}))
    mode = AnimatedSceneMode(cfg)
    mgr = FakeManager()
    mode.enter(mgr)
    mode.update(1 / 60)  # must not raise
    mode.render(mgr.screen)


def test_all_motion_names_render(tmp_path):
    names = ["a.png", "b.png", "c.png", "d.png", "e.png"]
    motions = ["static", "bob", "sway", "drift_circle", "random"]
    layers = [
        {"image": n, "x": 0.5, "y": 0.5, "motion": m}
        for n, m in zip(names, motions)
    ]
    cfg = _make_project(tmp_path, [{"name": "all", "layers": layers}],
                        image_names=names)
    mode = AnimatedSceneMode(cfg)
    mgr = FakeManager()
    mode.enter(mgr)
    for _ in range(30):
        mode.update(1 / 60)
        mode.render(mgr.screen)
    assert set(motions) <= ALL_MOTIONS

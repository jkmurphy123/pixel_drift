# tests/test_control_panel_anim.py
#
# Phase 2 tests: signals + the first animated controls (gauge, lamp, scope).
#
# Run headless:
#   SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests/test_control_panel_anim.py -q

import os
import random
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

from controlpanel.controls import ControlContext, make_control  # noqa: E402
from controlpanel.layout import load_layout  # noqa: E402
from controlpanel.signals import build_signal  # noqa: E402
from modes.control_panel_mode import ControlPanelMode  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def pygame_init():
    pygame.init()
    pygame.font.init()
    yield
    pygame.quit()


def _run_signal(sig, seconds=30.0, dt=1 / 60):
    vals = []
    for _ in range(int(seconds / dt)):
        sig.update(dt)
        vals.append(sig.value)
    return vals


# ── signals ─────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["sine", "random_walk", "step", "square",
                                  "pulse", "noise"])
def test_unipolar_signals_stay_in_range(kind):
    rng = random.Random(42)
    sig = build_signal({"kind": kind}, rng, default_kind="sine")
    assert not sig.bipolar
    for v in _run_signal(sig):
        assert 0.0 <= v <= 1.0, f"{kind} left range: {v}"


@pytest.mark.parametrize("kind", ["sine", "noise"])
def test_bipolar_signals_stay_in_range(kind):
    rng = random.Random(42)
    sig = build_signal({"kind": kind}, rng, default_kind="sine", bipolar=True)
    for v in _run_signal(sig):
        assert -1.0 <= v <= 1.0, f"{kind} left range: {v}"


def test_signals_actually_move():
    rng = random.Random(7)
    for kind in ["sine", "random_walk", "step", "square", "noise"]:
        sig = build_signal({"kind": kind}, rng, default_kind="sine")
        vals = _run_signal(sig, seconds=60.0)
        assert max(vals) - min(vals) > 0.2, f"{kind} looks dead"


def test_same_seed_same_choreography():
    a = build_signal({"kind": "random_walk"}, random.Random(1), "random_walk")
    b = build_signal({"kind": "random_walk"}, random.Random(1), "random_walk")
    for _ in range(600):
        a.update(1 / 60)
        b.update(1 / 60)
    assert a.value == b.value


def test_unknown_kind_falls_back():
    sig = build_signal({"kind": "bogus"}, random.Random(1), "sine")
    assert type(sig).__name__ == "SineSignal"


# ── animated controls from the demo layout ──────────────────────

def _animated_controls(seed=1):
    layout = load_layout("demo_console")
    ctx = ControlContext(seed=seed)
    controls = [make_control(p, ctx) for p in layout.controls]
    return [c for c in controls if c is not None]


def test_factory_builds_phase2_types():
    controls = _animated_controls()
    types = {c.type for c in controls}
    # demo has gauges, lamps, scopes animated; only "plate" stays static
    assert {"gauge_round", "lamp", "scope"} <= types
    assert len(controls) == 21  # all 22 demo controls except the plate


def test_controls_update_and_draw_headless():
    surface = pygame.Surface((1920, 1080))
    for control in _animated_controls():
        for _ in range(120):
            control.update(1 / 60)
        control.draw_overlay(surface)  # must not raise


def test_gauge_needle_follows_signal():
    controls = [c for c in _animated_controls() if c.type == "gauge_round"]
    c = controls[0]
    c.signal.value = 0.0
    surface = pygame.Surface((1920, 1080))
    c.draw_overlay(surface)
    c.signal.value = 1.0
    c.draw_overlay(surface)  # different angle, still no raise
    assert c.needle_len > 0 and c.sweep_deg > 0


def test_lamp_color_from_sprite_id():
    controls = [c for c in _animated_controls() if c.type == "lamp"]
    by_sprite = {c.sprite_id: c for c in controls}
    assert by_sprite["LED_LAMP_RED"].color == (255, 60, 50)
    assert by_sprite["LED_LAMP_GREEN"].color == (70, 255, 110)


# ── end-to-end: frames actually change over time ────────────────

class _FakeCache:
    def get_font(self, name, size, bold=False):
        return pygame.font.Font(None, size)


class _FakeManager:
    def __init__(self, w, h):
        self.screen = pygame.Surface((w, h))
        self.cache = _FakeCache()
        self.width, self.height = w, h


def test_animation_changes_pixels_over_time():
    mode = ControlPanelMode({"layout_file": "demo_console", "seed": 5})
    manager = _FakeManager(1920, 1080)
    mode.enter(manager)
    assert mode._error is None

    # settle, then compare two frames a second apart
    for _ in range(30):
        mode.update(1 / 60)
    mode.render(manager.screen)
    snap1 = manager.screen.copy()
    for _ in range(60):
        mode.update(1 / 60)
    mode.render(manager.screen)

    diff = sum(
        1 for x in range(0, 1920, 32) for y in range(0, 1080, 32)
        if manager.screen.get_at((x, y)) != snap1.get_at((x, y)))
    assert diff > 0, "nothing moved between frames"
    mode.exit()

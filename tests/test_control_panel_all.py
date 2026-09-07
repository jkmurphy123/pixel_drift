# tests/test_control_panel_all.py
#
# Phase 4 tests: every control type in the catalog animates.
#
# Run headless:
#   SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests/test_control_panel_all.py -q

import json
import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

from controlpanel import seven_seg  # noqa: E402
from controlpanel.controls import (CONTROL_CLASSES, ControlContext,  # noqa: E402
                                   make_control)
from controlpanel.layout import load_layout  # noqa: E402
from controlpanel.registry import CONTROL_TYPES  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def pygame_init():
    pygame.init()
    pygame.font.init()
    yield
    pygame.quit()


# One layout exercising every animated type (plate is static by design).
ALL_TYPES_LAYOUT = {
    "name": "all_types",
    "panels": [{"id": "p", "origin": [0, 0], "size": [15, 8]}],
    "controls": [
        {"type": "scope",           "sprite": "SCOPE_H_1",    "panel": "p", "at": [0, 0]},
        {"type": "strip_chart",     "sprite": "STRIP_CHART",  "panel": "p", "at": [4, 0]},
        {"type": "radar",           "sprite": "RADAR_ROUND",  "panel": "p", "at": [10, 0]},
        {"type": "gauge_round",     "sprite": "GAUGE_ROUND_SMALL_1", "panel": "p", "at": [0, 2]},
        {"type": "meter_vu",        "sprite": "METER_VU_H_1", "panel": "p", "at": [1, 2]},
        {"type": "bar_graph",       "sprite": "BAR_GRAPH_V_1", "panel": "p", "at": [3, 2]},
        {"type": "led_bar",         "sprite": "LED_BAR",      "panel": "p", "at": [4, 2]},
        {"type": "lamp",            "sprite": "LED_LAMP_RED", "panel": "p", "at": [0, 3]},
        {"type": "lamp_rect",      "sprite": "LED_LAMP_RECT", "panel": "p", "at": [8, 3]},
        {"type": "lamp_square",    "sprite": "LED_LAMP_SQUARE", "panel": "p", "at": [14, 3]},
        {"type": "lamp_bank",       "sprite": "LAMP_BANK",    "panel": "p", "at": [1, 3]},
        {"type": "led_matrix",      "sprite": "LED_MATRIX",   "panel": "p", "at": [4, 3]},
        {"type": "keypad",          "sprite": "KEYPAD",       "panel": "p", "at": [6, 3]},
        {"type": "push_button",     "sprite": "PUSH_BUTTON_1", "panel": "p", "at": [0, 4]},
        {"type": "digital_readout", "sprite": "READOUT_DIGITAL", "panel": "p", "at": [8, 4]},
        {"type": "clock",           "sprite": "CLOCK_FACE",   "panel": "p", "at": [12, 4]},
        {"type": "meter_vu",        "sprite": "METER_VU_V_1", "panel": "p", "at": [14, 4]},
        {"type": "toggle_switch",   "sprite": "TOGGLE_SWITCH_1", "panel": "p", "at": [0, 5]},
        {"type": "rotary_knob",     "sprite": "ROTARY_KNOB_1", "panel": "p", "at": [1, 5]},
        {"type": "selector_switch", "sprite": "SELECTOR_SWITCH", "panel": "p", "at": [2, 5]},
        {"type": "counter",         "sprite": "COUNTER",      "panel": "p", "at": [8, 5]},
        {"type": "nixie",           "sprite": "NIXIE_PAIR",   "panel": "p", "at": [4, 5]},
        {"type": "tape_reel",       "sprite": "TAPE_REEL",    "panel": "p", "at": [6, 5]},
    ],
}


@pytest.fixture(scope="module")
def all_controls(tmp_path_factory):
    path = tmp_path_factory.mktemp("layouts") / "all_types.json"
    path.write_text(json.dumps(ALL_TYPES_LAYOUT))
    layout = load_layout(str(path))
    ctx = ControlContext(seed=3)
    return [make_control(p, ctx) for p in layout.controls]


def test_every_type_except_plate_has_a_class():
    assert set(CONTROL_CLASSES) == set(CONTROL_TYPES) - {"plate"}


def test_all_types_construct(all_controls):
    assert all(c is not None for c in all_controls)
    assert len(all_controls) == len(ALL_TYPES_LAYOUT["controls"])


def test_all_types_update_and_draw_60s(all_controls):
    surface = pygame.Surface((1920, 1080))
    for _ in range(360):  # 6 simulated seconds at 60 fps
        for c in all_controls:
            c.update(1 / 60)
    for c in all_controls:
        c.draw_overlay(surface)  # must not raise


def test_keypad_types_and_submits(all_controls):
    keypad = next(c for c in all_controls if c.type == "keypad")
    seen_states = set()
    for _ in range(60 * 60):  # one simulated minute
        keypad.update(1 / 60)
        seen_states.add(keypad.state)
        assert len(keypad.entry) <= keypad.code_len
    # idle/press/hold/accept-or-reject all reached within a minute
    assert len(seen_states) >= 4


def test_counter_counts_up(all_controls):
    counter = next(c for c in all_controls if c.type == "counter")
    before = counter.value
    for _ in range(600):
        counter.update(1 / 60)
    assert counter.value > before


def test_seven_seg_draws_all_digits():
    surface = pygame.Surface((400, 100))
    seven_seg.draw_text(surface, "0123456789", (0, 0, 400, 100), (0, 255, 0))
    lit = sum(1 for x in range(0, 400, 4) for y in range(0, 100, 4)
              if surface.get_at((x, y))[1] > 0)
    assert lit > 100, "7-seg rendering drew nothing"


def test_readout_formats_value(all_controls):
    readout = next(c for c in all_controls if c.type == "digital_readout")
    readout.signal.value = 0.5
    readout.signal.update = lambda dt: None  # freeze the drift for the assertion
    readout._acc = readout.refresh  # force a refresh on next update
    readout.update(1 / 60)
    mid = (readout.lo + readout.hi) / 2
    assert readout.text == f"{mid:.0f}"

# tests/test_control_panel_color.py
#
# Per-control "color" override + gauge needle thickness.
#
# Run headless:
#   SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests/test_control_panel_color.py -q

import json
import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

from controlpanel.controls import ControlContext, make_control  # noqa: E402
from controlpanel.layout import load_layout  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def pygame_init():
    pygame.init()
    pygame.font.init()
    yield
    pygame.quit()


def _control(tmp_path, spec):
    """Build one control from a grid layout containing a single control."""
    data = {
        "name": "one",
        "panels": [{"id": "p", "origin": [0, 0], "size": [15, 8]}],
        "controls": [{"panel": "p", "at": [0, 0], **spec}],
    }
    path = tmp_path / "layout.json"
    path.write_text(json.dumps(data))
    layout = load_layout(str(path))
    return make_control(layout.controls[0], ControlContext(seed=1))


CYAN = [0, 255, 255]


def test_generic_color_overrides_default(tmp_path):
    g = _control(tmp_path, {"type": "gauge_round",
                            "sprite": "GAUGE_ROUND_SMALL_1",
                            "color": CYAN})
    assert g.needle_rgb == (0, 255, 255)


def test_generic_color_beats_type_specific_key(tmp_path):
    g = _control(tmp_path, {"type": "gauge_round",
                            "sprite": "GAUGE_ROUND_SMALL_1",
                            "color": CYAN, "needle_rgb": [255, 0, 0]})
    assert g.needle_rgb == (0, 255, 255)


def test_type_specific_key_still_works_alone(tmp_path):
    g = _control(tmp_path, {"type": "gauge_round",
                            "sprite": "GAUGE_ROUND_SMALL_1",
                            "needle_rgb": [255, 0, 0]})
    assert g.needle_rgb == (255, 0, 0)


def test_no_color_keeps_default(tmp_path):
    g = _control(tmp_path, {"type": "gauge_round",
                            "sprite": "GAUGE_ROUND_SMALL_1"})
    assert g.needle_rgb == ControlContext().accent_rgb


def test_generic_color_on_lamp_beats_sprite_inference(tmp_path):
    lamp = _control(tmp_path, {"type": "lamp", "sprite": "LED_LAMP_RED",
                               "color": CYAN})
    assert lamp.color == (0, 255, 255)


def test_generic_color_on_radar(tmp_path):
    r = _control(tmp_path, {"type": "radar", "sprite": "RADAR_ROUND",
                            "color": CYAN})
    assert r.color == (0, 255, 255)


def test_meter_explicit_color_disables_threshold_coloring(tmp_path):
    m = _control(tmp_path, {"type": "meter_vu", "sprite": "METER_VU_H_1",
                            "color": CYAN})
    surface = pygame.Surface((1920, 1080))
    for _ in range(120):
        m.update(1 / 60)
    m.draw_overlay(surface)
    assert m.needle_rgb == (0, 255, 255)  # never repainted green/amber/red


def test_meter_without_color_still_threshold_colors(tmp_path):
    m = _control(tmp_path, {"type": "meter_vu", "sprite": "METER_VU_H_1"})
    surface = pygame.Surface((1920, 1080))
    m.draw_overlay(surface)
    assert m.needle_rgb in ((70, 255, 110), (255, 176, 64), (255, 60, 50))


def test_gauge_needle_scales_with_size(tmp_path):
    # freeform lets us size the same control two ways
    def gauge(size):
        data = {
            "name": "ff", "mode": "freeform",
            "design_resolution": [1920, 1080],
            "controls": [{"type": "gauge_round",
                          "sprite": "GAUGE_ROUND_SMALL_1",
                          "at": [0, 0], "size": [size, size]}],
        }
        path = tmp_path / f"g{size}.json"
        path.write_text(json.dumps(data))
        layout = load_layout(str(path))
        return make_control(layout.controls[0], ControlContext(seed=1))

    small, big = gauge(128), gauge(512)
    assert big.needle_w > small.needle_w >= 4


def test_gauge_needle_width_override(tmp_path):
    g = _control(tmp_path, {"type": "gauge_round",
                            "sprite": "GAUGE_ROUND_SMALL_1",
                            "needle_width": 9})
    assert g.needle_w == 9

# tests/test_control_panel_freeform.py
#
# Freeform layout mode tests (decision D6): pixel-precise control placement
# over a full background image, alongside the original grid mode.
#
# Run headless:
#   SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests/test_control_panel_freeform.py -q

import json
import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

from controlpanel.layout import LayoutError, load_layout  # noqa: E402
from modes.control_panel_mode import ControlPanelMode  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def pygame_init():
    pygame.init()
    pygame.font.init()
    yield
    pygame.quit()


def _write(tmp_path, data, with_bg=True):
    data = dict(data)
    if "background_image" in data:
        bg_path = tmp_path / "bg.png"
        if with_bg:
            bg = pygame.Surface((320, 240))
            bg.fill((40, 40, 60))
            pygame.image.save(bg, str(bg_path))
        # absolute path so the test doesn't touch the real backgrounds dir
        data["background_image"] = str(bg_path)
    path = tmp_path / "layout.json"
    path.write_text(json.dumps(data))
    return str(path)


BASE = {
    "name": "ff",
    "mode": "freeform",
    "design_resolution": [320, 240],
    "background_image": "bg.png",
}


# ── validation ──────────────────────────────────────────────────

def test_freeform_validates_and_computes_rects(tmp_path):
    layout = load_layout(_write(tmp_path, {**BASE, "controls": [
        {"type": "gauge_round", "at": [10, 20]},                 # scale 1.0 -> 128x128
        {"type": "lamp", "at": [150, 20], "scale": 0.5},         # -> 64x64
        {"type": "scope", "at": [10, 170], "size": [200, 60]},   # explicit size
    ]}))
    assert layout.mode == "freeform"
    assert layout.background_image and layout.background_image.endswith("bg.png")
    r0, r1, r2 = [c.rect_px for c in layout.controls]
    assert r0 == (10, 20, 128, 128)
    assert r1 == (150, 20, 64, 64)
    assert r2 == (10, 170, 200, 60)


def test_freeform_default_resolution(tmp_path):
    # When a background image is supplied but design_resolution is omitted,
    # the canvas size is inferred from the image so the artwork is not forced
    # into the legacy 1920x1080 default.
    data = {k: v for k, v in BASE.items() if k != "design_resolution"}
    layout = load_layout(_write(tmp_path, {**data, "controls": []}))
    assert layout.design_resolution == (320, 240)


def test_freeform_no_background_defaults_to_1080p(tmp_path):
    data = {k: v for k, v in BASE.items() if k not in ("design_resolution", "background_image")}
    layout = load_layout(_write(tmp_path, {**data, "controls": []}))
    assert layout.design_resolution == (1920, 1080)


def test_freeform_portrait_background_infers_portrait_resolution(tmp_path):
    bg_path = tmp_path / "portrait.png"
    portrait = pygame.Surface((816, 1440))
    portrait.fill((20, 30, 40))
    pygame.image.save(portrait, str(bg_path))
    layout_path = tmp_path / "layout.json"
    layout_path.write_text(json.dumps({
        "name": "ff",
        "mode": "freeform",
        "background_image": str(bg_path),
        "controls": []
    }))
    layout = load_layout(str(layout_path))
    assert layout.design_resolution == (816, 1440)


def test_freeform_explicit_design_resolution_overrides_image(tmp_path):
    # e.g. 1920x1088 artwork: an explicit design_resolution wins
    data = {**BASE, "design_resolution": [1920, 1088], "controls": [
        {"type": "lamp", "at": [1800, 980], "size": [96, 96]}]}
    layout = load_layout(_write(tmp_path, data))
    assert layout.design_resolution == (1920, 1088)
    assert layout.controls[0].rect_px == (1800, 980, 96, 96)


def test_freeform_rejects_missing_at(tmp_path):
    with pytest.raises(LayoutError, match="missing 'at'"):
        load_layout(_write(tmp_path, {**BASE, "controls": [
            {"type": "lamp"}]}))


def test_freeform_rejects_off_canvas(tmp_path):
    with pytest.raises(LayoutError, match="exceeds"):
        load_layout(_write(tmp_path, {**BASE, "controls": [
            {"type": "lamp", "at": [300, 200]}]}))  # 300+128 > 320


def test_freeform_rejects_bad_scale(tmp_path):
    with pytest.raises(LayoutError, match="scale"):
        load_layout(_write(tmp_path, {**BASE, "controls": [
            {"type": "lamp", "at": [0, 0], "scale": -1}]}))


def test_freeform_rejects_missing_background(tmp_path):
    with pytest.raises(LayoutError, match="background image not found"):
        load_layout(_write(tmp_path, BASE, with_bg=False))


def test_unknown_mode_rejected(tmp_path):
    with pytest.raises(LayoutError, match="unknown mode"):
        load_layout(_write(tmp_path, {**BASE, "mode": "weird", "controls": []}))


def test_grid_mode_still_default():
    layout = load_layout("demo_console")
    assert layout.mode == "grid"
    assert layout.panels


# ── bundled demo + end-to-end ───────────────────────────────────

class _FakeCache:
    def get_font(self, name, size, bold=False):
        return pygame.font.Font(None, size)


class _FakeManager:
    def __init__(self, w, h):
        self.screen = pygame.Surface((w, h))
        self.cache = _FakeCache()
        self.width, self.height = w, h


def test_freeform_demo_layout_valid():
    layout = load_layout("freeform_demo")
    assert layout.mode == "freeform"
    assert len(layout.controls) == 17
    assert layout.design_resolution == (1600, 900)


def test_freeform_mode_renders_and_animates():
    mode = ControlPanelMode({"layout_file": "freeform_demo", "seed": 2})
    manager = _FakeManager(1600, 900)
    mode.enter(manager)
    assert mode._error is None
    for _ in range(90):
        mode.update(1 / 60)
    mode.render(manager.screen)
    snap = manager.screen.copy()
    for _ in range(60):
        mode.update(1 / 60)
    mode.render(manager.screen)
    diff = sum(1 for x in range(0, 1600, 40) for y in range(0, 900, 40)
               if manager.screen.get_at((x, y)) != snap.get_at((x, y)))
    assert diff > 0, "freeform overlays did not animate"
    mode.exit()


def test_freeform_overlay_lands_on_art_position():
    # a lamp at a known position must light pixels at that position
    mode = ControlPanelMode({"layout_file": "freeform_demo", "seed": 2})
    manager = _FakeManager(1600, 900)
    mode.enter(manager)
    lamp = next(c for c in mode.controls if c.type == "lamp")
    lamp.level = 1.0  # force fully lit
    mode.render(manager.screen)
    cx, cy = int(lamp.center[0]), int(lamp.center[1])
    px = manager.screen.get_at((cx, cy))
    assert max(px[:3]) > 60, f"lamp overlay not at expected pixel: {px[:3]}"
    mode.exit()

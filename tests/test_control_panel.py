# tests/test_control_panel.py
#
# Phase 1 tests for the control_panel mode:
#   1. sprite_defs geometry is sane (whitelisted footprints, on-sheet, no overlaps)
#   2. the placeholder skin loads and exposes every defined sprite
#   3. the demo layout validates
#   4. layout validation catches authoring mistakes with clear errors
#   5. headless end-to-end: mode enter/update/render against a fake manager
#
# Run headless:
#   SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests/test_control_panel.py -q

import json
import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

from controlpanel import paths  # noqa: E402
from controlpanel.geometry import CELL_SIZE, FOOTPRINTS, GRID_COLS, GRID_ROWS  # noqa: E402
from controlpanel.layout import LayoutError, load_layout  # noqa: E402
from controlpanel.skin import SkinError, load_skin, load_sprite_defs  # noqa: E402
from modes.control_panel_mode import ControlPanelMode  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def pygame_init():
    pygame.init()
    pygame.font.init()
    # Dummy video driver needs a display surface before .convert() will work.
    pygame.display.set_mode((1, 1))
    yield
    pygame.quit()


# ── 1. sprite defs geometry ─────────────────────────────────────

def test_sprite_defs_geometry():
    defs = load_sprite_defs()
    sheet_cols, sheet_rows = defs["sheet_cells"]
    occupied = []
    for sprite_id, geo in defs["sprites"].items():
        w, h = geo["w"], geo["h"]
        assert (w, h) in FOOTPRINTS.values(), \
            f"{sprite_id}: footprint {w}x{h} not in whitelist"
        assert geo["x"] >= 0 and geo["y"] >= 0, f"{sprite_id}: negative origin"
        assert geo["x"] + w <= sheet_cols and geo["y"] + h <= sheet_rows, \
            f"{sprite_id}: exceeds {sheet_cols}x{sheet_rows} sheet"
        rect = (geo["x"], geo["y"], w, h)
        for o in occupied:
            overlap = (rect[0] < o[0] + o[2] and o[0] < rect[0] + rect[2]
                       and rect[1] < o[1] + o[3] and o[1] < rect[1] + rect[3])
            assert not overlap, f"{sprite_id}: overlaps another sprite at {o}"
        occupied.append(rect)


# ── 2. placeholder skin ─────────────────────────────────────────

def test_placeholder_skin_loads_all_sprites():
    skin = load_skin("placeholder")
    defs = load_sprite_defs()
    assert set(skin.sprites) == set(defs["sprites"])
    for sprite_id, geo in defs["sprites"].items():
        assert skin.get(sprite_id).get_size() == (
            geo["w"] * CELL_SIZE, geo["h"] * CELL_SIZE)


def test_missing_skin_raises():
    with pytest.raises(SkinError):
        load_skin("no_such_skin")


# ── 3. demo layout validates ────────────────────────────────────

def test_demo_layout_valid():
    layout = load_layout("demo_console")
    assert layout.panels and layout.controls
    assert layout.name == "demo_console"


# ── 4. validation catches mistakes ──────────────────────────────

def _write_layout(tmp_path, controls, panels=None):
    data = {
        "name": "bad",
        "panels": panels if panels is not None else [
            {"id": "p", "origin": [0, 0], "size": [GRID_COLS, GRID_ROWS]}
        ],
        "controls": controls,
    }
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data))
    return str(path)


def test_layout_rejects_unknown_type(tmp_path):
    with pytest.raises(LayoutError, match="unknown type"):
        load_layout(_write_layout(tmp_path, [
            {"type": "warp_drive", "panel": "p", "at": [0, 0]}]))


def test_layout_rejects_unknown_sprite(tmp_path):
    with pytest.raises(LayoutError, match="unknown sprite"):
        load_layout(_write_layout(tmp_path, [
            {"type": "lamp", "sprite": "NOPE", "panel": "p", "at": [0, 0]}]))


def test_layout_rejects_missing_at(tmp_path):
    with pytest.raises(LayoutError, match="missing 'at'"):
        load_layout(_write_layout(tmp_path, [
            {"type": "lamp", "panel": "p"}]))


def test_layout_rejects_unknown_panel(tmp_path):
    with pytest.raises(LayoutError, match="unknown panel"):
        load_layout(_write_layout(tmp_path, [
            {"type": "lamp", "panel": "nope", "at": [0, 0]}]))


def test_layout_rejects_out_of_bounds(tmp_path):
    panels = [{"id": "p", "origin": [0, 0], "size": [2, 2]}]
    with pytest.raises(LayoutError, match="does not fit"):
        load_layout(_write_layout(tmp_path, [
            {"type": "radar", "panel": "p", "at": [0, 0]}], panels))


def test_layout_rejects_overlap(tmp_path):
    with pytest.raises(LayoutError, match="overlaps"):
        load_layout(_write_layout(tmp_path, [
            {"type": "gauge_round", "panel": "p", "at": [0, 0]},
            {"type": "lamp", "panel": "p", "at": [0, 0]},
        ]))


def test_layout_rejects_duplicate_panel_id(tmp_path):
    panels = [{"id": "p", "origin": [0, 0], "size": [2, 2]},
              {"id": "p", "origin": [2, 0], "size": [2, 2]}]
    with pytest.raises(LayoutError, match="duplicate panel id"):
        load_layout(_write_layout(tmp_path, [], panels))


# ── 5. headless end-to-end ──────────────────────────────────────

class _FakeCache:
    def get_font(self, name, size, bold=False):
        return pygame.font.Font(None, size)


class _FakeManager:
    def __init__(self, w, h):
        self.screen = pygame.Surface((w, h))
        self.cache = _FakeCache()
        self.width, self.height = w, h


def test_mode_renders_at_design_resolution():
    mode = ControlPanelMode({"layout_file": "demo_console", "skin": "placeholder"})
    manager = _FakeManager(1920, 1080)
    mode.enter(manager)
    assert mode._error is None
    mode.update(0.016)
    mode.render(manager.screen)
    # canvas filled the screen (not left at the dummy driver's black)
    assert manager.screen.get_at((960, 540))[:3] != (0, 0, 0)
    mode.exit()
    assert mode.compositor is None


def test_mode_renders_scaled_to_other_resolution():
    mode = ControlPanelMode({"layout_file": "demo_console"})
    manager = _FakeManager(1280, 720)
    mode.enter(manager)
    mode.render(manager.screen)
    assert manager.screen.get_at((640, 360))[:3] != (0, 0, 0)
    mode.exit()


def test_mode_preserves_aspect_ratio_in_portrait():
    """Default scale_mode='fit' should letterbox, not squash a landscape layout."""
    mode = ControlPanelMode({"layout_file": "demo_console", "skin": "placeholder"})
    manager = _FakeManager(1080, 1920)
    mode.enter(manager)
    assert mode.scale_mode == "fit"
    mode.render(manager.screen)
    assert mode.compositor is not None
    bg = mode.compositor.background_rgb
    # top bar is letterbox fill
    assert manager.screen.get_at((540, 10))[:3] == bg
    # center of the scaled content is not letterbox fill
    assert manager.screen.get_at((540, 960))[:3] != bg
    mode.exit()


def test_mode_scale_mode_stretch_fills_portrait_screen():
    """Explicit scale_mode='stretch' keeps the legacy fill-and-distort behavior."""
    mode = ControlPanelMode(
        {"layout_file": "demo_console", "skin": "placeholder", "scale_mode": "stretch"}
    )
    manager = _FakeManager(1080, 1920)
    mode.enter(manager)
    assert mode.scale_mode == "stretch"
    mode.render(manager.screen)
    assert mode.compositor is not None
    bg = mode.compositor.background_rgb
    # with stretch the top edge maps to the top of the design, so it is content
    assert manager.screen.get_at((540, 10))[:3] != bg
    mode.exit()


def test_mode_scale_mode_cover_fills_screen():
    """scale_mode='cover' uniformly fills the screen, cropping instead of letterboxing."""
    mode = ControlPanelMode(
        {"layout_file": "demo_console", "skin": "placeholder", "scale_mode": "cover"}
    )
    manager = _FakeManager(1080, 1920)
    mode.enter(manager)
    assert mode.scale_mode == "cover"
    mode.render(manager.screen)
    assert mode.compositor is not None
    # screen is filled horizontally (no side pillarboxes); sample near top edge
    bg = mode.compositor.background_rgb
    assert manager.screen.get_at((10, 100))[:3] != bg
    assert manager.screen.get_at((1069, 100))[:3] != bg
    # center is still content
    assert manager.screen.get_at((540, 960))[:3] != bg
    mode.exit()


def test_mode_error_path_renders_message():
    mode = ControlPanelMode({"layout_file": "no_such_layout"})
    manager = _FakeManager(640, 480)
    mode.enter(manager)
    assert mode._error is not None
    mode.render(manager.screen)  # must not raise
    mode.exit()

# tests/test_puppet_theatre.py
#
# Headless tests for the puppet theatre mode.
# Run with: SDL_VIDEODRIVER=dummy pytest tests/test_puppet_theatre.py

import os
import sys

import pygame
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from modes.puppet_theatre_mode import (
    PuppetTheatreMode,
    _word_count,
    DEFAULT_STAGE_POSITIONS,
)


@pytest.fixture(scope="module", autouse=True)
def init_pygame():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    yield
    pygame.quit()


@pytest.fixture
def manager():
    screen = pygame.display.set_mode((800, 600))

    class FakeManager:
        def __init__(self):
            self.screen = screen
            from core.cache import ResourceCache

            self.cache = ResourceCache()
            self.width = 800
            self.height = 600

    return FakeManager()


@pytest.fixture
def mode(manager):
    cfg = {
        "scenes_file": "assets/puppet_theatre/scene_files/puppet_scenes.json",
        "image_folder": "assets/puppet_theatre",
    }
    m = PuppetTheatreMode(cfg)
    m.enter(manager)
    yield m
    m.exit()


def test_word_count():
    assert _word_count("") == 0
    assert _word_count("hello") == 1
    assert _word_count("one two three") == 3


def test_scene_load(mode):
    assert len(mode._scenes) == 2
    assert mode._scenes[0].title == "The Argument"
    assert mode._scenes[1].title == "The Reconciliation"


def test_layer_count(mode):
    for scene in mode._scenes:
        assert len(scene.layers) == 4


def test_state_machine_advances(mode):
    """After enough time, the mode should leave the intro state."""
    assert mode._scene_state == "intro"
    mode.update(2.0)
    assert mode._scene_state != "intro"


def test_smoke_render_300_frames(mode, manager):
    """Render 300 frames without raising."""
    clock = pygame.time.Clock()
    for _ in range(300):
        dt = clock.tick(60) / 1000.0
        mode.update(dt)
        mode.render(manager.screen)


def test_stage_positions_default():
    assert "stage_left" in DEFAULT_STAGE_POSITIONS
    assert "stage_center" in DEFAULT_STAGE_POSITIONS
    assert "stage_right" in DEFAULT_STAGE_POSITIONS


def test_loop_fade_to_black_after_last_scene(manager):
    """After the last scene's outro, the mode enters loop_black before restarting."""
    cfg = {
        "scenes_file": "assets/puppet_theatre/scene_files/puppet_scenes.json",
        "image_folder": "assets/puppet_theatre",
        "scene_description_hold_sec": 0.01,
        "dialogue_hold_sec": 0.01,
        "transition_duration_sec": 0.01,
        "scene_pause_before_script_sec": 0.01,
        "scene_pause_after_script_sec": 0.01,
        "loop_fade_to_black_sec": 0.05,
        "loop_black_hold_sec": 0.05,
    }
    mode = PuppetTheatreMode(cfg)
    mode.enter(manager)

    # Step through until we leave the first scene.
    for _ in range(2000):
        mode.update(0.05)
        if mode._scene_index == 1:
            break

    # Now step through the second (last) scene until we hit loop_black.
    saw_loop_black = False
    for _ in range(2000):
        mode.update(0.05)
        if mode._scene_state == "loop_black":
            saw_loop_black = True
        if mode._scene_index == 0 and mode._scene_state == "intro":
            break

    mode.exit()
    assert saw_loop_black, "expected to enter loop_black state after last scene"
    assert not mode._characters, "expected character state to be cleared after loop restart"


def test_exit_transition_hides_character_after_completion(manager):
    """After an exit transition finishes, the character should no longer be visible."""
    cfg = {
        "scenes_file": "assets/puppet_theatre/scene_files/puppet_scenes.json",
        "image_folder": "assets/puppet_theatre",
        "transition_duration_sec": 0.2,
    }
    mode = PuppetTheatreMode(cfg)
    mode.enter(manager)

    mode._apply_script_line({
        "character": "ALICE",
        "transition": "ENTER_STAGE_LEFT",
        "emotion": "CALM",
        "mouth": "SPEAKING",
        "dialogue": "",
        "position": None,
    })
    mode.update(0.3)
    assert mode._characters["ALICE"].visible, "character should be visible after entering"

    mode._apply_script_line({
        "character": "ALICE",
        "transition": "EXIT_STAGE_LEFT",
        "emotion": "CALM",
        "mouth": "SILENT",
        "dialogue": "",
        "position": None,
    })
    mode.update(0.3)
    assert not mode._characters["ALICE"].visible, "character should be hidden after exiting"
    mode.exit()

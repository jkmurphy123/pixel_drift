# controlpanel/skin.py
#
# Skin loading: reads a skin directory (skin.json + sheet PNG), validates it
# against the canonical sprite_defs.json geometry, and extracts one pygame
# Surface per sprite ID.
#
# Sprite geometry is shared and skin-independent (assets/control_panel/
# sprite_defs.json): every skin uses the identical to-the-pixel layout, so
# swapping skins re-themes every layout without touching config or code.

import json

import pygame

from . import paths
from .geometry import CELL_SIZE, footprint_of


class SkinError(Exception):
    """Raised for any skin manifest / sheet problem (caught by the mode)."""


def load_sprite_defs(defs_path=None) -> dict:
    """Load the canonical sprite geometry shared by all skins."""
    defs_path = defs_path or paths.SPRITE_DEFS_FILE
    try:
        with open(defs_path) as f:
            data = json.load(f)
    except FileNotFoundError:
        raise SkinError(f"sprite defs not found: {defs_path}")
    except json.JSONDecodeError as e:
        raise SkinError(f"invalid JSON in {defs_path}: {e}")

    sprites = data.get("sprites")
    if not isinstance(sprites, dict) or not sprites:
        raise SkinError(f"{defs_path}: 'sprites' must be a non-empty object")
    return data


class Skin:
    """A loaded sprite sheet: name, background color, sprite surfaces."""

    def __init__(self, name: str, background_rgb, sprites: dict):
        self.name = name
        self.background_rgb = tuple(background_rgb)
        # sprite ID -> pygame.Surface (already cropped to footprint)
        self.sprites = sprites

    def get(self, sprite_id: str) -> pygame.Surface:
        surf = self.sprites.get(sprite_id)
        if surf is None:
            raise SkinError(f"skin '{self.name}' has no sprite '{sprite_id}'")
        return surf


def load_skin(name_or_path: str) -> Skin:
    """
    Load a skin by bare name (under assets/control_panel/skins/) or by path.
    Raises SkinError with a one-line reason on any problem.
    """
    skin_dir = paths.resolve_under(paths.SKINS_DIR, name_or_path)
    manifest_path = skin_dir / "skin.json"

    if not manifest_path.exists():
        raise SkinError(f"skin manifest not found: {manifest_path}")
    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except json.JSONDecodeError as e:
        raise SkinError(f"invalid JSON in {manifest_path}: {e}")

    name = manifest.get("name", skin_dir.name)
    image_name = manifest.get("image")
    if not image_name:
        raise SkinError(f"{manifest_path}: missing required field 'image'")
    background_rgb = manifest.get("background_rgb", [18, 20, 24])

    sheet_path = skin_dir / image_name
    if not sheet_path.exists():
        raise SkinError(f"skin sheet not found: {sheet_path}")
    try:
        sheet = pygame.image.load(str(sheet_path)).convert()
    except pygame.error as e:
        raise SkinError(f"cannot load skin sheet {sheet_path}: {e}")

    defs = load_sprite_defs()
    sheet_w, sheet_h = sheet.get_size()
    if sheet_w % CELL_SIZE or sheet_h % CELL_SIZE:
        raise SkinError(
            f"skin '{name}': sheet {sheet_w}x{sheet_h} is not a multiple "
            f"of the {CELL_SIZE}px cell size"
        )

    sprites = {}
    for sprite_id, geo in defs["sprites"].items():
        x, y, w, h = geo["x"], geo["y"], geo["w"], geo["h"]
        if footprint_of(w, h) is None:
            raise SkinError(
                f"sprite_defs: {sprite_id} has non-whitelisted footprint {w}x{h}"
            )
        rect = pygame.Rect(x * CELL_SIZE, y * CELL_SIZE,
                           w * CELL_SIZE, h * CELL_SIZE)
        if not sheet.get_rect().contains(rect):
            raise SkinError(
                f"skin '{name}': sprite {sprite_id} rect {rect} exceeds sheet"
            )
        # copy so the full sheet can be freed after load
        sprites[sprite_id] = sheet.subsurface(rect).copy()

    return Skin(name, background_rgb, sprites)

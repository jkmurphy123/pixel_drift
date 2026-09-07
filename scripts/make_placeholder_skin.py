#!/usr/bin/env python3
# scripts/make_placeholder_skin.py
#
# Generates the "placeholder" control-panel skin: a flat, labeled sprite
# sheet matching the canonical geometry in assets/control_panel/sprite_defs.json.
# Every sprite is a dark plate with a border, its ID, and its footprint, so
# layouts can be built and tested before any real art exists.
#
# Run headless:
#   SDL_VIDEODRIVER=dummy python scripts/make_placeholder_skin.py

import json
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

from controlpanel import paths  # noqa: E402
from controlpanel.geometry import CELL_SIZE  # noqa: E402

PLATE_FILL = (44, 47, 52)
PLATE_BORDER = (120, 126, 134)
LABEL_RGB = (200, 205, 210)
SUB_LABEL_RGB = (140, 145, 150)
ACCENT_RGB = (90, 160, 220)
SHEET_BG = (24, 26, 30)


def main():
    with open(paths.SPRITE_DEFS_FILE) as f:
        defs = json.load(f)

    sheet_cells = defs.get("sheet_cells", [16, 16])
    sheet_w = sheet_cells[0] * CELL_SIZE
    sheet_h = sheet_cells[1] * CELL_SIZE

    pygame.init()
    pygame.font.init()

    sheet = pygame.Surface((sheet_w, sheet_h))
    sheet.fill(SHEET_BG)

    font = pygame.font.Font(None, 22)
    small = pygame.font.Font(None, 18)

    for sprite_id, geo in sorted(defs["sprites"].items()):
        rect = pygame.Rect(geo["x"] * CELL_SIZE, geo["y"] * CELL_SIZE,
                           geo["w"] * CELL_SIZE, geo["h"] * CELL_SIZE)
        inner = rect.inflate(-8, -8)
        pygame.draw.rect(sheet, PLATE_FILL, inner)
        pygame.draw.rect(sheet, PLATE_BORDER, inner, 2)

        # animation-anchor crosshair at the plate center
        cx, cy = inner.center
        pygame.draw.line(sheet, ACCENT_RGB, (cx - 8, cy), (cx + 8, cy), 1)
        pygame.draw.line(sheet, ACCENT_RGB, (cx, cy - 8), (cx, cy + 8), 1)

        # ID centered above the crosshair, footprint below it
        label = font.render(sprite_id, True, LABEL_RGB)
        sheet.blit(label, label.get_rect(center=(cx, cy - 14)))
        sub = small.render(f"{geo['w']}x{geo['h']}", True, SUB_LABEL_RGB)
        sheet.blit(sub, sub.get_rect(center=(cx, cy + 14)))

    out_dir = paths.SKINS_DIR / "placeholder"
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet_path = out_dir / "sheet.png"
    pygame.image.save(sheet, str(sheet_path))

    manifest = {
        "name": "placeholder",
        "image": "sheet.png",
        "background_rgb": [18, 20, 24],
        "comment": (
            "Auto-generated test skin. Geometry comes from the shared "
            "assets/control_panel/sprite_defs.json — regenerate with "
            "scripts/make_placeholder_skin.py after editing sprite defs."
        ),
    }
    with open(out_dir / "skin.json", "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"[make_placeholder_skin] wrote {sheet_path} ({sheet_w}x{sheet_h}, "
          f"{len(defs['sprites'])} sprites) + skin.json")


if __name__ == "__main__":
    main()

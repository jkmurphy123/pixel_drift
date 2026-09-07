#!/usr/bin/env python3
# scripts/make_freeform_demo.py
#
# Generates the freeform demo assets: a complete control-panel background
# image (1600x900) plus a matching freeform layout JSON, both from ONE
# shared spec so the printed dials and the animation overlays can never
# drift apart (decision D6).
#
# Outputs:
#   assets/control_panel/backgrounds/freeform_demo.png
#   assets/control_panel/layouts/freeform_demo.json
#
# Run headless:
#   SDL_VIDEODRIVER=dummy python scripts/make_freeform_demo.py

import json
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

from controlpanel import paths  # noqa: E402

W, H = 1600, 900

PLATE = (38, 41, 46)
BEZEL = (120, 126, 134)
FACE = (22, 24, 28)
SCREEN = (10, 22, 14)
TICK = (160, 166, 172)

# Shared spec: (type, cx, cy, size, extras for the layout entry)
# The art below and the layout JSON both derive from this table.
CONTROLS = [
    ("radar",    260, 260, 380, {}),
    ("gauge_round", 640, 200, 190, {"pivot": [0.5, 0.5], "sweep_deg": 240}),
    ("gauge_round", 860, 200, 190, {"pivot": [0.5, 0.5], "sweep_deg": 240}),
    ("clock",    1080, 200, 190, {}),
    ("scope",    1340, 200, 380, {"size": [380, 190],
                                  "window": [0.07, 0.12, 0.86, 0.76]}),
    ("lamp",     600, 480, 70, {}),
    ("lamp",     700, 480, 70, {"color_rgb": [70, 255, 110]}),
    ("lamp",     800, 480, 70, {"color_rgb": [80, 170, 255]}),
    ("toggle_switch", 950, 480, 90, {}),
    ("rotary_knob",  1080, 480, 110, {}),
    ("push_button",  1210, 480, 90, {}),
    ("digital_readout", 1420, 480, 260, {"size": [260, 80],
                                         "window": [0.05, 0.15, 0.90, 0.70]}),
    ("bar_graph", 180, 660, 60, {"size": [60, 300],
                                 "window": [0.20, 0.05, 0.60, 0.90]}),
    ("led_bar",   700, 830, 500, {"size": [500, 50],
                                  "window": [0.03, 0.20, 0.94, 0.60]}),
    ("keypad",   1300, 700, 220, {}),
    ("tape_reel", 420, 680, 220, {}),
    ("nixie",    1080, 680, 180, {}),
]


def draw_art(screen, ctype, cx, cy, size):
    """Draw the printed bezel/plate for one control."""
    w = h = size
    if ctype in ("scope",):
        w, h = size, size // 2
    if ctype in ("digital_readout",):
        w, h = 260, 80
    if ctype in ("bar_graph",):
        w, h = 60, 300
    if ctype in ("led_bar",):
        w, h = 500, 50
    rect = pygame.Rect(cx - w // 2, cy - h // 2, w, h)
    pygame.draw.rect(screen, PLATE, rect.inflate(16, 16))
    pygame.draw.rect(screen, BEZEL, rect.inflate(16, 16), 2)

    if ctype in ("gauge_round", "radar", "clock"):
        pygame.draw.circle(screen, FACE, (cx, cy), size // 2)
        pygame.draw.circle(screen, BEZEL, (cx, cy), size // 2, 3)
        if ctype == "gauge_round":
            for deg in range(-120, 121, 30):  # tick marks around the dial
                import math
                a = math.radians(deg - 90)
                r1, r2 = size * 0.40, size * 0.46
                pygame.draw.line(screen, TICK,
                                 (cx + r1 * math.cos(a), cy + r1 * math.sin(a)),
                                 (cx + r2 * math.cos(a), cy + r2 * math.sin(a)), 2)
        if ctype == "radar":
            for frac in (0.33, 0.66, 1.0):
                pygame.draw.circle(screen, (30, 60, 40), (cx, cy),
                                   int(size / 2 * frac * 0.9), 1)
    elif ctype in ("scope", "digital_readout", "led_bar"):
        pygame.draw.rect(screen, SCREEN, rect)
        pygame.draw.rect(screen, BEZEL, rect, 2)
    else:
        pygame.draw.circle(screen, FACE, (cx, cy), size // 2)
        pygame.draw.circle(screen, BEZEL, (cx, cy), size // 2, 2)


def main():
    pygame.init()
    screen = pygame.Surface((W, H))
    screen.fill((18, 20, 24))

    for ctype, cx, cy, size, _ in CONTROLS:
        draw_art(screen, ctype, cx, cy, size)

    paths.BACKGROUNDS_DIR.mkdir(parents=True, exist_ok=True)
    bg_path = paths.BACKGROUNDS_DIR / "freeform_demo.png"
    pygame.image.save(screen, str(bg_path))

    # emit the layout from the same spec: at = top-left of the control rect.
    # Always emit explicit "size" — unambiguous regardless of the sprite's
    # natural footprint ("scale" is still supported for hand-authored files).
    controls = []
    for ctype, cx, cy, size, extras in CONTROLS:
        entry = {"type": ctype}
        if "size" in extras:
            w, h = extras["size"]
        elif ctype == "scope":
            w, h = size, size // 2
        else:
            w = h = size
        entry["at"] = [cx - w // 2, cy - h // 2]
        entry["size"] = [w, h]
        entry.update({k: v for k, v in extras.items() if k != "size"})
        controls.append(entry)

    layout = {
        "name": "freeform_demo",
        "mode": "freeform",
        "design_resolution": [W, H],
        "background_image": "freeform_demo.png",
        "controls": controls,
    }
    layout_path = paths.LAYOUTS_DIR / "freeform_demo.json"
    with open(layout_path, "w") as f:
        json.dump(layout, f, indent=2)

    print(f"[make_freeform_demo] wrote {bg_path} + {layout_path} "
          f"({len(controls)} controls)")


if __name__ == "__main__":
    main()

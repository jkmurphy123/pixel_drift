# controlpanel/layout.py
#
# Layout file loading + validation. Two layout modes (decision D6):
#
#   "grid" (default) — the original slot approach: panels + controls placed
#       in 128px cells on the 15x8 design grid; sprites come from the skin.
#
#   "freeform" — for complete control-panel artwork: a full-screen
#       background image plus controls placed at precise pixel coordinates,
#       sized with "size" [w,h] or "scale". No skin sprites are blitted —
#       controls draw only their animation overlays on top of the art.
#
# Everything is validated at load so authoring mistakes produce one clear
# error line instead of a broken screen.

import json
import struct

import pygame

from . import paths
from .geometry import CELL_SIZE, GRID_COLS, GRID_ROWS, cell_rect
from .registry import CONTROL_TYPES
from .skin import load_sprite_defs


# PNG dimensions can be read from the IHDR chunk without decoding the whole
# image. This lets freeform layouts infer design_resolution from a background
# image even before pygame.display.set_mode has been called (e.g. headless
# tests or layout validation), and avoids a pygame dependency on the image
# being loadable in the current video driver.
def _png_size(path):
    with open(path, "rb") as f:
        header = f.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    # bytes 12-15: IHDR chunk type, 16-19: width, 20-23: height (big-endian)
    if header[12:16] != b"IHDR":
        raise ValueError("missing IHDR chunk")
    width, height = struct.unpack(">II", header[16:24])
    return width, height


class LayoutError(Exception):
    """Raised for any layout file problem (caught by the mode)."""


class Panel:
    def __init__(self, panel_id, origin, size, fill_rgb, border_rgb):
        self.id = panel_id
        self.origin = tuple(origin)          # (col, row) on the design grid
        self.size = tuple(size)              # (w, h) in cells
        self.fill_rgb = tuple(fill_rgb)
        self.border_rgb = tuple(border_rgb)

    def contains(self, at, size) -> bool:
        """True if a control at cell `at` with `size` fits inside this panel."""
        return (
            0 <= at[0] and 0 <= at[1]
            and at[0] + size[0] <= self.size[0]
            and at[1] + size[1] <= self.size[1]
        )


class PlacedControl:
    """A control validated and resolved to a pixel rect on the canvas."""

    def __init__(self, ctype, sprite_id, panel, at, size, raw, rect_px):
        self.type = ctype
        self.sprite_id = sprite_id
        self.panel = panel                   # Panel, or None in freeform mode
        self.at = tuple(at)                  # grid: panel-relative cells;
                                             # freeform: pixel [x, y]
        self.size = tuple(size)              # grid: cells; freeform: pixels
        self.raw = raw                       # original dict (signal specs etc.)
        self.rect_px = tuple(rect_px)        # (x, y, w, h) px on the canvas

    @property
    def grid_origin(self):
        """Absolute (col, row) on the design grid (grid mode only)."""
        return (self.panel.origin[0] + self.at[0],
                self.panel.origin[1] + self.at[1])


class Layout:
    def __init__(self, name, mode, design_resolution, background_rgb,
                 panels, controls, background_image=None):
        self.name = name
        self.mode = mode                     # "grid" | "freeform"
        self.design_resolution = tuple(design_resolution)
        # None means "use the skin's background" (compositor resolves it)
        self.background_rgb = tuple(background_rgb) if background_rgb else None
        self.panels = panels                 # list[Panel] (empty in freeform)
        self.controls = controls             # list[PlacedControl]
        self.background_image = background_image  # path str or None


def _rects_overlap(a, b) -> bool:
    """Cell-rect overlap: rects are (col, row, w, h)."""
    return (a[0] < b[0] + b[2] and b[0] < a[0] + a[2]
            and a[1] < b[1] + b[3] and b[1] < a[1] + a[3])


def _check_common(name, i, c, sprite_defs):
    """Validate the fields both modes share. Returns (ctype, sprite_id)."""
    where = f"layout '{name}' control #{i}"
    ctype = c.get("type")
    if ctype not in CONTROL_TYPES:
        raise LayoutError(
            f"{where}: unknown type '{ctype}' (known: {sorted(CONTROL_TYPES)})"
        )
    sprite_id = c.get("sprite", CONTROL_TYPES[ctype])
    if sprite_id not in sprite_defs:
        raise LayoutError(f"{where}: unknown sprite '{sprite_id}'")
    return ctype, sprite_id


# ── grid mode (original slot approach) ──────────────────────────

def _load_grid(name, data, sprite_defs):
    resolution = data.get("design_resolution", [1920, 1080])
    grid_cols = resolution[0] // CELL_SIZE
    grid_rows = resolution[1] // CELL_SIZE
    if (grid_cols, grid_rows) != (GRID_COLS, GRID_ROWS):
        raise LayoutError(
            f"layout '{name}': design_resolution {resolution} gives a "
            f"{grid_cols}x{grid_rows} grid, expected {GRID_COLS}x{GRID_ROWS} "
            f"(grid mode is fixed at {GRID_COLS * CELL_SIZE}x1080; use "
            f"mode 'freeform' for other resolutions)"
        )

    panels = {}
    for i, p in enumerate(data.get("panels", [])):
        pid = p.get("id")
        if not pid:
            raise LayoutError(f"layout '{name}': panel #{i} missing 'id'")
        if pid in panels:
            raise LayoutError(f"layout '{name}': duplicate panel id '{pid}'")
        origin, size = p.get("origin"), p.get("size")
        if not origin or not size:
            raise LayoutError(f"layout '{name}': panel '{pid}' needs origin and size")
        if (origin[0] < 0 or origin[1] < 0
                or origin[0] + size[0] > grid_cols
                or origin[1] + size[1] > grid_rows):
            raise LayoutError(
                f"layout '{name}': panel '{pid}' {origin}+{size} exceeds the "
                f"{grid_cols}x{grid_rows} design grid"
            )
        panels[pid] = Panel(
            pid, origin, size,
            p.get("fill_rgb", [28, 30, 34]),
            p.get("border_rgb", [70, 74, 80]),
        )

    controls = []
    occupied = []  # cell rects for overlap detection: (col, row, w, h)
    for i, c in enumerate(data.get("controls", [])):
        where = f"layout '{name}' control #{i}"
        ctype, sprite_id = _check_common(name, i, c, sprite_defs)
        panel_id = c.get("panel")
        panel = panels.get(panel_id)
        if panel is None:
            raise LayoutError(f"{where}: unknown panel '{panel_id}'")
        at = c.get("at")
        if at is None:
            raise LayoutError(
                f"{where}: missing 'at' (explicit placement only, decision D1)"
            )

        geo = sprite_defs[sprite_id]
        size = (geo["w"], geo["h"])
        if not panel.contains(at, size):
            raise LayoutError(
                f"{where}: {sprite_id} at {at} with size {size} does not fit "
                f"inside panel '{panel_id}' ({panel.size} cells)"
            )

        rect = (panel.origin[0] + at[0], panel.origin[1] + at[1], *size)
        for other in occupied:
            if _rects_overlap(rect, other):
                raise LayoutError(
                    f"{where}: {sprite_id} at grid {rect[:2]} overlaps "
                    f"another control"
                )
        occupied.append(rect)

        controls.append(PlacedControl(
            ctype, sprite_id, panel, at, size, c,
            rect_px=cell_rect(at, size, panel.origin)))

    return Layout(name, "grid", resolution, data.get("background_rgb"),
                  list(panels.values()), controls)


# ── freeform mode (pixel-precise over full artwork, D6) ─────────

def _load_freeform(name, data, sprite_defs):
    # Resolve the background image first because, when no design_resolution
    # is supplied, the layout canvas should match the artwork's native
    # resolution. This avoids accidentally forcing a portrait background
    # into the default 1920x1080 landscape canvas.
    background_image = None
    bg = data.get("background_image")
    if bg:
        bg_path = paths.resolve_under(paths.BACKGROUNDS_DIR, bg)
        if not bg_path.exists():
            raise LayoutError(f"layout '{name}': background image not found: {bg_path}")
        background_image = str(bg_path)

    if "design_resolution" in data:
        resolution = data["design_resolution"]
    elif background_image:
        try:
            resolution = list(_png_size(background_image))
        except (OSError, ValueError):
            try:
                resolution = list(pygame.image.load(background_image).get_size())
            except pygame.error as e:
                raise LayoutError(f"layout '{name}': cannot read background image {background_image}: {e}")
    else:
        resolution = [1920, 1080]

    if resolution[0] <= 0 or resolution[1] <= 0:
        raise LayoutError(f"layout '{name}': bad design_resolution {resolution}")
    canvas_w, canvas_h = int(resolution[0]), int(resolution[1])

    controls = []
    for i, c in enumerate(data.get("controls", [])):
        where = f"layout '{name}' control #{i}"
        ctype, sprite_id = _check_common(name, i, c, sprite_defs)

        at = c.get("at")
        if at is None:
            raise LayoutError(f"{where}: missing 'at' [x, y] in pixels")

        # size: explicit "size" [w, h] px wins; otherwise the sprite's
        # natural footprint scaled by "scale" (default 1.0)
        if "size" in c:
            w, h = int(c["size"][0]), int(c["size"][1])
        else:
            geo = sprite_defs[sprite_id]
            scale = float(c.get("scale", 1.0))
            if scale <= 0:
                raise LayoutError(f"{where}: scale must be positive")
            w = int(geo["w"] * CELL_SIZE * scale)
            h = int(geo["h"] * CELL_SIZE * scale)
        if w <= 0 or h <= 0:
            raise LayoutError(f"{where}: control size must be positive")

        x, y = int(at[0]), int(at[1])
        if x < 0 or y < 0 or x + w > canvas_w or y + h > canvas_h:
            raise LayoutError(
                f"{where}: rect ({x}, {y}, {w}, {h}) exceeds the "
                f"{canvas_w}x{canvas_h} canvas"
            )
        # no overlap check in freeform: overlays sit on top of printed art,
        # and only the author knows where the art's dials actually are

        controls.append(PlacedControl(
            ctype, sprite_id, None, at, (w, h), c, rect_px=(x, y, w, h)))

    return Layout(name, "freeform", (canvas_w, canvas_h),
                  data.get("background_rgb"), [], controls,
                  background_image=background_image)


def load_layout(name_or_path: str) -> Layout:
    """
    Load and fully validate a layout by bare name (under
    assets/control_panel/layouts/) or by path.
    Raises LayoutError with a one-line reason on any problem.
    """
    layout_path = paths.resolve_under(paths.LAYOUTS_DIR, name_or_path, ".json")
    if not layout_path.exists():
        raise LayoutError(f"layout not found: {layout_path}")
    try:
        with open(layout_path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise LayoutError(f"invalid JSON in {layout_path}: {e}")

    name = data.get("name", layout_path.stem)
    sprite_defs = load_sprite_defs()["sprites"]
    mode = str(data.get("mode", "grid")).strip().lower()
    if mode == "grid":
        return _load_grid(name, data, sprite_defs)
    if mode == "freeform":
        return _load_freeform(name, data, sprite_defs)
    raise LayoutError(
        f"layout '{name}': unknown mode '{mode}' (expected 'grid' or 'freeform')"
    )

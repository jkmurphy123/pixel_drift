# controlpanel/geometry.py
#
# Cell-grid math for the control panel mode.
#
# Everything on the console is measured in CELLS of CELL_SIZE x CELL_SIZE px.
# All sprite footprints are whole multiples of one cell so panels tile the
# screen with no gaps or overlaps (see CONTROL_PANEL_DESIGN.md section 2).

CELL_SIZE = 128

# Design resolution: layouts are authored against this canvas and the
# compositor smoothscales it to the actual screen (decision D2).
DESIGN_WIDTH = 1920
DESIGN_HEIGHT = 1080

# Design grid: 15 cols x 8 rows. 1080 / 128 = 8.4375, so 8 full rows;
# the leftover 56 px are a centered letterbox band (see compositor).
GRID_COLS = DESIGN_WIDTH // CELL_SIZE   # 15
GRID_ROWS = DESIGN_HEIGHT // CELL_SIZE  # 8

# Fixed whitelist of allowed sprite/control footprints, in cells.
# Keeping this small makes layout validation trivial (design 2.2).
FOOTPRINTS = {
    "1x1": (1, 1),
    "2x1": (2, 1),
    "1x2": (1, 2),
    "2x2": (2, 2),
    "3x2": (3, 2),
    "4x1": (4, 1),
    "4x2": (4, 2),
    "2x4": (2, 4),
    "4x4": (4, 4),
}


def footprint_of(w_cells: int, h_cells: int) -> str | None:
    """Return the footprint name for a cell size, or None if not whitelisted."""
    for name, (w, h) in FOOTPRINTS.items():
        if (w, h) == (w_cells, h_cells):
            return name
    return None


def cell_rect(origin_cells, size_cells, panel_origin_cells=(0, 0)) -> tuple[int, int, int, int]:
    """
    Convert cell coordinates to a pixel rect on the design canvas.

    origin_cells: (col, row) of the control inside its panel
    size_cells:   (w, h) footprint in cells
    panel_origin_cells: (col, row) of the panel on the design grid
    Returns (x, y, w, h) in pixels.
    """
    col = panel_origin_cells[0] + origin_cells[0]
    row = panel_origin_cells[1] + origin_cells[1]
    return (
        col * CELL_SIZE,
        row * CELL_SIZE,
        size_cells[0] * CELL_SIZE,
        size_cells[1] * CELL_SIZE,
    )

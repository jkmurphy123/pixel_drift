# controlpanel/controls/base.py
#
# Control base class + the shared context every control gets.
#
# Controls are created from a validated PlacedControl (position/sprite/raw
# spec from the layout file) plus a ControlContext (rng + palette from the
# mode config). The static sprite background is blitted by the compositor;
# controls only draw their animated overlay primitives on top, in
# design-canvas coordinates.

import random

from ..geometry import CELL_SIZE, cell_rect  # noqa: F401  (cell_rect re-exported)


class ControlContext:
    """Shared per-mode state handed to every control."""

    def __init__(self, seed=None, accent_rgb=(255, 176, 64),
                 trace_rgb=(80, 255, 120), lamp_rgb=None):
        self.rng = random.Random(seed)
        self.accent_rgb = tuple(accent_rgb)
        self.trace_rgb = tuple(trace_rgb)
        # default lamp color when the sprite ID doesn't name one
        self.lamp_rgb = tuple(lamp_rgb) if lamp_rgb else (255, 60, 50)


class Control:
    """
    Base class for animated controls.

    rect: pixel rect on the design canvas (static sprite area).
    The layout's raw control dict is available as self.spec for per-control
    overrides (signal, wave, colors, ...).

    Color override chain for any drawn color: the generic "color" key wins,
    then the type-specific key ("needle_rgb", "trace_rgb", ...), then the
    control's built-in default. Use self._color() to resolve.
    """

    def __init__(self, placed, ctx: ControlContext):
        self.ctx = ctx
        self.spec = placed.raw
        self.type = placed.type
        self.sprite_id = placed.sprite_id
        # pixel rect on the design canvas — computed by the layout loader
        # for both grid (cells -> px) and freeform (explicit px) modes
        self.rect = placed.rect_px

    def _color(self, key: str, default):
        """
        Resolve a drawn color: layout "color" overrides everything, then
        the type-specific layout key (e.g. "needle_rgb"), then default.
        """
        return tuple(self.spec.get("color", self.spec.get(key, default)))

    def _anchor(self, key: str, default):
        """
        Anchor point as a fraction of the sprite rect, overridable per
        control in the layout (e.g. "pivot": [0.5, 0.62]). Fractions keep
        anchors valid across footprints (design section 7).
        """
        fx, fy = self.spec.get(key, default)
        x, y, w, h = self.rect
        return (x + fx * w, y + fy * h)

    def _window(self, default=(0.08, 0.18, 0.84, 0.64)):
        """
        Sub-rect of the sprite to draw into, as fractions
        (fx, fy, fw, fh) — used by scopes/readouts. Overridable via
        the layout's "window" key.
        """
        fx, fy, fw, fh = self.spec.get("window", default)
        x, y, w, h = self.rect
        return (x + fx * w, y + fy * h, fw * w, fh * h)

    def update(self, dt: float):
        pass

    def draw_overlay(self, surface):
        pass

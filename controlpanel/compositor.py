# controlpanel/compositor.py
#
# Compositor: builds the static layer once onto a canvas at the layout's
# design resolution, then smoothscales that canvas to the actual screen
# each frame (decision D2). Per frame the canvas is copied to a reusable
# frame surface and each control draws its animated overlay on top.
#
# Static layer contents depend on the layout mode (decision D6):
#   grid     — background color + panel plates + skin sprites
#   freeform — background color + the full background image (no sprites)

import pygame

from .geometry import CELL_SIZE, DESIGN_WIDTH, GRID_ROWS
from .layout import LayoutError

_DEFAULT_BG = (18, 20, 24)


class Compositor:
    def __init__(self, layout, skin=None, scale_mode="stretch"):
        self.layout = layout
        self.skin = skin                  # None in freeform mode
        self.scale_mode = scale_mode      # "stretch" | "fit" | "cover"
        self.canvas: pygame.Surface | None = None
        self._frame: pygame.Surface | None = None
        self._scaled: pygame.Surface | None = None
        self._scaled_size: tuple[int, int] | None = None

    @property
    def background_rgb(self):
        # layout background overrides the skin's, else a neutral default
        if self.layout.background_rgb:
            return self.layout.background_rgb
        if self.skin is not None:
            return self.skin.background_rgb
        return _DEFAULT_BG

    def build(self):
        """Compose the static layer onto the design canvas."""
        w, h = self.layout.design_resolution
        canvas = pygame.Surface((w, h))
        canvas.fill(self.background_rgb)

        if self.layout.background_image:
            try:
                img = pygame.image.load(self.layout.background_image).convert()
            except pygame.error as e:
                raise LayoutError(
                    f"layout '{self.layout.name}': cannot load background "
                    f"{self.layout.background_image}: {e}"
                )
            if img.get_size() != (w, h):
                img = pygame.transform.smoothscale(img, (w, h))
            canvas.blit(img, (0, 0))

        # panel plates: filled rect + thin border (grid mode only)
        grid_h = GRID_ROWS * CELL_SIZE
        for panel in self.layout.panels:
            rect = pygame.Rect(
                panel.origin[0] * CELL_SIZE,
                panel.origin[1] * CELL_SIZE,
                panel.size[0] * CELL_SIZE,
                panel.size[1] * CELL_SIZE,
            )
            # clip panels to the cell area (rows beyond GRID_ROWS would
            # spill into the letterbox band — layout validation prevents it)
            rect = rect.clip(pygame.Rect(0, 0, DESIGN_WIDTH, grid_h))
            pygame.draw.rect(canvas, panel.fill_rgb, rect)
            pygame.draw.rect(canvas, panel.border_rgb, rect, 2)

        # control sprites at their validated positions (grid mode only;
        # freeform controls draw overlays directly over the artwork)
        if self.skin is not None:
            for control in self.layout.controls:
                x, y, cw, ch = control.rect_px
                canvas.blit(self.skin.get(control.sprite_id), (x, y))

        self.canvas = canvas
        self._frame = None

    def render(self, screen: pygame.Surface, controls=()):
        """
        Blit the static canvas plus each control's animated overlay,
        scaling to the screen if resolutions differ.
        """
        screen.fill(self.background_rgb)
        if self.canvas is None:
            return
        if self._frame is None:
            self._frame = pygame.Surface(self.layout.design_resolution)
        frame = self._frame
        frame.blit(self.canvas, (0, 0))
        for control in controls:
            control.draw_overlay(frame)

        sw, sh = screen.get_size()
        fw, fh = frame.get_size()
        if (sw, sh) == (fw, fh):
            screen.blit(frame, (0, 0))
            return

        target, offset = self._scale_target(sw, sh, fw, fh)
        if target == (fw, fh):
            screen.blit(frame, offset)
        else:
            scaled = pygame.transform.smoothscale(frame, target)
            screen.blit(scaled, offset)

    def _scale_target(self, sw: int, sh: int, fw: int, fh: int):
        """Return (target_w, target_h) and (offset_x, offset_y) for the chosen scale_mode."""
        if self.scale_mode == "fit":
            scale = min(sw / fw, sh / fh) if fw and fh else 0
            tw, th = int(fw * scale), int(fh * scale)
            return (tw, th), ((sw - tw) // 2, (sh - th) // 2)
        if self.scale_mode == "cover":
            scale = max(sw / fw, sh / fh) if fw and fh else 0
            tw, th = int(fw * scale), int(fh * scale)
            return (tw, th), ((sw - tw) // 2, (sh - th) // 2)
        # legacy "stretch" fills the screen exactly
        return (sw, sh), (0, 0)

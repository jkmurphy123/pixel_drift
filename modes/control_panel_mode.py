# modes/control_panel_mode.py
#
# control_panel mode: an old-fashioned make-believe control panel — gauges,
# switches, lamps, scopes and readouts arranged by a JSON layout file and
# drawn from a swappable sprite-sheet skin. See CONTROL_PANEL_DESIGN.md.
#
# Phase 2: signals + animated gauge_round / lamp / scope controls. Other
# types render as their static sprite until their phase lands.
#
# Config keys (see modes_registry.json "controlpanel" entry):
#   layout_file (required) — layout name under assets/control_panel/layouts/
#                            or a full path
#   skin        (optional) — skin name under assets/control_panel/skins/
#                            or a full path (default "placeholder")
#   seed        (optional) — int; fixes the random choreography for debugging
#   accent_rgb  (optional) — needle/overlay color (default amber)
#   trace_rgb   (optional) — scope trace color (default green)
#   lamp_rgb    (optional) — fallback lamp color when the sprite ID doesn't
#                            name one (default red)

import pygame

from controlpanel.compositor import Compositor
from controlpanel.controls import ControlContext, make_control
from controlpanel.layout import LayoutError, load_layout
from controlpanel.skin import SkinError, load_skin


class ControlPanelMode:
    # Valid scaling strategies for the design canvas -> screen blit.
    #   stretch — legacy fill-the-screen behavior (may distort aspect ratio)
    #   fit     — uniform scale to fit inside the screen, letterboxing if needed
    #   cover   — uniform scale to cover the screen, cropping if needed
    _VALID_SCALE_MODES = {"stretch", "fit", "cover"}

    def __init__(self, config: dict):
        # Keep __init__ cheap and asset-free: tests construct every mode
        # without a display. All file/graphics work happens in enter().
        self.layout_file = config.get("layout_file", "")
        self.skin_name = str(config.get("skin", "placeholder")).strip()
        self.seed = config.get("seed")
        self.accent_rgb = tuple(config.get("accent_rgb", [255, 176, 64]))
        self.trace_rgb = tuple(config.get("trace_rgb", [80, 255, 120]))
        lamp_rgb = config.get("lamp_rgb")
        self.lamp_rgb = tuple(lamp_rgb) if lamp_rgb else None

        scale_mode = str(config.get("scale_mode", "fit")).strip().lower()
        if scale_mode not in self._VALID_SCALE_MODES:
            scale_mode = "fit"
        self.scale_mode = scale_mode

        self.manager = None
        self.compositor: Compositor | None = None
        self.controls: list = []
        self._error: str | None = None

    def enter(self, manager):
        self.manager = manager
        self._error = None
        self.controls = []
        try:
            layout = load_layout(self.layout_file)
            # freeform layouts carry their own full-panel artwork; grid
            # layouts are built from skin sprites (decision D6)
            skin = None if layout.mode == "freeform" else load_skin(self.skin_name)
            self.compositor = Compositor(layout, skin, scale_mode=self.scale_mode)
            self.compositor.build()

            ctx = ControlContext(seed=self.seed, accent_rgb=self.accent_rgb,
                                 trace_rgb=self.trace_rgb, lamp_rgb=self.lamp_rgb)
            for placed in layout.controls:
                control = make_control(placed, ctx)
                if control is not None:
                    self.controls.append(control)

            skin_name = skin.name if skin is not None else "(background image)"
            print(f"[ControlPanel] skin='{skin_name}' layout='{layout.name}' "
                  f"mode={layout.mode} "
                  f"({len(layout.panels)} panels, {len(layout.controls)} controls, "
                  f"{len(self.controls)} animated)")
        except (SkinError, LayoutError) as e:
            # kiosk-friendly: log once, show the reason on screen
            self._error = str(e)
            self.compositor = None
            print(f"[ControlPanel] failed to load: {self._error}")

    def exit(self):
        # drop surfaces so GC can reclaim them
        self.compositor = None
        self.controls = []
        self.manager = None

    def handle_event(self, event):
        pass

    def update(self, dt: float):
        for control in self.controls:
            control.update(dt)

    def render(self, screen: pygame.Surface):
        if self.compositor is not None:
            self.compositor.render(screen, self.controls)
            return

        # error fallback: plain background + one-line reason
        screen.fill((18, 20, 24))
        if self.manager is not None and self._error:
            font = self.manager.cache.get_font("dejavusansmono", 28)
            surf = font.render(f"ControlPanel: {self._error}", True, (255, 120, 120))
            screen.blit(surf, (40, 40))

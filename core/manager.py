# core/manager.py
#
# ModeManager: scene-based lifecycle for modes inside a single pygame shell.
# One window forever — no mode creates its own display.

import gc

import pygame

from .cache import ResourceCache
from .loader import create_mode_instance


class ModeManager:
    def __init__(self, screen, registry, modes_config, max_modes, secrets=None):
        self.screen = screen
        self.registry = registry
        self.modes_config = modes_config
        self.max_modes = max_modes
        self.secrets = secrets or {}

        self.cache = ResourceCache()

        self.mode_index = 0
        self.current_mode = None

        # Transition settings
        self.fade_seconds = 0.20
        self._fade_t = 0.0
        self._fade_state = "idle"  # idle | fading_out | fading_in
        self._pending_index = None

        # Pre-allocated fade overlay (reused every frame; recreated on resize).
        # The old controllers allocated a fresh SRCALPHA surface per frame
        # during transitions — 60 temp surfaces/sec for no benefit.
        self._fade_overlay = None
        self._fade_overlay_size = None

        # Overlay settings
        self.show_mode_number = True
        self.mode_number_font_px = 18
        self.mode_number_margin_px = 8

        # Optional: reduce memory pressure by clearing image cache each switch
        self.clear_images_on_switch = True

    # Convenience so modes written against the old MinimalHost keep working.
    @property
    def width(self):
        return self.screen.get_width()

    @property
    def height(self):
        return self.screen.get_height()

    # ---------- scene lifecycle ----------

    def start(self, initial_index=0):
        self.mode_index = initial_index % self.max_modes
        self._activate_now(self.mode_index)

    def request_switch(self, new_index: int):
        new_index = new_index % self.max_modes
        if new_index == self.mode_index:
            return
        self._pending_index = new_index
        self._fade_t = 0.0
        self._fade_state = "fading_out"

    def _activate_now(self, index: int):
        # Exit old
        if self.current_mode is not None:
            try:
                self.current_mode.exit()
            except Exception as e:
                print(f"[Mode] exit() error: {e}")
            self.current_mode = None

        # Optional cache trimming between modes to reduce long-run memory build-up
        if self.clear_images_on_switch:
            self.cache.clear_images()
        gc.collect()

        # Create new
        self.mode_index = index
        self.current_mode = create_mode_instance(
            self.registry, self.modes_config, index, self.secrets
        )

        if self.current_mode is None:
            return

        # Enter new
        try:
            self.current_mode.enter(self)
        except Exception as e:
            print(f"[Mode] enter() error: {e}")
            self.current_mode = None

    # ---------- main loop hooks ----------

    def handle_event(self, event):
        if self.current_mode is not None:
            try:
                self.current_mode.handle_event(event)
            except Exception as e:
                print(f"[Mode] handle_event() error: {e}")

    def update(self, dt: float):
        # Transition logic
        if self._fade_state == "fading_out":
            self._fade_t += dt
            if self._fade_t >= self.fade_seconds:
                # Switch at full black
                if self._pending_index is not None:
                    self._activate_now(self._pending_index)
                self._pending_index = None
                self._fade_state = "fading_in"
                self._fade_t = self.fade_seconds

        elif self._fade_state == "fading_in":
            self._fade_t -= dt
            if self._fade_t <= 0.0:
                self._fade_t = 0.0
                self._fade_state = "idle"

        # Mode update
        if self.current_mode is not None:
            try:
                self.current_mode.update(dt)
            except Exception as e:
                print(f"[Mode] update() error: {e}")

    def render(self):
        if self.current_mode is not None:
            try:
                self.current_mode.render(self.screen)
            except Exception as e:
                print(f"[Mode] render() error: {e}")
                self.screen.fill((0, 0, 0))
        else:
            self.screen.fill((0, 0, 0))

        # Mode number in lower-left (small)
        if self.show_mode_number:
            try:
                font = self.cache.get_font(None, self.mode_number_font_px, bold=False)
                label = font.render(f"{self.mode_index}", True, (220, 220, 220))
                x = self.mode_number_margin_px
                y = self.screen.get_height() - label.get_height() - self.mode_number_margin_px
                self.screen.blit(label, (x, y))
            except Exception:
                pass

        # Fade overlay (black), reusing one pre-allocated surface
        if self._fade_state != "idle":
            alpha = int(255 * (self._fade_t / self.fade_seconds)) if self.fade_seconds > 0 else 255
            alpha = max(0, min(255, alpha))
            size = self.screen.get_size()
            if self._fade_overlay is None or self._fade_overlay_size != size:
                self._fade_overlay = pygame.Surface(size, pygame.SRCALPHA)
                self._fade_overlay_size = size
            self._fade_overlay.fill((0, 0, 0, alpha))
            self.screen.blit(self._fade_overlay, (0, 0))

    def is_transitioning(self) -> bool:
        return self._fade_state != "idle"

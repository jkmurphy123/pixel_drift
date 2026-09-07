from __future__ import annotations

import pygame

from .behavior import update_queen, update_workers
from .config import load_config
from .planner import update_planner
from .render import AntFarmRenderer
from .world import World


class AntFarmMode:
    def __init__(self, config: dict):
        self.config = load_config(config)
        self.manager = None
        self.world = World(self.config)
        self.renderer = AntFarmRenderer(self.config)
        self._tick_accum = 0.0
        self._last_size = (0, 0)

    def enter(self, manager):
        self.manager = manager
        self._rebuild_world()

    def exit(self):
        self.manager = None

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
            self._rebuild_world()

    def update(self, dt: float):
        if self.manager is None:
            return

        if self.manager.screen.get_size() != self._last_size:
            self._rebuild_world()

        tick_dt = 1.0 / self.config.sim_ticks_per_second
        self._tick_accum += dt
        while self._tick_accum >= tick_dt:
            self._tick_accum -= tick_dt
            update_workers(self.world, tick_dt)
            update_queen(self.world, tick_dt)
            update_planner(self.world, tick_dt)

    def render(self, screen: pygame.Surface):
        self.renderer.render(screen, self.world, self.manager)

    def _rebuild_world(self):
        if self.manager is None:
            return
        self._last_size = self.manager.screen.get_size()
        self.world.rebuild(*self._last_size)
        self._tick_accum = 0.0

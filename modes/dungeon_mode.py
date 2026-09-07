# modes/dungeon_mode.py
#
# pixel_drift mode entrypoint for the procedural dungeon expedition.
# Phase 2: connected dungeon generation, fog-of-war revealing, party marker,
# frontier selection, movement animation, and the standard pixel_drift mode
# contract.
#
# Config keys (see modes_registry.json "dungeonexpedition" entry):
#   seed                       (optional) int; fixes dungeon generation
#   dungeon_width              (optional) int; default 64
#   dungeon_height             (optional) int; default 40
#   minimum_rooms              (optional) int; default 8
#   maximum_rooms              (optional) int; default 15
#   seconds_per_step           (optional) float; default 2.0
#   journal_pause_seconds      (optional) float; default 8.0
#   simulation_speed           (optional) float; default 1.0
#   major_grid_interval        (optional) int; default 5
#   show_room_numbers          (optional) bool; default True
#   show_expedition_route      (optional) bool; default True
#   paper_style                (optional) str; "blue_green" or "sepia"
#   layout                     (optional) str; "auto", "portrait", "landscape"
#   font_name                  (optional) str; font passed to manager cache

import pygame

from dungeon.generator import GenerationError, generate_dungeon
from dungeon.renderer import Renderer
from dungeon.simulation import create_expedition, update_expedition


class DungeonMode:
    def __init__(self, config: dict):
        self.config = config
        self.seed = config.get("seed")
        self.dungeon_width = int(config.get("dungeon_width", 64))
        self.dungeon_height = int(config.get("dungeon_height", 40))
        self.minimum_rooms = int(config.get("minimum_rooms", 8))
        self.maximum_rooms = int(config.get("maximum_rooms", 15))

        self.manager = None
        self.renderer: Renderer | None = None
        self._error: str | None = None
        self._paused = False

    def enter(self, manager):
        self.manager = manager
        self._error = None
        try:
            dungeon = generate_dungeon(
                width=self.dungeon_width,
                height=self.dungeon_height,
                min_rooms=self.minimum_rooms,
                max_rooms=self.maximum_rooms,
                seed=self.seed,
            )
            expedition = create_expedition(dungeon, seed=self.seed)

            self.renderer = Renderer(
                expedition=expedition,
                config=self.config,
                font_getter=lambda name, size: manager.cache.get_font(name, size),
            )
            print(
                f"[DungeonExpedition] generated floor {dungeon.width}x{dungeon.height} "
                f"with {len(dungeon.rooms)} rooms (seed={dungeon.seed})"
            )
        except GenerationError as e:
            self._error = str(e)
            self.renderer = None
            print(f"[DungeonExpedition] failed to generate: {self._error}")

    def exit(self):
        self.renderer = None
        self.manager = None

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_SPACE:
                self._paused = not self._paused
            elif event.key == pygame.K_UP:
                self.config["simulation_speed"] = float(self.config.get("simulation_speed", 1.0)) + 0.5
            elif event.key == pygame.K_DOWN:
                self.config["simulation_speed"] = max(0.0, float(self.config.get("simulation_speed", 1.0)) - 0.5)

    def update(self, dt: float):
        if self.renderer is None or self._paused:
            return
        update_expedition(self.renderer.expedition, dt, self.config)

    def render(self, screen: pygame.Surface):
        if self.renderer is not None:
            self.renderer.render(screen)
            return

        screen.fill((18, 20, 24))
        if self.manager is not None and self._error:
            font = self.manager.cache.get_font("dejavusansmono", 28)
            surf = font.render(f"DungeonExpedition: {self._error}", True, (255, 120, 120))
            screen.blit(surf, (40, 40))

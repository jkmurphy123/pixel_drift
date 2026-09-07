# modes/dungeon_mode.py
#
# pixel_drift mode entrypoint for the procedural dungeon expedition.
# Phase 4: persistent atomic saves, multi-floor progression, and retreat logic.
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
#   save_path                  (optional) str; default "dungeon_save.json"
#   save_interval_seconds      (optional) float; default 30.0
#   auto_descend               (optional) bool; default True
#   heal_on_descend            (optional) int; default 2

import os

import pygame

from dungeon.generator import GenerationError, generate_dungeon
from dungeon.persistence import load_expedition, save_expedition, wait_for_saves
from dungeon.renderer import Renderer
from dungeon.simulation import create_expedition, descend_floor, update_expedition
from dungeon.model import ExpeditionPhase


DEFAULT_SAVE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dungeon_save.json")


class DungeonMode:
    def __init__(self, config: dict):
        self.config = config
        self.seed = config.get("seed")
        self.dungeon_width = int(config.get("dungeon_width", 64))
        self.dungeon_height = int(config.get("dungeon_height", 40))
        self.minimum_rooms = int(config.get("minimum_rooms", 8))
        self.maximum_rooms = int(config.get("maximum_rooms", 15))
        self.save_path = str(config.get("save_path", DEFAULT_SAVE_PATH))
        self.save_interval = max(5.0, float(config.get("save_interval_seconds", 30.0)))
        self.auto_descend = bool(config.get("auto_descend", True))

        self.manager = None
        self.renderer: Renderer | None = None
        self._error: str | None = None
        self._paused = False
        self._save_timer = 0.0
        self._descend_timer = 0.0

    def enter(self, manager):
        self.manager = manager
        self._error = None
        self._save_timer = 0.0
        self._descend_timer = 0.0

        expedition = load_expedition(self.save_path)
        if expedition is not None:
            self.renderer = Renderer(
                expedition=expedition,
                config=self.config,
                font_getter=lambda name, size: manager.cache.get_font(name, size),
            )
            print(
                f"[DungeonExpedition] resumed floor {expedition.floor} "
                f"with {len(expedition.dungeon.rooms)} rooms (seed={expedition.seed})"
            )
            return

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
        if self.renderer is not None:
            save_expedition(self.renderer.expedition, self.save_path)
            wait_for_saves(timeout=2.0)
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
            elif event.key == pygame.K_s:
                if self.renderer is not None:
                    save_expedition(self.renderer.expedition, self.save_path)

    def update(self, dt: float):
        if self.renderer is None or self._paused:
            return

        expedition = self.renderer.expedition
        update_expedition(expedition, dt, self.config)

        # Periodic background save.
        self._save_timer += dt
        if self._save_timer >= self.save_interval:
            self._save_timer = 0.0
            save_expedition(expedition, self.save_path)

        # Auto-descend to the next floor after a brief pause on completion.
        if expedition.phase == ExpeditionPhase.EXPEDITION_COMPLETE and self.auto_descend:
            self._descend_timer += dt
            if self._descend_timer >= 10.0:
                self._descend_timer = 0.0
                if descend_floor(expedition, self.config):
                    print(f"[DungeonExpedition] descended to floor {expedition.floor}")
                else:
                    print("[DungeonExpedition] could not descend further")
        else:
            self._descend_timer = 0.0

    def render(self, screen: pygame.Surface):
        if self.renderer is not None:
            self.renderer.render(screen)
            return

        screen.fill((18, 20, 24))
        if self.manager is not None and self._error:
            font = self.manager.cache.get_font("dejavusansmono", 28)
            surf = font.render(f"DungeonExpedition: {self._error}", True, (255, 120, 120))
            screen.blit(surf, (40, 40))

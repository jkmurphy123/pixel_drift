import random
import time
import pygame


class ConwayLifeMode:
    def __init__(self, config: dict):
        self.title = config.get("title", "CONWAY'S GAME OF LIFE")
        self.update_hz = float(config.get("update_hz", 10.0))
        self.random_fill = float(config.get("random_fill", 0.28))
        self.wrap = bool(config.get("wrap", True))
        self.reset_if_static_steps = int(config.get("reset_if_static_steps", 80))
        self.reset_interval_sec = float(config.get("reset_interval_sec", 120.0))
        self.seed = config.get("seed")

        self.cells_on_short_side = int(config.get("cells_on_short_side", 80))
        self.cell_size_px = config.get("cell_size_px")

        self.alive_rgb = tuple(config.get("alive_rgb", [180, 255, 200]))
        self.dead_rgb = tuple(config.get("dead_rgb", [0, 0, 0]))
        self.show_grid = bool(config.get("show_grid", False))
        self.grid_rgb = tuple(config.get("grid_rgb", [20, 40, 20]))

        self.manager = None
        self.w = 0
        self.h = 0
        self.cols = 0
        self.rows = 0
        self.cell_size = 8
        self.grid = []

        self._step_accum = 0.0
        self._last_reset_t = time.time()
        self._static_steps = 0
        self._cell_surf = None  # pre-rendered alive cell, rebuilt on resize

    def enter(self, manager):
        self.manager = manager
        self._sync_size(force=True)
        self._reset_grid()

    def exit(self):
        self.manager = None

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_SPACE, pygame.K_r):
                self._reset_grid()

    def update(self, dt: float):
        if self._sync_size(force=False):
            self._reset_grid()
            return

        self._step_accum += dt
        step_time = 1.0 / max(1e-6, self.update_hz)
        while self._step_accum >= step_time:
            self._step_accum -= step_time
            changed = self._step_grid()
            if changed == 0:
                self._static_steps += 1
            else:
                self._static_steps = 0

        if self.reset_if_static_steps > 0 and self._static_steps >= self.reset_if_static_steps:
            self._reset_grid()

        if self.reset_interval_sec > 0:
            now = time.time()
            if now - self._last_reset_t >= self.reset_interval_sec:
                self._reset_grid()

    def render(self, screen: pygame.Surface):
        screen.fill(self.dead_rgb)

        # Batch all alive cells into one C-accelerated blits() call using a
        # pre-rendered cell surface. (Previously one pygame.draw.rect per
        # cell — tens of thousands of Python-level draw calls per frame at
        # kiosk resolutions.)
        cs = self.cell_size
        if self._cell_surf is None or self._cell_surf.get_width() != cs:
            self._cell_surf = pygame.Surface((cs, cs))
            self._cell_surf.fill(self.alive_rgb)
        blit_seq = [
            (self._cell_surf, (x * cs, y * cs))
            for y, row in enumerate(self.grid)
            for x, alive in enumerate(row)
            if alive
        ]
        if blit_seq:
            screen.blits(blit_seq, doreturn=0)

        if self.show_grid:
            for x in range(0, self.w, self.cell_size):
                pygame.draw.line(screen, self.grid_rgb, (x, 0), (x, self.h), 1)
            for y in range(0, self.h, self.cell_size):
                pygame.draw.line(screen, self.grid_rgb, (0, y), (self.w, y), 1)

        font = self.manager.cache.get_font("dejavusansmono", max(12, int(self.h * 0.02)), bold=True)
        title_surf = font.render(self.title, True, self.alive_rgb)
        screen.blit(title_surf, (16, 14))

    def _sync_size(self, force: bool) -> bool:
        if self.manager is None:
            return False
        w, h = self.manager.screen.get_size()
        if not force and (w == self.w and h == self.h):
            return False
        self.w, self.h = w, h
        short_side = min(self.w, self.h)
        if self.cell_size_px is not None:
            self.cell_size = max(4, int(self.cell_size_px))
        else:
            self.cell_size = max(4, int(short_side / max(10, self.cells_on_short_side)))
        self.cols = max(10, self.w // self.cell_size)
        self.rows = max(10, self.h // self.cell_size)
        return True

    def _reset_grid(self):
        if self.seed is not None:
            random.seed(self.seed)
        self._sync_size(force=True)
        self.grid = [
            [random.random() < self.random_fill for _ in range(self.cols)]
            for _ in range(self.rows)
        ]
        self._step_accum = 0.0
        self._static_steps = 0
        self._last_reset_t = time.time()

    def _step_grid(self) -> int:
        changed = 0
        next_grid = [[False for _ in range(self.cols)] for _ in range(self.rows)]

        if self.wrap:
            for y in range(self.rows):
                ym1 = (y - 1) % self.rows
                yp1 = (y + 1) % self.rows
                for x in range(self.cols):
                    xm1 = (x - 1) % self.cols
                    xp1 = (x + 1) % self.cols
                    neighbors = (
                        self.grid[ym1][xm1] + self.grid[ym1][x] + self.grid[ym1][xp1]
                        + self.grid[y][xm1] + self.grid[y][xp1]
                        + self.grid[yp1][xm1] + self.grid[yp1][x] + self.grid[yp1][xp1]
                    )
                    alive = self.grid[y][x]
                    next_alive = neighbors == 3 or (alive and neighbors == 2)
                    next_grid[y][x] = next_alive
                    if next_alive != alive:
                        changed += 1
        else:
            for y in range(self.rows):
                for x in range(self.cols):
                    neighbors = 0
                    for dy in (-1, 0, 1):
                        ny = y + dy
                        if ny < 0 or ny >= self.rows:
                            continue
                        for dx in (-1, 0, 1):
                            if dx == 0 and dy == 0:
                                continue
                            nx = x + dx
                            if nx < 0 or nx >= self.cols:
                                continue
                            if self.grid[ny][nx]:
                                neighbors += 1
                    alive = self.grid[y][x]
                    next_alive = neighbors == 3 or (alive and neighbors == 2)
                    next_grid[y][x] = next_alive
                    if next_alive != alive:
                        changed += 1

        self.grid = next_grid
        return changed

import random
import pygame


class GaltonBoardMode:
    def __init__(self, config: dict):
        self.title = config.get("title", "GALTON BOARD")
        self.pin_rows = int(config.get("pin_rows", config.get("pins", 12)))
        self.total_balls = int(config.get("balls", 300))
        self.drop_rate = float(config.get("drop_rate", 40.0))
        self.drop_one_at_time = bool(config.get("drop_one_at_time", True))
        self.wait_after_sec = float(config.get("wait_after_sec", 10.0))
        self.fall_speed = float(config.get("fall_speed", 260.0))
        self.seed = config.get("seed")

        self.background_rgb = tuple(config.get("background_rgb", [0, 0, 0]))
        self.pin_rgb = tuple(config.get("pin_rgb", [190, 190, 210]))
        self.bin_rgb = tuple(config.get("bin_rgb", [80, 80, 90]))

        self.ball_color_cfg = config.get("ball_color", config.get("ball_rgb", [255, 200, 120]))
        self.ball_radius_px = config.get("ball_radius_px")
        self.pin_radius_px = config.get("pin_radius_px")
        self.show_pins = bool(config.get("show_pins", True))
        self.show_bins = bool(config.get("show_bins", True))

        self.manager = None
        self.w = 0
        self.h = 0

        self.board_rect = pygame.Rect(0, 0, 0, 0)
        self.pin_spacing = 20.0
        self.row_spacing = 18.0
        self.pin_radius = 3
        self.ball_radius = 5
        self.center_x = 0.0
        self.start_y = 0.0
        self.row_ys = []
        self.bin_top = 0.0
        self.bin_bottom = 0.0

        self._rng = random.Random()
        self._spawn_accum = 0.0
        self._balls_dropped = 0
        self._balls_active = []
        self._bin_stacks = []
        self._state = "dropping"
        self._wait_t = 0.0
        self._last_size = (0, 0)

        self._random_colors = False
        self._ball_color = (255, 200, 120)

    def enter(self, manager):
        self.manager = manager
        self._reset_board(force_rebuild=True)

    def exit(self):
        self.manager = None

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_r, pygame.K_SPACE):
                self._reset_board(force_rebuild=False)

    def update(self, dt: float):
        if self._sync_size():
            self._reset_board(force_rebuild=False)

        if self._state == "dropping":
            if self.drop_one_at_time:
                if self._balls_dropped < self.total_balls and not self._balls_active:
                    self._spawn_ball()
                    self._spawn_accum = 0.0
            else:
                self._spawn_accum += dt
                if self.drop_rate > 0:
                    spawn_interval = 1.0 / max(1e-6, self.drop_rate)
                    while self._spawn_accum >= spawn_interval and self._balls_dropped < self.total_balls:
                        self._spawn_accum -= spawn_interval
                        self._spawn_ball()

        self._update_balls(dt)

        if self._state == "dropping":
            if self._balls_dropped >= self.total_balls and not self._balls_active:
                self._state = "waiting"
                self._wait_t = 0.0

        elif self._state == "waiting":
            self._wait_t += dt
            if self._wait_t >= self.wait_after_sec:
                self._reset_board(force_rebuild=False)

    def render(self, screen: pygame.Surface):
        screen.fill(self.background_rgb)

        if self.show_pins:
            for pos in self._pins:
                pygame.draw.circle(screen, self.pin_rgb, (int(pos[0]), int(pos[1])), self.pin_radius)

        if self.show_bins:
            for i in range(self.pin_rows + 2):
                x = self.center_x - (self.pin_rows * self.pin_spacing / 2.0) + i * self.pin_spacing
                pygame.draw.line(screen, self.bin_rgb, (x, self.bin_top), (x, self.bin_bottom), 1)

        self._draw_landed_balls(screen)
        self._draw_active_balls(screen)

        font = self.manager.cache.get_font("dejavusansmono", max(14, int(self.h * 0.02)), bold=True)
        title_surf = font.render(self.title, True, self.pin_rgb)
        screen.blit(title_surf, (16, 16))

        small = self.manager.cache.get_font("dejavusansmono", max(12, int(self.h * 0.015)), bold=False)
        status = f"Balls: {min(self._balls_dropped, self.total_balls)}/{self.total_balls}"
        status_surf = small.render(status, True, self.bin_rgb)
        screen.blit(status_surf, (16, 16 + title_surf.get_height() + 6))

    def _sync_size(self) -> bool:
        if self.manager is None:
            return False
        size = self.manager.screen.get_size()
        if size == self._last_size:
            return False
        self._last_size = size
        self.w, self.h = size
        self._rebuild_geometry()
        return True

    def _reset_board(self, force_rebuild: bool):
        self.pin_rows = max(5, min(30, int(self.pin_rows)))
        self.total_balls = max(1, int(self.total_balls))
        self.drop_rate = max(0.1, float(self.drop_rate))
        self.drop_one_at_time = bool(self.drop_one_at_time)
        self.fall_speed = max(40.0, float(self.fall_speed))

        if self.manager is not None:
            self.w, self.h = self.manager.screen.get_size()
            self._last_size = (self.w, self.h)
            if force_rebuild:
                self._rebuild_geometry()
            else:
                self._rebuild_geometry()

        if self.seed is not None:
            self._rng.seed(self.seed)

        self._balls_dropped = 0
        self._spawn_accum = 0.0
        self._balls_active = []
        self._bin_stacks = [[] for _ in range(self.pin_rows + 1)]
        self._state = "dropping"
        self._wait_t = 0.0

        self._random_colors, self._ball_color = self._parse_ball_color(self.ball_color_cfg)

    def _rebuild_geometry(self):
        margin_x = int(self.w * 0.08)
        margin_top = int(self.h * 0.10)
        margin_bottom = int(self.h * 0.12)

        self.board_rect = pygame.Rect(
            margin_x,
            margin_top,
            max(1, self.w - margin_x * 2),
            max(1, self.h - margin_top - margin_bottom),
        )

        self.center_x = self.board_rect.centerx

        width = self.board_rect.width
        height = self.board_rect.height
        self.pin_spacing = max(10.0, min(width / max(1, self.pin_rows), height / (self.pin_rows + 4)))
        self.row_spacing = self.pin_spacing * 0.9

        if self.pin_radius_px is not None:
            self.pin_radius = max(2, int(self.pin_radius_px))
        else:
            self.pin_radius = max(2, int(self.pin_spacing * 0.12))

        if self.ball_radius_px is not None:
            self.ball_radius = max(3, int(self.ball_radius_px))
        else:
            self.ball_radius = max(3, int(self.pin_spacing * 0.18))

        self.start_y = self.board_rect.top - self.row_spacing * 0.7
        self.row_ys = [self.board_rect.top + (i + 0.6) * self.row_spacing for i in range(self.pin_rows)]
        self.bin_top = self.board_rect.top + (self.pin_rows + 0.8) * self.row_spacing
        self.bin_bottom = self.board_rect.bottom

        self._pins = []
        for row in range(self.pin_rows):
            y = self.row_ys[row]
            left = self.center_x - (row * self.pin_spacing / 2.0)
            for col in range(row + 1):
                x = left + col * self.pin_spacing
                self._pins.append((x, y))

    def _parse_ball_color(self, value):
        if isinstance(value, str):
            low = value.strip().lower()
            if low == "random":
                return True, (255, 200, 120)
            if low.startswith("#") and len(low) == 7:
                try:
                    r = int(low[1:3], 16)
                    g = int(low[3:5], 16)
                    b = int(low[5:7], 16)
                    return False, (r, g, b)
                except ValueError:
                    return False, (255, 200, 120)
            named = {
                "white": (240, 240, 240),
                "red": (240, 80, 80),
                "green": (120, 240, 140),
                "blue": (100, 180, 240),
                "yellow": (240, 220, 120),
                "cyan": (120, 230, 230),
                "magenta": (220, 120, 240),
            }
            if low in named:
                return False, named[low]
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return False, (int(value[0]), int(value[1]), int(value[2]))
        return False, (255, 200, 120)

    def _random_ball_rgb(self):
        return (
            self._rng.randint(80, 255),
            self._rng.randint(80, 255),
            self._rng.randint(80, 255),
        )

    def _x_for_row(self, row: int, rights: int) -> float:
        left = self.center_x - (row * self.pin_spacing / 2.0)
        return left + rights * self.pin_spacing

    def _spawn_ball(self):
        rights = 0
        x_points = [self.center_x]
        for row in range(self.pin_rows):
            x_points.append(self._x_for_row(row, rights))
            if self._rng.random() < 0.5:
                rights += 1

        x_points.append(self._x_for_row(self.pin_rows, rights))
        y_points = [self.start_y] + self.row_ys + [self.bin_top]

        color = self._random_ball_rgb() if self._random_colors else self._ball_color
        ball = {
            "seg": 0,
            "y": y_points[0],
            "x_points": x_points,
            "y_points": y_points,
            "bin": rights,
            "color": color,
        }
        self._balls_active.append(ball)
        self._balls_dropped += 1

    def _update_balls(self, dt: float):
        if not self._balls_active:
            return
        remaining = []
        for ball in self._balls_active:
            travel = self.fall_speed * dt
            landed = False
            while travel > 0 and not landed:
                seg = ball["seg"]
                y0 = ball["y_points"][seg]
                y1 = ball["y_points"][seg + 1]
                seg_len = max(1e-6, y1 - y0)
                remaining_dist = y1 - ball["y"]
                if travel < remaining_dist:
                    ball["y"] += travel
                    travel = 0
                else:
                    ball["y"] = y1
                    travel -= remaining_dist
                    ball["seg"] += 1
                    if ball["seg"] >= len(ball["y_points"]) - 1:
                        landed = True
                        bin_idx = max(0, min(self.pin_rows, int(ball["bin"])))
                        self._bin_stacks[bin_idx].append(ball["color"])
            if not landed:
                remaining.append(ball)
        self._balls_active = remaining

    def _draw_active_balls(self, screen):
        for ball in self._balls_active:
            seg = ball["seg"]
            x0 = ball["x_points"][seg]
            x1 = ball["x_points"][seg + 1]
            y0 = ball["y_points"][seg]
            y1 = ball["y_points"][seg + 1]
            if y1 <= y0:
                x = x1
            else:
                t = (ball["y"] - y0) / (y1 - y0)
                x = x0 + (x1 - x0) * t
            pygame.draw.circle(screen, ball["color"], (int(x), int(ball["y"])), self.ball_radius)

    def _draw_landed_balls(self, screen):
        if not self._bin_stacks:
            return
        base_y = self.bin_bottom - self.ball_radius - 4
        step_y = self.ball_radius * 2 + 2
        for i, stack in enumerate(self._bin_stacks):
            if not stack:
                continue
            x = self._x_for_row(self.pin_rows, i)
            max_stack = int((self.bin_bottom - self.bin_top) / step_y)
            visible = min(len(stack), max_stack)
            for k in range(visible):
                y = base_y - k * step_y
                color = stack[k]
                pygame.draw.circle(screen, color, (int(x), int(y)), self.ball_radius)

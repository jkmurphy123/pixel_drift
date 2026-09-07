import random
import pygame

class BinaryWaterfallMode:
    def __init__(self, config: dict):
        self.title = config.get("title", "BINARY WATERFALL")
        self.accent_rgb = tuple(config.get("accent_rgb", [0, 255, 0]))
        self.refresh_hz = float(config.get("refresh_hz", 60.0))
        self.drop_speed_range = config.get("drop_speed_range", [2, 7])
        self.spawn_rate = config.get("spawn_rate", 0.1)
        self.flicker_speed = config.get("flicker_speed", 0.05)
        self.binary_only = config.get("binary_only", False)
        
        self.scanline_alpha = config.get("scanline_alpha", 15)
        self.vignette_strength = config.get("vignette_strength", 0.3)

        self.manager = None
        self.w, self.h = 0, 0
        self.drops = []  # Each drop: [column_x, current_y, speed, characters_list]
        self.char_size = 20
        self.chars = ["0", "1"] if self.binary_only else ["0", "1", "A", "B", "C", "D", "E", "F", "x", "#", "!", "v"]

    def enter(self, manager):
        self.manager = manager
        self.w, self.h = self.manager.screen.get_size()
        self.char_size = max(14, int(self.h * 0.025))
        # Pre-fill some drops so it doesn't start empty
        for _ in range(20):
            self._spawn_drop(random_y=True)

    def exit(self):
        self.manager = None

    def _spawn_drop(self, random_y=False):
        col = random.randint(0, self.w // self.char_size) * self.char_size
        y = random.randint(-self.h, 0) if random_y else -self.char_size
        speed = random.uniform(self.drop_speed_range[0], self.drop_speed_range[1])
        # Length of the trail
        length = random.randint(10, 25)
        trail = [random.choice(self.chars) for _ in range(length)]
        self.drops.append({'x': col, 'y': y, 'speed': speed, 'chars': trail})

    def update(self, dt: float):
        # Move existing drops
        for drop in self.drops:
            drop['y'] += drop['speed']
            # Occasionally flicker characters in the trail
            if random.random() < self.flicker_speed:
                idx = random.randint(0, len(drop['chars'])-1)
                drop['chars'][idx] = random.choice(self.chars)

        # Remove drops that are off screen
        self.drops = [d for d in self.drops if d['y'] - (len(d['chars']) * self.char_size) < self.h]

        # Spawn new drops
        if random.random() < self.spawn_rate:
            self._spawn_drop()

    def render(self, screen: pygame.Surface):
        screen.fill((0, 5, 0)) # Very dark green base
        
        font = self.manager.cache.get_font("dejavusansmono", self.char_size, bold=True)

        for drop in self.drops:
            for i, char in enumerate(drop['chars']):
                # Calculate Y position for each character in the trail
                char_y = drop['y'] - (i * self.char_size)
                
                # Skip if off screen
                if char_y < -self.char_size or char_y > self.h:
                    continue

                # The "Head" of the drop is white, the tail fades to dark green
                if i == 0:
                    color = (200, 255, 200) # Bright head
                else:
                    # Fade calculation
                    alpha_factor = 1.0 - (i / len(drop['chars']))
                    color = (
                        int(self.accent_rgb[0] * alpha_factor),
                        int(self.accent_rgb[1] * alpha_factor),
                        int(self.accent_rgb[2] * alpha_factor)
                    )

                char_surf = font.render(char, True, color)
                screen.blit(char_surf, (drop['x'], char_y))

        # UI Overlay: Title
        title_font = self.manager.cache.get_font("dejavusansmono", int(self.h * 0.02), bold=True)
        title_surf = title_font.render(self.title, True, self.accent_rgb)
        screen.blit(title_surf, (20, self.h - 40))

        self._draw_crt_effects(screen)

    def _draw_crt_effects(self, screen):
        return

import os
import random
import pygame

class AnimatedCityRainMode:
    def __init__(self, config: dict):
        self.title = config.get("title", "ATMOSPHERIC RAIN")
        self.image_folder = config.get("image_folder")
        self.accent_rgb = tuple(config.get("accent_rgb", [180, 200, 255]))
        self.density = int(config.get("rain_density", 150))
        self.speed_range = config.get("rain_speed_range", [10, 20])
        self.wind_slant = int(config.get("wind_slant", -2))
        
        self.scanline_alpha = config.get("scanline_alpha", 15)
        self.vignette_strength = config.get("vignette_strength", 0.3)

        self.manager = None
        self.background = None
        self.rain_drops = [] # [x, y, speed, length]

    def enter(self, manager):
        self.manager = manager
        w, h = self.manager.screen.get_size()
        
        # Load random image
        self._load_random_background(w, h)
        
        # Initialize rain
        for _ in range(self.density):
            self.rain_drops.append([
                random.randint(-100, w + 100), 
                random.randint(0, h), 
                random.uniform(self.speed_range[0], self.speed_range[1]),
                random.randint(5, 12)
            ])

    def _load_random_background(self, w, h):
        try:
            files = [f for f in os.listdir(self.image_folder) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
            if not files:
                return
            
            img_path = os.path.join(self.image_folder, random.choice(files))
            raw_img = pygame.image.load(img_path).convert()
            
            # Scale to cover the screen (Center Crop style)
            img_rect = raw_img.get_rect()
            screen_ratio = w / h
            img_ratio = img_rect.width / img_rect.height
            
            if img_ratio > screen_ratio:
                new_h = h
                new_w = int(h * img_ratio)
            else:
                new_w = w
                new_h = int(w / img_ratio)
                
            self.background = pygame.transform.smoothscale(raw_img, (new_w, new_h))
            self.bg_offset = ((w - new_w) // 2, (h - new_h) // 2)
        except Exception as e:
            print(f"Error loading background: {e}")

    def update(self, dt: float):
        w, h = self.manager.screen.get_size()
        for drop in self.rain_drops:
            drop[1] += drop[2] # vertical move
            drop[0] += self.wind_slant # horizontal slant
            
            # Reset if off screen
            if drop[1] > h:
                drop[1] = random.randint(-50, -10)
                drop[0] = random.randint(-100, w + 100)

    def render(self, screen: pygame.Surface):
        # 1. Draw Background
        if self.background:
            screen.blit(self.background, self.bg_offset)
        else:
            screen.fill((20, 20, 30))

        # 2. Draw Rain Particles
        for drop in self.rain_drops:
            start_pos = (drop[0], drop[1])
            end_pos = (drop[0] - self.wind_slant, drop[1] + drop[3])
            # Draw with slight transparency
            pygame.draw.line(screen, (150, 160, 180, 100), start_pos, end_pos, 1)

        # 3. Overlays
        self._draw_crt_effects(screen)
        
        title_font = self.manager.cache.get_font("dejavusansmono", int(screen.get_height() * 0.02), bold=True)
        title_surf = title_font.render(self.title, True, self.accent_rgb)
        screen.blit(title_surf, (20, screen.get_height() - 40))

    def _draw_crt_effects(self, screen):
        return

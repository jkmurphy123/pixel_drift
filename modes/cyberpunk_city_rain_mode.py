import random
import pygame
import math

class CyberpunkCityRainMode:
    def __init__(self, config: dict):
        self.title = config.get("title", "CYBERPUNK CITY")
        self.accent_rgb = tuple(config.get("accent_rgb", [140, 80, 255]))
        self.refresh_hz = float(config.get("refresh_hz", 60.0))
        self.rain_density = int(config.get("rain_density", 100))
        self.parallax_speed = float(config.get("parallax_speed", 1.0))
        self.vehicle_freq = float(config.get("vehicle_frequency", 0.02))
        
        self.scanline_alpha = config.get("scanline_alpha", 15)
        self.vignette_strength = config.get("vignette_strength", 0.4)

        self.manager = None
        self.w, self.h = 0, 0
        
        # Parallax Layers: [(x_pos, width, height, color)]
        self.layers = [[], [], []] 
        self.rain_drops = []
        self.vehicles = [] # [{'x', 'y', 'speed', 'color'}]

    def enter(self, manager):
        self.manager = manager
        self.w, self.h = self.manager.screen.get_size()
        self._generate_city()
        for _ in range(self.rain_density):
            self.rain_drops.append([random.randint(0, self.w), random.randint(0, self.h), random.uniform(10, 20)])

    def _generate_city(self):
        # Generate 3 layers of buildings
        for layer_idx in range(3):
            curr_x = 0
            while curr_x < self.w * 2: # Extra width for scrolling
                b_w = random.randint(60, 150)
                b_h = random.randint(self.h // 4, self.h // (1.5 + layer_idx))
                # Darker color for closer layers
                brightness = 10 + (layer_idx * 15)
                color = (brightness, brightness, brightness + 10)
                self.layers[layer_idx].append({'x': curr_x, 'w': b_w, 'h': b_h, 'color': color})
                curr_x += b_w + random.randint(-10, 20)

    def update(self, dt: float):
        # Update Rain
        for drop in self.rain_drops:
            drop[1] += drop[2] # Fall speed
            drop[0] -= 2 # Slant
            if drop[1] > self.h:
                drop[1] = random.randint(-20, 0)
                drop[0] = random.randint(0, self.w + 100)

        # Update Parallax City (very slow scroll)
        for i, layer in enumerate(self.layers):
            move_amount = self.parallax_speed * (i + 1) * 0.2
            for b in layer:
                b['x'] -= move_amount
            # Simple wrap-around logic
            if layer[0]['x'] + layer[0]['w'] < 0:
                first = layer.pop(0)
                first['x'] = layer[-1]['x'] + layer[-1]['w']
                layer.append(first)

        # Spawn Vehicles
        if random.random() < self.vehicle_freq:
            self.vehicles.append({
                'x': self.w + 50,
                'y': random.randint(100, self.h - 100),
                'speed': random.uniform(5, 12),
                'color': random.choice([(255, 50, 50), (50, 255, 255), self.accent_rgb])
            })
        
        for v in self.vehicles:
            v['x'] -= v['speed']
        self.vehicles = [v for v in v in self.vehicles if v['x'] > -100]

    def render(self, screen: pygame.Surface):
        screen.fill((2, 2, 8)) # Deep night sky

        # Render Layers (Back to Front)
        for i in range(2, -1, -1):
            for b in self.layers[i]:
                rect = (int(b['x']), self.h - b['h'], b['w'], b['h'])
                pygame.draw.rect(screen, b['color'], rect)
                # Random window lights on closest layer
                if i == 0 and random.random() < 0.005:
                     pygame.draw.rect(screen, (100, 100, 40), (b['x']+10, self.h - b['h'] + 20, 5, 5))

        # Render Vehicles
        for v in self.vehicles:
            pygame.draw.line(screen, v['color'], (v['x'], v['y']), (v['x'] + 20, v['y']), 2)
            # Add a glow/trail effect
            trail = pygame.Surface((40, 4), pygame.SRCALPHA)
            pygame.draw.rect(trail, (*v['color'], 100), (0, 0, 40, 2))
            screen.blit(trail, (v['x'], v['y']))

        # Render Rain
        for drop in self.rain_drops:
            pygame.draw.line(screen, (80, 80, 120), (drop[0], drop[1]), (drop[0] - 2, drop[1] + 5), 1)

        # Title and UI
        title_font = self.manager.cache.get_font("dejavusansmono", int(self.h * 0.02), bold=True)
        title_surf = title_font.render(self.title, True, self.accent_rgb)
        screen.blit(title_surf, (30, self.h - 50))

        self._draw_crt_effects(screen)

    def _draw_crt_effects(self, screen):
        return

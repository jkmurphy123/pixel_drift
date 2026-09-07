import time
import json
import math
import random
import urllib.request
import pygame

class GlobalThreatMapMode:
    def __init__(self, config: dict):
        self.title = config.get("title", "THREAT MONITOR")
        self.accent_rgb = tuple(config.get("accent_rgb", [50, 255, 100]))
        self.update_interval = float(config.get("api_update_interval_min", 5)) * 60
        self.glow = int(config.get("vector_glow_strength", 2))
        
        self.manager = None
        self.events = [] # List of {'lat', 'lon', 'mag', 'time', 'alpha'}
        self.last_fetch = 0
        self.w, self.h = 0, 0

    def enter(self, manager):
        self.manager = manager
        self.w, self.h = self.manager.screen.get_size()
        self._fetch_data()

    def _fetch_data(self):
        """Pulls real-time earthquake data as a proxy for 'threat events'."""
        try:
            # USGS Earthquake API (Past 24 hours)
            url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode())
            
            new_events = []
            for feature in data['features'][:20]: # Only take recent 20
                coords = feature['geometry']['coordinates']
                new_events.append({
                    'lon': coords[0],
                    'lat': coords[1],
                    'mag': feature['properties']['mag'],
                    'alpha': 255,
                    'pulse': 0.0
                })
            self.events = new_events
            self.last_fetch = time.time()
        except Exception as e:
            print(f"API Error: {e}")

    def _lat_lon_to_px(self, lat, lon):
        # Basic Equirectangular Projection
        x = int((lon + 180) * (self.w / 360))
        y = int((90 - lat) * (self.h / 180))
        return x, y

    def update(self, dt: float):
        if time.time() - self.last_fetch > self.update_interval:
            self._fetch_data()
        
        # Animate event pulses
        for e in self.events:
            e['pulse'] += dt * 3
            if e['pulse'] > math.pi: e['pulse'] = 0

    def render(self, screen: pygame.Surface):
        screen.fill((5, 15, 5)) # Deep vector black/green
        
        # 1. Draw World Grid
        grid_color = (self.accent_rgb[0]//5, self.accent_rgb[1]//5, self.accent_rgb[2]//5)
        for x in range(0, self.w, self.w // 18):
            pygame.draw.line(screen, grid_color, (x, 0), (x, self.h), 1)
        for y in range(0, self.h, self.h // 9):
            pygame.draw.line(screen, grid_color, (0, y), (self.w, y), 1)

        # 2. Draw Vector Events
        for e in self.events:
            x, y = self._lat_lon_to_px(e['lat'], e['lon'])
            
            # Pulsing Circle (Wargames "Impact" Style)
            radius = int(10 + math.sin(e['pulse']) * 10)
            pygame.draw.circle(screen, self.accent_rgb, (x, y), radius, 1)
            pygame.draw.circle(screen, (255, 255, 255), (x, y), 2) # Center point
            
            # Draw Data Tag
            font = self.manager.cache.get_font("dejavusansmono", 12, bold=True)
            tag = f"LVL:{e['mag']} LOC:{int(e['lat'])},{int(e['lon'])}"
            surf = font.render(tag, True, self.accent_rgb)
            screen.blit(surf, (x + 15, y - 5))

        # 3. UI Header
        title_font = self.manager.cache.get_font("dejavusansmono", int(self.h * 0.03), bold=True)
        title_surf = title_font.render(self.title, True, self.accent_rgb)
        screen.blit(title_surf, (20, 20))
        
        # Clock
        time_str = time.strftime("%H:%M:%S UTC")
        time_surf = title_font.render(time_str, True, self.accent_rgb)
        screen.blit(time_surf, (self.w - time_surf.get_width() - 20, 20))

        self._draw_crt_effects(screen)

    def _draw_crt_effects(self, screen):
        # Scanlines and Vignette (matching your system style)
        for y in range(0, self.h, 4):
            line = pygame.Surface((self.w, 2), pygame.SRCALPHA)
            line.fill((0, 0, 0, 30))
            screen.blit(line, (0, y))
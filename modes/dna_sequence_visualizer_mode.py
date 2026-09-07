import time
import random
import math
import pygame

class DNASequenceVisualizerMode:
    def __init__(self, config: dict):
        self.title = config.get("title", "GENETIC SEQUENCER")
        self.accent_rgb = tuple(config.get("accent_rgb", [100, 255, 100]))
        self.refresh_hz = float(config.get("refresh_hz", 60.0))
        self.scroll_speed = float(config.get("scroll_speed", 3.0))
        self.helix_speed = float(config.get("helix_rotation_speed", 1.0))
        self.marker_prob = float(config.get("marker_probability", 0.05))
        
        self.scanline_alpha = config.get("scanline_alpha", 15)
        self.vignette_strength = config.get("vignette_strength", 0.3)

        self.manager = None
        self.w, self.h = 0, 0
        self.clock = pygame.time.Clock()
        
        # Sequence data
        self.bases = ["A", "C", "G", "T"]
        self.rows = [] # (string, is_marker)
        self.scroll_offset = 0.0
        
        # Visuals
        self.angle = 0.0

    # Inside the enter method:
    def enter(self, manager):
        self.manager = manager
        self.w, self.h = self.manager.screen.get_size()
        # Change 0.025 to 0.015 for smaller text
        self.font_size = int(self.h * 0.015) 
        self._generate_initial_data()

    def exit(self):
        self.manager = None

    def _generate_initial_data(self):
        num_rows = (self.h // 16) + 5
        for _ in range(num_rows):
            self.rows.append(self._generate_row())

    def _generate_row(self):
        if random.random() < self.marker_prob:
            return (f"MARKER: [0x{random.randint(0x1000, 0xFFFF):X}]", True)
        seq = "".join(random.choices(self.bases, k=12))
        return (f"{seq}  {random.randint(10,99)}%", False)

    def update(self, dt: float):
        self.angle += self.helix_speed * dt
        self.scroll_offset += self.scroll_speed
        
        # Change 24 to 16 (or match your new font size)
        if self.scroll_offset >= 16: 
            self.scroll_offset = 0
            self.rows.pop(0)
            self.rows.append(self._generate_row())

    def render(self, screen: pygame.Surface):
        screen.fill((5, 10, 5))
        
        # 1. Draw Helix (Left side)
        helix_x = self.w * 0.25
        self._draw_helix(screen, helix_x)

        # 2. Draw Text Sequence (Right side)
        font = self.manager.cache.get_font("dejavusansmono", int(self.h * 0.015), bold=True)
        text_x = self.w * 0.55
        
        for i, (text, is_marker) in enumerate(self.rows):
            y = (i * 16) - self.scroll_offset
            color = self.accent_rgb if is_marker else (self.accent_rgb[0]//2, self.accent_rgb[1]//2, self.accent_rgb[2]//2)
            surf = font.render(text, True, color)
            screen.blit(surf, (text_x, y))

        # 3. UI Overlays
        title_font = self.manager.cache.get_font("dejavusansmono", int(self.h * 0.02), bold=True)
        title_surf = title_font.render(self.title, True, self.accent_rgb)
        screen.blit(title_surf, (20, 20))

        self._draw_crt_effects(screen)

    def _draw_helix(self, screen, cx):
        # Mathematical double helix
        nodes = 20
        spacing = self.h / nodes
        for i in range(nodes + 1):
            y = i * spacing
            # Calculate 3D-like sine positions
            a1 = self.angle + (i * 0.5)
            a2 = a1 + math.pi # Opposite side
            
            x1 = cx + math.sin(a1) * (self.w * 0.1)
            x2 = cx + math.sin(a2) * (self.w * 0.1)
            
            # Draw rungs (connections)
            pygame.draw.line(screen, (40, 60, 40), (x1, y), (x2, y), 1)
            
            # Draw "Nucleotides" (spheres)
            size1 = 5 + int(math.cos(a1) * 3) # Perspective size
            size2 = 5 + int(math.cos(a2) * 3)
            
            pygame.draw.circle(screen, self.accent_rgb, (int(x1), int(y)), size1)
            pygame.draw.circle(screen, (200, 200, 200), (int(x2), int(y)), size2)

    def _draw_crt_effects(self, screen):
        return

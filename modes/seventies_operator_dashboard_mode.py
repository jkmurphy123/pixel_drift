# seventies_operator_dashboard_mode.py
import pygame
import random
import time
import math

class SeventiesComputerDashboardMode:
    """
    Simulated 1970s computer operator console with blinking lamps,
    analog-style meters, and scrolling job logs.
    """

    def __init__(self, config: dict):
        self.title = config.get("title", "CENTRAL SYSTEM // NODE-70")
        self.accent_rgb = tuple(config.get("accent_rgb", [255, 210, 140]))
        self.refresh_hz = float(config.get("refresh_hz", 60))
        self.panel_count = int(config.get("panel_count", 3))
        self.lamp_count = int(config.get("lamp_count", 18))
        self.flicker_rate = float(config.get("flicker_rate", 2.0))
        self.needle_speed = float(config.get("needle_speed", 0.3))
        self.show_log = bool(config.get("show_log", True))
        self.seed = int(config.get("seed", int(time.time())))

        random.seed(self.seed)

        self._last_update = 0
        self._refresh_period = 1.0 / self.refresh_hz
        self._lamps = [random.random() > 0.5 for _ in range(self.lamp_count)]
        self._panel_values = [random.random() for _ in range(self.panel_count)]
        self._logs = []
        self._last_log_time = 0
        self._font = None
        self._small_font = None

    def enter(self, manager):
        self.manager = manager
        self.w, self.h = self.manager.screen.get_size()
        self._font = self.manager.cache.get_font("dejavusansmono", int(self.h * 0.05), bold=True)
        self._small_font = self.manager.cache.get_font("dejavusansmono", int(self.h * 0.025), bold=False)
        self._generate_initial_logs()

    def exit(self):
        self._logs.clear()

    def update(self, dt):
        now = time.time()
        if (now - self._last_update) >= self._refresh_period:
            self._update_lamps()
            self._update_panels(dt)
            if self.show_log and now - self._last_log_time > 1.5:
                self._append_log_entry()
                self._last_log_time = now
            self._last_update = now

    def render(self, screen):
        screen.fill((0, 0, 0))
        w, h = self.w, self.h

        # TITLE BAR
        title_surf = self._font.render(self.title, True, self.accent_rgb)
        screen.blit(title_surf, (w * 0.05, h * 0.05))

        # PANELS
        self._draw_panels(screen, w, h)

        # LAMPS
        self._draw_lamps(screen, w, h)

        # LOG
        if self.show_log:
            self._draw_logs(screen, w, h)

    # ---------- Internal Rendering ----------

    def _draw_panels(self, screen, w, h):
        panel_h = int(h * 0.15)
        spacing = int(h * 0.05)
        start_y = h * 0.20
        cx = w // 2

        for i, val in enumerate(self._panel_values):
            y = start_y + i * (panel_h + spacing)
            self._draw_gauge(screen, cx, y, int(w * 0.6), panel_h, val)

    def _draw_gauge(self, screen, cx, y, width, height, value):
        rect = pygame.Rect(cx - width // 2, y, width, height)
        pygame.draw.rect(screen, (40, 40, 40), rect, border_radius=8)
        pygame.draw.rect(screen, self.accent_rgb, rect, 2, border_radius=8)

        # Needle
        needle_x = rect.left + int(value * width)
        pygame.draw.line(screen, self.accent_rgb, (needle_x, rect.top + 4), (needle_x, rect.bottom - 4), 3)

        # Ticks
        for i in range(0, 11):
            tx = rect.left + int(i * width / 10)
            pygame.draw.line(screen, (120, 120, 120), (tx, rect.bottom - 8), (tx, rect.bottom - 2), 1)

    def _draw_lamps(self, screen, w, h):
        lamp_radius = int(min(w, h) * 0.015)
        start_x = int(w * 0.08)
        start_y = int(h * 0.75)
        gap = int(w * 0.045)
        for i, state in enumerate(self._lamps):
            x = start_x + i * gap
            color = self.accent_rgb if state else (60, 60, 60)
            pygame.draw.circle(screen, color, (x, start_y), lamp_radius)
            pygame.draw.circle(screen, (0, 0, 0), (x, start_y), lamp_radius, 2)

    def _draw_logs(self, screen, w, h):
        log_area_h = int(h * 0.18)
        base_y = h - log_area_h - int(h * 0.03)
        pygame.draw.rect(screen, (15, 15, 15), (w * 0.05, base_y, w * 0.9, log_area_h))
        pygame.draw.rect(screen, self.accent_rgb, (w * 0.05, base_y, w * 0.9, log_area_h), 1)

        y = base_y + 8
        for text in self._logs[-int(log_area_h / (self._small_font.get_linesize() + 2)):]:
            surf = self._small_font.render(text, True, self.accent_rgb)
            screen.blit(surf, (w * 0.07, y))
            y += self._small_font.get_linesize() + 2

    # ---------- Internal Simulation ----------

    def _update_lamps(self):
        for i in range(self.lamp_count):
            if random.random() < self.flicker_rate * 0.05:
                self._lamps[i] = not self._lamps[i]

    def _update_panels(self, dt):
        for i in range(self.panel_count):
            drift = (random.random() - 0.5) * self.needle_speed
            new_val = self._panel_values[i] + drift
            self._panel_values[i] = max(0.0, min(1.0, new_val))

    def _generate_initial_logs(self):
        self._logs = [
            "INIT MAINFRAME DIAGNOSTICS...",
            "CPU STATUS: NOMINAL",
            "TAPE DRIVE 02: ONLINE",
            "CARD READER: READY",
            "CORE TEMP: 32.4C",
            "SYS READY FOR JOB INPUT"
        ]

    def _append_log_entry(self):
        templates = [
            "JOB {id:04d}: EXECUTE BATCH {num}",
            "TAPE UNIT {unit} READ BLOCK {blk:03d}",
            "I/O CH {ch}: {msg}",
            "MEM CHECKSUM: OK",
            "TEMP SENSOR {s}: {t:.1f}C",
            "ALERT CLEARED: CODE {code}"
        ]
        t = random.choice(templates)
        line = t.format(
            id=random.randint(1000, 9999),
            num=random.randint(1, 9),
            unit=random.randint(1, 3),
            blk=random.randint(1, 120),
            ch=random.choice(["A", "B", "C"]),
            msg=random.choice(["READY", "COMPLETE", "WAIT", "TIMEOUT"]),
            s=random.randint(1, 4),
            t=random.uniform(28.0, 39.0),
            code=random.randint(10, 99)
        )
        self._logs.append(line)
        if len(self._logs) > 100:
            self._logs.pop(0)

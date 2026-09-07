# system_information_mode.py

import os
import time
import platform
import shutil
import subprocess
from datetime import datetime

import pygame


class SystemInformationMode:
    """
    Scene-style system info dashboard with big clock.

    Config:
      - refresh_hz (float): info updates per second (default 2.0)
      - show_seconds (bool): include seconds in clock (default True)

    Layout behavior matches your original intent:
      - Portrait: top ~1/4 clock, bottom ~3/4 single column
      - Landscape: top ~1/3 clock, bottom ~2/3 two columns if wide enough
    """

    def __init__(self, config: dict):
        self.refresh_hz = float(config.get("refresh_hz", 2.0))
        self.show_seconds = bool(config.get("show_seconds", True))

        # runtime
        self.manager = None
        self.w = 0
        self.h = 0

        self._is_portrait = False
        self._side_margin = 0
        self._top_pad = 0
        self._clock_area_h = 0
        self._info_area_h = 0

        # font sizes (derived)
        self._base_clock_size = 0
        self._info_size = 0

        # refresh scheduling
        self._last_refresh = 0.0
        self._refresh_period = 1.0 / max(0.1, self.refresh_hz)

        # cached info lines [(text, is_dim)]
        self._lines = []

        # colors
        self._bg = (0, 0, 0)
        self._fg = (235, 235, 235)
        self._dim = (160, 160, 160)
        self._accent = (80, 200, 255)

    # ---------- lifecycle ----------

    def enter(self, manager):
        self.manager = manager
        self._recompute_layout()
        self._force_refresh()

    def exit(self):
        self.manager = None
        self._lines = []

    def handle_event(self, event):
        # (optional) allow ESC to quit the whole app if you want:
        # if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
        #     pygame.event.post(pygame.event.Event(pygame.QUIT))
        pass

    def update(self, dt: float):
        # handle resolution changes (hotplug, rotation, etc.)
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            self._force_refresh()

        now = time.time()
        if (now - self._last_refresh) >= self._refresh_period:
            self._lines = self._gather_info_lines()
            self._last_refresh = now

    def render(self, screen: pygame.Surface):
        w, h = self.w, self.h
        screen.fill(self._bg)

        # --- CLOCK (top band) ---
        now = datetime.now()
        time_str = now.strftime("%H:%M:%S") if self.show_seconds else now.strftime("%H:%M")

        # heartbeat tint (same idea as original)
        time_color = self._fg
        if self.show_seconds:
            time_color = self._fg if (now.microsecond // 500_000) == 0 else self._accent

        max_clock_w = w - 2 * self._side_margin
        clock_size = self._base_clock_size

        # auto-fit horizontally by shrinking if needed
        while True:
            clock_font = self.manager.cache.get_font("dejavusansmono", clock_size, bold=True)
            clock_surf = clock_font.render(time_str, True, time_color)
            if clock_surf.get_width() <= max_clock_w or clock_size <= 28:
                break
            clock_size = max(28, clock_size - 6)

        clock_rect = clock_surf.get_rect(center=(w // 2, (self._clock_area_h // 2) + self._top_pad))
        screen.blit(clock_surf, clock_rect)

        # divider
        pygame.draw.line(
            screen,
            self._dim,
            (self._side_margin, self._clock_area_h),
            (w - self._side_margin, self._clock_area_h),
            2
        )

        # --- INFO PANEL (bottom band) ---
        info_font = self.manager.cache.get_font("dejavusansmono", self._info_size, bold=False)

        left_margin = self._side_margin
        top_margin = self._clock_area_h + int(self._info_area_h * 0.05)
        line_h = info_font.get_linesize() + 4

        use_two_cols = (not self._is_portrait) and (w >= 900)

        if not self._lines:
            # small hint if lines haven't populated yet
            hint = info_font.render("Gathering system info…", True, self._dim)
            screen.blit(hint, (left_margin, top_margin))
            return

        if use_two_cols:
            col_gap = int(w * 0.06)
            col_w = (w - 2 * left_margin - col_gap) // 2
            mid = (len(self._lines) + 1) // 2
            cols = [self._lines[:mid], self._lines[mid:]]

            for col_i, col_lines in enumerate(cols):
                x = left_margin + col_i * (col_w + col_gap)
                y = top_margin
                for text, is_dim in col_lines:
                    color = self._dim if is_dim else self._fg
                    surf = info_font.render(text, True, color)
                    screen.blit(surf, (x, y))
                    y += line_h
        else:
            x = left_margin
            y = top_margin
            y_limit = h - int(self._info_area_h * 0.05)

            for text, is_dim in self._lines:
                if y + line_h > y_limit:
                    hint = info_font.render("…(more hidden) reduce info/font or add scrolling", True, self._dim)
                    screen.blit(hint, (x, y_limit - line_h))
                    break
                color = self._dim if is_dim else self._fg
                surf = info_font.render(text, True, color)
                screen.blit(surf, (x, y))
                y += line_h

    # ---------- helpers ----------

    def _recompute_layout(self):
        self.w, self.h = self.manager.screen.get_size()
        w, h = self.w, self.h

        self._is_portrait = h > w
        self._side_margin = int(w * 0.06)
        self._top_pad = int(h * 0.02)

        if self._is_portrait:
            self._clock_area_h = int(h * 0.25)
        else:
            self._clock_area_h = int(h * 0.33)

        self._info_area_h = h - self._clock_area_h

        # Font sizing (same logic as original)
        if self._is_portrait:
            self._base_clock_size = max(24, int(w * 0.18))
            self._info_size = max(14, int(w * 0.045))
        else:
            self._base_clock_size = max(24, h // 5)
            self._info_size = max(16, h // 40)

    def _force_refresh(self):
        self._lines = self._gather_info_lines()
        self._last_refresh = time.time()

    def _gather_info_lines(self):
        host = platform.node()
        os_name = f"{platform.system()} {platform.release()}"
        arch = platform.machine()

        ip = self._get_ip()
        uptime = self._get_uptime()
        temp = self._get_cpu_temp()
        load = self._get_load()
        mem = self._get_mem()
        disk = self._get_disk("/")
        vcgencmd = self._get_vcgencmd_throttle()

        lines = [
            (f"Host: {host}", False),
            (f"OS: {os_name}", False),
            (f"Arch: {arch}", True),
            ("", True),
            (f"IP: {ip}", False),
            (f"Uptime: {uptime}", False),
            (f"CPU Temp: {temp}", False),
            (f"Load (1/5/15): {load}", False),
            ("", True),
            (f"RAM: {mem}", False),
            (f"Disk (/): {disk}", False),
        ]

        if vcgencmd:
            lines += [("", True), (f"Throttle: {vcgencmd}", False)]

        lines += [
            ("", True),
            ("Tip: turn the knob to change modes", True),
            ("Hold knob 2s to reboot", True),
        ]

        return [(t, d) for (t, d) in lines if t is not None]

    def _get_ip(self):
        try:
            out = subprocess.check_output(["hostname", "-I"], text=True).strip()
            return out if out else "n/a"
        except Exception:
            return "n/a"

    def _get_uptime(self):
        try:
            with open("/proc/uptime", "r") as f:
                seconds = float(f.read().split()[0])
            days = int(seconds // 86400)
            hours = int((seconds % 86400) // 3600)
            mins = int((seconds % 3600) // 60)
            if days > 0:
                return f"{days}d {hours}h {mins}m"
            return f"{hours}h {mins}m"
        except Exception:
            return "n/a"

    def _get_cpu_temp(self):
        paths = ["/sys/class/thermal/thermal_zone0/temp"]
        for p in paths:
            try:
                with open(p, "r") as f:
                    raw = f.read().strip()
                c = float(raw) / 1000.0
                return f"{c:.1f} °C"
            except Exception:
                continue
        return "n/a"

    def _get_load(self):
        try:
            a, b, c = os.getloadavg()
            return f"{a:.2f}  {b:.2f}  {c:.2f}"
        except Exception:
            return "n/a"

    def _get_mem(self):
        try:
            meminfo = {}
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    k, v = line.split(":", 1)
                    meminfo[k.strip()] = v.strip()
            total_kb = int(meminfo["MemTotal"].split()[0])
            avail_kb = int(meminfo.get("MemAvailable", meminfo["MemFree"]).split()[0])
            used_kb = total_kb - avail_kb
            total_mb = total_kb / 1024
            used_mb = used_kb / 1024
            return f"{used_mb:.0f} MB / {total_mb:.0f} MB"
        except Exception:
            return "n/a"

    def _get_disk(self, path):
        try:
            du = shutil.disk_usage(path)
            used_gb = du.used / (1024**3)
            total_gb = du.total / (1024**3)
            return f"{used_gb:.1f} GB / {total_gb:.1f} GB"
        except Exception:
            return "n/a"

    def _get_vcgencmd_throttle(self):
        try:
            out = subprocess.check_output(["vcgencmd", "get_throttled"], text=True).strip()
            return out
        except Exception:
            return ""

import math
import platform
import random
import re
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime

import pygame


LATENCY_RE = re.compile(r"time[=<]?\s*(\d+(?:\.\d+)?)\s*ms", re.IGNORECASE)
WINDOWS_AVG_RE = re.compile(r"Average = (\d+)\s*ms", re.IGNORECASE)


@dataclass
class DeviceSpec:
    hostname: str
    name: str
    role: str


@dataclass
class DeviceState:
    hostname: str
    name: str
    role: str
    ip_address: str = "resolving..."
    reachable: bool = False
    latency_ms: float | None = None
    last_checked_epoch: float = 0.0
    last_change_epoch: float = 0.0
    last_error: str = "pending"
    up_count: int = 0
    down_count: int = 0
    current_streak: int = 0
    current_streak_up: bool = False


class NetworkStatusWallMode:
    """
    Network Status Wall
    - Monitors a configured set of hosts with DNS resolution + ping reachability.
    - Renders a responsive grid of device cards for portrait or landscape kiosks.

    Config:
      - title (str)
      - subtitle (str)
      - accent_rgb ([r,g,b])
      - devices ([{"hostname": str, "name": str, "role": str?}, ...])
      - columns_portrait (int)
      - columns_landscape (int)
      - panel_spacing_scale (float)
      - refresh_hz (float)
      - poll_interval_sec (float)
      - ping_timeout_sec (float)
      - scanline_alpha (int)
      - noise_alpha (int)
      - vignette_strength (float)
      - seed (int)
    """

    def __init__(self, config: dict):
        self.title = str(config.get("title", "HOME NETWORK STATUS WALL"))
        self.subtitle = str(config.get("subtitle", "LAN reachability monitor"))
        self.accent_rgb = tuple(config.get("accent_rgb", [90, 220, 255]))
        self.refresh_hz = float(config.get("refresh_hz", 60.0))
        self.columns_portrait = int(config.get("columns_portrait", 2))
        self.columns_landscape = int(config.get("columns_landscape", 3))
        self.panel_spacing_scale = float(config.get("panel_spacing_scale", 0.028))
        self.poll_interval_sec = float(config.get("poll_interval_sec", 15.0))
        self.ping_timeout_sec = float(config.get("ping_timeout_sec", 1.5))
        self.scanline_alpha = int(config.get("scanline_alpha", 10))
        self.noise_alpha = int(config.get("noise_alpha", 8))
        self.vignette_strength = float(config.get("vignette_strength", 0.25))
        self.seed = config.get("seed")

        device_rows = config.get("devices", [])
        self.devices = [self._parse_device(row) for row in device_rows]

        self.manager = None
        self.w = 0
        self.h = 0
        self._is_portrait = False
        self._t = 0.0
        self._rng = random.Random()

        self._bg = (0, 0, 0)
        self._fg = (235, 235, 235)
        self._dim = (148, 148, 148)
        self._ok = (120, 255, 165)
        self._bad = (255, 115, 115)
        self._warn = (255, 210, 120)

        self._pad = 0
        self._header_h = 0
        self._footer_h = 0
        self._grid_rect = pygame.Rect(0, 0, 0, 0)

        self._font_header = None
        self._font_small = None
        self._font_body = None
        self._font_mono = None

        self._overlay = None
        self._vignette = None

        self._state_lock = threading.Lock()
        self._states: dict[str, DeviceState] = {
            d.hostname: DeviceState(hostname=d.hostname, name=d.name, role=d.role) for d in self.devices
        }
        self._last_sweep_epoch = 0.0
        self._last_sweep_duration = 0.0

        self._stop_event = threading.Event()
        self._refresh_event = threading.Event()
        self._worker_thread = None

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._recompute_layout()
        self._build_overlays()
        self._stop_event.clear()
        self._refresh_event.set()
        self._worker_thread = threading.Thread(target=self._poll_loop, name="network-status-wall", daemon=True)
        self._worker_thread.start()

    def exit(self):
        self._stop_event.set()
        self._refresh_event.set()
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=2.0)
        self._worker_thread = None
        self.manager = None
        self._overlay = None
        self._vignette = None

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
            self._refresh_event.set()

    def update(self, dt: float):
        self._t += dt
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()
            self._build_overlays()

    def render(self, screen: pygame.Surface):
        screen.fill(self._bg)
        self._draw_header(screen)
        self._draw_grid(screen)
        self._draw_footer(screen)

        if self._overlay is not None:
            screen.blit(self._overlay, (0, 0))
        if self._vignette is not None:
            screen.blit(self._vignette, (0, 0))
        if self.noise_alpha > 0:
            self._draw_noise(screen)

    def _parse_device(self, row: dict) -> DeviceSpec:
        hostname = str(row.get("hostname", "")).strip()
        if not hostname:
            hostname = "unknown.local"
        name = str(row.get("name") or row.get("friendly_name") or hostname).strip()
        role = str(row.get("role", "")).strip()
        return DeviceSpec(hostname=hostname, name=name, role=role)

    def _reseed(self):
        if self.seed is None:
            self.seed = random.randrange(1, 2**31 - 1)
        self._rng.seed(int(self.seed))

    def _recompute_layout(self):
        self.w, self.h = self.manager.screen.get_size()
        self._is_portrait = self.h > self.w

        self._pad = int(min(self.w, self.h) * 0.045)
        self._header_h = max(86, int(self.h * 0.15))
        self._footer_h = max(44, int(self.h * 0.07))
        self._grid_rect = pygame.Rect(
            self._pad,
            self._header_h,
            self.w - 2 * self._pad,
            self.h - self._header_h - self._footer_h,
        )

        base = min(self.w, self.h)
        self._font_header = self.manager.cache.get_font("dejavusansmono", max(18, int(base * 0.050)), bold=True)
        self._font_body = self.manager.cache.get_font("dejavusansmono", max(13, int(base * 0.026)), bold=False)
        self._font_small = self.manager.cache.get_font("dejavusansmono", max(11, int(base * 0.019)), bold=False)
        self._font_mono = self.manager.cache.get_font("dejavusansmono", max(11, int(base * 0.021)), bold=True)

    def _build_overlays(self):
        self._overlay = None
        self._vignette = None

    def _build_vignette(self, w: int, h: int, strength: float):
        strength = max(0.0, min(1.0, float(strength)))
        if strength <= 0.0:
            return None
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        layers = 68
        max_a = int(190 * strength)
        for i in range(layers):
            a = int(max_a * (i / layers) ** 1.8)
            pygame.draw.rect(surf, (0, 0, 0, a), pygame.Rect(i, i, w - 2 * i, h - 2 * i), 1)
        return surf

    def _poll_loop(self):
        while not self._stop_event.is_set():
            self._refresh_event.wait(timeout=max(1.0, self.poll_interval_sec))
            if self._stop_event.is_set():
                break
            self._refresh_event.clear()
            self._run_sweep()

    def _run_sweep(self):
        if not self.devices:
            return

        started = time.time()
        max_workers = max(1, min(8, len(self.devices)))
        updates = []
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(self._probe_device, device): device for device in self.devices}
            for future in as_completed(futures):
                device = futures[future]
                try:
                    updates.append(future.result())
                except Exception as exc:
                    updates.append(
                        {
                            "hostname": device.hostname,
                            "name": device.name,
                            "role": device.role,
                            "ip_address": "unresolved",
                            "reachable": False,
                            "latency_ms": None,
                            "checked_epoch": time.time(),
                            "error": f"probe error: {exc}",
                        }
                    )

        checked_epoch = time.time()
        with self._state_lock:
            for info in updates:
                existing = self._states.get(info["hostname"])
                if existing is None:
                    existing = DeviceState(
                        hostname=info["hostname"],
                        name=info["name"],
                        role=info["role"],
                    )
                    self._states[info["hostname"]] = existing

                previous = existing.reachable
                now_reachable = bool(info["reachable"])

                existing.name = info["name"]
                existing.role = info["role"]
                existing.ip_address = info["ip_address"]
                existing.reachable = now_reachable
                existing.latency_ms = info["latency_ms"]
                existing.last_checked_epoch = info["checked_epoch"]
                existing.last_error = info["error"]

                if now_reachable:
                    existing.up_count += 1
                else:
                    existing.down_count += 1

                if existing.up_count + existing.down_count == 1:
                    existing.current_streak = 1
                    existing.current_streak_up = now_reachable
                    existing.last_change_epoch = info["checked_epoch"]
                elif previous == now_reachable:
                    existing.current_streak += 1
                else:
                    existing.current_streak = 1
                    existing.current_streak_up = now_reachable
                    existing.last_change_epoch = info["checked_epoch"]

            self._last_sweep_epoch = checked_epoch
            self._last_sweep_duration = checked_epoch - started

    def _probe_device(self, device: DeviceSpec) -> dict:
        checked_epoch = time.time()
        ip_address = "unresolved"
        resolve_error = ""

        try:
            infos = socket.getaddrinfo(device.hostname, None, proto=socket.IPPROTO_TCP)
            ips = []
            for info in infos:
                addr = info[4][0]
                if addr not in ips:
                    ips.append(addr)
            if ips:
                ip_address = ips[0]
        except Exception as exc:
            resolve_error = f"dns {exc}"

        reachable, latency_ms, ping_error = self._ping_host(device.hostname)
        error_parts = [part for part in (resolve_error, ping_error) if part]
        return {
            "hostname": device.hostname,
            "name": device.name,
            "role": device.role,
            "ip_address": ip_address,
            "reachable": reachable,
            "latency_ms": latency_ms,
            "checked_epoch": checked_epoch,
            "error": "; ".join(error_parts) if error_parts else "ok",
        }

    def _ping_host(self, hostname: str) -> tuple[bool, float | None, str]:
        system = platform.system().lower()
        timeout_ms = max(250, int(self.ping_timeout_sec * 1000))

        if system.startswith("win"):
            cmd = ["ping", "-n", "1", "-w", str(timeout_ms), hostname]
        else:
            timeout_sec = max(1, int(math.ceil(self.ping_timeout_sec)))
            cmd = ["ping", "-c", "1", "-W", str(timeout_sec), hostname]

        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=max(1.0, self.ping_timeout_sec + 1.0),
                check=False,
            )
        except FileNotFoundError:
            return False, None, "ping unavailable"
        except subprocess.TimeoutExpired:
            return False, None, "ping timeout"
        except Exception as exc:
            return False, None, f"ping error: {exc}"

        output = f"{completed.stdout}\n{completed.stderr}"
        latency_ms = self._parse_latency_ms(output)
        if completed.returncode == 0:
            return True, latency_ms, ""
        return False, latency_ms, "no reply"

    def _parse_latency_ms(self, output: str) -> float | None:
        match = LATENCY_RE.search(output)
        if match:
            return float(match.group(1))
        match = WINDOWS_AVG_RE.search(output)
        if match:
            return float(match.group(1))
        return None

    def _draw_header(self, screen: pygame.Surface):
        band = pygame.Surface((self.w, self._header_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, 0))

        title = self._font_header.render(self.title, True, self.accent_rgb)
        screen.blit(title, (self._pad, int(self._header_h * 0.18)))

        up_count, down_count = self._status_counts()
        subtitle = self._font_small.render(
            f"{self.subtitle}   |   ONLINE {up_count}   OFFLINE {down_count}   HOSTS {len(self.devices)}",
            True,
            self._dim,
        )
        screen.blit(subtitle, (self._pad, int(self._header_h * 0.18) + title.get_height() + 6))

        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        age = max(0.0, time.time() - self._last_sweep_epoch) if self._last_sweep_epoch else -1.0
        right_text = f"UTC {ts}   |   sweep {self._last_sweep_duration:0.1f}s"
        if age >= 0.0:
            right_text += f"   |   age {age:0.0f}s"
        right = self._font_small.render(right_text, True, self._dim)
        screen.blit(right, (self.w - self._pad - right.get_width(), int(self._header_h * 0.18)))

        pygame.draw.line(screen, self._dim, (self._pad, self._header_h - 2), (self.w - self._pad, self._header_h - 2), 2)

    def _draw_footer(self, screen: pygame.Surface):
        y0 = self.h - self._footer_h
        band = pygame.Surface((self.w, self._footer_h), pygame.SRCALPHA)
        band.fill((0, 0, 0, 215))
        screen.blit(band, (0, y0))

        hint = "R: refresh now   |   green = reachable   |   red = unreachable"
        surf = self._font_small.render(hint, True, self._dim)
        screen.blit(surf, (self._pad, y0 + (self._footer_h - surf.get_height()) // 2))

    def _status_counts(self) -> tuple[int, int]:
        with self._state_lock:
            states = list(self._states.values())
        up_count = sum(1 for state in states if state.reachable)
        down_count = max(0, len(states) - up_count)
        return up_count, down_count

    def _draw_grid(self, screen: pygame.Surface):
        if not self.devices:
            msg = self._font_body.render("No devices configured.", True, self._warn)
            screen.blit(msg, (self._grid_rect.left + 20, self._grid_rect.top + 20))
            return

        cols = self.columns_portrait if self._is_portrait else self.columns_landscape
        cols = max(1, int(cols))
        rows = max(1, math.ceil(len(self.devices) / cols))
        gap = max(8, int(min(self.w, self.h) * self.panel_spacing_scale))
        cell_w = (self._grid_rect.width - (cols - 1) * gap) // cols
        cell_h = (self._grid_rect.height - (rows - 1) * gap) // rows

        with self._state_lock:
            cards = [self._states.get(device.hostname) for device in self.devices]

        idx = 0
        for row in range(rows):
            for col in range(cols):
                if idx >= len(cards):
                    return
                x = self._grid_rect.left + col * (cell_w + gap)
                y = self._grid_rect.top + row * (cell_h + gap)
                self._draw_device_card(screen, pygame.Rect(x, y, cell_w, cell_h), cards[idx])
                idx += 1

    def _draw_device_card(self, screen: pygame.Surface, rect: pygame.Rect, state: DeviceState | None):
        panel = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 210))
        screen.blit(panel, rect.topleft)
        pygame.draw.rect(screen, (*self.accent_rgb, 130), rect, 2)

        if state is None:
            return

        chip_color = self._ok if state.reachable else self._bad
        pulse = 0.70 + 0.30 * math.sin(self._t * 2.6 + rect.x * 0.01 + rect.y * 0.01)
        glow = tuple(min(255, int(c * (0.82 + 0.30 * pulse))) for c in chip_color)

        dot_x = rect.left + 18
        dot_y = rect.top + 18
        pygame.draw.circle(screen, glow, (dot_x, dot_y), 8)
        pygame.draw.circle(screen, (*glow, 100), (dot_x, dot_y), 14, 1)

        status_label = "ONLINE" if state.reachable else "OFFLINE"
        status = self._font_small.render(status_label, True, chip_color)
        screen.blit(status, (dot_x + 14, rect.top + 9))

        friendly = self._font_body.render(state.name, True, self._fg)
        screen.blit(friendly, (rect.left + 16, rect.top + 36))

        host = self._font_small.render(state.hostname, True, self.accent_rgb)
        screen.blit(host, (rect.left + 16, rect.top + 36 + friendly.get_height() + 2))

        y = rect.top + 36 + friendly.get_height() + host.get_height() + 14
        line_gap = self._font_small.get_linesize() + 4
        self._draw_kv(screen, rect.left + 16, y, "IP", state.ip_address, self._fg)
        self._draw_kv(
            screen,
            rect.left + 16,
            y + line_gap,
            "LAT",
            f"{state.latency_ms:0.0f} ms" if state.latency_ms is not None else "--",
            chip_color if state.reachable else self._warn,
        )
        self._draw_kv(
            screen,
            rect.left + 16,
            y + line_gap * 2,
            "ROLE",
            state.role or "--",
            self._fg,
        )

        total = state.up_count + state.down_count
        availability = (100.0 * state.up_count / total) if total else 0.0
        since_change = max(0.0, time.time() - state.last_change_epoch) if state.last_change_epoch else 0.0
        self._draw_kv(
            screen,
            rect.left + 16,
            y + line_gap * 3,
            "AVAIL",
            f"{availability:5.1f}%",
            self._ok if availability >= 80.0 else self._warn if availability >= 50.0 else self._bad,
        )
        streak_label = "UP" if state.current_streak_up else "DOWN"
        self._draw_kv(
            screen,
            rect.left + 16,
            y + line_gap * 4,
            "STREAK",
            f"{streak_label} x{state.current_streak}",
            chip_color,
        )

        checked_text = self._format_age(state.last_checked_epoch)
        change_text = self._format_duration(since_change)
        footer_left = self._font_small.render(f"checked {checked_text}", True, self._dim)
        screen.blit(footer_left, (rect.left + 16, rect.bottom - footer_left.get_height() - 12))

        footer_right = self._font_small.render(f"state {change_text}", True, self._dim)
        screen.blit(footer_right, (rect.right - 16 - footer_right.get_width(), rect.bottom - footer_right.get_height() - 12))

    def _draw_kv(self, screen: pygame.Surface, x: int, y: int, key: str, value: str, value_color):
        key_surf = self._font_small.render(f"{key:>5s}", True, self._dim)
        val_surf = self._font_mono.render(value, True, value_color)
        screen.blit(key_surf, (x, y))
        screen.blit(val_surf, (x + 68, y - 1))

    def _format_age(self, epoch: float) -> str:
        if not epoch:
            return "--"
        delta = max(0.0, time.time() - epoch)
        return self._format_duration(delta)

    def _format_duration(self, seconds: float) -> str:
        seconds = int(max(0.0, seconds))
        if seconds < 60:
            return f"{seconds}s"
        minutes, sec = divmod(seconds, 60)
        if minutes < 60:
            return f"{minutes}m{sec:02d}s"
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h{minutes:02d}m"

    def _draw_noise(self, screen: pygame.Surface):
        count = max(120, (self.w * self.h) // 10000)
        surf = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        for _ in range(count):
            x = self._rng.randrange(0, self.w)
            y = self._rng.randrange(0, self.h)
            a = self._rng.randrange(0, self.noise_alpha + 1)
            surf.set_at((x, y), (255, 255, 255, a))
        screen.blit(surf, (0, 0))

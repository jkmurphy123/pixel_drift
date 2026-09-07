# hacker_bbs_feed_mode.py
import pygame
import random
import time
import textwrap

class HackerBBSFeedMode:
    """
    Simulates a vintage 1980s hacker bulletin board system (BBS) feed.
    Displays scrolling messages, logins, posts, and ASCII art.
    """

    def __init__(self, config: dict):
        self.title = config.get("title", "ACCESSING BBS NODE // 1987")
        self.accent_rgb = tuple(config.get("accent_rgb", [80, 255, 120]))
        self.refresh_hz = float(config.get("refresh_hz", 60))
        self.typing_cps = int(config.get("typing_cps", 40))
        self.message_interval_sec = float(config.get("message_interval_sec", 1.5))
        self.max_messages = int(config.get("max_messages", 18))
        self.max_lines = config.get("max_lines", None)
        self.max_chars_per_line = int(config.get("max_chars_per_line", 60))
        self.font_size = config.get("font_size", None)
        self.seed = int(config.get("seed", int(time.time())))

        random.seed(self.seed)
        self._last_update = 0
        self._refresh_period = 1.0 / self.refresh_hz
        self._last_message_time = 0
        self._messages = []
        self._typing_buffer = ""
        self._font = None
        self._line_height = 0
        self._typing_speed = 1.0 / max(1, self.typing_cps)
        self._last_char_time = 0
        self._current_msg = ""

    # ---------------- Lifecycle ----------------

    def enter(self, manager):
        self.manager = manager
        self.w, self.h = self.manager.screen.get_size()
        font_px = int(self.font_size) if self.font_size is not None else int(self.h * 0.035)
        self._font = self.manager.cache.get_font("dejavusansmono", max(10, font_px))
        self._line_height = self._font.get_linesize() + 4
        self._append_banner()
        self._append_system_message("*** CONNECTED TO MATRIXNET BBS // NODE 42 ***")

    def exit(self):
        self._messages.clear()

    def update(self, dt):
        now = time.time()
        if (now - self._last_update) >= self._refresh_period:
            if now - self._last_message_time > self.message_interval_sec:
                self._start_new_message()
                self._last_message_time = now
            self._update_typing()
            self._last_update = now

    def render(self, screen):
        screen.fill((0, 0, 0))
        w, h = self.w, self.h
        y = h * 0.1

        # Header title
        title_surf = self._font.render(self.title, True, self.accent_rgb)
        screen.blit(title_surf, (w * 0.05, h * 0.03))
        pygame.draw.line(screen, self.accent_rgb, (w * 0.05, h * 0.08), (w * 0.95, h * 0.08), 2)

        # Messages
        auto_lines = int((h * 0.85) / self._line_height)
        max_visible = int(self.max_lines) if self.max_lines is not None else auto_lines
        max_visible = max(1, max_visible)
        visible = self._messages[-max_visible:]
        for line in visible:
            surf = self._font.render(line, True, self.accent_rgb)
            screen.blit(surf, (w * 0.05, y))
            y += self._line_height

        # Typing buffer (partial message)
        if self._typing_buffer:
            typed_lines = textwrap.wrap(self._typing_buffer, width=self.max_chars_per_line) or [""]
            typed_lines[-1] = typed_lines[-1] + "_"

            remaining_rows = max_visible - len(visible)
            if remaining_rows <= 0:
                typed_lines = typed_lines[-1:]
            else:
                typed_lines = typed_lines[:remaining_rows]

            for line in typed_lines:
                surf = self._font.render(line, True, self.accent_rgb)
                screen.blit(surf, (w * 0.05, y))
                y += self._line_height

    # ---------------- Internals ----------------

    def _append_message(self, text: str):
        wrapped = textwrap.wrap(text, width=self.max_chars_per_line)
        for wline in wrapped:
            self._messages.append(wline)
        if len(self._messages) > self.max_messages * 3:
            self._messages = self._messages[-self.max_messages * 3 :]

    def _append_banner(self):
        banner = [
            "┌────────────────────────────────────────────┐",
            "│      MATRIXNET BBS  v3.1.7 (C) 1987        │",
            "│      'Where Hackers Meet the Machine'      │",
            "└────────────────────────────────────────────┘",
        ]
        self._messages.extend(banner)

    def _append_system_message(self, text):
        self._messages.append(f"[SYS] {text}")

    def _start_new_message(self):
        msg = random.choice([
            f"{self._random_user()} logged in from {self._random_city()}",
            f"{self._random_user()}: anyone got the new warez list?",
            f"{self._random_user()} uploading {self._random_file()}...",
            f"{self._random_user()} >> decrypting sector dump...",
            f"{self._random_user()} disconnected.",
            f"{self._random_user()} joined #phreakers",
            f"{self._random_user()}: {self._random_quote()}",
        ])
        self._current_msg = msg
        self._typing_buffer = ""
        self._last_char_time = time.time()

    def _update_typing(self):
        if not self._current_msg:
            return
        now = time.time()
        if now - self._last_char_time > self._typing_speed:
            next_index = len(self._typing_buffer)
            if next_index < len(self._current_msg):
                self._typing_buffer += self._current_msg[next_index]
                self._last_char_time = now
            else:
                self._append_message(self._typing_buffer)
                self._typing_buffer = ""
                self._current_msg = ""

    # ---------------- Randomized Content ----------------

    def _random_user(self):
        handles = ["NEONKID", "BITRAT", "CYBERFOX", "L33T_OPS", "SYS404", "NINJACODE", "ZEROCOOL", "TRONIX"]
        return random.choice(handles)

    def _random_city(self):
        return random.choice(["NYC", "TOKYO", "BERLIN", "OSLO", "HELSINKI", "AUSTIN", "TORONTO"])

    def _random_file(self):
        return random.choice(["HACKTOOL.EXE", "DATA_DUMP.ZIP", "COREMEM.DAT", "ANONOPS.BIN", "SYSCRACK.COM"])

    def _random_quote(self):
        quotes = [
            "the system is only as secure as its weakest human",
            "hack the planet!",
            "root access achieved...",
            "disconnect before trace completes",
            "information wants to be free",
        ]
        return random.choice(quotes)

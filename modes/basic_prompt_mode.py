import random
from datetime import datetime

import pygame


class BasicPromptMode:
    """
    BASIC Prompt
    - Simulates typing a small line-numbered BASIC program
    - Alternates between editing, LIST, RUN, and output phases
    - Portrait-friendly terminal layout without CRT distortion

    Config (optional):
      - title
      - machine_name
      - prompt
      - palette
      - typing_cps
      - cursor_blink_hz
      - lines_on_screen
      - max_chars_per_line
      - seed
    """

    def __init__(self, config: dict):
        self.title = str(config.get("title", "BASIC PROMPT"))
        self.machine_name = str(config.get("machine_name", "MICRO-COMPUTER BASIC V2"))
        self.prompt = str(config.get("prompt", "READY."))
        self.palette = str(config.get("palette", "amber")).lower()
        self.typing_cps = float(config.get("typing_cps", 30.0))
        self.cursor_blink_hz = float(config.get("cursor_blink_hz", 2.0))
        self.lines_on_screen_cfg = config.get("lines_on_screen", None)
        self.max_chars_per_line_cfg = config.get("max_chars_per_line", None)
        self.seed = config.get("seed", None)

        self.manager = None
        self.w = 0
        self.h = 0

        self._bg = (0, 0, 0)
        self._fg = (255, 220, 150)
        self._dim = (170, 130, 90)
        self._accent = (255, 192, 96)

        self._pad = 0
        self._header_h = 0
        self._footer_h = 0
        self._term_rect = pygame.Rect(0, 0, 0, 0)

        self._font_size = 18
        self._font = None
        self._font_bold = None
        self._char_w = 10
        self._line_h = 18
        self._max_cols = 60
        self._max_lines = 26

        self._rng = random.Random()
        self._t = 0.0
        self._scrollback = []
        self._current_line = ""
        self._typing_queue = ""
        self._typing_progress = 0.0
        self._script_blocks = []
        self._script_i = 0

        self._cursor_on = True
        self._cursor_period = 0.5
        self._cursor_t = 0.0

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._set_palette()
        self._recompute_layout()
        self._build_script()
        self._scrollback = []
        self._current_line = ""
        self._typing_queue = ""
        self._typing_progress = 0.0
        self._script_i = 0
        self._cursor_t = 0.0
        self._cursor_period = 1.0 / max(0.1, self.cursor_blink_hz)
        self._enqueue_next_block()

    def exit(self):
        self.manager = None
        self._scrollback = []
        self._typing_queue = ""

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self._enqueue_next_block()

    def update(self, dt: float):
        self._t += dt
        self._cursor_t += dt
        if self._cursor_t >= self._cursor_period:
            self._cursor_t = 0.0
            self._cursor_on = not self._cursor_on

        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()

        if self._typing_queue:
            self._typing_progress += self.typing_cps * dt
            n = int(self._typing_progress)
            if n > 0:
                self._typing_progress -= n
                chunk = self._typing_queue[:n]
                self._typing_queue = self._typing_queue[n:]
                self._consume_text(chunk)
        else:
            if self._rng.random() < 0.018:
                self._enqueue_next_block()

    def render(self, screen: pygame.Surface):
        screen.fill(self._bg)
        self._draw_header(screen)
        self._draw_terminal(screen)
        self._draw_footer(screen)

    def _reseed(self):
        if self.seed is None:
            self.seed = random.randrange(1, 2**31 - 1)
        self._rng.seed(int(self.seed))

    def _set_palette(self):
        if self.palette == "green":
            self._fg = (170, 255, 170)
            self._dim = (110, 170, 110)
            self._accent = (120, 255, 160)
        elif self.palette == "white":
            self._fg = (235, 235, 235)
            self._dim = (150, 150, 150)
            self._accent = (255, 255, 255)
        else:
            self._fg = (255, 220, 150)
            self._dim = (170, 130, 90)
            self._accent = (255, 192, 96)

    def _recompute_layout(self):
        self.w, self.h = self.manager.screen.get_size()
        self._pad = int(min(self.w, self.h) * 0.045)
        self._header_h = max(58, int(self.h * 0.11))
        self._footer_h = max(34, int(self.h * 0.06))
        self._term_rect = pygame.Rect(
            self._pad,
            self._header_h,
            self.w - 2 * self._pad,
            self.h - self._header_h - self._footer_h,
        )

        self._font_size = max(16, int(min(self.w, self.h) * 0.030))
        self._font = self.manager.cache.get_font("dejavusansmono", self._font_size, bold=False)
        self._font_bold = self.manager.cache.get_font("dejavusansmono", int(self._font_size * 1.06), bold=True)
        test = self._font.render("M", True, self._fg)
        self._char_w = max(6, test.get_width())
        self._line_h = max(12, self._font.get_linesize() + 2)

        auto_cols = max(28, self._term_rect.width // self._char_w)
        self._max_cols = int(self.max_chars_per_line_cfg) if self.max_chars_per_line_cfg else auto_cols
        auto_lines = max(8, self._term_rect.height // self._line_h)
        self._max_lines = int(self.lines_on_screen_cfg) if self.lines_on_screen_cfg else auto_lines

    def _build_script(self):
        banner = f"{self.machine_name}\n38911 BYTES FREE\n\n{self.prompt}\n"
        program_variants = [
            [
                "10 REM STARFIELD DEMO\n",
                "20 FOR I=1 TO 12\n",
                "30 PRINT TAB(I);\"*\"\n",
                "40 NEXT I\n",
                "50 PRINT\n",
                "60 GOTO 20\n",
            ],
            [
                "10 REM TIMES TABLE\n",
                "20 FOR A=1 TO 5\n",
                "30 FOR B=1 TO 5\n",
                "40 PRINT A;\"X\";B;\"=\";A*B\n",
                "50 NEXT B\n",
                "60 PRINT\n",
                "70 NEXT A\n",
            ],
            [
                "10 REM COUNTDOWN\n",
                "20 FOR N=10 TO 1 STEP -1\n",
                "30 PRINT \"T-\";N\n",
                "40 NEXT N\n",
                "50 PRINT \"LIFTOFF!\"\n",
            ],
        ]
        program = self._rng.choice(program_variants)

        blocks = [banner]
        for line in program:
            blocks.append(line)

        blocks.extend(
            [
                "LIST\n",
                "".join(program),
                f"{self.prompt}\n",
                "RUN\n",
                self._make_output_for_program(program),
                f"{self.prompt}\n",
                "PRINT PEEK(197)\n0\n",
                f"{self.prompt}\n",
                "RUN\n?SYNTAX ERROR IN 40\n",
                f"{self.prompt}\n",
                "40 PRINT A;\" X \";B;\" = \";A*B\n" if "TIMES TABLE" in program[0] else "40 NEXT I\n",
                "RUN\n",
                self._make_output_for_program(program, corrected=True),
                f"{self.prompt}\nNEW\n{self.prompt}\n",
            ]
        )
        self._script_blocks = blocks

    def _make_output_for_program(self, program, corrected: bool = False):
        header = program[0]
        if "STARFIELD" in header:
            lines = []
            for loop in range(3):
                for i in range(1, 13):
                    lines.append(" " * i + "*")
                lines.append("")
            return "\n".join(lines) + "\n"
        if "TIMES TABLE" in header:
            lines = []
            for a in range(1, 6):
                for b in range(1, 6):
                    lines.append(f"{a} X {b} = {a*b}")
                lines.append("")
            return "\n".join(lines) + "\n"
        lines = [f"T-{n}" for n in range(10, 0, -1)]
        lines.append("LIFTOFF!")
        if corrected:
            lines.append("OK")
        return "\n".join(lines) + "\n"

    def _enqueue_next_block(self):
        if not self._script_blocks:
            return
        if self._script_i >= len(self._script_blocks):
            self._build_script()
            self._script_i = 0
        self._typing_queue += self._script_blocks[self._script_i]
        self._script_i += 1

    def _consume_text(self, chunk: str):
        for ch in chunk:
            if ch == "\n":
                self._commit_current_line()
            else:
                self._current_line += ch
                if len(self._current_line) >= self._max_cols:
                    self._commit_current_line()

    def _commit_current_line(self):
        self._scrollback.append(self._current_line)
        if len(self._scrollback) > self._max_lines * 3:
            self._scrollback = self._scrollback[-self._max_lines * 3:]
        self._current_line = ""

    def _draw_header(self, screen):
        title = self._font_bold.render(self.title, True, self._accent)
        machine = self._font.render(self.machine_name, True, self._fg)
        screen.blit(title, (self._pad, int(self._header_h * 0.18)))
        screen.blit(machine, (self._pad, int(self._header_h * 0.58)))

        stamp = self._font.render(datetime.now().strftime("%H:%M:%S"), True, self._dim)
        screen.blit(stamp, (self.w - self._pad - stamp.get_width(), int(self._header_h * 0.34)))

    def _draw_terminal(self, screen):
        pygame.draw.rect(screen, (8, 8, 8), self._term_rect)
        pygame.draw.rect(screen, self._dim, self._term_rect, 1)

        lines = self._scrollback[-(self._max_lines - 1):] if self._max_lines > 1 else []
        if self._current_line or not lines:
            lines = lines + [self._current_line]
        lines = lines[-self._max_lines:]

        x = self._term_rect.left + 12
        y = self._term_rect.top + 12
        for idx, line in enumerate(lines):
            color = self._fg
            if "ERROR" in line:
                color = (255, 120, 120)
            elif line.startswith("READY") or line.endswith("FREE"):
                color = self._accent
            surf = self._font.render(line, True, color)
            screen.blit(surf, (x, y + idx * self._line_h))

        if self._cursor_on:
            cursor_line = lines[-1] if lines else ""
            cx = x + self._font.size(cursor_line)[0]
            cy = y + (len(lines) - 1) * self._line_h
            pygame.draw.rect(screen, self._fg, pygame.Rect(cx + 2, cy + 2, max(8, self._char_w - 2), self._line_h - 4))

    def _draw_footer(self, screen):
        left = self._font.render("SPACE: SKIP AHEAD", True, self._dim)
        right = self._font.render(f"SEED {self.seed}", True, self._dim)
        y = self.h - self._footer_h + 8
        screen.blit(left, (self._pad, y))
        screen.blit(right, (self.w - self._pad - right.get_width(), y))

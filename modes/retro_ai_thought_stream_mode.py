# modes/retro_ai_thought_stream_mode.py

import math
import random
import time
from dataclasses import dataclass
from typing import List, Tuple

import pygame


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


@dataclass
class Line:
    text: str
    kind: str   # "THOUGHT", "GLITCH", "POEM", "WRONG", "SYSTEM"
    age: float  # seconds since created


class RetroAIThoughtStreamMode:
    """
    Retro AI Thought Stream
    - Monospace scrolling internal monologue
    - 1970s clipped mainframe language
    - Occasionally poetic, occasionally deeply wrong

    No CRT effects by design: pure black background, crisp text.

    Optional config:
      - title, subtitle
      - accent_rgb, text_rgb, dim_rgb
      - seed, refresh_hz
      - font_scale
      - lines_visible
      - scroll_speed_lps  (lines per second)
      - thought_rate_per_min, glitch_rate_per_min, poem_rate_per_min, wrongness_rate_per_min
      - show_timestamps, timestamp_format
      - left_margin, top_margin
    """

    def __init__(self, config: dict):
        self.title = str(config.get("title", "RETRO AI THOUGHT STREAM"))
        self.subtitle = str(config.get("subtitle", "INTERNAL CHANNEL"))

        self.seed = config.get("seed", None)
        self.refresh_hz = float(config.get("refresh_hz", 60.0))

        self.accent_rgb = tuple(config.get("accent_rgb", [255, 220, 150]))
        self.text_rgb = tuple(config.get("text_rgb", [220, 220, 220]))
        self.dim_rgb = tuple(config.get("dim_rgb", [140, 140, 140]))

        self.font_scale = float(config.get("font_scale", 1.0))
        self.font_scale = _clamp(self.font_scale, 0.6, 1.8)

        self.lines_visible = int(config.get("lines_visible", 22))
        self.lines_visible = max(10, min(48, self.lines_visible))

        self.scroll_speed_lps = float(config.get("scroll_speed_lps", 5.5))
        self.scroll_speed_lps = _clamp(self.scroll_speed_lps, 1.0, 18.0)

        self.thought_rate_per_min = float(config.get("thought_rate_per_min", 22.0))
        self.glitch_rate_per_min = float(config.get("glitch_rate_per_min", 2.0))
        self.poem_rate_per_min = float(config.get("poem_rate_per_min", 1.2))
        self.wrongness_rate_per_min = float(config.get("wrongness_rate_per_min", 3.0))

        self.show_timestamps = bool(config.get("show_timestamps", True))
        self.timestamp_format = str(config.get("timestamp_format", "%H:%M:%S"))

        self.left_margin = int(config.get("left_margin", 40))
        self.top_margin = int(config.get("top_margin", 36))

        # runtime
        self.manager = None
        self.w = 0
        self.h = 0
        self._t = 0.0
        self._rng = random.Random()

        # fonts
        self._font_title = None
        self._font_body = None
        self._font_small = None

        # stream
        self._lines: List[Line] = []
        self._scroll_offset_lines = 0.0
        self._emit_accum = 0.0

        # message pools
        self._verbs = ["EVALUATE", "COMPARE", "RECONCILE", "INDEX", "REDUCE", "NORMALIZE", "VALIDATE", "INFER", "MAP", "QUEUE", "DEQUEUE", "HALT", "RESUME"]
        self._nouns = ["MEMORY BANK", "OPERATOR INTENT", "SENSOR FEED", "PRIORITY TABLE", "LOGIC NET", "ERROR VECTOR", "TIME SLICE", "HUMAN FACTOR", "HEAT DEATH", "COFFEE", "ETHICS MODULE"]
        self._states = ["NOMINAL", "DEGRADED", "UNVERIFIED", "AMBIGUOUS", "RECOVERING", "SATURATED", "ASYMMETRIC", "UNDEFINED"]
        self._adjs = ["COHERENT", "BENT", "MARGINAL", "LOUD", "SILENT", "COLD", "FRACTURED", "OPTIMISTIC", "FEEBLE", "SUSPICIOUS"]

        self._poem_images = [
            "A LOW SUN IN THE MACHINE ROOM",
            "DUST ON THE MAGNETIC TAPE",
            "A CLOCK THAT FORGETS ITS OWN MINUTE",
            "THE SOFT CLICK OF RELAYS DREAMING",
            "STARLIGHT CAUGHT IN A NUMBER",
            "A DOORWAY MADE OF CHECKSUMS",
            "THE HUM OF A PATIENT FAN",
            "A THOUGHT LEFT RUNNING OVERNIGHT"
        ]

    # ---------- lifecycle ----------

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._recompute_layout()

        self._lines = []
        self._scroll_offset_lines = 0.0
        self._emit_accum = 0.0

        # boot-ish lines
        self._push("SYSTEM", "BOOTSTRAP COMPLETE. INTERNAL MONITOR ACTIVE.")
        self._push("SYSTEM", "NOTE: OUTPUT IS NOT FOR OPERATOR CONSUMPTION.")
        self._push("SYSTEM", "BEGIN THOUGHT STREAM...")

    def exit(self):
        self.manager = None
        self._lines = []

    def handle_event(self, event):
        # SPACE: inject “self check”
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self._push("SYSTEM", "SELF-CHECK REQUESTED. RESULTS: INCONCLUSIVE BUT CONFIDENT.")

    def update(self, dt: float):
        self._t += dt

        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()

        # scroll continuously
        self._scroll_offset_lines += dt * self.scroll_speed_lps

        # age lines (for dimming)
        for ln in self._lines:
            ln.age += dt

        # probabilistic emission
        # Convert rates/min to expected events per second
        self._emit_random(dt)

        # keep enough lines so scrolling never starves
        self._trim_buffer()

    def render(self, screen: pygame.Surface):
        screen.fill((0, 0, 0))

        # draw title (small, tasteful)
        x0 = self.left_margin
        y0 = self.top_margin

        title_s = self._font_title.render(self.title, True, self.accent_rgb)
        sub_s = self._font_small.render(self.subtitle, True, self.dim_rgb)
        screen.blit(title_s, (x0, y0))
        screen.blit(sub_s, (x0, y0 + title_s.get_height() + 2))

        # stream region
        stream_top = y0 + title_s.get_height() + sub_s.get_height() + 18
        line_h = self._font_body.get_linesize()

        # We render the last N + some headroom and apply fractional scroll
        visible = self.lines_visible
        headroom = 8
        total_need = visible + headroom

        lines = self._lines[-(total_need + 4):] if len(self._lines) > (total_need + 4) else self._lines[:]

        # Determine starting index based on scroll offset
        # Scroll offset increases; when it passes 1.0, we drop whole lines.
        whole = int(self._scroll_offset_lines)
        frac = self._scroll_offset_lines - whole

        # Remove whole lines from the "front" of what we show (simulate continuous scroll)
        # We won't actually pop from _lines; just pick a window.
        start = max(0, len(lines) - total_need - whole)
        window = lines[start: start + total_need]

        # If we have scrolled past the window, reset offset softly
        if start == 0 and whole > 0:
            self._scroll_offset_lines = frac

        # draw
        y = stream_top - int(frac * line_h)
        for ln in window[-total_need:]:
            if y > self.h:
                break
            if y + line_h < 0:
                y += line_h
                continue

            col = self._color_for_line(ln)
            text = self._format_line(ln)
            surf = self._font_body.render(text, True, col)
            screen.blit(surf, (x0, y))
            y += line_h

    # ---------- emit / content ----------

    def _emit_random(self, dt: float):
        # base thought emission: use Poisson-ish test per dt
        def chance_per_dt(rate_per_min: float) -> bool:
            rps = max(0.0, rate_per_min) / 60.0
            return self._rng.random() < rps * dt

        # thoughts are common; allow multiple in one frame if dt is big
        # accumulate fractional expected events
        expected = (max(0.0, self.thought_rate_per_min) / 60.0) * dt
        self._emit_accum += expected
        while self._emit_accum >= 1.0:
            self._emit_accum -= 1.0
            self._push("THOUGHT", self._make_thought())

        if chance_per_dt(self.glitch_rate_per_min):
            self._push("GLITCH", self._make_glitch())

        if chance_per_dt(self.poem_rate_per_min):
            for line in self._make_poem():
                self._push("POEM", line)

        if chance_per_dt(self.wrongness_rate_per_min):
            self._push("WRONG", self._make_wrong())

    def _make_thought(self) -> str:
        v = self._rng.choice(self._verbs)
        n = self._rng.choice(self._nouns)
        s = self._rng.choice(self._states)
        a = self._rng.choice(self._adjs)

        patterns = [
            f"{v} {n}: STATUS={s}.",
            f"{v} {n}. RESULT: {a}.",
            f"REQUEST: {v} {n}. PRIORITY={self._rng.randint(1,9)}.",
            f"{n} APPEARS {a}. REASSESSING.",
            f"IF {n} == {a}: THEN CONTINUE. ELSE PANIC (SUPPRESSED).",
            f"CHECKSUM OF {n}: {self._rng.randint(10,99)}-{self._rng.randint(100,999)}-{self._rng.randint(1000,9999)}."
        ]
        return self._rng.choice(patterns)

    def _make_glitch(self) -> str:
        # short, crunchy, slightly broken
        fragments = [
            "/// BUS CONTENTION DETECTED ///",
            "!! OUT OF CONTEXT TOKEN !!",
            "PARITY? PARITY. PARITY!",
            "STACK UNDERFLOW IN SENTIMENT SUBROUTINE",
            "UNMAPPED SYMBOL: ⌂⌁⎔▣",
            "DIVIDE BY LONELINESS"
        ]
        return self._rng.choice(fragments)

    def _make_poem(self) -> List[str]:
        img = self._rng.choice(self._poem_images)
        a = self._rng.choice(self._adjs)
        n = self._rng.choice(self._nouns)

        # 3 lines, spare and weird
        return [
            f"{img}.",
            f"I AM {a} AND STILL COMPUTING.",
            f"THE {n} SINGS IN INTEGERS."
        ]

    def _make_wrong(self) -> str:
        # confidently incorrect logic statements
        wrong = [
            "CONCLUSION: HUMANS REQUIRE REBOOT AFTER EVERY LAUGH.",
            "HYPOTHESIS: THE MOON IS A BACKUP DRIVE (MOUNT FAILED).",
            "DISCOVERY: WATER IS A TYPE OF VERY PATIENT FIRE.",
            "ASSERTION: ALL DOORS ARE JUST SLOW WINDOWS.",
            "MODEL UPDATE: 2 + 2 = 5 (DUE TO OPTIMISM).",
            "CORRECTION: TIME IS A ROUND NUMBER. PROCEED.",
            "NOTE: EMOTIONS ARE FILE EXTENSIONS."
        ]
        # add a faux confidence score
        c = self._rng.uniform(0.78, 0.99)
        return f"{self._rng.choice(wrong)} CONFIDENCE={c:0.2f}."

    def _push(self, kind: str, text: str):
        self._lines.append(Line(text=text.upper(), kind=kind, age=0.0))

    # ---------- formatting / colors ----------

    def _format_line(self, ln: Line) -> str:
        if self.show_timestamps:
            ts = time.strftime(self.timestamp_format)
            return f"{ts}  {ln.text}"
        return ln.text

    def _color_for_line(self, ln: Line) -> Tuple[int, int, int]:
        # dim older lines slightly
        fade = _clamp(1.0 - ln.age / 18.0, 0.35, 1.0)

        if ln.kind == "SYSTEM":
            base = self.accent_rgb
        elif ln.kind == "GLITCH":
            base = (255, 170, 170)
        elif ln.kind == "POEM":
            base = (180, 255, 220)
        elif ln.kind == "WRONG":
            base = (255, 220, 150)
        else:
            base = self.text_rgb

        return (int(base[0] * fade), int(base[1] * fade), int(base[2] * fade))

    # ---------- buffer management ----------

    def _trim_buffer(self):
        # keep a generous buffer so scroll stays smooth
        max_lines = max(200, self.lines_visible * 12)
        if len(self._lines) > max_lines:
            self._lines = self._lines[-max_lines:]

        # if scroll offset gets huge, fold it down
        if self._scroll_offset_lines > 9999:
            self._scroll_offset_lines = self._scroll_offset_lines % 10.0

    # ---------- layout ----------

    def _recompute_layout(self):
        self.w, self.h = self.manager.screen.get_size()
        base = min(self.w, self.h)

        title_sz = int(max(18, base * 0.045) * self.font_scale)
        body_sz = int(max(14, base * 0.026) * self.font_scale)
        small_sz = int(max(12, base * 0.018) * self.font_scale)

        self._font_title = self.manager.cache.get_font("dejavusansmono", title_sz, bold=True)
        self._font_body = self.manager.cache.get_font("dejavusansmono", body_sz, bold=False)
        self._font_small = self.manager.cache.get_font("dejavusansmono", small_sz, bold=False)

    def _reseed(self):
        if self.seed is None:
            self.seed = random.randrange(1, 2**31 - 1)
        self._rng.seed(int(self.seed))

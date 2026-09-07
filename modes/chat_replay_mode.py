import json
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import pygame


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _hex_to_rgb(s: str, default=(200, 200, 200)) -> Tuple[int, int, int]:
    if not isinstance(s, str):
        return default
    s = s.strip()
    if s.startswith("#"):
        s = s[1:]
    if len(s) == 3:
        s = "".join([c * 2 for c in s])
    if len(s) != 6:
        return default
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except Exception:
        return default


def _soften(rgb: Tuple[int, int, int], amt: float) -> Tuple[int, int, int]:
    amt = _clamp(amt, 0.0, 1.0)
    r, g, b = rgb
    return (
        int(r + (255 - r) * amt),
        int(g + (255 - g) * amt),
        int(b + (255 - b) * amt),
    )


def _wrap_text(font: pygame.font.Font, text: str, max_w: int) -> List[str]:
    lines: List[str] = []
    for para in (text or "").split("\n"):
        words = para.split(" ")
        cur = ""
        for w in words:
            test = (cur + " " + w).strip()
            if not test:
                continue
            if font.size(test)[0] <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                    cur = w
                else:
                    # hard cut long token
                    chunk = w
                    while chunk:
                        lo, hi = 1, len(chunk)
                        best = 1
                        while lo <= hi:
                            mid = (lo + hi) // 2
                            if font.size(chunk[:mid])[0] <= max_w:
                                best = mid
                                lo = mid + 1
                            else:
                                hi = mid - 1
                        lines.append(chunk[:best])
                        chunk = chunk[best:]
                    cur = ""
        if cur:
            lines.append(cur)
        lines.append("")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


@dataclass
class Participant:
    name: str
    image_file_name: str
    bubble_rgb: Tuple[int, int, int]


@dataclass
class Turn:
    speaker: str
    text: str


@dataclass
class LoadedConversation:
    conversation_id: str
    premise: str
    participants: List[Participant]
    turns: List[Turn]
    source_path: str


class ChatReplayMode:
    """
    Chat replay screensaver mode.

    Required config:
      - conversations_folder: folder of conversation JSON files
      - thumbnails_folder: base folder containing character thumbnails

    Notes:
      - This mode ONLY uses participant info embedded in the conversation JSON.
      - No config.json, no fallback.
      - Each conversation file must include:
          participants: [{name, image_file_name, color}, ...]
          turns: [{speaker, text}, ...]
    """

    def __init__(self, config: dict):
        self.title = str(config.get("title", "CHAT REPLAY"))
        self.conversations_folder = str(config["conversations_folder"])
        self.thumbnails_folder = str(config["thumbnails_folder"])

        self.seed = config.get("seed", None)
        self.refresh_hz = float(config.get("refresh_hz", 60.0))

        self.font_scale = float(config.get("font_scale", 1.0))
        self.font_scale = _clamp(self.font_scale, 0.6, 1.6)

        self.header_height_frac = float(config.get("header_height_frac", 0.12))
        self.footer_height_frac = float(config.get("footer_height_frac", 0.06))
        self.chat_padding = int(config.get("chat_padding", 18))

        self.typing_cps = float(config.get("typing_cps", 45.0))
        self.min_pause_s = float(config.get("min_pause_s", 0.6))
        self.max_pause_s = float(config.get("max_pause_s", 1.8))
        self.typing_indicator_min_s = float(config.get("typing_indicator_min_s", 0.8))
        self.typing_indicator_max_s = float(config.get("typing_indicator_max_s", 2.6))
        self.end_pause_s = float(config.get("end_pause_s", 3.0))

        self.bubble_radius = int(config.get("bubble_radius", 18))
        self.bubble_max_width_frac = float(config.get("bubble_max_width_frac", 0.72))
        self.bubble_alpha = int(config.get("bubble_alpha", 210))
        self.bubble_outline_alpha = int(config.get("bubble_outline_alpha", 90))

        self.show_timestamp = bool(config.get("show_timestamp", True))
        self.timestamp_format = str(config.get("timestamp_format", "%H:%M"))

        self.bg_rgb = tuple(config.get("bg_rgb", [0, 0, 0]))
        self.panel_outline_alpha = int(config.get("panel_outline_alpha", 120))
        self.noise_alpha = int(config.get("noise_alpha", 8))

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
        self._font_tiny = None

        # layout
        self._pad = 0
        self._header_h = 0
        self._footer_h = 0
        self._chat_rect = pygame.Rect(0, 0, 0, 0)

        # file list + thumb cache
        self._conversation_files: List[str] = []
        self._thumb_cache: Dict[str, Optional[pygame.Surface]] = {}

        # active conversation playback state
        self._conv: Optional[LoadedConversation] = None
        self._turn_index = 0
        self._char_index = 0
        self._phase = "LOAD"  # LOAD -> TYPE_INDICATOR -> TYPING -> PAUSE -> DONE_WAIT
        self._phase_until = 0.0

        self._typing_speaker = ""
        self._typing_full_text = ""
        self._typing_visible_text = ""
        self._typing_indicator = ""

        self._messages: List[Dict[str, Any]] = []  # committed history

    # ---------- lifecycle ----------

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._recompute_layout()

        self._conversation_files = self._find_conversation_files(self.conversations_folder)
        self._thumb_cache = {}
        self._messages = []
        self._conv = None
        self._phase = "LOAD"
        self._phase_until = 0.0

    def exit(self):
        self.manager = None
        self._conversation_files = []
        self._thumb_cache = {}
        self._messages = []
        self._conv = None

    def handle_event(self, event):
        # SPACE: skip to next conversation
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self._phase = "LOAD"
            self._phase_until = 0.0
            self._messages = []
            self._conv = None

    def update(self, dt: float):
        self._t += dt

        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()

        if not self._conversation_files:
            return

        if self._phase == "LOAD":
            self._load_random_conversation()
            return

        if self._phase == "TYPE_INDICATOR":
            if self._t >= self._phase_until:
                self._phase = "TYPING"
            else:
                dots = int((self._t * 3.0) % 4)
                self._typing_indicator = f"{self._typing_speaker} is typing" + ("." * dots)
            return

        if self._phase == "TYPING":
            cps = max(8.0, self.typing_cps)
            self._char_index += int(cps * dt)
            self._char_index = min(self._char_index, len(self._typing_full_text))
            self._typing_visible_text = self._typing_full_text[: self._char_index]

            if self._char_index >= len(self._typing_full_text):
                self._commit_message(self._typing_speaker, self._typing_full_text)
                self._phase = "PAUSE"
                self._phase_until = self._t + self._rng.uniform(self.min_pause_s, self.max_pause_s)
            return

        if self._phase == "PAUSE":
            if self._t >= self._phase_until:
                self._advance_turn()
            return

        if self._phase == "DONE_WAIT":
            if self._t >= self._phase_until:
                self._phase = "LOAD"
                self._messages = []
                self._conv = None
            return

    def render(self, screen: pygame.Surface):
        screen.fill(self.bg_rgb)

        if not self._conversation_files:
            self._draw_center_message(screen, "No conversation files found.")
            return

        if self._conv is None and self._phase != "LOAD":
            self._draw_center_message(screen, "Loading conversation…")
            return

        self._draw_chat(screen)

        if self.noise_alpha > 0:
            self._draw_noise(screen)

    # ---------- loading ----------

    def _find_conversation_files(self, folder: str) -> List[str]:
        if not os.path.isdir(folder):
            print(f"[ChatReplayMode] conversations_folder does not exist: {folder}")
            return []
        files = [os.path.join(folder, fn) for fn in os.listdir(folder) if fn.lower().endswith(".json")]
        files.sort()
        print(f"[ChatReplayMode] found {len(files)} conversation file(s) in {folder}")
        return files

    def _load_random_conversation(self):
        path = self._rng.choice(self._conversation_files)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[ChatReplayMode] failed to load conversation: {path}: {e}")
            self._phase = "LOAD"
            return

        # participants are required in-file
        participants_data = data.get("participants", [])
        participants: List[Participant] = []
        for p in participants_data:
            name = str(p.get("name", "")).strip()
            img = str(p.get("image_file_name", "")).strip()
            col = str(p.get("color", "#CCCCCC")).strip()
            if not name or not img:
                continue
            participants.append(Participant(name=name, image_file_name=img, bubble_rgb=_hex_to_rgb(col)))

        if len(participants) < 2:
            print(f"[ChatReplayMode] conversation missing participants (need 2+): {path}")
            self._phase = "LOAD"
            return

        turns_data = data.get("turns", [])
        turns: List[Turn] = []
        for t in turns_data:
            sp = str(t.get("speaker", "")).strip()
            tx = str(t.get("text", "")).strip()
            if sp and tx:
                turns.append(Turn(speaker=sp, text=tx))

        if not turns:
            print(f"[ChatReplayMode] conversation has no turns: {path}")
            self._phase = "LOAD"
            return

        conv_id = str(data.get("conversation_id", os.path.basename(path)))
        premise = str(data.get("premise", "")).strip()

        self._conv = LoadedConversation(
            conversation_id=conv_id,
            premise=premise,
            participants=participants,
            turns=turns,
            source_path=path,
        )

        self._messages = []
        self._turn_index = 0
        self._thumb_cache = {}  # clear between convos so sizes update cleanly

        self._start_turn()

    # ---------- playback ----------

    def _start_turn(self):
        assert self._conv is not None
        if self._turn_index >= len(self._conv.turns):
            self._phase = "DONE_WAIT"
            self._phase_until = self._t + max(0.8, self.end_pause_s)
            return

        turn = self._conv.turns[self._turn_index]
        self._typing_speaker = turn.speaker
        self._typing_full_text = turn.text
        self._typing_visible_text = ""
        self._char_index = 0

        dur = self._rng.uniform(self.typing_indicator_min_s, self.typing_indicator_max_s)
        self._typing_indicator = f"{self._typing_speaker} is typing..."
        self._phase = "TYPE_INDICATOR"
        self._phase_until = self._t + dur

    def _advance_turn(self):
        self._turn_index += 1
        self._start_turn()

    def _commit_message(self, speaker: str, text: str):
        stamp = time.strftime(self.timestamp_format) if self.show_timestamp else ""
        self._messages.append({"speaker": speaker, "text": text, "stamp": stamp})

    # ---------- layout & drawing ----------

    def _recompute_layout(self):
        self.w, self.h = self.manager.screen.get_size()
        base = min(self.w, self.h)

        self._pad = int(base * 0.05)
        # No header / footer — full-screen chat
        self._header_h = 0
        self._footer_h = 0

        self._chat_rect = pygame.Rect(
            self._pad,
            self._pad,
            self.w - 2 * self._pad,
            self.h - 2 * self._pad,
        )

        title_sz = int(max(18, base * 0.050) * self.font_scale)
        body_sz = int(max(14, base * 0.028) * self.font_scale)
        small_sz = int(max(12, base * 0.020) * self.font_scale)
        tiny_sz = int(max(10, base * 0.017) * self.font_scale)

        self._font_title = self.manager.cache.get_font("dejavusansmono", title_sz, bold=True)
        self._font_body = self.manager.cache.get_font("dejavusansmono", body_sz, bold=False)
        self._font_small = self.manager.cache.get_font("dejavusansmono", small_sz, bold=False)
        self._font_tiny = self.manager.cache.get_font("dejavusansmono", tiny_sz, bold=False)

    def _draw_center_message(self, screen: pygame.Surface, msg: str):
        f = self.manager.cache.get_font("dejavusansmono", 28, bold=True)
        s = f.render(msg, True, (220, 220, 220))
        r = s.get_rect(center=screen.get_rect().center)
        screen.blit(s, r)

    def _participant_style(self, name: str) -> Participant:
        assert self._conv is not None
        for p in self._conv.participants:
            if p.name == name:
                return p
        # No fallback: if unknown speaker, still render with neutral style
        return Participant(name=name, image_file_name="", bubble_rgb=(200, 200, 200))

    def _thumb_for(self, participant: Participant, size: int) -> Optional[pygame.Surface]:
        # cache by name+size+image_file_name
        key = f"{participant.name}::{participant.image_file_name}::{size}"
        if key in self._thumb_cache:
            return self._thumb_cache[key]

        if not participant.image_file_name:
            self._thumb_cache[key] = None
            return None

        # If image_file_name includes folders, respect it under thumbnails_folder
        candidate = os.path.join(self.thumbnails_folder, participant.image_file_name)
        if not os.path.exists(candidate):
            # also try basename under thumbnails_folder (common layout)
            candidate = os.path.join(self.thumbnails_folder, os.path.basename(participant.image_file_name))
            if not os.path.exists(candidate):
                self._thumb_cache[key] = None
                return None

        try:
            img = self.manager.cache.get_image(candidate, convert_alpha=True)
            thumb = pygame.transform.smoothscale(img, (size, size))
            self._thumb_cache[key] = thumb
            return thumb
        except Exception:
            self._thumb_cache[key] = None
            return None

    def _draw_chat(self, screen: pygame.Surface):
        r = self._chat_rect
        pygame.draw.rect(screen, (0, 0, 0), r)
        pygame.draw.rect(screen, (220, 220, 220, self.panel_outline_alpha), r, 2)

        inner = r.inflate(-self.chat_padding, -self.chat_padding)
        bubble_max_w = int(inner.width * _clamp(self.bubble_max_width_frac, 0.45, 0.90))
        avatar_size = max(40, int(min(inner.width, inner.height) * 0.09))
        gap_y = 10

        # items = committed + current typing/indicator
        render_items: List[Dict[str, Any]] = list(self._messages)
        if self._phase in ("TYPE_INDICATOR", "TYPING") and self._conv is not None:
            if self._phase == "TYPE_INDICATOR":
                render_items.append({"speaker": self._typing_speaker, "text": "", "stamp": "", "indicator": self._typing_indicator})
            else:
                render_items.append({"speaker": self._typing_speaker, "text": self._typing_visible_text, "stamp": "", "indicator": None})

        # decide left/right based on participant order in file
        left_name = self._conv.participants[0].name if self._conv else ""
        right_name = self._conv.participants[1].name if (self._conv and len(self._conv.participants) > 1) else ""

        blocks = []
        for item in render_items:
            speaker = item.get("speaker", "")
            text = item.get("text", "")
            indicator = item.get("indicator", None)
            stamp = item.get("stamp", "")

            is_left = (speaker == left_name) if left_name else True
            if speaker == right_name:
                is_left = False

            pstyle = self._participant_style(speaker)
            bubble_rgb = pstyle.bubble_rgb
            outline_rgb = _soften(bubble_rgb, 0.25)

            lines = _wrap_text(self._font_body, text, bubble_max_w - 26) if text else []
            if indicator:
                lines = [indicator]

            line_h = self._font_body.get_linesize()
            text_h = max(1, len(lines)) * line_h
            stamp_h = self._font_tiny.get_linesize() if (stamp and self.show_timestamp and not indicator) else 0

            bubble_w = bubble_max_w
            if lines:
                longest = max(self._font_body.size(l)[0] for l in lines)
                bubble_w = min(bubble_max_w, max(160, longest + 26))

            bubble_h = text_h + 18 + (stamp_h + 6 if stamp_h else 0)
            row_h = max(bubble_h, avatar_size) + 6

            blocks.append({
                "speaker": speaker,
                "participant": pstyle,
                "is_left": is_left,
                "bubble_rgb": bubble_rgb,
                "outline_rgb": outline_rgb,
                "lines": lines,
                "stamp": stamp,
                "indicator": indicator,
                "bubble_size": (bubble_w, bubble_h),
                "avatar_size": avatar_size,
                "row_h": row_h,
            })

        total_h = sum(b["row_h"] + gap_y for b in blocks)
        y = inner.bottom - total_h
        if y > inner.top:
            y = inner.top

        for b in blocks:
            is_left = b["is_left"]
            speaker = b["speaker"]
            pstyle: Participant = b["participant"]
            bubble_w, bubble_h = b["bubble_size"]
            avatar_size = b["avatar_size"]

            if is_left:
                ax = inner.left
                bx = ax + avatar_size + 12
            else:
                ax = inner.right - avatar_size
                bx = ax - 12 - bubble_w

            ay = y + (b["row_h"] - avatar_size) // 2
            by = y + 3

            # avatar
            thumb = self._thumb_for(pstyle, avatar_size)
            if thumb:
                screen.blit(thumb, (ax, ay))
                pygame.draw.rect(screen, (220, 220, 220, 60), pygame.Rect(ax, ay, avatar_size, avatar_size), 2, border_radius=10)
            else:
                pygame.draw.rect(screen, (80, 80, 80), pygame.Rect(ax, ay, avatar_size, avatar_size), border_radius=10)
                pygame.draw.rect(screen, (220, 220, 220, 60), pygame.Rect(ax, ay, avatar_size, avatar_size), 2, border_radius=10)
                init = (speaker[:1] or "?").upper()
                t = self._font_body.render(init, True, (220, 220, 220))
                tr = t.get_rect(center=(ax + avatar_size // 2, ay + avatar_size // 2))
                screen.blit(t, tr)

            # name label
            name_s = self._font_tiny.render(speaker, True, (170, 170, 170))
            if is_left:
                screen.blit(name_s, (bx, y - 1))
            else:
                screen.blit(name_s, (bx + bubble_w - name_s.get_width(), y - 1))

            # bubble surface
            bubble = pygame.Surface((bubble_w, bubble_h), pygame.SRCALPHA)
            pygame.draw.rect(
                bubble,
                (*b["bubble_rgb"], int(_clamp(self.bubble_alpha, 0, 255))),
                bubble.get_rect(),
                border_radius=self.bubble_radius,
            )
            pygame.draw.rect(
                bubble,
                (*b["outline_rgb"], int(_clamp(self.bubble_outline_alpha, 0, 255))),
                bubble.get_rect(),
                width=2,
                border_radius=self.bubble_radius,
            )

            tx = 13
            ty = 9
            for line in b["lines"]:
                if not line:
                    ty += self._font_body.get_linesize()
                    continue
                ts = self._font_body.render(line, True, (15, 15, 15))
                bubble.blit(ts, (tx, ty))
                ty += self._font_body.get_linesize()

            if b["stamp"] and self.show_timestamp and not b["indicator"]:
                ts = self._font_tiny.render(b["stamp"], True, (25, 25, 25))
                bubble.blit(ts, (bubble_w - ts.get_width() - 10, bubble_h - ts.get_height() - 8))

            screen.blit(bubble, (bx, by))

            y += b["row_h"] + gap_y

    def _draw_noise(self, screen: pygame.Surface):
        n = max(140, (self.w * self.h) // 14000)
        s = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        for _ in range(n):
            x = self._rng.randrange(0, self.w)
            y = self._rng.randrange(0, self.h)
            a = self._rng.randrange(0, max(1, self.noise_alpha) + 1)
            s.set_at((x, y), (255, 255, 255, a))
        screen.blit(s, (0, 0))

    def _reseed(self):
        if self.seed is None:
            self.seed = random.randrange(1, 2**31 - 1)
        self._rng.seed(int(self.seed))

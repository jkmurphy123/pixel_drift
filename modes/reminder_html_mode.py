# reminder_html_mode.py

import os
import re
import time
from html.parser import HTMLParser

import pygame


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def parse_style(style_str: str):
    out = {}
    if not style_str:
        return out
    parts = style_str.split(";")
    for p in parts:
        if ":" not in p:
            continue
        k, v = p.split(":", 1)
        k = k.strip().lower()
        v = v.strip().lower()
        if k == "color":
            out["color"] = v
        elif k == "font-size":
            out["font_size"] = v
        elif k == "text-align":
            out["text_align"] = v
    return out


def parse_color(value: str, fallback):
    if not value:
        return fallback
    value = value.strip()
    if value.startswith("#") and len(value) == 7:
        try:
            r = int(value[1:3], 16)
            g = int(value[3:5], 16)
            b = int(value[5:7], 16)
            return (r, g, b)
        except Exception:
            return fallback
    return fallback


def parse_font_size(value: str, fallback_px: int):
    if not value:
        return fallback_px
    m = re.match(r"^\s*(\d+)\s*px\s*$", value)
    if not m:
        return fallback_px
    return clamp(int(m.group(1)), 10, 180)


def parse_align(value: str, fallback: str):
    if not value:
        return fallback
    v = value.strip().lower()
    if v in ("center", "left"):
        return v
    return fallback


class _HTMLLite(HTMLParser):
    def __init__(self, default_color, default_size_px):
        super().__init__(convert_charrefs=True)
        self.default_color = default_color
        self.default_size_px = default_size_px

        self.tokens = []
        self._stack = [{
            "bold": False,
            "italic": False,
            "underline": False,
            "color": default_color,
            "size_px": default_size_px,
            "align": "left",
        }]

        self._in_ul = 0
        self._in_ol = 0
        self._ol_index_stack = []

    def _cur(self):
        return self._stack[-1]

    def _push(self, patch: dict):
        cur = self._cur().copy()
        cur.update(patch)
        self._stack.append(cur)

    def _pop(self):
        if len(self._stack) > 1:
            self._stack.pop()

    def _paragraph_break(self):
        if self.tokens and not self.tokens[-1].get("br", False):
            self.tokens.append({"br": True})
        self.tokens.append({"br": True})

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs = dict(attrs or [])

        if tag == "br":
            self.tokens.append({"br": True})
            return

        if tag in ("p", "div"):
            self._paragraph_break()
            return

        if tag == "center":
            self._paragraph_break()
            self._push({"align": "center"})
            return

        if tag == "ul":
            self._in_ul += 1
            self._paragraph_break()
            return

        if tag == "ol":
            self._in_ol += 1
            self._ol_index_stack.append(1)
            self._paragraph_break()
            return

        if tag == "li":
            ordered = self._in_ol > 0
            idx = self._ol_index_stack[-1] if ordered and self._ol_index_stack else 1
            if ordered and self._ol_index_stack:
                self._ol_index_stack[-1] += 1
            if self.tokens and not self.tokens[-1].get("br", False):
                self.tokens.append({"br": True})
            self.tokens.append({"li": True, "ordered": ordered, "index": idx, "align": self._cur()["align"]})
            return

        if tag in ("b", "strong", "i", "em", "u", "span", "h1", "h2", "h3"):
            patch = {}
            if tag in ("b", "strong"):
                patch["bold"] = True
            if tag in ("i", "em"):
                patch["italic"] = True
            if tag == "u":
                patch["underline"] = True

            if tag in ("h1", "h2", "h3"):
                mult = {"h1": 1.8, "h2": 1.4, "h3": 1.2}[tag]
                patch["size_px"] = clamp(int(self._cur()["size_px"] * mult), 12, 180)
                patch["bold"] = True
                self._paragraph_break()

            if tag == "span":
                st = parse_style(attrs.get("style", ""))
                if "color" in st:
                    patch["color"] = parse_color(st.get("color"), self._cur()["color"])
                if "font_size" in st:
                    patch["size_px"] = parse_font_size(st.get("font_size"), self._cur()["size_px"])
                if "text_align" in st:
                    patch["align"] = parse_align(st.get("text_align"), self._cur()["align"])

            self._push(patch)
            return

    def handle_endtag(self, tag):
        tag = tag.lower()

        if tag == "center":
            self._pop()
            self._paragraph_break()
            return

        if tag == "ul":
            self._in_ul = max(0, self._in_ul - 1)
            self._paragraph_break()
            return

        if tag == "ol":
            self._in_ol = max(0, self._in_ol - 1)
            if self._ol_index_stack:
                self._ol_index_stack.pop()
            self._paragraph_break()
            return

        if tag in ("p", "div"):
            self._paragraph_break()
            return

        if tag in ("b", "strong", "i", "em", "u", "span", "h1", "h2", "h3"):
            self._pop()
            if tag in ("h1", "h2", "h3"):
                self._paragraph_break()
            return

    def handle_data(self, data):
        txt = (data or "").replace("\r", "")
        if not txt:
            return
        txt = re.sub(r"[ \t]+", " ", txt)
        style = self._cur()
        self.tokens.append({
            "text": txt,
            "bold": style["bold"],
            "italic": style["italic"],
            "underline": style["underline"],
            "color": style["color"],
            "size_px": style["size_px"],
            "align": style["align"],
        })


class ReminderHTMLMode:
    """
    Scene-style HTML-lite whiteboard reminder.

    Config:
      - file (required)
      - bg_rgb (default white)
      - default_fg_rgb (default blue)
      - default_font_name (default Comic Sans MS)
      - default_font_size (optional; else auto)
      - margin_scale (default 0.06)
      - line_spacing (default 8)
      - refresh_hz (default 1.0)
    """

    def __init__(self, config: dict):
        self.file_path = str(config.get("file", "")).strip()

        self.bg_rgb = tuple(config.get("bg_rgb", [255, 255, 255]))
        self.default_fg = tuple(config.get("default_fg_rgb", [20, 80, 200]))

        self.default_font_name = str(config.get("default_font_name", "Comic Sans MS")).strip()
        self.default_font_size = config.get("default_font_size", None)
        self.margin_scale = float(config.get("margin_scale", 0.06))
        self.line_spacing = int(config.get("line_spacing", 8))
        self.refresh_hz = float(config.get("refresh_hz", 1.0))

        # runtime
        self.manager = None
        self.w = 0
        self.h = 0

        self._base_size = 28
        self._margin = 24
        self._max_w = 200
        self._max_h = 200

        self._font_cache = {}  # (size,bold,italic,underline) -> pygame Font (SysFont)

        self._last_read = 0.0
        self._last_html = None
        self._tokens = []

        # cached layout
        self._layout_key = None
        self._lines = []  # each: {"segs":[(surf,w)], "w":int, "h":int, "align":str}

    def enter(self, manager):
        self.manager = manager
        self._recompute_geometry()
        self._force_reload()

    def exit(self):
        self._tokens = []
        self._lines = []
        self._font_cache.clear()
        self.manager = None

    def handle_event(self, event):
        pass

    def update(self, dt: float):
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self.w, self.h = w2, h2
            self._recompute_geometry()
            self._layout_key = None

        now = time.time()
        if (now - self._last_read) >= (1.0 / max(0.2, self.refresh_hz)):
            self._last_read = now
            html = self._read_html()
            if html != self._last_html:
                self._last_html = html
                parser = _HTMLLite(default_color=self.default_fg, default_size_px=self._base_size)
                parser.feed(html)
                self._tokens = parser.tokens
                self._layout_key = None  # force relayout

        self._ensure_layout()

    def render(self, screen: pygame.Surface):
        screen.fill(self.bg_rgb)

        y = self._margin
        y_limit = self._margin + self._max_h

        for ln in self._lines:
            if y >= y_limit:
                break

            if ln["align"] == "center":
                x = self._margin + max(0, (self._max_w - ln["w"]) // 2)
            else:
                x = self._margin

            for surf, sw in ln["segs"]:
                screen.blit(surf, (x, y))
                x += sw

            y += (max(ln["h"], self._base_size) + self.line_spacing)

    # ---------- internals ----------

    def _recompute_geometry(self):
        self.w, self.h = self.manager.screen.get_size()
        is_portrait = self.h > self.w

        if self.default_font_size is None:
            base = int(self.w * (0.065 if is_portrait else 0.055))
            self._base_size = clamp(base, 18, 96)
        else:
            self._base_size = clamp(int(self.default_font_size), 12, 180)

        self._margin = int(self.w * self.margin_scale)
        self._max_w = max(80, self.w - 2 * self._margin)
        self._max_h = max(80, self.h - 2 * self._margin)

    def _force_reload(self):
        self._last_read = 0.0
        self._last_html = None
        self._layout_key = None

    def _read_html(self):
        if not self.file_path:
            return "<p><b>ReminderHTMLMode:</b> No 'file' configured.</p>"
        if not os.path.exists(self.file_path):
            return f"<p><b>ReminderHTMLMode:</b> File not found:<br>{self.file_path}</p>"
        try:
            with open(self.file_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception as e:
            return f"<p><b>ReminderHTMLMode:</b> Error reading file:<br>{e}</p>"

    def _font_candidates(self):
        return [
            self.default_font_name,
            "Comic Sans MS",
            "Segoe Print",
            "Bradley Hand",
            "Chilanka",
            "DejaVu Sans",
        ]

    def _get_font(self, size, bold, italic, underline):
        key = (size, bool(bold), bool(italic), bool(underline))
        if key in self._font_cache:
            return self._font_cache[key]

        font = None
        for name in self._font_candidates():
            try:
                font = pygame.font.SysFont(name, size, bold=bold, italic=italic)
                break
            except Exception:
                continue
        if font is None:
            font = pygame.font.SysFont(None, size, bold=bold, italic=italic)

        try:
            font.set_underline(bool(underline))
        except Exception:
            pass

        self._font_cache[key] = font
        return font

    def _split_wrap(self, text, font, max_width):
        if not text:
            return [""]

        words = text.split(" ")
        lines = []
        cur = ""

        def fits(s):
            return font.size(s)[0] <= max_width

        for w in words:
            cand = w if cur == "" else cur + " " + w
            if fits(cand):
                cur = cand
            else:
                if cur:
                    lines.append(cur)
                    cur = w
                else:
                    chunk = ""
                    for ch in w:
                        cand2 = chunk + ch
                        if fits(cand2):
                            chunk = cand2
                        else:
                            if chunk:
                                lines.append(chunk)
                            chunk = ch
                    cur = chunk

        if cur:
            lines.append(cur)
        return lines

    def _ensure_layout(self):
        key = (self.w, self.h, self._last_html, self._base_size, self._max_w)
        if key == self._layout_key:
            return

        lines = []
        cur_segs = []
        cur_w = 0
        cur_h = 0
        cur_align = "left"

        def flush_line(force_blank=False):
            nonlocal cur_segs, cur_w, cur_h, cur_align
            if force_blank or cur_segs:
                lines.append({"segs": cur_segs, "w": cur_w, "h": max(cur_h, 0), "align": cur_align})
            cur_segs = []
            cur_w = 0
            cur_h = 0
            cur_align = "left"

        for tk in self._tokens:
            if tk.get("br"):
                flush_line(force_blank=True)
                continue

            if tk.get("li"):
                cur_align = tk.get("align", cur_align)
                bullet = f"{tk['index']}." if tk.get("ordered") else "•"
                font = self._get_font(self._base_size, bold=True, italic=False, underline=False)
                surf = font.render(bullet + " ", True, self.default_fg)
                sw = surf.get_width()
                sh = font.get_linesize()

                if cur_w + sw > self._max_w and cur_segs:
                    flush_line(force_blank=False)

                cur_segs.append((surf, sw))
                cur_w += sw
                cur_h = max(cur_h, sh)
                continue

            text = tk.get("text", "")
            if not text:
                continue

            align = tk.get("align", "left")
            if cur_segs and align != cur_align:
                flush_line(force_blank=False)
            cur_align = align

            size_px = clamp(int(tk.get("size_px", self._base_size)), 12, 180)
            color = tk.get("color", self.default_fg)
            bold = bool(tk.get("bold", False))
            italic = bool(tk.get("italic", False))
            underline = bool(tk.get("underline", False))

            font = self._get_font(size_px, bold, italic, underline)
            sh = font.get_linesize()

            remaining = self._max_w - cur_w
            pieces = self._split_wrap(text, font, max(40, remaining))

            for pi, piece in enumerate(pieces):
                if pi > 0:
                    flush_line(force_blank=False)
                remaining = self._max_w - cur_w
                if cur_segs and font.size(piece)[0] > remaining:
                    flush_line(force_blank=False)

                surf = font.render(piece, True, color)
                sw = surf.get_width()
                cur_segs.append((surf, sw))
                cur_w += sw
                cur_h = max(cur_h, sh)

        flush_line(force_blank=False)

        self._lines = lines
        self._layout_key = key

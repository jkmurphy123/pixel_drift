# controlpanel/seven_seg.py
#
# 7-segment digit drawing primitives (decision D4). Shared by the digital
# readout, counter, nixie and keypad entry line — anywhere a number glows.
#
# Segment layout:      --a--
#                     |     |
#                     f     b
#                     |--g--|
#                     e     c
#                     |     |
#                      --d--

import pygame

# digit -> lit segments (a, b, c, d, e, f, g)
_SEGMENTS = {
    "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc",
    "5": "afgcd", "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcfgd",
    "-": "g", " ": "",
}


def _segment_rects(x, y, w, h, t):
    """Segment name -> pygame.Rect for a digit box at (x, y, w, h)."""
    hw = w - t          # horizontal segment length
    vh = (h - 3 * t) // 2  # vertical segment length (per half)
    return {
        "a": pygame.Rect(x + t, y, hw - t, t),
        "g": pygame.Rect(x + t, y + t + vh, hw - t, t),
        "d": pygame.Rect(x + t, y + 2 * (t + vh), hw - t, t),
        "f": pygame.Rect(x, y + t, t, vh),
        "b": pygame.Rect(x + w - t, y + t, t, vh),
        "e": pygame.Rect(x, y + 2 * t + vh, t, vh),
        "c": pygame.Rect(x + w - t, y + 2 * t + vh, t, vh),
    }


def draw_digit(surface, ch, rect, color, dim_color=None):
    """
    Draw one 7-seg character centered in rect (x, y, w, h).
    Unlit segments are drawn faintly in dim_color when given (authentic
    "ghost segments" look).
    """
    ch = str(ch)
    lit = _SEGMENTS.get(ch, "")
    x, y, w, h = rect
    t = max(2, int(min(w, h) * 0.14))  # segment thickness scales with digit
    rects = _segment_rects(x, y, w, h, t)
    for name, r in rects.items():
        if name in lit:
            pygame.draw.rect(surface, color, r)
        elif dim_color:
            pygame.draw.rect(surface, dim_color, r)


def draw_text(surface, text, rect, color, dim_color=None, pad_frac=0.08):
    """
    Draw a string of 7-seg characters centered in rect, sizing digits to fit.
    Only 0-9, '-', and space render; other chars become blank.
    """
    text = str(text)
    if not text:
        return
    x, y, w, h = rect
    pad = h * pad_frac
    digit_h = h - 2 * pad
    digit_w = digit_h * 0.55
    gap = digit_w * 0.25
    total_w = len(text) * digit_w + (len(text) - 1) * gap
    if total_w > w - 2 * pad:  # too many digits: shrink to fit
        scale = (w - 2 * pad) / total_w
        digit_w *= scale
        digit_h *= scale
        gap *= scale
        total_w = len(text) * digit_w + (len(text) - 1) * gap
    cx = x + (w - total_w) / 2
    cy = y + (h - digit_h) / 2
    for i, ch in enumerate(text):
        draw_digit(surface, ch,
                   (cx + i * (digit_w + gap), cy, digit_w, digit_h),
                   color, dim_color)

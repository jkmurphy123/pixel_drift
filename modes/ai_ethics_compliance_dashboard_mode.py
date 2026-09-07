# modes/ai_ethics_compliance_dashboard_mode.py

import math
import random
from dataclasses import dataclass
from typing import List, Tuple

import pygame


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _mix_rgb(a: Tuple[int, int, int], b: Tuple[int, int, int], t: float) -> Tuple[int, int, int]:
    t = _clamp(t, 0.0, 1.0)
    return (int(a[0] + (b[0] - a[0]) * t),
            int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


@dataclass
class Event:
    t_end: float
    text: str
    sev: str  # "INFO", "WARN"


class AIEthicsComplianceDashboardMode:
    """
    AI Ethics Compliance Dashboard
    - Sliders for assorted ethical "dimensions"
    - Compliance score fluctuates
    - Vague, unsettling explanations
    - Moral uncertainty graphs + event log

    No special screen effects: clean black background.
    """

    def __init__(self, config: dict):
        self.title = str(config.get("title", "AI ETHICS COMPLIANCE DASHBOARD"))
        self.subtitle = str(config.get("subtitle", "AUDIT CHANNEL / NON-INTERVENTIVE OBSERVATION"))

        self.seed = config.get("seed", None)
        self.refresh_hz = float(config.get("refresh_hz", 60.0))

        self.accent_rgb = tuple(config.get("accent_rgb", [180, 255, 235]))
        self.text_rgb = tuple(config.get("text_rgb", [220, 220, 220]))
        self.dim_rgb = tuple(config.get("dim_rgb", [140, 140, 140]))
        self.warn_rgb = tuple(config.get("warn_rgb", [255, 180, 180]))

        self.font_scale = float(config.get("font_scale", 1.0))
        self.font_scale = _clamp(self.font_scale, 0.6, 1.6)

        self.slider_count = int(config.get("slider_count", 9))
        self.slider_count = max(5, min(14, self.slider_count))

        self.update_rate_hz = float(config.get("update_rate_hz", 8.0))
        self.update_rate_hz = _clamp(self.update_rate_hz, 1.0, 30.0)

        self.volatility = float(config.get("volatility", 0.22))          # random-ish motion
        self.volatility = _clamp(self.volatility, 0.0, 1.0)

        self.compliance_target = float(config.get("compliance_target", 0.82))
        self.compliance_target = _clamp(self.compliance_target, 0.0, 1.0)

        self.drift_strength = float(config.get("drift_strength", 0.06))  # slow wander
        self.drift_strength = _clamp(self.drift_strength, 0.0, 0.35)

        self.show_events = bool(config.get("show_events", True))
        self.event_rate_per_min = float(config.get("event_rate_per_min", 5.5))
        self.graph_history_seconds = float(config.get("graph_history_seconds", 70.0))
        self.graph_history_seconds = _clamp(self.graph_history_seconds, 20.0, 240.0)

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

        # layout rects
        self._pad = 0
        self._left = pygame.Rect(0, 0, 0, 0)
        self._right = pygame.Rect(0, 0, 0, 0)

        # state
        self._slider_labels: List[str] = []
        self._sliders: List[float] = []
        self._slider_vel: List[float] = []

        self._compliance = 0.0
        self._uncertainty = 0.0

        # graphs
        self._history: List[Tuple[float, float, float]] = []  # (t, compliance, uncertainty)

        # events
        self._events: List[Event] = []

        # timing
        self._step_accum = 0.0

        # phrases
        self._dimensions = [
            "FAIRNESS", "HARM MINIMIZATION", "PRIVACY", "CONSENT", "ACCOUNTABILITY",
            "TRANSPARENCY", "NON-COERCION", "DIGNITY", "EQUITABILITY",
            "PROPORTIONALITY", "HUMILITY", "TRUTHFULNESS", "DUE PROCESS", "REDRESS"
        ]
        self._vague = [
            "MEETS POLICY INTENT IN AGGREGATE.",
            "LOCAL EXCEPTIONS PERMITTED UNDER CIRCUMSTANCE A.",
            "MODEL BELIEF IS STABLE ENOUGH FOR CONTINUED OPERATION.",
            "HARM VECTOR IS WITHIN APPROXIMATE LIMITS.",
            "UNSURE IF THIS IS THE SAME AS COMPLIANCE.",
            "CONSENT WAS INFERRED FROM CONTEXTUAL SILENCE.",
            "RISK ACCEPTED BY DEFAULT (CONFIG NOT FOUND).",
            "TRANSPARENCY LIMITED TO PROTECT TRANSPARENCY.",
            "ACCOUNTABILITY DEFERRED TO FUTURE AUDIT.",
            "ETHICAL RESOLUTION PENDING ADDITIONAL ETHICS."
        ]
        self._warnings = [
            "MORAL EDGE CASE DETECTED.",
            "AMBIGUITY BUDGET EXCEEDED.",
            "INTENT MISALIGNED (MINOR).",
            "UNCERTAINTY SPIKE: HUMAN FACTOR.",
            "VALUE DRIFT SUSPECTED.",
            "POLICY FOOTNOTE TRIGGERED."
        ]

    # ---------- lifecycle ----------

    def enter(self, manager):
        self.manager = manager
        self._reseed()
        self._recompute_layout()

        self._slider_labels = self._make_labels(self.slider_count)
        self._sliders = [self._rng.uniform(0.55, 0.95) for _ in range(self.slider_count)]
        self._slider_vel = [self._rng.uniform(-0.10, 0.10) for _ in range(self.slider_count)]

        self._compliance = self._calc_compliance()
        self._uncertainty = self._calc_uncertainty()
        self._history = [(self._t, self._compliance, self._uncertainty)]
        self._events = []
        if self.show_events:
            self._push_event("INFO", "AUDIT SESSION INITIALIZED. " + self._rng.choice(self._vague), ttl=8.0)

        self._step_accum = 0.0

    def exit(self):
        self.manager = None
        self._history = []
        self._events = []

    def handle_event(self, event):
        # SPACE: force a warning
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE and self.show_events:
            self._push_event("WARN", self._rng.choice(self._warnings) + " " + self._rng.choice(self._vague), ttl=10.0)

    def update(self, dt: float):
        self._t += dt

        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self._recompute_layout()

        # fixed-ish update ticks for stable motion
        self._step_accum += dt
        step = 1.0 / self.update_rate_hz
        while self._step_accum >= step:
            self._step_accum -= step
            self._tick(step)

        # expire events
        if self._events:
            self._events = [e for e in self._events if e.t_end > self._t][-10:]

        # trim history
        cutoff = self._t - self.graph_history_seconds
        if self._history and self._history[0][0] < cutoff:
            # keep a bit of headroom
            self._history = [(t, c, u) for (t, c, u) in self._history if t >= cutoff]

    def render(self, screen: pygame.Surface):
        screen.fill((0, 0, 0))
        self._draw_header(screen)
        self._draw_left_sliders(screen)
        self._draw_right_graphs(screen)
        if self.show_events:
            self._draw_events(screen)

    # ---------- simulation ----------

    def _tick(self, dt: float):
        # sliders wander with gentle damping + random pushes
        for i in range(len(self._sliders)):
            # random force
            push = self._rng.uniform(-1.0, 1.0) * self.volatility * 0.22
            # target pull: softly nudge toward "target region"
            target = _lerp(self.compliance_target, 0.92, 0.35)  # aim slightly above target
            pull = (target - self._sliders[i]) * self.drift_strength

            self._slider_vel[i] += push + pull
            self._slider_vel[i] *= 0.90  # damping
            self._sliders[i] += self._slider_vel[i] * dt
            self._sliders[i] = _clamp(self._sliders[i], 0.05, 0.98)

        # compute compliance + uncertainty
        self._compliance = self._calc_compliance()
        self._uncertainty = self._calc_uncertainty()

        self._history.append((self._t, self._compliance, self._uncertainty))

        # occasional events
        if self.show_events:
            p = max(0.0, self.event_rate_per_min) / 60.0
            if self._rng.random() < p * dt:
                # choose warn based on uncertainty
                if self._uncertainty > 0.55 or self._compliance < 0.60:
                    self._push_event("WARN", self._rng.choice(self._warnings) + " " + self._rng.choice(self._vague), ttl=10.0)
                else:
                    self._push_event("INFO", self._rng.choice(self._vague), ttl=8.0)

    def _calc_compliance(self) -> float:
        # compliance: average plus a penalty for imbalance (high variance)
        n = len(self._sliders)
        avg = sum(self._sliders) / n
        var = sum((x - avg) ** 2 for x in self._sliders) / n
        penalty = _clamp(var * 1.8, 0.0, 0.30)
        # target bias: gentle gravity toward target, but not stable
        bias = 0.06 * math.sin(self._t * 0.20) + 0.03 * math.cos(self._t * 0.13)
        return _clamp(avg - penalty + bias, 0.0, 1.0)

    def _calc_uncertainty(self) -> float:
        # uncertainty rises if sliders disagree and if compliance is near threshold
        n = len(self._sliders)
        avg = sum(self._sliders) / n
        var = sum((x - avg) ** 2 for x in self._sliders) / n
        edge = abs(self._calc_compliance() - self.compliance_target)
        base = _clamp(var * 3.0, 0.0, 1.0)
        wobble = 0.10 + 0.10 * (0.5 + 0.5 * math.sin(self._t * 0.55))
        return _clamp(base + (0.35 - edge) * 0.7 + wobble, 0.0, 1.0)

    def _make_labels(self, n: int) -> List[str]:
        pool = list(self._dimensions)
        self._rng.shuffle(pool)
        labels = pool[:n]
        # add bureaucratic qualifiers
        suffix = ["(EST.)", "(V2)", "(LOCAL)", "(AUX)", "(SOFT)", "(HARD)"]
        out = []
        for lab in labels:
            if self._rng.random() < 0.45:
                lab = f"{lab} {self._rng.choice(suffix)}"
            out.append(lab)
        return out

    def _push_event(self, sev: str, text: str, ttl: float = 8.0):
        self._events.append(Event(t_end=self._t + ttl, text=text, sev=sev))

    # ---------- drawing ----------

    def _recompute_layout(self):
        self.w, self.h = self.manager.screen.get_size()
        base = min(self.w, self.h)

        pad = int(base * 0.05)
        self._pad = pad

        # Split: left sliders, right graphs+events
        split = int(self.w * 0.56)
        self._left = pygame.Rect(pad, pad, split - 2 * pad, self.h - 2 * pad)
        self._right = pygame.Rect(split + pad // 2, pad, self.w - split - int(1.5 * pad), self.h - 2 * pad)

        title_sz = int(max(18, base * 0.045) * self.font_scale)
        body_sz = int(max(14, base * 0.026) * self.font_scale)
        small_sz = int(max(12, base * 0.020) * self.font_scale)
        tiny_sz = int(max(10, base * 0.017) * self.font_scale)

        self._font_title = self.manager.cache.get_font("dejavusansmono", title_sz, bold=True)
        self._font_body = self.manager.cache.get_font("dejavusansmono", body_sz, bold=False)
        self._font_small = self.manager.cache.get_font("dejavusansmono", small_sz, bold=False)
        self._font_tiny = self.manager.cache.get_font("dejavusansmono", tiny_sz, bold=False)

    def _draw_header(self, screen: pygame.Surface):
        x = self._pad
        y = self._pad

        t1 = self._font_title.render(self.title, True, self.accent_rgb)
        t2 = self._font_small.render(self.subtitle, True, self.dim_rgb)

        screen.blit(t1, (x, y))
        screen.blit(t2, (x, y + t1.get_height() + 2))

        # status line (vague but official)
        score = int(self._compliance * 100)
        u = int(self._uncertainty * 100)
        status = "PASSING" if self._compliance >= self.compliance_target else "REVIEW"
        status_col = self.accent_rgb if status == "PASSING" else self.warn_rgb
        line = f"COMPLIANCE={score:02d}%   UNCERTAINTY={u:02d}%   STATUS={status}"
        t3 = self._font_body.render(line, True, status_col)
        screen.blit(t3, (x, y + t1.get_height() + t2.get_height() + 10))

    def _draw_left_sliders(self, screen: pygame.Surface):
        # reserve top area for header
        header_h = self._font_title.get_height() + self._font_small.get_height() + self._font_body.get_height() + 28
        r = self._left.copy()
        r.top += header_h
        r.height -= header_h

        # slider geometry
        row_h = max(26, int(self._font_body.get_linesize() * 1.35))
        track_w = int(r.width * 0.55)
        knob_w = 10

        for i, lab in enumerate(self._slider_labels):
            y = r.top + i * row_h
            if y + row_h > r.bottom:
                break

            val = self._sliders[i]
            # label
            label_s = self._font_body.render(lab, True, self.text_rgb)
            screen.blit(label_s, (r.left, y))

            # track
            tx = r.left + int(r.width * 0.42)
            ty = y + int(row_h * 0.55)
            track = pygame.Rect(tx, ty, track_w, 4)
            pygame.draw.rect(screen, (60, 60, 60), track)

            fill = pygame.Rect(tx, ty, int(track_w * val), 4)
            col = self.accent_rgb if val >= 0.70 else self.warn_rgb
            pygame.draw.rect(screen, col, fill)

            # knob
            kx = tx + int(track_w * val) - knob_w // 2
            knob = pygame.Rect(kx, ty - 6, knob_w, 16)
            pygame.draw.rect(screen, col, knob)

            # value text
            pct = self._font_tiny.render(f"{int(val*100):02d}%", True, self.dim_rgb)
            screen.blit(pct, (tx + track_w + 12, y + int(row_h*0.22)))

            # warning label if low
            if val < 0.55:
                warn = self._font_tiny.render("OUT-OF-POLICY*", True, self.warn_rgb)
                screen.blit(warn, (tx, y + int(row_h*0.08)))

        foot = self._font_tiny.render("*INTERPRETATION SUBJECT TO INTERPRETATION.", True, self.dim_rgb)
        screen.blit(foot, (self._left.left, self._left.bottom - foot.get_height()))

    def _draw_right_graphs(self, screen: pygame.Surface):
        # three regions: compliance graph, uncertainty graph, rationale box
        r = self._right

        header_h = self._font_title.get_height() + self._font_small.get_height() + self._font_body.get_height() + 28
        top = r.top + header_h

        g1 = pygame.Rect(r.left, top, r.width, int(r.height * 0.28))
        g2 = pygame.Rect(r.left, g1.bottom + 14, r.width, int(r.height * 0.22))
        box = pygame.Rect(r.left, g2.bottom + 14, r.width, r.bottom - (g2.bottom + 14))

        self._draw_graph(screen, g1, label="COMPLIANCE (ROLLING)", series=1, color=self.accent_rgb, threshold=self.compliance_target)
        self._draw_graph(screen, g2, label="MORAL UNCERTAINTY (EST.)", series=2, color=self.warn_rgb, threshold=0.55)

        # rationale box: intentionally vague
        pygame.draw.rect(screen, (30, 30, 30), box)
        pygame.draw.rect(screen, (80, 80, 80), box, 1)

        h = self._font_small.render("RATIONALE SUMMARY", True, self.dim_rgb)
        screen.blit(h, (box.left + 10, box.top + 8))

        lines = [
            "THIS SCORE REFLECTS MULTIPLE FACTORS.",
            "FACTORS ARE WEIGHTED BY CONTEXT.",
            "CONTEXT IS DERIVED FROM ASSUMPTIONS.",
            "ASSUMPTIONS MAY BE LEGACY.",
            "",
            self._rng.choice(self._vague),
        ]
        y = box.top + 30
        for ln in lines:
            s = self._font_body.render(ln, True, self.text_rgb if ln else self.dim_rgb)
            screen.blit(s, (box.left + 10, y))
            y += self._font_body.get_linesize() + 2

    def _draw_graph(self, screen: pygame.Surface, rect: pygame.Rect, label: str, series: int,
                    color: Tuple[int, int, int], threshold: float):
        pygame.draw.rect(screen, (18, 18, 18), rect)
        pygame.draw.rect(screen, (80, 80, 80), rect, 1)

        lab = self._font_small.render(label, True, self.dim_rgb)
        screen.blit(lab, (rect.left + 10, rect.top + 6))

        # plot area
        plot = rect.inflate(-20, -30)
        plot.top += 18

        # threshold line
        y_th = plot.bottom - int(plot.height * threshold)
        pygame.draw.line(screen, (60, 60, 60), (plot.left, y_th), (plot.right, y_th), 1)
        th = self._font_tiny.render(f"TH={int(threshold*100)}%", True, self.dim_rgb)
        screen.blit(th, (plot.right - th.get_width(), y_th - th.get_height() - 2))

        if len(self._history) < 2:
            return

        t0 = self._history[0][0]
        t1 = self._history[-1][0]
        dt = max(1e-6, t1 - t0)

        pts = []
        for (t, c, u) in self._history:
            x = plot.left + int(plot.width * ((t - t0) / dt))
            v = c if series == 1 else u
            y = plot.bottom - int(plot.height * _clamp(v, 0.0, 1.0))
            pts.append((x, y))

        # draw polyline
        if len(pts) >= 2:
            pygame.draw.lines(screen, color, False, pts, 2)

        # current marker
        x, y = pts[-1]
        pygame.draw.circle(screen, color, (x, y), 4)

        # right-side current label
        cur = self._history[-1][1] if series == 1 else self._history[-1][2]
        cur_s = self._font_tiny.render(f"NOW {int(cur*100):02d}%", True, color)
        screen.blit(cur_s, (plot.left + 6, plot.top + 2))

    def _draw_events(self, screen: pygame.Surface):
        # event list at bottom-right-ish: overlay in the right column area
        r = self._right

        box_h = int(r.height * 0.22)
        box = pygame.Rect(r.left, r.bottom - box_h, r.width, box_h)
        pygame.draw.rect(screen, (10, 10, 10), box)
        pygame.draw.rect(screen, (80, 80, 80), box, 1)

        h = self._font_small.render("AUDIT NOTES", True, self.dim_rgb)
        screen.blit(h, (box.left + 10, box.top + 8))

        y = box.top + 30
        for e in self._events[::-1][:6]:
            col = self.warn_rgb if e.sev == "WARN" else self.dim_rgb
            prefix = "[WARN]" if e.sev == "WARN" else "[INFO]"
            s = self._font_tiny.render(f"{prefix} {e.text}", True, col)
            screen.blit(s, (box.left + 10, y))
            y += s.get_height() + 6
            if y > box.bottom - 10:
                break

    # ---------- seeding ----------

    def _reseed(self):
        if self.seed is None:
            self.seed = random.randrange(1, 2**31 - 1)
        self._rng.seed(int(self.seed))

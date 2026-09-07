# controlpanel/signals.py
#
# Signal generators: the "life" behind every animated control
# (CONTROL_PANEL_DESIGN.md section 3.1).
#
# A Signal produces a normalized float that changes over time. Controls
# compose signals rather than subclassing behavior, so a gauge, a bar graph
# and a readout can all drink from the same recipe. Each control instance
# gets its own signal instance (seeded from the mode rng) so the panel never
# moves in lockstep.
#
# Signals are stateful: call update(dt) once per frame, then read .value.
# Unipolar signals return 0.0..1.0; bipolar (scope) signals return -1.0..1.0.

import math
import random


class Signal:
    """Base class. value is read after update(dt)."""

    bipolar = False

    def __init__(self):
        self.value = 0.0

    def update(self, dt: float):
        pass


class SineSignal(Signal):
    """Smooth sine. Unipolar by default, bipolar for scope traces."""

    def __init__(self, rng: random.Random, freq=0.2, bipolar=False, **_):
        super().__init__()
        self.bipolar = bipolar
        self.freq = float(freq)
        self.phase = rng.uniform(0.0, math.tau)
        self.t = 0.0

    def update(self, dt: float):
        self.t += dt
        s = math.sin(math.tau * self.freq * self.t + self.phase)
        self.value = s if self.bipolar else (s + 1.0) * 0.5


class RandomWalkSignal(Signal):
    """
    Gauge drift: eases toward a random target; when it arrives (or the hold
    expires) it picks a new one. `period` is the average seconds between
    target changes; `speed` is the easing rate.
    """

    def __init__(self, rng: random.Random, period=6.0, speed=1.5,
                 min=0.1, max=0.9, **_):
        super().__init__()
        self.rng = rng
        self.speed = float(speed)
        self.lo, self.hi = float(min), float(max)
        self.hold_range = (float(period) * 0.5, float(period) * 1.5)
        self.value = rng.uniform(self.lo, self.hi)
        self.target = self.value
        self.hold = rng.uniform(*self.hold_range)

    def update(self, dt: float):
        self.hold -= dt
        if self.hold <= 0.0:
            self.target = self.rng.uniform(self.lo, self.hi)
            self.hold = self.rng.uniform(*self.hold_range)
        # exponential ease toward the target
        self.value += (self.target - self.value) * min(1.0, self.speed * dt)


class StepSignal(Signal):
    """Jumps to a new random level, then holds it (hold_range in seconds)."""

    def __init__(self, rng: random.Random, hold_range=(0.8, 2.5),
                 min=0.0, max=1.0, **_):
        super().__init__()
        self.rng = rng
        self.hold_range = (float(hold_range[0]), float(hold_range[1]))
        self.lo, self.hi = float(min), float(max)
        self.value = rng.uniform(self.lo, self.hi)
        self.hold = rng.uniform(*self.hold_range)

    def update(self, dt: float):
        self.hold -= dt
        if self.hold <= 0.0:
            self.value = self.rng.uniform(self.lo, self.hi)
            self.hold = self.rng.uniform(*self.hold_range)


class SquareSignal(Signal):
    """Blink: 0/1 with the given period and duty cycle."""

    def __init__(self, rng: random.Random, period=1.0, duty=0.5, **_):
        super().__init__()
        self.period = max(0.05, float(period))
        self.duty = min(0.95, max(0.05, float(duty)))
        self.t = rng.uniform(0.0, self.period)

    def update(self, dt: float):
        self.t = (self.t + dt) % self.period
        self.value = 1.0 if self.t < self.period * self.duty else 0.0


class PulseTrainSignal(Signal):
    """
    Activity LED: brief flashes at `rate` pulses/sec (with jitter),
    each pulse decaying exponentially.
    """

    def __init__(self, rng: random.Random, rate=1.5, decay=6.0, **_):
        super().__init__()
        self.rng = rng
        self.rate = float(rate)
        self.decay = float(decay)

    def update(self, dt: float):
        self.value *= math.exp(-self.decay * dt)
        if self.rng.random() < self.rate * dt:
            self.value = 1.0


class NoiseSignal(Signal):
    """Sample-and-hold noise: a new random level `rate` times per second."""

    def __init__(self, rng: random.Random, rate=8.0, bipolar=False, **_):
        super().__init__()
        self.bipolar = bipolar
        self.rng = rng
        self.rate = float(rate)
        self.acc = 0.0

    def update(self, dt: float):
        self.acc += dt
        step = 1.0 / max(0.1, self.rate)
        while self.acc >= step:
            self.acc -= step
            v = self.rng.random()
            self.value = (v * 2.0 - 1.0) if self.bipolar else v


_KINDS = {
    "sine": SineSignal,
    "random_walk": RandomWalkSignal,
    "step": StepSignal,
    "square": SquareSignal,
    "pulse": PulseTrainSignal,
    "noise": NoiseSignal,
}


def build_signal(spec, rng: random.Random, default_kind: str,
                 bipolar: bool = False) -> Signal:
    """
    Build a signal from a layout/control spec dict, e.g.
    {"kind": "random_walk", "period": 6.0}. Missing/invalid kinds fall back
    to the control's default. Extra keys are passed to the constructor.
    """
    spec = dict(spec or {})
    kind = str(spec.pop("kind", default_kind)).strip().lower()
    cls = _KINDS.get(kind) or _KINDS[default_kind]
    spec.setdefault("bipolar", bipolar)
    return cls(rng, **spec)

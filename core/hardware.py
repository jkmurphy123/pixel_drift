# core/hardware.py
#
# Raspberry Pi rotary-encoder / button / LED hardware input.
#
# gpiozero is imported lazily inside setup() so the rest of the project
# runs fine on Windows / vanilla Linux dev machines without it installed.


class RotaryHardware:
    """
    Wires up:
      - rotary encoder (pins a=17, b=27)  -> on_rotate(delta)
      - encoder push button (pin 23)      -> short press: on_tap(), hold 2s: on_hold()
      - 8 indicator LEDs                  -> set_mode(mode_index)
    """

    LED_PINS = [5, 6, 13, 19, 26, 21, 20, 16]

    def __init__(self, on_rotate, on_tap, on_hold):
        self._on_rotate = on_rotate
        self._on_tap = on_tap
        self._on_hold = on_hold

        self.encoder = None
        self.button = None
        self.leds = []

        self._last_steps = 0
        self._press_t0 = 0.0

    def setup(self) -> bool:
        """Initialize GPIO devices. Returns False if gpiozero is unavailable."""
        try:
            from gpiozero import Button, LED, RotaryEncoder
        except Exception as e:
            print(f"[Hardware] gpiozero not available ({e}); rotary input disabled")
            return False

        import time as _time
        self._time = _time

        self.encoder = RotaryEncoder(a=17, b=27, max_steps=0)
        self.button = Button(23, pull_up=True, hold_time=2.0)
        self.leds = [LED(pin) for pin in self.LED_PINS]

        self.encoder.when_rotated = self._handle_rotation
        self.button.when_pressed = self._handle_pressed
        self.button.when_released = self._handle_released
        self.button.when_held = self._handle_held
        return True

    # ---------- callbacks ----------

    def _handle_rotation(self):
        steps = self.encoder.steps
        delta = steps - self._last_steps
        self._last_steps = steps
        if delta != 0:
            self._on_rotate(1 if delta > 0 else -1)

    def _handle_pressed(self):
        self._press_t0 = self._time.time()

    def _handle_released(self):
        held = self._time.time() - self._press_t0
        if held < self.button.hold_time:
            print(f"[Hardware] Short press ({held:.2f}s)")
            self._on_tap()

    def _handle_held(self):
        self._on_hold()

    # ---------- LEDs ----------

    def set_mode(self, mode_index: int):
        if not self.leds:
            return
        led_index = mode_index % len(self.leds)
        for i, led in enumerate(self.leds):
            led.on() if i == led_index else led.off()

    # ---------- cleanup ----------

    def close(self):
        try:
            for led in self.leds:
                led.off()
        except Exception:
            pass
        for dev in [self.encoder, self.button, *self.leds]:
            try:
                if dev is not None:
                    dev.close()
            except Exception:
                pass

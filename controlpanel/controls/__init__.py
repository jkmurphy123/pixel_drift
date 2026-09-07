# controlpanel/controls/__init__.py
#
# Control factory + shared base. Every animated control type maps to a class
# here; "plate" deliberately has none (purely decorative static sprite).

from .base import Control, ControlContext  # noqa: F401
from .bars import BarGraphControl, LedBarControl  # noqa: F401
from .keypad import KeypadControl  # noqa: F401
from .lampgroups import LampBankControl, LedMatrixControl  # noqa: F401
from .lamps import LampControl, RectLampControl, SquareLampControl  # noqa: F401
from .needles import GaugeControl, MeterControl  # noqa: F401
from .readouts import (CounterControl, DigitalReadoutControl,  # noqa: F401
                       NixieControl)
from .reels import ClockControl, RadarControl, TapeReelControl  # noqa: F401
from .stateful import (PushButtonControl, RotaryKnobControl,  # noqa: F401
                       SelectorSwitchControl, ToggleSwitchControl)
from .traces import ScopeControl, StripChartControl  # noqa: F401

# type key -> animation class (see CONTROL_PANEL_DESIGN.md section 3.3)
CONTROL_CLASSES = {
    "gauge_round": GaugeControl,
    "meter_vu": MeterControl,
    "scope": ScopeControl,
    "strip_chart": StripChartControl,
    "bar_graph": BarGraphControl,
    "led_bar": LedBarControl,
    "lamp": LampControl,
    "lamp_square": SquareLampControl,
    "lamp_rect": RectLampControl,
    "lamp_bank": LampBankControl,
    "led_matrix": LedMatrixControl,
    "push_button": PushButtonControl,
    "keypad": KeypadControl,
    "toggle_switch": ToggleSwitchControl,
    "rotary_knob": RotaryKnobControl,
    "selector_switch": SelectorSwitchControl,
    "digital_readout": DigitalReadoutControl,
    "counter": CounterControl,
    "nixie": NixieControl,
    "tape_reel": TapeReelControl,
    "radar": RadarControl,
    "clock": ClockControl,
    # "plate": static only
}


def make_control(placed, ctx: ControlContext):
    """
    Instantiate the animation object for a validated PlacedControl, or None
    if this type is static-only (renders as its sprite).
    """
    cls = CONTROL_CLASSES.get(placed.type)
    if cls is None:
        return None
    return cls(placed, ctx)

# controlpanel/registry.py
#
# Control type registry: maps the layout-file "type" key to its default
# sprite. Animation classes attach here in later phases (design 3.3);
# for phase 1 every control renders as its static sprite.

# type key -> default sprite ID (from sprite_defs.json)
CONTROL_TYPES = {
    "gauge_round":     "GAUGE_ROUND_SMALL_1",
    "meter_vu":        "METER_VU_H_1",
    "scope":           "SCOPE_H_1",
    "strip_chart":     "STRIP_CHART",
    "bar_graph":       "BAR_GRAPH_V_1",
    "led_bar":         "LED_BAR",
    "lamp":            "LED_LAMP_RED",
    "lamp_bank":       "LAMP_BANK",
    "led_matrix":      "LED_MATRIX",
    "push_button":     "PUSH_BUTTON_1",
    "keypad":          "KEYPAD",
    "toggle_switch":   "TOGGLE_SWITCH_1",
    "rotary_knob":     "ROTARY_KNOB_1",
    "selector_switch": "SELECTOR_SWITCH",
    "digital_readout": "READOUT_DIGITAL",
    "counter":         "COUNTER",
    "nixie":           "NIXIE_PAIR",
    "tape_reel":       "TAPE_REEL",
    "radar":           "RADAR_ROUND",
    "clock":           "CLOCK_FACE",
    "plate":           "PANEL_PLATE_1",
}

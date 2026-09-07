#!/usr/bin/env python3
# pixel_drift.py
#
# Unified mode controller — replaces the old mode_controller.py,
# single_mode_controller.py, and auto_mode_controller.py.
#
# Usage:
#   python3 pixel_drift.py --show_modes
#   python3 pixel_drift.py --play 3                     # single mode, ESC quits
#   python3 pixel_drift.py --play 3 --windowed --width 1280 --height 720
#   python3 pixel_drift.py                              # manual: arrows switch, ESC quits
#   python3 pixel_drift.py --auto 30                    # auto-cycle every 30s
#   python3 pixel_drift.py --auto 30 --shuffle --start 2
#   python3 pixel_drift.py --input rotary               # Raspberry Pi rotary encoder
#
# Input:
#   keyboard (default): LEFT/RIGHT switch modes, ESC quits
#   rotary (--input rotary): knob switches, tap quits, hold 2s reboots (Pi only)

import argparse
import os
import sys
import time

import pygame

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from core.config import (
    infer_max_modes_from_config,
    list_configured_modes,
    load_project_config,
    load_secrets,
)
from core.hardware import RotaryHardware
from core.manager import ModeManager
from core.playlist import Playlist


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="pixel_drift — kiosk mode controller"
    )

    parser.add_argument("--show_modes", action="store_true",
                        help="List all configured modes and exit")
    parser.add_argument("--play", type=int, default=None, metavar="N",
                        help="Play only mode N (no switching)")
    parser.add_argument("--auto", type=float, default=None, metavar="SECONDS",
                        help="Auto-cycle through modes every N seconds")
    parser.add_argument("--start", type=int, default=0,
                        help="Mode index to start on (default: 0)")
    parser.add_argument("--shuffle", action="store_true",
                        help="Cycle through modes in random order (with --auto)")
    parser.add_argument("--max-modes", type=int, default=None,
                        help="Override maximum number of modes")
    parser.add_argument("--input", choices=["keyboard", "rotary", "none"],
                        default="keyboard",
                        help="Input source for mode switching (default: keyboard)")
    parser.add_argument("--config", default=None, metavar="FILE",
                        help="Override modes config file (default: from registry settings)")

    parser.add_argument("--windowed", action="store_true",
                        help="Run in a window instead of fullscreen")
    parser.add_argument("--width", type=int, default=1280,
                        help="Window width (used with --windowed)")
    parser.add_argument("--height", type=int, default=720,
                        help="Window height (used with --windowed)")

    parser.add_argument("--gc-seconds", type=float, default=30.0,
                        help="Run gc.collect() every N seconds (default: 30, 0 disables)")

    args = parser.parse_args(argv[1:])

    if args.auto is not None and args.auto <= 0:
        parser.error("--auto duration must be > 0")
    if args.max_modes is not None and args.max_modes < 1:
        parser.error("--max-modes must be >= 1")
    if args.width <= 0 or args.height <= 0:
        parser.error("--width and --height must be > 0")
    if args.gc_seconds < 0:
        parser.error("--gc-seconds must be >= 0")
    if args.play is not None and args.auto is not None:
        parser.error("--play and --auto are mutually exclusive")

    return args


def main(argv=None):
    args = parse_args(argv or sys.argv)

    registry_json, registry, modes_config, config_path = load_project_config(
        BASE_DIR, config_override=args.config
    )
    secrets = load_secrets(BASE_DIR)
    max_modes = args.max_modes or infer_max_modes_from_config(modes_config)

    if args.show_modes:
        list_configured_modes(modes_config, config_path)
        return 0

    print(f"[Controller] Max modes: {max_modes}")

    # ---------------- pygame shell ----------------

    pygame.init()
    pygame.display.init()
    pygame.font.init()
    pygame.mouse.set_visible(False)

    if args.windowed:
        screen = pygame.display.set_mode((args.width, args.height), pygame.RESIZABLE)
        pygame.display.set_caption("pixel_drift — windowed")
    else:
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.display.set_caption("pixel_drift")

    # ---------------- playlist / manager ----------------

    single_mode_lock = args.play is not None
    if single_mode_lock:
        playlist = Playlist.single(args.play % max_modes)
        print(f"[Controller] Single-mode lock: mode {args.play % max_modes}")
    else:
        playlist = Playlist(max_modes, shuffle=args.shuffle,
                            start_index=args.start % max_modes)

    manager = ModeManager(screen, registry, modes_config, max_modes, secrets)
    manager.start(initial_index=playlist.current)

    # ---------------- hardware input (optional) ----------------

    hardware = None
    quit_requested = False

    if args.input == "rotary" and not single_mode_lock:
        def on_rotate(delta):
            if manager.is_transitioning():
                return
            playlist.advance(delta)
            manager.request_switch(playlist.current)

        def on_tap():
            nonlocal quit_requested
            quit_requested = True

        def on_hold():
            print("[Controller] Encoder held 2s -> rebooting")
            os.system("sudo reboot")

        hardware = RotaryHardware(on_rotate, on_tap, on_hold)
        if hardware.setup():
            hardware.set_mode(manager.mode_index)
        else:
            hardware = None
            print("[Controller] Falling back to keyboard input")

    # ---------------- main loop ----------------

    clock = pygame.time.Clock()
    elapsed_in_mode = 0.0
    queued_delta = 0
    last_gc = time.time()

    if args.auto:
        print(f"[Controller] Auto-cycle every {args.auto:.1f}s. ESC quits.")
    elif single_mode_lock:
        print("[Controller] Running single mode. ESC quits.")
    else:
        print("[Controller] Manual mode. LEFT/RIGHT switch, ESC quits.")

    import gc as _gc

    try:
        while not quit_requested:
            dt = clock.tick(60) / 1000.0
            elapsed_in_mode += dt

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    quit_requested = True
                    continue

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        quit_requested = True
                        continue

                    if not single_mode_lock and args.input == "keyboard":
                        if event.key == pygame.K_RIGHT:
                            if manager.is_transitioning():
                                queued_delta += 1
                            else:
                                playlist.advance(+1)
                                manager.request_switch(playlist.current)
                                elapsed_in_mode = 0.0
                            continue
                        if event.key == pygame.K_LEFT:
                            if manager.is_transitioning():
                                queued_delta -= 1
                            else:
                                playlist.advance(-1)
                                manager.request_switch(playlist.current)
                                elapsed_in_mode = 0.0
                            continue

                manager.handle_event(event)

            # Apply arrow presses queued during a fade, once stable
            if not single_mode_lock and not manager.is_transitioning() and queued_delta != 0:
                step = 1 if queued_delta > 0 else -1
                queued_delta -= step
                playlist.advance(step)
                manager.request_switch(playlist.current)
                elapsed_in_mode = 0.0

            # Auto-cycle
            if (args.auto is not None and not single_mode_lock
                    and not manager.is_transitioning()
                    and elapsed_in_mode >= args.auto):
                playlist.advance(+1)
                manager.request_switch(playlist.current)
                elapsed_in_mode = 0.0

            manager.update(dt)
            manager.render()
            pygame.display.flip()

            if hardware is not None:
                hardware.set_mode(manager.mode_index)

            if args.gc_seconds > 0:
                now = time.time()
                if now - last_gc >= args.gc_seconds:
                    _gc.collect()
                    last_gc = now

    finally:
        print("[Controller] Quitting cleanly...")
        try:
            if manager.current_mode is not None:
                manager.current_mode.exit()
        except Exception:
            pass
        if hardware is not None:
            hardware.close()
        try:
            pygame.quit()
        except Exception:
            pass

    print("[Controller] Exited.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

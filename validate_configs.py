#!/usr/bin/env python3
# validate_configs.py
#
# Static validation of modes_registry.json + modes config files.
# Catches config typos at dev time instead of at kiosk runtime.
#
# Usage:
#   python3 validate_configs.py              # validate the active config
#   python3 validate_configs.py --all        # also validate every configs/*.json variant
#   python3 validate_configs.py --config configs/modes_config_windows.json
#
# Exit code 0 = no errors (warnings allowed), 1 = errors found.

import argparse
import importlib
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from core.config import (
    COMMON_INSTANCE_KEYS,
    infer_max_modes_from_config,
    load_json,
    load_project_config,
    normalize_type,
)

errors = []
warnings = []


def err(msg):
    errors.append(msg)
    print(f"  ERROR: {msg}")


def warn(msg):
    warnings.append(msg)
    print(f"  warn:  {msg}")


def validate_registry(registry_json: dict) -> dict:
    print("[Validate] Registry: modes_registry.json")
    types = registry_json.get("types")
    if not isinstance(types, dict) or not types:
        err("registry has no 'types' dict (or it is empty)")
        return {}

    for type_key, spec in types.items():
        if not isinstance(spec, dict):
            err(f"type '{type_key}': entry is not an object")
            continue

        entrypoint = spec.get("entrypoint")
        if not entrypoint:
            err(f"type '{type_key}': missing 'entrypoint'")
            continue

        if ":" not in entrypoint:
            err(f"type '{type_key}': entrypoint '{entrypoint}' lacks 'module:Class' form")
            continue

        module_name, class_name = entrypoint.split(":", 1)
        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            err(f"type '{type_key}': cannot import module '{module_name}': {e}")
            continue
        if not hasattr(module, class_name):
            err(f"type '{type_key}': module '{module_name}' has no class '{class_name}'")

        # A normalized type key should round-trip (catches confusing aliases)
        if normalize_type(type_key) != type_key:
            warn(f"type '{type_key}': key is not in normalized form "
                 f"('{normalize_type(type_key)}')")

        # Secrets must not live in the registry
        for key in spec.get("type_config", {}):
            if "api_key" in key or "secret" in key or "token" in key:
                warn(f"type '{type_key}': type_config contains '{key}' — "
                     f"secrets belong in secrets.json or env vars")

    print(f"[Validate] Registry OK: {len(types)} type(s)")
    return types


def validate_modes_config(name: str, modes_config: dict, registry: dict):
    print(f"[Validate] Config: {name}")

    if not modes_config:
        err(f"{name}: no 'modes' found (or file missing/invalid)")
        return

    for mode_key, cfg in sorted(modes_config.items(),
                                key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 10**9):
        if not str(mode_key).isdigit():
            warn(f"mode key '{mode_key}' is not numeric — it will never be loaded")
            continue
        if not isinstance(cfg, dict):
            err(f"mode {mode_key}: config is not an object")
            continue

        raw_type = cfg.get("type")
        if not raw_type:
            err(f"mode {mode_key}: missing 'type'")
            continue

        type_key = normalize_type(raw_type)
        spec = registry.get(type_key)
        if spec is None:
            err(f"mode {mode_key}: unknown type '{raw_type}' (normalized '{type_key}')")
            continue

        # Required keys
        required = spec.get("required", [])
        missing = [k for k in required if k not in cfg]
        if missing:
            err(f"mode {mode_key} ({type_key}): missing required keys: {missing}")

        # Unknown keys (typo-catcher, e.g. 'led_collor')
        known = set(required) | set(spec.get("optional", [])) | COMMON_INSTANCE_KEYS
        for key in cfg:
            if key not in known:
                warn(f"mode {mode_key} ({type_key}): unknown key '{key}' "
                     f"(not in required/optional for this type)")

        # Local data-file references should exist (relative to project root)
        for key in ("file", "data_file", "quotes_file"):
            val = cfg.get(key)
            if isinstance(val, str) and val and not os.path.isabs(val):
                if not os.path.exists(os.path.join(BASE_DIR, val)):
                    warn(f"mode {mode_key} ({type_key}): '{key}' -> '{val}' not found "
                         f"relative to project root")

    max_modes = infer_max_modes_from_config(modes_config)
    print(f"[Validate] Config OK: {len(modes_config)} mode(s), max_modes={max_modes}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate pixel_drift configs")
    parser.add_argument("--config", default=None,
                        help="Specific modes config file to validate")
    parser.add_argument("--all", action="store_true",
                        help="Also validate every configs/*.json variant")
    args = parser.parse_args((argv or sys.argv)[1:])

    # Registry
    registry_json = load_json(os.path.join(BASE_DIR, "modes_registry.json"), {})
    registry = validate_registry(registry_json)

    # Active config (respects registry settings / --config / local override)
    _, _, modes_config, config_path = load_project_config(
        BASE_DIR, config_override=args.config
    )
    validate_modes_config(os.path.basename(config_path), modes_config, registry)

    # All variants on request
    if args.all:
        variants_dir = os.path.join(BASE_DIR, "configs")
        if os.path.isdir(variants_dir):
            for fname in sorted(os.listdir(variants_dir)):
                if not fname.endswith(".json"):
                    continue
                path = os.path.join(variants_dir, fname)
                cfg = load_json(path, {}).get("modes", {})
                validate_modes_config(f"configs/{fname}", cfg, registry)

    print()
    print(f"[Validate] Done: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

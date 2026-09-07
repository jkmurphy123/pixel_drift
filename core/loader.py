# core/loader.py
#
# Mode plugin loading: entrypoint resolution, config validation, and
# instantiation with merged config (type_config -> instance -> secrets).

import importlib

from .config import normalize_type

# Placeholder-shaped values that should be replaced by real secrets.
_PLACEHOLDER_MARKERS = ("...", "your-", "changeme", "placeholder")


def load_entrypoint(entrypoint: str):
    if ":" not in entrypoint:
        raise ValueError(f"Invalid entrypoint '{entrypoint}'")
    module_name, class_name = entrypoint.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def validate_mode_config(registry: dict, type_key: str, cfg: dict) -> bool:
    spec = registry.get(type_key, {})
    required = spec.get("required", [])
    missing = [k for k in required if k not in cfg]
    if missing:
        print(f"[ModeConfig] Mode type '{type_key}' missing required keys: {missing}")
        return False
    return True


def _looks_like_placeholder(value) -> bool:
    if not isinstance(value, str):
        return False
    v = value.strip().lower()
    return any(m in v for m in _PLACEHOLDER_MARKERS)


def build_merged_config(spec: dict, instance_cfg: dict, secrets: dict | None = None) -> dict:
    """
    Merge registry type_config under the instance config, then inject
    secrets for any key the merged config declares but leaves empty or
    placeholder-shaped (e.g. openai_api_key).
    """
    merged = {}
    merged.update(spec.get("type_config", {}))
    merged.update(instance_cfg)

    if secrets:
        for key, secret_val in secrets.items():
            existing = merged.get(key)
            if existing is None or _looks_like_placeholder(existing):
                # Only inject keys the mode actually declares interest in,
                # plus the well-known openai_api_key used by LLM modes.
                if key in merged or key == "openai_api_key":
                    merged[key] = secret_val

    return merged


def create_mode_instance(registry: dict, modes_config: dict, mode_number: int,
                         secrets: dict | None = None):
    """
    Build a mode instance for the given mode number.
    Returns None (with a printed reason) on any config problem.
    """
    cfg = modes_config.get(str(mode_number))
    if not cfg:
        print(f"[Mode] No config for mode {mode_number}")
        return None

    raw_type = cfg.get("type")
    type_key = normalize_type(raw_type)

    spec = registry.get(type_key)
    if not spec:
        print(f"[Mode] Unknown mode type '{raw_type}'. Check modes_registry.json")
        return None

    if not validate_mode_config(registry, type_key, cfg):
        return None

    entrypoint = spec.get("entrypoint")
    if not entrypoint:
        print(f"[Mode] No entrypoint for mode type '{type_key}'")
        return None

    merged_cfg = build_merged_config(spec, cfg, secrets)

    cls = load_entrypoint(entrypoint)
    print(f"[Mode] Creating mode {mode_number}: {type_key} -> {entrypoint}")
    return cls(merged_cfg)

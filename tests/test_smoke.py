# tests/test_smoke.py
#
# Smoke tests: cheap safety net for refactors.
#   1. registry entrypoints all import
#   2. configs validate with zero errors
#   3. every configured mode constructs with its merged config (no enter())
#
# Run headless:
#   SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests/ -q
# (pygame is initialized so font/image code paths don't explode)

import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

from core.config import load_json, load_project_config, load_secrets  # noqa: E402
from core.loader import build_merged_config, load_entrypoint  # noqa: E402
import validate_configs  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def pygame_init():
    pygame.init()
    pygame.font.init()
    yield
    pygame.quit()


@pytest.fixture(scope="session")
def project():
    registry_json, registry, modes_config, config_path = load_project_config(BASE_DIR)
    secrets = load_secrets(BASE_DIR)
    return registry_json, registry, modes_config, secrets


def test_validate_configs_clean(capsys):
    rc = validate_configs.main(["validate_configs.py"])
    assert rc == 0, "validate_configs reported errors (see output)"


def test_all_entrypoints_importable(project):
    _, registry, _, _ = project
    assert registry, "registry has no types"
    for type_key, spec in registry.items():
        entrypoint = spec.get("entrypoint", "")
        cls = load_entrypoint(entrypoint)  # raises on failure
        assert callable(cls), f"{type_key}: {entrypoint} is not callable"


def test_configured_modes_construct(project):
    _, registry, modes_config, secrets = project
    failures = []
    for mode_key, cfg in modes_config.items():
        spec = registry.get(cfg.get("type", "").lower().replace(" ", "").replace("_", ""))
        if not spec:
            failures.append((mode_key, "no registry spec"))
            continue
        merged = build_merged_config(spec, cfg, secrets)
        try:
            cls = load_entrypoint(spec["entrypoint"])
            cls(merged)  # construct only — no enter(), no display needed
        except Exception as e:
            failures.append((mode_key, f"{type(e).__name__}: {e}"))
    assert not failures, f"modes failed to construct: {failures}"

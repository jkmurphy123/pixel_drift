# controlpanel/paths.py
#
# One place that knows where control-panel assets live, so skin.py,
# layout.py, the mode wrapper and the placeholder-skin generator all agree.

from pathlib import Path

# controlpanel/ -> project root
BASE_DIR = Path(__file__).resolve().parent.parent

ASSETS_DIR = BASE_DIR / "assets" / "control_panel"
SPRITE_DEFS_FILE = ASSETS_DIR / "sprite_defs.json"
SKINS_DIR = ASSETS_DIR / "skins"
LAYOUTS_DIR = ASSETS_DIR / "layouts"
BACKGROUNDS_DIR = ASSETS_DIR / "backgrounds"


def resolve_under(directory: Path, name_or_path: str, suffix: str = "") -> Path:
    """
    Resolve a config value to a real file.

    Bare names (e.g. "placeholder" or "demo_console") resolve under the
    given asset directory; absolute/relative paths with a separator are
    used as-is so per-host overrides via modes_config.local.json can point
    anywhere.
    """
    p = Path(name_or_path)
    if p.is_absolute() or p.parent != Path("."):
        return p
    return directory / f"{name_or_path}{suffix}"

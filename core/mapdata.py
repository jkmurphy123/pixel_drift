# core/mapdata.py
#
# Shared loader for the bundled Natural Earth 110m world coastline data
# (data/world_coastline_110m.json, public domain). Used by any mode that
# draws a world map (mission control, satellite tracker, ...).
#
# The file is resolved relative to this module so modes work regardless of
# the process working directory, and cached at module level so repeated
# mode switches never re-read disk.

import json
import os

_COASTLINE_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "world_coastline_110m.json")
)

_cache = None
_failed = False


def load_coastlines(path=_COASTLINE_FILE):
    """
    Return the coastline polylines as a list of [[lon, lat], ...] lists,
    or None if the bundled data file is missing/corrupt (callers should
    draw a fallback in that case).
    """
    global _cache, _failed
    if _cache is not None or _failed:
        return _cache
    try:
        with open(path, "r") as f:
            data = json.load(f)
        lines = data.get("lines")
        if isinstance(lines, list) and lines:
            _cache = lines
        else:
            _failed = True
    except Exception as e:
        print(f"[MapData] coastline data unavailable ({e})")
        _failed = True
    return _cache

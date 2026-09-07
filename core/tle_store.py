# core/tle_store.py
#
# TLE (Two-Line Element set) fetching and disk caching for the satellite
# tracker mode.
#
# Data source: CelesTrak (https://celestrak.org) — free, no API key.
# CelesTrak asks clients not to poll a file more often than ~2 hours, so
# each catalog group is cached to disk and refreshed at most every
# `max_age_hours`. If the network is down we happily run on stale cache
# (TLEs degrade gracefully over days) and report the age to the caller.
#
# Note: CelesTrak rejects urllib's TLS fingerprint (HTTP 500) but accepts
# requests and curl — use `requests` here.

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php"
USER_AGENT = "pixel-drift/1.0 (kiosk satellite tracker)"


@dataclass
class TLERecord:
    """One satellite's element set plus provenance."""
    name: str
    norad_id: int
    line1: str
    line2: str
    group: str
    fetched_at: float          # epoch seconds of last successful download
    status: str                # "refreshed" | "cached" | "stale"

    @property
    def age_hours(self):
        return max(0.0, (time.time() - self.fetched_at) / 3600.0)


def parse_tle_text(text: str):
    """
    Parse classic 3-line TLE text (name / line1 / line2) into
    {norad_id: (name, line1, line2)}. Tolerates blank lines and also
    accepts 2-line input (name falls back to the catalog number).
    """
    sats = {}
    lines = [ln.rstrip("\r").rstrip() for ln in text.splitlines() if ln.strip()]
    i = 0
    while i < len(lines):
        if lines[i].startswith("1 ") and i + 1 < len(lines) and lines[i + 1].startswith("2 "):
            norad = int(lines[i][2:7])
            sats[norad] = (str(norad), lines[i], lines[i + 1])
            i += 2
        elif i + 2 < len(lines) and lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
            norad = int(lines[i + 1][2:7])
            sats[norad] = (lines[i].strip(), lines[i + 1], lines[i + 2])
            i += 3
        else:
            i += 1
    return sats


def _default_fetch(group: str, timeout: float) -> str:
    import requests  # imported lazily so offline tests never need it
    r = requests.get(
        CELESTRAK_URL,
        params={"GROUP": group, "FORMAT": "tle"},
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.text


class TLEStore:
    """
    Disk-cached TLE source.

    fetcher(group, timeout) -> TLE text is injectable for tests; the default
    hits CelesTrak via requests.
    """

    def __init__(self, cache_dir, max_age_hours=24, fetch_timeout=8, fetcher=None):
        self.cache_dir = Path(cache_dir)
        self.max_age_hours = float(max_age_hours)
        self.fetch_timeout = float(fetch_timeout)
        self._fetch = fetcher or _default_fetch
        self._groups = {}  # group -> (parse dict, meta) once loaded

    # ----- internals -----------------------------------------------------

    def _cache_path(self, group):
        return self.cache_dir / f"{group}.tle"

    def _meta_path(self, group):
        return self.cache_dir / f"{group}.meta.json"

    def _read_cache(self, group):
        """Return (sats_dict, fetched_at) from disk, or None."""
        try:
            text = self._cache_path(group).read_text()
            meta = json.loads(self._meta_path(group).read_text())
            sats = parse_tle_text(text)
            if not sats:
                return None
            return sats, float(meta.get("fetched_at", 0.0))
        except Exception:
            return None

    def _write_cache(self, group, text, fetched_at):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path(group).write_text(text)
        self._meta_path(group).write_text(json.dumps({
            "fetched_at": fetched_at,
            "url": f"{CELESTRAK_URL}?GROUP={group}&FORMAT=tle",
        }))

    def _load_group(self, group):
        """
        Return (sats_dict, fetched_at, status) where status is
        "refreshed" | "cached" | "stale" | "unavailable".
        """
        if group in self._groups:
            return self._groups[group]

        cached = self._read_cache(group)
        fresh_enough = (
            cached is not None
            and (time.time() - cached[1]) / 3600.0 <= self.max_age_hours
        )

        if fresh_enough and cached is not None:
            result = (cached[0], cached[1], "cached")
        else:
            # Cache missing or too old — try the network (bounded timeout).
            try:
                text = self._fetch(group, self.fetch_timeout)
                sats = parse_tle_text(text)
                if not sats:
                    raise ValueError("no TLEs in response")
                fetched_at = time.time()
                self._write_cache(group, text, fetched_at)
                result = (sats, fetched_at, "refreshed")
            except Exception as e:
                print(f"[TLE] fetch failed for group '{group}' ({type(e).__name__}: {e})")
                if cached:
                    result = (cached[0], cached[1], "stale")
                else:
                    result = ({}, 0.0, "unavailable")

        self._groups[group] = result
        return result

    # ----- public API ----------------------------------------------------

    def get_satellite(self, group: str, norad_id: int):
        """
        Look up one satellite. Returns a TLERecord, or None if the group
        could not be loaded at all or the NORAD id is not in it.
        """
        sats, fetched_at, status = self._load_group(group)
        entry = sats.get(int(norad_id))
        if entry is None:
            return None
        name, l1, l2 = entry
        return TLERecord(
            name=name, norad_id=int(norad_id), line1=l1, line2=l2,
            group=group, fetched_at=fetched_at, status=status,
        )

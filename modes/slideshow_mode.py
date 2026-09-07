# modes/slideshow_mode.py

import os
import random
import time
import json
import threading
import urllib.parse
import urllib.request
from collections import OrderedDict

import pygame

class _LRU:
    def __init__(self, max_items=3):
        self.max_items = max_items
        self.d = OrderedDict()

    def get(self, k):
        if k in self.d:
            self.d.move_to_end(k)
            return self.d[k]
        return None

    def put(self, k, v):
        self.d[k] = v
        self.d.move_to_end(k)
        while len(self.d) > self.max_items:
            _, old = self.d.popitem(last=False)
            del old

class SlideshowMode:
    """
    Scene-style fullscreen slideshow.

    Config:
      - folder (required)
      - duration (required) seconds per image
      - name (optional)
      - scale_mode (optional): "cover" (default) or "contain"

      Overlays (all optional; shown in LOWER-LEFT and rotated each image change):
      - show_time: true/false
      - show_date: true/false
      - show_weather: true/false
          - weather_location: str (e.g. "Pittsburgh, PA")
          - weather_units: "imperial" (default) or "metric"
      - show_crypto: true/false
          - crypto_ids: list[str] (default: ["bitcoin","ethereum","tether"])
      - show_dow: true/false
          - dow_symbol: str (default: "^DJI")

      Text styling:
      - font_size (optional): int, pixels
      - overlay_margin (optional): int, pixels

      Refresh tuning:
      - overlay_update_seconds_weather (optional): int (default 600)
      - overlay_update_seconds_markets (optional): int (default 120)
    """

    def __init__(self, config: dict):
        self.folder = config.get("folder", ".")
        self.duration = float(config.get("duration", 10))
        self.name = config.get("name", "Slideshow")
        self.scale_mode = str(config.get("scale_mode", "cover")).lower()

        self._scaled_cache = _LRU(max_items=int(config.get("scaled_cache_items", 2)))

        self.manager = None
        self.screen_size = (0, 0)

        self.images = []
        self.current_path = None
        self.current_surface = None

        self._image_index = 0

        # ---- overlay controls ----
        self.show_time = bool(config.get("show_time", False))
        self.show_date = bool(config.get("show_date", False))
        self.show_weather = bool(config.get("show_weather", False))
        self.show_crypto = bool(config.get("show_crypto", False))
        self.show_dow = bool(config.get("show_dow", False))

        self.overlay_font_path = config.get(
            "overlay_font_path",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        )
        self.font_size = int(config.get("font_size", 28))
        self.overlay_font_size = int(config.get("overlay_font_size", self.font_size))
        self.overlay_margin = int(config.get("overlay_margin", 12))

        self.weather_location = str(config.get("weather_location", "New York, NY"))
        self.weather_units = str(config.get("weather_units", "imperial")).lower().strip()

        crypto_ids = config.get("crypto_ids", ["bitcoin", "ethereum", "tether"])
        self.crypto_ids = list(crypto_ids) if isinstance(crypto_ids, (list, tuple)) else ["bitcoin", "ethereum", "tether"]

        self.dow_symbol = str(config.get("dow_symbol", "^DJI"))

        self.overlay_update_seconds_weather = int(config.get("overlay_update_seconds_weather", 600))
        self.overlay_update_seconds_markets = int(config.get("overlay_update_seconds_markets", 120))

        # rotation state
        self._overlay_keys = []
        self._overlay_index = 0
        self._current_overlay_key = None
        self._current_overlay_text = None

        # simple network/cache state
        self._geo_cache = {}  # location_str -> dict(lat=..., lon=..., name=..., country=..., cached_at=...)
        self._weather_cache = {"text": None, "fetched_at": 0.0, "error_until": 0.0}
        self._crypto_cache = {"text": None, "fetched_at": 0.0, "error_until": 0.0}
        self._dow_cache = {"text": None, "fetched_at": 0.0, "error_until": 0.0}

        # Background network refresher. All HTTP happens on this thread so a
        # slow/hung request can never stall the pygame frame loop. The render
        # path only ever reads the caches above (dict assignment is atomic
        # under the GIL, so no lock is needed for this simple shape).
        self._net_stop = threading.Event()
        self._net_thread = None

        self._next_swap_at = 0.0

    # ---------- lifecycle ----------

    def enter(self, manager):
        self.manager = manager
        self.screen_size = manager.screen.get_size()
        self.images = self._load_image_list()
        random.shuffle(self.images)
        self._image_index = 0

        self.current_path = None
        self.current_surface = None

        self._next_swap_at = time.time()

        # build enabled overlay list
        self._rebuild_overlay_keys()
        self._overlay_index = 0
        self._current_overlay_key = None
        self._current_overlay_text = None

        # kick off background network refreshes (weather/crypto/dow)
        self._net_stop.clear()
        if self.show_weather or self.show_crypto or self.show_dow:
            self._net_thread = threading.Thread(
                target=self._network_worker, daemon=True, name="slideshow-net"
            )
            self._net_thread.start()

    def exit(self):
        # Stop the network worker before dropping state
        self._net_stop.set()
        if self._net_thread is not None:
            self._net_thread.join(timeout=1.0)
            self._net_thread = None

        # Drop references so Surfaces can be freed when cache clears
        self.current_surface = None
        self.current_path = None
        self.images = []
        self.manager = None

    def handle_event(self, event):
        pass

    def update(self, dt: float):
        if not self.images:
            return

        now = time.time()
        if self.current_surface is None or now >= self._next_swap_at:
            self.current_path = self.images[self._image_index]
            self._image_index = (self._image_index + 1) % len(self.images)

            # Drop the old surface reference before replacing it
            if self.current_surface is not None:
                old = self.current_surface
                self.current_surface = None
                del old

            self.current_surface = self._load_and_scale(self.current_path, self.screen_size)
            self._next_swap_at = now + self.duration

            self._advance_overlay(now)


    def render(self, screen: pygame.Surface):
            screen.fill((0, 0, 0))

            if not self.images:
                # ... (keep existing no-image logic)
                return

            if self.current_surface:
                rect = self.current_surface.get_rect(center=screen.get_rect().center)
                screen.blit(self.current_surface, rect)

            # 1. New: Dedicated centered time at the top
            if self.show_time:
                self._draw_centered_time(screen)

            # 2. Existing: Rotating corner overlays (Date, Weather, etc.)
            if self._current_overlay_text:
                self._draw_overlay_lower_left(screen, self._current_overlay_text)

    # ---------- overlay rotation ----------

    def _rebuild_overlay_keys(self):
        keys = []
        if self.show_date:
            keys.append("date")
        if self.show_weather:
            keys.append("weather")
        if self.show_crypto:
            keys.append("crypto")
        if self.show_dow:
            keys.append("dow")
        self._overlay_keys = keys

    def _advance_overlay(self, now: float):
        if not self._overlay_keys:
            self._current_overlay_key = None
            self._current_overlay_text = None
            return

        self._current_overlay_key = self._overlay_keys[self._overlay_index % len(self._overlay_keys)]
        self._overlay_index = (self._overlay_index + 1) % len(self._overlay_keys)

        # compute / refresh the displayed text
        self._current_overlay_text = self._get_overlay_text(self._current_overlay_key, now)

    def _get_overlay_text(self, key: str, now: float) -> str | None:
        if key == "time":
            return self._format_time()
        if key == "date":
            return self._format_date()

        # Network-backed overlays: read the cache only. Fetching happens on
        # the background worker — never on the frame loop.
        if key == "weather":
            return self._cached_net_text(self._weather_cache, "weather", now)
        if key == "crypto":
            return self._cached_net_text(self._crypto_cache, "crypto", now)
        if key == "dow":
            return self._cached_net_text(self._dow_cache, "dow", now)

        return None

    def _cached_net_text(self, cache: dict, label: str, now: float) -> str | None:
        if cache.get("text"):
            return cache["text"]
        if now < cache.get("error_until", 0.0):
            return f"NETWORK TROUBLE ({label})"
        return None  # first fetch still in flight; skip overlay this round

    # ---------- background network worker ----------

    def _network_worker(self):
        """
        Loop forever (until exit()) refreshing stale network caches.
        The _get_*_text getters self-throttle via fetched_at / error_until,
        so calling them on a short cadence is cheap.
        """
        while not self._net_stop.is_set():
            now = time.time()
            try:
                if self.show_weather:
                    self._get_weather_text(now)
                if self.show_crypto:
                    self._get_crypto_text(now)
                if self.show_dow:
                    self._get_dow_text(now)
            except Exception as e:
                # Getters already swallow their own errors; this is a last resort.
                print(f"[SlideshowMode] network worker error: {e}")
            # Wake once a second, but stay responsive to exit()
            self._net_stop.wait(1.0)

    # ---------- overlay content formatters ----------

    def _draw_centered_time(self, screen: pygame.Surface):
            # We use a larger font size for the centered clock if desired
            clock_font = self.manager.cache.get_font(
                self.overlay_font_path,
                int(self.font_size), # Slightly larger than corner text
                bold=True
            )
            
            time_str = self._format_time()
            
            # Render text with shadow
            surf = clock_font.render(time_str, True, (240, 240, 240))
            shadow = clock_font.render(time_str, True, (0, 0, 0))
            
            # Position: Centered horizontally, Margin distance from top
            x = screen.get_width() // 2
            y = self.overlay_margin + (surf.get_height() // 2)
            
            rect = surf.get_rect(center=(x, y))
            shadow_rect = rect.move(2, 2)
            
            screen.blit(shadow, shadow_rect)
            screen.blit(surf, rect)

    def _format_time(self) -> str:
        # Linux supports %-I; keep a fallback just in case.
        try:
            return time.strftime("%-I:%M %p")
        except Exception:
            s = time.strftime("%I:%M %p")
            return s[1:] if s.startswith("0") else s

    def _format_date(self) -> str:
        # "Wednesday, July 31"
        try:
            s = time.strftime("%A, %B %-d")
            return s
        except Exception:
            s = time.strftime("%A, %B %d")
            # strip leading zero from day
            parts = s.rsplit(" ", 1)
            if len(parts) == 2:
                return parts[0] + " " + parts[1].lstrip("0")
            return s

    # ---------- network helpers ----------

    def _http_get_json(self, url: str, timeout: float = 2.5) -> dict:
        req = urllib.request.Request(
            url,
            headers={
                # Some public endpoints are happier if you look like a browser.
                "User-Agent": "RotaryMode/1.0 (+pygame; slideshow overlay)",
                "Accept": "application/json",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        return json.loads(data.decode("utf-8"))

    def _http_get_text(self, url: str, timeout: float = 2.5) -> str:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "RotaryMode/1.0 (+pygame; slideshow overlay)"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        return data.decode("utf-8", errors="replace")

    # ---------- weather (Open-Meteo) ----------

    def _geocode_location(self, location: str) -> dict | None:
        loc_key = location.strip()
        if not loc_key:
            return None

        cached = self._geo_cache.get(loc_key)
        if cached and (time.time() - cached.get("cached_at", 0.0) < 24 * 3600):
            return cached

        q = urllib.parse.quote(loc_key)
        url = f"https://geocoding-api.open-meteo.com/v1/search?name={q}&count=1&language=en&format=json"
        data = self._http_get_json(url)

        results = data.get("results") or []
        if not results:
            return None

        r = results[0]
        out = {
            "lat": r.get("latitude"),
            "lon": r.get("longitude"),
            "name": r.get("name"),
            "admin1": r.get("admin1"),
            "country": r.get("country"),
            "cached_at": time.time(),
        }
        self._geo_cache[loc_key] = out
        return out

    def _weather_code_desc(self, code: int) -> str:
        # Open-Meteo weather codes (abridged but useful)
        table = {
            0: "Clear",
            1: "Mainly clear",
            2: "Partly cloudy",
            3: "Overcast",
            45: "Fog",
            48: "Rime fog",
            51: "Light drizzle",
            53: "Drizzle",
            55: "Heavy drizzle",
            56: "Freezing drizzle",
            57: "Freezing drizzle",
            61: "Light rain",
            63: "Rain",
            65: "Heavy rain",
            66: "Freezing rain",
            67: "Freezing rain",
            71: "Light snow",
            73: "Snow",
            75: "Heavy snow",
            77: "Snow grains",
            80: "Rain showers",
            81: "Rain showers",
            82: "Violent showers",
            85: "Snow showers",
            86: "Snow showers",
            95: "Thunderstorm",
            96: "Thunderstorm hail",
            99: "Thunderstorm hail",
        }
        return table.get(code, f"WX {code}")

    def _get_weather_text(self, now: float) -> str:
        cache = self._weather_cache

        # If we recently failed, show "NETWORK TROUBLE" for a bit.
        if now < cache.get("error_until", 0.0):
            return "NETWORK TROUBLE (weather)"

        # Serve from cache if fresh
        if cache.get("text") and (now - cache.get("fetched_at", 0.0) < self.overlay_update_seconds_weather):
            return cache["text"]

        try:
            loc = self._geocode_location(self.weather_location)
            if not loc or loc.get("lat") is None or loc.get("lon") is None:
                cache["text"] = f"Weather: can't find '{self.weather_location}'"
                cache["fetched_at"] = now
                return cache["text"]

            lat = loc["lat"]
            lon = loc["lon"]

            temp_unit = "fahrenheit" if self.weather_units == "imperial" else "celsius"
            wind_unit = "mph" if self.weather_units == "imperial" else "kmh"

            url = (
                "https://api.open-meteo.com/v1/forecast"
                f"?latitude={lat}&longitude={lon}"
                "&current_weather=true"
                f"&temperature_unit={temp_unit}"
                f"&windspeed_unit={wind_unit}"
                "&timezone=auto"
            )

            data = self._http_get_json(url)
            cw = data.get("current_weather") or {}

            t = cw.get("temperature")
            w = cw.get("windspeed")
            code = cw.get("weathercode")

            place_bits = [loc.get("name")]
            if loc.get("admin1"):
                place_bits.append(loc.get("admin1"))
            place = ", ".join([b for b in place_bits if b])

            desc = self._weather_code_desc(int(code)) if code is not None else "Weather"
            deg = "°F" if self.weather_units == "imperial" else "°C"
            wind = "mph" if self.weather_units == "imperial" else "km/h"

            if t is None:
                text = f"{desc}"
            else:
                # Keep it compact. This is a corner whisper, not a meteorology dissertation.
                if w is None:
                    text = f"{int(round(t))}{deg} \n{desc}"
                else:
                    text = f"{int(round(t))}{deg} \n{desc} \nWind {int(round(w))} {wind}"

            cache["text"] = text
            cache["fetched_at"] = now
            return text

        except Exception:
            cache["error_until"] = now + 15.0
            return "NETWORK TROUBLE (weather)"

    # ---------- crypto (CoinGecko) ----------

    def _get_crypto_text(self, now: float) -> str:
        cache = self._crypto_cache

        if now < cache.get("error_until", 0.0):
            return "NETWORK TROUBLE (crypto)"

        if cache.get("text") and (now - cache.get("fetched_at", 0.0) < self.overlay_update_seconds_markets):
            return cache["text"]

        try:
            ids = [c.strip() for c in self.crypto_ids if str(c).strip()]
            if not ids:
                ids = ["bitcoin", "ethereum", "tether"]

            ids_q = urllib.parse.quote(",".join(ids))
            url = (
                "https://api.coingecko.com/api/v3/simple/price"
                f"?ids={ids_q}&vs_currencies=usd&include_24hr_change=true"
            )
            data = self._http_get_json(url)

            # map some common ids to nicer tickers
            pretty = {
                "bitcoin": "BTC",
                "ethereum": "ETH",
                "tether": "USDT",
                "solana": "SOL",
                "ripple": "XRP",
                "cardano": "ADA",
                "dogecoin": "DOGE",
            }

            parts = []
            for cid in ids[:3]:
                row = data.get(cid) or {}
                price = row.get("usd")
                chg = row.get("usd_24h_change")

                sym = pretty.get(cid, cid.upper()[:6])
                if price is None:
                    parts.append(f"{sym} ?")
                    continue

                # arrows for up/down
                arrow = "▲" if (chg is not None and chg > 0) else ("▼" if (chg is not None and chg < 0) else "•")

                if price >= 1000:
                    price_str = f"${price:,.0f}"
                elif price >= 1:
                    price_str = f"${price:,.2f}"
                else:
                    price_str = f"${price:,.4f}"

                if chg is None:
                    parts.append(f"{sym} {price_str}")
                else:
                    parts.append(f"{sym} {price_str} {arrow}{abs(chg):.2f}%")

            text = "\n".join(parts) if parts else "Crypto: (no data)"

            cache["text"] = text
            cache["fetched_at"] = now
            return text

        except Exception:
            cache["error_until"] = now + 15.0
            return "NETWORK TROUBLE (crypto)"

    # ---------- Dow (Stooq) ----------

    def _get_dow_text(self, now: float) -> str:
        cache = self._dow_cache

        if now < cache.get("error_until", 0.0):
            return "NETWORK TROUBLE (dow)"

        if cache.get("text") and (now - cache.get("fetched_at", 0.0) < self.overlay_update_seconds_markets):
            return cache["text"]

        try:
            symbol = self.dow_symbol or "^DJI"
            sym_q = urllib.parse.quote(symbol)

            url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={sym_q}"
            data = self._http_get_json(url)

            result = data["quoteResponse"]["result"]
            if not result:
                raise ValueError("No DJI data")

            q = result[0]

            price = q.get("regularMarketPrice")
            change = q.get("regularMarketChange")
            pct = q.get("regularMarketChangePercent")

            if price is None:
                raise ValueError("Missing price")

            arrow = "▲" if change and change > 0 else ("▼" if change and change < 0 else "•")

            if pct is not None:
                text = f"DJI {price:,.2f} {arrow}{abs(pct):.2f}%"
            else:
                text = f"DJI {price:,.2f}"

            cache["text"] = text
            cache["fetched_at"] = now
            return text

        except Exception:
            cache["error_until"] = now + 15.0
            return "NETWORK TROUBLE (dow)"

    # ---------- drawing ----------

    def _draw_overlay_lower_left(self, screen: pygame.Surface, text: str):
        font = self.manager.cache.get_font(
            self.overlay_font_path,
            self.overlay_font_size,
            bold=True
        )

        lines = text.splitlines()
        line_height = font.get_linesize()

        x = self.overlay_margin
        y = screen.get_height() - self.overlay_margin

        # draw from bottom upward so it hugs the corner nicely
        for line in reversed(lines):
            surf = font.render(line, True, (240, 240, 240))
            rect = surf.get_rect(bottomleft=(x, y))

            shadow = font.render(line, True, (0, 0, 0))
            shadow_rect = rect.move(2, 2)

            screen.blit(shadow, shadow_rect)
            screen.blit(surf, rect)

            y -= line_height


    # ---------- image helpers ----------

    def _load_image_list(self):
        if not os.path.isdir(self.folder):
            print(f"[SlideshowMode] folder does not exist: {self.folder}")
            return []

        exts = (".png", ".jpg", ".jpeg", ".bmp", ".gif")
        files = [
            os.path.join(self.folder, f)
            for f in os.listdir(self.folder)
            if f.lower().endswith(exts)
        ]
        files.sort()
        print(f"[SlideshowMode] found {len(files)} image(s) in {self.folder}")
        return files

    def _load_and_scale(self, path, target_size):
        tw, th = target_size

        try:
            img = pygame.image.load(path)

            # Prefer convert() unless you truly need alpha (most JPGs don't).
            # If you have PNGs with transparency that matters, use convert_alpha().
            if path.lower().endswith(".png"):
                img = img.convert_alpha()
            else:
                img = img.convert()

            iw, ih = img.get_width(), img.get_height()
            if iw <= 0 or ih <= 0:
                return None

            if self.scale_mode == "contain":
                scale = min(tw / iw, th / ih)
            else:
                scale = max(tw / iw, th / ih)

            nw = max(1, int(iw * scale))
            nh = max(1, int(ih * scale))

            scaled = pygame.transform.smoothscale(img, (nw, nh))
            del img  # drop original ASAP

            if self.scale_mode == "cover":
                # For cover, use opaque surface unless you truly need alpha
                out = pygame.Surface((tw, th))
                out.fill((0, 0, 0))
                src_rect = scaled.get_rect(center=(tw // 2, th // 2))
                out.blit(scaled, (0, 0), area=src_rect)
                del scaled
                return out

            return scaled

        except Exception as e:
            print(f"[SlideshowMode] Failed to load image '{path}': {e}")
            return None


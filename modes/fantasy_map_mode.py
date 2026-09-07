# modes/fantasy_map_mode.py
"""
Fantasy Map Generator Mode -- procedurally generates an RPG-style outdoor map
with terrain, rivers, roads, and named settlements.

Phase 1: Colored block rendering.  Bitmap feature stamps planned for Phase 2.

Algorithm: Fractal Brownian Motion (fBm) over Simplex noise → heightmap +
moisture map → terrain classification → river tracing → settlement placement
→ road network.

Config (all optional):
  - seed (int):            Reproducible map seed (default: random)
  - map_size (int):        Internal heightmap resolution (default: 256)
  - water_level (float):   Sea-level threshold 0-1 (default: 0.40)
  - mountain_level (float): Mountain threshold     (default: 0.72)
  - hill_level (float):    Hill threshold          (default: 0.58)
  - num_rivers (int):      River seed points       (default: 18)
  - num_settlements (int): Cities/villages to place (default: 14)
  - regeneration_interval_sec (float): Auto-regen interval; 0 = never (default: 45)
  - show_labels (bool):    Render settlement names  (default: True)
  - show_rivers (bool):    Render rivers            (default: True)
  - show_roads (bool):     Render roads             (default: True)
  - terrain_colors (dict): Override terrain palette
  - border_color (list):   RGB for parchment border
  - title (str):           Override title; empty = auto-generated
"""

import math
import random
from collections import defaultdict

import pygame

# ═══════════════════════════════════════════════════════════════
# Pure-Python 2D Simplex Noise
# ═══════════════════════════════════════════════════════════════

# Skew / unskew factors for 2D simplex
_F2 = 0.5 * (math.sqrt(3.0) - 1.0)
_G2 = (3.0 - math.sqrt(3.0)) / 6.0

# Gradient vectors (12 directions)
_GRAD2 = [
    (1, 0), (-1, 0), (0, 1), (0, -1),
    (1, 1), (-1, 1), (1, -1), (-1, -1),
    (1, 2), (-1, 2), (1, -2), (-1, -2),
]


class SimplexNoise2D:
    """Compact 2D Simplex noise in pure Python — no native deps."""

    def __init__(self, seed: int = 0):
        rng = random.Random(seed)
        # Build a permutation table of size 256 and double it for easy wrapping
        p = list(range(256))
        rng.shuffle(p)
        self._perm = p + p  # 512 elements

    def _hash(self, i: int) -> int:
        return self._perm[i & 255]

    def _dot2(self, g_idx: int, x: float, y: float) -> float:
        gx, gy = _GRAD2[g_idx % 12]
        return gx * x + gy * y

    def noise2d(self, x: float, y: float) -> float:
        """Return simplex noise value in [-1, 1] for point (x, y)."""
        # Skew input space to simplex grid
        s = (x + y) * _F2
        i = int(math.floor(x + s))
        j = int(math.floor(y + s))
        t = (i + j) * _G2
        x0 = x - (i - t)
        y0 = y - (j - t)

        # Determine which simplex we are in
        if x0 > y0:
            i1, j1 = 1, 0
        else:
            i1, j1 = 0, 1

        x1 = x0 - i1 + _G2
        y1 = y0 - j1 + _G2
        x2 = x0 - 1.0 + 2.0 * _G2
        y2 = y0 - 1.0 + 2.0 * _G2

        # Hash corners
        ii = i & 255
        jj = j & 255
        gi0 = self._perm[ii + self._perm[jj]] % 12
        gi1 = self._perm[ii + i1 + self._perm[jj + j1]] % 12
        gi2 = self._perm[ii + 1 + self._perm[jj + 1]] % 12

        # Contributions
        n0 = n1 = n2 = 0.0

        t0 = 0.5 - x0 * x0 - y0 * y0
        if t0 > 0:
            t0 *= t0
            n0 = t0 * t0 * self._dot2(gi0, x0, y0)

        t1 = 0.5 - x1 * x1 - y1 * y1
        if t1 > 0:
            t1 *= t1
            n1 = t1 * t1 * self._dot2(gi1, x1, y1)

        t2 = 0.5 - x2 * x2 - y2 * y2
        if t2 > 0:
            t2 *= t2
            n2 = t2 * t2 * self._dot2(gi2, x2, y2)

        # Scale to approximately [-1, 1]
        return 70.0 * (n0 + n1 + n2)

    def fbm(self, x: float, y: float, octaves: int = 6,
            lacunarity: float = 2.0, gain: float = 0.5) -> float:
        """Fractal Brownian Motion — layered octaves of noise."""
        value = 0.0
        amplitude = 1.0
        frequency = 1.0
        max_value = 0.0

        for _ in range(octaves):
            value += amplitude * self.noise2d(x * frequency, y * frequency)
            max_value += amplitude
            amplitude *= gain
            frequency *= lacunarity

        return value / max_value  # Normalise to approx [-1, 1]


# ═══════════════════════════════════════════════════════════════
# Fantasy name generator
# ═══════════════════════════════════════════════════════════════

_PREFIXES = [
    "Nor", "East", "West", "South", "Kings", "Iron", "Shadow", "Silver",
    "Gold", "Stone", "Storm", "High", "Deep", "Dark", "White", "Red",
    "Frost", "Thorn", "Ash", "Oak", "Raven", "Wolf", "Star", "Sun",
    "Moon", "Fire", "Wind", "Crystal", "Elder", "Briar", "Mist", "Grim",
    "Bright", "Still", "Cold", "Hollow", "Fair", "Dun", "Far", "Black",
]

_MIDDLES = [
    "", "", "", "", "", "", "",  # 40% chance of no middle
    "en", "ar", "mar", "dal", "tan", "rel", "nor", "car",
    "mel", "rin", "fal", "gar",
]

_SUFFIXES = [
    "haven", "dale", "watch", "fell", "moor", "bridge", "crest",
    "ford", "shire", "burg", "wick", "stead", "helm", "mere",
    "gate", "hollow", "rest", "vale", "mark", "hold", "keep",
    "wall", "field", "wood", "glen", "cairn", "cross", "port",
    "water", "reach", "land", "march",
]

_REGION_NAMES = [
    "Kingdom", "March", "Valley", "Realm", "Wilds", "Fells",
    "Moors", "Shires", "Wolds", "Dales", "Lands", "Reach",
    "Expanse", "Dominion", "Province",
]


def _make_place_name(rng: random.Random) -> str:
    pref = rng.choice(_PREFIXES)
    mid = rng.choice(_MIDDLES)
    suff = rng.choice(_SUFFIXES)
    return pref + mid + suff


def _make_map_name(rng: random.Random) -> str:
    place = _make_place_name(rng)
    region = rng.choice(_REGION_NAMES)
    pattern = rng.choice([
        f"The {place} {region}",
        f"The {region} of {place}",
        f"{place} {region}",
    ])
    return pattern


# ═══════════════════════════════════════════════════════════════
# Terrain constants
# ═══════════════════════════════════════════════════════════════

DEEP_WATER = 0
SHALLOW_WATER = 1
BEACH = 2
GRASSLAND = 3
FOREST = 4
DESERT = 5
HILLS = 6
MOUNTAINS = 7
SNOW_PEAK = 8

DEFAULT_COLORS = {
    DEEP_WATER: (20, 40, 110),
    SHALLOW_WATER: (40, 70, 150),
    BEACH: (210, 195, 150),
    GRASSLAND: (100, 155, 80),
    FOREST: (40, 100, 35),
    DESERT: (200, 180, 120),
    HILLS: (130, 120, 90),
    MOUNTAINS: (110, 105, 95),
    SNOW_PEAK: (230, 230, 235),
}

# ═══════════════════════════════════════════════════════════════
# Map Generator
# ═══════════════════════════════════════════════════════════════


class MapGenerator:
    """Full procedural fantasy-map pipeline."""

    def __init__(self, config: dict):
        self.map_size = int(config.get("map_size", 256))
        self.water_level = float(config.get("water_level", 0.40))
        self.mountain_level = float(config.get("mountain_level", 0.72))
        self.hill_level = float(config.get("hill_level", 0.58))
        self.num_rivers = int(config.get("num_rivers", 18))
        self.num_settlements = int(config.get("num_settlements", 14))
        self.show_labels = bool(config.get("show_labels", True))
        self.show_rivers = bool(config.get("show_rivers", True))
        self.show_roads = bool(config.get("show_roads", True))

        # Colour overrides
        raw_colors = config.get("terrain_colors", {})
        self.colors = dict(DEFAULT_COLORS)
        for k_str, rgb in raw_colors.items():
            try:
                self.colors[int(k_str)] = tuple(rgb)
            except (ValueError, KeyError):
                pass

        # Seed
        seed = config.get("seed")
        if seed is None:
            seed = random.randrange(1, 2 ** 31 - 1)
        self.seed = int(seed)
        self._rng = random.Random(self.seed)

        # Noise generators — separate seeds for height, moisture, detail
        self._noise_height = SimplexNoise2D(self._rng.randint(0, 2 ** 30))
        self._noise_moisture = SimplexNoise2D(self._rng.randint(0, 2 ** 30))
        self._noise_coast = SimplexNoise2D(self._rng.randint(0, 2 ** 30))

        # Output grid
        self.terrain = None       # 2D list of terrain type ints
        self.heightmap = None     # 2D list of float 0-1
        self.moisture = None      # 2D list of float 0-1
        self.rivers = set()       # set of (x, y) river cells
        self.settlements = []     # list of (name, x, y, is_city)
        self.roads = []           # list of (x1, y1, x2, y2) road segments
        self.road_cells = set()   # set of (x, y) cells on roads

        # Phase 2: high-res rendering
        self.render_scale = int(config.get("render_scale", 4))
        self._features = []       # list of (bitmap_key, x, y) stamp placements
        self._bitmaps = {}        # cached placeholder bitmaps

        # Generated map name
        self.map_name = ""

    # ── generation pipeline ───────────────────────────────────

    def generate(self):
        """Run the full pipeline and produce terrain + features."""
        self._generate_heightmap()
        self._generate_moisture()
        self._classify_terrain()
        self._roughen_coastline()
        if self.show_rivers:
            self._generate_rivers()
        self._place_settlements()
        if self.show_roads:
            self._build_roads()
        self._place_feature_stamps()
        self.map_name = _make_map_name(self._rng)

    # ── heightmap ─────────────────────────────────────────────

    def _generate_heightmap(self):
        """fBm noise → raw heightmap (0-1)."""
        n = self.map_size
        self.heightmap = [[0.0] * n for _ in range(n)]

        # Scale so noise domain covers the map
        scale = 3.0 / n  # roughly 3 "continent" features across the map

        for y in range(n):
            for x in range(n):
                raw = self._noise_height.fbm(x * scale, y * scale,
                                             octaves=6, lacunarity=2.2, gain=0.52)
                # Remap from [-1,1] to [0,1]
                self.heightmap[y][x] = (raw + 1.0) * 0.5

    # ── moisture ──────────────────────────────────────────────

    def _generate_moisture(self):
        """Separate noise field for moisture/wetness."""
        n = self.map_size
        self.moisture = [[0.0] * n for _ in range(n)]
        scale = 2.5 / n

        for y in range(n):
            for x in range(n):
                raw = self._noise_moisture.fbm(x * scale, y * scale,
                                               octaves=5, lacunarity=2.4, gain=0.5)
                self.moisture[y][x] = (raw + 1.0) * 0.5

    # ── terrain classification ────────────────────────────────

    def _classify_terrain(self):
        """Threshold heightmap + moisture → terrain types."""
        n = self.map_size
        self.terrain = [[0] * n for _ in range(n)]

        for y in range(n):
            for x in range(n):
                h = self.heightmap[y][x]
                m = self.moisture[y][x]

                if h < self.water_level - 0.08:
                    t = DEEP_WATER
                elif h < self.water_level:
                    t = SHALLOW_WATER
                elif h < self.water_level + 0.04:
                    t = BEACH
                elif h >= self.mountain_level:
                    t = MOUNTAINS
                elif h >= self.mountain_level - 0.06:
                    t = SNOW_PEAK  # highest peaks
                elif h >= self.hill_level:
                    t = HILLS
                else:
                    # Grassland zone — use moisture for biome
                    if m > 0.65:
                        t = FOREST
                    elif m < 0.28:
                        t = DESERT
                    else:
                        t = GRASSLAND

                self.terrain[y][x] = t

    # ── coastline roughening ──────────────────────────────────

    def _roughen_coastline(self):
        """Add small noise perturbation to the land/water boundary."""
        n = self.map_size
        scale = 15.0 / n
        for y in range(n):
            for x in range(n):
                t = self.terrain[y][x]
                # Only adjust cells near the water boundary
                if t in (BEACH, SHALLOW_WATER):
                    nv = self._noise_coast.noise2d(x * scale, y * scale)
                    h = self.heightmap[y][x]
                    # Shift the effective height slightly
                    adj = h + nv * 0.035
                    if adj < self.water_level:
                        self.terrain[y][x] = SHALLOW_WATER if adj > self.water_level - 0.04 else DEEP_WATER
                    else:
                        self.terrain[y][x] = BEACH if adj < self.water_level + 0.04 else GRASSLAND

    # ── river generation ──────────────────────────────────────

    def _is_water(self, x: int, y: int) -> bool:
        n = self.map_size
        if not (0 <= x < n and 0 <= y < n):
            return True  # off-map = water sink
        return self.terrain[y][x] in (DEEP_WATER, SHALLOW_WATER)

    def _is_land(self, x: int, y: int) -> bool:
        return not self._is_water(x, y)

    def _generate_rivers(self):
        """D8 flow accumulation — rivers form where many upstream cells drain through."""
        n = self.map_size
        self.rivers = set()

        # D8 direction vectors: N, NE, E, SE, S, SW, W, NW
        _D8 = [(0, -1), (1, -1), (1, 0), (1, 1),
               (0, 1), (-1, 1), (-1, 0), (-1, -1)]

        # ---- 1. Compute D8 flow direction for every cell ----
        # flow_dir[y][x] = index into _D8, or -1 for cells with no downhill neighbor
        flow_dir = [[-1] * n for _ in range(n)]

        for y in range(n):
            for x in range(n):
                h = self.heightmap[y][x]
                best_slope = 0.0
                best_d = -1
                for d, (dx, dy) in enumerate(_D8):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < n and 0 <= ny < n:
                        slope = h - self.heightmap[ny][nx]
                        if slope > best_slope:
                            best_slope = slope
                            best_d = d
                if best_slope > 0:
                    flow_dir[y][x] = best_d

        # ---- 2. Compute flow accumulation ----
        # Start with 1 unit per cell (rainfall).  Process from highest to lowest.
        flow_acc = [[1.0] * n for _ in range(n)]

        # Also track a "river count" — only cells that pass a threshold become rivers
        # We use a secondary accumulation that only starts from mountain/hill cells
        flow_from_highland = [[1.0 if self.terrain[y][x] in (HILLS, MOUNTAINS, SNOW_PEAK) else 0.0
                                for x in range(n)] for y in range(n)]

        # Sort cells by elevation (highest first) for topological propagation
        cells = [(self.heightmap[y][x], x, y) for y in range(n) for x in range(n)]
        cells.sort(key=lambda c: c[0], reverse=True)

        for _, x, y in cells:
            d = flow_dir[y][x]
            if d < 0:
                continue
            dx, dy = _D8[d]
            nx, ny = x + dx, y + dy
            if 0 <= nx < n and 0 <= ny < n:
                flow_acc[ny][nx] += flow_acc[y][x]
                flow_from_highland[ny][nx] += flow_from_highland[y][x]

        # ---- 3. Threshold to produce rivers ----
        # num_rivers acts as a density knob: more rivers → lower threshold
        # Base threshold scales with map size
        base_threshold = max(3.0, n * 0.08)  # ~20 at 256px
        # num_rivers of 18 is the "normal" density; adjust relative to that
        density_factor = 18.0 / max(1, self.num_rivers)
        threshold = base_threshold * density_factor

        for y in range(n):
            for x in range(n):
                if flow_from_highland[y][x] >= threshold or flow_acc[y][x] >= threshold * 2.5:
                    # Make rivers wider in flatter terrain (accumulation spreads out)
                    t = self.terrain[y][x]
                    if t not in (DEEP_WATER, SHALLOW_WATER):
                        self.rivers.add((x, y))
                    # Extend river into water cells for a visible delta
                    elif flow_from_highland[y][x] >= threshold * 1.5:
                        self.rivers.add((x, y))

    # ── settlement placement ──────────────────────────────────

    def _place_settlements(self):
        """Score-based settlement placement near water and flat land."""
        n = self.map_size
        self.settlements = []
        if self.num_settlements <= 0:
            return

        # Precompute distance-to-water
        water_dist = self._distance_to_water()

        # Score each land cell
        scores = []
        for y in range(n):
            for x in range(n):
                t = self.terrain[y][x]
                if t in (DEEP_WATER, SHALLOW_WATER, MOUNTAINS, SNOW_PEAK):
                    continue

                # Base score: prefer moderate elevations, near water, flat
                h = self.heightmap[y][x]
                wd = water_dist[y][x]

                # Flatness bonus: difference from neighbors
                flatness = 0.0
                count = 0
                for dx in (-2, 0, 2):
                    for dy in (-2, 0, 2):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < n and 0 <= ny < n:
                            flatness += abs(h - self.heightmap[ny][nx])
                            count += 1
                flatness = 1.0 - (flatness / max(1, count)) * 3.0  # lower diff = flatter = higher score

                water_score = 1.0 / (1.0 + wd * 0.25)  # closer = better
                elev_score = 1.0 - abs(h - 0.52) * 3.0  # prefer moderate elevation
                coast_bonus = 1.5 if t == BEACH else 1.0

                total = water_score * 2.0 + elev_score * 1.5 + flatness * 2.0 + coast_bonus
                total = max(0.0, total)
                scores.append((total, x, y))

        scores.sort(reverse=True)

        # Greedy placement with minimum distance
        placed = []
        min_dist_sq = (n * 0.065) ** 2  # minimum distance between settlements

        for _, sx, sy in scores:
            if len(placed) >= self.num_settlements:
                break
            too_close = False
            for px, py in placed:
                if (sx - px) ** 2 + (sy - py) ** 2 < min_dist_sq:
                    too_close = True
                    break
            if not too_close:
                placed.append((sx, sy))
                name = _make_place_name(self._rng)
                # 20% chance of being a "city" (larger marker)
                is_city = self._rng.random() < 0.2
                self.settlements.append((name, sx, sy, is_city))

    def _distance_to_water(self):
        """BFS-based distance transform to nearest water cell."""
        n = self.map_size
        from collections import deque

        dist = [[-1] * n for _ in range(n)]
        q = deque()

        for y in range(n):
            for x in range(n):
                if self._is_water(x, y):
                    dist[y][x] = 0
                    q.append((x, y))

        while q:
            x, y = q.popleft()
            d = dist[y][x]
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < n and 0 <= ny < n and dist[ny][nx] == -1:
                        dist[ny][nx] = d + 1
                        q.append((nx, ny))

        return dist

    # ── road network ──────────────────────────────────────────

    def _build_roads(self):
        """Connect settlements with roads via minimum spanning tree + extras."""
        if len(self.settlements) < 2:
            return

        n = self.map_size
        nodes = [(sx, sy) for _, sx, sy, _ in self.settlements]

        # Build complete graph with cost = squared distance (water penalty)
        edges = []
        for i in range(len(nodes)):
            x1, y1 = nodes[i]
            for j in range(i + 1, len(nodes)):
                x2, y2 = nodes[j]
                dx = x2 - x1
                dy = y2 - y1
                cost = dx * dx + dy * dy
                # Penalise water crossings by checking midpoint
                mx, my = (x1 + x2) // 2, (y1 + y2) // 2
                if 0 <= mx < n and 0 <= my < n and self._is_water(mx, my):
                    cost *= 100.0
                edges.append((cost, i, j))

        edges.sort()

        # Kruskal's MST
        parent = list(range(len(nodes)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i, j):
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[ri] = rj
                return True
            return False

        mst_edges = []
        for cost, i, j in edges:
            if union(i, j):
                mst_edges.append((i, j))

        # Add a few extra edges for redundancy (~30% more)
        extra_count = max(1, len(nodes) // 3)
        extra = []
        for cost, i, j in edges:
            if (i, j) not in mst_edges and (j, i) not in mst_edges:
                # Only add if both nodes aren't already well-connected
                if len(extra) < extra_count:
                    extra.append((i, j))

        # Collect road cells
        self.roads = []
        self.road_cells = set()
        all_edges = mst_edges + extra

        for i, j in all_edges:
            x1, y1 = nodes[i]
            x2, y2 = nodes[j]
            self.roads.append((x1, y1, x2, y2))
            self._raster_line(x1, y1, x2, y2, self.road_cells, n)

    def _raster_line(self, x1, y1, x2, y2, cell_set, n):
        """Bresenham line rasterization — add cells to set."""
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        sx = 1 if x1 < x2 else -1
        sy = 1 if y1 < y2 else -1
        err = dx - dy
        x, y = x1, y1

        while True:
            if 0 <= x < n and 0 <= y < n:
                cell_set.add((x, y))
            if x == x2 and y == y2:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy

    # ── Phase 2: feature stamps + high-res prerender ─────────────

    _STAMP_SIZES = {
        "mountain": 64, "mountain_small": 40, "snow_peak": 64,
        "forest": 64, "forest_small": 40,
        "tree": 24,
        "village": 32, "city": 48,
    }

    def _get_bitmap(self, key: str) -> pygame.Surface:
        """Return (or generate + cache) a placeholder bitmap for the given key."""
        if key in self._bitmaps:
            return self._bitmaps[key]

        size = self._STAMP_SIZES.get(key, 32)
        surf = pygame.Surface((size, size), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))

        if key == "mountain":
            # Grey triangle with white snow cap
            pts = [(size // 2, 2), (6, size - 6), (size - 6, size - 6)]
            pygame.draw.polygon(surf, (110, 105, 95), pts)
            pygame.draw.polygon(surf, (140, 135, 125), pts, 1)
            # Snow cap
            cap_pts = [(size // 2, 2), (size // 2 - 10, 18), (size // 2 + 10, 18)]
            pygame.draw.polygon(surf, (230, 230, 235), cap_pts)

        elif key == "mountain_small":
            pts = [(size // 2, 2), (4, size - 4), (size - 4, size - 4)]
            pygame.draw.polygon(surf, (120, 115, 105), pts)
            pygame.draw.polygon(surf, (150, 145, 135), pts, 1)

        elif key == "snow_peak":
            # Taller, mostly white
            pts = [(size // 2, 2), (8, size - 6), (size - 8, size - 6)]
            pygame.draw.polygon(surf, (210, 210, 225), pts)
            pts2 = [(size // 2, 2), (size // 2 - 8, 22), (size // 2 + 8, 22)]
            pygame.draw.polygon(surf, (240, 240, 245), pts2)

        elif key in ("forest", "forest_small"):
            # Cluster of overlapping dark green circles
            cx, cy = size // 2, size // 2
            for _ in range(5):
                ox = int((self._rng.random() - 0.5) * size * 0.6)
                oy = int((self._rng.random() - 0.5) * size * 0.5)
                r = max(10, int(size * (0.2 + self._rng.random() * 0.15)))
                shade = 35 + int(self._rng.random() * 30)
                pygame.draw.circle(surf, (shade, 100 + int(self._rng.random() * 30), shade - 5),
                                   (cx + ox, int(cy + oy * 0.8)), r)

        elif key == "tree":
            # Single tree: brown trunk + green canopy
            trunk_w = max(4, size // 6)
            pygame.draw.rect(surf, (90, 60, 30),
                             (size // 2 - trunk_w // 2, size // 2, trunk_w, size // 2))
            pygame.draw.circle(surf, (45, 110, 40), (size // 2, size // 3), size // 3)
            pygame.draw.circle(surf, (55, 125, 50), (size // 2 - 4, size // 3 + 2), size // 4)

        elif key == "village":
            # Small cluster of huts
            for _ in range(4):
                hx = int(self._rng.random() * size * 0.7) + 4
                hy = int(self._rng.random() * size * 0.5) + 4
                hw, hh = size // 6, size // 5
                # walls
                pygame.draw.rect(surf, (180, 150, 110), (hx, hy + hh // 2, hw, hh // 2))
                # roof
                roof_pts = [(hx - 2, hy + hh // 2), (hx + hw // 2, hy - 2), (hx + hw + 2, hy + hh // 2)]
                pygame.draw.polygon(surf, (140, 80, 40), roof_pts)

        elif key == "city":
            # Walled town with central keep
            # Walls
            pygame.draw.rect(surf, (150, 140, 120),
                             (4, size // 3, size - 8, size * 2 // 3 - 4), 2)
            # Buildings
            for _ in range(8):
                bx = int(self._rng.random() * (size - 16)) + 8
                by = int(self._rng.random() * size * 0.4) + size // 3 + 4
                bw, bh = size // 8, size // 6
                pygame.draw.rect(surf, (180, 160, 130), (bx, by, bw, bh))
                pygame.draw.polygon(surf, (130, 70, 30),
                                    [(bx - 2, by), (bx + bw // 2, by - bh // 2), (bx + bw + 2, by)])
            # Keep (center tower)
            keep_w = size // 4
            pygame.draw.rect(surf, (170, 155, 130),
                             (size // 2 - keep_w // 2, size // 5, keep_w, size // 3))
            keep_roof = [(size // 2 - keep_w // 2 - 3, size // 5),
                         (size // 2, size // 10), (size // 2 + keep_w // 2 + 3, size // 5)]
            pygame.draw.polygon(surf, (120, 60, 25), keep_roof)

        self._bitmaps[key] = surf
        return surf

    def _place_feature_stamps(self):
        """Place bitmap stamps across the terrain with spacing constraints."""
        n = self.map_size
        self._features = []
        rs = self.render_scale

        # ── Mountains: place on mountain and snow-peak cells ──
        min_dist = max(6, n // 30)  # cells
        min_dist_sq = min_dist ** 2
        placed_mtn = []
        mountain_cells = [(x, y) for y in range(n) for x in range(n)
                          if self.terrain[y][x] in (MOUNTAINS, SNOW_PEAK)]
        self._rng.shuffle(mountain_cells)

        for x, y in mountain_cells:
            # Check spacing
            too_close = any((x - px) ** 2 + (y - py) ** 2 < min_dist_sq for px, py in placed_mtn)
            if too_close:
                continue
            placed_mtn.append((x, y))
            t = self.terrain[y][x]
            key = "snow_peak" if t == SNOW_PEAK and self._rng.random() < 0.6 else "mountain"
            if self._rng.random() < 0.3:
                key = "mountain_small"
            # Stamp at cell center, minus half bitmap size in render coords
            bx = int(x * rs + rs / 2 - self._STAMP_SIZES[key] / 2)
            by = int(y * rs + rs / 2 - self._STAMP_SIZES[key] / 2)
            self._features.append((key, bx, by))

        # ── Forests: place forest clusters on forest cells ──
        min_dist_forest = max(8, n // 20)
        min_df_sq = min_dist_forest ** 2
        placed_for = []
        forest_cells = [(x, y) for y in range(n) for x in range(n)
                        if self.terrain[y][x] == FOREST]
        self._rng.shuffle(forest_cells)

        for x, y in forest_cells:
            too_close = any((x - px) ** 2 + (y - py) ** 2 < min_df_sq for px, py in placed_for)
            if too_close:
                continue
            placed_for.append((x, y))
            key = "forest" if self._rng.random() < 0.7 else "forest_small"
            bx = int(x * rs + rs / 2 - self._STAMP_SIZES[key] / 2)
            by = int(y * rs + rs / 2 - self._STAMP_SIZES[key] / 2)
            self._features.append((key, bx, by))

        # ── Scattered trees: in grassland near forest edges ──
        tree_min_dist = max(4, n // 40)
        tmd_sq = tree_min_dist ** 2
        placed_trees = []
        # Find grassland cells within 3 cells of forest
        near_forest = set()
        for y in range(n):
            for x in range(n):
                if self.terrain[y][x] == GRASSLAND:
                    for dx in range(-3, 4):
                        for dy in range(-3, 4):
                            nx, ny = x + dx, y + dy
                            if 0 <= nx < n and 0 <= ny < n and self.terrain[ny][nx] == FOREST:
                                near_forest.add((x, y))
                                break
                        else:
                            continue
                        break

        tree_cells = list(near_forest)
        self._rng.shuffle(tree_cells)
        max_trees = n // 2  # cap total scatter trees

        for x, y in tree_cells:
            if len(placed_trees) >= max_trees:
                break
            too_close = any((x - px) ** 2 + (y - py) ** 2 < tmd_sq for px, py in placed_trees)
            if too_close:
                continue
            placed_trees.append((x, y))
            bx = int(x * rs + rs / 2 - 12)
            by = int(y * rs + rs / 2 - 12)
            self._features.append(("tree", bx, by))

    def prerender(self, surface: pygame.Surface):
        """Render map at high resolution with terrain blocks + feature stamps."""
        n = self.map_size
        rs = self.render_scale
        rn = n * rs  # render resolution

        # Ensure surface is the right size
        if surface.get_width() != rn or surface.get_height() != rn:
            surface = pygame.Surface((rn, rn))

        # ── 1. Base terrain as colored blocks ──
        px = pygame.PixelArray(surface)
        for y in range(n):
            base_y = y * rs
            for x in range(n):
                t = self.terrain[y][x]
                color = self.colors.get(t, (0, 0, 0))
                # Fill the rs×rs block
                for dy in range(rs):
                    row = base_y + dy
                    if row >= rn:
                        break
                    for dx in range(rs):
                        col = x * rs + dx
                        if col >= rn:
                            break
                        px[col, row] = color
        del px

        # ── 2. Feature stamps (drawn under rivers/roads) ──
        # Generate placeholder bitmaps on first use
        if not self._bitmaps:
            for key in self._STAMP_SIZES:
                self._get_bitmap(key)

        for key, bx, by in self._features:
            bmp = self._get_bitmap(key)
            sx = max(0, bx)
            sy = max(0, by)
            surface.blit(bmp, (sx, sy))

        # ── 3. Rivers (on top of terrain and stamps) ──
        if self.show_rivers and self.rivers:
            river_color = (60, 140, 220)
            river_width = max(2, rs // 2)
            for cx, cy in self.rivers:
                rx = cx * rs + rs // 2
                ry = cy * rs + rs // 2
                pygame.draw.circle(surface, river_color, (rx, ry), river_width)

        # ── 4. Roads (on top of terrain and stamps) ──
        if self.show_roads and self.road_cells:
            road_color = (150, 130, 100)
            road_width = max(2, rs // 2)
            for cx, cy in self.road_cells:
                rx = cx * rs + rs // 2
                ry = cy * rs + rs // 2
                t = self.terrain[cy][cx]
                if t not in (DEEP_WATER, SHALLOW_WATER):
                    pygame.draw.circle(surface, road_color, (rx, ry), road_width)

        # ── 5. Settlement markers ──
        for name, sx, sy, is_city in self.settlements:
            rx = sx * rs + rs // 2
            ry = sy * rs + rs // 2
            radius = max(4, rs * 2) if is_city else max(3, rs)
            color = (220, 50, 40)
            pygame.draw.circle(surface, color, (rx, ry), radius)
            pygame.draw.circle(surface, (255, 255, 255), (rx, ry), radius, max(1, rs // 3))


# ═══════════════════════════════════════════════════════════════
# Mode class (mode_manager interface)
# ═══════════════════════════════════════════════════════════════


class FantasyMapMode:
    """Mode that generates and displays a procedural fantasy map."""

    def __init__(self, config: dict):
        # Generator params
        self._gen_cfg = config

        # Display
        self.title = str(config.get("title", ""))
        self.regeneration_interval_sec = float(config.get("regeneration_interval_sec", 45))
        self.border_color = tuple(config.get("border_color", [210, 190, 150]))
        self.show_labels = bool(config.get("show_labels", True))

        # Runtime
        self.manager = None
        self._t = 0.0
        self._map_surface = None         # raw map at map_size resolution
        self._map_overlay = None          # surface for labels (same size as map_surface)
        self._generator = MapGenerator(self._gen_cfg)
        self._map_name = ""
        self._font_label = None
        self._font_title = None

    # ── life cycle ────────────────────────────────────────────

    def enter(self, manager):
        self.manager = manager
        self._recompute_fonts()
        self._regenerate()

    def exit(self):
        self.manager = None
        self._map_surface = None
        self._map_overlay = None

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_SPACE, pygame.K_r):
                self._regenerate()

    def update(self, dt: float):
        self._t += dt
        if self.regeneration_interval_sec > 0 and self._t >= self.regeneration_interval_sec:
            self._t = 0.0
            self._regenerate()

    def render(self, screen):
        w, h = screen.get_size()

        # Thin border around the whole screen
        border = max(8, int(min(w, h) * 0.015))  # ~12px at 800px

        # Map fills the screen inside the border (stretches to aspect ratio)
        map_rect = pygame.Rect(border, border, w - 2 * border, h - 2 * border)

        # Dark background behind the border
        screen.fill((20, 15, 10))

        # Decorative border frame (warm parchment tone)
        inner_border = 2
        pygame.draw.rect(screen, (160, 140, 110),
                         (map_rect.left - inner_border, map_rect.top - inner_border,
                          map_rect.width + 2 * inner_border, map_rect.height + 2 * inner_border),
                         inner_border)

        # Draw map (scaled to fill — non-uniform stretch is fine for kiosk display)
        if self._map_surface is not None:
            scaled = pygame.transform.smoothscale(self._map_surface,
                                                  (map_rect.width, map_rect.height))
            screen.blit(scaled, map_rect)

        # Draw overlay with labels (same scale)
        if self._map_overlay is not None and self.show_labels:
            scaled_ov = pygame.transform.smoothscale(self._map_overlay,
                                                     (map_rect.width, map_rect.height))
            screen.blit(scaled_ov, map_rect)

        # Title bar overlaid at top
        if self._font_title and self._map_name:
            self._draw_title_bar(screen, map_rect)

    # ── internals ─────────────────────────────────────────────

    def _regenerate(self):
        """Generate a new map."""
        seed = self._gen_cfg.get("seed")
        if seed is None:
            self._gen_cfg["seed"] = random.randrange(1, 2 ** 31 - 1)
        else:
            # Re-seed with new random if seed not pinned
            self._gen_cfg["seed"] = random.randrange(1, 2 ** 31 - 1)

        self._generator = MapGenerator(self._gen_cfg)
        self._generator.generate()
        self._map_name = self._generator.map_name

        # Prerender map
        rs = self._generator.render_scale
        rn = self._generator.map_size * rs
        self._map_surface = pygame.Surface((rn, rn))
        self._generator.prerender(self._map_surface)

        # Build label overlay
        self._rebuild_overlay()

        self._t = 0.0
        print(f"[FantasyMap] Generated map: {self._map_name} (seed={self._generator.seed})")

    def _recompute_fonts(self):
        if self.manager is None:
            return
        base = min(self.manager.screen.get_width(), self.manager.screen.get_height())
        self._font_title = self.manager.cache.get_font(
            "dejavuserif", max(16, int(base * 0.052)), bold=True
        )
        self._font_label = self.manager.cache.get_font(
            "dejavuserif", max(8, int(base * 0.028)), bold=False
        )

    def _rebuild_overlay(self):
        """Create a surface with settlement name labels at render resolution."""
        if not self.show_labels or self._font_label is None:
            self._map_overlay = None
            return

        n = self._generator.map_size
        rs = self._generator.render_scale
        rn = n * rs
        self._map_overlay = pygame.Surface((rn, rn), pygame.SRCALPHA)

        for name, sx, sy, is_city in self._generator.settlements:
            color = (30, 20, 10)  # dark brown text
            size = max(9, int(n * 0.022))
            if is_city:
                size = int(size * 1.3)
            try:
                font = self.manager.cache.get_font("dejavuserif", size, bold=is_city)
            except Exception:
                font = self._font_label

            text = font.render(name, True, color)
            # Position in render coordinates
            rx = sx * rs + rs * 2 + 4
            ry = sy * rs + rs // 2 - text.get_height() // 2
            # Clamp to map bounds
            rx = max(0, min(rx, rn - text.get_width()))
            ry = max(0, min(ry, rn - text.get_height()))
            self._map_overlay.blit(text, (rx, ry))

    def _draw_title_bar(self, screen, map_rect: pygame.Rect):
        """Draw the map name overlaid at the top of the map area."""
        if self._font_title is None:
            return
        text = self._font_title.render(self._map_name, True, (50, 30, 10))
        tw = text.get_width()
        th = text.get_height()

        # Semi-transparent banner across the full width
        banner_h = th + 12
        banner = pygame.Surface((map_rect.width, banner_h), pygame.SRCALPHA)
        banner.fill((200, 180, 140, 180))
        screen.blit(banner, (map_rect.left, map_rect.top))

        # Centered text on the banner
        x = map_rect.left + (map_rect.width - tw) // 2
        y = map_rect.top + (banner_h - th) // 2
        screen.blit(text, (x, y))

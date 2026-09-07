# penrose_tiling_mode.py
#
# A kiosk mode that displays a gradually growing Penrose tiling.
# Supports P1 (simplified pentagon wheel), P2 (kite & dart), and
# P3 (thin & thick rhombus).
#
# P2 and P3 are built via Robinson triangle subdivision — the
# standard deflation method that preserves aperiodicity.  Each
# generation produces ≈ 1.618× more triangles at 1/φ the scale.
# The mode advances one generation every `generation_interval_sec`
# seconds, then resets after `max_generations`.
#
# For P2 and P3 we render the Robinson triangles directly and
# optionally attempt to assemble them into rhombuses / kites.
# Rendering triangles directly is always correct; tile assembly
# is best-effort and works best when the seed naturally produces
# paired triangles.
#
# P1 uses a simplified pentagon-wheel decomposition — not the
# full 6-tile protoset, but visually satisfying.

import math
import random
from collections import defaultdict
from typing import List, Tuple

import pygame

# ── golden ratio ────────────────────────────────────────────────
φ = (1.0 + math.sqrt(5.0)) / 2.0  # ≈ 1.618

# ── Robinson triangle types ─────────────────────────────────────
#
# A Robinson triangle is stored as (type, A, B, C) where:
#   ACUTE:  A is the 36° apex, B and C are the 72° base vertices.
#           Equal sides A-B and A-C are LONG.  Base B-C is SHORT.
#           Two ACUTE triangles sharing their SHORT edge (B-C)
#           form a thin rhombus (P3) or kite half (P2).
#   OBTUSE: A is the 108° apex, B and C are the 36° base vertices.
#           Equal sides A-B and A-C are SHORT.  Base B-C is LONG.
#           Two OBTUSE triangles sharing their LONG edge (B-C)
#           form a thick rhombus (P3).

ACUTE  = 0   # 36°-72°-72°
OBTUSE = 1   # 108°-36°-36°

# ── geometry helpers ────────────────────────────────────────────

def _vkey(pt: Tuple[float, float]) -> Tuple[float, float]:
    """Quantise a point for hash-map neighbour lookups."""
    return (round(pt[0], 3), round(pt[1], 3))

def _ekey(a, b):
    """Canonical key for an undirected edge."""
    ka, kb = _vkey(a), _vkey(b)
    return (ka, kb) if ka < kb else (kb, ka)

def _tri_id(tri_type, v0, v1, v2):
    """Order-independent ID for a triangle (for used-set dedup)."""
    return (tri_type, frozenset([_vkey(v0), _vkey(v1), _vkey(v2)]))

def _golden_split(p1, p2):
    """Point at 1/φ from p1 along p1→p2."""
    t = 1.0 / φ  # ≈ 0.618
    return (p1[0] + t * (p2[0] - p1[0]),
            p1[1] + t * (p2[1] - p1[1]))

def _mid(p1, p2):
    return ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)

# ── Robinson triangle subdivision ────────────────────────────────
#
# Subdivision rules (one generation of deflation):
#   ACUTE(A=36°,B=72°,C=72°) splits into 1 smaller ACUTE + 1 OBTUSE
#   OBTUSE(A=108°,B=36°,C=36°) splits into 1 smaller ACUTE
#
# The new triangles are φ times smaller (linear scale) than parents.

def subdivide_acute(A, B, C):
    """A=36° apex, B,C=72° base. Returns [(type, v0, v1, v2), ...]."""
    # Split the SHORT base B-C at golden-ratio point P (nearer B).
    P = _golden_split(B, C)
    return [
        (ACUTE,  A, P, B),   # smaller acute; apex still A, base P-B
        (OBTUSE, A, C, P),   # obtuse; apex A, base C-P
    ]

def subdivide_obtuse(A, B, C):
    """A=108° apex, B,C=36° base. Returns [(type, v0, v1, v2), ...]."""
    # Split the LONG base B-C at golden-ratio point Q (nearer B).
    Q = _golden_split(B, C)
    return [
        (ACUTE, A, B, Q),    # acute; apex A, base B-Q
    ]

# ── Tile assembly (best-effort rhombus / kite pairing) ──────────

def assemble_p3_rhombuses(triangles: list) -> list:
    """
    Pair Robinson triangles into P3 rhombuses.
    - Two ACUTE sharing their SHORT edge (B-C) → thin rhombus
    - Two OBTUSE sharing their LONG edge (B-C) → thick rhombus

    The B-C edge is ALWAYS the base for both triangle types,
    so we only need to index that one edge per triangle.

    Returns list of (kind, v0, v1, v2, v3) where kind is 'thin' or 'thick'.
    """
    # Index triangles by their base edge (v1-v2)
    bases = defaultdict(list)  # _ekey → [(tri_type, apex, base_a, base_b), ...]
    for tri_type, v0, v1, v2 in triangles:
        bases[_ekey(v1, v2)].append((tri_type, v0, v1, v2))

    rhombuses = []
    used = set()

    for ek, items in bases.items():
        acute_items = [it for it in items if it[0] == ACUTE]
        obtuse_items = [it for it in items if it[0] == OBTUSE]

        # Thin rhombus: two ACUTE sharing the SHORT base
        for i in range(0, len(acute_items) - 1, 2):
            t1, t2 = acute_items[i], acute_items[i + 1]
            id1, id2 = _tri_id(*t1), _tri_id(*t2)
            if id1 in used or id2 in used:
                continue
            used.add(id1)
            used.add(id2)
            # Rhombus vertices in CCW order:
            # base_end_a, apex_t1, base_end_b, apex_t2
            rhombuses.append(('thin', t1[2], t1[1], t1[3], t2[1]))

        # Thick rhombus: two OBTUSE sharing the LONG base
        for i in range(0, len(obtuse_items) - 1, 2):
            t1, t2 = obtuse_items[i], obtuse_items[i + 1]
            id1, id2 = _tri_id(*t1), _tri_id(*t2)
            if id1 in used or id2 in used:
                continue
            used.add(id1)
            used.add(id2)
            rhombuses.append(('thick', t1[2], t1[1], t1[3], t2[1]))

    return rhombuses


def assemble_p2_kites_darts(triangles: list) -> list:
    """
    Best-effort P2 kite/dart assembly from Robinson triangles.
    A kite = one ACUTE + one OBTUSE sharing an edge.
    A dart = two OBTUSE sharing a SHORT edge.

    Returns list of (kind, v0, v1, v2, v3).
    """
    # Index ALL edges for cross-type matching
    all_edges = defaultdict(list)
    for tri_type, v0, v1, v2 in triangles:
        for ea, eb in [(v0, v1), (v1, v2), (v2, v0)]:
            all_edges[_ekey(ea, eb)].append((tri_type, v0, v1, v2))

    kites_darts = []
    used = set()

    for ek, items in all_edges.items():
        acute = [it for it in items if it[0] == ACUTE]
        obtuse = [it for it in items if it[0] == OBTUSE]

        # Kite: one acute + one obtuse sharing an edge
        for a in acute:
            for o in obtuse:
                aid, oid = _tri_id(*a), _tri_id(*o)
                if aid in used or oid in used:
                    continue
                used.add(aid)
                used.add(oid)
                # Approximate kite vertices
                kites_darts.append(('kite', a[1], a[2], a[3], o[3]))
                break

    return kites_darts


# ── P1: simplified pentagon wheel ───────────────────────────────

def p1_wheel_tiles(cx, cy, radius, depth):
    """
    Generate a P1-like pentagon wheel recursively.
    Returns list of (shape_type, vertices_list).
    shape_type: 'pentagon' or 'rhombus'
    """
    if depth <= 0:
        verts = []
        for k in range(5):
            angle = -math.pi / 2 + k * 2 * math.pi / 5
            verts.append((cx + radius * math.cos(angle),
                          cy + radius * math.sin(angle)))
        return [('pentagon', verts)]

    results = []
    inner_radius = radius / (φ * φ)
    pent_verts = []
    for k in range(5):
        angle = -math.pi / 2 + k * 2 * math.pi / 5
        pent_verts.append((cx + inner_radius * math.cos(angle),
                           cy + inner_radius * math.sin(angle)))
    results.append(('pentagon', pent_verts))

    for k in range(5):
        angle_k = -math.pi / 2 + k * 2 * math.pi / 5
        angle_next = -math.pi / 2 + (k + 1) * 2 * math.pi / 5
        inner_a = (cx + inner_radius * math.cos(angle_k),
                   cy + inner_radius * math.sin(angle_k))
        inner_b = (cx + inner_radius * math.cos(angle_next),
                   cy + inner_radius * math.sin(angle_next))
        outer_a = (cx + radius * math.cos(angle_k),
                   cy + radius * math.sin(angle_k))
        outer_b = (cx + radius * math.cos(angle_next),
                   cy + radius * math.sin(angle_next))
        results.append(('rhombus', [inner_a, outer_a, outer_b, inner_b]))

        tip_angle = -math.pi / 2 + (k + 0.5) * 2 * math.pi / 5
        sub_cx = cx + radius * 1.05 * math.cos(tip_angle)
        sub_cy = cy + radius * 1.05 * math.sin(tip_angle)
        results.extend(p1_wheel_tiles(sub_cx, sub_cy, radius / φ, depth - 1))

    return results


# ── Mode class ──────────────────────────────────────────────────

class PenroseTilingMode:
    """
    Gradually growing Penrose tiling.

    Config keys (all optional):
      tiling_type          'p1' | 'p2' | 'p3'            (default 'p3')
      generation_interval_sec  sec per generation          (default 3.0)
      max_generations      gens before reset               (default 10)
      render_mode          'triangles' | 'tiles' | 'both'  (default 'both')
      tile_fill_alpha      fill opacity 0..255             (default 200)
      tile_edge_alpha      edge opacity 0..255             (default 80)
      bg_rgb               background [r,g,b]              (default [8,8,16])
      palette              list of [r,g,b] colours         (default: 5-set)
      palette_obtuse       alt colour for obtuse triangles (default: palette)
      seed                 RNG seed                        (default None)
      center_x, center_y   centre fraction (0..1)          (default 0.5)
      initial_radius       starting radius px              (default auto)
    """

    def __init__(self, config: dict):
        self.tiling_type = str(config.get('tiling_type', 'p3')).lower().strip()
        self.gen_interval = float(config.get('generation_interval_sec', 3.0))
        self.max_generations = int(config.get('max_generations', 10))
        self.render_mode = str(config.get('render_mode', 'both')).lower().strip()
        self.fill_alpha = int(config.get('tile_fill_alpha', 200))
        self.edge_alpha = int(config.get('tile_edge_alpha', 80))
        self.bg_rgb = tuple(config.get('bg_rgb', [8, 8, 16]))
        self.center_x = float(config.get('center_x', 0.5))
        self.center_y = float(config.get('center_y', 0.5))
        self.initial_radius = config.get('initial_radius', None)

        raw_palette = config.get('palette', [
            [200, 140, 60],
            [80, 160, 200],
            [180, 100, 160],
            [100, 190, 130],
            [220, 180, 100],
        ])
        self.palette = [tuple(c) for c in raw_palette]

        raw_obtuse = config.get('palette_obtuse', None)
        if raw_obtuse:
            self.palette_obtuse = [tuple(c) for c in raw_obtuse]
        else:
            # Default: slightly shifted versions of palette
            self.palette_obtuse = [
                (min(255, c[0] + 30), min(255, c[1] + 20), max(0, c[2] - 20))
                for c in self.palette
            ]

        self.seed = config.get('seed', None)

        # Runtime
        self.manager = None
        self.w = 0
        self.h = 0
        self.cx = 0.0
        self.cy = 0.0
        self.radius = 200.0
        self._gen = 0
        self._triangles = []
        self._tiles = []
        self._accum = 0.0
        self._rng = random.Random()
        self._tri_surf = None   # pre-rendered triangle surface
        self._tile_surf = None  # pre-rendered tile surface

    # ── lifecycle ────────────────────────────────────────────

    def enter(self, manager):
        self.manager = manager
        self._sync_size()
        self._init_seed()
        self._gen = 0
        self._build_generation()

    def exit(self):
        self.manager = None
        self._tri_surf = None
        self._tile_surf = None

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_r:
                self._gen = 0
                self._build_generation()
            elif event.key == pygame.K_SPACE:
                self._advance()
            elif event.key == pygame.K_LEFT and self._gen > 0:
                self._gen -= 1
                self._build_generation()
            elif event.key == pygame.K_m:
                # Cycle render mode: both → triangles → tiles → both
                modes = ['both', 'triangles', 'tiles']
                idx = modes.index(self.render_mode) if self.render_mode in modes else 0
                self.render_mode = modes[(idx + 1) % len(modes)]
                self._build_generation()
            elif event.key == pygame.K_t:
                # Cycle tiling type
                types = ['p3', 'p2', 'p1']
                idx = types.index(self.tiling_type) if self.tiling_type in types else 0
                self.tiling_type = types[(idx + 1) % len(types)]
                self._gen = 0
                self._build_generation()

    def update(self, dt: float):
        self._sync_size()
        self._accum += dt
        if self._accum >= self.gen_interval:
            self._accum = max(0.0, self._accum - self.gen_interval)
            self._advance()

    def _advance(self):
        if self._gen < self.max_generations:
            self._gen += 1
            self._build_generation()
        else:
            self._gen = 0
            self._init_seed()
            self._build_generation()

    def render(self, screen: pygame.Surface):
        screen.fill(self.bg_rgb)

        # Draw pre-rendered surfaces centred
        ox = int(self.w * self.center_x)
        oy = int(self.h * self.center_y)

        if self.render_mode in ('triangles', 'both') and self._tri_surf is not None:
            tw, th = self._tri_surf.get_size()
            screen.blit(self._tri_surf, (ox - tw // 2, oy - th // 2))

        if self.render_mode in ('tiles', 'both') and self._tile_surf is not None:
            tw, th = self._tile_surf.get_size()
            screen.blit(self._tile_surf, (ox - tw // 2, oy - th // 2))

        # Info overlay
        if self.manager and self._gen <= 2:
            font = self.manager.cache.get_font(None, 14, bold=False)
            info = (f"type:{self.tiling_type} gen:{self._gen}/{self.max_generations} "
                    f"tris:{len(self._triangles)} render:{self.render_mode} "
                    f"[SPACE]next [R]reset [M]mode [T]type")
            label = font.render(info, True, (160, 160, 190))
            screen.blit(label, (8, 8))

    # ── build pipeline ───────────────────────────────────────

    def _build_generation(self):
        if self.tiling_type == 'p1':
            self._build_p1()
            return
        self._build_p2_p3()

    def _build_p1(self):
        tiles = p1_wheel_tiles(self.cx, self.cy, self.radius, self._gen)
        self._tiles = tiles
        self._triangles = []
        self._tri_surf = None
        self._tile_surf = self._render_p1(tiles)

    def _build_p2_p3(self):
        self._triangles = self._seed_triangles()
        for _ in range(self._gen):
            self._triangles = self._subdivide_all(self._triangles)

        # Assemble tiles
        if self.tiling_type == 'p2':
            self._tiles = assemble_p2_kites_darts(self._triangles)
        else:
            self._tiles = assemble_p3_rhombuses(self._triangles)

        # Render
        self._tri_surf = self._render_triangles(self._triangles)
        self._tile_surf = self._render_tiles(self._tiles)

    def _seed_triangles(self):
        """
        Classic Penrose P3 seed: the "sun" pattern — 5 thick rhombuses
        arranged around a central point.  Each thick rhombus is
        decomposed into 2 obtuse Robinson triangles that share their
        LONG base.  This gives 10 obtuse triangles that pair into
        5 thick rhombuses at gen 0.

        For P2, the same seed is used — Robinson subdivision naturally
        produces the correct kite/dart pairing after 1+ generations.
        """
        tris = []
        # 5 thick rhombuses meet at center with their 72° corners.
        # Each rhombus's short diagonal connects the two 72° vertices
        # (center and outer-72°); the long diagonal connects the two
        # 108° vertices.  Splitting along the short diagonal gives
        # 2 obtuse Robinson triangles per rhombus.

        # We build 5 pairs of obtuse triangles sharing their long base.
        for k in range(5):
            # Centre angle of this rhombus sector
            base_angle = -math.pi / 2 + k * 2 * math.pi / 5
            next_angle = -math.pi / 2 + (k + 1) * 2 * math.pi / 5

            # The thick rhombus has vertices:
            #   center (72°), r1 (108°), outer (72°), r2 (108°)
            # where r1 and r2 are at the golden-ratio distance.
            center = (self.cx, self.cy)
            outer = (self.cx + self.radius * math.cos(base_angle + math.pi / 5),
                     self.cy + self.radius * math.sin(base_angle + math.pi / 5))
            r1 = (self.cx + self.radius * math.cos(base_angle),
                  self.cy + self.radius * math.sin(base_angle))
            r2 = (self.cx + self.radius * math.cos(next_angle),
                  self.cy + self.radius * math.sin(next_angle))

            # The short diagonal is center→outer.
            # Two obtuse triangles: (108° at r1, 36° at center, 36° at outer)
            # and (108° at r2, 36° at center, 36° at outer).
            # They share the long base (center→outer is the SHORT diagonal,
            # the LONG base of each obtuse triangle is center→outer).
            # Wait — for obtuse (108°,36°,36°), the BASE (B-C) is the
            # LONG side opposite the 108° apex.  Two obtuse triangles
            # sharing their long base form a thick rhombus.
            #
            # The short diagonal (center→outer) of the thick rhombus
            # splits it into two (54°,72°,54°) triangles — NOT obtuse
            # Robinson triangles.
            #
            # To get Robinson triangles, we split along the LONG diagonal
            # (r1→r2), giving two obtuse (108°,36°,36°) triangles
            # sharing the LONG base r1→r2.
            #
            # Obtuse triangle 1: apex center (108°), bases r1, r2 (36° each)
            # Obtuse triangle 2: apex outer (108°), bases r1, r2 (36° each)

            # Obtuse triangle 1: apex=center, base=r1, base=r2
            tris.append((OBTUSE, center, r1, r2))
            # Obtuse triangle 2: apex=outer, base=r1, base=r2
            tris.append((OBTUSE, outer, r1, r2))

        return tris

    def _subdivide_all(self, triangles):
        result = []
        for tri_type, v0, v1, v2 in triangles:
            if tri_type == ACUTE:
                result.extend(subdivide_acute(v0, v1, v2))
            else:
                result.extend(subdivide_obtuse(v0, v1, v2))
        return result

    # ── rendering ────────────────────────────────────────────

    def _render_triangles(self, triangles):
        """Render Robinson triangles to a pre-computed surface."""
        if not triangles:
            return None
        return _render_tri_list(triangles, self.palette, self.palette_obtuse,
                                self.fill_alpha, self.edge_alpha)

    def _render_tiles(self, tiles):
        """Render assembled tiles to a pre-computed surface."""
        if not tiles:
            return None
        return _render_tile_list(tiles, self.palette,
                                 self.fill_alpha, self.edge_alpha)

    def _render_p1(self, tiles):
        """Render P1 tiles to a pre-computed surface."""
        if not tiles:
            return None
        return _render_p1_list(tiles, self.palette,
                               self.fill_alpha, self.edge_alpha)

    # ── helpers ──────────────────────────────────────────────

    def _sync_size(self):
        if self.manager is None:
            return
        w, h = self.manager.screen.get_size()
        if w == self.w and h == self.h:
            return
        self.w, self.h = w, h
        self.cx = w * self.center_x
        self.cy = h * self.center_y
        if self.initial_radius is not None:
            self.radius = float(self.initial_radius)
        else:
            self.radius = min(w, h) * 0.38

    def _init_seed(self):
        self._rng = random.Random(self.seed if self.seed is not None else None)


# ── rendering helpers (module-level for clarity) ────────────────

def _compute_surface(triangles_or_tiles, draw_fn) -> pygame.Surface | None:
    """Compute bounding box and render onto an RGBA surface via draw_fn."""
    all_x, all_y = [], []
    # Collect points — draw_fn should yield all vertices
    # We do a quick first pass to compute bounds
    for item in triangles_or_tiles:
        for pt in _item_vertices(item):
            all_x.append(pt[0])
            all_y.append(pt[1])

    if not all_x:
        return None

    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    bw = int(max_x - min_x) + 4
    bh = int(max_y - min_y) + 4
    bw, bh = max(bw, 4), max(bh, 4)

    surf = pygame.Surface((bw, bh), pygame.SRCALPHA)
    surf.fill((0, 0, 0, 0))
    ox, oy = -min_x + 2, -min_y + 2

    for item in triangles_or_tiles:
        draw_fn(surf, item, ox, oy)

    return surf


def _item_vertices(item):
    """Yield all (x,y) tuples from a triangle or tile tuple."""
    if isinstance(item[0], int):  # Robinson triangle: (type, v0, v1, v2)
        yield item[1]; yield item[2]; yield item[3]
    elif len(item) == 5:  # assembled tile: (kind, v0, v1, v2, v3)
        yield item[1]; yield item[2]; yield item[3]; yield item[4]
    else:  # P1 tile: (shape_type, [vertices])
        for v in item[1]:
            yield v


def _render_tri_list(triangles, palette, palette_obtuse, fill_alpha, edge_alpha):
    """Render Robinson triangles."""
    if not triangles:
        return None

    all_x, all_y = [], []
    for tri_type, v0, v1, v2 in triangles:
        for p in (v0, v1, v2):
            all_x.append(p[0]); all_y.append(p[1])

    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    bw = int(max_x - min_x) + 4
    bh = int(max_y - min_y) + 4
    bw, bh = max(bw, 4), max(bh, 4)

    surf = pygame.Surface((bw, bh), pygame.SRCALPHA)
    surf.fill((0, 0, 0, 0))
    ox, oy = -min_x + 2, -min_y + 2

    for tri_type, v0, v1, v2 in triangles:
        pts = [(int(v0[0] + ox), int(v0[1] + oy)),
               (int(v1[0] + ox), int(v1[1] + oy)),
               (int(v2[0] + ox), int(v2[1] + oy))]
        if tri_type == ACUTE:
            color = palette[0]
        else:
            color = palette_obtuse[0]
        fill = (*color, fill_alpha)
        edge = (*color, edge_alpha)
        pygame.draw.polygon(surf, fill, pts)
        pygame.draw.polygon(surf, edge, pts, 1)

    return surf


def _render_tile_list(tiles, palette, fill_alpha, edge_alpha):
    """Render assembled rhombus/kite tiles."""
    if not tiles:
        return None

    all_x, all_y = [], []
    for t in tiles:
        for i in range(1, 5):
            all_x.append(t[i][0]); all_y.append(t[i][1])

    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    bw = int(max_x - min_x) + 4
    bh = int(max_y - min_y) + 4
    bw, bh = max(bw, 4), max(bh, 4)

    surf = pygame.Surface((bw, bh), pygame.SRCALPHA)
    surf.fill((0, 0, 0, 0))
    ox, oy = -min_x + 2, -min_y + 2

    for i, t in enumerate(tiles):
        kind = t[0]
        pts = [(int(t[j][0] + ox), int(t[j][1] + oy)) for j in range(1, 5)]
        ci = i % len(palette)
        color = palette[ci]
        fill = (*color, fill_alpha)
        edge = (*color, edge_alpha)
        pygame.draw.polygon(surf, fill, pts)
        pygame.draw.polygon(surf, edge, pts, 1)

    return surf


def _render_p1_list(tiles, palette, fill_alpha, edge_alpha):
    """Render P1 pentagon/rhombus tiles."""
    if not tiles:
        return None

    all_x, all_y = [], []
    for _, verts in tiles:
        for v in verts:
            all_x.append(v[0]); all_y.append(v[1])

    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    bw = int(max_x - min_x) + 4
    bh = int(max_y - min_y) + 4
    bw, bh = max(bw, 4), max(bh, 4)

    surf = pygame.Surface((bw, bh), pygame.SRCALPHA)
    surf.fill((0, 0, 0, 0))
    ox, oy = -min_x + 2, -min_y + 2

    for i, (shape_type, verts) in enumerate(tiles):
        pts = [(int(v[0] + ox), int(v[1] + oy)) for v in verts]
        ci = i % len(palette)
        color = palette[ci]
        fill = (*color, fill_alpha)
        edge = (*color, edge_alpha)
        pygame.draw.polygon(surf, fill, pts)
        pygame.draw.polygon(surf, edge, pts, 1)

    return surf

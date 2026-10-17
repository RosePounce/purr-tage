# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""The map: terrain, lakes, resource nodes, bases.

A map is either generated from a seed, at one of the `MAP_SIZES`, or drawn in
the editor and read back from a file (see `purrtage.mapfile`).
"""

import math
import random

from .settings import (DEFAULT_MAP_SIZE, RES_AMOUNT, R_CATNIP, R_KIBBLE,
                       R_STONE, R_WOOL, TERRAIN_WALKABLE, TILE, T_FLOWER, T_GRASS,
                       T_MEADOW, T_SAND, T_WATER)
from .utils import ValueNoise, bresenham, clamp


class ResourceNode(object):
    """A resource node: a kibble bowl, a ball of wool, a catnip patch or a
    heap of stones."""

    __slots__ = ("kind", "tx", "ty", "amount", "max_amount", "variant", "alive")

    def __init__(self, kind, tx, ty, amount=None, variant=0):
        self.kind = kind
        self.tx, self.ty = tx, ty
        self.max_amount = amount or RES_AMOUNT[kind]
        self.amount = self.max_amount
        self.variant = variant
        self.alive = True

    @property
    def x(self):
        return self.tx * TILE + TILE * 0.5

    @property
    def y(self):
        return self.ty * TILE + TILE * 0.5

    @property
    def pos(self):
        return (self.x, self.y)

    def take(self, qty):
        qty = min(qty, self.amount)
        self.amount -= qty
        if self.amount <= 0:
            self.alive = False
        return qty


# Distance between a base and the two map edges it sits next to.
BASE_MARGIN = 11


class World(object):
    def __init__(self, seed=None, size=DEFAULT_MAP_SIZE, generate=True):
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self.rng = random.Random(self.seed)
        self.w = self.h = int(size)
        self.name = ""                    # set on a map drawn in the editor
        self.terrain = [bytearray(self.w) for _ in range(self.h)]
        self.blocked = [bytearray(self.w) for _ in range(self.h)]
        self.nodes = []
        self.node_at = {}                 # (tx, ty) -> ResourceNode
        self.building_at = {}             # (tx, ty) -> Building
        self.decor = []                   # (tx, ty, variant) small bushes
        self.start_tiles = []             # the center tile of each base
        if generate:
            self._generate()

    @classmethod
    def blank(cls, size=DEFAULT_MAP_SIZE, seed=None):
        """All grass, the two bases in their usual corners: a blank page."""
        world = cls(seed, size, generate=False)
        for row in world.terrain:
            row[:] = bytes((T_GRASS,)) * world.w
        world.start_tiles = world.default_start_tiles()
        world.finish()
        return world

    @property
    def world_w(self):
        """The map width in world pixels."""
        return self.w * TILE

    @property
    def world_h(self):
        return self.h * TILE

    def default_start_tiles(self):
        return [(BASE_MARGIN, self.h - BASE_MARGIN),
                (self.w - BASE_MARGIN, BASE_MARGIN)]

    def finish(self):
        """Dress a map whose terrain, nodes and bases are set: the bushes,
        then the obstacle grid. Called after generating or loading."""
        self.decor = []
        self._place_decor()
        self._rebuild_blocked()

    # ------------------------------------------------------------ generation --
    def _area_ratio(self):
        """How much bigger than the default map this one is."""
        return self.w * self.h / float(DEFAULT_MAP_SIZE * DEFAULT_MAP_SIZE)

    def _generate(self):
        # The noise grids grow with the map, so that a lake keeps the same
        # size in tiles on a big map instead of being blown up with it.
        k = self.w / float(DEFAULT_MAP_SIZE)
        h = ValueNoise(self.seed, max(4, int(round(8 * k))))
        d = ValueNoise(self.seed + 7919, max(8, int(round(16 * k))))
        for ty in range(self.h):
            for tx in range(self.w):
                nx, ny = tx / float(self.w), ty / float(self.h)
                v = h.octaves(nx, ny, 4)
                # raise the ground level towards the base corners
                v += 0.10 * (1.0 - abs(nx - ny))
                if v < 0.325:
                    t = T_WATER
                elif v < 0.375:
                    t = T_SAND
                else:
                    dv = d.octaves(nx * 2.0 % 1.0, ny * 2.0 % 1.0, 3)
                    t = T_MEADOW if dv > 0.62 else (T_FLOWER if dv < 0.33 else T_GRASS)
                self.terrain[ty][tx] = t

        self.start_tiles = self.default_start_tiles()
        for (bx, by) in self.start_tiles:
            self._flatten(bx, by, 9)
        self._ensure_connectivity()
        self._rebuild_blocked()
        self._place_resources()
        self.finish()

    def _flatten(self, cx, cy, r):
        """Turn the area into walkable grass (around a base)."""
        for ty in range(cy - r, cy + r + 1):
            for tx in range(cx - r, cx + r + 1):
                if not self.in_bounds(tx, ty):
                    continue
                if (tx - cx) ** 2 + (ty - cy) ** 2 <= r * r:
                    if self.terrain[ty][tx] in (T_WATER, T_SAND):
                        self.terrain[ty][tx] = T_GRASS

    def _ensure_connectivity(self):
        """Dig an isthmus when the two bases are not connected by land."""
        a, b = self.start_tiles
        if self._reachable(a, b):
            return
        mid = ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)
        jitter = (clamp(mid[0] + self.rng.randint(-14, 14), 4, self.w - 5),
                  clamp(mid[1] + self.rng.randint(-14, 14), 4, self.h - 5))
        for seg in ((a, jitter), (jitter, b)):
            for (x, y) in bresenham(seg[0][0], seg[0][1], seg[1][0], seg[1][1]):
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        nx, ny = x + dx, y + dy
                        if self.in_bounds(nx, ny) and self.terrain[ny][nx] == T_WATER:
                            self.terrain[ny][nx] = T_SAND

    def bases_connected(self):
        """True when a cat can walk from every base to every other one."""
        first = self.start_tiles[0] if self.start_tiles else None
        return all(self._reachable(first, other)
                   for other in self.start_tiles[1:])

    def _reachable(self, a, b):
        seen = {a}
        stack = [a]
        while stack:
            x, y = stack.pop()
            if (x, y) == b:
                return True
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if (nx, ny) in seen or not self.in_bounds(nx, ny):
                    continue
                if TERRAIN_WALKABLE[self.terrain[ny][nx]]:
                    seen.add((nx, ny))
                    stack.append((nx, ny))
        return False

    def _free_for_node(self, tx, ty, keep_clear):
        if not self.in_bounds(tx, ty):
            return False
        if not TERRAIN_WALKABLE[self.terrain[ty][tx]]:
            return False
        if (tx, ty) in self.node_at:
            return False
        for (bx, by) in self.start_tiles:
            if abs(bx - tx) <= keep_clear and abs(by - ty) <= keep_clear:
                return False
        return True

    def _add_node(self, kind, tx, ty, keep_clear=3):
        if not self._free_for_node(tx, ty, keep_clear):
            return None
        node = ResourceNode(kind, tx, ty, variant=self.rng.randrange(3))
        self.nodes.append(node)
        self.node_at[(tx, ty)] = node
        return node

    def _cluster(self, kind, cx, cy, count, spread, keep_clear=3):
        placed = 0
        for _ in range(count * 14):
            if placed >= count:
                break
            tx = cx + self.rng.randint(-spread, spread)
            ty = cy + self.rng.randint(-spread, spread)
            if self._add_node(kind, tx, ty, keep_clear):
                placed += 1
        return placed

    def _place_resources(self):
        # Starting endowment, strictly identical for every base.
        for (bx, by) in self.start_tiles:
            for (kind, count, rmin, rmax) in ((R_WOOL, 7, 4, 7),
                                              (R_KIBBLE, 5, 5, 8),
                                              (R_CATNIP, 3, 6, 9),
                                              (R_STONE, 3, 7, 10)):
                placed = 0
                for _ in range(400):
                    if placed >= count:
                        break
                    ang = self.rng.random() * 6.28318
                    rad = self.rng.uniform(rmin, rmax)
                    tx = int(bx + rad * math.cos(ang))
                    ty = int(by + rad * math.sin(ang))
                    if self._add_node(kind, tx, ty, keep_clear=3):
                        placed += 1

        # Nodes scattered over the rest of the map, as many per tile
        # whatever its size.
        for _ in range(int(round(26 * self._area_ratio()))):
            cx = self.rng.randrange(4, self.w - 4)
            cy = self.rng.randrange(4, self.h - 4)
            kind = self.rng.choice((R_WOOL, R_WOOL, R_KIBBLE, R_CATNIP,
                                    R_STONE))
            self._cluster(kind, cx, cy, self.rng.randint(3, 7), 3, keep_clear=11)

    def _place_decor(self):
        # Its own generator: redrawing the bushes after an edit must give
        # the same ones, and must not shift the draws of anything else.
        rng = random.Random(self.seed + 104729)
        for _ in range(int(round(420 * self._area_ratio()))):
            tx = rng.randrange(self.w)
            ty = rng.randrange(self.h)
            if (tx, ty) in self.node_at:
                continue
            if self.terrain[ty][tx] in (T_GRASS, T_MEADOW, T_FLOWER):
                self.decor.append((tx, ty, rng.randrange(4)))

    # --------------------------------------------------------------- editing --
    def put_node(self, kind, tx, ty, amount=None, variant=None):
        """Place a node as is, replacing the one already there.

        No placement rule here, unlike `_add_node`: the editor and the map
        files decide where the nodes go.
        """
        old = self.node_at.get((tx, ty))
        if old is not None:
            self.remove_node(old)
        if variant is None:
            variant = (tx * 7 + ty * 13) % 3
        node = ResourceNode(kind, tx, ty, amount=amount, variant=variant)
        self.nodes.append(node)
        self.node_at[(tx, ty)] = node
        return node

    def base_footprint(self, start):
        """The tiles of the basket a base starts with (see `Game`)."""
        bx, by = start
        return [(x, y) for y in range(by - 1, by + 2)
                for x in range(bx - 1, bx + 2)]

    # -------------------------------------------------------------- queries --
    def in_bounds(self, tx, ty):
        return 0 <= tx < self.w and 0 <= ty < self.h

    def terrain_at(self, tx, ty):
        return self.terrain[ty][tx] if self.in_bounds(tx, ty) else T_WATER

    def is_blocked(self, tx, ty):
        if not self.in_bounds(tx, ty):
            return True
        return bool(self.blocked[ty][tx])

    def _rebuild_blocked(self):
        for ty in range(self.h):
            row, trow = self.blocked[ty], self.terrain[ty]
            for tx in range(self.w):
                row[tx] = 0 if TERRAIN_WALKABLE[trow[tx]] else 1
        for (tx, ty) in self.node_at:
            self.blocked[ty][tx] = 1
        for (tx, ty) in self.building_at:
            self.blocked[ty][tx] = 1

    def set_occupancy(self, tiles, occupied, owner=None):
        for (tx, ty) in tiles:
            if not self.in_bounds(tx, ty):
                continue
            if occupied:
                self.building_at[(tx, ty)] = owner
                self.blocked[ty][tx] = 1
            else:
                self.building_at.pop((tx, ty), None)
                if (tx, ty) not in self.node_at:
                    self.blocked[ty][tx] = 0 if TERRAIN_WALKABLE[self.terrain[ty][tx]] else 1

    def remove_node(self, node):
        node.alive = False
        self.node_at.pop((node.tx, node.ty), None)
        if node in self.nodes:
            self.nodes.remove(node)
        tx, ty = node.tx, node.ty
        if (tx, ty) not in self.building_at:
            self.blocked[ty][tx] = 0 if TERRAIN_WALKABLE[self.terrain[ty][tx]] else 1

    def can_place(self, tx, ty, size, ignore_fog=True, fog=None):
        """Test whether a size x size building fits from corner (tx, ty)."""
        for y in range(ty, ty + size):
            for x in range(tx, tx + size):
                if not self.in_bounds(x, y):
                    return False
                if not TERRAIN_WALKABLE[self.terrain[y][x]]:
                    return False
                if (x, y) in self.node_at or (x, y) in self.building_at:
                    return False
                if fog is not None and not ignore_fog and not fog.explored[y][x]:
                    return False
        return True

    def nearest_node(self, x, y, kind=None, max_tiles=40):
        best, best_d = None, 1e18
        for node in self.nodes:
            if kind is not None and node.kind != kind:
                continue
            if not node.alive:
                continue
            d = (node.x - x) ** 2 + (node.y - y) ** 2
            if d < best_d:
                best, best_d = node, d
        if best and best_d > (max_tiles * TILE) ** 2:
            return None
        return best

    def free_tile_around(self, tiles, blocked=None, near=None, avoid=None):
        """A free tile adjacent to a footprint, the closest one to `near`.

        `avoid` rules out the tiles already claimed by other workers: without
        it several cats aim at the same square, push each other away and spin
        around without ever getting any work done.
        """
        blocked = blocked if blocked is not None else self.blocked
        ring = set()
        for (tx, ty) in tiles:
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    n = (tx + dx, ty + dy)
                    if n not in tiles:
                        ring.add(n)
        free = sorted(t for t in ring
                      if self.in_bounds(t[0], t[1]) and not blocked[t[1]][t[0]])
        if avoid:
            unclaimed = [t for t in free if t not in avoid]
            if unclaimed:
                free = unclaimed
        if not free:
            return None
        if near is None:
            cx = sum(t[0] for t in tiles) / float(len(tiles))
            cy = sum(t[1] for t in tiles) / float(len(tiles))
        else:
            cx, cy = near[0] / float(TILE) - 0.5, near[1] / float(TILE) - 0.5
        return min(free, key=lambda t: (t[0] - cx) ** 2 + (t[1] - cy) ** 2)

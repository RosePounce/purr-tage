# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fog of war: the "explored" and "visible" grids."""

import math

from .settings import DEFAULT_MAP_SIZE, FOG_EXPLORED, FOG_UNSEEN, TILE


class Fog(object):
    def __init__(self, enabled=True, size=(DEFAULT_MAP_SIZE, DEFAULT_MAP_SIZE)):
        self.enabled = enabled
        self.w, self.h = size
        self.explored = [bytearray(self.w) for _ in range(self.h)]
        self.visible = [bytearray(self.w) for _ in range(self.h)]
        self._disc_cache = {}
        if not enabled:
            self.reveal_all()

    def reveal_all(self):
        for y in range(self.h):
            for x in range(self.w):
                self.explored[y][x] = 1
                self.visible[y][x] = 1

    def _disc(self, radius_tiles):
        """The (dx, dy) offsets of a disc, cached."""
        r = int(radius_tiles)
        offs = self._disc_cache.get(r)
        if offs is None:
            offs = []
            rr = r * r
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if dx * dx + dy * dy <= rr:
                        offs.append((dx, dy))
            self._disc_cache[r] = offs
        return offs

    def update(self, sources):
        """`sources`: an iterable of (world_x, world_y, range_in_pixels)."""
        if not self.enabled:
            return
        vis = self.visible
        for row in vis:
            for i in range(self.w):
                row[i] = 0
        exp = self.explored
        for (wx, wy, rng) in sources:
            cx, cy = int(wx) // TILE, int(wy) // TILE
            for (dx, dy) in self._disc(max(1, int(rng / TILE))):
                x, y = cx + dx, cy + dy
                if 0 <= x < self.w and 0 <= y < self.h:
                    vis[y][x] = 1
                    exp[y][x] = 1

    # ---------------------------------------------------------------- queries --
    def is_visible(self, tx, ty):
        if not self.enabled:
            return True
        if 0 <= tx < self.w and 0 <= ty < self.h:
            return bool(self.visible[ty][tx])
        return False

    def is_explored(self, tx, ty):
        if not self.enabled:
            return True
        if 0 <= tx < self.w and 0 <= ty < self.h:
            return bool(self.explored[ty][tx])
        return False

    def visible_at(self, wx, wy):
        return self.is_visible(int(wx) // TILE, int(wy) // TILE)

    def explored_at(self, wx, wy):
        return self.is_explored(int(wx) // TILE, int(wy) // TILE)

    def alpha_at(self, tx, ty):
        if not self.enabled:
            return 0
        if not (0 <= tx < self.w and 0 <= ty < self.h):
            return FOG_UNSEEN
        if self.visible[ty][tx]:
            return 0
        if self.explored[ty][tx]:
            return FOG_EXPLORED
        return FOG_UNSEEN

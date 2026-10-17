# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""A* pathfinding on a grid (8 directions) with path smoothing."""

import heapq
import math

from .settings import TILE
from .utils import bresenham

DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1),
        (1, 1), (1, -1), (-1, 1), (-1, -1))
DIAG = math.sqrt(2.0)


def in_bounds(blocked, tx, ty):
    """The grid carries the map size: no global needed, whatever the map."""
    return 0 <= ty < len(blocked) and 0 <= tx < len(blocked[0])


def walkable(blocked, tx, ty):
    return in_bounds(blocked, tx, ty) and not blocked[ty][tx]


def heuristic(ax, ay, bx, by):
    dx, dy = abs(ax - bx), abs(ay - by)
    return (dx + dy) + (DIAG - 2.0) * min(dx, dy)


def nearest_open(blocked, tile, max_r=8):
    """The free tile closest to a (possibly) blocked tile."""
    tx, ty = tile
    if walkable(blocked, tx, ty):
        return tile
    for r in range(1, max_r + 1):
        best, best_d = None, 1e18
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r:
                    continue
                nx, ny = tx + dx, ty + dy
                if walkable(blocked, nx, ny):
                    d = dx * dx + dy * dy
                    if d < best_d:
                        best, best_d = (nx, ny), d
        if best:
            return best
    return None


def line_clear(blocked, a, b):
    """True when the segment between two tiles crosses no obstacle."""
    for (x, y) in bresenham(a[0], a[1], b[0], b[1]):
        if not walkable(blocked, x, y):
            return False
    return True


def smooth(blocked, path):
    """Drop the useless waypoints (taut string)."""
    if len(path) < 3:
        return path
    out = [path[0]]
    i = 0
    while i < len(path) - 1:
        j = len(path) - 1
        while j > i + 1 and not line_clear(blocked, path[i], path[j]):
            j -= 1
        out.append(path[j])
        i = j
    return out


def astar(blocked, start, goal, max_nodes=6000):
    """The tile path from `start` (excluded) to `goal`, or None."""
    if not in_bounds(blocked, *start) or not in_bounds(blocked, *goal):
        return None
    if start == goal:
        return [goal]
    target = goal if walkable(blocked, *goal) else nearest_open(blocked, goal)
    if target is None:
        return None
    if start == target:
        return [target]

    open_heap = [(heuristic(start[0], start[1], target[0], target[1]), 0.0, start)]
    came = {start: None}
    gscore = {start: 0.0}
    expanded = 0
    best_node, best_h = start, heuristic(start[0], start[1], target[0], target[1])

    while open_heap:
        _, g, cur = heapq.heappop(open_heap)
        if cur == target:
            break
        if g > gscore.get(cur, 1e18):
            continue
        expanded += 1
        if expanded > max_nodes:
            target = best_node          # failure: get as close as we can
            break
        cx, cy = cur
        for k, (dx, dy) in enumerate(DIRS):
            nx, ny = cx + dx, cy + dy
            if not walkable(blocked, nx, ny):
                continue
            if k >= 4 and (blocked[cy][nx] or blocked[ny][cx]):
                continue            # no diagonal squeeze between two walls
            step = DIAG if k >= 4 else 1.0
            ng = g + step
            nxt = (nx, ny)
            if ng < gscore.get(nxt, 1e18):
                gscore[nxt] = ng
                came[nxt] = cur
                h = heuristic(nx, ny, target[0], target[1])
                if h < best_h:
                    best_h, best_node = h, nxt
                heapq.heappush(open_heap, (ng + h, ng, nxt))
    else:
        target = best_node

    if target not in came:
        return None
    path = []
    node = target
    while node is not None:
        path.append(node)
        node = came[node]
    path.reverse()
    return smooth(blocked, path)[1:] or [target]


def tile_center(tile):
    return (tile[0] * TILE + TILE * 0.5, tile[1] * TILE + TILE * 0.5)


def to_tile(x, y):
    return (int(x) // TILE, int(y) // TILE)

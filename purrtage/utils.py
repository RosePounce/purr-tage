# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Small geometric and graphical helpers."""

import math
import random


def clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def lerp(a, b, t):
    return a + (b - a) * t


def dist(ax, ay, bx, by):
    # math.sqrt is correctly rounded by the IEEE 754 standard, hence identical
    # on every machine; math.hypot is not. The networked simulation requires
    # the former.
    dx, dy = bx - ax, by - ay
    return math.sqrt(dx * dx + dy * dy)


def dist2(ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    return dx * dx + dy * dy


def normalize(dx, dy):
    d = math.sqrt(dx * dx + dy * dy)
    if d < 1e-6:
        return 0.0, 0.0
    return dx / d, dy / d


def mix(c1, c2, t):
    """Linear blend of two RGB colors."""
    return (int(lerp(c1[0], c2[0], t)),
            int(lerp(c1[1], c2[1], t)),
            int(lerp(c1[2], c2[2], t)))


def shade(c, f):
    """Lighten (f>1) or darken (f<1) a color."""
    return (int(clamp(c[0] * f, 0, 255)),
            int(clamp(c[1] * f, 0, 255)),
            int(clamp(c[2] * f, 0, 255)))


def fmt_time(seconds):
    seconds = int(max(0, seconds))
    return "%d:%02d" % (seconds // 60, seconds % 60)


class ValueNoise:
    """Multi-octave value noise, in pure Python (no dependency)."""

    def __init__(self, seed=0, size=16):
        self.rng = random.Random(seed)
        self.size = size
        self.grid = [[self.rng.random() for _ in range(size + 1)]
                     for _ in range(size + 1)]

    def _sample(self, x, y):
        s = self.size
        gx, gy = x * s, y * s
        x0, y0 = int(gx) % s, int(gy) % s
        tx, ty = gx - int(gx), gy - int(gy)
        tx = tx * tx * (3 - 2 * tx)
        ty = ty * ty * (3 - 2 * ty)
        g = self.grid
        a = lerp(g[y0][x0], g[y0][x0 + 1], tx)
        b = lerp(g[y0 + 1][x0], g[y0 + 1][x0 + 1], tx)
        return lerp(a, b, ty)

    def octaves(self, x, y, n=4):
        total, amp, freq, norm = 0.0, 1.0, 1.0, 0.0
        for _ in range(n):
            total += self._sample((x * freq) % 1.0, (y * freq) % 1.0) * amp
            norm += amp
            amp *= 0.5
            freq *= 2.0
        return total / norm


def bresenham(x0, y0, x1, y1):
    """The list of tiles crossed by a segment (Bresenham's algorithm)."""
    points = []
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        points.append((x0, y0))
        if x0 == x1 and y0 == y1:
            return points
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy

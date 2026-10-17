# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Camera: scrolling, zoom and screen <-> world conversions."""

import math

from .settings import (CAMERA_ARROWS_ONLY, CAM_SPEED, DEFAULT_MAP_SIZE,
                       DEFAULT_ZOOM_INDEX, EDGE_SCROLL_ENABLED,
                       EDGE_SCROLL_MARGIN, EDGE_SCROLL_SPEED, MAX_SCENE_PX,
                       TILE, ZOOM_LEVELS)
from . import keymap
from .utils import clamp


class Camera(object):
    def __init__(self, view_rect, asset_scale=1.0, world_size=None):
        self.view = view_rect              # pygame.Rect of the play area
        self.asset_scale = float(asset_scale)
        # The map extent in world pixels: the camera never shows past it.
        self.world_w, self.world_h = world_size or (DEFAULT_MAP_SIZE * TILE,
                                                    DEFAULT_MAP_SIZE * TILE)
        self.levels = self._usable_levels()
        self.zoom_index = min(DEFAULT_ZOOM_INDEX, len(self.levels) - 1)
        self._codes = None             # camera keys, see _camera_codes
        self._codes_rev = -1
        self.x = 0.0
        self.y = 0.0
        self.shake = 0.0
        self._shake_off = (0.0, 0.0)
        self.edge_scroll = EDGE_SCROLL_ENABLED

    def _usable_levels(self):
        """Keep only the steps that are useful and affordable.

        We discard those that would show more than the whole map, and those
        whose intermediate surface would exceed the pixel budget.
        """
        a = self.asset_scale
        keep = []
        for z in ZOOM_LEVELS:
            if self.view.w / (z * a) > self.world_w * 1.08:
                continue
            if self.view.h / (z * a) > self.world_h * 1.08:
                continue
            if (self.view.w / z) * (self.view.h / z) > MAX_SCENE_PX:
                continue
            keep.append(z)
        return tuple(keep) if len(keep) >= 2 else ZOOM_LEVELS[-2:]

    def set_view(self, view_rect, asset_scale=None):
        """React to a resolution change."""
        center = self.center
        self.view = view_rect
        if asset_scale is not None:
            self.asset_scale = float(asset_scale)
        self.levels = self._usable_levels()
        self.zoom_index = int(clamp(self.zoom_index, 0, len(self.levels) - 1))
        self.center_on(*center)

    # -------------------------------------------------------------- geometry --
    @property
    def scene_zoom(self):
        """The ratio between sprite pixels and screen pixels."""
        return self.levels[self.zoom_index]

    @property
    def zoom(self):
        """Screen pixels per world pixel."""
        return self.levels[self.zoom_index] * self.asset_scale

    @property
    def vw(self):
        """Visible width in world units."""
        return self.view.w / self.zoom

    @property
    def vh(self):
        return self.view.h / self.zoom

    def clamp_pos(self):
        self.x = clamp(self.x, 0.0, max(0.0, self.world_w - self.vw))
        self.y = clamp(self.y, 0.0, max(0.0, self.world_h - self.vh))

    def center_on(self, wx, wy):
        self.x = wx - self.vw * 0.5
        self.y = wy - self.vh * 0.5
        self.clamp_pos()

    @property
    def center(self):
        return (self.x + self.vw * 0.5, self.y + self.vh * 0.5)

    def set_zoom(self, index, anchor=None):
        index = int(clamp(index, 0, len(self.levels) - 1))
        if index == self.zoom_index:
            return
        if anchor is None:
            cx, cy = self.center
            self.zoom_index = index
            self.center_on(cx, cy)
        else:
            wx, wy = self.screen_to_world(*anchor)
            rx = (anchor[0] - self.view.x) / float(self.view.w)
            ry = (anchor[1] - self.view.y) / float(self.view.h)
            self.zoom_index = index
            self.x = wx - rx * self.vw
            self.y = wy - ry * self.vh
            self.clamp_pos()

    # ----------------------------------------------------------- conversions --
    def world_to_screen(self, wx, wy):
        z = self.zoom
        return (self.view.x + (wx - self.x) * z, self.view.y + (wy - self.y) * z)

    def screen_to_world(self, sx, sy):
        z = self.zoom
        return ((sx - self.view.x) / z + self.x, (sy - self.view.y) / z + self.y)

    def world_rect(self):
        return (self.x, self.y, self.vw, self.vh)

    def visible_tiles(self, pad=2):
        t0x = max(0, int(self.x // TILE) - pad)
        t0y = max(0, int(self.y // TILE) - pad)
        t1x = int((self.x + self.vw) // TILE) + pad
        t1y = int((self.y + self.vh) // TILE) + pad
        return t0x, t0y, t1x, t1y

    # ------------------------------------------------------------- camera keys --
    @staticmethod
    def _held(keys, code):
        return code is not None and keys[code]

    def _camera_codes(self):
        """The four scroll keys as pygame codes, resolved once per remapping."""
        if self._codes_rev == keymap.revision() and self._codes is not None:
            return self._codes
        import pygame
        codes = {}
        for binding in ("camera.left", "camera.right", "camera.up",
                        "camera.down"):
            name = keymap.key_for(binding)
            try:
                codes[binding] = pygame.key.key_code(name) if name else None
            except ValueError:
                codes[binding] = None   # a hand-written file can name anything
        self._codes = codes
        self._codes_rev = keymap.revision()
        return codes

    # ----------------------------------------------------------------- update --
    def update(self, dt, keys, mouse_pos, mouse_in_window, edge_scroll=True):
        import pygame
        dx = dy = 0.0
        left = keys[pygame.K_LEFT]
        right = keys[pygame.K_RIGHT]
        up = keys[pygame.K_UP]
        down = keys[pygame.K_DOWN]
        if not CAMERA_ARROWS_ONLY:      # the letter keys, ZQSD or WASD or else
            codes = self._camera_codes()
            left = left or self._held(keys, codes["camera.left"])
            right = right or self._held(keys, codes["camera.right"])
            up = up or self._held(keys, codes["camera.up"])
            down = down or self._held(keys, codes["camera.down"])
        dx -= 1.0 if left else 0.0
        dx += 1.0 if right else 0.0
        dy -= 1.0 if up else 0.0
        dy += 1.0 if down else 0.0

        # Edge scrolling is proportional to how deep the cursor sits in the
        # sensitive band: gentle when brushing it, brisk in the corner. It can
        # be switched off (menu or F7) because it gets in the way when aiming
        # at the panel edges.
        if edge_scroll and self.edge_scroll and mouse_in_window:
            mx, my = mouse_pos
            m = float(EDGE_SCROLL_MARGIN)
            k = EDGE_SCROLL_SPEED
            if mx <= m:
                dx -= (m - mx) / m * k
            elif mx >= self.view.right - m:
                dx += (mx - (self.view.right - m)) / m * k
            if my <= m:
                dy -= (m - my) / m * k
            elif my >= self.view.bottom - m:
                dy += (my - (self.view.bottom - m)) / m * k

        if dx or dy:
            n = max(1.0, math.hypot(dx, dy))
            sp = CAM_SPEED * dt / self.zoom
            self.x += dx / n * sp
            self.y += dy / n * sp
            self.clamp_pos()

        if self.shake > 0.0:
            import random
            self.shake = max(0.0, self.shake - dt * 2.4)
            a = self.shake * 7.0
            self._shake_off = (random.uniform(-a, a), random.uniform(-a, a))
        else:
            self._shake_off = (0.0, 0.0)

    def add_shake(self, amount):
        self.shake = min(1.0, self.shake + amount)

    @property
    def shake_offset(self):
        return self._shake_off

    def pan(self, dx_screen, dy_screen):
        self.x -= dx_screen / self.zoom
        self.y -= dy_screen / self.zoom
        self.clamp_pos()

# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Interface scaling according to the window resolution.

Every interface size is written in "units" calibrated on a reference window of
1280x760. `Layout` converts those units into pixels for the actual resolution,
so that the game stays readable both at 1280x760 and at 2880x1800.
"""

import pygame

from .settings import (HUD_H, SCREEN_H, SCREEN_W, TOPBAR_H, UI_REF_H,
                       UI_SCALE_MAX, UI_SCALE_MIN)
from .utils import clamp


def ui_scale_for(height):
    """The interface scale factor for a given window height."""
    return clamp(round(height / float(UI_REF_H), 2),
                 UI_SCALE_MIN, UI_SCALE_MAX)


def asset_scale_for(height):
    """Sprite generation scale: clean steps rather than a continuum.

    We stick to 1, 1.5 or 2: zoom level 1.0 then shows one sprite pixel per
    screen pixel, hence no image resampling at all.
    """
    scale = ui_scale_for(height)
    for step in (1.0, 1.5, 2.0):
        if scale <= step + 0.24:
            return step
    return 2.0


class Layout(object):
    def __init__(self, width=SCREEN_W, height=SCREEN_H):
        self.resize(width, height)

    def resize(self, width, height):
        self.w = int(width)
        self.h = int(height)
        self.scale = ui_scale_for(self.h)
        self.asset_scale = asset_scale_for(self.h)
        self.topbar = self.u(TOPBAR_H)
        self.hud = self.u(HUD_H)
        self.view = pygame.Rect(0, self.topbar, self.w,
                                max(120, self.h - self.topbar - self.hud))
        return self

    def u(self, value):
        """Interface units -> pixels."""
        return int(round(value * self.scale))

    @property
    def size(self):
        return (self.w, self.h)

    def __repr__(self):
        return "<Layout %dx%d scale %.2f sprites x%.1f>" % (
            self.w, self.h, self.scale, self.asset_scale)

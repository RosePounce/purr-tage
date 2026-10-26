# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Procedural art: every visual is drawn by the code, no asset at all.

The surfaces are painted supersampled (x3) then scaled down with
`smoothscale`, which gives smoothed outlines for free. Everything is cached:
the cost is paid only once, at start-up.
"""

import math
import random

import pygame

from .settings import (BUILDINGS, C_FLOWER, C_GRASS, C_MEADOW, C_SAND,
                       C_WATER, C_WATER_DEEP, RES_COLOR, R_CATNIP, R_KIBBLE,
                       R_STONE, R_WOOL, TILE, T_FLOWER, T_GRASS, T_MEADOW, T_SAND,
                       T_WATER, UNITS)
from .utils import mix, shade

SS = 3                      # base supersampling factor

# Sprite generation scale, in screen pixels per world pixel. Raised on large
# resolutions so that the cats stay crisp.
ASSET_SCALE = 1.0

_unit_cache = {}
_build_cache = {}
_node_cache = {}
_tile_cache = {}
_decor_cache = {}
_icon_cache = {}
_misc_cache = {}

# Which cat art to draw. This branch introduced a new, rounder look; the
# classic profile cats are kept so the player can switch back from the
# options. Flipped through `set_cat_style`, remembered in the preferences.
CLASSIC_CATS = False

# The colour worn by each team for this game. Sprites are cached by team index
# (0/1), so a game with two factions just swaps this table and the cache
# follows. `None` until first read: the defaults come from the settings.
_team_colors = None


def team_color(team):
    """The active colour of a team, defaulting to the settings palette."""
    global _team_colors
    if _team_colors is None:
        from .settings import TEAM_COLORS
        _team_colors = [tuple(c) for c in TEAM_COLORS]
    return _team_colors[team % len(_team_colors)]


def set_team_colors(colors):
    """Set the per-team colours for the current game or menu.

    Drops the sprite and icon caches so the new colours show at once. A no-op
    when the colours are already the ones asked for, so it is cheap to call
    every frame from a screen that simply wants to assert its palette.
    """
    global _team_colors
    cols = [tuple(c) for c in colors]
    if _team_colors == cols:
        return
    _team_colors = cols
    _unit_cache.clear()
    _build_cache.clear()
    _icon_cache.clear()

# Coats of the various cat breeds
FUR = {
    "kitten":    ((246, 226, 196), (214, 186, 150), (120, 96, 76)),
    "scratcher": ((226, 152, 84), (196, 118, 58), (108, 62, 32)),
    "spitter":   ((178, 182, 192), (142, 148, 160), (74, 78, 90)),
    "tomcat":    ((104, 92, 90), (74, 64, 64), (36, 30, 32)),
}
EYE = {
    "kitten": (118, 196, 142), "scratcher": (236, 196, 86),
    "spitter": (122, 190, 226), "tomcat": (236, 134, 86),
}


def set_asset_scale(scale):
    """Change the generation scale and clear the caches it affects."""
    global ASSET_SCALE
    scale = float(scale)
    if abs(scale - ASSET_SCALE) < 1e-6:
        return
    ASSET_SCALE = scale
    for cache in (_unit_cache, _build_cache, _node_cache, _tile_cache,
                  _decor_cache, _icon_cache, _misc_cache):
        cache.clear()


def tile_px():
    """The size of a terrain tile in sprite pixels."""
    return max(1, int(round(TILE * ASSET_SCALE)))


def _supersample():
    """No point supersampling 3x what is already drawn at double size."""
    return max(2.0, SS / ASSET_SCALE)


class _P(object):
    """A tiny painter in logical coordinates, rendered supersampled."""

    def __init__(self, w, h, ss=None):
        ss = _supersample() if ss is None else ss
        self.w, self.h, self.ss = w, h, ss
        self.surf = pygame.Surface((max(1, int(w * ss)), max(1, int(h * ss))),
                                   pygame.SRCALPHA)

    def _p(self, x, y):
        return (int(round(x * self.ss)), int(round(y * self.ss)))

    def ell(self, color, cx, cy, rx, ry):
        s = self.ss
        pygame.draw.ellipse(self.surf, color, pygame.Rect(
            int((cx - rx) * s), int((cy - ry) * s),
            max(1, int(rx * 2 * s)), max(1, int(ry * 2 * s))))

    def circ(self, color, cx, cy, r):
        pygame.draw.circle(self.surf, color, self._p(cx, cy), max(1, int(r * self.ss)))

    def rect(self, color, x, y, w, h, radius=0):
        s = self.ss
        r = pygame.Rect(int(x * s), int(y * s), max(1, int(w * s)), max(1, int(h * s)))
        if radius:
            pygame.draw.rect(self.surf, color, r, border_radius=int(radius * s))
        else:
            pygame.draw.rect(self.surf, color, r)

    def poly(self, color, pts):
        pygame.draw.polygon(self.surf, color, [self._p(*p) for p in pts])

    def line(self, color, a, b, width=1.0):
        pygame.draw.line(self.surf, color, self._p(*a), self._p(*b),
                         max(1, int(width * self.ss)))

    def curve(self, color, pts, width=1.0):
        if len(pts) > 1:
            pygame.draw.lines(self.surf, color, False,
                              [self._p(*p) for p in pts], max(1, int(width * self.ss)))

    def done(self, w=None, h=None):
        w = int(w or self.w)
        h = int(h or self.h)
        return pygame.transform.smoothscale(self.surf, (max(1, w), max(1, h)))


# -------------------------------------------------------------------- cats ----
def _draw_cat_new(utype, team_color, frame):
    """A chibi cat: a big round head over a small body. `frame` 0..3 walks.

    Drawn facing right; `unit_sprite` flips it the other way. The head is
    almost front-on -- two big eyes and round cheeks read far cuter than a
    strict profile -- while the body stays in three-quarter view.
    """
    scale = {"kitten": 0.80, "scratcher": 1.0, "spitter": 0.94,
             "tomcat": 1.26}[utype] * ASSET_SCALE
    w, h = 42 * scale, 42 * scale
    p = _P(w, h)
    base, dark, outline = FUR[utype]
    accent = mix(team_color, (255, 255, 255), 0.10)
    light = mix(base, (255, 255, 255), 0.35)
    cheek = mix(base, (240, 120, 140), 0.45)
    pink = (244, 150, 166)

    bob = (0.0, -0.8, 0.0, 0.8)[frame % 4] * scale
    swing = (1.0, 0.0, -1.0, 0.0)[frame % 4]

    cx, cy = w * 0.42, h * 0.66 + bob
    bw, bh = w * 0.27, h * 0.23

    # drop shadow (its own surface: the only true-alpha stroke)
    _ss = p.ss
    sh = pygame.Surface((max(1, int(bw * 2.3 * _ss)), max(1, int(bh * 0.8 * _ss))),
                        pygame.SRCALPHA)
    pygame.draw.ellipse(sh, (0, 0, 0, 65), sh.get_rect())
    p.surf.blit(sh, (int((cx - bw * 1.15) * _ss), int((h * 0.90) * _ss)))

    rim = 0.9 * scale          # shared soft-outline width

    # curled tail: thick, outlined, with a soft rounded tip
    tail = []
    for i in range(10):
        t = i / 9.0
        tx = cx - bw * 0.90 - math.sin(t * 2.2) * w * 0.15
        ty = cy - bh * 0.1 - t * h * 0.33 + math.sin(t * 3.0 + frame) * 1.0 * scale
        tail.append((tx, ty))
    p.curve(outline, tail, 4.4 * scale)
    p.curve(base, tail, 2.8 * scale)
    p.circ(outline, tail[-1][0], tail[-1][1], 2.2 * scale)
    p.circ(accent, tail[-1][0], tail[-1][1], 1.5 * scale)

    # round body, same outlined-sticker treatment as the head
    p.ell(outline, cx, cy, bw + 1.0 * scale, bh + 1.0 * scale)
    p.ell(base, cx, cy, bw, bh)
    p.ell(light, cx - bw * 0.20, cy - bh * 0.25, bw * 0.55, bh * 0.45)   # back sheen
    p.ell(mix(base, (255, 255, 255), 0.45),
          cx + bw * 0.18, cy + bh * 0.32, bw * 0.55, bh * 0.46)          # belly
    # soft rounded tabby stripes instead of hard dark lines
    stripe = mix(dark, base, 0.45)
    for i in range(2):
        sx = cx - bw * 0.30 + i * bw * 0.45
        p.curve(stripe, [(sx, cy - bh * 0.72),
                         (sx - 1.4 * scale, cy - bh * 0.30),
                         (sx - 0.6 * scale, cy + bh * 0.05)], 1.7 * scale)

    # stubby bean paws, drawn over the body's lower edge so they peek out
    paw_w, paw_h = w * 0.12, h * 0.13
    for i, lx in enumerate((cx - bw * 0.52, cx - bw * 0.16,
                            cx + bw * 0.22, cx + bw * 0.56)):
        s = (swing if i % 2 == 0 else -swing) * 1.1 * scale
        col = dark if i < 2 else base
        px, py = lx - paw_w * 0.5 + s, cy + bh * 0.62
        p.rect(outline, px - rim, py - rim, paw_w + 2 * rim, paw_h + 2 * rim,
               radius=(paw_w + 2 * rim) * 0.5)
        p.rect(col, px, py, paw_w, paw_h, radius=paw_w * 0.5)
        p.ell(mix(col, (255, 255, 255), 0.25), px + paw_w * 0.5, py + paw_h * 0.30,
              paw_w * 0.30, paw_h * 0.22)                      # tiny toe highlight

    # the tomcat's breastplate sits on the chest: over the body, under the head
    if utype == "tomcat":
        bx, by = cx - bw * 0.39, cy - bh * 0.077
        p.rect(outline, bx - bw * 0.48, by - bh * 0.48, bw * 1.26, bh * 0.86,
               radius=2.0 * scale)                                # breastplate rim
        p.rect(mix((150, 152, 164), accent, 0.4), bx - bw * 0.45, by - bh * 0.45,
               bw * 1.20, bh * 0.80, radius=1.8 * scale)          # breastplate
        for i in range(3):
            p.circ(outline, bx - bw * 0.20 + i * bw * 0.35, by - bh * 0.05,
                   1.4 * scale)
            p.circ((210, 214, 224), bx - bw * 0.20 + i * bw * 0.35,
                   by - bh * 0.05, 0.9 * scale)                   # rivets

    # big head, almost front-on
    hr = w * 0.26
    hx, hy = cx + bw * 0.72, cy - bh * 1.02
    # ears (behind the head): rounded outer + pink inner
    for sgn in (-1, 1):
        ex = hx + sgn * hr * 0.60
        p.poly(outline, [(ex - hr * 0.34, hy - hr * 0.35),
                         (ex + hr * 0.34, hy - hr * 0.35),
                         (ex + sgn * hr * 0.12, hy - hr * 1.20)])
        p.poly(mix(pink, base, 0.45),
               [(ex - hr * 0.18, hy - hr * 0.42),
                (ex + hr * 0.18, hy - hr * 0.42),
                (ex + sgn * hr * 0.06, hy - hr * 0.98)])
    p.circ(outline, hx, hy, hr + 1.0 * scale)
    p.circ(base, hx, hy, hr)
    p.ell(light, hx - hr * 0.30, hy - hr * 0.30, hr * 0.50, hr * 0.42)   # forehead sheen

    # eyes: big, two of them, each with a sparkle
    eye_y = hy + hr * 0.10
    for sgn in (-1, 1):
        ex = hx + sgn * hr * 0.42
        p.ell(outline, ex, eye_y, hr * 0.30, hr * 0.37)
        p.ell(EYE[utype], ex, eye_y, hr * 0.24, hr * 0.31)
        p.ell((34, 30, 36), ex, eye_y + hr * 0.04, hr * 0.15, hr * 0.22)
        p.circ((255, 255, 255), ex - sgn * hr * 0.08, eye_y - hr * 0.12, hr * 0.10)
        p.circ((255, 255, 255), ex + sgn * hr * 0.07, eye_y + hr * 0.10, hr * 0.045)

    # rosy cheeks
    for sgn in (-1, 1):
        p.ell(cheek, hx + sgn * hr * 0.52, eye_y + hr * 0.42, hr * 0.19, hr * 0.13)

    # nose + ":3" mouth
    nose_y = eye_y + hr * 0.46
    p.poly(pink, [(hx - hr * 0.10, nose_y), (hx + hr * 0.10, nose_y),
                  (hx, nose_y + hr * 0.13)])
    p.curve(outline, [(hx, nose_y + hr * 0.13),
                      (hx - hr * 0.13, nose_y + hr * 0.30),
                      (hx - hr * 0.24, nose_y + hr * 0.17)], 0.8 * scale)
    p.curve(outline, [(hx, nose_y + hr * 0.13),
                      (hx + hr * 0.13, nose_y + hr * 0.30),
                      (hx + hr * 0.24, nose_y + hr * 0.17)], 0.8 * scale)
    # whiskers
    whisker = mix(outline, (255, 255, 255), 0.5)
    for dy in (-0.04, 0.14):
        for sgn in (-1, 1):
            p.line(whisker, (hx + sgn * hr * 0.50, nose_y + hr * dy),
                   (hx + sgn * hr * 1.15, nose_y + hr * (dy - 0.12)), 0.6 * scale)

    # a little gear per class, kept soft and round to match the face
    if utype == "kitten":
        sx0, sy0 = cx - bw * 0.98, cy - bh * 0.15
        sw, sh2 = bw * 0.72, bh * 0.95
        p.rect(outline, sx0 - rim, sy0 - rim, sw + 2 * rim, sh2 + 2 * rim,
               radius=2.4 * scale)                                # satchel rim
        p.rect(mix((196, 150, 96), accent, 0.25), sx0, sy0, sw, sh2,
               radius=1.8 * scale)                                # satchel
        p.curve(mix((120, 94, 60), base, 0.1),
                [(sx0 + sw * 0.11, sy0 - 0.6 * scale),
                 (sx0 + sw * 0.61, sy0 - bh * 0.40),
                 (sx0 + sw * 0.90, sy0 - 0.13 * scale)], 1.4 * scale)  # handle arching over the satchel
        p.ell((120, 94, 60), sx0 + sw * 0.5, sy0 + sh2 * 0.32,
              sw * 0.26, sh2 * 0.14)                              # clasp
    elif utype == "scratcher":
        p.rect(outline, hx - hr * 0.98, hy - hr * 0.54, hr * 1.96, hr * 0.42,
               radius=hr * 0.2)                                   # headband rim
        p.rect(accent, hx - hr * 0.95, hy - hr * 0.50, hr * 1.90, hr * 0.34,
               radius=hr * 0.17)                                  # headband
        for k in range(3):                                        # three soft claws
            clx = cx + bw * (0.18 + k * 0.17)
            p.circ(outline, clx, cy + bh * 0.95, 1.9 * scale)
            p.circ((228, 228, 236), clx, cy + bh * 0.95, 1.2 * scale)
    # the spitter wears nothing here, and the tomcat's breastplate is drawn
    # earlier (under the head)

    return p.done(w, h)


def _draw_cat_classic(utype, team_color, frame):
    """A cat seen in profile, facing right. `frame` 0..3 = the walk cycle."""
    scale = {"kitten": 0.80, "scratcher": 1.0, "spitter": 0.94,
             "tomcat": 1.26}[utype] * ASSET_SCALE
    w, h = 44 * scale, 38 * scale
    p = _P(w, h)
    base, dark, outline = FUR[utype]
    accent = mix(team_color, (255, 255, 255), 0.10)

    bob = (0.0, -0.7, 0.0, 0.7)[frame % 4] * scale
    swing = (1.0, 0.0, -1.0, 0.0)[frame % 4]

    cx, cy = w * 0.47, h * 0.60 + bob
    bw, bh = w * 0.27, h * 0.19

    # drop shadow
    _ss = p.ss
    sh = pygame.Surface((max(1, int(bw * 2.2 * _ss)), max(1, int(bh * 0.9 * _ss))),
                        pygame.SRCALPHA)
    pygame.draw.ellipse(sh, (0, 0, 0, 70), sh.get_rect())
    p.surf.blit(sh, (int((cx - bw * 1.1) * _ss), int((h * 0.86) * _ss)))

    # paws (two planes, animated in opposition)
    leg_w, leg_h = w * 0.072, h * 0.20
    for i, lx in enumerate((cx - bw * 0.62, cx - bw * 0.18,
                            cx + bw * 0.34, cx + bw * 0.72)):
        s = swing if i % 2 == 0 else -swing
        col = dark if i < 2 else base
        p.rect(col, lx - leg_w * 0.5 + s * 0.9 * scale, cy + bh * 0.45,
               leg_w, leg_h - abs(s) * 0.8 * scale, radius=leg_w * 0.5)
        p.ell(outline, lx + s * 0.9 * scale, cy + bh * 0.45 + leg_h - 1.0 * scale,
              leg_w * 0.62, leg_w * 0.42)

    # tail: a curve raised up behind the cat
    tail = []
    for i in range(9):
        t = i / 8.0
        tx = cx - bw * 0.95 - t * w * 0.19
        ty = cy - t * t * h * 0.34 + math.sin(t * 3.0 + frame) * 1.1 * scale
        tail.append((tx, ty))
    p.curve(outline, tail, 3.4 * scale)
    p.curve(base, tail, 2.3 * scale)
    p.ell(accent, tail[-1][0], tail[-1][1], 1.9 * scale, 1.9 * scale)

    # body
    p.ell(outline, cx, cy, bw + 0.9 * scale, bh + 0.9 * scale)
    p.ell(base, cx, cy, bw, bh)
    p.ell(mix(base, (255, 255, 255), 0.22), cx + bw * 0.1, cy + bh * 0.3,
          bw * 0.62, bh * 0.44)
    # tabby stripes
    for i in range(3):
        sx = cx - bw * 0.45 + i * bw * 0.42
        p.line(dark, (sx, cy - bh * 0.78), (sx - 1.2 * scale, cy - bh * 0.1),
               1.5 * scale)

    # head
    hx, hy = cx + bw * 0.95, cy - bh * 0.95
    hr = w * 0.155
    # ears
    for sgn, ox in ((-1, -hr * 0.52), (1, hr * 0.56)):
        p.poly(outline, [(hx + ox - hr * 0.42, hy - hr * 0.42),
                         (hx + ox + hr * 0.30, hy - hr * 0.40),
                         (hx + ox - hr * 0.05, hy - hr * 1.48)])
        p.poly(mix(accent, base, 0.35),
               [(hx + ox - hr * 0.26, hy - hr * 0.50),
                (hx + ox + hr * 0.18, hy - hr * 0.48),
                (hx + ox - hr * 0.04, hy - hr * 1.18)])
    p.circ(outline, hx, hy, hr + 0.9 * scale)
    p.circ(base, hx, hy, hr)
    p.ell(mix(base, (255, 255, 255), 0.30), hx + hr * 0.25, hy + hr * 0.3,
          hr * 0.6, hr * 0.48)
    # muzzle + nose + whiskers
    p.ell(mix(base, (255, 255, 255), 0.55), hx + hr * 0.52, hy + hr * 0.30,
          hr * 0.44, hr * 0.33)
    p.poly((226, 132, 150), [(hx + hr * 0.80, hy + hr * 0.10),
                             (hx + hr * 1.02, hy + hr * 0.10),
                             (hx + hr * 0.91, hy + hr * 0.30)])
    for dy in (-0.12, 0.10, 0.32):
        p.line(mix(outline, (255, 255, 255), 0.45),
               (hx + hr * 0.72, hy + hr * (0.20 + dy)),
               (hx + hr * 1.70, hy + hr * (0.02 + dy * 1.7)), 0.75 * scale)
    # eyes
    p.ell(EYE[utype], hx + hr * 0.42, hy - hr * 0.12, hr * 0.21, hr * 0.26)
    p.line((20, 18, 22), (hx + hr * 0.42, hy - hr * 0.34),
           (hx + hr * 0.42, hy + hr * 0.10), 0.9 * scale)
    p.circ((255, 255, 255), hx + hr * 0.50, hy - hr * 0.24, hr * 0.08)

    # team marking + gear depending on the class
    p.ell(accent, hx - hr * 0.12, hy + hr * 0.92, hr * 0.62, hr * 0.22)   # collar
    p.circ((250, 220, 110), hx - hr * 0.12, hy + hr * 1.06, hr * 0.14)    # medal

    if utype == "kitten":
        p.rect(mix((196, 150, 96), accent, 0.25), cx - bw * 0.95, cy - bh * 1.5,
               bw * 0.8, bh * 1.1, radius=1.6 * scale)     # satchel
        p.line((120, 94, 60), (cx - bw * 0.6, cy - bh * 1.4),
               (cx + bw * 0.2, cy - bh * 0.6), 1.1 * scale)
    elif utype == "scratcher":
        p.rect(accent, hx - hr * 1.0, hy - hr * 0.58, hr * 2.0, hr * 0.40,
               radius=hr * 0.2)                            # headband
        p.poly((228, 228, 236), [(cx + bw * 0.1, cy + bh * 0.6),
                                 (cx + bw * 0.5, cy + bh * 1.5),
                                 (cx + bw * 0.28, cy + bh * 0.6)])  # claw
    elif utype == "spitter":
        p.poly(accent, [(hx - hr * 0.7, hy + hr * 0.85),
                        (hx + hr * 0.5, hy + hr * 0.95),
                        (hx - hr * 0.3, hy + hr * 2.0)])   # scarf
        p.ell((150, 146, 140), cx - bw * 0.2, cy - bh * 1.35, bw * 0.3, bh * 0.3)
    else:  # tomcat
        p.rect(mix((150, 152, 164), accent, 0.4), cx - bw * 0.5, cy - bh * 1.05,
               bw * 1.3, bh * 0.85, radius=1.8 * scale)    # breastplate
        for i in range(3):
            p.line((200, 204, 214), (cx - bw * 0.4 + i * bw * 0.4, cy - bh * 1.0),
                   (cx - bw * 0.4 + i * bw * 0.4, cy - bh * 0.25), 0.8 * scale)
        p.line((228, 160, 160), (hx - hr * 0.1, hy - hr * 0.6),
               (hx + hr * 0.3, hy + hr * 0.2), 1.0 * scale)  # scar

    return p.done(w, h)


def _draw_cat(utype, team_color, frame):
    """Draw a cat in whichever style the player has chosen."""
    draw = _draw_cat_classic if CLASSIC_CATS else _draw_cat_new
    return draw(utype, team_color, frame)


def set_cat_style(classic):
    """Switch between the classic (profile) cats and the new ones.

    Drops the sprite and icon caches so the change shows at once, in game and
    in the menus alike. A no-op when the style is already the one asked for.
    """
    global CLASSIC_CATS
    classic = bool(classic)
    if classic == CLASSIC_CATS:
        return
    CLASSIC_CATS = classic
    _unit_cache.clear()
    _icon_cache.clear()


def unit_sprite(utype, team, frame=0, facing=1):
    key = (utype, team, frame % 4, facing)
    surf = _unit_cache.get(key)
    if surf is None:
        surf = _draw_cat(utype, team_color(team), frame % 4)
        if facing < 0:
            surf = pygame.transform.flip(surf, True, False)
        _unit_cache[key] = surf
    return surf


# --------------------------------------------------------------- buildings ----
def _draw_building(btype, team_color, px, level=1):
    p = _P(px, px)
    accent = team_color
    wood = (156, 112, 70)
    wood_d = (112, 76, 46)
    W = px

    if btype == "wall":
        return _draw_wall(team_color, px, 0)

    # ground shadow
    _ss = p.ss
    sh = pygame.Surface((max(1, int(W * 0.92 * _ss)), max(1, int(W * 0.22 * _ss))),
                        pygame.SRCALPHA)
    pygame.draw.ellipse(sh, (0, 0, 0, 80), sh.get_rect())
    p.surf.blit(sh, (int(W * 0.04 * _ss), int(W * 0.76 * _ss)))

    if btype == "basket":
        # a big wicker basket with a cushion and a pennant
        p.ell((122, 86, 52), W * 0.5, W * 0.80, W * 0.42, W * 0.13)
        p.rect(mix(wood, (220, 190, 140), 0.35), W * 0.12, W * 0.42,
               W * 0.76, W * 0.40, radius=W * 0.10)
        for i in range(5):                                  # weave
            y = W * 0.46 + i * W * 0.075
            p.line(wood_d, (W * 0.13, y), (W * 0.87, y), W * 0.016)
        for i in range(9):
            x = W * 0.15 + i * W * 0.0875
            p.line(mix(wood, (240, 210, 160), 0.2), (x, W * 0.43), (x, W * 0.81),
                   W * 0.012)
        p.ell(mix(accent, (255, 255, 255), 0.25), W * 0.5, W * 0.45,
              W * 0.38, W * 0.12)                            # cushion
        p.ell(accent, W * 0.5, W * 0.43, W * 0.30, W * 0.08)
        p.line(wood_d, (W * 0.78, W * 0.44), (W * 0.78, W * 0.10), W * 0.03)
        p.poly(accent, [(W * 0.78, W * 0.11), (W * 0.78, W * 0.27),
                        (W * 0.98, W * 0.19)])               # pennant
        p.circ((250, 220, 110), W * 0.78, W * 0.08, W * 0.035)
        # a small plush mouse sticking out
        p.ell((188, 180, 196), W * 0.34, W * 0.40, W * 0.07, W * 0.045)
        p.line((188, 180, 196), (W * 0.27, W * 0.40), (W * 0.19, W * 0.36), W * 0.014)

    elif btype == "shed":
        p.rect(wood, W * 0.18, W * 0.44, W * 0.64, W * 0.38, radius=W * 0.03)
        for i in range(4):
            y = W * 0.48 + i * W * 0.09
            p.line(wood_d, (W * 0.19, y), (W * 0.81, y), W * 0.015)
        p.poly(mix(accent, (90, 70, 70), 0.45),
               [(W * 0.10, W * 0.47), (W * 0.50, W * 0.17), (W * 0.90, W * 0.47)])
        p.poly(mix(accent, (255, 255, 255), 0.12),
               [(W * 0.14, W * 0.45), (W * 0.50, W * 0.21), (W * 0.86, W * 0.45)])
        p.ell((48, 40, 44), W * 0.50, W * 0.74, W * 0.13, W * 0.16)   # cat flap
        p.ell((70, 60, 66), W * 0.50, W * 0.70, W * 0.11, W * 0.12)
        p.circ((250, 228, 150), W * 0.72, W * 0.56, W * 0.055)        # window
        p.poly(accent, [(W * 0.50, W * 0.19), (W * 0.50, W * 0.30),
                        (W * 0.70, W * 0.25)])

    elif btype == "scratching_post":
        p.rect(mix(wood, (90, 90, 100), 0.3), W * 0.18, W * 0.72,
               W * 0.64, W * 0.13, radius=W * 0.03)           # base
        p.rect((188, 158, 118), W * 0.40, W * 0.22, W * 0.20, W * 0.52)
        for i in range(11):                                   # sisal rope
            y = W * 0.24 + i * W * 0.046
            p.line((152, 122, 84), (W * 0.40, y), (W * 0.60, y + W * 0.012),
                   W * 0.016)
        p.rect(mix(accent, (240, 240, 240), 0.2), W * 0.26, W * 0.14,
               W * 0.48, W * 0.10, radius=W * 0.02)           # platform
        p.line((120, 110, 110), (W * 0.70, W * 0.18), (W * 0.76, W * 0.38),
               W * 0.012)
        p.circ(mix(accent, (255, 255, 255), 0.3), W * 0.77, W * 0.42, W * 0.055)
        for i in range(3):                                    # claw marks
            x = W * 0.22 + i * W * 0.04
            p.line((226, 230, 236), (x, W * 0.50), (x + W * 0.05, W * 0.66),
                   W * 0.014)

    elif btype == "dojo":
        p.rect((88, 60, 48), W * 0.20, W * 0.50, W * 0.60, W * 0.32, radius=W * 0.02)
        p.rect((198, 176, 140), W * 0.24, W * 0.54, W * 0.52, W * 0.24)
        p.poly((168, 62, 58), [(W * 0.06, W * 0.52), (W * 0.50, W * 0.30),
                               (W * 0.94, W * 0.52), (W * 0.82, W * 0.52),
                               (W * 0.50, W * 0.36), (W * 0.18, W * 0.52)])
        p.poly(mix((168, 62, 58), (0, 0, 0), 0.25),
               [(W * 0.16, W * 0.33), (W * 0.50, W * 0.14),
                (W * 0.84, W * 0.33), (W * 0.74, W * 0.33),
                (W * 0.50, W * 0.20), (W * 0.26, W * 0.33)])
        p.rect((60, 48, 44), W * 0.44, W * 0.60, W * 0.12, W * 0.22)   # door
        p.circ((250, 206, 120), W * 0.26, W * 0.42, W * 0.05)          # lanterns
        p.circ((250, 206, 120), W * 0.74, W * 0.42, W * 0.05)
        p.rect(accent, W * 0.48, W * 0.06, W * 0.04, W * 0.12)
        p.poly(accent, [(W * 0.52, W * 0.06), (W * 0.52, W * 0.15),
                        (W * 0.70, W * 0.11)])
        p.circ((250, 240, 210), W * 0.50, W * 0.26, W * 0.045)         # paw emblem
        for a in range(3):
            ang = -2.4 + a * 0.7
            p.circ((250, 240, 210), W * 0.50 + math.cos(ang) * W * 0.055,
                   W * 0.26 + math.sin(ang) * W * 0.055, W * 0.018)

    else:  # tower
        p.rect((150, 146, 152), W * 0.28, W * 0.34, W * 0.44, W * 0.50,
               radius=W * 0.03)
        for i in range(4):                                     # stones
            y = W * 0.40 + i * W * 0.11
            p.line((112, 108, 116), (W * 0.29, y), (W * 0.71, y), W * 0.016)
        p.line((112, 108, 116), (W * 0.50, W * 0.34), (W * 0.50, W * 0.84), W * 0.014)
        p.rect(mix(accent, (160, 160, 170), 0.45), W * 0.22, W * 0.26,
               W * 0.56, W * 0.12, radius=W * 0.02)            # battlements
        for i in range(4):
            p.rect(mix(accent, (160, 160, 170), 0.45), W * 0.22 + i * W * 0.155,
                   W * 0.18, W * 0.10, W * 0.10)
        p.ell((48, 42, 46), W * 0.50, W * 0.56, W * 0.07, W * 0.09)  # arrow slit
        for i, off in enumerate((-0.09, 0.0, 0.09)):           # a big claw
            p.poly((236, 238, 244),
                   [(W * (0.50 + off) - W * 0.022, W * 0.18),
                    (W * (0.50 + off) + W * 0.022, W * 0.18),
                    (W * (0.50 + off), W * 0.03)])
        if level >= 2:
            # A stone skirt and the colours on a pole.
            p.rect((128, 124, 130), W * 0.22, W * 0.72, W * 0.56, W * 0.12,
                   radius=W * 0.02)
            p.line((112, 108, 116), (W * 0.36, W * 0.72), (W * 0.36, W * 0.84),
                   W * 0.014)
            p.line((112, 108, 116), (W * 0.64, W * 0.72), (W * 0.64, W * 0.84),
                   W * 0.014)
            p.line(wood_d, (W * 0.16, W * 0.70), (W * 0.16, W * 0.12), W * 0.025)
            p.poly(accent, [(W * 0.16, W * 0.13), (W * 0.16, W * 0.27),
                            (W * 0.02, W * 0.20)])
        if level >= 3:
            # A golden band under the battlements, a second flag.
            p.rect((236, 196, 96), W * 0.26, W * 0.38, W * 0.48, W * 0.04)
            p.line(wood_d, (W * 0.84, W * 0.70), (W * 0.84, W * 0.12), W * 0.025)
            p.poly(accent, [(W * 0.84, W * 0.13), (W * 0.84, W * 0.27),
                            (W * 0.98, W * 0.20)])
            p.circ((250, 220, 110), W * 0.50, W * 0.48, W * 0.035)
    return p.done(px, px)


# Which neighbours a block of rampart joins up with: one bit per side.
WALL_N, WALL_E, WALL_S, WALL_W = 1, 2, 4, 8


def _draw_wall(team_color, px, links):
    """One tile of rampart, shaped by the blocks next to it.

    Running east-west the wall shows its face, merlons on top. Running
    north-south it shows its walkway from above, merlons along both edges,
    and its face only where the column ends. `links` holds the WALL_* bits.
    """
    p = _P(px, px)
    W = px
    stone, stone_d = (156, 152, 150), (112, 108, 110)
    walk = (178, 174, 170)
    crest = mix(team_color, (160, 160, 170), 0.45)
    north, south = links & WALL_N, links & WALL_S
    across = links & (WALL_E | WALL_W)
    upright = (north or south) and not across
    x0, x1 = W * 0.18, W * 0.82             # edges of the north-south walkway

    def walkway(top, bottom):
        p.rect(walk, x0, top, x1 - x0, bottom - top)
        p.line(stone_d, (x0, top), (x0, bottom), W * 0.04)
        p.line(stone_d, (x1, top), (x1, bottom), W * 0.04)
        y = top
        while y < bottom - W * 0.02:                         # flagstones
            p.line(mix(walk, stone_d, 0.5), (x0, y), (x1, y), W * 0.02)
            y += W * 0.25
        y = top + W * 0.04
        while y < bottom - W * 0.06:                         # merlons
            h = min(W * 0.12, bottom - y)
            p.rect(crest, x0 - W * 0.02, y, W * 0.12, h, radius=W * 0.02)
            p.rect(crest, x1 - W * 0.10, y, W * 0.12, h, radius=W * 0.02)
            y += W * 0.25

    def face(left, right, top):
        p.rect(stone_d, left, top + W * 0.04, right - left, W * 0.96 - top)
        p.rect(stone, left, top, right - left, W * 0.94 - top)
        for i, y in enumerate((top + W * 0.18, top + W * 0.36)):  # mortar
            if y < W * 0.9:
                p.line(stone_d, (left, y), (right, y), W * 0.03)
        mid = (left + right) * 0.5
        p.line(stone_d, (mid, top + W * 0.18), (mid, top + W * 0.36), W * 0.03)
        p.rect(crest, left, top - W * 0.08, right - left, W * 0.10)

    def merlons(left, right, top):
        x = left + W * 0.04
        while x < right - W * 0.08:
            p.rect(crest, x, top, min(W * 0.36, right - x - W * 0.02), W * 0.14,
                   radius=W * 0.03)
            x += W * 0.50

    if upright:
        walkway(0 if north else W * 0.10, W if south else W * 0.62)
        if not south:                                        # end of the column
            face(x0, x1, W * 0.62)
        if not north:
            merlons(x0, x1, W * 0.02)
        return p.done(px, px)

    if north and south:
        # The column runs straight through; the east-west wall abuts it.
        if links & WALL_W:
            face(0, x0, W * 0.34)
            merlons(0, x0, W * 0.14)
        if links & WALL_E:
            face(x1, W, W * 0.34)
            merlons(x1, W, W * 0.14)
        walkway(0, W)
        return p.done(px, px)

    if north:                                                # behind the face
        walkway(0, W * 0.30)
    left = 0 if links & WALL_W else (x0 if links else W * 0.08)
    right = W if links & WALL_E else (x1 if links else W * 0.92)
    face(left, right, W * 0.34)
    merlons(left, right, W * 0.14)
    if south:                                                # in front of it
        walkway(W * 0.55, W)
    return p.done(px, px)


def wall_sprite(team, px, links):
    # Its own tag: ("wall", team, px, 1) is already the isolated block that
    # `building_sprite` caches for level 1, and a column foot has links == 1.
    key = ("wall-links", team, px, links)
    surf = _build_cache.get(key)
    if surf is None:
        surf = _draw_wall(team_color(team), px, links)
        _build_cache[key] = surf
    return surf


def building_sprite(btype, team, px, level=1):
    key = (btype, team, px, level)
    surf = _build_cache.get(key)
    if surf is None:
        surf = _draw_building(btype, team_color(team), px, level)
        _build_cache[key] = surf
    return surf


def scaffold_sprite(px, ratio):
    """Building site scaffolding (0..1 of progress)."""
    key = ("scaf", px, int(ratio * 8))
    surf = _misc_cache.get(key)
    if surf:
        return surf
    p = _P(px, px)
    W = px
    p.rect((176, 150, 110), W * 0.14, W * 0.80, W * 0.72, W * 0.06, radius=W * 0.02)
    for x in (0.18, 0.46, 0.76):
        p.line((196, 168, 124), (W * x, W * 0.82), (W * x, W * 0.30), W * 0.035)
    levels = max(1, int(1 + ratio * 3))
    for i in range(levels):
        y = W * (0.74 - i * 0.16)
        p.line((206, 180, 134), (W * 0.15, y), (W * 0.85, y), W * 0.03)
    p.poly((240, 206, 110), [(W * 0.60, W * 0.30), (W * 0.84, W * 0.30),
                             (W * 0.72, W * 0.14)])
    surf = p.done(px, px)
    _misc_cache[key] = surf
    return surf


# ------------------------------------------------------------------- nodes ----
def _draw_node(kind, variant, step):
    px = int(round((TILE + 14) * ASSET_SCALE))
    p = _P(px, px)
    W = px
    full = 0.45 + 0.55 * (step / 4.0)       # size depending on depletion

    _ss = p.ss
    sh = pygame.Surface((max(1, int(W * 0.6 * _ss)), max(1, int(W * 0.18 * _ss))),
                        pygame.SRCALPHA)
    pygame.draw.ellipse(sh, (0, 0, 0, 70), sh.get_rect())
    p.surf.blit(sh, (int(W * 0.20 * _ss), int(W * 0.70 * _ss)))

    if kind == R_KIBBLE:
        # a metal bowl filled with kibble
        p.ell((150, 154, 164), W * 0.5, W * 0.72, W * 0.38 * full, W * 0.13 * full)
        p.ell((188, 192, 202), W * 0.5, W * 0.60, W * 0.38 * full, W * 0.17 * full)
        p.ell((126, 130, 140), W * 0.5, W * 0.57, W * 0.31 * full, W * 0.12 * full)
        rng = random.Random(variant * 31 + step)
        for _ in range(int(14 * full) + 3):
            cx = W * 0.5 + rng.uniform(-0.25, 0.25) * W * full
            cy = W * 0.55 + rng.uniform(-0.06, 0.05) * W
            p.circ(mix(RES_COLOR[R_KIBBLE], (120, 70, 30), rng.random() * 0.5),
                   cx, cy, W * 0.045)
        if variant == 1:        # a fish bone
            p.line((236, 236, 240), (W * 0.18, W * 0.80), (W * 0.36, W * 0.80), W * 0.02)
            for i in range(3):
                p.line((236, 236, 240), (W * (0.22 + i * 0.06), W * 0.77),
                       (W * (0.22 + i * 0.06), W * 0.83), W * 0.015)

    elif kind == R_WOOL:
        # a ball of wool
        r = W * 0.34 * full
        base = RES_COLOR[R_WOOL] if variant != 2 else (168, 144, 226)
        p.circ(shade(base, 0.75), W * 0.5, W * 0.56, r)
        p.circ(base, W * 0.48, W * 0.54, r * 0.94)
        for i in range(5):
            a0 = i * 1.25
            pts = [(W * 0.48 + math.cos(a0 + t * 0.9) * r * (0.9 - t * 0.12),
                    W * 0.54 + math.sin(a0 + t * 0.9) * r * (0.55 - t * 0.06))
                   for t in range(6)]
            p.curve(shade(base, 0.6), pts, W * 0.016)
        p.circ(mix(base, (255, 255, 255), 0.35), W * 0.40, W * 0.46, r * 0.3)
        p.curve(shade(base, 0.65), [(W * 0.74, W * 0.58), (W * 0.84, W * 0.66),
                                    (W * 0.78, W * 0.76), (W * 0.88, W * 0.80)],
                W * 0.016)

    elif kind == R_STONE:
        # a heap of rocks; the second variant has moss, the third is slate
        rng = random.Random(variant * 23 + step)
        base = (RES_COLOR[R_STONE], (150, 160, 140), (140, 150, 170))[variant]
        rocks = [(0.50, 0.62, 0.20), (0.33, 0.68, 0.14), (0.67, 0.67, 0.15),
                 (0.42, 0.48, 0.13), (0.60, 0.47, 0.12)]
        for (rx, ry, rr) in rocks[:2 + int(3 * full)]:
            cx = W * (0.5 + (rx - 0.5) * full)
            cy = W * (0.7 - (0.7 - ry) * full)
            r = W * rr * (0.6 + 0.4 * full)
            tone = mix(base, (90, 88, 92), rng.random() * 0.25)
            p.ell(shade(tone, 0.7), cx, cy + r * 0.18, r * 1.1, r * 0.82)
            p.ell(tone, cx, cy, r * 1.05, r * 0.78)
            p.ell(mix(tone, (255, 255, 255), 0.3), cx - r * 0.3, cy - r * 0.3,
                  r * 0.35, r * 0.22)
        if variant == 1:
            p.ell((104, 150, 86), W * 0.44, W * 0.52, W * 0.07, W * 0.03)

    else:   # catnip
        rng = random.Random(variant * 17 + step)
        p.ell((92, 70, 48), W * 0.5, W * 0.78, W * 0.20, W * 0.065)
        for i in range(int(8 * full) + 3):
            ang = -1.57 + rng.uniform(-1.0, 1.0)
            ln = W * (0.30 + rng.random() * 0.20) * full
            tipx = W * 0.5 + math.cos(ang) * ln
            tipy = W * 0.74 + math.sin(ang) * ln
            p.poly(mix(RES_COLOR[R_CATNIP], (40, 110, 60), rng.random() * 0.6),
                   [(W * 0.5 - W * 0.055, W * 0.76), (W * 0.5 + W * 0.055, W * 0.76),
                    (tipx, tipy)])
        for _ in range(int(5 * full)):
            fx = W * 0.5 + rng.uniform(-0.22, 0.22) * W
            fy = W * 0.46 + rng.uniform(-0.12, 0.12) * W
            p.circ((176, 146, 220), fx, fy, W * 0.048)
            p.circ((214, 192, 240), fx, fy, W * 0.022)
    return p.done(px, px)


def node_sprite(kind, variant, ratio):
    step = max(0, min(4, int(ratio * 4.0 + 0.999)))
    key = (kind, variant % 3, step)
    surf = _node_cache.get(key)
    if surf is None:
        surf = _draw_node(kind, variant % 3, step)
        _node_cache[key] = surf
    return surf


# ----------------------------------------------------------------- terrain ----
def tile_sprite(terrain, variant):
    key = (terrain, variant)
    surf = _tile_cache.get(key)
    if surf:
        return surf
    rng = random.Random(terrain * 1000 + variant)
    TP = tile_px()
    s = pygame.Surface((TILE, TILE))
    if terrain == T_WATER:
        s.fill(C_WATER)
        for i in range(3):
            y = rng.randrange(TILE)
            pygame.draw.line(s, mix(C_WATER, C_WATER_DEEP, 0.7), (0, y), (TILE, y + 1))
        for _ in range(2):
            y = rng.randrange(TILE)
            x = rng.randrange(TILE - 10)
            pygame.draw.line(s, mix(C_WATER, (255, 255, 255), 0.25),
                             (x, y), (x + 8, y))
    elif terrain == T_SAND:
        s.fill(C_SAND)
        for _ in range(14):
            s.set_at((rng.randrange(TILE), rng.randrange(TILE)),
                     mix(C_SAND, (150, 130, 90), rng.random() * 0.6))
    else:
        base = {T_GRASS: C_GRASS, T_MEADOW: C_MEADOW, T_FLOWER: C_FLOWER}[terrain]
        s.fill(base)
        for _ in range(26):
            x, y = rng.randrange(TILE), rng.randrange(TILE)
            c = mix(base, (60, 100, 50) if rng.random() < 0.6 else (150, 190, 120),
                    rng.random() * 0.55)
            pygame.draw.line(s, c, (x, y), (x, y - rng.randint(1, 3)))
        if terrain == T_FLOWER:
            for _ in range(3):
                x, y = rng.randrange(2, TILE - 2), rng.randrange(2, TILE - 2)
                pygame.draw.circle(s, rng.choice(((238, 226, 150), (236, 180, 200),
                                                  (206, 220, 246))), (x, y), 1)
    if TP != TILE:
        s = pygame.transform.smoothscale(s, (TP, TP))
    _tile_cache[key] = s
    return s


def decor_sprite(variant):
    surf = _decor_cache.get(variant)
    if surf:
        return surf
    W = TILE * 0.7 * ASSET_SCALE
    p = _P(W, W)
    rng = random.Random(variant * 77)
    if variant == 0:                     # a tuft of grass
        for i in range(5):
            x = W * (0.25 + i * 0.12)
            p.line((78, 118, 64), (x, W * 0.78), (x + rng.uniform(-3, 3), W * 0.30),
                   1.2)
    elif variant == 1:                   # pebbles
        p.ell((136, 132, 138), W * 0.45, W * 0.68, W * 0.16, W * 0.11)
        p.ell((160, 156, 162), W * 0.60, W * 0.74, W * 0.09, W * 0.07)
    elif variant == 2:                   # small flowers
        for i in range(3):
            x = W * (0.3 + i * 0.2)
            p.line((92, 136, 72), (x, W * 0.8), (x, W * 0.5), 1.0)
            p.circ((242, 226, 150) if i % 2 else (236, 170, 194), x, W * 0.46, W * 0.07)
    else:                                # paw prints
        for i in range(2):
            cx, cy = W * (0.32 + i * 0.3), W * (0.70 - i * 0.22)
            p.ell((88, 110, 76), cx, cy, W * 0.07, W * 0.055)
            for a in range(3):
                ang = -2.3 + a * 0.75
                p.circ((88, 110, 76), cx + math.cos(ang) * W * 0.075,
                       cy + math.sin(ang) * W * 0.075, W * 0.025)
    surf = p.done(int(W), int(W))
    _decor_cache[variant] = surf
    return surf


# ------------------------------------------------------ odds & ends, icons ----
def node_halo(kind, px=None):
    """The halo shown under a node the mouse hovers over."""
    px = px or int(round((TILE + 26) * ASSET_SCALE))
    key = ("halo", kind, px)
    surf = _misc_cache.get(key)
    if surf:
        return surf
    color = RES_COLOR[kind]
    surf = pygame.Surface((px, px), pygame.SRCALPHA)
    steps = 9
    for i in range(steps, 0, -1):
        t = i / float(steps)
        r = px * 0.5 * t
        alpha = int(54 * (1.0 - t) + 16)
        pygame.draw.ellipse(surf, (color[0], color[1], color[2], alpha),
                            pygame.Rect(px * 0.5 - r, px * 0.5 - r * 0.72,
                                        r * 2, r * 1.44))
    ring = pygame.Rect(px * 0.09, px * 0.21, px * 0.82, px * 0.60)
    pygame.draw.ellipse(surf, (255, 255, 255, 210), ring, max(2, int(px * 0.045)))
    pygame.draw.ellipse(surf, (color[0], color[1], color[2], 255), ring,
                        max(1, int(px * 0.028)))
    _misc_cache[key] = surf
    return surf


def hairball_sprite():
    surf = _misc_cache.get("hairball")
    if surf:
        return surf
    A = ASSET_SCALE
    p = _P(14 * A, 14 * A)
    p.circ((118, 112, 110), 7 * A, 7 * A, 4.6 * A)
    p.circ((152, 146, 142), 6.2 * A, 6.0 * A, 3.4 * A)
    for a in range(8):
        ang = a * 0.785
        p.line((96, 90, 88),
               ((7 + math.cos(ang) * 3.4) * A, (7 + math.sin(ang) * 3.4) * A),
               ((7 + math.cos(ang) * 6.2) * A, (7 + math.sin(ang) * 6.2) * A), 0.9 * A)
    surf = p.done(int(14 * A), int(14 * A))
    _misc_cache["hairball"] = surf
    return surf


def resource_icon(kind, px=20):
    key = ("res", kind, px)
    surf = _icon_cache.get(key)
    if surf:
        return surf
    if px <= 15:
        # at a tiny size, a colored dot stays far more readable
        p = _P(px, px)
        c = RES_COLOR[kind]
        p.circ(shade(c, 0.55), px * 0.5, px * 0.52, px * 0.40)
        p.circ(c, px * 0.5, px * 0.5, px * 0.34)
        p.circ(mix(c, (255, 255, 255), 0.5), px * 0.42, px * 0.40, px * 0.12)
        surf = p.done(px, px)
        _icon_cache[key] = surf
        return surf
    p = _P(px, px)
    W = px
    if kind == R_KIBBLE:
        p.ell((186, 190, 200), W * 0.5, W * 0.62, W * 0.40, W * 0.20)
        p.ell((126, 130, 140), W * 0.5, W * 0.56, W * 0.32, W * 0.14)
        for (dx, dy) in ((-0.14, 0.0), (0.0, -0.06), (0.14, 0.02), (0.05, 0.08)):
            p.circ(RES_COLOR[kind], W * (0.5 + dx), W * (0.54 + dy), W * 0.085)
    elif kind == R_WOOL:
        p.circ(shade(RES_COLOR[kind], 0.75), W * 0.5, W * 0.52, W * 0.34)
        p.circ(RES_COLOR[kind], W * 0.47, W * 0.49, W * 0.31)
        for i in range(4):
            a0 = i * 1.5
            p.curve(shade(RES_COLOR[kind], 0.6),
                    [(W * 0.47 + math.cos(a0 + t * 0.8) * W * 0.26,
                      W * 0.49 + math.sin(a0 + t * 0.8) * W * 0.16) for t in range(5)],
                    W * 0.05)
    elif kind == R_STONE:
        c = RES_COLOR[kind]
        p.ell(shade(c, 0.7), W * 0.40, W * 0.64, W * 0.30, W * 0.22)
        p.ell(c, W * 0.40, W * 0.60, W * 0.29, W * 0.21)
        p.ell(shade(c, 0.7), W * 0.66, W * 0.46, W * 0.22, W * 0.17)
        p.ell(mix(c, (255, 255, 255), 0.15), W * 0.66, W * 0.43, W * 0.21, W * 0.16)
        p.ell(mix(c, (255, 255, 255), 0.45), W * 0.32, W * 0.52, W * 0.09, W * 0.05)
    else:
        for ang in (-2.2, -1.57, -0.9):
            p.poly(RES_COLOR[kind], [(W * 0.44, W * 0.84), (W * 0.56, W * 0.84),
                                     (W * 0.5 + math.cos(ang) * W * 0.40,
                                      W * 0.80 + math.sin(ang) * W * 0.40)])
        p.circ((176, 146, 220), W * 0.5, W * 0.36, W * 0.10)
    surf = p.done(px, px)
    _icon_cache[key] = surf
    return surf


def upgrade_icon(key, px=38):
    """An upgrade icon: claws, fur (a shield), quick paws, a building level."""
    ckey = ("up", key, px)
    surf = _icon_cache.get(ckey)
    if surf:
        return surf
    p = _P(px, px)
    W = px
    if key == "claws":
        for i, off in enumerate((-0.17, 0.0, 0.17)):
            p.poly((236, 238, 246),
                   [(W * (0.5 + off) - W * 0.055, W * 0.80),
                    (W * (0.5 + off) + W * 0.055, W * 0.80),
                    (W * (0.5 + off) + W * 0.02, W * 0.16)])
            p.poly((176, 180, 192),
                   [(W * (0.5 + off) - W * 0.02, W * 0.78),
                    (W * (0.5 + off) + W * 0.02, W * 0.78),
                    (W * (0.5 + off) + W * 0.01, W * 0.26)])
        p.ell((206, 170, 120), W * 0.5, W * 0.84, W * 0.30, W * 0.09)
    elif key == "fur":
        p.poly((150, 162, 186), [(W * 0.5, W * 0.12), (W * 0.84, W * 0.28),
                                 (W * 0.78, W * 0.70), (W * 0.5, W * 0.90),
                                 (W * 0.22, W * 0.70), (W * 0.16, W * 0.28)])
        p.poly((196, 208, 228), [(W * 0.5, W * 0.20), (W * 0.76, W * 0.33),
                                 (W * 0.71, W * 0.66), (W * 0.5, W * 0.81),
                                 (W * 0.29, W * 0.66), (W * 0.24, W * 0.33)])
        p.ell((126, 110, 102), W * 0.5, W * 0.55, W * 0.16, W * 0.13)
        for a in range(3):
            ang = -2.35 + a * 0.78
            p.circ((126, 110, 102), W * 0.5 + math.cos(ang) * W * 0.21,
                   W * 0.52 + math.sin(ang) * W * 0.21, W * 0.055)
    elif key == "level":
        # a block of stone with two golden chevrons pointing up
        p.rect((112, 108, 110), W * 0.18, W * 0.62, W * 0.64, W * 0.26,
               radius=W * 0.03)
        p.rect((160, 156, 154), W * 0.18, W * 0.60, W * 0.64, W * 0.22,
               radius=W * 0.03)
        p.line((112, 108, 110), (W * 0.50, W * 0.60), (W * 0.50, W * 0.82),
               W * 0.04)
        for y in (0.14, 0.34):
            p.poly((240, 200, 100), [(W * 0.50, W * y), (W * 0.80, W * (y + 0.20)),
                                     (W * 0.66, W * (y + 0.20)),
                                     (W * 0.50, W * (y + 0.10)),
                                     (W * 0.34, W * (y + 0.20)),
                                     (W * 0.20, W * (y + 0.20))])
    else:   # quick paws
        p.ell((242, 206, 150), W * 0.58, W * 0.62, W * 0.19, W * 0.15)
        for a in range(4):
            ang = -2.55 + a * 0.58
            p.circ((242, 206, 150), W * 0.58 + math.cos(ang) * W * 0.26,
                   W * 0.58 + math.sin(ang) * W * 0.26, W * 0.065)
        for i, y in enumerate((0.32, 0.52, 0.72)):
            p.line((248, 228, 140), (W * 0.06, W * y),
                   (W * (0.26 - i * 0.03), W * y), W * 0.055)
    surf = p.done(px, px)
    _icon_cache[ckey] = surf
    return surf


def unit_icon(utype, team, px=44):
    key = ("u", utype, team, px)
    surf = _icon_cache.get(key)
    if surf is None:
        src = unit_sprite(utype, team, 0, 1)
        r = min(px / src.get_width(), px / src.get_height()) * 0.98
        surf = pygame.transform.smoothscale(
            src, (max(1, int(src.get_width() * r)), max(1, int(src.get_height() * r))))
        _icon_cache[key] = surf
    return surf


def building_icon(btype, team, px=44):
    key = ("b", btype, team, px)
    surf = _icon_cache.get(key)
    if surf is None:
        surf = building_sprite(btype, team, px)
        _icon_cache[key] = surf
    return surf


def entity_icon(kind, team, px=44):
    return unit_icon(kind, team, px) if kind in UNITS else building_icon(kind, team, px)


def paw_cursor_marker(color):
    """The "cat paw" marker shown at an order's destination."""
    key = ("paw", color)
    surf = _misc_cache.get(key)
    if surf:
        return surf
    A = ASSET_SCALE
    p = _P(26 * A, 26 * A)
    p.ell(color, 13 * A, 15 * A, 5.2 * A, 4.2 * A)
    for a in range(4):
        ang = -2.6 + a * 0.62
        p.circ(color, (13 + math.cos(ang) * 7.0) * A,
               (14 + math.sin(ang) * 7.0) * A, 2.1 * A)
    surf = p.done(int(26 * A), int(26 * A))
    _misc_cache[key] = surf
    return surf


def prewarm(teams=(0, 1)):
    """Generate the most used sprites before the game starts."""
    for team in teams:
        for utype in UNITS:
            for frame in range(4):
                for facing in (1, -1):
                    unit_sprite(utype, team, frame, facing)
            unit_icon(utype, team, 46)
        for btype, spec in BUILDINGS.items():
            for level in range(1, 2 + len(spec.get("levels", ()))):
                building_sprite(btype, team, spec["size"] * TILE, level)
            building_icon(btype, team, 46)
    from .settings import UPGRADE_ORDER
    for key in UPGRADE_ORDER + ("level",):
        upgrade_icon(key, 38)
    for terrain in (T_WATER, T_SAND, T_GRASS, T_MEADOW, T_FLOWER):
        for v in range(4):
            tile_sprite(terrain, v)
    for v in range(4):
        decor_sprite(v)
    for kind in RES_COLOR:
        for variant in range(3):
            for step in range(5):
                node_sprite(kind, variant, step / 4.0)
        resource_icon(kind, 22)
    hairball_sprite()

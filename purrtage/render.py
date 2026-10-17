# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""World rendering: terrain, entities, fog, effects.

The world is painted on an intermediate surface expressed in *sprite pixels*:
one world pixel takes up `sprites.ASSET_SCALE` pixels there. That surface is
then scaled to the play area. At zoom level 1.0 both sizes coincide, so the
image is copied as is, without resampling: that is the nominal case, and the
crispest one.
"""

import math

import pygame

from . import entities as E
from . import sprites
from .settings import (BUILDINGS, C_SELECT, RES_COLOR, TILE, TEAM_COLORS,
                       UNITS)
from .utils import clamp, mix, shade


class WorldRenderer(object):
    def __init__(self, game):
        self.game = game
        self.scene = None
        self._scene_key = None
        self.hover = None
        self._disc_cache = {}
        self._ring_cache = {}
        self._puff_cache = {}
        self._fog_small = None
        self._fog_stamp = -1.0
        self._fog_big = None
        self._fog_big_key = None

    # ------------------------------------------------------------ utilitaires --
    @property
    def A(self):
        """Sprite pixels per world pixel."""
        return sprites.ASSET_SCALE

    def _get_scene(self, cam):
        """The intermediate surface, sized to cover the play area."""
        z = cam.scene_zoom
        key = (int(cam.view.w / z) + 2, int(cam.view.h / z) + 2)
        if self._scene_key != key:
            self.scene = pygame.Surface(key).convert()
            self._scene_key = key
        return self.scene

    def invalidate(self):
        """To be called after a resolution or scale change."""
        self.scene = None
        self._scene_key = None
        self._disc_cache.clear()
        self._ring_cache.clear()
        self._puff_cache.clear()
        self._fog_small = None
        self._fog_stamp = -1.0
        self._fog_big = None
        self._fog_big_key = None

    def _visible_enemy(self, ent):
        g = self.game
        if ent.player is g.human or not g.fog.enabled:
            return True
        if ent.is_building:
            return g.fog.explored_at(ent.x, ent.y)
        return g.fog.visible_at(ent.x, ent.y)

    # ----------------------------------------------------------------- rendu --
    def draw(self, screen, font_small):
        g = self.game
        cam = g.camera
        scene = self._get_scene(cam)
        A = self.A
        sx_shake, sy_shake = cam.shake_offset
        ox = -cam.x * A + sx_shake * A
        oy = -cam.y * A + sy_shake * A

        self._draw_terrain(scene, ox, oy)
        self._draw_markers(scene, ox, oy)
        self._draw_nodes(scene, ox, oy)
        self._draw_entities(scene, ox, oy)
        self._draw_projectiles(scene, ox, oy)
        self._draw_effects(scene, ox, oy, font_small)
        self._draw_build_ghost(scene, ox, oy)

        view = g.view
        if scene.get_size() == (view.w, view.h):
            screen.blit(scene, view.topleft)          # nominal case: a crisp copy
        else:
            pygame.transform.scale(scene, (view.w, view.h),
                                   screen.subsurface(view))
        # The fog is applied after the scaling: far fewer pixels to process,
        # and softened edges for free.
        self._draw_fog(screen)

    # --------------------------------------------------------------- terrain --
    def _draw_terrain(self, surf, ox, oy):
        g = self.game
        TP = sprites.tile_px()
        t0x, t0y, t1x, t1y = g.camera.visible_tiles(1)
        sw, sh = surf.get_size()
        world = g.world
        t0x, t0y = max(0, t0x), max(0, t0y)
        t1x, t1y = min(world.w - 1, t1x), min(world.h - 1, t1y)
        # map edges: blacken whatever sticks out
        if (t0x * TILE * self.A + ox > 0 or t0y * TILE * self.A + oy > 0
                or (t1x + 1) * TILE * self.A + ox < sw
                or (t1y + 1) * TILE * self.A + oy < sh):
            surf.fill((14, 16, 20))
        blit = surf.blit
        tiles = world.terrain
        tile_sprite = sprites.tile_sprite
        for ty in range(t0y, t1y + 1):
            row = tiles[ty]
            py = ty * TP + oy
            for tx in range(t0x, t1x + 1):
                blit(tile_sprite(row[tx], (tx * 7 + ty * 13) & 3), (tx * TP + ox, py))
        decor_sprite = sprites.decor_sprite
        off = 4 * self.A
        for (tx, ty, v) in world.decor:
            if t0x <= tx <= t1x and t0y <= ty <= t1y:
                blit(decor_sprite(v), (tx * TP + ox + off, ty * TP + oy + off * 1.5))

    def _draw_nodes(self, surf, ox, oy):
        g = self.game
        A = self.A
        t0x, t0y, t1x, t1y = g.camera.visible_tiles(1)
        hover = g.hover_node
        for node in g.world.nodes:
            if not (t0x <= node.tx <= t1x and t0y <= node.ty <= t1y):
                continue
            if g.fog.enabled and not g.fog.is_explored(node.tx, node.ty):
                continue
            cx = node.x * A + ox
            cy = node.y * A + oy
            if node is hover:
                halo = sprites.node_halo(node.kind)
                # a slight pulse: the halo stays alive without being garish
                pulse = 0.78 + 0.22 * math.sin(g.elapsed * 5.0)
                size = max(4, int(halo.get_width() * pulse))
                img = (halo if size == halo.get_width()
                       else pygame.transform.smoothscale(halo, (size, size)))
                surf.blit(img, (cx - size * 0.5, cy - size * 0.42))
            spr = sprites.node_sprite(node.kind, node.variant,
                                      node.amount / float(node.max_amount))
            surf.blit(spr, (cx - spr.get_width() * 0.5,
                            cy - spr.get_height() * 0.62))

    def _draw_markers(self, surf, ox, oy):
        A = self.A
        for (mx, my, t, color) in self.game.markers:
            k = clamp(t / 0.7, 0.0, 1.0)
            spr = sprites.paw_cursor_marker(color)
            size = max(2, int(spr.get_width() * (0.7 + k * 0.9)))
            s = pygame.transform.smoothscale(spr, (size, size))
            s.set_alpha(int(235 * (1.0 - k)))
            surf.blit(s, (mx * A - size * 0.5 + ox, my * A - size * 0.5 + oy))

    # ------------------------------------------------------------- entities ---
    def _draw_entities(self, surf, ox, oy):
        g = self.game
        cam = g.camera
        x0, y0 = cam.x - 80, cam.y - 90
        x1, y1 = cam.x + cam.vw + 80, cam.y + cam.vh + 90

        drawables = []
        for b in g.buildings:
            if x0 <= b.x <= x1 and y0 <= b.y <= y1 and self._visible_enemy(b):
                drawables.append((b.y + b.size * TILE * 0.3, 0, b))
        for c in g.corpses:
            if x0 <= c.x <= x1 and y0 <= c.y <= y1:
                drawables.append((c.y, 1, c))
        for u in g.units:
            if x0 <= u.x <= x1 and y0 <= u.y <= y1 and self._visible_enemy(u):
                drawables.append((u.y, 2, u))
        drawables.sort(key=lambda d: (d[0], d[1]))

        for (_, kind, ent) in drawables:
            if kind == 0:
                self._draw_building(surf, ent, ox, oy)
            elif kind == 1:
                self._draw_corpse(surf, ent, ox, oy)
            else:
                self._draw_unit(surf, ent, ox, oy)

    def _draw_building(self, surf, b, ox, oy):
        A = self.A
        TP = sprites.tile_px()
        px = b.size * TP
        left = b.tx * TP + ox
        top = b.ty * TP + oy
        cx = b.x * A + ox
        cy = b.y * A + oy
        remembered = (self.game.fog.enabled and b.player is not self.game.human
                      and not self.game.fog.visible_at(b.x, b.y))

        if b.selected:
            self._selection_ring(surf, cx, cy + px * 0.30,
                                 px * 0.56, px * 0.26, C_SELECT)
        elif not b.spec.get("line"):
            # Not under every block of a rampart: a line of rings is clutter.
            self._selection_ring(surf, cx, cy + px * 0.30,
                                 px * 0.50, px * 0.22, b.player.color,
                                 width=max(1, int(2 * A)), alpha=120)

        if b.under_construction:
            surf.blit(sprites.scaffold_sprite(px, b.progress), (left, top))
            spr = self._building_sprite(b, px).copy()
            spr.set_alpha(int(60 + 170 * b.progress))
            surf.blit(spr, (left, top))
        else:
            spr = self._building_sprite(b, px)
            if remembered:
                spr = spr.copy()
                spr.set_alpha(150)
            surf.blit(spr, (left, top))

        if b.hit_flash > 0.0:
            flash = self._building_sprite(b, px).copy()
            flash.fill((255, 120, 120, 0), special_flags=pygame.BLEND_RGBA_ADD)
            flash.set_alpha(int(190 * (b.hit_flash / 0.18)))
            surf.blit(flash, (left, top))

        if not remembered and (b.hp < b.max_hp - 0.5 or b.selected
                               or b.under_construction):
            self._hp_bar(surf, cx, top - 7 * A, px * 0.78, b.hp / b.max_hp,
                         b.player.color)
        if b.under_construction:
            self._progress_bar(surf, cx, top - 2 * A, px * 0.78, b.progress,
                               (240, 206, 120))
        elif b.queue:
            q = b.queue[0]
            self._progress_bar(surf, cx, top - 2 * A, px * 0.78,
                               1.0 - q[1] / q[2], (150, 220, 250))
        elif b.research:
            r = b.research
            self._progress_bar(surf, cx, top - 2 * A, px * 0.78,
                               1.0 - r[1] / r[2], (200, 160, 250))
        elif b.leveling:
            r = b.leveling
            self._progress_bar(surf, cx, top - 2 * A, px * 0.78,
                               1.0 - r[0] / r[1], (200, 160, 250))
        if b.rally and b.player is self.game.human and b.selected:
            pygame.draw.line(surf, (240, 230, 150), (cx, cy),
                             (b.rally[0] * A + ox, b.rally[1] * A + oy),
                             max(1, int(2 * A)))
            pygame.draw.circle(surf, (240, 230, 150),
                               (int(b.rally[0] * A + ox), int(b.rally[1] * A + oy)),
                               max(2, int(5 * A)), max(1, int(2 * A)))

    def _building_sprite(self, b, px):
        """The sprite of a building; a rampart joins up with its neighbours."""
        if b.btype != "wall":
            return sprites.building_sprite(b.btype, b.team, px, b.level)
        links = 0
        at = self.game.world.building_at
        for bit, (dx, dy) in ((sprites.WALL_N, (0, -1)), (sprites.WALL_E, (1, 0)),
                              (sprites.WALL_S, (0, 1)), (sprites.WALL_W, (-1, 0))):
            other = at.get((b.tx + dx, b.ty + dy))
            if other is not None and other.btype == "wall" and other.team == b.team:
                links |= bit
        return sprites.wall_sprite(b.team, px, links)

    def _draw_unit(self, surf, u, ox, oy):
        A = self.A
        spr = sprites.unit_sprite(u.utype, u.team, u.frame(), u.facing)
        w, h = spr.get_size()
        cx = u.x * A + ox
        cy = u.y * A + oy
        px = cx - w * 0.5
        py = cy - h * 0.78

        color = u.player.color
        r = (u.radius + 2) * A
        if u.selected:
            rs = (u.radius + 7) * A
            self._selection_ring(surf, cx, cy + 3 * A, rs, rs * 0.52, C_SELECT,
                                 width=max(1, int(2 * A)))
        self._team_disc(surf, cx, cy + 3 * A, r, color)

        surf.blit(spr, (px, py))
        if u.hit_flash > 0.0:
            flash = spr.copy()
            flash.fill((255, 110, 110, 0), special_flags=pygame.BLEND_RGBA_ADD)
            flash.set_alpha(int(200 * (u.hit_flash / 0.18)))
            surf.blit(flash, (px, py))

        if u.carry > 0 and u.carry_kind:
            bx, by = cx + 9 * A, cy - h * 0.62
            pygame.draw.circle(surf, (28, 26, 30), (int(bx), int(by)),
                               max(2, int(6 * A)))
            pygame.draw.circle(surf, RES_COLOR[u.carry_kind], (int(bx), int(by)),
                               max(1, int(5 * A)))

        if u.hp < u.max_hp - 0.5 or u.selected:
            self._hp_bar(surf, cx, py - 5 * A, 26 * A, u.hp / u.max_hp, color)

    def _draw_corpse(self, surf, c, ox, oy):
        A = self.A
        spr = sprites.unit_sprite(c.utype, c.team, 0, c.facing)
        img = pygame.transform.rotate(spr, 78 if c.facing > 0 else -78)
        img = img.copy()
        img.set_alpha(int(190 * max(0.0, 1.0 - c.t / 7.0)))
        surf.blit(img, (c.x * A - img.get_width() * 0.5 + ox,
                        c.y * A - img.get_height() * 0.5 + oy))

    # ----------------------------------------------------------------- decor ---
    def _team_disc(self, surf, cx, cy, r, color):
        key = (int(r), color)
        s = self._disc_cache.get(key)
        if s is None:
            d = max(2, int(r * 2))
            s = pygame.Surface((d + 2, max(2, int(d * 0.62)) + 2), pygame.SRCALPHA)
            pygame.draw.ellipse(s, (color[0], color[1], color[2], 110), s.get_rect())
            pygame.draw.ellipse(s, (color[0], color[1], color[2], 210), s.get_rect(),
                                max(1, int(2 * self.A)))
            self._disc_cache[key] = s
        surf.blit(s, (cx - s.get_width() * 0.5, cy - s.get_height() * 0.5))

    def _selection_ring(self, surf, cx, cy, rx, ry, color, width=2, alpha=235):
        key = (int(rx), int(ry), color, width, alpha)
        s = self._ring_cache.get(key)
        if s is None:
            s = pygame.Surface((max(2, int(rx * 2)) + 4, max(2, int(ry * 2)) + 4),
                               pygame.SRCALPHA)
            pygame.draw.ellipse(s, (color[0], color[1], color[2], alpha),
                                s.get_rect().inflate(-2, -2), width)
            self._ring_cache[key] = s
        surf.blit(s, (cx - s.get_width() * 0.5, cy - s.get_height() * 0.5))

    def _hp_bar(self, surf, cx, top, width, ratio, color):
        A = self.A
        ratio = clamp(ratio, 0.0, 1.0)
        w = max(4, int(width))
        th = max(2, int(4 * A))
        x = int(cx - w * 0.5)
        pygame.draw.rect(surf, (18, 16, 20), (x - 1, int(top) - 1, w + 2, th + 2))
        fill = (int(230 * (1 - ratio) + 90 * ratio),
                int(70 * (1 - ratio) + 210 * ratio), 80)
        pygame.draw.rect(surf, fill, (x, int(top), int(w * ratio), th))
        pygame.draw.rect(surf, color, (x, int(top), w, th), 1)

    def _progress_bar(self, surf, cx, top, width, ratio, color):
        A = self.A
        w = max(4, int(width))
        th = max(2, int(3 * A))
        x = int(cx - w * 0.5)
        pygame.draw.rect(surf, (18, 16, 20), (x - 1, int(top) - 1, w + 2, th + 2))
        pygame.draw.rect(surf, color, (x, int(top), int(w * clamp(ratio, 0, 1)), th))

    # ---------------------------------------------------------- projectiles ---
    def _draw_projectiles(self, surf, ox, oy):
        A = self.A
        cam = self.game.camera
        x0, y0 = cam.x - 40, cam.y - 40
        x1, y1 = cam.x + cam.vw + 40, cam.y + cam.vh + 40
        spr = sprites.hairball_sprite()
        for p in self.game.projectiles:
            if not (x0 <= p.x <= x1 and y0 <= p.y <= y1):
                continue
            img = pygame.transform.rotate(spr, int(math.degrees(p.spin)) // 15 * 15)
            surf.blit(img, (p.x * A - img.get_width() * 0.5 + ox,
                            p.y * A - img.get_height() * 0.5 + oy))

    def _puff_dot(self, color, rad):
        key = (color, rad)
        s = self._puff_cache.get(key)
        if s is None:
            s = pygame.Surface((rad * 2, rad * 2), pygame.SRCALPHA)
            pygame.draw.circle(s, (color[0], color[1], color[2], 255), (rad, rad), rad)
            self._puff_cache[key] = s
        return s

    def _draw_effects(self, surf, ox, oy, font):
        A = self.A
        cam = self.game.camera
        x0, y0 = cam.x - 60, cam.y - 60
        x1, y1 = cam.x + cam.vw + 60, cam.y + cam.vh + 60
        for e in self.game.effects:
            if not (x0 <= e.x <= x1 and y0 <= e.y <= y1):
                continue                      # off screen: nothing to draw
            if isinstance(e, E.Puff):
                k = e.t / e.dur
                a = int(220 * (1.0 - k))
                if a <= 0:
                    continue
                for (dx, dy, r) in e.parts:
                    rad = max(1, int(r * (0.6 + k * 1.3) * A))
                    dot = self._puff_dot(e.color, rad)
                    dot.set_alpha(a)
                    surf.blit(dot, ((e.x + dx * k) * A - rad + ox,
                                    (e.y + dy * k) * A - rad + oy))
            elif isinstance(e, E.FloatText):
                a = clamp(1.0 - e.t / e.dur, 0.0, 1.0)
                img = font.render(e.text, True, e.color)
                img.set_alpha(int(255 * a))
                surf.blit(img, (e.x * A - img.get_width() * 0.5 + ox, e.y * A + oy))

    # ----------------------------------------------------- build site preview --
    def _draw_build_ghost(self, surf, ox, oy):
        g = self.game
        if not g.build_mode:
            return
        mx, my = pygame.mouse.get_pos()
        if not g.view.collidepoint(mx, my):
            return
        wx, wy = g.camera.screen_to_world(mx, my)
        size = BUILDINGS[g.build_mode]["size"]
        if g.line_start is not None:
            # A rampart being dragged: one ghost per segment, red past the
            # treasury as on a taken tile.
            cost = BUILDINGS[g.build_mode]["cost"]
            budget = dict(g.human.res)
            for (tx, ty) in g.line_tiles(g.line_start,
                                         g._ghost_tile(wx, wy, 1)):
                ok = (g.world.can_place(tx, ty, 1)
                      and not (g.fog.enabled and not g.fog.is_explored(tx, ty)))
                if ok:
                    ok = all(budget.get(k, 0) >= v for k, v in cost.items())
                    for k, v in cost.items():
                        budget[k] = budget.get(k, 0) - v
                self._draw_ghost_at(surf, ox, oy, tx, ty, 1, ok)
            return
        tx, ty = g._ghost_tile(wx, wy, size)
        ok = g.world.can_place(tx, ty, size)
        if ok and g.fog.enabled and not g.fog.is_explored(tx, ty):
            ok = False
        self._draw_ghost_at(surf, ox, oy, tx, ty, size, ok)

    def _draw_ghost_at(self, surf, ox, oy, tx, ty, size, ok):
        g = self.game
        TP = sprites.tile_px()
        px = size * TP
        left, top = tx * TP + ox, ty * TP + oy
        spr = sprites.building_sprite(g.build_mode, g.human.team, px).copy()
        spr.set_alpha(165)
        surf.blit(spr, (left, top))
        tint = (110, 230, 130) if ok else (240, 100, 100)
        s = pygame.Surface((px, px), pygame.SRCALPHA)
        pygame.draw.rect(s, (tint[0], tint[1], tint[2], 70), s.get_rect())
        pygame.draw.rect(s, (tint[0], tint[1], tint[2], 235), s.get_rect(),
                         max(1, int(2 * self.A)))
        for i in range(1, size):
            pygame.draw.line(s, (tint[0], tint[1], tint[2], 90),
                             (i * TP, 0), (i * TP, px))
            pygame.draw.line(s, (tint[0], tint[1], tint[2], 90),
                             (0, i * TP), (px, i * TP))
        surf.blit(s, (left, top))

    # ----------------------------------------------------------------- fog ----
    def _fog_grid(self):
        """A 1 pixel = 1 tile image of the whole fog, refreshed at 5 Hz."""
        g = self.game
        if self._fog_small is not None and g.elapsed - self._fog_stamp < 0.2:
            return self._fog_small
        w, h = g.world.w, g.world.h
        small = pygame.Surface((w, h), pygame.SRCALPHA)
        small.fill((8, 8, 16, 0))
        alpha_at = g.fog.alpha_at
        set_at = small.set_at
        for ty in range(h):
            for tx in range(w):
                a = alpha_at(tx, ty)
                if a:
                    set_at((tx, ty), (8, 8, 16, a))
        self._fog_small = small
        self._fog_stamp = g.elapsed
        return small

    def _draw_fog(self, screen):
        g = self.game
        if not g.fog.enabled:
            return
        cam = g.camera
        t0x, t0y, t1x, t1y = cam.visible_tiles(2)
        t0x, t0y = max(0, t0x), max(0, t0y)
        t1x, t1y = min(g.world.w - 1, t1x), min(g.world.h - 1, t1y)
        w, h = t1x - t0x + 1, t1y - t0y + 1
        if w <= 0 or h <= 0:
            return
        grid = self._fog_grid()
        # The enlarged image depends only on the tile block and the zoom,
        # never on the camera position inside a tile: we cache it, which
        # avoids an expensive enlargement on every frame.
        key = (self._fog_stamp, t0x, t0y, w, h, round(cam.zoom, 4))
        if self._fog_big_key != key:
            patch = grid.subsurface(pygame.Rect(t0x, t0y, w, h))
            self._fog_big = pygame.transform.smoothscale(
                patch, (max(1, int(w * TILE * cam.zoom)),
                        max(1, int(h * TILE * cam.zoom))))
            self._fog_big_key = key
        sx, sy = cam.world_to_screen(t0x * TILE, t0y * TILE)
        old = screen.get_clip()
        screen.set_clip(g.view)
        screen.blit(self._fog_big, (sx, sy))
        screen.set_clip(old)

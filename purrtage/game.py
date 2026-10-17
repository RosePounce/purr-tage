# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Game engine: simulation, orders, selection, victory conditions."""

import math
import random
import zlib
from collections import deque

import pygame

from . import commands as C
from . import entities as E
from . import i18n
from .ai import CatAI
from .camera import Camera
from .fog import Fog
from .layout import Layout
from .pathfinding import astar, nearest_open, tile_center, to_tile
from .player import Player
from .settings import (BUILDINGS, DEFEND_RANGE, DIFFICULTIES, HUD_H,
                       MAX_CATCHUP, MILITARY, NEXT_SITE_TILES, RESOURCES,
                       SCREEN_H, SCREEN_W, TICK_DT, TILE, TOPBAR_H, UNITS,
                       UPGRADES)
from .utils import bresenham, clamp, dist, dist2

PATHS_PER_FRAME = 16
CELL = 96                     # the size of one cell of the spatial grid

# Positions of the four starting kittens around the basket (cos/sin
# precomputed for the angles -0.9 / -0.3 / 0.3 / 0.9 radian).
START_OFFSETS = ((0.6216099683, -0.7833269096),
                 (0.9553364891, -0.2955202067),
                 (0.9553364891, 0.2955202067),
                 (0.6216099683, 0.7833269096))

ST_PLAYING, ST_PAUSED, ST_VICTORY, ST_DEFEAT = range(4)


class Game(object):
    def __init__(self, world, difficulty="tomcat", fog_enabled=True, audio=None,
                 layout=None, local_team=0, use_ai=True):
        E.reset_ids()               # the same entity identifiers on both sides
        self.world = world
        self.difficulty = difficulty
        self.diff = DIFFICULTIES[difficulty]
        self.audio = audio

        self.layout = layout or Layout()
        self.view = self.layout.view
        self.camera = Camera(self.view, self.layout.asset_scale,
                             (world.world_w, world.world_h))
        self.fog = Fog(fog_enabled, (world.w, world.h))

        # `human` is the player sitting in front of THIS screen: over the
        # network each machine names a different one, but the simulation is
        # shared.
        self.local_team = int(local_team)
        self.players = [Player(0, is_ai=False),
                        Player(1, is_ai=bool(use_ai), difficulty=difficulty)]
        self.human = self.players[self.local_team]
        self.enemy = self.players[1 - self.local_team]
        self.use_ai = bool(use_ai)

        self.units = []
        self.buildings = []
        self.projectiles = []
        self.effects = []
        self.corpses = []

        self.grid = {}
        self.path_queue = deque()
        self.messages = []
        self.selection = []
        self.groups = {}
        self.build_mode = None
        self.line_start = None         # first tile of a wall line being dragged
        self.attack_move_mode = False
        self.state = ST_PLAYING
        self.elapsed = 0.0
        self.speed = 1.0
        self.tick_no = 0
        self._accum = 0.0
        self._fog_timer = 0.0
        self._alert_timer = 0.0
        self._pop_warn = 0.0
        self.last_alert_pos = None
        self.hover_node = None          # the node under the cursor
        self.show_help = False
        self.markers = []              # visual feedback of the orders given
        self.dispatch = None           # set by the network session

        self._setup_bases()
        # Over the network both sides are human: no AI runs at all.
        self.ai = CatAI(self, self.players[1], difficulty) if use_ai else None
        self.camera.center_on(*self.home_base_pos(self.human))
        self._refresh_fog(force=True)

    # -------------------------------------------------------------------- setup --
    def _setup_bases(self):
        for player, (btx, bty) in zip(self.players, self.world.start_tiles):
            tx, ty = btx - 1, bty - 1
            base = self.place_building(player, "basket", tx, ty,
                                       free=True, complete=True)
            if base is None:       # a very unlikely fallback: look for a gap
                for r in range(1, 10):
                    done = False
                    for dy in range(-r, r + 1):
                        for dx in range(-r, r + 1):
                            base = self.place_building(player, "basket",
                                                       tx + dx, ty + dy,
                                                       free=True, complete=True)
                            if base:
                                done = True
                                break
                        if done:
                            break
                    if done:
                        break
            # Frozen offsets rather than cos/sin: not every maths library
            # gives the same last bit, and a networked game has to start out
            # identical down to the pixel.
            for (fx, fy) in START_OFFSETS:
                sx = base.x + fx * TILE * 2.6
                sy = base.y + fy * TILE * 2.6
                spot = nearest_open(self.world.blocked, to_tile(sx, sy)) or (btx, bty)
                u = E.Unit("kitten", player.team, *tile_center(spot), player=player)
                self.units.append(u)
                player.stat_units += 1
        self.recompute_pop()

    def resize(self, layout):
        """Take a new resolution into account without interrupting the game."""
        self.layout = layout
        self.view = layout.view
        self.camera.set_view(layout.view, layout.asset_scale)

    def home_base_pos(self, player):
        for b in self.buildings:
            if b.player is player and b.btype == "basket":
                return (b.x, b.y)
        for b in self.buildings:
            if b.player is player:
                return (b.x, b.y)
        for u in self.units:
            if u.player is player:
                return (u.x, u.y)
        return (self.world.world_w * 0.5, self.world.world_h * 0.5)

    # ----------------------------------------------------------- construction --
    def place_building(self, player, btype, tx, ty, free=False, complete=False):
        spec = BUILDINGS[btype]
        size = spec["size"]
        if not self.world.can_place(tx, ty, size):
            return None
        if not free:
            if not player.can_afford(spec["cost"]):
                return None
            player.pay(spec["cost"])
        b = E.Building(btype, player.team, tx, ty, player, complete=complete)
        self.buildings.append(b)
        self.world.set_occupancy(b.tiles, True, b)
        player.stat_buildings += 1
        if complete:
            self.recompute_pop()
        return b

    def on_building_complete(self, b):
        self.recompute_pop()
        if b.player is self.human:
            self.message(i18n.t("messages.building_done." + b.gender,
                                name=b.name), (168, 220, 168))
            self.play("build")
        self._refresh_fog(force=True)

    # ---------------------------------------------------------------- units ---
    def spawn_unit(self, utype, building, player):
        x, y = building.spawn_point(self)
        u = E.Unit(utype, player.team, x, y, player)
        self.units.append(u)
        player.stat_units += 1
        self.recompute_pop()
        if building.rally:
            rx, ry = building.rally
            tgt = self.building_at_point(rx, ry)
            node = self.world.node_at.get(to_tile(rx, ry))
            if node is not None and utype == "kitten":
                u.order_gather(self, node)
            elif tgt is not None and tgt.player is player and tgt.under_construction:
                u.order_build(self, tgt)
            else:
                u.order_move(self, rx, ry)
        if player is self.human:
            self.play("meow")
        return u

    # ------------------------------------------------------------ population --
    def recompute_pop(self):
        for p in self.players:
            p.pop = 0
            p.pop_cap = 0
        for u in self.units:
            if u.alive:
                u.player.pop += UNITS[u.utype]["pop"]
        for b in self.buildings:
            if b.alive and not b.under_construction:
                b.player.pop_cap += b.spec.get("pop_bonus", 0)

    def player_pop_free(self, player, amount=1):
        return player.pop + amount <= player.pop_limit

    def notify_pop_block(self, player):
        if player is self.human and self._pop_warn <= 0.0:
            self._pop_warn = 9.0
            self.message(i18n.t("messages.pop_full"), (236, 196, 108))

    # -------------------------------------------------------------- chemins ---
    def request_path(self, unit, goal_tile):
        unit.path_pending = True
        self.path_queue.append((unit, goal_tile))

    def _process_paths(self):
        budget = PATHS_PER_FRAME
        while self.path_queue and budget > 0:
            unit, goal = self.path_queue.popleft()
            budget -= 1
            if not unit.alive:
                continue
            unit.path_pending = False
            start = nearest_open(self.world.blocked, unit.tile) or unit.tile
            path = astar(self.world.blocked, start, goal)
            unit.path = path or []
            if not path:
                unit.dest = None

    # ---------------------------------------------------- spatial queries ----
    def _rebuild_grid(self):
        self.grid = {}
        for u in self.units:
            if u.alive:
                key = (int(u.x) // CELL, int(u.y) // CELL)
                self.grid.setdefault(key, []).append(u)

    def _nearby_units(self, x, y, radius):
        r = int(radius // CELL) + 1
        cx, cy = int(x) // CELL, int(y) // CELL
        out = []
        for gy in range(cy - r, cy + r + 1):
            for gx in range(cx - r, cx + r + 1):
                bucket = self.grid.get((gx, gy))
                if bucket:
                    out.extend(bucket)
        return out

    def find_enemy_near(self, entity, radius, from_building=False):
        """The closest enemy (units first, then buildings)."""
        best, best_d = None, radius * radius
        for u in self._nearby_units(entity.x, entity.y, radius + 64):
            if u.team == entity.team or not u.alive:
                continue
            d = dist2(entity.x, entity.y, u.x, u.y)
            if d < best_d:
                best, best_d = u, d
        if best is not None:
            return best
        if from_building:
            return None
        for b in self.buildings:
            if b.team == entity.team or not b.alive:
                continue
            if entity.edge_dist(b) <= radius:
                return b
        return None

    def nearest_dropoff(self, unit):
        best, best_d = None, 1e18
        for b in self.buildings:
            if b.player is not unit.player or not b.alive or b.under_construction:
                continue
            if not b.spec.get("dropoff"):
                continue
            d = dist2(unit.x, unit.y, b.x, b.y)
            if d < best_d:
                best, best_d = b, d
        return best

    def nearest_site(self, unit):
        """The closest unfinished site of the same side, or None.

        Walks `self.buildings` in order and breaks ties with the first one
        found: two networked machines must name the same one.
        """
        limit = (NEXT_SITE_TILES * TILE) ** 2
        best, best_d = None, limit
        for b in self.buildings:
            if (b.player is not unit.player or not b.alive
                    or not b.under_construction):
                continue
            d = dist2(unit.x, unit.y, b.x, b.y)
            if d < best_d:
                best, best_d = b, d
        return best

    def player_by_team(self, team):
        for p in self.players:
            if p.team == team:
                return p
        return None

    def entity_by_id(self, eid):
        """Find an entity by its identifier: that is how orders name their
        targets over the network."""
        if eid is None:
            return None
        for u in self.units:
            if u.eid == eid:
                return u
        for b in self.buildings:
            if b.eid == eid:
                return b
        return None

    def building_at_point(self, wx, wy):
        return self.world.building_at.get(to_tile(wx, wy))

    def entity_at_point(self, wx, wy, pad=6.0):
        best, best_d = None, 1e18
        for u in self.units:
            if not u.alive:
                continue
            d = dist2(wx, wy, u.x, u.y)
            if d < (u.radius + pad) ** 2 and d < best_d:
                best, best_d = u, d
        if best:
            return best
        return self.building_at_point(wx, wy)

    # --------------------------------------------------------------- combat ---
    def deal_damage(self, source, target, amount, direct=False):
        armor = target.armor if target.is_unit else 0
        dmg = max(1.0, amount - armor)
        target.take_damage(dmg, self, source)
        if target.is_unit:
            self.add_effect(E.Puff(target.x, target.y - 6, (226, 196, 180),
                                   count=4, spread=26))
        if not direct:
            self.play("hit")

    def spawn_projectile(self, source, target, damage):
        self.projectiles.append(E.Projectile(source, target, damage))
        self.play("spit")

    def on_damaged(self, target, source):
        if target.player is self.human and self._alert_timer <= 0.0:
            if source is not None and (target.is_building or target.is_unit):
                self._alert_timer = 11.0
                self.last_alert_pos = (target.x, target.y)
                self.message(i18n.t("messages.under_attack." + target.gender,
                                    name=target.name), (240, 140, 140))
                self.play("alert")
        if target.is_building and not target.is_unit:
            target.smoke = 1.0

    def on_death(self, ent, source):
        if source is not None and getattr(source, "player", None) is not None:
            source.player.stat_kills += 1
        ent.player.stat_losses += 1
        if ent.is_unit:
            self.corpses.append(E.Corpse(ent))
            self.add_effect(E.Puff(ent.x, ent.y - 6, (230, 214, 198), count=10))
            if ent.player is self.human:
                self.play("hurt")
        else:
            self.world.set_occupancy(ent.tiles, False)
            self.add_effect(E.Puff(ent.x, ent.y, (120, 110, 104), count=18,
                                   spread=110))
            self.camera.add_shake(0.5)
            self.play("boom")
            for p in self.players:
                p.pop = p.pop  # the population is recomputed right after
            self.recompute_pop()
            if ent.player is self.human:
                self.message(i18n.t("messages.destroyed." + ent.gender,
                                    name=ent.name), (240, 140, 140))
                self.last_alert_pos = (ent.x, ent.y)
        if ent in self.selection:
            self.selection.remove(ent)

    def on_deposit(self, unit, kind, amount):
        from .settings import RES_COLOR
        if unit.player is self.human:
            self.add_effect(E.FloatText(unit.x, unit.y - 22, "+%d" % amount,
                                        RES_COLOR[kind], 0.9))

    def complete_upgrade(self, player, key):
        player.upgrades.add(key)
        player.researching.discard(key)
        spec = UPGRADES[key]
        if "hp_mult" in spec:
            mult = spec["hp_mult"]
            for u in self.units:
                if u.player is player and u.alive:
                    u.max_hp *= mult
                    u.hp *= mult
        if player is self.human:
            self.message(i18n.t("messages.upgrade_done",
                                name=i18n.upgrade_name(key)), (176, 212, 246))
            self.play("upgrade")

    def on_level_up(self, b):
        if b.player is self.human:
            self.message(i18n.t("messages.level_done." + b.gender, name=b.name,
                                level=b.level), (176, 212, 246))
            self.play("upgrade")

    def add_effect(self, eff):
        self.effects.append(eff)

    def message(self, text, color=(236, 232, 226)):
        self.messages.append([text, color, 0.0])
        if len(self.messages) > 6:
            self.messages.pop(0)

    def play(self, key):
        if self.audio:
            self.audio.play(key)

    # ------------------------------------------------------------ simulation --
    def update(self, dt):
        """Convert the real time elapsed into fixed simulation steps.

        The engine never advances by a variable step: two machines that got
        the same orders must end up with exactly the same game.
        """
        if self.state != ST_PLAYING:
            return 0
        self._accum += dt * self.speed
        ran = 0
        while self._accum >= TICK_DT and ran < MAX_CATCHUP:
            self._accum -= TICK_DT
            self.tick()
            ran += 1
        if ran >= MAX_CATCHUP:
            self._accum = 0.0        # drop the delay rather than spiral
        return ran

    def checksum(self):
        """A fingerprint of the simulated state, to detect a desync."""
        parts = [self.tick_no]
        for u in self.units:
            parts.append((u.eid, u.team, int(u.x * 16), int(u.y * 16),
                          int(u.hp * 4), u.state, int(u.carry)))
        for b in self.buildings:
            parts.append((b.eid, b.team, b.tx, b.ty, int(b.hp * 4),
                          len(b.queue), int(b.build_done), b.level))
        for p in self.players:
            parts.append((p.team,) + tuple(int(p.res[r]) for r in RESOURCES)
                         + (p.pop, p.pop_cap, len(p.upgrades)))
        return zlib.crc32(repr(parts).encode("utf-8")) & 0xFFFFFFFF

    def tick(self):
        """One simulation step of fixed duration."""
        dt = TICK_DT
        self.tick_no += 1
        self.elapsed += dt
        self._alert_timer = max(0.0, self._alert_timer - dt)
        self._pop_warn = max(0.0, self._pop_warn - dt)

        self._process_paths()
        self._rebuild_grid()

        for u in self.units:
            u.update(dt, self)
        for b in self.buildings:
            b.update(dt, self)
        for p in self.projectiles:
            p.update(dt, self)
        for e in self.effects:
            e.update(dt, self)
        for c in self.corpses:
            c.update(dt, self)
        for m in self.markers:
            m[2] += dt

        self._separate()
        self._cleanup()

        self._fog_timer -= dt
        if self._fog_timer <= 0.0:
            self._fog_timer = 0.2
            self._refresh_fog()

        if self.ai is not None:
            self.ai.update(dt)

        for msg in self.messages:
            msg[2] += dt
        self.messages = [m for m in self.messages if m[2] < 7.0]
        self.markers = [m for m in self.markers if m[2] < 0.7]

        self._check_victory()

    # A cell and the four neighbours after it: each pair of adjacent cells is
    # visited once, so two cats on either side of a border still meet.
    _SEPARATE_NEIGHBOURS = ((1, 0), (-1, 1), (0, 1), (1, 1))

    def _separate(self):
        """Keep the cats from overlapping (a light local repulsion)."""
        grid = {}
        for u in self.units:
            if u.alive:
                grid.setdefault((int(u.x) // 48, int(u.y) // 48), []).append(u)
        for (cx, cy), bucket in grid.items():
            pairs = [(bucket[i], bucket[j]) for i in range(len(bucket))
                     for j in range(i + 1, len(bucket))]
            for ox, oy in self._SEPARATE_NEIGHBOURS:
                other = grid.get((cx + ox, cy + oy))
                if other:
                    pairs.extend((a, b) for a in bucket for b in other)
            for a, b in pairs:
                dx, dy = b.x - a.x, b.y - a.y
                d2 = dx * dx + dy * dy
                md = a.radius + b.radius
                if d2 < 1e-4:
                    # A reproducible nudge: derived from the identifiers,
                    # not from chance, so both machines agree.
                    a.x += ((a.eid * 7919) % 200) / 100.0 - 1.0
                    a.y += ((a.eid * 6271) % 200) / 100.0 - 1.0
                    continue
                if d2 < md * md:
                    d = math.sqrt(d2)
                    push = (md - d) * 0.35
                    nx, ny = dx / d, dy / d
                    a.x -= nx * push
                    a.y -= ny * push
                    b.x += nx * push
                    b.y += ny * push
        right, bottom = self.world.world_w - 2.0, self.world.world_h - 2.0
        for u in self.units:
            u.x = clamp(u.x, 2.0, right)
            u.y = clamp(u.y, 2.0, bottom)

    def _cleanup(self):
        if any(not u.alive for u in self.units):
            self.units = [u for u in self.units if u.alive]
            self.recompute_pop()
        if any(not b.alive for b in self.buildings):
            self.buildings = [b for b in self.buildings if b.alive]
        self.projectiles = [p for p in self.projectiles if p.alive]
        self.effects = [e for e in self.effects if e.alive]
        self.corpses = [c for c in self.corpses if c.alive]
        self.selection = [e for e in self.selection if e.alive]

    def _refresh_fog(self, force=False):
        if not self.fog.enabled:
            return
        sources = []
        for u in self.units:
            if u.player is self.human and u.alive:
                sources.append((u.x, u.y, u.vision))
        for b in self.buildings:
            if b.player is self.human and b.alive:
                sources.append((b.x, b.y, b.vision))
        self.fog.update(sources)

    def _check_victory(self):
        """A side is defeated as soon as it can no longer produce: no
        production building standing, and no kitten to rebuild one."""
        for p in self.players:
            if p.defeated:
                continue
            can_produce = any(b.player is p and b.alive
                              and not b.under_construction
                              and b.spec.get("trains")
                              for b in self.buildings)
            has_builder = any(u.player is p and u.alive and u.spec.get("builder")
                              for u in self.units)
            if not can_produce and not has_builder:
                p.defeated = True
        if self.enemy.defeated and not self.human.defeated:
            self.state = ST_VICTORY
            self.play("victory")
        elif self.human.defeated:
            self.state = ST_DEFEAT
            self.play("defeat")

    def update_hover(self, screen_pos, active=True):
        """Spot the node under the cursor, so as to halo it."""
        self.hover_node = None
        if not active or self.build_mode or not self.view.collidepoint(screen_pos):
            return None
        wx, wy = self.camera.screen_to_world(*screen_pos)
        tx, ty = to_tile(wx, wy)
        best, best_d = None, (TILE * 0.85) ** 2
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                node = self.world.node_at.get((tx + dx, ty + dy))
                if node is None or not node.alive:
                    continue
                if self.fog.enabled and not self.fog.is_explored(node.tx, node.ty):
                    continue
                d = dist2(wx, wy, node.x, node.y)
                if d < best_d:
                    best, best_d = node, d
        self.hover_node = best
        return best

    # ------------------------------------------------------------- selection --
    def visible_entity(self, ent):
        if not self.fog.enabled or ent.player is self.human:
            return True
        return self.fog.visible_at(ent.x, ent.y)

    def select_single(self, wx, wy, additive=False):
        ent = None
        best = 1e18
        for u in self.units:
            if not u.alive or not self.visible_entity(u):
                continue
            d = dist2(wx, wy, u.x, u.y)
            if d < (u.radius + 7.0) ** 2 and d < best:
                ent, best = u, d
        if ent is None:
            b = self.building_at_point(wx, wy)
            if b is not None and b.alive and (
                    b.player is self.human or self.fog.explored_at(b.x, b.y)):
                ent = b
        if ent is None:
            if not additive:
                self.clear_selection()
            return None
        if additive and ent.player is self.human:
            if ent in self.selection:
                self.selection.remove(ent)
                ent.selected = False
            else:
                self.selection.append(ent)
                ent.selected = True
        else:
            self.clear_selection()
            self.selection = [ent]
            ent.selected = True
            if ent.player is self.human:
                self.play("select")
        return ent

    def select_box(self, wrect, additive=False):
        if not additive:
            self.clear_selection()
        found = [u for u in self.units
                 if u.alive and u.player is self.human
                 and wrect.collidepoint(u.x, u.y)]
        if found:
            military = [u for u in found if u.is_military]
            picked = military or found           # fighters take precedence
            for u in picked:
                if u not in self.selection:
                    self.selection.append(u)
                    u.selected = True
            self.play("select")
            return
        if not additive:
            for b in self.buildings:
                if (b.alive and b.player is self.human
                        and wrect.collidepoint(b.x, b.y)):
                    self.selection = [b]
                    b.selected = True
                    return

    def select_same_type(self, proto, on_screen_only=True):
        self.clear_selection()
        wx, wy, ww, wh = self.camera.world_rect()
        rect = pygame.Rect(wx, wy, ww, wh)
        for u in self.units:
            if not u.alive or u.player is self.human and u.utype != proto.utype:
                continue
            if u.player is not self.human:
                continue
            if on_screen_only and not rect.collidepoint(u.x, u.y):
                continue
            self.selection.append(u)
            u.selected = True
        self.play("select")

    def clear_selection(self):
        for e in self.selection:
            e.selected = False
        self.selection = []

    def select_idle_worker(self):
        workers = [u for u in self.units
                   if u.player is self.human and u.alive
                   and u.spec.get("builder") and u.state == E.IDLE]
        if not workers:
            self.message(i18n.t("messages.no_idle_worker"), (200, 196, 190))
            return
        self._idle_index = (getattr(self, "_idle_index", -1) + 1) % len(workers)
        w = workers[self._idle_index]
        self.clear_selection()
        self.selection = [w]
        w.selected = True
        self.camera.center_on(w.x, w.y)
        self.play("select")

    def set_group(self, n):
        self.groups[n] = [e for e in self.selection if e.player is self.human]
        if self.groups[n]:
            self.message(i18n.t("messages.group_saved", number=n,
                                count=len(self.groups[n])), (190, 200, 230))

    def recall_group(self, n, center=False):
        g = [e for e in self.groups.get(n, []) if e.alive]
        self.groups[n] = g
        if not g:
            return
        self.clear_selection()
        self.selection = list(g)
        for e in g:
            e.selected = True
        if center:
            self.camera.center_on(
                sum(e.x for e in g) / len(g), sum(e.y for e in g) / len(g))
        self.play("select")

    # ---------------------------------------------------------------- orders --
    def submit(self, cmd):
        """Post an order.

        In solo play it applies right away. Over the network the session
        routes it to the lockstep queue: it will run on the same simulation
        step on both machines.
        """
        if cmd is None:
            return False
        if self.dispatch is not None:
            return self.dispatch(cmd)
        return C.apply(self, cmd)

    def selected_units(self):
        return [e for e in self.selection if e.is_unit and e.player is self.human]

    def resolve_command(self, wx, wy, queued=False, force_attack=False):
        """Turn a right click into a concrete order, without running anything.

        This reading depends on purely local information — the selection, the
        fog, whatever sits under the cursor — which is why it happens here,
        before sending, and never on reception.
        """
        team = self.human.team
        units = self.selected_units()
        if not units:
            b = next((e for e in self.selection
                      if e.is_building and e.player is self.human), None)
            if b is not None and not b.under_construction:
                return C.make(team, C.RALLY, eid=b.eid, x=wx, y=wy)
            return None

        ids = [u.eid for u in units]
        target = self.entity_at_point(wx, wy)
        node = self.world.node_at.get(to_tile(wx, wy))

        if (target is not None and target.alive and target.team != team
                and self.visible_entity(target)):
            return C.make(team, C.ATTACK, ids=ids, target=target.eid,
                          x=wx, y=wy)
        if force_attack:
            return C.make(team, C.AMOVE, ids=ids, x=wx, y=wy, queued=queued)
        if node is not None and node.alive:
            return C.make(team, C.GATHER, ids=ids, tx=node.tx, ty=node.ty,
                          x=wx, y=wy, queued=queued)
        if (target is not None and target.is_building
                and target.player is self.human
                and (target.under_construction or target.hp < target.max_hp)):
            return C.make(team, C.BUILD, ids=ids, target=target.eid,
                          x=wx, y=wy, queued=queued)
        return C.make(team, C.MOVE, ids=ids, x=wx, y=wy, queued=queued)

    def command(self, wx, wy, queued=False, force_attack=False):
        """A shortcut: resolve the click, then post the order."""
        return self.submit(self.resolve_command(wx, wy, queued, force_attack))

    def formation_move(self, units, wx, wy, queued):
        n = len(units)
        if n == 1:
            units[0].order_move(self, wx, wy, queued)
            return
        cols = int(math.ceil(math.sqrt(n)))
        spacing = TILE * 0.95
        for i, u in enumerate(units):
            ox = (i % cols - (cols - 1) * 0.5) * spacing
            oy = (i // cols - (n // cols) * 0.5) * spacing
            u.order_move(self, wx + ox, wy + oy, queued)

    def stop_selection(self):
        units = self.selected_units()
        if not units:
            return False
        return self.submit(C.make(self.human.team, C.STOP,
                                  ids=[u.eid for u in units]))

    # ----------------------------------------------------- mode construction --
    def start_build_mode(self, btype):
        if not any(u.spec.get("builder") for u in self.selected_units()):
            self.message(i18n.t("messages.select_builder"), (236, 196, 108))
            return
        cost = BUILDINGS[btype]["cost"]
        if not self.human.can_afford(cost):
            self.warn_cost(cost)
            return
        self.build_mode = btype
        self.attack_move_mode = False

    def warn_cost(self, cost):
        missing = self.human.missing(cost)
        self.message(i18n.t("messages.missing",
                            resources=", ".join(i18n.resource_name(m)
                                                for m in missing)),
                     (236, 150, 120))
        self.play("deny")

    def resolve_place(self, wx, wy):
        """Check a building placement on the player's side, then emit the order.

        The fog is local information: we check it here, not at execution time,
        otherwise the two machines would not judge it the same way.
        """
        btype = self.build_mode
        if btype is None:
            return None
        spec = BUILDINGS[btype]
        tx, ty = self._ghost_tile(wx, wy, spec["size"])
        if not self.world.can_place(tx, ty, spec["size"]):
            self.message(i18n.t("messages.cannot_place"), (236, 150, 120))
            self.play("deny")
            return None
        if self.fog.enabled and not self.fog.is_explored(tx, ty):
            self.message(i18n.t("messages.unexplored"), (236, 150, 120))
            self.play("deny")
            return None
        if not self.human.can_afford(spec["cost"]):
            self.warn_cost(spec["cost"])
            return None
        workers = [u.eid for u in self.selected_units()
                   if u.spec.get("builder")]
        return C.make(self.human.team, C.PLACE, ids=workers, btype=btype,
                      tx=tx, ty=ty)

    def line_tiles(self, start, end):
        """The tiles of a wall line from one tile to another, ends included."""
        return list(bresenham(start[0], start[1], end[0], end[1]))

    def resolve_place_line(self, start, wx, wy):
        """The orders laying a line of one-tile buildings, `start` to the cursor.

        Tiles that are taken, unexplored or beyond the treasury are left out
        here, on the player's side, rather than refused one by one later.
        Each kitten takes one segment; the others are picked up as they go.
        """
        btype = self.build_mode
        if btype is None:
            return []
        cost = BUILDINGS[btype]["cost"]
        end = self._ghost_tile(wx, wy, 1)
        budget = dict(self.human.res)
        workers = [u.eid for u in self.selected_units()
                   if u.spec.get("builder")]
        cmds = []
        for (tx, ty) in self.line_tiles(start, end):
            if not self.world.can_place(tx, ty, 1):
                continue
            if self.fog.enabled and not self.fog.is_explored(tx, ty):
                continue
            if any(budget.get(k, 0) < v for k, v in cost.items()):
                break
            for k, v in cost.items():
                budget[k] -= v
            ids = [workers[len(cmds)]] if len(cmds) < len(workers) else []
            cmds.append(C.make(self.human.team, C.PLACE, ids=ids,
                               btype=btype, tx=tx, ty=ty))
        if not cmds:
            if not self.human.can_afford(cost):
                self.warn_cost(cost)
            else:
                self.message(i18n.t("messages.cannot_place"), (236, 150, 120))
                self.play("deny")
        return cmds

    def try_place_line(self, start, wx, wy, chain=False):
        cmds = self.resolve_place_line(start, wx, wy)
        placed = False
        for cmd in cmds:
            placed = self.submit(cmd) or placed
        btype = self.build_mode
        if not chain or not self.human.can_afford(BUILDINGS[btype]["cost"]):
            self.build_mode = None
        return placed

    def try_place(self, wx, wy, chain=False):
        cmd = self.resolve_place(wx, wy)
        if cmd is None:
            return False
        placed = self.submit(cmd)
        btype = self.build_mode
        if not chain or not self.human.can_afford(BUILDINGS[btype]["cost"]):
            self.build_mode = None
        return placed

    def _ghost_tile(self, wx, wy, size):
        tx = int(wx // TILE) - (size - 1) // 2
        ty = int(wy // TILE) - (size - 1) // 2
        tx = int(clamp(tx, 0, self.world.w - size))
        ty = int(clamp(ty, 0, self.world.h - size))
        return tx, ty

    # ------------------------------------------------------------- production --
    def train(self, building, utype):
        spec = UNITS[utype]
        owner = building.player
        mine = owner is self.human
        if not building.can_train(utype):
            return False
        if len(building.queue) >= 8:
            if mine:
                self.message(i18n.t("messages.queue_full"), (236, 196, 108))
            return False
        if not owner.can_afford(spec["cost"]):
            if mine:
                self.warn_cost(spec["cost"])
            return False
        if owner.pop + spec["pop"] > owner.pop_limit:
            if mine:
                self.message(i18n.t("messages.pop_short"), (236, 196, 108))
                self.play("deny")
            return False
        owner.pay(spec["cost"])
        building.enqueue(utype)
        if mine:
            self.play("click")
        return True

    def research(self, building, key):
        owner = building.player
        mine = owner is self.human
        if building.research is not None or not building.spec.get("research"):
            return False
        if key in owner.upgrades or key in owner.researching:
            return False
        spec = UPGRADES[key]
        if not owner.can_afford(spec["cost"]):
            if mine:
                self.warn_cost(spec["cost"])
            return False
        owner.pay(spec["cost"])
        owner.researching.add(key)
        building.start_research(key)
        if mine:
            self.play("click")
        return True

    def level_up(self, building):
        owner = building.player
        mine = owner is self.human
        step = building.next_level()
        if (step is None or building.under_construction
                or building.leveling is not None):
            return False
        if not owner.can_afford(step["cost"]):
            if mine:
                self.warn_cost(step["cost"])
            return False
        owner.pay(step["cost"])
        building.start_level_up()
        if mine:
            self.play("click")
        return True

    def order_level_up(self, building):
        return self.submit(C.make(self.human.team, C.LEVEL_UP,
                                  eid=building.eid))

    def order_train(self, building, utype):
        return self.submit(C.make(self.human.team, C.TRAIN,
                                  eid=building.eid, utype=utype))

    def order_research(self, building, key):
        return self.submit(C.make(self.human.team, C.RESEARCH,
                                  eid=building.eid, key=key))

    def cancel_production(self, building):
        return self.submit(C.make(self.human.team, C.CANCEL_PROD,
                                  eid=building.eid))

    def cancel_site(self, building):
        return self.submit(C.make(self.human.team, C.CANCEL_SITE,
                                  eid=building.eid))

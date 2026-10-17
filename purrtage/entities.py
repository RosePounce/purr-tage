# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Units, buildings, projectiles and visual effects."""

import math
import random

from . import i18n
from .pathfinding import nearest_open, tile_center, to_tile
from .settings import (AGGRO_RANGE, BUILDINGS, BUILD_SPEED, CORPSE_TIME,
                       DEFEND_RANGE, PROJECTILE_SPEED, REPAIR_RATE,
                       RETARGET_BONUS, TILE, UNITS)
from .utils import clamp, dist, normalize

# ------------------------------------------------------------------ states ----
IDLE, MOVE, ATTACK_MOVE, GATHER, RETURN, BUILD, ATTACK = range(7)

def rect_dist(x, y, left, top, w, h):
    """The distance from a point to a rectangle (0 when inside it)."""
    dx = max(left - x, 0.0, x - (left + w))
    dy = max(top - y, 0.0, y - (top + h))
    return math.sqrt(dx * dx + dy * dy)


WORK_RANGE = TILE * 1.2        # reach for gathering, building and dropping off

_next_id = [0]


def reset_ids():
    """Reset the identifier counter at the start of a game.

    Essential over the network: orders designate entities by their
    identifier, so both machines must hand them out identically, even when
    one of them has already played a solo game beforehand.
    """
    _next_id[0] = 0


def _new_id():
    _next_id[0] += 1
    return _next_id[0]


class Entity(object):
    is_unit = False
    is_building = False

    def __init__(self, team, x, y, hp):
        self.eid = _new_id()
        self.team = team
        self.x, self.y = float(x), float(y)
        self.max_hp = float(hp)
        self.hp = float(hp)
        self.alive = True
        self.radius = 10.0
        self.hit_flash = 0.0
        self.last_attacker = None

    @property
    def pos(self):
        return (self.x, self.y)

    @property
    def tile(self):
        return to_tile(self.x, self.y)

    def point_dist(self, x, y):
        """The distance from a point to the entity (a circle by default)."""
        return max(0.0, dist(self.x, self.y, x, y) - self.radius)

    def edge_dist(self, other):
        """Edge-to-edge distance; buildings count as a square."""
        if other.is_building:
            return max(0.0, other.point_dist(self.x, self.y) - self.radius)
        if self.is_building:
            return max(0.0, self.point_dist(other.x, other.y) - other.radius)
        return max(0.0, dist(self.x, self.y, other.x, other.y)
                   - self.radius - other.radius)

    def take_damage(self, amount, game, source=None):
        if not self.alive:
            return
        self.hp -= amount
        self.hit_flash = 0.18
        if source is not None:
            self.last_attacker = source
        game.on_damaged(self, source)
        if self.hp <= 0:
            self.hp = 0.0
            self.alive = False
            game.on_death(self, source)


# ------------------------------------------------------------------- units ----
class Unit(Entity):
    is_unit = True

    def __init__(self, utype, team, x, y, player):
        spec = UNITS[utype]
        Entity.__init__(self, team, x, y, spec["hp"] * player.hp_mult())
        self.utype = utype
        self.spec = spec
        self.player = player
        self.radius = float(spec["radius"])
        self.state = IDLE
        self.path = []
        self.dest = None               # (x, y) in world coordinates
        self.dest_tile = None
        self.target = None             # the Entity being aimed at
        self.node = None               # the node being worked
        self.site = None               # site / building to repair
        self.carry = 0
        self.carry_kind = None
        self.cooldown = 0.0
        self.repath = 0.0
        self.path_pending = False
        self.anim = (self.eid * 0.37) % 4.0
        self.facing = 1
        self.home = (x, y)             # guard point used for retaliation
        self.stuck = 0.0
        self.waypoints = []            # queued orders (Shift + click)
        self.selected = False
        self.ordered_attack = False    # an attack order, not a retaliation
        self.work_tile = None          # the reserved work tile

    # ----------------------------------------------------------- properties --
    @property
    def name(self):
        return i18n.unit_name(self.utype)

    @property
    def gender(self):
        """The gender of the translated name: French needs it for agreement."""
        return i18n.unit_gender(self.utype)

    @property
    def role(self):
        return i18n.unit_role(self.utype)

    @property
    def desc(self):
        return i18n.unit_desc(self.utype)

    @property
    def speed(self):
        return self.spec["speed"] * self.player.speed_mult()

    @property
    def attack(self):
        return self.spec["atk"] + self.player.atk_bonus()

    @property
    def armor(self):
        return self.spec["armor"] + self.player.armor_bonus()

    @property
    def is_military(self):
        return not self.spec.get("builder", False)

    @property
    def vision(self):
        return self.spec["vision"]

    # --------------------------------------------------------------- orders --
    def clear_orders(self):
        self.path = []
        self.dest = self.dest_tile = None
        self.target = self.node = self.site = None
        self.waypoints = []
        self.path_pending = False
        self.ordered_attack = False
        self.work_tile = None

    def stop(self):
        self.clear_orders()
        self.state = IDLE
        self.home = (self.x, self.y)

    def _goto(self, game, x, y):
        x = clamp(x, TILE * 0.5, game.world.world_w - TILE * 0.5)
        y = clamp(y, TILE * 0.5, game.world.world_h - TILE * 0.5)
        self.dest = (x, y)
        goal = to_tile(x, y)
        goal = nearest_open(game.world.blocked, goal) or goal
        self.dest_tile = goal
        self.path = []
        game.request_path(self, goal)

    def order_move(self, game, x, y, queued=False):
        if queued and self.state in (MOVE, ATTACK_MOVE):
            self.waypoints.append(("move", (x, y)))
            return
        self.clear_orders()
        self.state = MOVE
        self.home = (x, y)
        self._goto(game, x, y)

    def order_attack_move(self, game, x, y, queued=False):
        if queued and self.state in (MOVE, ATTACK_MOVE):
            self.waypoints.append(("amove", (x, y)))
            return
        self.clear_orders()
        self.state = ATTACK_MOVE
        self.ordered_attack = True
        self.home = (x, y)
        self._goto(game, x, y)

    def order_attack(self, game, target):
        self.clear_orders()
        self.state = ATTACK
        self.ordered_attack = True
        self.target = target
        self.home = (self.x, self.y)
        self._goto(game, target.x, target.y)

    def hunt_range(self):
        """The search radius for a new target after bringing one down.

        Wider than a plain retaliation: a cat sent on the attack chains onto
        the next enemy instead of stopping dead.
        """
        if self.ordered_attack:
            return max(AGGRO_RANGE, self.vision * RETARGET_BONUS)
        return AGGRO_RANGE

    def leash_range(self):
        """The maximum chase distance from the guard post.

        Wide on an explicit attack order — the player wants their cats to
        close in — and short on a plain retaliation, so that a garrison does
        not let itself be lured away.
        """
        return DEFEND_RANGE * (6.0 if self.ordered_attack else 2.4)

    def acquire(self, game, foe):
        """Engage a new target and move the guard post here."""
        self.target = foe
        self.state = ATTACK
        self.home = (self.x, self.y)
        if foe.is_building:
            self._goto_building(game, foe)
        else:
            self._goto(game, foe.x, foe.y)

    def order_gather(self, game, node):
        if not self.spec.get("builder"):
            return self.order_move(game, node.x, node.y)
        self.clear_orders()
        self.state = GATHER
        self.node = node
        if self.carry and self.carry_kind != node.kind:
            self.carry, self.carry_kind = 0, None
        self._goto_node(game, node)

    def order_build(self, game, site):
        if not self.spec.get("builder"):
            return self.order_move(game, site.x, site.y)
        self.clear_orders()
        self.state = BUILD
        self.site = site
        self._goto_building(game, site)

    def _claimed_tiles(self, game, around):
        """The tiles already reserved by other workers on the same target."""
        taken = set()
        for other in game.units:
            if other is self or not other.alive or other.work_tile is None:
                continue
            if other.node is around or other.site is around:
                taken.add(other.work_tile)
        return taken

    def _goto_node(self, game, node):
        spot = game.world.free_tile_around(
            {(node.tx, node.ty)}, near=(self.x, self.y),
            avoid=self._claimed_tiles(game, node))
        if spot is None:
            self.state = IDLE
            return
        self.work_tile = spot
        cx, cy = tile_center(spot)
        self._goto(game, cx, cy)

    def _goto_building(self, game, b):
        spot = game.world.free_tile_around(
            set(b.tiles), near=(self.x, self.y),
            avoid=self._claimed_tiles(game, b))
        if spot is None:
            self.work_tile = None
            self._goto(game, b.x, b.y)
        else:
            self.work_tile = spot
            cx, cy = tile_center(spot)
            self._goto(game, cx, cy)

    # -------------------------------------------------------------- update ---
    def update(self, dt, game):
        if not self.alive:
            return
        self.cooldown = max(0.0, self.cooldown - dt)
        self.hit_flash = max(0.0, self.hit_flash - dt)
        self.repath = max(0.0, self.repath - dt)

        handler = (self._st_idle, self._st_move, self._st_amove, self._st_gather,
                   self._st_return, self._st_build, self._st_attack)[self.state]
        handler(dt, game)

    # ------------------------------------------------------------ states ----
    def _st_idle(self, dt, game):
        if self.is_military:
            foe = game.find_enemy_near(self, self.hunt_range())
            if foe:
                self.acquire(game, foe)
        elif self.last_attacker is not None and self.last_attacker.alive:
            # a worker under attack retaliates timidly
            if dist(self.x, self.y, self.last_attacker.x, self.last_attacker.y) < 110:
                self.state = ATTACK
                self.target = self.last_attacker

    def _next_waypoint(self, game):
        if not self.waypoints:
            return False
        kind, data = self.waypoints.pop(0)
        if kind == "move":
            self.state = MOVE
            self._goto(game, *data)
        elif kind == "amove":
            self.state = ATTACK_MOVE
            self._goto(game, *data)
        return True

    def _st_move(self, dt, game):
        if self._travel(dt, game):
            if not self._next_waypoint(game):
                self.state = IDLE
                self.home = (self.x, self.y)

    def _st_amove(self, dt, game):
        foe = game.find_enemy_near(self, self.hunt_range())
        if foe:
            self.waypoints.insert(0, ("amove", self.dest or (self.x, self.y)))
            self.acquire(game, foe)
            return
        if self._travel(dt, game):
            if not self._next_waypoint(game):
                self.state = IDLE
                self.home = (self.x, self.y)

    def _st_gather(self, dt, game):
        node = self.node
        if node is None or not node.alive:
            nxt = game.world.nearest_node(self.x, self.y,
                                          node.kind if node else None, 26)
            if nxt is None:
                self.node = None
                self.state = RETURN if self.carry else IDLE
                return
            self.node = nxt
            self._goto_node(game, nxt)
            return
        reach = rect_dist(self.x, self.y, node.tx * TILE, node.ty * TILE,
                          TILE, TILE)
        if reach > WORK_RANGE:
            arrived = self._travel(dt, game)
            if arrived and not self.path and self.repath <= 0.0:
                self.repath = 0.5
                self._goto_node(game, node)
            return
        self.path = []
        self.facing = 1 if node.x >= self.x else -1
        rate = self.spec["gather_rate"] * 10.0 * dt
        got = node.take(rate)
        self.carry_kind = node.kind
        self.carry += got
        self.anim += dt * 6.0
        if not node.alive:
            game.world.remove_node(node)
        if self.carry >= self.spec["carry"] or not node.alive:
            if self.carry > 0:
                self.state = RETURN
                drop = game.nearest_dropoff(self)
                if drop:
                    self._goto_building(game, drop)
                    self.site = drop
                else:
                    self.state = GATHER

    def _st_return(self, dt, game):
        drop = self.site
        if drop is None or not drop.alive or drop.under_construction:
            drop = game.nearest_dropoff(self)
            self.site = drop
            if drop is None:
                self.state = IDLE
                return
            self._goto_building(game, drop)
            return
        if drop.edge_dist(self) > WORK_RANGE:
            arrived = self._travel(dt, game)
            if arrived and not self.path and self.repath <= 0.0:
                self.repath = 0.5
                self._goto_building(game, drop)
            return
        self.path = []
        if self.carry > 0 and self.carry_kind:
            self.player.add(self.carry_kind, int(self.carry))
            game.on_deposit(self, self.carry_kind, int(self.carry))
        self.carry = 0
        self.site = None
        if self.node is not None and self.node.alive:
            self.state = GATHER
            self._goto_node(game, self.node)
        else:
            nxt = game.world.nearest_node(self.x, self.y, self.carry_kind, 26)
            if nxt:
                self.node = nxt
                self.state = GATHER
                self._goto_node(game, nxt)
            else:
                self.state = IDLE

    def _next_site(self, game):
        """Chain onto another site, like the gatherer onto another node.

        A kitten that had just finished a shed used to stand right there while
        the sites laid out just before were waiting for it: that is what a
        player reported. It now moves on to the closest one by itself.
        """
        nxt = game.nearest_site(self)
        if nxt is None:
            return False
        self.site = nxt
        self.state = BUILD
        self.work_tile = None
        self._goto_building(game, nxt)
        return True

    def _st_build(self, dt, game):
        site = self.site
        if site is None or not site.alive or site.team != self.team:
            self.site = None
            if not self._next_site(game):
                self.state = IDLE
            return
        if not site.under_construction and site.hp >= site.max_hp:
            self.site = None
            if not self._next_site(game):
                self.state = IDLE
            return
        if site.edge_dist(self) > WORK_RANGE:
            arrived = self._travel(dt, game)
            if arrived and not self.path and self.repath <= 0.0:
                self.repath = 0.5
                self._goto_building(game, site)
            return
        self.path = []
        self.facing = 1 if site.x >= self.x else -1
        self.anim += dt * 7.0
        if site.under_construction:
            site.add_progress(BUILD_SPEED * dt, game)
        else:
            site.hp = min(site.max_hp, site.hp + REPAIR_RATE * dt)

    def _st_attack(self, dt, game):
        tgt = self.target
        if tgt is None or not tgt.alive:
            self.target = None
            foe = (game.find_enemy_near(self, self.hunt_range())
                   if self.is_military else None)
            if foe:
                self.acquire(game, foe)
                return
            if self.waypoints:
                self._next_waypoint(game)
            else:
                self.state = IDLE
            return

        reach = self.spec["rng"]
        d = self.edge_dist(tgt)
        if d > reach:
            # Give up the chase when the enemy flees too far from the post.
            # The post moves on every new engagement, so a cat can chain
            # fights without crossing the map after a runaway.
            if (self.is_military and self.state == ATTACK
                    and dist(self.x, self.y, self.home[0], self.home[1])
                    > self.leash_range()):
                self.target = None
                self.state = MOVE
                self._goto(game, *self.home)
                return
            if self.repath <= 0.0 and (not self.path or
                                       dist(tgt.x, tgt.y, *(self.dest or (0, 0))) > TILE * 1.5):
                self.repath = 0.45
                if tgt.is_building:
                    self._goto_building(game, tgt)
                else:
                    self._goto(game, tgt.x, tgt.y)
            self._travel(dt, game)
            return

        self.path = []
        self.facing = 1 if tgt.x >= self.x else -1
        if self.cooldown <= 0.0:
            self.cooldown = self.spec["cooldown"]
            dmg = self.attack
            if tgt.is_building:
                dmg *= self.spec.get("bonus_vs_building", 1.0)
            if self.spec.get("projectile"):
                game.spawn_projectile(self, tgt, dmg)
            else:
                game.deal_damage(self, tgt, dmg)

    # ------------------------------------------------------------- movement --
    def _travel(self, dt, game):
        """Advance along the path. Returns True once the destination is reached."""
        if not self.path:
            if self.path_pending:
                return False
            if self.dest is None:
                return True
            if dist(self.x, self.y, self.dest[0], self.dest[1]) < TILE * 0.7:
                self.dest = None
                return True
            if self.repath <= 0.0:
                self.repath = 0.6
                self.stuck += 1
                if self.stuck > 4:
                    self.stuck = 0
                    self.dest = None
                    return True
                game.request_path(self, self.dest_tile or to_tile(*self.dest))
            return False

        self.stuck = 0
        tx, ty = tile_center(self.path[0])
        dx, dy = tx - self.x, ty - self.y
        d = math.sqrt(dx * dx + dy * dy)
        step = self.speed * dt
        if d <= max(step, 2.0):
            self.x, self.y = tx, ty
            self.path.pop(0)
            if not self.path:
                self.dest = None
                return True
            return False
        nx, ny = dx / d, dy / d
        self.x += nx * step
        self.y += ny * step
        if abs(nx) > 0.15:
            self.facing = 1 if nx > 0 else -1
        self.anim += dt * (6.0 + self.speed * 0.045)
        return False

    # ------------------------------------------------------------- display ---
    def frame(self):
        if self.state in (MOVE, ATTACK_MOVE) or (self.state == ATTACK and self.path):
            return int(self.anim) % 4
        if self.state in (GATHER, BUILD):
            return int(self.anim) % 4
        return 0

    def status_label(self):
        return i18n.t("status." + {IDLE: "idle", MOVE: "move",
                                   ATTACK_MOVE: "attack_move", GATHER: "gather",
                                   RETURN: "return", BUILD: "build",
                                   ATTACK: "attack"}[self.state])


# --------------------------------------------------------------- buildings ----
class Building(Entity):
    is_building = True

    def __init__(self, btype, team, tx, ty, player, complete=False):
        spec = BUILDINGS[btype]
        size = spec["size"]
        cx = (tx + size * 0.5) * TILE
        cy = (ty + size * 0.5) * TILE
        Entity.__init__(self, team, cx, cy, spec["hp"])
        self.btype = btype
        self.spec = spec
        self.player = player
        self.size = size
        self.tx, self.ty = tx, ty
        self.tiles = [(tx + dx, ty + dy) for dy in range(size) for dx in range(size)]
        self.radius = size * TILE * 0.42
        self.under_construction = not complete
        self.build_total = spec["build_time"] * BUILD_SPEED
        self.build_done = 0.0 if not complete else self.build_total
        self.hp = self.max_hp if complete else max(1.0, self.max_hp * 0.08)
        self.queue = []                      # [[kind, left, total], ...]
        self.research = None                 # [key, left, total]
        self.level = 1
        self.leveling = None                 # [left, total] towards level + 1
        self.rally = None
        self.cooldown = 0.0
        self.selected = False
        self.smoke = 0.0

    @property
    def name(self):
        return i18n.building_name(self.btype)

    @property
    def gender(self):
        """The gender of the translated name: French needs it for agreement."""
        return i18n.building_gender(self.btype)

    @property
    def desc(self):
        return i18n.building_desc(self.btype)

    @property
    def vision(self):
        return self.spec["vision"]

    def point_dist(self, x, y):
        """The distance from a point to the building rectangle (0 when inside)."""
        left = self.tx * TILE
        top = self.ty * TILE
        right = left + self.size * TILE
        bottom = top + self.size * TILE
        dx = max(left - x, 0.0, x - right)
        dy = max(top - y, 0.0, y - bottom)
        return math.sqrt(dx * dx + dy * dy)

    @property
    def progress(self):
        return clamp(self.build_done / self.build_total, 0.0, 1.0)

    # ---------------------------------------------------------------- levels --
    @property
    def max_level(self):
        return 1 + len(self.spec.get("levels", ()))

    def next_level(self):
        """The spec of the next level step, or None at the top."""
        steps = self.spec.get("levels", ())
        return steps[self.level - 1] if self.level - 1 < len(steps) else None

    def _level_bonus(self, stat):
        return sum(step.get(stat, 0)
                   for step in self.spec.get("levels", ())[:self.level - 1])

    @property
    def attack(self):
        return (self.spec.get("atk", 0) + self._level_bonus("atk")
                + self.player.atk_bonus())

    @property
    def attack_range(self):
        return self.spec.get("rng", 0) + self._level_bonus("rng")

    def start_level_up(self):
        step = self.next_level()
        self.leveling = [step["time"], step["time"]]

    def finish_level_up(self):
        step = self.next_level()
        self.leveling = None
        self.level += 1
        self.max_hp += step.get("hp", 0)
        self.hp += step.get("hp", 0)

    def add_progress(self, amount, game):
        if not self.under_construction:
            return
        self.build_done += amount
        self.hp = min(self.max_hp,
                      self.max_hp * (0.08 + 0.92 * self.progress))
        if self.build_done >= self.build_total:
            self.build_done = self.build_total
            self.under_construction = False
            self.hp = self.max_hp
            game.on_building_complete(self)

    # ------------------------------------------------------------ production --
    def can_train(self, utype):
        return (not self.under_construction and utype in self.spec.get("trains", ()))

    def enqueue(self, utype):
        spec = UNITS[utype]
        self.queue.append([utype, spec["train_time"], spec["train_time"]])

    def cancel_last(self, game):
        if self.queue:
            kind = self.queue.pop()[0]
            self.player.refund(UNITS[kind]["cost"])
            return kind
        if self.research:
            from .settings import UPGRADES
            key = self.research[0]
            self.player.refund(UPGRADES[key]["cost"])
            self.player.researching.discard(key)
            self.research = None
            return key
        if self.leveling:
            self.player.refund(self.next_level()["cost"])
            self.leveling = None
            return "level"
        return None

    def start_research(self, key):
        from .settings import UPGRADES
        self.research = [key, UPGRADES[key]["time"], UPGRADES[key]["time"]]

    def spawn_point(self, game):
        spot = game.world.free_tile_around(set(self.tiles))
        if spot is None:
            return (self.x, self.y + self.size * TILE * 0.6)
        return tile_center(spot)

    def update(self, dt, game):
        if not self.alive:
            return
        self.hit_flash = max(0.0, self.hit_flash - dt)
        self.cooldown = max(0.0, self.cooldown - dt)
        if self.under_construction:
            return

        if self.queue:
            entry = self.queue[0]
            if game.player_pop_free(self.player, UNITS[entry[0]]["pop"]):
                entry[1] -= dt
                if entry[1] <= 0:
                    self.queue.pop(0)
                    game.spawn_unit(entry[0], self, self.player)
            else:
                game.notify_pop_block(self.player)

        if self.research:
            self.research[1] -= dt
            if self.research[1] <= 0:
                key = self.research[0]
                self.research = None
                game.complete_upgrade(self.player, key)

        if self.leveling:
            self.leveling[0] -= dt
            if self.leveling[0] <= 0:
                self.finish_level_up()
                game.on_level_up(self)

        if self.spec.get("atk") and self.cooldown <= 0.0:
            foe = game.find_enemy_near(self, self.attack_range, from_building=True)
            if foe:
                self.cooldown = self.spec["cooldown"]
                game.spawn_projectile(self, foe, self.attack)

    def status_label(self):
        if self.under_construction:
            return i18n.t("status.site", percent=int(self.progress * 100))
        if self.queue:
            kind, left, _total = self.queue[0]
            extra = (i18n.t("status.training_extra", count=len(self.queue) - 1)
                     if len(self.queue) > 1 else "")
            return i18n.t("status.training", name=i18n.unit_name(kind),
                          seconds=int(left) + 1, extra=extra)
        if self.research:
            return i18n.t("status.researching",
                          name=i18n.upgrade_name(self.research[0]))
        if self.leveling:
            return i18n.t("status.leveling", level=self.level + 1,
                          seconds=int(self.leveling[0]) + 1)
        return i18n.t("status.ready")


# ------------------------------------------------------ projectiles/effects ----
class Projectile(object):
    __slots__ = ("x", "y", "sx", "sy", "tx", "ty", "target", "damage", "team",
                 "source", "t", "dur", "alive", "spin")

    def __init__(self, source, target, damage):
        self.source = source
        self.target = target
        self.team = source.team
        self.damage = damage
        self.x = self.sx = source.x
        self.y = self.sy = source.y - 8
        self.tx, self.ty = target.x, target.y
        self.dur = max(0.12, dist(self.sx, self.sy, self.tx, self.ty) / PROJECTILE_SPEED)
        self.t = 0.0
        self.alive = True
        self.spin = random.random() * 6.28

    def update(self, dt, game):
        self.t += dt
        if self.target is not None and self.target.alive:
            self.tx, self.ty = self.target.x, self.target.y
        k = clamp(self.t / self.dur, 0.0, 1.0)
        self.x = self.sx + (self.tx - self.sx) * k
        self.y = self.sy + (self.ty - self.sy) * k - math.sin(k * math.pi) * 26.0
        self.spin += dt * 9.0
        if k >= 1.0:
            self.alive = False
            if self.target is not None and self.target.alive:
                game.deal_damage(self.source, self.target, self.damage,
                                 direct=True)
            game.add_effect(Puff(self.tx, self.ty, (170, 164, 158)))


class Puff(object):
    """A small puff of fur on impact."""
    __slots__ = ("x", "y", "t", "dur", "alive", "color", "parts")

    def __init__(self, x, y, color=(220, 210, 200), count=7, spread=46.0):
        self.x, self.y = x, y
        self.t, self.dur, self.alive = 0.0, 0.45, True
        self.color = color
        self.parts = []
        for _ in range(count):
            a = random.random() * 6.28318
            s = random.uniform(0.3, 1.0) * spread
            self.parts.append((math.cos(a) * s, math.sin(a) * s - 18.0,
                               random.uniform(1.6, 3.4)))

    def update(self, dt, game):
        self.t += dt
        if self.t >= self.dur:
            self.alive = False


class FloatText(object):
    __slots__ = ("x", "y", "text", "color", "t", "dur", "alive")

    def __init__(self, x, y, text, color=(240, 236, 220), dur=1.1):
        self.x, self.y, self.text, self.color = x, y, text, color
        self.t, self.dur, self.alive = 0.0, dur, True

    def update(self, dt, game):
        self.t += dt
        self.y -= 26.0 * dt
        if self.t >= self.dur:
            self.alive = False


class Corpse(object):
    __slots__ = ("x", "y", "utype", "team", "facing", "t", "alive")

    def __init__(self, unit):
        self.x, self.y = unit.x, unit.y
        self.utype = unit.utype
        self.team = unit.team
        self.facing = unit.facing
        self.t = 0.0
        self.alive = True

    def update(self, dt, game):
        self.t += dt
        if self.t >= CORPSE_TIME:
            self.alive = False

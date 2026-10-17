# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""The opposing AI: economy, build order, assault waves."""

import math
import random

from . import entities as E
from .settings import (BUILDINGS, DIFFICULTIES, MILITARY, RESOURCES,
                       R_CATNIP, R_KIBBLE, R_STONE, R_WOOL, TILE, UNITS,
                       UPGRADES, UPGRADE_ORDER)
from .utils import clamp, dist, dist2

# Target split of the gatherers, before it leans towards what is running low
GATHER_MIX = ((R_KIBBLE, 0.42), (R_WOOL, 0.36), (R_CATNIP, 0.16),
              (R_STONE, 0.06))

# The army gathers on a staging point this far from the basket, on the way to
# the enemy, and leaves from there as one wave.
STAGING_TILES = 8
# A wave falls back once fewer than this share of its cats are still alive.
RETREAT_SHARE = 0.35
# Fresh cats join a wave still on the move only as a group of this size.
REINFORCE_MIN = 4


class CatAI(object):
    def __init__(self, game, player, difficulty="tomcat"):
        self.game = game
        self.player = player
        self.cfg = DIFFICULTIES[difficulty]
        self.tempo = self.cfg["tempo"]
        self.think_timer = 1.5
        self.wave_timer = self.cfg["wave_delay"] * 0.85
        self.army_target = self.cfg["army"]
        self.worker_target = self.cfg["eco"]
        self.react_timer = 0.0
        self.attacking = False
        self.wave = []                 # the cats sent on the current assault
        self.wave_size = 0
        self.attack_point = None
        self.panic = 0.0
        self.base = game.home_base_pos(player)
        self.rng = random.Random(1234 + player.team)

    # -------------------------------------------------------------------- loop --
    def update(self, dt):
        if self.player.defeated:
            return
        self.wave_timer -= dt
        self.react_timer = max(0.0, self.react_timer - dt)
        self.panic = max(0.0, self.panic - dt)
        self.think_timer -= dt
        if self.think_timer > 0.0:
            return
        self.think_timer = 0.55 * self.tempo
        self.base = self.game.home_base_pos(self.player)
        self._defend()
        self._assign_workers()
        self._economy()
        self._build_order()
        self._army()
        self._research()
        self._towers()
        self._attack()

    # ---------------------------------------------------------------- access ---
    def _my_units(self, utype=None):
        return [u for u in self.game.units
                if u.player is self.player and u.alive
                and (utype is None or u.utype == utype)]

    def _my_buildings(self, btype=None, done=True):
        return [b for b in self.game.buildings
                if b.player is self.player and b.alive
                and (btype is None or b.btype == btype)
                and (not done or not b.under_construction)]

    def _military(self):
        return [u for u in self.game.units
                if u.player is self.player and u.alive and u.is_military]

    def _foe(self):
        """The other side. Not `game.human`: a test pits an AI on either side."""
        return next(p for p in self.game.players if p is not self.player)

    def _enemy_targets(self):
        foe = self._foe()
        out = [b for b in self.game.buildings if b.player is foe and b.alive]
        out.sort(key=lambda b: (b.btype != "basket",
                                dist2(b.x, b.y, self.base[0], self.base[1])))
        return out

    # -------------------------------------------------------------- economy ---
    def _afford_and_pay(self, cost):
        if self.player.can_afford(cost):
            self.player.pay(cost)
            return True
        return False

    def _assign_workers(self):
        workers = self._my_units("kitten")
        if not workers:
            return
        # Sites under way: send hands over there.
        sites = [b for b in self.game.buildings
                 if b.player is self.player and b.alive and b.under_construction]
        busy_builders = [w for w in workers if w.state == E.BUILD]
        for site in sites:
            want = 3 if site.btype in ("basket", "dojo", "scratching_post") else 2
            on_it = [w for w in busy_builders if w.site is site]
            if len(on_it) >= want:
                continue
            free = [w for w in workers
                    if w.state in (E.IDLE, E.GATHER, E.RETURN) and w.site is not site]
            free.sort(key=lambda w: dist2(w.x, w.y, site.x, site.y))
            for w in free[:want - len(on_it)]:
                w.order_build(self.game, site)
                busy_builders.append(w)

        mix = self._gather_mix()
        counts = {}
        for w in workers:
            if w.state in (E.GATHER, E.RETURN) and w.node is not None:
                counts[w.node.kind] = counts.get(w.node.kind, 0) + 1
        total = max(1, sum(counts.values()))
        idle = [w for w in workers if w.state == E.IDLE]
        for w in idle:
            want = None
            worst = -1.0
            for kind, ratio in mix:
                have = counts.get(kind, 0) / float(total)
                gap = ratio - have
                if gap > worst:
                    worst, want = gap, kind
            # The wanted kind, even a long walk away, before anything else:
            # the nearest node of any kind kept kittens on stone while the
            # kibble ran out.
            node = (self.game.world.nearest_node(w.x, w.y, want, 30)
                    or self.game.world.nearest_node(w.x, w.y, want, 70))
            for kind, _ratio in sorted(mix, key=lambda e: -e[1]):
                if node is not None:
                    break
                node = self.game.world.nearest_node(w.x, w.y, kind, 40)
            if node is not None:
                w.order_gather(self.game, node)
                counts[node.kind] = counts.get(node.kind, 0) + 1
                total += 1

        # Move one gatherer at a time from the most over-served resource to
        # the most wanted one. Without it a kitten stays on its first node
        # type for good, and the split only ever changed through new hires.
        if self.rng.random() < 0.35 and len(workers) >= 4:
            total = max(1, sum(counts.values()))
            target = dict(mix)
            under = max(mix, key=lambda e: e[1] - counts.get(e[0], 0) / total)[0]
            gaps = [(counts[k] / float(total) - target.get(k, 0.0), k)
                    for k in counts]
            if gaps:
                excess, over = max(gaps)
                if over != under and excess > 0.10:
                    cand = [w for w in workers if w.state == E.GATHER
                            and w.node is not None and w.node.kind == over
                            and w.carry < 4]
                    if cand:
                        w = self.rng.choice(cand)
                        node = self.game.world.nearest_node(w.x, w.y, under, 34)
                        if node:
                            w.order_gather(self.game, node)

    def _gather_mix(self):
        """The target split, leaning towards whatever runs low.

        A fixed split let the kibble run dry while wool and catnip piled up
        by the thousand, and with no kibble no cat gets recruited at all.
        Stone only counts while a tower can still go higher.
        """
        want_stone = any(b.next_level() is not None
                         for b in self._my_buildings("tower"))
        weights = []
        for kind, ratio in GATHER_MIX:
            if kind == R_STONE and not want_stone:
                continue
            need = clamp(500.0 / (self.player.res.get(kind, 0) + 150.0),
                         0.3, 3.0)
            weights.append((kind, ratio * need))
        total = sum(w for _, w in weights)
        return tuple((kind, w / total) for kind, w in weights)

    def _economy(self):
        centers = self._my_buildings("basket")
        if not centers:
            self._rebuild_center()
            return
        workers = len(self._my_units("kitten"))
        queued = sum(1 for b in centers for q in b.queue if q[0] == "kitten")
        if workers + queued < self.worker_target:
            c = min(centers, key=lambda b: len(b.queue))
            if len(c.queue) < 3:
                self._try_train(c, "kitten")

    def _rebuild_center(self):
        """No basket left: plant another one if any kittens survive."""
        workers = self._my_units("kitten")
        if not workers or not self.player.can_afford(BUILDINGS["basket"]["cost"]):
            return
        w = workers[0]
        self._place_near((w.x, w.y), "basket", radius=8, builders=workers[:4])

    def _try_train(self, building, utype):
        spec = UNITS[utype]
        if not building.can_train(utype):
            return False
        if self.player.pop + spec["pop"] > self.player.pop_limit:
            return False
        if not self._afford_and_pay(spec["cost"]):
            return False
        building.enqueue(utype)
        return True

    # --------------------------------------------------------- construction ---
    def _place_near(self, origin, btype, radius=9, builders=None):
        size = BUILDINGS[btype]["size"]
        ox, oy = int(origin[0] // TILE), int(origin[1] // TILE)
        best = None
        for r in range(2, radius + 1):
            cands = []
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if max(abs(dx), abs(dy)) != r:
                        continue
                    tx, ty = ox + dx, oy + dy
                    if self.game.world.can_place(tx, ty, size):
                        # keep a lane around the building
                        if self.game.world.can_place(tx - 1, ty - 1, size + 2):
                            cands.append((tx, ty))
            if cands:
                best = self.rng.choice(cands)
                break
        if best is None:
            return None
        b = self.game.place_building(self.player, btype, best[0], best[1])
        if b is None:
            return None
        if builders is None:
            workers = self._my_units("kitten")
            workers.sort(key=lambda w: dist2(w.x, w.y, b.x, b.y))
            builders = workers[:3]
        for w in builders:
            w.order_build(self.game, b)
        return b

    def _build_order(self):
        p = self.player
        pending = [b for b in self.game.buildings
                   if b.player is p and b.alive and b.under_construction]
        if len(pending) >= 2:
            return
        houses = self._my_buildings("shed", done=False)
        barracks = self._my_buildings("scratching_post", done=False)
        dojos = self._my_buildings("dojo", done=False)
        towers = self._my_buildings("tower", done=False)

        # 1. always room for the population (counting what is on its way)
        queued_pop = sum(UNITS[q[0]]["pop"]
                         for b in self._my_buildings() for q in b.queue)
        incoming_cap = sum(BUILDINGS[b.btype].get("pop_bonus", 0) for b in pending)
        headroom = (p.pop_limit + incoming_cap) - (p.pop + queued_pop)
        if headroom <= 4 and p.pop_limit + incoming_cap < 90:
            if p.can_afford(BUILDINGS["shed"]["cost"]):
                self._place_near(self.base, "shed", 10)
                return
        # 2. barracks early on
        if not barracks and self.game.elapsed > 35.0 * self.tempo:
            if p.can_afford(BUILDINGS["scratching_post"]["cost"]):
                self._place_near(self.base, "scratching_post", 11)
                return
        # 3. a dojo for the tomcats and the upgrades
        if barracks and not dojos and self.game.elapsed > 150.0 * self.tempo:
            if p.can_afford(BUILDINGS["dojo"]["cost"]):
                self._place_near(self.base, "dojo", 12)
                return
        # 4. a second barracks once the economy keeps up
        if len(barracks) < 2 and self.game.elapsed > 240.0 * self.tempo:
            if p.res[R_WOOL] > 320:
                self._place_near(self.base, "scratching_post", 12)
                return
        # 5. towers when we are being harassed
        if self.panic > 0.0 and len(towers) < 3:
            if p.can_afford(BUILDINGS["tower"]["cost"]):
                self._place_near(self.attack_point or self.base, "tower", 7)
                return
        # 6. another basket next to the resource that is running low, once
        #    the nodes of that kind near home are worked out
        baskets = self._my_buildings("basket", done=False)
        if (len(baskets) < 3
                and self.game.elapsed > 300.0 * self.tempo
                and p.res[R_WOOL] > 420):
            kinds = [k for k, _ in sorted(self._gather_mix(), key=lambda e: -e[1])
                     if k != R_STONE]
            for kind in kinds[:1]:
                far = self.game.world.nearest_node(self.base[0], self.base[1],
                                                   kind, 60)
                if far and all(dist(far.x, far.y, b.x, b.y) > 14 * TILE
                               for b in baskets):
                    self._place_near((far.x, far.y), "basket", 6)

    # ------------------------------------------------------------------ army ---
    def _army(self):
        barracks = self._my_buildings("scratching_post")
        dojos = self._my_buildings("dojo")
        army = len(self._military())
        queued = sum(len(b.queue) for b in barracks + dojos)
        if army + queued >= self.army_target + 4:
            return
        for b in dojos:
            if len(b.queue) < 2 and self.player.res[R_CATNIP] > 120:
                self._try_train(b, "tomcat")
        for b in barracks:
            if len(b.queue) >= 3:
                continue
            # a melee / ranged mix
            ranged = len(self._my_units("spitter"))
            melee = len(self._my_units("scratcher"))
            pick = "spitter" if ranged * 2 < melee + 1 else "scratcher"
            if not self._try_train(b, pick):
                self._try_train(b, "scratcher")

    def _research(self):
        dojos = [b for b in self._my_buildings("dojo") if b.research is None]
        if not dojos:
            return
        for key in UPGRADE_ORDER:
            if key in self.player.upgrades or key in self.player.researching:
                continue
            spec = UPGRADES[key]
            if self._afford_and_pay(spec["cost"]):
                self.player.researching.add(key)
                dojos[0].start_research(key)
            return

    def _towers(self):
        """Take one tower a level higher whenever the stone is there."""
        for b in self._my_buildings("tower"):
            step = b.next_level()
            if step is None or b.leveling is not None:
                continue
            if self._afford_and_pay(step["cost"]):
                b.start_level_up()
            return

    # -------------------------------------------------------------- defence ---
    def _defend(self):
        base = self.base
        threat = None
        best = 1e18
        for u in self.game.units:
            if u.player is self.player or not u.alive:
                continue
            d = dist2(u.x, u.y, base[0], base[1])
            if d < (16 * TILE) ** 2 and d < best:
                threat, best = u, d
        if threat is None:
            for b in self.game.buildings:
                if b.player is self.player and b.alive and b.hp < b.max_hp * 0.98:
                    if b.last_attacker is not None and b.last_attacker.alive:
                        threat = b.last_attacker
                        break
        if threat is None:
            return
        self.panic = 25.0
        self.attack_point = (threat.x, threat.y)
        if self.react_timer > 0.0:
            return
        self.react_timer = self.cfg["react"]
        self._end_wave()
        for u in self._military():
            if dist2(u.x, u.y, base[0], base[1]) < (34 * TILE) ** 2:
                u.order_attack_move(self.game, threat.x, threat.y)
        # the nearby kittens take cover in the basket
        for w in self._my_units("kitten"):
            if dist2(w.x, w.y, threat.x, threat.y) < (5 * TILE) ** 2:
                w.order_move(self.game, base[0], base[1])

    # -------------------------------------------------------------- offensive --
    def _staging_point(self):
        """Where the army gathers between two waves: in front of the basket,
        on the way to the enemy."""
        bx, by = self.base
        fx, fy = self.game.home_base_pos(self._foe())
        d = dist(bx, by, fx, fy)
        if d < 1.0:
            return self.base
        k = min(1.0, STAGING_TILES * TILE / d)
        return (bx + (fx - bx) * k, by + (fy - by) * k)

    def _end_wave(self, fall_back=False):
        """Close the current assault; the survivors may come home."""
        if fall_back:
            sx, sy = self._staging_point()
            for u in self.wave:
                if u.alive:
                    u.order_move(self.game, sx, sy)
        self.attacking = False
        self.wave = []
        self.wave_size = 0

    def _target_point(self):
        targets = self._enemy_targets()
        if targets:
            return targets[0]
        # no building left in sight: sweep towards the enemy cats
        foe = self._foe()
        return next((u for u in self.game.units
                     if u.player is foe and u.alive), None)

    def _send(self, units, target):
        for i, u in enumerate(units):
            ox = math.cos(i * 1.7) * TILE * 2.0
            oy = math.sin(i * 1.7) * TILE * 2.0
            u.order_attack_move(self.game, target.x + ox, target.y + oy)

    def _attack(self):
        """Assault in waves, never one cat at a time.

        The cats left at home gather on the staging point. A wave leaves
        once enough of them stand there, falls back when it has been cut
        down, and fresh cats only join it as a group. The earlier version
        sent every newly recruited cat straight at the enemy, alone, which
        fed the opponent one kill at a time.
        """
        if self.panic > 0.0:
            return
        army = self._military()
        wave_ids = set(u.eid for u in self.wave)
        home = [u for u in army if u.eid not in wave_ids]
        sx, sy = self._staging_point()

        if self.attacking:
            self.wave = [u for u in self.wave if u.alive]
            if len(self.wave) < max(2, self.wave_size * RETREAT_SHARE):
                self._end_wave(fall_back=True)
                self.wave_timer = max(self.wave_timer,
                                      self.cfg["wave_delay"] * 0.5)
            else:
                target = self._target_point()
                idle = [u for u in self.wave if u.state == E.IDLE]
                if target is None:
                    if len(idle) == len(self.wave):
                        self._end_wave(fall_back=True)
                elif idle:
                    self._send(idle, target)
                ready = [u for u in home if u.state == E.IDLE
                         and dist(u.x, u.y, sx, sy) < 6 * TILE]
                if target is not None and len(ready) >= REINFORCE_MIN:
                    self._send(ready, target)
                    self.wave.extend(ready)
                    self.wave_size += len(ready)
                    home = [u for u in home if u not in ready]

        # Everyone not on an assault waits on the staging point.
        for u in home:
            if u.state == E.IDLE and dist(u.x, u.y, sx, sy) > 4 * TILE:
                u.order_move(self.game, sx, sy)
        if self.attacking:
            return

        gathered = [u for u in home if dist(u.x, u.y, sx, sy) < 6 * TILE]
        ready = len(gathered) >= self.army_target
        if not ready or self.wave_timer > 0.0:
            if not ready and self.wave_timer <= 0.0:
                self.wave_timer = 12.0      # hold on, the army is reforming
            return
        target = self._target_point()
        if target is None:
            return
        self.attacking = True
        self.wave = list(gathered)
        self.wave_size = len(gathered)
        self.wave_timer = self.cfg["wave_delay"]
        self.army_target = min(42, self.army_target + 3)
        self.worker_target = min(26, self.worker_target + 2)
        self._send(self.wave, target)

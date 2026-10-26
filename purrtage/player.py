# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""A player's state: treasury, population, upgrades."""

from . import i18n
from .settings import (FACTIONS, POP_HARD_CAP, RESOURCES, START_RESOURCES,
                       TEAM_COLORS, UPGRADES)


class Player(object):
    def __init__(self, team, is_ai=False, difficulty=None, name=None,
                 faction=None):
        self.team = team
        self.is_ai = is_ai
        self.difficulty = difficulty
        self._name = name
        # A chosen faction wears its own colour; otherwise fall back to the
        # team's default. Cosmetic only: the colour never reaches the sim.
        self.faction = faction if faction in FACTIONS else None
        self.color = (FACTIONS[self.faction]["color"] if self.faction
                      else TEAM_COLORS[team % len(TEAM_COLORS)])
        self.res = dict(START_RESOURCES)
        self.pop = 0
        self.pop_cap = 0
        self.upgrades = set()
        self.researching = set()
        self.defeated = False
        # end-of-game statistics
        self.stat_gathered = dict((r, 0) for r in RESOURCES)
        self.stat_units = 0
        self.stat_kills = 0
        self.stat_losses = 0
        self.stat_buildings = 0

    @property
    def name(self):
        """The side's name. Translated on read: the language can change in game."""
        if self._name:
            return self._name
        if self.faction:
            return i18n.faction_name(self.faction)
        return i18n.team_name(self.team)

    # ------------------------------------------------------------ resources --
    def can_afford(self, cost):
        return all(self.res.get(k, 0) >= v for k, v in cost.items())

    def missing(self, cost):
        """The resources that are missing to pay `cost`."""
        return [k for k, v in cost.items() if self.res.get(k, 0) < v]

    def pay(self, cost):
        if not self.can_afford(cost):
            return False
        for k, v in cost.items():
            self.res[k] -= v
        return True

    def refund(self, cost):
        for k, v in cost.items():
            self.res[k] = self.res.get(k, 0) + v

    def add(self, kind, qty):
        self.res[kind] = self.res.get(kind, 0) + qty
        self.stat_gathered[kind] = self.stat_gathered.get(kind, 0) + qty

    # ---------------------------------------------------------- population ---
    @property
    def pop_limit(self):
        return min(self.pop_cap, POP_HARD_CAP)

    def has_pop(self, amount=1):
        return self.pop + amount <= self.pop_limit

    # -------------------------------------------------------------- upgrades --
    def atk_bonus(self):
        return sum(UPGRADES[u].get("atk", 0) for u in self.upgrades)

    def armor_bonus(self):
        return sum(UPGRADES[u].get("armor", 0) for u in self.upgrades)

    def speed_mult(self):
        m = 1.0
        for u in self.upgrades:
            m *= UPGRADES[u].get("speed_mult", 1.0)
        return m

    def hp_mult(self):
        m = 1.0
        for u in self.upgrades:
            m *= UPGRADES[u].get("hp_mult", 1.0)
        return m

    def upgrade_state(self, key):
        if key in self.upgrades:
            return "done"
        if key in self.researching:
            return "busy"
        return "available"

# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Serialisable orders — the only thing that travels between the two machines.

Networked play runs in "lockstep": the game state is never transmitted, only
the orders that were given, and each machine replays the same simulation. An
order therefore designates its entities by identifier, never by reference, and
its execution must not depend on any local information (selection, fog, mouse
position).

Resolving "what does this click mean?" stays local: it reads the selection and
the fog, then produces a concrete order. That order is what goes out over the
network.
"""

from . import i18n

MOVE = "move"
AMOVE = "amove"
ATTACK = "attack"
GATHER = "gather"
BUILD = "build"
PLACE = "place"
STOP = "stop"
TRAIN = "train"
RESEARCH = "research"
LEVEL_UP = "level_up"
CANCEL_PROD = "cancel_prod"
CANCEL_SITE = "cancel_site"
RALLY = "rally"

MARKER_COLORS = {
    MOVE: (150, 240, 160),
    AMOVE: (240, 150, 110),
    ATTACK: (240, 120, 120),
    GATHER: (240, 220, 130),
    BUILD: (160, 220, 240),
    RALLY: (240, 230, 150),
}


def make(team, kind, **payload):
    """Build an order. `team` identifies who gave it, not who carries it out."""
    cmd = {"team": int(team), "kind": kind}
    cmd.update(payload)
    return cmd


# --------------------------------------------------------------- execution --
def _units(game, cmd):
    """The targeted live units, filtered by side: a player never commands the
    cats from the other side, even if the order received asked for it."""
    team = cmd["team"]
    out = []
    for eid in cmd.get("ids", ()):
        ent = game.entity_by_id(eid)
        if ent is not None and ent.alive and ent.is_unit and ent.team == team:
            out.append(ent)
    return out


def _building(game, cmd, key="eid"):
    ent = game.entity_by_id(cmd.get(key))
    if ent is None or not ent.alive or not ent.is_building:
        return None
    if ent.team != cmd["team"]:
        return None
    return ent


def apply(game, cmd):
    """Carry out an order. Must give the same result on both machines."""
    kind = cmd.get("kind")
    handler = _HANDLERS.get(kind)
    if handler is None:
        return False
    done = handler(game, cmd)
    if done and cmd["team"] == game.human.team:
        _feedback(game, cmd, kind)
    return done


def _feedback(game, cmd, kind):
    """Local feedback: a ground marker and a small sound. Never for the opponent."""
    color = MARKER_COLORS.get(kind)
    if color is not None and "x" in cmd:
        game.markers.append([cmd["x"], cmd["y"], 0.0, color])
    if kind in (MOVE, AMOVE, ATTACK, GATHER, BUILD):
        game.play("order")


def _do_move(game, cmd):
    units = _units(game, cmd)
    if not units:
        return False
    game.formation_move(units, cmd["x"], cmd["y"], cmd.get("queued", False))
    return True


def _do_amove(game, cmd):
    units = _units(game, cmd)
    for u in units:
        u.order_attack_move(game, cmd["x"], cmd["y"], cmd.get("queued", False))
    return bool(units)


def _do_attack(game, cmd):
    units = _units(game, cmd)
    target = game.entity_by_id(cmd.get("target"))
    if not units or target is None or not target.alive:
        return False
    if target.team == cmd["team"]:
        return False
    for u in units:
        u.order_attack(game, target)
    return True


def _do_gather(game, cmd):
    units = _units(game, cmd)
    node = game.world.node_at.get((cmd["tx"], cmd["ty"]))
    if not units:
        return False
    if node is None or not node.alive:
        return _do_move(game, cmd) if "x" in cmd else False
    for u in units:
        if u.spec.get("builder"):
            u.order_gather(game, node)
        else:
            u.order_move(game, cmd["x"], cmd["y"], cmd.get("queued", False))
    return True


def _do_build(game, cmd):
    units = _units(game, cmd)
    site = game.entity_by_id(cmd.get("target"))
    if not units or site is None or not site.alive or not site.is_building:
        return False
    if site.team != cmd["team"]:
        return False
    for u in units:
        if u.spec.get("builder"):
            u.order_build(game, site)
        else:
            u.order_move(game, cmd["x"], cmd["y"], cmd.get("queued", False))
    return True


def _do_place(game, cmd):
    player = game.player_by_team(cmd["team"])
    if player is None:
        return False
    site = game.place_building(player, cmd["btype"], cmd["tx"], cmd["ty"])
    if site is None:
        # Ground taken or treasury too low: both machines reach the same
        # conclusion, so they stay in agreement.
        if cmd["team"] == game.human.team:
            game.message(i18n.t("messages.cannot_place"), (236, 150, 120))
            game.play("deny")
        return False
    for u in _units(game, cmd)[:5]:
        if u.spec.get("builder"):
            u.order_build(game, site)
    if cmd["team"] == game.human.team:
        game.play("place")
    return True


def _do_stop(game, cmd):
    units = _units(game, cmd)
    for u in units:
        u.stop()
    return bool(units)


def _do_train(game, cmd):
    b = _building(game, cmd)
    return bool(b) and game.train(b, cmd["utype"])


def _do_research(game, cmd):
    b = _building(game, cmd)
    return bool(b) and game.research(b, cmd["key"])


def _do_level_up(game, cmd):
    b = _building(game, cmd)
    return bool(b) and game.level_up(b)


def _do_cancel_prod(game, cmd):
    b = _building(game, cmd)
    if b is None:
        return False
    what = b.cancel_last(game)
    if what and cmd["team"] == game.human.team:
        game.message(i18n.t("messages.production_cancelled"), (210, 210, 210))
    return bool(what)


def _do_cancel_site(game, cmd):
    b = _building(game, cmd)
    if b is None or not b.under_construction:
        return False
    from .settings import BUILDINGS
    b.player.refund(BUILDINGS[b.btype]["cost"])
    b.alive = False
    game.world.set_occupancy(b.tiles, False)
    if cmd["team"] == game.human.team:
        game.message(i18n.t("messages.site_abandoned"), (210, 210, 210))
    return True


def _do_rally(game, cmd):
    b = _building(game, cmd)
    if b is None or b.under_construction:
        return False
    b.rally = (cmd["x"], cmd["y"])
    if cmd["team"] == game.human.team:
        game.message(i18n.t("messages.rally_set"), (210, 215, 230))
    return True


_HANDLERS = {
    MOVE: _do_move,
    AMOVE: _do_amove,
    ATTACK: _do_attack,
    GATHER: _do_gather,
    BUILD: _do_build,
    PLACE: _do_place,
    STOP: _do_stop,
    TRAIN: _do_train,
    RESEARCH: _do_research,
    LEVEL_UP: _do_level_up,
    CANCEL_PROD: _do_cancel_prod,
    CANCEL_SITE: _do_cancel_site,
    RALLY: _do_rally,
}

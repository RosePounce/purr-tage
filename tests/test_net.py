# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of the network transport and of the lockstep scheduler."""

import os
import time
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

pygame.init()
pygame.display.set_mode((64, 64))

from purrtage import commands as C                                   # noqa: E402
from purrtage import lockstep, net                                   # noqa: E402
from purrtage.game import Game                                       # noqa: E402
from purrtage.world import World                                     # noqa: E402

PORT = 50599            # a port dedicated to the tests, so no game is disturbed


def wait_for(predicate, timeout=5.0, step=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


class TestTransport(unittest.TestCase):
    def setUp(self):
        self.host = net.Host(name="test", port=PORT, announce=False)
        self.client = None

    def tearDown(self):
        if self.client:
            self.client.close()
        self.host.close()

    def _pair(self):
        self.client = net.connect("127.0.0.1", PORT, timeout=3.0)
        self.assertTrue(wait_for(lambda: self.host.connected),
                        "the host did not accept the connection")
        return self.host.link, self.client

    def test_messages_travel_both_ways(self):
        server, client = self._pair()
        server.send({"type": "start", "seed": 1234, "team": 1})
        self.assertTrue(wait_for(lambda: client.inbox.qsize() > 0))
        got = client.poll()
        self.assertEqual(got[0]["seed"], 1234)
        client.send({"type": "turn", "turn": 0, "cmds": []})
        self.assertTrue(wait_for(lambda: server.inbox.qsize() > 0))
        self.assertEqual(server.poll()[0]["turn"], 0)

    def test_accents_and_large_payloads_survive(self):
        server, client = self._pair()
        orders = [C.make(0, C.MOVE, ids=list(range(60)), x=1.5, y=2.5)
                  for _ in range(40)]
        server.send({"type": "turn", "turn": 7, "cmds": orders,
                     "note": "récolté à côté du Panier"})
        self.assertTrue(wait_for(lambda: client.inbox.qsize() > 0))
        msg = client.poll()[0]
        self.assertEqual(len(msg["cmds"]), 40)
        # Accented French on purpose: that is what the wire has to survive.
        self.assertEqual(msg["note"], "récolté à côté du Panier")

    def test_a_closed_link_is_reported(self):
        server, client = self._pair()
        client.close()
        self.assertTrue(wait_for(lambda: not server.alive),
                        "the cut is not detected")


class TestLockstep(unittest.TestCase):
    """Two linked simulations must stay identical turn after turn."""

    def setUp(self):
        self.host = net.Host(name="test", port=PORT, announce=False)
        self.client = net.connect("127.0.0.1", PORT, timeout=3.0)
        wait_for(lambda: self.host.connected)
        self.games = []
        self.sessions = []

    def tearDown(self):
        for s in self.sessions:
            s.close()
        self.client.close()
        self.host.close()

    def _session(self, link, team):
        game = Game(World(seed=777), fog_enabled=False, local_team=team,
                    use_ai=False)
        session = lockstep.NetSession(game, link, team)
        self.games.append(game)
        self.sessions.append(session)
        return game, session

    def _run(self, turns):
        """Advance both sessions up to the wanted number of turns."""
        deadline = time.time() + 20.0
        while time.time() < deadline:
            for s in self.sessions:
                s.update(lockstep.TURN_PERIOD)
            if all(s.turn >= turns for s in self.sessions):
                return True
            time.sleep(0.002)
        return False

    def test_orders_are_delayed_not_immediate(self):
        """An order does not run on the turn it is given: it travels."""
        game, session = self._session(self.host.link, 0)
        unit = next(u for u in game.units if u.player is game.human)
        before = (unit.x, unit.y)
        game.submit(C.make(0, C.MOVE, ids=[unit.eid],
                           x=before[0] + 300, y=before[1]))
        self.assertEqual(session.turn, 0)
        self.assertEqual(unit.dest, None, "the order was applied right away")

    def test_both_sides_stay_identical(self):
        ga, sa = self._session(self.host.link, 0)
        gb, sb = self._session(self.client, 1)
        # each side commands its own cats
        for game, team in ((ga, 0), (gb, 1)):
            base = game.home_base_pos(game.human)
            node = game.world.nearest_node(base[0], base[1], "wool", 20)
            ids = [u.eid for u in game.units if u.player is game.human][:2]
            game.submit(C.make(team, C.GATHER, ids=ids, tx=node.tx, ty=node.ty,
                               x=node.x, y=node.y))
        self.assertTrue(self._run(40), "the sessions are not advancing")
        self.assertIsNone(sa.desync)
        self.assertIsNone(sb.desync)
        self.assertEqual(ga.tick_no, gb.tick_no)
        self.assertEqual(ga.checksum(), gb.checksum())

    def test_a_peer_waits_instead_of_running_ahead(self):
        """Without the other side's orders we wait: never a solo run-ahead."""
        ga, sa = self._session(self.host.link, 0)
        for _ in range(30):
            sa.update(lockstep.TURN_PERIOD)
        self.assertLessEqual(sa.turn, lockstep.TURN_DELAY,
                             "a machine carried on without its opponent")
        self.assertTrue(sa.waiting)


if __name__ == "__main__":
    unittest.main(verbosity=2)

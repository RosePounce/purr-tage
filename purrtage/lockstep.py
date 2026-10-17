# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Lockstep: two machines play the same game by exchanging orders only.

Time is cut into "turns" of a few simulation steps. An order entered during
turn T is not played right away: it goes out over the network and runs on turn
T + DELAY, at the same moment on both sides. That small deferral — a tenth of
a second here — is what gives the packets time to arrive.

A machine never advances a turn before it has received the other side's orders
for that turn. When the network hiccups, both games wait together rather than
diverging.
"""

from .settings import TICK_DT
from . import commands as C
from . import i18n

TURN_TICKS = 3                       # simulation steps per turn
TURN_PERIOD = TURN_TICKS * TICK_DT   # 0.1 s at 30 Hz
TURN_DELAY = 2                       # turns of lead: the tolerated latency
MAX_LAG = 1.0                        # beyond this we stop piling up the delay


class NetSession(object):
    def __init__(self, game, link, local_team):
        self.game = game
        self.link = link
        self.local_team = local_team
        self.turn = 0                 # next turn to run
        self.sealed = 0               # next turn to seal and send
        self.pending = []             # orders entered since the last seal
        self.local_turns = {}         # turn -> orders from this side
        self.remote_turns = {}        # turn -> orders from the other side
        self.local_sums = {}
        self.remote_sums = {}
        self.desync = None            # (turn, ours, theirs) on divergence
        self.lost = False             # link cut
        self.waiting = False          # we are waiting on the opponent
        self.waited = 0.0             # recent cumulated waiting time
        self._acc = 0.0
        game.dispatch = self.submit
        game.speed = 1.0              # the game speed is shared
        for _ in range(TURN_DELAY):   # priming: the first turns are empty
            self._seal()

    # --------------------------------------------------------------- orders --
    def submit(self, cmd):
        """Called by the game: the order goes out and runs in two turns."""
        self.pending.append(cmd)
        return True

    def _seal(self):
        """Freeze the orders that were entered and send them for a future turn."""
        turn = self.sealed
        cmds = self.pending
        self.pending = []
        self.local_turns[turn] = cmds
        packet = {"type": "turn", "turn": turn, "cmds": cmds}
        last = turn - TURN_DELAY - 1
        if last in self.local_sums:
            packet["sum_turn"] = last
            packet["sum"] = self.local_sums[last]
        self.link.send(packet)
        self.sealed += 1

    # -------------------------------------------------------------- network --
    def _read(self):
        for msg in self.link.poll():
            if msg.get("type") == "turn":
                self.remote_turns[int(msg["turn"])] = msg.get("cmds", [])
                if "sum" in msg:
                    self.remote_sums[int(msg["sum_turn"])] = msg["sum"]
            elif msg.get("type") == "bye":
                self.lost = True
        if not self.link.alive:
            self.lost = True

    def _check_sums(self):
        if self.desync is not None:
            return
        for turn, theirs in list(self.remote_sums.items()):
            ours = self.local_sums.get(turn)
            if ours is None:
                continue
            if ours != theirs:
                self.desync = (turn, ours, theirs)
                return
            del self.remote_sums[turn]

    # ------------------------------------------------------------ execution --
    def _can_run(self):
        return (self.turn in self.local_turns
                and self.turn in self.remote_turns)

    def _run_turn(self):
        turn = self.turn
        # Fixed application order: side 0 then side 1, and in the order they
        # were entered. Without that, two competing orders could resolve
        # differently from one machine to the other.
        batch = []
        mine = self.local_turns.pop(turn, [])
        theirs = self.remote_turns.pop(turn, [])
        for cmd in mine + theirs:
            batch.append(cmd)
        batch.sort(key=lambda c: c.get("team", 0))
        for cmd in batch:
            C.apply(self.game, cmd)
        for _ in range(TURN_TICKS):
            self.game.tick()
        self.turn += 1
        self.local_sums[turn] = self.game.checksum()
        self._seal()

    def update(self, dt):
        """Advance the game at the network pace. Returns how many turns ran."""
        self._read()
        self._check_sums()
        if self.lost or self.desync:
            self.waiting = False
            return 0
        self._acc = min(self._acc + dt, MAX_LAG)
        played = 0
        while self._acc >= TURN_PERIOD:
            if not self._can_run():
                break
            self._acc -= TURN_PERIOD
            self._run_turn()
            played += 1
        self.waiting = self._acc >= TURN_PERIOD and not self._can_run()
        self.waited = self.waited + dt if self.waiting else 0.0
        return played

    # ---------------------------------------------------------------- state --
    def status(self):
        if self.desync:
            return i18n.t("net.desync", turn=self.desync[0])
        if self.lost:
            return i18n.t("net.link_lost")
        if self.waiting and self.waited > 0.35:
            return i18n.t("net.waiting")
        return None

    def close(self):
        try:
            self.link.send({"type": "bye"})
        except Exception:
            pass
        self.link.close()

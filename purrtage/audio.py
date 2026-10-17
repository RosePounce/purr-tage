# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sounds synthesised on the fly (no audio file needed).

Everything is wrapped: when the mixer is unavailable (a server without a
sound card), the game simply carries on silently.
"""

import array
import math
import random

import pygame

RATE = 22050


def _envelope(i, n, attack=0.02, release=0.35):
    a = max(1, int(n * attack))
    r = max(1, int(n * release))
    if i < a:
        return i / float(a)
    if i > n - r:
        return max(0.0, (n - i) / float(r))
    return 1.0


def _tone(freq_fn, dur, volume=0.3, kind="sine", vibrato=0.0, noise=0.0):
    n = int(RATE * dur)
    buf = array.array("h")
    phase = 0.0
    for i in range(n):
        t = i / float(RATE)
        f = freq_fn(t / dur if dur else 0.0)
        if vibrato:
            f *= 1.0 + vibrato * math.sin(t * 38.0)
        phase += 2.0 * math.pi * f / RATE
        if kind == "sine":
            v = math.sin(phase)
        elif kind == "saw":
            v = (phase % (2 * math.pi)) / math.pi - 1.0
        elif kind == "square":
            v = 1.0 if math.sin(phase) > 0 else -1.0
        else:
            v = math.sin(phase)
        if noise:
            v = v * (1.0 - noise) + random.uniform(-1.0, 1.0) * noise
        v *= _envelope(i, n) * volume
        buf.append(int(max(-1.0, min(1.0, v)) * 32000))
    return buf


class Audio(object):
    def __init__(self, enabled=True):
        self.enabled = False
        self.sounds = {}
        self.volume = 0.55
        self._last = {}
        if not enabled:
            return
        try:
            pygame.mixer.pre_init(RATE, -16, 1, 512)
            pygame.mixer.init(RATE, -16, 1, 512)
            self.enabled = True
        except Exception:
            self.enabled = False
            return
        try:
            self._build()
        except Exception:
            self.enabled = False

    def _snd(self, buf):
        return pygame.mixer.Sound(buffer=buf.tobytes())

    def _build(self):
        s = self.sounds
        # meow: rising then falling, with vibrato
        s["meow"] = self._snd(_tone(
            lambda k: 480 + 300 * math.sin(k * 3.1) - 120 * k, 0.34, 0.30,
            "saw", vibrato=0.035))
        s["select"] = self._snd(_tone(lambda k: 660 + 180 * k, 0.09, 0.20, "sine"))
        s["order"] = self._snd(_tone(lambda k: 520 - 120 * k, 0.11, 0.22, "sine"))
        s["click"] = self._snd(_tone(lambda k: 880, 0.05, 0.18, "square"))
        s["deny"] = self._snd(_tone(lambda k: 220 - 60 * k, 0.16, 0.26, "square"))
        s["hit"] = self._snd(_tone(lambda k: 320 - 160 * k, 0.11, 0.30,
                                   "saw", noise=0.55))
        s["spit"] = self._snd(_tone(lambda k: 900 - 500 * k, 0.12, 0.20,
                                    "saw", noise=0.35))
        s["hurt"] = self._snd(_tone(
            lambda k: 700 - 420 * k, 0.26, 0.30, "saw", vibrato=0.07))
        s["boom"] = self._snd(_tone(lambda k: 160 - 80 * k, 0.45, 0.38,
                                    "saw", noise=0.75))
        s["build"] = self._snd(_tone(lambda k: 420 + 260 * k, 0.22, 0.24, "sine"))
        s["place"] = self._snd(_tone(lambda k: 300 + 120 * k, 0.13, 0.22, "sine"))
        s["upgrade"] = self._snd(_tone(lambda k: 520 + 420 * k, 0.40, 0.26, "sine"))
        s["alert"] = self._snd(_tone(
            lambda k: 740 if int(k * 4) % 2 == 0 else 520, 0.42, 0.30, "square"))
        s["victory"] = self._snd(_tone(
            lambda k: (523, 659, 784, 1046)[min(3, int(k * 4))], 1.05, 0.30, "sine"))
        s["defeat"] = self._snd(_tone(
            lambda k: (440, 392, 330, 262)[min(3, int(k * 4))], 1.15, 0.30, "saw"))
        for snd in s.values():
            snd.set_volume(self.volume)

    def play(self, key, cooldown=0.06):
        if not self.enabled:
            return
        snd = self.sounds.get(key)
        if snd is None:
            return
        now = pygame.time.get_ticks() / 1000.0
        if now - self._last.get(key, -9.0) < cooldown:
            return
        self._last[key] = now
        try:
            snd.play()
        except Exception:
            pass

    def set_volume(self, v):
        self.volume = max(0.0, min(1.0, v))
        for snd in self.sounds.values():
            snd.set_volume(self.volume)

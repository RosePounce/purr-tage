# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bug reports: the player's description, the game context and a screenshot.

Triggered by F8. The game pauses, the player describes what they saw, and the
whole lot goes into `saves/bug/` next to a capture of the screen as it was at
the moment of the report.

The report is written in the player's language, and states which one: the
player is the one who reads it over before sending it.
"""

import datetime
import os
import platform
import sys
from collections import Counter

import pygame

from . import i18n, paths
from .settings import BUG_DIR, RESOURCES
from .utils import fmt_time

MAX_DESCRIPTION = 1200
LABEL_WIDTH = 21             # width of the label column


def report_dir():
    """The reports folder, created as needed, as an absolute path.

    The installed game does not write into its install folder: it files the
    reports under the player's home directory.
    """
    if os.path.isabs(BUG_DIR):
        path = BUG_DIR
        os.makedirs(path, exist_ok=True)
        return path
    return paths.ensure(*BUG_DIR.split("/"))


def _row(key, value):
    """A "label    value" row, aligned whatever the language."""
    return i18n.t("report." + key).ljust(LABEL_WIDTH) + str(value)


def _counts(items, key):
    c = Counter(key(i) for i in items)
    if not c:
        return i18n.t("report.none")
    return ", ".join("%s %d" % (k, v) for k, v in sorted(c.items()))


def _player_block(game, player, role):
    units = [u for u in game.units if u.player is player and u.alive]
    builds = [b for b in game.buildings if b.player is player and b.alive]
    return [
        "### %s (%s)" % (player.name, role),
        _row("resources", ", ".join(
            "%s %d" % (i18n.resource_name(r), int(player.res[r]))
            for r in RESOURCES)),
        _row("population", "%d / %d" % (player.pop, player.pop_limit)),
        _row("units", _counts(units, lambda u: u.utype)),
        _row("buildings", _counts(builds, lambda b: b.btype)),
        _row("upgrades", ", ".join(sorted(player.upgrades))
             or i18n.t("report.none_f")),
        _row("gathered", ", ".join(
            "%s %d" % (i18n.resource_name(r), player.stat_gathered[r])
            for r in RESOURCES)),
        _row("kills_losses", "%d / %d" % (player.stat_kills,
                                          player.stat_losses)),
    ]


def collect(app, fps=0):
    """The text of the technical context and of the game state."""
    game = app.game
    yes, no = i18n.t("report.yes"), i18n.t("report.no")
    lines = ["## " + i18n.t("report.context_heading"), ""]
    try:
        from . import __version__
    except Exception:
        __version__ = i18n.t("report.unknown")
    lines += [
        _row("date", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        _row("version", __version__),
        _row("language", i18n.language()),
        _row("python", sys.version.split()[0]),
        _row("pygame", "%s (SDL %s)" % (
            pygame.version.ver, ".".join(str(n) for n in pygame.version.SDL))),
        _row("system", "%s %s (%s)" % (platform.system(), platform.release(),
                                       platform.machine())),
        _row("install", i18n.t("report.frozen" if paths.is_frozen()
                               else "report.sources")),
        _row("window", i18n.t("report.window_value", w=app.layout.w,
                              h=app.layout.h,
                              full=yes if app.fullscreen else no)),
        _row("ui_scale", i18n.t("report.ui_scale_value",
                                scale="%.2f" % app.layout.scale,
                                assets="%.1f" % app.layout.asset_scale)),
        _row("fps", fps),
    ]

    if game is None:
        lines += [_row("screen", i18n.t("report.main_menu")), ""]
        return lines

    state = {0: "state_playing", 1: "state_paused", 2: "state_victory",
             3: "state_defeat"}.get(game.state)
    state = i18n.t("report." + state) if state else str(game.state)
    sel = game.selection
    lines += [
        "", "## " + i18n.t("report.game_heading"), "",
        _row("seed", game.world.seed),
        _row("map", i18n.t("report.map_saved", name=game.world.name,
                           size=i18n.map_size_name(game.world.w))
             if game.world.name else
             i18n.t("report.map_random",
                    size=i18n.map_size_name(game.world.w))),
        _row("difficulty", i18n.difficulty_name(game.difficulty)),
        _row("playtime", fmt_time(game.elapsed)),
        _row("state", state + (i18n.t("report.paused_suffix")
                               if app.paused else "")),
        _row("speed", "x%.1f" % game.speed),
        _row("fog", yes if game.fog.enabled else no),
        _row("camera", i18n.t("report.camera_value",
                              x=int(game.camera.x), y=int(game.camera.y),
                              zoom="%.2f" % game.camera.zoom)),
        _row("edge_scroll", yes if game.camera.edge_scroll else no),
        _row("selection", _counts(
            sel, lambda e: e.utype if e.is_unit else e.btype)
            if sel else i18n.t("report.empty")),
        _row("build_mode", game.build_mode or no),
        _row("entities", i18n.t("report.entities_value",
                                units=len(game.units),
                                buildings=len(game.buildings),
                                projectiles=len(game.projectiles))),
        "",
    ]
    lines += _player_block(game, game.human, i18n.t("report.role_player"))
    lines += [""]
    lines += _player_block(game, game.enemy, i18n.t("report.role_ai"))
    if game.messages:
        lines += ["", "### " + i18n.t("report.messages_heading")]
        lines += ["- " + m[0] for m in game.messages[-6:]]
    return lines


def save(app, description, screenshot=None, fps=0):
    """Write the report and its screenshot. Returns (txt_path, png_path)."""
    folder = report_dir()
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    # "bogue_" is player-facing output, like the in-game strings: it stays
    # French so that older reports keep sitting next to the new ones.
    base = os.path.join(folder, "bogue_%s" % stamp)
    txt_path = base + ".txt"
    png_path = None

    description = ((description or "").strip()
                   or i18n.t("report.no_description"))
    lines = ["# " + i18n.t("report.title"), "",
             "## " + i18n.t("report.description_heading"), "",
             description, ""]
    lines += collect(app, fps)

    shot_heading = "## " + i18n.t("report.screenshot_heading")
    if screenshot is not None:
        png_path = base + ".png"
        try:
            pygame.image.save(screenshot, png_path)
            lines += ["", shot_heading, "", os.path.basename(png_path)]
        except Exception as exc:
            png_path = None
            lines += ["", shot_heading, "",
                      i18n.t("report.screenshot_failed", error=exc)]

    with open(txt_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return txt_path, png_path

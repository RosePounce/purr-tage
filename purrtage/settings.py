# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Constants, balancing and palette of "Purr-tage: La Guerre des Chats".

No displayed text here: the labels of the units, buildings, resources and
difficulties live in `purrtage/locales/` and are fetched through
`purrtage.i18n`. All that remains are the identifiers — `kitten`, `basket`,
`kibble` — which belong to the code, in every language.
"""

# ----------------------------------------------------------------- Window ----
SCREEN_W, SCREEN_H = 1280, 760      # default window resolution
FPS = 60

# The simulation advances in fixed steps: that is the requirement for two
# networked machines to compute exactly the same game.
TICK_HZ = 30
TICK_DT = 1.0 / TICK_HZ
MAX_CATCHUP = 5             # maximum catch-up steps per frame

# Resolutions offered in the menu and accepted by --resolution.
RESOLUTIONS = ((1280, 760), (1600, 900), (1920, 1080),
               (2560, 1440), (2880, 1800))

# The whole interface is expressed in "units", then multiplied by a scale
# factor computed from the actual window height.
# In automatic fullscreen we do not render beyond this height: SDL then scales
# up on the GPU. --resolution overrides it for a native rendering.
RENDER_HEIGHT_CAP = 1200

# A zoom-out step whose intermediate surface would exceed this budget is
# simply dropped: it would cost more than it is worth.
MAX_SCENE_PX = 8_000_000

UI_REF_H = 760                      # reference height (scale = 1)
UI_SCALE_MIN, UI_SCALE_MAX = 1.0, 2.4
TOPBAR_H = 36                       # units, before scaling
HUD_H = 158                         # units, before scaling

# ------------------------------------------------------------------ World ----
TILE = 32
# The map is square; its side, in tiles, belongs to each `World`. Generated
# maps and the editor both offer these sizes.
MAP_SIZES = (64, 96, 128, 160)
DEFAULT_MAP_SIZE = 96

# Relative zoom factors: multiplied by the sprite scale, level 1.0 shows one
# asset pixel per screen pixel (hence no resampling at all).
ZOOM_LEVELS = (0.55, 0.75, 1.0, 1.35, 1.8)
DEFAULT_ZOOM_INDEX = 2
CAM_SPEED = 820.0          # world pixels / second
EDGE_SCROLL_MARGIN = 12     # sensitive band at the screen edge, in pixels
EDGE_SCROLL_ENABLED = True  # can be switched off in the menu or with F7
EDGE_SCROLL_SPEED = 0.8     # share of the keyboard speed, for a softer edge
CAMERA_ARROWS_ONLY = True   # letters stay free for the shortcuts

# --------------------------------------------------------------- Terrains ----
T_WATER, T_SAND, T_GRASS, T_MEADOW, T_FLOWER = range(5)
TERRAIN_WALKABLE = {T_WATER: False, T_SAND: True, T_GRASS: True,
                    T_MEADOW: True, T_FLOWER: True}

# -------------------------------------------------------------- Resources ---
# Stone comes last: map files store a node as its index in RESOURCES, so the
# older maps keep reading the same kinds.
R_KIBBLE, R_WOOL, R_CATNIP, R_STONE = "kibble", "wool", "catnip", "stone"
RESOURCES = (R_KIBBLE, R_WOOL, R_CATNIP, R_STONE)
RES_AMOUNT = {R_KIBBLE: 340, R_WOOL: 280, R_CATNIP: 420, R_STONE: 400}
RES_COLOR = {R_KIBBLE: (226, 162, 72), R_WOOL: (236, 118, 158),
             R_CATNIP: (126, 206, 118), R_STONE: (172, 168, 162)}

START_RESOURCES = {R_KIBBLE: 320, R_WOOL: 260, R_CATNIP: 140, R_STONE: 0}

# ------------------------------------------------------------------ Units ----
# The labels (name, role, description) live in `purrtage/locales/`, under the
# `units.<identifier>` key.
UNITS = {
    "kitten": dict(
        hp=75, atk=4, armor=0, rng=18,
        cooldown=1.2, speed=80.0, radius=9, vision=8 * TILE, pop=1,
        cost={R_KIBBLE: 50}, train_time=11.0,
        gather_rate=0.80, carry=12, builder=True,
        trained_at="basket",
        hotkey="A"),
    "scratcher": dict(
        hp=145, atk=14, armor=2, rng=22,
        cooldown=1.0, speed=74.0, radius=10, vision=7 * TILE, pop=1,
        cost={R_KIBBLE: 60, R_WOOL: 20}, train_time=15.0,
        trained_at="scratching_post",
        hotkey="F"),
    "spitter": dict(
        hp=95, atk=13, armor=0, rng=190,
        cooldown=1.7, speed=70.0, radius=9, vision=9 * TILE, pop=1,
        cost={R_KIBBLE: 45, R_WOOL: 45}, train_time=17.0,
        projectile=True,
        trained_at="scratching_post",
        hotkey="E"),
    "tomcat": dict(
        hp=270, atk=23, armor=5, rng=24,
        cooldown=1.4, speed=60.0, radius=12, vision=7 * TILE, pop=2,
        cost={R_KIBBLE: 80, R_CATNIP: 60}, train_time=23.0,
        trained_at="dojo",
        bonus_vs_building=1.8,
        hotkey="R"),
}
UNIT_ORDER = ("kitten", "scratcher", "spitter", "tomcat")
MILITARY = ("scratcher", "spitter", "tomcat")

# -------------------------------------------------------------- Buildings ----
# Labels under the `buildings.<identifier>` key; that is also where the gender
# of the name lives, which French needs for its agreements.
BUILDINGS = {
    "basket": dict(
        hp=1500, size=3, cost={R_WOOL: 200},
        build_time=42.0, pop_bonus=10, dropoff=True, vision=10 * TILE,
        trains=("kitten",),
        hotkey="P"),
    "shed": dict(
        hp=430, size=2, cost={R_WOOL: 30},
        build_time=14.0, pop_bonus=5, vision=6 * TILE,
        hotkey="C"),
    "scratching_post": dict(
        hp=950, size=3, cost={R_WOOL: 120},
        build_time=26.0, vision=7 * TILE, trains=("scratcher", "spitter"),
        hotkey="G"),
    "dojo": dict(
        hp=1150, size=3, cost={R_WOOL: 150, R_CATNIP: 100},
        build_time=34.0, vision=8 * TILE, trains=("tomcat",), research=True,
        hotkey="J"),
    "tower": dict(
        hp=750, size=2, cost={R_WOOL: 80, R_CATNIP: 40},
        build_time=20.0, vision=10 * TILE,
        atk=18, rng=215, cooldown=1.5, projectile=True,
        # Each step is bought on the tower itself and adds to the base
        # figures: level 2, then level 3.
        levels=(dict(cost={R_STONE: 80, R_CATNIP: 40}, time=22.0,
                     hp=350, atk=7, rng=32),
                dict(cost={R_STONE: 150, R_CATNIP: 80}, time=30.0,
                     hp=450, atk=9, rng=32)),
        hotkey="T"),
    # One tile of rampart. Dragging lays a whole line of them (`line`).
    "wall": dict(
        hp=700, size=1, cost={R_STONE: 12},
        build_time=5.0, vision=3 * TILE, line=True,
        hotkey="W"),
}
BUILD_MENU = ("shed", "scratching_post", "dojo", "tower", "wall", "basket")

BUILD_SPEED = 26.0       # build points / second / kitten
REPAIR_RATE = 22.0       # HP repaired / second / kitten

# Site finished: the kitten moves on to the next one if it is within this
# distance. Beyond that it stops, rather than crossing the map without being
# asked to. Same spirit as the gatherer, which moves on to the node next door.
NEXT_SITE_TILES = 26

# --------------------------------------------------------------- Upgrades ----
# Labels under the `upgrades.<identifier>` key.
UPGRADES = {
    "claws": dict(cost={R_CATNIP: 120, R_KIBBLE: 80},
                  time=34.0, atk=5, hotkey="U"),
    "fur": dict(cost={R_CATNIP: 100, R_WOOL: 120},
                time=34.0, armor=2, hp_mult=1.15, hotkey="I"),
    "paws": dict(cost={R_CATNIP: 90, R_KIBBLE: 120},
                 time=28.0, speed_mult=1.20, hotkey="O"),
}
UPGRADE_ORDER = ("claws", "fur", "paws")

# ----------------------------------------------------------------- Combat ----
POP_HARD_CAP = 120
AGGRO_RANGE = 200.0          # auto-detection by idle military units
DEFEND_RANGE = 260.0         # retaliation radius around the home point
CORPSE_TIME = 7.0
RETARGET_BONUS = 1.15        # search radius after bringing a target down
PROJECTILE_SPEED = 330.0

# ------------------------------------------------------------- Difficulty ----
# Labels under the `difficulties.<identifier>` key.
DIFFICULTIES = {
    "kitten": dict(army=6,  wave_delay=115.0, eco=8,  react=5.0, tempo=1.25),
    "tomcat": dict(army=10, wave_delay=85.0,  eco=11, react=3.0, tempo=1.0),
    "tiger":  dict(army=15, wave_delay=62.0,  eco=14, react=1.5, tempo=0.82),
}
DIFF_ORDER = ("kitten", "tomcat", "tiger")

# ------------------------------------------------------- Bug reports ----
BUG_DIR = "saves/bug"        # relative to the folder the game is launched from
# The relay that forwards reports to the issue tracker, Discord, e-mail...
# (see relay/). Only the packaged game uses it: run from the sources, the game
# keeps its reports on disk unless PURRTAGE_REPORT_URL is set, so that
# development and the test suite never file real reports.
BUG_REPORT_URL = "https://purr-tage.rose-pounce.workers.dev/report"

# ------------------------------------------------------------------ Teams ----
# The names of the two sides live in `purrtage/locales/`, under `teams`.
TEAM_COLORS = [(92, 162, 232), (226, 94, 94)]

# --------------------------------------------------------------- Factions ----
# The clans a player can wear before a game. Cosmetic for now: a name (under
# the `factions.<id>` key) and a colour. The first two reuse the team colours;
# the rest come from the design sheet (export-tableur/clans.csv). A game paints
# the local player in the chosen clan and the opponent in a contrasting one.
FACTIONS = {
    "whiskers":  dict(color=(92, 162, 232)),
    "chartreux": dict(color=(226, 94, 94)),
    "couch":     dict(color=(236, 230, 218)),
    "moon":      dict(color=(40, 54, 92)),
    "sun":       dict(color=(238, 206, 92)),
    "scratch":   dict(color=(104, 186, 110)),
    "league":    dict(color=(158, 110, 198)),
    "gingers":   dict(color=(226, 140, 72)),
}
FACTION_ORDER = ("whiskers", "chartreux", "couch", "moon", "sun",
                 "scratch", "league", "gingers")
DEFAULT_FACTION = "whiskers"

# ---------------------------------------------------------------- Palette ----
C_WATER       = (54, 102, 146)
C_WATER_DEEP  = (41, 80, 120)
C_SAND        = (214, 193, 141)
C_GRASS       = (104, 150, 86)
C_MEADOW      = (92, 136, 78)
C_FLOWER      = (116, 160, 94)

C_PANEL       = (34, 31, 40)
C_PANEL_LIGHT = (52, 48, 60)
C_PANEL_DARK  = (22, 20, 26)
C_BORDER      = (86, 79, 98)
C_TEXT        = (236, 232, 226)
C_TEXT_DIM    = (158, 152, 166)
C_GOLD        = (238, 198, 108)
C_OK          = (124, 206, 128)
C_BAD         = (226, 104, 104)
C_SELECT      = (246, 240, 150)

FOG_UNSEEN    = 238
FOG_EXPLORED  = 104

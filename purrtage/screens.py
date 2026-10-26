# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Out-of-game screens: main menu, pause, help, end of game.

Like the in-game panel, everything is sized in interface units then converted
by `Layout.u()`, so as to stay readable at any resolution.
"""

import math

import pygame

from . import i18n, keymap, mapfile, prefs, sprites
from .settings import (BUILDINGS, C_BORDER, C_GOLD, C_OK, C_BAD, C_PANEL,
                       C_PANEL_DARK, C_PANEL_LIGHT, C_TEXT, C_TEXT_DIM,
                       BUILD_MENU, DEFAULT_FACTION, DEFAULT_MAP_SIZE, DIFF_ORDER,
                       FACTION_ORDER, FACTIONS, MAP_SIZES, RESOLUTIONS,
                       RESOURCES, TEAM_COLORS, UNITS, UNIT_ORDER, UPGRADE_ORDER)
from .ui import format_cost
from .utils import clamp, fmt_time, mix


def help_keys():
    """The tokens the F1 catalogue writes as `{units}`, `{stop}`…

    The page used to spell "A Z E R" out, which stopped being true the moment
    the player remapped anything. The catalogue now names the binding and the
    live key is filled in here. Each unit, building and upgrade also answers
    to its own identifier — `{kitten}`, `{dojo}`, `{claws}` — for the F2 page.
    """
    def row(*bindings):
        return " ".join(keymap.label(b) for b in bindings)

    keys = {b.partition(".")[2]: keymap.label(b) for b in keymap.bindings()
            if b.partition(".")[0] in ("unit", "building", "upgrade")}
    keys.update({
        "units": row(*("unit.%s" % u for u in UNIT_ORDER)),
        "buildings": row(*("building.%s" % b for b in BUILD_MENU)),
        "upgrades": row(*("upgrade.%s" % k for k in UPGRADE_ORDER)),
        "camera": row("camera.up", "camera.left", "camera.down",
                      "camera.right"),
        "stop": keymap.label("command.stop"),
        "attack": keymap.label("command.attack_move"),
        "idle": keymap.label("command.idle_worker"),
        "center": keymap.label("command.center"),
        "mute": keymap.label("command.mute"),
        "level_up": keymap.label("command.level_up"),
    })
    return keys


def fill_keys(text, keys=None):
    """`text` with its `{…}` key tokens replaced by the keys in place."""
    try:
        return text.format(**(help_keys() if keys is None else keys))
    except (KeyError, IndexError, ValueError):
        return text          # a hand-written catalogue stays readable


def help_sections():
    """The F1 page listing: [(title, [(key, effect), …]), …].

    Read again on every draw: the language can change during the game, and so
    can the keys.
    """
    keys = help_keys()
    out = []
    for section in i18n.data("help.sections", []) or []:
        if not isinstance(section, dict):
            continue
        rows = [tuple(fill_keys(cell, keys) for cell in row[:2])
                for row in section.get("rows", [])
                if isinstance(row, list) and len(row) >= 2]
        if rows:
            out.append((section.get("title", ""), rows))
    return out


class Button(object):
    def __init__(self, rect, label, key=None, enabled=True):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.key = key
        self.enabled = enabled

    def draw(self, screen, font, mouse, radius=8):
        hov = self.rect.collidepoint(mouse) and self.enabled
        bg = C_PANEL_LIGHT if self.enabled else (40, 38, 44)
        if hov:
            bg = mix(bg, (255, 255, 255), 0.22)
        pygame.draw.rect(screen, bg, self.rect, border_radius=radius)
        pygame.draw.rect(screen, C_GOLD if hov else C_BORDER, self.rect, 2,
                         border_radius=radius)
        img = font.render(self.label, True, C_TEXT if self.enabled else C_TEXT_DIM)
        screen.blit(img, (self.rect.centerx - img.get_width() // 2,
                          self.rect.centery - img.get_height() // 2))


def _backdrop(screen, t, layout):
    """A gradient background + cats strolling by."""
    w, h = layout.w, layout.h
    top, bottom = (36, 46, 58), (74, 104, 76)
    for y in range(0, h, 4):
        k = y / float(h)
        pygame.draw.rect(screen, (int(top[0] + (bottom[0] - top[0]) * k),
                                  int(top[1] + (bottom[1] - top[1]) * k),
                                  int(top[2] + (bottom[2] - top[2]) * k)),
                         (0, y, w, 4))
    size = layout.u(66)
    for i, utype in enumerate(("scratcher", "kitten", "tomcat", "spitter")):
        speed = layout.u(42 + i * 17)
        x = (t * speed + i * layout.u(330)) % (w + size * 2) - size
        y = h - layout.u(88) + (i % 2) * layout.u(10)
        spr = sprites.unit_sprite(utype, i % 2, int(t * 7 + i) % 4, 1)
        ratio = size / float(max(spr.get_width(), 1))
        spr = pygame.transform.smoothscale(
            spr, (size, max(1, int(spr.get_height() * ratio))))
        screen.blit(spr, (x, y))


class MainMenu(object):
    def __init__(self, fonts, layout):
        self.fonts = fonts
        self.layout = layout
        self.diff_index = 1
        saved_faction = prefs.get("faction", DEFAULT_FACTION)
        self.faction_index = (FACTION_ORDER.index(saved_faction)
                              if saved_faction in FACTION_ORDER else 0)
        self.res_index = -1          # -1 = the desktop resolution
        self.fullscreen = False
        self.fog = True
        self.sound = True
        self.edge_scroll = True
        self.classic_cats = bool(prefs.get("classic_cats", False))
        # The map choices: a generated map at each size, then the saved maps
        # as (path, name, size). `map_index` runs over both lists in a row.
        self.maps = []
        self.map_index = MAP_SIZES.index(DEFAULT_MAP_SIZE)
        self.t = 0.0
        self.buttons = {}
        self.relayout(layout, fonts)

    def relayout(self, layout, fonts=None):
        self.layout = layout
        if fonts:
            self.fonts = fonts
        u = layout.u
        cx = layout.w // 2
        bw, half = u(300), u(145)
        # The block sits below the thumbnails of the four breeds and above
        # the two tip lines: it must never bite into either.
        height = u(56 + 4 + 44 + 4 + 44 + 4 + 48 + 4 + 44 + 8 + 40)
        min_top = u(360)
        bottom_room = layout.h - u(78)
        top = max(min_top, min_top + (bottom_room - min_top - height) // 2)
        self.buttons = {
            "play": Button((cx - bw // 2, top, bw, u(56)), i18n.t("menu.play")),
            "map": Button((cx - bw // 2, top + u(60), bw, u(44)), ""),
            "faction": Button((cx - bw // 2, top + u(108), bw, u(44)), ""),
            "lan": Button((cx - bw // 2, top + u(156), bw, u(48)),
                          i18n.t("menu.lan")),
            "options": Button((cx - bw // 2, top + u(208), half, u(44)),
                              i18n.t("menu.options")),
            "editor": Button((cx + u(5), top + u(208), half, u(44)),
                             i18n.t("menu.editor")),
            "help": Button((cx - bw // 2, top + u(260), half, u(40)),
                           i18n.t("menu.help")),
            "quit": Button((cx + u(5), top + u(260), half, u(40)),
                           i18n.t("menu.quit")),
        }

    # ----------------------------------------------------------------- maps --
    def refresh_maps(self):
        """Read the maps folder again, keeping the current choice if it is
        still there (a map saved in the editor shows up straight away)."""
        current = self.map_choice()
        self.maps = mapfile.list_maps()
        choices = self.map_choices()
        self.map_index = (choices.index(current) if current in choices
                          else MAP_SIZES.index(DEFAULT_MAP_SIZE))

    def map_choices(self):
        return [(None, None, side) for side in MAP_SIZES] + list(self.maps)

    def map_choice(self):
        """(path, name, size): path is None for a generated map."""
        choices = self.map_choices()
        return choices[self.map_index % len(choices)]

    def select_map(self, path):
        for i, choice in enumerate(self.map_choices()):
            if choice[0] == path:
                self.map_index = i

    def map_label(self):
        path, name, side = self.map_choice()
        if path is None:
            return i18n.t("menu.map_random", size=i18n.map_size_name(side))
        return i18n.t("menu.map_saved", name=name,
                      size=i18n.map_size_name(side))

    def resolution(self):
        """The chosen resolution, or None for "the desktop one"."""
        if self.res_index < 0:
            return None
        return RESOLUTIONS[self.res_index % len(RESOLUTIONS)]

    # ------------------------------------------------------------- faction --
    def faction_id(self):
        return FACTION_ORDER[self.faction_index % len(FACTION_ORDER)]

    def faction_color(self):
        return FACTIONS[self.faction_id()]["color"]

    def update(self, dt):
        self.t += dt

    def draw(self, screen):
        L = self.layout
        u = L.u
        # Preview the chosen clan: the strolling cats and the breed thumbnails
        # below take team 0's colour, so paint it with the selected faction.
        sprites.set_team_colors([self.faction_color(), TEAM_COLORS[1]])
        f_tiny, f_small, f_med, f_big, f_huge = self.fonts
        _backdrop(screen, self.t, L)
        cx = L.w // 2
        titre = i18n.t("menu.title")
        title = f_huge.render(titre, True, (248, 236, 196))
        shadow = f_huge.render(titre, True, (26, 24, 30))
        ty = u(120)
        screen.blit(shadow, (cx - title.get_width() // 2 + u(3), ty + u(3)))
        screen.blit(title, (cx - title.get_width() // 2, ty))
        sub = f_med.render(i18n.t("menu.subtitle"), True, (226, 220, 206))
        screen.blit(sub, (cx - sub.get_width() // 2, ty + u(72)))

        icon = u(70)
        step = u(100)
        x = cx - step * 2 + (step - icon) // 2
        for utype in ("kitten", "scratcher", "spitter", "tomcat"):
            spr = sprites.unit_icon(utype, 0, icon)
            screen.blit(spr, (x, ty + u(130)))
            lab = f_tiny.render(i18n.unit_name(utype), True, (230, 226, 214))
            screen.blit(lab, (x + icon // 2 - lab.get_width() // 2, ty + u(202)))
            x += step

        mouse = pygame.mouse.get_pos()
        self.buttons["map"].label = self.map_label()
        self.buttons["faction"].label = i18n.t(
            "menu.faction", value=i18n.faction_name(self.faction_id()))
        for key, b in self.buttons.items():
            b.draw(screen, f_big if key == "play" else
                   (f_med if key == "lan" else f_small), mouse, u(8))
        for i, line in enumerate((
                i18n.t("menu.goal"),
                i18n.t("menu.footer", difficulty=i18n.difficulty_name(
                    DIFF_ORDER[self.diff_index])))):
            tip = f_tiny.render(line, True,
                                (214, 210, 200) if i == 0 else C_GOLD)
            screen.blit(tip, (cx - tip.get_width() // 2,
                              self.buttons["quit"].rect.bottom + u(14)
                              + i * (tip.get_height() + u(5))))

    def click(self, pos, button=1):
        """The key of the button under the cursor. The map button cycles
        through the choices, backwards with the right button."""
        for key, b in self.buttons.items():
            if b.rect.collidepoint(pos):
                if key == "map":
                    step = -1 if button == 3 else 1
                    self.map_index = ((self.map_index + step)
                                      % len(self.map_choices()))
                    return None
                if key == "faction":
                    step = -1 if button == 3 else 1
                    self.faction_index = ((self.faction_index + step)
                                          % len(FACTION_ORDER))
                    prefs.write("faction", self.faction_id())
                    return None
                return key
        return None


class OptionsScreen(object):
    """Game and display settings.

    The values stay held by the main menu, which is the reference when a game
    starts; this screen only presents them.
    """

    def __init__(self, fonts, layout, menu):
        self.fonts = fonts
        self.layout = layout
        self.menu = menu
        self.t = 0.0
        self.buttons = {}
        self.relayout(layout, fonts)

    def relayout(self, layout, fonts=None):
        self.layout = layout
        if fonts:
            self.fonts = fonts
        u = layout.u
        cx = layout.w // 2
        bw, half = u(340), u(166)
        top = layout.h // 2 - u(176)
        self.buttons = {
            "diff": Button((cx - bw // 2, top, bw, u(46)), ""),
            "res": Button((cx - bw // 2, top + u(56), half, u(44)), ""),
            "full": Button((cx + u(5), top + u(56), half, u(44)), ""),
            "fog": Button((cx - bw // 2, top + u(108), half, u(44)), ""),
            "sound": Button((cx + u(5), top + u(108), half, u(44)), ""),
            "edge": Button((cx - bw // 2, top + u(160), bw, u(44)), ""),
            "cats": Button((cx - bw // 2, top + u(212), bw, u(44)), ""),
            "lang": Button((cx - bw // 2, top + u(264), bw, u(44)), ""),
            "keys": Button((cx - bw // 2, top + u(316), bw, u(44)), ""),
            "back": Button((cx - bw // 2, top + u(376), bw, u(46)), ""),
        }

    def update(self, dt):
        self.t += dt
        m = self.menu
        res = m.resolution()
        yes, no = i18n.t("options.yes"), i18n.t("options.no")
        self.buttons["diff"].label = i18n.t(
            "options.difficulty",
            value=i18n.difficulty_name(DIFF_ORDER[m.diff_index]))
        self.buttons["res"].label = (i18n.t("options.screen_auto") if res is None
                                     else i18n.t("options.resolution",
                                                 w=res[0], h=res[1]))
        self.buttons["full"].label = i18n.t(
            "options.fullscreen", value=yes if m.fullscreen else no)
        self.buttons["fog"].label = i18n.t("options.fog",
                                           value=yes if m.fog else no)
        self.buttons["sound"].label = i18n.t("options.sound",
                                             value=yes if m.sound else no)
        self.buttons["edge"].label = i18n.t(
            "options.edge_scroll", value=yes if m.edge_scroll else no)
        self.buttons["cats"].label = i18n.t(
            "options.cats",
            value=i18n.t("options.cat_classic" if m.classic_cats
                         else "options.cat_new"))
        self.buttons["lang"].label = i18n.t("options.language",
                                            value=i18n.language_name())
        self.buttons["keys"].label = i18n.t("options.keys")
        self.buttons["back"].label = i18n.t("options.back")

    def draw(self, screen):
        L = self.layout
        u = L.u
        f_tiny, f_small, f_med, f_big, f_huge = self.fonts
        _backdrop(screen, self.t, L)
        cx = L.w // 2
        title = f_big.render(i18n.t("options.title"), True, (248, 236, 196))
        screen.blit(title, (cx - title.get_width() // 2, u(110)))
        mouse = pygame.mouse.get_pos()
        for key, b in self.buttons.items():
            b.draw(screen, f_med if key == "back" else f_small, mouse, u(8))
        y = self.buttons["back"].rect.bottom + u(22)
        for line in i18n.lines("options.notes"):
            img = f_tiny.render(line, True, C_TEXT_DIM)
            screen.blit(img, (cx - img.get_width() // 2, y))
            y += img.get_height() + u(6)

    def click(self, pos):
        """Returns "display", "edge", "language", "keys", "back", or nothing."""
        m = self.menu
        for key, b in self.buttons.items():
            if not b.rect.collidepoint(pos):
                continue
            if key == "diff":
                m.diff_index = (m.diff_index + 1) % len(DIFF_ORDER)
                return None
            if key == "res":
                m.res_index += 1
                if m.res_index >= len(RESOLUTIONS):
                    m.res_index = -1
                return "display"
            if key == "full":
                m.fullscreen = not m.fullscreen
                return "display"
            if key == "fog":
                m.fog = not m.fog
                return None
            if key == "sound":
                m.sound = not m.sound
                return None
            if key == "edge":
                m.edge_scroll = not m.edge_scroll
                return "edge"
            if key == "cats":
                m.classic_cats = not m.classic_cats
                sprites.set_cat_style(m.classic_cats)
                prefs.write("classic_cats", m.classic_cats)
                return None
            if key == "lang":
                i18n.set_language(i18n.next_language())
                return "language"
            if key == "keys":
                return "keys"
            if key == "back":
                return "back"
        return None


class KeysScreen(object):
    """Rebinding the keys, with an AZERTY / QWERTY switch.

    The shortcuts were drawn on an AZERTY board and SDL resolves a key by the
    character it produces, so a QWERTY player gets `A Z E R` scattered across
    their keyboard. The two presets fix the common case in one click; the rows
    below are there for everything else.

    Clicking a key cap arms the capture: the next press lands in that binding.
    `purrtage/app.py` routes the event here, because only the screen knows
    which row is waiting.
    """

    def __init__(self, fonts, layout):
        self.fonts = fonts
        self.layout = layout
        self.t = 0.0
        self.waiting = None        # the binding that is capturing, or None
        self.note = ""             # one line of feedback under the rows
        self.note_t = 0.0
        self.buttons = {}
        self.rows = {}             # binding -> pygame.Rect of its key cap
        self.relayout(layout, fonts)

    # ------------------------------------------------------------- layout --
    def relayout(self, layout, fonts=None):
        self.layout = layout
        if fonts:
            self.fonts = fonts
        u = layout.u
        cx = layout.w // 2
        groups = keymap.groups()
        # Two columns: the two long families on the left, the rest on the
        # right, so the whole thing holds on one screen at 1280x760.
        left_groups, right_groups = groups[:2], groups[2:]
        colw = u(330)
        gap = u(60)
        lx = cx - colw - gap // 2
        rx = cx + gap // 2
        self.columns = ((lx, left_groups), (rx, right_groups))
        self.col_width = colw

        top = u(118)
        self.rows = {}
        self.headers = []
        bottom = top
        for x, column in self.columns:
            y = top
            for title_key, entries in column:
                self.headers.append((title_key, x, y))
                y += u(24)
                for binding, _label in entries:
                    self.rows[binding] = pygame.Rect(
                        x + colw - u(84), y, u(84), u(24))
                    y += u(27)
                y += u(12)
            bottom = max(bottom, y)

        # The feedback lines go here, between the columns and the buttons: at
        # 1280x760 one unit is one pixel and there is nothing left underneath.
        self.notes_top = bottom + u(4)
        by = bottom + u(62)
        bw = u(150)
        self.buttons = {
            "azerty": Button((cx - bw - u(80), by, bw, u(38)), ""),
            "qwerty": Button((cx - bw // 2 + u(2), by, bw, u(38)), ""),
            "reset": Button((cx + u(80), by, bw, u(38)), ""),
            "back": Button((cx - u(110), by + u(48), u(220), u(40)), ""),
        }

    # ------------------------------------------------------------- update --
    def update(self, dt):
        self.t += dt
        if self.note_t > 0.0:
            self.note_t = max(0.0, self.note_t - dt)
            if self.note_t == 0.0:
                self.note = ""
        preset = keymap.preset_in_use()
        for name in ("azerty", "qwerty"):
            label = i18n.t("keys.preset_%s" % name)
            # No tick mark: the bundled font has no U+2713 and draws a tofu
            # box. A word says it just as well, and it translates.
            if preset == name:
                label += " " + i18n.t("keys.in_use")
            self.buttons[name].label = label
        self.buttons["reset"].label = i18n.t("keys.reset")
        self.buttons["back"].label = i18n.t("options.back")

    def _say(self, text):
        self.note = text
        self.note_t = 3.5

    # --------------------------------------------------------------- draw --
    def draw(self, screen):
        L = self.layout
        u = L.u
        f_tiny, f_small, f_med, f_big, f_huge = self.fonts
        _backdrop(screen, self.t, L)
        cx = L.w // 2

        # The title block sits above the columns, which start at u(118):
        # there are twenty-one rows to fit and no room to waste up here.
        title = f_big.render(i18n.t("keys.title"), True, (248, 236, 196))
        screen.blit(title, (cx - title.get_width() // 2, u(42)))
        sub = f_tiny.render(i18n.t("keys.subtitle"), True, C_TEXT_DIM)
        screen.blit(sub, (cx - sub.get_width() // 2,
                          u(42) + title.get_height() + u(8)))

        for title_key, x, y in self.headers:
            img = f_small.render(i18n.t(title_key), True, C_GOLD)
            screen.blit(img, (x, y))
            pygame.draw.line(screen, C_BORDER, (x, y + img.get_height() + u(2)),
                             (x + self.col_width, y + img.get_height() + u(2)))

        mouse = pygame.mouse.get_pos()
        clashing = keymap.duplicates()
        for x, column in self.columns:
            for _title, entries in column:
                for binding, _key in entries:
                    rect = self.rows[binding]
                    img = f_tiny.render(keymap.display_name(binding), True,
                                        C_TEXT)
                    screen.blit(img, (x, rect.centery - img.get_height() // 2))
                    self._draw_cap(screen, rect, binding, mouse, clashing)

        for key, b in self.buttons.items():
            b.draw(screen, f_small if key != "back" else f_med, mouse, u(8))

        y = self.notes_top
        for text, colour in ((self.note, (240, 200, 130)),
                             (i18n.t("keys.clash") if clashing else "", C_BAD),
                             (i18n.t("keys.hint"), C_TEXT_DIM)):
            if not text:
                continue
            img = f_tiny.render(text, True, colour)
            screen.blit(img, (cx - img.get_width() // 2, y))
            y += img.get_height() + u(3)

    def _draw_cap(self, screen, rect, binding, mouse, clashing):
        u = self.layout.u
        f_tiny = self.fonts[0]
        armed = (self.waiting == binding)
        hov = rect.collidepoint(mouse)
        bg = C_PANEL_LIGHT
        if armed:
            # A slow pulse, so an armed row cannot be missed.
            bg = mix(bg, (236, 196, 108), 0.35 + 0.25 * math.sin(self.t * 6.0))
        elif hov:
            bg = mix(bg, (255, 255, 255), 0.22)
        border = C_GOLD if (armed or hov) else (
            C_BAD if binding in clashing else C_BORDER)
        pygame.draw.rect(screen, bg, rect, border_radius=u(5))
        pygame.draw.rect(screen, border, rect, 2, border_radius=u(5))
        text = i18n.t("keys.press") if armed else keymap.label(binding)
        img = f_tiny.render(text, True, C_TEXT)
        screen.blit(img, (rect.centerx - img.get_width() // 2,
                          rect.centery - img.get_height() // 2))

    # -------------------------------------------------------------- input --
    def click(self, pos):
        """Returns "back", "keymap" after a change, or None."""
        for binding, rect in self.rows.items():
            if rect.collidepoint(pos):
                self.waiting = None if self.waiting == binding else binding
                self.note = ""
                return None
        for key, b in self.buttons.items():
            if not b.rect.collidepoint(pos):
                continue
            self.waiting = None
            if key == "back":
                return "back"
            if key == "reset":
                keymap.reset()
            else:
                keymap.apply_preset(key)
            self._say(i18n.t("keys.applied"))
            return "keymap"
        self.waiting = None
        return None

    def key(self, ev):
        """A press while a row is armed. Returns "keymap" when it took."""
        if self.waiting is None:
            return None
        if ev.key == pygame.K_ESCAPE:
            self.waiting = None
            return None
        name = pygame.key.name(ev.key)
        freed = keymap.assign(self.waiting, name)
        if freed is False:
            # The field cannot be called `key`: that is `i18n.t`'s own first
            # parameter, and the call would collide with it.
            self._say(i18n.t("keys.reserved", pressed=keymap.key_label(name)))
            return None
        if freed:
            self._say(i18n.t("keys.freed",
                             name=keymap.display_name(freed)))
        else:
            self.note = ""
        self.waiting = None
        return "keymap"


class LanScreen(object):
    """Host or join a game on the local network."""

    MENU, HOSTING, BROWSING = range(3)

    def __init__(self, fonts, layout):
        self.fonts = fonts
        self.layout = layout
        self.mode = self.MENU
        self.message = ""
        self.manual = ""
        self.typing = False
        self.rows = []            # buttons for the hosts that were found
        self.relayout(layout, fonts)

    def relayout(self, layout, fonts=None):
        self.layout = layout
        if fonts:
            self.fonts = fonts
        u = layout.u
        cx = layout.w // 2
        top = layout.h // 2 - u(60)
        bw, half = u(340), u(165)
        self.buttons = {
            "host": Button((cx - bw // 2, top, bw, u(52)), i18n.t("lan.host")),
            "join": Button((cx - bw // 2, top + u(62), bw, u(52)),
                           i18n.t("lan.join")),
            "back": Button((cx - bw // 2, top + u(136), bw, u(44)),
                           i18n.t("lan.back")),
            "manual": Button((cx - bw // 2, top + u(136), half, u(44)),
                             i18n.t("lan.manual")),
            "cancel": Button((cx + u(5), top + u(136), half, u(44)),
                             i18n.t("lan.cancel")),
        }
        self.list_rect = pygame.Rect(cx - bw // 2, top - u(10), bw, u(140))

    # ------------------------------------------------------------ affichage --
    def draw(self, screen, host, browser, t):
        L = self.layout
        u = L.u
        f_tiny, f_small, f_med, f_big, f_huge = self.fonts
        _backdrop(screen, t, L)
        cx = L.w // 2
        title = f_big.render(i18n.t("lan.title"), True, (248, 236, 196))
        screen.blit(title, (cx - title.get_width() // 2, u(100)))
        mouse = pygame.mouse.get_pos()

        if self.mode == self.MENU:
            sub = f_small.render(i18n.t("lan.same_network"),
                                 True, (226, 220, 206))
            screen.blit(sub, (cx - sub.get_width() // 2, u(150)))
            for key in ("host", "join", "back"):
                self.buttons[key].draw(screen, f_med, mouse, u(8))

        elif self.mode == self.HOSTING:
            lines = [i18n.t("lan.waiting"), ""]
            if host is not None:
                lines.append(i18n.t("lan.your_address", ip=host.ip))
                lines.append(i18n.t("lan.port", port=host.port))
                lines.append("")
                lines.append(i18n.t("lan.will_see_you"))
            y = u(170)
            for i, line in enumerate(lines):
                font = f_med if i == 0 else f_small
                col = C_GOLD if i == 0 else C_TEXT
                img = font.render(line, True, col)
                screen.blit(img, (cx - img.get_width() // 2, y))
                y += img.get_height() + u(6)
            dots = "." * (1 + int(t * 2) % 3)
            img = f_med.render(dots, True, C_GOLD)
            screen.blit(img, (cx - img.get_width() // 2, y + u(6)))
            self.buttons["back"].draw(screen, f_med, mouse, u(8))

        else:
            hosts = browser.hosts() if browser else []
            self.rows = []
            y = u(170)
            if browser is not None and browser.error:
                warn = f_small.render(
                    i18n.t("lan.discovery_unavailable", error=browser.error),
                    True, C_BAD)
                screen.blit(warn, (cx - warn.get_width() // 2, y))
                y += u(30)
            elif not hosts:
                img = f_small.render(
                    i18n.t("lan.searching", dots="." * (1 + int(t * 2) % 3)),
                    True, C_TEXT_DIM)
                screen.blit(img, (cx - img.get_width() // 2, y))
                y += u(30)
            for ip, info in hosts[:4]:
                rect = pygame.Rect(cx - u(170), y, u(340), u(42))
                b = Button(rect, i18n.t("lan.host_row", name=info["name"], ip=ip))
                b.draw(screen, f_small, mouse, u(6))
                self.rows.append((b, ip, info["port"]))
                y += u(48)
            if self.typing:
                y += u(6)
                box = pygame.Rect(cx - u(170), y, u(340), u(40))
                pygame.draw.rect(screen, C_PANEL_DARK, box, border_radius=u(6))
                pygame.draw.rect(screen, C_GOLD, box, 2, border_radius=u(6))
                caret = "|" if int(t * 2) % 2 == 0 else " "
                img = f_small.render(
                    i18n.t("lan.address_field", value=self.manual + caret),
                    True, C_TEXT)
                screen.blit(img, (box.x + u(10),
                                  box.centery - img.get_height() // 2))
                tip = f_tiny.render(i18n.t("lan.typing_tip"), True, C_TEXT_DIM)
                screen.blit(tip, (cx - tip.get_width() // 2, box.bottom + u(6)))
            self.buttons["manual"].draw(screen, f_small, mouse, u(8))
            self.buttons["cancel"].draw(screen, f_small, mouse, u(8))

        if self.message:
            img = f_small.render(self.message, True, C_BAD)
            screen.blit(img, (cx - img.get_width() // 2, L.h - u(70)))

    # ---------------------------------------------------------- interaction --
    def click(self, pos):
        """Returns an action: host, browse, back, connect:<ip>:<port>."""
        if self.mode == self.MENU:
            for key in ("host", "join", "back"):
                if self.buttons[key].rect.collidepoint(pos):
                    return {"host": "host", "join": "browse", "back": "back"}[key]
            return None
        if self.mode == self.HOSTING:
            if self.buttons["back"].rect.collidepoint(pos):
                return "back"
            return None
        for (b, ip, port) in self.rows:
            if b.rect.collidepoint(pos):
                return "connect:%s:%d" % (ip, port)
        if self.buttons["manual"].rect.collidepoint(pos):
            self.typing = not self.typing
            return None
        if self.buttons["cancel"].rect.collidepoint(pos):
            return "back"
        return None

    def key(self, event):
        """Typing an address by hand. Returns "connect:…" once confirmed."""
        if not self.typing:
            return None
        if event.key == pygame.K_ESCAPE:
            self.typing = False
            self.manual = ""
            return None
        if event.key == pygame.K_BACKSPACE:
            self.manual = self.manual[:-1]
            return None
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            addr = self.manual.strip()
            self.typing = False
            self.manual = ""
            return ("connect:%s:%d" % (addr, 50507)) if addr else None
        ch = event.unicode
        if ch and (ch.isdigit() or ch == "." or ch == ":") and len(self.manual) < 21:
            self.manual += ch
        return None


# ------------------------------------------------------------ "play" page ----
def _title(screen, font, text, x, y, u):
    screen.blit(font.render(text, True, (168, 212, 246)), (x, y))
    return y + font.get_height() + u(8)


def _line(screen, font, text, x, y, u, color=C_TEXT):
    screen.blit(font.render(text, True, color), (x, y))
    return y + font.get_height() + u(4)


def draw_guide(screen, fonts, layout):
    """The F2 page: what each cat is for and how to get it.

    A tester believed a kitten grew into a tomcat; this page exists so that
    the answer leaps off the screen.
    """
    f_tiny, f_small, f_med, f_big, f_huge = fonts
    u = layout.u
    screen.fill((12, 12, 18))      # a reference page: a flat background, no veil

    title = f_big.render(i18n.t("guide.title"), True, C_GOLD)
    screen.blit(title, (layout.w // 2 - title.get_width() // 2, u(20)))

    colw = (layout.w - u(130)) // 2
    lx = u(50)
    rx = lx + colw + u(30)
    top = u(20) + title.get_height() + u(16)

    # ---------------------------------------------------- left column ----
    y = _title(screen, f_med, i18n.t("guide.goal_title"), lx, top, u)
    for line in i18n.lines("guide.goal_lines"):
        y = _line(screen, f_small, line, lx, y, u)
    y += u(14)

    y = _title(screen, f_med, i18n.t("guide.resources_title"), lx, y, u)
    icon = u(22)
    for kind in RESOURCES:
        screen.blit(sprites.resource_icon(kind, icon), (lx, y))
        screen.blit(f_small.render(i18n.resource_name(kind), True, C_GOLD),
                    (lx + icon + u(8), y))
        screen.blit(f_small.render("— " + i18n.t("guide.resource_uses.%s" % kind),
                                   True, C_TEXT),
                    (lx + icon + u(130), y))
        y += max(icon, f_small.get_height()) + u(8)
    y += u(2)
    for line in i18n.lines("guide.resources_note"):
        y = _line(screen, f_tiny, line, lx, y, u, C_TEXT_DIM)
    y += u(14)

    y = _title(screen, f_med, i18n.t("guide.start_title"), lx, y, u)
    keys = help_keys()
    for i, step in enumerate(i18n.lines("guide.start_steps"), 1):
        step = fill_keys(step, keys)
        screen.blit(f_small.render("%d." % i, True, C_GOLD), (lx, y))
        screen.blit(f_small.render(step, True, C_TEXT), (lx + u(24), y))
        y += f_small.get_height() + u(6)

    # --------------------------------------------------- right column ----
    y = _title(screen, f_med, i18n.t("guide.cats_title"), rx, top, u)

    # The warning first: that is what people come here for.
    box_lines = i18n.lines("guide.cats_warning")
    bh = u(14) + len(box_lines) * (f_small.get_height() + u(3))
    box = pygame.Rect(rx, y, colw, bh)
    pygame.draw.rect(screen, (46, 36, 30), box, border_radius=u(6))
    pygame.draw.rect(screen, (236, 170, 90), box, max(1, u(2)), border_radius=u(6))
    by = y + u(7)
    for line in box_lines:
        screen.blit(f_small.render(line, True, (246, 220, 170)), (rx + u(12), by))
        by += f_small.get_height() + u(3)
    y = box.bottom + u(14)

    icon = u(46)
    for utype in UNIT_ORDER:
        spec = UNITS[utype]
        screen.blit(sprites.unit_icon(utype, 0, icon), (rx, y))
        tx = rx + icon + u(10)
        name = i18n.unit_name(utype)
        screen.blit(f_small.render(name, True, C_GOLD), (tx, y))
        role = f_tiny.render(i18n.t("guide.role", role=i18n.unit_role(utype)),
                             True, C_TEXT_DIM)
        screen.blit(role, (tx + f_small.size(name)[0] + u(10), y + u(3)))
        screen.blit(f_tiny.render(
            i18n.t("guide.recruited_at",
                   building=i18n.building_name(spec["trained_at"]),
                   cost=format_cost(spec["cost"])), True, C_TEXT),
            (tx, y + f_small.get_height() + u(2)))
        screen.blit(f_tiny.render(i18n.unit_desc(utype), True, C_TEXT_DIM),
                    (tx, y + f_small.get_height() + f_tiny.get_height() + u(5)))
        y += max(icon, u(58)) + u(10)

    y = _title(screen, f_med, i18n.t("guide.buildings_title"), rx, y + u(6), u)
    icon = u(30)
    for btype in ("basket", "shed", "scratching_post", "dojo", "tower", "wall"):
        spec = BUILDINGS[btype]
        screen.blit(sprites.building_icon(btype, 0, icon), (rx, y))
        tx = rx + icon + u(10)
        name = f_small.render(i18n.building_name(btype), True, C_GOLD)
        screen.blit(name, (tx, y + u(1)))
        screen.blit(f_tiny.render(format_cost(spec["cost"]), True, C_TEXT_DIM),
                    (tx + name.get_width() + u(12), y + u(4)))
        screen.blit(f_tiny.render(i18n.building_desc(btype), True, C_TEXT),
                    (tx, y + name.get_height() + u(2)))
        y += max(icon, u(36)) + u(6)

    tip = f_small.render(i18n.t("guide.close"), True, C_TEXT_DIM)
    screen.blit(tip, (layout.w // 2 - tip.get_width() // 2, layout.h - u(34)))


def draw_help(screen, fonts, layout):
    f_tiny, f_small, f_med, f_big, f_huge = fonts
    u = layout.u
    overlay = pygame.Surface(layout.size, pygame.SRCALPHA)
    overlay.fill((10, 10, 16, 228))
    screen.blit(overlay, (0, 0))
    title = f_big.render(i18n.t("help.title"), True, C_GOLD)
    screen.blit(title, (layout.w // 2 - title.get_width() // 2, u(24)))

    col_x = [u(70), layout.w // 2 + u(40)]
    col_y = [u(78), u(78)]
    line_h = f_small.get_height() + u(4)
    col = 0
    for (section, rows) in help_sections():
        if col_y[col] + u(30) + len(rows) * line_h > layout.h - u(90) and col < 1:
            col += 1
        x, y = col_x[col], col_y[col]
        screen.blit(f_med.render(section, True, (168, 212, 246)), (x, y))
        y += f_med.get_height() + u(6)
        key_w = max(u(150), max(f_small.size(k)[0] for k, _ in rows) + u(12))
        for (k, v) in rows:
            screen.blit(f_small.render(k, True, C_GOLD), (x, y))
            screen.blit(f_small.render("— " + v, True, C_TEXT), (x + key_w, y))
            y += line_h
        col_y[col] = y + u(14)
    tip = f_small.render(i18n.t("help.close"), True, C_TEXT_DIM)
    screen.blit(tip, (layout.w // 2 - tip.get_width() // 2, layout.h - u(36)))


def _wrap_pixels(text, font, width):
    """Split a text into lines that fit within `width` pixels."""
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        cur = ""
        for word in paragraph.split(" "):
            trial = (cur + " " + word).strip()
            if font.size(trial)[0] <= width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def draw_bug_report(screen, fonts, layout, text, folder, saved, caret_on,
                    attach_shot=True, online=False, status=None):
    """The report window: a free-form description + a reminder of what is attached.

    `online`: the game knows a relay, so the report is also sent. `status`:
    where the sending stands once the report is saved — "sending", or one of
    the outcomes of `bugsend`.

    Returns the clickable areas: {"shot": checkbox} while typing,
    {"open": button} once saved.
    """
    f_tiny, f_small, f_med, f_big, f_huge = fonts
    u = layout.u
    overlay = pygame.Surface(layout.size, pygame.SRCALPHA)
    overlay.fill((8, 8, 14, 210))
    screen.blit(overlay, (0, 0))

    w = min(layout.w - u(80), u(720))
    h = min(layout.h - u(80), u(450))
    box = pygame.Rect((layout.w - w) // 2, (layout.h - h) // 2, w, h)
    pygame.draw.rect(screen, C_PANEL, box, border_radius=u(10))
    pygame.draw.rect(screen, C_GOLD, box, max(2, u(2)), border_radius=u(10))

    pad = u(20)
    y = box.y + pad
    title = f_big.render(i18n.t("bug.title"), True, C_GOLD)
    screen.blit(title, (box.x + pad, y))
    y += title.get_height() + u(6)

    if saved:
        ok = f_med.render(i18n.t("bug.saved"), True, C_OK)
        screen.blit(ok, (box.x + pad, y))
        y += ok.get_height() + u(10)
        if status:
            color = {"sent": C_OK, "rejected": C_BAD}.get(status, C_GOLD)
            img = f_small.render(i18n.t("bug." + status), True, color)
            screen.blit(img, (box.x + pad, y))
            y += img.get_height() + u(10)
        for line in saved:
            screen.blit(f_small.render(line, True, C_TEXT), (box.x + pad, y))
            y += f_small.get_height() + u(4)
        tip = f_small.render(i18n.t("bug.any_key"), True, C_TEXT_DIM)
        screen.blit(tip, (box.x + pad, box.bottom - pad - tip.get_height()))

        label = f_small.render(i18n.t("bug.open_folder"), True, C_TEXT)
        button = pygame.Rect(0, 0, label.get_width() + u(28),
                             label.get_height() + u(14))
        button.right = box.right - pad
        button.bottom = box.bottom - pad
        hover = button.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(screen, C_PANEL_DARK, button, border_radius=u(6))
        pygame.draw.rect(screen, C_GOLD if hover else C_BORDER, button,
                         max(1, u(2)), border_radius=u(6))
        screen.blit(label, label.get_rect(center=button.center))
        return {"open": button}

    intro = f_small.render(i18n.t("bug.intro"), True, C_TEXT_DIM)
    screen.blit(intro, (box.x + pad, y))
    y += intro.get_height() + u(10)

    field = pygame.Rect(box.x + pad, y, w - 2 * pad,
                        box.bottom - u(130) - y)
    pygame.draw.rect(screen, C_PANEL_DARK, field, border_radius=u(6))
    pygame.draw.rect(screen, C_BORDER, field, 1, border_radius=u(6))

    line_h = f_small.get_height() + u(3)
    max_lines = max(1, (field.h - u(12)) // line_h)
    lines = _wrap_pixels(text, f_small, field.w - u(16)) or [""]
    shown = lines[-max_lines:]
    ty = field.y + u(6)
    for i, line in enumerate(shown):
        img = f_small.render(line, True, C_TEXT)
        screen.blit(img, (field.x + u(8), ty))
        if caret_on and i == len(shown) - 1:
            cx = field.x + u(8) + img.get_width() + u(2)
            pygame.draw.line(screen, C_GOLD, (cx, ty),
                             (cx, ty + f_small.get_height()), max(1, u(2)))
        ty += line_h

    foot = field.bottom + u(12)
    keys = f_small.render(i18n.t("bug.keys"), True, C_GOLD)
    screen.blit(keys, (box.x + pad, foot))
    foot += keys.get_height() + u(8)

    # The screenshot checkbox: drawn, not a glyph, so that no font lacks it.
    label = f_small.render(i18n.t("bug.attach_shot"), True, C_TEXT)
    side = label.get_height() - u(2)
    tick = pygame.Rect(box.x + pad, foot + u(1), side, side)
    pygame.draw.rect(screen, C_PANEL_DARK, tick, border_radius=u(3))
    pygame.draw.rect(screen, C_GOLD, tick, max(1, u(2)), border_radius=u(3))
    if attach_shot:
        pygame.draw.lines(screen, C_OK, False, [
            (tick.x + side * 0.22, tick.y + side * 0.52),
            (tick.x + side * 0.42, tick.y + side * 0.74),
            (tick.x + side * 0.78, tick.y + side * 0.28)], max(2, u(3)))
    screen.blit(label, (tick.right + u(8), foot))
    shot_area = tick.union(pygame.Rect(tick.right, foot, label.get_width() + u(8),
                                       label.get_height()))
    foot += label.get_height() + u(8)

    destination = ("bug.destination_online" if online else "bug.destination")
    for line in (i18n.t("bug.attached"), i18n.t(destination, folder=folder)):
        screen.blit(f_tiny.render(line, True, C_TEXT_DIM), (box.x + pad, foot))
        foot += f_tiny.get_height() + u(4)
    return {"shot": shot_area}


def draw_pause(screen, fonts, buttons, layout):
    f_tiny, f_small, f_med, f_big, f_huge = fonts
    overlay = pygame.Surface(layout.size, pygame.SRCALPHA)
    overlay.fill((10, 10, 16, 190))
    screen.blit(overlay, (0, 0))
    title = f_huge.render(i18n.t("pause.title"), True, C_GOLD)
    screen.blit(title, (layout.w // 2 - title.get_width() // 2, layout.u(180)))
    mouse = pygame.mouse.get_pos()
    for b in buttons:
        b.draw(screen, f_med, mouse, layout.u(8))


def draw_end(screen, fonts, game, victory, buttons, layout):
    f_tiny, f_small, f_med, f_big, f_huge = fonts
    u = layout.u
    overlay = pygame.Surface(layout.size, pygame.SRCALPHA)
    overlay.fill((10, 10, 16, 215))
    screen.blit(overlay, (0, 0))
    cx = layout.w // 2
    label = i18n.t("end.victory") if victory else i18n.t("end.defeat")
    color = (246, 222, 128) if victory else (236, 118, 118)
    title = f_huge.render(label, True, color)
    screen.blit(title, (cx - title.get_width() // 2, u(86)))
    sub = i18n.t("end.victory_sub" if victory else "end.defeat_sub",
                 winner=(game.human if victory else game.enemy).name)
    s = f_med.render(sub, True, C_TEXT)
    screen.blit(s, (cx - s.get_width() // 2, u(150)))

    rows = [
        (i18n.t("end.duration"), fmt_time(game.elapsed), fmt_time(game.elapsed)),
        (i18n.t("end.units"), str(game.human.stat_units),
         str(game.enemy.stat_units)),
        (i18n.t("end.buildings"), str(game.human.stat_buildings),
         str(game.enemy.stat_buildings)),
        (i18n.t("end.kills"), str(game.human.stat_kills),
         str(game.enemy.stat_kills)),
        (i18n.t("end.losses"), str(game.human.stat_losses),
         str(game.enemy.stat_losses)),
    ]
    for r in RESOURCES:
        rows.append((i18n.t("end.gathered", resource=i18n.resource_name(r)),
                     str(game.human.stat_gathered[r]),
                     str(game.enemy.stat_gathered[r])))

    line_h = f_small.get_height() + u(8)
    box = pygame.Rect(cx - u(320), u(200), u(640), u(46) + len(rows) * line_h)
    pygame.draw.rect(screen, C_PANEL_DARK, box, border_radius=u(8))
    pygame.draw.rect(screen, C_BORDER, box, 1, border_radius=u(8))
    col_a, col_b = box.x + u(330), box.x + u(480)
    screen.blit(f_small.render(game.human.name, True, game.human.color),
                (col_a, box.y + u(12)))
    screen.blit(f_small.render(game.enemy.name, True, game.enemy.color),
                (col_b, box.y + u(12)))
    y = box.y + u(40)
    for (lab, a, b) in rows:
        screen.blit(f_small.render(lab, True, C_TEXT_DIM), (box.x + u(20), y))
        screen.blit(f_small.render(a, True, C_TEXT), (col_a, y))
        screen.blit(f_small.render(b, True, C_TEXT), (col_b, y))
        y += line_h

    mouse = pygame.mouse.get_pos()
    for btn in buttons:
        btn.draw(screen, f_med, mouse, u(8))

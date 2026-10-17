# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Interface: resource bar, minimap, selection, action buttons.

Every dimension is written in interface units then converted to pixels by
`Layout.u()`, so that the panel stays readable from 1280x760 up to 2880x1800.
"""

import math

import pygame

from . import i18n, keymap, sprites
from .settings import (BUILDINGS, BUILD_MENU, C_BAD, C_BORDER, C_GOLD, C_OK,
                       C_PANEL, C_PANEL_DARK, C_PANEL_LIGHT, C_SAND, C_TEXT,
                       C_TEXT_DIM, C_WATER, MILITARY, RESOURCES,
                       RES_COLOR, TEAM_COLORS, TILE,
                       T_FLOWER, T_GRASS, T_MEADOW, T_SAND, T_WATER, UNITS,
                       UNIT_ORDER, UPGRADES, UPGRADE_ORDER)
from .utils import clamp, fmt_time, mix, shade

BTN = 66          # interface units
BTN_GAP = 12

MINIMAP_COLORS = {T_WATER: C_WATER, T_SAND: C_SAND, T_GRASS: (96, 140, 80),
                  T_MEADOW: (84, 126, 72), T_FLOWER: (108, 150, 88)}


def minimap_surface(world):
    """The map at one pixel per tile: terrain, then the resource nodes."""
    surf = pygame.Surface((world.w, world.h))
    for ty in range(world.h):
        row = world.terrain[ty]
        for tx in range(world.w):
            surf.set_at((tx, ty), MINIMAP_COLORS[row[tx]])
    for node in world.nodes:
        surf.set_at((node.tx, node.ty), shade(RES_COLOR[node.kind], 0.9))
    return surf


class Action(object):
    # `binding` is the name the keymap knows this action by, None when the key
    # is fixed (Escape, Delete, Backspace). `hotkey` stays the text printed on
    # the cap: it follows both the language and the player's remapping.
    __slots__ = ("kind", "arg", "owner", "icon", "label", "hotkey", "binding",
                 "cost", "enabled", "tooltip", "rect", "progress")

    def __init__(self, kind, arg, owner=None, icon=None, label="", hotkey="",
                 cost=None, enabled=True, tooltip="", progress=None,
                 binding=None):
        self.kind, self.arg, self.owner = kind, arg, owner
        self.icon, self.label, self.hotkey = icon, label, hotkey
        self.binding = binding
        self.cost, self.enabled, self.tooltip = cost, enabled, tooltip
        self.progress = progress
        self.rect = pygame.Rect(0, 0, 1, 1)


class HUD(object):
    def __init__(self, game, fonts):
        self.game = game
        self.set_fonts(fonts)
        self.actions = []
        self.hover_action = None
        self.mini_terrain = None
        self.dragging_mini = False
        self._fog_cache = None
        self._fog_cache_t = -1.0
        self.relayout()
        self._build_minimap_terrain()

    def set_fonts(self, fonts):
        self.f_tiny, self.f_small, self.f_med, self.f_big, self.f_huge = fonts

    # ------------------------------------------------------------ template ----
    def relayout(self):
        """(Re)compute the panel rectangles for the current resolution."""
        L = self.game.layout
        self.L = L
        u = L.u
        self.btn = u(BTN)
        self.btn_gap = u(BTN_GAP)
        self.panel = pygame.Rect(0, L.h - L.hud, L.w, L.hud)
        pad = u(10)
        mini = L.hud - 2 * pad
        self.mini_rect = pygame.Rect(pad, self.panel.y + pad, mini, mini)
        info_w = min(u(430), max(u(260), L.w - self.mini_rect.right - u(360)))
        self.info_rect = pygame.Rect(self.mini_rect.right + u(12),
                                     self.panel.y + u(8), info_w, L.hud - u(16))
        self.act_rect = pygame.Rect(self.info_rect.right + u(12),
                                    self.panel.y + pad,
                                    max(self.btn, L.w - self.info_rect.right - u(22)),
                                    L.hud - 2 * pad)
        self._fog_cache = None
        self._fog_cache_t = -1.0

    # ----------------------------------------------------------- minimap ------
    def _build_minimap_terrain(self):
        self.mini_terrain = minimap_surface(self.game.world)

    def _fog_overlay(self, size):
        """The minimap fog layer, recomputed four times a second."""
        g = self.game
        if self._fog_cache is not None and g.elapsed - self._fog_cache_t < 0.25:
            return self._fog_cache
        overlay = pygame.Surface((g.world.w, g.world.h), pygame.SRCALPHA)
        for ty in range(g.world.h):
            exp = g.fog.explored[ty]
            vis = g.fog.visible[ty]
            for tx in range(g.world.w):
                if not exp[tx]:
                    overlay.set_at((tx, ty), (8, 8, 16, 255))
                elif not vis[tx]:
                    overlay.set_at((tx, ty), (8, 8, 16, 96))
        self._fog_cache = pygame.transform.scale(overlay, size)
        self._fog_cache_t = g.elapsed
        return self._fog_cache

    def mini_to_world(self, mx, my):
        fx = clamp((mx - self.mini_rect.x) / float(self.mini_rect.w), 0.0, 1.0)
        fy = clamp((my - self.mini_rect.y) / float(self.mini_rect.h), 0.0, 1.0)
        world = self.game.world
        return fx * world.world_w, fy * world.world_h

    def world_to_mini(self, wx, wy):
        world = self.game.world
        return (self.mini_rect.x + wx / float(world.world_w) * self.mini_rect.w,
                self.mini_rect.y + wy / float(world.world_h) * self.mini_rect.h)

    def draw_minimap(self, screen):
        g = self.game
        u = self.L.u
        r = self.mini_rect
        pygame.draw.rect(screen, C_PANEL_DARK, r.inflate(u(8), u(8)),
                         border_radius=u(6))
        mini = pygame.transform.scale(self.mini_terrain, r.size)
        if g.fog.enabled:
            mini.blit(self._fog_overlay(r.size), (0, 0))

        sx = r.w / float(g.world.world_w)
        sy = r.h / float(g.world.world_h)
        for b in g.buildings:
            if not b.alive:
                continue
            if (g.fog.enabled and b.player is not g.human
                    and not g.fog.explored_at(b.x, b.y)):
                continue
            size = max(3, int(b.size * TILE * sx))
            pygame.draw.rect(mini, b.player.color,
                             (int(b.tx * TILE * sx), int(b.ty * TILE * sy),
                              size, size))
        dot = max(2, u(2))
        for unit in g.units:
            if not unit.alive:
                continue
            if (g.fog.enabled and unit.player is not g.human
                    and not g.fog.visible_at(unit.x, unit.y)):
                continue
            col = unit.player.color if not unit.selected else (250, 245, 170)
            pygame.draw.circle(mini, col, (int(unit.x * sx), int(unit.y * sy)), dot)

        screen.blit(mini, r.topleft)
        cx, cy, cw, ch = g.camera.world_rect()
        vr = pygame.Rect(r.x + cx * sx, r.y + cy * sy,
                         max(4, cw * sx), max(4, ch * sy))
        pygame.draw.rect(screen, (250, 250, 230), vr, max(1, u(1)))
        pygame.draw.rect(screen, C_BORDER, r, max(1, u(1)))

        if g._alert_timer > 0.0 and g.last_alert_pos:
            px, py = self.world_to_mini(*g.last_alert_pos)
            k = (math.sin(g.elapsed * 7.0) + 1.0) * 0.5
            pygame.draw.circle(screen, (250, 90, 90), (int(px), int(py)),
                               int(u(5) + k * u(5)), max(1, u(2)))

    # ------------------------------------------------------------- top bar --
    def draw_topbar(self, screen, fps):
        g = self.game
        L = self.L
        u = L.u
        pygame.draw.rect(screen, C_PANEL, (0, 0, L.w, L.topbar))
        pygame.draw.line(screen, C_BORDER, (0, L.topbar - 1), (L.w, L.topbar - 1))
        icon_px = u(22)
        ty = (L.topbar - self.f_med.get_height()) // 2
        x = u(12)
        for kind in RESOURCES:
            screen.blit(sprites.resource_icon(kind, icon_px), (x, (L.topbar - icon_px) // 2))
            txt = self.f_med.render(str(int(g.human.res[kind])), True, C_TEXT)
            screen.blit(txt, (x + icon_px + u(4), ty))
            x += icon_px + u(8) + txt.get_width() + u(22)

        pop_col = C_BAD if g.human.pop >= g.human.pop_limit else C_TEXT
        ptxt = self.f_med.render(i18n.t("hud.population", pop=g.human.pop,
                                        limit=g.human.pop_limit),
                                 True, pop_col)
        screen.blit(ptxt, (x, ty))
        x += ptxt.get_width() + u(26)

        army = sum(1 for unit in g.units
                   if unit.player is g.human and unit.is_military)
        atxt = self.f_med.render(i18n.t("hud.army", count=army), True, C_TEXT_DIM)
        screen.blit(atxt, (x, ty))

        # right-hand block, right-aligned to avoid any overlap
        sty = (L.topbar - self.f_small.get_height()) // 2
        right = L.w - u(12)
        htxt = self.f_small.render(i18n.t("hud.keys"), True, C_TEXT_DIM)
        right -= htxt.get_width()
        screen.blit(htxt, (right, sty))
        ftxt = self.f_small.render(i18n.t("hud.fps", fps=fps), True, C_TEXT_DIM)
        right -= ftxt.get_width() + u(20)
        screen.blit(ftxt, (right, sty))
        if g.speed != 1.0:
            sp = self.f_small.render(i18n.t("hud.speed", speed="%.1f" % g.speed),
                                     True, C_GOLD)
            right -= sp.get_width() + u(16)
            screen.blit(sp, (right, sty))
        ttxt = self.f_med.render(fmt_time(g.elapsed), True, C_GOLD)
        right -= ttxt.get_width() + u(20)
        screen.blit(ttxt, (right, ty))

    # ------------------------------------------------------------ selection --
    def draw_selection(self, screen):
        g = self.game
        u = self.L.u
        r = self.info_rect
        pygame.draw.rect(screen, C_PANEL_DARK, r, border_radius=u(6))
        pygame.draw.rect(screen, C_BORDER, r, 1, border_radius=u(6))
        sel = g.selection
        if not sel:
            for i, line in enumerate(i18n.lines("hud.hints")):
                screen.blit(self.f_small.render(line, True, C_TEXT_DIM),
                            (r.x + u(12), r.y + u(12) + i * u(22)))
            return
        if len(sel) == 1:
            self._draw_single(screen, r, sel[0])
        else:
            self._draw_multi(screen, r, sel)

    def _draw_single(self, screen, r, ent):
        u = self.L.u
        icon_kind = ent.utype if ent.is_unit else ent.btype
        icon = sprites.entity_icon(icon_kind, ent.team, u(54))
        screen.blit(icon, (r.x + u(10), r.y + u(12)))
        tx = r.x + u(74)
        screen.blit(self.f_med.render(ent.name, True, C_TEXT), (tx, r.y + u(10)))
        own = ent.player is self.game.human
        sub = ent.role if ent.is_unit else i18n.t("hud.building")
        if not own:
            sub = i18n.t("hud.owned_by", what=sub, owner=ent.player.name)
        screen.blit(self.f_small.render(sub, True, C_TEXT_DIM), (tx, r.y + u(32)))

        hp_ratio = ent.hp / ent.max_hp
        bar = pygame.Rect(tx, r.y + u(52), min(u(200), r.right - tx - u(70)), u(12))
        pygame.draw.rect(screen, (24, 22, 28), bar)
        pygame.draw.rect(screen, (int(220 * (1 - hp_ratio) + 90 * hp_ratio),
                                  int(70 * (1 - hp_ratio) + 205 * hp_ratio), 80),
                         (bar.x, bar.y, int(bar.w * hp_ratio), bar.h))
        pygame.draw.rect(screen, C_BORDER, bar, 1)
        screen.blit(self.f_tiny.render(i18n.t("hud.hp", hp=int(ent.hp),
                                               max=int(ent.max_hp)),
                                       True, C_TEXT),
                    (bar.right + u(8), bar.y))

        y = r.y + u(72)
        if ent.is_unit:
            stats = i18n.t("hud.stats", atk=int(ent.attack), armor=int(ent.armor),
                           rng=int(ent.spec["rng"] / TILE) or 1)
            screen.blit(self.f_small.render(stats, True, C_TEXT_DIM), (tx, y))
            y += u(20)
            if own:
                st = ent.status_label()
                if ent.carry > 0 and ent.carry_kind:
                    st += i18n.t("hud.carrying", amount=int(ent.carry),
                                 resource=i18n.resource_short(ent.carry_kind))
                screen.blit(self.f_small.render(st, True, C_GOLD), (tx, y))
        else:
            if ent.spec.get("atk"):
                stats = i18n.t("hud.building_stats", atk=int(ent.attack),
                               rng=int(ent.attack_range / TILE) or 1,
                               level=ent.level, max=ent.max_level)
                screen.blit(self.f_small.render(stats, True, C_TEXT_DIM),
                            (tx, y))
                y += u(20)
            screen.blit(self.f_small.render(ent.status_label(), True, C_GOLD), (tx, y))
            y += u(20)
            if own and ent.queue:
                qx = tx
                for q in ent.queue[:8]:
                    screen.blit(sprites.unit_icon(q[0], ent.team, u(26)), (qx, y))
                    qx += u(28)
            elif own and ent.desc:
                screen.blit(self.f_tiny.render(ent.desc[:58], True, C_TEXT_DIM),
                            (tx, y))

    def _draw_multi(self, screen, r, sel):
        u = self.L.u
        screen.blit(self.f_small.render(i18n.tp("hud.selected", len(sel)),
                                        True, C_TEXT), (r.x + u(10), r.y + u(6)))
        cell = u(40)
        icon_px = u(34)
        x, y = r.x + u(10), r.y + u(26)
        per_row = max(1, (r.w - u(20)) // cell)
        rows = max(1, (r.h - u(30)) // u(38))
        for i, ent in enumerate(sel[:rows * per_row]):
            kind = ent.utype if ent.is_unit else ent.btype
            px = x + (i % per_row) * cell
            py = y + (i // per_row) * u(38)
            pygame.draw.rect(screen, C_PANEL_LIGHT,
                             (px - u(2), py - u(2), icon_px + u(4), icon_px + u(2)),
                             border_radius=u(4))
            screen.blit(sprites.entity_icon(kind, ent.team, icon_px), (px, py))
            ratio = ent.hp / ent.max_hp
            pygame.draw.rect(screen, (30, 28, 34), (px, py + u(30), u(32), u(4)))
            pygame.draw.rect(screen, (90, 205, 95) if ratio > 0.4 else C_BAD,
                             (px, py + u(30), int(u(32) * ratio), u(4)))
        if len(sel) > rows * per_row:
            screen.blit(self.f_tiny.render(
                i18n.t("hud.more", count=len(sel) - rows * per_row),
                True, C_TEXT_DIM),
                        (r.right - u(40), r.bottom - u(18)))

    # -------------------------------------------------------------- actions --
    def build_actions(self):
        g = self.game
        acts = []
        sel = [e for e in g.selection if e.player is g.human]
        units = [e for e in sel if e.is_unit]
        builders = [unit for unit in units if unit.spec.get("builder")]
        buildings = [e for e in sel if e.is_building]

        if g.build_mode:
            acts.append(Action("cancel_build", None,
                               label=i18n.t("actions.cancel"),
                               hotkey=i18n.t("actions.key_escape"),
                               tooltip=i18n.t("actions.cancel_tip")))
            return acts

        if builders:
            for btype in BUILD_MENU:
                spec = BUILDINGS[btype]
                cost = spec["cost"]
                acts.append(Action(
                    "build", btype, icon=("b", btype),
                    label=i18n.building_short(btype),
                    binding="building.%s" % btype,
                    hotkey=keymap.label("building.%s" % btype), cost=cost,
                    enabled=g.human.can_afford(cost),
                    tooltip=i18n.building_desc(btype)))
        if units:
            acts.append(Action("stop", None, label=i18n.t("actions.stop"),
                               binding="command.stop",
                               hotkey=keymap.label("command.stop"),
                               tooltip=i18n.t("actions.stop_tip")))
            if any(unit.is_military for unit in units):
                acts.append(Action("amove", None, label=i18n.t("actions.attack"),
                                   binding="command.attack_move",
                                   hotkey=keymap.label("command.attack_move"),
                                   tooltip=i18n.t("actions.attack_tip")))
        if len(buildings) == 1 and not units:
            b = buildings[0]
            if b.under_construction:
                acts.append(Action("cancel_build_site", b,
                                   label=i18n.t("actions.demolish"),
                                   hotkey=i18n.t("actions.key_delete"),
                                   tooltip=i18n.t("actions.demolish_tip")))
            else:
                for utype in b.spec.get("trains", ()):
                    spec = UNITS[utype]
                    afford = g.human.can_afford(spec["cost"])
                    pop_ok = g.human.pop + spec["pop"] <= g.human.pop_limit
                    acts.append(Action(
                        "train", utype, owner=b, icon=("u", utype),
                        label=i18n.unit_short(utype),
                        binding="unit.%s" % utype,
                        hotkey=keymap.label("unit.%s" % utype),
                        cost=spec["cost"], enabled=afford and pop_ok,
                        tooltip=i18n.t("actions.train_tip",
                                       name=i18n.unit_name(utype),
                                       role=i18n.unit_role(utype),
                                       desc=i18n.unit_desc(utype))))
                if b.spec.get("research"):
                    for key in UPGRADE_ORDER:
                        spec = UPGRADES[key]
                        state = g.human.upgrade_state(key)
                        acts.append(Action(
                            "research", key, owner=b,
                            label=i18n.upgrade_short(key),
                            icon=("up", key),
                            binding="upgrade.%s" % key,
                            hotkey=keymap.label("upgrade.%s" % key),
                            cost=spec["cost"],
                            enabled=(state == "available"
                                     and g.human.can_afford(spec["cost"])
                                     and b.research is None),
                            tooltip=i18n.t("actions.research_tip",
                                           name=i18n.upgrade_name(key),
                                           desc=i18n.upgrade_desc(key))
                            + (i18n.t("actions.research_done")
                               if state == "done" else "")))
                if b.spec.get("levels"):
                    acts.append(self._level_action(b))
                if b.queue or b.research or b.leveling:
                    acts.append(Action("cancel_prod", b,
                                       label=i18n.t("actions.cancel_prod"),
                                       hotkey=i18n.t("actions.key_backspace"),
                                       tooltip=i18n.t("actions.cancel_prod_tip")))
        return acts

    def _level_action(self, b):
        """The button that takes a building (a tower) up one level."""
        step = b.next_level()
        common = dict(label=i18n.t("actions.level_up"), icon=("up", "level"),
                      binding="command.level_up",
                      hotkey=keymap.label("command.level_up"))
        if step is None:
            return Action("level_up", b, enabled=False,
                          tooltip=i18n.t("actions.level_max"), **common)
        tip = i18n.t("actions.level_up_tip", level=b.level + 1,
                     atk=step.get("atk", 0), hp=step.get("hp", 0),
                     rng=int(step.get("rng", 0) / TILE))
        return Action("level_up", b, cost=step["cost"],
                      enabled=(b.leveling is None
                               and self.game.human.can_afford(step["cost"])),
                      tooltip=tip, **common)

    def layout_actions(self, acts):
        r = self.act_rect
        step = self.btn + self.btn_gap
        cols = max(1, r.w // step)
        row_h = step + self.L.u(10)
        for i, a in enumerate(acts):
            a.rect = pygame.Rect(r.x + (i % cols) * step,
                                 r.y + (i // cols) * row_h, self.btn, self.btn)
        return acts

    def draw_actions(self, screen):
        u = self.L.u
        mouse = pygame.mouse.get_pos()
        self.hover_action = None
        icon_px = u(38)
        for a in self.actions:
            hovered = a.rect.collidepoint(mouse)
            if hovered:
                self.hover_action = a
            bg = C_PANEL_LIGHT if a.enabled else (42, 38, 46)
            if hovered and a.enabled:
                bg = mix(bg, (255, 255, 255), 0.18)
            pygame.draw.rect(screen, bg, a.rect, border_radius=u(6))
            pygame.draw.rect(screen, C_BORDER if a.enabled else (60, 56, 66),
                             a.rect, max(1, u(1)), border_radius=u(6))
            if a.icon:
                kind, key = a.icon
                if kind == "u":
                    icon = sprites.unit_icon(key, 0, icon_px)
                elif kind == "up":
                    icon = sprites.upgrade_icon(key, icon_px)
                else:
                    icon = sprites.building_icon(key, 0, icon_px)
                if not a.enabled:
                    icon = icon.copy()
                    icon.set_alpha(110)
                screen.blit(icon, (a.rect.centerx - icon.get_width() // 2,
                                   a.rect.y + u(5)))
                img = self.f_tiny.render(self._fit(a.label, a.rect.w - u(6)), True,
                                         C_TEXT if a.enabled else C_TEXT_DIM)
                screen.blit(img, (a.rect.centerx - img.get_width() // 2,
                                  a.rect.bottom - img.get_height() - u(3)))
            else:
                img = self.f_small.render(
                    self._fit(a.label, a.rect.w - u(8), self.f_small), True,
                    C_TEXT if a.enabled else C_TEXT_DIM)
                # shifted down: the shortcut takes up the top right corner
                screen.blit(img, (a.rect.centerx - img.get_width() // 2,
                                  a.rect.centery - img.get_height() // 2 + u(6)))
            hk = self.f_tiny.render(a.hotkey, True,
                                    C_GOLD if a.enabled else C_TEXT_DIM)
            screen.blit(hk, (a.rect.right - hk.get_width() - u(4), a.rect.y + u(3)))
            if a.cost:
                items, total = [], 0
                res_px = u(12)
                for kind, val in a.cost.items():
                    t = self.f_tiny.render(str(val), True,
                                           C_TEXT if a.enabled else C_BAD)
                    items.append((kind, t))
                    total += res_px + t.get_width() + u(5)
                cx = a.rect.centerx - total // 2
                cy = a.rect.bottom + u(3)
                for (kind, t) in items:
                    screen.blit(sprites.resource_icon(kind, res_px), (cx, cy))
                    screen.blit(t, (cx + res_px + u(1), cy + u(1)))
                    cx += res_px + t.get_width() + u(5)

    def draw_tooltip(self, screen):
        a = self.hover_action
        if not a:
            return
        u = self.L.u
        lines = [a.label]
        if a.tooltip:
            lines += _wrap(a.tooltip, 46)
        if a.cost:
            lines.append(i18n.t("hud.cost", cost=format_cost(a.cost)))
        lh = self.f_small.get_height() + u(3)
        w = max(self.f_small.size(line)[0] for line in lines) + u(20)
        h = u(10) + len(lines) * lh
        x = clamp(a.rect.centerx - w // 2, u(6), self.L.w - w - u(6))
        y = max(u(6), a.rect.y - h - u(10))
        box = pygame.Rect(x, y, w, h)
        pygame.draw.rect(screen, (18, 16, 22), box, border_radius=u(6))
        pygame.draw.rect(screen, C_GOLD, box, max(1, u(1)), border_radius=u(6))
        for i, line in enumerate(lines):
            col = C_GOLD if i == 0 else C_TEXT
            screen.blit(self.f_small.render(line, True, col),
                        (x + u(10), y + u(5) + i * lh))

    # -------------------------------------------------------------- messages --
    def draw_messages(self, screen):
        g = self.game
        u = self.L.u
        y = self.L.topbar + u(10)
        for (text, color, t) in g.messages[-5:]:
            a = 255 if t < 5.0 else int(255 * (1.0 - (t - 5.0) / 2.0))
            img = self.f_small.render(text, True, color)
            img.set_alpha(max(0, a))
            bg = pygame.Surface((img.get_width() + u(14), img.get_height() + u(6)),
                                pygame.SRCALPHA)
            bg.fill((16, 14, 20, min(170, max(0, a))))
            screen.blit(bg, (u(12), y - u(3)))
            screen.blit(img, (u(19), y))
            y += img.get_height() + u(8)

    def draw_hover_tip(self, screen):
        """A small label near the cursor over a hovered node."""
        node = self.game.hover_node
        if node is None:
            return
        u = self.L.u
        text = i18n.t("hud.node", resource=i18n.resource_name(node.kind),
                      amount=int(node.amount), max=node.max_amount)
        icon_px = u(16)
        img = self.f_small.render(text, True, C_TEXT)
        w = icon_px + u(8) + img.get_width() + u(16)
        h = max(img.get_height(), icon_px) + u(10)
        mx, my = pygame.mouse.get_pos()
        x = clamp(mx + u(18), u(4), self.L.w - w - u(4))
        y = clamp(my - h - u(10), self.L.topbar + u(4), self.L.h - h - u(4))
        box = pygame.Rect(x, y, w, h)
        pygame.draw.rect(screen, (18, 16, 22), box, border_radius=u(5))
        pygame.draw.rect(screen, RES_COLOR[node.kind], box, max(1, u(1)),
                         border_radius=u(5))
        screen.blit(sprites.resource_icon(node.kind, icon_px),
                    (box.x + u(8), box.centery - icon_px // 2))
        screen.blit(img, (box.x + u(8) + icon_px + u(8),
                          box.centery - img.get_height() // 2))

    # ------------------------------------------------------------- ensemble --
    def draw(self, screen, fps):
        pygame.draw.rect(screen, C_PANEL, self.panel)
        pygame.draw.line(screen, C_BORDER, self.panel.topleft,
                         (self.panel.right, self.panel.y))
        self.draw_topbar(screen, fps)
        self.draw_minimap(screen)
        self.draw_selection(screen)
        self.actions = self.layout_actions(self.build_actions())
        self.draw_actions(screen)
        self.draw_messages(screen)
        self.draw_hover_tip(screen)
        self.draw_tooltip(screen)

    # ------------------------------------------------------------ interaction --
    def _fit(self, text, width, font=None):
        """Truncate a label so that it fits in the given width."""
        font = font or self.f_tiny
        if font.size(text)[0] <= width:
            return text
        for i in range(len(text) - 1, 0, -1):
            cut = text[:i] + "."
            if font.size(cut)[0] <= width:
                return cut
        return text[:1]

    def action_at(self, pos):
        for a in self.actions:
            if a.rect.collidepoint(pos):
                return a
        return None

    def action_by_binding(self, binding):
        if binding is None:
            return None
        for a in self.actions:
            if a.binding == binding:
                return a
        return None

    def action_by_hotkey(self, name):
        """Still used for the fixed keys, which have no binding of their own."""
        for a in self.actions:
            if a.hotkey.lower() == name.lower():
                return a
        return None

    def activate(self, a):
        g = self.game
        if a is None:
            return False
        if not a.enabled and a.kind in ("build", "train", "research",
                                         "level_up"):
            cost = a.cost or {}
            if cost and not g.human.can_afford(cost):
                g.warn_cost(cost)
            else:
                g.message(i18n.t("messages.unavailable"), (236, 196, 108))
                g.play("deny")
            return True
        if a.kind == "build":
            g.start_build_mode(a.arg)
        elif a.kind == "cancel_build":
            g.build_mode = None
        elif a.kind == "train":
            g.order_train(a.owner, a.arg)
        elif a.kind == "research":
            g.order_research(a.owner, a.arg)
        elif a.kind == "level_up":
            g.order_level_up(a.arg)
        elif a.kind == "cancel_prod":
            g.cancel_production(a.arg)
        elif a.kind == "cancel_build_site":
            g.cancel_site(a.arg)
        elif a.kind == "stop":
            g.stop_selection()
        elif a.kind == "amove":
            g.attack_move_mode = True
            g.message(i18n.t("messages.attack_move"), (240, 190, 130))
        return True


def format_cost(cost):
    """"50 Kib.  20 Wool" — a cost written with the short names."""
    return "  ".join(i18n.t("hud.resource_amount", amount=v,
                            resource=i18n.resource_short(k))
                     for k, v in cost.items())


def _wrap(text, width):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines

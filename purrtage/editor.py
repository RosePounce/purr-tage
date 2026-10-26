# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""The map editor: terrain, resource nodes and bases, painted with the mouse.

The screen mirrors a game: the map in the middle, a bar at the top, a panel at
the bottom with the minimap, the tools and the file actions. The world is
drawn by the game's own `WorldRenderer`, which only needs to find here the few
things it reads from a game: `world`, `camera`, `fog`, `hover_node` and
`elapsed`.

Maps are written by `purrtage.mapfile`; the menu lists them next to the
generated maps, for solo and network games alike.
"""

import os

import pygame

from . import i18n, mapfile, sprites
from .camera import Camera
from .fog import Fog
from .render import WorldRenderer
from .screens import Button, _wrap_pixels
from .settings import (C_BAD, C_BORDER, C_GOLD, C_OK, C_PANEL, C_PANEL_DARK,
                       C_PANEL_LIGHT, C_TEXT, C_TEXT_DIM, DEFAULT_MAP_SIZE,
                       MAP_SIZES, RES_AMOUNT, R_CATNIP, R_KIBBLE, R_STONE,
                       R_WOOL, TEAM_COLORS, TERRAIN_WALKABLE, TILE, T_FLOWER, T_GRASS,
                       T_MEADOW, T_SAND, T_WATER)
from .ui import minimap_surface
from .utils import bresenham, clamp, mix
from .world import World

# (kind, value): what a left click does on the map.
TOOLS = (("terrain", T_WATER), ("terrain", T_SAND), ("terrain", T_GRASS),
         ("terrain", T_MEADOW), ("terrain", T_FLOWER),
         ("node", R_KIBBLE), ("node", R_WOOL), ("node", R_CATNIP),
         ("node", R_STONE),
         ("base", 0), ("base", 1), ("erase", None))
TERRAIN_KEYS = {T_WATER: "water", T_SAND: "sand", T_GRASS: "grass",
                T_MEADOW: "meadow", T_FLOWER: "flower"}
# Digit row: 1 to 0 pick the first ten tools, Delete the eraser.
TOOL_KEYS = (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5,
             pygame.K_6, pygame.K_7, pygame.K_8, pygame.K_9, pygame.K_0)

BRUSHES = (1, 3, 5, 9)          # brush side, in tiles
AMOUNT_STEP = 20                # Ctrl + wheel on a node
AMOUNT_MIN, AMOUNT_MAX = 20, 5000
MAX_NAME = 40
UNDO_DEPTH = 40
MINIMAP_REFRESH = 0.25          # seconds between two minimap rebuilds
LIST_ROWS = 9                   # saved maps shown at once in the open list


class MapEditor(object):
    def __init__(self, fonts, layout, edge_scroll=True):
        self.fonts = fonts
        self.layout = layout
        self.edge_scroll = edge_scroll
        self.elapsed = 0.0
        self.hover_node = None
        self.hover_tile = None
        self.tool = 2                   # grass
        self.brush = 1                  # index in BRUSHES
        self.new_size = MAP_SIZES.index(DEFAULT_MAP_SIZE)
        self.path = None                # the file the map was read from or saved to
        self.dirty = False
        self.pending = None             # an action waiting for its confirmation
        self.undo_stack = []
        self.stroke = None              # (button, last tile) while painting
        self.stroke_changed = False
        self.panning = False
        self.dragging_mini = False
        self.editing_name = False
        self.text_events = False
        self.listing = None             # the saved maps while the open list shows
        self.list_top = 0
        self.status = ""
        self.status_color = C_TEXT
        self.status_t = 0.0
        self._mini = None
        self._mini_t = -1.0
        self._mini_dirty = True
        self.buttons = {}
        self.tool_rects = []
        self.list_buttons = []
        self.set_world(World.blank(DEFAULT_MAP_SIZE))
        self.relayout(layout, fonts)

    # ----------------------------------------------------------------- world --
    def set_world(self, world, path=None):
        """Edit another map: a blank one, a generated one or a saved one."""
        while len(world.start_tiles) < mapfile.BASES:
            world.start_tiles.append(
                world.default_start_tiles()[len(world.start_tiles)])
        self.world = world
        self.path = path
        self.dirty = False
        self.pending = None
        self.undo_stack = []
        self.fog = Fog(False, (world.w, world.h))
        self.camera = Camera(self.layout.view, self.layout.asset_scale,
                             (world.world_w, world.world_h))
        self.camera.edge_scroll = self.edge_scroll
        self.camera.center_on(world.world_w * 0.5, world.world_h * 0.5)
        self.renderer = WorldRenderer(self)
        self.hover_node = None
        self._mini_dirty = True

    def _snapshot(self):
        """Remember the map before a change, for Ctrl+Z."""
        self.undo_stack.append(mapfile.encode(self.world))
        del self.undo_stack[:-UNDO_DEPTH]

    def undo(self):
        if not self.undo_stack:
            self.say(i18n.t("editor.nothing_to_undo"), C_TEXT_DIM)
            return
        world = mapfile.decode(self.undo_stack.pop())
        world.name = self.world.name        # typing is not undone with Ctrl+Z
        # Keep the camera where it is: undoing must not throw the view around.
        self.world = world
        self.renderer = WorldRenderer(self)
        self.hover_node = None
        self.dirty = True
        self._mini_dirty = True

    # ---------------------------------------------------------------- layout --
    def relayout(self, layout, fonts=None):
        self.layout = layout
        if fonts:
            self.fonts = fonts
        L = layout
        u = L.u
        self.camera.set_view(L.view, L.asset_scale)
        self.renderer.invalidate()
        self.panel = pygame.Rect(0, L.h - L.hud, L.w, L.hud)
        pad = u(10)
        mini = L.hud - 2 * pad
        self.mini_rect = pygame.Rect(pad, self.panel.y + pad, mini, mini)

        # The tools, on two rows: terrains then the rest. They narrow down
        # in a small window rather than run under the action buttons.
        side, gap, bgap = u(58), u(6), u(8)
        left = self.mini_rect.right + u(16)
        room = L.w - left - pad - 3 * u(110) - 2 * bgap - u(16)
        tw = max(side, min(u(84), room // (len(TOOLS) - 5) - gap))
        self.tool_rects = []
        for i in range(len(TOOLS)):
            row, col = (0, i) if i < 5 else (1, i - 5)
            self.tool_rects.append(pygame.Rect(
                left + col * (tw + gap),
                self.panel.y + pad + row * (side + u(12)), tw, side))
        tools_right = max(r.right for r in self.tool_rects)

        # The actions, three columns on the right.
        bw = max(u(110), min(u(170), (L.w - tools_right - u(40)) // 3))
        bh = u(38)
        x0 = L.w - pad - 3 * bw - 2 * bgap
        y0 = self.panel.y + pad
        grid = (("brush", "size", "new"),
                ("random", "open", "save"),
                ("undo", None, "back"))
        self.buttons = {}
        for r, row in enumerate(grid):
            for c, key in enumerate(row):
                if key:
                    self.buttons[key] = Button(
                        (x0 + c * (bw + bgap), y0 + r * (bh + bgap), bw, bh),
                        "", key)
        self.name_rect = pygame.Rect(u(10), u(4), u(360), L.topbar - u(8))
        self._relayout_list()

    def _relayout_list(self):
        L = self.layout
        u = L.u
        w = u(460)
        x = L.w // 2 - w // 2
        rows = min(LIST_ROWS, len(self.listing or ()))
        top = L.h // 2 - u(40 + 23 * rows)
        self.list_rect = pygame.Rect(x - u(16), top - u(56), w + u(32),
                                     u(56 + 46 * rows + 70))
        self.list_buttons = []
        if self.listing is None:
            return
        shown = self.listing[self.list_top:self.list_top + LIST_ROWS]
        for i, (path, name, side) in enumerate(shown):
            label = i18n.t("editor.list_row", name=name,
                           size=i18n.map_size_name(side))
            self.list_buttons.append(
                Button((x, top + i * u(46), w, u(40)), label, path))
        self.list_buttons.append(
            Button((x + w // 4, top + rows * u(46) + u(8), w // 2, u(40)),
                   i18n.t("editor.cancel"), None))

    # ------------------------------------------------------------- messages --
    def say(self, text, color=C_TEXT):
        self.status = text
        self.status_color = color
        self.status_t = 4.0

    def _confirm(self, action):
        """True when `action` may go ahead: at once if nothing would be lost,
        on a second click otherwise."""
        if not self.dirty or self.pending == action:
            self.pending = None
            return True
        self.pending = action
        self.say(i18n.t("editor.confirm"), C_GOLD)
        return False

    # ---------------------------------------------------------------- update --
    def update(self, dt):
        self.elapsed += dt
        self.status_t = max(0.0, self.status_t - dt)
        if self.listing is None and not self.editing_name:
            mouse = pygame.mouse.get_pos()
            focused = pygame.mouse.get_focused()
            if self.panning or self.stroke:
                focused = False         # no edge scrolling while dragging
            self.camera.update(dt, pygame.key.get_pressed(), mouse, focused)
        self._update_hover(pygame.mouse.get_pos())
        self.buttons["brush"].label = i18n.t(
            "editor.brush", size=BRUSHES[self.brush])
        self.buttons["size"].label = i18n.t(
            "editor.new_size", size=i18n.map_size_name(MAP_SIZES[self.new_size]))
        self.buttons["new"].label = i18n.t("editor.new")
        self.buttons["random"].label = i18n.t("editor.random")
        self.buttons["open"].label = i18n.t("editor.open")
        self.buttons["save"].label = i18n.t("editor.save")
        self.buttons["undo"].label = i18n.t("editor.undo")
        self.buttons["back"].label = i18n.t("editor.back")
        self.buttons["undo"].enabled = bool(self.undo_stack)

    def _tile_at(self, pos):
        if not self.layout.view.collidepoint(pos):
            return None
        wx, wy = self.camera.screen_to_world(*pos)
        tile = (int(wx // TILE), int(wy // TILE))
        return tile if self.world.in_bounds(*tile) else None

    def _update_hover(self, pos):
        self.hover_tile = self._tile_at(pos)
        self.hover_node = (self.world.node_at.get(self.hover_tile)
                           if self.hover_tile else None)

    # --------------------------------------------------------------- editing --
    def _brush_tiles(self, tile):
        """The tiles of a round brush centred on `tile`, inside the map."""
        side = BRUSHES[self.brush]
        r = (side - 1) // 2
        rr = (side / 2.0) ** 2
        cx, cy = tile
        out = []
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy <= rr and self.world.in_bounds(cx + dx, cy + dy):
                    out.append((cx + dx, cy + dy))
        return out

    def _in_base(self, tile):
        return any(tile in self.world.base_footprint(s)
                   for s in self.world.start_tiles)

    def _apply(self, tile, erase):
        """One dab of the current tool. True when the map changed."""
        w = self.world
        kind, value = TOOLS[self.tool]
        if erase or kind == "erase":
            gone = [w.node_at[t] for t in self._brush_tiles(tile) if t in w.node_at]
            for node in gone:
                w.remove_node(node)
            return bool(gone)
        if kind == "terrain":
            changed = False
            for (tx, ty) in self._brush_tiles(tile):
                if w.terrain[ty][tx] != value:
                    w.terrain[ty][tx] = value
                    changed = True
                node = w.node_at.get((tx, ty))
                if node is not None and not TERRAIN_WALKABLE[value]:
                    w.remove_node(node)         # no kibble bowl afloat
                    changed = True
            return changed
        if kind == "node":
            tx, ty = tile
            node = w.node_at.get(tile)
            if node is not None and node.kind == value:
                return False
            if not TERRAIN_WALKABLE[w.terrain[ty][tx]] or self._in_base(tile):
                return False
            w.put_node(value, tx, ty)
            return True
        if kind == "base":
            tx = int(clamp(tile[0], 1, w.w - 2))
            ty = int(clamp(tile[1], 1, w.h - 2))
            if w.start_tiles[value] == (tx, ty):
                return False
            w.start_tiles[value] = (tx, ty)
            for t in w.base_footprint((tx, ty)):
                if t in w.node_at:
                    w.remove_node(w.node_at[t])
            return True
        return False

    def _paint_to(self, tile):
        """Paint from the last tile of the stroke to `tile`, without gaps
        however fast the mouse goes."""
        button, last = self.stroke
        erase = button == 3
        kind = TOOLS[self.tool][0]
        if kind == "base" and not erase:
            path = [tile]               # a base follows the mouse, it is not a trail
        elif last is None:
            path = [tile]
        else:
            path = bresenham(last[0], last[1], tile[0], tile[1])[1:]
        for t in path:
            if self._apply(t, erase):
                self.stroke_changed = True
                self._mini_dirty = True
        self.stroke = (button, tile)

    def _start_stroke(self, button, tile):
        self._snapshot()
        self.stroke = (button, None)
        self.stroke_changed = False
        self._paint_to(tile)

    def _end_stroke(self):
        if self.stroke is None:
            return
        self.stroke = None
        if self.stroke_changed:
            self.dirty = True
            self.pending = None
            self.world.finish()         # the bushes and the obstacle grid
        else:
            self.undo_stack.pop()       # nothing happened: nothing to undo

    def _change_amount(self, node, direction):
        self._snapshot()
        amount = int(clamp(node.max_amount + direction * AMOUNT_STEP,
                           AMOUNT_MIN, AMOUNT_MAX))
        node.max_amount = node.amount = amount
        self.dirty = True

    # ------------------------------------------------------------ file menu --
    def new_map(self, generated):
        if not self._confirm("random" if generated else "new"):
            return
        side = MAP_SIZES[self.new_size]
        world = World(None, side) if generated else World.blank(side)
        self.set_world(world)
        self.say(i18n.t("editor.created", size=i18n.map_size_name(side)), C_OK)

    def open_list(self):
        if not self._confirm("open"):
            return
        self.listing = mapfile.list_maps()
        self.list_top = 0
        if not self.listing:
            self.listing = None
            self.say(i18n.t("editor.no_maps", folder=mapfile.maps_dir()),
                     C_TEXT_DIM)
            return
        self._relayout_list()

    def close_list(self):
        self.listing = None
        self.list_buttons = []

    def open_map(self, path):
        self.close_list()
        try:
            world = mapfile.load(path)
        except (OSError, mapfile.MapError) as exc:
            self.say(i18n.t("editor.load_failed", error=exc), C_BAD)
            return
        self.set_world(world, path)
        self.say(i18n.t("editor.opened", name=world.name), C_OK)

    def save(self):
        """Write the map, unless it cannot be played. True on success."""
        problems = mapfile.problems(self.world)
        if problems:
            self.say(i18n.t(problems[0]), C_BAD)
            return False
        name = self.world.name.strip() or i18n.t("editor.default_name")
        self.world.name = name
        path = os.path.join(mapfile.maps_dir(), mapfile.file_name(name))
        if os.path.exists(path) and path != self.path:
            self.say(i18n.t("editor.name_taken", name=name), C_BAD)
            return False
        try:
            mapfile.save(self.world, path)
        except OSError as exc:
            self.say(i18n.t("editor.save_failed", error=exc), C_BAD)
            return False
        self.path = path
        self.dirty = False
        self.pending = None
        self.say(i18n.t("editor.saved", path=path), C_OK)
        return True

    # ------------------------------------------------------------ name field --
    def start_name(self):
        """Type the map name. TEXTINPUT is authoritative when SDL sends it,
        as in the bug report: reading KEYDOWN too would double every letter."""
        self.editing_name = True
        self.text_events = False
        try:
            pygame.key.start_text_input()
            self.text_events = hasattr(pygame, "TEXTINPUT")
        except Exception:
            pass

    def stop_name(self):
        if self.editing_name:
            try:
                pygame.key.stop_text_input()
            except Exception:
                pass
        self.editing_name = False

    def _name_event(self, ev):
        w = self.world
        if ev.type == pygame.TEXTINPUT:
            self._type(ev.text)
        elif ev.type == pygame.MOUSEBUTTONDOWN:
            self.stop_name()
            return False                # the click still does its own job
        elif ev.type == pygame.KEYDOWN:
            if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE,
                          pygame.K_TAB):
                self.stop_name()
            elif ev.key == pygame.K_BACKSPACE:
                if w.name:
                    w.name = w.name[:-1]
                    self.dirty = True
            elif (not self.text_events
                    and ev.unicode and ev.unicode.isprintable()):
                self._type(ev.unicode)  # no TEXTINPUT event on this system
        return True

    def _type(self, text):
        text = "".join(ch for ch in text if ch.isprintable())
        if text and len(self.world.name) < MAX_NAME:
            self.world.name = (self.world.name + text)[:MAX_NAME]
            self.dirty = True

    # ---------------------------------------------------------------- events --
    def event(self, ev):
        """Handle one event. Returns "back" when leaving the editor."""
        if self.editing_name and self._name_event(ev):
            return None
        if self.listing is not None:
            return self._list_event(ev)
        if ev.type == pygame.KEYDOWN:
            return self._key(ev)
        if ev.type == pygame.MOUSEBUTTONDOWN:
            return self._mouse_down(ev)
        if ev.type == pygame.MOUSEBUTTONUP:
            if ev.button in (1, 3):
                self._end_stroke()
            if ev.button == 2:
                self.panning = False
            if ev.button == 1:
                self.dragging_mini = False
        elif ev.type == pygame.MOUSEMOTION:
            if self.panning:
                self.camera.pan(*ev.rel)
            elif self.dragging_mini:
                self._mini_jump(ev.pos)
            elif self.stroke:
                tile = self._tile_at(ev.pos)
                if tile:
                    self._paint_to(tile)
        elif ev.type == pygame.MOUSEWHEEL:
            self._wheel(ev)
        return None

    def _list_event(self, ev):
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            self.close_list()
        elif ev.type == pygame.MOUSEWHEEL:
            top = self.list_top - ev.y
            self.list_top = int(clamp(top, 0, max(0, len(self.listing) - LIST_ROWS)))
            self._relayout_list()
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for b in self.list_buttons:
                if b.rect.collidepoint(ev.pos):
                    if b.key is None:
                        self.close_list()
                    else:
                        self.open_map(b.key)
                    return None
            if not self.list_rect.collidepoint(ev.pos):
                self.close_list()
        return None

    def _key(self, ev):
        ctrl = ev.mod & pygame.KMOD_CTRL
        if ev.key == pygame.K_ESCAPE:
            if self.stroke:
                return None
            return "back" if self._confirm("back") else None
        if ctrl and ev.key == pygame.K_s:
            self.save()
        elif ctrl and ev.key == pygame.K_z:
            if not self.stroke:
                self.undo()
        elif ev.key in TOOL_KEYS:
            self.tool = TOOL_KEYS.index(ev.key)
        elif ev.key in (pygame.K_DELETE, pygame.K_BACKSPACE):
            self.tool = len(TOOLS) - 1
        elif ev.key in (pygame.K_KP_PLUS, pygame.K_PAGEUP):
            self.brush = min(len(BRUSHES) - 1, self.brush + 1)
        elif ev.key in (pygame.K_KP_MINUS, pygame.K_PAGEDOWN):
            self.brush = max(0, self.brush - 1)
        return None

    def _wheel(self, ev):
        mx, my = pygame.mouse.get_pos()
        if not self.layout.view.collidepoint(mx, my) or self.stroke:
            return
        if pygame.key.get_mods() & pygame.KMOD_CTRL:
            if self.hover_node is not None:
                self._change_amount(self.hover_node, 1 if ev.y > 0 else -1)
            return
        self.camera.set_zoom(self.camera.zoom_index + (1 if ev.y > 0 else -1),
                             (mx, my))

    def _mouse_down(self, ev):
        pos = ev.pos
        if ev.button == 2 and self.layout.view.collidepoint(pos):
            self.panning = True
            return None
        if ev.button not in (1, 3):
            return None
        if self.panel.collidepoint(pos):
            return self._panel_click(pos, ev.button) if ev.button == 1 else None
        if ev.button == 1 and self.name_rect.collidepoint(pos):
            self.start_name()
            return None
        tile = self._tile_at(pos)
        if tile:
            self._start_stroke(ev.button, tile)
        return None

    def _panel_click(self, pos, button):
        if self.mini_rect.collidepoint(pos):
            self.dragging_mini = True
            self._mini_jump(pos)
            return None
        for i, rect in enumerate(self.tool_rects):
            if rect.collidepoint(pos):
                self.tool = i
                return None
        for key, b in self.buttons.items():
            if not (b.rect.collidepoint(pos) and b.enabled):
                continue
            if key == "brush":
                self.brush = (self.brush + 1) % len(BRUSHES)
            elif key == "size":
                self.new_size = (self.new_size + 1) % len(MAP_SIZES)
            elif key == "new":
                self.new_map(False)
            elif key == "random":
                self.new_map(True)
            elif key == "open":
                self.open_list()
            elif key == "save":
                self.save()
            elif key == "undo":
                self.undo()
            elif key == "back":
                return "back" if self._confirm("back") else None
        return None

    def _mini_jump(self, pos):
        r = self.mini_rect
        fx = clamp((pos[0] - r.x) / float(r.w), 0.0, 1.0)
        fy = clamp((pos[1] - r.y) / float(r.h), 0.0, 1.0)
        self.camera.center_on(fx * self.world.world_w, fy * self.world.world_h)

    # ------------------------------------------------------------------ draw --
    def draw(self, screen):
        # The editor shows both start baskets: keep the default team palette,
        # whatever clan the menu was previewing.
        sprites.set_team_colors(TEAM_COLORS)
        cam = self.camera
        rnd = self.renderer
        scene = rnd._get_scene(cam)
        A = sprites.ASSET_SCALE
        ox, oy = -cam.x * A, -cam.y * A
        rnd._draw_terrain(scene, ox, oy)
        rnd._draw_nodes(scene, ox, oy)
        self._draw_bases(scene, ox, oy)
        self._draw_brush(scene, ox, oy)
        view = self.layout.view
        if scene.get_size() == (view.w, view.h):
            screen.blit(scene, view.topleft)
        else:
            pygame.transform.scale(scene, (view.w, view.h),
                                   screen.subsurface(view))
        self._draw_hint(screen)
        self._draw_topbar(screen)
        self._draw_panel(screen)
        if self.listing is not None:
            self._draw_list(screen)

    def _draw_bases(self, surf, ox, oy):
        w = self.world
        TP = sprites.tile_px()
        bad = set(mapfile.problems(w)) & {"editor.problems.base_blocked",
                                          "editor.problems.bases_overlap"}
        font = self.fonts[2]
        for team, start in enumerate(w.start_tiles):
            left = (start[0] - 1) * TP + ox
            top = (start[1] - 1) * TP + oy
            surf.blit(sprites.building_sprite("basket", team, 3 * TP), (left, top))
            blocked = bad and any(
                not TERRAIN_WALKABLE[w.terrain_at(*t)] or t in w.node_at
                or not w.in_bounds(*t) for t in w.base_footprint(start))
            if blocked or "editor.problems.bases_overlap" in bad:
                color = C_BAD
            else:
                color = TEAM_COLORS[team]
            pygame.draw.rect(surf, color, (left, top, 3 * TP, 3 * TP),
                             max(2, TP // 10), border_radius=TP // 4)
            label = font.render(str(team + 1), True, C_TEXT)
            plate = pygame.Rect(0, 0, label.get_width() + TP // 3,
                                label.get_height())
            plate.midbottom = (left + 1.5 * TP, top)
            pygame.draw.rect(surf, mix(color, (0, 0, 0), 0.35), plate,
                             border_radius=TP // 5)
            surf.blit(label, label.get_rect(center=plate.center))

    def _draw_brush(self, surf, ox, oy):
        if self.hover_tile is None or self.listing is not None:
            return
        TP = sprites.tile_px()
        kind, value = TOOLS[self.tool]
        if kind == "base":
            tx = int(clamp(self.hover_tile[0], 1, self.world.w - 2))
            ty = int(clamp(self.hover_tile[1], 1, self.world.h - 2))
            ghost = sprites.building_sprite("basket", value, 3 * TP).copy()
            ghost.set_alpha(130)
            surf.blit(ghost, ((tx - 1) * TP + ox, (ty - 1) * TP + oy))
            return
        tiles = ([self.hover_tile] if kind == "node"
                 else self._brush_tiles(self.hover_tile))
        color = C_BAD if kind == "erase" else (250, 250, 240)
        overlay = pygame.Surface((TP, TP), pygame.SRCALPHA)
        overlay.fill((color[0], color[1], color[2], 50))
        pygame.draw.rect(overlay, (color[0], color[1], color[2], 170),
                         overlay.get_rect(), max(1, TP // 16))
        for (tx, ty) in tiles:
            surf.blit(overlay, (tx * TP + ox, ty * TP + oy))

    def _draw_topbar(self, screen):
        L = self.layout
        u = L.u
        f_tiny, f_small = self.fonts[0], self.fonts[1]
        bar = pygame.Rect(0, 0, L.w, L.topbar)
        pygame.draw.rect(screen, C_PANEL, bar)
        pygame.draw.line(screen, C_BORDER, (0, bar.bottom - 1),
                         (L.w, bar.bottom - 1))

        # The name field.
        r = self.name_rect
        pygame.draw.rect(screen, C_PANEL_DARK if self.editing_name
                         else C_PANEL_LIGHT, r, border_radius=u(5))
        pygame.draw.rect(screen, C_GOLD if self.editing_name else C_BORDER,
                         r, 1, border_radius=u(5))
        name = self.world.name
        caret = "|" if self.editing_name and int(self.elapsed * 2) % 2 == 0 else ""
        text = (i18n.t("editor.name", name=name + caret) if name or caret
                else i18n.t("editor.name_hint"))
        img = f_small.render(text, True, C_TEXT if name else C_TEXT_DIM)
        old = screen.get_clip()
        screen.set_clip(r.inflate(-u(8), 0))
        screen.blit(img, (r.x + u(8), r.centery - img.get_height() // 2))
        screen.set_clip(old)

        # Size and save state, then the node under the cursor.
        info = i18n.t("editor.info", size=i18n.map_size_name(self.world.w),
                      w=self.world.w, h=self.world.h)
        if self.dirty:
            info += i18n.t("editor.unsaved")
        img = f_tiny.render(info, True, C_GOLD if self.dirty else C_TEXT_DIM)
        screen.blit(img, (r.right + u(12), r.centery - img.get_height() // 2))
        x = r.right + u(24) + img.get_width()
        if self.hover_node is not None:
            n = self.hover_node
            img = f_small.render(i18n.t(
                "editor.node_info", resource=i18n.resource_name(n.kind),
                amount=int(n.max_amount), default=RES_AMOUNT[n.kind]),
                True, C_TEXT)
            screen.set_clip(pygame.Rect(x, 0, L.w - x - u(10), L.topbar))
            screen.blit(img, (max(x, L.w - u(10) - img.get_width()),
                              r.centery - img.get_height() // 2))
            screen.set_clip(old)

    def _draw_hint(self, screen):
        """The strip at the foot of the map: the last message, or the
        reminder of the mouse and keyboard controls."""
        L = self.layout
        u = L.u
        if self.status_t > 0.0:
            text, color = self.status, self.status_color
        else:
            text, color = i18n.t("editor.hint"), C_TEXT_DIM
        font = self.fonts[0]
        lines = [font.render(line, True, color)
                 for line in _wrap_pixels(text, font, L.w - u(20))]
        height = sum(img.get_height() for img in lines) + u(8)
        strip = pygame.Surface((L.w, height), pygame.SRCALPHA)
        strip.fill((16, 15, 20, 170))
        y = L.view.bottom - height
        screen.blit(strip, (0, y))
        y += u(4)
        for img in lines:
            screen.blit(img, (L.w // 2 - img.get_width() // 2, y))
            y += img.get_height()

    def _tool_icon(self, index, px):
        kind, value = TOOLS[index]
        if kind == "terrain":
            return pygame.transform.smoothscale(
                sprites.tile_sprite(value, 0), (px, px))
        if kind == "node":
            return sprites.resource_icon(value, px)
        if kind == "base":
            return sprites.building_icon("basket", value, px)
        surf = pygame.Surface((px, px), pygame.SRCALPHA)
        k = px // 4
        pygame.draw.line(surf, C_BAD, (k, k), (px - k, px - k), max(2, px // 9))
        pygame.draw.line(surf, C_BAD, (px - k, k), (k, px - k), max(2, px // 9))
        return surf

    def tool_label(self, index):
        kind, value = TOOLS[index]
        if kind == "terrain":
            return i18n.t("editor.terrains." + TERRAIN_KEYS[value])
        if kind == "node":
            return i18n.resource_name(value)
        if kind == "base":
            return i18n.t("editor.base", team=value + 1)
        return i18n.t("editor.erase")

    def _draw_panel(self, screen):
        L = self.layout
        u = L.u
        f_tiny, f_small = self.fonts[0], self.fonts[1]
        pygame.draw.rect(screen, C_PANEL, self.panel)
        pygame.draw.line(screen, C_BORDER, self.panel.topleft,
                         self.panel.topright, 2)

        # Minimap, with the bases and the camera frame.
        r = self.mini_rect
        if self._mini_dirty and self.elapsed - self._mini_t >= MINIMAP_REFRESH:
            self._mini = minimap_surface(self.world)
            self._mini_t = self.elapsed
            self._mini_dirty = False
        pygame.draw.rect(screen, C_PANEL_DARK, r.inflate(u(8), u(8)),
                         border_radius=u(6))
        screen.blit(pygame.transform.scale(self._mini, r.size), r.topleft)
        sx = r.w / float(self.world.world_w)
        sy = r.h / float(self.world.world_h)
        for team, (bx, by) in enumerate(self.world.start_tiles):
            c = (r.x + (bx + 0.5) * TILE * sx, r.y + (by + 0.5) * TILE * sy)
            pygame.draw.circle(screen, TEAM_COLORS[team], c, max(3, u(4)))
            pygame.draw.circle(screen, (20, 20, 24), c, max(3, u(4)), 1)
        cam = self.camera
        pygame.draw.rect(screen, (240, 240, 230),
                         (r.x + cam.x * sx, r.y + cam.y * sy,
                          cam.vw * sx, cam.vh * sy), 1)

        # Tools.
        mouse = pygame.mouse.get_pos()
        icon_px = u(34)
        for i, rect in enumerate(self.tool_rects):
            active = i == self.tool
            hov = rect.collidepoint(mouse)
            bg = C_PANEL_LIGHT if not active else mix(C_PANEL_LIGHT, C_GOLD, 0.25)
            if hov:
                bg = mix(bg, (255, 255, 255), 0.15)
            pygame.draw.rect(screen, bg, rect, border_radius=u(6))
            pygame.draw.rect(screen, C_GOLD if active else C_BORDER, rect,
                             2 if active else 1, border_radius=u(6))
            icon = self._tool_icon(i, icon_px)
            screen.blit(icon, (rect.centerx - icon.get_width() // 2,
                               rect.y + u(4)))
            label = f_tiny.render(self.tool_label(i), True,
                                  C_TEXT if active else C_TEXT_DIM)
            if label.get_width() > rect.w - u(4):
                label = pygame.transform.smoothscale(
                    label, (rect.w - u(4), label.get_height()))
            screen.blit(label, (rect.centerx - label.get_width() // 2,
                                rect.bottom - label.get_height() - u(2)))
            if i < len(TOOL_KEYS):
                key = f_tiny.render(str((i + 1) % 10), True, C_TEXT_DIM)
                screen.blit(key, (rect.x + u(4), rect.y + u(2)))

        for key, b in self.buttons.items():
            b.draw(screen, f_small, mouse, u(6))

    def _draw_list(self, screen):
        L = self.layout
        u = L.u
        shade = pygame.Surface((L.w, L.h), pygame.SRCALPHA)
        shade.fill((10, 10, 16, 150))
        screen.blit(shade, (0, 0))
        pygame.draw.rect(screen, C_PANEL, self.list_rect, border_radius=u(10))
        pygame.draw.rect(screen, C_BORDER, self.list_rect, 2, border_radius=u(10))
        title = self.fonts[3].render(i18n.t("editor.open_title"), True, C_TEXT)
        screen.blit(title, (self.list_rect.centerx - title.get_width() // 2,
                            self.list_rect.y + u(14)))
        mouse = pygame.mouse.get_pos()
        for b in self.list_buttons:
            b.draw(screen, self.fonts[1], mouse, u(6))
        if len(self.listing) > LIST_ROWS:
            more = self.fonts[0].render(
                i18n.t("editor.list_scroll", first=self.list_top + 1,
                       last=min(len(self.listing), self.list_top + LIST_ROWS),
                       count=len(self.listing)), True, C_TEXT_DIM)
            screen.blit(more, (self.list_rect.centerx - more.get_width() // 2,
                               self.list_rect.bottom - more.get_height() - u(6)))

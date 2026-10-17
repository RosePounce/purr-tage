# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Map sizes, map files and the map editor (no window: SDL in "dummy" mode)."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

pygame.init()
pygame.display.set_mode((64, 64))

from purrtage import mapfile                                           # noqa: E402
from purrtage.app import App                                           # noqa: E402
from purrtage.editor import TOOLS, MapEditor                           # noqa: E402
from purrtage.fonts import load_fonts                                  # noqa: E402
from purrtage.game import Game                                         # noqa: E402
from purrtage.layout import Layout                                     # noqa: E402
from purrtage.settings import (MAP_SIZES, R_KIBBLE, R_WOOL, TILE,      # noqa: E402
                             T_GRASS, T_SAND, T_WATER)
from purrtage.world import World                                       # noqa: E402


def node_rows(world):
    return [(n.kind, n.tx, n.ty, n.max_amount, n.variant) for n in world.nodes]


class TestMapSizes(unittest.TestCase):
    def test_every_size_gives_a_playable_map(self):
        for side in MAP_SIZES:
            w = World(seed=9, size=side)
            self.assertEqual((w.w, w.h), (side, side))
            self.assertEqual(len(w.terrain), side)
            self.assertEqual(len(w.terrain[0]), side)
            self.assertTrue(w.bases_connected(), "bases cut off at %d" % side)
            self.assertEqual(mapfile.problems(w), [])

    def test_bigger_maps_hold_more_resources(self):
        small, big = World(seed=4, size=64), World(seed=4, size=160)
        self.assertGreater(len(big.nodes), len(small.nodes))

    def test_a_game_runs_on_a_small_and_a_big_map(self):
        for side in (64, 160):
            g = Game(World(seed=3, size=side), fog_enabled=True)
            self.assertEqual(len(g.fog.explored), side)
            self.assertEqual(g.camera.world_w, side * TILE)
            for _ in range(60):
                g.update(1 / 30.0)
            for u in g.units:
                self.assertLess(u.x, side * TILE)
                self.assertLess(u.y, side * TILE)

    def test_the_camera_stops_at_the_edge_of_a_small_map(self):
        g = Game(World(seed=3, size=64), fog_enabled=False)
        g.camera.center_on(10 ** 6, 10 ** 6)
        self.assertLessEqual(g.camera.x + g.camera.vw, 64 * TILE + 1)

    def test_a_blank_map_is_all_grass_with_two_bases(self):
        w = World.blank(64)
        self.assertTrue(all(t == T_GRASS for row in w.terrain for t in row))
        self.assertEqual(len(w.start_tiles), 2)
        self.assertEqual(w.nodes, [])
        self.assertEqual(mapfile.problems(w), [])


class TestMapFile(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        patcher = mock.patch.object(mapfile, "maps_dir",
                                    return_value=self.folder)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_round_trip_keeps_everything(self):
        w = World(seed=42, size=128)
        w.name = "Île aux chats"
        w.nodes[0].max_amount = 999
        back = mapfile.decode(mapfile.encode(w))
        self.assertEqual(back.name, w.name)
        self.assertEqual(back.terrain, w.terrain)
        self.assertEqual(back.start_tiles, w.start_tiles)
        self.assertEqual(node_rows(back), node_rows(w))
        self.assertEqual(back.blocked, w.blocked)
        self.assertEqual(back.decor, w.decor)

    def test_the_text_form_survives_json(self):
        import json
        w = World.blank(64, seed=5)
        w.name = "Duel"
        w.put_node(R_WOOL, 30, 30, amount=500)
        msg = json.loads(json.dumps({"map": mapfile.to_text(w)}))
        back = mapfile.from_text(msg["map"])
        self.assertEqual(node_rows(back), node_rows(w))

    def test_damaged_files_are_refused(self):
        good = mapfile.encode(World.blank(64))
        for bad in (b"", b"hello", good[:20], good[:8] + b"\x00" * 30,
                    b"PURRMAP\x09" + good[8:]):
            with self.assertRaises(mapfile.MapError):
                mapfile.decode(bad)

    def test_save_list_and_load(self):
        w = World.blank(96)
        w.name = "Les deux rives"
        path = mapfile.save(w)
        self.assertEqual(os.path.dirname(path), self.folder)
        self.assertTrue(path.endswith(mapfile.EXTENSION))
        with open(os.path.join(self.folder, "junk" + mapfile.EXTENSION),
                  "wb") as f:
            f.write(b"not a map")
        listed = mapfile.list_maps()
        self.assertEqual(listed, [(path, "Les deux rives", 96)])
        self.assertEqual(mapfile.load(path).terrain, w.terrain)

    def test_file_names_stay_safe(self):
        self.assertEqual(mapfile.file_name("../../etc/passwd"),
                         "etc_passwd" + mapfile.EXTENSION)
        self.assertEqual(mapfile.file_name("   "), "map" + mapfile.EXTENSION)

    def test_problems_are_reported(self):
        w = World.blank(64)
        bx, by = w.start_tiles[0]
        w.terrain[by][bx] = T_WATER
        self.assertIn("editor.problems.base_blocked", mapfile.problems(w))

        w = World.blank(64)
        w.start_tiles[1] = (w.start_tiles[0][0] + 1, w.start_tiles[0][1])
        self.assertIn("editor.problems.bases_overlap", mapfile.problems(w))

        w = World.blank(64)
        for row in w.terrain:            # a river from top to bottom
            row[32] = T_WATER
        w.finish()
        self.assertEqual(mapfile.problems(w), ["editor.problems.not_connected"])


class TestNetworkStart(unittest.TestCase):
    def test_a_generated_map_grows_again_from_seed_and_size(self):
        msg = {"type": "start", "seed": 77, "size": 128}
        a = App.world_from_start(msg)
        self.assertEqual(a.w, 128)
        self.assertEqual(a.terrain, World(77, 128).terrain)

    def test_a_drawn_map_travels_whole(self):
        w = World.blank(64, seed=3)
        w.name = "Maison"
        w.put_node(R_KIBBLE, 20, 20)
        back = App.world_from_start({"seed": 1, "size": 96,
                                     "map": mapfile.to_text(w)})
        self.assertEqual(back.w, 64)
        self.assertEqual(node_rows(back), node_rows(w))

    def test_an_old_start_message_means_the_default_size(self):
        self.assertEqual(App.world_from_start({"seed": 5}).w, 96)

    def test_both_machines_simulate_the_same_drawn_map(self):
        host = World(seed=12, size=64)
        host.name = "Partagée"
        host.terrain[20][20] = T_SAND
        host.put_node(R_KIBBLE, 40, 30, amount=600)
        host.finish()
        client = App.world_from_start({"seed": 0,
                                       "map": mapfile.to_text(host)})
        games = [Game(w, fog_enabled=False, local_team=team, use_ai=False)
                 for team, w in ((0, host), (1, client))]
        for _ in range(200):
            for g in games:
                g.tick()
        self.assertEqual(games[0].checksum(), games[1].checksum())


class TestEditor(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        patcher = mock.patch.object(mapfile, "maps_dir",
                                    return_value=self.folder)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.folder, True)
        layout = Layout(1280, 760)
        self.ed = MapEditor(load_fonts(layout.scale), layout)
        self.ed.update(0.1)

    def tool(self, kind, value):
        self.ed.tool = TOOLS.index((kind, value))

    def paint(self, tile, button=1, to=None):
        self.ed._start_stroke(button, tile)
        if to:
            self.ed._paint_to(to)
        self.ed._end_stroke()

    def test_terrain_brush_and_drag(self):
        self.tool("terrain", T_SAND)
        self.ed.brush = 0
        self.paint((40, 40), to=(46, 40))
        w = self.ed.world
        self.assertTrue(all(w.terrain[40][x] == T_SAND for x in range(40, 47)))
        self.assertTrue(self.ed.dirty)

    def test_water_drowns_the_nodes_and_blocks(self):
        w = self.ed.world
        w.put_node(R_WOOL, 40, 40)
        self.tool("terrain", T_WATER)
        self.paint((40, 40))
        self.assertNotIn((40, 40), self.ed.world.node_at)
        self.assertTrue(self.ed.world.is_blocked(40, 40))

    def test_resources_place_change_and_erase(self):
        self.tool("node", R_KIBBLE)
        self.paint((40, 40))
        node = self.ed.world.node_at[(40, 40)]
        self.assertEqual(node.kind, R_KIBBLE)
        self.ed._change_amount(node, +1)
        self.assertGreater(node.max_amount, 340)
        self.tool("node", R_WOOL)
        self.paint((40, 40))
        self.assertEqual(self.ed.world.node_at[(40, 40)].kind, R_WOOL)
        self.paint((40, 40), button=3)
        self.assertNotIn((40, 40), self.ed.world.node_at)

    def test_no_resource_on_water_or_on_a_base(self):
        w = self.ed.world
        w.terrain[30][30] = T_WATER
        self.tool("node", R_KIBBLE)
        self.paint((30, 30))
        self.paint(w.start_tiles[0])
        self.assertEqual(self.ed.world.nodes, [])

    def test_moving_a_base_clears_its_footprint(self):
        w = self.ed.world
        w.put_node(R_WOOL, 51, 50)
        self.tool("base", 1)
        self.paint((50, 50))
        self.assertEqual(w.start_tiles[1], (50, 50))
        self.assertNotIn((51, 50), w.node_at)

    def test_undo_restores_the_map(self):
        before = [bytearray(r) for r in self.ed.world.terrain]
        self.tool("terrain", T_WATER)
        self.paint((40, 40))
        self.ed.undo()
        self.assertEqual(self.ed.world.terrain, before)

    def test_save_refuses_an_unplayable_map_then_accepts_a_good_one(self):
        w = self.ed.world
        for row in w.terrain:
            row[48] = T_WATER
        w.finish()
        self.assertFalse(self.ed.save())
        self.assertEqual(os.listdir(self.folder), [])
        self.ed.undo_stack = []
        for row in w.terrain:
            row[48] = T_GRASS
        w.finish()
        w.name = "Prairie"
        self.assertTrue(self.ed.save())
        self.assertFalse(self.ed.dirty)
        self.assertEqual(mapfile.list_maps()[0][1], "Prairie")

    def test_a_name_already_taken_is_refused(self):
        other = World.blank(64)
        other.name = "Prairie"
        mapfile.save(other)
        self.ed.world.name = "Prairie"
        self.assertFalse(self.ed.save())

    def test_leaving_with_changes_asks_twice(self):
        self.tool("terrain", T_SAND)
        self.paint((40, 40))
        esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0,
                                 unicode="")
        self.assertIsNone(self.ed.event(esc))
        self.assertEqual(self.ed.event(esc), "back")

    def test_new_map_of_each_size(self):
        for i, side in enumerate(MAP_SIZES):
            self.ed.new_size = i
            self.ed.new_map(False)
            self.assertEqual(self.ed.world.w, side)
            self.assertEqual(self.ed.camera.world_w, side * TILE)

    def test_draws_at_every_resolution(self):
        for (w, h) in ((1280, 760), (1920, 1080), (2880, 1800)):
            layout = Layout(w, h)
            screen = pygame.Surface((w, h))
            self.ed.relayout(layout, load_fonts(layout.scale))
            self.ed.update(0.1)
            self.ed.draw(screen)
            panel_right = max(b.rect.right for b in self.ed.buttons.values())
            self.assertLessEqual(panel_right, w)
            tools_right = max(r.right for r in self.ed.tool_rects)
            self.assertLess(tools_right,
                            min(b.rect.left for b in self.ed.buttons.values()))


if __name__ == "__main__":
    unittest.main()

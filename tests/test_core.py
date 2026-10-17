# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Engine tests (no window: SDL in "dummy" mode)."""

import math
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

pygame.init()
pygame.display.set_mode((64, 64))

from purrtage import entities as E                                    # noqa: E402
from purrtage.fonts import font_backend, load_fonts                   # noqa: E402
from purrtage.camera import Camera                                     # noqa: E402
from purrtage.layout import Layout, asset_scale_for, ui_scale_for      # noqa: E402
from purrtage import bugreport, bugsend                               # noqa: E402
from purrtage.game import Game, ST_DEFEAT, ST_VICTORY                 # noqa: E402
from purrtage.pathfinding import astar, line_clear, nearest_open      # noqa: E402
from purrtage.player import Player                                    # noqa: E402
from purrtage.settings import (DEFAULT_MAP_SIZE, R_KIBBLE, R_WOOL,   # noqa: E402
                             TILE, UNITS)
from purrtage.world import World                                      # noqa: E402


def empty_grid():
    return [bytearray(DEFAULT_MAP_SIZE) for _ in range(DEFAULT_MAP_SIZE)]


def make_game(seed=2024, fog=False):
    return Game(World(seed=seed), difficulty="tomcat", fog_enabled=fog)


def run(game, seconds, dt=1 / 30.0):
    for _ in range(int(seconds / dt)):
        game.update(dt)


class TestFonts(unittest.TestCase):
    """The game must survive an install where `pygame.font` is broken."""

    def setUp(self):
        import sys
        self.saved = {name: sys.modules.get(name)
                      for name in ("pygame.font", "pygame.ftfont")}

    def tearDown(self):
        import sys
        for name, module in self.saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    @staticmethod
    def _broken():
        class Broken(object):
            def get_init(self):
                raise NotImplementedError("font module not available")

            def init(self):
                raise NotImplementedError("font module not available")

            def Font(self, *args):
                raise NotImplementedError("font module not available")
        return Broken()

    def test_loads_five_sizes(self):
        fonts = load_fonts()
        self.assertEqual(len(fonts), 5)
        heights = [f.get_height() for f in fonts]
        self.assertEqual(heights, sorted(heights))

    def test_falls_back_to_ftfont(self):
        import sys
        sys.modules["pygame.font"] = self._broken()
        self.assertEqual(font_backend().__name__, "pygame.ftfont")
        img = load_fonts()[2].render(u"Chaton éàç", True, (255, 255, 255))
        self.assertGreater(img.get_width(), 0)

    def test_explains_how_to_fix_when_nothing_works(self):
        import sys
        sys.modules["pygame.font"] = self._broken()
        sys.modules["pygame.ftfont"] = self._broken()
        with self.assertRaises(RuntimeError) as ctx:
            font_backend()
        message = str(ctx.exception)
        self.assertIn("pip install -r requirements.txt", message)
        self.assertIn("pygame-ce", message)


class TestPaths(unittest.TestCase):
    """An installed game does not write into its install folder."""

    def test_sources_write_next_to_the_project(self):
        from purrtage import paths
        self.assertFalse(paths.is_frozen())
        self.assertEqual(paths.data_dir(), paths.install_dir())

    def test_installed_falls_back_to_the_user_folder(self):
        from purrtage import paths
        home = os.path.expanduser("~")
        folder = paths._system_data_dir()
        self.assertTrue(os.path.isabs(folder))
        self.assertTrue(folder.startswith(home)
                        or folder.startswith(os.environ.get("APPDATA", "\0")),
                        "the data does not land in the user folder: %s"
                        % folder)

    def test_bug_reports_live_under_the_data_folder(self):
        from purrtage import bugreport, paths
        folder = bugreport.report_dir()
        self.assertTrue(os.path.isabs(folder))
        self.assertTrue(folder.startswith(paths.data_dir()))
        self.assertTrue(os.path.isdir(folder))


class TestMenuLayout(unittest.TestCase):
    """The menu had grown to the point of covering the breed thumbnails."""

    @staticmethod
    def _menu(w, h):
        from purrtage import screens
        from purrtage.fonts import load_fonts
        layout = Layout(w, h)
        return screens.MainMenu(load_fonts(layout.scale), layout), layout

    def test_buttons_clear_the_unit_portraits(self):
        for (w, h) in ((1280, 760), (1600, 900), (1920, 1080), (2880, 1800)):
            menu, layout = self._menu(w, h)
            portraits_bottom = layout.u(120) + layout.u(202) + layout.u(18)
            self.assertGreater(menu.buttons["play"].rect.top, portraits_bottom,
                               "the menu covers the thumbnails at %dx%d" % (w, h))

    def test_buttons_fit_on_screen(self):
        for (w, h) in ((1280, 760), (1600, 900), (1920, 1080), (2880, 1800)):
            menu, layout = self._menu(w, h)
            lowest = max(b.rect.bottom for b in menu.buttons.values())
            self.assertLess(lowest, h - layout.u(55),
                            "the menu overflows at %dx%d" % (w, h))

    def test_settings_moved_to_the_options_screen(self):
        from purrtage import screens
        from purrtage.fonts import load_fonts
        layout = Layout(1280, 760)
        fonts = load_fonts(layout.scale)
        menu = screens.MainMenu(fonts, layout)
        self.assertEqual(set(menu.buttons),
                         {"play", "map", "lan", "options", "editor", "help",
                          "quit"})
        options = screens.OptionsScreen(fonts, layout, menu)
        for key in ("diff", "res", "full", "fog", "sound", "edge", "back"):
            self.assertIn(key, options.buttons)

    def test_options_edit_the_values_the_game_starts_from(self):
        from purrtage import screens
        from purrtage.fonts import load_fonts
        layout = Layout(1280, 760)
        fonts = load_fonts(layout.scale)
        menu = screens.MainMenu(fonts, layout)
        options = screens.OptionsScreen(fonts, layout, menu)
        options.update(0.1)
        before = menu.diff_index
        options.click(options.buttons["diff"].rect.center)
        self.assertNotEqual(menu.diff_index, before)
        options.click(options.buttons["fog"].rect.center)
        self.assertFalse(menu.fog)
        self.assertEqual(options.click(options.buttons["back"].rect.center), "back")

    def test_cat_style_option_switches_the_sprites(self):
        """The options offer a switch between the new and the classic cats."""
        from purrtage import prefs, screens, sprites
        from purrtage.fonts import load_fonts
        layout = Layout(1280, 760)
        fonts = load_fonts(layout.scale)
        menu = screens.MainMenu(fonts, layout)
        options = screens.OptionsScreen(fonts, layout, menu)
        self.assertIn("cats", options.buttons)
        saved_style, saved_write = sprites.CLASSIC_CATS, prefs.write
        prefs.write = lambda *a, **k: True          # keep the test off the disk
        try:
            before = menu.classic_cats
            options.click(options.buttons["cats"].rect.center)
            self.assertNotEqual(menu.classic_cats, before)
            self.assertEqual(sprites.CLASSIC_CATS, menu.classic_cats)
        finally:
            prefs.write = saved_write
            sprites.set_cat_style(saved_style)


class TestGuide(unittest.TestCase):
    """The F2 page must tell the truth about recruitment.

    A tester believed a kitten turned into a tomcat as it grew up; the page
    corrects that idea, provided it does not get it wrong itself.
    """

    def test_every_unit_names_the_building_that_recruits_it(self):
        from purrtage.settings import BUILDINGS, UNITS
        for utype, spec in UNITS.items():
            home = spec.get("trained_at")
            self.assertIn(home, BUILDINGS,
                          "%s does not say where it is recruited" % utype)
            self.assertIn(utype, BUILDINGS[home].get("trains", ()),
                          "the %s does not recruit any %s" % (home, utype))

    def test_every_recruiting_building_is_reachable_from_a_unit(self):
        from purrtage.settings import BUILDINGS, UNITS
        for btype, spec in BUILDINGS.items():
            for utype in spec.get("trains", ()):
                self.assertEqual(UNITS[utype].get("trained_at"), btype)

    def test_no_text_still_says_the_building_shapes_a_cat(self):
        """"Forme : Matou" read like the shape of the thing."""
        from purrtage import i18n
        from purrtage.settings import BUILDINGS
        before = i18n.language()
        try:
            for code, _name in i18n.available():
                i18n.set_language(code)
                for btype in BUILDINGS:
                    self.assertNotIn("forme", i18n.building_desc(btype).lower(),
                                     "%s in %s" % (btype, code))
        finally:
            i18n.set_language(before)

    def test_the_page_draws_at_every_resolution(self):
        from purrtage import screens
        from purrtage.fonts import load_fonts
        for (w, h) in ((1280, 760), (1920, 1080), (2880, 1800)):
            layout = Layout(w, h)
            surface = pygame.Surface(layout.size)
            screens.draw_guide(surface, load_fonts(layout.scale), layout)

    def test_a_building_in_production_says_it_recruits(self):
        g = make_game()
        base = next(b for b in g.buildings
                    if b.player is g.human and b.btype == "basket")
        g.order_train(base, "kitten")
        label = base.status_label()
        self.assertIn("Recrute", label)
        self.assertIn("Chaton", label)


class TestLayout(unittest.TestCase):
    """The interface must follow the resolution, from 1280x760 to 2880x1800."""

    def test_scale_grows_with_height(self):
        scales = [ui_scale_for(h) for h in (760, 900, 1080, 1440, 1800)]
        self.assertEqual(scales, sorted(scales))
        self.assertEqual(ui_scale_for(760), 1.0)
        self.assertGreater(ui_scale_for(1800), 2.0)

    def test_asset_scale_uses_clean_steps(self):
        for h in (720, 760, 900, 1080, 1440, 1800, 2160):
            self.assertIn(asset_scale_for(h), (1.0, 1.5, 2.0))

    def test_panels_stay_inside_the_window(self):
        for (w, h) in ((1280, 760), (1600, 900), (1920, 1080), (2880, 1800)):
            L = Layout(w, h)
            self.assertEqual(L.view.w, w)
            self.assertGreater(L.view.h, 0)
            self.assertEqual(L.view.y, L.topbar)
            self.assertEqual(L.topbar + L.view.h + L.hud, h)

    def test_fonts_grow_with_the_window(self):
        small = [f.get_height() for f in load_fonts(Layout(1280, 760).scale)]
        large = [f.get_height() for f in load_fonts(Layout(2880, 1800).scale)]
        for a, b in zip(small, large):
            self.assertGreater(b, a)


class TestEdgeScroll(unittest.TestCase):
    """Edge scrolling must be switchable off (it is very sensitive)."""

    @staticmethod
    def _no_keys():
        # The SDL2 key constants are very large: a default dictionary stands
        # in for the sequence returned by pygame.key.get_pressed().
        import collections
        return collections.defaultdict(int)

    def _camera(self):
        return Camera(pygame.Rect(0, 36, 1280, 566))

    def test_edge_scroll_moves_the_camera(self):
        cam = self._camera()
        cam.center_on(1500, 1500)
        before = cam.x
        cam.update(0.2, self._no_keys(), (0, 300), True)
        self.assertLess(cam.x, before)

    def test_disabling_it_stops_the_movement(self):
        cam = self._camera()
        cam.edge_scroll = False
        cam.center_on(1500, 1500)
        before = (cam.x, cam.y)
        cam.update(0.2, self._no_keys(), (0, 300), True)
        self.assertEqual((cam.x, cam.y), before)

    def test_the_push_is_proportional_to_the_depth(self):
        """Brushing the edge must shift less than pressing against it."""
        far, near = self._camera(), self._camera()
        far.center_on(1500, 1500)
        near.center_on(1500, 1500)
        start = far.x
        far.update(0.2, self._no_keys(), (11, 300), True)     # barely in the band
        near.update(0.2, self._no_keys(), (0, 300), True)     # right on the edge
        self.assertLess(start - far.x, start - near.x)


class TestBugReport(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.saved_dir = bugreport.BUG_DIR
        bugreport.BUG_DIR = os.path.join(self.tmp, "saves", "bug")

    def tearDown(self):
        import shutil
        bugreport.BUG_DIR = self.saved_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    class _App(object):
        def __init__(self, game):
            self.layout = Layout(1280, 760)
            self.fullscreen = False
            self.paused = True
            self.game = game

    def test_writes_report_and_screenshot(self):
        g = make_game()
        app = self._App(g)
        shot = pygame.Surface((64, 48))
        shot.fill((10, 20, 30))
        txt, png = bugreport.save(app, "Les chatons restent bloqués.", shot, fps=57)
        self.assertTrue(os.path.isfile(txt))
        self.assertTrue(os.path.isfile(png))
        with open(txt, encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("Les chatons restent bloqués.", body)
        self.assertIn("Graine de carte", body)
        self.assertIn(str(g.world.seed), body)
        self.assertIn("pygame", body)
        self.assertIn(g.human.name, body)

    def test_works_without_a_game_and_without_a_screenshot(self):
        txt, png = bugreport.save(self._App(None), "", None)
        self.assertTrue(os.path.isfile(txt))
        self.assertIsNone(png)
        with open(txt, encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("aucune description", body)
        self.assertIn("menu principal", body)

    def test_creates_the_folder_on_demand(self):
        self.assertFalse(os.path.isdir(bugreport.BUG_DIR))
        path = bugreport.report_dir()
        self.assertTrue(os.path.isdir(path))
        self.assertTrue(os.path.isabs(path))



class _Relay(object):
    """A stand-in for the relay, on localhost: records what it receives."""

    def __init__(self, status=200):
        import http.server
        import threading
        relay = self
        self.status = status
        self.answer = '{"id": "20261016-101500-abc", "delivered": []}'
        self.bodies = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                size = int(self.headers.get("Content-Length", 0))
                relay.bodies.append(self.rfile.read(size))
                body = relay.answer.encode("utf-8")
                self.send_response(relay.status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d/report" % self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class TestBugSend(unittest.TestCase):
    """Reports leave for the relay, and wait in the outbox when they cannot."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.saved_dir = bugreport.BUG_DIR
        bugreport.BUG_DIR = os.path.join(self.tmp, "saves", "bug")
        bugsend.results()                       # drop leftovers

    def tearDown(self):
        import shutil
        bugreport.BUG_DIR = self.saved_dir
        os.environ.pop("PURRTAGE_REPORT_URL", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _ticket(self, shot=True, text="Le chaton est coincé."):
        image = None
        if shot:
            image = pygame.Surface((32, 24))
            image.fill((200, 60, 60))
        txt, png = bugreport.save(TestBugReport._App(None), text, image)
        return bugsend.queue_report(txt, png, text), txt, png

    def test_sending_is_off_without_an_address(self):
        os.environ.pop("PURRTAGE_REPORT_URL", None)
        self.assertFalse(bugsend.enabled())
        self.assertIsNone(bugsend.flush_async())

    def test_only_the_packaged_game_uses_the_built_in_relay(self):
        from unittest import mock
        from purrtage import paths
        os.environ.pop("PURRTAGE_REPORT_URL", None)
        self.assertEqual(bugsend.report_url(), "")          # from the sources
        with mock.patch.object(paths, "is_frozen", return_value=True):
            self.assertEqual(bugsend.report_url(), bugsend.BUG_REPORT_URL)
            os.environ["PURRTAGE_REPORT_URL"] = "http://localhost/report"
            self.assertEqual(bugsend.report_url(), "http://localhost/report")

    def test_https_has_certificates_to_check_against(self):
        self.assertGreater(bugsend.certificate_count(), 0)

    def test_a_sent_report_leaves_the_outbox_but_stays_on_disk(self):
        relay = _Relay()
        try:
            ticket, txt, png = self._ticket()
            self.assertEqual(bugsend.send(ticket, relay.url), bugsend.SENT)
        finally:
            relay.close()
        self.assertFalse(os.path.exists(ticket))
        self.assertTrue(os.path.isfile(txt) and os.path.isfile(png))
        body = relay.bodies[0]
        self.assertIn("Le chaton est coincé.".encode("utf-8"), body)
        self.assertIn(b'name="report"', body)
        self.assertIn(b'name="screenshot"', body)
        self.assertIn(b"\x89PNG", body)

    def test_without_a_screenshot_only_the_text_leaves(self):
        relay = _Relay()
        try:
            ticket, txt, png = self._ticket(shot=False)
            self.assertEqual(bugsend.send(ticket, relay.url), bugsend.SENT)
        finally:
            relay.close()
        self.assertIsNone(png)
        self.assertNotIn(b'name="screenshot"', relay.bodies[0])

    def test_no_connection_keeps_the_ticket(self):
        relay = _Relay()
        url = relay.url
        relay.close()                           # nobody listens any more
        ticket, _, _ = self._ticket()
        self.assertEqual(bugsend.send(ticket, url), bugsend.QUEUED)
        self.assertEqual(bugsend.pending(), [ticket])

    def test_a_refusal_drops_the_ticket_but_a_busy_relay_does_not(self):
        relay = _Relay(status=400)
        try:
            refused, _, _ = self._ticket()
            self.assertEqual(bugsend.send(refused, relay.url), bugsend.REJECTED)
            self.assertFalse(os.path.exists(refused))
            relay.status = 429
            busy, _, _ = self._ticket(text="Encore.")
            self.assertEqual(bugsend.send(busy, relay.url), bugsend.QUEUED)
            self.assertTrue(os.path.exists(busy))
        finally:
            relay.close()

    def test_a_200_from_something_else_is_not_a_delivery(self):
        """Report of 2026-10-16: the address lacked /report, the relay's
        home page answered 200, and the game dropped the report."""
        relay = _Relay()
        relay.answer = "Purr-tage bug report relay"
        try:
            ticket, _, _ = self._ticket()
            self.assertEqual(bugsend.send(ticket, relay.url), bugsend.QUEUED)
        finally:
            relay.close()
        self.assertTrue(os.path.exists(ticket))
        self.assertIn("is not the relay", self._log())

    def _log(self):
        path = os.path.join(bugreport.report_dir(), bugsend.LOG_NAME)
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_every_attempt_is_logged(self):
        relay = _Relay(status=400)
        try:
            refused, _, _ = self._ticket()
            bugsend.send(refused, relay.url)
            relay.status = 200
            sent, _, _ = self._ticket(text="Encore.")
            bugsend.send(sent, relay.url)
            url = relay.url
        finally:
            relay.close()
        down, _, _ = self._ticket(text="Toujours.")
        bugsend.send(down, url)
        log = self._log()
        self.assertIn("refused by %s, HTTP 400" % url, log)
        self.assertIn("sent to %s, HTTP 200" % url, log)
        self.assertIn("unreachable", log)
        self.assertNotIn("Le chaton est coincé.", log)   # no player's words

    def test_the_outbox_is_flushed_in_the_background(self):
        relay = _Relay(status=503)
        try:
            os.environ["PURRTAGE_REPORT_URL"] = relay.url
            ticket, _, _ = self._ticket()
            bugsend.flush_async().join(10)      # the relay is down
            self.assertEqual(bugsend.results(), [(ticket, bugsend.QUEUED)])
            relay.status = 200                  # next launch: it is back
            bugsend.flush_async().join(10)
            self.assertEqual(bugsend.results(), [(ticket, bugsend.SENT)])
            self.assertEqual(bugsend.pending(), [])
        finally:
            relay.close()


class TestDeterminism(unittest.TestCase):
    """The basis of networked play: same orders, hence exactly the same game.

    Lockstep only transmits the orders; if the two machines do not compute the
    same result down to the bit, the game diverges silently.
    """

    @staticmethod
    def _play(ticks):
        import random as _random
        from purrtage.ai import CatAI
        g = Game(World(seed=2024), difficulty="tomcat", fog_enabled=True)
        mirror = CatAI(g, g.human, "tomcat")
        g.human.is_ai = True
        for t in range(ticks):
            if t == 30:
                base = g.home_base_pos(g.human)
                node = g.world.nearest_node(base[0], base[1], R_WOOL, 20)
                for u in [x for x in g.units if x.player is g.human][:2]:
                    u.order_gather(g, node)
            if t == 120:
                base = g.home_base_pos(g.human)
                workers = [x for x in g.units
                           if x.player is g.human and x.utype == "kitten"][:2]
                g.selection = list(workers)
                g.build_mode = "shed"
                g.try_place(base[0] + 7 * TILE, base[1])
            g.tick()
            mirror.update(1 / 30.0)
        return g

    def test_two_runs_match_bit_for_bit(self):
        import random as _random
        _random.seed(1)
        [_random.random() for _ in range(500)]      # deliberate noise
        a = self._play(600)
        _random.seed(99)
        [_random.random() for _ in range(321)]
        b = self._play(600)
        self.assertEqual(a.checksum(), b.checksum())
        self.assertEqual(a.tick_no, b.tick_no)
        self.assertEqual(len(a.units), len(b.units))

    def test_entity_ids_restart_with_each_game(self):
        """Otherwise a machine that already played would hand out other ids."""
        def ids(game):
            return [e.eid for e in list(game.buildings) + list(game.units)]
        first, second = ids(make_game()), ids(make_game())
        self.assertEqual(first, second)
        self.assertEqual(min(first), 1)       # the counter really restarts at zero

    def test_the_clock_advances_in_fixed_steps(self):
        from purrtage.settings import TICK_DT
        g = make_game()
        self.assertEqual(g.update(TICK_DT * 0.4), 0)      # too short: nothing
        self.assertEqual(g.tick_no, 0)
        self.assertEqual(g.update(TICK_DT * 0.7), 1)      # the remainder tops it up
        self.assertEqual(g.update(TICK_DT * 2), 2)
        self.assertAlmostEqual(g.elapsed, TICK_DT * 3, places=6)

    def test_simulation_uses_no_global_randomness(self):
        """The remaining randomness must only touch the animated decor."""
        import random as _random
        g = make_game()
        _random.seed(4242)
        for _ in range(120):
            g.tick()
        first = g.checksum()
        g2 = make_game()
        _random.seed(7)
        for _ in range(120):
            g2.tick()
        self.assertEqual(first, g2.checksum())


class TestPathfinding(unittest.TestCase):
    def test_straight_line(self):
        self.assertEqual(astar(empty_grid(), (2, 2), (9, 2)), [(9, 2)])

    def test_goes_around_wall(self):
        grid = empty_grid()
        for y in range(0, 20):
            grid[y][6] = 1
        path = astar(grid, (2, 2), (10, 2))
        self.assertIsNotNone(path)
        self.assertEqual(path[-1], (10, 2))
        for (x, y) in path:
            self.assertEqual(grid[y][x], 0)

    def test_blocked_goal_falls_back_to_neighbour(self):
        grid = empty_grid()
        grid[5][5] = 1
        path = astar(grid, (1, 1), (5, 5))
        self.assertIsNotNone(path)
        self.assertNotEqual(path[-1], (5, 5))

    def test_nearest_open(self):
        grid = empty_grid()
        grid[4][4] = 1
        self.assertEqual(nearest_open(grid, (7, 7)), (7, 7))
        self.assertNotEqual(nearest_open(grid, (4, 4)), (4, 4))

    def test_line_clear(self):
        grid = empty_grid()
        self.assertTrue(line_clear(grid, (0, 0), (10, 10)))
        grid[5][5] = 1
        self.assertFalse(line_clear(grid, (0, 0), (10, 10)))


class TestWorld(unittest.TestCase):
    def test_reproducible_and_connected(self):
        a, b = World(seed=5), World(seed=5)
        self.assertEqual(a.terrain[10][10], b.terrain[10][10])
        self.assertEqual(len(a.nodes), len(b.nodes))
        self.assertTrue(a._reachable(*a.start_tiles))

    def test_bases_get_the_same_starting_resources(self):
        w = World(seed=11)
        counts = []
        for (bx, by) in w.start_tiles:
            near = [n for n in w.nodes
                    if abs(n.tx - bx) <= 10 and abs(n.ty - by) <= 10]
            counts.append(sorted(n.kind for n in near))
        self.assertEqual(counts[0], counts[1])

    def test_nodes_block_movement_and_free_on_depletion(self):
        w = World(seed=3)
        node = w.nodes[0]
        self.assertTrue(w.is_blocked(node.tx, node.ty))
        node.take(node.max_amount)
        self.assertFalse(node.alive)
        w.remove_node(node)
        self.assertFalse(w.is_blocked(node.tx, node.ty))

    def test_free_tile_around_picks_nearest(self):
        w = World(seed=3)
        tiles = {(20, 20), (21, 20), (20, 21), (21, 21)}
        for t in tiles:
            w.blocked[t[1]][t[0]] = 0
        spot = w.free_tile_around(tiles, near=(19 * TILE, 20 * TILE))
        self.assertLessEqual(abs(spot[0] - 19), 1)


class TestEconomy(unittest.TestCase):
    def test_pay_refund_and_missing(self):
        p = Player(0)
        self.assertTrue(p.can_afford({R_WOOL: 100}))
        p.pay({R_WOOL: 100})
        self.assertEqual(p.res[R_WOOL], 160)
        p.refund({R_WOOL: 100})
        self.assertEqual(p.res[R_WOOL], 260)
        self.assertEqual(p.missing({R_WOOL: 9999}), [R_WOOL])

    def test_upgrades_change_stats(self):
        p = Player(0)
        base_atk, base_speed = p.atk_bonus(), p.speed_mult()
        p.upgrades.update(("claws", "paws"))
        self.assertGreater(p.atk_bonus(), base_atk)
        self.assertGreater(p.speed_mult(), base_speed)


class TestGameFlow(unittest.TestCase):
    def test_camera_adapts_to_the_resolution(self):
        from purrtage.settings import MAX_SCENE_PX
        for (w, h) in ((1280, 760), (1920, 1080), (2880, 1800)):
            layout = Layout(w, h)
            g = Game(World(seed=2024), difficulty="tomcat", fog_enabled=False,
                     layout=layout)
            self.assertGreaterEqual(len(g.camera.levels), 2)
            for z in g.camera.levels:
                scene = (g.view.w / z) * (g.view.h / z)
                self.assertLessEqual(scene, MAX_SCENE_PX)
                self.assertLessEqual(g.view.w / (z * layout.asset_scale),
                                     g.world.world_w * 1.08)
            # the zoom expressed in screen pixels accounts for the sprites
            self.assertAlmostEqual(g.camera.zoom,
                                   g.camera.scene_zoom * layout.asset_scale,
                                   places=5)

    def test_resize_keeps_the_game_running(self):
        g = make_game()
        before = len(g.units)
        g.resize(Layout(1920, 1080))
        self.assertEqual(g.view.w, 1920)
        run(g, 2)
        self.assertEqual(len(g.units), before)

    def test_initial_setup(self):
        g = make_game()
        self.assertEqual(len([u for u in g.units if u.player is g.human]), 4)
        self.assertEqual(len([b for b in g.buildings if b.player is g.human]), 1)
        self.assertEqual(g.human.pop, 4)
        self.assertEqual(g.human.pop_limit, 10)

    def test_building_rect_distance(self):
        g = make_game()
        base = next(b for b in g.buildings if b.player is g.human)
        # a point right next to the footprint is less than a tile away
        x = (base.tx - 1) * TILE + TILE * 0.5
        y = base.ty * TILE + TILE * 0.5
        self.assertLess(base.point_dist(x, y), TILE)
        self.assertEqual(base.point_dist(base.x, base.y), 0.0)

    def test_construction_completes(self):
        g = make_game()
        workers = [u for u in g.units if u.player is g.human][:2]
        base = next(b for b in g.buildings if b.player is g.human)
        g.selection = list(workers)
        g.build_mode = "shed"
        placed = g.try_place(base.x + 7 * TILE, base.y)
        self.assertTrue(placed)
        site = next(b for b in g.buildings if b.btype == "shed")
        run(g, 40)
        self.assertFalse(site.under_construction)
        self.assertEqual(g.human.pop_limit, 15)

    def test_several_workers_share_one_deposit(self):
        """Several kittens on one node must spread out around it.

        They all aimed at the same access tile, pushed each other away, came
        back to it and gathered nothing any more: a single kitten brought in
        more than four.
        """
        yields = []
        for n in (1, 2, 3):
            g = make_game()
            base = g.home_base_pos(g.human)
            node = g.world.nearest_node(base[0], base[1], R_WOOL, 20)
            workers = [u for u in g.units if u.player is g.human][:n]
            for u in workers:
                u.order_gather(g, node)
            run(g, 60)
            yields.append(g.human.stat_gathered[R_WOOL])
        self.assertGreater(yields[0], 0, "a single kitten gathers nothing")
        self.assertGreater(yields[1], yields[0] * 1.5,
                           "two kittens do not gather more than one")
        self.assertGreater(yields[2], yields[1],
                           "three kittens do not gather more than two")

    def test_workers_claim_different_tiles(self):
        g = make_game()
        base = g.home_base_pos(g.human)
        node = g.world.nearest_node(base[0], base[1], R_WOOL, 20)
        workers = [u for u in g.units if u.player is g.human][:3]
        for u in workers:
            u.order_gather(g, node)
        spots = [u.work_tile for u in workers]
        self.assertEqual(len(set(spots)), len(spots), "two cats aim at the same tile")

    def test_gathering_fills_the_treasury(self):
        g = make_game()
        workers = [u for u in g.units if u.player is g.human]
        base = next(b for b in g.buildings if b.player is g.human)
        node = g.world.nearest_node(base.x, base.y, R_KIBBLE, 20)
        self.assertIsNotNone(node)
        before = g.human.res[R_KIBBLE]
        for u in workers:
            u.order_gather(g, node)
        run(g, 60)
        self.assertGreater(g.human.res[R_KIBBLE], before)
        self.assertGreater(g.human.stat_gathered[R_KIBBLE], 0)

    def test_training_costs_and_spawns(self):
        g = make_game()
        base = next(b for b in g.buildings
                    if b.player is g.human and b.btype == "basket")
        mine = lambda: len([u for u in g.units if u.player is g.human])
        before_res = g.human.res[R_KIBBLE]
        before_units = mine()
        g.train(base, "kitten")
        self.assertEqual(g.human.res[R_KIBBLE],
                         before_res - UNITS["kitten"]["cost"][R_KIBBLE])
        run(g, 14)
        self.assertEqual(mine(), before_units + 1)

    def test_population_cap_blocks_training(self):
        g = make_game()
        base = next(b for b in g.buildings
                    if b.player is g.human and b.btype == "basket")
        g.human.pop = g.human.pop_limit
        before = g.human.res[R_KIBBLE]
        g.train(base, "kitten")
        self.assertEqual(g.human.res[R_KIBBLE], before)   # nothing is charged
        self.assertEqual(base.queue, [])

    def test_units_chain_onto_the_next_enemy(self):
        """After bringing a target down, the cats chain onto the next one."""
        g = make_game()
        g.ai.think_timer = 1e9          # the AI does not move the targets
        base = g.home_base_pos(g.human)
        mine = []
        for i in range(5):
            u = E.Unit("scratcher", 0, base[0] + i * 20, base[1] + 220, g.human)
            g.units.append(u)
            mine.append(u)
        foes = []
        for i in range(3):
            f = E.Unit("scratcher", 1, base[0] + 150 + i * 90, base[1] + 220, g.enemy)
            f.stop()
            g.units.append(f)
            foes.append(f)
        for u in mine:
            u.order_attack(g, foes[0])      # one single designated target
        self.assertTrue(all(u.ordered_attack for u in mine))
        for _ in range(60 * 90):
            g.update(1 / 60.0)
            if not any(f.alive for f in foes):
                break
        self.assertFalse(any(f.alive for f in foes),
                         "the cats stopped after the first target")
        self.assertTrue(any(u.alive for u in mine))

    def test_two_cats_across_a_grid_border_push_apart(self):
        """A bug report: cats stacked on one another in a fight.

        The repulsion sorts the cats into 48-pixel cells, and only compared
        the cats of one same cell: two cats a hair apart on either side of a
        border never pushed each other away.
        """
        g = make_game()
        a = E.Unit("kitten", 0, 48 * 40 - 1.0, 1000.0, g.human)
        b = E.Unit("kitten", 0, 48 * 40 + 1.0, 1000.0, g.human)
        g.units += [a, b]
        for _ in range(30):
            g._separate()
        self.assertAlmostEqual(math.hypot(b.x - a.x, b.y - a.y),
                               a.radius + b.radius, places=1)

    def test_an_ordered_attack_pursues_further_than_a_riposte(self):
        g = make_game()
        u = next(x for x in g.units if x.player is g.human)
        u.ordered_attack = False
        short = u.leash_range()
        u.ordered_attack = True
        self.assertGreater(u.leash_range(), short)
        self.assertGreater(u.hunt_range(), 0)

    def test_hover_finds_the_resource_under_the_cursor(self):
        g = make_game(fog=False)
        base = g.home_base_pos(g.human)
        g.camera.center_on(*base)
        node = g.world.nearest_node(base[0], base[1], R_WOOL, 20)
        sx, sy = g.camera.world_to_screen(node.x, node.y)
        self.assertIs(g.update_hover((int(sx), int(sy))), node)
        self.assertIs(g.hover_node, node)
        # far from any node, then during a building placement
        self.assertIsNone(g.update_hover((int(sx) + 400, int(sy))))
        g.build_mode = "shed"
        self.assertIsNone(g.update_hover((int(sx), int(sy))))

    def test_combat_damages_and_kills(self):
        g = make_game()
        attacker = next(u for u in g.units if u.player is g.enemy)
        victim = next(u for u in g.units if u.player is g.human)
        victim.x, victim.y = attacker.x + 12, attacker.y
        hp = victim.hp
        g.deal_damage(attacker, victim, 20.0)
        self.assertLess(victim.hp, hp)
        g.deal_damage(attacker, victim, 9999.0)
        self.assertFalse(victim.alive)
        self.assertEqual(g.enemy.stat_kills, 1)

    def test_armour_reduces_damage_but_never_below_one(self):
        g = make_game()
        attacker = next(u for u in g.units if u.player is g.enemy)
        victim = next(u for u in g.units if u.player is g.human)
        victim.spec = dict(victim.spec)
        hp = victim.hp
        g.deal_damage(attacker, victim, 1.0)
        self.assertAlmostEqual(hp - victim.hp, 1.0, places=5)

    def test_defeat_when_production_is_lost(self):
        g = make_game()
        for u in [u for u in g.units if u.player is g.human]:
            u.alive = False
        for b in [b for b in g.buildings if b.player is g.human]:
            b.alive = False
        g.update(0.05)
        self.assertEqual(g.state, ST_DEFEAT)

    def test_still_alive_while_a_single_kitten_remains(self):
        g = make_game()
        for b in [b for b in g.buildings if b.player is g.human]:
            b.alive = False
        g.update(0.05)
        self.assertEqual(g.state, 0)        # a kitten can rebuild everything
        self.assertFalse(g.human.defeated)

    def test_victory_when_the_enemy_is_wiped_out(self):
        g = make_game()
        for u in [u for u in g.units if u.player is g.enemy]:
            u.alive = False
        for b in [b for b in g.buildings if b.player is g.enemy]:
            b.alive = False
        g.update(0.05)
        self.assertEqual(g.state, ST_VICTORY)

    def test_fog_hides_then_reveals(self):
        g = make_game(fog=True)
        far = g.world.start_tiles[1]
        self.assertFalse(g.fog.is_explored(*far))
        near = g.world.start_tiles[0]
        self.assertTrue(g.fog.is_explored(*near))

    def test_ai_builds_and_trains(self):
        g = make_game()
        run(g, 150)
        enemy_buildings = [b for b in g.buildings if b.player is g.enemy]
        enemy_units = [u for u in g.units if u.player is g.enemy]
        self.assertGreater(len(enemy_buildings), 1)
        self.assertGreater(len(enemy_units), 4)


class TestReportTyping(unittest.TestCase):
    """Report of 2026-10-11: "aatttteennttiioonn ddoouubbllaaggee"."""

    @classmethod
    def setUpClass(cls):
        from purrtage.app import App
        cls.app = App(skip_menu=True, sound=False)

    def setUp(self):
        self.app.open_bug_report()

    def tearDown(self):
        self.app.close_bug_report()

    def _keydown(self, ch):
        return pygame.event.Event(pygame.KEYDOWN, key=ord(ch), unicode=ch, mod=0)

    def _type(self, text):
        """SDL emits KEYDOWN *then* TEXTINPUT for a printable key."""
        for ch in text:
            self.app._bug_event(self._keydown(ch))
            self.app._bug_event(pygame.event.Event(pygame.TEXTINPUT, text=ch))

    def test_a_letter_typed_once_lands_once(self):
        self._type("le chaton...")
        self.assertEqual(self.app.bug_text, "le chaton...")

    def test_backspace_removes_one_letter(self):
        self._type("miaou")
        self.app._bug_event(pygame.event.Event(
            pygame.KEYDOWN, key=pygame.K_BACKSPACE, unicode="\b", mod=0))
        self.assertEqual(self.app.bug_text, "miao")

    def test_the_keyboard_fallback_still_fills_the_field(self):
        """Without TEXTINPUT — old pygame — typing goes through KEYDOWN alone."""
        self.app.bug_text_events = False
        for ch in "miaou":
            self.app._bug_event(self._keydown(ch))
        self.assertEqual(self.app.bug_text, "miaou")


class TestReportWindow(unittest.TestCase):
    """The F8 window: the screenshot checkbox, then the sending."""

    @classmethod
    def setUpClass(cls):
        from purrtage.app import App
        cls.app = App(skip_menu=True, sound=False)

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.saved_dir = bugreport.BUG_DIR
        bugreport.BUG_DIR = os.path.join(self.tmp, "saves", "bug")
        bugsend.results()
        self.app.bug_attach_shot = True
        self.app.open_bug_report()
        self.app.bug_text = "Le Matou ne bouge plus."

    def tearDown(self):
        import shutil
        self.app.close_bug_report()
        bugreport.BUG_DIR = self.saved_dir
        os.environ.pop("PURRTAGE_REPORT_URL", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tab_toggles_the_screenshot(self):
        tab = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB,
                                 unicode="\t", mod=0)
        self.app._bug_event(tab)
        self.assertFalse(self.app.bug_attach_shot)
        self.app._bug_event(tab)
        self.assertTrue(self.app.bug_attach_shot)
        self.assertEqual(self.app.bug_text, "Le Matou ne bouge plus.")

    def test_an_unticked_screenshot_is_not_saved(self):
        self.app.bug_attach_shot = False
        self.app.submit_bug_report()
        names = os.listdir(bugreport.report_dir())
        self.assertTrue(any(n.endswith(".txt") for n in names))
        self.assertFalse(any(n.endswith(".png") for n in names))
        self.assertIsNone(self.app.bug_send)    # no relay: nothing to send

    def test_without_a_relay_the_log_says_why(self):
        os.environ.pop("PURRTAGE_REPORT_URL", None)
        self.app.submit_bug_report()
        path = os.path.join(bugreport.report_dir(), bugsend.LOG_NAME)
        with open(path, encoding="utf-8") as fh:
            self.assertIn("not sent, no relay address", fh.read())

    def test_the_window_follows_the_sending(self):
        relay = _Relay()
        try:
            os.environ["PURRTAGE_REPORT_URL"] = relay.url
            self.app.submit_bug_report()
            self.assertEqual(self.app.bug_send, "sending")
            import time
            deadline = time.time() + 10
            while self.app.bug_send == "sending" and time.time() < deadline:
                self.app._poll_bug_sends()
                time.sleep(0.02)
        finally:
            relay.close()
        self.assertEqual(self.app.bug_send, bugsend.SENT)
        self.assertEqual(len(relay.bodies), 1)

    def test_the_window_draws_in_every_state(self):
        from purrtage import i18n, screens
        surface = pygame.Surface(self.app.layout.size)
        for code in i18n.codes():
            i18n.set_language(code)
            for online in (False, True):
                areas = screens.draw_bug_report(
                    surface, self.app.fonts, self.app.layout, "texte",
                    "/tmp", None, True, attach_shot=True, online=online)
                self.assertIn("shot", areas)
            for status in (None, "sending", bugsend.SENT, bugsend.QUEUED,
                           bugsend.REJECTED):
                areas = screens.draw_bug_report(
                    surface, self.app.fonts, self.app.layout, "",
                    "/tmp", ["bogue.txt"], True, status=status)
                self.assertIn("open", areas)
        i18n.set_language("fr")


class TestBuildSites(unittest.TestCase):
    """Report of 2026-10-11: "the kitten that builds must keep building"."""

    @staticmethod
    def _spots(game, count, size=2):
        """Free locations around the player's basket."""
        bx, by = game.home_base_pos(game.human)
        tx, ty = int(bx // TILE), int(by // TILE)
        found = []
        for radius in range(3, 14):
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    spot = (tx + dx, ty + dy)
                    if game.world.can_place(spot[0], spot[1], size):
                        if all(abs(spot[0] - a) > size
                               or abs(spot[1] - b) > size
                               for (a, b) in found):
                            found.append(spot)
                    if len(found) == count:
                        return found
        raise AssertionError("not enough room around the basket")

    def _kitten(self, game):
        return next(u for u in game.units
                    if u.player is game.human and u.utype == "kitten")

    def test_a_builder_moves_on_to_the_next_site(self):
        g = make_game()
        one, two = self._spots(g, 2)
        site1 = g.place_building(g.human, "shed", *one, free=True)
        site2 = g.place_building(g.human, "shed", *two, free=True)
        kitten = self._kitten(g)
        kitten.order_build(g, site1)
        run(g, 60)
        self.assertFalse(site1.under_construction, "the first one is not finished")
        self.assertFalse(site2.under_construction,
                         "the kitten left the second site unfinished")

    def test_a_builder_with_nothing_left_to_do_stops(self):
        g = make_game()
        (lone,) = self._spots(g, 1)
        site = g.place_building(g.human, "shed", *lone, free=True)
        kitten = self._kitten(g)
        kitten.order_build(g, site)
        run(g, 40)
        self.assertFalse(site.under_construction)
        self.assertEqual(kitten.state, E.IDLE)
        self.assertIsNone(kitten.site)

    def test_a_builder_ignores_a_site_on_the_other_side_of_the_map(self):
        """It chains onto what sits next door, it does not cross the map."""
        from purrtage.settings import NEXT_SITE_TILES
        g = make_game()
        (here,) = self._spots(g, 1)
        site = g.place_building(g.human, "shed", *here, free=True)
        kitten = self._kitten(g)
        far = None
        for tx in range(g.world.w - 3, 2, -1):
            if (abs(tx - here[0]) > NEXT_SITE_TILES + 4
                    and g.world.can_place(tx, here[1], 2)):
                far = g.place_building(g.human, "shed", tx, here[1], free=True)
                break
        self.assertIsNotNone(far, "no room far enough away on the map")
        kitten.order_build(g, site)
        run(g, 40)
        self.assertFalse(site.under_construction)
        self.assertTrue(far.under_construction,
                        "the kitten went off to the other end of the map")


class TestStoneAndRamparts(unittest.TestCase):
    """Stone, the ramparts it builds and the towers it takes higher."""

    def _kitten(self, game):
        return next(u for u in game.units
                    if u.player is game.human and u.utype == "kitten")

    def _room(self, game, size):
        (spot,) = TestBuildSites._spots(game, 1, size=size)
        return spot

    def test_every_base_has_stone_next_door(self):
        from purrtage.settings import R_STONE
        w = World(seed=2024)
        for (bx, by) in w.start_tiles:
            near = [n for n in w.nodes if n.kind == R_STONE
                    and abs(n.tx - bx) <= 11 and abs(n.ty - by) <= 11]
            self.assertGreaterEqual(len(near), 3)

    def test_a_kitten_brings_stone_home(self):
        from purrtage.settings import R_STONE
        g = make_game()
        bx, by = g.home_base_pos(g.human)
        node = g.world.nearest_node(bx, by, R_STONE, 20)
        self.assertIsNotNone(node)
        self._kitten(g).order_gather(g, node)
        run(g, 40)
        self.assertGreater(g.human.res[R_STONE], 0)

    def test_dragging_lays_a_line_of_ramparts(self):
        from purrtage.settings import BUILDINGS, R_STONE
        g = make_game()
        tx, ty = self._room(g, 5)
        g.human.res[R_STONE] = 100
        kitten = self._kitten(g)
        g.selection = [kitten]
        g.build_mode = "wall"
        g.try_place_line((tx, ty), (tx + 4.5) * TILE, (ty + 0.5) * TILE)
        walls = [b for b in g.buildings if b.btype == "wall"]
        self.assertEqual(sorted((b.tx, b.ty) for b in walls),
                         [(tx + i, ty) for i in range(5)])
        self.assertEqual(g.human.res[R_STONE],
                         100 - 5 * BUILDINGS["wall"]["cost"][R_STONE])
        self.assertTrue(all(g.world.is_blocked(b.tx, b.ty) for b in walls))
        self.assertIsNone(g.build_mode)
        run(g, 60)
        self.assertFalse(any(b.under_construction for b in walls),
                         "the kitten did not raise the whole line")

    def test_a_line_stops_where_the_stone_runs_out(self):
        from purrtage.settings import BUILDINGS, R_STONE
        g = make_game()
        tx, ty = self._room(g, 5)
        g.human.res[R_STONE] = BUILDINGS["wall"]["cost"][R_STONE] * 2 + 1
        g.selection = [self._kitten(g)]
        g.build_mode = "wall"
        g.try_place_line((tx, ty), (tx + 4.5) * TILE, (ty + 0.5) * TILE)
        self.assertEqual(sum(1 for b in g.buildings if b.btype == "wall"), 2)

    def _tower(self, g):
        tx, ty = self._room(g, 2)
        return g.place_building(g.human, "tower", tx, ty, free=True,
                                complete=True)

    def test_a_tower_climbs_its_levels(self):
        from purrtage.settings import BUILDINGS, R_CATNIP, R_STONE
        g = make_game()
        tower = self._tower(g)
        atk, rng, hp = tower.attack, tower.attack_range, tower.max_hp
        g.human.res[R_STONE] = g.human.res[R_CATNIP] = 1000
        first, second = BUILDINGS["tower"]["levels"]
        self.assertTrue(g.order_level_up(tower))
        self.assertEqual(g.human.res[R_STONE], 1000 - first["cost"][R_STONE])
        self.assertFalse(g.order_level_up(tower), "two upgrades at once")
        run(g, first["time"] + 1)
        self.assertEqual(tower.level, 2)
        self.assertEqual(tower.attack, atk + first["atk"])
        self.assertEqual(tower.attack_range, rng + first["rng"])
        self.assertEqual(tower.max_hp, hp + first["hp"])
        self.assertTrue(g.order_level_up(tower))
        run(g, second["time"] + 1)
        self.assertEqual(tower.level, tower.max_level)
        self.assertFalse(g.order_level_up(tower), "past the top level")

    def test_cancelling_an_upgrade_gives_the_stone_back(self):
        from purrtage.settings import R_CATNIP, R_STONE
        g = make_game()
        tower = self._tower(g)
        g.human.res[R_STONE] = g.human.res[R_CATNIP] = 500
        g.order_level_up(tower)
        g.cancel_production(tower)
        self.assertIsNone(tower.leveling)
        self.assertEqual(g.human.res[R_STONE], 500)
        self.assertEqual(tower.level, 1)

    def test_ramparts_join_up_with_their_neighbours(self):
        """Report of 2026-10-15: a column of ramparts looked like a pile of
        loose blocks. Each block now knows which sides it joins."""
        from purrtage import sprites
        from purrtage.render import WorldRenderer
        g = make_game()
        tx, ty = self._room(g, 3)
        for (x, y) in ((tx, ty), (tx + 1, ty), (tx, ty + 1), (tx, ty + 2)):
            g.place_building(g.human, "wall", x, y, free=True, complete=True)
        corner = g.world.building_at[(tx, ty)]
        foot = g.world.building_at[(tx, ty + 2)]
        r = WorldRenderer(g)
        self.assertIs(r._building_sprite(corner, TILE),
                      sprites.wall_sprite(g.human.team, TILE,
                                          sprites.WALL_E | sprites.WALL_S))
        self.assertIs(r._building_sprite(foot, TILE),
                      sprites.wall_sprite(g.human.team, TILE, sprites.WALL_N))

    def test_a_column_foot_is_not_the_loose_block(self):
        """Report of 2026-10-15, 11:19: the foot of a column (joined to the
        north only) came out of the cache as the isolated block."""
        from purrtage import sprites
        team = 0
        loose = sprites.building_sprite("wall", team, TILE, 1)
        foot = sprites.wall_sprite(team, TILE, sprites.WALL_N)
        self.assertIsNot(foot, loose)
        self.assertIs(sprites.building_sprite("wall", team, TILE, 1), loose)

    def test_only_towers_offer_a_level(self):
        from purrtage.settings import BUILDINGS
        for btype, spec in BUILDINGS.items():
            self.assertEqual(bool(spec.get("levels")), btype == "tower", btype)


class TestAIWaves(unittest.TestCase):
    """Report of 2026-10-15, 12:36: after its first assault the AI sent each
    new soldier at the enemy on its own, as soon as it was recruited."""

    def _setup(self, count):
        g = make_game()
        ai = g.ai
        ai.panic = 0.0
        ai.wave_timer = 0.0
        sx, sy = ai._staging_point()
        cats = [E.Unit("scratcher", ai.player.team, sx, sy, ai.player)
                for _ in range(count)]
        g.units.extend(cats)
        return g, ai, cats

    def test_a_wave_leaves_together_once_the_army_has_gathered(self):
        g, ai, cats = self._setup(6)
        ai.army_target = 6
        ai._attack()
        self.assertTrue(ai.attacking)
        self.assertEqual(len(ai.wave), 6)
        self.assertTrue(all(u.state == E.ATTACK_MOVE for u in cats))

    def test_a_fresh_cat_waits_instead_of_running_off_alone(self):
        g, ai, cats = self._setup(6)
        ai.army_target = 6
        ai._attack()
        bx, by = ai.base
        fresh = E.Unit("scratcher", ai.player.team, bx + 3 * TILE, by,
                       ai.player)
        g.units.append(fresh)
        ai._attack()
        self.assertNotIn(fresh, ai.wave)
        self.assertNotEqual(fresh.state, E.ATTACK_MOVE,
                            "a lone recruit was sent at the enemy")

    def test_a_cut_down_wave_falls_back(self):
        g, ai, cats = self._setup(10)
        ai.army_target = 10
        ai._attack()
        for u in cats[:8]:
            u.alive = False
        ai._attack()
        self.assertFalse(ai.attacking)
        self.assertTrue(all(u.state == E.MOVE for u in cats[8:]),
                        "the survivors did not come home")

    def test_reinforcements_go_as_a_group(self):
        from purrtage.ai import REINFORCE_MIN
        g, ai, cats = self._setup(10)
        ai.army_target = 10
        ai._attack()
        sx, sy = ai._staging_point()
        fresh = [E.Unit("scratcher", ai.player.team, sx, sy, ai.player)
                 for _ in range(REINFORCE_MIN)]
        g.units.extend(fresh)
        ai._attack()
        self.assertTrue(all(u in ai.wave for u in fresh))
        self.assertTrue(all(u.state == E.ATTACK_MOVE for u in fresh))

    def test_gathering_leans_towards_what_runs_low(self):
        from purrtage.settings import R_KIBBLE, R_WOOL
        g = make_game()
        ai = g.ai
        ai.player.res[R_KIBBLE], ai.player.res[R_WOOL] = 0, 3000
        mix = dict(ai._gather_mix())
        self.assertGreater(mix[R_KIBBLE], 0.7)
        self.assertLess(mix[R_WOOL], 0.1)


class TestPackaging(unittest.TestCase):
    """The game name ends up as a file name: it may be pretty, it may not be
    illegal."""

    FORBIDDEN = set('\\/:*?"<>|')

    @staticmethod
    def _root():
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _define(self, text, name):
        import re
        found = re.search(r'#define %s "([^"]+)"' % name, text)
        self.assertIsNotNone(found, "%s missing from the installer" % name)
        return found.group(1)

    def test_the_windows_shortcuts_have_a_legal_name(self):
        """"Purr-tage : …" with a colon would make iscc fail."""
        path = os.path.join(self._root(), "packaging", "windows",
                            "installer.iss")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        filename = self._define(text, "FileName")
        self.assertFalse(self.FORBIDDEN & set(filename),
                         "\"%s\" cannot name a shortcut" % filename)
        self.assertFalse(self.FORBIDDEN & set(self._define(text, "Exe")
                                              .replace(".exe", "")))
        for line in text.splitlines():
            if line.startswith("Name:") and "{#Name}" in line:
                self.fail("a shortcut uses the display name: %s" % line)

    def test_the_packaged_name_matches_everywhere(self):
        """The executable of the recipe, the AppImage script and the installer."""
        root = self._root()
        def read(*parts):
            with open(os.path.join(root, *parts), encoding="utf-8") as fh:
                return fh.read()
        spec = read("packaging", "purrtage.spec")
        import re
        names = set(re.findall(r'name="([^"]+)"', spec))
        self.assertEqual(len(names), 1, "the recipe gives two names: %s" % names)
        name = names.pop()
        self.assertIn("dist/%s" % name, read("packaging", "linux",
                                             "make_appimage.sh"))
        self.assertIn("dist\\%s\\*" % name,
                      read("packaging", "windows", "installer.iss"))
        self.assertIn("Exec=%s" % name, read("packaging", "linux",
                                             "purrtage.desktop"))


class TestExportSvg(unittest.TestCase):
    """The SVG export replays the game drawing: it must follow its changes."""

    def setUp(self):
        import sys
        import tempfile
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, "packaging")
        if path not in sys.path:
            sys.path.insert(0, path)
        import export_svg
        self.export_svg = export_svg
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_exporter_knows_every_primitive_of_the_painter(self):
        """One more primitive in `_P` must show up here, not in a truncated
        SVG shipped without a word."""
        self.export_svg.check_api()

    def test_every_vector_sprite_comes_out_as_valid_svg(self):
        import xml.etree.ElementTree as ET
        written = self.export_svg.export(self.tmp)
        self.assertTrue(written, "no sprite was exported")
        for path in written:
            root = ET.parse(path).getroot()
            self.assertTrue(root.tag.endswith("svg"),
                            "%s has no <svg> root" % path)
            self.assertTrue(root.get("viewBox"),
                            "%s has no viewBox" % path)
            self.assertTrue(len(list(root)),
                            "%s draws nothing" % path)

    def test_the_four_cats_and_the_buildings_are_in_the_lot(self):
        from purrtage.settings import BUILDINGS, UNIT_ORDER
        names = {os.path.basename(p) for p in self.export_svg.export(self.tmp)}
        for utype in UNIT_ORDER:
            self.assertIn("cat-%s-0.svg" % utype, names)
        for btype in BUILDINGS:
            self.assertIn("building-%s.svg" % btype, names)

    def test_the_export_works_on_caches_the_game_already_filled(self):
        """The sprites are cached. Exporting after a game must not spit back
        out the pygame surfaces that were already computed."""
        from purrtage import sprites
        sprites.decor_sprite(0)
        sprites.unit_sprite("kitten", 0, 0, 1)
        for path in self.export_svg.export(self.tmp):
            with open(path, encoding="utf-8") as fh:
                self.assertTrue(fh.read().startswith("<svg"),
                                "%s is not SVG" % path)

    def test_the_export_leaves_the_sprite_caches_usable(self):
        """The export hijacks the painter: if a cache kept SVG, the game
        would get a string instead of a surface."""
        from purrtage import sprites
        self.export_svg.export(self.tmp)
        self.assertIsInstance(sprites.unit_sprite("scratcher", 0, 0, 1),
                              pygame.Surface)
        self.assertIsInstance(sprites.decor_sprite(0), pygame.Surface)
        self.assertIsInstance(sprites.building_sprite("tower", 0, 64),
                              pygame.Surface)
        self.assertEqual(sorted(sprites.FUR), sorted(UNITS),
                         "the export carried off the cats' coats")


if __name__ == "__main__":
    unittest.main(verbosity=2)

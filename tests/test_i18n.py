# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Translation tests.

What we want to guarantee: no language loses a key along the way, the `{…}`
fields stay the same from one language to the next, and switching language
really changes what gets displayed — without breaking the layout.
"""

import os
import string
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

pygame.init()
pygame.display.set_mode((64, 64))

from purrtage import i18n                                              # noqa: E402
from purrtage.layout import Layout                                     # noqa: E402
from purrtage.settings import (BUILDINGS, DIFF_ORDER, RESOURCES, UNITS,  # noqa: E402
                             UPGRADES)


def leaf_keys(node, prefix=""):
    """Every key that carries a text, in dotted notation."""
    if isinstance(node, dict):
        for name, value in node.items():
            for key in leaf_keys(value, "%s.%s" % (prefix, name) if prefix
                                 else name):
                yield key
    elif isinstance(node, list):
        for index, value in enumerate(node):
            for key in leaf_keys(value, "%s[%d]" % (prefix, index)):
                yield key
    else:
        yield prefix


def fields(text):
    """The names of the `{…}` fields of a text."""
    if not isinstance(text, str):
        return set()
    return set(name for _lit, name, _spec, _conv
               in string.Formatter().parse(text) if name)


def walk(node):
    """The (key, text) pairs of a whole catalog."""
    if isinstance(node, dict):
        items = node.items()
    elif isinstance(node, list):
        items = enumerate(node)
    else:
        return
    for name, value in items:
        if isinstance(value, str):
            yield str(name), value
        else:
            for sub, text in walk(value):
                yield "%s.%s" % (name, sub), text


class TestCatalogs(unittest.TestCase):
    def setUp(self):
        self.before = i18n.language()

    def tearDown(self):
        i18n.set_language(self.before)

    def test_french_and_english_are_installed(self):
        codes = i18n.codes()
        self.assertIn("fr", codes)
        self.assertIn("en", codes)
        self.assertEqual(codes[0], i18n.REFERENCE,
                         "the reference language must come first")

    def test_every_language_declares_its_own_name(self):
        for code, name in i18n.available():
            self.assertTrue(name and name != code.upper(),
                            "language %s has no \"language.name\"" % code)

    def test_no_language_is_missing_a_key(self):
        reference = set(leaf_keys(i18n.catalog(i18n.REFERENCE)))
        self.assertTrue(reference)
        for code in i18n.codes():
            if code == i18n.REFERENCE:
                continue
            missing = sorted(reference - set(leaf_keys(i18n.catalog(code))))
            self.assertEqual(missing, [],
                             "keys missing from %s.json: %s" % (code, missing))

    def test_the_placeholders_survive_translation(self):
        reference = dict(walk(i18n.catalog(i18n.REFERENCE)))
        for code in i18n.codes():
            if code == i18n.REFERENCE:
                continue
            for key, text in walk(i18n.catalog(code)):
                if key not in reference:
                    continue
                self.assertEqual(fields(text), fields(reference[key]),
                                 "different {…} fields for %s in %s"
                                 % (key, code))


class TestGameData(unittest.TestCase):
    """Every identifier in the code must have a label in every language."""

    def setUp(self):
        self.before = i18n.language()

    def tearDown(self):
        i18n.set_language(self.before)

    def test_every_identifier_is_named_in_every_language(self):
        for code in i18n.codes():
            i18n.set_language(code)
            for utype in UNITS:
                self.assertNotEqual(i18n.unit_name(utype), utype,
                                    "%s has no name in %s" % (utype, code))
                self.assertTrue(i18n.unit_role(utype))
                self.assertTrue(i18n.unit_desc(utype))
                self.assertIn(i18n.unit_gender(utype), ("m", "f"))
            for btype in BUILDINGS:
                self.assertNotEqual(i18n.building_name(btype), btype,
                                    "%s has no name in %s" % (btype, code))
                self.assertTrue(i18n.building_desc(btype))
                self.assertIn(i18n.building_gender(btype), ("m", "f"))
            for key in UPGRADES:
                self.assertNotEqual(i18n.upgrade_name(key), key)
                self.assertTrue(i18n.upgrade_desc(key))
            for kind in RESOURCES:
                self.assertNotEqual(i18n.resource_name(kind), kind)
                self.assertTrue(i18n.resource_short(kind))
            for key in DIFF_ORDER:
                self.assertNotEqual(i18n.difficulty_name(key), key)
            for team in (0, 1):
                self.assertTrue(i18n.team_name(team))

    def test_the_gendered_messages_have_both_forms(self):
        """French agrees "termine" / "terminee" with the translated name."""
        for code in i18n.codes():
            i18n.set_language(code)
            for key in ("messages.building_done", "messages.destroyed",
                        "messages.under_attack"):
                for gender in ("m", "f"):
                    text = i18n.t("%s.%s" % (key, gender), name="X")
                    self.assertIn("X", text, "%s.%s in %s" % (key, gender, code))


class TestLookup(unittest.TestCase):
    def setUp(self):
        self.before = i18n.language()

    def tearDown(self):
        i18n.set_language(self.before)

    def test_an_unknown_key_shows_itself(self):
        self.assertEqual(i18n.t("nothing.at.all"), "nothing.at.all")

    def test_an_unknown_language_falls_back_to_french(self):
        self.assertEqual(i18n.set_language("kl"), i18n.REFERENCE)

    def test_a_missing_field_keeps_the_raw_text(self):
        i18n.set_language("fr")
        self.assertIn("{pop}", i18n.t("hud.population", unknown=1))

    def test_the_plural_picks_the_right_form(self):
        i18n.set_language("en")
        self.assertEqual(i18n.tp("hud.selected", 1), "1 unit selected")
        self.assertEqual(i18n.tp("hud.selected", 4), "4 units selected")

    def test_a_language_without_the_key_borrows_the_french_one(self):
        i18n.set_language("en")
        self.assertEqual(i18n.t("language.code"), "en")
        # a key missing everywhere: we see it, we do not make it up
        self.assertEqual(i18n.t("menu.nonexistent"), "menu.nonexistent")

    def test_the_languages_cycle(self):
        order = i18n.codes()
        seen = [order[0]]
        for _ in range(len(order)):
            seen.append(i18n.next_language(seen[-1]))
        self.assertEqual(seen[-1], order[0], "the cycle must come back round")
        self.assertEqual(sorted(set(seen)), sorted(order))

    def test_detection_prefers_the_remembered_choice(self):
        """The player's choice wins over the system language."""
        import shutil
        import tempfile
        from purrtage import paths
        folder = tempfile.mkdtemp()
        real = paths.data_dir
        paths.data_dir = lambda: folder
        try:
            self.assertIsNone(i18n.preference())
            self.assertTrue(i18n.remember("en"))
            self.assertEqual(i18n.preference(), "en")
            self.assertEqual(i18n.detect(), "en")
        finally:
            paths.data_dir = real
            shutil.rmtree(folder, ignore_errors=True)


class TestInGameSwitch(unittest.TestCase):
    """Switching language must change the screen, not just a variable."""

    def setUp(self):
        self.before = i18n.language()

    def tearDown(self):
        i18n.set_language(self.before)

    def test_the_names_follow_the_language(self):
        from purrtage.game import Game
        from purrtage.world import World
        i18n.set_language("fr")
        game = Game(World(seed=7), difficulty="tomcat", fog_enabled=False)
        kitten = next(u for u in game.units if u.utype == "kitten")
        self.assertEqual(kitten.name, "Chaton")
        self.assertEqual(game.human.name, "Clan Moustache")
        i18n.set_language("en")
        self.assertEqual(kitten.name, "Kitten")
        self.assertEqual(game.human.name, "Whisker Clan")
        self.assertEqual(kitten.status_label(), i18n.t("status.idle"))

    def test_the_options_button_switches_the_language(self):
        from purrtage import screens
        from purrtage.fonts import load_fonts
        i18n.set_language("fr")
        layout = Layout(1280, 760)
        fonts = load_fonts(layout.scale)
        menu = screens.MainMenu(fonts, layout)
        options = screens.OptionsScreen(fonts, layout, menu)
        options.update(0.1)
        self.assertIn("Français", options.buttons["lang"].label)
        self.assertEqual(options.click(options.buttons["lang"].rect.center),
                         "language")
        self.assertNotEqual(i18n.language(), "fr")
        options.update(0.1)
        self.assertIn(i18n.language_name(), options.buttons["lang"].label)

    def test_the_options_buttons_fit_on_screen(self):
        from purrtage import screens
        from purrtage.fonts import load_fonts
        for (w, h) in ((1280, 760), (1600, 900), (1920, 1080), (2880, 1800)):
            layout = Layout(w, h)
            fonts = load_fonts(layout.scale)
            menu = screens.MainMenu(fonts, layout)
            options = screens.OptionsScreen(fonts, layout, menu)
            highest = min(b.rect.top for b in options.buttons.values())
            lowest = max(b.rect.bottom for b in options.buttons.values())
            self.assertGreater(highest, layout.u(150),
                               "the options cover the title at %dx%d" % (w, h))
            self.assertLess(lowest, h - layout.u(110),
                            "the options overflow at %dx%d" % (w, h))

    def test_every_page_draws_in_every_language(self):
        from purrtage import screens
        from purrtage.fonts import load_fonts
        for code in i18n.codes():
            i18n.set_language(code)
            for (w, h) in ((1280, 760), (2880, 1800)):
                layout = Layout(w, h)
                fonts = load_fonts(layout.scale)
                surface = pygame.Surface(layout.size)
                screens.draw_guide(surface, fonts, layout)
                screens.draw_help(surface, fonts, layout)
                screens.MainMenu(fonts, layout).draw(surface)
                screens.OptionsScreen(fonts, layout,
                                      screens.MainMenu(fonts, layout)).draw(surface)
                screens.LanScreen(fonts, layout).draw(surface, None, None, 0.0)


if __name__ == "__main__":
    unittest.main()


class TestGlyphs(unittest.TestCase):
    """No catalogue string may use a character the bundled font lacks.

    A missing glyph does not fail, it draws a blank box, and nobody notices
    until a player sends a screenshot. Two of them — a tick mark and an arrow —
    reached the keys screen before this test existed.
    """

    @staticmethod
    def _strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for inner in value.values():
                for text in TestGlyphs._strings(inner):
                    yield text
        elif isinstance(value, list):
            for inner in value:
                for text in TestGlyphs._strings(inner):
                    yield text

    def test_every_character_has_a_glyph(self):
        import json
        import io as _io
        import os as _os
        import pygame
        from purrtage.fonts import load_fonts

        pygame.init()
        pygame.display.set_mode((64, 64))
        font = load_fonts(1.0)[2]

        def shape(char):
            img = font.render(char, True, (255, 255, 255))
            w, h = img.get_size()
            # The colour is white everywhere; the alpha channel carries the
            # drawing, so that is what tells one glyph from another.
            return (w, h, tuple(img.get_at((x, y))[3] > 90
                                for y in range(h) for x in range(w)))

        # Three private-use code points: the font has none of them, so they
        # all come out as the same replacement box.
        missing = {shape(c) for c in ("", "", "")}

        root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        folder = _os.path.join(root, "purrtage", "locales")
        seen = {}
        for name in sorted(_os.listdir(folder)):
            if not name.endswith(".json"):
                continue
            with _io.open(_os.path.join(folder, name), encoding="utf-8") as fh:
                catalog = json.load(fh)
            for text in self._strings(catalog):
                for char in set(text):
                    if ord(char) < 128 or char in seen:
                        continue
                    seen[char] = True
                    self.assertNotIn(
                        shape(char), missing,
                        "%s uses U+%04X %r, which the font cannot draw: %r"
                        % (name, ord(char), char, text[:60]))

# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the rebindable keys: the map, the storage and the screen."""

import io
import json
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

pygame.init()
pygame.display.set_mode((64, 64))

from purrtage import i18n, keymap, prefs, screens            # noqa: E402
from purrtage.camera import Camera                           # noqa: E402
from purrtage.fonts import load_fonts                        # noqa: E402
from purrtage.layout import Layout                           # noqa: E402

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class KeymapCase(unittest.TestCase):
    """Every test writes its own settings file, never the player's."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._path = prefs.path
        prefs.path = lambda: os.path.join(self.tmp, "preferences.json")
        keymap.reload()

    def tearDown(self):
        prefs.path = self._path
        keymap.reload()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestDefaults(KeymapCase):

    def test_every_binding_has_a_key(self):
        for binding in keymap.bindings():
            self.assertTrue(keymap.key_for(binding),
                            "%s has no key" % binding)

    def test_shipped_keys_do_not_clash(self):
        self.assertEqual(keymap.duplicates(), set())
        self.assertEqual(keymap.preset_in_use(), "azerty")

    def test_both_presets_are_playable(self):
        for preset in keymap.PRESET_ORDER:
            keymap.apply_preset(preset)
            self.assertEqual(keymap.duplicates(), set(),
                             "the %s preset clashes with itself" % preset)
            self.assertEqual(keymap.preset_in_use(), preset)

    def test_qwerty_moves_the_cat_row_onto_the_same_physical_keys(self):
        keymap.apply_preset("qwerty")
        row = [keymap.key_for("unit.%s" % u)
               for u in ("kitten", "scratcher", "spitter", "tomcat")]
        self.assertEqual(row, ["q", "f", "e", "r"])
        self.assertEqual(keymap.key_for("camera.up"), "w")

    def test_no_key_does_two_things(self):
        """The camera included: one key, one action, in every preset."""
        for preset in keymap.PRESET_ORDER:
            keymap.apply_preset(preset)
            keys = [keymap.key_for(b) for b in keymap.bindings()]
            self.assertEqual(len(keys), len(set(keys)),
                             "the %s preset reuses a key" % preset)
            self.assertFalse(set(keys) & keymap.RESERVED,
                             "the %s preset uses a reserved key" % preset)
        keymap.reset()
        self.assertEqual(keymap.binding_for("z"), "camera.up")


class TestAssign(KeymapCase):

    def test_a_key_is_taken_from_its_previous_holder(self):
        freed = keymap.assign("unit.kitten", keymap.key_for("unit.tomcat"))
        self.assertEqual(freed, "unit.tomcat")
        self.assertEqual(keymap.key_for("unit.tomcat"), "")
        self.assertEqual(keymap.duplicates(), set())

    def test_the_camera_takes_a_key_from_an_action_too(self):
        """Binding the camera onto an action key disarms the action."""
        before = keymap.key_for("unit.spitter")
        freed = keymap.assign("camera.left", before)
        self.assertEqual(freed, "unit.spitter")
        self.assertEqual(keymap.key_for("unit.spitter"), "")
        self.assertEqual(keymap.binding_for(before), "camera.left")
        self.assertEqual(keymap.duplicates(), set())

    def test_reserved_keys_are_refused(self):
        for name in ("escape", "f1", "1", "left shift", "right ctrl", "up",
                     "+", "[-]"):
            self.assertIs(keymap.assign("unit.kitten", name), False)
        self.assertEqual(keymap.key_for("unit.kitten"), "a")

    def test_an_unknown_binding_is_refused(self):
        self.assertIs(keymap.assign("unit.dragon", "y"), False)


class TestStorage(KeymapCase):

    def _saved(self):
        with io.open(prefs.path(), encoding="utf-8") as fh:
            return json.load(fh)

    def test_a_change_survives_a_restart(self):
        keymap.assign("unit.kitten", "y")
        keymap.reload()                      # as if the game were relaunched
        self.assertEqual(keymap.key_for("unit.kitten"), "y")

    def test_only_the_difference_is_written(self):
        """So that a later rebalance of the defaults can still reach players."""
        keymap.assign("unit.kitten", "y")
        stored = self._saved()[keymap.PREFERENCE]
        self.assertEqual(set(stored), {"unit.kitten"})

    def test_the_language_is_not_trampled(self):
        prefs.write("language", "en")
        keymap.assign("unit.kitten", "y")
        self.assertEqual(self._saved()["language"], "en")

    def test_a_stale_or_hostile_file_is_ignored(self):
        prefs.write(keymap.PREFERENCE, {
            "unit.kitten": "y",              # good
            "unit.dragon": "k",              # a binding from another version
            "unit.tomcat": 17,               # not even a string
            "unit.spitter": "",              # empty
        })
        keymap.reload()
        self.assertEqual(keymap.key_for("unit.kitten"), "y")
        self.assertEqual(keymap.key_for("unit.tomcat"), "r")
        self.assertEqual(keymap.key_for("unit.spitter"), "e")
        self.assertNotIn("unit.dragon", keymap.current())

    def test_reset_goes_back_to_the_factory_keys(self):
        keymap.assign("unit.kitten", "y")
        keymap.reset()
        self.assertEqual(keymap.current(), keymap.defaults())


class TestWiring(KeymapCase):
    """The map is worth nothing if the game does not read it."""

    def test_the_camera_follows_a_remap(self):
        camera = Camera(pygame.Rect(0, 0, 800, 600))
        self.assertEqual(camera._camera_codes()["camera.up"],
                         pygame.key.key_code("z"))
        keymap.apply_preset("qwerty")
        self.assertEqual(camera._camera_codes()["camera.up"],
                         pygame.key.key_code("w"),
                         "the camera kept the key it resolved first")

    def test_the_camera_survives_a_key_name_that_means_nothing(self):
        prefs.write(keymap.PREFERENCE, {"camera.up": "not a key"})
        keymap.reload()
        camera = Camera(pygame.Rect(0, 0, 800, 600))
        self.assertIsNone(camera._camera_codes()["camera.up"])

    def test_the_action_panel_prints_the_remapped_key(self):
        from purrtage import ui
        keymap.assign("unit.kitten", "y")
        action = ui.Action("train", "kitten", binding="unit.kitten",
                           hotkey=keymap.label("unit.kitten"))
        self.assertEqual(action.hotkey, "Y")

    def test_the_guide_prints_the_remapped_key(self):
        keymap.assign("building.dojo", "y")
        step = screens.fill_keys("{dojo} pour un Dojo ({tomcat})")
        self.assertEqual(step, "Y pour un Dojo (R)")

    def test_a_press_resolves_to_its_action(self):
        from purrtage import ui
        acts = [ui.Action("train", "kitten", binding="unit.kitten"),
                ui.Action("build", "dojo", binding="building.dojo")]
        hud = ui.HUD.__new__(ui.HUD)
        hud.actions = acts
        keymap.assign("unit.kitten", "y")
        found = hud.action_by_binding(keymap.binding_for("y"))
        self.assertIsNotNone(found)
        self.assertEqual(found.arg, "kitten")


class TestScreen(KeymapCase):

    @staticmethod
    def _screen(w, h):
        layout = Layout(w, h)
        return screens.KeysScreen(load_fonts(layout.scale), layout), layout

    def test_it_fits_on_every_supported_resolution(self):
        for (w, h) in ((1280, 760), (1600, 900), (1920, 1080), (2880, 1800)):
            screen, layout = self._screen(w, h)
            screen.update(0.0)
            lowest = max(b.rect.bottom for b in screen.buttons.values())
            self.assertLess(lowest, h,
                            "the keys screen overflows at %dx%d" % (w, h))
            for binding, rect in screen.rows.items():
                self.assertLess(rect.bottom, lowest,
                                "%s sits under the buttons at %dx%d"
                                % (binding, w, h))

    def test_every_binding_has_a_row(self):
        screen, _ = self._screen(1280, 760)
        self.assertEqual(set(screen.rows), set(keymap.bindings()))

    def test_the_rows_never_overlap(self):
        screen, _ = self._screen(1280, 760)
        rects = list(screen.rows.values())
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                self.assertFalse(a.colliderect(b), "two key caps overlap")

    def test_it_draws_in_both_languages(self):
        before = i18n.language()
        try:
            for code in i18n.codes():
                i18n.set_language(code)
                screen, layout = self._screen(1280, 760)
                screen.update(0.0)
                screen.waiting = "unit.kitten"
                screen.draw(pygame.Surface(layout.size))
        finally:
            i18n.set_language(before)

    def test_clicking_a_row_arms_it_then_a_press_binds_it(self):
        screen, _ = self._screen(1280, 760)
        screen.update(0.0)
        screen.click(screen.rows["unit.kitten"].center)
        self.assertEqual(screen.waiting, "unit.kitten")
        screen.key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_y))
        self.assertIsNone(screen.waiting)
        self.assertEqual(keymap.key_for("unit.kitten"), "y")

    def test_escape_cancels_the_capture_without_binding_it(self):
        screen, _ = self._screen(1280, 760)
        screen.update(0.0)
        screen.click(screen.rows["unit.kitten"].center)
        screen.key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        self.assertIsNone(screen.waiting)
        self.assertEqual(keymap.key_for("unit.kitten"), "a")

    def test_a_reserved_key_is_refused_and_says_so(self):
        screen, _ = self._screen(1280, 760)
        screen.update(0.0)
        screen.click(screen.rows["unit.kitten"].center)
        screen.key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F1))
        self.assertEqual(keymap.key_for("unit.kitten"), "a")
        self.assertTrue(screen.note)

    def test_the_preset_buttons_apply_their_preset(self):
        screen, _ = self._screen(1280, 760)
        screen.update(0.0)
        screen.click(screen.buttons["qwerty"].rect.center)
        self.assertEqual(keymap.preset_in_use(), "qwerty")
        screen.click(screen.buttons["reset"].rect.center)
        self.assertEqual(keymap.preset_in_use(), "azerty")


class TestTexts(KeymapCase):
    """A binding with no label shows the player a raw key like `keys.stop`."""

    def test_every_row_reads_as_words(self):
        for code in i18n.codes():
            i18n.set_language(code)
            for binding in keymap.bindings():
                name = keymap.display_name(binding)
                self.assertNotIn(".", name,
                                 "%s has no label in %s: %r"
                                 % (binding, code, name))
        i18n.set_language(i18n.REFERENCE)

    def test_every_group_and_message_is_translated(self):
        wanted = ["keys.title", "keys.subtitle", "keys.hint", "keys.clash",
                  "keys.press", "keys.applied", "keys.reserved", "keys.freed",
                  "keys.reset", "keys.in_use", "keys.preset_azerty",
                  "keys.preset_qwerty", "options.keys"]
        wanted += [title for title, _rows in keymap.groups()]
        for code in i18n.codes():
            i18n.set_language(code)
            for key in wanted:
                self.assertIsInstance(i18n.data(key), str,
                                      "%s missing from %s" % (key, code))
        i18n.set_language(i18n.REFERENCE)

    def test_the_readmes_mention_the_screen(self):
        for name in ("README.md", "README.en.md"):
            with io.open(os.path.join(RACINE, name), encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("AZERTY", text, "%s says nothing about it" % name)


if __name__ == "__main__":
    unittest.main(verbosity=2)

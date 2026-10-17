# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which key does what, and how the player changes it.

The shortcuts were picked on an AZERTY keyboard: `A E R` sit on its top-left
letter row and `P C G T` are the initials of the French building names. `Z`
and `D` belong to the camera (ZQSD), so the scratcher moved to `F` and the dojo
to `J`. SDL resolves a key by the character it *produces*, not by where it
sits, so on QWERTY that row scatters — `a` lands on the home row, `z` at the
bottom left — and the cats are no longer under the fingers.

So a binding is named rather than spelled. The code asks for
`keymap.key_for("unit.kitten")`, never for the letter A, and the player is
free to put that binding wherever they like. Two presets cover the common
cases and the rest is one binding at a time.

One key, one action: no two bindings ever share a key, the camera included,
and a key the game already uses on its own is not on offer.

    keymap.key_for("unit.kitten")        -> "a"        the pygame key name
    keymap.binding_for("a")              -> "unit.kitten"
    keymap.label("unit.kitten")          -> "A"        what the panel shows
    keymap.assign("unit.kitten", "y")    -> frees whoever held "y"

The defaults for the catalogue entries are read from `purrtage/settings.py`,
which stays the one place where a unit is described. The rest is below.

What is deliberately *not* rebindable: the function keys, Escape, Delete,
Backspace, the digits of the control groups, the arrows, the zoom keys and the
modifiers. They sit at the same place on every layout, and several of them
mean "get me out of here" — a player who mis-binds those has no way back.
Shift and Ctrl already shape a click or a group, so a binding on them would
fire under every shift-click.
"""

from . import prefs
from .settings import (BUILD_MENU, BUILDINGS, UNIT_ORDER, UNITS,
                       UPGRADE_ORDER, UPGRADES)

PREFERENCE = "keymap"     # the key under which `prefs` stores the overrides

# Keys the player cannot take, whatever they press: either the game already
# uses them on its own, or they would lock the player out of their settings.
RESERVED = frozenset(("escape", "f1", "f2", "f5", "f6", "f7", "f8", "f10",
                      "f11", "return", "delete", "backspace", "break",
                      "up", "down", "left", "right",
                      "+", "=", "-", "[+]", "[-]",
                      "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
                      "left shift", "right shift", "left ctrl", "right ctrl",
                      "left alt", "right alt", "left meta", "right meta",
                      "alt gr", "caps lock", "numlock"))

# Groups, in the order the settings screen lists them. Each entry is
# (binding id, label key in the catalogues).
CAMERA = (("camera.left", "keys.camera_left"),
          ("camera.right", "keys.camera_right"),
          ("camera.up", "keys.camera_up"),
          ("camera.down", "keys.camera_down"))

COMMANDS = (("command.stop", "keys.stop"),
            ("command.attack_move", "keys.attack_move"),
            ("command.idle_worker", "keys.idle_worker"),
            ("command.center", "keys.center"),
            ("command.level_up", "keys.level_up"),
            ("command.mute", "keys.mute"))

# The camera on ZQSD and the commands; the catalogue keys come from settings.
_DEFAULT_EXTRA = {
    "camera.left": "q", "camera.right": "d",
    "camera.up": "z", "camera.down": "s",
    "command.stop": "x", "command.attack_move": "v",
    "command.idle_worker": ".", "command.center": "space",
    "command.level_up": "n", "command.mute": "m",
}

# Same physical keys on a QWERTY board, and initials that match the English
# identifiers where the camera leaves them free: basket, scratching_post and
# tower. The shed and the dojo keep the keys they have on AZERTY, and the wall
# stays on the key AZERTY calls W, which QWERTY calls Z.
PRESETS = {
    "azerty": {},         # the defaults, listed for the screen to name them
    "qwerty": {
        "unit.kitten": "q", "unit.scratcher": "f",
        "unit.spitter": "e", "unit.tomcat": "r",
        "building.basket": "b", "building.shed": "c",
        "building.scratching_post": "p", "building.dojo": "j",
        "building.tower": "t", "building.wall": "z",
        "camera.left": "a", "camera.right": "d",
        "camera.up": "w", "camera.down": "s",
    },
}
PRESET_ORDER = ("azerty", "qwerty")

_current = None           # binding id -> key name, built on first use
_revision = 0             # bumped on every change, so caches can tell


# ------------------------------------------------------------- catalogue ----
def _catalogue():
    """Every binding, in screen order: (binding id, label key)."""
    rows = [("unit.%s" % u, "units.%s.short" % u) for u in UNIT_ORDER]
    rows += [("building.%s" % b, "buildings.%s.short" % b) for b in BUILD_MENU]
    rows += [("upgrade.%s" % k, "upgrades.%s.short" % k) for k in UPGRADE_ORDER]
    return tuple(rows) + CAMERA + COMMANDS


def groups():
    """The settings screen reads this: (group label key, rows)."""
    return (("keys.group_units",
             tuple(("unit.%s" % u, "units.%s.short" % u) for u in UNIT_ORDER)),
            ("keys.group_buildings",
             tuple(("building.%s" % b, "buildings.%s.short" % b)
                   for b in BUILD_MENU)),
            ("keys.group_upgrades",
             tuple(("upgrade.%s" % k, "upgrades.%s.short" % k)
                   for k in UPGRADE_ORDER)),
            ("keys.group_camera", CAMERA),
            ("keys.group_commands", COMMANDS))


def bindings():
    return tuple(row[0] for row in _catalogue())


def label_key(binding):
    for row in _catalogue():
        if row[0] == binding:
            return row[1]
    return binding


def display_name(binding):
    """What the settings screen writes in front of the key cap.

    The catalogue entries borrow the short label the action panel already
    uses, which falls back to the full name when no short one exists — the
    units have none today. The rest has a label of its own under `keys.`.
    """
    from . import i18n
    family, _, which = binding.partition(".")
    if family == "unit":
        return i18n.unit_short(which)
    if family == "building":
        return i18n.building_short(which)
    if family == "upgrade":
        return i18n.upgrade_short(which)
    return i18n.t(label_key(binding))


def defaults():
    """The shipped keymap, catalogue entries included."""
    out = {}
    for utype in UNIT_ORDER:
        out["unit.%s" % utype] = UNITS[utype]["hotkey"].lower()
    for btype in BUILD_MENU:
        out["building.%s" % btype] = BUILDINGS[btype]["hotkey"].lower()
    for key in UPGRADE_ORDER:
        out["upgrade.%s" % key] = UPGRADES[key]["hotkey"].lower()
    out.update(_DEFAULT_EXTRA)
    return out


# --------------------------------------------------------------- reading ----
def _load():
    """Defaults, then whatever the player saved on top. Hostile-input proof."""
    current = defaults()
    saved = prefs.get(PREFERENCE, {})
    if isinstance(saved, dict):
        known = set(current)
        for binding, name in saved.items():
            # A stale file from an older version names bindings that no longer
            # exist, and a hand-edited one can hold anything at all.
            if binding in known and isinstance(name, str) and name:
                current[binding] = name.lower()
    return current


def current():
    global _current
    if _current is None:
        _current = _load()
    return dict(_current)


def reload():
    """Forget the cache; the next read goes back to the file."""
    global _current, _revision
    _current = None
    _revision += 1


def revision():
    """Counts the changes. Whoever caches a resolved key watches this."""
    return _revision


def key_for(binding):
    return current().get(binding, "")


def binding_for(name):
    """Which binding a pressed key triggers, or None.

    Ties cannot happen through `assign`, which frees the previous holder, but
    a hand-written file can hold them: the catalogue order decides, so the
    answer is at least always the same one.
    """
    if not name:
        return None
    name = name.lower()
    active = current()
    for binding in bindings():
        if active.get(binding) == name:
            return binding
    return None


def duplicates():
    """The bindings sharing a key. Empty is the healthy case."""
    seen = {}
    for binding in bindings():
        seen.setdefault(key_for(binding), []).append(binding)
    clashing = set()
    for key, holders in seen.items():
        if key and len(holders) > 1:
            clashing.update(holders)
    return clashing


def label(binding):
    """What the action panel and the settings screen print on a key cap."""
    return key_label(key_for(binding))


def key_label(name):
    if not name:
        return "—"
    if len(name) == 1:
        return name.upper()
    # "space", "left"… read better translated. `i18n.t` has no default, so the
    # raw value is asked for and the key name stands in when it is missing.
    from . import i18n
    pretty = i18n.data("keys.name_%s" % name.replace(" ", "_"))
    return pretty if isinstance(pretty, str) else name.upper()


# --------------------------------------------------------------- writing ----
def _bump():
    global _revision
    _revision += 1
    _save()


def _save():
    """Only what differs from the defaults, so a later rebalance can land."""
    base = defaults()
    diff = {b: k for b, k in current().items() if base.get(b) != k}
    return prefs.write(PREFERENCE, diff)


def assign(binding, name):
    """Give `binding` that key, taking it from whoever held it.

    Returns the binding that lost its key, or None. Refuses a reserved key
    and returns False, which the screen tells apart from None.
    """
    global _current
    if binding not in set(bindings()) or not name:
        return False
    name = name.lower()
    if name in RESERVED:
        return False
    active = current()
    freed = None
    for other in bindings():
        if active.get(other) == name and other != binding:
            freed = other
            active[other] = ""
    active[binding] = name
    _current = active
    _bump()
    return freed


def apply_preset(preset):
    global _current
    if preset not in PRESETS:
        return False
    active = defaults()
    active.update(PRESETS[preset])
    _current = active
    _bump()
    return True


def preset_in_use():
    """The preset the current keymap matches, or None once it was tweaked."""
    active = current()
    for name in PRESET_ORDER:
        wanted = defaults()
        wanted.update(PRESETS[name])
        if wanted == active:
            return name
    return None


def reset():
    global _current
    _current = defaults()
    _bump()

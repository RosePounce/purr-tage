# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Translation of the interface and of the game texts.

One language = one JSON file in `purrtage/locales/`: "fr.json", "en.json"…
Adding one only takes dropping one more file in there — the code keeps no list
of languages up to date. The player can also drop their own file into
`<data folder>/locales/`, which makes it possible to translate the game without
rebuilding it; on a name clash, theirs wins.

The keys are hierarchical and written with dots:

    i18n.t("messages.pop_full")
    i18n.t("hud.population", pop=12, limit=15)

French is the reference language: a key missing from the current language is
taken from there, and a key missing everywhere is returned as is — plainly
visible on screen rather than silently empty.

The game's proper nouns go through here as labels only; the identifiers
(`kitten`, `basket`, `kibble`…) belong to the code.
"""

import json
import locale as _locale
import os
import sys

from . import paths
from . import prefs

REFERENCE = "fr"          # reference language, and fallback for all others

_catalogs = {}            # code -> loaded catalog
_files = None             # code -> file path, None = not scanned yet
_language = REFERENCE


# ---------------------------------------------------------------- catalogs ----
def locale_dirs():
    """Folders searched for languages, from the lowest to the highest priority."""
    dirs = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")]
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        dirs.append(os.path.join(bundle, "purrtage", "locales"))
    try:
        dirs.append(os.path.join(paths.data_dir(), "locales"))
    except Exception:
        pass
    return dirs


def _scan(force=False):
    """The language files that were found: {code: path}."""
    global _files
    if _files is not None and not force:
        return _files
    found = {}
    for folder in locale_dirs():
        if not os.path.isdir(folder):
            continue
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for name in names:
            if name.startswith("_") or not name.endswith(".json"):
                continue
            found[name[:-5].lower()] = os.path.join(folder, name)
    _files = found
    return found


def catalog(code):
    """A language catalog, loaded only once. {} when unreadable."""
    code = (code or "").lower()
    if code in _catalogs:
        return _catalogs[code]
    path = _scan().get(code)
    data = {}
    if path:
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            print("Unreadable language \"%s\" (%s): %s" % (code, path, exc),
                  file=sys.stderr)
            data = {}
    if not isinstance(data, dict):
        data = {}
    _catalogs[code] = data
    return data


def reload():
    """Forget the in-memory catalogs: useful after editing a file."""
    _catalogs.clear()
    _scan(force=True)


def available():
    """Installed languages: [(code, name in that language), …], reference first."""
    out = []
    for code in _scan():
        name = _lookup(catalog(code), "language.name")
        out.append((code, name if isinstance(name, str) else code.upper()))
    out.sort(key=lambda item: (item[0] != REFERENCE, item[1].lower()))
    return out


def codes():
    """The codes of the installed languages, in display order."""
    return [code for code, _name in available()]


# ----------------------------------------------------------------- lookup ----
def _lookup(node, key):
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def data(key, default=None):
    """The raw value of a key: a string, a list or a dictionary."""
    for code in (_language, REFERENCE):
        value = _lookup(catalog(code), key)
        if value is not None:
            return value
    return default


def _format(value, fields):
    if not fields:
        return value
    try:
        return value.format(**fields)
    except (KeyError, IndexError, ValueError):
        return value          # bad field: the raw text beats nothing at all


def t(key, **fields):
    """The text of a key, with its fields: `t("hud.army", count=3)`."""
    value = data(key)
    if not isinstance(value, str):
        return key
    return _format(value, fields)


def tp(key, count, **fields):
    """Pluralised text: the key carries the "one" and "other" forms."""
    node = data(key)
    if isinstance(node, dict):
        value = node.get("one" if abs(count) == 1 else "other")
        if not isinstance(value, str):
            value = node.get("other")
    else:
        value = node
    if not isinstance(value, str):
        return key
    fields.setdefault("count", count)
    return _format(value, fields)


def lines(key):
    """A list of strings (a paragraph split up by the translator)."""
    value = data(key)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    if isinstance(value, str):
        return [value]
    return []


# -------------------------------------------------------- current language ----
def language():
    return _language


def language_name(code=None):
    code = code or _language
    name = _lookup(catalog(code), "language.name")
    return name if isinstance(name, str) else code.upper()


def set_language(code):
    """Pick the language. Returns the one that was actually applied."""
    global _language
    code = (code or "").lower()
    _language = code if code in _scan() else REFERENCE
    return _language


def next_language(code=None):
    """The next language in the list, for a button that cycles through them."""
    order = codes() or [REFERENCE]
    try:
        index = order.index(code or _language)
    except ValueError:
        return order[0]
    return order[(index + 1) % len(order)]


# --------------------------------------------------------- player's choice ----
def preference():
    """The language remembered at the last launch, or None."""
    code = prefs.get("language")
    return code.lower() if isinstance(code, str) else None


def remember(code):
    """Remember the language for the next games. Silent on failure."""
    return prefs.write("language", code)


def _system_tags():
    """The language tags advertised by the system, the most reliable first."""
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(name)
        if value:
            for tag in value.split(":"):
                if tag:
                    yield tag
    try:
        tag = _locale.getdefaultlocale()[0]
    except (ValueError, TypeError):
        tag = None
    if tag:
        yield tag


def detect():
    """The language to use: remembered choice, else the system one, else French."""
    installed = _scan()
    saved = preference()
    if saved in installed:
        return saved
    for tag in _system_tags():
        code = tag.split(".")[0].replace("-", "_").split("_")[0].lower()
        if code in installed:
            return code
    return REFERENCE


# -------------------------------------------------- labels of the game data ----
def _text(key, fallback):
    value = data(key)
    return value if isinstance(value, str) else fallback


def unit_name(utype):
    return _text("units.%s.name" % utype, utype)


def unit_short(utype):
    return _text("units.%s.short" % utype, unit_name(utype))


def unit_role(utype):
    return _text("units.%s.role" % utype, "")


def unit_desc(utype):
    return _text("units.%s.desc" % utype, "")


def unit_gender(utype):
    return _text("units.%s.gender" % utype, "m")


def building_name(btype):
    return _text("buildings.%s.name" % btype, btype)


def building_short(btype):
    return _text("buildings.%s.short" % btype, building_name(btype))


def building_desc(btype):
    return _text("buildings.%s.desc" % btype, "")


def building_gender(btype):
    return _text("buildings.%s.gender" % btype, "m")


def upgrade_name(key):
    return _text("upgrades.%s.name" % key, key)


def upgrade_short(key):
    return _text("upgrades.%s.short" % key, upgrade_name(key))


def upgrade_desc(key):
    return _text("upgrades.%s.desc" % key, "")


def resource_name(kind):
    return _text("resources.%s.name" % kind, kind)


def resource_short(kind):
    return _text("resources.%s.short" % kind, resource_name(kind))


def difficulty_name(key):
    return _text("difficulties.%s.name" % key, key)


def team_name(team):
    return _text("teams.%d" % team, "%d" % team)


def map_size_name(side):
    """The label of a map side: medium for 96; off the list, "200 x 200"."""
    return _text("map_sizes.%d" % side, "%d x %d" % (side, side))

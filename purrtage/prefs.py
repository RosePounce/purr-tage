# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""The player's settings, kept between launches.

One JSON file, `preferences.json`, in the writable data folder. The language
lived here first and `purrtage/i18n.py` owned the reading and the writing; the
keymap needs the same file, so the store moved out here rather than being
written a second time.

Every call is silent on failure. A settings file that cannot be read or
written must never stop a game from starting: the defaults take over and the
player loses a preference, not their evening.
"""

import json
import os

from . import paths

FILE = "preferences.json"


def path():
    return os.path.join(paths.data_dir(), FILE)


def read():
    """The whole file as a dict. An empty one when anything goes wrong."""
    try:
        with open(path(), encoding="utf-8") as fh:
            saved = json.load(fh)
        return saved if isinstance(saved, dict) else {}
    except (OSError, ValueError):
        return {}


def get(key, default=None):
    value = read().get(key, default)
    return default if value is None else value


def write(key, value):
    """Store one entry, keeping the others. True when it reached the disk."""
    saved = read()
    saved[key] = value
    try:
        paths.ensure()
        with open(path(), "w", encoding="utf-8") as fh:
            json.dump(saved, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
    except OSError:
        return False
    return True

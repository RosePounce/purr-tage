# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where the game is allowed to write.

Run from the sources, it writes next to the project, which is handy while
developing. Installed — under `C:\\Program Files` or `/usr/bin` — that folder
is read-only: bug reports then go to the player's home directory, at the usual
spot for each system.

The game was called "La Guerre des Chats" up to version 1.0: a player coming
from there has their reports and settings under the old name. We adopt them
once and for all on the first launch, rather than letting them believe they
lost everything.
"""

import os
import sys

APP_NAME = "Purrtage"
UNIX_NAME = "purrtage"

# Former names, adopted exactly once if they are still lying around.
LEGACY_APP_NAME = "LaGuerreDesChats"
LEGACY_UNIX_NAME = "la-guerre-des-chats"


def is_frozen():
    """True when the game runs from a packaged executable (PyInstaller)."""
    return getattr(sys, "frozen", False)


def install_dir():
    """The folder the game is launched from."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _system_data_dir(name=APP_NAME, unix_name=UNIX_NAME):
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, name)
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library",
                            "Application Support", name)
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, unix_name)


def _adopt_legacy_dir(path):
    """Rename the folder of the game's former name, exactly once.

    We touch nothing if the new folder already exists: current data always
    wins over older data. And if the rename fails — permissions, a different
    drive — so be it: the game starts from an empty folder rather than
    refusing to run.
    """
    if os.path.exists(path):
        return path
    legacy = _system_data_dir(LEGACY_APP_NAME, LEGACY_UNIX_NAME)
    if legacy == path or not os.path.isdir(legacy):
        return path
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        os.rename(legacy, path)
    except OSError:
        pass
    return path


def data_dir():
    """The writable folder for saves and reports.

    From the sources: the project folder. Installed, or when the install
    folder is not writable: the player's home directory.
    """
    if not is_frozen():
        here = install_dir()
        if os.access(here, os.W_OK):
            return here
    return _adopt_legacy_dir(_system_data_dir())


def ensure(*parts):
    """Build a path under `data_dir()` and create the folders as needed."""
    path = os.path.join(data_dir(), *parts)
    os.makedirs(path, exist_ok=True)
    return path


def open_folder(path):
    """Show a folder in the system's file manager. Returns True if launched.

    PyInstaller points LD_LIBRARY_PATH at its own libraries; a file manager
    started with them may refuse to run, so it gets the original value back.
    """
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)              # noqa: only exists on Windows
            return True
        import subprocess
        env = dict(os.environ)
        if is_frozen():
            original = env.pop("LD_LIBRARY_PATH_ORIG", None)
            if original is not None:
                env["LD_LIBRARY_PATH"] = original
            else:
                env.pop("LD_LIBRARY_PATH", None)
        command = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([command, path], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

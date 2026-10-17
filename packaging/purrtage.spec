# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe — identical on Windows and on Linux.

Nothing is drawn from a file: all the graphics and all the sound are
synthesised by the code. The only bundled resources are the language files
from `purrtage/locales/`; the rest of the package is Python, pygame and its
SDL.
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(SPEC), ".."))
PACKAGING = os.path.join(ROOT, "packaging")
WINDOWS = sys.platform.startswith("win")

icon = os.path.join(PACKAGING, "icon.ico" if WINDOWS else "icon.png")
if not os.path.exists(icon):
    icon = None

# The translations travel as they are: the player can add one by dropping an
# extra file next to them, or in their home directory.
LOCALES = [(os.path.join(ROOT, "purrtage", "locales"),
            os.path.join("purrtage", "locales"))]

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=LOCALES,
    # certifi carries its own certificates: the bundled OpenSSL does not
    # always find the system's, and bug reports go out over HTTPS.
    hiddenimports=["certifi"],
    hookspath=[],
    runtime_hooks=[],
    # Slims the package down. We stick to the modules we are sure about:
    # `xml` and `email` look useless but `pkg_resources` loads them at start-up.
    excludes=["tkinter", "numpy", "matplotlib", "PIL", "pydoc", "doctest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Purrtage",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # no black window behind the game
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Purrtage",
)

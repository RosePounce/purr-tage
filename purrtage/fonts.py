# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Font loading, with a fallback when the SDL_ttf module is unavailable.

On some installations — typically pygame built from source because no wheel
exists for the Python version in use — `pygame.font` fails to load. pygame
then ships `pygame.ftfont`, a drop-in replacement built on FreeType with the
same API: we switch to it automatically instead of crashing.
"""

import sys

from . import i18n

SIZES = (18, 21, 26, 34, 62)      # reference sizes, in interface units


def _try_backend(name):
    """Return the font module if it really works, otherwise None."""
    try:
        __import__(name)
        module = sys.modules[name]
        if not module.get_init():
            module.init()
        module.Font(None, 16).render(u"é", True, (255, 255, 255))
        return module
    except Exception:                      # ImportError, OSError, pygame.error…
        return None


def font_backend():
    """A usable font module, or `RuntimeError` explaining what to do."""
    errors = []
    for name in ("pygame.font", "pygame.ftfont"):
        module = _try_backend(name)
        if module is not None:
            return module
        errors.append(name)
    try:
        import pygame
        pygame.font.Font(None, 16)         # triggers the original error
    except Exception as exc:
        detail = "%s: %s" % (type(exc).__name__, exc)
    else:
        detail = i18n.t("fonts.no_backend", modules=", ".join(errors))
    raise RuntimeError(i18n.t("fonts.error", detail=detail,
                              major=sys.version_info[0],
                              minor=sys.version_info[1]))


def load_fonts(scale=1.0, sizes=SIZES):
    """The game's five fonts, from the smallest to the largest.

    `scale` follows the window resolution: the fonts are vector based, so
    asking for a larger size gives crisp text, never a blurry one.
    """
    module = font_backend()
    return tuple(module.Font(None, max(8, int(round(size * scale))))
                 for size in sizes)

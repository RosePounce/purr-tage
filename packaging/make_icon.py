# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the application icon from the game sprites.

Like everything else, it is drawn by the code: no image to version. Produces
`build/icon.png` and, when Pillow is available, `build/icon.ico` for Windows.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import pygame                                                  # noqa: E402

pygame.init()
pygame.display.set_mode((64, 64))

from purrtage import sprites                                   # noqa: E402

SIZE = 512
CORNER = 96        # corner rounding


def render():
    sprites.set_asset_scale(2.0)
    surf = pygame.Surface((SIZE, SIZE), pygame.SRCALPHA)
    # background: the game's green gradient, rounded corners
    for i in range(SIZE):
        k = i / float(SIZE)
        color = (int(92 + 26 * k), int(140 + 24 * k), int(78 + 18 * k))
        pygame.draw.rect(surf, color, (0, i, SIZE, 1))
    mask = pygame.Surface((SIZE, SIZE), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(),
                     border_radius=CORNER)
    surf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)

    cat = sprites.unit_sprite("scratcher", 0, 0, 1)
    ratio = (SIZE * 0.78) / cat.get_width()
    cat = pygame.transform.smoothscale(
        cat, (int(cat.get_width() * ratio), int(cat.get_height() * ratio)))
    surf.blit(cat, (SIZE // 2 - cat.get_width() // 2,
                    SIZE // 2 - cat.get_height() // 2 + int(SIZE * 0.04)))

    border = pygame.Surface((SIZE, SIZE), pygame.SRCALPHA)
    pygame.draw.rect(border, (42, 54, 44, 230), border.get_rect(), 14,
                     border_radius=CORNER)
    surf.blit(border, (0, 0))
    return surf


def main():
    surf = render()
    png = os.path.join(HERE, "icon.png")
    pygame.image.save(surf, png)
    print("written:", png)

    try:
        from PIL import Image
    except ImportError:
        print("Pillow missing: no .ico (only Windows needs one)")
        return 0
    img = Image.open(png)
    ico = os.path.join(HERE, "icon.ico")
    img.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                         (64, 64), (128, 128), (256, 256)])
    print("written:", ico)
    return 0


if __name__ == "__main__":
    sys.exit(main())

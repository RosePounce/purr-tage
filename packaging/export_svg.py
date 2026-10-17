# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Export the game sprites as SVG.

All the art goes through `_P`, the small painter of `purrtage.sprites`, whose
API is entirely vector based: ellipses, circles, rounded rectangles, polygons,
lines and polylines. Each one has an exact SVG counterpart.

Rather than drawing the cats a second time — two versions to keep in sync, and
one day two different cats — we swap the painter for a recorder that speaks the
same language, and let the drawing code run as it is. The art stays written in
a single place.

    python packaging/export_svg.py                  # into build/svg/
    python packaging/export_svg.py my/folder --team 1

The terrain tiles are left out: they are painted pixel by pixel, and an SVG
with one element per pixel would do nobody any good.
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
from purrtage.settings import (BUILDINGS, RESOURCES, TEAM_COLORS,  # noqa: E402
                               TILE, UNIT_ORDER)

# The game's polylines are mostly used for the cats' tails: a round cap suits
# them better than pygame's flat cut. Set "butt" to match the in-game
# rendering down to the pixel.
LINECAP = "round"


def _paint(color):
    """A pygame color -> (SVG paint, opacity); None when fully opaque."""
    values = tuple(color)
    r, g, b = (int(c) for c in values[:3])
    alpha = int(values[3]) if len(values) > 3 else 255
    paint = "rgb(%d,%d,%d)" % (r, g, b)
    if alpha >= 255:
        return paint, None
    return paint, round(alpha / 255.0, 4)


def _n(value):
    """A short number: SVG has no use for the decimal noise of floats."""
    return ("%.3f" % float(value)).rstrip("0").rstrip(".") or "0"


class _Shadow(object):
    """Stands in for `_P.surf`.

    The drop shadow is the only stroke that does not go through the painter:
    the sprites compose it separately, then blit it. We catch it here for what
    it is, a translucent ellipse.
    """

    def __init__(self, painter):
        self._painter = painter

    def blit(self, source, position):
        w, h = source.get_size()
        color = source.get_at((w // 2, h // 2))
        self._painter.ell(color, position[0] + w / 2.0, position[1] + h / 2.0,
                          w / 2.0, h / 2.0)


class SvgPainter(object):
    """The same API as `purrtage.sprites._P`, but it writes SVG.

    The coordinates stay logical: `ss` is 1, so the sprite computations have
    nothing to adapt. The drawing order becomes the document order, which is
    exactly the way SVG paints.
    """

    def __init__(self, w, h, ss=None):
        self.w, self.h = w, h
        self.ss = 1.0              # no point supersampling vector output
        self.surf = _Shadow(self)
        self.parts = []

    def _add(self, tag, attributes, color, stroke=False):
        paint, opacity = _paint(color)
        if stroke:
            attributes.append(("fill", "none"))
            attributes.append(("stroke", paint))
            if opacity is not None:
                attributes.append(("stroke-opacity", opacity))
        else:
            attributes.append(("fill", paint))
            if opacity is not None:
                attributes.append(("fill-opacity", opacity))
        body = " ".join('%s="%s"' % (key, val) for key, val in attributes)
        self.parts.append("  <%s %s/>" % (tag, body))

    def ell(self, color, cx, cy, rx, ry):
        self._add("ellipse", [("cx", _n(cx)), ("cy", _n(cy)),
                              ("rx", _n(max(rx, 0.5))),
                              ("ry", _n(max(ry, 0.5)))], color)

    def circ(self, color, cx, cy, r):
        self._add("circle", [("cx", _n(cx)), ("cy", _n(cy)),
                             ("r", _n(max(r, 0.5)))], color)

    def rect(self, color, x, y, w, h, radius=0):
        attributes = [("x", _n(x)), ("y", _n(y)),
                      ("width", _n(max(w, 0.5))), ("height", _n(max(h, 0.5)))]
        if radius:
            attributes.append(("rx", _n(radius)))
        self._add("rect", attributes, color)

    def poly(self, color, pts):
        points = " ".join("%s,%s" % (_n(x), _n(y)) for x, y in pts)
        self._add("polygon", [("points", points)], color)

    def line(self, color, a, b, width=1.0):
        self._add("line", [("x1", _n(a[0])), ("y1", _n(a[1])),
                           ("x2", _n(b[0])), ("y2", _n(b[1])),
                           ("stroke-width", _n(max(width, 0.4)))],
                  color, stroke=True)

    def curve(self, color, pts, width=1.0):
        if len(pts) < 2:
            return
        points = " ".join("%s,%s" % (_n(x), _n(y)) for x, y in pts)
        self._add("polyline", [("points", points),
                               ("stroke-width", _n(max(width, 0.4))),
                               ("stroke-linejoin", "round"),
                               ("stroke-linecap", LINECAP)],
                  color, stroke=True)

    def done(self, w=None, h=None):
        w = float(w or self.w)
        h = float(h or self.h)
        header = ('<svg xmlns="http://www.w3.org/2000/svg" '
                  'viewBox="0 0 %s %s" width="%s" height="%s" '
                  'shape-rendering="geometricPrecision">'
                  % (_n(w), _n(h), _n(w), _n(h)))
        return "\n".join([header] + self.parts + ["</svg>", ""])


def check_api():
    """Has the game painter gained a primitive the export ignores?

    Without this guard rail, a new method in `_P` would break nothing: it
    would raise an obscure error in the middle of a sprite, or worse, emit a
    truncated SVG without saying a word.
    """
    primitives = set()
    for name in dir(sprites._P):
        if not name.startswith("_") and callable(getattr(sprites._P, name)):
            primitives.add(name)
    missing = sorted(primitives - set(dir(SvgPainter)))
    if missing:
        raise RuntimeError(
            "the game painter can do %s, the SVG export cannot"
            % ", ".join(missing))


def _clear_caches():
    """Clear the sprite caches, in both directions.

    A cache filled by a running game would return pygame surfaces where the
    export expects SVG; a cache filled by the export would return SVG where
    the game expects surfaces.

    We only clear the `_*_cache` entries: the module keeps other dictionaries,
    the cats' coats among them, which must not be touched.
    """
    for name, value in vars(sprites).items():
        if name.endswith("_cache") and isinstance(value, dict):
            value.clear()


def _write(folder, name, svg):
    path = os.path.join(folder, "%s.svg" % name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg)
    return path


def export(folder, team=0):
    """Write one SVG per exportable sprite. Returns the paths written."""
    check_api()
    color = TEAM_COLORS[team % len(TEAM_COLORS)]
    os.makedirs(folder, exist_ok=True)
    written = []

    painter = sprites._P
    sprites._P = SvgPainter
    # Before, because a sprite already drawn by the game would come back from
    # the cache as a pygame surface; after, so as not to leave SVG behind.
    _clear_caches()
    try:
        for utype in UNIT_ORDER:
            for frame in range(4):
                written.append(_write(
                    folder, "cat-%s-%d" % (utype, frame),
                    sprites._draw_cat(utype, color, frame)))
        for btype, spec in BUILDINGS.items():
            written.append(_write(
                folder, "building-%s" % btype,
                sprites._draw_building(btype, color, spec["size"] * TILE)))
            # The higher levels of a tower, "building-tower-2" and so on.
            for level in range(2, 2 + len(spec.get("levels", ()))):
                written.append(_write(
                    folder, "building-%s-%d" % (btype, level),
                    sprites._draw_building(btype, color, spec["size"] * TILE,
                                           level)))
        for kind in RESOURCES:
            for variant in range(3):
                written.append(_write(
                    folder, "node-%s-%d" % (kind, variant),
                    sprites._draw_node(kind, variant, 4)))
        for variant in range(4):
            written.append(_write(folder, "decor-%d" % variant,
                                  sprites.decor_sprite(variant)))
    finally:
        sprites._P = painter
        _clear_caches()
    return written


def main(argv=None):
    import argparse

    default = os.path.join(os.path.dirname(HERE), "build", "svg")
    parser = argparse.ArgumentParser(
        description="Export the game sprites as SVG.")
    parser.add_argument("folder", nargs="?", default=default,
                        help="where to write the files (default: build/svg)")
    parser.add_argument("--team", "--equipe", dest="team", type=int, default=0,
                        help="team color, 0 or 1")
    args = parser.parse_args(argv)

    written = export(args.folder, args.team)
    print("%d files written in %s" % (len(written), args.folder))
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Maps drawn in the editor: the binary format, the files, the checks.

A map file is a short header followed by a zlib-compressed body:

    header   b"PURRMAP" then the format version, one byte
    body     width, height                      u16 each
             seed (bushes, nothing else)        u32
             name                               u8 length, then UTF-8
             terrain                            width x height bytes, by rows
             bases                              u8 count, then tx, ty u16
             nodes                              u32 count, then for each:
                                                kind u8 (index in RESOURCES),
                                                variant u8, tx u16, ty u16,
                                                amount u16

Everything is big-endian. The same bytes travel over the network when the
host plays a map of its own, so that both machines build the very same world.
"""

import base64
import os
import re
import struct
import zlib

from . import paths
from .settings import RESOURCES, T_FLOWER, TERRAIN_WALKABLE
from .world import World

MAGIC = b"PURRMAP"
VERSION = 1
EXTENSION = ".pmap"
MAPS_DIR = "saves/maps"      # under paths.data_dir(), next to the reports

MIN_SIDE, MAX_SIDE = 16, 256
MAX_NAME_BYTES = 120
BASES = 2                    # the game is a duel

_HEAD = struct.Struct("!HHI")
_BASE = struct.Struct("!HH")
_NODE = struct.Struct("!BBHHH")
_COUNT8 = struct.Struct("!B")
_COUNT32 = struct.Struct("!I")


class MapError(ValueError):
    """A file that is not a map, or a damaged one."""


# ------------------------------------------------------------------ format ---
def encode(world):
    """The map as bytes: terrain, bases and nodes, not the game in progress."""
    name = world.name.encode("utf-8")[:MAX_NAME_BYTES]
    out = [_HEAD.pack(world.w, world.h, world.seed & 0xFFFFFFFF),
           _COUNT8.pack(len(name)), name]
    out.extend(bytes(row) for row in world.terrain)
    out.append(_COUNT8.pack(len(world.start_tiles)))
    out.extend(_BASE.pack(tx, ty) for (tx, ty) in world.start_tiles)
    nodes = [n for n in world.nodes if n.alive]
    out.append(_COUNT32.pack(len(nodes)))
    out.extend(_NODE.pack(RESOURCES.index(n.kind), n.variant, n.tx, n.ty,
                          min(int(n.max_amount), 0xFFFF)) for n in nodes)
    return MAGIC + bytes((VERSION,)) + zlib.compress(b"".join(out), 9)


class _Reader(object):
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def take(self, n):
        if self.pos + n > len(self.data):
            raise MapError("truncated map")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def unpack(self, fmt):
        return fmt.unpack(self.take(fmt.size))


def decode(data):
    """Build the `World` a map file describes. Raises `MapError`."""
    if not data.startswith(MAGIC) or len(data) < len(MAGIC) + 1:
        raise MapError("not a map file")
    version = data[len(MAGIC)]
    if version != VERSION:
        raise MapError("unknown map version %d" % version)
    try:
        body = zlib.decompress(data[len(MAGIC) + 1:])
    except zlib.error as exc:
        raise MapError("damaged map: %s" % exc)
    r = _Reader(body)

    w, h, seed = r.unpack(_HEAD)
    if not (MIN_SIDE <= w <= MAX_SIDE and MIN_SIDE <= h <= MAX_SIDE):
        raise MapError("map size out of range: %dx%d" % (w, h))
    (length,) = r.unpack(_COUNT8)
    name = r.take(length).decode("utf-8", "replace")

    world = World(seed, w, generate=False)
    world.h = h
    world.terrain = [bytearray(r.take(w)) for _ in range(h)]
    world.blocked = [bytearray(w) for _ in range(h)]
    world.name = name
    if any(t > T_FLOWER for row in world.terrain for t in row):
        raise MapError("unknown terrain")

    (count,) = r.unpack(_COUNT8)
    world.start_tiles = [r.unpack(_BASE) for _ in range(count)]
    if any(not world.in_bounds(tx, ty) for (tx, ty) in world.start_tiles):
        raise MapError("base outside the map")

    (count,) = r.unpack(_COUNT32)
    for _ in range(count):
        kind, variant, tx, ty, amount = r.unpack(_NODE)
        if kind >= len(RESOURCES) or not world.in_bounds(tx, ty):
            raise MapError("bad resource node")
        world.put_node(RESOURCES[kind], tx, ty, amount or None, variant % 3)
    world.finish()
    return world


def to_text(world):
    """The map as ASCII, to travel inside a JSON message."""
    return base64.b64encode(encode(world)).decode("ascii")


def from_text(text):
    try:
        data = base64.b64decode(text.encode("ascii"), validate=True)
    except (ValueError, UnicodeError) as exc:
        raise MapError("damaged map: %s" % exc)
    return decode(data)


# ------------------------------------------------------------------- checks ---
def problems(world):
    """What keeps a map from being played, as `editor.problems.*` keys.

    An empty list means the map is good to go.
    """
    out = []
    if len(world.start_tiles) != BASES:
        return ["editor.problems.bases"]
    for start in world.start_tiles:
        for (tx, ty) in world.base_footprint(start):
            if (not world.in_bounds(tx, ty)
                    or not TERRAIN_WALKABLE[world.terrain[ty][tx]]
                    or (tx, ty) in world.node_at):
                out.append("editor.problems.base_blocked")
                break
    a, b = world.start_tiles
    if abs(a[0] - b[0]) < 4 and abs(a[1] - b[1]) < 4:
        out.append("editor.problems.bases_overlap")
    if not out and not world.bases_connected():
        out.append("editor.problems.not_connected")
    return out


# -------------------------------------------------------------------- files ---
def maps_dir():
    """The maps folder, created as needed."""
    return paths.ensure(*MAPS_DIR.split("/"))


def file_name(name):
    """A file name drawn from the map name: letters, digits and dashes."""
    stem = re.sub(r"[^\w-]+", "_", name.strip(), flags=re.UNICODE).strip("_")
    return (stem or "map")[:60] + EXTENSION


def save(world, path=None):
    """Write the map, by default under its own name. Returns the path."""
    path = path or os.path.join(maps_dir(), file_name(world.name))
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(encode(world))
    os.replace(tmp, path)
    return path


def load(path):
    with open(path, "rb") as f:
        return decode(f.read())


def list_maps():
    """The readable maps of the maps folder: [(path, name, size)], by name.

    A damaged file is left out rather than failing the whole list.
    """
    folder = maps_dir()
    out = []
    for entry in sorted(os.listdir(folder)):
        if not entry.endswith(EXTENSION):
            continue
        path = os.path.join(folder, entry)
        try:
            world = load(path)
        except (OSError, MapError):
            continue
        out.append((path, world.name or entry[:-len(EXTENSION)], world.w))
    out.sort(key=lambda item: item[1].lower())
    return out

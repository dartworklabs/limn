"""The Limn mark: one stroke that starts at a small dot (the pin) and runs into a line (the source line).

The geometry lives here once, on the 24-unit grid the viewer's Lucide icons use, and three forms are drawn from it:

- inline_svg(): the viewer's markup. It carries classes (limn-mark*), never colours - the stylesheet fills the tile with the
  instance accent (--brand) or the foreground, so the mark follows the theme (docs/handbook/viewer.md §마크와 파비콘).
- favicon_svg(accent): a self-contained SVG for the favicon data URL, tile in the accent, glyph white.
- png(size, accent): the same picture as a PNG, for browsers and home screens that do not take SVG icons. Drawn with
  signed distances (one sample per pixel, coverage from the distance to each shape's edge) and written with zlib, so the
  server stays standard-library only and there is no checked-in image to fall out of step with the geometry.

Pure: no files, no clock and no state beyond the constants below - png() memoises its result per (size, accent,
rounded), which changes nothing observable.
"""

from __future__ import annotations

import functools
import math
import re
import struct
import zlib

GRID = 24.0
TILE_RADIUS = 5.5  # the tile's corner radius (about the viewer's --radius-lg at 44px)
DOT = (8.0, 8.0, 2.6)  # the pin: centre x, centre y, radius
STROKE = 2.4  # the line's width (round caps); the dot is a little over twice as wide
CORNER = (11.75, 13.5, 3.75)  # the quarter turn: centre x, centre y, radius
LINE_Y = CORNER[1] + CORNER[2]  # the source line's height: 17.25
LINE_END = 17.2  # where the source line stops (the round cap reaches 1.2 further)
# The stroke from the dot's centre: down, a quarter turn to the right, then along the line.
PATH = "M8 8V13.5a3.75 3.75 0 0 0 3.75 3.75H17.2"
ACCENT_RE = re.compile(r"#[0-9a-fA-F]{6}")


def inline_svg() -> str:
    """The viewer's markup for the mark: a tile, the dot and the stroke, coloured only through the classes
    limn-mark-tile, limn-mark-dot and limn-mark-line - never plain .mark, which is the pin box on the PDF that marks()
    removes and redraws. Decorative (aria-hidden) - the label or heading next to it names the thing."""
    return (
        '<svg class="limn-mark" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<rect class="limn-mark-tile" width="24" height="24" rx="%g"/>'
        '<circle class="limn-mark-dot" cx="%g" cy="%g" r="%g"/>'
        '<path class="limn-mark-line" d="%s" stroke-width="%g" stroke-linecap="round" stroke-linejoin="round"/></svg>'
        % (TILE_RADIUS, DOT[0], DOT[1], DOT[2], PATH, STROKE)
    )


def favicon_svg(accent: str) -> str:
    """The mark as a standalone SVG document: the tile in accent (#rrggbb), the dot and the stroke in white. ValueError
    for any other accent string - it is written into markup."""
    _rgb(accent)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<rect width="24" height="24" rx="%g" fill="%s"/>'
        '<circle cx="%g" cy="%g" r="%g" fill="#ffffff"/>'
        '<path d="%s" fill="none" stroke="#ffffff" stroke-width="%g" stroke-linecap="round" stroke-linejoin="round"/>'
        "</svg>" % (TILE_RADIUS, accent, DOT[0], DOT[1], DOT[2], PATH, STROKE)
    )


def _rgb(accent: str) -> tuple[int, int, int]:
    """'#1d4ed8' -> (29, 78, 216); ValueError unless accent is exactly #rrggbb."""
    if not isinstance(accent, str) or not ACCENT_RE.fullmatch(accent):
        raise ValueError("accent must be #rrggbb: %r" % (accent,))
    return int(accent[1:3], 16), int(accent[3:5], 16), int(accent[5:7], 16)


def _segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Distance from (px, py) to the segment a-b."""
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def _corner(px: float, py: float) -> float:
    """Distance from (px, py) to the quarter circle that turns the stroke from down to right (the arc below-left of
    its centre on screen, where y grows downwards)."""
    cx, cy, r = CORNER
    if px <= cx and py >= cy:
        return abs(math.hypot(px - cx, py - cy) - r)
    return min(math.hypot(px - cx + r, py - cy), math.hypot(px - cx, py - cy - r))


def glyph_distance(px: float, py: float) -> float:
    """Signed distance from grid point (px, py) to the glyph (dot and stroke): negative inside, positive outside."""
    dot = math.hypot(px - DOT[0], py - DOT[1]) - DOT[2]
    stem = _segment(px, py, DOT[0], DOT[1], DOT[0], CORNER[1])
    line = _segment(px, py, CORNER[0], LINE_Y, LINE_END, LINE_Y)
    return min(dot, min(stem, _corner(px, py), line) - STROKE / 2)


def tile_distance(px: float, py: float, rounded: bool = True) -> float:
    """Signed distance from grid point (px, py) to the tile: the full 24x24 square, with round corners unless not rounded."""
    r = TILE_RADIUS if rounded else 0.0
    h = GRID / 2 - r
    qx, qy = abs(px - GRID / 2) - h, abs(py - GRID / 2) - h
    return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r


def _coverage(d: float, pixel: float) -> float:
    """How much of a pixel (pixel grid units wide) a shape covers when its edge is d away from the pixel's centre."""
    return max(0.0, min(1.0, 0.5 - d / pixel))


@functools.lru_cache(maxsize=16)
def png(size: int, accent: str, rounded: bool = True) -> bytes:
    """The mark as a size x size RGBA PNG: the tile in accent, the glyph white on it. rounded=False gives a full
    square (an apple-touch-icon - iOS rounds it itself and would show transparent corners as black). ValueError for a
    bad accent or a size outside 8..512."""
    red, green, blue = _rgb(accent)
    if not isinstance(size, int) or not 8 <= size <= 512:
        raise ValueError("size must be 8..512: %r" % (size,))
    pixel = GRID / size
    rows = []
    for y in range(size):
        row = bytearray(b"\x00")  # filter type 0 (none) for every row
        py = (y + 0.5) * pixel
        for x in range(size):
            px = (x + 0.5) * pixel
            tile = _coverage(tile_distance(px, py, rounded), pixel)
            ink = _coverage(glyph_distance(px, py), pixel)
            row += bytes(
                (
                    round(red + (255 - red) * ink),
                    round(green + (255 - green) * ink),
                    round(blue + (255 - blue) * ink),
                    round(255 * tile),
                )
            )
        rows.append(bytes(row))

    def chunk(tag: bytes, data: bytes) -> bytes:
        """One PNG chunk: length, tag, data, CRC of tag + data."""
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA, no interlace
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )

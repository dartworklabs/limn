"""Page images as PNG, written with the standard library from the PPM pdftoppm draws.

pdftoppm's own PNG encoder spends about half of a page's render time choosing row filters and compressing hard. A page
image only has to reach the screen before PDF.js draws the page as vectors, so the bytes matter less than the time:
every row goes behind filter 0 (None) and the image is deflated at zlib level 1. The pixels are the PPM's, unchanged,
so the image decodes to exactly what `pdftoppm -png` would have stored. Pure functions: nothing here reads a file or
starts a process.
"""

import re
import struct
import zlib
from dataclasses import dataclass

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# The header pdftoppm writes before the pixels: P6, width, height, maxval 255, each after whitespace, and exactly one
# whitespace byte before the first pixel. No comments: pdftoppm writes none.
_PPM_HEAD = re.compile(rb"P6\s+(\d+)\s+(\d+)\s+(\d+)\s")
PIECE_BYTES = 1 << 20  # about this many raw bytes per compress call, so a page is never copied whole a second time
ZLIB_LEVEL = 1
INCH_M = 0.0254


@dataclass(frozen=True)
class Ppm:
    """One 8-bit RGB image: width and height in pixels, and its rows top to bottom (width * height * 3 bytes)."""

    width: int
    height: int
    pixels: memoryview


def parse_ppm(data: bytes) -> Ppm | None:
    """data as a binary PPM (P6) with maxval 255 and exactly width * height * 3 pixel bytes, the image
    `pdftoppm -singlefile` writes to stdout; None for anything else (another magic or maxval, a zero size, short or
    long pixel data), so a failed or garbled page never becomes an image of the wrong size."""
    m = _PPM_HEAD.match(data)
    if m is None:
        return None
    w, h, maxval = (int(g) for g in m.groups())
    if w <= 0 or h <= 0 or maxval != 255 or len(data) - m.end() != w * h * 3:
        return None
    return Ppm(w, h, memoryview(data)[m.end() :])


def _chunk(kind: bytes, body: bytes) -> bytes:
    """One PNG chunk: length, type, body and the CRC-32 of type and body."""
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def png_from_ppm(img: Ppm, dpi: int) -> bytes:
    """The PNG of img: IHDR (8-bit truecolour), pHYs (dpi in pixels per metre, truncated as pdftoppm writes it), one
    IDAT holding every row behind filter byte 0 deflated at ZLIB_LEVEL in pieces of about PIECE_BYTES, and IEND."""
    stride = img.width * 3
    rows_per_piece = max(1, PIECE_BYTES // (stride + 1))
    z = zlib.compressobj(ZLIB_LEVEL)
    parts = []
    for top in range(0, img.height, rows_per_piece):
        piece = bytearray()
        for y in range(top, min(img.height, top + rows_per_piece)):
            piece += b"\x00"
            piece += img.pixels[y * stride : (y + 1) * stride]
        parts.append(z.compress(piece))
    parts.append(z.flush())
    ppm_per_m = int(dpi / INCH_M)
    return (
        PNG_SIGNATURE
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", img.width, img.height, 8, 2, 0, 0, 0))
        + _chunk(b"pHYs", struct.pack(">IIB", ppm_per_m, ppm_per_m, 1))
        + _chunk(b"IDAT", b"".join(parts))
        + _chunk(b"IEND", b"")
    )

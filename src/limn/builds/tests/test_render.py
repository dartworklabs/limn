"""limn.builds.engine.render_pages and limn.builds.png - the page images of one build.

A build draws every page with its own pdftoppm process (a bounded pool) and turns each page's PPM into a PNG with the
standard library. The images must stay what `pdftoppm -png` made before, pixel for pixel and name for name, and a page
that cannot be drawn must fail the whole build without leaving a page folder a client could reach.

The real-poppler cases carry the `tex` marker (needs_tex); the rest use small pdfinfo/pdftoppm stand-ins on PATH.

Run: uv run pytest -q src/limn/builds/tests/test_render.py
"""

import os
import struct
import subprocess
import tempfile
import threading
import unittest
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from unittest import mock

from limn.builds import artifacts as build, engine as build_engine, png
from limn.builds.artifacts import PagesNotRendered

from helpers import needs_tex


@dataclass
class RenderDoc:
    """The part of a document render_pages reads: its state folder, PDF copy name and build state."""

    dir: Path
    pdf_name: str = "main.pdf"
    bstate: dict = field(default_factory=lambda: {"state": "running"})
    bstate_lock: threading.Lock = field(default_factory=threading.Lock)
    builds_lock: threading.Lock = field(default_factory=threading.Lock)


def rect_pdf(pages: int, size: tuple[int, int] = (200, 300)) -> bytes:
    """A valid PDF of `pages` pages of `size` points, each with a filled box and a stroked diagonal at a place and in a
    colour of its own (so page order shows in the pixels) - no fonts, so poppler draws it the same everywhere."""
    w, h = size
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    kids = []
    for i in range(pages):
        stream = b"%.2f %.2f %.2f rg %d %d 40 30 re f %.2f 0 0 RG 3 w 5 5 m %d %d l S" % (
            (i * 0.37) % 1,
            (i * 0.61) % 1,
            (i * 0.13) % 1,
            10 + (i * 13) % (w - 60),
            10 + (i * 29) % (h - 50),
            (i * 0.29) % 1,
            w - 5,
            h - 5 - i,
        )
        kids.append(len(objs) + 1)
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R >>" % (w, h, len(objs) + 2))
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objs[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), pages)
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return bytes(out)


def png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    """The (type, body) chunks of a PNG, each CRC checked; fails on a bad signature or CRC."""
    assert data[:8] == png.PNG_SIGNATURE, "not a PNG"
    out, i = [], 8
    while i < len(data):
        (n,) = struct.unpack(">I", data[i : i + 4])
        kind, body = data[i + 4 : i + 8], data[i + 8 : i + 8 + n]
        (crc,) = struct.unpack(">I", data[i + 8 + n : i + 12 + n])
        assert crc == zlib.crc32(kind + body), "bad CRC in %r" % kind
        out.append((kind, body))
        i += 12 + n
    return out


def decode_rgb_png(data: bytes) -> tuple[int, int, bytes]:
    """(width, height, RGB pixels) of an 8-bit truecolour, non-interlaced PNG, every row filter undone - the decoder
    the pixel comparison needs, since pdftoppm's own PNGs use all five filters."""
    chunks = png_chunks(data)
    w, h, depth, ctype, _comp, _filt, interlace = struct.unpack(">IIBBBBB", chunks[0][1])
    assert (depth, ctype, interlace) == (8, 2, 0), (depth, ctype, interlace)
    raw = zlib.decompress(b"".join(body for kind, body in chunks if kind == b"IDAT"))
    stride, bpp = w * 3, 3
    prev, rows = bytearray(stride), []
    for y in range(h):
        f, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1 : (y + 1) * (stride + 1)])
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b, c = prev[x], (prev[x - bpp] if x >= bpp else 0)
            if f == 1:
                line[x] = (line[x] + a) & 0xFF
            elif f == 2:
                line[x] = (line[x] + b) & 0xFF
            elif f == 3:
                line[x] = (line[x] + (a + b) // 2) & 0xFF
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 0xFF
            else:
                assert f == 0, "unknown filter %d" % f
        rows.append(bytes(line))
        prev = line
    return w, h, b"".join(rows)


def ppm(w: int, h: int, pixels: bytes) -> bytes:
    """A binary PPM (P6, maxval 255) of w x h RGB pixels, as pdftoppm writes it."""
    return b"P6\n%d %d\n255\n" % (w, h) + pixels


class PngFromPpm(unittest.TestCase):
    """png.parse_ppm reads pdftoppm's PPM and png.png_from_ppm writes it as a PNG with filter 0 and one zlib stream."""

    def test_a_ppm_comes_back_from_its_png_row_for_row(self):
        """The PNG holds the PPM's size (png_size reads it), a pHYs of the dpi in pixels per metre, and IDAT that
        inflates to every row behind filter byte 0 - the PPM's pixels unchanged."""
        pixels = bytes((i * 7) % 256 for i in range(5 * 3 * 3))
        img = png.parse_ppm(ppm(5, 3, pixels))
        self.assertIsNotNone(img)
        data = png.png_from_ppm(img, 150)
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "page-1.png"
            f.write_bytes(data)
            self.assertEqual(build.png_size(f), (5, 3))
        chunks = png_chunks(data)
        self.assertEqual([k for k, _ in chunks], [b"IHDR", b"pHYs", b"IDAT", b"IEND"])
        self.assertEqual(struct.unpack(">IIBBBBB", chunks[0][1]), (5, 3, 8, 2, 0, 0, 0))
        self.assertEqual(struct.unpack(">IIB", chunks[1][1]), (5905, 5905, 1))  # int(150 / 0.0254), as pdftoppm
        raw = zlib.decompress(chunks[2][1])
        self.assertEqual(raw, b"".join(b"\x00" + pixels[y * 15 : (y + 1) * 15] for y in range(3)))
        self.assertEqual(decode_rgb_png(data), (5, 3, pixels))

    def test_a_tall_page_is_compressed_in_pieces_into_one_stream(self):
        """A page taller than one compression piece still inflates to every row in order."""
        w, h = 3, 5000
        pixels = bytes((y * 3 + x) % 251 for y in range(h) for x in range(w * 3))
        img = png.parse_ppm(ppm(w, h, pixels))
        with mock.patch.object(png, "PIECE_BYTES", 64):
            data = png.png_from_ppm(img, 72)
        self.assertEqual(decode_rgb_png(data), (w, h, pixels))

    def test_anything_but_an_8_bit_rgb_ppm_is_refused(self):
        """Another magic, another maxval, a zero or missing size, short or long pixel data, or no header at all are
        None - never a PNG of the wrong size."""
        good = ppm(2, 2, bytes(12))
        self.assertIsNotNone(png.parse_ppm(good))
        for name, data in (
            ("grey P5", b"P5\n2 2\n255\n" + bytes(4)),
            ("16-bit", b"P6\n2 2\n65535\n" + bytes(24)),
            ("zero width", b"P6\n0 2\n255\n"),
            ("short", good[:-1]),
            ("long", good + b"\x00"),
            ("no header", b""),
            ("text", b"Syntax Error: not a PDF\n"),
            ("no size", b"P6\n255\n" + bytes(12)),
        ):
            with self.subTest(name):
                self.assertIsNone(png.parse_ppm(data))


# pdfinfo stand-in: LIMN_TEST_PAGES pages, or exit 1 when LIMN_TEST_PDFINFO is "fail".
FAKE_PDFINFO = """#!/bin/sh
[ "$LIMN_TEST_PDFINFO" = fail ] && { echo "Syntax Error: broken" >&2; exit 1; }
echo "Title: x"
echo "Pages:          ${LIMN_TEST_PAGES:-3}"
"""

# pdftoppm stand-in for `pdftoppm -r DPI -f N -l N -singlefile PDF`: a 4x2 PPM of page N on stdout. It lists the
# state folder into $LIMN_TEST_SEEN while it runs, counts how many copies run at once (max in $LIMN_TEST_MAX), and
# fails page $LIMN_TEST_FAIL_PAGE.
FAKE_PDFTOPPM = """#!/bin/sh
page=$4
mkdir -p "$LIMN_TEST_RUN"
touch "$LIMN_TEST_RUN/$page"
n=$(ls "$LIMN_TEST_RUN" | wc -l)
[ "$n" -gt "$(cat "$LIMN_TEST_MAX" 2>/dev/null || echo 0)" ] && echo "$n" > "$LIMN_TEST_MAX"
ls -a "$LIMN_TEST_DIR" >> "$LIMN_TEST_SEEN"
sleep "${LIMN_TEST_SLEEP:-0}"
rm -f "$LIMN_TEST_RUN/$page"
if [ "$page" = "$LIMN_TEST_FAIL_PAGE" ]; then echo "Syntax Error: page $page" >&2; exit 3; fi
printf 'P6\\n4 2\\n255\\n'
head -c 24 /dev/zero | tr '\\000' "\\\\$(printf '%03o' "$page")"
"""


class RenderWithStandIns(unittest.TestCase):
    """render_pages' contract with stand-in poppler tools: names, order, the pool bound and every failure."""

    def setUp(self):
        """A state folder, a fake PDF and the stand-ins first on PATH."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.D = RenderDoc(dir=root / "state" / "docs" / "ms")
        self.D.dir.mkdir(parents=True)
        self.pdf = root / "main.pdf"
        self.pdf.write_bytes(b"%PDF-1.4 stand-in")
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for name, text in (("pdfinfo", FAKE_PDFINFO), ("pdftoppm", FAKE_PDFTOPPM)):
            (bin_dir / name).write_text(text, encoding="utf-8")
            (bin_dir / name).chmod(0o755)
        self.seen, self.max = root / "seen.txt", root / "max.txt"
        env = mock.patch.dict(
            os.environ,
            {
                "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
                "LIMN_TEST_RUN": str(root / "running"),
                "LIMN_TEST_MAX": str(self.max),
                "LIMN_TEST_SEEN": str(self.seen),
                "LIMN_TEST_DIR": str(self.D.dir),
                "LIMN_TEST_PAGES": "3",
                "LIMN_TEST_FAIL_PAGE": "",
                "LIMN_TEST_PDFINFO": "ok",
            },
        )
        env.start()
        self.addCleanup(env.stop)

    def render(self, workers: int | None = None, **env: str) -> Path | PagesNotRendered:
        """render_pages of the fake PDF at 72 dpi with the stand-ins in the given modes."""
        with mock.patch.dict(os.environ, env):
            return build_engine.render_pages(self.D, self.pdf, [], 72, workers)

    def test_pages_are_named_as_pdftoppm_names_them(self):
        """Nine pages are page-1..page-9 and ten are page-01..page-10 - zero-padded to the page count's digits, as
        `pdftoppm -png` does (page_list sorts by name) - each the PNG of its own page's PPM."""
        for pages, names in (
            ("9", ["page-%d.png" % i for i in range(1, 10)]),
            ("10", ["page-%02d.png" % i for i in range(1, 11)]),
        ):
            with self.subTest(pages=pages):
                out = self.render(LIMN_TEST_PAGES=pages)
                self.assertIsInstance(out, Path)
                self.assertEqual(sorted(p.name for p in out.glob("page-*.png")), names)
                self.assertEqual([p["name"] for p in build.page_list(out, 72)], names)
                last = out / names[-1]
                self.assertEqual(decode_rgb_png(last.read_bytes()), (4, 2, bytes([int(pages)]) * 24))

    def test_at_most_the_given_number_of_pdftoppm_run_at_once(self):
        """With a pool of 2, six pages never have more than two pdftoppm processes at once, and do overlap."""
        out = self.render(workers=2, LIMN_TEST_PAGES="6", LIMN_TEST_SLEEP="0.5")
        self.assertIsInstance(out, Path)
        self.assertEqual(int(self.max.read_text()), 2)

    def test_the_pool_is_at_most_eight_and_at_most_the_cpu_count(self):
        """The default pool is min(8, os.cpu_count()), and one when the count is unknown."""
        for cpus, want in ((64, 8), (8, 8), (3, 3), (1, 1), (None, 1)):
            with self.subTest(cpus=cpus), mock.patch.object(build_engine.os, "cpu_count", return_value=cpus):
                self.assertEqual(build_engine.render_workers(), want)

    def test_one_failed_page_fails_the_render_and_leaves_no_page_folder(self):
        """Page 2 of 5 failing is PagesNotRendered render naming that page and pdftoppm's message; no pages-* folder
        and no half-made folder stays behind, and the pointer is untouched."""
        out = self.render(LIMN_TEST_PAGES="5", LIMN_TEST_FAIL_PAGE="2")
        self.assertIsInstance(out, PagesNotRendered)
        self.assertEqual(out.kind, "render")
        self.assertIn("page 2", out.detail)
        self.assertIn("Syntax Error: page 2", out.detail)
        self.assertEqual(sorted(p.name for p in self.D.dir.iterdir()), [])
        self.assertFalse((self.D.dir / "pages.cur").exists())

    def test_a_pdf_without_a_page_count_fails_the_render(self):
        """pdfinfo failing, or answering no page count, is PagesNotRendered render naming pdfinfo; nothing is left."""
        out = self.render(LIMN_TEST_PDFINFO="fail")
        self.assertIsInstance(out, PagesNotRendered)
        self.assertEqual(out.kind, "render")
        self.assertIn("pdfinfo", out.detail)
        out = self.render(LIMN_TEST_PAGES="0")
        self.assertIsInstance(out, PagesNotRendered)
        self.assertIn("no pages", out.detail)
        self.assertEqual(list(self.D.dir.iterdir()), [])

    def test_no_page_folder_is_visible_while_pages_are_drawn(self):
        """While pdftoppm runs, the state folder holds no name a client may ask for (valid_build_name); the finished
        folder appears whole, with its PDF copy, only once every page is written."""
        out = self.render(LIMN_TEST_PAGES="4")
        self.assertIsInstance(out, Path)
        listed = {ln.strip() for ln in self.seen.read_text().splitlines()} - {".", ".."}
        self.assertTrue(listed, "the stand-in never listed the folder")
        self.assertFalse([n for n in listed if build.valid_build_name(n)], listed)
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["main.pdf"] + ["page-%d.png" % i for i in range(1, 5)])

    def test_a_name_from_the_history_is_never_used_again(self):
        """A page folder name that builds.json still lists - its folder long deleted - is not reused even when the
        clock gives the same second again, so a URL that names a build never meets other images."""
        (self.D.dir / "builds.json").write_text(
            '{"seq": 1, "last": null, "builds": [{"build": "pages-20260927120000", "src_hash": "h"}]}'
        )
        with mock.patch.object(build_engine.time, "strftime", return_value="20260927120000"):
            out = self.render()
        self.assertIsInstance(out, Path)
        self.assertEqual(out.name, "pages-20260927120000-1")

    def test_a_stale_half_made_folder_is_cleared_by_the_next_render(self):
        """A half-made folder a killed process left behind is removed when the document renders again."""
        stale = self.D.dir / ".pages-20260927120000.part"
        stale.mkdir()
        (stale / "page-1.png").write_bytes(b"partial")
        out = self.render()
        self.assertIsInstance(out, Path)
        self.assertFalse(stale.exists())


class RenderWithPoppler(unittest.TestCase):
    """render_pages against the real `pdftoppm -png` on a ten-page PDF: the same names, sizes and pixels."""

    def setUp(self):
        """A ten-page PDF in a temporary folder."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.pdf = root / "main.pdf"
        self.pdf.write_bytes(rect_pdf(10))
        self.ref = root / "ref"
        self.D = RenderDoc(dir=root / "state")

    @needs_tex("pdftoppm", "pdfinfo")
    def test_every_page_matches_pdftoppm_png_pixel_for_pixel(self):
        """Each page image has pdftoppm's name, the same size in points (page_list), and decodes to exactly the
        pixels of pdftoppm's own PNG; the PDF copy sits beside them."""
        self.ref.mkdir()
        subprocess.run(["pdftoppm", "-r", "72", "-png", str(self.pdf), str(self.ref / "page")], check=True)
        out = build_engine.render_pages(self.D, self.pdf, [], 72)
        self.assertIsInstance(out, Path)
        ref_names = sorted(p.name for p in self.ref.glob("page-*.png"))
        self.assertEqual(ref_names[:2], ["page-01.png", "page-02.png"])
        self.assertEqual(sorted(p.name for p in out.glob("page-*.png")), ref_names)
        self.assertEqual(build.page_list(out, 72), build.page_list(self.ref, 72))
        for name in ref_names:
            with self.subTest(page=name):
                self.assertEqual(
                    decode_rgb_png((out / name).read_bytes()), decode_rgb_png((self.ref / name).read_bytes())
                )
        self.assertEqual((out / "main.pdf").read_bytes(), self.pdf.read_bytes())


if __name__ == "__main__":
    unittest.main()

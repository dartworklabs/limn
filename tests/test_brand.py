"""The Limn mark: one stroke that starts at a small dot (the pin) and runs into a line (the source line).

The viewer draws it as inline SVG coloured by CSS tokens (top bar next to the instance label, the [더보기] label chip,
the help dialog header) - no external asset, no build step. The favicon is the same geometry as an SVG data URL in
the instance accent, with PNG fallbacks drawn at runtime by limn.mark from the standard library only
(docs/handbook/viewer.md §마크와 파비콘).

Run: uv run pytest -q tests/test_brand.py
"""

import json
import os
import re
import shutil
import struct
import unittest
import zlib
from urllib.parse import unquote

from limn import mark

from helpers import ps, req, split_resp
from test_access import AccessBase, talk_to
from test_viewer_files import viewer_text

ACCENT = "#1d4ed8"


def decode_png(data: bytes):
    """(width, height, rows of RGBA tuples) for an 8-bit RGBA, non-interlaced PNG with filter 0 on every row."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, chunks = 8, {}
    while pos < len(data):
        n, tag = struct.unpack(">I4s", data[pos : pos + 8])
        chunks.setdefault(tag, b"")
        chunks[tag] += data[pos + 8 : pos + 8 + n]
        crc = struct.unpack(">I", data[pos + 8 + n : pos + 12 + n])[0]
        assert crc == zlib.crc32(tag + data[pos + 8 : pos + 8 + n]) & 0xFFFFFFFF, tag
        pos += 12 + n
    w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", chunks[b"IHDR"])
    assert (depth, ctype, interlace) == (8, 6, 0)
    raw = zlib.decompress(chunks[b"IDAT"])
    stride = 1 + 4 * w
    rows = []
    for y in range(h):
        line = raw[y * stride : (y + 1) * stride]
        assert line[0] == 0
        rows.append([tuple(line[1 + 4 * x : 5 + 4 * x]) for x in range(w)])
    assert b"IEND" in chunks
    return w, h, rows


def at(rows, size, u, v):
    """The pixel under grid point (u, v) of the mark's 24-unit grid."""
    return rows[int(v / 24 * size)][int(u / 24 * size)]


def rgb(hexcolour):
    """'#1d4ed8' -> (29, 78, 216)."""
    return tuple(int(hexcolour[i : i + 2], 16) for i in (1, 3, 5))


class MarkRaster(unittest.TestCase):
    """limn.mark.png(): the favicon fallback, drawn without any imaging library."""

    def test_png_is_rgba_of_the_requested_size(self):
        """A well-formed RGBA PNG (signature, CRCs, IHDR, one filter byte per row) of each size asked for."""
        for size in (16, 32, 180):
            with self.subTest(size=size):
                w, h, rows = decode_png(mark.png(size, ACCENT))
                self.assertEqual((w, h, len(rows)), (size, size, size))

    def test_tile_is_the_accent_and_the_glyph_is_white(self):
        """Away from the glyph the tile is the accent, opaque; the dot's centre and the middle of the line are white."""
        size = 64
        _, _, rows = decode_png(mark.png(size, ACCENT))
        self.assertEqual(at(rows, size, 20, 6), rgb(ACCENT) + (255,))
        self.assertEqual(at(rows, size, *mark.DOT[:2]), (255, 255, 255, 255))
        line_y = mark.LINE_Y
        self.assertEqual(at(rows, size, 15, line_y), (255, 255, 255, 255))
        self.assertEqual(at(rows, size, 8, 20.5), rgb(ACCENT) + (255,))  # below the corner: tile, not glyph

    def test_favicon_corners_are_round_and_the_touch_icon_is_square(self):
        """The favicon tile has transparent round corners; the apple-touch-icon is a full square (iOS rounds it)."""
        _, _, rows = decode_png(mark.png(32, ACCENT))
        self.assertEqual(rows[0][0][3], 0)
        _, _, rows = decode_png(mark.png(180, ACCENT, rounded=False))
        self.assertEqual(rows[0][0], rgb(ACCENT) + (255,))

    def test_glyph_reads_at_16px(self):
        """At 16px the dot and the line are still separate white marks on the tile (no smear into one blob)."""
        size = 16
        _, _, rows = decode_png(mark.png(size, ACCENT))
        light = lambda p: p[0] > 200 and p[1] > 200 and p[2] > 200  # noqa: E731
        self.assertTrue(light(at(rows, size, *mark.DOT[:2])))
        self.assertTrue(light(at(rows, size, 15, mark.LINE_Y)))
        self.assertFalse(light(at(rows, size, 15, 9)))  # right of the dot, above the line: tile
        whites = sum(light(p) for row in rows for p in row)
        self.assertTrue(12 <= whites <= 60, whites)

    def test_only_hex_accents_are_accepted(self):
        """The accent comes from --accent (#rrggbb); anything else is refused rather than drawn."""
        for bad in ("red", "#12345", "1d4ed8", "#1d4ed8;x"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                mark.png(32, bad)

    def test_same_input_same_bytes(self):
        """Deterministic, so a cached response never differs from a fresh one."""
        self.assertEqual(mark.png.__wrapped__(32, "#047857"), mark.png.__wrapped__(32, "#047857"))  # past the cache
        self.assertNotEqual(mark.png(32, "#047857"), mark.png(32, ACCENT))


class MarkMarkup(unittest.TestCase):
    """The SVG forms: the favicon data URL and the inline viewer markup."""

    def test_favicon_is_the_mark_in_the_accent(self):
        """The SVG favicon is the tile in the accent with the white dot and stroke - no label letter any more."""
        out = ps.favicon_href(ACCENT)
        self.assertTrue(out.startswith("data:image/svg+xml,"))
        svg = unquote(out)
        self.assertIn('fill="%s"' % ACCENT, svg)
        self.assertIn("<circle", svg)
        self.assertIn('d="%s"' % mark.PATH, svg)
        self.assertNotIn("<text", svg)

    def test_inline_mark_is_coloured_by_tokens_only(self):
        """The inline SVG carries geometry, classes and aria-hidden - never a colour literal."""
        svg = mark.inline_svg()
        self.assertIn('class="limn-mark"', svg)
        self.assertIn('aria-hidden="true"', svg)
        for cls in ("limn-mark-tile", "limn-mark-dot", "limn-mark-line"):
            self.assertIn('class="%s"' % cls, svg)
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,6}|fill=\"(?!none)|stroke=\"", svg))

    def test_mark_classes_are_its_own(self):
        """The mark's classes are limn-mark*, which no viewer script touches: plain .mark is the pin box on the PDF that
        marks() removes and redraws (a first cut used .mark, and every mark vanished once the pins were drawn)."""
        classes = re.findall(r'class="([^"]+)"', mark.inline_svg())
        self.assertTrue(classes and all(c.startswith("limn-mark") for c in classes), classes)
        js = viewer_text("__APP_JS__")
        self.assertNotIn("limn-mark", js)
        css = re.sub(r"/\*.*?\*/", "", viewer_text("__APP_CSS__"), flags=re.S)
        rules = [r for r in re.findall(r"([^{}]*)\{[^{}]*\}", css) if "limn-mark" in r]
        self.assertEqual(len(rules), 9, rules)
        self.assertFalse(
            [r for r in re.findall(r"([^{}]*)\{[^{}]*\}", css) if re.search(r"\.mark(?![\w-])", r) and "limn-mark" in r]
        )

    def test_viewer_places_the_mark_by_the_label_and_in_the_help_header(self):
        """Top bar (next to the label), the [더보기] label chip and the help dialog header each have the mark once."""
        out = ps.build_html("A-DEMO", ACCENT)
        ident = out[out.index('id="paper-identity"') : out.index('id="doc-select-wrap"')]
        self.assertIn('<svg class="limn-mark"', ident)
        self.assertIn("<span>A-DEMO</span>", ident)
        help_h = out[out.index('<h2 id="help-h"') : out.index("</h2>", out.index('<h2 id="help-h"'))]
        self.assertIn('<svg class="limn-mark"', help_h)
        label = out[out.index('<span id="more-label"') : out.index("</span>", out.index('<span id="more-label"') + 30)]
        self.assertIn('<svg class="limn-mark"', label)
        self.assertEqual(out.count('<svg class="limn-mark"'), 3)
        self.assertNotIn("__LIMN_MARK__", out)

    def test_favicon_links_svg_first_class_with_png_fallbacks(self):
        """The page links the SVG favicon plus 32px PNG and apple-touch-icon fallbacks, cache-keyed by the accent."""
        out = ps.build_html("A-DEMO", ACCENT)
        head = out[: out.index("</head>")]
        self.assertIn('<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png?c=1d4ed8">', head)
        self.assertRegex(head, r'<link rel="icon" type="image/svg\+xml" href="data:image/svg\+xml,[^"]+">')
        self.assertIn('<link rel="apple-touch-icon" href="/apple-touch-icon.png?c=1d4ed8">', head)


class FaviconRoutes(AccessBase):
    """GET /favicon-32.png and /apple-touch-icon.png serve the runtime PNGs in this instance's accent."""

    def get(self, path):
        """(status, headers, body) of one GET through the real handler."""
        code, hdrs, body = split_resp(talk_to(ps, req("GET", path)))
        return code, hdrs, body

    def test_png_routes_draw_the_instance_accent(self):
        """Both routes answer image/png of their size, in C.accent, cacheable; the query only busts caches."""
        ps.C.accent = "#be123c"
        for path, size in (("/favicon-32.png", 32), ("/apple-touch-icon.png", 180), ("/favicon-32.png?c=be123c", 32)):
            with self.subTest(path=path):
                code, hdrs, body = self.get(path)
                self.assertEqual((code, hdrs.get("content-type")), (200, "image/png"))
                self.assertIn("max-age", hdrs.get("cache-control", ""))
                w, _, rows = decode_png(body)
                self.assertEqual(w, size)
                self.assertEqual(at(rows, size, 20, 6)[:3], rgb("#be123c"))

    def test_favicon_ico_is_still_empty(self):
        """/favicon.ico keeps its 204 (the page links the real icons)."""
        code, _, body = self.get("/favicon.ico")
        self.assertEqual((code, body), (204, b""))


class MarkInTheBrowser(unittest.TestCase):
    """Real Chromium: the mark renders at its size in both themes, filled by the right tokens."""

    @classmethod
    def setUpClass(cls):
        """Start Chromium once (skip without Playwright or a browser, fail if LIMN_TEST_REQUIRE_BROWSER=1)."""
        required = os.environ.get("LIMN_TEST_REQUIRE_BROWSER") == "1"
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            if required:
                raise
            raise unittest.SkipTest("Playwright unavailable") from None
        cls.pw = sync_playwright().start()
        exe = os.environ.get("LIMN_CHROMIUM") or shutil.which("google-chrome") or shutil.which("chromium")
        try:
            cls.browser = cls.pw.chromium.launch(executable_path=exe or None, args=["--no-sandbox"])
        except Exception as e:  # no bundled or system browser
            cls.pw.stop()
            if required:
                raise
            raise unittest.SkipTest("Chromium unavailable: %s" % e) from e
        cls.html = ps.build_html("A-DEMO", ACCENT).replace("\nboot();", "\n")

    @classmethod
    def tearDownClass(cls):
        """Close the browser and Playwright."""
        cls.browser.close()
        cls.pw.stop()

    def page(self, theme):
        """The viewer markup alone (boot() off), desktop width, in theme."""
        context = self.browser.new_context(viewport={"width": 1400, "height": 850})
        self.addCleanup(context.close)
        page = context.new_page()
        page.add_init_script("localStorage.setItem('pinPrefs', %s)" % json.dumps(json.dumps({"theme": theme})))
        page.route(
            "**/*",
            lambda route: (
                route.fulfill(content_type="text/html", body=self.html)
                if route.request.url.startswith("http://viewer.test/")
                else route.abort()
            ),
        )
        page.goto("http://viewer.test/")
        page.evaluate("document.body.classList.add('lay-wide')")
        return page

    def test_top_bar_and_help_marks_render_with_tokens(self):
        """The top-bar mark is 16px with the accent tile; the help header mark is monochrome (the dialog's text colour)."""
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                page = self.page(theme)
                box = page.eval_on_selector(
                    "#paper-identity-mark svg", "e=>{const r=e.getBoundingClientRect();return [r.width,r.height]}"
                )
                self.assertEqual(box, [16, 16])
                fills = page.evaluate("""()=>{const f=s=>getComputedStyle(document.querySelector(s)).fill;
                  const fg=getComputedStyle(document.querySelector('#help')).color;
                  return [f('#paper-identity-mark .limn-mark-tile'),f('#paper-identity-mark .limn-mark-dot'),
                          f('#help-h .limn-mark-tile'),fg];}""")
                self.assertEqual(fills[0], "rgb(%d, %d, %d)" % rgb(ACCENT))
                self.assertEqual(fills[1], "rgb(255, 255, 255)")
                self.assertEqual(fills[2], fills[3])


if __name__ == "__main__":
    unittest.main()

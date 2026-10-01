"""The Limn logo in the viewer: the confirmed icon and wordmark, vendored from dartworklabs/limn-sans (src/limn/viewer/brand/).

The favicons and the apple-touch-icon are the brand build's files served byte for byte - the tab favicon is one drawing
for light and dark tabs, the 16 and 32 px pixel drawings of the i on a 먹 rounded square that fills the square. The viewer inlines the icon (top bar 16px,
[더보기] label chip 14px) and the wordmark (help header, 20px tall) as SVG with classes only, coloured by the brand
tokens for the theme (docs/handbook/viewer.md §마크와 파비콘). limn.viewer.mark is pure; server.read_brand reads the folder.

Run: uv run pytest -q src/limn/viewer/tests/test_brand.py
"""

import ast
import hashlib
import json
import re
import struct
import unittest
import zlib
from pathlib import Path

from limn.security import access as access
from limn.viewer import assemble, assemble as viewer_assemble, mark as mark, routes as viewer_shell_routes
from limn.web.errors import HTTPError

from helpers import page_for, ps, req, set_config, split_resp, viewer_text
from helpers_access import AccessBase, talk_to
from helpers_browser import ChromiumTestCase

BRAND_DIR = viewer_assemble.BRAND_DIR
INK, VER, BONE, CREAM = (21, 22, 26), (232, 69, 44), (251, 241, 230), (244, 237, 225)
# The favicon drawings as limn-brand.js FAVICON_PX draws them (limn-sans site/icons.html): the stem [x, width, top,
# base) in whole pixels (the 32's top row is its antialiased round cap), the first row below the pin, and the pin's
# solid pixels. The ground is 먹 to the edges of the square, the stem 미색.
FAVICON_DRAWINGS = {
    16: {"stem": (7, 2, 6, 13), "cap": False, "pin_end": 5, "pin": {(7, 3), (8, 3), (7, 4), (8, 4)}},
    32: {
        "stem": (14, 4, 13, 26),
        "cap": True,
        "pin_end": 11,
        "pin": {(x, y) for x in range(14, 18) for y in (7, 8, 9)},
    },
}


def decode_png(data: bytes):
    """(width, height, rows of RGBA tuples) of an 8-bit RGBA, non-interlaced PNG, undoing the five row filters."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, chunks = 8, {}
    while pos < len(data):
        n, tag = struct.unpack(">I4s", data[pos : pos + 8])
        chunks[tag] = chunks.get(tag, b"") + data[pos + 8 : pos + 8 + n]
        pos += 12 + n
    w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", chunks[b"IHDR"])
    assert (depth, ctype, interlace) == (8, 6, 0), (depth, ctype, interlace)
    raw, stride, prev, rows = zlib.decompress(chunks[b"IDAT"]), 4 * w, bytearray(4 * w), []
    for y in range(h):
        kind, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1 : (y + 1) * (stride + 1)])
        for i in range(stride):
            a, b, c = line[i - 4] if i >= 4 else 0, prev[i], prev[i - 4] if i >= 4 else 0
            p = a + b - c
            pred = [
                0,
                a,
                b,
                (a + b) // 2,
                a if abs(p - a) <= min(abs(p - b), abs(p - c)) else b if abs(p - b) <= abs(p - c) else c,
            ]
            line[i] = (line[i] + pred[kind]) & 0xFF
        rows.append([tuple(line[4 * x : 4 * x + 4]) for x in range(w)])
        prev = line
    return w, h, rows


def ico_frames(data: bytes) -> dict[int, bytes]:
    """{size: PNG bytes} of an .ico whose frames are PNGs (as Pillow writes them)."""
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1)
    frames = {}
    for i in range(count):
        w, _, _, _, _, _, size, offset = struct.unpack("<BBBBHHII", data[6 + 16 * i : 22 + 16 * i])
        frames[w or 256] = data[offset : offset + size]
    return frames


def vendored(name: str) -> bytes:
    """One file of src/limn/viewer/brand/ as packaged."""
    return (BRAND_DIR / name).read_bytes()


class VendoredFiles(unittest.TestCase):
    """src/limn/viewer/brand/ is the brand build's output, unchanged: every file is listed in SHA256SUMS with its hash, and
    the favicons are the pixel drawings."""

    def test_every_file_is_listed_in_sha256sums_with_its_hash(self):
        """Each file beside README.md and SHA256SUMS has exactly one line, and its bytes hash to it - a file edited or
        added by hand, or a stale copy, fails here. The package reads only listed files."""
        lines = (BRAND_DIR / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
        listed = dict(reversed(line.split("  ", 1)) for line in lines)
        on_disk = {p.name for p in BRAND_DIR.iterdir()} - {"README.md", "SHA256SUMS"}
        self.assertEqual(sorted(listed), sorted(on_disk))
        self.assertEqual(len(listed), len(lines))
        for name, digest in listed.items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256(vendored(name)).hexdigest(), digest)
        self.assertLessEqual(mark.FILES, set(listed))

    def test_the_tab_favicon_is_the_ink_pixel_drawing(self):
        """/favicon-16.png and /favicon-32.png: 먹 opaque to the middle of every edge and nothing in the very corners (a
        rounded square filling the square), whole-pixel stem columns in 미색, only 먹 between pin and stem, the pin
        solid 주 - and 주 nowhere else."""
        for size, spec in FAVICON_DRAWINGS.items():
            path = "/favicon-%d.png" % size
            with self.subTest(path=path):
                w, h, rows = decode_png(vendored(mark.ICON_ROUTES[path][0]))
                self.assertEqual((w, h), (size, size))
                for x, y in ((size // 2, 0), (size // 2, size - 1), (0, size // 2), (size - 1, size // 2)):
                    self.assertEqual(rows[y][x], INK + (255,), (x, y))
                for x, y in ((0, 0), (size - 1, 0), (0, size - 1), (size - 1, size - 1)):
                    self.assertEqual(rows[y][x][3], 0, (x, y))
                x0, sw, top, base = spec["stem"]
                for x in range(x0, x0 + sw):
                    for y in range(top + (1 if spec["cap"] else 0), base):
                        self.assertEqual(rows[y][x], CREAM + (255,), (x, y))
                    for y in range(spec["pin_end"], top):
                        self.assertEqual(rows[y][x], INK + (255,), (x, y))
                for x, y in spec["pin"]:
                    self.assertEqual(rows[y][x], VER + (255,), (x, y))
                vermilion = {(x, y) for y in range(h) for x in range(w) if rows[y][x][:3] == VER}
                self.assertEqual(vermilion, spec["pin"])

    def test_favicon_ico_holds_the_16_and_32_favicon_drawings(self):
        """The .ico's two frames are the favicon PNGs' pixels."""
        frames = ico_frames(vendored(mark.ICON_ROUTES["/favicon.ico"][0]))
        self.assertEqual(sorted(frames), [16, 32])
        for size in (16, 32):
            with self.subTest(size=size):
                png = vendored(mark.ICON_ROUTES["/favicon-%d.png" % size][0])
                self.assertEqual(decode_png(frames[size]), decode_png(png))

    def test_the_touch_icon_is_an_opaque_bone_square(self):
        """apple-touch-icon.png is 180 px with no transparent pixel (iOS shows those black and rounds the icon itself),
        뼈종이 in the corners, the pin and the stem down its middle."""
        w, h, rows = decode_png(vendored("apple-touch-icon.png"))
        self.assertEqual((w, h), (180, 180))
        self.assertEqual({p[3] for row in rows for p in row}, {255})
        for x, y in ((0, 0), (179, 0), (0, 179), (179, 179)):
            self.assertEqual(rows[y][x][:3], BONE)
        column = [rows[y][90][:3] for y in range(h)]
        self.assertIn(VER, column)
        self.assertIn(INK, column)
        self.assertLess(column.index(VER), column.index(INK))


class ParseSvg(unittest.TestCase):
    """limn.viewer.mark.parse_svg: a vendored SVG as a Drawing, from a closed vocabulary; anything else is refused."""

    ICON = vendored("limn-icon-light-16.svg").decode()
    WORDMARK = vendored("limn-wordmark-light-20.svg").decode()

    def roles(self, parts):
        """Every role in parts, in document order, groups before their children."""
        out = []
        for part in parts:
            if part.role:
                out.append(part.role)
            if isinstance(part, mark.Group):
                out += self.roles(part.children)
        return out

    def test_the_icon_is_a_tile_a_stroke_and_one_pin(self):
        """The icon file parses into the squircle (tile), then the stem (stroke) and the pin inside the i's group."""
        drawing = mark.parse_svg(self.ICON)
        self.assertEqual((drawing.view_box, drawing.width, drawing.height), ("0 0 1024 1024", "16", "16"))
        self.assertEqual(self.roles(drawing.parts), ["tile", "stroke", "pin"])

    def test_the_wordmark_is_one_stroke_group_and_one_pin(self):
        """The wordmark's four letters are one group painted as a stroke; the i's pin is the one circle."""
        drawing = mark.parse_svg(self.WORDMARK)
        self.assertEqual(drawing.height, "20")
        self.assertEqual(self.roles(drawing.parts), ["stroke", "pin"])
        self.assertEqual(len(drawing.parts[0].children), 4)

    def test_markup_or_dtds_outside_the_vocabulary_are_refused(self):
        """A DOCTYPE or entity, a comment, an element outside svg/g/path/circle (a rect too), text, a non-SVG root or
        namespace, and anything that is not XML raise ValueError - none of it can reach the page."""
        head = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="16" height="16">'
        circle = '<circle cx="1" cy="1" r="1" fill="#e8452c"/>'
        for bad in (
            '<!DOCTYPE svg [<!ENTITY x "y">]>' + head + circle + "</svg>",
            head + "<!-- x -->" + circle + "</svg>",
            head + circle + "<script>alert(1)</script></svg>",
            head + circle + '<image href="x.png"/></svg>',
            head + circle + "<foreignObject><p>x</p></foreignObject></svg>",
            head + circle + '<use href="#a"/></svg>',
            head + circle + '<rect x="0" y="0" width="1" height="1" fill="#fbf1e6"/></svg>',
            head + circle + "hello</svg>",
            head + '<g fill="#15161a">x<path d="M0 0Z"/></g></svg>',
            '<html xmlns="http://www.w3.org/2000/svg">' + circle + "</html>",
            '<svg viewBox="0 0 24 24" width="16" height="16">' + circle + "</svg>",
            head + "</svg>",
            head + circle,
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                mark.parse_svg(bad)

    def test_attributes_and_values_outside_the_vocabulary_are_refused(self):
        """An event handler, style, class or href attribute; a fill that is not a brand colour (or is a paint server);
        path data, a transform or a number that is not plain geometry; a malformed viewBox or size; and a shape that
        nothing paints all raise ValueError."""
        for attrs, body in (
            (
                'viewBox="0 0 24 24" width="16" height="16" onload="alert(1)"',
                '<circle cx="1" cy="1" r="1" fill="#e8452c"/>',
            ),
            (
                'viewBox="0 0 24 24" width="16" height="16"',
                '<circle cx="1" cy="1" r="1" fill="#e8452c" onclick="x()"/>',
            ),
            (
                'viewBox="0 0 24 24" width="16" height="16"',
                '<circle cx="1" cy="1" r="1" fill="#e8452c" style="fill:red"/>',
            ),
            ('viewBox="0 0 24 24" width="16" height="16"', '<circle cx="1" cy="1" r="1" fill="#e8452c" class="x"/>'),
            ('viewBox="0 0 24 24" width="16" height="16"', '<circle cx="1" cy="1" r="1" fill="#ff0000"/>'),
            ('viewBox="0 0 24 24" width="16" height="16"', '<circle cx="1" cy="1" r="1" fill="url(#g)"/>'),
            ('viewBox="0 0 24 24" width="16" height="16"', '<path d="M0 0&quot;/&gt;" fill="#15161a"/>'),
            (
                'viewBox="0 0 24 24" width="16" height="16"',
                '<g transform="rotate(4)"><path d="M0 0Z" fill="#15161a"/></g>',
            ),
            (
                'viewBox="0 0 24 24" width="16" height="16"',
                '<g transform="translate(javascript:1)"><path d="M0 0Z" fill="#15161a"/></g>',
            ),
            ('viewBox="0 0 24 24" width="16" height="16"', '<circle cx="1px" cy="1" r="1" fill="#e8452c"/>'),
            ('viewBox="0 0 24 24" width="16" height="16"', '<circle cx="1" cy="1" fill="#e8452c"/>'),
            ('viewBox="0 0 24" width="16" height="16"', '<circle cx="1" cy="1" r="1" fill="#e8452c"/>'),
            ('viewBox="0 0 24 24" width="100%" height="16"', '<circle cx="1" cy="1" r="1" fill="#e8452c"/>'),
            ('viewBox="0 0 24 24" width="16" height="16"', '<circle cx="1" cy="1" r="1"/>'),
            ('viewBox="0 0 24 24" width="16" height="16"', '<g><path d="M0 0Z"/></g>'),
        ):
            text = '<svg xmlns="http://www.w3.org/2000/svg" %s>%s</svg>' % (attrs, body)
            with self.subTest(text=text), self.assertRaises(ValueError):
                mark.parse_svg(text)


class InlineMarkup(unittest.TestCase):
    """The markup the page inlines: classes and geometry only, the icon decorative, the wordmark named Limn."""

    BRAND = viewer_assemble.read_brand()

    def test_inline_logos_carry_classes_and_never_a_colour(self):
        """Every slot's markup is an <svg> of limn-mark* classes with no colour literal, fill or stroke attribute."""
        self.assertEqual(sorted(self.BRAND.marks), sorted(mark.MARK_SLOTS))
        for placeholder, svg in self.BRAND.marks.items():
            with self.subTest(placeholder=placeholder):
                self.assertTrue(svg.startswith('<svg class="%s"' % mark.MARK_SLOTS[placeholder].css_class), svg[:60])
                self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}|\b(?:fill|stroke|style)=", svg))
                classes = re.findall(r'class="([^"]+)"', svg)
                self.assertTrue(classes and all(c.startswith("limn-mark") for c in classes), classes)
                self.assertIn('class="limn-mark-pin"', svg)
                self.assertEqual(svg.count('class="limn-mark-pin"'), 1)

    def test_the_icons_are_decorative_and_the_wordmark_is_an_image_named_limn(self):
        """The two icons sit next to the label that names them (aria-hidden); the wordmark stands for the word Limn in
        the help heading, so it is role=img with that name."""
        marks = self.BRAND.marks
        for placeholder in ("__LIMN_MARK_16__", "__LIMN_MARK_14__"):
            self.assertIn('aria-hidden="true" focusable="false"', marks[placeholder])
            self.assertNotIn("role=", marks[placeholder])
        self.assertIn('role="img" aria-label="Limn" focusable="false"', marks["__LIMN_WORDMARK__"])
        self.assertIn('width="14" height="14"', marks["__LIMN_MARK_14__"])
        self.assertIn('width="16" height="16"', marks["__LIMN_MARK_16__"])
        self.assertIn('height="20"', marks["__LIMN_WORDMARK__"])

    def test_mark_classes_are_its_own(self):
        """The logo's classes are limn-mark*, which no viewer script touches: plain .mark is the pin box on the PDF that
        marks() removes and redraws (a first cut used .mark, and every mark vanished once the pins were drawn)."""
        js = viewer_text("__APP_JS__")
        self.assertNotIn("limn-mark", js)
        css = re.sub(r"/\*.*?\*/", "", viewer_text("__APP_CSS__"), flags=re.S)
        rules = [r.strip() for r in re.findall(r"([^{}]*)\{[^{}]*\}", css) if "limn-mark" in r]
        self.assertEqual(len(rules), 6, rules)
        self.assertFalse([r for r in rules if re.search(r"\.mark(?![\w-])", r)])


class BrandValue(unittest.TestCase):
    """limn.viewer.mark.brand over the folder's bytes: which bytes each route serves, and the content key."""

    FILES = {name: vendored(name) for name in mark.FILES}

    def test_each_route_serves_its_file_unchanged(self):
        """Every ICON_ROUTES path maps to its file's bytes and content type; nothing else is served."""
        icons = mark.brand(self.FILES).icons
        self.assertEqual(sorted(icons), sorted(mark.ICON_ROUTES))
        for path, (name, content_type) in mark.ICON_ROUTES.items():
            self.assertEqual((icons[path].body, icons[path].content_type), (self.FILES[name], content_type))

    def test_the_key_follows_the_bytes_of_the_served_icons(self):
        """The same files give the same 12-digit key; one changed icon byte (same length) or one more byte gives a new
        one, so browsers fetch the new drawing; an SVG-only change (not served as a file) leaves it."""
        key = mark.brand(self.FILES).key
        self.assertRegex(key, r"^[0-9a-f]{12}$")
        self.assertEqual(mark.brand(dict(self.FILES)).key, key)
        ico = self.FILES["favicon.ico"]
        for changed in (ico[:-1] + bytes([ico[-1] ^ 1]), ico + b"\0"):
            with self.subTest(length=len(changed)):
                self.assertNotEqual(mark.brand(dict(self.FILES, **{"favicon.ico": changed})).key, key)
        svg = dict(self.FILES, **{"limn-icon-light-14.svg": self.FILES["limn-icon-light-14.svg"] + b"\n"})
        self.assertEqual(mark.brand(svg).key, key)

    def test_a_missing_or_broken_file_fails_the_start(self):
        """Without one of FILES brand() raises KeyError; with an SVG that is not UTF-8 or not in the vocabulary it
        raises ValueError - read_viewer() then fails at startup rather than serve a page without its logo."""
        for name in sorted(mark.FILES):
            with self.subTest(missing=name), self.assertRaises(KeyError):
                mark.brand({n: b for n, b in self.FILES.items() if n != name})
        for bad in (b"\xff\xfe", b"<svg/>"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                mark.brand(dict(self.FILES, **{"limn-wordmark-light-20.svg": bad}))

    def test_a_broken_svg_is_named_in_the_error(self):
        """The startup error names the file that broke - an SVG that is not UTF-8, not XML or outside the vocabulary
        raises ValueError whose message starts with that file's name, so a packaging defect points at its file."""
        for name in sorted(s.file for s in mark.MARK_SLOTS.values()):
            for bad in (b"\xff\xfe", b"<svg", b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>'):
                with self.subTest(name=name, bad=bad), self.assertRaises(ValueError) as caught:
                    mark.brand(dict(self.FILES, **{name: bad}))
                self.assertTrue(str(caught.exception).startswith(name + ": "), str(caught.exception))


class MarkPurity(unittest.TestCase):
    """limn.viewer.mark is pure domain (docs/handbook/architecture.md, 순수 도메인): it turns bytes it is given into values and
    never reaches files, processes, the network or the server's run state - server.read_brand reads the folder."""

    SOURCE = Path(mark.__file__).read_text(encoding="utf-8")
    PURE_IMPORTS = {"hashlib", "html", "re", "xml.etree.ElementTree", "collections.abc", "dataclasses", "typing"}

    def test_imports_only_pure_standard_modules(self):
        """Every import is one of the pure standard modules it uses; a file, subprocess, HTTP or limn import here
        would put an effect or the server's state inside the domain (architecture.md 멈춤 신호)."""
        imported = set()
        for node in ast.walk(ast.parse(self.SOURCE)):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        self.assertLessEqual(imported, self.PURE_IMPORTS)

    def test_reads_no_file_and_no_run_state(self):
        """No open() or Path, and neither the run config (C.) nor the current document (cur_doc)."""
        names = {n.id for n in ast.walk(ast.parse(self.SOURCE)) if isinstance(n, ast.Name)}
        self.assertEqual(names & {"open", "Path", "C", "cur_doc", "__import__"}, set())
        self.assertNotIn("cur_doc(", self.SOURCE)


class PageLinks(unittest.TestCase):
    """Where the page puts the logo and how its <head> links the icons."""

    def test_icon_by_the_label_and_in_the_chip_wordmark_in_the_help_header(self):
        """Top bar (before the label) and the [더보기] label chip show the icon once each; the help header shows the
        wordmark where the word Limn was, followed by the rest of the title."""
        out = page_for("A-DEMO", "#1d4ed8")
        ident = out[out.index('id="paper-identity"') : out.index('id="doc-select-wrap"')]
        self.assertIn('<svg class="limn-mark" viewBox="0 0 1024 1024" width="16" height="16"', ident)
        self.assertIn("<span>A-DEMO</span>", ident)
        label = out[out.index('<span id="more-label"') : out.index("</span>", out.index('<span id="more-label"') + 30)]
        self.assertIn('<svg class="limn-mark" viewBox="0 0 1024 1024" width="14" height="14"', label)
        help_h = out[out.index('<h2 id="help-h"') : out.index("</h2>", out.index('<h2 id="help-h"'))]
        self.assertIn('<svg class="limn-mark-word"', help_h)
        self.assertTrue(help_h.endswith("</svg><span>— 사용법</span>"), help_h[-60:])
        self.assertEqual((out.count('<svg class="limn-mark"'), out.count('<svg class="limn-mark-word"')), (2, 1))
        self.assertNotIn("__LIMN_", out)

    def test_head_links_one_favicon_set_with_the_content_key(self):
        """One favicon for light and dark tabs: the .ico, the 16 and 32 PNGs and the touch icon, each with ?v=<content
        key>; no media=, no dark set, no colour-scheme script, no accent-coloured data: SVG or ?c=<accent> key."""
        key = viewer_assemble.read_brand().key
        head = page_for("A-DEMO", "#1d4ed8")
        head = head[: head.index("</head>")]
        links = re.findall(r"<link rel=\"(icon|apple-touch-icon)\"([^>]*)>", head)
        hrefs = [re.search(r'href="([^"]+)"', a).group(1) for _, a in links]
        self.assertEqual(
            hrefs,
            [
                "/favicon.ico?v=" + key,
                "/favicon-16.png?v=" + key,
                "/favicon-32.png?v=" + key,
                "/apple-touch-icon.png?v=" + key,
            ],
        )
        self.assertEqual([a for _, a in links if "media=" in a], [])
        icons = head[head.index("</title>") : head.index("<style>")]  # the links, and nothing between them and the CSS
        self.assertNotIn("<script", icons)
        for gone in ("favicon-dark", "data:image/svg", "?c="):
            self.assertNotIn(gone, head)

    def test_the_icons_do_not_depend_on_the_instance(self):
        """Two runs with different labels and accents link the same icons: the tile is never the instance colour."""
        a, b = page_for("A-DEMO", "#1d4ed8"), page_for("B-DEMO", "#be123c")
        links = lambda page: re.findall(r"<link rel=\"(?:icon|apple-touch-icon)\"[^>]*>", page)  # noqa: E731
        self.assertEqual(links(a), links(b))
        self.assertNotIn("#be123c", "".join(links(b)))


class IconRoutes(AccessBase):
    """GET of each ICON_ROUTES path through the real handler serves the vendored file; other paths serve no icon."""

    def get(self, path):
        """(status, headers, body) of one GET through the real handler."""
        return split_resp(talk_to(ps, req("GET", path)))

    def test_each_route_serves_the_vendored_bytes_whatever_the_accent(self):
        """200 with the file's bytes and content type, cacheable publicly for a day; the ?v= key and the instance's
        accent change nothing."""
        set_config(accent="#be123c")
        for path, (name, content_type) in mark.ICON_ROUTES.items():
            for query in ("", "?v=0123456789ab"):
                with self.subTest(path=path + query):
                    code, hdrs, body = self.get(path + query)
                    self.assertEqual((code, hdrs.get("content-type")), (200, content_type))
                    self.assertEqual(hdrs.get("cache-control"), "public, max-age=86400")
                    self.assertEqual(body, vendored(name))

    def test_the_retired_dark_paths_answer_like_any_unknown_icon_path(self):
        """/favicon-dark.ico, /favicon-dark-16.png and /favicon-dark-32.png, which 0.3.8 served as the one favicon for the
        0.3.6-0.3.7 pages, are gone in 0.4.0: each answers what a path that never existed answers (exactly 404, no icon
        bytes), with or without the ?v= key, and none is an icon route or a read path any more."""
        icons = {vendored(n) for n, _ in mark.ICON_ROUTES.values()}
        unknown = self.get("/favicon-never-served.ico")
        self.assertEqual(unknown[0], 404)
        for retired in ("/favicon-dark.ico", "/favicon-dark-16.png", "/favicon-dark-32.png"):
            for query in ("", "?v=0123456789ab"):
                with self.subTest(path=retired + query):
                    code, _, body = self.get(retired + query)
                    self.assertEqual(code, 404)
                    self.assertNotIn(body, icons)
            self.assertNotIn(retired, mark.ICON_ROUTES)
            self.assertNotIn(retired, access.READ_PATHS)

    def test_icon_routes_are_explicit_read_paths(self):
        """access.py admits each icon route by name (a new path is denied by default); test_web's GuardOrder walks
        every one of them through the access checks."""
        self.assertLessEqual(set(mark.ICON_ROUTES), access.READ_PATHS)

    def test_other_icon_like_paths_serve_no_icon(self):
        """A size or scheme that has no file, a path below an icon, a traversal or an encoded name is not answered
        with an icon."""
        icons = {vendored(n) for n, _ in mark.ICON_ROUTES.values()}
        for path in (
            "/favicon-64.png",
            "/favicon-light-16.png",
            "/favicon.ico/x",
            "/favicon-16.png/../favicon.ico",
            "/brand/favicon.ico",
            "/%66avicon.ico",
            "/apple-touch-icon-precomposed.png",
        ):
            with self.subTest(path=path):
                code, _, body = self.get(path)
                self.assertNotEqual(code, 200)
                self.assertNotIn(body, icons)

    def test_a_viewer_without_icons_answers_404(self):
        """A run whose ServedViewer holds no icons (a partial test runtime) refuses an icon route with not_found
        rather than an empty 200."""

        class App:
            """The members viewer_shell.get reads for an icon route."""

            APP_NAME = "Limn"

            def viewer(self):
                """A viewer with no icons."""
                return assemble.ServedViewer("<p></p>", "", {})

            def hdr_text(self, value):
                """The path as it is."""
                return str(value)

        request = type("Request", (), {"path": "/favicon.ico"})()
        with self.assertRaises(HTTPError) as caught:
            viewer_shell_routes.get(request, App())
        self.assertEqual((caught.exception.code, caught.exception.body["reason"]), (404, "not_found"))


class LogoInTheBrowser(ChromiumTestCase):
    """Real Chromium: the logo renders at its size in the theme's brand colours, and the favicon links follow the
    browser's colour scheme."""

    @classmethod
    def setUpClass(cls):
        """Start Chromium once (skip without Playwright or a browser, fail if LIMN_TEST_REQUIRE_BROWSER=1)."""
        super().setUpClass()
        cls.html = page_for("A-DEMO", "#1d4ed8").replace("\nboot();", "\n")

    def page(self, theme=None, scheme="light"):
        """The viewer markup alone (boot() off), desktop width, in theme (the viewer's own setting) and the browser's
        colour scheme."""
        context = self.browser.new_context(viewport={"width": 1400, "height": 850}, color_scheme=scheme)
        self.addCleanup(context.close)
        page = context.new_page()
        if theme:
            page.add_init_script("localStorage.setItem('pinPrefs', %s)" % json.dumps(json.dumps({"theme": theme})))
        page.route(
            "**/*",
            lambda route: (
                route.fulfill(content_type="text/html", body=self.html)
                if route.request.url == "http://viewer.test/"
                else route.abort()
            ),
        )
        page.goto("http://viewer.test/")
        page.evaluate("document.body.classList.add('lay-wide')")
        return page

    def test_the_logo_takes_the_themes_brand_colours(self):
        """Light: 뼈종이 tile, 먹 strokes; dark: 먹 tile, 미색 strokes; the pin 주 in both. The top-bar icon is 16px,
        the chip's 14px, the help wordmark 20px tall."""
        expect = {"light": (BONE, INK), "dark": (INK, CREAM)}
        for theme, (tile, stroke) in expect.items():
            with self.subTest(theme=theme):
                page = self.page(theme)
                got = page.evaluate(
                    """()=>{const f=(s,p)=>getComputedStyle(document.querySelector(s+' '+p)).fill;
                    const box=s=>{const r=document.querySelector(s).getBoundingClientRect();return [r.width,r.height]};
                    const inDialog=(id,s)=>{const d=document.getElementById(id);d.showModal();const b=box(s);d.close();return b};
                    return {fills:[f('#paper-identity-mark','.limn-mark-tile'),f('#paper-identity-mark','.limn-mark-stroke'),
                      f('#paper-identity-mark','.limn-mark-pin'),f('#more-label','.limn-mark-tile'),
                      f('#help-h','.limn-mark-stroke'),f('#help-h','.limn-mark-pin')],
                      top:box('#paper-identity-mark svg'),chip:inDialog('more','#more-label svg'),
                      word:inDialog('help','#help-h svg')[1]}}"""
                )
                rgb = "rgb(%d, %d, %d)"
                self.assertEqual(
                    got["fills"], [rgb % tile, rgb % stroke, rgb % VER, rgb % tile, rgb % stroke, rgb % VER]
                )
                self.assertEqual((got["top"], got["chip"], got["word"]), ([16, 16], [14, 14], 20))

    def test_favicon_links_are_the_same_in_every_colour_scheme(self):
        """The favicon links do not depend on the browser's colour scheme: a page opened light, opened dark, and one
        whose scheme changes while it is open all keep the same four icon links."""
        hrefs = "()=>[...document.querySelectorAll('link[rel=icon],link[rel=apple-touch-icon]')].map(l=>l.getAttribute('href'))"
        light_page = self.page(scheme="light")
        light = light_page.evaluate(hrefs)
        self.assertEqual(len(light), 4)
        self.assertEqual(self.page(scheme="dark").evaluate(hrefs), light)
        light_page.emulate_media(color_scheme="dark")
        light_page.wait_for_timeout(200)  # a change listener, if there were one, would have run by now
        self.assertEqual(light_page.evaluate(hrefs), light)


if __name__ == "__main__":
    unittest.main()

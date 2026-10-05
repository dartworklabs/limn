"""The interface font the viewer bundles: Pretendard Variable, its official dynamic subset (src/limn/vendor/pretendard/).

Every device draws the interface in this one build (docs/handbook/viewer.md §글꼴): the slices are the release's files
byte for byte (SHA256SUMS), and the stylesheet names each of them once, at its versioned URL, with no local() - so a
device's own fonts never take its place. GET /vendor/pretendard/<file> serves them like the bundled PDF.js
(docs/handbook/api.md §화면·PDF·정적 파일): one leaf name, a slice or the stylesheet, cached for good under its versioned
URL. The page links the stylesheet and sets its sans-serif stack in Pretendard Variable first; in Chromium the
interface text is drawn in it from the page's own origin, and what the viewer measures from text is measured again
once the font arrives.

Run: uv run pytest -q src/limn/viewer/tests/test_bundled_font.py
"""

import hashlib
import re
import unittest
from urllib.parse import urlparse

from limn.pins.lifecycle.rules import CloseRequest
from limn.security.access import LOCAL_ACTOR
from limn.viewer import assemble

from helpers import HTML, Base, add_pin, ps, req, split_resp
from helpers_access import ALICE, actor
from helpers_authority import post_authority
from helpers_browser import BrowserBase, booted, settle, watch_idle

FONT_DIR = assemble.default_pretendard_dir()
# The files of the folder that are not slices: the record of where they come from, their license, the slices' hashes and
# the stylesheet.
NOT_SLICES = {"README.md", "LICENSE", "SHA256SUMS", "pretendard.css"}
# One @font-face rule of the stylesheet, and one declaration in it.
FONT_FACE = re.compile(r"@font-face\s*\{([^}]*)\}")
DECLARATION = re.compile(r"\s*([a-z-]+)\s*:\s*([^;]+?)\s*;")


def font_faces(css: str) -> list[dict[str, str]]:
    """The declarations of each @font-face rule in css, by property name, in the order the rules are written."""
    return [dict(DECLARATION.findall(body)) for body in FONT_FACE.findall(css)]


class PretendardFiles(unittest.TestCase):
    """src/limn/vendor/pretendard/ holds the release's slices unchanged, a stylesheet that loads each of them by its
    versioned URL and nothing else, and the license the font is distributed under."""

    def slices(self) -> set[str]:
        """The names of the font slices in the folder: every file but the four that describe them."""
        return {p.name for p in FONT_DIR.iterdir()} - NOT_SLICES

    def test_every_slice_is_listed_in_sha256sums_with_its_hash(self):
        """Each slice has exactly one line in SHA256SUMS and its bytes hash to it - a slice edited, added by hand or left
        from another release fails here - and every slice is a woff2 file (its signature 'wOF2')."""
        lines = (FONT_DIR / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
        listed = dict(reversed(line.split("  ", 1)) for line in lines)
        self.assertEqual(len(listed), len(lines))
        self.assertEqual(sorted(listed), sorted(self.slices()))
        self.assertEqual(len(listed), 92)
        for name, digest in listed.items():
            with self.subTest(name=name):
                data = (FONT_DIR / name).read_bytes()
                self.assertTrue(name.endswith(".woff2"), name)
                self.assertEqual(data[:4], b"wOF2")
                self.assertEqual(hashlib.sha256(data).hexdigest(), digest)

    def test_the_stylesheet_loads_each_slice_once_from_its_versioned_url_and_nothing_local(self):
        """Every @font-face rule is the family 'Pretendard Variable' with font-display: swap and one src: url() of a slice
        beside the stylesheet with ?v=PRETENDARD_VERSION, in the variable woff2 format - no local(), no other origin, no
        path. Each slice is named by exactly one rule, and each rule keeps its unicode-range."""
        css = (FONT_DIR / "pretendard.css").read_text(encoding="utf-8")
        self.assertNotIn("local(", css)
        faces = font_faces(css)
        self.assertEqual(len(faces), css.count("@font-face"))
        named = []
        for face in faces:
            with self.subTest(src=face.get("src")):
                self.assertEqual(face["font-family"], "'Pretendard Variable'")
                self.assertEqual(face["font-display"], "swap")
                self.assertEqual(face["font-style"], "normal")
                self.assertTrue(face["unicode-range"].startswith("U+"), face)
                src = re.fullmatch(r"url\(([^()?/]+)\?v=([^()]+)\) format\('woff2-variations'\)", face["src"])
                self.assertIsNotNone(src, face["src"])
                self.assertEqual(src[2], assemble.PRETENDARD_VERSION)
                named.append(src[1])
        self.assertEqual(sorted(named), sorted(self.slices()))

    def test_the_record_names_the_version_and_the_license_is_the_ofl(self):
        """README.md records the release the files come from, and LICENSE is the SIL Open Font License with the
        Reserved Font Name - the terms the font may be redistributed under."""
        readme = (FONT_DIR / "README.md").read_text(encoding="utf-8")
        self.assertIn("Pretendard %s" % assemble.PRETENDARD_VERSION, readme)
        self.assertIn("pretendard@%s" % assemble.PRETENDARD_VERSION, readme)
        license_text = (FONT_DIR / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("SIL OPEN FONT LICENSE Version 1.1", license_text)
        self.assertIn("Reserved Font Name Pretendard", license_text)


# A slice, the stylesheet, and how each is answered: its media type. Both cache for a year, immutable: every URL the page
# and the stylesheet name carries the version.
SERVED = {"PretendardVariable.subset.0.woff2": "font/woff2", "pretendard.css": "text/css; charset=utf-8"}
IMMUTABLE = "public, max-age=31536000, immutable"


class PretendardRoute(Base):
    """GET /vendor/pretendard/<file> through the handler: a slice or the stylesheet, by one leaf name, as its bytes on
    disk with its media type and a year's immutable cache; anything else under the prefix is a 404 that names no file
    and caches nothing."""

    def get(self, path, headers=None):
        """One GET through the handler from loopback -> (status, lowercase headers, body)."""
        return split_resp(self.talk(req("GET", path, headers=headers)))

    def test_a_slice_and_the_stylesheet_are_served_as_they_are_with_their_type_and_an_immutable_cache(self):
        """200 with the file's bytes, font/woff2 for a slice and text/css for the stylesheet, nosniff, and
        Cache-Control: public, max-age=31536000, immutable - with the page's ?v= and without a query."""
        for name, media in SERVED.items():
            for query in ("?v=%s" % assemble.PRETENDARD_VERSION, ""):
                with self.subTest(name=name, query=query):
                    code, h, body = self.get("/vendor/pretendard/%s%s" % (name, query))
                    self.assertEqual(code, 200)
                    self.assertEqual(h["content-type"], media)
                    self.assertEqual(h["cache-control"], IMMUTABLE)
                    self.assertEqual(h["x-content-type-options"], "nosniff")
                    self.assertEqual(body, (FONT_DIR / name).read_bytes())

    def test_traversal_subpaths_encodings_and_other_names_are_404(self):
        """Only a leaf name of a slice or the stylesheet is served: a path out of the folder (plain or %-encoded), a
        subpath, a dotfile, the folder's own records (LICENSE, README.md, SHA256SUMS), an unknown slice, another
        suffix and a PDF.js file asked for here are all 404 not_found, uncached, with no file's bytes in the body."""
        for path in (
            "/vendor/pretendard/../pdfjs/pdf.min.mjs",
            "/vendor/pretendard/..%2fpdfjs%2fpdf.min.mjs",
            "/vendor/pretendard/%2e%2e/%2e%2e/server.py",
            "/vendor/pretendard/%50retendardVariable.subset.0.woff2",
            "/vendor/pretendard/PretendardVariable.subset.0.woff2%00.css",
            "/vendor/pretendard/sub/pretendard.css",
            "/vendor/pretendard/woff2-dynamic-subset/PretendardVariable.subset.0.woff2",
            "/vendor/pretendard/pretendard.css/",
            "/vendor/pretendard//etc/passwd",
            "/vendor/pretendard/",
            "/vendor/pretendard/.pretendard.css",
            "/vendor/pretendard/LICENSE",
            "/vendor/pretendard/README.md",
            "/vendor/pretendard/SHA256SUMS",
            "/vendor/pretendard/PretendardVariable.subset.92.woff2",
            "/vendor/pretendard/PretendardVariable.subset.0.woff",
            "/vendor/pretendard/pretendard.CSS",
            "/vendor/pretendard/pdf.min.mjs",
        ):
            with self.subTest(path=path):
                code, h, body = self.get(path)
                self.assertEqual(code, 404)
                self.assertEqual(h["cache-control"], "no-store")
                self.assertIn(b'"not_found"', body)
                self.assertNotIn(b"wOF2", body)
                self.assertNotIn(b"Open Font License", body)
                self.assertNotIn(b"@font-face", body)

    def test_the_pdfjs_route_still_serves_only_its_modules(self):
        """The two families stay apart: the PDF.js prefix answers a .mjs and refuses the stylesheet and a slice, which
        exist only in Pretendard's folder."""
        self.assertEqual(self.get("/vendor/pdfjs/pdf.min.mjs?v=%s" % assemble.PDFJS_VERSION)[0], 200)
        for name in SERVED:
            with self.subTest(name=name):
                self.assertEqual(self.get("/vendor/pdfjs/%s" % name)[0], 404)


class PageLinksTheFont(unittest.TestCase):
    """The served page loads the bundled stylesheet itself - linked once in the head at its versioned URL, not inlined -
    and its sans-serif stack names Pretendard Variable first, with the stack it had before as the fallbacks."""

    def test_the_head_links_the_stylesheet_once_at_its_versioned_url(self):
        """One stylesheet link, in the head, to /vendor/pretendard/pretendard.css?v=PRETENDARD_VERSION; no @font-face
        rule in the page itself."""
        links = re.findall(r'<link rel="stylesheet" href="([^"]+)">', HTML)
        self.assertEqual(links, ["/vendor/pretendard/pretendard.css?v=%s" % assemble.PRETENDARD_VERSION])
        self.assertIn(links[0], HTML.split("</head>", 1)[0])
        self.assertNotIn("@font-face", HTML)

    def test_the_sans_stack_starts_with_the_bundled_family_and_the_mono_stack_is_as_it_was(self):
        """--font-sans is "Pretendard Variable" and then the stack the viewer had before; --font-mono is unchanged."""
        tokens = dict(re.findall(r"--(font-[a-z]+):([^;}]+)", HTML))
        self.assertEqual(
            tokens["font-sans"].split(","),
            [
                '"Pretendard Variable"',
                "-apple-system",
                "BlinkMacSystemFont",
                '"Pretendard"',
                '"Noto Sans KR"',
                "sans-serif",
            ],
        )
        self.assertEqual(tokens["font-mono"], '"JetBrains Mono",ui-monospace,monospace')


# Every drawn element whose own text is plain Hangul, Latin and digits and whose font is the sans stack, marked
# data-font-probe=<index>; returns their texts. CSS.getPlatformFontsForNode then says what drew each.
FONT_PROBES = """() => {const plain = /^[가-힣A-Za-z0-9 .,()\\-]+$/, out = [];
  document.querySelectorAll('[data-font-probe]').forEach(e => e.removeAttribute('data-font-probe'));
  for (const e of document.querySelectorAll('body *')) {
    if (!e.getClientRects().length || getComputedStyle(e).visibility === 'hidden') continue;
    if (!getComputedStyle(e).fontFamily.startsWith('"Pretendard Variable"')) continue;
    const own = [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.nodeValue).join('').trim();
    if (!own || !plain.test(own)) continue;
    e.setAttribute('data-font-probe', String(out.length)); out.push(own);}
  return out;}"""
# The font loading state once every load started so far has finished, and whether the bundled family has the given
# text ready to draw (document.fonts.check: every slice its characters need has loaded).
FONTS_READY = """async (text) => {await document.fonts.ready;
  return {status: document.fonts.status, check: document.fonts.check('16px "Pretendard Variable"', text)};}"""
# A family CSS.getPlatformFontsForNode reports for the bundled font: its name, with the rendering back end Chromium adds
# in parentheses ("Pretendard Variable (Fontations)").
BUNDLED = re.compile(r"Pretendard Variable( \(\w+\))?")
# A fallback far from Pretendard for the time its slices are held back: the sans stack is Pretendard Variable, then the
# generic monospace - wider, with other ink - whatever fonts the machine has.
MONO_FALLBACK = (
    "document.addEventListener('DOMContentLoaded',()=>{const s=document.createElement('style');"
    "s.textContent=':root:root{--font-sans:\"Pretendard Variable\",monospace}';document.head.append(s);});"
)
# What the viewer measured from text: the sheet bar's step and [더보기]'s foot ink line (layout.js fitBarWords, footInk).
MEASURED = """() => {const f = document.querySelector('#more-foot').style;
  return {bar: ['bar-sel-icon', 'bar-snug', 'bar-tight'].filter(c => document.querySelector('#bar1').classList.contains(c)),
    foot: ['--ink-word', '--ink-ver', '--help-chev'].map(k => f.getPropertyValue(k))};}"""
PHONE = {"viewport": {"width": 384, "height": 832}, "is_mobile": True, "has_touch": True, "device_scale_factor": 2.625}
DESK = {"viewport": {"width": 1400, "height": 850}}


class BundledFontInBrowser(BrowserBase):
    """The real page in Chromium (docs/handbook/viewer.md §글꼴): the interface text is drawn in the bundled Pretendard
    Variable - the platform font Chromium reports for it, not just a font that claims to be loaded - fetched only as
    slices from the page's own /vendor/pretendard/ and from no other origin. CI's runner has no Pretendard installed, so
    there this is the check that the font renders without one; a machine that has it cannot pass a static Pretendard off
    as the bundled one, whose family name differs."""

    held: list | None = None

    def setUp(self):
        """BrowserBase's manuscript with three open pins and one awaiting review, so the sheet bar's chip has both halves
        and their counts to fit."""
        super().setUp()
        for lo in (4, 8, 12):
            add_pin({"file": str(self.main), "lo": lo, "hi": lo + 1, "page": 1, "note": "n"}, actor(ALICE))
        rid = add_pin({"file": str(self.main), "lo": 20, "hi": 21, "page": 2, "note": "r"}, actor(ALICE)).record["id"]
        ps.APP.pin_lifecycle.close_pin(
            rid,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", rid),
            CloseRequest(reply="done"),
        )

    def route(self, route):
        """The fixture's routes, holding back every font slice while self.held is a list (release() answers them)."""
        if self.held is not None and urlparse(route.request.url).path.endswith(".woff2"):
            self.held.append(route)
            return None
        return super().route(route)

    def release(self):
        """Answer every held slice request through the handler, and stop holding."""
        held, self.held = self.held or [], None
        for route in held:
            self.forward(route)

    def view(self, device, lang, wait=True, init=None):
        """Open the viewer on device in lang, after the script init when given; return the page and the (url, resource
        type) of every request it made. With wait, return once boot() has finished with the three open pins and the page
        has settled (its fonts loaded); else once boot() has finished, without waiting for the page's load event, which
        held fonts would delay."""
        context = self.browser.new_context(**device)
        self.addCleanup(context.close)
        if init:
            context.add_init_script(init)
        watch_idle(context)
        page = context.new_page()
        requests, errors = [], []
        page.on("request", lambda r: requests.append((r.url, r.resource_type)))
        page.on("pageerror", lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.route("**/*", self.route)
        page.goto("http://viewer.test/?lang=%s" % lang, wait_until="domcontentloaded")
        page.wait_for_function(booted(3), timeout=20000)
        if wait:
            settle(page)
        return page, requests

    def platform_fonts(self, page):
        """{text: the fonts Chromium drew it in} for every FONT_PROBES element, from CSS.getPlatformFontsForNode: each
        font as (family, whether it is a web font)."""
        texts = page.evaluate(FONT_PROBES)
        cdp = page.context.new_cdp_session(page)
        cdp.send("DOM.enable")
        cdp.send("CSS.enable")
        root = cdp.send("DOM.getDocument", {"depth": 0})["root"]["nodeId"]
        out = {}
        for i, text in enumerate(texts):
            node = cdp.send("DOM.querySelector", {"nodeId": root, "selector": '[data-font-probe="%d"]' % i})["nodeId"]
            fonts = cdp.send("CSS.getPlatformFontsForNode", {"nodeId": node})["fonts"]
            out[text] = sorted({(f["familyName"], f["isCustomFont"]) for f in fonts})
        return out

    def test_the_interface_text_is_drawn_in_the_bundled_font_from_its_own_slices_only(self):
        """A phone and a desktop, Korean and English: once the fonts are ready, document.fonts.check says Pretendard
        Variable has '본문' (Korean) or 'Pins' (English) ready; every plain text in the sans stack is drawn in the web
        font Pretendard Variable and nothing else (there is Hangul among them in Korean); the page asked for the
        stylesheet and some of the 92 slices, all at /vendor/pretendard/ with the version, and made no request to
        another origin."""
        version = "v=%s" % assemble.PRETENDARD_VERSION
        for device in (PHONE, DESK):
            for lang in ("ko", "en"):
                with self.subTest(w=device["viewport"]["width"], lang=lang):
                    page, requests = self.view(device, lang)
                    word = "본문" if lang == "ko" else "Pins"
                    self.assertEqual(page.evaluate(FONTS_READY, word), {"status": "loaded", "check": True})
                    drawn = self.platform_fonts(page)
                    self.assertTrue(drawn)
                    other = {t: f for t, f in drawn.items() if not all(BUNDLED.fullmatch(n) and web for n, web in f)}
                    self.assertEqual(other, {})
                    if lang == "ko":
                        self.assertTrue(any(re.search(r"[가-힣]", t) for t in drawn), drawn)
                    urls = [urlparse(u) for u, _ in requests]
                    self.assertEqual({u.netloc for u in urls}, {"viewer.test"})
                    fonts = [urlparse(u) for u, kind in requests if kind == "font"]
                    self.assertTrue(fonts)
                    for u in fonts:
                        self.assertRegex(u.path, r"^/vendor/pretendard/PretendardVariable\.subset\.\d+\.woff2$")
                        self.assertEqual(u.query, version)
                    self.assertLess(len({u.path for u in fonts}), 92)
                    css = [u for u, kind in requests if kind == "stylesheet"]
                    self.assertEqual(css, ["http://viewer.test/vendor/pretendard/pretendard.css?%s" % version])

    def test_text_measures_are_taken_again_once_the_font_arrives(self):
        """A 430px phone in English and Korean with a monospace fallback (MONO_FALLBACK): its slices held back while the
        viewer boots and [더보기] opens, the bar's step and the foot's ink line are measured in the fallback and differ
        from a page that had the font from the start; once the slices are let through and have loaded, they are that
        page's."""
        device = dict(PHONE, viewport={"width": 430, "height": 932})
        for lang in ("en", "ko"):
            with self.subTest(lang=lang):
                page, _ = self.view(device, lang, init=MONO_FALLBACK)
                page.evaluate("openMore()")
                settle(page)
                want = page.evaluate(MEASURED)
                self.held = []
                page, _ = self.view(device, lang, wait=False, init=MONO_FALLBACK)
                page.evaluate("openMore()")
                page.wait_for_function("document.fonts.status === 'loading'")
                self.assertNotEqual(page.evaluate(MEASURED), want)
                self.release()
                self.assertEqual(page.evaluate(FONTS_READY, "Pins")["status"], "loaded")
                settle(page)
                self.assertEqual(page.evaluate(MEASURED), want)


if __name__ == "__main__":
    unittest.main()

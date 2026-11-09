"""The vendored KaTeX the page draws a Markdown document's math with (docs/adr/0036-markdown-drawn-math.md D1, D8).

GET /vendor/katex/<file> serves the module, the stylesheet and the fonts as the other bundles' files are served
(VendorMarkdownIt, VendorPdfjs): the right media type, one leaf name only, Host and Origin checked like any GET - and,
every URL carrying the version, a year's immutable cache.

The bundle's provenance is checked against itself, so a file replaced by hand without its README is a failure:

- SHA256SUMS lists every served file, and nothing else, with its hash (KatexFiles);
- katex.css is upstream's katex.min.css with one change in each of its 20 @font-face rules, so the upstream file is
  derived back from it and its sha256 compared with the README's; every font the stylesheet names is here and every
  font here is named (KatexStylesheet);
- the module is the unmodified ESM: it writes its output with DOM calls and holds no innerHTML, no eval and no
  Function, and the three `style` attributes the page policy would block are the known ones (KatexModule);
- THIRD_PARTY_NOTICES.md and the README name this version (KatexInventory).

What the drawn math looks like is in test_viewer_markdown_math.py; the rules that decide what is drawn are in
test_md_surface.py.

Run: uv run pytest -q src/limn/viewer/tests/test_vendor_katex.py
"""

import hashlib
import re
import unittest

from limn.viewer import assemble

from helpers import PKG, ROOT, Base, req, split_resp

VENDOR = PKG / "vendor" / "katex"
SUMS = VENDOR / "SHA256SUMS"
README = VENDOR / "README.md"
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
MODULE = VENDOR / "katex.mjs"
STYLESHEET = VENDOR / "katex.css"
V = assemble.KATEX_VERSION
# The served suffixes, in the order SHA256SUMS lists its files (the module, the stylesheet, then the fonts by name).
SERVED = (".mjs", ".css", ".woff2")
# One line of SHA256SUMS, as `shasum -a 256` writes it.
SUM_LINE = re.compile(r"^([0-9a-f]{64})  (\S+)$", re.M)
# One @font-face src of the served stylesheet, and the upstream triple it was derived from (vendor/katex/README.md).
SRC = re.compile(r'src:url\((KaTeX_[A-Za-z0-9-]+)\.woff2\?v=%s\) format\("woff2"\)' % re.escape(V))
UPSTREAM_SRC = 'src:url(fonts/%(n)s.woff2) format("woff2"),url(fonts/%(n)s.woff) format("woff"),url(fonts/%(n)s.ttf) format("truetype")'
# The provenance comment Limn prepends to the stylesheet, which the derivation takes off again.
LIMN_HEAD = re.compile(r"\A/\*\n(?: \*.*\n)* \*/\n/\* Limn:(?:.*\n)*?.*\*/\n")


def sums() -> dict[str, str]:
    """SHA256SUMS as name -> hash."""
    return {name: digest for digest, name in SUM_LINE.findall(SUMS.read_text(encoding="utf-8"))}


def upstream_css() -> str:
    """The upstream katex.min.css derived back from the served katex.css: the provenance comment off and each src list
    the upstream triple again. The one change the README claims, undone - so everything else must be upstream's."""
    text = LIMN_HEAD.sub("", STYLESHEET.read_text(encoding="utf-8"))
    return SRC.sub(lambda m: UPSTREAM_SRC % {"n": m.group(1)}, text)


class KatexFiles(unittest.TestCase):
    """The folder against SHA256SUMS."""

    def test_sha256sums_lists_every_served_file_and_each_hash_is_the_files(self):
        """Every file with a served suffix has a line, every line names a file that is there, and each hash matches.
        Mutation: change one byte of a font -> fails."""
        listed = sums()
        here = sorted(p.name for p in VENDOR.iterdir() if p.suffix in SERVED)
        self.assertEqual(sorted(listed), here)
        self.assertEqual(len(here), 22, here)  # the module, the stylesheet and 20 woff2
        for name, digest in listed.items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((VENDOR / name).read_bytes()).hexdigest(), digest)

    def test_only_the_served_suffixes_and_the_provenance_files_are_here(self):
        """No woff, no ttf, no katex-swap stylesheet, no contrib - the README says why each is left out."""
        names = {p.name for p in VENDOR.iterdir()}
        self.assertEqual(names - set(sums()), {"LICENSE", "README.md", "SHA256SUMS"})

    def test_default_dir_finds_repo_vendor(self):
        self.assertEqual(assemble.default_katex_dir().resolve(), VENDOR.resolve())


class KatexStylesheet(unittest.TestCase):
    """katex.css against upstream's katex.min.css and against the fonts beside it."""

    def test_it_is_upstream_with_one_change_in_each_font_face(self):
        """Taking the provenance comment off and putting the upstream src triple back gives a file whose sha256 is the
        one the README records for katex.min.css. Mutation: change any other byte of the stylesheet -> fails."""
        recorded = re.search(
            r"upstream `katex.min.css` \(sha256 `([0-9a-f]{8})…([0-9a-f]{5})`, ([\d,]+) bytes\)",
            README.read_text(encoding="utf-8"),
        )
        self.assertIsNotNone(recorded, "the README must record the upstream stylesheet's sha256 and size")
        assert recorded is not None
        back = upstream_css().encode("utf-8")
        digest = hashlib.sha256(back).hexdigest()
        self.assertEqual(len(back), int(recorded.group(3).replace(",", "")))
        self.assertTrue(digest.startswith(recorded.group(1)), digest)
        self.assertTrue(digest.endswith(recorded.group(2)), digest)

    def test_every_font_face_names_one_versioned_woff2_beside_it(self):
        """20 rules, each with exactly one src: a leaf name with this version. No subfolder, no woff, no ttf, so the
        route - which serves leaf names only - answers every URL the stylesheet names."""
        css = STYLESHEET.read_text(encoding="utf-8")
        self.assertEqual(css.count("@font-face{"), 20)
        self.assertEqual(css.count("src:"), 20)
        self.assertEqual(len(SRC.findall(css)), 20)
        for gone in ("fonts/", ".ttf", ".woff)", 'format("woff")', 'format("truetype")', "local("):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, css)

    def test_the_fonts_the_stylesheet_names_are_the_fonts_that_are_here(self):
        named = {"%s.woff2" % n for n in SRC.findall(STYLESHEET.read_text(encoding="utf-8"))}
        self.assertEqual(named, {p.name for p in VENDOR.iterdir() if p.suffix == ".woff2"})

    def test_nothing_outside_katex_is_styled_but_the_equation_counters(self):
        """A stylesheet the page adds for one document must not restyle the rest of the viewer. Upstream's only rule
        outside .katex resets the \\tag counters on body."""
        css = STYLESHEET.read_text(encoding="utf-8")
        bare = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        rules = [sel.strip() for block in re.findall(r"([^{}]+)\{", bare) for sel in block.split(",")]
        outside = sorted({r for r in rules if r and "katex" not in r and r != "@font-face"})
        self.assertEqual(outside, ["body"])
        self.assertIn("body{counter-reset:katexEqnNo mmlEqnNo}", css)


class KatexModule(unittest.TestCase):
    """katex.mjs as the page imports it."""

    def test_it_builds_its_output_with_dom_calls_and_holds_no_html_sink(self):
        """The reason the page may draw math at all under the page policy and the renderer's discipline (viewer.md
        §마크업 만들기): KaTeX writes elements, not markup. Mutation: a bundle built with innerHTML -> fails."""
        js = MODULE.read_text(encoding="utf-8")
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "new Function", "eval("):
            with self.subTest(sink=sink):
                self.assertNotIn(sink, js)
        self.assertIn("document.createElement", js)
        self.assertIn("document.createElementNS", js)
        self.assertIn("Object.assign(node.style, this.style)", js)  # inline sizes through the CSSOM, which CSP allows

    def test_the_style_attributes_the_page_policy_blocks_are_the_three_known_ones(self):
        """A `style` attribute is blocked by style-src, so each one is accounted for in ADR-0036: two MathML builders
        (\\boldsymbol, \\fcolorbox) lose their decoration, and the third is the throwOnError:false error colour, which the
        viewer never reaches. A new one in a later release is a failure, not a surprise."""
        js = MODULE.read_text(encoding="utf-8")
        found = re.findall(r'setAttribute\("style", (.*?)\);', js)
        self.assertEqual(len(found), 3, found)
        self.assertEqual(
            sorted(found),
            sorted(
                [
                    '"text-shadow: 0.02em 0.01em 0.04px"',
                    '"border: " + makeEm(thk) + " solid " + group.borderColor',
                    '"color:" + options.errorColor',
                ]
            ),
        )

    def test_it_exports_render_and_names_this_version(self):
        js = MODULE.read_text(encoding="utf-8")
        self.assertRegex(js, r"(?m)^  render,$")
        self.assertIn('version = "%s"' % V, js)


class VendorKatex(Base):
    """GET /vendor/katex/<file>."""

    def get(self, path, headers=None):
        return split_resp(self.talk(req("GET", path, headers=headers)))

    def test_serves_the_module_the_stylesheet_and_a_font(self):
        for name, media in (
            ("katex.mjs", "text/javascript; charset=utf-8"),
            ("katex.css", "text/css; charset=utf-8"),
            ("KaTeX_Main-Regular.woff2", "font/woff2"),
        ):
            with self.subTest(name=name):
                code, h, body = self.get("/vendor/katex/%s?v=%s" % (name, V))
                self.assertEqual(code, 200)
                self.assertEqual(h["content-type"], media)
                self.assertEqual(h["x-content-type-options"], "nosniff")
                self.assertEqual(h["cache-control"], "public, max-age=31536000, immutable")
                self.assertEqual(body, (VENDOR / name).read_bytes())

    def test_traversal_provenance_files_and_other_suffixes_are_404(self):
        for path in (
            "/vendor/katex/../markdown-it/markdown-it.esm.min.mjs",
            "/vendor/katex/..%2f..%2fserver.py",
            "/vendor/katex/LICENSE",
            "/vendor/katex/README.md",
            "/vendor/katex/SHA256SUMS",
            "/vendor/katex/fonts/KaTeX_Main-Regular.woff2",
            "/vendor/katex/fonts%2fKaTeX_Main-Regular.woff2",
            "/vendor/katex/.katex.mjs",
            "/vendor/katex/",
            "/vendor/katex/katex.mjs/",
            "/vendor/katex/none.mjs",
            "/vendor/katex/KaTeX_Main-Regular.woff",
            "/vendor/katex/KaTeX_Main-Regular.ttf",
        ):
            with self.subTest(path=path):
                code, h, _body = self.get(path)
                self.assertEqual(code, 404)
                self.assertEqual(h["cache-control"], "no-store")

    def test_host_and_origin_checked_like_other_gets(self):
        path = "/vendor/katex/katex.mjs"
        self.assertEqual(self.get(path, {"Host": "evil.example"})[0], 403)
        self.assertEqual(self.get(path, {"Origin": "https://evil.example"})[0], 403)

    def test_the_page_names_the_vendored_version_and_asks_for_nothing_else(self):
        """The page's own script imports the module and links the stylesheet at this version, from this origin, and no
        other katex URL is in it - the fonts come from the stylesheet."""
        page = assemble.read_viewer().template
        self.assertNotIn("__KATEX_VERSION__", page)
        self.assertEqual(
            sorted(set(re.findall(r"/vendor/katex/[A-Za-z0-9_.-]+", page))),
            ["/vendor/katex/katex.css", "/vendor/katex/katex.mjs"],
        )
        self.assertIn("'/vendor/katex/katex.mjs?v='+KATEX_V", page)
        self.assertIn("'/vendor/katex/katex.css?v='+KATEX_V", page)
        self.assertIn("const KATEX_V='%s';" % V, page)


class KatexInventory(unittest.TestCase):
    """The README and THIRD_PARTY_NOTICES.md against the bundle."""

    def test_the_version_is_the_modules_the_readmes_and_the_stylesheets(self):
        self.assertIn("katex@%s" % V, README.read_text(encoding="utf-8"))
        self.assertIn("KaTeX %s -" % V, STYLESHEET.read_text(encoding="utf-8"))
        self.assertIn("The MIT License (MIT)", (VENDOR / "LICENSE").read_text(encoding="utf-8"))

    def test_readme_records_the_license_hash_and_the_module_size(self):
        readme = README.read_text(encoding="utf-8")
        licence = hashlib.sha256((VENDOR / "LICENSE").read_bytes()).hexdigest()
        self.assertIn("`%s…%s`" % (licence[:8], licence[-6:]), readme)
        self.assertIn("(%s bytes)" % format(MODULE.stat().st_size, ","), readme)

    def test_third_party_notices_name_katex(self):
        notices = NOTICES.read_text(encoding="utf-8")
        self.assertIn("KaTeX", notices)
        self.assertIn(V, notices)
        self.assertIn("src/limn/vendor/katex/LICENSE", notices)

    def test_the_readme_links_only_files_that_are_there(self):
        """A relative link of the README that points inside the repository names a file that exists."""
        for ref in re.findall(r"\]\((?!https?:)([^)#]+)", README.read_text(encoding="utf-8")):
            with self.subTest(ref=ref):
                self.assertTrue((VENDOR / ref).resolve().exists(), ref)

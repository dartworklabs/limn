"""The interface font the viewer bundles: Pretendard Variable, its official dynamic subset (src/limn/vendor/pretendard/).

Every device draws the interface in this one build: the slices are the release's files
byte for byte (SHA256SUMS), and the stylesheet names each of them once, at its versioned URL, with no local() - so a
device's own fonts never take its place. GET /vendor/pretendard/<file> serves them like the bundled PDF.js
(docs/handbook/api.md §화면·PDF·정적 파일): one leaf name, a slice or the stylesheet, cached for good under its versioned URL.

Run: uv run pytest -q src/limn/viewer/tests/test_bundled_font.py
"""

import hashlib
import re
import unittest

from limn.viewer import assemble

from helpers import Base, req, split_resp

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


if __name__ == "__main__":
    unittest.main()

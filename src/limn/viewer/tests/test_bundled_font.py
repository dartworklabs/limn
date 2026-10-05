"""The interface font the viewer bundles: Pretendard Variable, its official dynamic subset (src/limn/vendor/pretendard/).

Every device draws the interface in this one build: the slices are the release's files
byte for byte (SHA256SUMS), and the stylesheet names each of them once, at its versioned URL, with no local() - so a
device's own fonts never take its place.

Run: uv run pytest -q src/limn/viewer/tests/test_bundled_font.py
"""

import hashlib
import re
import unittest

from limn.viewer import assemble

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


if __name__ == "__main__":
    unittest.main()

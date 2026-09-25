"""The viewer's source lives in src/limn/viewer as three build-free files the server inlines into one page.

index.html carries one __APP_CSS__ and one __APP_JS__ marker; app.css and app.js hold the exact text that goes
there. GET / must stay a single response, byte for byte what the template produced before the split.

Run: uv run pytest -q tests/test_viewer_files.py
"""
import tempfile
import unittest
from pathlib import Path

from test_server import PKG, ps

VIEWER = PKG / "viewer"
PARTS = {"__APP_CSS__": "app.css", "__APP_JS__": "app.js"}


class ViewerFiles(unittest.TestCase):
    """The packaged viewer files and how the server puts them back together."""

    def test_the_three_files_sit_next_to_the_server(self):
        """The server reads the viewer from its own package folder, never from the working directory."""
        self.assertEqual(ps.VIEWER_DIR, VIEWER)
        for name in ("index.html", "app.css", "app.js"):
            self.assertTrue((VIEWER / name).is_file(), name)

    def test_each_marker_appears_once_in_the_page_and_never_in_the_parts(self):
        """A marker inside CSS or JS would be replaced twice or leak into the page."""
        page = (VIEWER / "index.html").read_text(encoding="utf-8")
        for marker in PARTS:
            self.assertEqual(page.count(marker), 1, marker)
            for part in PARTS.values():
                self.assertNotIn(marker, (VIEWER / part).read_text(encoding="utf-8"), (marker, part))

    def test_assembled_page_inlines_the_whole_stylesheet_and_script(self):
        """load_viewer_html() puts app.css and app.js back where the markers were, unchanged."""
        page = ps.load_viewer_html(VIEWER)
        for marker, part in PARTS.items():
            self.assertNotIn(marker, page)
            self.assertIn((VIEWER / part).read_text(encoding="utf-8"), page)
        self.assertNotIn("__APP_", ps.HTML)

    def test_a_missing_marker_is_a_packaging_error_at_load(self):
        """A template without its marker fails loudly instead of serving a page without its script."""
        with tempfile.TemporaryDirectory() as d:
            broken = Path(d)
            (broken / "index.html").write_text("<style>__APP_CSS__</style><script></script>", encoding="utf-8")
            (broken / "app.css").write_text("body{}", encoding="utf-8")
            (broken / "app.js").write_text("boot();", encoding="utf-8")
            with self.assertRaises(ValueError):
                ps.load_viewer_html(broken)


if __name__ == "__main__":
    unittest.main()

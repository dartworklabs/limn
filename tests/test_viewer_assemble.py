"""limn/viewer/assemble.py: the viewer page as one string, from the viewer folder and the explicit inputs only.

viewer_html() joins index.html with its parts and fills the build-time placeholders (PDF.js version, the mark, the
icon table, the message table, {{ic:...}} tokens) from its arguments; the run-time ones (label, accent, favicon) are
left for server.py's build_html(). These tests drive it with a small viewer folder of their own, so the contract is
checked apart from the real page; tests/test_viewer_files.py checks the packaged page itself.

Run: uv run pytest -q tests/test_viewer_assemble.py
"""
import ast
import json
import tempfile
import unittest
from pathlib import Path

from limn.viewer import assemble

PAGE = ("<html><style>__APP_CSS__</style><title>__LABEL__</title>{{ic:x}}<i>__LIMN_MARK__</i>"
        "<script>const V='__PDFJS_VERSION__';const ICONS=__LUCIDE_JSON__;const I18N_EN=__UI_EN_JSON__;\n"
        "__APP_JS__</script></html>")
ICONS = {"x": '<path d="M1 1"/>', "a": '<path d="M2 2"/>'}


def viewer_folder(root: Path, page: str = PAGE) -> Path:
    """A minimal viewer folder under root: index.html, one CSS part, two JS parts and their manifest."""
    (root / "css").mkdir()
    (root / "js").mkdir()
    (root / "index.html").write_text(page, encoding="utf-8")
    (root / "css" / "a.css").write_text("b{}\n", encoding="utf-8")
    (root / "js" / "one.js").write_text("f();\n", encoding="utf-8")
    (root / "js" / "two.js").write_text("g({{ic:a}});\n", encoding="utf-8")
    (root / "parts.txt").write_text("__APP_CSS__\ncss/a.css\n__APP_JS__\njs/one.js\njs/two.js\n", encoding="utf-8")
    return root


class ViewerHtml(unittest.TestCase):
    """viewer_html(directory, messages, pdfjs_version=, mark=, icons=) -> the page before build_html()."""

    def setUp(self):
        """A fresh viewer folder per test."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = viewer_folder(Path(self.tmp.name))

    def html(self, messages=None, icons=ICONS):
        """The assembled test page with fixed inputs."""
        return assemble.viewer_html(self.dir, {"가": "A"} if messages is None else messages,
                                    pdfjs_version="9.9.9", mark="<svg id=m/>", icons=icons)

    def test_every_build_time_placeholder_is_filled_from_the_arguments(self):
        """The exact page: parts joined in order, the version, the mark, both JSON tables (sorted), icon tokens in
        the page and inside a part replaced - and the run-time __LABEL__ left for build_html()."""
        svg = lambda name: assemble.icon_svg(name, ICONS)  # noqa: E731 - a local shorthand
        expected = ("<html><style>b{}\n</style><title>__LABEL__</title>" + svg("x") + "<i><svg id=m/></i>"
                    "<script>const V='9.9.9';const ICONS=" + json.dumps(ICONS, sort_keys=True)
                    + ';const I18N_EN={"가": "A"};\nf();\ng(' + svg("a") + ");\n</script></html>")
        self.assertEqual(self.html(), expected)

    def test_the_same_inputs_give_the_same_page_whatever_the_table_order(self):
        """The JSON forms are sorted by key, so two tables with the same entries give the same bytes."""
        a = self.html({"b": "B", "a": {"one": "x", "other": "y"}}, dict(sorted(ICONS.items())))
        b = self.html({"a": {"one": "x", "other": "y"}, "b": "B"}, dict(reversed(sorted(ICONS.items()))))
        self.assertEqual(a, b)
        self.assertIn('{"a": {"one": "x", "other": "y"}, "b": "B"}', a)

    def test_a_message_can_never_close_the_script(self):
        """"</" in a message is written as "<\\/", which the JS string reads back the same."""
        out = self.html({"</script>": "</b>"})
        self.assertIn('{"<\\/script>": "<\\/b>"}', out)
        self.assertEqual(out.count("</script>"), 1)

    def test_an_icon_token_the_table_lacks_is_a_packaging_error(self):
        """{{ic:x}} with no "x" in the table raises instead of serving a page with a hole."""
        with self.assertRaises(KeyError):
            self.html(icons={"a": ICONS["a"]})

    def test_a_malformed_folder_raises(self):
        """A missing manifest (OSError) or a template without its marker (ValueError) fails at assembly."""
        (self.dir / "parts.txt").unlink()
        with self.assertRaises(OSError):
            self.html()
        with tempfile.TemporaryDirectory() as d:
            broken = viewer_folder(Path(d), PAGE.replace("__APP_JS__", ""))
            with self.assertRaises(ValueError):
                assemble.viewer_html(broken, {}, pdfjs_version="1", mark="", icons=ICONS)

    def test_the_packaged_page_keeps_only_the_run_time_placeholders(self):
        """The real folder with the real tables: no build-time placeholder or icon token survives, and the four
        placeholders build_html() fills are still there."""
        out = assemble.viewer_html(assemble.VIEWER_DIR, {}, pdfjs_version=assemble.PDFJS_VERSION, mark="<svg/>",
                                   icons=assemble.LUCIDE)
        for gone in ("__APP_CSS__", "__APP_JS__", "__PDFJS_VERSION__", "__LIMN_MARK__", "__LUCIDE_JSON__",
                     "__UI_EN_JSON__", "{{ic:"):
            self.assertNotIn(gone, out)
        for kept in ("__LABEL__", "__ACCENT__", "__ACCENT_KEY__", "__FAVICON_HREF__"):
            self.assertIn(kept, out)


class LoadUiMessages(unittest.TestCase):
    """load_ui_messages(path): the message table, with unusable entries dropped and a bad file as an empty table."""

    def test_a_missing_or_unreadable_file_is_an_empty_table(self):
        """No file, or a file that is not JSON, gives {} - the viewer then shows Korean only."""
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ui_en.json"
            self.assertEqual(assemble.load_ui_messages(path), {})
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(assemble.load_ui_messages(path), {})

    def test_only_strings_and_well_formed_plural_forms_are_kept(self):
        """Empty keys or values, non-string values and plural forms without a string "other" are dropped."""
        table = {"가": "A", "": "x", "나": "", "다": 3, "{n}라": {"one": "r", "other": "rs"}, "{n}마": {"one": "m"},
                 "{n}바": {"other": ""}}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ui_en.json"
            path.write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(assemble.load_ui_messages(path), {"가": "A", "{n}라": {"one": "r", "other": "rs"}})


class Independence(unittest.TestCase):
    """The assembly takes everything as arguments or from its own folder: no server state, no HTTP layer."""

    def test_imports_only_the_standard_library(self):
        """assemble.py imports json, re, pathlib, typing and collections.abc - never server.py, limn.web or settings."""
        tree = ast.parse(Path(assemble.__file__).read_text(encoding="utf-8"))
        modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        modules |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertEqual(modules, {"__future__", "json", "re", "collections.abc", "pathlib", "typing"})
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertEqual(names & {"C", "cur_doc", "HTML", "UI_EN"}, set())


if __name__ == "__main__":
    unittest.main()

"""limn/viewer/assemble.py: the viewer page and its script, from the viewer folder and the explicit inputs only.

viewer_html() joins index.html with its stylesheet parts and fills the build-time placeholders (the script's content key,
PDF.js, KaTeX and font versions, the logo's inline SVGs and icon key, {{ic:...}} tokens) from its arguments; the run-time
ones (label, accent) are left for run_page(). viewer_script() is the script GET /viewer.js serves, with the PDF.js and KaTeX
versions, the icon table, the message table and {{ic:...}} tokens filled. These tests drive it with a small viewer folder of their own, so the contract is
checked apart from the real page; src/limn/viewer/tests/test_viewer_files.py checks the packaged page itself.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_assemble.py
"""

import ast
import json
import tempfile
import unittest
from pathlib import Path

from limn.viewer import assemble, mark

BRAND_DIR = Path(mark.__file__).with_name("brand")  # the vendored logo files (server.BRAND_DIR)

PAGE = (
    "<html><style>__APP_CSS__</style><title>__LABEL__</title>{{ic:x}}<i>__LIMN_MARK_16__</i><b>__LIMN_WORDMARK__</b><u>v__LIMN_VERSION__</u>"
    '<link href="/favicon.ico?v=__ICON_KEY__"><link rel="stylesheet" href="/f.css?v=__PRETENDARD_VERSION__">'
    '<script src="/viewer.js?v=__VIEWER_JS_KEY__"></script></html>'
)
# The script's modules: placeholders in the first, an icon token in the second. The built script (dist/viewer.js) is
# their text joined, as tools/build_viewer.mjs writes it for modules with no import or export.
SCRIPT_PARTS = (
    "const V='__PDFJS_VERSION__',W='__KATEX_VERSION__';const ICONS=__LUCIDE_JSON__;const I18N_EN=__UI_EN_JSON__;\nf();\n",
    "g({{ic:a}});\n",
)
ICONS = {"x": '<path d="M1 1"/>', "a": '<path d="M2 2"/>'}


def viewer_folder(root: Path, page: str = PAGE) -> Path:
    """A minimal viewer folder under root: index.html, one CSS part, two JS modules, their manifest and the built script."""
    (root / "css").mkdir()
    (root / "js").mkdir()
    (root / "dist").mkdir()
    (root / "dist" / "viewer.js").write_text("".join(SCRIPT_PARTS), encoding="utf-8")
    (root / "index.html").write_text(page, encoding="utf-8")
    (root / "css" / "a.css").write_text("b{}\n", encoding="utf-8")
    (root / "js" / "one.js").write_text(SCRIPT_PARTS[0], encoding="utf-8")
    (root / "js" / "two.js").write_text(SCRIPT_PARTS[1], encoding="utf-8")
    (root / "parts.txt").write_text("__APP_CSS__\ncss/a.css\n__APP_JS__\njs/one.js\njs/two.js\n", encoding="utf-8")
    return root


class ViewerHtml(unittest.TestCase):
    """viewer_html(directory, pdfjs_version=, katex_version=, pretendard_version=, marks=, icon_key=, icons=,
    version=, script_key=) -> the page before run_page(); viewer_script(directory, messages, pdfjs_version=,
    katex_version=, icons=) -> the script GET /viewer.js serves."""

    def setUp(self):
        """A fresh viewer folder per test."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = viewer_folder(Path(self.tmp.name))

    def html(self, icons=ICONS):
        """The assembled test page with fixed inputs."""
        return assemble.viewer_html(
            self.dir,
            pdfjs_version="9.9.9",
            katex_version="7.7.7",
            pretendard_version="8.8.8",
            marks={"__LIMN_MARK_16__": "<svg id=m/>", "__LIMN_WORDMARK__": "<svg id=w/>"},
            icon_key="0123456789ab",
            icons=icons,
            version="1.2.3",
            script_key="00112233aabbccdd",
        )

    def script(self, messages=None, icons=ICONS):
        """The test folder's script with fixed inputs."""
        return assemble.viewer_script(
            self.dir,
            {"가": "A"} if messages is None else messages,
            pdfjs_version="9.9.9",
            katex_version="7.7.7",
            icons=icons,
        )

    def test_every_build_time_placeholder_is_filled_from_the_arguments(self):
        """The exact page: the stylesheet parts joined in order, the script's key, the font version, each logo placeholder
        its markup, Limn's version ([더보기]'s foot), the icon key and the page's icon tokens - and the run-time __LABEL__
        left for run_page(). The exact script: the built script (dist/viewer.js) with the PDF.js and KaTeX versions, both JSON
        tables (sorted) and the icon token inside it replaced."""
        svg = lambda name: assemble.icon_svg(name, ICONS)  # noqa: E731 - a local shorthand
        page = (
            "<html><style>b{}\n</style><title>__LABEL__</title>"
            + svg("x")
            + "<i><svg id=m/></i><b><svg id=w/></b><u>v1.2.3</u>"
            '<link href="/favicon.ico?v=0123456789ab"><link rel="stylesheet" href="/f.css?v=8.8.8">'
            '<script src="/viewer.js?v=00112233aabbccdd"></script></html>'
        )
        self.assertEqual(self.html(), page)
        script = (
            "const V='9.9.9',W='7.7.7';const ICONS="
            + json.dumps(ICONS, sort_keys=True)
            + ';const I18N_EN={"가": "A"};\nf();\ng('
            + svg("a")
            + ");\n"
        )
        self.assertEqual(self.script(), script)

    def test_the_script_key_is_its_content_hash(self):
        """script_key is the first 16 hex digits of the script's SHA-256: the same script, the same key; another, another."""
        self.assertEqual(assemble.script_key("a"), "ca978112ca1bbdca")
        self.assertNotEqual(assemble.script_key(self.script()), assemble.script_key(self.script({"나": "B"})))

    def test_the_same_inputs_give_the_same_script_whatever_the_table_order(self):
        """The JSON forms are sorted by key, so two tables with the same entries give the same bytes."""
        a = self.script({"b": "B", "a": {"one": "x", "other": "y"}}, dict(sorted(ICONS.items())))
        b = self.script({"a": {"one": "x", "other": "y"}, "b": "B"}, dict(reversed(sorted(ICONS.items()))))
        self.assertEqual(a, b)
        self.assertIn('{"a": {"one": "x", "other": "y"}, "b": "B"}', a)

    def test_a_message_keeps_its_closing_tag_escaped(self):
        """ "</" in a message is written as "<\\/", which the JS string reads back the same: the table is written as it
        was when the script sat inside the page, so a copy of the script put back inline still cannot be closed by it."""
        out = self.script({"</script>": "</b>"})
        self.assertIn('{"<\\/script>": "<\\/b>"}', out)
        self.assertNotIn("</script", out)

    def test_an_icon_token_the_table_lacks_is_a_packaging_error(self):
        """{{ic:x}} with no "x" in the table raises instead of serving a page with a hole, and so does {{ic:a}} in the
        script."""
        with self.assertRaises(KeyError):
            self.html(icons={"a": ICONS["a"]})
        with self.assertRaises(KeyError):
            self.script(icons={"x": ICONS["x"]})

    def test_a_malformed_folder_raises(self):
        """A missing manifest or built script (OSError), a template without its stylesheet marker or with the script's
        (ValueError) fails at assembly."""
        (self.dir / "dist" / "viewer.js").unlink()
        with self.assertRaises(OSError):
            self.script()
        (self.dir / "parts.txt").unlink()
        with self.assertRaises(OSError):
            self.html()
        for page in (PAGE.replace("__APP_CSS__", ""), PAGE.replace("</html>", "<script>__APP_JS__</script></html>")):
            with self.subTest(page=page[-60:]), tempfile.TemporaryDirectory() as d:
                broken = viewer_folder(Path(d), page)
                with self.assertRaises(ValueError):
                    assemble.viewer_html(
                        broken,
                        pdfjs_version="1",
                        katex_version="1",
                        pretendard_version="1",
                        marks={},
                        icon_key="k",
                        icons=ICONS,
                        version="1",
                        script_key="k",
                    )

    def test_the_packaged_page_keeps_only_the_run_time_placeholders(self):
        """The real folder with the real tables and logo: no build-time placeholder or icon token survives in the page or
        the script, and the placeholders run_page() fills are still in the page (and none in the script, which every run
        serves the same)."""
        logo = mark.brand({name: (BRAND_DIR / name).read_bytes() for name in mark.FILES})
        script = assemble.viewer_script(
            assemble.VIEWER_DIR,
            {},
            pdfjs_version=assemble.PDFJS_VERSION,
            katex_version=assemble.KATEX_VERSION,
            icons=assemble.LUCIDE,
        )
        out = assemble.viewer_html(
            assemble.VIEWER_DIR,
            pdfjs_version=assemble.PDFJS_VERSION,
            katex_version=assemble.KATEX_VERSION,
            pretendard_version=assemble.PRETENDARD_VERSION,
            marks=logo.marks,
            icon_key=logo.key,
            icons=assemble.LUCIDE,
            version="0.0.0",
            script_key=assemble.script_key(script),
        )
        for gone in (
            "__APP_CSS__",
            "__APP_JS__",
            "__PDFJS_VERSION__",
            "__PRETENDARD_VERSION__",
            "__LIMN_",
            "__ICON_KEY__",
            "__LUCIDE_JSON__",
            "__UI_EN_JSON__",
            "{{ic:",
            "__VIEWER_JS_KEY__",
            "__KATEX_VERSION__",
        ):
            self.assertNotIn(gone, out)
            self.assertNotIn(gone, script)
        for kept in ("__LABEL__", "__ACCENT__", "__UI_LANG__"):
            self.assertIn(kept, out)
            self.assertNotIn(kept, script)
        for gone in ("__ACCENT_KEY__", "__FAVICON_HREF__"):
            self.assertNotIn(gone, out)


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
        table = {
            "가": "A",
            "": "x",
            "나": "",
            "다": 3,
            "{n}라": {"one": "r", "other": "rs"},
            "{n}마": {"one": "m"},
            "{n}바": {"other": ""},
        }
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ui_en.json"
            path.write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(assemble.load_ui_messages(path), {"가": "A", "{n}라": {"one": "r", "other": "rs"}})


class Independence(unittest.TestCase):
    """The assembly takes everything as arguments or from its own folder: no server state, no HTTP layer."""

    def test_imports_only_the_standard_library(self):
        """assemble.py imports the standard library, the pure mark (limn.viewer.mark, for the served icons' type) and the
        package's version string (limn.__version__, for [더보기]'s foot - a constant like PDFJS_VERSION) - never server.py,
        limn.web or settings."""
        tree = ast.parse(Path(assemble.__file__).read_text(encoding="utf-8"))
        modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        modules |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertEqual(
            modules,
            {
                "hashlib",
                "html",
                "json",
                "re",
                "collections.abc",
                "dataclasses",
                "pathlib",
                "typing",
                "limn",
                "limn.viewer.mark",
            },
        )
        froms = {(n.module, a.name) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        self.assertIn(("limn", "__version__"), froms)
        self.assertEqual([a for m, a in froms if m == "limn"], ["__version__"])
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertEqual(names & {"C", "cur_doc", "HTML", "UI_EN"}, set())


class ServiceWorker(unittest.TestCase):
    """service_worker: the script GET /sw.js serves, read from the viewer folder as it is."""

    def test_reads_sw_js_unchanged_and_a_missing_file_raises(self):
        """The folder's sw.js comes back byte for byte (placeholders untouched); without one it is a packaging defect."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with self.assertRaises(OSError):
                assemble.service_worker(root)
            (root / "sw.js").write_text("'use strict';\nconst L='__LABEL__';\n", encoding="utf-8")
            self.assertEqual(assemble.service_worker(root), "'use strict';\nconst L='__LABEL__';\n")

    def test_the_packaged_worker_keeps_the_document_but_never_the_api(self):
        """The shipped worker answers notification clicks and keeps this document for reading with no network
        (docs/handbook/viewer.md §끊긴 채 보기와 핀 쌓기). Pin and meta answers are never kept: a stale list must never
        read as the current one."""
        sw = assemble.service_worker(assemble.VIEWER_DIR)
        self.assertIn("notificationclick", sw)
        self.assertIn("addEventListener('fetch'", sw)
        self.assertIn("startsWith('/api/')", sw)


class ServedPage(unittest.TestCase):
    """serve_viewer / run_page: the page one run serves is the template with its label and accent filled in; the
    template itself (ViewerFiles) stays as read, and the icons pass through."""

    def test_the_served_page_fills_the_run_placeholders_and_leaves_the_template(self):
        """Both run-time placeholders are filled (the label escaped, the accent as given); the service worker, the
        message table and the icons pass through unchanged, and the ViewerFiles template still holds the placeholders."""
        template = '<title>__LABEL__</title><i s="__ACCENT__"></i><link href="/favicon.ico?v=0123456789ab">'
        icons = {"/favicon.ico": mark.Icon(b"ico", "image/x-icon")}
        files = assemble.ViewerFiles(template, "sw", {"가": "A"}, icons)
        served = assemble.serve_viewer(files, "<A&B>", "#BE123C", None)
        self.assertEqual(
            served.page, '<title>&lt;A&amp;B&gt;</title><i s="#BE123C"></i><link href="/favicon.ico?v=0123456789ab">'
        )
        self.assertEqual((served.service_worker, served.messages, served.icons), ("sw", {"가": "A"}, icons))
        self.assertIn("__LABEL__", files.template)

    def test_the_icons_are_the_same_for_every_label_and_accent(self):
        """Two runs with different labels and accents serve the same icon values: the favicon is never the instance
        colour (the tab title tells instances apart)."""
        icons = {"/favicon.ico": mark.Icon(b"ico", "image/x-icon")}
        files = assemble.ViewerFiles("<title>__LABEL__</title>", "sw", {}, icons)
        a, b = assemble.serve_viewer(files, "A", "#1d4ed8", None), assemble.serve_viewer(files, "B", "#be123c", "ko")
        self.assertEqual(a.icons, b.icons)
        self.assertNotEqual(a.page, b.page)

    def test_the_instance_ui_language_fills_the_head_script(self):
        """run_page(template, label, accent, ui_lang): __UI_LANG__ becomes ko or en, and the empty string without --ui-lang
        (the head script then skips that step); the same arguments give the same bytes."""
        template = "<script>var d='__UI_LANG__';</script><title>__LABEL__</title>"
        self.assertEqual(
            assemble.run_page(template, "A", "#1d4ed8", None), "<script>var d='';</script><title>A</title>"
        )
        self.assertEqual(
            assemble.run_page(template, "A", "#1d4ed8", "ko"), "<script>var d='ko';</script><title>A</title>"
        )
        self.assertEqual(
            assemble.run_page(template, "A", "#1d4ed8", "en"), assemble.run_page(template, "A", "#1d4ed8", "en")
        )
        self.assertEqual(
            assemble.serve_viewer(assemble.ViewerFiles(template, "sw", {}), "A", "#1d4ed8", "en").page,
            "<script>var d='en';</script><title>A</title>",
        )

    def test_the_packaged_head_script_reads_the_ui_language_placeholder(self):
        """The viewer's language script has the one run-time placeholder __UI_LANG__ (index.html's <head>)."""
        head = (assemble.VIEWER_DIR / "index.html").read_text(encoding="utf-8").split("<body>")[0]
        self.assertEqual(head.count("__UI_LANG__"), 1)


if __name__ == "__main__":
    unittest.main()

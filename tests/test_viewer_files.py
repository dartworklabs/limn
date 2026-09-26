"""The viewer's source lives in src/limn/viewer as build-free files the server inlines into one page.

index.html carries one __APP_CSS__ and one __APP_JS__ marker. parts.txt lists, per marker and in page order, the part
files under css/ and js/; the server joins each list byte for byte into the marker's place, so the stylesheet is one
<style> and the script one classic <script> sharing a single scope - no bundler, no module loader. GET / must stay a
single response, byte for byte what the parts joined in that order produce. The page's inline scripts must parse:
node --check runs on each of them (skipped without node, required where LIMN_TEST_REQUIRE_NODE=1, as in CI).

Run: uv run pytest -q tests/test_viewer_files.py
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from test_server import PKG, ps

VIEWER = PKG / "viewer"
EXT = {"__APP_CSS__": ".css", "__APP_JS__": ".js"}


def viewer_text(marker: str, directory: Path = VIEWER) -> str:
    """The text the server puts at marker: the manifest's parts for it, joined in order (what test_brand reads)."""
    return "".join((directory / n).read_text(encoding="utf-8") for n in ps.viewer_manifest(directory)[marker])


class _InlineScripts(HTMLParser):
    """Collects the text of every inline <script> (one without src) in document order."""

    def __init__(self):
        """Start with no scripts; convert_charrefs=False keeps script text exactly as served."""
        super().__init__(convert_charrefs=False)
        self.scripts: list[str] = []
        self._inside = False

    def handle_starttag(self, tag, attrs):
        """Open a script to collect unless it loads its code from src."""
        if tag == "script" and not dict(attrs).get("src"):
            self._inside = True
            self.scripts.append("")

    def handle_endtag(self, tag):
        """Close the script being collected."""
        if tag == "script":
            self._inside = False

    def handle_data(self, data):
        """Script text arrives as data (HTMLParser treats <script> content as CDATA)."""
        if self._inside:
            self.scripts[-1] += data


def inline_scripts(page: str) -> list[str]:
    """The inline scripts of an HTML page, in order."""
    p = _InlineScripts()
    p.feed(page)
    p.close()
    return p.scripts


def part_line(line: int, directory: Path = VIEWER) -> str:
    """Which JS part line `line` (1-based) of the main script comes from, as 'js/name.js:N'. The main script is the
    joined parts with single-line placeholders filled, so its line numbers are the parts' lines laid end to end."""
    for name in ps.viewer_manifest(directory)["__APP_JS__"]:
        n = (directory / name).read_text(encoding="utf-8").count("\n")
        if line <= n:
            return "%s:%d" % (name, line)
        line -= n
    return "after the last part"


def script_errors(page: str, directory: Path = VIEWER) -> list[str] | None:
    """node --check on every inline script of page as a classic script: the error text of each that fails ([] = all
    parse), led by the part file and line for the main (last) script. None when node is not installed. Each script is
    written to a .cjs file so node never reads it as an ES module."""
    node = shutil.which("node")
    if not node:
        return None
    errors = []
    scripts = inline_scripts(page)
    with tempfile.TemporaryDirectory() as d:
        for i, js in enumerate(scripts):
            path = Path(d) / ("script-%d.cjs" % i)
            path.write_text(js, encoding="utf-8")
            r = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=30, check=False)
            if r.returncode == 0:
                continue
            where = "inline script %d" % i
            at = re.match(r".*?" + re.escape(path.name) + r":(\d+)", r.stderr.strip())   # node may print the real path
            if at and i == len(scripts) - 1:
                where += " at " + part_line(int(at.group(1)), directory)
            errors.append("%s: %s" % (where, r.stderr.strip()))
    return errors


class ViewerFiles(unittest.TestCase):
    """The packaged viewer files, their manifest, and how the server puts them back together."""

    def test_the_page_and_every_listed_part_sit_next_to_the_server(self):
        """The server reads the viewer from its own package folder, never from the working directory, and every
        part the manifest names is a file there with the extension of its marker's language."""
        self.assertEqual(ps.VIEWER_DIR, VIEWER)
        self.assertTrue((VIEWER / "index.html").is_file())
        manifest = ps.viewer_manifest(VIEWER)
        self.assertEqual(tuple(manifest), ps.VIEWER_MARKERS)
        for marker, names in manifest.items():
            for name in names:
                self.assertTrue((VIEWER / name).is_file(), name)
                self.assertEqual(Path(name).suffix, EXT[marker], name)

    def test_every_part_file_is_listed_exactly_once(self):
        """A file under css/ or js/ that the manifest forgets would silently never reach the page."""
        on_disk = sorted(p.relative_to(VIEWER).as_posix() for d in ("css", "js") for p in (VIEWER / d).rglob("*")
                         if p.is_file())
        listed = sorted(n for names in ps.viewer_manifest(VIEWER).values() for n in names)
        self.assertEqual(listed, on_disk)

    def test_every_part_is_whole_lines(self):
        """Each part ends with a newline, so joining never glues one file's last line to the next file's first (a
        glued line could change what the script means, e.g. a `//` comment swallowing the next file's first line)."""
        for names in ps.viewer_manifest(VIEWER).values():
            for name in names:
                self.assertTrue((VIEWER / name).read_text(encoding="utf-8").endswith("\n"), name)

    def test_each_marker_appears_once_in_the_page_and_never_in_the_parts(self):
        """A marker inside CSS or JS would be replaced twice or leak into the page."""
        page = (VIEWER / "index.html").read_text(encoding="utf-8")
        for marker in ps.VIEWER_MARKERS:
            self.assertEqual(page.count(marker), 1, marker)
        for names in ps.viewer_manifest(VIEWER).values():
            for name in names:
                text = (VIEWER / name).read_text(encoding="utf-8")
                for marker in ps.VIEWER_MARKERS:
                    self.assertNotIn(marker, text, (marker, name))

    def test_assembled_page_is_the_parts_joined_in_manifest_order(self):
        """load_viewer_html() is index.html with each marker replaced by its parts joined in the listed order -
        nothing added between or around them - and the served template keeps no marker."""
        expected = (VIEWER / "index.html").read_text(encoding="utf-8")
        for marker in ps.VIEWER_MARKERS:
            expected = expected.replace(marker, viewer_text(marker))
        self.assertEqual(ps.load_viewer_html(VIEWER), expected)
        self.assertNotIn("__APP_", ps.HTML)

    def test_a_missing_marker_is_a_packaging_error_at_load(self):
        """A template without its marker fails loudly instead of serving a page without its script."""
        with tempfile.TemporaryDirectory() as d:
            broken = Path(d)
            (broken / "index.html").write_text("<style>__APP_CSS__</style><script></script>", encoding="utf-8")
            (broken / "parts.txt").write_text("__APP_CSS__\ncss/a.css\n__APP_JS__\njs/a.js\n", encoding="utf-8")
            for name, text in (("css/a.css", "body{}\n"), ("js/a.js", "boot();\n")):
                (broken / name).parent.mkdir(exist_ok=True)
                (broken / name).write_text(text, encoding="utf-8")
            with self.assertRaises(ValueError):
                ps.load_viewer_html(broken)

    def test_a_malformed_manifest_is_a_packaging_error_at_load(self):
        """The manifest decides what the page contains, so any line it cannot place fails at import: a part before
        any marker, an unknown or repeated marker, a marker with no parts or missing, a part listed twice, a path
        that could leave the viewer folder."""
        cases = {
            "part before a marker": "css/a.css\n__APP_CSS__\ncss/b.css\n__APP_JS__\njs/a.js\n",
            "unknown marker": "__APP_CSS__\ncss/a.css\n__APP_JS__\njs/a.js\n__APP_X__\njs/b.js\n",
            "repeated marker": "__APP_CSS__\ncss/a.css\n__APP_JS__\njs/a.js\n__APP_CSS__\ncss/b.css\n",
            "marker without parts": "__APP_CSS__\n__APP_JS__\njs/a.js\n",
            "missing marker": "__APP_JS__\njs/a.js\n",
            "part twice": "__APP_CSS__\ncss/a.css\n__APP_JS__\njs/a.js\njs/a.js\n",
            "path out of the folder": "__APP_CSS__\n../a.css\n__APP_JS__\njs/a.js\n",
            "absolute path": "__APP_CSS__\n/etc/a.css\n__APP_JS__\njs/a.js\n",
        }
        for why, text in cases.items():
            with self.subTest(why), tempfile.TemporaryDirectory() as d:
                (Path(d) / "parts.txt").write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    ps.viewer_manifest(Path(d))

    def test_manifest_comments_and_blank_lines_are_not_parts(self):
        """A '#' comment (whole line or after a path) and blank lines carry no part, so the manifest can say what
        each part is for."""
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "parts.txt").write_text("# order\n\n__APP_CSS__   # style\ncss/a.css  # tokens\n\n"
                                               "__APP_JS__\njs/a.js\njs/b.js # last\n", encoding="utf-8")
            self.assertEqual(ps.viewer_manifest(Path(d)),
                             {"__APP_CSS__": ("css/a.css",), "__APP_JS__": ("js/a.js", "js/b.js")})


class ViewerScriptParses(unittest.TestCase):
    """The served page's inline scripts are valid JavaScript (node --check), whatever the part files look like alone."""

    def setUp(self):
        """Skip without node, unless LIMN_TEST_REQUIRE_NODE=1 (CI), where a missing node is a failure."""
        if shutil.which("node"):
            return
        if os.environ.get("LIMN_TEST_REQUIRE_NODE") == "1":
            self.fail("node is required (LIMN_TEST_REQUIRE_NODE=1) but not installed")
        self.skipTest("node is not installed")

    def test_every_inline_script_of_the_served_page_parses(self):
        """The page GET / serves - parts joined and every placeholder filled - has three inline scripts (two in the
        head, the main one at the end of the body), and node parses each as a classic script."""
        page = ps.build_html("Paper", "#2563eb")
        scripts = inline_scripts(page)
        self.assertEqual(len(scripts), 3)
        self.assertIn(viewer_text("__APP_JS__")[:200], scripts[-1])
        self.assertEqual(script_errors(page), [])

    def test_a_syntax_error_planted_in_one_part_fails_the_check_and_names_the_part(self):
        """The check sees through the split: one bad line at the top of a part in the middle of the list is a
        SyntaxError of the assembled main script, reported at that part's line 1, while the same folder without the
        plant parses (so the failure is the plant, not the copy or its unfilled placeholders)."""
        with tempfile.TemporaryDirectory() as d:
            copy = Path(d) / "viewer"
            shutil.copytree(VIEWER, copy)
            self.assertEqual(script_errors(ps.load_viewer_html(copy), copy), [])
            names = ps.viewer_manifest(copy)["__APP_JS__"]
            victim = names[len(names) // 2]
            (copy / victim).write_text("const = 1;\n" + (copy / victim).read_text(encoding="utf-8"), encoding="utf-8")
            errors = script_errors(ps.load_viewer_html(copy), copy)
            self.assertEqual(len(errors), 1, errors)
            self.assertIn("SyntaxError", errors[0])
            self.assertIn(" at %s:1:" % victim, errors[0])

if __name__ == "__main__":
    unittest.main()

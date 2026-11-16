"""The viewer's source lives in src/limn/viewer as files the server puts together into a page and its script.

parts.txt lists, per section and in order, the part files under css/ and js/. index.html carries one __APP_CSS__ marker,
where the server joins the stylesheet parts byte for byte into its one <style>; the script parts are joined the same way
into the one classic script GET /viewer.js serves (ViewerScriptRoute), which the page loads from this origin. The page's
inline scripts and the served script must parse: node --check runs on each of them (skipped without node, required
where LIMN_TEST_REQUIRE_NODE=1, as in CI). The notification service worker is its own file, served at GET /sw.js
(ServiceWorkerRoute).

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_files.py
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from limn.viewer import assemble

from helpers import HTML, SCRIPT, SW_JS, VIEWER, VIEWER_FILES, Base, page_for, req, split_resp, viewer_text
from helpers_js import inline_scripts

EXT = {"__APP_CSS__": ".css", "__APP_JS__": ".js"}


def part_line(line: int, directory: Path = VIEWER) -> str:
    """Which JS part line `line` (1-based) of the main script comes from, as 'js/name.js:N'. The main script is the
    joined parts with single-line placeholders filled, so its line numbers are the parts' lines laid end to end."""
    for name in assemble.viewer_manifest(directory)["__APP_JS__"]:
        n = (directory / name).read_text(encoding="utf-8").count("\n")
        if line <= n:
            return "%s:%d" % (name, line)
        line -= n
    return "after the last part"


def script_errors(scripts: list[str], directory: Path = VIEWER) -> list[str] | None:
    """node --check on every script of scripts as a classic script: the error text of each that fails ([] = all parse),
    led by the part file and line for the viewer's own script (the last one). None when node is not installed. Each
    script is written to a .cjs file so node never reads it as an ES module."""
    node = shutil.which("node")
    if not node:
        return None
    errors = []
    with tempfile.TemporaryDirectory() as d:
        for i, js in enumerate(scripts):
            path = Path(d) / ("script-%d.cjs" % i)
            path.write_text(js, encoding="utf-8")
            r = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=30, check=False)
            if r.returncode == 0:
                continue
            where = "script %d" % i
            at = re.match(r".*?" + re.escape(path.name) + r":(\d+)", r.stderr.strip())  # node may print the real path
            if at and i == len(scripts) - 1:
                where += " at " + part_line(int(at.group(1)), directory)
            errors.append("%s: %s" % (where, r.stderr.strip()))
    return errors


class ViewerFiles(unittest.TestCase):
    """The packaged viewer files, their manifest, and how the server puts them back together."""

    def test_the_page_and_every_listed_part_sit_next_to_the_server(self):
        """The server reads the viewer from its own package folder, never from the working directory, and every
        part the manifest names is a file there with the extension of its marker's language."""
        self.assertEqual(assemble.VIEWER_DIR, VIEWER)
        self.assertTrue((VIEWER / "index.html").is_file())
        manifest = assemble.viewer_manifest(VIEWER)
        self.assertEqual(tuple(manifest), assemble.VIEWER_MARKERS)
        for marker, names in manifest.items():
            for name in names:
                self.assertTrue((VIEWER / name).is_file(), name)
                self.assertEqual(Path(name).suffix, EXT[marker], name)

    def test_every_part_file_is_listed_exactly_once(self):
        """A file under css/ or js/ that the manifest forgets would silently never reach the page."""
        on_disk = sorted(
            p.relative_to(VIEWER).as_posix() for d in ("css", "js") for p in (VIEWER / d).rglob("*") if p.is_file()
        )
        listed = sorted(n for names in assemble.viewer_manifest(VIEWER).values() for n in names)
        self.assertEqual(listed, on_disk)

    def test_every_part_is_whole_lines(self):
        """Each part ends with a newline, so joining never glues one file's last line to the next file's first (a
        glued line could change what the script means, e.g. a `//` comment swallowing the next file's first line)."""
        for names in assemble.viewer_manifest(VIEWER).values():
            for name in names:
                self.assertTrue((VIEWER / name).read_text(encoding="utf-8").endswith("\n"), name)

    def test_each_marker_appears_once_in_the_page_and_never_in_the_parts(self):
        """A marker inside CSS or JS would be replaced twice or leak into the page; the script's marker is not in the
        page at all (the page loads the script from this origin)."""
        page = (VIEWER / "index.html").read_text(encoding="utf-8")
        for marker in assemble.VIEWER_MARKERS:
            self.assertEqual(page.count(marker), 1 if marker in assemble.PAGE_MARKERS else 0, marker)
        self.assertEqual(page.count('<script src="/viewer.js?v=__VIEWER_JS_KEY__"></script>'), 1)
        for names in assemble.viewer_manifest(VIEWER).values():
            for name in names:
                text = (VIEWER / name).read_text(encoding="utf-8")
                for marker in assemble.VIEWER_MARKERS:
                    self.assertNotIn(marker, text, (marker, name))

    def test_assembled_page_is_the_parts_joined_in_manifest_order(self):
        """load_viewer_html() is index.html with the stylesheet marker replaced by its parts joined in the listed order,
        and load_viewer_script() the script parts joined the same way - nothing added between or around them - and
        neither the served template nor the served script keeps a marker."""
        expected = (
            (VIEWER / "index.html").read_text(encoding="utf-8").replace("__APP_CSS__", viewer_text("__APP_CSS__"))
        )
        self.assertEqual(assemble.load_viewer_html(VIEWER), expected)
        self.assertEqual(assemble.load_viewer_script(VIEWER), viewer_text("__APP_JS__"))
        self.assertNotIn("__APP_", HTML)

    def test_a_missing_marker_is_a_packaging_error_at_load(self):
        """A template without its stylesheet marker, or with the script's marker still in it, fails loudly instead of
        serving a page without its style or with a hole for a script it no longer inlines."""
        for page in ("<style></style><script></script>", "<style>__APP_CSS__</style><script>__APP_JS__</script>"):
            with self.subTest(page=page), tempfile.TemporaryDirectory() as d:
                broken = Path(d)
                (broken / "index.html").write_text(page, encoding="utf-8")
                (broken / "parts.txt").write_text("__APP_CSS__\ncss/a.css\n__APP_JS__\njs/a.js\n", encoding="utf-8")
                for name, text in (("css/a.css", "body{}\n"), ("js/a.js", "boot();\n")):
                    (broken / name).parent.mkdir(exist_ok=True)
                    (broken / name).write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    assemble.load_viewer_html(broken)

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
                    assemble.viewer_manifest(Path(d))

    def test_manifest_comments_and_blank_lines_are_not_parts(self):
        """A '#' comment (whole line or after a path) and blank lines carry no part, so the manifest can say what
        each part is for."""
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "parts.txt").write_text(
                "# order\n\n__APP_CSS__   # style\ncss/a.css  # tokens\n\n__APP_JS__\njs/a.js\njs/b.js # last\n",
                encoding="utf-8",
            )
            self.assertEqual(
                assemble.viewer_manifest(Path(d)), {"__APP_CSS__": ("css/a.css",), "__APP_JS__": ("js/a.js", "js/b.js")}
            )


class ViewerScriptParses(unittest.TestCase):
    """The served page's inline scripts and its script are valid JavaScript (node --check), whatever the part files look
    like alone."""

    def setUp(self):
        """Skip without node, unless LIMN_TEST_REQUIRE_NODE=1 (CI), where a missing node is a failure."""
        if shutil.which("node"):
            return
        if os.environ.get("LIMN_TEST_REQUIRE_NODE") == "1":
            self.fail("node is required (LIMN_TEST_REQUIRE_NODE=1) but not installed")
        self.skipTest("node is not installed")

    def test_every_script_of_the_served_page_parses(self):
        """The page GET / serves has two inline scripts (in the head: theme and language), and the script it loads (GET
        /viewer.js: the parts joined, every placeholder filled) is the viewer's; node parses each as a classic script."""
        page = page_for("Paper", "#2563eb")
        scripts = inline_scripts(page)
        self.assertEqual(len(scripts), 2)
        unfilled = re.split(r"__[A-Z_]+__", viewer_text("__APP_JS__"))[0]  # the parts up to their first placeholder
        self.assertTrue(SCRIPT.startswith(unfilled))
        self.assertEqual(script_errors([*scripts, SCRIPT]), [])

    def test_a_syntax_error_planted_in_one_part_fails_the_check_and_names_the_part(self):
        """The check sees through the split: one bad line at the top of a part in the middle of the list is a
        SyntaxError of the assembled main script, reported at that part's line 1, while the same folder without the
        plant parses (so the failure is the plant, not the copy or its unfilled placeholders)."""
        with tempfile.TemporaryDirectory() as d:
            copy = Path(d) / "viewer"
            shutil.copytree(VIEWER, copy)
            self.assertEqual(script_errors([assemble.load_viewer_script(copy)], copy), [])
            names = assemble.viewer_manifest(copy)["__APP_JS__"]
            victim = names[len(names) // 2]
            (copy / victim).write_text("const = 1;\n" + (copy / victim).read_text(encoding="utf-8"), encoding="utf-8")
            errors = script_errors([assemble.load_viewer_script(copy)], copy)
            self.assertEqual(len(errors), 1, errors)
            self.assertIn("SyntaxError", errors[0])
            self.assertIn(" at %s:1:" % victim, errors[0])

    def test_the_served_service_worker_parses(self):
        """GET /sw.js serves viewer/sw.js as it is (SW_JS), and node parses it as a classic script."""
        self.assertEqual(SW_JS, (VIEWER / "sw.js").read_text(encoding="utf-8"))
        r = subprocess.run(
            [shutil.which("node"), "--check", str(VIEWER / "sw.js")],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(r.returncode, 0, r.stderr)


class ViewerScriptRoute(Base):
    """GET /viewer.js serves the page's script: JavaScript, revalidated, host-checked, the very text the page's key names."""

    def get(self, path, headers=None):
        code, h, raw = split_resp(self.talk(req("GET", path, headers=headers)))
        return code, h, raw

    def test_the_script_route_serves_the_script_the_page_names(self):
        """The page loads /viewer.js?v=<key> once; that URL answers the filled script whose key it is, as JavaScript that
        the browser asks again on every load (as it did when the script came inside the page), with a policy that only
        forbids framing. Another host is refused as for any GET."""
        page = page_for("Paper", "#2563eb")
        key = assemble.script_key(VIEWER_FILES.script)
        self.assertEqual(page.count('<script src="/viewer.js?v=%s"></script>' % key), 1)
        code, h, raw = self.get("/viewer.js?v=" + key)
        self.assertEqual(code, 200)
        self.assertEqual(h["content-type"], "text/javascript; charset=utf-8")
        self.assertEqual(h["cache-control"], "no-cache")
        self.assertEqual(h["content-security-policy"], "frame-ancestors 'none'")
        self.assertEqual(raw.decode("utf-8"), VIEWER_FILES.script)
        self.assertEqual(self.get("/viewer.js", {"Host": "evil.example"})[0], 403)


class ServiceWorkerRoute(Base):
    """GET /sw.js serves the notification service worker: JavaScript, not cached, host-checked, no app-data cache."""

    def setUp(self):
        super().setUp()

    def get(self, path, headers=None):
        code, h, raw = split_resp(self.talk(req("GET", path, headers=headers)))
        return code, h, raw

    def test_service_worker_route(self):
        code, h, raw = self.get("/sw.js")
        self.assertEqual(code, 200)
        self.assertEqual(h["content-type"], "text/javascript; charset=utf-8")
        self.assertEqual(h["cache-control"], "no-cache")
        js = raw.decode()
        self.assertIn("notificationclick", js)
        self.assertIn("clients.openWindow", js)
        # v0.2.2: [되살리기] on a 'dropped' notification
        self.assertIn("postMessage({type:e.action==='restore'?'restore-pin':'open-pin'", js)
        self.assertIn("addEventListener('fetch'", js)  # keeps the document for reading with no network
        self.assertIn("startsWith('/api/')", js)  # but never a pin or meta answer: a stale list is not the current one
        code, _, _ = self.get("/sw.js", {"Host": "evil.example"})
        self.assertEqual(code, 403)
        if shutil.which("node"):
            r = subprocess.run(["node", "--check", "-"], input=js, capture_output=True, text=True, check=False)
            self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()

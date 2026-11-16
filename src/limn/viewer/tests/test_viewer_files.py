"""The viewer's source lives in src/limn/viewer as files the server puts together into a page and its script.

parts.txt lists, per section and in order, the stylesheet parts under css/ and the ES modules under js/. index.html carries
one __APP_CSS__ marker, where the server joins the stylesheet parts byte for byte into its one <style>. The modules are
built into one classic script, dist/viewer.js (tools/build_viewer.mjs, docs/adr/0042-viewer-es-modules.md), which the
repository keeps and GET /viewer.js serves (ViewerScriptRoute); the page loads it from this origin. The built script is
the modules' code in the listed order with their import and export statements taken out - checked here without node;
CI also builds it again and compares the bytes (npm run build:check). The page's inline scripts and the served script
must parse as classic scripts and each module as a module: node --check runs on each of them (skipped without node,
required where LIMN_TEST_REQUIRE_NODE=1, as in CI). The notification service worker is its own file, served at GET /sw.js
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
from helpers_js import inline_scripts, module_code

EXT = {"__APP_CSS__": ".css", "__APP_JS__": ".js"}


def script_errors(scripts: list[str], module: bool = False) -> list[str] | None:
    """node --check on every script of scripts - as a classic script, or as an ES module when module is set: the error
    text of each that fails ([] = all parse). None when node is not installed. Each script is written to a .cjs or .mjs
    file so node reads it the way it is meant."""
    node = shutil.which("node")
    if not node:
        return None
    errors = []
    with tempfile.TemporaryDirectory() as d:
        for i, js in enumerate(scripts):
            path = Path(d) / ("script-%d.%s" % (i, "mjs" if module else "cjs"))
            path.write_text(js, encoding="utf-8")
            r = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=30, check=False)
            if r.returncode:
                errors.append("script %d: %s" % (i, r.stderr.strip()))
    return errors


def module_errors(directory: Path = VIEWER) -> list[str] | None:
    """node --check on each module parts.txt lists under __APP_JS__, as an ES module: 'js/name.js: <error>' for each that
    fails ([] = all parse), None without node."""
    names = assemble.viewer_manifest(directory)["__APP_JS__"]
    errors = script_errors([(directory / n).read_text(encoding="utf-8") for n in names], module=True)
    if errors is None:
        return None
    return ["%s: %s" % (names[int(e.split(":")[0].split()[1])], e) for e in errors]


def built_from_modules(built: str, plant: bool = False) -> str:
    """What dist/viewer.js should hold for the modules as they are: its first three lines ('use strict' and the build's
    note), then each listed module's code in order; with plant, one module carries an extra line."""
    modules = [
        module_code((VIEWER / n).read_text(encoding="utf-8")) for n in assemble.viewer_manifest(VIEWER)["__APP_JS__"]
    ]
    if plant:
        modules[len(modules) // 2] += "const planted=1;\n"
    return "\n".join(built.split("\n")[:3]) + "\n" + "\n".join(modules)


def without_blank_lines(text: str) -> str:
    """text with every run of line breaks made one: the build leaves or drops a blank line where it takes a module's
    import and export statements out, and nothing else is spacing."""
    return re.sub(r"\n+", "\n", text).strip("\n")


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
        """load_viewer_html() is index.html with the stylesheet marker replaced by its parts joined in the listed order -
        nothing added between or around them - load_viewer_script() is the built script as the repository keeps it, and
        neither the served template nor the served script keeps a marker."""
        page = (VIEWER / "index.html").read_text(encoding="utf-8")
        self.assertEqual(assemble.load_viewer_html(VIEWER), page.replace("__APP_CSS__", viewer_text("__APP_CSS__")))
        self.assertEqual(
            assemble.load_viewer_script(VIEWER), (VIEWER / "dist" / "viewer.js").read_text(encoding="utf-8")
        )
        self.assertNotIn("__APP_", HTML)

    def test_the_built_script_is_the_modules_code_in_list_order(self):
        """dist/viewer.js is 'use strict', the build's note, then each listed module's code (module_code: its import and
        export statements taken out) in the listed order, byte for byte but for blank lines - so the committed script
        cannot fall behind a module, or run them in another order, without this failing (CI also rebuilds and compares
        the bytes)."""
        built = (VIEWER / "dist" / "viewer.js").read_text(encoding="utf-8")
        self.assertTrue(built.startswith("'use strict';\n// Built by tools/build_viewer.mjs"), built[:80])
        self.assertEqual(without_blank_lines(built), without_blank_lines(built_from_modules(built)))

    def test_a_module_left_behind_fails_the_check(self):
        """The check above sees a line added to one module that the built script lacks."""
        built = (VIEWER / "dist" / "viewer.js").read_text(encoding="utf-8")
        self.assertNotEqual(without_blank_lines(built), without_blank_lines(built_from_modules(built, plant=True)))

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
        /viewer.js: the built script, every placeholder filled) is the viewer's; node parses each as a classic script."""
        page = page_for("Paper", "#2563eb")
        scripts = inline_scripts(page)
        self.assertEqual(len(scripts), 2)
        built = (VIEWER / "dist" / "viewer.js").read_text(encoding="utf-8")
        unfilled = re.split(r"__[A-Z_]+__", built)[0]  # the built script up to its first placeholder
        self.assertTrue(SCRIPT.startswith(unfilled))
        self.assertEqual(script_errors([*scripts, SCRIPT]), [])

    def test_every_module_parses_and_a_planted_error_names_its_module(self):
        """Each listed module parses as an ES module; one bad line at the top of a module in the middle of the list is a
        SyntaxError reported for that module, while the same folder without the plant parses (so the failure is the
        plant, not the copy)."""
        with tempfile.TemporaryDirectory() as d:
            copy = Path(d) / "viewer"
            shutil.copytree(VIEWER, copy)
            self.assertEqual(module_errors(copy), [])
            names = assemble.viewer_manifest(copy)["__APP_JS__"]
            victim = names[len(names) // 2]
            (copy / victim).write_text("const = 1;\n" + (copy / victim).read_text(encoding="utf-8"), encoding="utf-8")
            errors = module_errors(copy)
            self.assertEqual(len(errors), 1, errors)
            self.assertIn("SyntaxError", errors[0])
            self.assertTrue(errors[0].startswith(victim + ": "), errors[0])

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

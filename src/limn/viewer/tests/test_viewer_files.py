"""The packaged viewer serves its ordered stylesheets inline and its prebuilt classic script from the same origin.

The Node build checks module reachability and bundle freshness. These tests also check the syntax of the served
scripts and individual modules when Node is available.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_files.py
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from limn.viewer import assemble

from helpers import (
    HTML,
    SCRIPT,
    SW_JS,
    VIEWER,
    VIEWER_FILES,
    Base,
    page_for,
    req,
    split_resp,
    sq,
    viewer_css,
    viewer_modules,
)
from helpers_js import inline_scripts, strip_results


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
    """Every module under js/ through the build's first step and node --check: its types taken out
    (tools/strip_types.mjs refuses a module TypeScript cannot parse with a SyntaxError), then its code parsed as an ES
    module. 'js/name.ts: <error>' for each that fails ([] = all parse), None without node."""
    names = viewer_modules(directory)
    if not shutil.which("node"):
        return None
    results = strip_results(tuple((n, (directory / n).read_text(encoding="utf-8")) for n in names))
    out = ["%s: %s" % (n, text) for n, (ok, text) in zip(names, results, strict=True) if not ok]
    stripped = [(n, text) for n, (ok, text) in zip(names, results, strict=True) if ok]
    errors = script_errors([text for _, text in stripped], module=True) or []
    return out + ["%s: %s" % (stripped[int(e.split(":")[0].split()[1])][0], e) for e in errors]


class ViewerFiles(unittest.TestCase):
    """The packaged viewer files, their stylesheets, and how the server puts them back together."""

    def test_stylesheet_list_covers_every_css_part_once(self):
        """An omitted stylesheet would disappear from the page."""
        self.assertEqual(assemble.VIEWER_DIR, VIEWER)
        listed = assemble.STYLESHEETS
        on_disk = [p.relative_to(VIEWER).as_posix() for p in (VIEWER / "css").rglob("*") if p.is_file()]
        self.assertCountEqual(listed, on_disk)
        for name in listed:
            self.assertTrue((VIEWER / name).read_bytes().endswith(b"\n"), name)

    def test_source_modules_end_with_a_newline(self):
        """Source inspections read whole lines from each module."""
        for name in viewer_modules():
            self.assertTrue((VIEWER / name).read_bytes().endswith(b"\n"), name)

    def test_assembled_page_is_the_parts_joined_in_cascade_order(self):
        """load_viewer_html() is index.html with the stylesheet marker replaced by its parts joined in the listed order -
        nothing added between or around them - load_viewer_script() is the built script as the repository keeps it, and
        neither the served template nor the served script keeps a marker."""
        page = (VIEWER / "index.html").read_text(encoding="utf-8")
        self.assertEqual(assemble.load_viewer_html(VIEWER), page.replace("__APP_CSS__", viewer_css()))
        self.assertEqual(
            assemble.load_viewer_script(VIEWER), (VIEWER / "dist" / "viewer.js").read_text(encoding="utf-8")
        )
        self.assertNotIn("__APP_", HTML)

    def test_inline_css_preserves_cascade_order_and_file_contents(self):
        """Conflicting rules in the fixture reach the browser in the declared cascade order."""
        with tempfile.TemporaryDirectory() as d, patch.object(assemble, "STYLESHEETS", ("css/z.css", "css/a.css")):
            root = Path(d)
            (root / "css").mkdir()
            (root / "css/z.css").write_text("b{color:red}\n", encoding="utf-8")
            (root / "css/a.css").write_text("b{color:blue}\n", encoding="utf-8")
            (root / "index.html").write_text("<style>__APP_CSS__</style>", encoding="utf-8")
            self.assertEqual(assemble.load_viewer_html(root), "<style>b{color:red}\nb{color:blue}\n</style>")


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
        """Each source module parses as an ES module; one bad line at the top of a module in the middle of the list is a
        SyntaxError reported for that module, while the same folder without the plant parses (so the failure is the
        plant, not the copy)."""
        with tempfile.TemporaryDirectory() as d:
            copy = Path(d) / "viewer"
            shutil.copytree(VIEWER, copy)
            self.assertEqual(module_errors(copy), [])
            names = viewer_modules(copy)
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
        self.assertIn(sq("postMessage({type:e.action==='restore'?'restore-pin':'open-pin'"), sq(js))
        self.assertIn("addEventListener('fetch'", js)  # keeps the document for reading with no network
        self.assertIn("startsWith('/api/')", js)  # but never a pin or meta answer: a stale list is not the current one
        code, _, _ = self.get("/sw.js", {"Host": "evil.example"})
        self.assertEqual(code, 403)
        if shutil.which("node"):
            r = subprocess.run(["node", "--check", "-"], input=js, capture_output=True, text=True, check=False)
            self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()

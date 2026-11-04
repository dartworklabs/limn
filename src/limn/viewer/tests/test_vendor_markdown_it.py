"""The vendored markdown-it and the Markdown parse worker that imports it (docs/adr/0025-html-document-surface.md D5).

GET /vendor/markdown-it/<file>.mjs serves the ESM browser build as PDF.js's files are served (VendorPdfjs in
src/limn/runtime/tests/test_server.py): JavaScript, a day's cache, nothing but a leaf .mjs, Host and Origin checked like any
GET. GET /md-parse.mjs serves the parse worker, its import's version filled in. The bundle inlines other packages, so the
inventory in vendor/markdown-it/README.md is checked against the file itself: every `//#region` the bundle names and
every code marker the inventory gives has a row, and each row's licence file is there, unmodified as its size and sha256
say, and named in THIRD_PARTY_NOTICES.md.

Run: uv run pytest -q src/limn/viewer/tests/test_vendor_markdown_it.py
"""

import hashlib
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from limn.viewer import assemble, routes
from limn.viewer.application import ViewerShell
from limn.web.errors import HTTPError
from limn.web.routes import GetRequest

from helpers import PKG, ROOT, Base, ps, req, split_resp

VENDOR = PKG / "vendor" / "markdown-it"
BUNDLE = VENDOR / "markdown-it.esm.min.mjs"
README = VENDOR / "README.md"
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
WORKER = PKG / "viewer" / assemble.MD_WORKER
# A row of the README's inventory table: package, version, licence, region, marker, licence file, bytes, licence sha256.
ROW = re.compile(
    r"^\| (?P<package>[^|]+?) \| [^|]+ \| [^|]+ \|\s*(?P<region>[^|]*?)\s*\|\s*(?P<marker>[^|]*?)\s*\| "
    r"\[`licenses/(?P<file>[^`]+)`\]\(licenses/[^)]+\) \| (?P<bytes>[\d,]+) \| `(?P<sha>[0-9a-f]{64})` \|",
    re.M,
)


def inventory(readme: str) -> list[dict[str, str]]:
    """The README's inventory rows, their cells stripped of spaces and backticks."""
    return [{k: v.strip().strip("`") for k, v in m.groupdict().items()} for m in ROW.finditer(readme)]


def bundle_regions(bundle: str) -> set[str]:
    """The packages the bundle's region markers name: node_modules/<package> and \\0<package>[@version] (one folder deep),
    the markdown-it's own src/ left out."""
    found = set()
    for m in re.finditer(r"^//#region (\S+)", bundle, re.M):
        where = m.group(1)
        if where.startswith("node_modules/"):
            found.add("/".join(where.split("/")[:2]))
        elif where.startswith("\\0"):
            found.add(where.split("/")[0])
    return found


def missing_rows(bundle: str, rows: list[dict[str, str]]) -> list[str]:
    """What the inventory leaves out: each region the bundle names without a row, each row's marker the bundle lacks."""
    regions = {r["region"] for r in rows if r["region"]}
    out = ["region %s" % r for r in sorted(bundle_regions(bundle) - regions)]
    out += ["marker %r" % r["marker"] for r in rows if r["marker"] and r["marker"] not in bundle]
    return out


class VendorMarkdownIt(Base):
    """GET /vendor/markdown-it/<file> and GET /md-parse.mjs."""

    def get(self, path, headers=None):
        return split_resp(self.talk(req("GET", path, headers=headers)))

    def test_serves_the_module_as_javascript(self):
        code, h, body = self.get("/vendor/markdown-it/markdown-it.esm.min.mjs?v=%s" % assemble.MARKDOWN_IT_VERSION)
        self.assertEqual(code, 200)
        self.assertEqual(h["content-type"], "text/javascript; charset=utf-8")
        self.assertEqual(h["x-content-type-options"], "nosniff")
        self.assertEqual(h["cache-control"], "public, max-age=86400")
        self.assertEqual(body, BUNDLE.read_bytes())

    def test_traversal_licences_and_non_module_names_are_404(self):
        for path in (
            "/vendor/markdown-it/../pdfjs/pdf.min.mjs",
            "/vendor/markdown-it/..%2f..%2fserver.py",
            "/vendor/markdown-it/LICENSE",
            "/vendor/markdown-it/README.md",
            "/vendor/markdown-it/licenses/entities-8.1.0.LICENSE",
            "/vendor/markdown-it/licenses%2fentities-8.1.0.LICENSE",
            "/vendor/markdown-it/.markdown-it.esm.min.mjs",
            "/vendor/markdown-it/",
            "/vendor/markdown-it/markdown-it.esm.min.mjs/",
            "/vendor/markdown-it/none.mjs",
        ):
            with self.subTest(path=path):
                code, h, body = self.get(path)
                self.assertEqual(code, 404)
                self.assertNotIn(b"Permission is hereby granted", body)
                self.assertEqual(h["cache-control"], "no-store")

    def test_host_and_origin_checked_like_other_gets(self):
        path = "/vendor/markdown-it/markdown-it.esm.min.mjs"
        self.assertEqual(self.get(path, {"Host": "evil.example"})[0], 403)
        self.assertEqual(self.get(path, {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.get("/md-parse.mjs", {"Host": "evil.example"})[0], 403)

    def test_the_parse_worker_imports_this_version_and_is_not_cached(self):
        """GET /md-parse.mjs is viewer/md-parse.mjs with the version filled: it imports exactly the vendored file at
        MARKDOWN_IT_VERSION, from this origin, and nothing else."""
        code, h, body = self.get("/md-parse.mjs")
        self.assertEqual(code, 200)
        self.assertEqual(h["content-type"], "text/javascript; charset=utf-8")
        self.assertEqual(h["cache-control"], "no-cache")
        js = body.decode()
        self.assertEqual(js, WORKER.read_text(encoding="utf-8").replace("__MARKDOWN_IT_VERSION__", "15.0.3"))
        self.assertEqual(
            re.findall(r"^import .* from '([^']+)';$", js, re.M),
            ["/vendor/markdown-it/markdown-it.esm.min.mjs?v=%s" % assemble.MARKDOWN_IT_VERSION],
        )
        self.assertNotIn("import(", js)
        self.assertNotIn("importScripts", js)

    def test_a_viewer_without_the_worker_answers_404(self):
        """A served viewer with no worker (ServedViewer's default, as a stand-in viewer has) answers 404 not_found."""
        served = assemble.ServedViewer("<p></p>", "", {})
        app = ViewerShell(lambda: ps.APP.C, lambda: served)
        request = GetRequest("/md-parse.mjs", {}, ps.APP.docs[0], {}, None, "127.0.0.1", lambda: None)
        with self.assertRaises(HTTPError) as caught:
            routes.get(request, app)
        self.assertEqual((caught.exception.code, caught.exception.body["reason"]), (404, "not_found"))

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_the_worker_parses_as_a_module(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "md-parse.mjs"
            path.write_text(assemble.md_worker(WORKER.parent, assemble.MARKDOWN_IT_VERSION), encoding="utf-8")
            r = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_default_dir_finds_repo_vendor(self):
        self.assertEqual(assemble.default_markdown_it_dir().resolve(), VENDOR.resolve())


class MarkdownItInventory(unittest.TestCase):
    """vendor/markdown-it/README.md against the bundle, the licence files and THIRD_PARTY_NOTICES.md."""

    def test_the_version_is_the_bundles_and_the_readmes(self):
        head = BUNDLE.read_bytes()[:200].decode("utf-8")
        self.assertTrue(head.startswith("/*! markdown-it %s " % assemble.MARKDOWN_IT_VERSION), head)
        self.assertIn("markdown-it@%s" % assemble.MARKDOWN_IT_VERSION, README.read_text(encoding="utf-8"))
        self.assertIn("Permission is hereby granted", (VENDOR / "LICENSE").read_text(encoding="utf-8"))

    def test_readme_sizes_and_sha256_match_the_files(self):
        readme = README.read_text(encoding="utf-8")
        for name in ("markdown-it.esm.min.mjs", "LICENSE"):
            with self.subTest(name=name):
                data = (VENDOR / name).read_bytes()
                m = re.search(r"\| `%s` \| ([\d,]+) \| `([0-9a-f]{64})` \|" % re.escape(name), readme)
                self.assertIsNotNone(m, name)
                self.assertEqual(int(m.group(1).replace(",", "")), len(data))
                self.assertEqual(m.group(2), hashlib.sha256(data).hexdigest())

    def test_every_licence_file_is_listed_with_its_size_and_sha256(self):
        """Each row's licence file is there as the row says, and every file under licenses/ has a row."""
        rows = inventory(README.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(rows), 9)
        for r in rows:
            with self.subTest(file=r["file"]):
                data = (VENDOR / "licenses" / r["file"]).read_bytes()
                self.assertEqual(int(r["bytes"].replace(",", "")), len(data))
                self.assertEqual(r["sha"], hashlib.sha256(data).hexdigest())
        self.assertEqual({r["file"] for r in rows}, {p.name for p in (VENDOR / "licenses").iterdir()})

    def test_every_region_and_marker_of_the_bundle_has_a_row(self):
        """Every node_modules/<package> and \\0<package> region the bundle names is a row's, and every row's code marker
        is in the bundle - entities, mdurl, the rolldown runtime and the oxc helpers by region; linkify-it, uc.micro,
        punycode.js and Babel's typeof by marker."""
        bundle = BUNDLE.read_text(encoding="utf-8")
        rows = inventory(README.read_text(encoding="utf-8"))
        self.assertEqual(
            bundle_regions(bundle),
            {"node_modules/entities", "node_modules/mdurl", "\\0rolldown", "\\0@oxc-project+runtime@0.154.0"},
        )
        self.assertEqual(missing_rows(bundle, rows), [])

    def test_the_inventory_check_finds_a_row_left_out(self):
        """The check above is not vacuous: without entities' row its region is missing, and a marker the bundle lacks is
        found."""
        bundle = BUNDLE.read_text(encoding="utf-8")
        rows = inventory(README.read_text(encoding="utf-8"))
        without = [r for r in rows if r["package"] != "entities"]
        self.assertEqual(missing_rows(bundle, without), ["region node_modules/entities"])
        bogus = rows + [dict(rows[0], region="", marker="not in the bundle")]
        self.assertEqual(missing_rows(bundle, bogus), ["marker 'not in the bundle'"])

    def test_third_party_notices_name_markdown_it_and_every_bundled_package(self):
        notices = NOTICES.read_text(encoding="utf-8")
        self.assertIn("markdown-it", notices)
        self.assertIn("src/limn/vendor/markdown-it/LICENSE", notices)
        self.assertIn("src/limn/vendor/markdown-it/licenses/", notices)
        for package in (
            "entities",
            "mdurl",
            "linkify-it",
            "uc.micro",
            "punycode.js",
            "rolldown",
            "@oxc-project/runtime",
        ):
            with self.subTest(package=package):
                self.assertIn("`%s`" % package if package != "rolldown" else "rolldown", notices)
        self.assertIn("@babel/runtime", notices)
        self.assertIn("Joyent", notices)
        self.assertIn("THIRD-PARTY-LICENSE", notices)


if __name__ == "__main__":
    unittest.main()

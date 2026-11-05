"""The Markdown surface's tree references (docs/adr/0030-markdown-tree-images-and-document-links.md): a relative path resolved
against the document's own path (mdRelPath), what an image's source loads (mdImgPath), what a link may do (mdTarget) and the
only address an image is fetched from (mdAssetUrl).

The served functions run under node, on hrefs as the vendored markdown-it hands them over (it percent-encodes a link's
destination), so the rules see what the viewer sees. The browser behaviour - images drawn and kept in place, a link to another
document and back, an SVG opened on its own - is in test_viewer_markdown_assets.py; the server's own check of every path in
src/limn/documents/tests/test_assets.py.

Run: uv run pytest -q src/limn/viewer/tests/test_md_tree_refs.py
"""

import json
import os
import shutil
import unittest
from pathlib import Path

import limn
from limn.documents.assets import ASSET_TYPES, AssetPath, asset_path

from helpers import extract_js_fn, run_node

BUNDLE = Path(limn.__file__).resolve().parent / "vendor" / "markdown-it" / "markdown-it.esm.min.mjs"
ORIGIN = "https://limn.example.ts.net:18020"
BASE = "docs/guide.md"
DOCS = [
    {"key": "rd", "name": "README", "path": "README.md"},
    {"key": "gd", "name": "안내", "path": "docs/guide.md"},
    {"key": "pl", "name": "계획", "path": "notes/plan.md"},
    {"key": "ms", "name": "본문", "path": "paper/main.tex"},
]

# ref (as written in docs/guide.md) -> mdRelPath's answer: [path, frag], 'out', 'bad' or None (no relative reference).
REL = {
    "img/a.png": ["docs/img/a.png", ""],
    "./img/a.png": ["docs/img/a.png", ""],
    "../README.md": ["README.md", ""],
    "../notes/plan.md#일정": ["notes/plan.md", "일정"],
    "../notes/plan.md?plain=1#x": ["notes/plan.md", "x"],
    "/notes/plan.md": ["notes/plan.md", ""],
    "a/../b.png": ["docs/b.png", ""],
    "img//a.png": ["docs/img/a.png", ""],
    "%EA%B7%B8%EB%A6%BC.png": ["docs/그림.png", ""],
    "../../outside.png": "out",
    "../../../etc/passwd": "out",
    "..%2F..%2Foutside.png": "out",
    "img/%2e%2e/%2e%2e/%2e%2e/x.png": "out",
    "../.git/config": "bad",
    ".env": "bad",
    "img/.hidden.png": "bad",
    "a%5Cb.png": "bad",
    "a%00.png": "bad",
    "%E0%A4%A": "bad",
    "#heading": None,
    "": None,
    "?x=1": None,
    "..": None,
    "https://example.org/a.png": None,
    "//evil.example/a.png": None,
    "mailto:a@example.com": None,
    "data:image/png;base64,AAAA": None,
    "javascript:x": None,
    "C:foo.png": None,
}

# src -> mdImgPath's answer: a tree path, or why it is not loaded.
IMG = {
    "img/chart.png": "docs/img/chart.png",
    "../figures/photo.JPG": "figures/photo.JPG",
    "img/flow.svg": "docs/img/flow.svg",
    "https://tracker.example/p.png": "remote",
    "http://tracker.example/p.png": "remote",
    "//tracker.example/p.png": "remote",
    "data:image/png;base64,AAAA": "data",
    "DATA:image/svg+xml,<svg/>": "data",
    "../../outside.png": "out",
    "../.git/logo.png": "out",
    "notes.txt": "type",
    "img/": "type",
    "file:///etc/x.png": "other",
    "ftp://example.org/a.png": "other",
}

# href -> mdTarget's open value (and, for a document, its key and heading).
TARGET = {
    "../README.md": ["doc", "rd", ""],
    "../notes/plan.md#일정": ["doc", "pl", "일정"],
    "/paper/main.tex": ["doc", "ms", ""],
    "guide.md#설치": ["doc", "gd", "설치"],
    "../figures/photo.jpg": ["asset"],
    "../notes/todo.txt": [None, "unregistered"],
    "../../outside.png": [None, "out"],
    "../.git/config": [None, "out"],
    "/api/pins": [None, "unregistered"],
    "/api/asset?doc=gd&path=x.png": [None, "unregistered"],
    "https://example.org/a": ["web"],
    ORIGIN + "/api/meta": [None, ""],
    "http://localhost:18920/api/pins": [None, ""],
    "#설치": ["anchor"],
    "mailto:a@example.com": ["mail"],
    "ftp://example.org/f": [None, ""],
}


class TreeReferenceRules(unittest.TestCase):
    """mdRelPath, mdImgPath, mdTarget and mdAssetUrl, as served."""

    def setUp(self):
        """Skip without node, unless LIMN_TEST_REQUIRE_NODE=1 makes that a failure."""
        if not shutil.which("node"):
            if os.environ.get("LIMN_TEST_REQUIRE_NODE") == "1":
                self.fail("node required (LIMN_TEST_REQUIRE_NODE=1) but not installed")
            self.skipTest("node not available")

    def node(self, body: str):
        """body run with the served functions and `md` (the vendored markdown-it as the parse worker configures it); `out`
        is the answer, as JSON."""
        fns = ("mdHostKey", "mdSameOrigin", "mdIpv6", "mdLoopback", "mdHref", "mdRelPath", "mdIsImg", "mdImgPath")
        js = "\n".join(
            [
                *(extract_js_fn(f) for f in fns),
                extract_js_fn("mdTarget"),
                extract_js_fn("mdAssetUrl"),
                "const MD_IMG_EXT=['png','jpg','jpeg','gif','webp','svg'];",
                "const {pathToFileURL}=require('node:url');",
                "(async()=>{const MarkdownIt=(await import(pathToFileURL(%s).href)).default;" % json.dumps(str(BUNDLE)),
                "const md=MarkdownIt({html:true,linkify:false,typographer:false,maxNesting:20}); let out=null;",
                body,
                "console.log(JSON.stringify(out));})().catch(e=>{console.error(e); process.exit(1);});",
            ]
        )
        return json.loads(run_node(js))

    def test_a_relative_reference_resolves_in_the_tree_or_says_why_not(self):
        """Folders, '.', '..', a leading '/' (the tree's root), '?' dropped, '#' kept, percent escapes decoded once; above
        the root is out; a dot-named part, a backslash, a control character or a broken escape is bad; anything with a
        scheme, '//host', '#…' alone or nothing is no relative reference."""
        got = self.node(
            "out=Object.fromEntries(%s.map(h=>{const r=mdRelPath(h,%s); return [h,r===null?null:r.out?'out':r.bad?'bad':[r.path,r.frag]];}));"
            % (json.dumps(list(REL), ensure_ascii=False), json.dumps(BASE))
        )
        self.assertEqual(got, REL)

    def test_a_document_outside_the_tree_resolves_nothing_inside_it(self):
        """With no tree path for the document (it lies outside --manuscript), every relative reference is out."""
        got = self.node("out=['img/a.png','../README.md','/x.png'].map(h=>mdRelPath(h,null));")
        self.assertEqual(got, [{"out": True}] * 3)

    def test_an_image_loads_only_from_the_tree_with_an_image_suffix(self):
        """A tree path with one of the served suffixes loads; remote, data:, out of the tree, another type or another
        scheme says why it does not."""
        got = self.node(
            "out=Object.fromEntries(%s.map(h=>{const r=mdImgPath(h,%s); return [h,r.path||r.why];}));"
            % (json.dumps(list(IMG)), json.dumps(BASE))
        )
        self.assertEqual(got, IMG)

    def test_the_viewers_image_suffixes_are_the_servers(self):
        """The suffixes mdImgPath loads are the ones GET /api/asset serves - the served constant, read from the file."""
        src = (Path(limn.__file__).resolve().parent / "viewer" / "js" / "md-surface.js").read_text(encoding="utf-8")
        line = next(ln for ln in src.splitlines() if ln.startswith("const MD_IMG_EXT="))
        exts = json.loads(line.split("Object.freeze(", 1)[1].split(")", 1)[0].replace("'", '"'))
        self.assertEqual({"." + e for e in exts}, set(ASSET_TYPES))

    def test_a_link_opens_a_registered_document_an_image_or_nothing(self):
        """A relative link to a registered document's path is that document (with its heading); to an image of the tree,
        that image in a new tab; to another file of the tree or out of it, nothing - and every absolute link is mdHref's
        verdict as before (the viewer's own origin and loopback stay inert)."""
        got = self.node(
            "out=Object.fromEntries(%s.map(h=>{const r=mdTarget(h,%s,%s,%s);"
            " return [h,r.open==='doc'?[r.open,r.key,r.id]:r.open?[r.open]:[null,r.why]];}));"
            % (json.dumps(list(TARGET), ensure_ascii=False), json.dumps(ORIGIN), json.dumps(BASE), json.dumps(DOCS))
        )
        self.assertEqual(got, TARGET)

    def test_hrefs_as_markdown_it_encodes_them_resolve_to_the_written_path(self):
        """markdown-it percent-encodes a destination's Hangul and the space a <...> destination may hold: the image and the
        link still name the file as written, the heading as written."""
        src = "![그림](<img/막대 그림.png>) [가기](<../notes/계획 노트.md#다음 일>)"
        got = self.node(
            "const kids=md.parse(%s,{}).flatMap(t=>t.children||[]);"
            "const img=kids.find(c=>c.type==='image').attrGet('src'),a=kids.find(c=>c.type==='link_open').attrGet('href');"
            "out=[img,mdImgPath(img,%s),a,mdRelPath(a,%s)];"
            % (json.dumps(src, ensure_ascii=False), json.dumps(BASE), json.dumps(BASE))
        )
        self.assertIn("%", got[0])
        self.assertEqual(got[1], {"path": "docs/img/막대 그림.png"})
        self.assertIn("%", got[2])
        self.assertEqual(got[3], {"path": "notes/계획 노트.md", "frag": "다음 일"})

    def test_the_image_address_is_built_from_the_checked_path_and_is_one_the_server_takes(self):
        """mdAssetUrl is always this origin's /api/asset with the document and the path percent-encoded whole, and every path
        mdImgPath loads is one the server's asset_path takes as it is."""
        got = self.node(
            "out=%s.map(h=>{const r=mdImgPath(h,%s); return r.path?[r.path,mdAssetUrl('gd',r.path)]:null;}).filter(Boolean);"
            % (json.dumps(list(IMG)), json.dumps(BASE))
        )
        self.assertTrue(got)
        for path, url in got:
            with self.subTest(path=path):
                self.assertTrue(url.startswith("/api/asset?doc=gd&path="), url)
                self.assertNotIn("/", url.split("&path=", 1)[1])
                self.assertIsInstance(asset_path(path), AssetPath)

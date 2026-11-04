"""PoC (throwaway, not for merge): the HTML surface's rendered text -> source line mapping and its link allowlist.

docs/superpowers/specs/2026-10-24-html-document-surface.md §결정 4·5·6. The served mdInlineLines and mdHref run under node
on the token stream of the vendored markdown-it (src/limn/vendor/markdown-it/), so the parser is the one the viewer loads.

Run: uv run pytest -q src/limn/viewer/tests/test_md_surface_poc.py
"""

import json
import os
import shutil
import unittest
from pathlib import Path

import limn

from helpers import extract_js_fn, run_node

BUNDLE = Path(limn.__file__).resolve().parent / "vendor" / "markdown-it" / "markdown-it.esm.min.mjs"
ORIGIN = "https://limn.example.ts.net:18020"

# Each case: its source and, for the inline tokens in document order, what the mapping must say. A tuple (lo, hi) is a token
# whose lines cannot be told: the whole token takes lo..hi. A dict {text: line} is an exact token: each named text piece is on
# that source line (the oracle every exact piece also meets: its text is in the source line it is given).
CASES = {
    "plain lines": ("one\ntwo\nthree", [{"one": 1, "two": 2, "three": 3}]),
    "emphasis over a line end": ("a *b\nc* d\ne", [{"a ": 1, "b": 1, "c": 2, " d": 2, "e": 3}]),
    "link text over a line end": ("[x\ny](https://a.org) z\nw", [{"x": 1, "y": 2, " z": 2, "w": 3}]),
    "strong over three lines": ("**p\nq\nr** s", [{"p": 1, "q": 2, "r": 3, " s": 3}]),
    "hard breaks": ("a  \nb\\\nc", [{"a": 1, "b": 2, "c": 3}]),
    "code span over a line end": ("a `b\nc` d\ne", [(1, 3)]),
    "inline HTML over a line end": ('a <span\nclass="x"> b\nc', [(1, 3)]),
    "link destination and title over a line end": ('[a](https://x.org\n"t") b\nc', [(1, 3)]),
    "image alt over a line end": ("![a\nb](x.png) c\nd", [(1, 3)]),
    "reference label over a line end": ("[a][b\nc] d\ne\n\n[b c]: https://x.org", [(1, 3)]),
    "a later block keeps its lines after an unclear one": (
        "a `b\nc`\n\nnext line\nlast",
        [(1, 2), {"next line": 4, "last": 5}],
    ),
    "blocks below the first line": (
        "# T\n\npara one\npara *two\nthree*\n\n- item a\n  item b\n\n> q1\nq2",
        [{"T": 1}, {"para one": 3, "para ": 4, "two": 4, "three": 5}, {"item a": 7, "item b": 8}, {"q1": 10, "q2": 11}],
    ),
    "setext heading": ("Title\nmore\n===\n\nafter", [{"Title": 1, "more": 2}, {"after": 5}]),
}

# href -> what mdHref opens with the viewer at ORIGIN: 'web', 'mail', 'anchor' or None (inert).
HREFS = {
    "https://example.org/a": "web",
    "HTTPS://Example.org": "web",
    "http://example.org:8080/x?y=1": "web",
    "mailto:a@example.org": "mail",
    "#제목": "anchor",
    "ftp://example.org/f": None,
    "myapp://open": None,
    "javascript:alert(1)": None,
    "data:image/png;base64,AAAA": None,
    "/api/pins": None,
    "docs/x.md": None,
    "//evil.example/x": None,
    ORIGIN + "/api/meta": None,
    "http://localhost:18920/api/pins": None,
    "http://127.0.0.1:18920/": None,
    "http://2130706433/": None,
    "http://[::1]:18920/": None,
    "http://[::ffff:127.0.0.1]/": None,
    "http://0/": None,
    "https://user:pw@example.org/": None,
}


class MarkdownSurfacePoc(unittest.TestCase):
    """mdInlineLines and mdHref, as served, on the vendored markdown-it's tokens."""

    def setUp(self):
        """Skip without node, unless LIMN_TEST_REQUIRE_NODE=1 makes that a failure."""
        if not shutil.which("node"):
            if os.environ.get("LIMN_TEST_REQUIRE_NODE") == "1":
                self.fail("node required (LIMN_TEST_REQUIRE_NODE=1) but not installed")
            self.skipTest("node not available")

    def node(self, body: str):
        """body run with the served functions, `md` (the vendored markdown-it as the viewer configures it) and `out`, whose
        JSON is the answer."""
        js = "\n".join(
            [
                extract_js_fn("mdInlineLines"),
                extract_js_fn("mdLoopback"),
                extract_js_fn("mdHref"),
                "const {pathToFileURL}=require('node:url');",
                "(async()=>{const MarkdownIt=(await import(pathToFileURL(%s).href)).default;" % json.dumps(str(BUNDLE)),
                "const md=MarkdownIt({html:true,linkify:false,typographer:false}); let out=null;",
                body,
                "console.log(JSON.stringify(out));})().catch(e=>{console.error(e); process.exit(1);});",
            ]
        )
        return json.loads(run_node(js))

    def test_each_rendered_piece_is_given_the_source_line_it_comes_from(self):
        """Exact tokens put every text piece on the line it is written on, a break inside emphasis or a link included; a token
        with a line end the parser swallowed (code span, inline HTML, link destination or title, image alt, reference label)
        is not exact and takes its whole range, so no piece after the swallowed line end is labelled a line early."""
        got = self.node(
            "const cases=%s; out={};"
            "for(const [name,src] of Object.entries(cases)){out[name]=md.parse(src,{}).filter(t=>t.type==='inline').map(t=>{"
            "const m=mdInlineLines(t); return {exact:m.exact,lo:m.lo,hi:m.hi,"
            "pieces:(t.children||[]).map((c,i)=>c.type==='text'||c.type==='code_inline'?[c.content,m.lines[i]]:null).filter(Boolean)};});}"
            % json.dumps({name: src for name, (src, _) in CASES.items()}, ensure_ascii=False)
        )
        for name, (src, want) in CASES.items():
            lines = src.split("\n")
            with self.subTest(name):
                tokens = got[name]
                self.assertEqual(len(tokens), len(want), tokens)
                for token, expect in zip(tokens, want, strict=True):
                    if isinstance(expect, tuple):
                        self.assertFalse(token["exact"], token)
                        self.assertEqual((token["lo"], token["hi"]), expect)
                        continue
                    self.assertTrue(token["exact"], token)
                    placed = dict(token["pieces"])
                    for text, line in expect.items():
                        self.assertEqual(placed.get(text), line, (text, token))
                    for text, line in token["pieces"]:
                        self.assertIn(text.strip(), lines[line - 1], (text, line))

    def test_a_table_cell_takes_its_row(self):
        """markdown-it maps no table cell's inline token, only each row (tr_open): a cell's text is not exact and carries no
        range of its own, so a pick in it falls to its row's one line (mdRangeAt's nearest block)."""
        got = self.node(
            "const toks=md.parse('| h | i |\\n| - | - |\\n| a | b |\\n| c | d |',{});"
            "out={rows:toks.filter(t=>t.type==='tr_open').map(t=>[t.map[0]+1,t.map[1]]),"
            "cells:toks.filter(t=>t.type==='inline').map(t=>{const m=mdInlineLines(t); return [m.exact,m.lo];})};"
        )
        self.assertEqual(got["rows"], [[1, 1], [3, 3], [4, 4]])
        self.assertEqual(got["cells"], [[False, 0]] * 6)

    def test_links_open_only_through_the_allowlist(self):
        """mdHref opens another origin's http(s) URL (as parsed), mailto and an in-document heading; every other href -
        another scheme, a relative or scheme-relative path, the viewer's own origin, a loopback host, a URL with
        credentials - is inert."""
        got = self.node(
            "out=Object.fromEntries(%s.map(h=>[h,mdHref(h,%s).open]));" % (json.dumps(list(HREFS)), json.dumps(ORIGIN))
        )
        self.assertEqual(got, HREFS)

    def test_a_link_is_followed_as_it_was_checked(self):
        """A raw 'https:/api/meta' resolves against the page to the viewer's own origin; mdHref parses it alone, checks that and
        hands back exactly that URL, which is what the link element is given."""
        got = self.node("out=mdHref('https:/api/meta',%s);" % json.dumps(ORIGIN))
        self.assertEqual(got, {"open": "web", "href": "https://api/meta"})

    def test_markdown_it_lets_other_schemes_through_so_the_renderer_must_gate_every_link_token(self):
        """markdown-it's validateLink is a denylist: an ordinary link, an autolink and a reference link to ftp:, a custom
        scheme or a data: image all become link tokens. mdHref keeps every one of them inert."""
        src = (
            "[a](ftp://example.org/f) <ftp://example.org/g> [c][r] [d](myapp://open) [e](data:image/png;base64,AAAA)"
            " [f](javascript:alert(1))\n\n[r]: myapp://ref"
        )
        got = self.node(
            "out=md.parse(%s,{}).flatMap(t=>t.children||[]).filter(c=>c.type==='link_open')"
            ".map(c=>[c.attrGet('href'),c.markup,mdHref(c.attrGet('href'),%s).open]);"
            % (json.dumps(src), json.dumps(ORIGIN))
        )
        self.assertEqual(
            got,
            [
                ["ftp://example.org/f", "", None],
                ["ftp://example.org/g", "autolink", None],
                ["myapp://ref", "", None],
                ["myapp://open", "", None],
                ["data:image/png;base64,AAAA", "", None],
            ],
        )


if __name__ == "__main__":
    unittest.main()

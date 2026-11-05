"""The Markdown surface's pure rules: rendered text -> source line mapping and the link allowlist (docs/adr/0025 D6, D7;
docs/superpowers/specs/2026-10-24-html-document-surface.md §결정 5·6).

The served mdInlineLines and mdHref run under node on the token stream of the vendored markdown-it
(src/limn/vendor/markdown-it/), configured as the parse worker configures it (src/limn/viewer/md-parse.mjs), so the parser
is the one the viewer loads. The browser behaviour - the DOM these rules label, picks, marks, limits - is in
test_viewer_markdown.py.

Run: uv run pytest -q src/limn/viewer/tests/test_md_surface.py
"""

import json
import os
import shutil
import unittest
from pathlib import Path

import limn

import helpers_js
from helpers import extract_js_fn, run_node

BUNDLE = Path(limn.__file__).resolve().parent / "vendor" / "markdown-it" / "markdown-it.esm.min.mjs"
WORKER = Path(limn.__file__).resolve().parent / "viewer" / "md-parse.mjs"
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
    # The same hosts spelt another way: a trailing dot (kept by the URL parser, dropped by DNS and by Limn's Host check),
    # case, percent escapes, full-width letters, other IPv4 forms, IPv6 written out or mapped, 0.0.0.0 and :: - and the
    # viewer's own origin with a trailing dot, in capitals or with its default port written out.
    "http://localhost.:18920/api/source?doc=fixture": None,
    "http://LOCALHOST..:18920/": None,
    "http://localhost%2e:18920/": None,
    "http://localhost\u3002:18920/": None,
    "http://\uff4c\uff4f\uff43\uff41\uff4c\uff48\uff4f\uff53\uff54/": None,
    "http://a.localhost./": None,
    "http://127.0.0.1.:18920/": None,
    "http://127.1/": None,
    "http://0x7f.1/": None,
    "http://017700000001/": None,
    "http://127.255.255.254/": None,
    "http://0.0.0.0./": None,
    "http://[0:0:0:0:0:0:0:1]:18920/": None,
    "http://[::]/": None,
    "http://[::ffff:0.0.0.0]/": None,
    "http://[::127.0.0.1]/": None,
    "https://limn.example.ts.net.:18020/api/meta": None,
    "HTTPS://LIMN.EXAMPLE.TS.NET.:18020/": None,
    "https://limn.example.ts.net..:18020/": None,
    # Not the viewer: another port or scheme of its host, another tailnet name, an address that is not loopback.
    "https://limn.example.ts.net/": "web",
    "http://limn.example.ts.net:18020/": "web",
    "https://other.example.ts.net.:18020/": "web",
    "http://128.0.0.1/": "web",
    "http://[::2:7f00:1]/": "web",
    "http://localhost.example.org/": "web",
}


class MarkdownSurfaceRules(unittest.TestCase):
    """mdInlineLines and mdHref, as served, on the vendored markdown-it's tokens."""

    def setUp(self):
        """Skip without node, unless LIMN_TEST_REQUIRE_NODE=1 makes that a failure."""
        if not shutil.which("node"):
            if os.environ.get("LIMN_TEST_REQUIRE_NODE") == "1":
                self.fail("node required (LIMN_TEST_REQUIRE_NODE=1) but not installed")
            self.skipTest("node not available")

    def node(self, body: str):
        """body run with the served functions, `md` (the vendored markdown-it as the viewer configures it), `mdLinkify`
        (the same with linkify on, which the viewer leaves off) and `out`, whose JSON is the answer."""
        js = "\n".join(
            [
                extract_js_fn("mdInlineLines"),
                extract_js_fn("mdHostKey"),
                extract_js_fn("mdSameOrigin"),
                extract_js_fn("mdIpv6"),
                extract_js_fn("mdLoopback"),
                extract_js_fn("mdHref"),
                "const {pathToFileURL}=require('node:url');",
                "(async()=>{const MarkdownIt=(await import(pathToFileURL(%s).href)).default;" % json.dumps(str(BUNDLE)),
                "const md=MarkdownIt({html:true,linkify:false,typographer:false,maxNesting:20}); let out=null;",
                "const mdLinkify=MarkdownIt({html:true,linkify:true,typographer:false});",
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

    def test_a_trailing_dot_or_other_spelling_of_limn_stays_inert_in_every_kind_of_link(self):
        """The hosts mdHref refuses, spelt as Limn's Host check still admits them (a trailing dot, capitals, the viewer's
        host with a dot), reach the gate through every link token markdown-it makes - an inline link, a reference link
        and an autolink - and each stays inert, while another origin in the same tokens opens. The viewer leaves linkify
        off, so a bare URL is no link; with it on, linkify-it ends a bare URL's host at a trailing dot (the rest is text)
        and the link it makes is gated the same way: loopback stays inert, the viewer's host without its port is another
        origin."""
        cases = {
            "http://localhost.:18920/api/source?doc=fixture": (None, ("http://localhost", None)),
            "http://LOCALHOST.:18920/api/meta": (None, ("http://LOCALHOST", None)),
            "http://127.0.0.1.:18920/": (None, ("http://127.0.0.1", None)),
            "http://[::1]:18920/": (None, ("http://[::1]:18920/", None)),
            "https://limn.example.ts.net.:18020/api/meta": (None, ("https://limn.example.ts.net", "web")),
            "https://example.org/a": ("web", ("https://example.org/a", "web")),
        }
        paras = ["[i](%s) [r][r%d] <%s> bare %s\n\n[r%d]: %s" % (h, n, h, h, n, h) for n, h in enumerate(cases)]
        got = self.node(
            "const paras=%s,origin=%s; const links=(m,src)=>m.parse(src,{}).flatMap(t=>t.children||[])"
            ".filter(c=>c.type==='link_open').map(c=>[c.markup,c.attrGet('href'),mdHref(c.attrGet('href'),origin).open]);"
            "out=paras.map(src=>({viewer:links(md,src),linkify:links(mdLinkify,src)}));"
            % (json.dumps(paras), json.dumps(ORIGIN))
        )
        for (h, (want, (bare, bare_open))), links in zip(cases.items(), got, strict=True):
            with self.subTest(h):
                written = [["", h, want], ["", h, want], ["autolink", h, want]]
                self.assertEqual(
                    [[m, href.lower(), o] for m, href, o in links["viewer"]],
                    [[m, href.lower(), o] for m, href, o in written],
                )
                self.assertEqual(
                    [[m, href.lower(), o] for m, href, o in links["linkify"]],
                    [[m, href.lower(), o] for m, href, o in written + [["linkify", bare, bare_open]]],
                )

    def test_the_viewer_origin_is_read_in_the_same_spelling(self):
        """A viewer opened at its host with a trailing dot (or in capitals) still refuses its own origin without the dot,
        and one whose origin does not parse ('null') opens no web link at all."""
        got = self.node(
            "out=[mdHref('https://limn.example.ts.net:18020/api/meta','https://limn.example.ts.net.:18020').open,"
            "mdHref('https://limn.example.ts.net:18020/api/meta','https://LIMN.example.ts.net:18020').open,"
            "mdHref('https://limn.example.ts.net:443/','https://limn.example.ts.net').open,"
            "mdHref('https://example.org/','null').open];"
        )
        self.assertEqual(got, [None, None, None, None])


# YAML front matter (md-parse.mjs mdFrontMatter, ADR-0032 제안): source -> the front_matter token's map [first, end) and
# closing marker, or None when the document has none and the other rules read its first lines as before; then the first
# token after it, which keeps its own source lines.
FRONT = {
    "a closed block": ("---\ntitle: A\nauthors: [a, b]\n---\n\n# H", ([0, 4], "---"), ("heading_open", [5, 6])),
    "closed by dots": ("---\ntitle: A\n...\ntext", ([0, 3], "..."), ("paragraph_open", [3, 4])),
    "a comment first, blanks inside": ("---\n# note\n\nkey: v\n---\nbody", ([0, 5], "---"), ("paragraph_open", [5, 6])),
    "a byte order mark and trailing blanks": (
        "\ufeff--- \nk: v\n---\t\nx",
        ([0, 3], "---"),
        ("paragraph_open", [3, 4]),
    ),
    "a key whose value has colons": ('---\nurl: "https://a.org/x"\n---', ([0, 3], "---"), None),
    "a blank line after the opening (Pandoc: a rule)": ("---\n\nk: v\n---", None, ("hr", [0, 1])),
    "never closed": ("---\ntitle: A\n\npara", None, ("hr", [0, 1])),
    "not on the first line": ("\n---\nk: v\n---", None, ("hr", [1, 2])),
    "a paragraph, not a mapping (a setext heading as before)": ("---\nJust words\n---", None, ("hr", [0, 1])),
    "a URL is no key": ("---\nhttps://a.org\n---", None, ("hr", [0, 1])),
    "four dashes": ("----\nk: v\n----", None, ("hr", [0, 1])),
    "indented opening": ("  ---\nk: v\n---", None, ("hr", [0, 1])),
}


class FrontMatterRule(unittest.TestCase):
    """mdFrontMatter as served in the parse worker, installed by its mdParser on the vendored markdown-it."""

    def setUp(self):
        if not shutil.which("node"):
            if os.environ.get("LIMN_TEST_REQUIRE_NODE") == "1":
                self.fail("node required (LIMN_TEST_REQUIRE_NODE=1) but not installed")
            self.skipTest("node not available")

    def node(self, body: str):
        page = "<script>" + WORKER.read_text(encoding="utf-8") + "</script>"
        js = "\n".join(
            [
                helpers_js.function_source(page, "mdParser"),
                helpers_js.function_source(page, "mdFrontMatter"),
                "const {pathToFileURL}=require('node:url'); let markdownit=null;",
                "(async()=>{markdownit=(await import(pathToFileURL(%s).href)).default;" % json.dumps(str(BUNDLE)),
                "const md=mdParser(20); let out=null;",
                body,
                "console.log(JSON.stringify(out));})().catch(e=>{console.error(e); process.exit(1);});",
            ]
        )
        return json.loads(run_node(js))

    def test_front_matter_is_one_block_only_where_pandoc_would_read_one(self):
        """A '---' first line, a mapping's first line and a '---' or '...' line make one front_matter token over exactly those
        lines; a blank line after the opening, no closing line, a later start, a first line that is no key or comment, four
        dashes or an indented opening leave the document to the other rules, which read it as before."""
        got = self.node(
            "out={}; for(const [name,src] of Object.entries(%s)){const ts=md.parse(src,{}); const f=ts.find(t=>t.type==='front_matter');"
            "const next=ts.filter(t=>t.type!=='front_matter'&&t.map&&t.nesting!==-1)[0];"
            "out[name]={front:f?[f.map,f.info]:null,next:next?[next.type,next.map]:null,"
            "lines:f?f.content.split('\\n').length:0};}"
            % json.dumps({name: src for name, (src, _, _) in FRONT.items()}, ensure_ascii=False)
        )
        for name, (_src, front, nxt) in FRONT.items():
            with self.subTest(name):
                self.assertEqual(got[name]["front"], list(front) if front else None)
                self.assertEqual(got[name]["next"], list(nxt) if nxt else None)
                if front:
                    self.assertEqual(got[name]["lines"], front[0][1] - 2)

    def test_the_blocks_after_it_keep_the_lines_they_have_without_it(self):
        """Every token after the front matter has the map it has when the front matter lines are blank lines instead: the rule
        only takes its own lines."""
        src = "---\ntitle: A\ntags: [x]\n---\n# H\n\npara *one\ntwo*\n\n- a\n- b\n"
        blank = "\n\n\n\n" + src.split("---\n", 2)[2]
        got = self.node(
            "const m=s=>md.parse(s,{}).filter(t=>t.type!=='front_matter'&&t.map).map(t=>[t.type,t.map]);"
            "out=[m(%s),m(%s)];" % (json.dumps(src), json.dumps(blank))
        )
        self.assertEqual(got[0], got[1])
        self.assertTrue(got[0])


if __name__ == "__main__":
    unittest.main()

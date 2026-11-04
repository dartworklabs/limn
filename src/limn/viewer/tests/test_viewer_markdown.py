"""The Markdown surface in the browser (docs/handbook/viewer.md §Markdown 화면, docs/adr/0025-html-document-surface.md).

A Markdown document (kind markdown) is drawn by the viewer from GET /api/source - parsed in the worker GET /md-parse.mjs
serves, built with DOM calls only - and pinned by its source lines. These tests drive the real viewer against the
in-process server (BrowserBase) and check what a person sees and what the server stores:

- the drawing: every block and line carries the server's line numbers, for every line separator the server splits on;
- the security fixtures: raw HTML, scripts, handlers, javascript: and data: links, remote images and every other link that
  is not another origin's http(s), mailto or an in-document heading are inert, and no request leaves the viewer;
- picks: a click or tap on a block, a drag over lines, a line that cannot be told inside a block, a table row, a heading;
  the ladder (lines, block, section), the save with no page, frac or pdf_build, the marks and badges, the outline;
- the limits (MD_LIMITS): each fixture of the spec's table gives a drawn document or the plain source-line view within the
  time limit, the elements under the limit, and every source line in the view or the notice saying why not;
- the IME rule on the surface's keys and on a redraw; the page-only controls hidden; the changes view's source diff.

The pure rules (mdInlineLines, mdHref) are in test_md_surface.py; the enforced page policy over this surface in
test_viewer_csp.py.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_markdown.py
"""

import json
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from limn.administration import serve_documents as startup_documents

import helpers_csp
from helpers import ps, req
from helpers_browser import BrowserBase, ime_compose, ime_end_with, settle
from helpers_figure import BUILD1, viewer_build

# Resolves when the Markdown document on screen is drawn (a document, the line view or a notice) and no parse is in flight.
DRAWN = "typeof MD!=='undefined'&&MD.shown===DOC&&!!document.querySelector('#md')&&!MD.job"

# A document with every block kind, inline constructs whose lines can and cannot be told, a table, and the security cases:
# raw HTML blocks and tags, script and handlers, javascript:/data:/ftp:/custom-scheme links, relative and scheme-relative
# paths, the viewer's own origin and loopback in several spellings through inline, reference and autolink tokens, a remote
# image. Lines are referred to by number below.
FIXTURE = """# 시험 문서

문단 첫 줄이다.
문단 둘째 줄에 **굵은 글**과 `코드`가 있다.
문단 셋째 줄.

## 목록

- 첫째 항목
- 둘째 항목
  - 하위 항목

1. 번호 하나
2. 번호 둘

## 표

| 종류 | 값 |
| --- | ---: |
| 가 | 1 |
| 나 | 2 |

## 코드와 인용

```python
def pick(lo, hi):
    return lo, hi
```

> 인용 첫 줄
> 인용 둘째 줄

## 여러 줄 인라인

강조가 *줄을 넘어
이어진다* 그래도 줄은 맞는다.

코드 표시가 `줄을
넘으면` 줄을 셀 수 없다.
그래서 이 문단은 통째로 고른다.

## 보안

<div onclick="window.__mdRan=1"><script>window.__mdRan=2</script><img src="https://tracker.example/x.png" onerror="window.__mdRan=3"></div>

인라인 <b onmouseover="window.__mdRan=4">태그</b>와 <script>window.__mdRan=5</script> 글.
[자바](javascript:window.__mdRan=6) [데이터](data:text/html,<script>parent.__mdRan=7</script>) [그림 데이터](data:image/png;base64,AAAA)
[에프](ftp://example.org/f) <ftp://example.org/g> [앱](myapp://open) [상대](docs/x.md) [뿌리](/api/pins) [스킴](//evil.example/x)
[자기](http://viewer.test/api/meta) [자기점](http://viewer.test./api/meta) [대문자](HTTP://VIEWER.TEST/api/pins) [루프](http://localhost.:18999/api/pins)
[참조][r1] [참조점][r2] <http://127.0.0.1.:18999/api/meta> <http://viewer.test./api/meta> [자격](https://u:p@example.org/)
[밖](https://example.org/a) [메일](mailto:alice@example.com) [제목으로](#코드와-인용)
![원격 그림](https://tracker.example/pixel.png)

[r1]: http://LOCALHOST..:18999/api/meta
[r2]: http://viewer.test./api/source?doc=nt

---

마지막 문단.
"""
# The links the fixture lets open, each as the browser gets it: another origin's http(s), mailto - and no other.
OPEN_LINKS = ["https://example.org/a", "mailto:alice@example.com"]


RULE = FIXTURE.split("\n").index("---") + 1  # the thematic break's line


def fixture_line(text: str) -> int:
    """The 1-based line of FIXTURE that holds text."""
    return next(i for i, ln in enumerate(FIXTURE.split("\n"), 1) if text in ln)


def server_lines(path: Path) -> list[str]:
    """The file's lines as the server numbers them (limn.platform.files.tex_lines: the UTF-8 text, str.splitlines())."""
    return path.read_bytes().decode("utf-8").splitlines()


def records(state: Path) -> list[dict]:
    """The live pin records in the state folder's pins.jsonl."""
    f = state / "pins.jsonl"
    return [json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()] if f.exists() else []


class MarkdownBase(BrowserBase):
    """BrowserBase with a Markdown document nt (notes.md, MD_TEXT) first and the LaTeX manuscript ms second (its two-page build
    on screen), so the viewer opens on the Markdown document."""

    MD_TEXT = FIXTURE

    def setUp(self):
        super().setUp()
        self.src = self.main.parent
        self.md = self.src / "notes.md"
        self.write(self.MD_TEXT)
        docs = startup_documents.make_docs(["nt=노트:notes.md", "ms=본문:main.tex"], self.src, ps.APP.C.paths)
        assert isinstance(docs, list), docs
        ps.APP.set_docs(docs)
        self.nt, self.ms = docs
        viewer_build(self.ms, BUILD1)

    def write(self, text):
        """notes.md as text (str) or bytes."""
        if isinstance(text, bytes):
            self.md.write_bytes(text)
        else:
            self.md.write_text(text, encoding="utf-8")

    def open_md(self, n_open=0, **kw):
        """The viewer on the Markdown document, once it is drawn."""
        page = self.open(n_open, **kw)
        page.wait_for_function(DRAWN, timeout=20000)
        settle(page)
        return page

    def line_el(self, page, n):
        """A locator for source line n's element on screen (its line span, else the smallest block that starts there)."""
        return page.locator("#md [data-line='%d']" % n).first

    def pick_line(self, page, n):
        """Click source line n and wait for the composer to show it."""
        self.line_el(page, n).click()
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo>0", timeout=5000)
        return page.evaluate(
            "({lo:COMPOSE.current.lo,hi:COMPOSE.current.hi,scope:COMPOSE.current.scope,"
            "levels:COMPOSE.current.levels.map(l=>[l.level,l.lo,l.hi,l.env||null])})"
        )

    def save_via_api(self, lo, hi, **extra):
        """A line pin on notes.md through POST /api/pin, as an agent makes one (no pick)."""
        body = json.dumps({"doc": "nt", "file": str(self.md), "lo": lo, "hi": hi, "note": "n", **extra}).encode()
        code, _, out = self.talk(req("POST", "/api/pin", body, {"Content-Type": "application/json"}))
        self.assertEqual(code, 200, out)
        return json.loads(out)["id"]

    def save(self, page, note="고쳐 주세요"):
        """Type note into the composer and save; wait for the new pin in the list."""
        n = page.evaluate("PINS.length")
        page.fill("#note", note)
        page.click("#btn-save")
        page.wait_for_function("PINS.length>%d" % n, timeout=8000)
        settle(page)


class Drawing(MarkdownBase):
    """The document is drawn from its source with the server's line numbers."""

    def test_every_block_and_line_carries_the_servers_lines(self):
        """Headings, paragraphs, items, the table's rows, the code block's lines, the quote, the raw HTML placeholder and the
        rule each carry their source range, and every line span's text is on the server's line it names."""
        page = self.open_md()
        lines = server_lines(self.md)
        # Each text node under a line span, and the line it names: the drawn text without its markup (**, `) is still a
        # run of the source line, piece by piece (an image's stand-in words are the viewer's, not the source's).
        got = page.evaluate(
            "[...document.querySelectorAll('#md [data-line]')].flatMap(e=>{const w=document.createTreeWalker(e,NodeFilter.SHOW_TEXT),out=[];"
            "for(let t=w.nextNode();t;t=w.nextNode())if(!t.parentElement.closest('.md-img'))out.push([+e.dataset.line,t.data]); return out;})"
        )
        self.assertGreater(len(got), 20)
        for n, text in got:
            for piece in text.split("\n"):
                self.assertIn(piece.strip(), lines[n - 1], (n, piece))
        kinds = page.evaluate(
            "Object.fromEntries([...document.querySelectorAll('#md [data-kind]')].map(e=>[e.dataset.kind+':'+e.dataset.lo,+e.dataset.hi]))"
        )
        for kind, lo, hi in (
            ("heading", 1, 1),
            ("paragraph", 3, 5),
            ("item", fixture_line("첫째 항목"), fixture_line("첫째 항목")),
            ("table", fixture_line("| 종류"), fixture_line("| 나 |")),
            ("row", fixture_line("| 가 |"), fixture_line("| 가 |")),
            ("code", fixture_line("```python"), fixture_line("    return") + 1),
            ("quote", fixture_line("인용 첫"), fixture_line("인용 둘째")),
            ("html", fixture_line("<div onclick"), fixture_line("<div onclick")),
            ("rule", RULE, RULE),
        ):
            with self.subTest(kind=kind):
                self.assertEqual(kinds.get("%s:%d" % (kind, lo)), hi)
        self.assertEqual(
            page.evaluate("[...document.querySelectorAll('#md pre [data-line]')].map(e=>+e.dataset.line)"),
            [fixture_line("def pick"), fixture_line("    return")],
        )

    def test_a_line_that_cannot_be_told_takes_its_whole_paragraph(self):
        """A code span over a line end swallows it: that paragraph is one range (data-lo..hi, kind lines), never lines one
        early; the emphasis over a line end before it keeps its lines."""
        page = self.open_md()
        lo = fixture_line("코드 표시가")
        self.assertEqual(
            page.evaluate(
                "(()=>{const e=document.querySelector('#md [data-kind=lines]'); return e&&[+e.dataset.lo,+e.dataset.hi];})()"
            ),
            [lo, lo + 2],
        )
        em = fixture_line("강조가 *줄을")
        self.assertIn(
            "이어진다", page.evaluate("document.querySelector(\"#md [data-line='%d']\").textContent" % (em + 1))
        )

    def test_line_numbers_match_the_server_for_every_separator(self):
        """CRLF, a lone CR, form feed, vertical tab, U+2028, U+2029, the three record separators and NEL are line ends for
        str.splitlines(): the server numbers lines so, and the viewer's data-line names the same line for every text."""
        seps = ["\r\n", "\r", "\f", "\v", " ", " ", "\x1c", "\x1d", "\x1e", "\x85"]
        body = "# 머리\n\n" + "".join("줄%d 글%s" % (i, s) for i, s in enumerate(seps)) + "끝 줄\n"
        self.write(body)
        page = self.open_md()
        lines = server_lines(self.md)
        self.assertEqual(page.evaluate("MD.lines.length"), len(lines))
        got = page.evaluate(
            "[...document.querySelectorAll('#md [data-line],#md [data-lo]')].map(e=>[+(e.dataset.line||e.dataset.lo),+(e.dataset.line||e.dataset.hi),e.textContent])"
        )
        for i in range(len(seps)):
            text = "줄%d 글" % i
            hits = [(lo, hi) for lo, hi, t in got if text in t and lo == hi]
            n = next(k for k, ln in enumerate(lines, 1) if text in ln)
            self.assertIn((n, n), hits, text)

    def test_the_outline_and_strip_follow_the_headings(self):
        """The outline lists the headings with their lines (L<line>); picking one scrolls it to the top and the strip and the
        outline's current entry name it."""
        page = self.open_md()
        entries = page.evaluate("OUTLINE_ENTRIES.map(e=>[e.title,e.pageLabel,e.depth])")
        self.assertEqual(entries[0], ["시험 문서", "L1", 0])
        self.assertIn(["표", "L%d" % fixture_line("## 표"), 1], entries)
        i = [e[0] for e in entries].index("코드와 인용")
        page.click("#outline-items button[data-index='%d']" % i)
        page.wait_for_function("document.querySelector('#section-current').textContent==='코드와 인용'", timeout=5000)
        self.assertEqual(page.evaluate("OUTLINE_SELECTED"), i)

    def test_the_page_only_controls_are_hidden_and_the_search_is_the_browsers(self):
        """No page count, page jump, zoom buttons, [선택], Limn search or PDF download on screen; Ctrl+F is left to the
        browser (not taken by the page)."""
        page = self.open_md()
        for sel in ("#nav-page", "#section-page", "#doc-search", "#jump", "#btn-zoom-in", "#btn-select"):
            with self.subTest(sel=sel):
                self.assertFalse(page.locator(sel).is_visible())
        taken = page.evaluate(
            "(()=>{const e=new KeyboardEvent('keydown',{key:'f',code:'KeyF',ctrlKey:true,metaKey:true,bubbles:true,cancelable:true});"
            "document.body.dispatchEvent(e); return e.defaultPrevented;})()"
        )
        self.assertFalse(taken)
        self.assertEqual(page.evaluate("document.querySelectorAll('#doc .pg,#doc .pv').length"), 0)

    def test_switching_to_the_latex_document_and_back_draws_each(self):
        """The LaTeX manuscript's pages replace the column and the column comes back, at the line it was read at."""
        page = self.open_md()
        page.evaluate("document.querySelector('#md [data-kind=table]').scrollIntoView({block:'start'})")
        page.wait_for_function("MD.at>=%d" % fixture_line("## 표"), timeout=5000)
        page.evaluate("switchDoc('ms')")
        page.wait_for_function(
            "DOC==='ms'&&document.querySelectorAll('#doc .pg').length===2&&!document.querySelector('#md')",
            timeout=10000,
        )
        self.assertFalse(page.evaluate("document.body.classList.contains('md-surface')"))
        page.evaluate("switchDoc('nt')")
        page.wait_for_function(DRAWN, timeout=10000)
        self.assertGreaterEqual(page.evaluate("mdReadingLine()"), fixture_line("## 표") - 2)


class Security(MarkdownBase):
    """The security fixture is drawn inert: nothing runs, nothing is fetched, only the allowed links open."""

    def route(self, route):
        """Record every request the page makes to another host before aborting it."""
        u = urlparse(route.request.url)
        if u.netloc != "viewer.test":
            self.away.append(route.request.url)
            return route.abort()
        return super().route(route)

    def setUp(self):
        self.away = []
        super().setUp()

    def test_raw_html_scripts_and_handlers_are_inert(self):
        """The raw HTML block is a placeholder with its line, inline tags are code text; no script, img, iframe, object or
        embed element and no on* attribute is in the document; nothing it holds has run; no dialog opened."""
        dialogs = []
        page = self.open_md()
        page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
        page.locator("#md b, #md .md-html, #md .md-html-in").first.hover()
        got = page.evaluate(
            "({bad:document.querySelectorAll('#md script,#md img,#md iframe,#md object,#md embed,#md style,#md link').length,"
            "on:[...document.querySelectorAll('#md *')].filter(e=>[...e.attributes].some(a=>/^on/i.test(a.name))).length,"
            "ran:window.__mdRan||0,html:[...document.querySelectorAll('#md .md-html')].map(e=>e.textContent),"
            "inl:[...document.querySelectorAll('#md .md-html-in')].map(e=>e.textContent)})"
        )
        self.assertEqual((got["bad"], got["on"], got["ran"]), (0, 0, 0))
        self.assertEqual(len(got["html"]), 1)
        self.assertIn("HTML 1줄 · 그리지 않습니다", got["html"][0])
        self.assertIn('<b onmouseover="window.__mdRan=4">', got["inl"])
        self.assertEqual(dialogs, [])

    def test_only_another_origins_web_link_and_mailto_open(self):
        """Every link element of the document is one of OPEN_LINKS, opening a new tab without referrer or opener; the in-
        document heading link is a button-like anchor; every other link token - javascript:, data:, ftp:, a custom scheme,
        relative and scheme-relative paths, the viewer's own origin in any spelling, loopback with a trailing dot, through
        inline, reference and autolink tokens, a URL with credentials - is inert text naming its target."""
        page = self.open_md()
        got = page.evaluate(
            "[...document.querySelectorAll('#md a[href]')].map(a=>[a.getAttribute('href'),a.target,a.rel])"
        )
        self.assertEqual([g[0] for g in got], OPEN_LINKS)
        self.assertTrue(all(t == "_blank" and r == "noopener noreferrer" for _, t, r in got))
        inert = page.evaluate("[...document.querySelectorAll('#md .md-rel')].map(e=>e.dataset.tip)")
        # markdown-it's own denylist leaves javascript: and data:text/html as plain text (no link token at all).
        text = page.evaluate("document.querySelector('#md').textContent")
        self.assertIn("[자바](javascript:window.__mdRan=6)", text)
        for target in (
            "data:image/png",
            "ftp://example.org/f",
            "ftp://example.org/g",
            "myapp://open",
            "docs/x.md",
            "/api/pins",
            "//evil.example/x",
            "http://viewer.test/api/meta",
            "http://viewer.test./api/meta",
            "HTTP://VIEWER.TEST/api/pins",
            "http://localhost.:18999/api/pins",
            "http://LOCALHOST..:18999/api/meta",
            "http://viewer.test./api/source",
            "http://127.0.0.1.:18999/api/meta",
            "https://u:p@example.org/",
        ):
            with self.subTest(target=target):
                self.assertTrue(any(target.lower() in t.lower() for t in inert), (target, inert))
        self.assertEqual(page.evaluate("document.querySelectorAll('#md .md-anchor[data-act=md-anchor]').length"), 1)

    def test_nothing_is_fetched_from_another_host(self):
        """The remote images (an img in the raw HTML, a Markdown image) are never fetched: the image is its alt text with its
        address in the tip, and the page asked no host but its own."""
        page = self.open_md()
        settle(page)
        self.assertEqual(self.away, [])
        self.assertEqual(
            page.evaluate("[...document.querySelectorAll('#md .md-img')].map(e=>[e.textContent,e.dataset.tip])"),
            [["그림: 원격 그림", "그림은 불러오지 않습니다 · https://tracker.example/pixel.png"]],
        )

    def test_an_in_document_link_goes_to_its_heading_and_its_enter_asks_the_input_method_first(self):
        """[제목으로](#코드와-인용) scrolls that heading to the top on Enter - but not on the Enter that ended a Hangul
        composition: here the field it composed in leaves the document as the composition ends and the focus lands on the
        link (the case imeTail keeps: the key goes on where the focus went, docs/handbook/viewer.md §조합을 끝내는 키), as
        ibus-hangul hands that Enter on (ime_end_with). The global key path asks imeKey before it activates the link."""
        page = self.open_md()
        page.evaluate(
            "(()=>{const a=document.querySelector('#md .md-anchor'),i=document.createElement('input'); i.id='md-probe'; a.after(i);"
            "i.addEventListener('compositionend',()=>{a.focus(); i.remove();},{once:true}); i.focus();})()"
        )
        cdp = page.context.new_cdp_session(page)
        ime_compose(cdp, "ㄱ", "가")
        ime_end_with(cdp, "Enter", "가")
        settle(page)
        self.assertTrue(page.evaluate("document.activeElement.classList.contains('md-anchor')"))
        self.assertNotEqual(page.evaluate("document.querySelector('#section-current').textContent"), "코드와 인용")
        page.keyboard.press("Enter")
        page.wait_for_function("document.querySelector('#section-current').textContent==='코드와 인용'", timeout=5000)


class Picking(MarkdownBase):
    """Picks, the ladder and the saved pin."""

    def test_a_click_picks_the_block_with_the_three_rungs_and_saves_no_page(self):
        """A click on a paragraph's line: the composer offers the line, the paragraph (default) and the heading's section; the
        saved pin is that block's lines, kind md:paragraph, scope block, and carries no page, frac or pdf_build; pins.md writes
        '—' in its page column; the line gets a mark and a gutter badge, and the card's head names no page."""
        page = self.open_md()
        got = self.pick_line(page, 4)
        self.assertEqual((got["lo"], got["hi"], got["scope"]), (3, 5, "block"))
        self.assertEqual([lv[0] for lv in got["levels"]], ["raw", "block", "section"])
        self.assertEqual(got["levels"][0][1:3], [4, 4])
        self.assertEqual(got["levels"][1][3], "paragraph")
        self.assertEqual(
            page.evaluate("[...document.querySelectorAll('#md .md-sel')].map(e=>+(e.dataset.line||e.dataset.lo))"),
            [3, 4, 5],
        )
        # Each rung says what it takes, after its lines (no 'undefined'); the chosen lines have a primary outline over their
        # tint, apart from a pin's; the location line names no page and no 'Markdown'.
        tips = page.evaluate(
            "[...document.querySelectorAll('#c-levels button')].map(b=>[b.dataset.tip,b.getAttribute('aria-description')||b.dataset.tip])"
        )
        self.assertEqual(len(tips), 3)
        for tip, desc in tips:
            with self.subTest(tip=tip):
                self.assertRegex(tip, r"^L\d+(-L\d+)? · \S")
                self.assertNotIn("undefined", tip + desc)
        self.assertIn("블록", tips[1][0])
        self.assertIn("제목", tips[2][0])
        self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('#md .md-sel')).outlineStyle"), "solid")
        self.assertTrue(page.evaluate("document.getElementById('c-page').hidden"))
        self.save(page)
        rec = records(ps.APP.C.state)[-1]
        self.assertEqual(
            (rec["lo"], rec["hi"], rec["kind"], rec["scope"], rec["doc"]), (3, 5, "md:paragraph", "block", "nt")
        )
        for field in ("page", "frac", "pdf_build"):
            self.assertNotIn(field, rec)
        md = self.talk(req("GET", "/pins.md"))[2].decode()
        row = next(ln for ln in md.splitlines() if ln.startswith("| ") and "L3-L5" in ln)
        self.assertIn("| — |", row)
        self.assertIn("md:paragraph", row)
        self.assertEqual(
            page.evaluate("[...document.querySelectorAll('#md .md-badge')].map(b=>b.textContent)"), [str(rec["id"])]
        )
        self.assertEqual(page.evaluate("document.querySelectorAll('#md .md-pin').length"), 3)
        head = page.evaluate("document.querySelector('.pin .go-all .lbl').textContent")
        self.assertEqual(head, "#%d · L3-L5" % rec["id"])

    def test_a_drag_picks_the_lines_it_covers(self):
        """A mouse drag from line 3 into line 4 picks lines 3-4 at the chosen-lines rung; a triple click that ends at the
        start of the next block does not take that block's line."""
        page = self.open_md()
        # A source line's span may begin on the visual row where the line before it ends (its soft break is a space): the
        # drag runs from line 3's first box to the middle of line 4's last one.
        x0, y0, x1, y1 = page.evaluate(
            "(()=>{const r=n=>[...document.querySelector(`#md [data-line='${n}']`).getClientRects()],a=r(3)[0],b=r(4).at(-1);"
            "return [a.left+2,a.top+a.height/2,b.left+b.width/2,b.top+b.height/2];})()"
        )
        page.mouse.move(x0, y0)
        page.mouse.down()
        page.mouse.move(x1, y1, steps=6)
        page.mouse.up()
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.scope==='raw'", timeout=5000)
        self.assertEqual(page.evaluate("[COMPOSE.current.lo,COMPOSE.current.hi]"), [3, 4])
        page.evaluate("discardSelection()")
        page.locator("#md [data-line='%d']" % fixture_line("인용 첫")).click(click_count=3)
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.scope==='raw'", timeout=5000)
        lo, hi = page.evaluate("[COMPOSE.current.lo,COMPOSE.current.hi]")
        self.assertLessEqual(hi, fixture_line("인용 둘째"))

    def test_a_table_cell_picks_its_row_and_the_block_is_the_table(self):
        """A click in a cell: the chosen lines are its row's one line; the block rung is the whole table (md:table)."""
        page = self.open_md()
        page.locator("#md td", has_text="나").click()
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo>0", timeout=5000)
        levels = page.evaluate("COMPOSE.current.levels.map(l=>[l.level,l.lo,l.hi,l.env])")
        row = fixture_line("| 나 |")
        self.assertEqual(levels[0][:3], ["raw", row, row])
        self.assertEqual(levels[1], ["block", fixture_line("| 종류"), row, "table"])

    def test_a_heading_tap_picks_its_section(self):
        """A click on a heading chooses its section: from the heading to the line before the next heading of its level."""
        page = self.open_md()
        page.locator("#md h2", has_text="목록").click()
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo>0", timeout=5000)
        lo = fixture_line("## 목록")
        self.assertEqual(
            page.evaluate("[COMPOSE.current.scope,COMPOSE.current.lo,COMPOSE.current.hi]"),
            ["section", lo, fixture_line("2. 번호 둘")],
        )

    def test_a_pick_inside_a_run_whose_lines_cannot_be_told_takes_the_run(self):
        """A click in the paragraph with a code span over a line end takes all three of its lines, at every rung."""
        page = self.open_md()
        lo = fixture_line("코드 표시가")
        page.locator("#md [data-kind=lines]").click()
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo>0", timeout=5000)
        self.assertEqual(
            page.evaluate("COMPOSE.current.levels[0].lo+'-'+COMPOSE.current.levels[0].hi"), "%d-%d" % (lo, lo + 2)
        )

    def test_a_badge_opens_the_card_and_view_comes_back_to_the_line(self):
        """The gutter badge of a pin opens its card; the card's [보기] scrolls the pin's first line to the reading depth and
        flashes its lines."""
        self.save_via_api(fixture_line("인용 첫"), fixture_line("인용 둘째"))
        page = self.open_md(1)
        page.locator("#md .md-badge").click()
        page.wait_for_selector(".pin.cur", timeout=5000)
        # [보기] and the card's number speak of the document, not a PDF
        for sel in (".pin.cur button[data-act=view]", ".pin.cur .n.go"):
            with self.subTest(sel=sel):
                self.assertNotIn("PDF", page.locator(sel).first.get_attribute("data-tip"))
        page.evaluate("document.getElementById('left').scrollTop=0")
        page.locator(".pin.cur button[data-act=view]").first.click()
        page.wait_for_function("document.querySelectorAll('#md .md-flash').length>0", timeout=5000)

    def test_a_drag_over_two_blocks_offers_them_whole_and_saves_lines(self):
        """A drag from the paragraph's second line into the first list item: the ladder is the chosen lines, the two blocks
        whole ('블록 2개', the paragraph's first line to the item's) and the section; that rung saves as lines (scope lines -
        the server has no scope for several blocks)."""
        page = self.open_md()
        item = fixture_line("첫째 항목")
        x0, y0, x1, y1 = page.evaluate(
            "(()=>{const a=document.querySelector(\"#md [data-line='4']\").getClientRects()[0],"
            "b=[...document.querySelector(\"#md li[data-lo='%d']\").getClientRects()].at(-1);"
            "return [a.left+4,a.top+a.height/2,b.right-4,b.top+b.height/2];})()" % item
        )
        page.mouse.move(x0, y0)
        page.mouse.down()
        page.mouse.move(x1, y1, steps=8)
        page.mouse.up()
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.levels.length===3", timeout=5000)
        levels = page.evaluate("COMPOSE.current.levels.map(l=>[l.level,l.lo,l.hi,l.label])")
        self.assertEqual([lv[0] for lv in levels], ["raw", "blocks", "section"])
        self.assertEqual(levels[0][1:3], [4, item])
        self.assertEqual(levels[1], ["blocks", 3, item, "블록 2개"])
        page.click("#c-levels [data-act=level][data-level=blocks]")
        page.wait_for_function("COMPOSE.current.scope==='blocks'", timeout=5000)
        self.save(page)
        rec = records(ps.APP.C.state)[-1]
        self.assertEqual((rec["lo"], rec["hi"], rec["scope"], rec["kind"]), (3, item, "lines", "lines"))

    def test_stacked_badges_each_take_the_press_on_them(self):
        """Two pins on one first line stack their badges 2px apart: each badge's own top, middle and bottom go to it -
        toward the other one its press reaches only half the gap - and a lone badge answers at least --mark-hit tall."""
        self.save_via_api(3, 5)
        self.save_via_api(3, 3)
        for device in ({}, {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}):
            with self.subTest(touch=bool(device)):
                page = self.open_md(2, **device)
                self.assertEqual(page.evaluate("document.querySelectorAll('#md .md-badges').length"), 1)
                got = page.evaluate(
                    "[...document.querySelectorAll('#md .md-badge')].map(b=>{const r=b.getBoundingClientRect(),x=r.left+r.width/2,"
                    "at=y=>{const e=document.elementFromPoint(x,y); return e&&e.closest('.md-badge')===b;};"
                    "return [at(r.top+0.5),at(r.top+r.height/2),at(r.bottom-0.5)];})"
                )
                self.assertEqual(got, [[True, True, True], [True, True, True]])

    def test_the_lost_save_answer_is_found_by_its_lines(self):
        """A save whose answer never arrives finds the pin on the server by this person, document, file and lines - it has
        no page - and reports it saved, not failed (no second pin)."""
        page = self.open_md()
        self.pick_line(page, 4)
        page.fill("#note", "답을 잃은 저장")
        # The server stores the pin (answer() hands the request to it), and the answer is lost on the way back.
        page.route(
            "**/api/pin", lambda r: (self.answer(r.request), r.abort()) if r.request.method == "POST" else self.route(r)
        )
        page.click("#btn-save")
        page.wait_for_function("PINS.length===1&&!COMPOSE.current", timeout=8000)
        self.assertEqual(len(records(ps.APP.C.state)), 1)

    def test_the_list_orders_pinned_lines_by_line(self):
        """[위치순] orders a Markdown document's pins by their lines (they have no page)."""
        for lo, hi in ((fixture_line("마지막 문단"),) * 2, (3, 5), (fixture_line("| 가 |"),) * 2):
            self.save_via_api(lo, hi)
        page = self.open_md(3)
        got = page.evaluate("orderPins(PINS,LIST_ORDER.PAGE).map(p=>p.lo)")
        self.assertEqual(got, sorted(got))
        self.assertEqual(len(got), 3)


class EditingAndSuggestions(MarkdownBase):
    """The edit card, a re-place and a suggested edit on a Markdown pin."""

    def test_the_edit_card_ladder_is_the_documents_and_a_replace_picks_new_lines(self):
        """An edit card on a pin of lines 3-5 offers the document's rungs (the paragraph, its section); [위치 다시 잡기] takes
        the next line clicked as the candidate, and applying it moves the pin to that block, still with no page."""
        pid = self.save_via_api(3, 5, scope="block", kind="md:paragraph")
        page = self.open_md(1)
        page.evaluate("openEdit(%d)" % pid)
        page.wait_for_function("EDITOR.current&&EDITOR.current.levels.length>1", timeout=5000)
        self.assertEqual(
            page.evaluate("EDITOR.current.levels.map(l=>[l.level,l.lo,l.hi])"),
            [["raw", 3, 5], ["section", 1, RULE + 2]],
        )
        page.evaluate("startRepick()")
        page.wait_for_function("!!REPICK", timeout=5000)
        self.assertIn("문서에서 고르세요", page.evaluate("document.getElementById('banner').textContent"))
        self.line_el(page, fixture_line("인용 첫")).click()
        page.wait_for_function("REPICK&&REPICK.cand", timeout=5000)
        page.click("[data-act=rp-apply]")
        page.wait_for_function("PINS.find(p=>p.id===%d).lo===%d" % (pid, fixture_line("인용 첫")), timeout=8000)
        rec = next(r for r in records(ps.APP.C.state) if r["id"] == pid)
        self.assertEqual(
            (rec["lo"], rec["hi"], rec["kind"]), (fixture_line("인용 첫"), fixture_line("인용 둘째"), "md:quote")
        )
        self.assertNotIn("page", rec)

    def test_a_suggested_edit_shows_and_saves_the_markdown_source(self):
        """[제안 수정] on lines of the document fills its editor with the lines' Markdown source (not the drawn text), and the
        saved pin carries the suggestion against that base."""
        page = self.open_md()
        self.line_el(page, 4).click()
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo===3", timeout=5000)
        page.click("#c-levels [data-act=level][data-level=raw]")
        page.wait_for_function("COMPOSE.current.scope==='raw'&&COMPOSE.current.lo===4", timeout=5000)
        page.click("#c-sg-tg")
        page.wait_for_function("SG.on&&SG.base", timeout=5000)
        self.assertEqual(page.evaluate("SG.base"), "문단 둘째 줄에 **굵은 글**과 `코드`가 있다.")
        page.fill("#c-sg-text", "문단 둘째 줄에 **굵은 글**과 `코드`가 함께 있다.")
        self.save(page, "제안")
        rec = records(ps.APP.C.state)[-1]
        self.assertEqual(rec["suggest"]["base"], "문단 둘째 줄에 **굵은 글**과 `코드`가 있다.")
        self.assertNotIn("page", rec)


class Redrawing(MarkdownBase):
    """The source changing on disk, and the IME rule on a redraw."""

    def test_an_edited_source_is_drawn_again_at_the_reading_line(self):
        """A change to notes.md reaches the screen within a light poll: the new text is drawn, the reading spot kept."""
        page = self.open_md()
        page.evaluate("document.querySelector('#md pre').scrollIntoView({block:'start'})")
        before = page.evaluate("mdReadingLine()")
        self.write(FIXTURE.replace("문단 셋째 줄.", "문단 셋째 줄을 고쳤다."))
        page.evaluate("pollLightOnce()")
        page.wait_for_function(
            "document.querySelector('#md').textContent.includes('문단 셋째 줄을 고쳤다.')", timeout=8000
        )
        self.assertLessEqual(abs(page.evaluate("mdReadingLine()") - before), 1)

    def test_a_read_that_failed_is_asked_again_on_the_next_poll(self):
        """An edit whose source read fails once (the request aborted) leaves the notice; once reads answer again, the next
        light polls read and draw the new text - a read that failed does not count as the source read at that time."""
        page = self.open_md()
        self.write(FIXTURE.replace("문단 셋째 줄.", "문단 셋째 줄을 고쳤다."))
        failed = []

        def source(route):
            if urlparse(route.request.url).path == "/api/source" and not failed:
                failed.append(route.request.url)
                return route.abort()
            return self.route(route)

        page.route("**/*", source)
        page.evaluate("pollLightOnce()")
        page.wait_for_function("!!document.querySelector('#md.md-note')", timeout=8000)
        self.assertEqual(page.evaluate("document.querySelector('#md').textContent"), "원문을 읽지 못했습니다")
        self.assertEqual(len(failed), 1)
        for _ in range(2):
            page.evaluate("pollLightOnce()")
        page.wait_for_function(
            "document.querySelector('#md').textContent.includes('문단 셋째 줄을 고쳤다.')", timeout=8000
        )

    def test_a_read_that_failed_on_a_return_to_the_document_is_asked_again(self):
        """Back on the Markdown document after the LaTeX one, its unchanged source's read fails once: the notice is shown,
        and the next light polls read and draw it again - the earlier visit's read does not stand for the failed one."""
        page = self.open_md()
        page.evaluate("switchDoc('ms')")
        page.wait_for_function("DOC==='ms'&&!document.querySelector('#md')", timeout=10000)
        failed = []

        def source(route):
            if urlparse(route.request.url).path == "/api/source" and not failed:
                failed.append(route.request.url)
                return route.abort()
            return self.route(route)

        page.route("**/*", source)
        page.evaluate("switchDoc('nt')")
        page.wait_for_function("!!document.querySelector('#md.md-note')", timeout=10000)
        self.assertEqual(page.evaluate("document.querySelector('#md').textContent"), "원문을 읽지 못했습니다")
        self.assertEqual(len(failed), 1)
        for _ in range(3):
            page.evaluate("pollLightOnce()")
        page.wait_for_function(DRAWN, timeout=8000)

    def test_a_redraw_waits_while_a_field_in_the_document_is_composing(self):
        """A redraw would replace every node of #doc: while a field in it composes (here a field put there, as any field
        the surface may hold), the old document stays; when the composition ends the redraw runs."""
        page = self.open_md()
        page.evaluate(
            "(()=>{const i=document.createElement('input'); i.id='md-probe'; document.querySelector('#md').appendChild(i);})()"
        )
        page.focus("#md-probe")
        cdp = page.context.new_cdp_session(page)
        cdp.send("Input.imeSetComposition", {"text": "가", "selectionStart": 1, "selectionEnd": 1})
        page.evaluate("mdBuild()")
        settle(page)
        self.assertTrue(page.evaluate("MD.waiting&&!!document.getElementById('md-probe')"))
        cdp.send("Input.insertText", {"text": "가"})
        page.wait_for_function("!MD.waiting&&!document.getElementById('md-probe')&&" + DRAWN, timeout=8000)

    def test_a_note_composing_in_the_composer_keeps_its_text_across_a_redraw(self):
        """The composer is outside the document: a redraw while its note composes leaves the note's text, focus and
        composition alone."""
        page = self.open_md()
        self.pick_line(page, 4)
        page.focus("#note")
        cdp = page.context.new_cdp_session(page)
        cdp.send("Input.imeSetComposition", {"text": "고", "selectionStart": 1, "selectionEnd": 1})
        page.evaluate("mdBuild()")
        page.wait_for_function("!MD.waiting&&" + DRAWN, timeout=8000)
        cdp.send("Input.insertText", {"text": "고"})
        self.assertEqual(
            page.evaluate("[document.activeElement.id,document.getElementById('note').value]"), ["note", "고"]
        )


# The spec's limit fixtures (§결정 5): name -> (source, what the screen must be: 'drawn', 'lines' (the line view), a
# notice's limit, or None for either drawn or the line view - a fixture whose parse time is near the limit on a slow machine).
REFERENCE = re.compile(r"^ {0,3}\[[^\]]+\]:\s")  # a link reference definition's line


def nested_list(depth: int) -> str:
    return "".join("  " * i + "- 항목 %d\n" % i for i in range(depth)) + "\n뒤 문단\n"


LIMIT_CASES = {
    "long line": ("a" * 400_000 + "\n", "drawn"),
    "emphasis openers": ("*a" * 100_000 + "\n", None),
    "underscore runs": ("_a_ " * 60_000 + "\n", None),
    "brackets": ("[" * 300_000 + "\n", None),
    "backticks": ("`a" * 100_000 + "\n", None),
    "html openers": ("<a" * 100_000 + "\n", None),
    "entities": ("&amp;" * 60_000 + "\n", None),
    "nested list under the limit": (nested_list(8), "drawn"),
    "nested list over the limit": (nested_list(12), "nesting"),
    "nested quote under the limit": (">" * 17 + " q\n\n뒤\n", "drawn"),
    "nested quote over the limit": (">" * 25 + " q\n\n뒤\n", "nesting"),
    "narrow table": ("| a |\n| - |\n" + "| x |\n" * 6_100, "blocks"),
    "wide table": ("|" + " c |" * 500 + "\n|" + " - |" * 500 + "\n" + ("|" + " x |" * 500 + "\n") * 20, "blocks"),
    "reference definitions": (
        "".join("[r%d]: https://example.org/%d\n" % (i, i) for i in range(20_000)) + "\n끝\n",
        "drawn",
    ),
    "too many inline tokens": ("*a* " * 45_000 + "\n", "inlines"),
    "too many elements": ("![a](b)" * 61_000 + "\n", "elements"),
}


class Limits(MarkdownBase):
    """Each limit fixture gives a drawn document or the plain source-line view, in time, under the element limit, with every
    source line on screen or the notice saying why not."""

    MD_TEXT = "# 처음\n"

    def check(self, page, want, n_lines):
        """The screen after a draw: the elements under the limit, and every source line in a data-line or data-lo..hi, or
        the line view's head line naming its limit."""
        got = page.evaluate(
            "({limit:MD.limit,els:document.querySelectorAll('#md *').length,"
            "lines:[...document.querySelectorAll('#md [data-line]')].map(e=>+e.dataset.line),"
            "ranges:[...document.querySelectorAll('#md [data-lo]')].map(e=>[+e.dataset.lo,+e.dataset.hi]),"
            "head:(document.querySelector('#md .md-limit')||{}).textContent||''})"
        )
        self.assertLessEqual(got["els"], 60_000 + 10)
        covered = set(got["lines"])
        for lo, hi in got["ranges"]:
            covered |= set(range(lo, hi + 1))
        lines = server_lines(self.md)
        # A link reference definition is no block: markdown-it keeps it for the links and draws nothing, as GitHub does.
        missing = [n for n, ln in enumerate(lines, 1) if ln.strip() and not REFERENCE.match(ln) and n not in covered]
        self.assertEqual(missing, [])
        if want == "drawn":
            self.assertIsNone(got["limit"])
        elif want is None:
            self.assertIn(got["limit"], (None, "time", "blocks", "inlines", "elements", "nesting"))
        else:
            self.assertEqual(got["limit"], want)
            self.assertIn("원문 줄로 보입니다", got["head"])
        return got

    def test_every_limit_fixture_is_drawn_or_shown_as_lines_in_time(self):
        page = self.open_md()
        for name, (text, want) in LIMIT_CASES.items():
            with self.subTest(name=name):
                self.write(text)
                t0 = time.monotonic()
                page.evaluate("mdBuild()")
                page.wait_for_function(DRAWN, timeout=20000)
                took = time.monotonic() - t0
                self.check(page, want, len(server_lines(self.md)))
                self.assertLess(took, 15, name)

    def test_one_long_inline_run_or_code_block_yields_inside_and_a_newer_draw_stops_it(self):
        """'*x* ' 30,000 times is one inline token of 119,999 children (30,002 elements) and a fenced block of 30,000
        lines one token: the build yields inside each, never more than two chunks' elements apart, and a draw started at a
        yield inside one stops the older draw - only the newer one is shown."""
        page = self.open_md()
        page.evaluate(
            "(()=>{const y=mdYield,s=mdShow; window.mdYield=()=>{const w=window.__md; w.y.push(MD.els);"
            "if(w.race&&w.y.length===w.race){w.race=0; mdBuild();} return y();};"
            "window.mdShow=n=>{window.__md.shown.push(n.dataset.limit||'drawn'); return s(n);};})()"
        )
        chunk = page.evaluate("MD_LIMITS.chunk")
        cases = {"inline": "*x* " * 30_000 + "\n", "code": "```\n" + "x\n" * 30_000 + "```\n"}
        for name, text in cases.items():
            with self.subTest(name=name):
                self.write(text)
                page.evaluate("window.__md={y:[],shown:[],race:0}; mdBuild()")
                page.wait_for_function("window.__md.shown.length>0&&" + DRAWN, timeout=20000)
                y = page.evaluate("window.__md.y")
                self.assertEqual(page.evaluate("window.__md.shown"), ["drawn"])
                self.assertGreater(len(y), 10)
                gaps = [b - a for a, b in zip([0, *y[:-1]], y, strict=True)]
                self.assertLessEqual(max(gaps), 2 * chunk, gaps[:5])
                page.evaluate("window.__md={y:[],shown:[],race:5}; mdBuild()")
                page.wait_for_function("window.__md.shown.length>0&&" + DRAWN, timeout=20000)
                settle(page)
                self.assertEqual(page.evaluate("[window.__md.race,window.__md.shown]"), [0, ["drawn"]])

    def test_a_parse_past_the_time_limit_is_stopped_and_the_lines_are_shown(self):
        """A parse that never answers (the module made to hang) is stopped at MD_LIMITS.ms: the line view says so, and the
        next draw starts a fresh worker."""
        hang = b"export default function(){return {parse(){for(;;){}}}};"
        self.write("# 제목\n\n본문 한 줄\n")
        page = self.open(0)

        def module(route):
            if "/vendor/markdown-it/" in route.request.url and self.hang:
                return route.fulfill(status=200, headers={"content-type": "text/javascript"}, body=hang)
            return self.route(route)

        self.hang = True
        page.route("**/vendor/markdown-it/**", module)
        page.evaluate("mdParseStop(null); MD.worker&&MD.worker.terminate(); MD.worker=null; mdBuild()")
        page.wait_for_function("MD.limit==='time'&&" + DRAWN, timeout=15000)
        self.assertIn("2초", page.evaluate("document.querySelector('#md .md-limit').textContent"))
        self.assertEqual(
            page.evaluate("[...document.querySelectorAll('#md [data-line]')].map(e=>e.textContent)"),
            ["# 제목\n", "\n", "본문 한 줄\n"],
        )
        self.hang = False

    def test_a_parser_that_does_not_load_shows_the_lines(self):
        """The module failing to load (404) leaves the line view with its own head line."""
        page = self.open(0)
        page.route("**/vendor/markdown-it/**", lambda r: r.fulfill(status=404, body=b"no"))
        page.evaluate("mdParseStop(null); MD.worker&&MD.worker.terminate(); MD.worker=null; mdBuild()")
        page.wait_for_function("MD.limit==='load'&&" + DRAWN, timeout=15000)
        self.assertIn("파서를 불러오지 못해", page.evaluate("document.querySelector('#md .md-limit').textContent"))

    def test_the_byte_limit_is_a_notice_with_the_size(self):
        """A source of 1 MiB is drawn (or shown as lines); 1 MiB + 1 byte is the server's 413, said in the document's place
        with its size and the limit; the pins list stays."""
        page = self.open_md()
        self.write(b"a" * (1024 * 1024 - 1) + b"\n")
        page.evaluate("mdBuild()")
        page.wait_for_function(DRAWN, timeout=20000)
        self.assertNotEqual(page.evaluate("MD.limit"), "bytes")
        self.write(b"a" * (1024 * 1024) + b"\n")
        page.evaluate("mdBuild()")
        page.wait_for_function("MD.limit==='bytes'&&" + DRAWN, timeout=20000)
        self.assertEqual(
            page.evaluate("document.querySelector('#md').textContent"), "이 문서는 1 MiB라 그리지 않습니다(한도 1 MiB)"
        )

    def test_more_lines_than_the_line_view_takes_is_a_notice_of_its_own(self):
        """A source of 60,001 short lines in one paragraph passes the element limit and has more lines than the line view
        draws: the notice names the count and the limit."""
        page = self.open_md()
        self.write("가\n" * 60_001)
        page.evaluate("mdBuild()")
        page.wait_for_function("MD.limit==='lines'&&" + DRAWN, timeout=20000)
        self.assertEqual(
            page.evaluate("document.querySelector('#md').textContent"),
            "이 문서는 원문이 60,001줄이라 그리지 않습니다(한도 50,000줄)",
        )


class KeptDraft(MarkdownBase):
    """A draft kept from the drawn document (a paragraph picked, a note typed), the page reloaded while the parser cannot
    load: the line view, the kept draft and a new pick."""

    def keep_draft(self, page):
        self.pick_line(page, 4)  # the paragraph, lines 3-5, with three rungs
        page.fill("#note", "남긴 메모")
        page.evaluate("syncDraft()")

    def reload_without_parser(self, page, hold_pins=False):
        """Reload with the parse worker's module failing; with hold_pins the boot's first pin list is held (returned)
        until the test answers it, so the line view is up before the boot brings the draft back."""
        held = []

        def route(r):
            path = urlparse(r.request.url).path
            if path == "/md-parse.mjs":
                return r.abort()
            if hold_pins and path == "/api/pins" and r.request.method == "GET" and not held:
                held.append(r)
                return None
            return self.route(r)

        page.route("**/*", route)
        page.reload()
        page.wait_for_selector("#md[data-limit=load]", timeout=20000)
        return held

    def test_a_kept_draft_on_the_line_view_keeps_its_lines_as_lines(self):
        """The kept paragraph comes back on the line view as its lines with the one rung the view has; a click on line 4
        there then picks line 4, and the save stores that line (not the kept paragraph)."""
        page = self.open_md()
        self.keep_draft(page)
        self.reload_without_parser(page)
        page.wait_for_function("DRAFT.ready&&!!COMPOSE.current", timeout=8000)
        settle(page)
        self.assertEqual(
            page.evaluate(
                "[COMPOSE.current.lo,COMPOSE.current.hi,COMPOSE.current.scope,COMPOSE.current.levels.map(l=>l.level)]"
            ),
            [3, 5, "raw", ["raw"]],
        )
        self.assertEqual(page.evaluate("document.getElementById('note').value"), "남긴 메모")
        self.line_el(page, 4).click()
        page.wait_for_function("COMPOSE.current.lo===4&&COMPOSE.current.hi===4", timeout=5000)
        self.save(page, "줄 하나")
        rec = records(ps.APP.C.state)[-1]
        self.assertEqual((rec["lo"], rec["hi"], rec["scope"]), (4, 4, "raw"))

    def test_a_pick_made_before_the_kept_draft_comes_back_wins(self):
        """A click on line 4 while the boot still waits for the pins: when they come, the kept paragraph does not replace
        that pick - only its note comes into it - and the save stores line 4."""
        page = self.open_md()
        self.keep_draft(page)
        held = self.reload_without_parser(page, hold_pins=True)
        self.assertEqual(len(held), 1)
        self.line_el(page, 4).click()
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo===4", timeout=5000)
        held[0].fulfill(**self.answer(held[0].request))
        page.wait_for_function("DRAFT.ready", timeout=8000)
        settle(page)
        self.assertEqual(
            page.evaluate(
                "[COMPOSE.current.lo,COMPOSE.current.hi,COMPOSE.current.scope,document.getElementById('note').value]"
            ),
            [4, 4, "raw", "남긴 메모"],
        )
        page.click("#btn-save")
        page.wait_for_function("PINS.length>0", timeout=8000)
        rec = records(ps.APP.C.state)[-1]
        self.assertEqual((rec["lo"], rec["hi"], rec["scope"], rec["note"]), (4, 4, "raw", "남긴 메모"))


class Zoom(MarkdownBase):
    """No pages to scale: two fingers and a trackpad gesture are the browser's on a Markdown document, the viewer's own zoom
    on a PDF document."""

    PROBE = (
        "(()=>{const L=document.getElementById('left'),r=L.getBoundingClientRect(),"
        "t=i=>new Touch({identifier:i,target:L,clientX:r.left+60+i*80,clientY:r.top+120}),"
        "ts=new TouchEvent('touchstart',{touches:[t(0),t(1)],targetTouches:[t(0),t(1)],changedTouches:[t(1)],cancelable:true,bubbles:true}),"
        "g=new Event('gesturestart',{cancelable:true,bubbles:true}),ch=new Event('gesturechange',{cancelable:true,bubbles:true});"
        "L.dispatchEvent(ts); L.dispatchEvent(new TouchEvent('touchend',{touches:[],targetTouches:[],changedTouches:[t(0),t(1)],cancelable:true,bubbles:true}));"
        "L.dispatchEvent(g); L.dispatchEvent(ch); L.dispatchEvent(new Event('gestureend',{cancelable:true,bubbles:true}));"
        "return [ts.defaultPrevented,g.defaultPrevented,ch.defaultPrevented,getComputedStyle(L).touchAction];})()"
    )

    def test_pinch_is_the_browsers_on_the_markdown_surface_only(self):
        page = self.open_md(viewport={"width": 820, "height": 1000}, has_touch=True)
        touch, gesture, change, action = page.evaluate(self.PROBE)
        self.assertEqual((touch, gesture, change), (False, False, False))
        self.assertTrue("pinch-zoom" in action or action == "manipulation", action)
        page.evaluate("switchDoc('ms')")
        page.wait_for_function("DOC==='ms'&&document.querySelectorAll('#doc .pg').length===2", timeout=10000)
        touch, gesture, change, action = page.evaluate(self.PROBE)
        self.assertEqual((touch, gesture, change), (True, True, True))
        self.assertNotIn("pinch-zoom", action)


# Three raw HTML blocks in a row (a README's head), a code block tall enough that the reading line stays above the heading,
# a heading and a paragraph, and one HTML block alone after them.
HTML_RUN = (
    '<p align="center">a</p>\n\n<p align="center">\n  <img src="x.png">\n</p>\n\n<div>c</div>\n\n'
    + "```\n"
    + "코드\n" * 60
    + "```\n\n"
    + "# 제목\n\n본문.\n\n<div>alone</div>\n"
)
HTML_ALONE = HTML_RUN.split("\n").index("<div>alone</div>") + 1


class HtmlRun(MarkdownBase):
    """Raw HTML blocks in a row are one closed placeholder that opens to its blocks; one alone stays its own."""

    MD_TEXT = HTML_RUN

    def test_a_run_is_one_closed_placeholder_that_opens_to_blocks_that_take_pins(self):
        self.save_via_api(3, 5)
        page = self.open_md(1)
        run = page.evaluate(
            "(()=>{const r=document.querySelector('#md .md-html-run'); return r&&[r.dataset.lo,r.dataset.hi,r.dataset.kind,"
            "r.querySelector('.md-html-sum').textContent,r.querySelector('.md-html-sum').getAttribute('aria-expanded'),"
            "r.querySelectorAll('.md-html[data-lo]').length,r.querySelector('.md-html-body').hidden];})()"
        )
        self.assertEqual(run, ["1", "7", "html", "HTML 블록 3개 · 7줄 · 그리지 않습니다", "false", 0, True])
        self.assertEqual(
            page.evaluate("document.querySelectorAll('#md > .md-html[data-lo=\"%d\"]').length" % HTML_ALONE), 1
        )
        self.assertEqual(page.evaluate("document.getElementById('section-current').textContent"), "문서 처음")
        # closed, the pin on lines 3-5 marks the run and its badge stands at it
        self.assertTrue(page.evaluate("document.querySelector('#md .md-html-run').classList.contains('md-pin')"))
        page.click("#md .md-html-sum")
        page.wait_for_function(
            "document.querySelector('#md .md-html-sum').getAttribute('aria-expanded')==='true'", timeout=5000
        )
        self.assertIsNone(page.evaluate("COMPOSE.current"))  # opening it picks nothing
        self.assertEqual(
            page.evaluate(
                "[...document.querySelectorAll('#md .md-html-run .md-html')].map(e=>[+e.dataset.lo,+e.dataset.hi])"
            ),
            [[1, 1], [3, 5], [7, 7]],
        )
        self.assertIsNone(page.evaluate("document.querySelector('#md .md-html-run').dataset.lo||null"))
        top = page.evaluate(
            "Math.round(document.querySelector('#md .md-html[data-lo=\"3\"]').getBoundingClientRect().top"
            "-document.querySelector('#md .md-badge').getBoundingClientRect().top)"
        )
        self.assertLessEqual(abs(top), 2)
        page.click("#md .md-html[data-lo='3']")  # its own lines: the block's rung is the chosen lines' (merged)
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo===3", timeout=5000)
        self.assertEqual(
            page.evaluate("[COMPOSE.current.lo,COMPOSE.current.hi,COMPOSE.current.levels[0].merged]"), [3, 5, ["block"]]
        )


class PageWords(MarkdownBase):
    """The viewer's own words and styles on a Markdown document: no PDF, no build time, the document's headings in its own
    style, the outline's empty line."""

    def test_the_head_line_and_the_outline_speak_of_the_document(self):
        page = self.open_md()
        got = page.evaluate(
            "[document.getElementById('meta-main').dataset.tip,document.getElementById('meta-pages').dataset.tip,"
            "document.getElementById('meta-built-w').hidden,document.getElementById('meta-txt').innerText.trim().endsWith('·')]"
        )
        self.assertEqual(got, ["이 탭의 원문 파일", "브라우저가 원문에서 그리는 문서 형식", True, False])
        # a heading of the document takes none of the viewer's own heading look (a bare h3 rule once did)
        style = page.evaluate(
            "(()=>{const h=document.createElement('h3'); h.textContent='Ab'; document.getElementById('md').appendChild(h);"
            "const s=getComputedStyle(h),c=getComputedStyle(document.getElementById('md')); const out=[s.textTransform,s.letterSpacing,s.color===c.color]; h.remove(); return out;})()"
        )
        self.assertEqual(style, ["none", "normal", True])
        self.write("본문만 있다.\n")
        page.evaluate("mdBuild()")
        page.wait_for_function(
            "!document.getElementById('md').textContent.includes('시험 문서')&&" + DRAWN, timeout=8000
        )
        self.assertEqual(
            page.evaluate("document.getElementById('outline-items').textContent"),
            "이 문서에는 이동할 수 있는 제목이 없습니다.",
        )
        page.evaluate("switchDoc('ms')")
        page.wait_for_function("DOC==='ms'&&document.querySelectorAll('#doc .pg').length===2", timeout=10000)
        self.assertEqual(
            page.evaluate(
                "[document.getElementById('meta-main').dataset.tip,document.getElementById('meta-built-w').hidden]"
            ),
            ["PDF를 만든 최상위 원고 파일", False],
        )

    def test_a_link_that_does_not_open_says_why_on_focus_with_its_url_apart(self):
        """A link that does not open is a disabled link to assistive technology, reachable by Tab: the keyboard's focus
        shows its description, the URL in a part of its own that may break anywhere."""
        page = self.open_md()
        rel = page.locator("#md .md-rel").first
        attrs = rel.evaluate(
            "e=>[e.tabIndex,e.getAttribute('role'),e.getAttribute('aria-disabled'),e.getAttribute('aria-description'),e.dataset.tip,e.dataset.tipUrl]"
        )
        self.assertEqual(attrs[:3], [0, "link", "true"])
        self.assertEqual(attrs[3], attrs[4])
        self.assertTrue(attrs[4].startswith("이 링크는 열지 않습니다 · ") and attrs[4].endswith(attrs[5]), attrs)
        page.keyboard.press("Shift")
        rel.focus()
        page.wait_for_function("!document.getElementById('tip').hidden", timeout=5000)
        tip = page.evaluate(
            "[document.getElementById('tip').textContent,(document.querySelector('#tip .tip-url')||{}).textContent,"
            "getComputedStyle(document.querySelector('#tip .tip-url')).wordBreak,getComputedStyle(document.getElementById('tip')).wordBreak]"
        )
        self.assertEqual(tip, [attrs[4], attrs[5], "break-all", "keep-all"])
        self.assertIsNone(page.evaluate("COMPOSE.current"))


class ChangesView(MarkdownBase):
    """A Markdown document's changes open on its source diff (no comparison PDF)."""

    def test_the_changes_view_opens_the_source_diff(self):
        run = lambda *a: subprocess.run(["git", "-C", str(self.src), *a], check=True, capture_output=True)  # noqa: E731
        run("init", "-q")
        run("config", "user.email", "alice@example.com")
        run("config", "user.name", "Alice")
        run("add", "-A")
        run("commit", "-qm", "first")
        self.write(FIXTURE.replace("문단 셋째 줄.", "문단 셋째 줄을 바꿨다."))
        run("commit", "-qam", "second")
        page = self.open_md()
        page.evaluate("setViewMode(VIEW_MODE.REVISIONS)")
        page.wait_for_function(
            "REV.format===DIFF_FORMAT.SOURCE&&!document.getElementById('revision-source').hidden&&REV.sourceCommit",
            timeout=15000,
        )
        self.assertTrue(page.evaluate("document.getElementById('revision-pdf-tab').hidden"))
        self.assertIn("문단 셋째 줄을 바꿨다.", page.evaluate("document.getElementById('revision-source').textContent"))


class Phone(MarkdownBase):
    """A phone (390x844, touch): a tap on a block opens the composer; the position button reads the line."""

    def test_a_tap_picks_a_block_and_the_position_button_reads_lines(self):
        page = self.open_md(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        self.assertRegex(
            page.evaluate("document.getElementById('btn-pos-p').textContent"), r"^L\d+/%d$" % len(server_lines(self.md))
        )
        self.line_el(page, 4).tap()
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.scope==='block'", timeout=5000)
        self.assertEqual(page.evaluate("[COMPOSE.current.lo,COMPOSE.current.hi]"), [3, 5])

    def test_the_chosen_lines_come_out_from_under_the_sheet(self):
        """A tap on a block near the screen's bottom opens the sheet over it: the column scrolls so the chosen lines stand
        above the sheet, as a PDF selection box does (revealBox)."""
        page = self.open_md(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        quote = fixture_line("인용 첫")
        page.evaluate(
            "(()=>{const L=document.getElementById('left'),e=document.querySelector(\"#md [data-line='%d']\");"
            "L.scrollTop+=e.getBoundingClientRect().bottom-L.getBoundingClientRect().bottom+12;})()" % quote
        )
        self.line_el(page, quote).tap()
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo===%d" % quote, timeout=5000)
        settle(page)
        got = page.evaluate(
            "[document.querySelector('#md .md-sel').getBoundingClientRect().bottom,"
            "document.getElementById('right').getBoundingClientRect().top]"
        )
        self.assertLessEqual(got[0], got[1])

    def test_a_tap_on_a_link_that_does_not_open_says_why_and_picks_nothing(self):
        page = self.open_md(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        rel = page.locator("#md .md-rel").first
        rel.scroll_into_view_if_needed()
        rel.tap(force=True)  # a disabled link to Playwright (aria-disabled), not to a finger
        page.wait_for_function("!document.getElementById('tip').hidden", timeout=5000)
        self.assertTrue(
            page.evaluate("document.getElementById('tip').textContent.startsWith('이 링크는 열지 않습니다')")
        )
        page.wait_for_timeout(400)
        self.assertIsNone(page.evaluate("COMPOSE.current"))

    def test_a_badge_answers_a_press_44px_wide_on_the_screen_and_off_the_text(self):
        """The phone's gutter is one press wide: a badge answers from 22px left to 22px right of its middle, all of it on
        the screen and left of where the text begins."""
        self.save_via_api(3, 5)
        page = self.open_md(1, viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        got = page.evaluate(
            "(()=>{const b=document.querySelector('#md .md-badge'),r=b.getBoundingClientRect(),x=r.left+r.width/2,y=r.top+r.height/2,"
            "at=x=>{const e=document.elementFromPoint(x,y); return !!e&&e.closest('.md-badge')===b;},"
            "md=document.getElementById('md'),text=md.getBoundingClientRect().left+parseFloat(getComputedStyle(md).paddingLeft);"
            "return [at(x-21.5),at(x+21.5),x-22>=0,x+22<=text];})()"
        )
        self.assertEqual(got, [True, True, True, True])

    def test_the_column_fits_the_phones_width(self):
        """The code block's and the table's widest lines scroll inside their own boxes: the column is no wider than the
        pane, and the pane does not scroll sideways (#doc is fit-content for pages, never for this column)."""
        self.write(FIXTURE + "\n```\n" + "x" * 300 + "\n```\n\n|" + " 넓은 칸 |" * 30 + "\n|" + " - |" * 30 + "\n")
        page = self.open_md(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        got = page.evaluate(
            "(()=>{const L=document.getElementById('left'),m=document.getElementById('md').getBoundingClientRect();"
            "return {over:L.scrollWidth-L.clientWidth,right:m.right,width:L.clientWidth};})()"
        )
        self.assertLessEqual(got["over"], 0)
        self.assertLessEqual(got["right"], got["width"] + 1)


class CoreFirefox(Picking):
    """The draw, a pick and its save in Firefox."""

    BROWSER_ENGINE = "firefox"


# Keep the CSP helpers imported: a test here that injects a violation would mark it expected (helpers_csp.harness_own).
_ = helpers_csp

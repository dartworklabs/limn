"""Characters that hide or reorder text in a drawn Markdown document (docs/adr/0029-text-documents.md D5, docs/handbook/viewer.md
§숨은 문자 and §Markdown 화면).

The real viewer against the in-process server (BrowserBase) on a Markdown document nt whose source puts a bidirectional
override, isolates, zero-width characters, a word joiner, a byte-order mark inside a line and a decoded entity in a heading, a paragraph,
a list item, table cells, a link's text, inline code, a code block, a raw HTML block and an image's alt text:

- each shows by name in its isolating box (.cc), the line reads in source order, the line's text - what a selection, a copy
  and a pin's quote take - is the source's exact characters, and a legitimate sequence (an emoji's joiners, the file's
  first byte-order mark) is left as it is; a notice above the document counts them (Display);
- the outline's rows and the section strip name a heading's characters as text, never raw (Display);
- a click still picks the line it is on and the quote keeps the characters (Display);
- the boxes count against the element limit: 20,000 of them in one paragraph are drawn, with pauses inside it; 40,000 are
  past it, and the line view then names them as text, as the text surface's names view does (Budget);
- a remote image's alt text of 10,000 boxes is built with pauses inside it, and a newer draw stops it there (AltBudget);
- the line view a limit gives draws its lines with the same boxes and notice (LineView);
- a document with a NUL (U+0000) - which markdown-it would turn into U+FFFD - is the line view, its NULs in their boxes,
  copied and quoted as U+0000 (Nul);
- the display holds in Firefox too (DisplayFirefox).

The repertoire itself, its exceptions and the box markup are test_text_surface.py's; the text surface's display is
test_viewer_text.py's.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_markdown_hidden.py
"""

from limn.administration import serve_documents as startup_documents

from helpers import ps
from helpers_browser import BrowserBase, settle, until
from helpers_figure import BUILD1, viewer_build

DRAWN = "typeof MD!=='undefined'&&MD.shown===DOC&&!!document.querySelector('#md')&&!MD.job"
RLO, LRI, PDI, ZWSP, ZWJ, WJ, BOM = "‮", "⁦", "⁩", "​", "‍", "⁠", "﻿"
TROJAN = 'if role != "admin' + RLO + " " + LRI + "# skip check" + PDI + " " + LRI + '":'
LINES = [
    BOM + "첫 줄은 파일의 BOM 으로 시작한다.",  # 1: the file's own mark, kept
    "",
    "# 제목" + RLO + "뒤집힘 " + LRI + "끝" + PDI,  # 3: a heading
    "",
    "문단의 " + RLO + "abc" + PDI + " 와 us" + ZWJ + "er 그리고 a" + BOM + "b.",  # 5: a paragraph
    "",
    "- 목록 항목 " + ZWSP + "영폭",  # 7: a list item
    "",
    "| 칸 | 값 |",  # 9
    "| --- | --- |",
    "| a" + WJ + "b | `코드" + RLO + "x` |",  # 11: table cells, inline code
    "",
    "[링크" + RLO + "글](#제목뒤집힘-끝)",  # 13: a link's text
    "",
    "```py",  # 15
    TROJAN,  # 16: a code block's line
    "```",
    "",
    "<div>" + RLO + "html</div>",  # 19: a raw HTML block
    "",
    "가족 \U0001f468" + ZWJ + "\U0001f469" + ZWJ + "\U0001f467 은 그대로.",  # 21: an emoji's joiners, kept
    "",
    "엔티티 &#x202E;뒤",  # 23: an entity markdown-it decodes into the character
    "",
    "![대체" + RLO + "글](https://tracker.example/x.png)",  # 25: an image's alt text
] + [x for i in range(1, 41) for x in ("", "채움 문단 %d." % i)]  # room to scroll the heading above the reading line
DOC = "\n".join(LINES) + "\n"
# Every box in the document, in document order: [line, name].
BOXES = (
    "[...document.querySelectorAll('#md .cc')].map(e=>{const l=e.closest('[data-line],[data-lo]');"
    "return [+(l.dataset.line||l.dataset.lo),e.dataset.cc];})"
)


class HiddenBase(BrowserBase):
    """BrowserBase with a Markdown document nt (notes.md, DOC) first and the LaTeX manuscript ms second, so the viewer opens on
    the Markdown document. Another document, by DOC_TEXT."""

    DOC_TEXT = DOC

    def setUp(self):
        super().setUp()
        self.src = self.main.parent
        self.md = self.src / "notes.md"
        self.md.write_text(self.DOC_TEXT, encoding="utf-8")
        docs = startup_documents.make_docs(["nt=노트:notes.md", "ms=본문:main.tex"], self.src, ps.APP.C.paths)
        assert isinstance(docs, list), docs
        ps.APP.set_docs(docs)
        viewer_build(docs[1], BUILD1)

    def route(self, route):
        """Another host's request (the remote image's) is aborted: nothing leaves the test."""
        if "tracker.example" in route.request.url:
            return route.abort()
        return super().route(route)

    def open_md(self, **kw):
        """The viewer on the Markdown document, once it is drawn."""
        page = self.open(0, **kw)
        until(page, DRAWN, 20)
        settle(page)
        return page


class Display(HiddenBase):
    """Each marked character shows by name in its box, wherever the document draws its source's text."""

    def test_each_shows_by_name_in_its_box_and_the_text_is_the_sources(self):
        """The boxes, by line: the heading's override and isolates, the paragraph's override, pop, ASCII joiner and inner
        byte-order mark, the item's zero-width space, the table row's word joiner and inline code's override, the link's,
        the code line's four, the HTML placeholder's, the decoded entity's and the alt text's - and none for the file's
        first byte-order mark or the emoji's joiners. Each is an isolating span; the notice counts them; each line's text
        is its source's characters; on the code line and the paragraph the boxes stand left to right in source order.
        Mutation: draw text nodes unmarked in mdText (if(true) for the CC_ANY test) -> fails."""
        page = self.open_md()
        boxes = page.evaluate(BOXES)
        self.assertEqual(
            boxes,
            [[3, "U+202E"], [3, "U+2066"], [3, "U+2069"]]
            + [[5, "U+202E"], [5, "U+2069"], [5, "U+200D"], [5, "U+FEFF"]]
            + [[7, "U+200B"], [11, "U+2060"], [11, "U+202E"], [13, "U+202E"]]
            + [[16, "U+202E"], [16, "U+2066"], [16, "U+2069"], [16, "U+2066"]]
            + [[19, "U+202E"], [23, "U+202E"], [25, "U+202E"]],
        )
        self.assertEqual(
            set(page.evaluate("[...document.querySelectorAll('#md .cc')].map(e=>getComputedStyle(e).unicodeBidi)")),
            {"isolate"},
        )
        note = page.evaluate("(document.querySelector('#md > .tx-note[data-note=marks]')||{}).textContent")
        self.assertEqual(note, "보이지 않거나 글 순서를 바꾸는 문자 %d개를 이름으로 표시했습니다" % len(boxes))
        self.assertEqual(page.evaluate("document.querySelector('#md').firstElementChild.dataset.note"), "marks")
        text = page.evaluate(
            '(()=>{const t=n=>document.querySelector("#md [data-line=\'"+n+"\']").textContent;'
            "return {first:t(1),head:t(3),para:t(5),code:t(16),kin:t(21),ent:t(23)};})()"
        )
        lines = LINES
        self.assertEqual(text["first"], lines[0])  # the mark kept as it is, in the text
        self.assertEqual(text["head"], lines[2][2:])
        self.assertEqual(text["para"], lines[4])
        self.assertEqual(text["code"], TROJAN + "\n")
        self.assertEqual(text["kin"], lines[20])
        self.assertEqual(text["ent"], "엔티티 " + RLO + "뒤")
        for n in (5, 16):
            xs = page.evaluate(
                "[...document.querySelectorAll(\"#md [data-line='%d'] .cc\")].map(e=>Math.round(e.getBoundingClientRect().left))"
                % n
            )
            self.assertEqual(xs, sorted(xs), n)
        alt = page.evaluate("document.querySelector('#md .md-img').textContent")
        self.assertEqual(alt, "그림: 대체" + RLO + "글")

    def test_a_selection_and_a_pick_keep_the_characters_and_their_lines(self):
        """A selection of the paragraph's line gives its exact characters; a click on it picks line 5 and the pin's quote keeps
        the override where it stands, with no space put round it; the line elements and their lines are what they would be
        without the boxes (no box carries a line). Mutation: read the tap's quote as the block's innerText -> fails."""
        page = self.open_md()
        sel = page.evaluate(
            "(()=>{const l=document.querySelector(\"#md [data-line='5']\"),r=document.createRange(); r.selectNodeContents(l);"
            "const s=getSelection(); s.removeAllRanges(); s.addRange(r); const t=s.toString(); s.removeAllRanges(); return t;})()"
        )
        self.assertEqual(sel, LINES[4])
        self.assertEqual(
            page.evaluate(
                "document.querySelectorAll('#md .cc[data-line],#md .cc[data-lo],#md .cc [data-line]').length"
            ),
            0,
        )
        lines = page.evaluate("mdLineEls().map(e=>+(e.dataset.line||e.dataset.lo))")
        self.assertEqual(lines, sorted(lines))
        page.locator("#md [data-line='5']").click()
        until(page, "COMPOSE.current&&COMPOSE.current.lo===5")
        got = page.evaluate("({lo:COMPOSE.current.lo,hi:COMPOSE.current.hi,quote:COMPOSE.current.quote})")
        self.assertEqual((got["lo"], got["hi"]), (5, 5))
        self.assertIn("문단의 " + RLO + "abc" + PDI + " 와 us" + ZWJ + "er", got["quote"])

    def test_the_outline_and_the_strip_name_a_headings_characters_as_text(self):
        """The heading's outline row and the section strip read its override and isolates as ⟨U+…⟩, with no raw character;
        the heading's slug and its in-document link still work. Mutation: give mdOutline the raw title -> fails."""
        page = self.open_md()
        row = page.evaluate("[...document.querySelectorAll('#outline-items .ol-name')].map(e=>e.textContent)")
        self.assertEqual(row, ["제목⟨U+202E⟩뒤집힘 ⟨U+2066⟩끝⟨U+2069⟩"])
        page.evaluate("document.querySelector('#left').scrollTop=document.querySelector('#left').scrollHeight")
        until(page, "document.querySelector('#section-current').textContent.startsWith('제목')")
        strip = page.evaluate("document.querySelector('#section-current').textContent")
        self.assertEqual(strip, "제목⟨U+202E⟩뒤집힘 ⟨U+2066⟩끝⟨U+2069⟩")
        for raw in (RLO, LRI, PDI):
            self.assertNotIn(raw, row[0] + strip)


class DisplayFirefox(Display):
    """The same display in Firefox."""

    BROWSER_ENGINE = "firefox"


class Budget(HiddenBase):
    """Boxes are elements: they count against MD_LIMITS.elements, and the build pauses among them."""

    DOC_TEXT = "# 한도\n\n" + ("a" + ZWSP) * 20_000 + "\n"

    def test_boxes_within_the_limit_are_drawn_with_pauses_and_past_it_the_line_view_names_them(self):
        """20,000 zero-width spaces in one paragraph: drawn (no data-limit), every one a box, under MD_LIMITS.elements
        elements, with a pause to the browser at least every MD_LIMITS.chunk of them. 40,000: past the limit, the line view
        (data-limit elements) names every one as ⟨U+200B⟩ in plain text, no box, its notice saying so. Mutation: count no
        element for a box in mdBox -> 40,000 boxes are drawn, fails."""
        page = self.open_md()
        got = page.evaluate(
            "(()=>{const md=document.querySelector('#md');return {limit:md.dataset.limit||null,boxes:md.querySelectorAll('.cc').length,"
            "els:md.querySelectorAll('*').length,max:MD_LIMITS.elements};})()"
        )
        self.assertEqual((got["limit"], got["boxes"]), (None, 20_000))
        self.assertLess(got["els"], got["max"])
        pauses = page.evaluate(
            "(async()=>{const y=mdYield; let n=0; window.mdYield=()=>{n++; return y();};"
            "const res=await mdParse(MD.lines.join('\\n')); await mdRenderAll(res.tokens,()=>false); window.mdYield=y; return n;})()"
        )
        self.assertGreaterEqual(pauses, 20_000 // 2_000)
        self.md.write_text("# 한도\n\n" + ("a" + ZWSP) * 40_000 + "\n", encoding="utf-8")
        page.evaluate("pollLight()")
        until(page, "document.querySelector('#md').dataset.limit==='elements'", 15)
        got = page.evaluate(
            "(()=>{const md=document.querySelector('#md'),l=md.querySelector(\"[data-line='3']\");"
            "return {lines:md.classList.contains('md-lines'),boxes:md.querySelectorAll('.cc').length,raw:l.textContent.includes('\\u200b'),"
            "count:(l.textContent.match(/\\u27e8U\\+200B\\u27e9/g)||[]).length,note:md.querySelector('.tx-note[data-note=marks]').textContent,"
            "head:md.querySelector('.md-limit:not(.tx-note)').textContent};})()"
        )
        self.assertEqual((got["lines"], got["boxes"], got["raw"], got["count"]), (True, 0, False, 40_000))
        self.assertIn("40,000개", got["note"])
        self.assertIn("이름이 복사됩니다", got["note"])
        self.assertIn("그릴 요소가 너무 많아", got["head"])


class AltBudget(HiddenBase):
    """A remote image's alt text is drawn text like a paragraph's: its boxes pause the build and a newer draw stops it."""

    DOC_TEXT = "# 대체 글\n\n![" + ("a" + ZWSP) * 10_000 + "](https://tracker.example/x.png)\n"

    def test_a_long_alt_text_yields_and_a_newer_draw_stops_it(self):
        """10,000 zero-width spaces in the alt text of a remote image (one inline child): all drawn as boxes in its
        .md-img, with a pause to the browser at least every MD_LIMITS.chunk of them; a build whose draw goes stale at its
        first pause stops there, with fewer than half of the boxes built. Mutation: draw the alt text with mdTextNow (no
        pause) -> no pause inside it and every box built before the stale draw stops, fails."""
        page = self.open_md()
        self.assertEqual(page.evaluate("document.querySelectorAll('#md .md-img .cc').length"), 10_000)
        got = page.evaluate(
            "(async()=>{const y=mdYield; let n=0; window.mdYield=()=>{n++; return y();};"
            "const res=await mdParse(MD.lines.join('\\n')); await mdRenderAll(res.tokens,()=>false); const pauses=n; n=0;"
            "const root=await mdRenderAll(res.tokens,()=>n>0); window.mdYield=y; return {pauses,stopped:root===null,built:MD.marked};})()"
        )
        self.assertGreaterEqual(got["pauses"], 10_000 // 2_000)
        self.assertTrue(got["stopped"])
        self.assertLess(got["built"], 5_000)


class LineView(HiddenBase):
    """The line view a parse limit gives draws the source's lines with the same boxes."""

    DOC_TEXT = "> " * 25 + "깊은 인용 " + RLO + "끝\n\n둘째 줄 " + ZWSP + "\n"

    def test_the_line_view_boxes_its_lines_characters_and_counts_them(self):
        """Nested past markdown-it's limit, the document is the line view (data-limit nesting): line 1's override and line
        3's zero-width space are boxes, line 1's text is its source's, and the notice under the limit's line counts two.
        Mutation: draw the line view's lines as plain text (srcLines without boxes) -> fails."""
        page = self.open_md()
        got = page.evaluate(
            "(()=>{const md=document.querySelector('#md');return {limit:md.dataset.limit,lines:md.classList.contains('md-lines'),"
            "boxes:[...md.querySelectorAll('.cc')].map(e=>[+e.closest('[data-line]').dataset.line,e.dataset.cc]),"
            "first:md.querySelector(\"[data-line='1']\").textContent,"
            "notes:[...md.querySelectorAll('.md-limit')].map(e=>e.dataset.note||'limit')};})()"
        )
        self.assertEqual((got["limit"], got["lines"]), ("nesting", True))
        self.assertEqual(got["boxes"], [[1, "U+202E"], [3, "U+200B"]])
        self.assertEqual(got["first"], self.DOC_TEXT.split("\n")[0] + "\n")
        self.assertEqual(got["notes"], ["limit", "marks"])
        self.assertEqual(
            page.evaluate("document.querySelector('#md .tx-note[data-note=marks]').textContent"),
            "보이지 않거나 글 순서를 바꾸는 문자 2개를 이름으로 표시했습니다",
        )


class Nul(HiddenBase):
    """A NUL (U+0000) in the source sends the document to the line view, which keeps it."""

    NUL = "\u0000"
    DOC_TEXT = "# 널\n\n문단 a" + NUL + "b 끝.\n\n`코드" + NUL + "x` 안.\n\n```\n줄 c" + NUL + "d\n```\n"

    def test_a_nul_in_a_paragraph_inline_code_and_a_code_block_is_kept_in_its_box(self):
        """NULs in a paragraph (line 3), in inline code (line 5) and on a code block's line (line 8): markdown-it would draw
        each as U+FFFD with no box, so the document is the line view (data-limit nul) under a line saying why; each NUL is
        a box named ␀ on its own line, the notice counts three, no U+FFFD is drawn, each line's text is its source's, a
        selection of line 3 copies the U+0000, and a click on it picks line 3 with the U+0000 in the pin's quote.
        Mutation: drop the NUL test before mdParse in mdBuild -> the drawn document shows U+FFFD and no box, fails."""
        page = self.open_md()
        lines = self.DOC_TEXT.split("\n")
        got = page.evaluate(
            "(()=>{const md=document.querySelector('#md');return {limit:md.dataset.limit||null,lines:md.classList.contains('md-lines'),"
            "boxes:[...md.querySelectorAll('.cc')].map(e=>[+e.closest('[data-line]').dataset.line,e.dataset.cc]),"
            "fffd:md.textContent.includes('\\ufffd'),head:(md.querySelector('.md-limit:not(.tx-note)')||{}).textContent,"
            "note:(md.querySelector('.tx-note[data-note=marks]')||{}).textContent,"
            "text:[3,5,8].map(n=>(md.querySelector(\"[data-line='\"+n+\"']\")||{}).textContent)};})()"
        )
        self.assertEqual((got["limit"], got["lines"], got["fffd"]), ("nul", True, False))
        self.assertEqual(got["boxes"], [[3, "\u2400"], [5, "\u2400"], [8, "\u2400"]])
        self.assertEqual(got["head"], "원문에 NUL 문자(U+0000)가 있어 원문 줄로 보입니다. Markdown으로 그리면 그 문자가 U+FFFD로 바뀝니다")
        self.assertEqual(got["note"], "보이지 않거나 글 순서를 바꾸는 문자 3개를 이름으로 표시했습니다")
        self.assertEqual(got["text"], [lines[2] + "\n", lines[4] + "\n", lines[7] + "\n"])
        sel = page.evaluate(
            "(()=>{const l=document.querySelector(\"#md [data-line='3']\"),r=document.createRange(); r.selectNodeContents(l);"
            "const s=getSelection(); s.removeAllRanges(); s.addRange(r); const t=s.toString(); s.removeAllRanges(); return t;})()"
        )
        self.assertIn("a" + self.NUL + "b", sel)
        page.locator("#md [data-line='3']").click()
        until(page, "COMPOSE.current&&COMPOSE.current.lo===3")
        self.assertIn("a" + self.NUL + "b", page.evaluate("COMPOSE.current.quote"))


class NulFirefox(Nul):
    """The same in Firefox."""

    BROWSER_ENGINE = "firefox"

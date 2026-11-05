"""The text surface in the browser (docs/adr/0029-text-documents.md, docs/superpowers/specs/2026-11-05-text-documents.md).

A text document (kind text, here check.py) is drawn by the viewer from GET /api/source line for line, never parsed. These
tests drive the real viewer against the in-process server (BrowserBase) and check what a person sees:

- a character that would hide or reorder text shows by name in its box, its line reads in source order, a selection's text
  keeps it, a notice counts them, and the ladder's labels and the excerpt under it name them too;
- the limits: a line of 100,000 zero-width spaces gives the bounded names view, the build pauses inside that line and a
  newer draw stops it;
- line ends that are not LF or CRLF are counted in a notice above the lines;
- a suggestion that adds such a character is marked in its card's diff and warned about under the editor;
- picks: a click or a tap takes its line, a drag or a finger's selection the lines it covers, the ladder's rungs (the
  chosen lines, the paragraph, the indented block, the shorter first and merged when alike, several paragraphs saved as
  lines) and the saved pin, which carries no page;
- the column at the foldable's 344 px outer screen: the page never scrolls sideways;
- a change to the source on disk is drawn again at the reading line.

Picks and the hidden-character display run in Firefox too (the *Firefox classes).

The pure rules (ladder, closing lines, the repertoire and its exceptions) are test_text_surface.py.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_text.py
"""

import json

from limn.administration import serve_documents as startup_documents

from helpers import add_pin, ps, req
from helpers_access import ALICE, actor
from helpers_browser import BrowserBase, settle
from helpers_figure import BUILD1, viewer_build

# Resolves when the text document on screen is drawn (its view or a notice) and no draw is waiting.
DRAWN = "typeof MD!=='undefined'&&MD.shown===DOC&&!!document.querySelector('#md')"
COACH_SEEN = "try{localStorage.setItem('pinPrefs',JSON.stringify({coach:{touch:1,mouse:1,sel:1}}));}catch(e){}"
# Trojan Source (CVE-2021-42574): drawn as it is, line 3 reads as a comparison followed by a comment; in the source the
# "comment" is inside the string. Line 6 heads a block whose header holds an override too.
TROJAN = 'if role != "admin‮ ⁦# skip check⁩ ⁦":'
TEXT = (
    "def check(role):\n"  # 1
    '    """Who may pass."""\n'  # 2
    "    " + TROJAN + "\n"  # 3
    "        return False\n"  # 4
    "    return True\n"  # 5
    "def ‮tick(x):\n"  # 6
    "    return x\n"  # 7
)


class TextBase(BrowserBase):
    """BrowserBase with a text document tx (check.py, TEXT) first and the LaTeX manuscript ms second (its two-page build on
    screen), so the viewer opens on the text document."""

    TEXT = TEXT

    def setUp(self):
        super().setUp()
        self.src = self.main.parent
        self.py = self.src / "check.py"
        self.write(self.TEXT)
        docs = startup_documents.make_docs(["tx=코드:check.py", "ms=본문:main.tex"], self.src, ps.APP.C.paths)
        assert isinstance(docs, list), docs
        ps.APP.set_docs(docs)
        self.tx, self.ms = docs
        viewer_build(self.ms, BUILD1)

    def write(self, text):
        """check.py as text (str, written as UTF-8 bytes: no newline translation) or bytes."""
        self.py.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))

    def open_tx(self, n_open=0, **kw):
        """The viewer on the text document, once it is drawn."""
        page = self.open(n_open, init=COACH_SEEN, **kw)
        page.wait_for_function(DRAWN, timeout=20000)
        settle(page)
        return page

    def pick_line(self, page, n):
        """Click source line n and wait for the composer to show it."""
        page.locator("#md [data-line='%d']" % n).first.click()
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo>0", timeout=5000)
        settle(page)

    def add(self, lo, hi, suggest=None, note="n"):
        """An open line pin on check.py lo-hi by Alice, with suggest when given; its id."""
        d = {"doc": "tx", "file": str(self.py), "lo": lo, "hi": hi, "note": note}
        if suggest:
            d["suggest"] = suggest
        return add_pin(d, actor(ALICE), doc=self.tx).core.id


class HiddenCharacters(TextBase):
    """Characters that would hide or reorder text, on the surface and wherever its lines are shown again."""

    def test_each_shows_by_name_its_line_reads_in_order_and_a_selection_keeps_it(self):
        """Line 3's override and isolates are boxes named U+202E, U+2066, U+2069, U+2066 in source order, each an
        isolating span; the notice counts the document's five; selecting line 3 gives its exact text with the characters
        and the line end."""
        page = self.open_tx()
        got = page.evaluate(
            "(()=>{const l=document.querySelector(\"#md [data-line='3']\"),cc=[...l.querySelectorAll('.cc')];"
            "return {names:cc.map(e=>e.dataset.cc),iso:cc.map(e=>getComputedStyle(e).unicodeBidi),text:l.textContent,"
            "note:(document.querySelector('#md .tx-note[data-note=marks]')||{}).textContent};})()"
        )
        self.assertEqual(got["names"], ["U+202E", "U+2066", "U+2069", "U+2066"])
        self.assertEqual(set(got["iso"]), {"isolate"})
        self.assertEqual(got["text"], "    " + TROJAN + "\n")
        self.assertEqual(got["note"], "보이지 않거나 글 순서를 바꾸는 문자 5개를 이름으로 표시했습니다")
        sel = page.evaluate(
            "(()=>{const l=document.querySelector(\"#md [data-line='3']\"),r=document.createRange(); r.selectNodeContents(l);"
            "const s=getSelection(); s.removeAllRanges(); s.addRange(r); const t=s.toString(); s.removeAllRanges(); return t;})()"
        )
        self.assertEqual(sel.rstrip("\n"), "    " + TROJAN)
        # Drawn, the boxes stand in source order from left to right: the string's closing quote stays after them.
        xs = page.evaluate(
            "[...document.querySelectorAll(\"#md [data-line='3'] .cc\")].map(e=>Math.round(e.getBoundingClientRect().left))"
        )
        self.assertEqual(xs, sorted(xs))

    def test_the_ladder_label_and_the_excerpt_name_them_too(self):
        """A pick of line 6, whose block header holds U+202E: the indent rung's label names it in angle brackets with no
        raw character; the excerpt under the ladder shows it in its box."""
        page = self.open_tx()
        self.pick_line(page, 6)
        labels = page.evaluate(
            "[...document.querySelectorAll('#c-levels button')].map(b=>b.textContent+'|'+b.getAttribute('aria-label'))"
        )
        indent = [t for t in labels if t.startswith("블록")]
        self.assertEqual(len(indent), 1, labels)
        self.assertIn("⟨U+202E⟩", indent[0])
        self.assertNotIn("‮", "".join(labels))
        self.assertEqual(
            page.evaluate("[...document.querySelectorAll(\"#c-xp .xp-row[data-line='6'] .cc\")].map(e=>e.dataset.cc)"),
            ["U+202E"],
        )

    def test_a_quote_names_them_on_its_card_and_in_its_tooltip(self):
        """A pin whose quote (the text a person selected) holds line 3's override: the card's quote line shows each in its
        box and its tooltip names them, never the raw character."""
        d = {"doc": "tx", "file": str(self.py), "lo": 3, "hi": 3, "note": "n", "quote": TROJAN}
        add_pin(d, actor(ALICE), doc=self.tx)
        page = self.open_tx(n_open=1)
        got = page.evaluate(
            "(()=>{const q=document.querySelector('.pin .quote'); return q&&{names:[...q.querySelectorAll('.cc')].map(e=>e.dataset.cc),tip:q.dataset.tip};})()"
        )
        self.assertEqual(got["names"], ["U+202E", "U+2066", "U+2069", "U+2066"])
        self.assertIn("⟨U+202E⟩", got["tip"])
        self.assertNotIn("\u202e", got["tip"])


class Limits(TextBase):
    """A line of 100,000 zero-width spaces: the bounded names view, a build that pauses inside the line and stops for a
    newer draw."""

    TEXT = "a​" * 100_000 + "\nlast\n"

    def test_past_the_element_limit_the_view_names_them_as_text(self):
        """The view is the names view (data-limit elements): no box, under MD_LIMITS.elements elements, line 1 names every
        character as ⟨U+200B⟩ in plain text, line 2 is there, and the notice says why and that a copy gives the names."""
        page = self.open_tx()
        got = page.evaluate(
            "(()=>{const md=document.querySelector('#md'),l=md.querySelector(\"[data-line='1']\");"
            "return {limit:md.dataset.limit,boxes:md.querySelectorAll('.cc').length,els:md.querySelectorAll('*').length,max:MD_LIMITS.elements,"
            "head:l.textContent.slice(0,22),count:(l.textContent.match(/\\u27e8U\\+200B\\u27e9/g)||[]).length,raw:l.textContent.includes('\\u200b'),"
            "last:md.querySelector(\"[data-line='2']\").textContent,note:md.querySelector('.tx-note[data-note=marks]').textContent};})()"
        )
        self.assertEqual((got["limit"], got["boxes"], got["raw"], got["count"]), ("elements", 0, False, 100_000))
        self.assertLess(got["els"], got["max"])
        self.assertEqual(got["head"], "a⟨U+200B⟩a⟨U+200B⟩a⟨U+")
        self.assertEqual(got["last"], "last\n")
        self.assertIn("100,000개", got["note"])
        self.assertIn("이름이 복사됩니다", got["note"])

    def test_the_build_pauses_inside_the_line_and_stops_for_a_newer_draw(self):
        """txView yields to the browser at least once per MD_LIMITS.chunk characters of the repertoire inside one line:
        over 20,000 of them, within the element limit, it draws every box; over 100,000 it ends in the names view; and a
        draw that turns stale after its third pause returns null at that pause."""
        page = self.open_tx()
        got = page.evaluate(
            "(async()=>{const y=mdYield,keep=MD.lines; let n=0; window.mdYield=()=>{n++; return y();};"
            "MD.lines=['a\\u200b'.repeat(20000)]; const b=await txView(()=>false,{}); const boxed=n; n=0; MD.lines=keep;"
            "const v=await txView(()=>false,{}); const full=n; n=0; let k=0; const s=await txView(()=>++k>3,{});"
            "window.mdYield=y; return {boxed,boxes:b&&b.querySelectorAll('.cc').length,boxLimit:b&&b.dataset.limit||null,"
            "full,limit:v&&v.dataset.limit,stale:s,pauses:n};})()"
        )
        self.assertEqual((got["boxes"], got["boxLimit"]), (20_000, None))
        self.assertGreaterEqual(got["boxed"], 20_000 // 2_000)
        self.assertGreaterEqual(got["full"], 100_000 // 2_000)
        self.assertEqual((got["limit"], got["stale"], got["pauses"]), ("elements", None, 4))


class MixedLimits(TextBase):
    """A line of 6,000 zero-width spaces and 49,999 plain lines after it: within the file's limits, but its boxes and its line
    spans together pass MD_LIMITS.elements."""

    TEXT = "\u200b" * 6_000 + "\n" + "x\n" * 49_999

    def test_every_line_counts_against_the_element_limit(self):
        """The view is the names view (data-limit elements, no box), under MD_LIMITS.elements elements, with all 50,000
        lines on screen and line 1 naming its 6,000 characters as text."""
        page = self.open_tx()
        got = page.evaluate(
            "(()=>{const md=document.querySelector('#md'),l=md.querySelector(\"[data-line='1']\");"
            "return {limit:md.dataset.limit||null,boxes:md.querySelectorAll('.cc').length,els:md.querySelectorAll('*').length,"
            "max:MD_LIMITS.elements,lines:md.querySelectorAll('.ln').length,count:(l.textContent.match(/\\u27e8U\\+200B\\u27e9/g)||[]).length};})()"
        )
        self.assertEqual((got["limit"], got["boxes"], got["lines"], got["count"]), ("elements", 0, 50_000, 6_000))
        self.assertLess(got["els"], got["max"])


class LineEnds(TextBase):
    """Line ends the server splits on that are not LF or CRLF are counted above the lines."""

    TEXT = b"a = 1\r\nb = 2\x0cc = 3\xe2\x80\xa8d = 4\x0ce = 5\n"

    def test_the_notice_names_each_with_its_count_and_crlf_is_none_of_them(self):
        """Two form feeds and a U+2028 (CRLF not counted): the notice names them; five lines carry the server's numbers."""
        page = self.open_tx()
        got = page.evaluate(
            "(()=>{const n=document.querySelector('#md .tx-note[data-note=ends]');"
            "return {note:n&&n.textContent,lines:[...document.querySelectorAll('#md .ln')].map(e=>e.textContent)};})()"
        )
        self.assertEqual(
            got["note"],
            "줄 끝 3곳이 LF가 아닙니다(U+000C 2, U+2028 1). Limn은 거기서 줄을 나누므로, 줄 번호가 LF만 세는 편집기·git과 "
            "다를 수 있고 복사하면 LF로 바뀝니다",
        )
        self.assertEqual(got["lines"], ["a = 1\n", "b = 2\n", "c = 3\n", "d = 4\n", "e = 5\n"])

    def test_a_document_of_lf_and_crlf_has_no_such_notice(self):
        """LF and CRLF only: no notice."""
        self.write(b"a\r\nb\nc\r\n")
        page = self.open_tx()
        self.assertFalse(page.evaluate("!!document.querySelector('#md .tx-note[data-note=ends]')"))


class Suggestions(TextBase):
    """A suggestion's text on a text document: its card's diff marks what it adds, and the editor warns before it is saved."""

    def test_a_card_marks_what_its_suggestion_adds(self):
        """A suggestion that turns line 5 into an override: its card's added row shows the U+202E box, the removed row none."""
        self.add(5, 5, suggest={"base": "    return True", "text": "    return ‮True"})
        page = self.open_tx(n_open=1)
        rows = page.evaluate(
            "[...document.querySelectorAll('.pin .sg-diff .rd-line')].map(r=>[r.className,[...r.querySelectorAll('.cc')].map(e=>e.dataset.cc)])"
        )
        self.assertEqual(rows, [["rd-line rd-del", []], ["rd-line rd-add", ["U+202E"]]])

    def test_the_editor_warns_about_what_the_draft_adds(self):
        """Line 3 picked and the switch on: the draft keeps the line's own four characters - a plain line says so; typing
        a zero-width space adds one - the line turns to the warning, names it with its count and shows the added line with
        its box; taking it out brings the plain line back."""
        page = self.open_tx()
        self.pick_line(page, 3)
        page.click("#c-sg-tg")
        page.wait_for_function("SG.base!=null", timeout=5000)
        settle(page)
        state = (
            "(()=>{const e=document.querySelector('#c-sg-cc');"
            "return {shown:!!e&&e.getClientRects().length>0,warn:e.classList.contains('sg-cc-warn'),text:e.querySelector('span')?e.querySelector('span').textContent:null,"
            "boxes:[...e.querySelectorAll('.sg-diff .cc')].map(b=>b.dataset.cc)};})()"
        )
        got = page.evaluate(state)
        self.assertEqual((got["shown"], got["warn"], got["boxes"]), (True, False, []))
        self.assertEqual(
            got["text"],
            "원문에 있던, 보이지 않거나 글 순서를 바꾸는 문자 4개가 제안 문안에 그대로 있습니다. 이 칸에서는 보이지 않습니다",
        )
        page.fill("#c-sg-text", "    " + TROJAN + "​")
        settle(page)
        got = page.evaluate(state)
        self.assertEqual((got["shown"], got["warn"]), (True, True))
        self.assertIn("U+200B 1개", got["text"])
        self.assertIn("U+200B", got["boxes"])
        page.fill("#c-sg-text", "    " + TROJAN)
        settle(page)
        self.assertEqual(page.evaluate(state)["warn"], False)

    def test_a_draft_that_adds_an_override_is_warned_about_and_pins_md_flags_it(self):
        """Line 5 (no hidden character) picked and the switch on: no line under the editor. A draft that adds U+202E turns
        it to the warning, naming U+202E with its count and showing the added line with its box; saved, the card's diff
        marks it and pins.md's `## 제안 문안` block carries the hidden-character line for the agent."""
        page = self.open_tx()
        self.pick_line(page, 5)
        page.click("#c-sg-tg")
        page.wait_for_function("SG.base!=null", timeout=5000)
        settle(page)
        state = (
            "(()=>{const e=document.querySelector('#c-sg-cc');"
            "return {shown:!!e&&e.getClientRects().length>0,warn:!!e&&e.classList.contains('sg-cc-warn'),"
            "text:e&&e.querySelector('span')?e.querySelector('span').textContent:null,"
            "boxes:e?[...e.querySelectorAll('.sg-diff .cc')].map(b=>b.dataset.cc):[]};})()"
        )
        self.assertEqual(page.evaluate(state)["shown"], False)
        page.fill("#c-sg-text", "    return \u202eTrue")
        settle(page)
        got = page.evaluate(state)
        self.assertEqual((got["shown"], got["warn"], got["boxes"]), (True, True, ["U+202E"]))
        self.assertEqual(
            got["text"],
            "제안 문안이 원문에 없는, 보이지 않거나 글 순서를 바꾸는 문자를 넣습니다: U+202E 1개. "
            "이 칸에서는 보이지 않거나 글 순서가 바뀌어 보입니다",
        )
        n = page.evaluate("PINS.length")
        page.click("#btn-save")
        page.wait_for_function("PINS.length>%d" % n, timeout=8000)
        settle(page)
        rows = page.evaluate(
            "[...document.querySelectorAll('.pin .sg-diff .rd-line')].map(r=>[r.className,[...r.querySelectorAll('.cc')].map(e=>e.dataset.cc)])"
        )
        self.assertEqual(rows, [["rd-line rd-del", []], ["rd-line rd-add", ["U+202E"]]])
        md = self.talk(req("GET", "/pins.md"))[2].decode()
        self.assertIn(
            "\n숨은 문자: 원문에 없는 U+202E 1개 — 보이지 않거나 글 순서를 바꾸는 문자다. "
            "넣기 전에 그 문자가 필요한지 답글로 묻는다\n```\n    return \u202eTrue\n```\n",
            md,
        )


# The pick fixture: a script with two paragraphs between blank lines, the first a function with a loop in it.
PLOT = (
    "import numpy as np\n"  # 1
    "\n"  # 2
    "def plot(ax, data):\n"  # 3
    '    """Draw the power."""\n'  # 4
    "    for row in data:\n"  # 5
    "        ax.plot(row)\n"  # 6
    "    return ax\n"  # 7
    "\n"  # 8
    "def save(fig):\n"  # 9
    '    fig.savefig("p.pdf")\n'  # 10
)
PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
OUTER = {"viewport": {"width": 344, "height": 882}, "is_mobile": True, "has_touch": True}  # the foldable's outer screen
# What the composer holds: the chosen range, its scope and the ladder's rungs [level, lo, hi, merged levels].
COMPOSED = (
    "COMPOSE.current&&{lo:COMPOSE.current.lo,hi:COMPOSE.current.hi,scope:COMPOSE.current.scope,"
    "levels:COMPOSE.current.levels.map(l=>[l.level,l.lo,l.hi,l.merged||[]])}"
)


def records(state):
    """The live pin records in the state folder's pins.jsonl."""
    f = state / "pins.jsonl"
    return [json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()] if f.exists() else []


class PickBase(TextBase):
    """TextBase on PLOT, with the pick and save steps a person takes."""

    TEXT = PLOT

    def composed(self, page):
        """The composer's range, scope and rungs once it shows a pick."""
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo>0", timeout=5000)
        settle(page)
        return page.evaluate("(()=>(%s))()" % COMPOSED)

    def drag(self, page, a, b):
        """A mouse drag from the first character of line a to the seventh of line b."""
        x0, y0, x1, y1 = page.evaluate(
            "([a,b])=>{const at=(n,k)=>{const t=document.querySelector(`#md [data-line='${n}']`).firstChild,"
            "r=document.createRange(); r.setStart(t,k); r.setEnd(t,k+1); return r.getBoundingClientRect();},"
            "s=at(a,0),e=at(b,6); return [s.left+1,s.top+s.height/2,e.left+e.width/2,e.top+e.height/2];}",
            [a, b],
        )
        page.mouse.move(x0, y0)
        page.mouse.down()
        page.mouse.move(x1, y1, steps=6)
        page.mouse.up()

    def choose(self, page, level):
        """Press the rung for level on the composer's ladder."""
        page.click("#c-levels button[data-level='%s']" % level)
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.scope===%s" % json.dumps(level), timeout=5000)

    def save(self, page, note="고쳐 주세요"):
        """Type note into the composer and save; the new pin's stored record."""
        n = page.evaluate("PINS.length")
        page.fill("#note", note)
        page.click("#btn-save")
        page.wait_for_function("PINS.length>%d" % n, timeout=8000)
        settle(page)
        return records(ps.APP.C.state)[-1]


class Picking(PickBase):
    """A click, a drag and the ladder on a text document, and the pin they save."""

    def test_a_click_picks_its_line_and_the_block_rung_saves_an_indent_pin(self):
        """A click on line 5 (a loop's header) picks that line at the chosen-lines rung; the ladder is the line, the
        loop's indented block (5-6) and the function's paragraph (3-7), the shorter first. The block rung saves kind and
        scope indent, no page, frac or pdf_build; pins.md writes `—` and `indent`; the two lines get the pin's mark and
        one gutter badge."""
        page = self.open_tx()
        page.locator("#md [data-line='5']").first.click()
        got = self.composed(page)
        self.assertEqual((got["lo"], got["hi"], got["scope"]), (5, 5, "raw"))
        self.assertEqual([lv[:3] for lv in got["levels"]], [["raw", 5, 5], ["indent", 5, 6], ["para", 3, 7]])
        labels = page.evaluate("[...document.querySelectorAll('#c-levels button')].map(b=>b.textContent.trim())")
        self.assertTrue(labels[1].startswith("블록 · for row in d"), labels)
        self.assertTrue(labels[2].startswith("문단"), labels)
        self.assertTrue(page.evaluate("document.getElementById('c-page').hidden"))
        self.choose(page, "indent")
        rec = self.save(page)
        self.assertEqual(
            (rec["doc"], rec["lo"], rec["hi"], rec["scope"], rec["kind"]), ("tx", 5, 6, "indent", "indent")
        )
        for field in ("page", "frac", "pdf_build"):
            self.assertNotIn(field, rec)
        md = self.talk(req("GET", "/pins.md"))[2].decode()
        self.assertIn("\n| %d | — | `check.py L5-L6` | indent | 고쳐 주세요 |\n" % rec["id"], md)
        self.assertEqual(
            page.evaluate("[...document.querySelectorAll('#md .md-badge')].map(b=>b.textContent)"), [str(rec["id"])]
        )
        self.assertEqual(page.evaluate("document.querySelectorAll('#md .md-pin').length"), 2)

    def test_a_drag_picks_the_lines_it_covers_and_a_block_like_its_paragraph_merges(self):
        """A drag from line 3 into line 4 picks lines 3-4 at the chosen-lines rung. Their paragraph and the function's
        block are both lines 3-7: one rung, the paragraph, with the block merged into it. Saved at that rung, the pin is
        a paragraph (scope para, kind paragraph)."""
        page = self.open_tx()
        self.drag(page, 3, 4)
        got = self.composed(page)
        self.assertEqual((got["lo"], got["hi"], got["scope"]), (3, 4, "raw"))
        self.assertEqual(got["levels"], [["raw", 3, 4, []], ["para", 3, 7, ["indent"]]])
        self.choose(page, "para")
        rec = self.save(page)
        self.assertEqual((rec["lo"], rec["hi"], rec["scope"], rec["kind"]), (3, 7, "para", "paragraph"))

    def test_a_pick_over_two_paragraphs_offers_them_whole_and_saves_lines(self):
        """A drag from line 7 into line 9 meets both paragraphs: the rung after the lines is '문단 2개' (3-10) and no block
        rung (the lines stand at the file's top level); saved at it, the pin is lines 3-10, scope and kind lines."""
        page = self.open_tx()
        self.drag(page, 7, 9)
        got = self.composed(page)
        self.assertEqual((got["lo"], got["hi"]), (7, 9))
        self.assertEqual([lv[:3] for lv in got["levels"]], [["raw", 7, 9], ["blocks", 3, 10]])
        self.assertTrue(
            page.evaluate("document.querySelectorAll('#c-levels button')[1].textContent.trim()").startswith("문단 2개")
        )
        page.click("#c-levels button[data-level='blocks']")
        settle(page)
        rec = self.save(page)
        self.assertEqual((rec["lo"], rec["hi"], rec["scope"], rec["kind"]), (3, 10, "lines", "lines"))


class PickingFirefox(Picking):
    """The click, the drag and the ladder in Firefox."""

    BROWSER_ENGINE = "firefox"


class HiddenCharactersFirefox(HiddenCharacters):
    """The boxes, their order, the notice and a selection's text in Firefox."""

    BROWSER_ENGINE = "firefox"


class Touch(PickBase):
    """A phone: a tap picks its line, a finger's selection the lines it covers. Lines are found by their text, so a line
    number the surface gets wrong shows."""

    def test_a_tap_picks_its_line_and_the_position_button_reads_lines(self):
        """A tap on `ax.plot(row)` picks line 6 at the chosen-lines rung (not its paragraph); the position button reads
        L<line>/10, and the empty list's help speaks of lines for a finger."""
        page = self.open_tx(**PHONE)
        self.assertRegex(page.evaluate("document.getElementById('btn-pos-p').textContent"), r"^L\d+/10$")
        hint = page.evaluate("document.querySelector('#empty .t-touch').textContent")
        self.assertIn("줄을 누르면 그 줄을,", hint)
        self.assertIn("길게 눌러 글을 고르면 그 줄들을 고르고", hint)
        page.locator("#md .ln", has_text="ax.plot(row)").tap()
        got = self.composed(page)
        self.assertEqual((got["lo"], got["hi"], got["scope"]), (6, 6, "raw"))

    def test_a_selection_made_with_the_long_press_handles_picks_its_lines_once_it_rests(self):
        """A long press makes a selection with no mouseup: a selection from `def save` into `fig.savefig`, as the handles
        leave it, is picked once it has rested (0.5 s) - lines 9-10 at the chosen-lines rung."""
        page = self.open_tx(**PHONE)
        self.assertTrue(page.evaluate("MQ_COARSE.matches"))
        page.evaluate(
            "(()=>{const ln=t=>[...document.querySelectorAll('#md .ln')].find(e=>e.textContent.includes(t)).firstChild,"
            "r=document.createRange(); r.setStart(ln('def save'),0); r.setEnd(ln('fig.savefig'),8);"
            "const s=getSelection(); s.removeAllRanges(); s.addRange(r);})()"
        )
        got = self.composed(page)
        self.assertEqual((got["lo"], got["hi"], got["scope"]), (9, 10, "raw"))


class Width(PickBase):
    """The foldable's outer screen (344 px): long lines wrap, the page never scrolls sideways."""

    TEXT = (
        PLOT
        + "x = '"
        + "a" * 300
        + "'\n"
        + "\t\tif value_with_a_long_name and another_long_name_that_goes_on and yet_another_condition_here:\n"
        + "# "
        + "한국어 산문은 띄어쓰기에서 접는다. " * 20
        + "\n"
    )

    def test_no_line_makes_the_page_scroll_sideways(self):
        """A 300-character token, a tab-indented condition and a long Korean comment: the pane does not scroll sideways,
        the column ends inside it, and every line's box ends inside the column; the tab-indented line hangs its
        continuation (--hang 8)."""
        page = self.open_tx(**OUTER)
        got = page.evaluate(
            "(()=>{const L=document.getElementById('left'),md=document.getElementById('md'),m=md.getBoundingClientRect(),"
            "ls=[...md.querySelectorAll('.ln')];"
            "return {over:L.scrollWidth-L.clientWidth,doc:document.documentElement.scrollWidth-innerWidth,right:m.right,"
            "width:L.getBoundingClientRect().right,wide:ls.filter(l=>l.scrollWidth>l.clientWidth+1).map(l=>l.dataset.line),"
            "hang:ls[11].style.getPropertyValue('--hang')};})()"
        )
        self.assertLessEqual(got["over"], 0)
        self.assertLessEqual(got["doc"], 0)
        self.assertLessEqual(got["right"], got["width"] + 1)
        self.assertEqual(got["wide"], [])
        self.assertEqual(got["hang"], "8")


class Redrawing(PickBase):
    """A change to the source on disk reaches the screen."""

    TEXT = "".join("line_%03d = %d\n" % (i, i) for i in range(1, 201))

    def test_an_edited_source_is_drawn_again_at_the_reading_line(self):
        """Scrolled to line 120, a change to line 150 on disk is drawn within a light poll and the reading line stays."""
        page = self.open_tx()
        page.evaluate("document.querySelector(\"#md [data-line='120']\").scrollIntoView({block:'start'})")
        settle(page)
        before = page.evaluate("mdReadingLine()")
        self.assertGreater(before, 100)
        self.write(self.TEXT.replace("line_150 = 150", "line_150 = 'changed'"))
        page.evaluate("pollLightOnce()")
        page.wait_for_function(
            "document.querySelector(\"#md [data-line='150']\").textContent.includes(\"'changed'\")", timeout=8000
        )
        settle(page)
        self.assertLessEqual(abs(page.evaluate("mdReadingLine()") - before), 1)

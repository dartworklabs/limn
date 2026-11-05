"""The text surface in the browser (docs/adr/0029-text-documents.md, docs/superpowers/specs/2026-11-05-text-documents.md).

A text document (kind text, here check.py) is drawn by the viewer from GET /api/source line for line, never parsed. These
tests drive the real viewer against the in-process server (BrowserBase) and check what a person sees:

- a character that would hide or reorder text shows by name in its box, its line reads in source order, a selection's text
  keeps it, a notice counts them, and the ladder's labels and the excerpt under it name them too;
- the limits: a line of 100,000 zero-width spaces gives the bounded names view, the build pauses inside that line and a
  newer draw stops it;
- line ends that are not LF or CRLF are counted in a notice above the lines;
- a suggestion that adds such a character is marked in its card's diff and warned about under the editor.

The pure rules (ladder, closing lines, the repertoire and its exceptions) are test_text_surface.py.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_text.py
"""

from limn.administration import serve_documents as startup_documents

from helpers import add_pin, ps
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

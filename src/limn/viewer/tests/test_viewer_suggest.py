"""Suggested edits in the viewer (docs/handbook/viewer.md §제안 수정, ADR-0020).

The composer's [제안 수정] switch and its editor, what a save sends and the server keeps, the 409 when the lines changed,
undo, a card's badge and line diff, and the edit card that changes or removes a suggestion.

- ``SuggestLogic`` runs the pure decisions of suggest.js under node.
- The browser classes drive the real viewer against the in-process server (helpers_browser.BrowserBase; /api/pick is
  answered from the manuscript). The manuscript's line 5 sits in a two-line paragraph (lines 4-5) inside a 94-line quote
  environment, so a pick offers the dragged line, the paragraph (its default) and an environment of more than 80 lines.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_suggest.py
"""

import json
import re
import shutil
import unittest

from limn.pins.editing.values import SUGGEST_LINES_MAX
from limn.pins.lifecycle.rules import CloseRequest
from limn.security.access import LOCAL_ACTOR

from helpers import HTML, add_pin, extract_js_fn, ps, req, run_node
from helpers_access import ALICE, actor
from helpers_authority import post_authority
from helpers_browser import MISSES_24, MISSES_44, BrowserBase, settle

HANGUL = re.compile(r"[가-힣]")
# Line 5 is the second line of the paragraph at lines 4-5; the quote environment around it runs from line 3 to 96.
TEX = (
    "\\documentclass{article}\n\\begin{document}\n\\begin{quote}\n"
    "First line of the paragraph.\nSecond line of the paragraph.\n\n"
    + "".join("Filler line %d.\n" % i for i in range(7, 96))
    + "\\end{quote}\n\\end{document}\n"
)
PARA = "First line of the paragraph.\nSecond line of the paragraph."
NEW = "The first line, shorter.\nSecond line of the paragraph."
DESK = {"viewport": {"width": 1440, "height": 900}}
PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True, "device_scale_factor": 3}
COACH_SEEN = "try{localStorage.setItem('pinPrefs',JSON.stringify({coach:{touch:1,mouse:1,sel:1}}));}catch(e){}"
# The composer's suggestion as drawn: the switch, the reason in its place, the editor and the line under it.
STATE = """() => {const q = s => document.querySelector(s), shown = e => !!e && e.getClientRects().length > 0;
  const line = q('#c-sg-note'), act = line && line.querySelector('button');
  return {switch: shown(q('#c-sg-tg')), on: q('#c-sg-tg').getAttribute('aria-checked'), why: shown(q('#c-sg-why')) ? q('#c-sg-why').textContent : null,
    editor: shown(q('#c-sg-text')), text: q('#c-sg-text').value, readOnly: q('#c-sg-text').readOnly,
    line: shown(line) ? line.querySelector('span').textContent : null, act: act ? act.textContent : null,
    cur: shown(q('#c-sg-cur')), base: SG.base, range: COMPOSE.current && [COMPOSE.current.lo, COMPOSE.current.hi]};}"""
# A card's suggestion as drawn: its badge (text, warning look), its diff rows (class, number, line) and the fold button.
CARD = """id => {const c = document.querySelector('.pin[data-id="' + id + '"]'), b = c.querySelector('.sg-badge'), f = c.querySelector('.sg-foot button');
  const shown = e => !!e && e.getClientRects().length > 0;
  return {badge: b ? b.textContent : null, warn: !!b && b.classList.contains('badge-warning'), note: c.querySelector('.note') ? c.querySelector('.note').textContent : null,
    view: shown(c.querySelector('.sg-view')),
    rows: [...c.querySelectorAll('.sg-diff .rd-line')].map(r => [r.className.replace('rd-line ', ''), r.querySelector('.rd-no').textContent, r.querySelector('.rd-code').textContent]),
    fold: f ? f.textContent : null};}"""


def lines(lo, hi):
    """Lines lo..hi of TEX joined as a suggestion's base is."""
    return "\n".join(TEX.split("\n")[lo - 1 : hi])


class SuggestLogic(unittest.TestCase):
    """The pure decisions: which selections can carry a suggestion, what a save and an edit send, the line diff and its
    fold, and the one line under the editor."""

    def setUp(self):
        """The decisions run the served functions under node."""
        if not shutil.which("node"):
            self.skipTest("node not available")

    def run_js(self, names, body):
        """The served functions names and the suggestion constants, then body; its printed JSON."""
        consts = "\n".join(
            re.search(r"^const %s=[^;]*;" % n, HTML, re.M).group(0) for n in ("SUGGEST_LINES", "SUGGEST_FOLD")
        )
        return json.loads(run_node("\n".join([consts] + [extract_js_fn(n) for n in names] + [body])))

    def test_the_server_and_the_viewer_cap_a_suggestion_at_the_same_lines(self):
        """SUGGEST_LINES is the server's SUGGEST_LINES_MAX: the switch offers what the server takes."""
        self.assertEqual(self.run_js([], "console.log(JSON.stringify(SUGGEST_LINES));"), SUGGEST_LINES_MAX)

    def test_only_a_latex_line_range_of_at_most_80_lines_can_carry_one(self):
        """A LaTeX line pick of 2 or 80 lines can; 81 lines is 'long'; a region pick, an edit card of a region or nothing
        is 'region'; a view-only PDF and a figure document say so whatever the pick (an unknown kind is LaTeX)."""
        got = self.run_js(
            ["isRegion", "isFigureKind", "suggestOff"],
            r"""const line = (lo, hi) => ({file: '/ms/main.tex', lo, hi});
            console.log(JSON.stringify([suggestOff(line(4, 5), DOC_KIND.TEX), suggestOff(line(1, 80), undefined),
              suggestOff(line(1, 81), DOC_KIND.TEX), suggestOff({kind: 'region', pdf: '/ms/r.pdf', page: 1}, DOC_KIND.TEX),
              suggestOff({region: true, lo: 1, hi: 2}, DOC_KIND.TEX), suggestOff(null, DOC_KIND.TEX),
              suggestOff(line(4, 5), DOC_KIND.PDF), suggestOff(line(4, 5), DOC_KIND.FIGURE)]));""",
        )
        self.assertEqual(got, [None, None, "long", "region", "region", "region", "pdf", "figure"])

    def test_a_save_sends_only_an_edited_text_with_its_base(self):
        """On, filled and edited: {base, text}; unedited, off, never filled or on a region: nothing; a range over 80 lines
        still sends it (the server's refusal says why); an empty text (delete the lines) is a suggestion."""
        got = self.run_js(
            ["suggestForSave"],
            r"""const d = (o) => ({on: true, text: 'new', base: 'old', ...o});
            console.log(JSON.stringify([suggestForSave(d({}), null), suggestForSave(d({text: 'old'}), null),
              suggestForSave(d({on: false}), null), suggestForSave(d({base: null}), null), suggestForSave(d({}), SUGGEST_OFF.REGION),
              suggestForSave(d({}), SUGGEST_OFF.LONG), suggestForSave(d({text: ''}), null)]));""",
        )
        self.assertEqual(
            got,
            [
                {"base": "old", "text": "new"},
                None,
                None,
                None,
                None,
                {"base": "old", "text": "new"},
                {"base": "old", "text": ""},
            ],
        )

    def test_an_edit_sends_a_change_null_to_remove_or_nothing(self):
        """The pin's own suggestion untouched sends nothing; a new text or base sends both; off, or the source's own text,
        removes what the pin had (null) and sends nothing for a pin without one; a draft not filled sends nothing."""
        got = self.run_js(
            ["suggestForEdit"],
            r"""const had = {base: 'old', text: 'new'}, d = (o) => ({on: true, text: 'new', base: 'old', had, ...o});
            const out = [suggestForEdit(d({}), null), suggestForEdit(d({text: 'newer'}), null), suggestForEdit(d({base: 'older'}), null),
              suggestForEdit(d({on: false}), null), suggestForEdit(d({text: 'old'}), null), suggestForEdit(d({had: null, on: false}), null),
              suggestForEdit(d({had: null, text: 'old'}), null), suggestForEdit(d({had: null}), null), suggestForEdit(d({had: null, base: null}), null)];
            console.log(JSON.stringify(out.map(v => v === undefined ? 'nothing' : v)));""",
        )
        self.assertEqual(
            got,
            [
                "nothing",
                {"base": "old", "text": "newer"},
                {"base": "older", "text": "new"},
                None,
                None,
                "nothing",
                "nothing",
                {"base": "old", "text": "new"},
                "nothing",
            ],
        )

    def test_the_diff_keeps_common_lines_and_numbers_both_sides(self):
        """base -> text from line 4: a changed first line is its deletion then its addition, the common second line a
        context row; deleting every line (empty text) is deletions only; a base line is numbered as in the file, an added
        line as after the change."""
        got = self.run_js(
            ["suggestLines", "suggestDiff"],
            r"""console.log(JSON.stringify([suggestDiff('a\nb', 'A\nb', 4), suggestDiff('a\nb', '', 4), suggestDiff('a', 'a\nx\ny', 10)]));""",
        )
        self.assertEqual(
            got[0], [{"k": "del", "t": "a", "n": 4}, {"k": "add", "t": "A", "n": 4}, {"k": "ctx", "t": "b", "n": 5}]
        )
        self.assertEqual(got[1], [{"k": "del", "t": "a", "n": 4}, {"k": "del", "t": "b", "n": 5}])
        self.assertEqual(
            got[2], [{"k": "ctx", "t": "a", "n": 10}, {"k": "add", "t": "x", "n": 11}, {"k": "add", "t": "y", "n": 12}]
        )

    def test_a_diff_of_more_than_five_rows_folds_to_its_ends(self):
        """Five rows stay; six fold to the first two, '… 2' and the last two; an open diff keeps them all."""
        got = self.run_js(
            ["suggestFold"],
            r"""const rows = n => Array.from({length: n}, (_, i) => ({k: 'add', t: 'l' + i, n: i}));
            const ks = rs => rs.map(r => r.k === 'fold' ? 'fold' + r.n : r.t);
            console.log(JSON.stringify([ks(suggestFold(rows(5), false)), ks(suggestFold(rows(6), false)), suggestFold(rows(6), true).length]));""",
        )
        self.assertEqual(got, [["l0", "l1", "l2", "l3", "l4"], ["l0", "l1", "fold2", "l4", "l5"], 6])

    def test_the_line_under_the_editor_says_the_first_thing_that_matters(self):
        """Off: nothing (the edit card of a pin with one: that saving removes it); a long range; a read under way; a failed
        read with its retry; a 409's current lines; a moved range of an edited text; a changed pin's base on the edit card;
        the source's own text; else nothing."""
        got = self.run_js(
            ["suggestKey", "suggestMoved", "suggestLine"],
            r"""const o = {file: 'f', lo: 4, hi: 5}, d = x => ({on: true, text: 'new', base: 'old', file: 'f', lo: 4, hi: 5, had: null, current: null, reading: '', fail: null, ...x});
            const say = l => l ? [l.msg, l.act && l.act.act] : null;
            console.log(JSON.stringify([say(suggestLine(d({on: false}), o, null, false)), say(suggestLine(d({on: false, had: {base: 'old', text: 'new'}}), o, null, true)),
              say(suggestLine(d({}), o, SUGGEST_OFF.LONG, false)), say(suggestLine(d({base: null, reading: 'f:4-5'}), o, null, false)),
              say(suggestLine(d({fail: {key: 'f:4-5', fill: true, why: 'x'}}), o, null, false)),
              say(suggestLine(d({current: {text: 'c', file: 'f', lo: 4, hi: 5}}), o, null, false)), say(suggestLine(d({lo: 3}), o, null, false)),
              say(suggestLine(d({had: {base: 'old', text: 'new'}}), o, null, true, SUGGEST_STATE.CHANGED)),
              say(suggestLine(d({text: 'old'}), o, null, false)), say(suggestLine(d({}), o, null, false))]));""",
        )
        self.assertEqual(
            got,
            [
                None,
                ["저장하면 이 핀의 제안 수정을 지웁니다", None],
                ["범위가 80줄을 넘어 이대로는 저장되지 않습니다 — 범위를 줄이거나 제안 수정을 끄세요", None],
                ["원문 읽는 중…", None],
                ["원문을 읽지 못했습니다 — x", "sg-reload"],
                ["그사이 원문이 바뀌었습니다 — 아래는 지금 원문과 이 글의 차이입니다", "sg-rebase"],
                ["범위가 바뀌었습니다", "sg-reload"],
                ["그사이 원문이 바뀌었습니다", "sg-rebase"],
                ["원문 그대로입니다 — 고친 글만 제안 수정으로 보냅니다", None],
                None,
            ],
        )


class SuggestBase(BrowserBase):
    """BrowserBase on TEX as Alice (a person who may pin), first-visit hints seen; picks and reads of the stored pins."""

    WHO = ALICE

    def setUp(self):
        """BrowserBase's fresh instance with TEX as its manuscript."""
        super().setUp()
        self.main.write_text(TEX, encoding="utf-8")

    def view(self, device=DESK, n_open=0, lang="ko"):
        """The viewer on device in lang, booted with at least n_open open pins."""
        return self.open(n_open, lang=lang, init=COACH_SEEN, **device)

    def compose(self, page, pointer="mouse"):
        """A pick through the real path (its default rung: the paragraph, lines 4-5); waits for the composer."""
        page.evaluate("p=>{LAST_PTR=p; pick({page:1,x0:10,y0:10,x1:200,y1:60});}", pointer)
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking", timeout=8000)
        settle(page)

    def switch_on(self, page, sel="#c-sg-tg"):
        """Press the [제안 수정] switch and wait for its editor to be filled."""
        page.click(sel)
        settle(page)

    def records(self):
        """Every pin the server answers (GET /api/pins?all=1 as the loopback agent)."""
        code, _, out = self.talk(req("GET", "/api/pins?all=1"))
        self.assertEqual(code, 200, out)
        return json.loads(out)

    def sent(self, page):
        """Collects the JSON bodies the page POSTs to /api/pin and to a pin's /edit, in order."""
        out = []
        page.on(
            "request",
            lambda r: (
                out.append(json.loads(r.post_data))
                if r.method == "POST" and re.search(r"/api/pin$|/api/pins/\d+/edit$", r.url)
                else None
            ),
        )
        return out

    def add(self, note="", suggest=None, lo=4, hi=5):
        """An open pin on lines lo-hi by Alice, with suggest when given; its id."""
        d = {"file": str(self.main), "lo": lo, "hi": hi, "page": 1, "note": note, "frac": [0.1, 0.1, 0.3, 0.05]}
        if suggest:
            d["suggest"] = suggest
        return add_pin(d, actor(ALICE)).core.id


class SuggestComposer(SuggestBase):
    """The composer: the switch where a suggestion can go and a reason where it cannot, the editor filled with the range's
    exact lines, following the range until edited, the reload line, undo, and [덧붙이기] waiting on a written suggestion."""

    def test_the_switch_stands_at_the_kind_rows_end_off(self):
        """A LaTeX line pick: the switch, off, ends the kind row on the kind control's line; no editor yet."""
        page = self.view()
        self.compose(page)
        s = page.evaluate(STATE)
        self.assertEqual((s["switch"], s["on"], s["why"], s["editor"]), (True, "false", None, False))
        g = page.evaluate(
            "(()=>{const R=s=>document.querySelector(s).getBoundingClientRect(),r=R('#c-kind-row'),k=R('#c-kind'),t=R('#c-sg-tg');"
            "return [r.right-t.right, (t.top+t.bottom)/2-(k.top+k.bottom)/2];})()"
        )
        self.assertEqual(g[0], 0)
        self.assertLessEqual(abs(g[1]), 0.5)

    def test_a_selection_that_cannot_carry_one_shows_why_in_the_switchs_place(self):
        """The environment rung (94 lines), an area pick, a view-only PDF and a figure document: no switch, the reason."""
        page = self.view()
        self.compose(page)
        page.click('#c-levels [data-level="env"]')
        settle(page)
        self.assertEqual(page.evaluate(STATE)["range"], [3, 96])
        s = page.evaluate(STATE)
        self.assertEqual((s["switch"], s["why"]), (False, "제안 수정은 80줄까지"))
        for kind, why in (("pdf", "보기 전용 PDF에는 제안 수정 없음"), ("figure", "그림 문서에는 제안 수정 없음")):
            with self.subTest(kind=kind):
                page.evaluate("k=>{META.kind=k; renderComposer();}", kind)
                s = page.evaluate(STATE)
                self.assertEqual((s["switch"], s["why"]), (False, why))
        page.evaluate("()=>{META.kind=DOC_KIND.TEX;}")
        self.PICK = {"kind": "region", "view_only": True, "lo": None, "hi": None, "file": None, "quote": "Area"}
        self.compose(page)
        s = page.evaluate(STATE)
        self.assertEqual((s["switch"], s["why"]), (False, "영역에는 제안 수정 없음"))

    def test_switching_on_fills_the_editor_with_the_ranges_exact_lines(self):
        """The editor opens holding lines 4-5 as the file has them, editable, its line saying an unedited text is not sent;
        switching off closes it."""
        page = self.view()
        self.compose(page)
        self.switch_on(page)
        s = page.evaluate(STATE)
        self.assertEqual((s["on"], s["editor"], s["text"], s["base"], s["readOnly"]), ("true", True, PARA, PARA, False))
        self.assertEqual(s["line"], "원문 그대로입니다 — 고친 글만 제안 수정으로 보냅니다")
        page.click("#c-sg-tg")
        self.assertEqual(page.evaluate(STATE)["editor"], False)

    def test_an_unedited_editor_follows_the_range(self):
        """Widened to line 6 in the excerpt, then the dragged-line rung: the editor holds each range's lines."""
        page = self.view()
        self.compose(page)
        self.switch_on(page)
        page.click('#c-xp [data-act="xp-to"][data-line="6"]')
        settle(page)
        s = page.evaluate(STATE)
        self.assertEqual(
            (s["range"], s["text"], s["base"], s["line"]),
            ([4, 6], lines(4, 6), lines(4, 6), "원문 그대로입니다 — 고친 글만 제안 수정으로 보냅니다"),
        )
        page.click('#c-levels [data-level="raw"]')
        settle(page)
        self.assertEqual(page.evaluate(STATE)["text"], lines(5, 5))

    def test_an_edited_editor_keeps_its_text_and_offers_to_read_the_new_range(self):
        """An edited text stays when the range changes and one line offers [원문 다시 불러오기], which fills the editor with
        the new range's lines."""
        page = self.view()
        self.compose(page)
        self.switch_on(page)
        page.fill("#c-sg-text", NEW)
        page.click('#c-xp [data-act="xp-to"][data-line="6"]')
        settle(page)
        s = page.evaluate(STATE)
        self.assertEqual(
            (s["text"], s["base"], s["line"], s["act"]), (NEW, PARA, "범위가 바뀌었습니다", "원문 다시 불러오기")
        )
        page.click("#c-sg-note button")
        settle(page)
        s = page.evaluate(STATE)
        self.assertEqual(
            (s["text"], s["base"], s["line"]),
            (lines(4, 6), lines(4, 6), "원문 그대로입니다 — 고친 글만 제안 수정으로 보냅니다"),
        )

    def test_typing_leaves_the_line_a_screen_reader_reads_alone(self):
        """The line under the editor is a polite live region: typing that keeps its message does not write it again (a
        screen reader would read it at every key), and a new message replaces it."""
        page = self.view()
        self.compose(page)
        self.switch_on(page)
        page.fill("#c-sg-text", NEW)
        page.click('#c-xp [data-act="xp-to"][data-line="6"]')
        settle(page)
        page.evaluate("document.querySelector('#c-sg-note span').__mark = 1")
        page.type("#c-sg-text", " more")
        settle(page)
        self.assertEqual(page.evaluate("document.querySelector('#c-sg-note span').__mark"), 1)
        page.click("#c-sg-note button")
        settle(page)
        self.assertIsNone(page.evaluate("document.querySelector('#c-sg-note span').__mark"))

    def test_discarding_offers_undo_that_brings_the_suggestion_back(self):
        """With an empty memo but an edited suggestion, Esc discards the selection with [되돌리기], which brings back the
        switch, the text and its base."""
        page = self.view()
        self.compose(page)
        self.switch_on(page)
        page.fill("#c-sg-text", NEW)
        page.keyboard.press("Escape")
        settle(page)
        self.assertTrue(page.evaluate("document.querySelector('#composer').hidden"))
        self.assertEqual(page.evaluate("[SG.on, SG.text]"), [False, ""])
        page.click('#status [data-act="notice-act"]')
        settle(page)
        s = page.evaluate(STATE)
        self.assertEqual((s["on"], s["editor"], s["text"], s["base"]), ("true", True, NEW, PARA))

    def test_append_waits_while_an_edited_suggestion_is_on(self):
        """Over an open pin on the same lines, [덧붙이기] is off while an edited suggestion is on, and back once it is off."""
        self.add(note="earlier")
        page = self.view(n_open=1)
        self.compose(page)
        appendable = "!document.querySelector('[data-act=\"overlap-append\"]').disabled"
        self.assertTrue(page.evaluate(appendable))
        self.switch_on(page)
        page.fill("#c-sg-text", NEW)
        settle(page)
        self.assertFalse(page.evaluate(appendable))
        page.click("#c-sg-tg")
        settle(page)
        self.assertTrue(page.evaluate(appendable))

    def test_the_english_screen_says_it_all_in_english(self):
        """In English the switch, the editor's name and line, the reason in the switch's place and a card's badge and fold
        carry no Hangul (the diff and the editor hold the manuscript's text, which is never translated)."""
        self.add(note="", suggest={"base": PARA, "text": "\n".join("New %d" % i for i in range(9))})
        page = self.view(n_open=1, lang="en")
        self.compose(page)
        self.switch_on(page)
        got = page.evaluate(
            """() => {const q = s => document.querySelector(s), c = q('.pin[data-id="1"]');
              return [q('#c-sg-tg').innerText, q('#c-sg-tg').dataset.tip, q('#c-sg-text').getAttribute('aria-label'), q('#c-sg-text').placeholder,
                q('#c-sg-note').innerText, c.querySelector('.sg-badge').innerText, c.querySelector('.sg-foot').innerText, c.querySelector('.note').innerText];}"""
        )
        page.click(
            '#c-levels [data-level="env"]'
        )  # on and over 80 lines: the switch stays, so it can go off; its line says why
        settle(page)
        got.append(page.inner_text("#c-sg-note"))
        page.click("#c-sg-tg")
        settle(page)
        got.append(page.inner_text("#c-sg-why"))
        self.assertEqual([t for t in got if HANGUL.search(t or "")], [], got)
        self.assertEqual((got[0], got[-1]), ("Suggested edit", "Suggested edits: 80 lines at most"))


class SuggestSave(SuggestBase):
    """What [핀 저장] sends and the server keeps, and the 409 when the lines changed in between."""

    def test_a_save_sends_the_edited_text_with_the_base_it_was_filled_from(self):
        """Memo and suggestion: the request carries suggest {base: the filled lines, text}; the stored pin has both and
        reads ready."""
        page = self.view()
        sent = self.sent(page)
        self.compose(page)
        page.fill("#note", "짧게")
        self.switch_on(page)
        page.fill("#c-sg-text", NEW)
        page.click("#btn-save")
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        self.assertEqual(sent[-1]["suggest"], {"base": PARA, "text": NEW})
        (p,) = self.records()
        self.assertEqual((p["note"], p["suggest"], p["suggest_state"]), ("짧게", {"base": PARA, "text": NEW}, "ready"))

    def test_a_suggestion_alone_is_saved_without_a_memo(self):
        """An empty memo with an edited suggestion saves a pin whose note is empty."""
        page = self.view()
        self.compose(page)
        self.switch_on(page)
        page.fill("#c-sg-text", NEW)
        page.keyboard.press("Control+Enter")
        page.wait_for_function("OPEN_ALL.length===1")
        (p,) = self.records()
        self.assertEqual((p["note"], p["suggest"]["text"]), ("", NEW))

    def test_an_unedited_or_switched_off_editor_sends_no_suggestion(self):
        """On with the source's own text, or off with an edited text: the request has no suggest and the pin none."""
        page = self.view()
        sent = self.sent(page)
        for edit, off in ((False, False), (True, True)):
            with self.subTest(edit=edit, off=off):
                self.compose(page)
                page.fill("#note", "메모")
                if not page.evaluate("SG.on"):
                    self.switch_on(page)
                if edit:
                    page.fill("#c-sg-text", NEW)
                if off:
                    page.click("#c-sg-tg")
                n = page.evaluate("OPEN_ALL.length")
                page.click("#btn-save")
                page.wait_for_function("n=>OPEN_ALL.length===n+1", arg=n)
                settle(page)
                self.assertNotIn("suggest", sent[-1])
        self.assertEqual([p.get("suggest") for p in self.records()], [None, None])

    def test_a_409_keeps_the_draft_shows_the_current_lines_and_offers_to_rebase(self):
        """Line 5 changes after the fill: the save stores nothing, the banner says why with [지금 원문으로 맞추기] and [핀 저장]
        reads [다시 저장], the editor keeps the text and shows the current lines against it; the action takes them as the
        base and the next save stores the suggestion on them."""
        page = self.view()
        self.compose(page)
        self.switch_on(page)
        page.fill("#c-sg-text", NEW)
        self.main.write_text(TEX.replace("Second line of the paragraph.", "Second line, changed."), encoding="utf-8")
        page.click("#btn-save")
        settle(page)
        self.assertEqual(self.records(), [])
        banner = page.evaluate(
            "(()=>{const b=document.querySelector('#composer ~ * .nt-banner, .nt-banner');return b?b.innerText:null;})()"
        )
        self.assertIn("그사이 그 줄들의 원문이 바뀌었습니다", banner)
        self.assertIn("지금 원문으로 맞추기", banner)
        self.assertIn("다시 저장", page.inner_text("#btn-save"))
        s = page.evaluate(STATE)
        self.assertEqual((s["text"], s["base"], s["cur"]), (NEW, PARA, True))
        self.assertIn("Second line, changed.", page.inner_text("#c-sg-cur"))
        page.click('.nt-banner [data-act="notice-act"]')
        settle(page)
        self.assertEqual(page.evaluate("SG.base"), "First line of the paragraph.\nSecond line, changed.")
        page.click("#btn-save")
        page.wait_for_function("OPEN_ALL.length===1")
        (p,) = self.records()
        self.assertEqual(p["suggest"], {"base": "First line of the paragraph.\nSecond line, changed.", "text": NEW})


class SuggestCard(SuggestBase):
    """A card shows its suggestion: the badge with its state, the line diff in the source-diff look, folded past five rows."""

    def test_a_card_shows_the_badge_and_the_line_diff(self):
        """A ready suggestion: the plain badge and the rows -first line (4), +new first line (4), common second line (5)."""
        self.add(note="짧게", suggest={"base": PARA, "text": NEW})
        page = self.view(n_open=1)
        c = page.evaluate(CARD, 1)
        self.assertEqual((c["badge"], c["warn"], c["fold"]), ("제안 수정", False, None))
        self.assertEqual(
            c["rows"],
            [
                ["rd-del", "4", "-First line of the paragraph."],
                ["rd-add", "4", "+The first line, shorter."],
                ["rd-context", "5", " Second line of the paragraph."],
            ],
        )

    def test_a_changed_or_unknown_suggestion_says_why_not_to_apply_it(self):
        """Line 5 edited: '제안 수정 · 원문 바뀜' as a warning; both lines gone (the pin loses its place): '확인 불가'; a pin
        sent to review: the plain badge, its diff still shown."""
        pid = self.add(note="짧게", suggest={"base": PARA, "text": NEW})
        self.main.write_text(TEX.replace("Second line of the paragraph.", "Second line, edited."), encoding="utf-8")
        page = self.view(n_open=1)
        self.assertEqual(page.evaluate(CARD, pid)["badge"], "제안 수정 · 원문 바뀜")
        self.assertTrue(page.evaluate(CARD, pid)["warn"])
        self.main.write_text(TEX.replace(PARA + "\n", "Something else entirely here.\nAnd more.\n"), encoding="utf-8")
        page.evaluate("loadPins()")
        settle(page)
        self.assertEqual(page.evaluate(CARD, pid)["badge"], "제안 수정 · 확인 불가")
        ps.APP.pin_lifecycle.close_pin(
            pid,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid),
            CloseRequest(reply="고침"),
        )
        page.evaluate("loadPins()")
        settle(page)
        c = page.evaluate(CARD, pid)
        self.assertEqual((c["badge"], c["warn"], len(c["rows"])), ("제안 수정", False, 3))

    def test_a_long_diff_folds_past_five_rows_and_unfolds(self):
        """Two lines replaced by nine: the first two and last two rows round '… 7줄', [제안 펼치기 · 11줄] opens all eleven,
        and the card stays open across a redraw; a suggestion without a memo reads '(제안 문안만)'."""
        self.add(note="", suggest={"base": PARA, "text": "\n".join("New %d" % i for i in range(9))})
        page = self.view(n_open=1)
        c = page.evaluate(CARD, 1)
        self.assertEqual(
            [r[2] for r in c["rows"]],
            ["-First line of the paragraph.", "-Second line of the paragraph.", "… 7줄", "+New 7", "+New 8"],
        )
        self.assertEqual((c["fold"], c["note"]), ("제안 펼치기 · 11줄", "(제안 문안만)"))
        page.click('.pin[data-id="1"] .sg-foot button')
        page.evaluate("drawPins()")
        c = page.evaluate(CARD, 1)
        self.assertEqual((len(c["rows"]), c["fold"]), (11, "제안 접기"))

    def test_a_folded_compact_card_hides_the_diff(self):
        """On a phone a folded card shows neither the diff nor the badge; opened, both."""
        self.add(note="짧게", suggest={"base": PARA, "text": NEW})
        page = self.view(PHONE, n_open=1)
        page.evaluate("setSide(true)")
        settle(page)
        self.assertFalse(page.evaluate(CARD, 1)["view"])
        page.click('.pin[data-id="1"] .b-fold')
        settle(page)
        self.assertTrue(page.evaluate(CARD, 1)["view"])


class SuggestEditCard(SuggestBase):
    """The edit card edits a suggestion, removes it by switching it off, adds one to a pin without, and shows a closed
    pin's read-only."""

    EDIT = """() => {const e = document.querySelector('.edit'), q = s => e.querySelector(s), shown = x => !!x && x.getClientRects().length > 0;
      const line = q('.e-sg .sg-note');
      return {switch: shown(q('.e-sg-row .sg-tg')), on: q('.e-sg-row .sg-tg').getAttribute('aria-checked'), editor: shown(q('.e-sg-text')),
        text: q('.e-sg-text').value, line: shown(line) ? line.querySelector('span').textContent : null, ro: shown(q('.e-sg-ro')),
        roRows: [...q('.e-sg-ro').querySelectorAll('.rd-line')].length};}"""

    def edit(self, page, pid):
        """Open pin pid's edit card and wait for its range to be read."""
        page.evaluate("id=>openEdit(id)", pid)
        page.wait_for_function("EDITOR.current&&EDITOR.current.levels.length>0")
        settle(page)

    def test_the_card_opens_on_the_suggestion_and_saves_a_new_text(self):
        """Switch on with the pin's text; a changed text is sent with the same base and stored."""
        pid = self.add(note="짧게", suggest={"base": PARA, "text": NEW})
        page = self.view(n_open=1)
        sent = self.sent(page)
        self.edit(page, pid)
        e = page.evaluate(self.EDIT)
        self.assertEqual((e["switch"], e["on"], e["text"]), (True, "true", NEW))
        page.fill(".e-sg-text", "Only one line now.")
        page.click(".edit .b-esave")
        page.wait_for_function("!EDITOR.current")
        settle(page)
        self.assertEqual(sent[-1]["suggest"], {"base": PARA, "text": "Only one line now."})
        self.assertEqual(self.records()[0]["suggest"], {"base": PARA, "text": "Only one line now."})

    def test_switching_off_and_saving_removes_the_suggestion(self):
        """Off: the line says saving removes it; the edit sends suggest null and the pin has none."""
        pid = self.add(note="짧게", suggest={"base": PARA, "text": NEW})
        page = self.view(n_open=1)
        sent = self.sent(page)
        self.edit(page, pid)
        page.click(".e-sg-row .sg-tg")
        settle(page)
        self.assertEqual(page.evaluate(self.EDIT)["line"], "저장하면 이 핀의 제안 수정을 지웁니다")
        page.click(".edit .b-esave")
        page.wait_for_function("!EDITOR.current")
        settle(page)
        self.assertIsNone(sent[-1]["suggest"])
        self.assertNotIn("suggest", self.records()[0])

    def test_a_pin_without_one_gets_a_suggestion_from_its_lines(self):
        """Switched on, the editor holds the pin's lines; an edited text is stored with them as its base."""
        pid = self.add(note="짧게")
        page = self.view(n_open=1)
        self.edit(page, pid)
        page.click(".e-sg-row .sg-tg")
        settle(page)
        self.assertEqual(page.evaluate(self.EDIT)["text"], PARA)
        page.fill(".e-sg-text", NEW)
        page.keyboard.press("Control+Enter")
        page.wait_for_function("!EDITOR.current")
        settle(page)
        self.assertEqual(self.records()[0]["suggest"], {"base": PARA, "text": NEW})

    def test_a_closed_pin_shows_the_suggestion_read_only(self):
        """A pin closed while its card is open (a dirty note keeps the card): no switch, no editor, the diff read-only."""
        pid = self.add(note="짧게", suggest={"base": PARA, "text": NEW})
        page = self.view(n_open=1)
        self.edit(page, pid)
        page.fill(".e-note", "짧게, 고침")
        ps.APP.pin_lifecycle.close_pin(
            pid,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid),
            CloseRequest(reply="고침"),
        )
        page.evaluate("loadPins()")
        settle(page)
        e = page.evaluate(self.EDIT)
        self.assertEqual((e["switch"], e["editor"], e["ro"], e["roRows"]), (False, False, True, 3))

    def test_a_409_keeps_the_card_and_shows_the_current_lines(self):
        """The lines changed before an edit's save: the card stays with its text, the banner says why, the current lines
        show against the text."""
        pid = self.add(note="짧게", suggest={"base": PARA, "text": NEW})
        page = self.view(n_open=1)
        self.edit(page, pid)
        page.fill(".e-sg-text", "Only one line now.")
        self.main.write_text(TEX.replace("Second line of the paragraph.", "Second line, changed."), encoding="utf-8")
        page.click(".edit .b-esave")
        settle(page)
        self.assertTrue(page.evaluate("!!EDITOR.current"))
        self.assertEqual(page.evaluate(self.EDIT)["text"], "Only one line now.")
        self.assertIn("그사이 그 줄들의 원문이 바뀌었습니다", page.inner_text(".nt-banner"))
        self.assertIn("Second line, changed.", page.inner_text(".edit .sg-cur"))
        self.assertEqual(self.records()[0]["suggest"], {"base": PARA, "text": NEW})


# The kind row and the editor as drawn: the row and the switch's boxes, the switch label's box (trimmed to its cap height),
# the kind track, the composer blocks' gaps, the editor's font size and whether its text overflows sideways, and the
# composer's bordered controls.
GEOMETRY = """() => {const q = s => document.querySelector(s), R = e => e.getBoundingClientRect(), r1 = v => Math.round(v * 10) / 10;
  const row = R(q('#c-kind-row')), tg = R(q('#c-sg-tg')), lbl = R(q('#c-sg-tg .lbl')), sw = R(q('#c-sg-tg .sg-sw')), k = R(q('#c-kind')), ta = q('#c-sg-text');
  const blocks = [...q('#composer').children].flatMap(e => getComputedStyle(e).display === 'contents' ? [...e.children] : [e])
    .filter(e => e.getClientRects().length && getComputedStyle(e).position !== 'absolute').map(e => [e.id || e.className, R(e).top, R(e).bottom]).sort((a, b) => a[1] - b[1]);
  const borders = [...document.querySelectorAll('#composer button,#composer input,#composer textarea,#c-actions button')].filter(e => e.getClientRects().length)
    .filter(e => {const c = getComputedStyle(e); return parseFloat(c.borderTopWidth) > 0 && c.borderTopColor !== 'rgba(0, 0, 0, 0)' && c.borderTopColor !== c.backgroundColor;}).map(e => e.id || e.className);
  return {rowH: r1(row.height), oneRow: Math.abs((tg.top + tg.bottom) / 2 - (k.top + k.bottom) / 2) <= 0.5, tgH: r1(tg.height), rowEnd: r1(row.right - tg.right),
    label: r1((lbl.top + lbl.bottom) / 2 - (tg.top + tg.bottom) / 2), track: r1((sw.top + sw.bottom) / 2 - (tg.top + tg.bottom) / 2),
    gaps: blocks.slice(1).map((b, i) => Math.round(b[1] - blocks[i][2])), order: blocks.map(b => b[0]),
    font: parseFloat(getComputedStyle(ta).fontSize), sideways: ta.scrollWidth > ta.clientWidth, borders};}"""
BANDS = {
    "phone 390x844": PHONE,
    "phone 320x720": {"viewport": {"width": 320, "height": 720}, "is_mobile": True, "has_touch": True},
    "tablet 768x1024": {"viewport": {"width": 768, "height": 1024}, "is_mobile": True, "has_touch": True},
    "tablet 1024x768": {"viewport": {"width": 1024, "height": 768}, "is_mobile": True, "has_touch": True},
    "fold outer 344x882": {"viewport": {"width": 344, "height": 882}, "is_mobile": True, "has_touch": True},
    "fold inner 673x841": {"viewport": {"width": 673, "height": 841}, "is_mobile": True, "has_touch": True},
    "fold inner 841x673": {"viewport": {"width": 841, "height": 673}, "is_mobile": True, "has_touch": True},
    "desktop 1440x900": DESK,
}


class SuggestGeometry(SuggestBase):
    """The kind row and the editor on every device group (docs/handbook/viewer.md §컴포넌트 규격): the switch on the kind
    control's line at the row's end, drawn at 28px in the 36px row, its label and track on the row's centre, answering 44px
    on touch and 24px with a mouse; with the editor open the composer's blocks stay one 8px step apart, the editor's text is
    16px on touch (12px with a mouse) and wraps, and only the text fields draw a border."""

    def test_the_lines_action_answers_44px_on_touch_and_24px_with_a_mouse(self):
        """[원문 다시 불러오기] under an edited editor whose range moved: 44px on a phone, 24px at the mouse desktop."""
        for name in ("phone 390x844", "desktop 1440x900"):
            with self.subTest(band=name):
                device = BANDS[name]
                touch = bool(device.get("has_touch"))
                page = self.view(device)
                self.compose(page, "touch" if touch else "mouse")
                self.switch_on(page)
                page.fill("#c-sg-text", NEW)
                page.click('#c-xp [data-act="xp-to"][data-line="6"]')
                settle(page)
                page.evaluate("document.querySelector('#c-sg-note').scrollIntoView({block:'center'})")
                settle(page)
                self.assertEqual(page.evaluate(MISSES_44 if touch else MISSES_24, "#c-sg-note button"), [])

    def test_the_kind_row_and_the_editor_keep_the_component_rules_on_every_band(self):
        """Each band of BANDS in Korean, the editor open on an edited text."""
        for name, device in BANDS.items():
            with self.subTest(band=name):
                page = self.view(device)
                touch = bool(device.get("has_touch"))
                self.compose(page, "touch" if touch else "mouse")
                self.switch_on(page)
                page.fill("#c-sg-text", NEW + " " + "word " * 40)
                settle(page)
                g = page.evaluate(GEOMETRY)
                self.assertTrue(g["oneRow"], g)
                self.assertEqual((g["rowH"], g["tgH"], g["rowEnd"]), (36, 28, 0), g)
                self.assertLessEqual(abs(g["label"]), 0.5, g)
                self.assertLessEqual(abs(g["track"]), 0.5, g)
                self.assertEqual(set(g["gaps"]), {8}, g)
                self.assertEqual(g["order"][g["order"].index("c-kind-row") + 1], "c-sg", g)
                self.assertEqual((g["font"], g["sideways"]), (16 if touch else 12, False), g)
                self.assertEqual(g["borders"], ["note", "c-sg-text"], g)
                misses = page.evaluate(MISSES_44 if touch else MISSES_24, "#c-sg-tg")
                self.assertEqual(misses, [], g)

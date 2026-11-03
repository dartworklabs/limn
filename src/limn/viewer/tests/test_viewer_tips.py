"""Explanations (data-tip) for the keyboard and screen readers (docs/handbook/viewer.md §설명과 접근성).

- ``TipDescriptionLogic`` runs tipDescText under node: what an explanation adds to a control's name.
- ``TipDescriptions`` drives the real viewer and reads Chrome's accessibility tree, which is what a screen reader is
  given: a focusable control's explanation is its description, without its name again, in the screen's language, and
  it follows the explanation when that changes.
- ``TipKeyboard`` holds the WAI-ARIA tooltip pattern: the keyboard's focus shows the box on every device, a tablet
  without hover too, Esc and leaving the control hide it - in a sheet the box before the sheet - and Tab's own scroll does
  not take it.
- ``TipReadAlong`` holds a badge's explanation, read with the card: the [제안 수정] badge says what it means to a screen
  reader, in its words' language, with nothing changed on screen or in the Tab order, and the words are neither copied
  with a selection nor found by the browser's find. A [제안 수정] warning badge reads only its words: its card's visible
  line says that the agent will not apply it, and is read with the card.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_tips.py
"""

import json
import re
import shutil
import unittest

from helpers import add_pin, extract_js_fn, run_node
from helpers_access import ALICE, actor
from helpers_browser import BrowserBase, settle

HANGUL = re.compile(r"[가-힣]")
DESK = {"viewport": {"width": 1440, "height": 900}}
TABLET = {"viewport": {"width": 768, "height": 1024}, "is_mobile": True, "has_touch": True, "device_scale_factor": 2}
COACH_SEEN = "try{localStorage.setItem('pinPrefs',JSON.stringify({coach:{touch:1,mouse:1,sel:1}}));}catch(e){}"
# The box as shown: hidden or not, its text, the focused control and that control's explanation.
BOX = """() => {const t = document.getElementById('tip'), f = document.activeElement;
  return {shown: !t.hidden, text: t.textContent, focus: f && (f.id || f.className), tip: f && f.dataset ? f.dataset.tip : null};}"""


def ax(page, selector):
    """Chrome's accessibility node for the first element matching selector: (role, name, description) as the browser
    gives them to a screen reader (CDP Accessibility.getPartialAXTree)."""
    cdp = page.context.new_cdp_session(page)
    try:
        found = cdp.send("Runtime.evaluate", {"expression": "document.querySelector(%s)" % json.dumps(selector)})
        oid = found["result"]["objectId"]
        node = cdp.send("Accessibility.getPartialAXTree", {"objectId": oid, "fetchRelatives": False})["nodes"][0]
    finally:
        cdp.detach()
    return tuple((node.get(k) or {}).get("value") for k in ("role", "name", "description"))


def ax_words(page, selector):
    """The words Chrome gives a screen reader for the element matching selector and everything in it, its static texts in
    reading order joined (CDP Accessibility.getPartialAXTree, then the children of each node)."""
    cdp = page.context.new_cdp_session(page)
    out = []
    try:
        cdp.send("Accessibility.enable")
        found = cdp.send("Runtime.evaluate", {"expression": "document.querySelector(%s)" % json.dumps(selector)})
        nodes = cdp.send(
            "Accessibility.getPartialAXTree", {"objectId": found["result"]["objectId"], "fetchRelatives": False}
        )

        seen = set()

        def walk(node):  # an ignored node's children are also its parent's: each is read once
            if node["nodeId"] in seen:
                return
            seen.add(node["nodeId"])
            if (node.get("role") or {}).get("value") == "StaticText" and not node.get("ignored"):
                out.append(node["name"]["value"])
            for child in cdp.send("Accessibility.getChildAXNodes", {"id": node["nodeId"]})["nodes"]:
                walk(child)

        walk(nodes["nodes"][0])
    finally:
        cdp.detach()
    return "".join(out)


class TipDescriptionLogic(unittest.TestCase):
    """What an explanation adds to a name: nothing when it is the name, the rest when it starts with the name and a
    separator, all of it otherwise."""

    def setUp(self):
        """The decision runs the served function under node."""
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_a_description_says_only_what_the_name_does_not(self):
        """The name again is no description; '폭 맞춤: …', '#3 · …' and 'X — …' give what follows the separator; a tip
        that only begins with the name's letters ('지금 빌드의 그림…' for '지금 빌드') is a sentence and stays whole; spaces
        and line breaks collapse; no tip, no description. The name's words may stand apart by a colon in the tip ('담당:
        Bob Park' for '담당 Bob Park'), and a name with regular-expression characters is matched as written."""
        got = json.loads(
            run_node(
                extract_js_fn("tipDescText")
                + r"""
            console.log(JSON.stringify([tipDescText('상태: 열림', '상태: 열림'), tipDescText('폭 맞춤: PDF 쪽 폭을 맞춥니다', '폭 맞춤'),
              tipDescText('#3 · 메모 첫 줄', '#3'), tipDescText('Fit width — fits the page', ' Fit width '),
              tipDescText('지금 빌드의 그림을 보입니다', '지금 빌드'), tipDescText('바꿀 글을\n  직접 씁니다', '제안 수정'),
              tipDescText('', '완료'), tipDescText('설명', ''),
              tipDescText('담당: Bob Park — 에이전트는 이 핀을 건너뜁니다', '담당 Bob Park'), tipDescText('담당: 나', '담당 나'),
              tipDescText('a.b (x)? · 설명', 'a.b (x)?')]));"""
            )
        )
        self.assertEqual(
            got,
            [
                "",
                "PDF 쪽 폭을 맞춥니다",
                "메모 첫 줄",
                "fits the page",
                "지금 빌드의 그림을 보입니다",
                "바꿀 글을 직접 씁니다",
                "",
                "설명",
                "에이전트는 이 핀을 건너뜁니다",
                "",
                "설명",
            ],
        )


class TipBase(BrowserBase):
    """BrowserBase as Alice with the first-visit hints seen."""

    def view(self, device=DESK, n_open=0, lang="ko"):
        """The viewer on device in lang, booted with at least n_open open pins."""
        return self.open(n_open, lang=lang, init=COACH_SEEN, **device)

    def compose(self, page, pointer="mouse"):
        """A pick through the real path, made with pointer; waits for the composer."""
        page.evaluate("p=>{LAST_PTR=p; pick({page:1,x0:10,y0:10,x1:200,y1:60});}", pointer)
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking", timeout=8000)
        settle(page)


class TipDescriptions(TipBase):
    """A focusable control's explanation is its accessible description - the composer's [제안 수정] switch had only its
    name ('switch "제안 수정"') - without repeating the name, in English on the English screen, and in step with it."""

    def test_the_suggest_switch_is_described_by_its_explanation(self):
        """The switch keeps its role and name, and its description is the whole explanation the box shows."""
        page = self.view()
        self.compose(page)
        tip = page.get_attribute("#c-sg-tg", "data-tip")
        self.assertEqual(ax(page, "#c-sg-tg"), ("switch", "제안 수정", tip))

    def test_a_control_whose_explanation_starts_with_its_name_is_described_by_the_rest(self):
        """[폭 맞춤] (named by aria-label) is described by what its tip says after '폭 맞춤:'; when its tip changes the
        description follows, and when the tip goes the description goes with it."""
        page = self.view()
        self.assertEqual(ax(page, "#btn-fit"), ("button", "폭 맞춤", "PDF 쪽 폭을 왼쪽 화면 폭에 맞춥니다 (Ctrl/⌘ 0)"))
        page.evaluate("document.getElementById('btn-fit').dataset.tip='폭 맞춤: 다른 설명'")
        settle(page)
        self.assertEqual(ax(page, "#btn-fit")[2], "다른 설명")
        page.evaluate("document.getElementById('btn-fit').removeAttribute('data-tip')")
        settle(page)
        self.assertIn(ax(page, "#btn-fit")[2], (None, ""))

    def test_the_english_screen_describes_in_english(self):
        """On the English screen the switch and [폭 맞춤] are described by their English explanations, with no Hangul
        left: the description is copied after the English observer has rewritten the tip."""
        page = self.view(lang="en")
        self.compose(page)
        role, name, desc = ax(page, "#c-sg-tg")
        self.assertEqual((role, name, desc), ("switch", "Suggested edit", page.get_attribute("#c-sg-tg", "data-tip")))
        self.assertTrue(desc and not HANGUL.search(desc), desc)
        role, name, desc = ax(page, "#btn-fit")
        self.assertEqual((role, name), ("button", "Fit width"))
        self.assertTrue(desc and not HANGUL.search(desc) and not desc.startswith("Fit width"), desc)


class TipKeyboard(TipBase):
    """The keyboard's focus shows the explanation as hovering does, on every device; Esc and leaving hide it."""

    def tab_to(self, page, selector):
        """Put the focus on the control before selector in Tab order and press Tab, so the focus arrives by the keyboard."""
        page.evaluate(
            """sel => {const t = document.querySelector(sel);
              const all = [...document.querySelectorAll('button,a[href],input,select,textarea,[tabindex]')]
                .filter(e => e.tabIndex >= 0 && !e.disabled && e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
              all[all.indexOf(t) - 1].focus();}""",
            selector,
        )
        page.keyboard.press("Tab")
        self.assertTrue(
            page.evaluate("sel => document.activeElement === document.querySelector(sel)", selector), selector
        )

    def test_the_keyboards_focus_shows_the_explanation_on_a_tablet_and_esc_or_leaving_hides_it(self):
        """A 768x1024 touch tablet (no hover) with a keyboard: Tab onto [제안 수정] shows its explanation by it; Esc hides
        it and leaves the focus and the composer where they were; coming back by Tab shows it again, and the focus leaving
        hides it. A finger's tap on a control shows nothing, as before."""
        page = self.view(TABLET)
        self.compose(page, "touch")
        self.tab_to(page, "#c-sg-tg")
        page.wait_for_function("!document.getElementById('tip').hidden", timeout=3000)
        box = page.evaluate(BOX)
        self.assertEqual((box["text"], box["focus"]), (box["tip"], "c-sg-tg"))
        page.keyboard.press("Escape")
        settle(page)
        self.assertEqual(
            page.evaluate("[TIP.hidden, document.activeElement.id, !!COMPOSE.current]"), [True, "c-sg-tg", True]
        )
        page.keyboard.press("Shift+Tab")
        page.keyboard.press("Tab")
        page.wait_for_function("!document.getElementById('tip').hidden", timeout=3000)
        page.evaluate("document.activeElement.blur()")
        settle(page)
        self.assertTrue(page.evaluate("TIP.hidden"))
        page.tap("#c-sg-tg")
        settle(page)
        self.assertTrue(page.evaluate("TIP.hidden"))

    def test_esc_before_the_box_has_shown_keeps_it_closed(self):
        """Tab then Esc at once on the desktop: the box that was still waiting to show (300ms) never opens."""
        page = self.view()
        self.tab_to(page, "#btn-fit")
        page.keyboard.press("Escape")
        settle(page)
        self.assertEqual(page.evaluate("[TIP.hidden, document.activeElement.id]"), [True, "btn-fit"])

    def test_a_tab_that_scrolls_its_control_into_view_still_shows_its_explanation(self):
        """Twelve open pins in a desktop panel: Tab onto the bottom card's [완료] scrolls the list to it, and the box shows
        by it once the scroll is over - the scroll used to take the box the focus had asked for."""
        for i in range(12):
            self.add_pin(i)
        page = self.view(n_open=12)
        below = page.evaluate(
            """() => {const b = [...document.querySelectorAll('.pin .acts button:last-child')].pop(); b.id = 'probe-done';
              return b.getBoundingClientRect().top > innerHeight;}"""
        )
        self.assertTrue(below)
        self.tab_to(page, "#probe-done")
        page.wait_for_function("!document.getElementById('tip').hidden", timeout=3000)
        box = page.evaluate(BOX)
        self.assertEqual((box["text"], box["focus"]), (box["tip"], "probe-done"))

    def test_esc_on_a_box_in_the_more_sheet_closes_the_box_first_and_then_the_sheet(self):
        """[더보기] is a modal dialog - a bottom sheet on a 768x1024 touch tablet, a menu under [⋯] on the desktop. Tab onto
        its [축소] and its box shows; the first Esc closes only the box, and the sheet and the focus on [축소] stay; the second
        Esc closes the sheet. The browser's close request used to take the box and the sheet at once."""
        for name, device, press in (("tablet", TABLET, "tap"), ("desktop", DESK, "click")):
            with self.subTest(name):
                page = self.view(device)
                getattr(page, press)("#btn-more")
                page.wait_for_function("document.getElementById('more').open")
                settle(page)
                zoom = "#more [data-act=zoom-out]"
                self.tab_to(page, zoom)
                page.wait_for_function("!document.getElementById('tip').hidden", timeout=3000)
                self.assertEqual(page.evaluate(BOX)["text"], page.get_attribute(zoom, "data-tip"))
                page.keyboard.press("Escape")
                settle(page)
                state = """sel => [TIP.hidden, document.getElementById('more').open,
                  document.activeElement === document.querySelector(sel)]"""
                self.assertEqual(page.evaluate(state, zoom), [True, True, True])
                page.keyboard.press("Escape")
                settle(page)
                self.assertEqual(page.evaluate(state, zoom)[1], False)

    def add_pin(self, i):
        """Open pin i+1 on its own line of the demo manuscript."""
        d = {"file": str(self.main), "lo": 3 + 2 * i, "hi": 3 + 2 * i, "page": 1, "note": "메모 %d" % (i + 1)}
        d["frac"] = [0.1, 0.05 + 0.04 * i, 0.3, 0.02]
        add_pin(d, actor(ALICE))


# A badge's words for a screen reader as drawn: the text it carries (data-tip-sr, drawn by its ::after), whether that text is a
# clipped 1px box, whether taking it away moves or resizes the badge (it must not: nothing on screen changes), whether the
# badge takes focus, and its own words. Put back as it was, at once.
READ_ALONG = """sel => {const b = document.querySelector(sel), said = b.getAttribute('data-tip-sr');
  if (said === null) return null;
  const a = getComputedStyle(b, '::after'), r = b.getBoundingClientRect();
  b.removeAttribute('data-tip-sr'); const q = b.getBoundingClientRect(); b.setAttribute('data-tip-sr', said);
  return {text: said, hidden: a.position === 'absolute' && a.width === '1px' && a.height === '1px' && a.clip === 'rect(0px, 0px, 0px, 0px)',
    same: r.left === q.left && r.top === q.top && r.width === q.width && r.height === q.height,
    focusable: b.tabIndex >= 0, words: b.textContent};}"""
# The words a selection over the card from its head to its note would copy (the browser's own serialization of the selection).
SELECT_CARD = """id => {const c = document.querySelector('.pin[data-id="' + id + '"]'), r = document.createRange();
  r.setStartBefore(c.querySelector('.head')); r.setEndAfter(c.querySelector('.note'));
  const s = getSelection(); s.removeAllRanges(); s.addRange(r); return s.toString();}"""


class TipReadAlong(TipBase):
    """A badge with an explanation carries it as words only a screen reader reads, so the card is read with it, and nothing
    is added on screen or to the Tab order. The words follow the explanation and speak the screen's language. A [제안 수정]
    warning badge carries none: its card says in a visible line that the agent will not apply it, and that line is read with
    the card."""

    BASE = "Line 4 of the demo manuscript.\nLine 5 of the demo manuscript."

    def add(self):
        """An open pin on lines 4-5 by Alice with a suggestion; its id."""
        d = {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "짧게", "frac": [0.1, 0.1, 0.3, 0.05]}
        d["suggest"] = {"base": self.BASE, "text": "Line four.\nLine 5 of the demo manuscript."}
        return add_pin(d, actor(ALICE)).core.id

    def card(self, lang="ko"):
        """A card whose suggestion still fits its lines, on the desktop in lang: the page, the pin's id and its plain
        [제안 수정] badge's selector."""
        pid = self.add()
        return self.view(n_open=1, lang=lang), pid, '.pin[data-id="%d"] .sg-badge' % pid

    def test_a_badge_is_read_with_its_explanation(self):
        """The card's plain '제안 수정' badge is read as its words and then its explanation (Chrome's tree and Playwright's
        snapshot), from a 1px hidden box that moves nothing and adds no tab stop; the words follow a changed explanation and
        go with a removed one."""
        page, pid, badge = self.card()
        tip = page.get_attribute(badge, "data-tip")
        self.assertIn("에이전트가 이 줄 범위에 넣고", tip)
        got = page.evaluate(READ_ALONG, badge)
        self.assertIsNotNone(got, "the badge has no words for a screen reader")
        self.assertEqual(got["text"], ": " + tip)
        self.assertEqual((got["words"], got["hidden"], got["same"], got["focusable"]), ("제안 수정", True, True, False))
        self.assertEqual(ax_words(page, badge), "제안 수정: " + tip)
        self.assertIn(tip, page.locator(badge).aria_snapshot())
        page.evaluate("s=>{document.querySelector(s).dataset.tip='다른 설명';}", badge)
        settle(page)
        self.assertEqual(ax_words(page, badge), "제안 수정: 다른 설명")
        page.evaluate("s=>document.querySelector(s).removeAttribute('data-tip')", badge)
        settle(page)
        self.assertIsNone(page.evaluate(READ_ALONG, badge))
        self.assertEqual(ax_words(page, badge), "제안 수정")

    def test_a_warning_badge_leaves_its_explanation_to_the_cards_line(self):
        """Line 5 edited after the suggestion: the '제안 수정 · 원문 바뀜' badge keeps its explanation box (data-tip) but is
        read as its words alone, and the card is read with its visible line that the agent will not apply it and what to
        do; the lines lost, the '확인 불가' badge likewise, the line saying it cannot be checked."""
        pid = self.add()
        tex = self.main.read_text(encoding="utf-8")
        self.main.write_text(tex.replace("Line 5 of the demo", "Line 5, edited, of the demo"), encoding="utf-8")
        page = self.view(n_open=1)
        card, badge = '.pin[data-id="%d"]' % pid, '.pin[data-id="%d"] .sg-badge' % pid
        for words, line in (
            ("제안 수정 · 원문 바뀜", "에이전트는 넣지 않음 · 수정해서 원문에 맞추기"),
            ("제안 수정 · 확인 불가", "에이전트는 넣지 않음 · 원문과 대조 불가"),
        ):
            with self.subTest(words):
                if words.endswith("확인 불가"):
                    self.main.write_text(tex.replace(self.BASE, "Something else.\nEntirely."), encoding="utf-8")
                    page.evaluate("loadPins()")
                    settle(page)
                self.assertIn("에이전트는 넣지 않고", page.get_attribute(badge, "data-tip"))
                self.assertIsNone(page.evaluate(READ_ALONG, badge), "a warning badge reads its explanation along")
                self.assertEqual(ax_words(page, badge), words)
                read = ax_words(page, card)
                self.assertIn(words, read)
                self.assertIn(line, read)
                self.assertNotIn("에이전트는 넣지 않고", read)

    def test_a_selection_across_the_badge_copies_only_the_words_on_screen(self):
        """Selecting the card from its head to its note and copying (Ctrl+C, pasted back into a field with Ctrl+V) gives the
        badge's words and none of its explanation: the read-along words are not selectable text."""
        page, pid, badge = self.card()
        selected = page.evaluate(SELECT_CARD, pid)
        page.keyboard.press("ControlOrMeta+c")
        page.evaluate(
            """() => {const t = document.createElement('textarea'); t.id = 'paste-probe'; document.body.append(t); t.focus();}"""
        )
        page.keyboard.press("ControlOrMeta+v")
        copied = page.input_value("#paste-probe")
        for text in (selected, copied):
            self.assertIn("제안 수정", text)
            self.assertNotIn("에이전트가 이 줄 범위에 넣고", text)

    def test_the_browsers_find_does_not_find_the_explanation(self):
        """The browser's find (window.find) finds the badge's words but no phrase of its explanation, which would be an
        invisible result; the explanation is still in the accessibility tree."""
        page, pid, badge = self.card()
        find = "t => {getSelection().removeAllRanges(); return window.find(t, false, false, true);}"
        self.assertTrue(page.evaluate(find, "제안 수정"))
        self.assertFalse(page.evaluate(find, "에이전트가 이 줄 범위에 넣고"))
        self.assertIn("에이전트가 이 줄 범위에 넣고", ax_words(page, badge))

    def test_the_english_screen_reads_the_explanation_in_english(self):
        """On the English screen the badge's words and explanation are both English: the copy is made from the
        explanation the English observer wrote, and is not translated again."""
        page, pid, badge = self.card(lang="en")
        words = ax_words(page, badge)
        self.assertEqual(words, "Suggested edit: " + page.get_attribute(badge, "data-tip"))
        self.assertIn("agent", words)
        self.assertIsNone(HANGUL.search(words), words)

    def test_the_reason_in_the_switchs_place_is_read_with_its_explanation(self):
        """An area pick has no [제안 수정] switch; the short reason in its place ('영역에는 제안 수정 없음') is read with its
        explanation, as a badge is."""
        self.PICK = {"kind": "region", "view_only": True, "lo": None, "hi": None, "file": None, "quote": "Area"}
        page = self.view()
        self.compose(page)
        tip = page.get_attribute("#c-sg-why", "data-tip")
        self.assertEqual(ax_words(page, "#c-sg-why"), "영역에는 제안 수정 없음: " + tip)
        self.assertTrue(page.evaluate(READ_ALONG, "#c-sg-why")["same"])


if __name__ == "__main__":
    unittest.main()

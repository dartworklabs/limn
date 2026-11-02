"""Explanations (data-tip) for the keyboard and screen readers (docs/handbook/viewer.md §설명과 접근성).

- ``TipDescriptionLogic`` runs tipDescText under node: what an explanation adds to a control's name.
- ``TipDescriptions`` drives the real viewer and reads Chrome's accessibility tree, which is what a screen reader is
  given: a focusable control's explanation is its description, without its name again, in the screen's language, and
  it follows the explanation when that changes.
- ``TipKeyboard`` holds the WAI-ARIA tooltip pattern: the keyboard's focus shows the box on every device, a tablet
  without hover too, Esc and leaving the control hide it, and Tab's own scroll does not take it.

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
# The box as shown: hidden or not, its text, and whether it stands by the focused control (beside or over it, no gap).
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
        and line breaks collapse; no tip, no description."""
        got = json.loads(
            run_node(
                extract_js_fn("tipDescText")
                + r"""
            console.log(JSON.stringify([tipDescText('상태: 열림', '상태: 열림'), tipDescText('폭 맞춤: PDF 쪽 폭을 맞춥니다', '폭 맞춤'),
              tipDescText('#3 · 메모 첫 줄', '#3'), tipDescText('Fit width — fits the page', ' Fit width '),
              tipDescText('지금 빌드의 그림을 보입니다', '지금 빌드'), tipDescText('바꿀 글을\n  직접 씁니다', '제안 수정'),
              tipDescText('', '완료'), tipDescText('설명', '')]));"""
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
        self.assertEqual(page.evaluate("document.activeElement.id"), selector.lstrip("#"))

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

    def add_pin(self, i):
        """Open pin i+1 on its own line of the demo manuscript."""
        d = {"file": str(self.main), "lo": 3 + 2 * i, "hi": 3 + 2 * i, "page": 1, "note": "메모 %d" % (i + 1)}
        d["frac"] = [0.1, 0.05 + 0.04 * i, 0.3, 0.02]
        add_pin(d, actor(ALICE))


if __name__ == "__main__":
    unittest.main()

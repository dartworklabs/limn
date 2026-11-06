"""A segmented control is a radio group the keyboard walks (docs/handbook/viewer.md §디자인 토큰과 컴포넌트, issue #417).

The whole group is one Tab stop - the chosen word - and Tab leaves it at once; inside it the arrows move the focus to the
previous or next word and choose it (wrapping at the ends), Home and End go to its first and last word, and a word that is
disabled is passed over. Each group kind is walked: one in the page's markup ([더보기]'s theme), one the composer shows
later (its kind row), the assignee row that draws its words again on every pick - the focus must stay on the word in the
same place - and the edit card's rows, drawn when it opens. Chromium and Firefox, since focus moves and Tab order are the
browser's.
"""

from limn.pins.editing.values import ASSIGNEE_AGENT as AGENT_ASSIGNEE

from helpers import add_pin, ps
from helpers_access import ALICE, BOB, CAROL, actor
from helpers_browser import BrowserBase, booted, settle

# Every radio group drawn on the page: its words as (key, checked, tabIndex), where key is the word's data-* value.
GROUPS = """() => [...document.querySelectorAll('[role=radiogroup]')].filter(g => g.getClientRects().length).map(g => ({
  group: g.id || g.className, words: [...g.querySelectorAll('[role=radio]')].filter(w => !w.disabled && !w.hidden)
    .map(w => [w.dataset.theme || w.dataset.lang || w.dataset.kind || w.dataset.v || w.dataset.mode || w.textContent.trim(),
      w.getAttribute('aria-checked') === 'true', w.tabIndex])}))"""
# Counts the presses (clicks) on any radio group's word, in SEG_CLICKS.
CLICKS = "window.SEG_CLICKS=0; document.addEventListener('click',e=>{if(e.target.closest('[role=radio]'))SEG_CLICKS++;},true)"
# [더보기]'s language row: the focused word's language and whether it is chosen, the words holding a Tab stop, the presses
# counted (CLICKS) and whether the page is still the one marked (STAY: a choice reopens it).
LANG_STATE = """(() => {const a = document.activeElement, ws = [...document.querySelectorAll('#m-lang [role=radio]')];
  return {at: a.dataset.lang, checked: a.getAttribute('aria-checked') === 'true', stops: ws.filter(w => w.tabIndex === 0)
    .map(w => w.dataset.lang), pressed: SEG_CLICKS, stay: window.STAY};})()"""
# The phone's navigation sheet: open or not, the focused word's view and whether it is chosen, the presses counted (CLICKS,
# 0 once the page has none counted) and whether the changes view is open.
VIEW_STATE = """[document.querySelector('#nav-sheet').open, document.activeElement.dataset.mode,
  document.activeElement.getAttribute('aria-checked') === 'true', window.SEG_CLICKS || 0,
  document.body.classList.contains('revision-open')]"""
# The focused element: the radio group it is in, its word's key and whether it is checked, else its id or tag.
FOCUS = """() => {const a = document.activeElement, g = a && a.closest && a.closest('[role=radiogroup]');
  if (!g) return {group: null, at: a ? a.id || a.tagName : null};
  return {group: g.id || g.className, at: a.dataset.theme || a.dataset.kind || a.dataset.v, checked: a.getAttribute('aria-checked') === 'true'};}"""


class SegmentKeys(BrowserBase):
    """In Chromium: the arrows, Home, End and Tab on each kind of segmented control."""

    def setUp(self):
        """Register Alice, Bob and Carol, so a note's @-tag of Bob offers the assignee row."""
        super().setUp()
        for person in (ALICE, BOB, CAROL):
            ps.APP.people_directory.record(actor(person))

    def assert_one_stop_each(self, page):
        """Every drawn radio group holds exactly one Tab stop (tabIndex 0), its checked word."""
        for g in page.evaluate(GROUPS):
            with self.subTest(group=g["group"]):
                stops = [w for w in g["words"] if w[2] == 0]
                self.assertEqual(len(stops), 1, g)
                self.assertTrue(stops[0][1], g)  # the stop is the checked word
                self.assertTrue(all(w[2] == -1 for w in g["words"] if w is not stops[0]), g)

    def key(self, page, name):
        """Press key name on the focused element and wait for what it set in motion."""
        page.keyboard.press(name)
        settle(page)
        return page.evaluate(FOCUS)

    def tab_leaves(self, page, group):
        """From the focused word of group: Tab leaves the group, and Shift+Tab comes back to its checked word, the next
        Shift+Tab leaves it backwards - one stop each way."""
        self.assertNotEqual(self.key(page, "Tab")["group"], group, "Tab stayed in %s" % group)
        back = self.key(page, "Shift+Tab")
        self.assertEqual((back["group"], back["checked"]), (group, True))
        self.assertNotEqual(self.key(page, "Shift+Tab")["group"], group, "Shift+Tab stayed in %s" % group)

    def test_the_arrows_home_and_end_walk_and_choose_the_theme(self):
        """[더보기]'s theme [시스템 | 밝게 | 어둡게], chosen 밝게: → chooses 어둡게 and the page turns dark, → wraps to
        시스템, ← back to 어둡게, Home 시스템, End 어둡게, ↑ 밝게, ↓ 어둡게 - the focus on the chosen word every time."""
        page = self.open(0, viewport={"width": 1440, "height": 900})
        page.locator("#btn-more").click()
        page.wait_for_selector("#more[open]")
        settle(page)
        self.assert_one_stop_each(page)
        page.focus("#m-theme [aria-checked=true]")
        self.assertEqual(page.evaluate(FOCUS)["at"], "light")
        for name, theme in (
            ("ArrowRight", "dark"),
            ("ArrowRight", "system"),
            ("ArrowLeft", "dark"),
            ("Home", "system"),
            ("End", "dark"),
            ("ArrowUp", "light"),
            ("ArrowDown", "dark"),
        ):
            with self.subTest(key=name):
                self.assertEqual(self.key(page, name), {"group": "m-theme", "at": theme, "checked": True})
                self.assertEqual(page.evaluate("prefs().theme"), theme)
        self.assertEqual(page.get_attribute("html", "data-theme"), "dark")
        self.assert_one_stop_each(page)
        self.tab_leaves(page, "m-theme")

    def test_a_key_onto_the_chosen_word_only_moves_the_focus(self):
        """A key that lands on the word already chosen presses nothing: [더보기]'s theme, 시스템 chosen - Home presses
        nothing, End chooses 어둡게, a second End nothing."""
        page = self.open(0, viewport={"width": 1440, "height": 900})
        page.locator("#btn-more").click()
        page.wait_for_selector("#more[open]")
        page.evaluate("setTheme('system')")
        settle(page)
        page.evaluate(CLICKS)
        page.focus("#m-theme [aria-checked=true]")
        for name, theme, n in (("Home", "system", 0), ("End", "dark", 1), ("End", "dark", 1)):
            with self.subTest(key=name, clicks=n):
                self.assertEqual(self.key(page, name), {"group": "m-theme", "at": theme, "checked": True})
                self.assertEqual(page.evaluate("SEG_CLICKS"), n)
        self.assert_one_stop_each(page)

    def test_the_language_is_walked_without_choosing_and_chosen_with_enter_or_space(self):
        """[더보기]'s language reopens the page when chosen, so its keys only move the focus (data-seg-manual): → from
        한국어 puts the focus on English and chooses nothing - the page stays, nothing is pressed - and Home, End and ←
        walk on; the stop goes with the focus, and once Tab has left it is the chosen word again, where Shift+Tab comes
        back. Enter on English reopens the page in English; there Space on 한국어, reached with ←, reopens it in Korean."""
        page = self.open(0, viewport={"width": 1440, "height": 900})
        page.locator("#btn-more").click()
        page.wait_for_selector("#more[open]")
        settle(page)
        page.evaluate(CLICKS + "; window.STAY = 1")
        page.focus("#m-lang [aria-checked=true]")
        for name, lang in (
            ("ArrowRight", "en"),
            ("Home", "ko"),
            ("End", "en"),
            ("ArrowLeft", "ko"),
            ("ArrowRight", "en"),
        ):
            with self.subTest(key=name):
                page.keyboard.press(name)
                self.assertEqual(
                    page.evaluate(LANG_STATE),
                    {"at": lang, "checked": lang == "ko", "stops": [lang], "pressed": 0, "stay": 1},
                )
        self.assertNotEqual(self.key(page, "Tab")["group"], "m-lang")
        self.assertEqual(page.evaluate(LANG_STATE)["stops"], ["ko"])  # the chosen word is the stop again
        back = self.key(page, "Shift+Tab")
        self.assertEqual((back["group"], page.evaluate(LANG_STATE)["at"]), ("m-lang", "ko"))
        page.keyboard.press("ArrowRight")
        with page.expect_navigation():
            page.keyboard.press("Enter")
        page.wait_for_function(booted(0), timeout=20000)
        self.assertEqual(page.evaluate("LANG"), "en")
        page.locator("#btn-more").click()
        page.wait_for_selector("#more[open]")
        settle(page)
        page.focus("#m-lang [aria-checked=true]")
        page.keyboard.press("ArrowLeft")
        self.assertEqual(page.evaluate("LANG"), "en")
        with page.expect_navigation():
            page.keyboard.press(" ")
        page.wait_for_function(booted(0), timeout=20000)
        self.assertEqual(page.evaluate("LANG"), "ko")

    def test_the_phone_navigation_sheets_view_is_walked_without_choosing(self):
        """The phone's navigation sheet [원고 | 변경사항] changes the view and closes the sheet when chosen, so its keys only
        move the focus (data-seg-manual): Home on 원고, the word chosen, leaves the sheet open on it (the press shut the
        sheet and sent the focus to [본문 ▾]); → puts the focus on 변경사항, End and ← walk on, the view and the sheet
        stay and nothing is pressed. Enter on 변경사항 opens the changes view and closes the sheet; opened again, Space on
        원고, reached with ←, goes back to the manuscript."""
        page = self.open(0, viewport={"width": 390, "height": 844})
        page.locator("#btn-pos").click()
        page.wait_for_selector("#nav-sheet[open]")
        settle(page)
        page.evaluate(CLICKS)
        page.focus("#ns-view [aria-checked=true]")
        for name, mode in (
            ("Home", "manuscript"),
            ("ArrowRight", "revisions"),
            ("End", "revisions"),
            ("ArrowLeft", "manuscript"),
            ("ArrowRight", "revisions"),
        ):
            with self.subTest(key=name):
                self.key(page, name)
                self.assertEqual(page.evaluate(VIEW_STATE), [True, mode, mode == "manuscript", 0, False])
        self.key(page, "Enter")
        self.assertEqual(page.evaluate(VIEW_STATE)[0::4], [False, True])  # the sheet closed, the changes view open
        page.locator("#btn-pos").click()
        page.wait_for_selector("#nav-sheet[open]")
        settle(page)
        page.focus("#ns-view [aria-checked=true]")
        self.key(page, "ArrowLeft")
        self.assertEqual(page.evaluate(VIEW_STATE)[0:3], [True, "manuscript", False])
        self.key(page, " ")
        self.assertEqual(page.evaluate(VIEW_STATE)[0::4], [False, False])

    def test_a_disabled_word_is_passed_over(self):
        """With 밝게 disabled, → from 시스템 goes to 어둡게 and ← from 어둡게 back to 시스템."""
        page = self.open(0, viewport={"width": 1440, "height": 900})
        page.locator("#btn-more").click()
        page.wait_for_selector("#more[open]")
        page.evaluate("setTheme('system')")
        page.evaluate("document.querySelector('#m-theme [data-theme=light]').disabled = true")
        settle(page)
        page.focus("#m-theme [aria-checked=true]")
        self.assertEqual(self.key(page, "ArrowRight")["at"], "dark")
        self.assertEqual(self.key(page, "ArrowLeft")["at"], "system")
        self.assertEqual(self.key(page, "End")["at"], "dark")

    def test_the_composers_kind_row_is_one_stop_and_the_arrows_choose_the_kind(self):
        """The composer opened on a pick: Tab from the note reaches the chosen kind (수정 요청) and the next Tab leaves the
        row; → chooses 질문 (the note's placeholder asks a question), ← 수정 요청 again."""
        page = self.open(0, viewport={"width": 1440, "height": 900})
        self.open_composer(page)
        settle(page)
        self.assert_one_stop_each(page)
        page.focus("#note")
        while page.evaluate(FOCUS)["group"] is None:  # the note, then whatever stands before the kind row
            self.key(page, "Tab")
        self.assertEqual(page.evaluate(FOCUS), {"group": "c-kind", "at": "fix", "checked": True})
        self.assertEqual(self.key(page, "ArrowRight"), {"group": "c-kind", "at": "question", "checked": True})
        self.assertEqual(page.evaluate("KIND_NEW"), "question")
        self.assertEqual(page.get_attribute("#note", "placeholder"), "무엇이 궁금한지 적어 주세요")
        self.assertEqual(self.key(page, "ArrowLeft"), {"group": "c-kind", "at": "fix", "checked": True})
        self.assert_one_stop_each(page)
        self.tab_leaves(page, "c-kind")

    def test_the_assignee_row_keeps_the_focus_in_place_though_it_draws_its_words_again(self):
        """A note tagging Bob and Carol offers [에이전트 | @Bob | @Carol], Bob chosen. Each pick draws the row's words anew;
        the arrows still walk it - ← 에이전트, End Carol, → wraps to 에이전트, Home stays - with the focus on the new word in
        the same place and the pick sent with the save."""
        page = self.open(0, viewport={"width": 1440, "height": 900})
        self.open_composer(page)
        page.fill("#note", "@Bob Park 그리고 @Carol Lee 확인")
        settle(page)
        bob, carol = BOB["Tailscale-User-Login"], CAROL["Tailscale-User-Login"]
        page.wait_for_selector('#c-assign [data-v="%s"]' % bob)
        self.assert_one_stop_each(page)
        page.focus("#c-assign [aria-checked=true]")
        before = page.evaluate_handle("document.activeElement")
        for name, who in (
            ("ArrowLeft", AGENT_ASSIGNEE),
            ("End", carol),
            ("ArrowRight", AGENT_ASSIGNEE),
            ("Home", AGENT_ASSIGNEE),
        ):
            with self.subTest(key=name):
                self.assertEqual(self.key(page, name), {"group": "c-assign", "at": who, "checked": True})
                self.assertEqual(page.evaluate("ASSIGN_NEW.v"), who)
        self.assertFalse(page.evaluate("e=>document.contains(e)", before))  # the row's words were drawn again
        self.assertEqual(self.key(page, "ArrowDown")["at"], bob)
        self.assert_one_stop_each(page)
        self.tab_leaves(page, "c-assign")

    def test_the_edit_cards_rows_are_one_stop_each_when_it_opens(self):
        """A stored question tagging Bob, opened for editing: the card's kind row and assignee row each hold one stop, on
        질문 and 에이전트; ↑ on the kind row chooses 수정 요청."""
        pid = add_pin(
            {
                "file": str(self.main),
                "lo": 4,
                "hi": 5,
                "page": 1,
                "note": "수치를 @Bob Park 확인",
                "kind_req": "question",
                "assignee": AGENT_ASSIGNEE,
            },
            actor(ALICE),
        ).record["id"]
        page = self.open(1, viewport={"width": 1440, "height": 900})
        page.evaluate("id=>openEdit(id)", pid)
        page.wait_for_function("EDITOR.current&&EDITOR.current.levels.length>0")
        settle(page)
        self.assert_one_stop_each(page)
        groups = {g["group"]: g["words"] for g in page.evaluate(GROUPS)}
        self.assertEqual([w[0] for w in groups["e-kind seg kind-seg"] if w[2] == 0], ["question"])
        self.assertEqual([w[0] for w in groups["e-assign assign-row"] if w[2] == 0], [AGENT_ASSIGNEE])
        page.focus(".e-kind [aria-checked=true]")
        self.assertEqual(self.key(page, "ArrowUp"), {"group": "e-kind seg kind-seg", "at": "fix", "checked": True})
        self.assert_one_stop_each(page)


class SegmentKeysFirefox(SegmentKeys):
    """The same walks in Firefox."""

    BROWSER_ENGINE = "firefox"

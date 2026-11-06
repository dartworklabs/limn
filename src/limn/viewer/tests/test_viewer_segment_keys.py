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
from helpers_browser import BrowserBase, settle

# Every radio group drawn on the page: its words as (key, checked, tabIndex), where key is the word's data-* value.
GROUPS = """() => [...document.querySelectorAll('[role=radiogroup]')].filter(g => g.getClientRects().length).map(g => ({
  group: g.id || g.className, words: [...g.querySelectorAll('[role=radio]')].filter(w => !w.disabled && !w.hidden)
    .map(w => [w.dataset.theme || w.dataset.lang || w.dataset.kind || w.dataset.v || w.dataset.mode || w.textContent.trim(),
      w.getAttribute('aria-checked') === 'true', w.tabIndex])}))"""
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

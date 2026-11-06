"""A segmented control is a radio group the keyboard walks (docs/handbook/viewer.md §디자인 토큰과 컴포넌트, issues #417, #438).

The whole group is one Tab stop - the chosen word - and Tab leaves it at once; inside it the arrows move the focus to the
previous or next word and choose it (wrapping at the ends), Home and End go to its first and last word, and a word that is
disabled is passed over. Each group kind is walked: one in the page's markup ([더보기]'s theme), one the composer shows
later (its kind row), the assignee row that draws its words again on every pick - the focus must stay on the word in the
same place - and the edit card's rows, drawn when it opens. So are the three that were rows of toggle buttons until #438:
the list's order [최신순 | 위치순 | 번호순], which sorts the list again in place, [더보기]'s panel width (the phone's sheet
height), drawn again on every pick, and the range ladder of the composer and the edit card, drawn again with the range.
Chromium and Firefox, since focus moves and Tab order are the browser's.
"""

from limn.pins.editing.values import ASSIGNEE_AGENT as AGENT_ASSIGNEE

from helpers import add_pin, ps
from helpers_access import ALICE, BOB, CAROL, actor
from helpers_browser import BrowserBase, booted, settle

# Every radio group drawn on the page: its words as (key, checked, tabIndex), where key is the word's data-* value.
GROUPS = """() => [...document.querySelectorAll('[role=radiogroup]')].filter(g => g.getClientRects().length).map(g => ({
  group: g.id || g.className, words: [...g.querySelectorAll('[role=radio]')].filter(w => !w.disabled && !w.hidden)
    .map(w => [w.dataset.theme || w.dataset.lang || w.dataset.kind || w.dataset.v || w.dataset.mode || w.dataset.order
      || w.dataset.level || w.dataset.i || w.textContent.trim(),
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
  return {group: g.id || g.className, at: a.dataset.theme || a.dataset.kind || a.dataset.v || a.dataset.order || a.dataset.level
    || a.dataset.i, checked: a.getAttribute('aria-checked') === 'true'};}"""
# The open pins' cards top to bottom, by pin id.
ROWS = "[...document.querySelectorAll('#pins .pin[data-id]')].map(e => Number(e.dataset.id))"
# The pin panel's width as drawn, in whole pixels.
SIDE_W = "Math.round(document.querySelector('#right').getBoundingClientRect().width)"
# A manuscript whose line 5 has three rungs: the line, its paragraph (lines 4-6) and the abstract round it (lines 3-9).
LADDER_TEX = (
    "\\documentclass{article}\n\\begin{document}\n\\begin{abstract}\nLine 4 first.\nLine 5 second.\nLine 6 third.\n\n"
    + "Line 8 next paragraph.\n\\end{abstract}\n"
    + "".join("Line %d of the demo manuscript.\n" % i for i in range(10, 40))
    + "\\end{document}\n"
)
# Each rung of LADDER_TEX's ladder at line 5 and the lines it sets.
RUNGS = {"raw": (5, 5), "para": (4, 6), "env": (3, 9)}


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
        질문 and 에이전트; ↑ on the kind row chooses 수정 요청, and → on the assignee row Bob - the row drawn again, the
        focus on Bob."""
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
        page.focus(".e-assign [aria-checked=true]")
        bob = BOB["Tailscale-User-Login"]
        self.assertEqual(self.key(page, "ArrowRight"), {"group": "e-assign assign-row", "at": bob, "checked": True})
        self.assertEqual(page.evaluate("EDITOR.current.assignee"), bob)
        self.assert_one_stop_each(page)

    def three_pins(self):
        """Three open pins whose orders all differ: newest first [c, b, a], by place [b, c, a], by number [a, b, c]."""
        at = (
            {"lo": 30, "hi": 30, "page": 2, "note": "가"},
            {"lo": 4, "hi": 4, "page": 1, "note": "나"},
            {"lo": 20, "hi": 20, "page": 2, "note": "다"},
        )
        return [add_pin(dict(p, file=str(self.main)), actor(ALICE)).record["id"] for p in at]

    def walk(self, page, group, steps, check):
        """From the focused word of group, press each (key, word) of steps: the focus is on that word, checked, and
        check(word) holds; a key onto the word already chosen presses nothing. Returns the presses counted."""
        page.evaluate(CLICKS)
        presses, was = 0, page.evaluate(FOCUS)["at"]
        for name, word in steps:
            with self.subTest(group=group, key=name, word=word):
                got = self.key(page, name)
                self.assertEqual(
                    dict(got, group=got["group"].split()[0]), {"group": group, "at": word, "checked": True}
                )
                presses += word != was
                self.assertEqual(page.evaluate("SEG_CLICKS"), presses)
                check(word)
            was = word
        return presses

    def test_the_list_order_is_one_stop_and_the_arrows_sort_the_list_again(self):
        """[최신순 | 위치순 | 번호순] over three pins whose orders differ: one stop, on 최신순; → 위치순 and the cards go by
        place, → 번호순 by number, → wraps to 최신순, End, Home, ← (wrapping) and ↑/↓ the same, the choice saved for this
        browser; a second End presses nothing. The focus stays on the same words: the control is not drawn again."""
        a, b, c = self.three_pins()
        page = self.open(3, viewport={"width": 1440, "height": 900})
        rows = {"new": [c, b, a], "page": [b, c, a], "id": [a, b, c]}
        self.assertEqual(page.evaluate(ROWS), rows["new"])
        self.assert_one_stop_each(page)
        page.focus("#list-order [aria-checked=true]")
        words = page.evaluate_handle("[...document.querySelectorAll('#list-order [role=radio]')]")

        def sorted_again(order):
            self.assertEqual(page.evaluate(ROWS), rows[order])
            self.assertEqual(page.evaluate("[ORDER, prefs().order]"), [order, order])

        steps = [("ArrowRight", "page"), ("ArrowRight", "id"), ("ArrowRight", "new"), ("End", "id"), ("Home", "new")]
        steps += [("ArrowLeft", "id"), ("ArrowUp", "page"), ("ArrowDown", "id"), ("End", "id")]
        self.assertEqual(self.walk(page, "list-order", steps, sorted_again), 8)
        self.assertTrue(page.evaluate("ws => ws.every(w => document.contains(w))", words))  # the same words throughout
        self.assert_one_stop_each(page)
        self.tab_leaves(page, "list-order")
        page.reload()  # the order saved comes back with the page, and with it the one stop
        page.wait_for_function(booted(3), timeout=20000)
        settle(page)
        self.assertEqual(page.evaluate(ROWS), rows["id"])
        self.assert_one_stop_each(page)

    def test_the_panel_width_is_one_stop_and_the_arrows_choose_and_draw_it(self):
        """[더보기]'s [좁게 | 보통 | 넓게] at 1440x900, 보통 chosen: → chooses 넓게 and the panel widens to that preset, →
        wraps to 좁게, Home on it presses nothing, End, ←, ↑ and ↓ walk on - each pick draws the words again, and the focus
        is on the new word in the same place."""
        page = self.open(0, viewport={"width": 1440, "height": 900})
        page.locator("#btn-more").click()
        page.wait_for_selector("#more[open]")
        settle(page)
        self.assert_one_stop_each(page)
        presets = page.evaluate("sideBounds(LAYOUT, innerWidth).presets")
        self.assertEqual(page.evaluate(SIDE_W), presets[1])
        page.focus("#m-size [aria-checked=true]")
        first = page.evaluate_handle("document.activeElement")

        def drawn(i):
            self.assertEqual(page.evaluate(SIDE_W), presets[int(i)])

        steps = [("ArrowRight", "2"), ("ArrowRight", "0"), ("Home", "0"), ("End", "2"), ("ArrowLeft", "1")]
        steps += [("ArrowUp", "0"), ("ArrowDown", "1")]
        self.assertEqual(self.walk(page, "m-size", steps, drawn), 6)
        self.assertFalse(page.evaluate("e => document.contains(e)", first))  # the words were drawn again
        self.assertLess(presets[0], presets[1])
        self.assertLess(presets[1], presets[2])
        self.assert_one_stop_each(page)
        self.tab_leaves(page, "m-size")

    def test_the_phones_sheet_height_is_walked_the_same(self):
        """On a phone the control is [낮게 | 보통 | 높게] for the sheet: → from 보통 chooses 높게 and the sheet stands at
        the full height, ← back to 보통, Home 낮게 - the focus on the new word each time."""
        page = self.open(0, viewport={"width": 390, "height": 844})
        page.locator("#btn-more").click()
        page.wait_for_selector("#more[open]")
        settle(page)
        self.assert_one_stop_each(page)
        page.focus("#m-size [aria-checked=true]")
        heights = {"0": 0.45, "1": 0.64, "2": 1}

        def drawn(i):
            self.assertEqual(page.evaluate("sheetF()"), heights[i])
            self.assertEqual(
                page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--sheet-f')"),
                str(heights[i]),
            )

        self.walk(page, "m-size", [("ArrowRight", "2"), ("ArrowLeft", "1"), ("Home", "0")], drawn)
        self.assertEqual(page.inner_text("#m-size-l"), "시트 높이")

    def test_the_tablets_folded_panel_checks_the_width_it_opens_at(self):
        """At 768x1024 the panel starts folded, and a folded panel measures 0 wide: [더보기] still checks 보통, the width it
        opens at, and → checks 넓게 - the panel opened is that wide."""
        page = self.open(0, viewport={"width": 768, "height": 1024})
        self.assertFalse(page.evaluate("SIDE_OPEN"))
        page.locator("#btn-more").click()
        page.wait_for_selector("#more[open]")
        settle(page)
        self.assert_one_stop_each(page)
        presets = page.evaluate("sideBounds(LAYOUT, innerWidth).presets")
        page.focus("#m-size [aria-checked=true]")
        self.assertEqual(page.evaluate(FOCUS), {"group": "m-size", "at": "1", "checked": True})
        self.assertEqual(self.key(page, "ArrowRight"), {"group": "m-size", "at": "2", "checked": True})
        self.assert_one_stop_each(page)
        page.keyboard.press("Escape")
        page.evaluate("setSide(true)")
        settle(page)
        self.assertEqual(page.evaluate(SIDE_W), presets[2])

    def open_ladder(self, page):
        """Open the composer on line 5 of LADDER_TEX, its paragraph chosen, and put the focus on the ladder's chosen rung."""
        self.open_composer(page)
        settle(page)
        self.assertEqual(
            page.evaluate("[...document.querySelectorAll('#c-levels [role=radio]')].map(w => w.dataset.level)"),
            ["raw", "para", "env"],
        )
        page.focus("#c-levels [aria-checked=true]")

    def test_the_range_ladder_is_one_stop_and_the_arrows_choose_the_range(self):
        """The composer's ladder [드래그한 줄 | 문단 | abstract], 문단 chosen: → chooses abstract and the range is its
        lines (the caption says so), → wraps to the line, ← abstract, Home the line, End abstract, a second End nothing, ↑
        문단 and ↓ abstract. The ladder is drawn again with every range, and the focus stays on the rung in that place."""
        self.main.write_text(LADDER_TEX, encoding="utf-8")
        page = self.open(0, viewport={"width": 1440, "height": 900})
        self.open_ladder(page)
        self.assert_one_stop_each(page)
        first = page.evaluate_handle("document.activeElement")

        def chosen(level):
            lo, hi = RUNGS[level]
            self.assertEqual(
                page.evaluate("[COMPOSE.current.lo, COMPOSE.current.hi, COMPOSE.current.scope]"), [lo, hi, level]
            )
            self.assertIn("L%d" % lo + ("-L%d" % hi if hi != lo else ""), page.inner_text("#c-cap"))

        steps = [("ArrowRight", "env"), ("ArrowRight", "raw"), ("ArrowLeft", "env"), ("Home", "raw"), ("End", "env")]
        steps += [("End", "env"), ("ArrowUp", "para"), ("ArrowDown", "env")]
        self.assertEqual(self.walk(page, "c-levels", steps, chosen), 7)
        self.assertFalse(page.evaluate("e => document.contains(e)", first))  # the rungs were drawn again
        self.assert_one_stop_each(page)
        self.tab_leaves(page, "c-levels")

    def test_enter_space_and_a_click_on_a_word_drawn_again_keep_the_focus_in_its_group(self):
        """A press that draws its group again does not drop the focus on the body: Space and Enter on the ladder's chosen
        rung, a click on another rung, and Space on [더보기]'s chosen width each leave the focus on the word in that place."""
        self.main.write_text(LADDER_TEX, encoding="utf-8")
        page = self.open(0, viewport={"width": 1440, "height": 900})
        self.open_ladder(page)
        for name in (" ", "Enter"):
            with self.subTest(key=name):
                self.assertEqual(self.key(page, name), {"group": "c-levels", "at": "para", "checked": True})
        page.click("#c-levels [data-level=raw]")
        settle(page)
        self.assertEqual(page.evaluate(FOCUS), {"group": "c-levels", "at": "raw", "checked": True})
        page.keyboard.press("Escape")
        page.locator("#btn-more").click()
        page.wait_for_selector("#more[open]")
        settle(page)
        page.focus("#m-size [aria-checked=true]")
        self.assertEqual(self.key(page, " "), {"group": "m-size", "at": "1", "checked": True})

    def test_the_edit_cards_ladder_is_one_stop_and_the_arrows_choose_its_range(self):
        """A stored pin on line 5 of LADDER_TEX, opened for editing: its ladder [지금 범위 | 문단 | abstract] holds one stop,
        on 지금 범위; → chooses 문단 and the card's range is lines 4-6, End abstract, Home back to the pin's own line - the
        focus on the rung in the same place though each pick draws the ladder again."""
        self.main.write_text(LADDER_TEX, encoding="utf-8")
        pid = add_pin({"file": str(self.main), "lo": 5, "hi": 5, "page": 1, "note": "고칠 곳"}, actor(ALICE)).record[
            "id"
        ]
        page = self.open(1, viewport={"width": 1440, "height": 900})
        page.evaluate("id=>openEdit(id)", pid)
        page.wait_for_function("EDITOR.current&&EDITOR.current.levels.length>2")
        settle(page)
        self.assert_one_stop_each(page)
        page.focus(".e-levels [aria-checked=true]")
        self.assertEqual(page.evaluate(FOCUS)["at"], "raw")

        def chosen(level):
            self.assertEqual(page.evaluate("[EDITOR.current.lo, EDITOR.current.hi]"), list(RUNGS[level]))

        steps = [("ArrowRight", "para"), ("End", "env"), ("Home", "raw")]
        self.assertEqual(self.walk(page, "e-levels", steps, chosen), 3)
        self.assert_one_stop_each(page)

    def test_a_disabled_word_is_passed_over_in_the_order_the_width_and_the_ladder(self):
        """With the middle word disabled, → from the first passes over it: 최신순 to 번호순, and - the width's 넓게 and the
        ladder's abstract disabled - → from 보통 wraps to 좁게 and from 문단 to the line."""
        self.main.write_text(LADDER_TEX, encoding="utf-8")
        self.three_pins()
        page = self.open(3, viewport={"width": 1440, "height": 900})
        page.evaluate("document.querySelector('#list-order [data-order=page]').disabled = true")
        page.focus("#list-order [aria-checked=true]")
        self.assertEqual(self.key(page, "ArrowRight")["at"], "id")
        self.assertEqual(self.key(page, "ArrowLeft")["at"], "new")
        page.locator("#btn-more").click()
        page.wait_for_selector("#more[open]")
        settle(page)
        page.evaluate("document.querySelector('#m-size [data-i=\"2\"]').disabled = true")
        page.focus("#m-size [aria-checked=true]")
        self.assertEqual(self.key(page, "ArrowRight")["at"], "0")
        page.keyboard.press("Escape")
        self.open_ladder(page)
        page.evaluate("document.querySelector('#c-levels [data-level=env]').disabled = true")
        self.assertEqual(self.key(page, "ArrowRight")["at"], "raw")


class SegmentKeysFirefox(SegmentKeys):
    """The same walks in Firefox."""

    BROWSER_ENGINE = "firefox"

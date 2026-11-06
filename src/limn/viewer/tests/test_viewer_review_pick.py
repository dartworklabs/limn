"""Confirming several pins awaiting review from their result rows (ADR-0035, docs/handbook/viewer.md §스레드와 검토).

The review section's [골라서 확인] turns its cards into result rows; a person ticks the rows whose result they have read
and [N건 확인] confirms them together, each with the done_at its row showed when it was ticked, through the one-pin route
after one undo row. ReviewPickFlows drives that in the real viewer against the in-process server as a person (Alice);
ReviewPickLayout measures the rows and the head's pick line against the design system on the four device classes;
ReviewPickOutcome runs the pure outcome and banner functions under node.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_review_pick.py
"""

import json
import os
import re
import shutil
import unittest
from urllib.parse import urlparse

from limn.pins.lifecycle import input as lifecycle_input
from limn.pins.lifecycle.rules import CloseRequest
from limn.pins.listing.projection import pin_state
from limn.security.access import LOCAL_ACTOR

from helpers import add_pin, edit_stored, extract_js_fn, find_record, js_i18n, ps, run_node
from helpers_access import ALICE, actor
from helpers_authority import post_authority
from helpers_browser import MEASURE, BrowserBase, fonts_ready, settle

A = actor(ALICE)
TOL = 0.5  # how far two edges or centres the design system lines up may differ, in CSS px
UNDO = "되돌리기"
# Records the viewer's POST /api/pins/<id>/confirm requests in window.CONFIRMS as {id, body, keepalive}, as they start.
RECORD_CONFIRMS = (
    "(()=>{window.CONFIRMS=[];const f=window.fetch;window.fetch=function(u,o){"
    "const m=/\\/api\\/pins\\/(\\d+)\\/confirm/.exec(String(u));"
    "if(m)window.CONFIRMS.push({id:+m[1],body:o&&o.body?JSON.parse(o.body):null,keepalive:!!(o&&o.keepalive)});"
    "return f.call(this,u,o);};})()"
)
# First-visit hints seen before the viewer boots, so no coach banner stands over the list.
SEEN = "try{localStorage.setItem('pinPrefs',%s);}catch(e){}" % json.dumps(
    json.dumps({"coach": {"touch": 1, "mouse": 1, "sel": 1, "side": 1}})
)
# The device classes a screen change is shown on (docs/handbook/workflow.md §화면 변경은 PoC를 먼저 보인다).
DEVICES = {
    "desktop": {"viewport": {"width": 1440, "height": 900}},
    "desktop-mid": {"viewport": {"width": 1024, "height": 768}},
    "tablet": {"viewport": {"width": 768, "height": 1024}, "is_mobile": True, "has_touch": True},
    "fold": {"viewport": {"width": 673, "height": 841}, "is_mobile": True, "has_touch": True},
    "phone": {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True},
}


class ReviewPickBase(BrowserBase):
    """Five of Alice's pins an agent closed: three with a reply (one with a reference), one with changed lines only, and
    one with nothing said - whose row has no result. A confirm to a pin in self.unreached is aborted, as a request that
    never reached the server."""

    def setUp(self):
        """The five pins awaiting review, and the viewer's identity Alice in the people directory."""
        super().setUp()
        ps.APP.people_directory.record(A)
        self.unreached = set()
        made = []
        for lo, note in ((4, "alpha"), (11, "beta"), (18, "gamma"), (25, "delta"), (30, "epsilon")):
            made.append(add_pin({"file": str(self.main), "lo": lo, "hi": lo, "page": 1, "note": note}, A).record["id"])
        self.p1, self.p2, self.p3, self.p4, self.bare = made
        self.close(self.p1, reply="alpha fixed", ref="PR #9")
        self.close(self.p2, reply="beta fixed")
        self.close(self.p3, changes=(lifecycle_input.CloseChange(str(self.main.resolve()), 18, 19).record(),))
        self.close(self.p4, reply="delta fixed")
        self.close(self.bare)

    def close(self, pid, **request):
        """Close pin pid as the agent would (it then awaits review), with request's reply, ref and changes."""
        store = ps.APP.pin_lifecycle.context().store
        ps.APP.pin_lifecycle.close_pin(
            pid, post_authority(store, dict(LOCAL_ACTOR), "close", pid), CloseRequest(**request)
        )

    def route(self, route):
        """BrowserBase's routing, except that a confirm of a pin in self.unreached is aborted (no answer)."""
        m = re.fullmatch(r"/api/pins/(\d+)/confirm", urlparse(route.request.url).path)
        if m and int(m.group(1)) in self.unreached:
            return route.abort()
        return super().route(route)

    def state(self, pid):
        """Pin pid's state on the server."""
        return pin_state(find_record(ps.APP.snapshot_pins(), pid))

    def done_at(self, pid):
        """The done_at of pin pid's close on the server."""
        return find_record(ps.APP.snapshot_pins(), pid)["done_at"]

    def review_page(self, **device):
        """The viewer as Alice with the pin panel and the review section open, recording its confirms (RECORD_CONFIRMS)."""
        page = self.open(0, init=SEEN + RECORD_CONFIRMS, **(device or DEVICES["desktop"]))
        page.evaluate("setSide(true); SEC.review=true; drawPins()")
        settle(page)
        return page

    def pick(self, page):
        """Press [골라서 확인] and wait for the pick line."""
        page.click("#review-pick")
        page.wait_for_selector("#rv-bar:not([hidden])")
        settle(page)

    def tick(self, page, *pids):
        """Tick (or clear) the rows of pids by pressing their boxes' labels - the press area, which on touch reaches 44px
        round the box over it (.hit)."""
        for pid in pids:
            page.click('#review-pins label.rv-ck:has(input[data-pick="%d"])' % pid)
        settle(page)

    def ticked(self, page):
        """The ids of the ticked rows as drawn."""
        return page.evaluate("[...document.querySelectorAll('#review-pins .rv-row.on')].map(r=>+r.dataset.id)")

    def send_now(self, page):
        """Close the undo row of [N건 확인] with its [x], which sends at once."""
        page.click(".nt:has-text('%s') [data-act=notice-x]" % UNDO)


class ReviewPickFlows(ReviewPickBase):
    """Picking, confirming, undoing, the refusals and the retry, the keyboard alone and a redraw, in the real viewer."""

    def test_rows_show_each_result_and_a_pin_closed_without_one_cannot_be_ticked(self):
        """Every review pin is a row: the explanation, its reference and changed lines are on it; the pin closed with nothing
        said has its box disabled and offers [카드에서 확인]. Each box is described by its own explanation. [모두 고르기]
        counts the four rows with a result, [확인] waits for a tick, and the head's toggle keeps its name, pressed."""
        page = self.review_page()
        self.pick(page)
        rows = page.evaluate(
            """() => [...document.querySelectorAll('#review-pins .rv-row')].map(r => {const box = r.querySelector('input');
              return {id: +r.dataset.id, text: r.innerText, disabled: box.disabled,
                described: document.getElementById(box.getAttribute('aria-describedby')) === r.querySelector('.rv-ans')};})"""
        )
        by = {r["id"]: r for r in rows}
        self.assertEqual(sorted(by), sorted([self.p1, self.p2, self.p3, self.p4, self.bare]))
        self.assertIn("alpha fixed", by[self.p1]["text"])
        self.assertIn("PR #9", by[self.p1]["text"])
        self.assertIn("바뀐 줄 L18-L19", by[self.p3]["text"])
        self.assertIn("설명 없음", by[self.p3]["text"])
        self.assertIn("설명 없이 닫힘", by[self.bare]["text"])
        self.assertIn("카드에서 확인", by[self.bare]["text"])
        self.assertEqual([r["id"] for r in rows if r["disabled"]], [self.bare])
        self.assertTrue(all(r["described"] for r in rows))
        self.assertIn("모두 고르기 (4)", page.inner_text("#rv-bar"))
        self.assertTrue(page.is_disabled("#rv-go"))
        self.assertEqual(page.get_attribute("#review-pick", "aria-pressed"), "true")
        self.assertEqual(page.inner_text("#review-pick").strip(), "골라서 확인")

    def test_the_head_button_needs_two_listed_pins_and_a_person_who_may_confirm(self):
        """[골라서 확인] is there for a person who may confirm while two or more pins are listed. A viewer-only person has
        none, and a pick ends (cards again) when the list falls to one pin."""
        page = self.review_page()
        self.assertTrue(page.is_visible("#review-pick"))
        page.evaluate("META.me.role=ROLE.VIEWER; drawPins()")
        self.assertFalse(page.is_visible("#review-pick"))
        page.evaluate("META.me.role=ROLE.EDITOR; drawPins()")
        self.pick(page)
        store = ps.APP.pin_lifecycle.context().store
        for pid in (self.p2, self.p3, self.p4, self.bare):
            ps.APP.pin_lifecycle.confirm_pin(pid, post_authority(store, A, "confirm", pid))
        page.evaluate("loadPins()")
        page.wait_for_selector('#review-pins .pin.card[data-id="%d"]' % self.p1)
        self.assertFalse(page.is_visible("#review-pick"))
        self.assertFalse(page.is_visible("#rv-bar"))
        self.assertEqual(page.evaluate("RV_PICK"), None)

    def test_collapsing_the_section_ends_the_pick_and_picking_opens_it_again(self):
        """Folding the section away while picking ends the pick (its rows are not there to read, so [N건 확인] goes too);
        [골라서 확인] on the folded head opens the section, remembered, and picks."""
        page = self.review_page()
        self.pick(page)
        self.tick(page, self.p1)
        page.click("#review-toggle")
        settle(page)
        self.assertEqual(page.evaluate("[RV_PICK, SEC.review]"), [None, False])
        self.assertFalse(page.is_visible("#rv-bar"))
        self.pick(page)
        self.assertEqual(page.evaluate("[SEC.review, prefs().sec.review, RV_PICK.size]"), [True, True, 0])
        self.assertEqual(page.locator("#review-pins .rv-row").count(), 5)

    def test_pick_all_ticks_every_row_with_a_result_and_a_partial_pick_shows_half_ticked(self):
        """[모두 고르기] ticks the four rows with a result, not the one without; clearing one leaves it half ticked, and
        pressing it then ticks them all again. The count and [N건 확인] follow."""
        page = self.review_page()
        self.pick(page)
        page.click("label.rv-all")
        settle(page)
        self.assertCountEqual(self.ticked(page), [self.p1, self.p2, self.p3, self.p4])
        self.assertEqual(page.inner_text("#rv-go").strip(), "4건 확인")
        self.assertEqual(page.evaluate("[$('#rv-all').checked,$('#rv-all').indeterminate]"), [True, False])
        self.tick(page, self.p2)
        self.assertEqual(page.evaluate("[$('#rv-all').checked,$('#rv-all').indeterminate]"), [False, True])
        self.assertEqual(page.inner_text("#rv-go").strip(), "3건 확인")
        page.click("label.rv-all")
        settle(page)
        self.assertCountEqual(self.ticked(page), [self.p1, self.p2, self.p3, self.p4])

    def test_confirm_waits_for_its_undo_then_sends_each_ticked_pin_with_the_close_its_row_showed(self):
        """[N건 확인] takes the ticked rows off at once and the rest stay picking; one undo row stands at the section's top,
        in view under its head, and takes the focus; nothing is sent while it stands. When it goes, each ticked pin gets
        one confirm with the done_at its row showed, kept alive, and both are done, confirmed by Alice; the rest still
        await review."""
        page = self.review_page()
        self.pick(page)
        self.tick(page, self.p1, self.p2)
        page.click("#rv-go")
        page.wait_for_selector(".nt:has-text('핀 2건 확인')")
        self.assertTrue(page.evaluate("document.activeElement.matches('.nt .nt-act')"))
        self.assertEqual(page.evaluate("RV_PICK&&RV_PICK.size"), 0)
        self.assertEqual(page.locator("#review-pins .rv-row").count(), 3)
        shown = page.evaluate(
            """() => {const n = document.querySelector('#review-pins .nt').getBoundingClientRect(),
              h = document.querySelector('#sec-review>.sec-head').getBoundingClientRect(),
              s = document.querySelector('#list').getBoundingClientRect();
              return n.top >= h.bottom - 0.5 && n.bottom <= s.bottom + 0.5;}"""
        )
        self.assertTrue(shown, "the undo row is in view, under the section's head")
        self.assertEqual(page.evaluate("CONFIRMS"), [])
        self.send_now(page)
        page.wait_for_function("CONFIRMS.length===2")
        sent = page.evaluate("CONFIRMS")
        self.assertCountEqual([c["id"] for c in sent], [self.p1, self.p2])
        for c in sent:
            with self.subTest(pin=c["id"]):
                self.assertEqual(c["body"], {"done_at": self.done_at(c["id"])})
                self.assertTrue(c["keepalive"])
        page.wait_for_function(
            "CONFIRMING.size===0&&DONE_ALL.filter(p=>[%d,%d].includes(p.id)).length===2" % (self.p1, self.p2)
        )
        for pid in (self.p1, self.p2):
            record = find_record(ps.APP.snapshot_pins(), pid)
            self.assertEqual((pin_state(record), record["confirmed_by"]["login"]), ("done", A["login"]))
        self.assertEqual([self.state(p) for p in (self.p3, self.p4, self.bare)], ["review"] * 3)

    def test_its_undo_sends_nothing_and_brings_back_the_rows_with_their_ticks(self):
        """[되돌리기] on the undo row sends nothing: the pins come back as ticked rows of a pick, the focus on [N건 확인]."""
        page = self.review_page()
        self.pick(page)
        self.tick(page, self.p1, self.p2)
        page.click("#rv-go")
        page.click(".nt:has-text('%s') [data-act=notice-act]" % UNDO)
        page.wait_for_selector("#rv-bar:not([hidden])")
        settle(page)
        self.assertCountEqual(self.ticked(page), [self.p1, self.p2])
        self.assertEqual(page.evaluate("document.activeElement.id"), "rv-go")
        self.assertEqual(page.evaluate("[CONFIRMS.length,DEFERRED.size,CONFIRMING.size]"), [0, 0, 0])
        self.assertEqual([self.state(p) for p in (self.p1, self.p2)], ["review", "review"])

    def test_its_undo_joins_the_ticks_of_a_pick_made_meanwhile(self):
        """Ticks made while the undo row stands stay when it is used: the pins it brings back join them, so [N건 확인]
        then confirms both - it never swaps a new pick for the one just taken back."""
        page = self.review_page()
        self.pick(page)
        self.tick(page, self.p1, self.p2)
        page.click("#rv-go")
        self.tick(page, self.p3)
        page.click(".nt:has-text('%s') [data-act=notice-act]" % UNDO)
        page.wait_for_selector('#review-pins .rv-row[data-id="%d"]' % self.p1)
        settle(page)
        self.assertCountEqual(self.ticked(page), [self.p1, self.p2, self.p3])
        self.assertEqual(page.inner_text("#rv-go").strip(), "3건 확인")
        self.assertEqual(page.evaluate("CONFIRMS.length"), 0)

    def test_a_row_without_a_result_leads_to_its_card(self):
        """[카드에서 확인] on the row of a pin closed with nothing said ends the pick and puts the focus on that pin's [확인]
        in its card - on a phone, whose cards are folded, the card unfolded and in view."""
        page = self.review_page(**DEVICES["phone"])
        self.pick(page)
        page.click('#review-pins .rv-row[data-id="%d"] [data-act=rv-card]' % self.bare)
        settle(page)
        self.assertEqual(page.evaluate("RV_PICK"), None)
        got = page.evaluate(
            """id => {const a = document.activeElement, r = a.getBoundingClientRect(),
              s = document.querySelector('#right').getBoundingClientRect();
              return [a.matches('.pin[data-id="' + id + '"] [data-act=confirm]'),
                r.height > 0 && r.top >= s.top && r.bottom <= s.bottom];}""",
            self.bare,
        )
        self.assertEqual(got, [True, True])

    def test_the_undo_row_shows_after_a_confirm_from_far_down_a_long_list(self):
        """[N건 확인] pressed in the stuck head with the list read far down (a phone, thirteen rows): the undo row - the
        section's first - is brought into view under the head, so its six seconds are not spent out of sight."""
        for lo in range(5, 37, 4):
            pid = add_pin({"file": str(self.main), "lo": lo, "hi": lo, "page": 1, "note": "more %d" % lo}, A).record[
                "id"
            ]
            self.close(pid, reply="fixed %d" % lo)
        page = self.review_page(**DEVICES["phone"])
        self.pick(page)
        last = page.evaluate("+[...document.querySelectorAll('#review-pins .rv-row')].pop().dataset.id")
        self.tick(page, last)
        page.evaluate("document.querySelector('#right').scrollTop = 1e6")
        settle(page)
        page.click("#rv-go")
        page.wait_for_selector(".nt:has-text('핀 1건 확인')")
        settle(page)
        shown = page.evaluate(
            """() => {const n = document.querySelector('#review-pins .nt').getBoundingClientRect(),
              h = document.querySelector('#sec-review>.sec-head').getBoundingClientRect(),
              s = document.querySelector('#right').getBoundingClientRect();
              return [n.top >= h.bottom - 0.5, n.bottom <= s.bottom + 0.5];}"""
        )
        self.assertEqual(shown, [True, True])

    def test_a_pin_closed_again_or_reopened_after_its_row_was_ticked_is_left_and_the_banner_says_why(self):
        """A row ticked, then its pin closed again by the agent (another done_at) or reopened by a person's reply: those
        confirms answer 409 and are not made, the other is, and one warning banner on the review section names each
        with why and offers [변경 보기]."""
        edit_stored(lambda rows: [r.update(done_at="2020-01-01 00:00:00") for r in rows if r["id"] == self.p1])
        page = self.review_page()
        self.pick(page)
        self.tick(page, self.p1, self.p2, self.p4)
        store = ps.APP.pin_lifecycle.context().store
        ps.APP.pin_lifecycle.reopen_pin(self.p1, post_authority(store, dict(LOCAL_ACTOR), "reopen", self.p1))
        self.close(self.p1, reply="alpha fixed again")
        ps.APP.pin_lifecycle.reply_pin(self.p2, "아직 아닙니다", post_authority(store, A, "reply", self.p2))
        page.click("#rv-go")
        self.send_now(page)
        banner = page.wait_for_selector(".nt-banner.nk-warn[role=alert]:has-text('3건 중 1건 확인')", timeout=10000)
        text = banner.inner_text()
        self.assertIn("#%d 다시 닫힘(새 결과를 보고 확인)" % self.p1, text)
        self.assertIn("#%d 그사이 다시 열림" % self.p2, text)
        self.assertIn("변경 보기", text)
        self.assertEqual([self.state(p) for p in (self.p1, self.p2, self.p4)], ["review", "open", "done"])

    def test_a_confirm_that_did_not_reach_the_server_is_sent_again_by_retry_with_the_same_close(self):
        """A confirm with no answer leaves its pin awaiting review and back in the picking list; an error banner names it
        and its [다시 시도] sends that pin alone again, with the done_at its row showed."""
        self.unreached.add(self.p2)
        page = self.review_page()
        self.pick(page)
        self.tick(page, self.p1, self.p2)
        page.click("#rv-go")
        self.send_now(page)
        banner = page.wait_for_selector(".nt-banner.nk-err[role=alert]:has-text('2건 중 1건 확인')", timeout=10000)
        self.assertIn("#%d 서버에 닿지 않아 보내지 못함" % self.p2, banner.inner_text())
        page.wait_for_selector('#review-pins .rv-row[data-id="%d"]' % self.p2)
        self.assertEqual((self.state(self.p1), self.state(self.p2)), ("done", "review"))
        self.unreached.clear()
        page.click(".nt-banner.nk-err [data-act=notice-act]")
        page.wait_for_function("CONFIRMS.length===3&&CONFIRMING.size===0")
        settle(page)
        first, again = [c for c in page.evaluate("CONFIRMS") if c["id"] == self.p2]
        self.assertEqual(again["body"], first["body"])
        self.assertEqual(again["body"], {"done_at": self.done_at(self.p2)})
        self.assertEqual(self.state(self.p2), "done")

    def test_hiding_the_page_starts_every_confirm_at_once(self):
        """When the page is hidden while the undo row stands (a tab switched, a window closed), every confirm starts in
        that same moment - not one after another's answer, which a closing page would never wait for."""
        page = self.review_page()
        self.pick(page)
        self.tick(page, self.p1, self.p2, self.p4)
        page.click("#rv-go")
        started = page.evaluate(
            "()=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});"
            "document.dispatchEvent(new Event('visibilitychange')); return CONFIRMS.map(c=>c.id);}"
        )
        self.assertCountEqual(started, [self.p1, self.p2, self.p4])
        page.wait_for_function("CONFIRMING.size===0")
        self.assertEqual([self.state(p) for p in (self.p1, self.p2, self.p4)], ["done"] * 3)

    def test_the_keyboard_alone_picks_ticks_confirms_undoes_and_ends(self):
        """Enter on [골라서 확인] picks and puts the focus on [모두 고르기]; Space ticks all; Tab goes to [N건 확인], then
        through the rows in order - the first row (no result) offers [카드에서 확인] and [변경 보기], the next its box
        (Space clears it) and its [변경 보기]; Enter on [N건 확인] confirms and puts the focus on the undo; Enter undoes;
        Esc ends the pick, the focus back on [골라서 확인]."""
        page = self.review_page()
        page.keyboard.press("Shift")
        page.focus("#review-pick")
        page.keyboard.press("Enter")
        page.wait_for_selector("#rv-bar:not([hidden])")
        self.assertEqual(page.evaluate("document.activeElement.id"), "rv-all")
        page.keyboard.press("Space")
        settle(page)
        self.assertEqual(len(self.ticked(page)), 4)
        page.keyboard.press("Tab")
        self.assertEqual(page.evaluate("document.activeElement.id"), "rv-go")
        here = "[+document.activeElement.closest('.rv-row').dataset.id, document.activeElement.dataset.act||'box']"
        rows = page.evaluate("[...document.querySelectorAll('#review-pins .rv-row')].map(r=>+r.dataset.id)")
        self.assertEqual(rows[0], self.bare)
        first = rows[1]
        page.keyboard.press("Tab")
        self.assertEqual(page.evaluate(here), [self.bare, "rv-card"])
        page.keyboard.press("Tab")
        self.assertEqual(page.evaluate(here), [self.bare, "change"])
        page.keyboard.press("Tab")
        self.assertEqual(page.evaluate(here), [first, "box"])
        page.keyboard.press("Space")
        settle(page)
        self.assertNotIn(first, self.ticked(page))
        self.assertEqual(page.evaluate(here), [first, "box"])
        page.keyboard.press("Tab")
        self.assertEqual(page.evaluate(here), [first, "change"])
        for _ in range(4):
            page.keyboard.press("Shift+Tab")
        self.assertEqual(page.evaluate("document.activeElement.id"), "rv-go")
        page.keyboard.press("Enter")
        page.wait_for_selector(".nt:has-text('핀 3건 확인')")
        self.assertTrue(page.evaluate("document.activeElement.matches('.nt .nt-act')"))
        page.keyboard.press("Enter")
        page.wait_for_selector("#rv-bar:not([hidden])")
        settle(page)
        self.assertEqual(len(self.ticked(page)), 3)
        self.assertEqual(page.evaluate("document.activeElement.id"), "rv-go")
        page.keyboard.press("Escape")
        settle(page)
        self.assertEqual(page.evaluate("[document.activeElement.id, RV_PICK]"), ["review-pick", None])
        self.assertEqual(page.get_attribute("#review-pick", "aria-pressed"), "false")
        self.assertEqual(page.evaluate("CONFIRMS.length"), 0)

    def test_a_jump_to_the_section_leaves_its_first_card_or_row_under_its_head_on_a_phone(self):
        """[검토 M] (gotoReview) and [골라서 확인] bring the review section to the top of the phone's sheet with its head
        under the stuck tool bar and the first card - or the first row - wholly under the head, not behind it."""
        page = self.review_page(**DEVICES["phone"])
        under = """sel => {const h = document.querySelector('#sec-review>.sec-head').getBoundingClientRect(),
          f = document.querySelector(sel).getBoundingClientRect(), bar = document.querySelector('#bar1').getBoundingClientRect();
          return [h.top >= bar.bottom - 0.5, f.top >= h.bottom - 0.5];}"""
        page.evaluate("document.querySelector('#right').scrollTop = 0; gotoReview()")
        settle(page)
        self.assertEqual(page.evaluate(under, "#review-pins .pin.card"), [True, True])
        page.evaluate("document.querySelector('#right').scrollTop = 0")
        self.pick(page)
        self.assertEqual(page.evaluate(under, "#review-pins .rv-row"), [True, True])

    def test_a_redraw_keeps_the_focus_and_the_ticks(self):
        """The list's redraw (the five-second sync) draws the rows anew: the focused box keeps the focus and every tick
        stays."""
        page = self.review_page()
        self.pick(page)
        self.tick(page, self.p1)
        page.keyboard.press("Shift")
        page.focus('#review-pins input[data-pick="%d"]' % self.p2)
        page.keyboard.press("Space")
        settle(page)
        page.evaluate("loadPins().then(()=>drawPins())")
        settle(page)
        self.assertEqual(page.evaluate("+document.activeElement.dataset.pick"), self.p2)
        self.assertCountEqual(self.ticked(page), [self.p1, self.p2])


# The readings ReviewPickLayout holds to the design system, from MEASURE's label and hit (window.__m).
GEOMETRY = """() => {
  const R = e => {const b = e.getBoundingClientRect(); return {x: b.left, r: b.right, t: b.top, b: b.bottom, w: b.width, h: b.height,
    cx: b.left + b.width / 2, cy: b.top + b.height / 2};};
  const q = s => document.querySelector(s), hitH = e => {const h = __m.hit(e); return h.t + h.b;};
  const box = q('#rv-all'), go = q('#rv-go'), lbl = q('label.rv-all');
  const out = {chev: R(q('#review-toggle .ic')), pick: R(q('#review-pick')), head: R(q('#sec-review>.sec-head')),
    all: R(box), go: R(go), goInk: __m.label(go, box), allInk: __m.label(lbl.querySelector('.lbl'), box),
    allHit: hitH(lbl), goHit: hitH(go), pickHit: hitH(q('#review-pick')),
    bar: {sw: q('#rv-bar').scrollWidth, cw: q('#rv-bar').clientWidth}, pins: R(q('#review-pins')),
    list: {sw: q('#list').scrollWidth, cw: q('#list').clientWidth}, rows: []};
  for (const row of document.querySelectorAll('#review-pins .rv-row')) {
    const b = row.querySelector('input[data-pick]'), h = row.querySelector('.rv-h'), chg = row.querySelector('.rv-chg');
    row.scrollIntoView({block: 'end'});   // its press areas are read where the stuck head does not cover it (a short sheet has no room to centre it)
    out.rows.push({id: +row.dataset.id, row: R(row), box: R(b), h: R(h), chg: R(chg), keys: [...row.querySelectorAll('.rv-k')].map(R),
      ask: R(row.querySelector('.rv-ask')), ans: R(row.querySelector('.rv-ans')), label: R(row.querySelector('label.rv-ck')),
      ink: __m.label(h, b), chgInk: __m.label(chg, b), labelHit: hitH(row.querySelector('label.rv-ck')), chgHit: hitH(chg),
      card: row.querySelector('[data-act=rv-card]') ? Object.assign(R(row.querySelector('[data-act=rv-card]')),
        {hit: hitH(row.querySelector('[data-act=rv-card]'))}) : null,
      sw: row.scrollWidth, cw: row.clientWidth});}
  return out;}"""
# The drawn look of the boxes and the colours they stand in, in the theme on screen. Colours are read through a canvas, so
# any colour the browser computes (color-mix, oklab) comes back as 8-bit sRGB; a row's surface is its tint over the panel.
LOOKS = """() => {
  const c = document.createElement('canvas').getContext('2d', {willReadFrequently: true});
  const rgba = s => {c.clearRect(0, 0, 1, 1); c.fillStyle = '#000'; c.fillStyle = s; c.fillRect(0, 0, 1, 1);
    const d = c.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255];};
  const over = (f, b) => [0, 1, 2].map(i => f[i] * f[3] + b[i] * (1 - f[3])).concat([1]);
  const lum = p => {const l = p.slice(0, 3).map(v => {v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;});
    return 0.2126 * l[0] + 0.7152 * l[1] + 0.0722 * l[2];};
  const ratio = (a, b) => {const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);};
  const panel = rgba(getComputedStyle(document.querySelector('#right')).backgroundColor);
  const surface = row => over(rgba(getComputedStyle(row).backgroundColor), panel);
  const look = (input, row) => {const s = getComputedStyle(input), bg = surface(row), edge = over(rgba(s.borderTopColor), bg);
    const fill = over(rgba(s.backgroundColor), bg), ic = input.parentElement.querySelector('.ic:not([style*=hidden])');
    return {w: parseFloat(s.width), h: parseFloat(s.height), radius: s.borderTopLeftRadius, border: s.borderTopWidth,
      edge: ratio(edge, bg), fill: ratio(fill, bg),
      tick: input.checked || input.indeterminate ? ratio(rgba(getComputedStyle(input.parentElement.querySelector(
        input.indeterminate ? '.ic-minus' : '.ic-check')).color), fill) : null};};
  const on = document.querySelector('#review-pins .rv-row.on'), off = document.querySelector('#review-pins .rv-row:not(.on):not(.off)');
  return {ticked: look(on.querySelector('input'), on), clear: look(off.querySelector('input'), off),
    half: look(document.querySelector('#rv-all'), document.querySelector('#sec-review>.sec-head'))};}"""
# Elements in the review section with a visible border on all four sides inside another such element (§한 겹 담기).
NESTED = """() => {const four = e => {const s = getComputedStyle(e);
    return ['Top', 'Right', 'Bottom', 'Left'].every(k => parseFloat(s['border' + k + 'Width']) > 0 && s['border' + k + 'Style'] !== 'none'
      && !/rgba\\(.*, 0\\)$|transparent/.test(s['border' + k + 'Color']));};
  const root = document.querySelector('#sec-review'), bad = [];
  for (const e of root.querySelectorAll('*')) {if (e.matches('input') || !four(e)) continue;
    for (let a = e.parentElement; a && a !== root; a = a.parentElement) if (four(a)) {bad.push(e.className + ' in ' + a.className); break;}}
  return bad;}"""


class ReviewPickLayout(ReviewPickBase):
    """The pick line and the result rows against the design system (docs/handbook/viewer.md §컴포넌트 규격, §글자 가운데,
    §한 겹 담기) on a desktop, a tablet, an unfolded foldable and a phone, in the bundled font: one box column centred
    under the head's chevron, the rows' text on one line under #N, '요청' and '답' on one column, one right edge for the
    head's buttons and the rows' [변경 보기], every control centred on its line's cap height, whole-pixel heights, press
    areas of 24px (mouse) or 44px (touch), nothing wider than the panel, no box in a box, and boxes whose edge and tick
    read at 3:1 in both themes."""

    def picked(self, device):
        """The viewer on device picking, one row ticked and MEASURE installed. The head's first line stands where it
        stood before the pick: the pick line under it does not move the toggle or the button that started it."""
        page = self.review_page(**device)
        self.assertEqual(fonts_ready(page), "loaded")
        line = (
            "['#review-toggle','#review-pick'].map(s=>document.querySelector(s).getBoundingClientRect().top-"
            "document.querySelector('#sec-review>.sec-head').getBoundingClientRect().top)"
        )
        before = page.evaluate(line)
        self.pick(page)
        self.assertEqual(page.evaluate(line), before, "the head's first line moved")
        self.tick(page, self.p4)
        page.evaluate(MEASURE)
        page.mouse.move(1, 1)
        settle(page)
        return page

    def test_the_rows_and_the_pick_line_line_up_on_every_device(self):
        """The alignment rules of the spec, measured on the four device classes."""
        for name, device in DEVICES.items():
            with self.subTest(device=name):
                page = self.picked(device)
                touch = bool(device.get("has_touch"))
                need = 44 if touch else 24
                g = page.evaluate(GEOMETRY)
                self.assertEqual(len(g["rows"]), 5)
                chev_cx = g["chev"]["cx"]
                self.assertAlmostEqual(g["all"]["cx"], chev_cx, delta=TOL, msg="the bar's box under the chevron")
                for row in g["rows"]:
                    where = "%s row #%d" % (name, row["id"])
                    self.assertAlmostEqual(row["box"]["x"], g["all"]["x"], delta=TOL, msg=where + ": one box column")
                    self.assertAlmostEqual(row["keys"][0]["x"], row["h"]["x"], delta=TOL, msg=where + ": text under #N")
                    self.assertAlmostEqual(row["keys"][1]["x"], row["h"]["x"], delta=TOL, msg=where)
                    self.assertAlmostEqual(row["ask"]["x"], row["ans"]["x"], delta=TOL, msg=where + ": 요청 and 답")
                    self.assertAlmostEqual(row["chg"]["r"], g["go"]["r"], delta=TOL, msg=where + ": right edge")
                    self.assertAlmostEqual(abs(row["ink"]["cap"]), 0, delta=TOL, msg=where + ": #N's caps on the box")
                    self.assertAlmostEqual(abs(row["ink"]["digits"]), 0, delta=TOL, msg=where + ": #N's digits")
                    self.assertAlmostEqual(
                        abs(row["chgInk"]["cap"]), 0, delta=TOL, msg=where + ": [변경 보기] on the box"
                    )
                    self.assertAlmostEqual(abs(row["chgInk"]["hangul"]), 0, delta=TOL, msg=where + ": its Hangul")
                    self.assertEqual(row["box"]["w"], 16, where)
                    self.assertEqual(row["box"]["h"], 16, where)
                    self.assertEqual(row["label"]["h"], round(row["label"]["h"]), where + ": whole px")
                    self.assertEqual(row["chg"]["h"], round(row["chg"]["h"]), where + ": whole px")
                    self.assertEqual(row["row"]["h"], round(row["row"]["h"]), where + ": the next row on a whole px")
                    self.assertGreaterEqual(row["labelHit"], need - TOL, where + ": the box's press area")
                    self.assertGreaterEqual(row["chgHit"], need - TOL, where + ": [변경 보기]'s press area")
                    self.assertEqual((row["label"]["h"], row["chg"]["h"]), (24, 24), where + ": the first line is 24px")
                    self.assertAlmostEqual(
                        row["row"]["x"], g["pins"]["x"], delta=TOL, msg=where + ": across the content"
                    )
                    self.assertAlmostEqual(
                        row["row"]["r"], g["pins"]["r"], delta=TOL, msg=where + ": across the content"
                    )
                    self.assertLessEqual(row["sw"], row["cw"], where + ": nothing wider than the row")
                    if row["card"]:  # [카드에서 확인] stands on the first line with [변경 보기]
                        self.assertEqual(row["card"]["h"], 24, where + ": [카드에서 확인] on the first line")
                        self.assertAlmostEqual(row["card"]["cy"], row["box"]["cy"], delta=TOL, msg=where)
                        self.assertGreaterEqual(
                            row["card"]["hit"], need - TOL, where + ": [카드에서 확인]'s press area"
                        )
                self.assertAlmostEqual(g["go"]["r"], g["pick"]["r"], delta=TOL, msg=name + ": the head's right edge")
                self.assertAlmostEqual(abs(g["allInk"]["cap"]), 0, delta=TOL, msg=name + ": [모두 고르기] on its box")
                self.assertAlmostEqual(abs(g["allInk"]["hangul"]), 0, delta=TOL, msg=name + ": its Hangul")
                self.assertAlmostEqual(
                    abs(g["goInk"]["cap"]), 0, delta=TOL, msg=name + ": [N건 확인] on the box's line"
                )
                for key in ("allHit", "goHit", "pickHit"):
                    self.assertGreaterEqual(g[key], need - TOL, "%s: %s" % (name, key))
                self.assertLessEqual(g["bar"]["sw"], g["bar"]["cw"], name + ": the pick line on one line")
                self.assertLessEqual(g["go"]["b"], g["head"]["b"] + TOL, name + ": [N건 확인] in the head")
                self.assertLessEqual(g["list"]["sw"], g["list"]["cw"], name + ": nothing wider than the list")
                self.assertEqual(page.evaluate(NESTED), [], name)
                page.context.close()

    def test_the_boxes_read_at_3_to_1_and_are_drawn_to_the_token_in_both_themes(self):
        """A clear box's edge, a ticked box's fill and the tick or the half-tick mark read at 3:1 against what they stand
        on (WCAG 1.4.11) in the light and the dark theme; every box is --check (16px) with --radius-sm and a 1px edge."""
        page = self.picked(DEVICES["desktop"])
        self.tick(page, self.p1)  # two of four ticked: [모두 고르기] is half ticked
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                page.evaluate("t=>setTheme(t)", theme)
                page.evaluate("()=>document.getAnimations().forEach(a=>a.finish())")
                settle(page)
                looks = page.evaluate(LOOKS)
                for key, look in looks.items():
                    where = "%s %s" % (theme, key)
                    self.assertEqual(
                        (look["w"], look["h"], look["radius"], look["border"]), (16, 16, "4px", "1px"), where
                    )
                self.assertGreaterEqual(looks["clear"]["edge"], 3, theme + ": a clear box's edge")
                for key in ("ticked", "half"):
                    self.assertGreaterEqual(looks[key]["fill"], 3, "%s: a %s box's fill" % (theme, key))
                    self.assertGreaterEqual(looks[key]["tick"], 3, "%s: the %s box's mark" % (theme, key))


class ReviewPickOutcome(unittest.TestCase):
    """rvOutcome and rvSaid under node with the real i18n: what each answer of one confirm means, and the banner for a
    send whose confirms did not all go through."""

    def setUp(self):
        """Skip without node, unless LIMN_TEST_REQUIRE_NODE=1 makes that a failure."""
        if not shutil.which("node"):
            if os.environ.get("LIMN_TEST_REQUIRE_NODE") == "1":
                self.fail("node required (LIMN_TEST_REQUIRE_NODE=1) but not installed")
            self.skipTest("node not available")

    def run_js(self, lang, expr):
        """The JSON value of expr, run after the real rvOutcome, rvSaid, pinState and the i18n of lang."""
        js = "\n".join(
            [
                js_i18n(lang),
                extract_js_fn("pinState"),
                re.search(r"const RV_OUT=Object\.freeze\(\{.*?\}\);", open_review_pick(), re.S).group(0),
                extract_js_fn("rvOutcome"),
                extract_js_fn("rvSaid"),
                "console.log(JSON.stringify(%s));" % expr,
            ]
        )
        return json.loads(run_node(js))

    def test_each_answer_of_a_confirm_has_one_outcome(self):
        """200 ok is done; 409 open is reopened; 409 conflict is closed again while the pin still awaits review, done by a
        person otherwise (and closed again when the body has no pin); 200 ok:false is gone; a refusal with a status keeps
        its text; an error without a status is the one [다시 시도] sends again."""
        got = self.run_js(
            "ko",
            """[rvOutcome({status:200,data:{ok:true}}), rvOutcome({status:409,data:{error:'open'}}),
              rvOutcome({status:409,data:{error:'conflict',pin:{state:'review'}}}),
              rvOutcome({status:409,data:{error:'conflict',pin:{state:'done'}}}),
              rvOutcome({status:409,data:{error:'conflict'}}), rvOutcome({status:200,data:{ok:false,pin:null}}),
              rvOutcome(null,{status:403,data:{error:'확인은 사람이 합니다'}}), rvOutcome(null,{})]""",
        )
        self.assertEqual(
            got,
            [
                {"out": "ok"},
                {"out": "reopened"},
                {"out": "closed-again"},
                {"out": "done"},
                {"out": "closed-again"},
                {"out": "gone"},
                {"out": "refused", "why": "확인은 사람이 합니다"},
                {"out": "unreached"},
            ],
        )

    def test_the_banner_names_each_pin_with_why_and_takes_the_kind_of_the_worst(self):
        """All done is no banner. Otherwise 'N건 중 K건 확인 — ' and the pins by kind; an unreached pin makes it an error,
        a closed-again, reopened, gone or refused pin a warning, and pins only done by a person meanwhile an info."""
        got = self.run_js(
            "ko",
            """[rvSaid([{id:1,out:'ok'},{id:2,out:'ok'}]),
              rvSaid([{id:1,out:'ok'},{id:2,out:'closed-again'},{id:3,out:'reopened'},{id:4,out:'unreached'}]),
              rvSaid([{id:1,out:'ok'},{id:5,out:'refused',why:'거절'}]), rvSaid([{id:1,out:'ok'},{id:6,out:'done'}])]""",
        )
        self.assertIsNone(got[0])
        self.assertEqual(
            got[1],
            {
                "msg": "4건 중 1건 확인 — #2 다시 닫힘(새 결과를 보고 확인) · #3 그사이 다시 열림 · #4 서버에 닿지 않아 보내지 못함",
                "kind": "err",
            },
        )
        self.assertEqual(got[2], {"msg": "2건 중 1건 확인 — #5 거절됨: 거절", "kind": "warn"})
        self.assertEqual(got[3], {"msg": "2건 중 1건 확인 — #6 이미 완료로 닫힘", "kind": "info"})

    def test_the_banner_reads_in_english(self):
        """The same banner in English through the table, with one dash: the banner shows what is before it as its title."""
        got = self.run_js("en", "rvSaid([{id:1,out:'ok'},{id:2,out:'closed-again'},{id:4,out:'unreached'}])")
        self.assertEqual(
            got["msg"],
            "Confirmed 1 of 3 — #2 closed again (look at the new result, then confirm) · #4 not sent (the server could not be reached)",
        )


def open_review_pick():
    """The text of review-pick.js."""
    from pathlib import Path

    return (Path(__file__).resolve().parents[1] / "js" / "review-pick.js").read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

"""Messages in context, with no toast (issue #167, docs/handbook/viewer.md §알림 자리).

The viewer has no toast. A success is silent unless it can be undone, and then its undo is where the action was: a chip
'저장됨 [되돌리기]' on the new pin's mark (there with the phone's sheet folded), a row in a deleted card's place. Errors and
conflicts are banners on top of the panel or section concerned, with their action - a failed save right above the save
row, whose button reads [다시 저장]. Background events and first-visit hints go to the status line (on the desktop the
line under the status chips), a background event also with a red dot on the chip that leads to it.

The pure rules run under node with the served functions; the flows run in Chromium against the in-process server
(helpers_browser.BrowserBase) on a phone (411x908, DPR 2.63, touch) and a desktop (1440x900).

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_notices.py
"""

import json
import unittest

from limn.pins.lifecycle.rules import CloseRequest
from limn.pins.listing.projection import pin_state
from limn.security.access import LOCAL_ACTOR

from helpers import add_pin, edit_stored, extract_js_fn, find_record, js_i18n, ps, run_node, trash_records
from helpers_access import ALICE, actor
from helpers_authority import post_authority
from helpers_browser import BrowserBase, settle
from helpers_notices import SCREENS, SEEN, WATCH_TOASTS, node_or_skip

A = actor(ALICE)
# Records the viewer's POST /api/pins/<id>/confirm requests in window.CONFIRMS, before they are sent.
COUNT_CONFIRMS = (
    "(()=>{window.CONFIRMS=[];const f=window.fetch;window.fetch=function(u,o){"
    "if(/\\/api\\/pins\\/\\d+\\/confirm/.test(String(u)))window.CONFIRMS.push(String(u));return f.call(this,u,o);};})()"
)


class PureRules(unittest.TestCase):
    """The decisions of notices.js and of the places that call it, run under node with the served functions."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    def run_js(self, names, body, lang="ko"):
        """Run body after the served functions names (and the Korean or English message functions); its JSON output."""
        return json.loads(run_node("\n".join([js_i18n(lang)] + [extract_js_fn(n) for n in names] + [body])))

    def test_a_message_splits_into_title_and_description_at_the_first_dash_else_the_first_dot(self):
        """'— ' wins over ' · ' (a notification's title keeps its '핀 #10 · 본문'); one without either is all title."""
        got = self.run_js(
            ["msgSplit"],
            "console.log(JSON.stringify(['핀 #3 저장됨 · pins.md 갱신','핀 저장 실패 — 서버에 닿지 않습니다','복사함',"
            "'핀 #10 · 본문 — 서준님이 불렀습니다: 봐 주세요',null].map(msgSplit)));",
        )
        self.assertEqual(
            got,
            [
                ["핀 #3 저장됨", "pins.md 갱신"],
                ["핀 저장 실패", "서버에 닿지 않습니다"],
                ["복사함", ""],
                ["핀 #10 · 본문", "서준님이 불렀습니다: 봐 주세요"],
                ["", ""],
            ],
        )

    def test_one_event_on_two_paths_is_shown_once_and_the_notification_path_wins(self):
        """noticeDupe: a later list-comparison message (rank 1) for an event the notification path (rank 2) already shows
        is suppressed; a notification-path message replaces the list comparison's; the same path's next event, a message
        without keys and one older than 8 seconds are never suppressed."""
        got = self.run_js(
            ["noticeDupe"],
            """const now=100000,m=(keys,rank,at)=>({keys,rank,at:at===undefined?now-1000:at});
            const rv1=m(['review_requested:37'],1),rv2=m(['review_requested:37'],2),old=m(['review_requested:37'],2,now-9000);
            const r=[noticeDupe([rv1],['review_requested:37'],2,now),noticeDupe([rv2],['review_requested:37'],1,now),
              noticeDupe([rv2],['review_requested:37'],2,now),noticeDupe([rv2],[],1,now),noticeDupe([old],['review_requested:37'],1,now),
              noticeDupe([rv2],['reopened:37'],1,now)];
            console.log(JSON.stringify(r.map(x=>[x.skip,x.drop.length])));""",
        )
        self.assertEqual(got, [[False, 1], [True, 0], [False, 0], [False, 0], [False, 0], [False, 0]])

    def test_a_banner_goes_to_the_open_trash_then_its_named_place_then_the_composer_or_the_panel(self):
        """bannerHost: the open Trash takes every banner (the page under it is inert); otherwise the named host; a call
        naming none goes to the composer while one is open, else to the top of the panel."""
        got = self.run_js(
            ["bannerHost"],
            """console.log(JSON.stringify([bannerHost('review',{trashOpen:true,composerOpen:true}),
              bannerHost('review',{trashOpen:false,composerOpen:true}),bannerHost(undefined,{trashOpen:false,composerOpen:true}),
              bannerHost(undefined,{trashOpen:false,composerOpen:false}),bannerHost('line',{trashOpen:false,composerOpen:false})]));""",
        )
        self.assertEqual(got, ["trash", "review", "composer", "list", "line"])

    def test_an_undo_stays_where_it_happened_only_while_that_place_is_on_screen(self):
        """offerSeen: a row or a card note needs the panel open and its section expanded, a Trash row the Trash open; a
        chip is decided by its mark (always true here). Anything else would leave an undo nobody can press."""
        got = self.run_js(
            ["offerSeen"],
            """const v=(s,e,t)=>({sideOpen:s,secOpen:e,trashOpen:t});
            console.log(JSON.stringify([offerSeen('row',v(true,true,false)),offerSeen('row',v(false,true,false)),
              offerSeen('card',v(true,false,false)),offerSeen('trash',v(true,true,false)),offerSeen('trash',v(false,false,true)),
              offerSeen('chip',v(false,false,false))]));""",
        )
        self.assertEqual(got, [True, False, False, False, True, True])

    def test_a_dot_marks_pin_n_only_while_the_panel_is_closed_and_review_m_always(self):
        """noticeDot and notifyDot: [핀 N]'s dot only with the panel closed (an open panel shows the list); [검토 M]'s
        always; a notification's review request marks [검토 M], another event on this document [핀 N], one on another
        document nothing."""
        got = self.run_js(
            ["noticeDot", "notifyDot"],
            """console.log(JSON.stringify([noticeDot('side',true),noticeDot('side',false),noticeDot('rv',true),noticeDot('',false),
              notifyDot('review_requested',false),notifyDot('mention',true),notifyDot('dropped',false)]));""",
        )
        self.assertEqual(got, ["", "side", "rv", "", "rv", "side", ""])

    def test_the_desktop_line_shows_only_messages_and_no_changes(self):
        """statusShown: the compact bands show every status item; the desktop's line only the messages and a rebuild's
        'no changes' - its chips already say the build, connection, sync, staleness and PNG."""
        got = self.run_js(
            ["statusShown"],
            """const L=['notice','failed','building','unchanged','stale','png'].map(kind=>({kind}));
            console.log(JSON.stringify([statusShown(L,false).map(i=>i.kind),statusShown(L,true).map(i=>i.kind)]));""",
        )
        self.assertEqual(got, [["notice", "failed", "building", "unchanged", "stale", "png"], ["notice", "unchanged"]])

    def test_two_boxes_meet_only_when_they_overlap_more_than_an_edge(self):
        """boxesMeet, the test that sends a chip under the select bar to the status line: overlapping boxes meet; boxes
        that only touch along an edge, or lie apart, do not."""
        got = self.run_js(
            ["boxesMeet"],
            """const b=(left,top,right,bottom)=>({left,top,right,bottom}),bar=b(10,10,110,50);
            console.log(JSON.stringify([boxesMeet(b(50,40,90,80),bar),boxesMeet(b(50,50,90,80),bar),boxesMeet(b(110,20,150,40),bar),
              boxesMeet(b(0,0,5,5),bar),boxesMeet(b(0,0,200,200),bar)]));""",
        )
        self.assertEqual(got, [True, False, False, False, True])

    def test_the_line_puts_its_messages_after_a_failure_and_before_the_rest(self):
        """statusList: the line's messages that are not errors (newest first) come after a build failure and a lost
        connection - errors outrank information - and before every other build and sync item."""
        got = self.run_js(
            ["statusProgress", "statusList"],
            """const n1={n:1},n2={n:2};
            const L=statusList({notices:[n2,n1],build:null,buildErr:{state:'fail'},offline:true,sync:null,stale:true,png:false,canRebuild:true,unchanged:null});
            console.log(JSON.stringify(L.map(i=>i.kind+(i.notice?i.notice.n:''))));""",
        )
        self.assertEqual(got, ["failed", "offline", "notice2", "notice1", "stale"])

    def test_a_confirm_conflict_warns_when_closed_again_and_informs_when_already_done(self):
        """confirmConflictKind follows confirmConflictText's rule: a pin still awaiting review (or none, an older server)
        is a warning that asks for a look; a pin a person already closed to done is information with nothing to do."""
        got = self.run_js(
            ["pinState", "confirmConflictText", "confirmConflictKind"],
            """const P=[{id:7,state:'review'},null,{id:7,state:'done'},{id:7,done:true}];
            console.log(JSON.stringify(P.map(p=>[confirmConflictKind(p),confirmConflictText(7,p)])));""",
        )
        self.assertEqual(
            got,
            [
                ["warn", "핀 #7 은 다시 닫혔습니다 — 새 결과를 보고 확인하세요"],
                ["warn", "핀 #7 은 다시 닫혔습니다 — 새 결과를 보고 확인하세요"],
                ["info", "핀 #7 은 이미 완료로 닫혔습니다 — 확인할 것이 없습니다"],
                ["info", "핀 #7 은 이미 완료로 닫혔습니다 — 확인할 것이 없습니다"],
            ],
        )


class NoticeFlows(BrowserBase):
    """Each class of message where it now lives, on the phone and the desktop."""

    WHO = ALICE

    def view(self, screen, init=SEEN, n_open=0):
        """The viewer on screen as Alice, with the toast watch and init (hints seen unless a test passes others)."""
        page = self._page = self.open(n_open, init=WATCH_TOASTS + ";" + init, **SCREENS[screen])
        return page

    def pin(self, lo, note):
        """An open pin by Alice on page 1, lines lo..lo+1, with a box where the mark is drawn; its id."""
        frac = [0.1, 0.05 + 0.1 * (lo % 7), 0.6, 0.03]
        return add_pin(
            {"file": str(self.main), "lo": lo, "hi": lo + 1, "page": 1, "note": note, "frac": frac}, A
        ).record["id"]

    def agent_close(self, pid, reply="고쳤습니다"):
        """The agent closes pin pid (to review) with a reference."""
        store = ps.APP.pin_lifecycle.context().store
        ps.APP.pin_lifecycle.close_pin(
            pid, post_authority(store, dict(LOCAL_ACTOR), "close", pid), CloseRequest(reply=reply, ref="abc1234")
        )

    def state(self, pid):
        """Pin pid's state on the server, or None once it is gone."""
        rec = find_record(ps.APP.snapshot_pins(), pid)
        return pin_state(rec) if rec else None

    def no_toast(self, page):
        """No toast-like element was ever added, and none is on the page."""
        self.assertEqual(page.evaluate("TOASTS_SEEN"), [])
        self.assertFalse(page.evaluate("!!document.querySelector('#toasts,#coach,.toast')"))

    def compose(self, page, note):
        """A selection on page 1 (the test server answers the pick) with note typed in."""
        page.evaluate("LAST_PTR='mouse'; pick({page:1,x0:10,y0:10,x1:200,y1:60})")
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo", timeout=8000)
        page.fill("#note", note)

    def centred(self, page, sel):
        """The vertical distance between the centres of sel's text block (.nt-t) and its buttons (.nt-acts)."""
        return page.evaluate(
            "(()=>{const e=document.querySelector(%s),t=e.querySelector('.nt-t').getBoundingClientRect(),"
            "a=e.querySelector('.nt-acts').getBoundingClientRect();return Math.abs((t.top+t.bottom)/2-(a.top+a.bottom)/2);})()"
            % json.dumps(sel)
        )

    def hit(self, page, sel):
        """The height of the press area of sel: its own box or its ::after, whichever is taller (touch draws ::after)."""
        return page.evaluate(
            "(()=>{const b=document.querySelector(%s),a=getComputedStyle(b,'::after');"
            "return Math.max(b.getBoundingClientRect().height,a.content!=='none'?parseFloat(a.height)||0:0);})()"
            % json.dumps(sel)
        )

    def test_the_main_flows_never_create_a_toast(self):
        """Red first for #167: saving, its undo, a failed save, deleting, completing, confirming, replying, discarding a
        selection, a background close and the first-visit hint run on both screens, and no #toasts, #coach or .toast
        element is ever added or present."""
        for screen in SCREENS:
            with self.subTest(screen=screen):
                self.tearDown()
                self.setUp()
                keep, rv = self.pin(4, "남길 핀"), self.pin(8, "검토할 핀")
                self.agent_close(rv)
                page = self.view(screen, init="", n_open=1)
                self.compose(page, "첫 메모")
                page.evaluate("savePin()")
                settle(page)
                page.evaluate("dropPin(%d,false)" % keep)
                settle(page)
                page.evaluate("restorePin(%d)" % keep)
                settle(page)
                page.evaluate("closePin(%d)" % keep)
                settle(page)
                page.evaluate("confirmPin(%d)" % rv)
                page.evaluate("flushDeferred()")
                settle(page)
                self.compose(page, "버릴 메모")
                page.evaluate("discardSelection()")
                page.route("**/api/pin", lambda r: r.abort())
                self.compose(page, "실패할 메모")
                page.evaluate("savePin()")
                settle(page)
                other = self.pin(12, "에이전트가 닫을 핀")
                page.evaluate("loadPins()")
                settle(page)
                self.agent_close(other)
                page.evaluate("loadPins()")
                settle(page)
                self.no_toast(page)

    def test_a_save_offers_its_undo_on_the_new_mark_even_with_the_sheet_folded(self):
        """Saved: a chip '저장됨 [되돌리기]' on the new pin's mark, nothing in the list; on the phone the sheet folds after the
        save and the chip is on screen above it, pressable. It is read out whole, its text and button centred, its
        button a 44px hit on touch. [되돌리기] takes the pin back (to the Trash) and reopens the composer with the note."""
        for screen in SCREENS:
            with self.subTest(screen=screen):
                page = self.view(screen)
                self.compose(page, "초록을 줄여 주세요")
                page.click("#btn-save")
                page.wait_for_selector(".mark .nt-chip")
                pid = page.evaluate("+document.querySelector('.mark:has(.nt-chip)').dataset.pin")
                chip = page.locator(".mark .nt-chip")
                self.assertEqual(chip.locator(".nt-ti").inner_text(), "저장됨")
                self.assertEqual(chip.locator("[data-act=notice-act]").inner_text(), "되돌리기")
                self.assertEqual(page.locator("#list .nt").count(), 0)
                self.assertIn("핀 #%d 저장됨" % pid, page.inner_text("#sr-news"))
                self.assertLessEqual(self.centred(page, ".mark .nt-chip"), 0.5)
                if screen == "phone":
                    self.assertFalse(page.evaluate("SIDE_OPEN"))  # the sheet folded after the save
                    self.assertTrue(
                        page.evaluate(
                            "(()=>{const b=document.querySelector('.mark .nt-chip [data-act=notice-act]').getBoundingClientRect();"
                            "const e=document.elementFromPoint(b.left+b.width/2,b.top+b.height/2);"
                            "return !!e&&!!e.closest('.nt-chip')&&b.bottom<=document.getElementById('right').getBoundingClientRect().top;})()"
                        )
                    )
                    self.assertGreaterEqual(self.hit(page, ".mark .nt-chip [data-act=notice-act]"), 44)
                    self.assertGreaterEqual(
                        page.evaluate(
                            "parseFloat(getComputedStyle(document.querySelector('.mark .nt-chip')).fontSize)"
                        ),
                        12,
                    )
                chip.locator("[data-act=notice-act]").click()
                page.wait_for_selector("#composer:not([hidden])")
                settle(page)
                self.assertEqual(page.input_value("#note"), "초록을 줄여 주세요")
                self.assertIsNone(self.state(pid))
                self.assertIn(pid, [r["id"] for r in trash_records()])
                self.assertEqual(page.locator(".nt-chip").count(), 0)
                self.no_toast(page)

    def test_a_failed_save_says_so_above_the_save_row_and_the_button_saves_again(self):
        """The server cannot be reached: an alert banner right above the save row ('핀 저장 실패 · 서버에 닿지 않습니다'),
        the note kept, [핀 저장] reading [다시 저장]. Once the server answers, [다시 저장] saves, the banner goes and the
        button reads [핀 저장] again."""
        for screen in SCREENS:
            with self.subTest(screen=screen):
                page = self.view(screen)
                page.route("**/api/pin", lambda r: r.abort())
                self.compose(page, "저장이 실패할 메모")
                page.click("#btn-save")
                banner = page.locator("#c-actions > .nt-banner.nk-err")
                banner.wait_for(state="visible")
                self.assertEqual(banner.get_attribute("role"), "alert")
                self.assertEqual(banner.locator(".nt-ti").inner_text(), "핀 저장 실패")
                self.assertEqual(banner.locator(".nt-d").inner_text(), "서버에 닿지 않습니다")
                self.assertTrue(page.inner_text("#btn-save").startswith("다시 저장"))
                self.assertEqual(page.input_value("#note"), "저장이 실패할 메모")
                geo = page.evaluate(
                    "(()=>{const b=document.querySelector('#c-actions > .nt-banner').getBoundingClientRect(),"
                    "s=document.getElementById('btn-save').getBoundingClientRect();return [b.bottom,s.top,b.left,b.right,innerWidth];})()"
                )
                self.assertLessEqual(geo[0], geo[1])  # right above the save row
                if screen == "phone":
                    self.assertAlmostEqual(geo[2], 12, delta=0.5)  # the phone's 12px edges
                    self.assertAlmostEqual(geo[4] - geo[3], 12, delta=0.5)
                self.assertLessEqual(self.centred(page, "#c-actions > .nt-banner"), 0.5)
                page.unroute("**/api/pin")
                page.click("#btn-save")
                page.wait_for_selector(".mark .nt-chip")
                settle(page)
                self.assertEqual(page.locator(".nt-banner").count(), 0)
                self.assertTrue(page.inner_text("#btn-save").startswith("핀 저장"))
                self.no_toast(page)

    def conflict(self, screen, person):
        """Alice's [확인] on an agent-closed pin, then - while its undo is up - the pin closed again by the agent or by a
        person straight to done; [x] on the undo sends the confirm now. Returns (page, pin id)."""
        pid = self.pin(6, "D2 추정량을 한 줄로 설명해 주세요")
        self.agent_close(pid)
        # the close the card shows happened long ago, so the close made below (now) is another one (done_at differs)
        edit_stored(lambda rows: [r.update(done_at="2020-01-01 00:00:00") for r in rows if r["id"] == pid])
        page = self.view(screen, init=SEEN + ";" + COUNT_CONFIRMS)
        page.evaluate("setSide(true); SEC.review=true; OPEN_CARDS.add(%d); drawPins()" % pid)
        settle(page)
        page.click('#review-pins [data-id="%d"] [data-act=confirm]' % pid)
        row = page.locator("#review-pins .nt-row")
        row.wait_for(state="visible")
        self.assertEqual(page.evaluate("CONFIRMS"), [])
        store = ps.APP.pin_lifecycle.context().store
        who = A if person else dict(LOCAL_ACTOR)
        ps.APP.pin_lifecycle.reopen_pin(pid, post_authority(store, who, "reopen", pid))
        ps.APP.pin_lifecycle.close_pin(pid, post_authority(store, who, "close", pid), CloseRequest())
        row.locator("[data-act=notice-x]").click()
        page.wait_for_function("CONFIRMS.length===1")
        page.wait_for_selector(".nt-banner", timeout=10000)
        settle(page)
        return page, pid

    def test_a_confirm_of_a_pin_closed_again_by_the_agent_is_a_warning_on_the_review_section(self):
        """409 conflict with the pin awaiting review again: an alert banner under the review section's head, with the
        closed-again wording and [변경 보기] to look at the new result; the pin is still awaiting review."""
        for screen in SCREENS:
            with self.subTest(screen=screen):
                self.tearDown()
                self.setUp()
                page, pid = self.conflict(screen, person=False)
                banner = page.locator("#sec-review > .nt-banner.nk-warn")
                self.assertEqual(banner.get_attribute("role"), "alert")
                self.assertEqual(banner.locator(".nt-ti").inner_text(), "핀 #%d 은 다시 닫혔습니다" % pid)
                self.assertEqual(banner.locator(".nt-d").inner_text(), "새 결과를 보고 확인하세요")
                self.assertEqual(banner.locator("[data-act=notice-act]").inner_text(), "변경 보기")
                self.assertEqual(self.state(pid), "review")
                self.no_toast(page)

    def test_a_confirm_of_a_pin_a_person_closed_to_done_says_there_is_nothing_to_confirm(self):
        """409 conflict with a done pin: an information banner (read out politely, not an alert) saying it was already
        closed and there is nothing to confirm - with no action - on top of the panel, as the review section is empty;
        nothing is confirmed."""
        for screen in SCREENS:
            with self.subTest(screen=screen):
                self.tearDown()
                self.setUp()
                page, pid = self.conflict(screen, person=True)
                banner = page.locator("#list > .nt-banner.nk-info")
                self.assertIsNone(banner.get_attribute("role"))
                self.assertEqual(banner.locator(".nt-ti").inner_text(), "핀 #%d 은 이미 완료로 닫혔습니다" % pid)
                self.assertEqual(banner.locator(".nt-d").inner_text(), "확인할 것이 없습니다")
                self.assertEqual(banner.locator("[data-act=notice-act]").count(), 0)
                self.assertIn("확인할 것이 없습니다", page.inner_text("#sr-news"))
                self.assertFalse(page.evaluate("document.body.innerText.includes('다시 닫혔습니다')"))
                self.assertIsNone(find_record(ps.APP.snapshot_pins(), pid).get("confirmed_by"))
                self.no_toast(page)

    def test_a_background_close_goes_to_the_status_line_with_a_dot_on_review(self):
        """The agent closes a pin while Alice reads: the status line (the desktop's under its chips) says it is awaiting
        review with [보기], read out politely, and the review chip carries a red dot; [보기] goes to the review section
        and the dot goes."""
        for screen in SCREENS:
            with self.subTest(screen=screen):
                self.tearDown()
                self.setUp()
                pid = self.pin(5, "근거 수치를 넣어 주세요")
                page = self.view(screen, n_open=1)
                if screen == "phone":
                    self.assertFalse(page.evaluate("SIDE_OPEN"))
                self.agent_close(pid)
                page.evaluate("loadPins()")
                page.wait_for_function("LINE.length===1")
                settle(page)
                want = "#%d 이 검토 대기로 넘어왔습니다" % pid
                self.assertIn(want, page.inner_text("#status .st-tx"))
                self.assertIn(want, page.inner_text("#status .st-sr"))
                self.assertEqual(page.get_attribute("#status .st-sr", "aria-live"), "polite")
                if screen == "desktop":
                    geo = page.evaluate(
                        "[document.getElementById('bar2').getBoundingClientRect().bottom,document.getElementById('status-wide').getBoundingClientRect().top,"
                        "document.getElementById('status').closest('#status-wide')!==null]"
                    )
                    self.assertTrue(geo[2])
                    self.assertAlmostEqual(geo[0], geo[1], delta=0.5)  # the line right under the chip row
                chip = "#btn-rv" if screen == "phone" else "#rv-chip"
                dot = page.evaluate(
                    "(()=>{const s=getComputedStyle(document.querySelector('%s'),'::before'),r=document.createElement('i');"
                    "r.style.background='var(--destructive)';document.body.appendChild(r);const want=getComputedStyle(r).backgroundColor;r.remove();"
                    "return [s.content,s.width,s.backgroundColor===want];})()" % chip
                )
                self.assertEqual(dot, ['""', "8px", True])  # a red 8px dot on the chip that leads there
                self.assertTrue(page.evaluate("document.body.classList.contains('dot-rv')"))
                page.click("#status [data-act=notice-act]")
                settle(page)
                self.assertFalse(page.evaluate("document.body.classList.contains('dot-rv')"))
                self.assertTrue(page.evaluate("SIDE_OPEN&&!document.getElementById('sec-review').hidden"))
                self.assertEqual(page.evaluate("LINE.length"), 0)
                self.no_toast(page)

    def test_a_delete_leaves_a_row_with_undo_in_the_cards_place(self):
        """[삭제]: the card goes and a row '핀 #N 삭제됨 · 휴지통에 30일 보관 [되돌리기]' takes its place between its
        neighbours, read out politely; its text and buttons centred and, on touch, its buttons 44px hits. [되돌리기]
        brings the pin back and the row goes; a later delete's row stays through a press elsewhere, and [x] takes it."""
        for screen in SCREENS:
            with self.subTest(screen=screen):
                self.tearDown()
                self.setUp()
                first, mid, last = self.pin(3, "첫째"), self.pin(9, "둘째"), self.pin(15, "셋째")
                page = self.view(screen, n_open=3)
                page.evaluate("setSide(true); OPEN_CARDS.add(%d); drawPins()" % mid)
                settle(page)
                page.click('#pins .pin[data-id="%d"] [data-act=drop]' % mid)
                row = page.locator("#pins > .nt-row")
                row.wait_for(state="visible")
                settle(page)
                order = page.evaluate(
                    "[...document.querySelectorAll('#pins > *')].map(e=>e.classList.contains('nt-row')?'row':e.dataset.id)"
                )
                self.assertEqual(order, [str(first), "row", str(last)])
                self.assertEqual(row.locator(".nt-ti").inner_text(), "핀 #%d 삭제됨" % mid)
                self.assertEqual(row.locator(".nt-d").inner_text(), "휴지통에 30일 보관")
                self.assertIn("핀 #%d 삭제됨" % mid, page.inner_text("#sr-news"))
                self.assertLessEqual(self.centred(page, "#pins > .nt-row"), 0.5)
                if screen == "phone":
                    self.assertGreaterEqual(self.hit(page, "#pins > .nt-row [data-act=notice-act]"), 44)
                    self.assertGreaterEqual(self.hit(page, "#pins > .nt-row [data-act=notice-x]"), 44)
                self.assertIsNone(self.state(mid))
                row.locator("[data-act=notice-act]").click()
                page.wait_for_function("OPEN_ALL.some(p=>p.id===%d)" % mid)
                settle(page)
                self.assertEqual(self.state(mid), "open")
                self.assertEqual(page.locator(".nt-row").count(), 0)
                page.click('#pins .pin[data-id="%d"] [data-act=drop]' % mid)
                page.locator("#pins > .nt-row").wait_for(state="visible")
                page.evaluate("document.body.click()")  # a press elsewhere
                self.assertEqual(page.locator(".nt-row").count(), 1)
                page.locator("#pins > .nt-row [data-act=notice-x]").click()
                self.assertEqual(page.locator(".nt-row").count(), 0)
                self.no_toast(page)

    def test_a_first_visit_hint_goes_to_the_status_line_until_the_person_picks(self):
        """First visit: the hint for the device (long-press on touch, drag with a mouse) is on the status line, read out
        politely; making a selection does what it says, and it goes."""
        hints = {"phone": "PDF를 길게 누르면 그 문단을 고릅니다", "desktop": "PDF를 끌어서 고칠 곳을 고르세요"}
        for screen in SCREENS:
            with self.subTest(screen=screen):
                page = self.view(screen, init="")
                page.wait_for_selector("#status:not([hidden])")
                self.assertIn(hints[screen], page.inner_text("#status .st-sr"))
                self.assertTrue(page.locator("#status .st-tx").is_visible())
                self.assertEqual(page.evaluate("LINE[0].kind"), "info")
                self.compose(page, "")
                settle(page)
                self.assertEqual(page.evaluate("LINE.length"), 0)
                self.no_toast(page)


# The visible elements whose box meets the select mode's bar (#sel-bar), as 'tag#id.class', or null while the bar is not
# shown. Left out: the bar itself, what it holds and what holds it, the PDF it floats over (the scroller #left, whose top
# padding is the reserve under the bar, and the pages in it, which scroll under the bar by design) - but not a message drawn
# on the PDF (.nt, a save's chip) - and visually hidden live regions (.sr-only).
OVER_SEL_BAR = """() => {
  const bar = document.getElementById('sel-bar');
  if (!bar || !bar.getClientRects().length) return null;
  const b = bar.getBoundingClientRect(), out = [];
  for (const e of document.querySelectorAll('body *')) {
    if (e === bar || bar.contains(e) || e.contains(bar) || e.classList.contains('sr-only')) continue;
    if (e.closest('#left') && !e.closest('.nt')) continue;
    if (!e.getClientRects().length) continue;
    const s = getComputedStyle(e);
    if (s.visibility === 'hidden' || parseFloat(s.opacity) === 0) continue;
    const r = e.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    if (r.left < b.right && b.left < r.right && r.top < b.bottom && b.top < r.bottom)
      out.push(e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (typeof e.className === 'string' && e.className.trim()
        ? '.' + e.className.trim().split(/\\s+/).join('.') : ''));
  }
  return out;
}"""


class SelectBarStaysClear(BrowserBase):
    """Nothing the viewer draws covers the touch select mode's bar (#sel-bar, 0.4.14): on the live 0.4.14 phone the
    first-visit hint chip (#coach) sat at the top of the screen over the bar. Hints now live on the status line at the
    bottom, and a save's chip whose box would meet the bar takes its undo to the status line."""

    WHO = ALICE

    def select_mode_on(self, page):
        """Turns the select mode on with a tap on [⬚ 선택] and waits for its bar."""
        page.locator("#btn-select").tap()
        page.wait_for_function("document.body.classList.contains('selmode')")
        page.wait_for_selector("#sel-bar", state="visible")
        settle(page)

    def test_nothing_covers_the_select_bar_on_a_first_visit_phone(self):
        """411x908 touch, a first visit (fresh storage, so the first-visit hint is due), the select mode turned on: the bar
        shows and no other visible element's box meets it."""
        page = self.open(0, **SCREENS["phone"])
        self.select_mode_on(page)
        self.assertEqual(page.evaluate(OVER_SEL_BAR), [])

    def test_a_save_chip_never_sits_under_the_select_bar(self):
        """A save's chip on the phone, then the select mode on and the page scrolled so the new mark is under the bar: the
        chip leaves the PDF for the status line with its [되돌리기], and nothing meets the bar."""
        page = self.open(0, init=SEEN, **SCREENS["phone"])
        page.evaluate("LAST_PTR='mouse'; pick({page:1,x0:10,y0:10,x1:200,y1:60})")
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo", timeout=8000)
        page.fill("#note", "선택 막대 아래로 가는 칩")
        page.click("#btn-save")
        page.wait_for_selector(".mark .nt-chip")
        pid = page.evaluate("+document.querySelector('.mark:has(.nt-chip)').dataset.pin")
        self.select_mode_on(page)
        page.evaluate(
            "id=>{const L=document.getElementById('left'),m=document.querySelector('.mark[data-pin=\"'+id+'\"]'),"
            "b=document.getElementById('sel-bar').getBoundingClientRect();"
            "L.scrollTop+=m.getBoundingClientRect().top-(b.top+b.bottom)/2;}",
            pid,
        )
        page.wait_for_function("!document.querySelector('.nt-chip')")
        settle(page)
        self.assertEqual(page.evaluate("LINE.map(n=>n.title)"), ["핀 #%d 저장됨" % pid])
        self.assertEqual(page.locator("#status [data-act=notice-act]").inner_text(), "되돌리기")
        self.assertEqual(page.evaluate(OVER_SEL_BAR), [])


if __name__ == "__main__":
    unittest.main()

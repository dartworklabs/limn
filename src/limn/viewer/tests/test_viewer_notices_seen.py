"""Messages are seen now, and an undo lives its full window (review of #167, docs/handbook/viewer.md §알림 자리).

Two rules, each with the defects of the first no-toast branch they close:

- An error or a failure appears where the person can see it now. A banner whose host is not on screen - the panel
  collapsed, the phone's sheet folded, the Trash closed - goes to the status line as an error, is read out through the
  alert region, and puts the red dot on the chip that leads there; errors (a build failure, a lost connection too) come
  before information on the line. A request a message's action sends keeps that message until it is answered.
- An undo lives for its full 6 s window, or until the person dismisses or uses it; other presses never end it. A mouse on
  the status line, or the open '+N' list, holds the line's windows; a new message never takes the keyboard focus from a
  [되돌리기] that is still there.

Also: copying says so on the button that copied; a review arrival goes once its pin has left review; a failed reply is
one alert, the reply box's own.

The flows run in Chromium against the in-process server on a phone (411x908, DPR 2.63, touch) and a desktop (1440x900).
Run: uv run pytest -q src/limn/viewer/tests/test_viewer_notices_seen.py
"""

import json
import time
import unittest

from limn.pins.lifecycle.rules import CloseRequest
from limn.pins.listing.projection import pin_state
from limn.security.access import LOCAL_ACTOR

from helpers import add_pin, extract_js_fn, find_record, js_i18n, ps, run_node, trash_records
from helpers_access import ALICE, BOB, actor
from helpers_authority import post_authority
from helpers_browser import BrowserBase, settle
from helpers_notices import SCREENS, SEEN, WATCH_TOASTS, node_or_skip

A, B = actor(ALICE), actor(BOB)

# Whether a message that says text is drawn on screen now and on top: a message element (.nt) or the status line's text,
# inside the viewport, with the point at its left edge's middle hitting it - not one in a closed dialog, a collapsed panel
# or a folded sheet, nor one under another element.
SEEN_NOW = """t => [...document.querySelectorAll('.nt, #status .st-tx')].some(e => {
  if (!e.textContent.includes(t) || !e.getClientRects().length) return false;
  const r = e.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0 || r.bottom <= 0 || r.top >= innerHeight || r.right <= 0 || r.left >= innerWidth) return false;
  const h = document.elementFromPoint(Math.max(r.left, 0) + 2, (Math.max(r.top, 0) + Math.min(r.bottom, innerHeight)) / 2);
  return !!h && (e.contains(h) || h.contains(e));
})"""
# Whether text was read out as an alert: the alert region (#sr-alert) says it, or an element drawn with role=alert does.
ALERTED = """t => document.getElementById('sr-alert').textContent.includes(t) ||
  [...document.querySelectorAll('[role=alert]')].some(e => e.getClientRects().length && e.textContent.includes(t))"""
# The visible elements with role=alert that say something, as their text.
ALERTS = """() => [...document.querySelectorAll('[role=alert]')].filter(e => e.getClientRects().length && e.textContent.trim())
  .map(e => e.textContent.trim())"""


def json_answer(data):
    """A route handler answering every request it catches with data as JSON (one parameter: Playwright passes the
    request too to a handler that takes two)."""
    body = json.dumps(data)
    return lambda route: route.fulfill(status=200, headers={"content-type": "application/json"}, body=body)


class SeenRules(unittest.TestCase):
    """The pure decisions behind the two rules, run under node with the served functions."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    def run_js(self, names, body):
        """Run body after the served functions names (and the Korean message functions); its JSON output."""
        return json.loads(run_node("\n".join([js_i18n("ko")] + [extract_js_fn(n) for n in names] + [body])))

    def test_a_banner_is_shown_only_where_its_host_is_on_screen(self):
        """bannerShown: the Trash's banner needs the Trash open; the composer's the panel (the phone's sheet) open with a
        composer in it; the list's and the review section's the panel open."""
        got = self.run_js(
            ["bannerShown"],
            """const v=(s,t,c)=>({sideOpen:s,trashOpen:t,composerOpen:c});
            console.log(JSON.stringify([bannerShown('trash',v(true,false,false)),bannerShown('trash',v(false,true,false)),
              bannerShown('composer',v(true,false,true)),bannerShown('composer',v(false,false,true)),bannerShown('composer',v(true,false,false)),
              bannerShown('list',v(false,false,false)),bannerShown('review',v(true,false,false))]));""",
        )
        self.assertEqual(got, [False, True, True, False, False, False, True])

    def test_errors_come_before_information_on_the_line(self):
        """statusList: an error message, then a build failure and a lost connection, then the other messages (newest
        first), then the build and sync items."""
        got = self.run_js(
            ["statusProgress", "statusList"],
            """const ok={n:1,kind:'ok'},info={n:2,kind:'info'},err={n:3,kind:'err'};
            const L=statusList({notices:[info,err,ok],build:null,buildErr:{state:'fail'},offline:true,sync:null,stale:true,png:false,canRebuild:true,unchanged:null});
            console.log(JSON.stringify(L.map(i=>i.kind+(i.notice?i.notice.n:''))));""",
        )
        self.assertEqual(got, ["notice3", "failed", "offline", "notice2", "notice1", "stale"])

    def test_a_review_arrival_is_stale_once_none_of_its_pins_awaits_review(self):
        """reviewNewsStale: a message about pins sent to review is stale when none of them awaits review any more; one
        about other events never is."""
        got = self.run_js(
            ["reviewPins", "reviewNewsStale"],
            """const k=ids=>ids.map(i=>'review_requested:'+i);
            console.log(JSON.stringify([reviewNewsStale(k([4]),[4,5]),reviewNewsStale(k([4]),[5]),reviewNewsStale(k([4,6]),[6]),
              reviewNewsStale(k([4,6]),[]),reviewNewsStale(['dropped:4'],[]),reviewNewsStale([],[])]));""",
        )
        self.assertEqual(got, [False, True, False, True, False, False])


class SeenFlows(BrowserBase):
    """Each defect of the review, on the phone and the desktop where it depends on the layout."""

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

    def agent_close(self, pid):
        """The agent closes pin pid (to review)."""
        store = ps.APP.pin_lifecycle.context().store
        ps.APP.pin_lifecycle.close_pin(
            pid, post_authority(store, dict(LOCAL_ACTOR), "close", pid), CloseRequest(reply="고쳤습니다", ref="abc1234")
        )

    def state(self, pid):
        """Pin pid's state on the server, or None once it is gone."""
        rec = find_record(ps.APP.snapshot_pins(), pid)
        return pin_state(rec) if rec else None

    def compose(self, page, note):
        """A selection on page 1 with note typed in, its draft stored."""
        page.evaluate("LAST_PTR='mouse'; pick({page:1,x0:10,y0:10,x1:200,y1:60})")
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo", timeout=8000)
        page.fill("#note", note)
        page.wait_for_function("DRAFT.timer===0", timeout=8000)

    def seen_now(self, page, text):
        """Whether a message saying text is on screen now (SEEN_NOW)."""
        return page.evaluate(SEEN_NOW, text)

    def alerted(self, page, text):
        """Whether text was read out as an alert (ALERTED)."""
        return page.evaluate(ALERTED, text)

    def line_has(self, page, text):
        """Whether one of the status line's messages says text."""
        return page.evaluate("t=>LINE.some(n=>(n.title+' '+n.desc).includes(t))", text)

    def wait_for_route(self, page, held):
        """Pump Playwright until the route handler that appends to held has caught a request."""
        for _ in range(100):
            if held:
                return
            page.wait_for_timeout(50)
        self.fail("the request never went out")

    def test_1_a_permanent_delete_failing_after_the_trash_closed_is_an_error_on_the_line(self):
        """[영구 삭제], the Trash closed inside its window, then the delete fails: the error is on the status line, read
        out as an alert, with the dot on [핀 N] while the panel is closed - not in the closed Trash."""
        ps.APP.C.people_file.write_text(
            json.dumps(
                {"version": 1, "people": [{"login": "alice@example.com", "name": "Alice Kim", "role": "owner"}]}
            ),
            encoding="utf-8",
        )
        for screen in SCREENS:
            with self.subTest(screen=screen):
                pid = self.pin(4, "영구히 지울 핀")
                ps.APP.pin_trash.drop_pin(pid, post_authority(ps.APP.pin_trash.context().store, A, "drop", pid))
                page = self.view(screen)
                page.route("**/api/pins/*/purge", lambda r: r.abort())
                page.evaluate("openTrash()")
                page.click('#trash .arc-row[data-id="%d"] [data-act=purge]' % pid)
                page.locator("#trash .nt-row").wait_for(state="visible")
                page.evaluate("document.getElementById('trash').close()")
                settle(page)
                page.click("#status [data-act=notice-x]")  # sends the delete now, as the end of its window would
                settle(page)
                self.assertTrue(self.seen_now(page, "영구 삭제 실패"))
                self.assertTrue(self.alerted(page, "영구 삭제 실패"))
                self.assertEqual(page.locator("#trash .nt-banner").count(), 0)
                if not page.evaluate("SIDE_OPEN"):
                    self.assertTrue(page.evaluate("document.body.classList.contains('dot-side')"))
                self.assertIn(pid, [r["id"] for r in trash_records()])

    def test_2_a_restore_from_the_line_failing_with_the_panel_closed_is_an_error_on_the_line(self):
        """Bob deletes Alice's pin while her panel is closed; her [되살리기] on the status line keeps that message while
        the request is out, and when it fails the line says so as an alert with the dot on [핀 N]."""
        held = []  # the restore request, caught and held until the test lets it fail
        for screen in SCREENS:
            with self.subTest(screen=screen):
                self.tearDown()
                self.setUp()
                held.clear()
                pid = self.pin(5, "되살릴 핀")
                page = self.view(screen, n_open=1)
                page.evaluate("setSide(false)")
                settle(page)
                ps.APP.pin_trash.drop_pin(pid, post_authority(ps.APP.pin_trash.context().store, B, "drop", pid))
                page.evaluate("loadPins()")
                settle(page)
                self.assertIn("삭제함", page.inner_text("#status .st-tx"))
                page.route("**/api/pins/*/restore", lambda route: held.append(route))
                page.click("#status [data-act=notice-act]")
                self.wait_for_route(page, held)
                self.assertIn("삭제함", page.inner_text("#status .st-tx"))  # not cleared as if it had worked
                held[0].abort()
                settle(page)
                self.assertTrue(self.seen_now(page, "되살리기 실패"))
                self.assertTrue(self.alerted(page, "되살리기 실패"))
                self.assertEqual(page.locator("#list .nt-banner").count(), 0)
                self.assertTrue(page.evaluate("document.body.classList.contains('dot-side')"))
                self.assertIsNone(self.state(pid))

    def test_3_a_build_failure_comes_before_a_lasting_message_and_is_read_out(self):
        """A first visit's hint lasts on the line; a build then fails: on the phone the line shows the failure, not the
        hint; on both screens the failure is read out as an alert."""
        for screen in SCREENS:
            with self.subTest(screen=screen):
                page = self.view(screen, init="")
                page.wait_for_function("LINE.length===1")
                seq = page.evaluate("BUILD.lastSeq")
                page.route(
                    "**/api/build*",
                    json_answer(
                        {"state": "fail", "seq": seq + 1, "log_tail": "! Undefined control sequence.", "errors": []}
                    ),
                )
                page.evaluate("pollBuild()")
                settle(page)
                if screen == "phone":
                    self.assertIn("빌드 실패", page.inner_text("#status .st-tx"))
                self.assertTrue(self.alerted(page, "빌드 실패"))

    def test_3_a_lost_connection_comes_before_a_lasting_message_and_is_read_out(self):
        """A first visit's hint lasts on the line; the light poll then fails twice: on the phone the line says the
        connection is lost, and on both screens that is read out as an alert."""
        for screen in SCREENS:
            with self.subTest(screen=screen):
                page = self.view(screen, init="")
                page.wait_for_function("LINE.length===1")
                page.route(lambda u: "/api/meta" in u and "light=1" in u, lambda r: r.abort())
                page.evaluate("(async()=>{await pollLightOnce(); await pollLightOnce();})()")
                settle(page)
                if screen == "phone":
                    self.assertIn("연결 끊김", page.inner_text("#status .st-tx"))
                self.assertTrue(self.alerted(page, "연결 끊김"))

    def test_4_a_failed_undo_of_a_save_keeps_the_pin_and_says_so(self):
        """[되돌리기] on the save chip, the delete fails: the pin stays, the composer does not come back (a second save
        would duplicate it), and the failure is on screen and read out; its [다시 시도] then takes the pin back and
        only then reopens the composer with the note."""
        for screen in SCREENS:
            with self.subTest(screen=screen):
                self.tearDown()
                self.setUp()
                page = self.view(screen)
                self.compose(page, "되돌리기가 실패할 메모")
                page.click("#btn-save")
                page.wait_for_selector(".mark .nt-chip")
                pid = page.evaluate("+document.querySelector('.mark:has(.nt-chip)').dataset.pin")
                page.route("**/api/pins/%d/drop" % pid, lambda r: r.abort())
                page.locator(".mark .nt-chip [data-act=notice-act]").click()
                settle(page)
                self.assertTrue(page.evaluate("document.getElementById('composer').hidden&&!COMPOSE.current"))
                self.assertEqual(self.state(pid), "open")
                self.assertTrue(page.evaluate("OPEN_ALL.some(p=>p.id===%d)" % pid))
                self.assertTrue(self.seen_now(page, "삭제 실패"))
                self.assertTrue(self.alerted(page, "삭제 실패"))
                page.unroute("**/api/pins/%d/drop" % pid)
                page.locator(":is(.nt-banner,#status)", has_text="삭제 실패").locator("[data-act=notice-act]").click()
                page.wait_for_selector("#composer:not([hidden])")
                settle(page)
                self.assertEqual(page.input_value("#note"), "되돌리기가 실패할 메모")
                self.assertIsNone(self.state(pid))

    def test_5_undo_rows_live_their_window_whatever_else_is_pressed(self):
        """[완료] on A, then on B: both rows stay, through a press elsewhere, each with its own [되돌리기] (A's still
        reopens A); on the desktop both then go when their 6 s windows end."""
        for screen in SCREENS:
            with self.subTest(screen=screen):
                self.tearDown()
                self.setUp()
                a, b, _ = self.pin(3, "에이"), self.pin(9, "비"), self.pin(15, "시")
                page = self.view(screen, n_open=3)
                page.evaluate("setSide(true); OPEN_CARDS.add(%d); OPEN_CARDS.add(%d); drawPins()" % (a, b))
                settle(page)
                page.click('#pins .pin[data-id="%d"] [data-act=close]' % a)
                page.locator("#pins > .nt-row").wait_for(state="visible")
                settle(page)
                t0 = time.monotonic()
                page.click('#pins .pin[data-id="%d"] [data-act=close]' % b)
                page.wait_for_function("document.querySelectorAll('#pins > .nt-row').length===2")
                page.evaluate("document.body.click()")  # a press elsewhere
                settle(page)
                self.assertEqual(page.locator("#pins > .nt-row").count(), 2)
                if screen == "desktop":
                    page.wait_for_function("!document.querySelector('#pins > .nt-row')", timeout=12000)
                    self.assertGreater(time.monotonic() - t0, 5.0)
                    continue
                page.locator("#pins > .nt-row", has_text="#%d" % a).locator("[data-act=notice-act]").click()
                page.wait_for_function("OPEN_ALL.some(p=>p.id===%d)" % a)
                settle(page)
                self.assertEqual(self.state(a), "open")

    def test_5_a_discarded_selection_keeps_its_undo_through_a_press_elsewhere(self):
        """[취소] with a note: '선택 취소됨 [되돌리기]' stays on the line through a press elsewhere, and still brings the
        selection and the note back."""
        for screen in SCREENS:
            with self.subTest(screen=screen):
                page = self.view(screen)
                self.compose(page, "버리기 전 메모")
                page.click("#btn-cancel")
                page.wait_for_function("LINE.some(n=>n.title==='선택 취소됨')")
                page.evaluate("document.body.click()")  # a press elsewhere
                settle(page)
                self.assertTrue(self.line_has(page, "선택 취소됨"))
                page.locator("#status", has_text="선택 취소됨").locator("[data-act=notice-act]").click()
                page.wait_for_selector("#composer:not([hidden])")
                self.assertEqual(page.input_value("#note"), "버리기 전 메모")

    def test_6_copying_says_so_on_the_button_for_a_moment(self):
        """The composer's copy button reads '복사됨' with a check for about 1.5 s, then goes back; it is read out
        politely. On the desktop a card's location does the same."""
        for screen in SCREENS:
            with self.subTest(screen=screen):
                self.tearDown()
                self.setUp()
                pid = self.pin(5, "복사할 핀")
                page = self.view(screen, n_open=1)
                self.compose(page, "복사 확인")
                copy = page.locator("#c-copy")
                if screen == "phone":
                    copy.tap()
                else:
                    copy.click()
                page.wait_for_function("document.getElementById('c-copy').textContent.includes('복사됨')", timeout=1000)
                self.assertEqual(page.locator("#c-copy svg").count(), 1)
                self.assertIn("복사함", page.inner_text("#sr-news"))
                page.wait_for_function(
                    "!document.getElementById('c-copy').textContent.includes('복사됨')", timeout=4000
                )
                self.assertEqual(page.get_attribute("#c-copy", "aria-label"), "위치 복사")
                if screen == "desktop":
                    page.click("#btn-cancel")
                    page.evaluate("setSide(true)")
                    settle(page)
                    loc = '#pins .pin[data-id="%d"] .loc' % pid
                    before = page.inner_text(loc)
                    page.click(loc)
                    page.wait_for_function(
                        "s=>document.querySelector(s).textContent.includes('복사됨')", arg=loc, timeout=1000
                    )
                    page.wait_for_function(
                        "([s,t])=>document.querySelector(s).innerText===t", arg=[loc, before], timeout=4000
                    )

    def test_7_a_review_arrival_and_its_dot_go_once_the_pin_leaves_review(self):
        """'#N 이 검토 대기로 넘어왔습니다 [보기]' and the review dot: confirmed here without [보기], both go (the
        collapsed desktop's [핀 N] carries no dot after); reopened elsewhere, both go too."""
        for screen in SCREENS:
            with self.subTest(screen=screen):
                self.tearDown()
                self.setUp()
                pid, other = self.pin(5, "검토 받을 핀"), self.pin(11, "다시 열릴 핀")
                page = self.view(screen, n_open=2)
                page.evaluate("setSide(false)")
                settle(page)
                self.agent_close(pid)
                page.evaluate("loadPins()")
                settle(page)
                self.assertTrue(self.line_has(page, "검토 대기로 넘어왔습니다"))
                self.assertTrue(page.evaluate("document.body.classList.contains('dot-rv')"))
                page.evaluate("setSide(true); SEC.review=true; OPEN_CARDS.add(%d); drawPins()" % pid)
                settle(page)
                page.click('#review-pins [data-id="%d"] [data-act=confirm]' % pid)
                page.locator("#review-pins .nt-row [data-act=notice-x]").click()  # sends the confirm now
                settle(page)
                self.assertEqual(self.state(pid), "done")
                self.assertFalse(self.line_has(page, "검토 대기로 넘어왔습니다"))
                self.assertFalse(page.evaluate("document.body.classList.contains('dot-rv')"))
                if screen == "desktop":
                    page.evaluate("setSide(false)")
                    settle(page)
                    self.assertEqual(
                        page.evaluate("getComputedStyle(document.getElementById('nav-side'),'::before').content"),
                        "none",
                    )
                page.evaluate("setSide(false)")
                self.agent_close(other)
                page.evaluate("loadPins()")
                settle(page)
                self.assertTrue(self.line_has(page, "검토 대기로 넘어왔습니다"))
                store = ps.APP.pin_lifecycle.context().store
                ps.APP.pin_lifecycle.reopen_pin(other, post_authority(store, dict(LOCAL_ACTOR), "reopen", other))
                page.evaluate("loadPins()")
                settle(page)
                self.assertFalse(self.line_has(page, "검토 대기로 넘어왔습니다"))
                self.assertFalse(page.evaluate("document.body.classList.contains('dot-rv')"))

    def test_a_mouse_on_the_line_or_the_open_list_holds_an_undo_window(self):
        """Desktop: '선택 취소됨 [되돌리기]' on the line outlives its 6 s while the mouse is on the line, and goes 6 s
        after the mouse leaves; another one outlives its 6 s while the '+N' list is open, and goes after it closes."""
        page = self.view("desktop")
        self.compose(page, "기다릴 메모")
        page.click("#btn-cancel")
        page.wait_for_function("LINE.some(n=>n.title==='선택 취소됨')")
        page.hover("#status .st-tx")
        page.wait_for_timeout(6600)
        self.assertTrue(self.line_has(page, "선택 취소됨"))
        page.mouse.move(700, 500)
        t0 = time.monotonic()
        page.wait_for_function("!LINE.some(n=>n.title==='선택 취소됨')", timeout=9000)
        self.assertGreater(time.monotonic() - t0, 5.0)
        self.compose(page, "목록에서 기다릴 메모")
        page.click("#btn-cancel")
        page.wait_for_function("LINE.some(n=>n.title==='선택 취소됨')")
        page.evaluate("lineNote('다른 소식',NOTICE_KIND.INFO)")
        page.click("#status [data-act=status-more]")
        page.mouse.move(700, 500)
        page.wait_for_timeout(6600)
        self.assertTrue(self.line_has(page, "선택 취소됨"))
        page.keyboard.press("Escape")
        page.wait_for_function("!LINE.some(n=>n.title==='선택 취소됨')", timeout=9000)

    def test_a_new_message_leaves_the_focus_on_a_live_undo(self):
        """Desktop: the focus on the line's [되돌리기] stays there when a background message arrives, and Enter still
        undoes; the new message is read out."""
        pid = self.pin(5, "닫힐 핀")
        page = self.view("desktop", n_open=1)
        self.compose(page, "포커스를 지킬 메모")
        page.click("#btn-cancel")
        page.wait_for_function("LINE.some(n=>n.title==='선택 취소됨')")
        page.focus("#status [data-act=notice-act]")
        n = page.evaluate("document.activeElement.dataset.n")
        self.agent_close(pid)
        page.evaluate("loadPins()")
        settle(page)
        self.assertTrue(self.line_has(page, "검토 대기로 넘어왔습니다"))
        self.assertEqual(
            page.evaluate("[document.activeElement.dataset.act,document.activeElement.dataset.n]"), ["notice-act", n]
        )
        self.assertIn("검토 대기로 넘어왔습니다", page.inner_text("#sr-news") + page.inner_text("#status .st-sr"))
        page.keyboard.press("Enter")
        page.wait_for_selector("#composer:not([hidden])")
        self.assertEqual(page.input_value("#note"), "포커스를 지킬 메모")

    def test_a_failed_reply_is_one_alert_in_the_reply_box(self):
        """Desktop: a reply whose send cannot reach the server is said once, on the reply box's own error line - no
        banner over the list, nothing in the alert region."""
        pid = self.pin(5, "답할 핀")
        self.agent_close(pid)
        page = self.view("desktop")
        page.evaluate("setSide(true); SEC.review=true; OPEN_CARDS.add(%d); drawPins()" % pid)
        settle(page)
        card = '#review-pins .pin[data-id="%d"]' % pid
        page.click(card + " .acts [data-act=reply-open]")
        page.fill(card + " textarea.r-text", "보내지 못할 답글")
        page.route("**/api/pins/%d/reply" % pid, lambda r: r.abort())
        page.click(card + " [data-act=reply-send]")
        page.locator(card + " .nt-note [data-act=notice-x]").click()  # sends it now
        settle(page)
        self.assertEqual(page.locator("#list .nt-banner").count(), 0)
        alerts = page.evaluate(ALERTS)
        self.assertEqual(len(alerts), 1, alerts)
        self.assertIn("보내지 못했습니다", alerts[0])
        self.assertEqual(page.inner_text("#sr-alert"), "")
        self.assertEqual(page.input_value(card + " textarea.r-text"), "보내지 못할 답글")


if __name__ == "__main__":
    unittest.main()

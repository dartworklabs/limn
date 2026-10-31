"""The notice store keeps its promises (second review of #167, docs/handbook/viewer.md §알림 자리).

The first fixes let a hold outlive the line it held, offered a pressed undo again, piled up one error per retry and kept an
old error above a later success, and let a burst of errors push an undo off the line. What the store promises instead:

- A hold (a mouse on the line, its open '+N' list, a mouse on a row or chip) never outlives the thing held: the line hiding,
  a message leaving it or the pointer leaving for any reason ends it, and a window stretched by a hold is still bounded
  (NOTICE_HOLD_MAX) - so a deferred send always goes, and pagehide still sends it at once.
- An undo that was pressed is offered nowhere else while its request is out - a busy button, not a new undo.
- An error is keyed by its source (the request; a rebuild by its document): a repeat replaces it and is said only when it
  first comes or changes, and the next success of that source clears it.
- The line's cap of five evicts information and errors only; an undo leaves by its window, its [되돌리기] or its [x].

A state model drives the real store under node with a fake clock through random sequences and checks the invariants after
every step; the flows run in Chromium against the in-process server.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_notices_store.py
"""

import json
import re
import time
import unittest

from helpers import HTML, extract_js_fn, js_i18n, run_node
from helpers_browser import BrowserBase, settle
from helpers_notices import COUNT_CONFIRMS, SEEN, WATCH_ALERTS, NoticePage, node_or_skip

# The store's functions, pulled from the served page as written, and the constants they read.
STORE_FNS = [
    "msgSplit", "noticeDupe", "noticeDot", "makeNotice", "lineNote", "endNotice", "noticeText", "armNotice",
    "noticeHeld", "lineHeld", "holdLine", "releaseLine", "lineHoverIn", "lineHoverOut", "lineVisible", "noticeAct",
    "noticeClose", "deferred", "deferredNote", "undoNote", "offerSeen", "sourceEntry", "sourceOk", "flushDeferred",
    "isUndo", "lineCap", "sameWords", "realMove",
]  # fmt: skip
STORE_CONSTS = r"^const (?:NOTICE_MS|NOTICE_HOLD_MAX|LINE_MAX)=\d+;"

# A fake clock (setTimeout, clearTimeout, Date.now; tick(ms) runs what falls due, in order) and the page around the store,
# stubbed: a closed panel, a hidden '+N' list, no drawing. drawStatus shows the line while it has messages, as the real one.
MODEL_PRELUDE = r"""
let NOW=0,QID=0; const Q=[];
function setTimeout(fn,ms){const id=++QID; Q.push({id,at:NOW+Math.max(0,Number(ms)||0),fn}); return id;}
function clearTimeout(id){const i=Q.findIndex(t=>t.id===id); if(i>=0)Q.splice(i,1);}
Date.now=()=>NOW;
function tick(ms){const end=NOW+ms; for(;;){Q.sort((a,b)=>a.at-b.at||a.id-b.id); const t=Q[0]; if(!t||t.at>end)break; Q.shift(); NOW=t.at; t.fn();} NOW=end;}
const stub=()=>({open:false,hidden:true,addEventListener(){},getClientRects:()=>[],matches:()=>false,querySelector:()=>null,querySelectorAll:()=>[],remove(){}});
const ELS={}; const $=s=>ELS[s]||(ELS[s]=stub());
const BODY=new Set();
const document={body:{classList:{add:c=>BODY.add(c),remove:c=>BODY.delete(c),contains:c=>BODY.has(c)}},querySelectorAll:()=>[],addEventListener(){},contains:()=>false};
const window={addEventListener(){}};
let SIDE_OPEN=false,STATUS_TOP=0; const SEC={},T={undo:'되돌리기'};
function announce(){} function drawOffer(){} function drawBanners(){} function syncSaveBtn(){}
const NOTICES=new Map(),LINE=[],BANNERS=new Map(),DEFERRED=new Set(); let NOTICE_SEQ=0,LINE_HOVER=false,PT_LAST=null;
function drawStatus(){lineVisible(LINE.length>0);}
"""

# Random sequences of: add an undo (a deferred send on the line, as with the panel closed), add an error or a piece of
# information, a source's success, press an undo, dismiss any message, a mouse moving over the line, the line drawn under a
# resting pointer, the pointer off the line, the line hiding, pagehide, and time passing. Hover steps go through the
# pointer-movement rule (lineHoverIn, realMove). The invariants are checked after every step, and at the end once every
# window has run out.
MODEL_RUN = r"""
function rng(seed){return ()=>{seed=seed+0x6D2B79F5|0; let t=Math.imul(seed^seed>>>15,1|seed); t=t+Math.imul(t^t>>>7,61|t)^t; return ((t^t>>>14)>>>0)/4294967296;};}
const bad=[],OPS=['undo','undo','error','error','info','ok','press','dismiss','move','still','out','hide','pagehide','tick','tick','tick'];
// A mouse move over the line as the page sees it: its listener runs, then the page notes the position (PT_LAST).
const over=(x,y,dx)=>{lineHoverIn({pointerType:'mouse',movementX:dx,movementY:0,clientX:x,clientY:y}); PT_LAST={x,y};};
for(let s=1;s<=SEEDS;s++){
  NOTICES.clear(); LINE.length=0; BANNERS.clear(); DEFERRED.clear(); Q.length=0; BODY.clear(); NOW=0; LINE_HOVER=false; PT_LAST=null;
  const R=rng(s),pick=a=>a[Math.floor(R()*a.length)],undos=[]; let free=false;
  const note=(k,what)=>{if(bad.length<20)bad.push([s,k,what]);};
  for(let k=0;k<STEPS;k++){const op=pick(OPS);
    if(op==='undo'){const u={sent:0,cancelled:0,at:NOW}; undos.push(u);
      const d=deferred(()=>{u.sent++; if(!free&&NOW-u.at<NOTICE_MS)note(k,'an undo sent before its window ended');},()=>{u.cancelled++;});
      deferredNote(d,NOTICE_PLACE.ROW,'핀 #'+undos.length+' 확인',{pin:undos.length,sec:'open'});}
    else if(op==='error'){const src='s'+Math.floor(R()*3); lineNote('오류 '+src+' — 사유 '+Math.floor(R()*2),NOTICE_KIND.ERR,null,{source:src});}
    else if(op==='info')lineNote('소식 '+k,NOTICE_KIND.INFO);
    else if(op==='ok'){const src='s'+Math.floor(R()*3); sourceOk(src);
      if([...NOTICES.values()].some(n=>n.source===src))note(k,'an error survived a later success of '+src);}
    else if(op==='press'){const u=[...NOTICES.values()].filter(n=>n.gone&&n.act); if(u.length)noticeAct(pick(u).n);}
    else if(op==='dismiss'){const all=[...NOTICES.values()]; if(all.length){free=true; noticeClose(pick(all).n); free=false;}}
    else if(op==='move')over(100+Math.floor(R()*80),20,3);   // a real movement over the line: it holds
    else if(op==='still'){const p=PT_LAST||{x:100,y:20},was=LINE_HOVER; over(p.x,p.y,0);   // the line drawn under a resting pointer
      if(!was&&LINE_HOVER)note(k,'a resting pointer started a hold');}
    else if(op==='out')lineHoverOut();
    else if(op==='hide'){lineVisible(false); if(LINE_HOVER||LINE.some(n=>n.held))note(k,'a pause survived the line hiding');}
    else if(op==='pagehide'){free=true; flushDeferred(); free=false;}
    else tick(Math.floor(R()*9000));
    const per={}; NOTICES.forEach(n=>{if(n.source)per[n.source]=(per[n.source]||0)+1;});
    for(const src in per)if(per[src]>1)note(k,'two entries for source '+src);
    undos.forEach((u,i)=>{if(u.sent+u.cancelled>1)note(k,'undo '+i+' sent '+u.sent+', cancelled '+u.cancelled);});}
  tick(NOTICE_MS+NOTICE_HOLD_MAX+1000);   // every window has run out - a held one too, by its bound
  undos.forEach((u,i)=>{if(u.sent+u.cancelled!==1)note('end','undo '+i+' sent '+u.sent+', cancelled '+u.cancelled);});}
console.log(JSON.stringify(bad));
"""


class NoticeStoreModel(unittest.TestCase):
    """The notice store under random sequences of what can happen to it, under node with a fake clock."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    def test_random_sequences_keep_the_stores_promises(self):
        """300 seeded sequences of 60 steps: every undo sends exactly once or is cancelled exactly once (never both,
        never neither by the end), and none is sent before its window ended unless dismissed or flushed by pagehide;
        no pause survives the line hiding; a resting pointer never starts one; at most one entry per error source; no
        error survives a later success of its source."""
        consts = "\n".join(re.findall(STORE_CONSTS, HTML, re.M))
        script = "\n".join(
            [js_i18n("ko"), MODEL_PRELUDE, consts]
            + [extract_js_fn(n) for n in STORE_FNS]
            + ["const SEEDS=300,STEPS=60;", MODEL_RUN]
        )
        self.assertEqual(json.loads(run_node(script)), [])


class StoreFlows(NoticePage, BrowserBase):
    """Each regression of the second review, in the browser."""

    def test_1_dismissing_the_last_message_under_the_mouse_leaves_no_hold(self):
        """Desktop: the mouse on the line dismisses its last message (the line hides) and moves away; a [확인] made
        then with the panel closed still sends when its 6 s window ends."""
        pid = self.pin(6, "확인할 핀")
        self.agent_close(pid)
        page = self.view("desktop", init=SEEN + ";" + COUNT_CONFIRMS)
        page.evaluate("setSide(false)")
        page.evaluate("lineNote('안내 한 줄',NOTICE_KIND.INFO)")
        settle(page)
        page.hover("#status .st-tx")
        page.click("#status [data-act=notice-x]")
        settle(page)
        page.mouse.move(700, 300)
        page.evaluate("confirmPin(%d)" % pid)
        self.assertTrue(self.line_has(page, "확인"))
        t0 = time.monotonic()
        page.wait_for_function("CONFIRMS.length===1", timeout=9000)
        self.assertLess(time.monotonic() - t0, 7.5)

    def test_2_a_pressed_save_undo_is_offered_nowhere_while_its_delete_is_out(self):
        """[되돌리기] on the save chip while the delete waits for the server: no other [되돌리기] for that pin anywhere
        (the chip nor the line); once the delete went through, nothing for it is left, and one delete was sent."""
        held = []  # the delete requests, caught and held until the test lets one through
        for screen in ("phone", "desktop"):
            with self.subTest(screen=screen):
                self.tearDown()
                self.setUp()
                held.clear()
                page = self.view(screen)
                self.compose(page, "되돌릴 메모")
                page.click("#btn-save")
                page.wait_for_selector(".mark .nt-chip")
                pid = page.evaluate("+document.querySelector('.mark:has(.nt-chip)').dataset.pin")
                page.route("**/api/pins/%d/drop" % pid, lambda route: held.append(route))
                page.locator(".mark .nt-chip [data-act=notice-act]").click()
                for _ in range(100):
                    if held:
                        break
                    page.wait_for_timeout(50)
                self.assertEqual(len(held), 1)
                offered = (
                    "id=>[...NOTICES.values()].filter(n=>!n.busy&&n.act&&n.act.label==='되돌리기'&&n.pin===id).length"
                )
                self.assertEqual(page.evaluate(offered, pid), 0)
                self.assertFalse(self.line_has(page, "저장됨"))
                self.route(held[0])  # the delete reaches the server now
                page.wait_for_selector("#composer:not([hidden])")
                settle(page)
                self.assertIsNone(self.state(pid))
                self.assertEqual(page.evaluate(offered, pid), 0)
                self.assertFalse(self.line_has(page, "저장됨"))
                self.assertEqual(len(held), 1)

    def test_3_a_failing_read_is_one_error_said_once_and_gone_when_it_works(self):
        """The phone, its sheet folded (and the desktop): the pin read fails five times; the line holds one '핀 읽기
        실패', read out once (the desktop: one banner); when the read works again it is gone."""

        def reads(url):
            """The pin snapshot read (GET /api/pins?all=1)."""
            return "/api/pins?all=1" in url

        for screen in ("phone", "desktop"):
            with self.subTest(screen=screen):
                self.tearDown()
                self.setUp()
                page = self.view(screen, init=SEEN + ";" + WATCH_ALERTS)
                if screen == "phone":
                    self.assertFalse(page.evaluate("SIDE_OPEN"))
                page.route(reads, lambda route: route.abort())
                for _ in range(5):
                    page.evaluate("loadPins()")
                settle(page)
                count = "[...NOTICES.values()].filter(n=>(n.title+n.desc).includes('핀 읽기 실패')).length"
                self.assertEqual(page.evaluate(count), 1)
                if screen == "phone":
                    self.assertEqual(page.evaluate("LINE.length"), 1)
                    said = page.evaluate("ALERTS_SAID.filter(t=>t.includes('핀 읽기 실패')).length")
                    self.assertEqual(said, 1)
                page.unroute(reads)
                page.evaluate("loadPins()")
                settle(page)
                self.assertEqual(page.evaluate(count), 0)

    def test_4_a_later_build_removes_the_rebuild_error(self):
        """Desktop: [PDF 재빌드] cannot reach the server - an error on the line; then a build completes: '재빌드 완료' is
        on the line and the old error is gone."""
        page = self.view("desktop")
        page.route("**/api/rebuild*", lambda route: route.abort())
        page.evaluate("rebuild()")
        settle(page)
        self.assertTrue(self.line_has(page, "PDF 재빌드 실패"))
        page.unroute("**/api/rebuild*")
        seq = page.evaluate("BUILD.lastSeq")
        body = json.dumps({"state": "ok", "seq": seq + 1, "elapsed_s": 3})
        page.route(
            "**/api/build*",
            lambda route: route.fulfill(status=200, headers={"content-type": "application/json"}, body=body),
        )
        page.evaluate("pollBuild()")
        settle(page)
        self.assertTrue(self.line_has(page, "재빌드 완료"))
        self.assertFalse(self.line_has(page, "PDF 재빌드 실패"))

    def test_5_a_burst_of_errors_never_evicts_an_undo(self):
        """Desktop, the panel closed: a [확인]'s undo on the line, then five errors within its window: the undo stays and
        nothing is sent early; it is sent once its window ends."""
        pid = self.pin(6, "확인할 핀")
        self.agent_close(pid)
        page = self.view("desktop", init=SEEN + ";" + COUNT_CONFIRMS)
        page.evaluate("setSide(false)")
        page.mouse.move(700, 300)
        page.evaluate("confirmPin(%d)" % pid)
        t0 = time.monotonic()
        page.evaluate("for(let i=0;i<5;i++)lineNote('오류 '+i+' — 사유',NOTICE_KIND.ERR,null,{source:'burst '+i})")
        settle(page)
        self.assertTrue(page.evaluate("LINE.some(n=>!!n.gone)"))
        self.assertEqual(page.evaluate("CONFIRMS.length"), 0)
        page.wait_for_function("CONFIRMS.length===1", timeout=9000)
        self.assertGreater(time.monotonic() - t0, 5.0)

    def review_pins(self, *los):
        """Pins by Alice on page 1 at lines lo, each closed by the agent (awaiting review); their ids."""
        ids = [self.pin(lo, "검토할 핀 %d" % lo) for lo in los]
        for pid in ids:
            self.agent_close(pid)
        return ids

    def test_6_an_undo_drawn_under_a_still_pointer_keeps_its_6_s(self):
        """Desktop, a long list scrolled to its end: [확인] on the last card by a mouse click, the pointer left still -
        the list closes up and the undo row lands under the pointer: the confirm goes when its 6 s end, not 30 s later.
        A real movement onto the next undo row still holds it, and it goes once the pointer moves off."""
        for lo in range(3, 33, 3):
            self.pin(lo, "열린 핀 %d" % lo)
        first, second = self.review_pins(34, 36)
        page = self.view("desktop", init=SEEN + ";" + COUNT_CONFIRMS, n_open=10)
        page.evaluate(
            "setSide(true); SEC.review=true; OPEN_CARDS.add(%d); OPEN_CARDS.add(%d); drawPins()" % (first, second)
        )
        page.evaluate("(()=>{const l=document.getElementById('list'); l.scrollTop=l.scrollHeight;})()")
        settle(page)
        last = '#review-pins [data-id="%d"] [data-act=confirm]' % second
        bb = page.locator(last).bounding_box()
        page.click(last)
        page.locator("#review-pins .nt-row").wait_for(state="visible")
        settle(page)
        under = page.evaluate(
            "([x,y])=>!!document.elementFromPoint(x,y).closest('.nt-row')",
            [bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2],
        )
        self.assertTrue(under)  # the row was drawn under the resting pointer
        t0 = time.monotonic()
        page.wait_for_function("CONFIRMS.length===1", timeout=9000)
        self.assertLess(time.monotonic() - t0, 7.5)
        settle(page)
        page.click('#review-pins [data-id="%d"] [data-act=confirm]' % first)
        row = page.locator("#review-pins .nt-row")
        row.wait_for(state="visible")
        box = row.bounding_box()
        page.mouse.move(box["x"] + 20, box["y"] + box["height"] / 2, steps=4)  # a real movement onto the row
        page.wait_for_timeout(7000)
        self.assertEqual(page.evaluate("CONFIRMS.length"), 1)  # held while the mouse is on it
        page.mouse.move(700, 300, steps=4)
        page.wait_for_function("CONFIRMS.length===2", timeout=9000)

    def test_7_an_undo_on_the_line_under_a_still_pointer_keeps_its_6_s(self):
        """Desktop, the panel closed: the pointer rests where the status line appears; a [확인]'s undo then appears on
        the line under it - the confirm goes when its 6 s end."""
        (pid,) = self.review_pins(6)
        page = self.view("desktop", init=SEEN + ";" + COUNT_CONFIRMS)
        page.evaluate("setSide(false)")
        page.evaluate("lineNote('자리 재기',NOTICE_KIND.INFO)")
        settle(page)
        box = page.locator("#status .st-tx").bounding_box()
        page.evaluate("LINE.slice().forEach(n=>endNotice(n,false))")  # gone without the mouse: the line hides
        settle(page)
        page.mouse.move(box["x"] + 10, box["y"] + box["height"] / 2, steps=4)
        page.evaluate("confirmPin(%d)" % pid)
        settle(page)
        self.assertTrue(page.evaluate("(()=>{const r=document.querySelector('#status .st-tx').getBoundingClientRect();"
                                      "return r.width>0;})()"))  # fmt: skip
        t0 = time.monotonic()
        page.wait_for_function("CONFIRMS.length===1", timeout=9000)
        self.assertLess(time.monotonic() - t0, 7.5)

    def test_8_a_note_edit_does_not_clear_a_failed_append(self):
        """Desktop: appending to a pin's note fails; a later edit of that pin's note (the same URL, another intent)
        succeeds and the append's failure stays; a later append that goes through clears it."""
        pid = self.pin(6, "덧붙일 핀")
        page = self.view("desktop", n_open=1)

        def edits(route):
            """POST /api/pins/<pid>/edit: an append fails, anything else reaches the server."""
            if "note_append" in (route.request.post_data or ""):
                return route.abort()
            return self.route(route)

        page.route("**/api/pins/%d/edit" % pid, edits)
        page.evaluate("appendToPin(%d,'덧붙인 줄')" % pid)
        settle(page)
        self.assertTrue(self.line_has(page, "메모 덧붙이기 실패"))
        page.evaluate("openEdit(%d)" % pid)
        page.fill('.pin[data-id="%d"] textarea.e-note' % pid, "고친 메모")
        page.evaluate("saveEdit()")
        settle(page)
        self.assertEqual(page.evaluate("PINS.find(p=>p.id===%d).note" % pid), "고친 메모")
        self.assertTrue(self.line_has(page, "메모 덧붙이기 실패"))
        page.unroute("**/api/pins/%d/edit" % pid)
        page.evaluate("appendToPin(%d,'덧붙인 줄')" % pid)
        settle(page)
        self.assertFalse(self.line_has(page, "메모 덧붙이기 실패"))

    def test_9_a_save_undo_answered_late_brings_the_composer_back_without_the_focus(self):
        """Desktop: the save chip's [되돌리기] pressed with the mouse, its delete held past the bound (#334): the status line
        says the undo is late, once. The person moves on to a tool button; the delete then goes through: the pin is gone,
        the composer is back with the note, the lateness is gone - and the focus is still on that button, which the note
        field took."""
        held = []  # the delete request, caught and held until the test lets it through
        page = self.view("desktop")
        self.compose(page, "되돌릴 메모")
        page.click("#btn-save")
        page.wait_for_selector(".mark .nt-chip")
        pid = page.evaluate("+document.querySelector('.mark:has(.nt-chip)').dataset.pin")
        page.route("**/api/pins/%d/drop" % pid, lambda route: held.append(route))
        page.evaluate("NOTICE_ACT_WAIT=150")
        page.locator(".mark .nt-chip [data-act=notice-act]").click()
        late = "()=>[...NOTICES.values()].filter(n=>n.title.startsWith('되돌리기의 답이 늦습니다 · 핀 #')).length"
        page.wait_for_function(late + "===1")
        self.assertEqual(len(held), 1)
        self.assertTrue(self.line_has(page, "핀 #%d 저장됨" % pid))
        page.focus("#btn-zoom-in")
        self.route(held[0])  # the delete reaches the server now
        page.wait_for_selector("#composer:not([hidden])")
        page.wait_for_function(late + "===0")
        settle(page)
        self.assertIsNone(self.state(pid))
        self.assertEqual(page.input_value("#note"), "되돌릴 메모")
        self.assertEqual(page.evaluate("document.activeElement.id"), "btn-zoom-in")
        self.assertEqual(len(held), 1)

    def test_10_a_save_undos_retry_answered_late_follows_the_same_focus_rule(self):
        """Desktop: the save chip's [되돌리기] cannot reach the server, so its failure offers [다시 시도] - no waiting action,
        so noticeAct's watch is not there. The retry's delete is held past the bound, then goes through: the composer is
        back with the note. With the focus moved to a tool button meanwhile it stays there; left alone, the note takes it as
        with an answer in time."""
        drops = []  # the delete requests: the first is lost on the way, the next held until the test lets it through

        def drop(route):
            """POST /api/pins/<pid>/drop: the first is lost, the rest are held."""
            drops.append(route)
            if len(drops) == 1:
                route.abort()

        for moved in (True, False):
            with self.subTest(moved=moved):
                self.tearDown()
                self.setUp()
                drops.clear()
                page = self.view("desktop")
                self.compose(page, "되돌릴 메모")
                page.click("#btn-save")
                page.wait_for_selector(".mark .nt-chip")
                pid = page.evaluate("+document.querySelector('.mark:has(.nt-chip)').dataset.pin")
                page.route("**/api/pins/%d/drop" % pid, drop)
                page.locator(".mark .nt-chip [data-act=notice-act]").click()
                retry = "()=>([...NOTICES.values()].find(n=>!!n.act&&n.act.label==='다시 시도')||{n:0}).n"
                page.wait_for_function(retry)
                settle(page)
                page.evaluate("NOTICE_ACT_WAIT=150")
                page.locator('[data-act="notice-act"][data-n="%d"]' % page.evaluate(retry)).first.click()
                for _ in range(100):
                    if len(drops) == 2:
                        break
                    page.wait_for_timeout(20)
                self.assertEqual(len(drops), 2)
                if moved:
                    page.focus("#btn-zoom-in")
                page.wait_for_timeout(300)  # past the bound
                self.route(drops[1])  # the retried delete reaches the server now
                page.wait_for_selector("#composer:not([hidden])")
                settle(page)
                self.assertIsNone(self.state(pid))
                self.assertEqual(page.input_value("#note"), "되돌릴 메모")
                self.assertEqual(page.evaluate("document.activeElement.id"), "btn-zoom-in" if moved else "note")
                self.assertEqual(len(drops), 2)


# The focused control's action (or tag) and its Trash row's pin.
TRASH_FOCUS = """() => {const a = document.activeElement, r = a && a.closest && a.closest('#trash-list .arc-row[data-id]');
  return [a ? a.dataset.act || a.tagName : '', r ? +r.dataset.id : null];}"""
# The message saying the Trash's [되살리기] of a pin is late, as [place, host, its text], or null.
RESTORE_LATE = """id => {const n = [...NOTICES.values()].find(n => n.source === NOTICE_LATE_SRC + 'restore:' + id);
  return n ? [n.place, n.host, n.title + (n.desc ? ' · ' + n.desc : '')] : null;}"""


class TrashRestore(NoticePage, BrowserBase):
    """[되살리기] on a Trash row (#336). By keyboard its row goes with the answer: the focus goes on in the Trash - the next
    row's [되살리기], else the one before's, else [닫기] - or stays on the row's when it failed; never to nothing, and a
    focus the person moved meanwhile is theirs. Its request has the bound an undo's has: past it the Trash (or, closed, the
    list) says the answer is late, and that goes with the answer."""

    def trash(self, n):
        """n pins deleted, the Trash open on the desktop; the page and the pins in the Trash's order."""
        ids = [self.pin(6 + 2 * i, "지울 핀 %d" % i) for i in range(n)]
        page = self.view("desktop", n_open=n)
        for pid in ids:
            page.evaluate("id=>dropPin(id,false)", pid)
        settle(page)
        page.evaluate("openTrash()")
        settle(page)
        order = page.evaluate(
            "()=>[...document.querySelectorAll('#trash-list .arc-row[data-id]')].map(r=>+r.dataset.id)"
        )
        self.assertEqual(sorted(order), sorted(ids))
        return page, order

    def press(self, page, pid):
        """Enter on pin pid's [되살리기] in the Trash."""
        page.locator('#trash-list .arc-row[data-id="%d"] [data-act="restore"]' % pid).focus()
        page.keyboard.press("Enter")

    def test_the_focus_goes_on_to_the_next_row_then_the_one_before_then_close(self):
        """Three rows a, b, c: b restored by key puts the focus on c's [되살리기]; c, the last, on a's; a, the only one, on
        [닫기]. The Trash stays open and every pin is back."""
        page, (a, b, c) = self.trash(3)
        for pid, then in ((b, ["restore", c]), (c, ["restore", a]), (a, ["trash-close", None])):
            self.press(page, pid)
            page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id)", arg=pid)
            settle(page)
            self.assertEqual(page.evaluate(TRASH_FOCUS), then, "after #%d" % pid)
            self.assertTrue(page.evaluate("()=>$('#trash').open"))
        self.assertEqual([self.state(x) for x in (a, b, c)], ["open"] * 3)

    def test_a_failed_restore_keeps_the_focus_on_its_row_and_a_moved_one_is_left_alone(self):
        """The restore answered 500: the row is drawn again and the focus is back on its [되살리기]. Then a restore held
        while the person moves to another row's [되살리기]: the answer leaves the focus there."""
        page, (a, b, c) = self.trash(3)
        held = []
        page.route("**/api/pins/%d/restore" % a, lambda route: held.append(route))
        self.press(page, a)
        for _ in range(100):
            if held:
                break
            page.wait_for_timeout(20)
        held[0].fulfill(status=500, headers={"content-type": "application/json"}, body='{"error": "서버 오류"}')
        page.wait_for_function("()=>[...NOTICES.values()].some(n=>n.kind===NOTICE_KIND.ERR)")
        settle(page)
        self.assertEqual(page.evaluate(TRASH_FOCUS), ["restore", a])
        self.assertFalse(page.evaluate("id=>OPEN_ALL.some(p=>p.id===id)", a))
        held.clear()
        self.press(page, a)
        for _ in range(100):
            if held:
                break
            page.wait_for_timeout(20)
        page.locator('#trash-list .arc-row[data-id="%d"] [data-act="restore"]' % c).focus()
        self.route(held[0])
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id)", arg=a)
        settle(page)
        self.assertEqual(page.evaluate(TRASH_FOCUS), ["restore", c])

    def late(self, n, kept=None):
        """n rows in the open Trash, the last one's restore pressed by key and held past the bound until its warning is in
        the Trash; the page, that pin and the held request. kept: the requests caught (kept[0] is held)."""
        held = [] if kept is None else kept
        page, order = self.trash(n)
        a = order[-1]
        page.route("**/api/pins/%d/restore" % a, lambda route: held.append(route))
        page.evaluate("NOTICE_ACT_WAIT=150")
        self.press(page, a)
        page.wait_for_function(RESTORE_LATE, arg=a)
        self.assertEqual(page.evaluate(RESTORE_LATE, a), ["banner", "trash", "되살리기의 답이 늦습니다 · 핀 #%d" % a])
        self.assertIn("되살리기의 답이 늦습니다", page.locator("#trash").inner_text())
        self.assertEqual(len(held), 1)
        return page, a, held

    def answered(self, page, a, held):
        """The held restore reaches the server: the warning goes with it, one request, the pin back."""
        self.route(held[0])
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id)", arg=a)
        page.wait_for_function("id=>!(" + RESTORE_LATE + ")(id)", arg=a)
        settle(page)
        self.assertEqual(self.state(a), "open")
        self.assertEqual(len(held), 1)

    def test_a_restore_that_does_not_answer_says_so_in_the_trash_and_where_it_is_closed_to(self):
        """The restore held past the bound: the Trash's banner says '되살리기의 답이 늦습니다 · 핀 #N', once, and goes with the
        answer. Closed while it waits, the Trash takes it out to the list or the line, which still says it, once."""
        held = []
        page, a, _ = self.late(1, held)
        self.answered(page, a, held)
        self.tearDown()
        self.setUp()
        held.clear()
        page, a, _ = self.late(1, held)
        page.keyboard.press("Escape")
        page.wait_for_function("()=>!$('#trash').open")
        page.wait_for_function(
            "id=>{const l=(" + RESTORE_LATE + ")(id); return !!l&&l[1]!=='trash';}", arg=a
        )  # on 'close'
        place, host, text = page.evaluate(RESTORE_LATE, a)
        self.assertEqual(text, "되살리기의 답이 늦습니다 · 핀 #%d" % a)
        self.assertNotEqual(host, "trash")
        self.assertEqual(
            page.evaluate(
                "()=>[...NOTICES.values()].filter(n=>(n.title+n.desc).includes('되살리기의 답이 늦습니다')).length"
            ),
            1,
        )
        self.answered(page, a, held)

    def test_a_focus_on_the_late_banner_stays_in_the_trash_when_it_goes(self):
        """The late banner's [x] has the focus when the restore answers: the banner goes, and the focus does not fall to
        nothing - the row is gone too, so it ends on the Trash's [닫기]."""
        held = []
        page, a, _ = self.late(1, held)
        page.locator("#trash .nt-banner [data-act=notice-x]").focus()
        self.answered(page, a, held)
        self.assertEqual(page.evaluate(TRASH_FOCUS), ["trash-close", None])

    def test_a_failure_answered_in_time_keeps_its_banner_while_the_reload_is_slow(self):
        """The restore answers 500 at once and the list reload after it is held past the bound: the failure's banner
        stays, and no lateness is said - the bound is the request's."""
        page, (a,) = self.trash(1)
        reloads = []
        page.route(
            "**/api/pins/%d/restore" % a,
            lambda route: route.fulfill(
                status=500, headers={"content-type": "application/json"}, body='{"error": "서버 오류"}'
            ),
        )
        page.evaluate("NOTICE_ACT_WAIT=150")
        page.route(lambda url: "/api/pins?" in url or url.endswith("/api/pins"), lambda route: reloads.append(route))
        self.press(page, a)
        page.wait_for_function("()=>[...NOTICES.values()].some(n=>n.kind===NOTICE_KIND.ERR)")
        page.wait_for_timeout(500)  # past the bound, the reload still held
        self.assertTrue(reloads)
        self.assertIsNone(page.evaluate(RESTORE_LATE, a))
        self.assertEqual(page.evaluate("()=>[...NOTICES.values()].filter(n=>n.kind===NOTICE_KIND.ERR).length"), 1)
        page.unroute(lambda url: "/api/pins?" in url or url.endswith("/api/pins"))
        for r in reloads:
            self.route(r)
        settle(page)
        self.assertEqual(page.evaluate("()=>[...NOTICES.values()].filter(n=>n.kind===NOTICE_KIND.ERR).length"), 1)


if __name__ == "__main__":
    unittest.main()

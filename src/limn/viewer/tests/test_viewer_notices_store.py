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
    "isUndo", "lineCap", "sameWords",
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
const NOTICES=new Map(),LINE=[],BANNERS=new Map(),DEFERRED=new Set(); let NOTICE_SEQ=0,LINE_HOVER=false;
function drawStatus(){lineVisible(LINE.length>0);}
"""

# Random sequences of: add an undo (a deferred send on the line, as with the panel closed), add an error or a piece of
# information, a source's success, press an undo, dismiss any message, a mouse onto and off the line, the line hiding,
# pagehide, and time passing. The invariants are checked after every step, and at the end once every window has run out.
MODEL_RUN = r"""
function rng(seed){return ()=>{seed=seed+0x6D2B79F5|0; let t=Math.imul(seed^seed>>>15,1|seed); t=t+Math.imul(t^t>>>7,61|t)^t; return ((t^t>>>14)>>>0)/4294967296;};}
const bad=[],OPS=['undo','undo','error','error','info','ok','press','dismiss','in','out','hide','pagehide','tick','tick','tick'];
for(let s=1;s<=SEEDS;s++){
  NOTICES.clear(); LINE.length=0; BANNERS.clear(); DEFERRED.clear(); Q.length=0; BODY.clear(); NOW=0; LINE_HOVER=false;
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
    else if(op==='in')lineHoverIn({pointerType:'mouse'});
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
        no pause survives the line hiding; at most one entry per error source; no error survives a later success of
        its source."""
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


if __name__ == "__main__":
    unittest.main()

"""The viewer page (src/limn/viewer): its scripts run under node, its HTML and CSS read as the page the server serves
(HTML), and its layout measured in a real Chromium.

Most classes check the served page for the fixed pattern and the absence of the old bug pattern. The ...Logic classes
pull pure functions out of the page with extract_js_fn and run them under node (skipped without node).
FrontendResponsiveBrowser drives Chromium ($LIMN_CHROMIUM, then a system Chrome/Chromium, then Playwright's bundled one;
skipped when none starts, a failure under LIMN_TEST_REQUIRE_BROWSER=1). How the page is assembled from its parts is
src/limn/viewer/tests/test_viewer_files.py and src/limn/viewer/tests/test_viewer_assemble.py; input and gestures are src/limn/viewer/tests/test_viewer_input.py;
whole feature flows in a real browser are src/limn/viewer/tests/test_viewer_browser.py.

Run: uv run pytest src/limn/viewer/tests/test_viewer.py
"""

import json
import re
import shutil
import unittest
from pathlib import Path

from limn.builds import figure_map
from limn.collaboration.events import NOTIFY_TYPES
from limn.pins.listing import render as md_render
from limn.pins.location import position
from limn.viewer import assemble as viewer_assemble

import helpers_js
from helpers import (
    DOCS_DIR,
    HTML,
    PKG,
    RULE_CASES,
    SKILL_KO,
    SKILL_MD,
    SW_JS,
    UI_EN,
    VIEWER_CLOSED_SETS,
    extract_js_fn,
    js_esc,
    js_i18n,
    js_icons,
    js_markup,
    js_thread,
    page_for,
    ps,
    rec_for,
    run_node,
)
from helpers_browser import ChromiumTestCase

# ---------------------------------------------------------------- frontend pure logic (run the real source under node)
#
# The server only uses the standard library and 127.0.0.1, but these tests run the client JS as-is under
# node for regression verification (they don't change the server itself). Skipped in environments without node.


class FrontendLogic(unittest.TestCase):
    """Exercise selection overlap, pin estimates, build polling, and other viewer decisions with real script functions."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_is_estimated_draws_server_est_only_regardless_of_timezone(self):
        # design 1: the viewer draws the est the server gave it as-is — it never re-judges via timezone/edited_at/sync.
        js = "\n".join(
            [
                extract_js_fn("isEstimated"),
                r"""
            const out=[isEstimated({est:true}), isEstimated({est:false,sync:'moved +3',at:'2026-01-01 00:00:00'}),
                       isEstimated({}), isEstimated({est:'true'})];
            console.log(JSON.stringify(out));
            """,
            ]
        )
        seoul = json.loads(run_node(js, tz="Asia/Seoul"))
        ny = json.loads(run_node(js, tz="America/New_York"))
        self.assertEqual(seoul, [True, False, False, False])
        self.assertEqual(seoul, ny)

    def test_sel_rel_matches_python_selection_rel(self):
        # design 2: the viewer recounts overlaps every time the range changes, without a round trip to the server — the rule must match the server's.
        cases = [(lo, hi, 4, 7) for lo in range(1, 10) for hi in range(lo, 11)]
        js = "\n".join(
            [
                extract_js_fn("selRel"),
                "console.log(JSON.stringify(%s.map(c=>selRel(c[0],c[1],c[2],c[3]))));" % json.dumps(cases),
            ]
        )
        got = json.loads(run_node(js))
        self.assertEqual(got, [position.selection_rel(*c) for c in cases])

    def test_overlaps_for_filters_by_file_and_skips_done(self):
        js = "\n".join(
            [
                extract_js_fn("selRel"),
                extract_js_fn("pinState"),
                extract_js_fn("overlapsFor"),
                r"""
            const PINS=[{id:1,file:'/a.tex',lo:4,hi:9},{id:2,file:'/b.tex',lo:4,hi:9},{id:3,file:'/a.tex',lo:4,hi:9,done:true},
                        {id:4,file:'/a.tex',lo:5,hi:5},{id:5,file:'/a.tex',lo:20,hi:30}];
            console.log(JSON.stringify(overlapsFor({file:'/a.tex',lo:4,hi:9},PINS)));
            """,
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)),
            [{"id": 1, "lo": 4, "hi": 9, "rel": "equal"}, {"id": 4, "lo": 5, "hi": 5, "rel": "contains"}],
        )

    def test_pick_overlap_priority_equal_inside_contains_partial(self):
        js = "\n".join(
            [
                extract_js_fn("pickOverlap"),
                r"""
            const out=[];
            out.push(pickOverlap([{id:6,lo:241,hi:243,rel:'contains'}]));
            out.push(pickOverlap([{id:1,lo:1,hi:100,rel:'contains'},{id:2,lo:10,hi:20,rel:'inside'}]));
            out.push(pickOverlap([{id:1,lo:1,hi:5,rel:'contains'},{id:2,lo:1,hi:9,rel:'contains'}]));
            out.push(pickOverlap([{id:3,lo:1,hi:9,rel:'inside'},{id:7,lo:4,hi:5,rel:'equal'}]));
            out.push(pickOverlap([{id:9,lo:1,hi:9,rel:'partial'},{id:8,lo:4,hi:12,rel:'partial'}]));
            console.log(JSON.stringify(out.map(o=>o&&o.id)));
            """,
            ]
        )
        self.assertEqual(json.loads(run_node(js)), [6, 2, 2, 7, 8])

    def test_overlap_banner_follows_level_change_and_dismiss_resets(self):
        # must-1 live path: drag (default level = env, wraps the pin) -> switch to [paragraph] level to
        # match an existing pin's range -> the banner switches to "same range". [Save as separate pin]
        # only turns off that relation and comes back on a fresh drag (pick's reset).
        js = "\n".join(
            [
                r"""
            const box={hidden:true,dataset:{},innerHTML:'',cls:new Set(),classList:{toggle(c,on){on?box.cls.add(c):box.cls.delete(c);}}};
            const $=s=>box;
            const COMPOSE={current:null,dismissedOverlap:null}; let PINS=[{id:5,file:'/m.tex',lo:405,hi:406}];
            const esc=s=>String(s);
            """,
                js_markup(),
                extract_js_fn("selRel"),
                extract_js_fn("pinState"),
                extract_js_fn("overlapsFor"),
                extract_js_fn("pickOverlap"),
                extract_js_fn("josa"),
                extract_js_fn("overlapText"),
                extract_js_fn("recomputeOverlap"),
                extract_js_fn("renderOverlapBanner"),
                extract_js_fn("overlapShort"),
                "let LAYOUT=LAYOUT_MODE.WIDE;",
                extract_js_fn("lvOf"),
                extract_js_fn("useLevel"),
                r"""
            const out=[];
            COMPOSE.current={file:'/m.tex',lo:401,hi:413,levels:[{level:'para',lo:405,hi:406},{level:'env',lo:401,hi:413}]};
            recomputeOverlap(); renderOverlapBanner(); out.push([box.hidden, box.dataset.rel]);
            useLevel(COMPOSE.current,'para'); recomputeOverlap(); renderOverlapBanner(); out.push([box.hidden, box.dataset.rel, /같은 범위/.test(box.innerHTML)]);
            COMPOSE.dismissedOverlap='5:equal'; renderOverlapBanner(); out.push([box.hidden]);
            useLevel(COMPOSE.current,'env'); recomputeOverlap(); renderOverlapBanner(); out.push([box.hidden, box.dataset.rel]);   // 관계가 바뀌면 다시 알림
            COMPOSE.dismissedOverlap=null;                        // pick() 의 리셋(새 선택)
            useLevel(COMPOSE.current,'para'); recomputeOverlap(); renderOverlapBanner(); out.push([box.hidden, box.dataset.rel]);
            LAYOUT=LAYOUT_MODE.NARROW; renderOverlapBanner();   // the phone sheet: one line, the short relation, the lines in the tooltip
            out.push([box.cls.has('one'), /<span class="ov-t" data-tip="[^"]*\(L405-L406\)">#5와 같은 범위<\/span>/.test(box.innerHTML), />덧붙이기</.test(box.innerHTML)]);
            LAYOUT=LAYOUT_MODE.WIDE; renderOverlapBanner(); out.push([box.cls.has('one')]);
            console.log(JSON.stringify(out));
            """,
            ]
        )
        out = json.loads(run_node(js))
        self.assertEqual(out[0], [False, "contains"])
        self.assertEqual(out[1], [False, "equal", True])
        self.assertEqual(out[2], [True])
        self.assertEqual(out[3], [False, "contains"])
        self.assertEqual(out[4], [False, "equal"])
        self.assertEqual(out[5], [True, True, True])  # narrow: one line (input diagnosis P2)
        self.assertEqual(out[6], [False])

    def test_poll_build_single_flight_and_once_per_seq(self):
        # design 4: pollBuild is single-flight — no matter how many times it's called concurrently,
        # /api/build fires once and completion (one seq) is handled once. A freshly opened tab shows an
        # already-failed build in the panel only, with no toast.
        js = "\n".join(
            [
                r"""
            const document={hidden:false};
            const el=()=>({hidden:true,textContent:'',disabled:false});
            const els={}; const $=s=>(els[s]=els[s]||el());
            let calls=0, resolveApi=null, nextState=null;
            function api(url){calls++; return new Promise(r=>{resolveApi=()=>r({data:nextState});});}
            const toasts=[], panels=[]; let refreshes=0;
            function toast(m,k){toasts.push(k);} function showBuildErr(b){panels.push(b.state);} function hideBuildErr(){}
            async function refreshDoc(){refreshes++;}
            const META={pages:[1,2]};
            let timers=0; function setInterval(){timers++; return 1;} function clearInterval(){}
            const BUILD={timer:null,error:null,lastSeq:3,booted:false,inflight:null};
            // 여러 문서(§Multiple documents) 전역 — 단일 문서 뷰어와 같은 값
            const DOC='main', SWITCHSEQ=0, DOC_SEQ=new Map(), BUILD_ERR_BY=new Map(); function dq(u){return u;}
            """,
                extract_js_fn("buildChipText"),
                extract_js_fn("pullSuffix"),
                extract_js_fn("buildsFromSource"),
                extract_js_fn("pollBuild"),
                extract_js_fn("pollBuildOnce"),
                r"""
            (async()=>{
              const out={};
              // 부팅: 이미 ok_errors 로 끝난 빌드(seq 그대로) → 패널만, 토스트 없음
              nextState={state:'ok_errors',seq:3,errors:[]};
              const p=pollBuild(); resolveApi(); await p;
              out.boot={calls, toasts:toasts.slice(), panels:panels.slice(), refreshes};
              // 동시 세 번 → 요청 한 번, 완료 처리 한 번
              calls=0; toasts.length=0; panels.length=0;
              nextState={state:'ok',seq:4,elapsed_s:3};
              const a=pollBuild(), b=pollBuild(), c=pollBuild();
              out.same=(a===b&&b===c);
              resolveApi(); await Promise.all([a,b,c]);
              out.burst={calls, toasts:toasts.slice(), refreshes};
              // 같은 seq 를 다시 봐도 아무 일 없음
              const d=pollBuild(); resolveApi(); await d;
              out.again={calls, toasts:toasts.slice(), refreshes};
              // 숨은 탭은 요청하지 않는다
              document.hidden=true; await pollBuild(); out.hidden=calls; document.hidden=false;
              // 5초 틈새에 두 빌드가 지나감(seq 4→6, 마지막 fail) → 한 번만, fail 토스트
              nextState={state:'fail',seq:6,errors:[]};
              const e=pollBuild(); resolveApi(); await e;
              out.skip={toasts:toasts.slice(), panels:panels.slice()};
              console.log(JSON.stringify(out));
            })();
            """,
            ]
        )
        out = json.loads(run_node(js))
        self.assertEqual(out["boot"], {"calls": 1, "toasts": [], "panels": ["ok_errors"], "refreshes": 0})
        self.assertTrue(out["same"])
        self.assertEqual(out["burst"], {"calls": 1, "toasts": ["ok"], "refreshes": 1})
        self.assertEqual(out["again"], {"calls": 2, "toasts": ["ok"], "refreshes": 1})
        self.assertEqual(out["hidden"], 2)
        self.assertEqual(out["skip"], {"toasts": ["ok", "err"], "panels": ["fail"]})

    def test_rel_badge_matches_python_smallest_inside_rule(self):
        # bug: relBadge (JS, card tag) used to pick insides[0] (the order the server happened to send,
        # arbitrary), while the server's rel_badge() (pins.md) picked the outer pin with the smallest
        # range — the card and pins.md notations disagreed.
        js = "\n".join(
            [
                extract_js_fn("josa"),
                extract_js_fn("relBadge"),
                r"""
            const PINS=[{id:1,lo:1,hi:100},{id:2,lo:10,hi:20},{id:3,lo:5,hi:50}];
            // rel 배열은 실제 서버 순서를 흉내내 일부러 '가장 작은 것'을 뒤에 둔다.
            const rel=[{id:1,rel:'inside'},{id:3,rel:'inside'},{id:2,rel:'inside'}];
            console.log(JSON.stringify(relBadge(rel)));
            """,
            ]
        )
        out = json.loads(run_node(js))
        self.assertEqual(out["id"], 2)  # id=2 (range 10-20, length 11) is the smallest outer pin

        # compare the same rule with the same by_id on the Python side (rel_badge, pins.md).
        by_id = {1: {"lo": 1, "hi": 100}, 2: {"lo": 10, "hi": 20}, 3: {"lo": 5, "hi": 50}}
        rel = [{"id": 1, "rel": "inside"}, {"id": 3, "rel": "inside"}, {"id": 2, "rel": "inside"}]
        self.assertEqual(md_render.rel_badge(rel, by_id), "#2 범위 안")

    def test_jump_to_card_sets_cur_and_clears_highlight_after_timeout(self):
        # bug: clicking the badge only added .flash (no .cur), and since the box-shadow was static, the highlight never went away.
        js = "\n".join(
            [
                r"""
            // jumpToCard 가 쓰는 만큼만 최소 DOM 을 흉내낸다.
            function makeEl(){
              const classes=new Set();
              return {
                classList:{add:(...c)=>c.forEach(x=>classes.add(x)),
                           remove:(...c)=>c.forEach(x=>classes.delete(x)),
                           contains:c=>classes.has(c)},
                scrollIntoView(){}, get offsetWidth(){return 0;},
              };
            }
            const el=makeEl();
            const document={querySelector:()=>el, querySelectorAll:()=>[]};
            const $=s=>document.querySelector(s), $$=s=>Array.from(document.querySelectorAll(s));
            const SMOOTH='auto'; function secOpenFor(){return false;}
            """,
                extract_js_fn("jumpToCard"),
                r"""
            jumpToCard(1);
            const mid=[el.classList.contains('cur'), el.classList.contains('flash')];
            // setTimeout 콜백을 동기로 즉시 실행할 수 있게 node 의 실제 타이머를 아주 짧게 기다린다.
            setTimeout(()=>{
              const after=[el.classList.contains('cur'), el.classList.contains('flash')];
              console.log(JSON.stringify({mid, after}));
            }, 1300);
            """,
            ]
        )
        out = json.loads(run_node(js))
        self.assertEqual(out["mid"], [True, True])  # right after clicking: both .cur and .flash are present
        self.assertEqual(out["after"], [False, False])  # after 1.2s: the highlight clears (static box-shadow bug fixed)

    def test_diff_toast_distinguishes_dropped_from_closed(self):
        # §A: the old implementation reported every pin that disappeared from the open list as "done" —
        # even a pin a coauthor dropped showed up on the author's screen as '#N 이 완료되었습니다' (observed).
        # id 2 is dropped because it's absent from d (open+closed) entirely; id 3 is done because it's in d with done:true.
        js = "\n".join(
            [
                r"""
            function who(a){return (a&&(a.name||a.login))||'';}
            const TOASTS=[]; const RESTORED=[];
            function toast(msg,kind,action){TOASTS.push({msg,kind,hasAction:!!action});}
            function restorePin(id){RESTORED.push(id);}
            const MY_ACTIONS=new Map();
            """,
                extract_js_fn("markMine"),
                extract_js_fn("consumeMine"),
                extract_js_fn("pinState"),
                extract_js_fn("diffToast"),
                r"""
            const prev=[{id:1},{id:2},{id:3}];
            const d=[{id:1,done:false},{id:3,done:true}];
            const dropped=[{id:2,dropped_by:{name:'Bob'}}];
            diffToast(prev,d,dropped);
            console.log(JSON.stringify(TOASTS));
            """,
            ]
        )
        out = json.loads(run_node(js))
        self.assertEqual(len(out), 2)
        closed = [t for t in out if "완료" in t["msg"]]
        dropped = [t for t in out if "삭제함" in t["msg"]]
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["msg"], "#3 이 완료되었습니다")
        self.assertEqual(closed[0]["kind"], "ok")
        self.assertEqual(len(dropped), 1)
        self.assertEqual(dropped[0]["msg"], "#2 을 Bob 가 삭제함")
        self.assertEqual(dropped[0]["kind"], "warn")
        self.assertTrue(dropped[0]["hasAction"])  # the [되살리기] (restore) action is attached

    def test_diff_toast_dropped_action_calls_restore_pin(self):
        js = "\n".join(
            [
                r"""
            function who(a){return (a&&(a.name||a.login))||'';}
            let CAPTURED=null; const RESTORED=[];
            function toast(msg,kind,action){if(action)CAPTURED=action;}
            function restorePin(id){RESTORED.push(id);}
            const MY_ACTIONS=new Map();
            """,
                extract_js_fn("markMine"),
                extract_js_fn("consumeMine"),
                extract_js_fn("pinState"),
                extract_js_fn("diffToast"),
                r"""
            diffToast([{id:9}],[],[{id:9,dropped_by:{login:'x'}}]);
            CAPTURED.fn();
            console.log(JSON.stringify(RESTORED));
            """,
            ]
        )
        self.assertEqual(json.loads(run_node(js)), [9])

    def test_diff_toast_unknown_dropper_falls_back_to_generic_label(self):
        js = "\n".join(
            [
                r"""
            function who(a){return (a&&(a.name||a.login))||'';}
            const TOASTS=[]; function toast(msg,kind,action){TOASTS.push(msg);}
            function restorePin(id){}
            const MY_ACTIONS=new Map();
            """,
                extract_js_fn("markMine"),
                extract_js_fn("consumeMine"),
                extract_js_fn("pinState"),
                extract_js_fn("diffToast"),
                r"""
            diffToast([{id:5}],[],[]);   // dropped 목록에도 없음(폴링 경합) — 그래도 삭제로는 알린다
            console.log(JSON.stringify(TOASTS));
            """,
            ]
        )
        out = json.loads(run_node(js))
        self.assertEqual(len(out), 1)
        self.assertIn("#5 을", out[0])
        self.assertIn("삭제함", out[0])

    def test_diff_toast_suppresses_own_recent_action_but_not_others(self):
        # bug: a pin the same tab just closed or dropped would also flow straight through diffToast
        # without markMine, doubling up with the local toast. An id marked via markMine(id) should be
        # swallowed exactly once; an unmarked id (= done by another tab) must still be reported.
        js = "\n".join(
            [
                r"""
            function who(a){return (a&&(a.name||a.login))||'';}
            const TOASTS=[]; function toast(msg,kind,action){TOASTS.push(msg);}
            function restorePin(id){}
            const MY_ACTIONS=new Map();
            """,
                extract_js_fn("markMine"),
                extract_js_fn("consumeMine"),
                extract_js_fn("pinState"),
                extract_js_fn("diffToast"),
                r"""
            markMine(1); markMine(2);   // 이 탭이 방금 #1 을 완료, #2 를 삭제했다
            const prev=[{id:1},{id:2},{id:3},{id:4}];
            const d=[{id:1,done:true},{id:3,done:true}];   // #2,#4 는 d 에 없음=삭제
            const dropped=[{id:2,dropped_by:{login:'me'}},{id:4,dropped_by:{name:'Coauthor'}}];
            diffToast(prev,d,dropped);
            console.log(JSON.stringify(TOASTS));
            """,
            ]
        )
        out = json.loads(run_node(js))
        joined = " | ".join(out)
        self.assertNotIn("#1", joined)  # own action — suppressed
        self.assertNotIn("#2", joined)  # own action — suppressed
        self.assertIn("#3 이 완료되었습니다", joined)  # another tab's completion — shown as-is
        # another tab's drop — shown as-is
        self.assertTrue(any("#4" in t and "삭제함" in t and "Coauthor" in t for t in out))


# ---------------------------------------------------------------- frontend structure (source-string inspection)
#
# Running the full polling loop and automatic panel display, which spans timers, fetch, and visibility,
# under node would require faking fetch/document.hidden/setInterval entirely (this project's hard
# constraint is stdlib-only, so we can't add such a shim to the server) — so instead we check the actual
# deployed HTML source string for the fixed pattern and the absence of the pre-fix pattern. This isn't
# execution verification, but it does catch regressions (reverting to the original bug pattern).


class FrontendStructure(unittest.TestCase):
    """Guard the assembled viewer wiring for polling, build errors, document menus, and interaction controls."""

    def test_build_polling_is_conditional_not_permanent(self):
        # bug: startBuildPolling() used to unconditionally set setInterval(pollBuild,1000), calling
        # /api/build every second even when the tab was hidden or there was nothing to do.
        m = re.search(r"function startBuildPolling\(\)\{(.*?)\n\}", HTML, re.S)
        self.assertIsNotNone(m)
        self.assertNotIn("setInterval(pollBuild", m.group(1))
        self.assertIn("pollBuild()", m.group(1))
        m1 = re.search(r"\nfunction pollBuild\(\)\{(.*?)\n\}", HTML, re.S)
        self.assertIn("if(document.hidden)returnPromise.resolve()", m1.group(1).replace(" ", ""))
        self.assertIn("if(BUILD.inflight)returnBUILD.inflight", m1.group(1).replace(" ", ""))
        m2 = re.search(r"async function pollBuildOnce\(\)\{(.*?)\n\}", HTML, re.S)
        body = m2.group(1)
        self.assertIn("if(!BUILD.timer)BUILD.timer=setInterval(pollBuild,1000)", body.replace(" ", ""))
        self.assertIn("clearInterval(BUILD.timer)", body)

    def test_light_poll_kicks_off_build_polling_when_running_or_seq_changed(self):
        m = re.search(r"async function pollLightOnce\(\)\{(.*?)\n\}", HTML, re.S)
        body = m.group(1).replace(" ", "")
        self.assertIn("d.build&&d.build.state===BUILD_STATE.RUNNING", body)
        self.assertIn("d.build_seq!==BUILD.lastSeq", body)
        self.assertIn("pollBuild()", body)

    def test_light_poll_is_single_flight(self):
        # bug: when visibilitychange and focus overlapped, pollLight() would call /api/meta·loadPins
        # fresh each time, firing loadPins up to 3 times. It needs the same single-flight pattern as pollBuild.
        m = re.search(r"\nfunction pollLight\(\)\{(.*?)\n\}", HTML, re.S)
        self.assertIsNotNone(m)
        body = m.group(1).replace(" ", "")
        self.assertIn("if(document.hidden)returnPromise.resolve()", body)
        self.assertIn("if(LIGHT_INFLIGHT)returnLIGHT_INFLIGHT", body)
        self.assertIn("LIGHT_INFLIGHT=pollLightOnce()", body)

    def test_build_err_reopen_affordance_exists(self):
        self.assertIn('id="build-err-chip"', HTML)
        self.assertIn('data-act="build-err-reopen"', HTML)
        self.assertIn("case 'build-err-reopen'", HTML)
        self.assertIn("function hideBuildErr()", HTML)
        self.assertIn("case 'err-close':hideBuildErr()", HTML)

    def test_doc_menu_closes_even_when_switch_doc_is_synchronous_and_cached(self):
        # regression: when switchDoc() runs synchronously through drawDocTabs->drawDocsMenu for a cached
        # document, it redraws the open #nav-sheet, detaching the clicked <a> from the DOM. Calling
        # a.closest() after switchDoc() then returns null and the menu stays open — inMenu must always
        # be determined *before* calling switchDoc().
        m = re.search(r"case 'doc':\{(.*?)\}", HTML, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        js = (
            """
            (async()=>{
              const out={};
              const docsMenu={closed:false,close(){this.closed=true;}};
              function $(sel){return sel==='#nav-sheet'?docsMenu:{};}
              let detached=false;
              function switchDoc(k){detached=true;}   // 캐시된 문서: 동기로 끝나며 a 를 떼어낸 것을 흉내
              const a={dataset:{doc:'ms'},closest(sel){return (!detached&&sel==='#nav-sheet')?{}:null;}};
              switch('doc'){case 'doc':{%s}}
              out.closed=docsMenu.closed;
              console.log(JSON.stringify(out));
            })();
            """
            % body
        )
        out = run_node(js)
        if out is None:
            self.skipTest("node not available")
        data = json.loads(out)
        self.assertTrue(data["closed"], "#nav-sheet must close even when the selected document is cached")

    def test_pick_resets_overlap_dismissed_and_recounts(self):
        m = re.search(r"async function pick\(r\)\{(.*?)\n\}", HTML, re.S)
        body = m.group(1)
        cur_idx = body.index("COMPOSE.current=sel;")
        self.assertGreater(body.index("COMPOSE.dismissedOverlap=null"), cur_idx)
        self.assertGreater(body.index("sel.overlaps=overlapsFor(sel,PINS)"), cur_idx)

    def test_level_and_excerpt_lines_recount_overlap_only_for_composer(self):
        m = re.search(r"case 'level':\{(.*?)\}\s*\n", HTML)
        self.assertIsNotNone(m)
        self.assertIn("if(!inEdit)recomputeOverlap()", m.group(1).replace(" ", ""))
        self.assertIn("if(o===COMPOSE.current)recomputeOverlap()", extract_js_fn("applyRange"))

    def test_pdf_build_travels_drag_to_pick_to_save_and_repick(self):
        self.assertIn("pdf_build:META.pages_build", HTML)  # drag -> /api/pick
        self.assertIn("quote:d.quote,pdf_build:d.pdf_build", HTML)  # pick response -> /api/pin
        self.assertIn("frac:c.frac,pdf_build:c.pdf_build", HTML)  # relocate -> loc

    def test_no_wall_clock_estimate_left_in_viewer(self):
        self.assertNotIn("pinAtEpoch", HTML)
        self.assertNotIn("frac_build", HTML)
        self.assertNotIn("LAST_SEEN_BUILD", HTML)

    def test_trash_ui_exists(self):
        # §B, v0.2.2: deleted pins live in the Trash dialog ([⋯] -> 휴지통 N, or the link under the list) with a restore button -
        # not in a section of the list.
        self.assertIn('<dialog id="trash"', HTML)
        self.assertIn('id="trash-list"', HTML)
        self.assertIn("case 'trash-open':openTrash();break;", HTML)
        self.assertNotIn('id="dropped-toggle"', HTML)
        self.assertIn("function droppedCard(", HTML)
        self.assertIn('data-act="restore"', HTML)
        self.assertIn("case 'restore':restorePin(id)", HTML)

    def test_load_pins_fetches_dropped_list_for_diff_and_panel(self):
        m = re.search(r"async function loadPins\(\)\{(.*?)\n\}", HTML, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn("/api/pins/dropped", body)
        applied = extract_js_fn("applyPinLists")
        self.assertIn("DROPPED=dropped", applied)
        self.assertIn("diffToast(prevOpen,rows,dropped)", applied)

    def test_draw_pins_counts_the_trash(self):
        body = extract_js_fn("drawPins")
        # LDROP = listDropped() (current document or all documents)
        self.assertIn("LDROP.filter(p=>!PURGING.has(p.id)).length", body)
        self.assertIn("tl('휴지통 {n}',{n:nTrash})", body)
        self.assertIn("if($('#trash').open)drawTrash();", body)
        self.assertIn("map(droppedCard)", extract_js_fn("drawTrash"))

    def test_done_card_shows_close_reply_and_ref(self):
        # §C: a closed card shows the reply/ref left at close time (both go through esc).
        m = re.search(r"function doneCard\(p\)\{(.*?)\n\}", HTML, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn("p.close_ref", body)
        self.assertIn("p.close_reply", body)
        self.assertIn("arcLine('r:'+p.id,p.close_reply", body)  # the reply line is drawn by arcLine, going through esc
        self.assertIn("fmtText(text,logins)", extract_js_fn("arcLine"))  # fmtText goes through esc first
        self.assertIn("${p.close_ref}", body)

    def test_close_curl_example_in_skill_md_documents_reply_and_ref(self):
        # whether the close example in SKILL.md's '핀 소비 절차' section was updated to leave reply/ref (§C).
        skill = SKILL_MD.read_text(encoding="utf-8")
        self.assertIn('"reply"', skill)
        self.assertIn('"ref"', skill)
        self.assertIn("/close", skill)


# ---------------------------------------------------------------- viewer structure — claim UI · log=1


class FrontendClaimUI(unittest.TestCase):
    """Check claim controls, role visibility, and build status requests in the served page."""

    def test_claim_badge_and_unclaim_button_wired(self):
        self.assertIn("function claimActive(", HTML)
        self.assertIn("function claimLabel(", HTML)
        self.assertIn('data-act="unclaim"', HTML)
        self.assertIn("case 'unclaim':unclaimPin(id)", HTML)
        self.assertIn("function unclaimPin(", HTML)
        self.assertIn("/api/pins/'+id+'/unclaim'", HTML)

    def test_no_claim_button_offered_to_viewer(self):
        # the viewer never claims (agent-only) — there must be no 'claim' action button.
        self.assertNotIn('data-act="claim"', HTML)

    def test_build_status_fetch_requests_full_log(self):
        self.assertIn("/api/build?log=1", HTML)

    def test_pull_chip_and_toast_wiring(self):
        self.assertIn("원격 main 당겨오는 중", HTML)
        self.assertIn("function pullSuffix(", HTML)
        self.assertIn("pullSuffix(b)", HTML)


# Mobile (Galaxy Z Fold 7 etc.) — docs/handbook/viewer.md §모바일 레이아웃. Measured live with Playwright; here we
# check that the deployed HTML has the required elements/copy/CSS/event paths, and run the pure-logic
# functions under node.
class FrontendMobileStructure(unittest.TestCase):
    """Guard viewport, toolbar, touch targets, and compact layout markup and styles."""

    def test_viewport_meta_allows_zoom_and_handles_keyboard_and_notch(self):
        m = re.search(r'<meta name="viewport" content="([^"]*)"', HTML)
        self.assertIsNotNone(m)
        v = m.group(1)
        for part in (
            "width=device-width",
            "initial-scale=1",
            "viewport-fit=cover",
            "interactive-widget=resizes-content",
        ):
            self.assertIn(part, v)
        # pinch-zoom is not blocked — you need to zoom to read the manuscript
        self.assertNotIn("user-scalable=no", v)
        self.assertNotIn("maximum-scale", v)

    def test_rebuild_label_is_short_everywhere(self):
        self.assertIn('data-act="rebuild"', HTML)
        self.assertRegex(
            HTML,
            r'id="btn-rebuild"[^>]*aria-label="PDF 재빌드"[^>]*><svg class="ic ic-refresh-cw"[^>]*>(?:(?!</svg>).)*</svg><span class="lbl">PDF 재빌드</span></button>',
        )
        self.assertNotIn("다시 만들기", HTML)
        self.assertNotIn("다시 만들기", Path(ps.__file__).read_text(encoding="utf-8"))
        for doc in [SKILL_MD, SKILL_KO] + sorted(DOCS_DIR.glob("*.md")):
            self.assertFalse("PDF 다시 만들기" in doc.read_text(encoding="utf-8"), doc.name)

    def test_layout_rules_hang_on_band_classes_not_width_queries(self):
        """The band is chosen in JS (layoutFor) from width, height and pointer: a width media query left in the CSS would
        switch on its own and disagree with it. The overlay panel's rules hang on body.mid-overlay instead of the old
        701-900px query."""
        css = (PKG / "viewer" / "css" / "responsive.css").read_text(encoding="utf-8")
        self.assertNotIn("min-width:701px", css)
        self.assertNotRegex(css, r"max-width:\s*900px")
        self.assertIn("body.mid-overlay.side-open #right{", css)

    def test_compact_toolbar_elements_and_more_menu(self):
        for el in (
            'id="btn-side"',
            'id="side-n"',
            'id="btn-select"',
            'id="btn-more"',
            '<dialog id="more"',
            'id="coach"',
            'id="more-info"',
            'id="m-trash"',
            'id="more-foot"',
            'id="btn-pos"',
        ):
            self.assertIn(el, HTML)
        # theme and language are segments showing the current value; the closed-pins row and the page field are gone (UX spec §V7)
        for seg in ("m-theme", "m-lang"):
            self.assertRegex(HTML, r'<div [^>]*id="%s"[^>]*role="radiogroup"' % seg)
        for gone in ('id="m-done"', 'id="m-jump"'):
            self.assertNotIn(gone, HTML)
        self.assertIn('aria-pressed="false"', re.search(r'<button id="btn-select"[^>]*>', HTML).group(0))
        # less important buttons are hidden in compact mode (.sec) and live inside [⋯] with the same data-act; the desktop's
        # bell, theme button and [?] are gone - [⋯] opens the same [더보기] there too (3b of the cross-resolution pass)
        for gone in ('id="btn-notify"', 'id="btn-theme"', 'id="btn-help"'):
            self.assertNotIn(gone, HTML)
        for bid, act in (
            ("btn-reload", "reload"),
            ("btn-zoom-out", "zoom-out"),
            ("btn-zoom-in", "zoom-in"),
            ("btn-fit", "fit"),
        ):
            tag = re.search(r'<button id="%s"[^>]*>' % bid, HTML).group(0)
            self.assertRegex(tag, r'class="sec( btn-[a-z]+)*"')
            more = HTML[HTML.index('<dialog id="more"') : HTML.index('<dialog id="help"')]
            self.assertIn('data-act="%s"' % act, more)
        self.assertRegex(HTML, r'<input class="n sec" id="jump"')
        self.assertIn("body.compact .sec{display:none}", HTML)
        for act in ("side", "selmode", "more", "more-close", "coach-close", "card-toggle"):
            self.assertIn("case '%s':" % act, HTML)

    def test_touch_css_targets_inputs_safe_area_and_selection_touch_action(self):
        """Touch CSS: 44px controls, 16px inputs, safe areas, and exactly which rules set touch-action (PDF, grips, panel, sheet bar)."""
        css = HTML[HTML.index("<style>") : HTML.index("</style>")]
        coarse = css[css.index("@media (pointer:coarse){") :]
        coarse = coarse[: coarse.index("\n}")]
        self.assertIn("min-height:44px", coarse)
        # prevents iOS zoom-in — 16px or larger
        self.assertIn("input,textarea,select{font-size:var(--text-xl)}", coarse)
        self.assertIn("--text-xl:16px", css)
        self.assertIn("env(safe-area-inset-bottom)", css)
        self.assertIn("var(--kb,0px)", css)
        # touch-action: the PDF areas allow only scroll and block browser pinch (two fingers do
        # app-level zoom, §PDF 영역 전용 확대). A page in selection mode is none (one-finger drag = select).
        # The width/height grips are none so they don't fight scroll while dragging. The panel is pan-y pinch-zoom
        # (a horizontal drag stays a pointer stream for the overlay's swipe; pinch keeps the browser's zoom), and
        # the narrow sheet's tool bar is none - the whole bar drags the sheet (input review 2026-09-26).
        css_nc = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        self.assertEqual(
            [x.strip() for x in re.findall(r"([^{}]*)\{[^{}]*touch-action", css_nc)],
            [
                "#left",
                "#outline-grip",
                "#revision-pdf",
                "#grip",
                "#right",
                "body.selmode .pg",
                "body.lay-narrow #sheet-grip",
                "body.lay-narrow #bar1",
            ],
        )
        self.assertRegex(css_nc, r"\n#right\{[^}]*touch-action:pan-y pinch-zoom\}")
        self.assertRegex(css_nc, r"\n#left\{[^}]*touch-action:pan-x pan-y\}")
        self.assertIn("body.selmode .pg{touch-action:none", css)
        self.assertNotIn("touch-action:pinch-zoom", css)
        # toasts move to a spot that doesn't overlap the sheet/panel toolbar row
        self.assertIn("body.lay-narrow #toasts{", css)
        self.assertIn("body.lay-mid #toasts{", css)

    def test_selection_uses_pointer_events_one_path(self):
        self.assertIn("$('#doc').addEventListener('pointerdown'", HTML)
        for ev in ("pointermove", "pointerup", "pointercancel"):
            self.assertIn("window.addEventListener('%s'" % ev, HTML)
        self.assertIn("if(mouse||SELMODE)", HTML)  # mouse still drags like before, regardless of mode
        self.assertIn("if(!e.isPrimary){cancelDrag()", HTML)  # a second finger (pinch) drops the selection
        self.assertNotIn("window.addEventListener('mouseup',e=>{if(!DRAG)", HTML)  # no old mouse-only path remains
        self.assertIn("function quickPick(", HTML)
        self.assertIn("LONGPRESS_MS", HTML)

    def test_touch_does_not_autofocus_note_or_pop_hover_tips(self):
        m = re.search(r"async function pick\(r\)\{(.*?)\n\}", HTML, re.S)
        self.assertIn("if(LAST_PTR==='mouse')$('#note').focus(", m.group(1))
        self.assertIn(
            "if(touchRecent()||MQ_NOHOVER.matches)return; const t=/** @type {HTMLElement} */(e.target); armTip(", HTML
        )
        # devices without hover don't show the focus tooltip either (QA phone: the tooltip stayed stuck over the list after a tap). The card as a whole gets no tooltip.
        self.assertIn("||touchRecent()||MQ_NOHOVER.matches){if(Date.now()>=SWALLOW_CLICK)hideTip();return;}", HTML)
        self.assertNotIn("data-doc=\"'+esc(pdoc(p))+'\" data-tip=\"'+tip+'\"", extract_js_fn("card"))
        self.assertIn("document.addEventListener('contextmenu'", HTML)

    def test_keyboard_and_resize_hooks(self):
        self.assertIn("vv.addEventListener('resize',onViewport)", HTML)
        self.assertIn("new ResizeObserver(", HTML)
        m = re.search(r"\nfunction relayout\(\)\{(.*?)\}\n", HTML, re.S)
        self.assertIn("topAnchor()", m.group(1))
        self.assertIn("restoreAnchor(a)", m.group(1))

    def test_page_images_lazy(self):
        self.assertIn('<img loading="lazy"', HTML)


# Vector rendering (docs/handbook/viewer.md §벡터 렌더링) — checks the deployed HTML for the PDF.js path, fallback, visible-area rendering, and the pixel cap.
class FrontendVector(unittest.TestCase):
    """Check the PDF.js loading, cache, render, and PNG fallback paths exposed by the viewer."""

    def fn(self, name):
        m = re.search(r"\n(?:async )?function %s\([^)]*\)\{(.*?)\n\}" % name, HTML, re.S)
        self.assertIsNotNone(m, name)
        return m.group(1)

    def test_loads_vendored_pdfjs_same_origin_with_version(self):
        self.assertNotIn("__PDFJS_VERSION__", HTML)
        self.assertIn("const PDFJS_V='%s'" % viewer_assemble.PDFJS_VERSION, HTML)
        self.assertIn("import('/vendor/pdfjs/pdf.min.mjs?v='+PDFJS_V)", HTML)
        self.assertIn("workerSrc='/vendor/pdfjs/pdf.worker.min.mjs?v='+PDFJS_V", HTML)
        for cdn in ("cdn.jsdelivr", "unpkg.com", "cdnjs", "mozilla.github.io/pdf.js/build"):
            self.assertNotIn(cdn, HTML)  # runs only inside the tailnet — no external CDN
        self.assertIn("isEvalSupported:false", HTML)
        self.assertIn("useWasm:false", HTML)  # wasm isn't in vendor (vendor/pdfjs/README.md)

    def test_pdf_is_the_screen_build(self):
        body = self.fn("vecOpen")
        self.assertIn("'/pdf?build='+encodeURIComponent(build)", body)
        self.assertIn("build=META.pages_build", body)
        self.assertIn("doc.numPages!==n", body)  # not used if the page count differs
        # close the old document after a rebuild. PDFDocumentProxy has no destroy (observed: 'old.destroy is not a function').
        self.assertIn("vecClose(old)", body)
        self.assertIn("doc.loadingTask.destroy()", self.fn("vecClose"))
        self.assertNotRegex(HTML, r"\b(doc|old|VEC\.doc)\.destroy\(")

    def test_stale_doc_detached_before_awaiting_new_pdf(self):
        # on a cache miss from a different document/rebuild, VEC.doc is left empty until the fetch
        # finishes — so a vecRun queued in the meantime by IntersectionObserver can't touch the old
        # PDFDocumentProxy with a now-wrong page number (cross-document contamination, or getting stuck
        # on PNG via 'Invalid page request').
        body = self.fn("vecOpen")
        i_if = body.index("if(!doc){")
        i_null = body.index("VEC.doc=null")
        i_fetch = body.index("await fetch(")
        self.assertLess(i_if, i_null)
        self.assertLess(i_null, i_fetch)
        self.assertIn("if(prev&&!vecCached(prev))vecClose(prev)", body)
        # old might already be null (cleared above) — vecClose(null) must not be called without a null guard
        self.assertIn("if(old&&old!==doc&&!vecCached(old))vecClose(old)", body)

    def test_fallback_to_png_on_any_failure(self):
        boot = self.fn("vecBoot")
        self.assertIn("catch(e){VEC.lib=null; vecFail(", boot)
        self.assertIn("vecFail('PDF 를 벡터로 열지 못했습니다'", self.fn("vecOpen"))
        run = self.fn("vecRun")
        self.assertIn("RenderingCancelledException", run)  # a cancellation is not a failure
        self.assertIn("vecFail('쪽을 그리지 못했습니다'", run)
        fail = self.fn("vecFail")
        self.assertIn("vecReleaseAll()", fail)  # removing the canvas reveals the PNG underneath
        self.assertIn("$('#vec-chip')", fail)
        self.assertIn('id="vec-chip" class="badge badge-warning" hidden', HTML)
        self.assertIn('<img loading="lazy"', HTML)  # PNG remains as the first paint / fallback
        css = HTML[HTML.index("<style>") : HTML.index("</style>")]
        self.assertIn(".pg.drawn>img{visibility:hidden}", css)
        self.assertIn(".pg>canvas{position:absolute;display:block;pointer-events:none}", css)  # .pg receives the drag

    def test_visible_pages_only_and_release(self):
        obs = self.fn("vecObserve")
        self.assertIn("new IntersectionObserver(", obs)
        self.assertIn("root:$('#left'),rootMargin:VEC_KEEP", obs)
        self.assertIn("vecRelease(n)", obs)
        self.assertIn("cv.width=0; cv.height=0", self.fn("vecDrop"))
        self.assertIn("vecObserve()", self.fn("buildDoc"))
        ref = self.fn("refreshDoc")
        self.assertIn("vecReleaseAll()", ref)  # canvases drawn from the old PDF are removed
        self.assertIn("vecOpen()", ref)  # reopen the PDF from the new build
        self.assertIn("vecInvalidate()", self.fn("setW"))  # redraw when the zoom changes

    def test_no_text_layer(self):
        for s in ("getTextContent", "TextLayer", "textLayer"):
            self.assertNotIn(s, HTML)


class FrontendVectorLogic(unittest.TestCase):
    """Exercise vector canvas sizing, stale PDF loading, and detail region calculations."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_backing_size_is_css_times_k_until_the_pixel_cap(self):
        js = "\n".join(
            [
                extract_js_fn("vecTarget"),
                "const cap=16777216; const out=[];",
                "for(const [cw,ch,k] of [[898,1270,2],[370,523,2.6],[1796,2540,2],[3592,5080,2],[4490,6350,2]]){",
                "  const t=vecTarget(cw,ch,k,cap); out.push([t.bw,t.bh,t.capped,t.bw*t.bh<=cap,+(t.bw/(cw*k)).toFixed(3)]);}",
                "console.log(JSON.stringify(out));",
            ]
        )
        out = json.loads(run_node(js))
        self.assertEqual(out[0][:3], [1796, 2540, False])
        self.assertEqual(out[1][:3], [962, 1360, False])
        for row in out[:2]:
            self.assertGreaterEqual(row[4], 1.0)  # within the cap, it's at least CSS x DPR
        for row in out[2:]:  # 1796x2540 CSS x DPR 2 = 18.2M pixels > 16.8M
            self.assertTrue(row[2])  # scaled down past the cap (the detail canvas fills the visible area)
            self.assertTrue(row[3])

    def test_vecopen_stale_doc_not_touched_while_new_pdf_is_fetching(self):
        # reproducing the observed case: if vecOpen is called for a new 27-page document while VEC.doc
        # still points at the old document (1 page), VEC.doc must be null before the fetch finishes
        # (so vecNextJob can't pull any work), and a vecRun queued in the meantime must not call the old
        # doc.getPage (it throws here if it does).
        js = "\n".join(
            [
                "const VEC_CACHE_MAX=3;",
                extract_js_fn("vecCacheKey"),
                extract_js_fn("vecCachePut"),
                extract_js_fn("vecCached"),
                extract_js_fn("vecForget"),
                extract_js_fn("vecClose"),
                extract_js_fn("vecCancel"),
                extract_js_fn("vecNextJob"),
                extract_js_fn("vecOpen"),
                r"""
            function $(sel){return {hidden:false};}
            function dq(u){return u;}
            function vecSchedule(){}
            function loadOutline(){}
            function vecFail(msg){throw new Error('vecFail: '+msg);}
            global.document={getElementById:(id)=>({})};

            let oldClosed=false;
            const oldDoc={numPages:1, loadingTask:{destroy(){oldClosed=true;}},
              getPage(){throw new Error('옛(다른 문서/옛 빌드) doc.getPage 가 불렸다');}};
            const VEC={lib:null, doc:oldDoc, build:'old', gen:0, failed:null, tDoc:0,
              st:new Map(), cur:null, cache:new Map(), near:new Set([2])};
            const DOC='doc1';
            const META={pages_build:'new', pages:new Array(27).fill(0), built_at:'v2'};

            let resolveFetch, resolveGetDoc;
            global.fetch=function(){return new Promise(res=>{resolveFetch=res;});};
            VEC.lib={getDocument(){return {promise:new Promise(res=>{resolveGetDoc=res;})};}};

            const p=vecOpen();
            const results={};
            results.docNulledBeforeFetch=(VEC.doc===null);
            results.oldClosedImmediately=oldClosed;
            results.noJobWhileDocNull=(vecNextJob()===null);

            resolveFetch({ok:true, arrayBuffer:()=>Promise.resolve(new ArrayBuffer(8))});
            setTimeout(()=>{
              resolveGetDoc({numPages:27, loadingTask:{destroy(){}}});
              p.then(()=>{
                results.newDocInstalled=(VEC.doc&&VEC.doc.numPages===27);
                console.log(JSON.stringify(results));
              }).catch(e=>{results.error=String(e); console.log(JSON.stringify(results));});
            },10);
            """,
            ]
        )
        out = json.loads(run_node(js))
        self.assertNotIn("error", out, out)
        self.assertTrue(out["docNulledBeforeFetch"])
        self.assertTrue(out["oldClosedImmediately"])
        self.assertTrue(out["noJobWhileDocNull"])
        self.assertTrue(out["newDocInstalled"])

    def test_detail_region_cover_check(self):
        js = "\n".join(
            [
                extract_js_fn("vecCovers"),
                "const reg={x:0.1,y:0.2,w:0.5,h:0.3}; const out=[];",
                "out.push(vecCovers(reg,{x:100,y:200,w:500,h:300,cw:1000,ch:1000}));",
                "out.push(vecCovers(reg,{x:150,y:250,w:100,h:100,cw:1000,ch:1000}));",
                "out.push(vecCovers(reg,{x:50,y:250,w:100,h:100,cw:1000,ch:1000}));",
                "out.push(vecCovers(reg,{x:150,y:250,w:100,h:300,cw:1000,ch:1000}));",
                "out.push(vecCovers(null,{x:0,y:0,w:1,h:1,cw:10,ch:10}));",
                "console.log(JSON.stringify(out));",
            ]
        )
        self.assertEqual(json.loads(run_node(js)), [True, True, False, False, False])


# PDF-area-only zoom (docs/handbook/viewer.md §PDF 영역 전용 확대) — whether browser zoom input is intercepted to change only the page width.
class FrontendZoom(unittest.TestCase):
    """Guard the inputs, bounds, and anchors used by PDF area zoom controls."""

    def test_ctrl_wheel_on_pdf_area_is_intercepted_non_passive(self):
        self.assertIn("L.addEventListener('wheel',e=>{if(!(e.ctrlKey||e.metaKey))return; e.preventDefault();", HTML)
        i = HTML.index("L.addEventListener('wheel'")
        self.assertIn("{passive:false}", HTML[i : i + 300])
        self.assertIn("const L=$('#left')", HTML[i - 500 : i])  # PDF area only — sidebar wheel scrolling is left alone
        self.assertIn("zoomTo(W*f,pt[0],pt[1])", HTML)  # anchored to the pointer

    def test_safari_gesture_and_touch_pinch(self):
        for ev in ("gesturestart", "gesturechange", "gestureend", "touchstart", "touchmove", "touchend", "touchcancel"):
            self.assertIn("L.addEventListener('%s'" % ev, HTML)
        i = HTML.index("L.addEventListener('touchstart'")
        blk = HTML[i : i + 400]
        self.assertIn("e.touches.length!==2", blk)
        self.assertIn("cancelDrag(); cancelLP();", blk)  # a pinch discards the in-progress selection/long-press
        self.assertIn("{passive:false}", blk)

    def test_keyboard_zoom_skips_inputs(self):
        """Only modifier shortcuts outside fields reach the visible PDF's controller."""
        m = re.search(r"document\.addEventListener\('keydown',e=>\{(.*?)\n\}\);", HTML, re.S)
        body = m.group(1)
        self.assertIn("if((e.ctrlKey||e.metaKey)&&!e.altKey&&!inField){const z=zoomKey(e);", body)
        self.assertIn("e.preventDefault();zoomVisiblePdf(z)", body)
        self.assertLess(body.index("inField="), body.index("zoomKey(e)"))

    def test_zoom_bounds_and_anchor(self):
        self.assertIn("const ZOOM_MIN=0.5,ZOOM_MAX=5", HTML)
        setw = re.search(r"\nfunction setW\(w,save\)\{(.*?)\}\n", HTML, re.S).group(1)
        self.assertIn("wBounds(fitWidth())", setw)
        self.assertNotIn("2200", setw)
        zt = re.search(r"\nfunction zoomTo\(w,cx,cy\)\{(.*?)\}\n", HTML, re.S).group(1)
        self.assertLess(zt.index("zoomAnchor(cx,cy)"), zt.index("setW(w)"))
        self.assertLess(zt.index("setW(w)"), zt.index("zoomRestore(a)"))


class FrontendZoomLogic(unittest.TestCase):
    """Exercise zoom key mappings and mouse or trackpad width calculations."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_zoom_key_map(self):
        js = "\n".join(
            [
                extract_js_fn("zoomKey"),
                "const ks=[['=','Equal'],['+','Equal'],['-','Minus'],['_','Minus'],['0','Digit0'],['+','NumpadAdd'],",
                " ['Process','Equal'],['Process','Minus'],['Process','Digit0'],['1','Digit1'],['Enter','Enter'],['a','KeyA']];",
                "console.log(JSON.stringify(ks.map(([key,code])=>zoomKey({key,code}))));",
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)), ["in", "in", "out", "out", "fit", "in", "in", "out", "fit", None, None, None]
        )

    def test_wheel_factor_mouse_notch_vs_trackpad_pinch(self):
        js = "\n".join(
            [
                "const ZOOM_STEP=1.2;",
                extract_js_fn("wheelFactor"),
                "console.log(JSON.stringify([wheelFactor(-100,0),wheelFactor(100,0),wheelFactor(-3,1),wheelFactor(0,0),",
                " wheelFactor(-10,0),wheelFactor(10,0),wheelFactor(-49,0)].map(v=>+v.toFixed(4))));",
            ]
        )
        out = json.loads(run_node(js))
        self.assertEqual(out[:4], [1.2, 0.8333, 1.2, 1])
        self.assertAlmostEqual(out[4], 1.1052, places=3)  # pinch dy=-10 -> zoom in slightly
        self.assertAlmostEqual(out[4] * out[5], 1.0, places=3)  # spreading then pinching returns to the same spot
        self.assertLess(out[6], 1.2)  # dy split into small increments never exceeds one step per event

    def test_width_bounds_are_half_to_five_times_fit(self):
        js = "\n".join(
            [
                "const ZOOM_MIN=0.5,ZOOM_MAX=5;",
                extract_js_fn("wBounds"),
                "console.log(JSON.stringify([wBounds(956),wBounds(370),wBounds(100)]));",
            ]
        )
        self.assertEqual(json.loads(run_node(js)), [[478, 4780], [185, 1850], [160, 800]])


class FrontendMobileLogic(unittest.TestCase):
    """Exercise responsive layout decisions and compact selection or keyboard calculations."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    # layoutFor(w, h, coarse) rows: (w, h, coarse, band). A mouse looks at the width only, so its rows hold at any height;
    # touch rows put both sides of every width, height and orientation boundary (docs/handbook/viewer.md §모바일 레이아웃).
    MOUSE_BANDS = [
        (412, 900, "phone"),
        (700, 900, "phone"),
        (701, 900, "mid-overlay"),
        (880, 900, "mid-overlay"),
        (900, 900, "mid-overlay"),
        (820, 390, "mid-overlay"),
        (901, 900, "mid-side"),
        (1099, 900, "mid-side"),
        (1100, 820, "wide"),
        (1180, 820, "wide"),
        (1366, 1024, "wide"),
        (1440, 900, "wide"),
    ]
    TOUCH_BANDS = [
        # width boundaries
        (599, 900, "phone"),
        (600, 900, "tablet-sheet"),
        (700, 900, "tablet-sheet"),
        (839, 700, "tablet-sheet"),
        (840, 700, "mid-overlay"),
        (900, 700, "mid-overlay"),
        (901, 700, "mid-side"),
        (1099, 900, "mid-side"),
        (1100, 900, "mid-side"),
        (1366, 1024, "mid-side"),
        (1367, 1024, "wide"),
        # height boundaries
        (844, 479, "short"),
        (844, 480, "mid-overlay"),
        (599, 300, "phone"),
        (600, 479, "short"),
        (1200, 479, "short"),
        # orientation (a square window is landscape)
        (860, 1000, "tablet-sheet"),
        (860, 860, "mid-overlay"),
        (860, 861, "tablet-sheet"),
        (800, 600, "tablet-sheet"),
        (1024, 1366, "mid-side"),
        # the diagnosis' viewports
        (360, 780, "phone"),
        (390, 844, "phone"),
        (430, 932, "phone"),
        (344, 882, "phone"),
        (844, 390, "short"),
        (932, 430, "short"),
        (640, 360, "short"),
        (842, 758, "mid-overlay"),
        (600, 900, "tablet-sheet"),
        (768, 1024, "tablet-sheet"),
        (820, 1180, "tablet-sheet"),
        (834, 1194, "tablet-sheet"),
        (1024, 768, "mid-side"),
        (1180, 820, "mid-side"),
        (1366, 1024, "mid-side"),
        (1440, 900, "wide"),
    ]

    def layout_bands(self, cases):
        """[(w, h, coarse)] -> [layoutFor(w, h, coarse)] from the served source."""
        js = extract_js_fn("layoutFor") + "\nconsole.log(JSON.stringify(%s.map(c=>layoutFor(c[0],c[1],c[2]))));" % (
            json.dumps(cases)
        )
        return json.loads(run_node(js))

    def test_layout_for_bands(self):
        """layoutFor(w, h, coarse) is the band table: a mouse gets the width-only bands at any height (300, the row's own
        and 2000), touch also reads the height and the orientation. Each row sits on one side of a boundary."""
        mouse = [(w, hh, False, b) for w, h, b in self.MOUSE_BANDS for hh in (h, 300, 2000)]
        touch = [(w, h, True, b) for w, h, b in self.TOUCH_BANDS]
        rows = mouse + touch
        got = self.layout_bands([r[:3] for r in rows])
        self.assertEqual([r[:3] + (g,) for r, g in zip(rows, got, strict=True)], rows)

    def test_band_settle_rules(self):
        """settleBand(C, N, typing): what a new window observation N does to the settled input C on touch - settle at once
        (no C yet, or a mouse), keep the band while a text field has focus or for a height change under 96px from C (C stays,
        so two 56px steps add up), and otherwise wait 200ms (a rotation, an unfolding, a pointer change)."""
        t = lambda w, h: {"w": w, "h": h, "coarse": True}  # noqa: E731
        m = lambda w, h: {"w": w, "h": h, "coarse": False}  # noqa: E731
        cases = [
            (None, t(768, 1024), False, "settle"),
            (t(768, 1024), t(768, 644), True, "keep"),  # the keyboard, while the note has focus
            (t(768, 1024), t(1024, 768), True, "keep"),  # a rotation, while the note has focus
            (t(844, 390), t(844, 446), False, "keep"),  # the address bar hides
            (t(844, 446), t(844, 390), False, "keep"),  # and comes back
            (t(1024, 768), t(1024, 712), False, "keep"),  # one 56px step
            (t(1024, 768), t(1024, 656), False, "wait"),  # the second, against the same C: 112px
            (t(1024, 768), t(1024, 673), False, "keep"),  # 95px
            (t(1024, 768), t(1024, 672), False, "wait"),  # 96px
            (t(768, 1024), t(1024, 768), False, "wait"),  # a rotation
            (t(344, 882), t(842, 758), False, "wait"),  # an unfolding
            (t(1180, 820), m(1180, 820), False, "wait"),  # the primary pointer turns fine
            (m(1180, 820), t(1180, 820), False, "wait"),  # and back
            (m(1000, 800), m(1200, 800), False, "settle"),  # a mouse window, at once
            (m(1000, 800), m(1000, 300), True, "settle"),  # even with a text field focused
        ]
        consts = re.search(r"^const BAND_HOLD_PX=.*;$", HTML, re.M).group(0)  # the served thresholds, not a copy
        js = (
            consts
            + extract_js_fn("settleBand")
            + "\nconsole.log(JSON.stringify(%s.map(c=>settleBand(c[0],c[1],c[2]))));"
            % (json.dumps([c[:3] for c in cases]))
        )
        got = json.loads(run_node(js))
        self.assertEqual([c[:3] + (g,) for c, g in zip(cases, got, strict=True)], cases)

    def test_a_mouse_window_keeps_the_width_only_layout_modes(self):
        """The mouse rows of the old width-only test give the same layout mode through BAND_MODE: 412 narrow, 880 mid,
        1440 wide."""
        consts = re.search(r"^const BAND_MODE=.*;$", HTML, re.M).group(0)
        js = "\n".join(
            [
                extract_js_fn("layoutFor"),
                helpers_js.closed_set_prelude(VIEWER_CLOSED_SETS, consts) + consts,
                "console.log(JSON.stringify([[412,900],[880,900],[1440,900]].map(c=>BAND_MODE[layoutFor(c[0],c[1],false)])));",
            ]
        )
        self.assertEqual(json.loads(run_node(js)), ["narrow", "mid", "wide"])

    def test_quick_pick_box_is_a_line_on_a_manuscript_and_a_point_on_a_figure(self):
        """A quick selection sends about one text line around the point on a manuscript page (+-7 % x +-0.6 %), and a
        point on a figure document: +-0.4 % of the page width by +-0.4 % of its height, a rectangle on a page that is
        not square (here 400 x 600); both are clamped to the page at every corner. The half-widths are the page's own
        (selection.js), not numbers this test repeats."""
        consts = re.search(r"^const c01=.*;$", HTML, re.M).group(0) + re.search(
            r"^const LONGPRESS_MS=.*;$", HTML, re.M
        ).group(0)
        js = "\n".join(
            [
                consts,
                r"""
            const out=[]; let META=null;
            const pg={getBoundingClientRect:()=>({left:100,top:50,width:400,height:600})};
            function newBox(){return {};} function finishRect(pg,box,x0,y0,x1,y1){out.push([x0,y0,x1,y1].map(v=>+v.toFixed(4)));}
            """,
                extract_js_fn("fracAt"),
                extract_js_fn("isFigureKind"),
                extract_js_fn("quickBox"),
                extract_js_fn("quickPick"),
                "quickPick(pg,300,350); quickPick(pg,90,40); quickPick(pg,510,660);"
                " META={kind:'figure'}; quickPick(pg,300,350); quickPick(pg,90,40); quickPick(pg,510,660);"
                " console.log(JSON.stringify([out,[QUICK_W,QUICK_H,QUICK_FIG]]));",
            ]
        )
        out, (quick_w, quick_h, quick_fig) = json.loads(run_node(js))
        self.assertEqual((quick_w, quick_h, quick_fig), (0.07, 0.006, 0.004))
        self.assertEqual(
            out,
            [
                [0.43, 0.494, 0.57, 0.506],
                [0, 0, 0.07, 0.006],
                [0.93, 0.994, 1, 1],
                [0.496, 0.496, 0.504, 0.504],
                [0, 0, 0.004, 0.004],
                [0.996, 0.996, 1, 1],
            ],
        )

    def test_keyboard_inset_ignores_pinch_zoom_and_desktop(self):
        # only the keyboard (visualViewport shrinking) is counted as --kb. Pinch-zoom (scale>1), small differences, and mouse devices all give 0.
        js = "\n".join(
            [
                r"""
            const props={}; let active=null;
            const document={documentElement:{clientHeight:915,style:{setProperty:(k,v)=>{props[k]=v;},getPropertyValue:k=>props[k]||''}},
                            get activeElement(){return active;}};
            const MQ_COARSE={matches:true}; const window={visualViewport:null};
            const $=()=>({contains:()=>false}); function requestAnimationFrame(f){f();}
            """,
                extract_js_fn("onViewport"),
                r"""
            const out=[];
            for(const [h,s,coarse] of [[400,1,true],[457.5,2,true],[875,1,true],[400,1,false],[915,1,true]]){
              window.visualViewport={height:h,scale:s}; MQ_COARSE.matches=coarse; onViewport(); out.push([props['--kb'],props['--vvh']]);}
            console.log(JSON.stringify(out));
            """,
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)),
            [["515px", "400px"], ["0px", "915px"], ["0px", "915px"], ["0px", "915px"], ["0px", "915px"]],
        )

    def test_card_accordion_summary_is_first_note_line(self):
        js = "\n".join(
            [
                js_esc(),
                r"""
            const T={stale:'s',n:'n',loc:'l',view:'v',edit:'e',close:'c',drop:'d'}; const EDITOR={current:null,saving:false}; let  PINS=[];
            const OPEN_CARDS=new Set([2]);
            function viaTag(){return null;} function relBadge(){return null;} function claimActive(){return false;}
            function claimLabel(){return '';} function authorTip(){return 'tip';} function who(a){return a?a.name:'';}
            function avatar(){return '';}
            let SHOW_ALL=false, DOCS=[], DOC='main', DEFAULT_DOC='main'; function docInfo(){return null;}
            let LAYOUT='mid', REPLY=null, META=null; const THREAD_OPEN=new Set();
            """,
                extract_js_fn("rng"),
                extract_js_fn("multiDoc"),
                extract_js_fn("pdoc"),
                extract_js_fn("isRegion"),
                extract_js_fn("locText"),
                extract_js_fn("locCopy"),
                extract_js_fn("docChip"),
                js_thread(),
                extract_js_fn("isFrac"),
                extract_js_fn("hasMark"),
                extract_js_fn("pinPlace"),
                extract_js_fn("elLost"),
                extract_js_fn("elLostTag"),
                extract_js_fn("figRegionBadge"),
                extract_js_fn("card"),
                extract_js_fn("cardActs"),  # the open card's action row (its visual order per layout)
                js_icons(),
                r"""
            const a=String(card({id:1,file:'/m.tex',name:'m.tex',lo:3,hi:5,page:2,note:'첫 줄 <b>\n둘째 줄'}));
            const b=String(card({id:2,file:'/m.tex',name:'m.tex',lo:3,hi:5,page:2,note:''}));
            const sum=s=>(/<div class="sum" translate="no" data-act="card-toggle">((?:[^<]|<span class="dim">|<\/span>)*)<\/div>/.exec(s)||[])[1];
            console.log(JSON.stringify([sum(a), / open"/.test(a), sum(b), / open"/.test(b), /class="tags"/.test(a),
              /data-act="card-toggle" aria-expanded="false"/.test(a), /aria-expanded="true"/.test(b)]));
            """,
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)),
            ["첫 줄 &lt;b&gt;", False, '<span class="dim">(메모 없음)</span>', True, True, True, True],
        )


# Panel tidy-up / width adjustment (docs/handbook/viewer.md §패널 정리). Measured live with Playwright
# (expanded 880x790, collapsed 412x915, desktop 1440x900); here we check pure logic like bounds/steps/
# labels under node, and layout/wiring via the HTML string.
class FrontendPanelWidthLogic(unittest.TestCase):
    """Exercise panel bounds and the location labels shown beside range controls."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_side_bounds_per_layout(self):
        js = "\n".join(
            [
                extract_js_fn("sideBounds"),
                r"""
            console.log(JSON.stringify([sideBounds('mid',880),sideBounds('mid',760),sideBounds('mid',701),
                                        sideBounds('wide',1440),sideBounds('wide',1100),sideBounds('wide',700)]));""",
            ]
        )
        got = json.loads(run_node(js))
        # 900px and below is an overlay; above that, 480px of body + an 8px grip are left over.
        self.assertEqual(got[0], {"min": 300, "max": 440, "def": 330, "presets": [300, 330, 440]})
        self.assertEqual(got[1]["max"], 440)
        self.assertEqual(got[2], {"min": 300, "max": 440, "def": 330, "presets": [300, 330, 351]})
        # desktop: default 348, min 280, max leaves 480px of body + the grip
        self.assertEqual(got[3], {"min": 280, "max": 954, "def": 348, "presets": [300, 348, 605]})
        self.assertEqual(got[4]["max"], 614)
        self.assertEqual(got[5], {"min": 280, "max": 280, "def": 280, "presets": [280, 280, 280]})
        for b in got:
            self.assertTrue(all(b["min"] <= w <= b["max"] for w in b["presets"] + [b["def"]]), b)

    def test_clamp_and_preset_cycle(self):
        js = "\n".join(
            [
                extract_js_fn("clampSide"),
                extract_js_fn("nextPreset"),
                extract_js_fn("presetIndex"),
                r"""
            const b={min:300,max:528},P=[300,334,440];
            console.log(JSON.stringify([[100,300.4,420,999].map(w=>clampSide(w,b)),
              [300,334,420,440,500,302].map(w=>nextPreset(P,w)), [300,331,338,420,440].map(w=>presetIndex(P,w))]));""",
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)), [[300, 300, 420, 528], [334, 440, 440, 300, 300, 334], [0, 1, 1, -1, 2]]
        )

    def test_level_name_is_short_and_disambiguates_nested_same_env(self):
        js = "\n".join(
            [
                extract_js_fn("levelName"),
                extract_js_fn("levelLabel"),
                extract_js_fn("rng"),
                r"""
            const A=[{level:'para',label:'문단'},{level:'env',label:'환경 abstract',env:'abstract'},
                     {level:'env2',label:'환경 frontmatter (바깥)',env:'frontmatter'}];
            const B=[{level:'env',label:'환경 itemize',env:'itemize'},{level:'env2',label:'환경 itemize (바깥)',env:'itemize'}];
            console.log(JSON.stringify([A.map(l=>levelName(l,A)),B.map(l=>levelName(l,B)),rng(159,159),rng(155,173)]));""",
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)),
            [["문단", "abstract", "frontmatter"], ["itemize", "itemize (바깥)"], "L159", "L155-L173"],
        )

    def test_via_tag_hides_confident_matches_and_flags_uncertain(self):
        # 90% and above hides the badge; below that shows '위치 불확실' (below 30% gets the warning color). Method/match rate/next step go in the tooltip.
        js = "\n".join(
            [
                "const T={synctex:'S',text:'X'};",
                extract_js_fn("viaTag"),
                r"""
            const V="const VIA_HIDE=90,VIA_WARN=30;";
            console.log(JSON.stringify([viaTag({via:'synctex',score:0.934}),viaTag({via:'synctex',score:0.884}),
              viaTag({via:'text',score:0.2}),viaTag({via:'synctex',score:1}),viaTag({})]));""",
            ]
        )
        js = js.replace("function viaTag(", "const VIA_HIDE=90,VIA_WARN=30;\nfunction viaTag(", 1)
        got = json.loads(run_node(js))
        self.assertIsNone(got[0])
        self.assertEqual(got[1], {"t": "위치 불확실", "tip": "좌표로 찾음 · 일치 88% — S", "low": False})
        self.assertEqual(
            got[2], {"t": "위치 불확실", "tip": "글자로 찾음 · 일치 20% — X 많이 어긋났을 수 있습니다.", "low": True}
        )
        self.assertIsNone(got[3])
        self.assertIsNone(got[4])
        self.assertIn("const VIA_HIDE=90,VIA_WARN=30;", HTML)


class FrontendPanelTidyStructure(unittest.TestCase):
    """Guard panel grips, width persistence, composer placement, and sheet controls."""

    def test_grip_is_one_pointer_events_separator(self):
        tag = re.search(r'<div id="grip"[^>]*>', HTML).group(0)
        for part in ('role="separator"', 'aria-orientation="vertical"', 'tabindex="0"', 'aria-controls="right"'):
            self.assertIn(part, tag)
        self.assertIn("(function(){const g=$('#grip');\n  let D=/** @type {", HTML)  # the handle's own drag state
        self.assertIn("g.setPointerCapture(e.pointerId)", HTML)
        self.assertNotIn("$('#grip').addEventListener('mousedown'", HTML)  # no old mouse-only path remains
        self.assertNotIn("body.compact #grip{display:none}", HTML)  # still visible in mid too
        self.assertIn("body.lay-narrow #grip,body.lay-mid:not(.side-open) #grip{display:none}", HTML)

    def test_width_is_remembered_per_layout_and_relayout_keeps_anchor(self):
        self.assertIn("function sideKey(){return LAYOUT===LAYOUT_MODE.MID?'sideMid':'side';}", HTML)
        m = re.search(r"\nfunction setSideWidth\(w\)\{(.*?)\}\n", HTML, re.S)
        self.assertIsNotNone(m)
        self.assertIn("savePrefs({[sideKey()]:w})", m.group(1))
        self.assertIn("relayout()", m.group(1))
        m = re.search(r"\nfunction relayout\(\)\{(.*?)\}\n", HTML, re.S)
        body = m.group(1)
        # the panel width must be settled first for the page width to match
        self.assertLess(body.index("applySideWidth()"), body.index("autoW()"))
        # ResizeObserver doesn't re-fit every frame while dragging
        self.assertIn("!document.body.classList.contains('resizing'))scheduleRelayout()", HTML)
        self.assertIn("body.lay-mid.side-open #right{width:var(--side-w,", HTML)

    def test_sheet_grip_and_size_presets_in_more(self):
        tag = re.search(r'<div id="sheet-grip"[^>]*>', HTML).group(0)
        self.assertIn('role="separator"', tag)
        self.assertIn('aria-orientation="horizontal"', tag)
        # the grip is an item of the tool bar's row (input diagnosis P3: its own 24px row took the buttons' top 8px), so it stays
        # with the tool bar on a collapsed sheet - its middle column, between the two cells (UX spec §V4)
        bar = HTML[HTML.index('<div class="bar" id="bar1"') : HTML.index('<div class="bar" id="bar2"')]
        self.assertRegex(
            bar,
            r'^<div class="bar" id="bar1"[^>]*>\s*<div class="bar-l">.*?</div>\s*<div id="sheet-grip"[^>]*></div>\s*<div class="bar-r">',
        )
        self.assertIn("body.compact:not(.side-open) #right>:not(#bar1):not(#bar2):not(#banner){display:none}", HTML)
        self.assertIn("var(--sheet-f,.64)", HTML)
        more = HTML[HTML.index('<dialog id="more"') : HTML.index('<dialog id="help"')]
        self.assertIn('id="m-size"', more)
        self.assertIn("case 'size-preset':sizePreset(Number(a.dataset.i))", HTML)
        self.assertIn("renderSizeSeg(); placeMore(); showSheet(d)", HTML)

    def test_actions_row_is_fixed_at_panel_bottom_outside_composer(self):
        right = HTML[HTML.index('<div id="right">') : HTML.index('<div id="tip"')]
        comp = right[right.index('<div id="composer"') : right.index('<div id="list">')]
        self.assertNotIn('id="btn-save"', comp)
        acts = right.index('<div id="c-actions">')
        self.assertGreater(acts, right.index('<div id="list">'))
        # cancel comes first, the primary action (save pin) is wide on the right
        self.assertLess(right.index('id="btn-cancel"', acts), right.index('id="btn-save"', acts))
        self.assertRegex(right, r'<button class="btn-default" id="btn-save"')  # primary action = the default variant
        css = HTML[HTML.index("<style>") : HTML.index("</style>")]
        self.assertIn("#composer[hidden]~#c-actions{display:none}", css)
        self.assertIn("grid-template-columns:1fr 2fr", css)
        self.assertIn("body.compact #c-actions{position:sticky;bottom:0", css)
        # the help paragraph is hidden while selecting
        self.assertIn("#composer:not([hidden])~#list #empty{display:none}", css)

    def test_composer_is_one_loc_line_segmented_ladder_and_folded_snippet(self):
        self.assertNotIn('id="c-meta"', HTML)  # location info repeated 3x -> now one line
        self.assertNotIn("드래그한 줄 L'+d.raw_lo", HTML)
        row = HTML[HTML.index('<div class="c-loc-row">') : HTML.index('<div id="c-warn"')]
        for el in ('id="c-loc"', 'id="c-page"', 'id="c-tag"', 'id="c-copy"'):
            self.assertIn(el, row)
        css = HTML[HTML.index("<style>") : HTML.index("</style>")]
        seg = re.search(r"\n\.seg\{([^}]*)\}", css).group(1)
        self.assertIn("flex-wrap:nowrap", seg)
        self.assertIn("overflow-x:auto", seg)
        self.assertNotIn('class="step"', HTML)  # the stepper is gone from every layout (the range is set in the source)
        # 4 lines + 8px top/bottom padding
        self.assertIn("#c-snip:not(.open){max-height:calc(6em + 16px);overflow:hidden}", css)
        m = re.search(r"\nfunction renderComposer\(\)\{(.*?)\n\}", HTML, re.S)
        self.assertIn("pre.scrollHeight>pre.clientHeight", m.group(1))
        # on every layout the note field comes before the range block in the markup (so Tab and the screen agree and the
        # note never hides under the action row)
        comp = HTML[HTML.index('<div id="composer"') : HTML.index('<div id="list">')]
        self.assertLess(comp.index('id="note"'), comp.index('id="c-kind"'))
        self.assertLess(comp.index('id="c-kind"'), comp.index('id="c-range"'))

    def test_card_head_tags_row_and_action_grid(self):
        m = re.search(r"\nfunction card\(p\)\{(.*?)\n\}", HTML, re.S)
        # the open card's action row is built by cardActs() in its visual order per layout (compact: icons first, wide: by name)
        body = m.group(1) + extract_js_fn("cardActs")
        self.assertNotIn('<span class="tags">', body)  # badges are not inside the head row
        # one line after the head (fold button)
        self.assertGreater(body.index('<div class="tags">'), body.index("b-fold"))
        self.assertLess(body.index("b-drop"), body.index("b-close"))  # done (primary) sits at the far right
        css = HTML[HTML.index("<style>") : HTML.index("</style>")]
        self.assertIn(".pin .acts{display:grid;grid-auto-flow:column;grid-auto-columns:1fr", css)
        # done = soft (pale blue, author-specified 09-23), drop = destructive
        self.assertIn('class="btn-sm btn-soft b-close"', body)
        self.assertNotIn("btn-secondary b-close", body)
        self.assertIn(
            "button.btn-soft{background:color-mix(in srgb,var(--primary) 14%,transparent);color:var(--primary)", css
        )
        self.assertIn('class="btn-sm btn-destructive b-drop"', body)

    def test_compact_toolbar_is_one_even_row(self):
        """The phone and tablet-sheet bar is a three-column grid with equal outer columns, the left cell start-aligned and
        the right one end-aligned (UX spec §V4); the mid bar keeps [⋯] a 44px flex item."""
        css = HTML[HTML.index("<style>") : HTML.index("</style>")]
        self.assertIn("body.compact #bar1 .sp{display:none}", css)
        self.assertIn(
            "body.lay-narrow #bar1{display:grid;grid-template-columns:minmax(0,1fr) var(--hit) minmax(0,1fr);", css
        )
        self.assertIn("body.lay-narrow #bar1 .bar-l{grid-column:1}", css)
        self.assertIn("body.lay-narrow #bar1 .bar-r{grid-column:3;justify-content:flex-end}", css)
        self.assertIn(".bar-l,.bar-r{display:contents}", css)
        self.assertIn("body.compact #bar1 #btn-more{flex:0 0 44px", css)

    def test_mid_layout_pins_nav_top_and_action_bar_bottom(self):
        # unfolded fold devices / tablets (mid): the action row doesn't follow the panel — it's pinned
        # full-width at the bottom of the screen, and the nav row is pinned full-width at the top
        # (docs/handbook/viewer.md §펼친 화면 레이아웃). Live browser measurements are in FrontendResponsiveBrowser.
        css = HTML[HTML.index("<style>") : HTML.index("</style>")]
        css_nc = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        self.assertIn("body.lay-mid #bar1{position:fixed;left:0;right:0;top:auto;bottom:var(--kb,0px);", css)
        self.assertIn("body.lay-mid #doc-nav{position:fixed;top:0;left:0;right:0;", css)
        # the body/panel only occupy the space between the two
        self.assertIn("padding-top:var(--mid-top);padding-bottom:var(--mbar-h)}", css)
        # touch: 40px buttons in 4px padding (input diagnosis P4: the row was 61px around 44px buttons); hit areas stay 44px (MidChrome)
        self.assertIn(
            "@media (pointer:coarse){body.lay-mid{--mbar-tb:var(--ctl-touch);--mbar-pad:var(--space-1)}}", css
        )
        # thumb order: [select] at the far left, [pin N] at the far right. DOM is shared with the narrow sheet, so only order changes.
        self.assertIn("body.lay-mid #btn-select{order:1}", css)
        self.assertIn("body.lay-mid #bar1 #btn-side{order:5}", css)
        # the toolbar is a fixed child of #right — giving #right a containing-block-creating property would make the action row move with the panel
        for sel, body in re.findall(r"([^{}]*#right[^{}]*)\{([^{}]*)\}", css_nc):
            if "lay-mid" in sel:
                self.assertIsNone(
                    re.search(
                        r"(?:^|;)(?:transform|translate|filter|opacity|contain|will-change|perspective)\s*:", body
                    ),
                    sel,
                )
        self.assertRegex(css_nc, r"@keyframes mid-panel-in\{from\{right:")  # the opening animation moves only via right
        # the first-run coach mark sits above the action row ([select] above), not over the nav row. Toasts sit right above the action row, panel side (FrontendToasts).
        self.assertIn("body.lay-mid #coach{top:auto;bottom:calc(var(--mbar-h)", css)
        self.assertIn("body.lay-mid #toasts{", css)
        # an overflowing document-link row fades at the edge instead of showing a scrollbar
        self.assertIn(
            "body:is(.lay-mid,.band-tablet-sheet) #doc-links.fade-r{mask-image:", css
        )  # the tablet sheet's nav bar too
        self.assertIn("function docLinksFade(){", HTML)
        self.assertIn("$('#doc-links').addEventListener('scroll',docLinksFade,{passive:true});", HTML)


# ---------------------------------------------------------------- design token guard (docs/handbook/viewer.md §디자인 토큰과 컴포넌트)
# Colors, radii, and font sizes used to vary per rule (54 color literals, 14 radii, 12 font sizes) — now
# collected into a token layer. This blocks any rule from reintroducing a literal going forward. The one
# exception is the allowlist below; if it grows, update design.md's table too.
# The token blocks: the two theme blocks (:root dark, :root[data-theme=light] light - each declares color-scheme) hold
# the theme colours; the scale block (the :root without color-scheme) holds only the theme-independent colours,
# SCALE_COLOURS: the Limn brand colours (--limn-*) and the text on the instance label (--brand-foreground).
TOKEN_SELECTORS = (":root", ":root[data-theme=light]")
SCALE_COLOURS = re.compile(r"--limn-[a-z]+|--brand-foreground")


COLOR_RE = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(|"
    r"\b(?:white|black|red|green|blue|gray|grey|yellow|orange|purple|pink|silver)\b",
    re.I,
)


RADIUS_OK = re.compile(r"^(?:var\(--radius(?:-sm|-lg)?\)|0|50%)$")


INLINE_STYLE_OK = {"background:__ACCENT__"}  # the instance label color — the server fills it in via the --accent value


def css_rules():
    """The (selector, [(property, value)]) list inside <style>. Strips comments and flattens @media rules too."""
    css = HTML[HTML.index("<style>") + len("<style>") : HTML.index("</style>")]
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = []
    for m in re.finditer(r"([^{}]*)\{([^{}]*)\}", css):
        sel = m.group(1).strip()
        decls = []
        for d in m.group(2).split(";"):
            if ":" in d:
                k, v = d.split(":", 1)
                decls.append((k.strip(), v.strip()))
        out.append((sel, decls))
    return out


def misplaced_colours(rules):
    """Every colour literal of rules ((selector, [(property, value)]) as css_rules gives them) that is not where it
    belongs, as "selector { property:value }": a theme colour is a custom property of a theme block (a TOKEN_SELECTORS
    rule that declares color-scheme) other than a SCALE_COLOURS name; a theme-independent colour is a SCALE_COLOURS
    property of the scale block (":root" without color-scheme). Any other colour literal - in a rule, in the scale
    block under another name, a brand colour in a theme block - is misplaced."""
    bad = []
    for sel, decls in rules:
        theme = sel in TOKEN_SELECTORS and any(k == "color-scheme" for k, _ in decls)
        scale = sel == ":root" and not theme
        for k, v in decls:
            if not COLOR_RE.search(v):
                continue
            brand = SCALE_COLOURS.fullmatch(k) is not None
            placed = (theme and k.startswith("--") and not brand) or (scale and brand)
            if not placed:
                bad.append("%s { %s:%s }" % (sel, k, v))
    return bad


class FrontendDesignTokens(unittest.TestCase):
    """Ensure both viewer themes use the documented token scales and no stray design literals."""

    def test_colour_literals_only_in_token_blocks(self):
        """The page's CSS keeps theme colours in the two theme blocks and the brand colours (plus the label's text
        colour) in the scale block - no colour literal anywhere else."""
        self.assertEqual(misplaced_colours(css_rules()), [])

    def test_a_colour_in_the_wrong_block_is_caught(self):
        """The guard tells the blocks apart: a theme colour planted in the scale block, a brand colour in a theme
        block, and a colour in an ordinary rule are each reported; the same tokens in their own blocks are not."""
        dark = (":root", [("color-scheme", "dark"), ("--muted", "#27272a"), ("--mark-tile", "var(--limn-ink)")])
        light = (":root[data-theme=light]", [("color-scheme", "light"), ("--muted", "#f4f4f5")])
        scale = (":root", [("--brand-foreground", "#ffffff"), ("--limn-ink", "#15161a"), ("--radius", "6px")])
        self.assertEqual(misplaced_colours([dark, light, scale]), [])
        for planted, expect in (
            ((":root", [("--limn-ink", "#15161a"), ("--muted", "#123456")]), ":root { --muted:#123456 }"),
            (
                (":root[data-theme=light]", [("color-scheme", "light"), ("--limn-ver", "#e8452c")]),
                ":root[data-theme=light] { --limn-ver:#e8452c }",
            ),
            ((".limn-mark-pin", [("fill", "#e8452c")]), ".limn-mark-pin { fill:#e8452c }"),
            ((":root", [("color", "white")]), ":root { color:white }"),
        ):
            with self.subTest(planted=planted):
                self.assertEqual(misplaced_colours([dark, light, scale, planted]), [expect])

    def test_both_themes_define_every_colour_token(self):
        blocks = {
            sel: dict(decls)
            for sel, decls in css_rules()
            if sel in TOKEN_SELECTORS and any(k == "color-scheme" for k, _ in decls)
        }
        dark, light = blocks[":root"], blocks[":root[data-theme=light]"]

        def lit(block):
            """Custom properties in a theme block whose value is a color."""
            return {k for k, v in block.items() if k.startswith("--") and COLOR_RE.search(v)}

        self.assertEqual(lit(dark) - set(light), set())  # dark colors don't leak into light
        self.assertEqual(set(light) - set(dark), set())  # light only overrides tokens that exist in dark
        for k in (
            "--background",
            "--foreground",
            "--card",
            "--card-foreground",
            "--muted",
            "--muted-foreground",
            "--border",
            "--input",
            "--ring",
            "--primary",
            "--primary-foreground",
            "--secondary",
            "--secondary-foreground",
            "--destructive",
            "--destructive-foreground",
            "--status-open",
            "--status-claimed",
            "--status-closed",
            "--status-dropped",
            "--status-warning",
        ):
            self.assertIn(k, dark)

    def test_radius_uses_scale_only(self):
        bad = []
        for sel, decls in css_rules():
            for k, v in decls:
                if re.fullmatch(r"border(?:-[a-z]+)*-radius", k) and not all(RADIUS_OK.match(t) for t in v.split()):
                    bad.append("%s { %s:%s }" % (sel, k, v))
        self.assertEqual(bad, [])
        defs = {k: v for sel, decls in css_rules() if sel == ":root" for k, v in decls}
        self.assertEqual([defs["--radius-sm"], defs["--radius"], defs["--radius-lg"]], ["4px", "6px", "10px"])

    def test_font_size_uses_text_scale_only(self):
        bad = []
        for sel, decls in css_rules():
            for k, v in decls:
                if k == "font-size" and not re.fullmatch(r"var\(--text-(?:xs|sm|base|lg|xl)\)|inherit", v):
                    bad.append("%s { %s:%s }" % (sel, k, v))
                if k == "font" and v != "inherit" and not v.startswith("var(--text-"):
                    bad.append("%s { %s:%s }" % (sel, k, v))
        self.assertEqual(bad, [])
        # the scale block (the :root that defines --text-sm) holds the five steps; touch only raises the smallest to 12px
        # (input diagnosis P7: badges and counts were 11px on a phone - the live check is PhoneTouchSizes)
        scale = next(dict(decls) for sel, decls in css_rules() if sel == ":root" and "--text-sm" in dict(decls))
        self.assertEqual(
            [scale["--text-" + n] for n in ("xs", "sm", "base", "lg", "xl")], ["11px", "12px", "13px", "14px", "16px"]
        )
        css = HTML[HTML.index("<style>") : HTML.index("</style>")]
        coarse = css[css.index("@media (pointer:coarse){") :]
        self.assertIn(":root{--doc-nav-h:48px;--text-xs:12px}", coarse[: coarse.index("\n}")])

    def test_inline_styles_and_scripts_carry_no_design_literals(self):
        body = HTML[HTML.index("</style>") :]
        for st in re.findall(r'style="([^"]*)"', body):
            self.assertTrue(
                st in INLINE_STYLE_OK or not (COLOR_RE.search(st) or re.search(r"font-size|radius", st)), st
            )
        # JS never sets color or font size directly on an element's style (only width/height/coordinates/token variables)
        self.assertEqual(
            re.findall(r"\.style\.(?:color|background\w*|fontSize|borderRadius|borderColor)\s*=", body), []
        )
        self.assertIsNone(re.search(r"['\"]#[0-9a-fA-F]{3,8}['\"]", body))

    def test_every_var_is_defined(self):
        css = HTML[HTML.index("<style>") : HTML.index("</style>")]
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        # values JS measures and sets (--kb, --side-w, etc.)
        runtime = set(re.findall(r"setProperty\('(--[a-z0-9-]+)'", HTML))
        used = set(re.findall(r"var\((--[a-z0-9-]+)", css))
        defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", css))
        self.assertEqual(used - defined - runtime, set())  # no old tokens left over from a rename (--acc, --dim, ...)

    def test_component_variants_exist(self):
        css = HTML[HTML.index("<style>") : HTML.index("</style>")]
        for cls in (
            "button.btn-default{",
            "button.btn-secondary{",
            "button.btn-soft{",
            "button.btn-ghost{",
            "button.btn-destructive{",
            "button.btn-sm{",
            "button.btn-icon{",
            ".badge{",
            ".badge-default{",
            ".badge-secondary{",
            ".badge-destructive{",
            ".badge-claimed{",
            ".badge-warning{",
            ".card{",
        ):
            self.assertIn(cls, css)
        for old in ("button.p{", "button.x{", "button.ghost{", "button.ib{", "button.ico{", ".tag{", ".tag.t{"):
            self.assertNotIn(old, css)  # old display-only classes were removed


# ---------------------------------------------------------------- toasts — docs/handbook/viewer.md §알림(토스트)
# author feedback (2026-09-24): saving a pin used to pop an "undo" toast at the bottom-left, far from the
# right-hand panel (1,100px+ away), with a tacky left color stripe. It now appears sonner-style right
# where you just clicked (bottom-right of the panel column, just above the action row; on narrow, above the sheet).
class FrontendToasts(unittest.TestCase):
    """Guard toast layout, stacking, placement, and accessible message structure."""

    css = HTML[HTML.index("<style>") : HTML.index("</style>")]

    def rules(self, pat):
        return [(sel, dict(d)) for sel, d in css_rules() if re.search(pat, sel)]

    def test_toast_has_no_left_stripe_and_is_a_single_floating_surface(self):
        for sel, d in self.rules(r"\.toast"):
            self.assertFalse([k for k in d if k.startswith("border-left")], sel)
        base = dict(self.rules(r"^\.toast$")[0][1])
        self.assertEqual(base["border"], "1px solid var(--border)")
        self.assertEqual(base["border-radius"], "var(--radius-lg)")
        self.assertEqual(base["background"], "var(--popover)")
        self.assertIn("box-shadow", base)
        # state is shown via the leading icon's color — not a stripe
        for kind, icon in (("ok", "circle-check"), ("warn", "triangle-alert"), ("err", "circle-x")):
            self.assertIn("%s:()=>ic('%s')" % (kind, icon), HTML)
        self.assertIn(".toast.warn>.ic{color:var(--warning)}", self.css)
        self.assertIn(".toast.err>.ic{color:var(--destructive)}", self.css)

    def test_toast_anchored_per_layout_near_the_action(self):
        box = dict(self.rules(r"^#toasts$")[0][1])
        self.assertEqual(box["right"], "var(--toast-r,var(--space-3))")
        self.assertEqual(box["bottom"], "var(--toast-b,var(--space-3))")
        self.assertNotIn("left", box)  # formerly: pinned bottom-left
        self.assertIn("body.lay-narrow #toasts{", self.css)
        self.assertIn("body.lay-mid #toasts{", self.css)
        self.assertNotRegex(self.css, r"body\.lay-mid #toasts\{[^}]*top:")  # formerly: top-left of the body
        body = extract_js_fn("placeToasts")
        self.assertIn("'#c-actions'", body)  # doesn't cover the save/cancel buttons
        # doesn't cover the bottom toolbar (the short band has none: its tool bar is in the top row)
        self.assertIn("LAYOUT===LAYOUT_MODE.MID&&BAND!==LAYOUT_BAND.SHORT?['#bar1']", body)
        self.assertIn("right.getBoundingClientRect().top", body)  # narrow: above the sheet
        self.assertIn("sd.getBoundingClientRect().top-20", body)  # ... and over the status line's action hit
        self.assertIn("innerWidth-rr.right+12", body)  # right edge inside the panel column
        # a nearly-full sheet: drop down so it doesn't cover the toolbar
        self.assertIn("if(top<vh*0.3){top=vh; const ca=$('#c-actions');", body)
        self.assertIn(
            "@media (pointer:coarse){.toast{pointer-events:none}.toast button{pointer-events:auto}}", self.css
        )
        for v in ("--toast-b", "--toast-r", "--toast-w"):
            self.assertIn("setProperty('%s'" % v, body)

    def test_toast_stacks_newest_on_top_and_collapses_after_three(self):
        """Newest toast on top, 6s life, more than three fold (hover, focus or the '+N' button opens them), no motion when reduced."""
        body = extract_js_fn("toast")
        self.assertIn("box.insertBefore(t,box.firstChild)", body)
        self.assertIn("setTimeout(kill,6000)", body)
        self.assertIn(
            "#toasts:not(:hover):not(:focus-within):not(.expanded) .toast:nth-child(n+4){display:none}", self.css
        )  # + the '+N' button on touch
        self.assertIn("@keyframes toast-in", self.css)
        self.assertIn("@media (prefers-reduced-motion: reduce){*{animation:none!important", self.css)

    def test_toast_title_and_description_split(self):
        if not shutil.which("node"):
            self.skipTest("node not available")
        js = (
            extract_js_fn("toastSplit")
            + "\nconsole.log(JSON.stringify(['핀 #3 저장됨 · pins.md 갱신','빌드 실패 — 화면은 이전 PDF입니다','복사함','핀 #10 · 본문 — 서준님이 불렀습니다: 봐 주세요'].map(toastSplit)));"
        )
        self.assertEqual(
            json.loads(run_node(js)),
            [
                ["핀 #3 저장됨", "pins.md 갱신"],
                ["빌드 실패", "화면은 이전 PDF입니다"],
                ["복사함", ""],
                ["핀 #10 · 본문", "서준님이 불렀습니다: 봐 주세요"],
            ],
        )


# ---------------------------------------------------------------- no outline inside an outline (docs/handbook/viewer.md §한 겹 담기)
# author feedback (2026-09-24): drawing a bordered box inside another bordered box looks tacky. There is
# exactly one containing layer — a card (one thin border) or a floating surface (dialog/toast/@-list).
# Everything inside it — badges, buttons, segmented controls, steppers, source, overlap banner, thread —
# is separated only by fill, spacing, and dividers.
class FrontendNoNestedOutlines(unittest.TestCase):
    """Ensure inner card controls stay flat while floating surfaces carry their own outline."""

    INNER = re.compile(
        r"^(?:\.badge|\.seg|\.step|pre\b|#c-overlap|\.thread|\.edit\b|\.arc-thread|\.arc-orig|\.arc-row|\.msg|\.reply-box)"
    )
    SEPARATORS = {".thread": "border-top", ".arc-row+.arc-row": "border-top"}

    def test_inner_components_draw_no_outline_box(self):
        bad = []
        for sel, decls in css_rules():
            for part in [x.strip() for x in sel.split(",")]:
                if not self.INNER.match(part) or part.startswith(".dchip"):
                    continue
                for k, v in decls:
                    if k == "border" and v not in ("0", "none", "1px solid transparent"):
                        bad.append("%s { %s:%s }" % (part, k, v))
                    if (
                        re.fullmatch(r"border-(?:top|right|bottom|left)", k)
                        and self.SEPARATORS.get(part) != k
                        and v not in ("0", "none")
                    ):
                        bad.append("%s { %s:%s }" % (part, k, v))
                    if k == "border-color" and v != "transparent" and not part.startswith("button.badge"):
                        bad.append("%s { %s:%s }" % (part, k, v))
        self.assertEqual(bad, [])

    def test_card_buttons_are_filled_and_destructive_is_quiet(self):
        css = HTML[HTML.index("<style>") : HTML.index("</style>")]
        self.assertIn(
            ".pin :is(.acts,.e-acts,.r-acts) button:not(.btn-soft):not(.btn-destructive):not(.btn-default){background:var(--secondary);"
            "color:var(--secondary-foreground);border-color:transparent}",
            css,
        )
        self.assertIn(".pin .acts button.btn-destructive{background:transparent}", css)
        self.assertIn(".seg button.on{background:var(--popover);border-color:transparent;", css)
        # [더보기]'s zoom buttons are filled and borderless (secondary); its pin-group rows are rows - an icon and a name on the
        # sheet, a fill only under a mouse's hover (UX spec §V7)
        more = HTML[HTML.index('<dialog id="more"') :]
        more = more[: more.index("</dialog>")]
        for act in ("zoom-out", "zoom-in"):
            self.assertRegex(more, r'<button class="btn-secondary[^"]*"[^>]*data-act="%s"' % act)
        grid = more[more.index('<div class="more-grid">') : more.index('<div class="more-foot"')]
        for tag in re.findall(r"<button[^>]*>", grid):
            self.assertNotIn("btn-", tag)

    def test_floating_surfaces_are_the_only_shadows_with_hairlines(self):
        for sel in ("dialog", "#mention-pop"):
            d = dict(dict(css_rules())[sel])
            self.assertEqual(d["border"], "1px solid var(--border)", sel)
            self.assertEqual(d["box-shadow"], "var(--shadow-lg)", sel)


# ---------------------------------------------------------------- meaning/function check (docs/handbook/viewer.md §뜻과 모양) + UX QA (2026-09-24)
class FrontendSemanticAudit(unittest.TestCase):
    """Guard time, identity, notification, text, and touch semantics across viewer components."""

    css = HTML[HTML.index("<style>") : HTML.index("</style>")]

    def test_relative_time_with_absolute_on_hover(self):
        if not shutil.which("node"):
            self.skipTest("node not available")
        js = "\n".join(
            [
                js_esc(),
                js_markup(),
                extract_js_fn("relTime"),
                extract_js_fn("relSpan"),
                r"""
            const now=new Date(2026,8,24,15,0).getTime();
            console.log(JSON.stringify(['2026-09-24 15:00:10','2026-09-24 14:57:00','2026-09-24 11:00:00','2026-09-21 10:00:00','2026-09-01 10:00:00','x']
              .map(s=>relTime(s,now)).concat([String(relSpan('2026-09-01 10:00','arc-t','닫은 시각'))])));""",
            ]
        )
        out = json.loads(run_node(js))
        self.assertEqual(out[:6], ["방금", "3분 전", "4시간 전", "3일 전", "9-1", "x"])
        self.assertIn('data-tip="닫은 시각 2026-09-01 10:00"', out[6])
        self.assertIn("setInterval(tickRel,60000);", HTML)
        # formerly: it could wrap to '09-24 1…'
        self.assertIn(".arc-t{flex:none;font-size:var(--text-xs);white-space:nowrap}", self.css)

    def test_one_toast_per_event_notify_wins(self):
        if not shutil.which("node"):
            self.skipTest("node not available")
        js = "\n".join(
            [
                "const TOAST_KEYS=[];",
                extract_js_fn("toastDup"),
                r"""
            const el=()=>({isConnected:true,removed:false,remove(){this.removed=true;this.isConnected=false;}});
            const a=el(); TOAST_KEYS.push({keys:['review_requested:37'],rank:1,el:a,t:Date.now()});
            const r1=toastDup({keys:['review_requested:37'],rank:2});           // 알림 경로가 이긴다 — 옛 것을 걷고 띄운다
            const b=el(); TOAST_KEYS.push({keys:['review_requested:37'],rank:2,el:b,t:Date.now()});
            const r2=toastDup({keys:['review_requested:37'],rank:1});           // 뒤늦은 목록 비교 알림은 띄우지 않는다
            const r3=toastDup({keys:['reopened:37'],rank:1}), r4=toastDup(null);
            const r5=toastDup({keys:['review_requested:37'],rank:2});           // 같은 경로의 다음 사건(두 번째 검토 대기)은 막지 않는다
            console.log(JSON.stringify([r1,a.removed,r2,r3,r4,r5]));""",
            ]
        )
        self.assertEqual(json.loads(run_node(js)), [False, True, True, False, False, False])
        self.assertIn("{keys:[e.type+':'+e.pin],rank:2,literal:true}", extract_js_fn("notifyShow"))
        self.assertIn("{keys:reviewed.map(i=>EVENT_TYPE.REVIEW_REQUESTED+':'+i)}", extract_js_fn("diffToast"))
        self.assertIn("{keys:[EVENT_TYPE.REOPENED+':'+p.id]}", extract_js_fn("reviewToast"))

    def test_closed_cards_drop_position_badges_and_thread_count_opens_reply(self):
        body = extract_js_fn("card")
        self.assertIn("const rb=closedCard?null:relBadge(p.rel,p);", body)
        self.assertIn("const v=closedCard?null:viaTag(p);", body)
        self.assertIn('class="th-n" role="button" tabindex="0" data-act="reply-open"', body)

    def test_long_messages_clamp_and_identity_marks(self):
        self.assertIn(".msg-t.clamp{display:-webkit-box;-webkit-line-clamp:6;", self.css)
        self.assertIn('data-act="msg-more"', extract_js_fn("msgBody"))
        agent = run_node(
            "\n".join(
                [js_esc(), js_icons(), extract_js_fn("isAgent"), extract_js_fn("avatar")]
                + ["console.log(String(avatar({login:'agent:x',name:'Bot'})));"]
            )
        )
        self.assertTrue(agent.startswith('<span class="av i agent" aria-hidden="true"><svg class="ic ic-bot"'), agent)
        self.assertIn("(나)", extract_js_fn("msgHtml"))
        self.assertIn("(나)", extract_js_fn("card"))

    def test_touch_targets_in_archive_rows(self):
        coarse = self.css[self.css.index("@media (pointer:coarse){") :]
        coarse = coarse[: coarse.index("\n}")]
        self.assertIn("button.arc-orig-t{min-height:44px;min-width:44px;", coarse)
        self.assertIn(".arc-reply{min-height:44px;", coarse)
        self.assertIn(".th-n{min-height:44px;min-width:44px;", coarse)

    def test_review_count_labels_scope_and_filter_is_compact(self):
        self.assertIn("' '+tl('(이 문서 {n})',{n:here})", extract_js_fn("updateReviewCount"))
        body = extract_js_fn("drawPins")
        self.assertIn(
            "setHtml(mf,html`${ic('at-sign')}${MINE.length}`); mf.setAttribute('aria-label',tl('나를 부른 핀 {n}',{n:MINE.length}));",
            body,
        )

    def test_revision_note_wraps_and_returns_to_previous_doc(self):
        """The guide line's buttons are one group at its right that never shrinks ([원고로], and [확인] for a pin awaiting
        review); revTargetActs draws them."""
        self.assertIn("#revision-pin .rp-acts{display:flex;gap:var(--space-2);flex:none;margin-left:auto}", self.css)
        self.assertIn('data-act="rev-back"', extract_js_fn("revTargetActs"))
        self.assertIn("if(fromManuscript)REV.back=back", extract_js_fn("showChange"))
        self.assertIn("case 'rev-back':", HTML)

    def test_the_source_diff_always_wraps(self):
        """The [줄바꿈] toggle is gone (the owner's decision): both diffs are always wrapped, a long token breaking too."""
        self.assertNotIn('id="revision-wrap"', HTML)
        self.assertNotIn('data-act="diff-wrap"', HTML)
        self.assertIn('<pre id="revision-diff" class="wrap"></pre>', HTML)
        self.assertIn(
            "#revision-diff.wrap .rd-code{flex:1;min-width:0;white-space:pre-wrap;overflow-wrap:anywhere}", self.css
        )

    def test_change_view_on_fold_and_phone(self):
        # [변경 보기] phone/fold QA (2026-09-25): on a fold (the overlay panel, body.mid-overlay), the pin panel floats on top,
        # hiding the right half of the diff and the [원고로] button — only the change view yields space
        # equal to the panel width. Commit picking / build-warning expand are 44px on touch.
        self.assertIn("body.mid-overlay.side-open #revision-view{padding-right:var(--side-w,330px)}", self.css)
        self.assertIn("#revision-list select,#revision-file-row select{min-height:var(--control-h-touch)}", self.css)
        self.assertIn("#revision-warning summary{line-height:var(--control-h-touch)}", self.css)
        # if the pin's range line isn't in the diff and only nearby lines changed, don't say "the highlighted line is the pin's range" (there is no highlighted line).
        self.assertIn("tg.near=!first&&tg.hit", extract_js_fn("revHighlight"))
        self.assertIn("tg.near?'핀 범위 줄 자체는 바뀌지 않았고", extract_js_fn("revTargetNote"))

    def test_references_share_one_link_style_and_pending_looks_pending(self):
        # one consistent link style (QA 2026-09-24): #number, line range, page N, and in-text #12 all share
        # one look — primary color, no underline at rest, solid underline on hover/focus. There used to be
        # three looks: bold dotted, blue, gray dotted. A dotted underline is now used only for an
        # unresolved @-mention (.mention-bad).
        self.assertIn(":is(.loc,.pg-link,.pin .n.go,.pin-ref){text-decoration:none;", self.css)
        self.assertIn(":is(.loc,.pg-link,.pin .n.go,.pin-ref):focus-visible{text-decoration:underline}", self.css)
        self.assertIn(  # the hover underline answers a mouse only (FrontendHoverForMouse)
            "@media (hover:hover){:is(.loc,.pg-link,.pin .n.go,.pin-ref):hover{text-decoration:underline}}", self.css
        )
        for rule in (
            ".pin .n.go{cursor:pointer;color:var(--primary);",
            ".pin-ref{color:var(--primary);",
            ".pg-link{color:var(--primary);",
        ):
            self.assertIn(rule, self.css)
        dotted = [r for r in re.findall(r"[^{}]+\{[^}]*underline dotted[^}]*\}", self.css)]
        self.assertEqual([r.split("{")[0].strip() for r in dotted], [".mention-bad"])
        self.assertIn("button[data-pending]{cursor:progress;", self.css)


def theme_tokens(theme: str) -> dict[str, str]:
    """The custom properties a theme ('dark' or 'light') resolves at :root: the scale block, the dark block and - for
    light - the light block over it, as written (values may still hold var())."""
    out: dict[str, str] = {}
    for sel, decls in css_rules():
        d = dict(decls)
        scheme = d.get("color-scheme")
        if (sel == ":root" and scheme in (None, "dark")) or (theme == "light" and sel == ":root[data-theme=light]"):
            out.update({k: v for k, v in decls if k.startswith("--")})
    return out


RGBA = tuple[float, float, float, float]


def css_colour(value: str, tokens: dict[str, str]) -> RGBA:
    """A token-built CSS colour as (r, g, b, alpha), r/g/b 0-255: var(--x), #rgb/#rrggbb/#rrggbbaa, transparent and
    color-mix(in srgb, A N%, B) with B optional."""
    v = value.strip()
    m = re.fullmatch(r"var\((--[\w-]+)\)", v)
    if m:
        return css_colour(tokens[m.group(1)], tokens)
    if v == "transparent":
        return (0.0, 0.0, 0.0, 0.0)
    m = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})", v)
    if m:
        h = m.group(1)
        h = "".join(c * 2 for c in h) if len(h) == 3 else h
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        return (float(int(h[0:2], 16)), float(int(h[2:4], 16)), float(int(h[4:6], 16)), a)
    m = re.fullmatch(r"color-mix\(in srgb,\s*(.+?)\s+(\d+(?:\.\d+)?)%\s*(?:,\s*(.+))?\)", v)
    if m:
        p = float(m.group(2)) / 100
        a, b = css_colour(m.group(1), tokens), css_colour(m.group(3) or "transparent", tokens)
        alpha = a[3] * p + b[3] * (1 - p)
        if not alpha:
            return (0.0, 0.0, 0.0, 0.0)
        mix = [(a[i] * a[3] * p + b[i] * b[3] * (1 - p)) / alpha for i in range(3)]
        return (mix[0], mix[1], mix[2], alpha)
    raise ValueError("not a token colour: %s" % value)


def contrast(fg: RGBA, bg: RGBA) -> float:
    """The WCAG contrast ratio of fg drawn over the opaque bg (fg's alpha composited first)."""

    def lum(c: tuple[float, float, float]) -> float:
        lin = [(x / 255 / 12.92) if x / 255 <= 0.03928 else ((x / 255 + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    over = tuple(fg[i] * fg[3] + bg[i] * (1 - fg[3]) for i in range(3))
    hi, lo = sorted((lum((over[0], over[1], over[2])), lum((bg[0], bg[1], bg[2]))), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def rule_value(selector: str, prop: str) -> str:
    """The last value of prop among the page's rules whose selector is exactly selector."""
    vals = [dict(decls)[prop] for sel, decls in css_rules() if sel == selector and prop in dict(decls)]
    if not vals:
        raise KeyError("%s { %s }" % (selector, prop))
    return vals[-1]


class FrontendColourRoles(unittest.TestCase):
    """Colour roles and contrast (docs/handbook/viewer.md §토큰, UX audit P10/P12): the instance colour paints the stripe, the
    label and the current document's underline only - a red count badge read like an unread alert; the sheet and panel
    grab bars reach 3:1 against their surface in both themes (the sheet's measured 2.5:1)."""

    def test_no_count_badge_is_painted_in_the_instance_colour(self):
        """The documents sheet's count of the current document ('11' white on red) used --brand; every .dcnt is neutral."""
        bad = [
            "%s { %s:%s }" % (sel, k, v)
            for sel, decls in css_rules()
            if ".dcnt" in sel
            for k, v in decls
            if "--brand" in v
        ]
        self.assertEqual(bad, [])

    def test_the_grab_bars_reach_3_to_1_on_their_surface_in_both_themes(self):
        """The phone and tablet sheet handle and the mid panel handle, over --sidebar, light and dark."""
        for sel in ("body.lay-narrow #sheet-grip::before", "body.lay-mid #grip::before"):
            for theme in ("light", "dark"):
                with self.subTest(handle=sel, theme=theme):
                    t = theme_tokens(theme)
                    ratio = contrast(css_colour(rule_value(sel, "background"), t), css_colour("var(--sidebar)", t))
                    self.assertGreaterEqual(ratio, 3.0)

    def test_the_review_pill_and_the_neutral_count_read_at_4_5_to_1(self):
        """The [핀 N] review pill (its number and eye icon) and the neutral count badge, both themes."""
        for theme in ("light", "dark"):
            t = theme_tokens(theme)
            for fg, bg in (
                ("--status-review-foreground", "--status-review"),
                ("--secondary-foreground", "--secondary"),
            ):
                with self.subTest(theme=theme, fg=fg):
                    ratio = contrast(css_colour("var(%s)" % fg, t), css_colour("var(%s)" % bg, t))
                    self.assertGreaterEqual(ratio, 4.5)

    def test_the_bars_review_half_reads_at_4_5_to_1_in_both_themes(self):
        """Every compact bar's review count is the split chip's right half [검토 M] (the [👁 M] pill inside [📍 N] went with
        2b of the cross-resolution pass): its review-coloured words and count read at 4.5:1 on the chip's tonal fill in both
        themes."""
        fg = rule_value("body.compact #bar1 #btn-rv,body.compact #bar1 #btn-rv .side-l", "color")
        bg = rule_value("body.compact #bar1 :is(#btn-side,#btn-rv,#btn-select)", "background")
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                t = theme_tokens(theme)
                self.assertGreaterEqual(contrast(css_colour(fg, t), css_colour(bg, t)), 4.5)

    def test_the_contrast_helper_matches_known_pairs(self):
        """Black on white is 21:1, #a1a1aa on white 2.56:1 (the old handle), and a 50% mix over white is the mix."""
        t = {"--w": "#ffffff", "--k": "#000000"}
        self.assertAlmostEqual(contrast(css_colour("#000", t), css_colour("var(--w)", t)), 21.0, places=2)
        self.assertAlmostEqual(contrast(css_colour("#a1a1aa", t), css_colour("#fff", t)), 2.56, delta=0.01)
        self.assertEqual(css_colour("color-mix(in srgb,var(--k) 50%,transparent)", t), (0.0, 0.0, 0.0, 0.5))


def hover_rules_outside_hover_media(css: str) -> list[str]:
    """The selector of every style rule in css that has :hover but that no `@media (hover:hover)` encloses. A negated
    query (`@media not all and (hover:hover)`) does not count: a hover look answers a mouse only, and a touch screen's
    tap leaves a sticky :hover behind (UX audit P4.6)."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    stack: list[str] = []
    bad: list[str] = []
    start = 0
    for i, ch in enumerate(css):
        if ch == "{":
            prelude = css[start:i].strip()
            if not prelude.startswith("@") and ":hover" in prelude:
                mouse = any(
                    p.startswith("@media")
                    and re.search(r"\(\s*hover\s*:\s*hover\s*\)", p)
                    and not re.match(r"@media\s+not\b", p)
                    for p in stack
                )
                if not mouse:
                    bad.append(prelude)
            stack.append(prelude)
            start = i + 1
        elif ch in "};":
            if ch == "}" and stack:
                stack.pop()
            start = i + 1
    return bad


class FrontendHoverForMouse(unittest.TestCase):
    """Every hover look sits inside `@media (hover:hover)` (docs/handbook/viewer.md §뜻과 모양): on a touch screen a tapped
    row of [더보기] stayed grey after the tap, the owner's 'Theme: System' (UX audit P4.6, 29 bare :hover rules)."""

    def test_no_hover_rule_answers_a_touch_screen(self):
        """The served page's CSS has no :hover rule outside a hover media query."""
        css = HTML[HTML.index("<style>") + len("<style>") : HTML.index("</style>")]
        self.assertEqual(hover_rules_outside_hover_media(css), [])

    def test_a_touch_press_gets_a_brief_token_wash_instead(self):
        """With hover answering a mouse only, a touch screen still sees a press: while a control is pressed (:active) an
        inset wash of the text colour covers its surface, from tokens, under the no-hover query only - so nothing stays
        after the finger lifts and a mouse keeps its hover look."""
        css = HTML[HTML.index("<style>") + len("<style>") : HTML.index("</style>")]
        self.assertIn(
            "@media not all and (hover:hover){button:active:not(:disabled){box-shadow:inset 0 0 0 100vmax "
            "color-mix(in srgb,var(--foreground) 8%,transparent)}}",
            css,
        )
        self.assertEqual(css.count(":active"), 1)

    def test_the_guard_catches_a_bare_a_negated_and_a_pointer_hover_rule(self):
        """A bare rule, one under the negated query and one under another media query are reported; the same rule inside
        `@media (hover:hover)` (alone or with another condition) is not."""
        ok = "@media (hover:hover){a:hover{color:red}}@media (hover:hover) and (pointer:fine){b:hover{color:red}}"
        self.assertEqual(hover_rules_outside_hover_media(ok + "c:focus-visible{color:red}"), [])
        for planted, sel in (
            ("button:hover{color:red}", "button:hover"),
            ("@media not all and (hover:hover){x:not(:hover) y{display:none}}", "x:not(:hover) y"),
            ("@media (pointer:coarse){z:is(:hover,:focus-visible){color:red}}", "z:is(:hover,:focus-visible)"),
        ):
            with self.subTest(planted=planted):
                self.assertEqual(hover_rules_outside_hover_media(ok + planted), [sel])


class PinNumberJump(unittest.TestCase):
    """Clicking the #number in a card's header jumps to that pin's spot in the PDF (same data-act="view" as [보기]/page N)."""

    def test_number_is_a_button_that_jumps(self):
        src = HTML
        self.assertIn('<span class="n go" role="button" tabindex="0" data-act="view"', src)
        self.assertIn("누르면 PDF에서 이 핀 자리로 갑니다", src)

    def test_number_is_keyboard_and_touch_reachable(self):
        """#N is a role=button the keyboard reaches; on touch #N, the line range and N쪽 are each a real 44x44 box.

        Regression: #N used to render at only its text width (26-35px) with a fixed 44x44 ::before centred on it, and
        '1쪽' (16px) and 'L4-L5' only got min-height - their centred hit areas overlapped 4-8px apart, so '1쪽' answered
        16x38 (input diagnosis P6). Real boxes cannot overlap; the live check is PhoneTouchSizes."""
        src = HTML
        self.assertIn("/^(button|link)$/.test(t.getAttribute('role')||'')&&t.dataset&&t.dataset.act", src)
        css = src[src.index("<style>") : src.index("</style>")]
        coarse = css[css.index("@media (pointer:coarse){") :]
        coarse = coarse[: coarse.index("\n}")]
        self.assertIn(
            ".loc,.pg-link,.pin .n.go{display:inline-flex;align-items:center;justify-content:center;"
            "min-height:var(--hit);min-width:var(--hit);position:relative}",
            coarse,
        )
        self.assertNotIn(".pin .n.go::before", css)

    def test_view_action_still_routes_to_jumppin(self):
        self.assertIn("case 'view':jumpPin(id);break;", HTML)

    def test_touch_media_query_wins_over_btn_icon_btn_sm_specificity(self):
        # regression: button.btn-icon.btn-sm{width:var(--control-h-sm)} (base rule, 0-0-2-1) is more
        # specific than the touch rule button.btn-icon{width:var(--control-h-touch)} (0-0-1-1), so the
        # card fold button (.b-fold) and the toast close button stayed at 24px even on touch (observed).
        # It has to be pinned again at the same specificity (.btn-icon.btn-sm) inside @media(pointer:coarse) to win.
        css = HTML[HTML.index("<style>") : HTML.index("</style>")]
        coarse = css[css.index("@media (pointer:coarse){") :]
        coarse = coarse[: coarse.index("\n}\n") + 3]
        self.assertIn(
            "button.btn-icon.btn-sm{width:var(--control-h-touch);min-width:var(--control-h-touch);"
            "height:var(--control-h-touch)}",
            coarse,
        )
        # real usage: both the card fold button and the toast close button use the .btn-icon.btn-sm combination.
        self.assertIn("btn-icon btn-sm btn-ghost cmp b-fold", HTML)
        self.assertIn("c.className='btn-icon btn-sm btn-ghost'", HTML)

    def test_compact_bar1_buttons_keep_touch_min_width_despite_shrink_to_fit(self):
        # regression: body.compact #bar1 button{min-width:0} (specific due to the id) beat the touch rule
        # button{min-width:44px}, so on a narrow screen like lay-mid the [select] button shrank to 40px
        # (observed). The same selector is pinned again inside @media(pointer:coarse) to keep the 44px floor.
        css = HTML[HTML.index("<style>") : HTML.index("</style>")]
        self.assertIn("body.compact #bar1 button{flex:1 1 auto;min-width:0;", css)
        self.assertIn("@media (pointer:coarse){body.compact #bar1 button{min-width:44px}}", css)
        # this override must come after the min-width:0 rule in source order to win at equal specificity.
        self.assertGreater(
            css.index("@media (pointer:coarse){body.compact #bar1 button{min-width:44px}}"),
            css.index("body.compact #bar1 button{flex:1 1 auto;min-width:0;"),
        )


class HtmlTemplateStructure(unittest.TestCase):
    """Whether HTML, as of module load (before main() runs), has the label placeholder and markup —
    structural verification must always hold regardless of the actual substituted value."""

    def test_title_has_label_placeholder(self):
        self.assertIn("<title>Limn · __LABEL__</title>", HTML)

    def test_favicon_links(self):
        """The favicon links carry the icons' content key, filled at assembly - no accent key or accent-coloured
        SVG is left for the run (test_brand.py)."""
        self.assertRegex(HTML, r'<link rel="icon" href="/favicon\.ico\?v=[0-9a-f]{12}" sizes="16x16 32x32"')
        for gone in ("__ICON_KEY__", "__FAVICON_HREF__", "__ACCENT_KEY__", "image/svg+xml"):
            self.assertNotIn(gone, HTML[: HTML.index("</head>")])

    def test_brand_stripe_present(self):
        self.assertIn('id="brand-stripe"', HTML)
        self.assertIn("#brand-stripe{position:fixed;top:0;left:0;right:0;height:4px", HTML)

    def test_identity_crumb_precedes_desktop_doc_links_and_not_right_toolbar(self):
        self.assertLess(HTML.index('id="paper-identity"'), HTML.index('id="doc-links"'))
        self.assertLess(HTML.index('id="paper-identity"'), HTML.index('id="right"'))
        self.assertNotIn('id="brand-chip"', HTML)

    def test_identity_crumb_does_not_take_mobile_space(self):
        self.assertIn("body.lay-narrow #paper-identity{display:none}", HTML)
        # the nav bar is off on the phone sheet only; the tablet sheet keeps it above the document
        self.assertIn("body:not(.lay-narrow) #doc-nav,body.band-tablet-sheet #doc-nav{display:flex}", HTML)

    def test_document_title_prefixes_label(self):
        # with multiple documents, the document name (META.doc_name) is used instead of the main filename — the label prefix stays the same.
        self.assertIn(
            "document.title='Limn · '+(META.label?META.label+' · ':'')+(multiDoc()?META.doc_name||META.main:META.main)"
            "+' · '+tl('열린 {n}',{n:PINS.length})",
            extract_js_fn("docTitle"),
        )
        self.assertIn("docTitle(true);", extract_js_fn("applyPinLists"))


class FrontendDocs(unittest.TestCase):
    """Distinguishes the desktop document selector from the mobile document menu."""

    def test_document_selector_and_mobile_button(self):
        css = HTML
        self.assertIn("#doc-select-wrap{display:none;", css)
        self.assertIn("#doc-links{display:none;", css)
        # the tablet sheet switches documents by the nav bar's links; only the phone has [본문 3/25 ▾] - with one document
        # too, since it also leads to the view, the page and the outline (UX spec §V9)
        self.assertIn(
            "body.docs-multi:not(.lay-narrow) #doc-links,body.docs-multi.band-tablet-sheet #doc-links{display:flex}",
            css,
        )
        self.assertIn("body:not(.lay-narrow) #doc-nav,body.band-tablet-sheet #doc-nav{display:flex}", css)
        self.assertIn("#btn-pos{display:none;", css)
        self.assertIn("body.band-phone #btn-pos{display:inline-flex}", css)
        self.assertNotIn('id="docs-menu"', HTML)
        self.assertIn("body.no-rebuild #btn-rebuild{display:none}", css)
        self.assertIn('id="all-docs"', css)
        self.assertIn("$('#all-docs').hidden=!multiDoc()", HTML)
        self.assertIn("document.body.classList.toggle('docs-multi',multiDoc())", HTML)

    def test_selector_views_and_outline_are_in_pdf_area(self):
        self.assertIn('<select id="doc-select" aria-label="문서 선택">', HTML)
        self.assertIn('<div id="doc-links" role="group" aria-label="문서 선택">', HTML)
        self.assertIn('id="view-manuscript" data-act="view-mode"', HTML)
        self.assertIn('id="view-revisions" data-act="view-mode"', HTML)
        self.assertIn('<nav id="outline" aria-label="원고 목차">', HTML)
        self.assertIn("body.outline-collapsed #outline{display:none}", HTML)
        self.assertIn('id="nav-toc-toggle" data-act="outline"', HTML)
        self.assertLess(HTML.index('id="doc-nav"'), HTML.index('id="right"'))
        body = extract_js_fn("drawDocTabs")
        self.assertIn("box.value=DOC", body)
        self.assertIn("DOCS.map", body)
        self.assertIn('aria-current="', body)

    def test_default_theme_is_light(self):
        self.assertIn('<html lang="ko" data-theme="light">', HTML)
        self.assertIn("p={theme:'light'}", HTML)
        self.assertIn("prefs().theme||'light'", HTML)

    def test_outline_labels_only_attach_to_matching_pdf_entries(self):
        js = "\n".join(
            [
                extract_js_fn("mergeOutlineLabels"),
                r"""
            const entries=[
              {title:'Experimental design',page:9,depth:0},
              {title:'Questions and comparisons',page:10,depth:1},
              {title:'Repeated',page:11,depth:1},
              {title:'Repeated',page:12,depth:1}];
            const labels=[
              {number:'4',title:'Experimental design',page:'9'},
              {number:'4.2',title:'Questions and comparisons',page:'11'},
              {number:'4.3',title:'Repeated',page:'11'},
              {number:'4.4',title:'Repeated',page:'13'}];
            console.log(JSON.stringify(mergeOutlineLabels(entries,labels).map(x=>[x.number,x.pageLabel])));""",
            ]
        )
        self.assertEqual(json.loads(run_node(js)), [["4", "9"], ["", ""], ["4.3", "11"], ["", ""]])

    def test_outline_labels_require_matching_section_depth_when_supported(self):
        js = "\n".join(
            [
                extract_js_fn("mergeOutlineLabels"),
                r"""
            const entries=[{title:'Overview',page:1,depth:0},{title:'Overview',page:1,depth:1}];
            const labels=[{number:'0.9',title:'Overview',page:'1',level:'subsection'},
                          {number:'1',title:'Overview',page:'1',level:'section'},
                          {number:'1.1',title:'Overview',page:'1',level:'subsection'}];
            console.log(JSON.stringify(mergeOutlineLabels(entries,labels).map(x=>x.number)));""",
            ]
        )
        self.assertEqual(json.loads(run_node(js)), ["1", "1.1"])

    def test_revision_async_result_is_ignored_after_doc_commit_or_view_change(self):
        js = "\n".join(
            [
                "let DOC='ms'; const REV={seq:8,commit:'abc'};",
                "const document={body:{classList:{contains:x=>x==='revision-open'}}};",
                extract_js_fn("revisionCurrent"),
                r"""
            console.log(JSON.stringify([
              revisionCurrent(8,'ms','abc'),revisionCurrent(7,'ms','abc'),
              revisionCurrent(8,'hl','abc'),revisionCurrent(8,'ms','def')]));""",
            ]
        )
        self.assertEqual(json.loads(run_node(js)), [True, False, False, False])

    def test_pin_actions_restore_pdf_from_revision_view(self):
        self.assertIn("setViewMode(VIEW_MODE.MANUSCRIPT)", extract_js_fn("jumpPin"))
        self.assertIn("jumpPin(id)", extract_js_fn("openEdit"))

    def test_revision_diff_rows_have_line_semantics_and_escape_source(self):
        patch = (
            "diff --git a/ms/main.tex b/ms/main.tex\n"
            "index 123..456 100644\n--- a/ms/main.tex\n+++ b/ms/main.tex\n"
            "@@ -3,2 +3,2 @@ heading\n-old <script>alert(1)</script>\n"
            "+new <img src=x onerror=alert(1)>\n context\n"
        )
        esc = re.search(r"^const esc=.*;$", HTML, re.M).group(0)
        js = "\n".join(
            [
                esc,
                js_markup(),
                extract_js_fn("renderRevisionDiff"),
                "console.log(JSON.stringify(String(renderRevisionDiff(%s))));" % json.dumps(patch),
            ]
        )
        out = run_node(js)
        if out is None:
            self.skipTest("node not available")
        rendered = json.loads(out)
        self.assertRegex(rendered, r"rd-hunk[^>]*>.*?@@ -3,2 \+3,2 @@")
        self.assertRegex(rendered, r"rd-del[^>]*>.*?rd-no[^>]*>3</span>")
        self.assertRegex(rendered, r"rd-add[^>]*>.*?rd-no[^>]*>3</span>")
        self.assertRegex(rendered, r"rd-context[^>]*>.*?rd-no[^>]*>4</span>")
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<img ", rendered)
        self.assertIn("rd-meta", rendered)

    def test_revision_file_selection_renders_only_selected_patch(self):
        esc = re.search(r"^const esc=.*;$", HTML, re.M).group(0)
        js = "\n".join(
            [
                esc,
                js_markup(),
                extract_js_fn("renderRevisionDiff"),
                extract_js_fn("renderRevisionFile"),
                r"""
            const REV={whole:'+from first\n+from second',files:[
              {text:'+from first'}, {text:'+from second'}]};
            const nodes={'#revision-file':{value:'1'},'#revision-diff':{innerHTML:''}};
            function $(selector){return nodes[selector];}
            renderRevisionFile(); console.log(JSON.stringify(nodes['#revision-diff'].innerHTML));""",
            ]
        )
        out = run_node(js)
        if out is None:
            self.skipTest("node not available")
        rendered = json.loads(out)
        self.assertIn("from second", rendered)
        self.assertNotIn("from first", rendered)
        self.assertIn("rd-add", rendered)

    def test_hash_dq_and_initial_doc(self):
        js = "\n".join(
            [
                r"""
            const DOCS=[{key:'ms'},{key:'rr'},{key:'rv'}]; let DOC='ms'; let _prefs={}; function prefs(){return _prefs;}
            const location={hash:''};
            """,
                extract_js_fn("docInfo"),
                extract_js_fn("dq"),
                extract_js_fn("hashDoc"),
                extract_js_fn("initialDoc"),
                r"""
            const out=[];
            out.push(dq('/api/meta'), dq('/api/meta?light=1'), dq('/pdf?build=x','rr'));
            location.hash='#doc=rr'; out.push(initialDoc());
            location.hash='#doc=Nope'; _prefs={lastDoc:'rv'}; out.push(initialDoc());       // 해시가 틀리면 마지막 문서
            location.hash='#doc=zz'; _prefs={lastDoc:'gone'}; out.push(initialDoc());      // 둘 다 없으면 첫 문서
            location.hash='#x=1&doc=rv'; _prefs={}; out.push(hashDoc());
            console.log(JSON.stringify(out));
            """,
            ]
        )
        out = run_node(js)
        if out is None:
            self.skipTest("node not available")
        self.assertEqual(
            json.loads(out),
            ["/api/meta?doc=ms", "/api/meta?light=1&doc=ms", "/pdf?build=x&doc=rr", "rr", "rv", "ms", "rv"],
        )

    def test_switch_shortcuts_skip_input_fields(self):
        m = re.search(r"document\.addEventListener\('keydown',e=>\{(.*?)\n\}\);", HTML, re.S)
        body = m.group(1)
        i = body.index("if(multiDoc()&&!inField){")
        self.assertIn("e.key==='PageUp'||e.key==='PageDown'", body[i:])
        self.assertIn("/^Digit[1-9]$/.test(e.code||'')", body[i:])
        self.assertLess(body.index("const t=/** @type {HTMLElement} */(e.target),inField="), i)

    def test_view_memory_and_pdfjs_cache_are_bounded(self):
        self.assertIn("const VEC_CACHE_MAX=3;", HTML)
        put = extract_js_fn("vecCachePut")
        self.assertIn("while(c.size>VEC_CACHE_MAX)", put)
        self.assertIn("vecClose(d)", put)
        sw = extract_js_fn("switchDoc")
        self.assertIn("saveView();", sw)
        self.assertIn("setHash(k)", sw)
        self.assertIn("savePrefs({lastDoc:k})", sw)
        show = extract_js_fn("showDoc")
        self.assertIn("restoreView(v)", show)
        self.assertIn("vecOpen()", show)

    def test_cross_doc_card_actions_switch_first(self):
        self.assertIn("function jumpPin(id){if(viaDoc(id,jumpPin))return;", HTML)
        self.assertIn("function openEdit(id){if(viaDoc(id,openEdit))return;", HTML)
        js = "\n".join(
            [
                r"""
            const OPEN_ALL=[{id:1,doc:'ms'},{id:2,doc:'rr'},{id:3}]; let DOC='ms',SWITCHSEQ=0; const DEFAULT_DOC='ms';
            const DOCS=[{key:'ms'},{key:'rr'}]; const seen=[];
            function switchDoc(k){seen.push('switch:'+k); DOC=k; SWITCHSEQ++; return Promise.resolve();}
            """,
                extract_js_fn("docInfo"),
                extract_js_fn("pdoc"),
                extract_js_fn("viaDoc"),
                r"""
            (async()=>{const out=[viaDoc(1,()=>{}), viaDoc(3,()=>{}), viaDoc(2,id=>seen.push('then:'+id))];
              await Promise.resolve(); await Promise.resolve(); out.push(seen); console.log(JSON.stringify(out));})();
            """,
            ]
        )
        out = run_node(js)
        if out is None:
            self.skipTest("node not available")
        self.assertEqual(json.loads(out), [False, False, True, ["switch:rr", "then:2"]])

    def test_region_selection_saves_page_and_frac_only(self):
        body = extract_js_fn("savePin")
        self.assertIn(
            "if(isRegion(d))body={page:d.page,frac:d.frac,note:note,quote:d.quote,pdf_build:d.pdf_build||undefined};",
            body,
        )
        self.assertIn("body.doc=d.doc||DOC||undefined;", body)
        self.assertIn("if(!o||!o.file)return out;", extract_js_fn("overlapsFor"))
        self.assertIn("#composer.region #c-levels", HTML)


def js_tooltips() -> str:
    """The viewer's tooltip table (`const T` in core.js) as the page declares it, for harnesses whose functions read T.x."""
    found = re.search(r"^const T=\{.*?^\};$", HTML, re.S | re.M)
    assert found is not None, "core.js no longer declares `const T={...};` at line start"
    return found.group(0)


def js_via_limits() -> str:
    """The location-confidence thresholds viaTag() reads (`const VIA_HIDE=...` in levels.js)."""
    found = re.search(r"^const VIA_HIDE=.*;$", HTML, re.M)
    assert found is not None, "levels.js no longer declares `const VIA_HIDE=...;` at line start"
    return found.group(0)


# ---------------------------------------------------------------- figure documents (docs/handbook/viewer.md §패널 정리, §상태 표현)
class FrontendFigure(unittest.TestCase):
    """Figure documents in the viewer (P1c): the map as a way of finding, the figure tab without rebuild, the element a
    pick chose (path, rungs, snapped box), what a figure pin saves, and where its mark goes. Pure functions run under
    node; wiring is read from the served source."""

    def node(self) -> None:
        """Skip the calling check when node is missing."""
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_a_figure_pick_under_90_percent_says_it_was_found_by_the_map(self):
        """A figure pick's badge says '지도로 찾음' and the map's hint in Korean and English; 90 % and up shows no
        badge, under 30 % the warning colour."""
        self.node()
        for lang, head in (
            ("ko", "지도로 찾음 · 일치 50% — 그림 지도에서 드래그와"),
            ("en", "Found by the figure map · 50% match — The figure map chose"),
        ):
            with self.subTest(lang=lang):
                js = "\n".join(
                    [
                        js_i18n(lang),
                        js_tooltips(),
                        js_via_limits(),
                        extract_js_fn("viaTag"),
                        "console.log(JSON.stringify([viaTag({via:'map',score:0.5}),viaTag({via:'map',score:0.95}),"
                        "viaTag({via:'map',score:0.2})]));",
                    ]
                )
                half, confident, weak = json.loads(run_node(js))
                self.assertTrue(half["tip"].startswith(head), half["tip"])
                self.assertFalse(half["low"])
                self.assertIsNone(confident)
                self.assertTrue(weak["low"])

    def test_rebuild_hides_by_document_kind_not_by_view_only(self):
        """Only a LaTeX document builds: the rebuild button and the rebuilt/redrawn wording follow META.kind and a
        document's kind, never view_only (a figure document is view_only:false and still has no rebuild)."""
        css = HTML[HTML.index("<style>") : HTML.index("</style>")]
        self.assertIn("body.no-rebuild #btn-rebuild{display:none}", css)
        # compact bars have no [PDF 재빌드]: the status line and the [⋯] row do it, and neither shows without a rebuild (UX spec §V8)
        self.assertIn("body.compact #btn-rebuild{display:none}", css)
        self.assertIn("body.compact:not(.no-rebuild) #m-rebuild{display:flex}", css)
        self.assertIn("canRebuild:!!META&&buildsFromSource(META.kind)&&!isViewer()", extract_js_fn("statusInput"))
        self.assertNotIn("body.view-only", css)
        self.assertIn(
            "document.body.classList.toggle('no-rebuild',!buildsFromSource(META.kind))", extract_js_fn("drawMeta")
        )
        for fn in ("drawMeta", "pollBuildOnce", "noteOtherDocs"):
            with self.subTest(fn=fn):
                self.assertNotIn("view_only", extract_js_fn(fn))
                self.assertIn("buildsFromSource(", extract_js_fn(fn))
        self.assertIn(
            "isFigureKind(d.kind)?' · '+tr('그림 문서(드래그하면 요소와 그 요소를 그린 코드 줄을 찾습니다)'):''",
            extract_js_fn("docTip"),
        )

    def test_the_empty_hint_and_the_commit_tooltip_hold_for_every_document_kind(self):
        """The first-use hint promises 'source line numbers' and the header's commit tooltip speaks of 'the source', not
        of a .tex file or a manuscript, since a figure document or a view-only PDF is opened with the same text; each has
        its English."""
        for text in (".tex 줄 번호", "원고 Git 커밋"):
            self.assertNotIn(text, HTML)
        for text, english in (
            ("<b>원문 줄 번호</b>", "source line number"),
            ("PDF를 만들 때의 소스 Git 커밋.", "The source's Git commit"),
        ):
            self.assertIn(text, HTML)
            self.assertTrue(any(english in v for v in UI_EN.values()), english)

    def test_the_document_kind_rules_are_asked_in_one_place_each(self):
        """'Is it a figure document' and 'is it rebuilt from source' are the two helpers isFigureKind and
        buildsFromSource, and no other code compares a kind with DOC_KIND.FIGURE or DOC_KIND.TEX. Both answer false for
        a kind the page does not know and for none."""
        self.node()
        self.assertEqual(len(re.findall(r"[=!]==\s*DOC_KIND\.FIGURE|DOC_KIND\.FIGURE\s*[=!]==", HTML)), 1)
        self.assertEqual(len(re.findall(r"[=!]==\s*DOC_KIND\.TEX|DOC_KIND\.TEX\s*[=!]==", HTML)), 1)
        js = "\n".join(
            [
                extract_js_fn("isFigureKind"),
                extract_js_fn("buildsFromSource"),
                "const K=['tex','pdf','figure','video',undefined,null];"
                "console.log(JSON.stringify(K.map(k=>[isFigureKind(k),buildsFromSource(k)])));",
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)),
            [[False, True], [False, False], [True, False], [False, False], [False, False], [False, False]],
        )

    def test_the_documents_list_marks_a_figure_and_keeps_the_pdf_mark(self):
        """The documents sheet marks a figure '그림' (English 'Figure'), keeps 'PDF' on a view-only PDF, and marks a
        LaTeX document with neither."""
        self.node()
        for lang, word, label in (("ko", "그림", "그림 문서"), ("en", "Figure", "Figure document")):
            with self.subTest(lang=lang):
                js = "\n".join(
                    [
                        js_i18n(lang),
                        js_esc(),
                        "let OPEN_ALL=[]; const DEFAULT_DOC='ms';",
                        extract_js_fn("pdoc"),
                        extract_js_fn("docCount"),
                        extract_js_fn("isFigureKind"),
                        js_markup(),
                        extract_js_fn("docBadge"),
                        "console.log(JSON.stringify([{key:'ms',kind:'tex',view_only:false},"
                        "{key:'fig',kind:'figure',view_only:false},{key:'rv',kind:'pdf',view_only:true}].map(d=>String(docBadge(d)))));",
                    ]
                )
                tex, fig, pdf = json.loads(run_node(js))
                self.assertNotIn("dfig", tex)
                self.assertNotIn("dvo", tex)
                self.assertIn('<span class="badge dfig" aria-label="%s">%s</span>' % (label, word), fig)
                self.assertNotIn("dvo", fig)
                self.assertIn('<span class="badge dvo" aria-label="보기 전용">PDF</span>', pdf)
                self.assertNotIn("dfig", pdf)

    def test_the_path_names_each_ancestor_by_its_rung_and_falls_back_to_the_id(self):
        """The location path is root first, named by the rung that carries each id; an ancestor with no rung of its own
        (merged into the inner rung, past the cap, drawn in another file) is written as its id, and a region answer names
        its element itself."""
        self.node()
        js = "\n".join(
            [extract_js_fn("elName"), extract_js_fn("elPathText")]
            + [
                r"""
            const cell={id:'B2/c/m07',path:['B2','B2/c','B2/c/m07'],label:'7월'},root={id:'B2',path:['B2']};
            const full=[{level:'el',lo:24,hi:26,label:'7월',el:cell},{level:'el2',lo:20,hi:30,label:'달력',el:{id:'B2/c',path:['B2','B2/c']}},
                        {level:'fig',lo:1,hi:40,label:'B2',el:root}];
            const merged=[{level:'el',lo:20,hi:30,label:'7월',merged:['el2'],el:cell},{level:'fig',lo:1,hi:40,label:'B2',el:root}];
            const box={id:'B9/x',path:['B9','B9/x'],part:'Box'};
            console.log(JSON.stringify([elPathText({levels:full,el:cell,elSel:cell}),elPathText({levels:full,el:cell,elSel:full[1].el}),
              elPathText({levels:merged,el:cell,elSel:cell}),elPathText({levels:[],el:box,elSel:box}),elPathText({levels:[],elSel:null})]));"""
            ]
        )
        self.assertEqual(json.loads(run_node(js)), ["B2 › 달력 › 7월", "B2 › 달력", "B2 › B2/c › 7월", "B9 › Box", ""])

    def test_figure_rungs_are_named_by_their_element_with_a_line_count(self):
        """A figure rung's segment reads its element's name and line count (derived when the rung has no n); its
        tooltip says the element's lines, or the whole figure's for the root."""
        self.node()
        js = "\n".join(
            [js_esc(), js_markup(), js_tooltips()]
            + [
                extract_js_fn(n)
                for n in (
                    "lvOf",
                    "curLevel",
                    "rng",
                    "levelLabel",
                    "elName",
                    "levelName",
                    "rungLines",
                    "rungTip",
                    "levelBtns",
                )
            ]
            + [
                r"""
            const o={lo:24,hi:26,scope:'el',levels:[
              {level:'el',lo:24,hi:26,label:'7월',snippet:'',el:{id:'B2/c/m07',path:['B2','B2/c','B2/c/m07']}},
              {level:'el2',lo:20,hi:30,n:11,label:'달력',snippet:'',el:{id:'B2/c',path:['B2','B2/c']}},
              {level:'fig',lo:1,hi:40,label:'B2',snippet:'',el:{id:'B2',path:['B2']}}]};
            const re=/data-level="([^"]+)" aria-pressed="([^"]+)"[^>]*data-tip="([^"]*)">([^<]*)<span class="k[^"]*">· ([^<]*)</g;
            console.log(JSON.stringify([...html`${levelBtns(o,false)}`.text.matchAll(re)].map(m=>[m[1],m[2],m[3],m[4].trim(),m[5]])));"""
            ]
        )
        el = "이 요소를 그린 코드 줄입니다. 대기 상자가 그림의 이 요소에 맞춰집니다"
        self.assertEqual(
            json.loads(run_node(js)),
            [
                ["el", "true", "L24-L26 · " + el, "7월", "3줄"],
                ["el2", "false", "L20-L30 · " + el, "달력", "11줄"],
                ["fig", "false", "L1-L40 · 그림 전체를 그린 코드 줄입니다", "B2", "40줄"],
            ],
        )

    def test_the_element_line_names_the_path_and_the_box_snaps_only_to_a_real_box(self):
        """renderElement shows '#c-path' with the path and the element id as its tip, and snaps the pending box to the
        element's frac; an element without a box (or with a null frac) keeps the dragged box, no element hides the
        line, no box is no error."""
        self.node()
        js = "\n".join(
            [extract_js_fn(n) for n in ("isFrac", "elName", "elPathText", "drawBox", "snapBox", "renderElement")]
            + [
                r"""
            function pendingBadgeSide(){}   // the badge's side needs the page on screen (markBadgeRoom); not this test's
            const nodes={'#c-path':{hidden:true,textContent:'',dataset:{}}}; const $=s=>nodes[s];
            const vals=b=>['left','top','width','height'].map(k=>parseFloat(b.style[k]));
            const cell={id:'B2/c/m07',path:['B2','B2/c','B2/c/m07'],label:'7월',frac:[0.47,0.18,0.07,0.12]};
            const levels=[{level:'el',lo:24,hi:26,label:'7월',el:cell},{level:'el2',lo:20,hi:30,label:'달력',el:{id:'B2/c',path:['B2','B2/c']}},
                          {level:'fig',lo:1,hi:40,label:'B2',el:{id:'B2',path:['B2']}}];
            const line=nodes['#c-path'],out=[];
            const box={style:{left:'48%',top:'20%',width:'4%',height:'8%'}};
            renderElement({levels,el:cell,elSel:cell},box); out.push([line.hidden,line.textContent,line.dataset.tip,vals(box)]);
            const drag={style:{left:'48%',top:'20%',width:'4%',height:'8%'}};
            renderElement({levels,el:cell,elSel:levels[1].el},drag); out.push([line.textContent,vals(drag)]);
            renderElement({file:'/m.tex',elSel:null},drag); out.push([line.hidden,vals(drag)]);
            renderElement({levels,el:cell,elSel:cell},null); out.push(line.hidden);
            const nul={id:'n',path:['n'],frac:null}; renderElement({levels:[],el:nul,elSel:nul},drag); out.push(vals(drag));
            console.log(JSON.stringify(out));"""
            ]
        )
        snapped, strip, none, boxless, null_frac = json.loads(run_node(js))
        self.assertEqual(snapped[:3], [False, "B2 › 달력 › 7월 ·", "요소 B2/c/m07"])
        for got, want in zip(snapped[3], (47, 18, 7, 12), strict=True):
            self.assertAlmostEqual(got, want, places=6)
        self.assertEqual(strip, ["B2 › 달력 ·", [48, 20, 4, 8]])
        self.assertEqual(none, [True, [48, 20, 4, 8]])
        self.assertFalse(boxless)
        self.assertEqual(null_frac, [48, 20, 4, 8])

    def test_a_rung_switch_selects_its_element_and_lines_set_by_hand_keep_it(self):
        """useLevel moves the selection to the rung's lines and element; lines set in the excerpt (setLines) are manual but
        keep the element; a rung without an element (a LaTeX rung) leaves the element as it was."""
        self.node()
        js = "\n".join(
            [extract_js_fn("lvOf"), extract_js_fn("useLevel"), extract_js_fn("setLines")]
            + [
                r"""
            const cell={id:'c'},strip={id:'s'};
            const o={lo:24,hi:26,n_lines:40,elSel:cell,levels:[{level:'el',lo:24,hi:26,snippet:'a',el:cell},
              {level:'el2',lo:20,hi:30,snippet:'b',el:strip},{level:'raw',lo:5,hi:5,snippet:'r'}]};
            const out=[]; useLevel(o,'el2'); out.push([o.scope,o.lo,o.hi,o.elSel.id]);
            setLines(o,o.lo-1,o.hi); out.push([o.scope,o.lo,o.elSel.id]);
            useLevel(o,'raw'); out.push([o.scope,o.elSel.id]);
            console.log(JSON.stringify(out));"""
            ]
        )
        self.assertEqual(json.loads(run_node(js)), [["el2", 20, 30, "s"], ["lines", 19, "s"], ["raw", "s"]])

    def test_the_composer_shows_the_element_from_the_pick_without_asking_again(self):
        """The location line has a path slot before the lines; both composer branches draw the element; a pick selects
        its element, a rung its rung's; the element code sends no request; figure.js sits between the ladder and the
        composer parts."""
        self.assertIn('<div class="c-loc-main"><span id="c-path" hidden></span><span id="c-loc"', HTML)
        for fn in ("renderComposer", "renderRegionComposer"):
            self.assertIn("renderElement(d,COMPOSE.box)", extract_js_fn(fn), fn)
        self.assertIn("sel.elSel=d.el||null;", extract_js_fn("pick"))
        self.assertIn("if(lv.el)o.elSel=lv.el;", extract_js_fn("useLevel"))
        for fn in ("elPathText", "snapBox", "renderElement"):
            self.assertNotIn("api(", extract_js_fn(fn), fn)
        parts = (PKG / "viewer" / "parts.txt").read_text(encoding="utf-8")
        self.assertLess(parts.index("js/levels.js"), parts.index("js/figure.js"))
        self.assertLess(parts.index("js/figure.js"), parts.index("js/composer.js"))

    def test_a_figure_region_is_named_by_what_the_map_found_and_a_view_only_region_keeps_its_name(self):
        """figRegionBadge: an element without code lines reads '코드 없는 요소', a figure region without an element
        (map unreadable) reads '영역', each with its own tooltip; off a figure document without an element there is no
        figure badge, so the caller's '보기 전용' stays."""
        self.node()
        js = "\n".join(
            [
                js_i18n("ko"),
                js_tooltips(),
                extract_js_fn("figRegionBadge"),
                "console.log(JSON.stringify([figRegionBadge({id:'x',path:['x']},true),figRegionBadge(null,true),"
                "figRegionBadge(null,false)]));",
            ]
        )
        with_el, figure, off = json.loads(run_node(js))
        self.assertEqual(with_el["t"], "코드 없는 요소")
        self.assertIn("이 요소를 그린 코드 줄을 찾지 못했습니다", with_el["tip"])
        self.assertEqual(figure["t"], "영역")
        self.assertIn("그림 지도를 읽지 못해", figure["tip"])
        self.assertIsNone(off)
        self.assertIn("figRegionBadge(d.el,", extract_js_fn("renderRegionComposer"))

    def test_a_figure_pins_mark_goes_to_its_element_and_otherwise_where_it_was_pinned(self):
        """pinPlace uses the server's mark on mark_page when both are well formed, else the pin's page and frac; elLost
        is true only for el_sync 'lost'."""
        self.node()
        js = "\n".join(
            [extract_js_fn(n) for n in ("isFrac", "hasMark", "pinPlace", "elLost")]
            + [
                r"""
            const P=[{page:1,frac:[0.1,0.1,0.1,0.1],mark:[0.55,0.2,0.07,0.12],mark_page:2,el_sync:'moved'},
                     {page:1,frac:[0.1,0.1,0.1,0.1],el_sync:'lost'},
                     {page:3,frac:[0.2,0.2,0.2,0.2]},
                     {page:1,frac:[0.1,0.1,0.1,0.1],mark:[0.5,0.5],mark_page:1},
                     {page:1,frac:[0.1,0.1,0.1,0.1],mark:[0.5,0.5,0.1,0.1],mark_page:0}];
            console.log(JSON.stringify(P.map(p=>[pinPlace(p),elLost(p)])));"""
            ]
        )
        pinned = {"page": 1, "frac": [0.1, 0.1, 0.1, 0.1]}
        self.assertEqual(
            json.loads(run_node(js)),
            [
                [{"page": 2, "frac": [0.55, 0.2, 0.07, 0.12]}, False],
                [pinned, True],
                [{"page": 3, "frac": [0.2, 0.2, 0.2, 0.2]}, False],
                [pinned, False],
                [pinned, False],
            ],
        )

    def test_a_lost_element_badge_reads_element_lost_in_both_languages(self):
        """The lost-element badge is the lost-line warning look with the text '요소 잃음' ('Element lost'); a moved or
        plain pin has none."""
        self.node()
        for lang, word in (("ko", "요소 잃음"), ("en", "Element lost")):
            with self.subTest(lang=lang):
                js = "\n".join(
                    [
                        js_i18n(lang),
                        js_esc(),
                        js_icons(),
                        js_tooltips(),
                        extract_js_fn("elLost"),
                        extract_js_fn("elLostTag"),
                        "console.log(JSON.stringify([String(elLostTag({el_sync:'lost'})),elLostTag({el_sync:'moved'}),elLostTag({})]));",
                    ]
                )
                tag, moved, plain = json.loads(run_node(js))
                self.assertIn(word, tag)
                self.assertIn('class="badge badge-warning"', tag)
                self.assertIn("ic-triangle-alert", tag)
                self.assertEqual((moved, plain), (None, None))

    def test_a_pin_that_loses_its_element_is_announced_once(self):
        """The list refresh announces '#N 요소를 잃었습니다' when an open pin's element becomes lost, not when it already
        was, and not for a move."""
        self.node()
        js = "\n".join(
            [
                r"""
            function who(a){return (a&&(a.name||a.login))||'';}
            const TOASTS=[]; function toast(m,k){TOASTS.push([m,k]);} function restorePin(){}
            const MY_ACTIONS=new Map();""",
                extract_js_fn("markMine"),
                extract_js_fn("consumeMine"),
                extract_js_fn("pinState"),
                extract_js_fn("diffToast"),
                r"""
            diffToast([{id:1,el_sync:'ok'},{id:2,el_sync:'lost'},{id:3}],[{id:1,el_sync:'lost'},{id:2,el_sync:'lost'},{id:3,el_sync:'moved'}],[]);
            console.log(JSON.stringify(TOASTS));""",
            ]
        )
        self.assertEqual(json.loads(run_node(js)), [["#1 요소를 잃었습니다", "warn"]])

    def test_marks_and_cards_place_a_figure_pin_where_its_element_is(self):
        """marks() and the card's page link use pinPlace; a placed mark is not dashed; a lost element marks the card and
        mark like a lost line; [보기] falls back to the mark's page; a figure region card is labelled by what the map
        found."""
        m = extract_js_fn("marks")
        self.assertIn("const at=pinPlace(p),el=document.getElementById('p'+at.page);", m)
        self.assertIn("if(!el||!isFrac(at.frac))return;", m)
        self.assertIn("const est=isEstimated(p)&&!hasMark(p),lost=p.stale||elLost(p);", m)
        c = extract_js_fn("card")
        # the open and the review card's N쪽, and compact's one head link '#N · L… · N쪽' (input diagnosis U5)
        self.assertEqual(c.count("{page:pinPlace(p).page}"), 1)  # one page label for both cards' links
        self.assertEqual(c.count("p.stale||elLost(p)?CARD_DOT.LOST"), 1)  # one status dot for both cards
        self.assertIn("const lostEl=elLostTag(p); if(lostEl)tags.push(lostEl);", c)
        self.assertIn("figRegionBadge(p.el,isFigureKind((docInfo(pdoc(p))||{}).kind))", c)
        self.assertIn("document.getElementById('p'+pinPlace(p).page)", extract_js_fn("jumpPin"))
        self.assertIn("p.el_sync===EL_SYNC.LOST", extract_js_fn("diffToast"))

    def test_a_pin_of_an_unknown_via_gets_a_neutral_hint_not_the_synctex_one(self):
        """A `via` this page does not know is named as it came ('찾은 방법: ...') with a hint that claims no method, in
        Korean and English; the three known methods keep their own hints."""
        self.node()
        for lang, head, neutral in (
            ("ko", "찾은 방법: ocr · 일치 50% — ", "이 화면이 알지 못하는 방법으로"),
            ("en", "Found by: ocr · 50% match — ", "This page does not know the method"),
        ):
            with self.subTest(lang=lang):
                js = "\n".join(
                    [
                        js_i18n(lang),
                        js_tooltips(),
                        js_via_limits(),
                        extract_js_fn("viaTag"),
                        "console.log(JSON.stringify([viaTag({via:'ocr',score:0.5}),viaTag({via:'synctex',score:0.5}),"
                        "viaTag({via:'text',score:0.5}),viaTag({via:'map',score:0.5})]));",
                    ]
                )
                unknown, *known = json.loads(run_node(js))
                self.assertTrue(unknown["tip"].startswith(head + neutral), unknown["tip"])
                self.assertNotIn("SyncTeX", unknown["tip"])
                self.assertEqual(len({k["tip"] for k in known} | {unknown["tip"]}), 4)

    def test_marks_draws_nothing_for_a_null_or_malformed_box_and_one_mark_for_a_good_one(self):
        """marks() itself run over pins whose box is null, has a non-number, is not four long or sits on a page that is
        not on screen draws nothing for them; a good pin beside them draws one mark, and a lost element is drawn at the
        pinned box. Nothing throws."""
        self.node()
        js = "\n".join(
            [
                r"""
            const DOC='d', DEFAULT_DOC='d', markBadgeSides=()=>{}; let PINS=[], REVIEW_ALL=[]; const drawn=[];
            const $$=()=>[]; const esc=s=>String(s);
            const page1={appendChild:m=>drawn.push([m.dataset.pin,m.className,m.style.left,m.style.width])};
            const document={getElementById:id=>id==='p1'?page1:null,
              createElement:()=>({dataset:{},style:{},className:'',set innerHTML(v){}})};""",
                js_markup(),
                js_i18n(),
                *[
                    extract_js_fn(n)
                    for n in (
                        "isFrac",
                        "hasMark",
                        "pinPlace",
                        "elLost",
                        "isEstimated",
                        "pinState",
                        "pdoc",
                        "marks",
                    )
                ],
                r"""
            const good=[0.1,0.2,0.3,0.4];
            PINS=[{id:1,page:1,frac:null},{id:2,page:1,frac:[0.1,'x',0.2,0.2]},{id:3,page:1,frac:[0.1,0.2,0.3]},
              {id:4,page:7,frac:good},{id:5,page:1,frac:null,mark:[NaN,0,0.1,0.1],mark_page:1,el_sync:'moved'},
              {id:6,page:1,frac:good},{id:7,page:1,frac:good,mark:null,mark_page:1,el_sync:'lost'},
              {id:8,page:1,frac:[0.9,0.9,0.05,0.05],mark:good,mark_page:1,el_sync:'moved'}];
            marks(); console.log(JSON.stringify(drawn));""",
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)),
            [
                ["6", "mark", "10%", "30%"],
                ["7", "mark st", "10%", "30%"],
                ["8", "mark", "10%", "30%"],
            ],  # dataset holds strings
        )

    def test_the_finished_build_toast_says_rebuilt_for_a_manuscript_and_redrawn_for_a_figure(self):
        """The toast after a finished build of the document on screen, and the one for another document's finished
        build, say 'PDF 재빌드 완료' for a LaTeX document and that the pages were redrawn for a figure or a view-only
        PDF, in Korean and English."""
        self.node()
        words = {
            "ko": {
                "tex": "PDF 재빌드 완료",
                "redrawn": "PDF가 바뀌어 쪽을 새로 그렸습니다",
                "other": "PDF 쪽을 새로 그렸습니다",
            },
            "en": {"tex": "PDF rebuilt", "redrawn": "The PDF changed, pages redrawn", "other": "PDF pages redrawn"},
        }
        for lang in ("ko", "en"):
            for kind in ("tex", "figure", "pdf"):
                with self.subTest(lang=lang, kind=kind):
                    js = "\n".join(
                        [
                            js_i18n(lang),
                            r"""
                        let DOC='a', SWITCHSEQ=1, META={kind:%s,pages:[1,2]}; const TOASTS=[]; let REPLY;
                        const BUILD={timer:null,error:null,lastSeq:0,booted:true,inflight:null};
                        const DOC_SEQ=new Map(), BUILD_ERR_BY=new Map(), META_BY=new Map();
                        const chip={hidden:false,textContent:''}, btn={disabled:false}; const $=s=>s==='#build-chip'?chip:btn;
                        const dq=u=>u; const pullSuffix=()=>''; const hideBuildErr=()=>{}; const showBuildErr=()=>{};
                        const api=async()=>REPLY; const refreshDoc=async()=>{};
                        const toast=(m,k)=>TOASTS.push([m,k]); const switchDoc=()=>{}; const drawDocTabs=()=>{};
                        const DOCS=[{key:'b',name:'Fig B',kind:%s}]; const docInfo=k=>DOCS.find(d=>d.key===k)||null;"""
                            % (json.dumps(kind), json.dumps(kind)),
                            *[extract_js_fn(n) for n in ("buildsFromSource", "pollBuildOnce", "noteOtherDocs")],
                            r"""
                        (async()=>{
                          REPLY={data:{state:'ok',seq:1,elapsed_s:3}}; await pollBuildOnce();
                          DOC_SEQ.set('b',1); noteOtherDocs([{key:'b',build_seq:2,last_state:'ok'}]);
                          console.log(JSON.stringify(TOASTS.map(t=>t[0])));})();""",
                        ]
                    )
                    on_screen, other = json.loads(run_node(js))
                    w = words[lang]
                    self.assertTrue(on_screen.startswith(w["tex"] if kind == "tex" else w["redrawn"]), on_screen)
                    self.assertIn(w["tex"] if kind == "tex" else w["other"], other)

    def test_a_region_pin_is_located_by_the_page_its_mark_is_on_now(self):
        """locCopy (the copy text) and arcLoc (an archive row) name a region pin's page by pinPlace: the page its
        element's mark is on in the current build, else the page it was pinned on. Lines are untouched."""
        self.node()
        js = "\n".join(
            [
                js_esc(),
                js_markup(),
                js_tooltips(),
                *[extract_js_fn(n) for n in ("isFrac", "hasMark", "pinPlace", "isRegion", "locCopy", "rng", "arcLoc")],
                r"""
            const moved={kind:'region',pdf:'fig.pdf',name:'fig.pdf',page:1,frac:[0.1,0.1,0.2,0.2],mark:[0.3,0.4,0.1,0.05],mark_page:2};
            const home={kind:'region',pdf:'fig.pdf',name:'fig.pdf',page:1,frac:[0.1,0.1,0.2,0.2]};
            const lines={file:'a.py',name:'a.py',page:3,lo:4,hi:6,mark:[0.3,0.4,0.1,0.05],mark_page:2};
            const loc=h=>[/data-copy="([^"]*)"/.exec(h)[1],/>([^<]*)<\/span>$/.exec(h)[1]];
            console.log(JSON.stringify([locCopy(moved),locCopy(home),locCopy(lines),loc(String(arcLoc(moved))),loc(String(arcLoc(home))),loc(String(arcLoc(lines)))]));""",
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)),
            [
                "fig.pdf 쪽 2",
                "fig.pdf 쪽 1",
                "a.py L4-L6",
                ["fig.pdf 쪽 2", "쪽 2 영역"],
                ["fig.pdf 쪽 1", "쪽 1 영역"],
                ["a.py L4-L6", "L4-L6"],
            ],
        )

    def test_null_boxes_and_a_null_claim_end_draw_nothing_and_claim_nothing(self):
        """Whole-field null from the API (a stored non-finite frac, el.frac or claim_until reads null): a pin with a null
        frac and no mark gets a place marks() skips, a mark that is not a box is no mark, a figure pick whose element box
        is null saves el without frac and keeps the body's frac, a null claim_until is no active claim, and a hand-edited
        list that is not four numbers is no box either."""
        self.node()
        js = "\n".join(
            [extract_js_fn(n) for n in ("isFrac", "hasMark", "pinPlace", "elForSave", "figureFields", "claimActive")]
            + [
                r"""
            const b=figureFields({frac:[0.1,0.1,0.2,0.2]},{id:'x',path:['x'],frac:null},null);
            console.log(JSON.stringify([isFrac(pinPlace({page:1,frac:null,el:{id:'x',path:['x'],frac:null}}).frac),
              hasMark({mark:null,mark_page:1}),b,claimActive({claim_until:null}),
              isFrac(pinPlace({page:1,frac:[0.1,'x',0.2,0.2]}).frac)]));"""
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)),
            [False, False, {"frac": [0.1, 0.1, 0.2, 0.2], "el": {"id": "x", "path": ["x"]}}, False, False],
        )

    def test_figure_fields_send_the_element_with_its_box_and_the_box_as_frac(self):
        """A pin body gets el with the record's fields only (id, path, label, part, impl, frac - no unknown keys), the
        element's box as its own frac too, and the element's kind when the range is that element's rung; nudged lines
        keep the body's kind; a pick without an element is untouched."""
        self.node()
        js = "\n".join(
            [extract_js_fn(n) for n in ("isFrac", "elForSave", "elKind", "figureFields")]
            + [
                r"""
            const cell={id:'B2/c/m07',path:['B2','B2/c','B2/c/m07'],label:'7월',part:'MonthCell',
              impl:{file:'lib/components.py',lo:1,hi:5,extra:1},frac:[0.47,0.18,0.07,0.12],unknown:'x'};
            const root={id:'B2',path:['B2'],frac:[0,0,1,1]};
            console.log(JSON.stringify([
              figureFields({frac:[0.48,0.2,0.04,0.08],kind:'lines'},cell,{el:cell}),
              figureFields({frac:[0.48,0.2,0.04,0.08],kind:'lines'},cell,null),
              figureFields({frac:[0.1,0.1,0.1,0.1]},{id:'x',path:['B2','x']},null),
              figureFields({kind:'lines'},root,{el:root}),
              figureFields({kind:'paragraph'},null,null)]));"""
            ]
        )
        cell = {
            "id": "B2/c/m07",
            "path": ["B2", "B2/c", "B2/c/m07"],
            "label": "7월",
            "part": "MonthCell",
            "impl": {"file": "lib/components.py", "lo": 1, "hi": 5},
            "frac": [0.47, 0.18, 0.07, 0.12],
        }
        got = json.loads(run_node(js))
        self.assertEqual(
            got,
            [
                {"frac": [0.47, 0.18, 0.07, 0.12], "kind": "el:MonthCell", "el": cell},
                {"frac": [0.47, 0.18, 0.07, 0.12], "kind": "lines", "el": cell},
                {"frac": [0.1, 0.1, 0.1, 0.1], "el": {"id": "x", "path": ["B2", "x"]}},
                {"kind": "figure", "el": {"id": "B2", "path": ["B2"], "frac": [0, 0, 1, 1]}, "frac": [0, 0, 1, 1]},
                {"kind": "paragraph"},
            ],
        )
        self.assertEqual(list(got[0]["el"]), ["id", "path", "label", "part", "impl", "frac"])  # the record's key order

    def test_a_null_element_box_is_kept_out_of_the_saved_el_and_the_pins_frac(self):
        """An element whose frac is null (the whole-field null of P1b) or has a non-finite entry sends its id and path
        without a box and leaves the body's own frac alone."""
        self.node()
        js = "\n".join(
            [extract_js_fn(n) for n in ("isFrac", "elForSave", "elKind", "figureFields")]
            + [
                r"""
            const out=[];
            for(const f of [null,[0.1,0.2,null,0.4],[0.1,0.2,0.3],'x'])
              out.push(figureFields({frac:[0.5,0.5,0.1,0.1]},{id:'x',path:['B2','x'],part:'P',frac:f},{el:{path:['B2','x'],part:'P'}}));
            console.log(JSON.stringify(out));"""
            ]
        )
        want = {"frac": [0.5, 0.5, 0.1, 0.1], "kind": "el:P", "el": {"id": "x", "path": ["B2", "x"], "part": "P"}}
        self.assertEqual(json.loads(run_node(js)), [want] * 4)

    def test_el_kind_names_elements_like_the_server(self):
        """The viewer's elKind() and the server's limn.builds.figure_map.element_kind() name the same elements the same
        way: 'figure' for a page's root (with or without a part), 'el:<part>' below it with the part cut to 77
        characters, 'el:?' without a part."""
        self.node()
        src = figure_map.SourceRef(file="B2_calendar.py", lo=1, hi=40)

        def element(eid: str, parent: str | None, part: str | None, label: str | None) -> figure_map.MapElement:
            """A map element of the parity cases at a fixed box with the given names."""
            return figure_map.MapElement(
                id=eid, parent=parent, frac=(0.1, 0.1, 0.2, 0.2), src=src, impl=None, part=part, label=label
            )

        cases = [
            (element("B2", None, None, None), True, {"id": "B2", "path": ["B2"]}),
            (element("B2", None, "Figure", "그림"), True, {"id": "B2", "path": ["B2"], "part": "Figure"}),
            (
                element("B2/c", "B2", "CalendarStrip", "달력"),
                False,
                {"id": "B2/c", "path": ["B2", "B2/c"], "part": "CalendarStrip"},
            ),
            (element("B2/c/x", "B2/c", None, "7월"), False, {"id": "B2/c/x", "path": ["B2", "B2/c", "B2/c/x"]}),
            (
                element("B2/c/y", "B2/c", "P" * 100, None),
                False,
                {"id": "B2/c/y", "path": ["B2", "B2/c", "B2/c/y"], "part": "P" * 100},
            ),
        ]
        js = extract_js_fn("elKind") + "\nconsole.log(JSON.stringify(%s.map(elKind)));" % json.dumps(
            [c[2] for c in cases], ensure_ascii=False
        )
        self.assertEqual(json.loads(run_node(js)), [figure_map.element_kind(e, root) for e, root, _ in cases])

    def test_saving_and_re_placing_send_the_figure_element(self):
        """savePin adds the figure fields after the region shape is chosen; a re-place adds them to its loc and snaps
        its '새 위치' box to the candidate's element; the edit card keeps the pin's element (and follows it after a
        re-place or a 409) and sends a range only when the lines changed."""
        save = extract_js_fn("savePin")
        region = (
            "if(isRegion(d))body={page:d.page,frac:d.frac,note:note,quote:d.quote,pdf_build:d.pdf_build||undefined};"
        )
        self.assertLess(save.index(region), save.index("figureFields(body,d.elSel,isRegion(d)?null:figRung(d));"))
        rp = extract_js_fn("applyRepick")
        self.assertLess(
            rp.index("if(isRegion(c))loc="), rp.index("figureFields(loc,repickEl(c),isRegion(c)||!lv.el?null:lv);")
        )
        self.assertIn("snapBox(R.box,repickEl(c));", extract_js_fn("bannerCompare"))
        self.assertIn("region:!!EDITOR.current.region", extract_js_fn("startRepick"))
        self.assertIn("pinEl:p.el||null", extract_js_fn("openEdit"))
        self.assertIn("(!E.pinEl&&(E.scope||null)!==(E.orig.scope||null))", extract_js_fn("saveEdit"))
        self.assertIn("pinEl:p.el||null", extract_js_fn("applyRepick"))
        self.assertIn("E.pinEl=p.el||null;", extract_js_fn("saveEdit"))

    def test_a_re_place_candidate_of_the_other_shape_is_not_offered(self):
        """/edit never turns a line pin into a region pin or back, so a candidate of the other shape (a region answer for
        a line pin, lines for a region pin) is dropped and the banner asks for another drag with the reason; a candidate
        of the same shape gets [이 위치로 바꾸기]."""
        self.node()
        js = "\n".join(
            [js_tooltips(), js_esc(), js_markup()]
            + [
                extract_js_fn(n)
                for n in ("isRegion", "lvOf", "levelLabel", "isFrac", "drawBox", "snapBox", "repickEl", "bannerCompare")
            ]
            + [
                r"""
            const out=[]; let REPICK;
            function banner(h){out.push(/data-act="rp-apply"/.test(h)?'apply':'banner');}
            function bannerRepick(err){out.push(['again',err]);} function scopeLabel(){return '';}
            const region={kind:'region',page:1,frac:[0.2,0.2,0.1,0.1],pdf:'x.pdf',quote:''};
            const line={file:'/f.py',page:1,lo:20,hi:30,default_level:'el',
              levels:[{level:'el',lo:20,hi:30,label:'달력',el:{id:'B2/c',path:['B2','B2/c']}}]};
            for(const [fromRegion,cand] of [[false,region],[true,line],[false,line],[true,region]]){
              REPICK={id:7,from:{lo:24,hi:26,page:1,region:fromRegion},box:null,cand};
              bannerCompare(); out.push(REPICK.cand===null);}
            console.log(JSON.stringify(out));"""
            ]
        )
        shape = "이 자리는 지금 핀과 모양(줄/영역)이 달라 옮길 수 없습니다 — 다른 자리를 고르거나 새 핀을 남기세요"
        self.assertEqual(
            json.loads(run_node(js)),
            [["again", shape], True, ["again", shape], True, "apply", False, "apply", False],
        )


# ---------------------------------------------------------------- icons: Lucide only, no emoji/symbol glyphs
# Emoji/basic-character icons (⏳ ▾ ☾ ✎ etc.) looked ugly because they render differently per
# device/font (author feedback 2026-09-23). Icons only use inline SVG elements from Lucide
# (vendor/lucide/README.md). Arrows in prose (→) and key names (⌘) remain as plain characters.
ICON_GLYPHS = re.compile("[⏳⌛▲-◃◐-◓☀☼☾✓✔✎✏⚠⧉⋯＋×↵⊂∩★☆●○\U0001f000-\U0001ffff✀-➿️]")


def html_without_comments(h: str) -> str:
    h = re.sub(r"/\*.*?\*/", "", h, flags=re.S)
    return "\n".join(ln for ln in h.split("\n") if not ln.strip().startswith("//"))


class FrontendIcons(unittest.TestCase):
    """Check vendored icon provenance, SVG output, and coverage of every referenced icon."""

    VENDOR = PKG / "vendor" / "lucide"

    def test_vendor_license_and_readme_record_version_and_icons(self):
        lic = (self.VENDOR / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("ISC License", lic)
        self.assertIn("Lucide Icons and Contributors", lic)
        readme = (self.VENDOR / "README.md").read_text(encoding="utf-8")
        self.assertIn("lucide-static@%s" % viewer_assemble.LUCIDE_VERSION, readme)
        table = readme[readme.index("## Icons in use") : readme.index("## Updating")]
        names = set()
        for row in re.findall(r"^\| (`[^|]+) \|", table, flags=re.M):
            names |= set(re.findall(r"`([a-z0-9-]+)`", row))
        self.assertEqual(names, set(viewer_assemble.LUCIDE))

    def test_icon_markup_is_plain_svg_elements(self):
        for name, body in viewer_assemble.LUCIDE.items():
            els = re.findall(r"<[^>]+>", body)
            self.assertTrue(els, name)
            for el in els:
                self.assertRegex(
                    el, r'^<(path|circle|rect|line|polyline|polygon|ellipse)( [a-z-]+="[^"<>]*")+/>$', name
                )
        svg = viewer_assemble.icon_svg("check")
        for attr in (
            'viewBox="0 0 24 24"',
            'fill="none"',
            'stroke="currentColor"',
            'stroke-width="2"',
            'aria-hidden="true"',
        ):
            self.assertIn(attr, svg)

    def test_every_used_icon_exists_and_every_icon_is_used(self):
        h = HTML
        self.assertNotIn("{{ic:", h)
        self.assertNotIn("__LUCIDE_JSON__", h)
        used = set(re.findall(r"ic\('([a-z0-9-]+)'\)", h)) | set(re.findall(r'class="ic ic-([a-z0-9-]+)"', h))
        used |= set(re.findall(r"'(chevron-(?:up|down|left|right))'", h))
        self.assertEqual(used - set(viewer_assemble.LUCIDE), set())
        self.assertEqual(set(viewer_assemble.LUCIDE) - used, set())

    def test_no_emoji_or_symbol_glyph_icons_in_viewer(self):
        found = sorted(set(ICON_GLYPHS.findall(html_without_comments(HTML))))
        self.assertEqual(found, [])

    def test_js_ic_matches_server_icon_svg(self):
        if not shutil.which("node"):
            self.skipTest("node not available")
        js = (
            js_icons()
            + "\nconsole.log(JSON.stringify(['check','clock','x','nope'].map(n=>{const h=ic(n); return h instanceof Html&&h.text;})));"
        )
        self.assertEqual(
            json.loads(run_node(js)),
            [viewer_assemble.icon_svg("check"), viewer_assemble.icon_svg("clock"), viewer_assemble.icon_svg("x"), ""],
        )

    def test_toolbar_icon_buttons_keep_accessible_names(self):
        for bid, label in (
            ("btn-zoom-out", "축소"),
            ("btn-zoom-in", "확대"),
            ("btn-more", "더보기"),
            ("c-copy", "위치 복사"),
        ):
            tag = re.search(r'<button[^>]*id="%s"[^>]*>' % bid, HTML).group(0)
            self.assertIn('aria-label="%s"' % label, tag)


# ---------------------------------------------------------------- status stripe / archive (closed, dropped pins)
# expanding closed/dropped pins used to look identical to open cards, so the boundary between them was
# unclear (author feedback 2026-09-23). Now there's a full-width sticky section header after the open
# list ('완료 N ─── 펼치기'), and below it are flat, dimmed rows instead of cards. Status is distinguished
# via the card's left stripe color.
class FrontendArchive(unittest.TestCase):
    """Guard completed and discarded card content, reply controls, and archive summaries."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def run_rows(self, script: str):
        js = "\n".join(
            [
                js_esc(),
                r"""
            const T={loc:'l',reply:'y',restore:'s',purge:'u',n:'n',change:'c'}; let SHOW_ALL=false, DOCS=[], DOC='main', DEFAULT_DOC='main';
            function docInfo(){return null;} function authorTip(){return 'tip';} function who(a){return a?a.name:'';}
            """,
                js_icons(),
                extract_js_fn("rng"),
                extract_js_fn("multiDoc"),
                extract_js_fn("pdoc"),
                extract_js_fn("isRegion"),
                extract_js_fn("locCopy"),
                extract_js_fn("docChip"),
                "const ARC_OPEN=new Set(); let LAYOUT='wide', REPLY=null, META=null; const THREAD_OPEN=new Set(); function avatar(){return '';}",
                extract_js_fn("arcTime"),
                extract_js_fn("arcLoc"),
                extract_js_fn("arcLine"),
                js_thread(),
                "const TRASH_DAYS=30;",
                extract_js_fn("trashDaysLeft"),
                extract_js_fn("isOwner"),
                extract_js_fn("isViewer"),
                extract_js_fn("doneCard"),
                extract_js_fn("droppedCard"),
                script,
            ]
        )
        return json.loads(run_node(js))

    def test_done_row_is_flat_with_reply_line_and_hidden_original_request(self):
        out = self.run_rows(r"""
            const p={id:7,file:'/m.tex',name:'m.tex',lo:3,hi:5,page:2,done:true,done_at:'2026-09-23 20:40:11',
              closed_by:{name:'에이전트'},close_reply:'제목을 <b>바꿈</b>',close_ref:'PR #227',note:'원래 <메모>'};
            const a=String(doneCard(p)); ARC_OPEN.add('o:7'); ARC_OPEN.add('r:7'); const b=String(doneCard(p));
            console.log(JSON.stringify([/class="arc-row done"/.test(a), !/class="pin/.test(a), /ic-check/.test(a),
              /data-act="reply-open"[^>]*>답글</.test(a), /PR #227/.test(a), /class="rt arc-t" data-at="2026-09-23 20:40:11" data-tip="닫은 사람 에이전트 · 닫은 시각 2026-09-23 20:40:11">[^<]+</.test(a),
              /<span class="arc-reply" [^>]*>제목을 &lt;b&gt;바꿈&lt;\/b&gt;<\/span>/.test(a), /arc-orig"/.test(a), /원래 요청<\/button>/.test(a),
              /arc-reply open/.test(b), /class="arc-orig" translate="no"><b>원래 요청<\/b>원래 &lt;메모&gt;/.test(b)]));
            """)
        self.assertEqual(out, [True, True, True, True, True, True, True, False, True, True, True])

    def test_done_row_reply_opens_the_reply_box_in_the_thread(self):
        # observed bug (v0.2.0): [다시 열기] on a done row called /reopen directly without asking for a reason. v0.2.2 has no
        # [다시 열기] at all: the row's [답글] opens the same reply box as a card (openReply), slotted into .reply-slot inside the
        # expanded thread, and a person's reply reopens the pin by the server rule.
        out = self.run_rows(r"""
            const p={id:9,file:'/m.tex',name:'m.tex',lo:3,hi:5,page:2,done:true,done_at:'2026-09-23 20:40:11',
              closed_by:{name:'에이전트'},close_reply:'고침',thread:[{id:1,by:{name:'에이전트'},at:'2026-09-23 20:40:11',text:'고침',ev:'close'}]};
            const idle=String(doneCard(p));
            REPLY={id:9,el:null};
            const replying=String(doneCard(p));
            console.log(JSON.stringify([!/data-act="reopen"/.test(idle), !/rv-reopen/.test(idle), /data-act="reply-open"/.test(idle),
              /class="reply-slot"/.test(idle), /class="reply-slot"/.test(replying), /class="arc-thread"/.test(replying)]));
            """)
        self.assertEqual(out, [True, True, True, False, True, True])

    def test_thread_toggle_says_whether_the_thread_is_open(self):
        """A done row's [스레드 N] carries aria-expanded "false" while folded and "true" once open; it once read "null"
        when no reply box was open, which is no ARIA value."""
        out = self.run_rows(r"""
            const p={id:9,file:'/m.tex',name:'m.tex',lo:3,hi:5,page:2,done:true,done_at:'2026-09-23 20:40:11',
              thread:[{id:1,by:{name:'에이전트'},at:'2026-09-23 20:40:11',text:'고침',ev:'close'},{id:2,by:{name:'S'},at:'2026-09-23 20:41:00',text:'고마워요'}]};
            const state=()=>(/data-key="t:9" aria-expanded="([^"]*)"/.exec(String(doneCard(p)))||[])[1];
            const folded=state(); ARC_OPEN.add('t:9'); const open=state();
            console.log(JSON.stringify([folded,open]));
            """)
        self.assertEqual(out, ["false", "true"])

    def test_placeholder_ref_dash_is_hidden(self):
        # observed bug: when a QA script or an old caller put '-' in the ref slot, a meaningless reference like '닫음 · -' would show.
        out = self.run_rows(r"""
            const dash=String(doneCard({id:1,file:'/m.tex',name:'m.tex',lo:1,hi:1,page:1,done:true,done_at:'2026-09-23 08:05:00',close_ref:'-'}));
            const real=String(doneCard({id:2,file:'/m.tex',name:'m.tex',lo:1,hi:1,page:1,done:true,done_at:'2026-09-23 08:05:00',close_ref:'PR #9'}));
            const evDash=String(msgHtml({id:1,by:{name:'에이전트'},at:'2026-09-23 08:05:00',text:'답',ev:'close',ref:'-'}));
            const evReal=String(msgHtml({id:1,by:{name:'에이전트'},at:'2026-09-23 08:05:00',text:'답',ev:'close',ref:'abc1234'}));
            console.log(JSON.stringify([/arc-ref/.test(dash), /arc-ref/.test(real), /PR #9/.test(real),
              / · -</.test(evDash), evDash.includes(' · -'), evReal.includes(' · abc1234')]));
            """)
        self.assertEqual(out, [False, True, True, False, False, True])

    def test_done_row_without_reply_says_so_and_dropped_row_restores(self):
        out = self.run_rows(r"""
            const a=String(doneCard({id:3,file:'/m.tex',name:'m.tex',lo:1,hi:1,page:1,done:true,done_at:'2026-09-23 08:05:00'}));
            const d=String(droppedCard({id:4,file:'/m.tex',name:'m.tex',lo:2,hi:9,page:1,note:'잘못 찍음',dropped_at:'2026-09-23 09:00:00',dropped_by:{name:'김'}}));
            console.log(JSON.stringify([/설명 없이 닫힘/.test(a), /원래 요청/.test(a), /class="arc-row dropped"/.test(d), /ic-trash-2/.test(d),
              /data-act="restore"[^>]*>되살리기</.test(d), />잘못 찍음</.test(d), /L2-L9/.test(d), /data-act="reopen"/.test(d),
              /data-act="purge"/.test(d)]));
            """)
        # [영구 삭제] is the owner's only
        self.assertEqual(out, [True, False, True, True, True, True, True, False, False])

    def test_section_head_reads_label_count_and_fold_state(self):
        # One header component for open / awaiting review / done (v0.2.2): chevron, name, count, and 'new N' while collapsed.
        js = "\n".join(
            [
                js_icons(),
                js_esc(),
                r"""
            const els={}; function el(id,ctl){return els[id]=els[id]||{id,innerHTML:'',hidden:false,attrs:{'aria-controls':ctl},
              setAttribute(k,v){this.attrs[k]=v;},getAttribute(k){return this.attrs[k];}};}
            el('done-toggle','done-list'); el('done-list');
            const document={getElementById:id=>els[id]||null};
            const SEC_DEFAULT={open:true,review:true,done:false}; let SEC={open:true,review:true,done:false};
            const SEC_SEEN={open:null,review:null,done:new Set([1,2])}; const SEC_NAME_ID={open:'list-h',review:'review-h',done:'done-h'};
            """,
                extract_js_fn("secNewCount"),
                extract_js_fn("secHead"),
                r"""
            const strip=s=>s.replace(/<svg.*?<\/svg>/g,'').replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').trim();
            const out=[]; const b=els['done-toggle'];
            secHead('done','완료',[1,2,3],[1,2,3,4]); out.push([strip(b.innerHTML),b.attrs['aria-expanded'],els['done-list'].hidden,/ic-chevron-right/.test(b.innerHTML)]);
            SEC.done=true; secHead('done','완료',[1,2,3],[1,2,3,4]); out.push([strip(b.innerHTML),b.attrs['aria-expanded'],els['done-list'].hidden,/ic-chevron-down/.test(b.innerHTML)]);
            SEC.done=false; secHead('done','완료',[1,2,3,4,5],[1,2,3,4,5]); out.push([strip(b.innerHTML)]);
            console.log(JSON.stringify(out));""",
            ]
        )
        out = json.loads(run_node(js))
        self.assertEqual(out, [["완료 3 새 1", "false", True, True], ["완료 3", "true", False, True], ["완료 5 새 1"]])

    def test_sections_are_sticky_and_wired(self):
        h = HTML
        for sid in ("sec-open", "sec-review", "sec-done"):
            self.assertIn('id="%s"' % sid, h)
        self.assertNotIn('id="sec-dropped"', h)  # v0.2.2: deleted pins are in the Trash dialog
        css = h[h.index("<style>") : h.index("</style>")]
        self.assertRegex(css, r"\.sec-head\{position:sticky;top:var\(--stick-top,0px\)")
        # regression: revealList()'s scrollIntoView({block:'start'}) aligns this header's "sticky-uncorrected"
        # static position to the top of the viewport (0). Without scroll-margin-top, that static position
        # sits above the actual sticky-pinned position (stick-top), so the row right after the header (the
        # restore button) got hidden behind #bar1 (observed in touch QA). scroll-margin-top uses the same
        # --stick-top variable to keep the two aligned.
        self.assertRegex(css, r"button\.sec-tg\{[^}]*scroll-margin-top:var\(--stick-top,0px\)")
        self.assertIn("function stickTop()", h)
        self.assertIn("case 'arc-toggle':", h)
        body = extract_js_fn("drawPins")
        self.assertIn("secHead('done',tr('완료'),LDONE.map(p=>p.id),DONE_ALL.map(p=>p.id))", body)
        self.assertIn("secHead('review',tr('검토 대기'),LREV.map(p=>p.id),REVIEW_ALL.map(p=>p.id))", body)
        self.assertIn("LDONE.slice().reverse().map(doneCard)", body)
        # the same list functions (listDone/listDropped) are used for document switching and the "all documents" toggle too
        self.assertIn("const LIST=listOpen(),LDONE=listDone(),LDROP=listDropped();", body)

    def test_status_without_stripes_dot_badge_and_icons(self):
        # author feedback (2026-09-24): a left color stripe looks tacky. Status uses a dot in the card
        # header plus a badge with the same meaning; the archive uses a leading icon.
        css = HTML[HTML.index("<style>") : HTML.index("</style>")]
        for sel, decls in css_rules():
            if re.search(r"\.pin\b|\.arc-row|\.toast|#revision-pin|\.dm-item", sel):
                keys = [k for k, _ in decls]
                self.assertFalse([k for k in keys if k.startswith("border-left")], sel)
                self.assertNotIn("::before", sel.replace(".pin .n.go::before", ""))  # no overlaid stripe either
                for _k, v in decls:
                    self.assertNotRegex(v, r"inset \d+px 0 0", sel)  # no box-shadow-drawn stripe either
        self.assertNotIn(".strip{", css)
        for st in ("claimed", "review", "lost", "done", "dropped"):
            self.assertIn(".st-dot.%s{background:var(--status-" % st, css)
        self.assertEqual(css.count("--status-claimed:"), 2)  # both dark and light
        body = extract_js_fn("card")
        self.assertIn("${claimed?' claimed':''}", body)
        self.assertIn(
            "stDot(rv?CARD_DOT.REVIEW:p.stale||elLost(p)?CARD_DOT.LOST:claimed?CARD_DOT.CLAIMED:CARD_DOT.OPEN)", body
        )
        self.assertIn("tl('상태: {name}',{name:tr(ST_NAME[st])})", extract_js_fn("stDot"))
        self.assertIn('role="img" aria-label="${t}"', extract_js_fn("stDot"))  # not distinguished by color alone
        self.assertIn("${ic('rotate-ccw')}다시 열림", body)
        self.assertIn(".arc-row+.arc-row{border-top:1px solid var(--border)}", css)


class FrontendClaimEta(unittest.TestCase):
    """Exercise claim deadline rounding, elapsed labels, and local clock presentation."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def run_info(self, script: str, tz="Asia/Seoul"):
        js = "\n".join(
            [
                "function who(a){return a?a.name:'';}",
                extract_js_fn("ceil5"),
                extract_js_fn("hhmm"),
                extract_js_fn("claimInfo"),
                extract_js_fn("claimLabel"),
                script,
            ]
        )
        return json.loads(run_node(js, tz=tz))

    def test_estimate_rounds_up_to_five_minutes_and_clock(self):
        # viewed at 20:23:00 KST, expected completion 20:37:12 -> 14.2 minutes remaining becomes '약 15분', clock reads ~20:40.
        out = self.run_info(r"""
            const now=Date.parse('2026-09-23T20:23:00+09:00'), eta=Date.parse('2026-09-23T20:37:12+09:00')/1000;
            const p={claimed_by:{name:'A'},claim_ts:Date.parse('2026-09-23T20:20:00+09:00')/1000,eta_ts:eta,
                     claim_until:Date.parse('2026-09-23T22:20:00+09:00')/1000};
            const a=claimInfo(p,now), b=claimInfo(Object.assign({},p,{eta_ts:(now/1000)+3*60}),now);
            console.log(JSON.stringify([a.t,a.late,b.t,/잠금 자동 해제 22:20/.test(a.tip),/22:20/.test(a.t),/예상 완료 20:37/.test(a.tip)]));
            """)
        self.assertEqual(out, ["처리 중 · 약 15분 · 20:40쯤", False, "처리 중 · 약 5분 · 20:30쯤", True, False, True])

    def test_overrun_reports_late_by_five_minute_steps(self):
        out = self.run_info(r"""
            const now=Date.parse('2026-09-23T20:45:00+09:00')/1000;
            const p=o=>Object.assign({claimed_by:{name:'A'},claim_until:now+3600},o);
            console.log(JSON.stringify([claimInfo(p({eta_ts:now-30}),now*1000).t, claimInfo(p({eta_ts:now-7*60}),now*1000).t,
              claimInfo(p({eta_ts:now-30}),now*1000).late, claimLabel(p({eta_ts:now-10*60}),now*1000)]));
            """)
        self.assertEqual(out, ["예상보다 늦어짐 (+5분)", "예상보다 늦어짐 (+10분)", True, "예상보다 늦어짐 (+10분)"])

    def test_legacy_claim_without_eta_shows_start_and_elapsed(self):
        out = self.run_info(r"""
            const st=Date.parse('2026-09-23T20:02:00+09:00')/1000, now=(st+22*60+30)*1000;
            const a=claimInfo({claimed_by:{name:'A'},claim_ts:st,claim_until:st+480*60},now);
            const b=claimInfo({claimed_by:{name:'A'},claim_until:st+480*60},now);
            console.log(JSON.stringify([a.t, b.t, /04:02/.test(a.t), /잠금 자동 해제 04:02/.test(a.tip)]));
            """)
        self.assertEqual(out, ["처리 중 · 20:02부터 (23분째)", "처리 중", False, True])

    def test_clock_uses_viewer_local_time(self):
        js = r"""
            const now=Date.parse('2026-09-23T11:23:00Z'), eta=Date.parse('2026-09-23T11:37:12Z')/1000;
            console.log(JSON.stringify(claimInfo({claimed_by:{name:'A'},eta_ts:eta,claim_until:eta+600},now).t));
            """
        self.assertEqual(self.run_info(js, tz="Asia/Seoul"), "처리 중 · 약 15분 · 20:40쯤")
        self.assertEqual(self.run_info(js, tz="America/New_York"), "처리 중 · 약 15분 · 07:40쯤")

    def test_js_ceil5_matches_server(self):
        out = self.run_info("console.log(JSON.stringify([0,0.2,5,5.01,14.9,23].map(ceil5)));")
        self.assertEqual(out, [md_render.ceil5(m) for m in (0, 0.2, 5, 5.01, 14.9, 23)])

    def test_card_uses_claim_tag_and_ticker(self):
        self.assertIn("if(claimed)tags.push(claimTag(p));", extract_js_fn("card"))
        self.assertIn('data-claim="', extract_js_fn("claimTag"))
        self.assertIn("setInterval(tickClaims,30000);", HTML)
        self.assertNotIn("toLocaleTimeString", extract_js_fn("claimInfo"))


class FrontendToolbarOneRow(unittest.TestCase):
    """On a 1400px desktop (default 430px panel), the toolbar stays one row even with a long label
    ('Long-DemoPaper1') (measured live with Playwright, docs/handbook/viewer.md §디자인 토큰과 컴포넌트). [핀 다시 읽기]
    moved to the open-pin-list header, and lives inside [더보기] in compact mode."""

    def test_reload_lives_in_list_head_not_toolbar(self):
        bar = HTML[HTML.index('<div class="bar" id="bar1"') : HTML.index('<div class="bar" id="bar2"')]
        self.assertNotIn('id="btn-reload"', bar)
        head = HTML[HTML.index('<div class="sec-head">') : HTML.index('<div id="pins">')]
        self.assertRegex(
            head, r'<button id="btn-reload" class="sec btn-sm" data-act="reload" aria-label="핀 다시 읽기"'
        )

    def test_label_chip_truncates_and_tip_has_full_label(self):
        css = HTML[HTML.index("<style>") : HTML.index("</style>")]
        self.assertIn("#bar1 .chip{height:var(--control-h-sm);display:block;", css)
        self.assertIn("flex:0 1 auto;min-width:40px}", css)
        self.assertIn("text-overflow:ellipsis", re.search(r"\n\.chip\{[^}]*\}", css).group(0))
        # in compact, the label yields space first
        self.assertIn("body.compact #bar1 .chip{flex:0 50 auto;min-width:28px}", css)
        out = page_for("Long-DemoPaper1", "#1d4ed8")
        self.assertIn('data-tip="Long-DemoPaper1 — 이 창이 다루는 논문', out)

    def test_fold_closed_moves_label_into_more_and_keeps_doc_name(self):
        # on a folded fold device (344px), the label shrank to 'C…' and the document button to '본..', unreadable (2026-09-23).
        # The position button [본문 3/25 ▾] names the document only from 400px; where it does, the name is the one part that
        # shrinks, and the pages and chevron keep their width (UX spec §V4 폭 예산).
        css = HTML[HTML.index("<style>") : HTML.index("</style>")]
        self.assertIn("body.lay-narrow #bar1 .chip,body.lay-mid #bar1 .chip{display:none}", css)
        self.assertIn("#btn-pos .nm{flex:0 1 auto;min-width:0;", css)
        self.assertIn("#btn-pos b{flex:none;", css)
        # [더보기]'s label is no chip: the instance colour's dot and the name (translate="no"), no Limn icon (UX spec §V7)
        more = HTML[HTML.index('<dialog id="more"') : HTML.index("</dialog>", HTML.index('<dialog id="more"'))]
        label = more[more.index('<span id="more-label"') : more.index("</span>", more.index('<span id="more-label"'))]
        self.assertNotIn('class="chip"', label)
        self.assertNotIn("<svg", label)
        self.assertIn('<i class="more-dot" aria-hidden="true"></i><b translate="no">__LABEL__</b>', label)
        out = page_for("Long-DemoPaper1", "#1d4ed8")
        self.assertIn('<dialog id="more" tabindex="-1" aria-label="더보기 · Long-DemoPaper1">', out)
        self.assertIn("#more .more-dot{", css)
        self.assertIn("background:var(--brand)", css[css.index("#more .more-dot{") :][:200])

    def test_fold_open_also_hides_toolbar_chip_and_relies_on_more(self):
        # regression: an unfolded fold device (884px) also puts #bar1 under flex-wrap:nowrap pressure,
        # shrinking the label to 'CE-iTra…' (71px), unreadable (observed in touch QA). Same fix as narrow —
        # hide the toolbar chip and show the full name only via #more-label inside [더보기]. #more is
        # layout-condition-free shared markup, so it works as-is in mid too.
        css = HTML[HTML.index("<style>") : HTML.index("</style>")]
        self.assertIn("body.lay-narrow #bar1 .chip,body.lay-mid #bar1 .chip{display:none}", css)
        self.assertIn('id="btn-more" class="cmp btn-icon"', HTML)  # [더보기] is shared across compact (= mid/narrow)


class FrontendToolbarSize(unittest.TestCase):
    """Whether the toolbar's 쪽 (page) field matches the buttons' height/font size (desktop 28px, touch 44px). Measured live with Playwright."""

    def test_page_field_matches_toolbar_buttons(self):
        css = HTML[HTML.index("<style>") : HTML.index("</style>")]
        self.assertIn("#bar1{flex-wrap:wrap;gap:var(--space-1);padding:var(--space-2);--tb-h:var(--control-h)}", css)
        self.assertIn("--control-h:28px", css)
        self.assertIn("--control-h-touch:44px", css)
        self.assertIn("#bar1>button,#bar1>input{height:var(--tb-h)}", css)
        # the single-character '쪽' field used to read as a button (QA 2026-09-24) — now left-aligned like a real input, placeholder '쪽 이동'. Height/font size match the buttons.
        # basis 40px, growing first to 54px: the English toolbar ('Rebuild PDF') still fits one row (FrontendEnglishChrome)
        self.assertIn(
            "#bar1 input.n{width:54px;flex:100 1 40px;min-width:40px;max-width:54px;padding:0 var(--space-1);font-size:var(--text-base);",
            css,
        )
        self.assertIn("#bar1 button.btn-icon{padding:0;width:var(--tb-h);min-width:var(--tb-h)}", css)
        coarse = css[css.index("@media (pointer:coarse){") :]
        self.assertIn("#bar1{flex-wrap:wrap;--tb-h:var(--control-h-touch)}", coarse)
        self.assertIn("#bar1 input.n{width:84px;flex:0 0 84px;max-width:none;font-size:var(--text-xl)}", coarse)
        self.assertRegex(HTML, r'<input class="n sec" id="jump" placeholder="쪽 이동"')
        # [더보기] has no page field any more: the phone's navigation sheet and the nav bar's page count take it (UX spec §V7)
        self.assertRegex(HTML, r'<button id="nav-page" data-act="nav-page"')
        self.assertIn('<input id="ns-page-in" inputmode="numeric"', HTML)


class FrontendSaveWhilePicking(unittest.TestCase):
    """Save while picking (docs/handbook/viewer.md §패널 정리): clicking [핀 저장] right after a drag, before the
    SyncTeX pick finishes (~1.1s), used to find COMPOSE.current still unset, so savePin() silently did nothing and the note was lost (observed). It now
    queues that request and auto-saves once pick finishes. Verified both structurally (the old silent
    early return is gone) and behaviorally, by running the real savePin()/pick() source under node
    through queuing, auto-save, cancel-on-failure, and toggle-cancel."""

    def test_save_pin_no_longer_silently_drops_missing_cur(self):
        body = extract_js_fn("savePin")
        self.assertNotIn("if(!COMPOSE.current||COMPOSE.saving)return;", body)
        self.assertIn("if(COMPOSE.saving)return;", body)
        self.assertIn("if(!COMPOSE.current){if(COMPOSE.picking)togglePendingSave(); return;}", body)

    def test_pick_triggers_queued_save_on_success_and_clears_on_error(self):
        pick_body = extract_js_fn("pick")
        self.assertIn("if(COMPOSE.pendingSave){clearPendingSave(); savePin();}", pick_body)
        # the failure path (catch/d.error) also clears the pending save — it never saves silently.
        self.assertIn("clearPendingSave();", pick_body)
        self.assertRegex(
            pick_body,
            r"catch\(e\)\{if\(seq!==PICKSEQ\)return; setBusy\(false\); if\(!rp\)\{COMPOSE.picking=false; clearPendingSave\(\);\}",
        )

    def _harness(self, extra_body):
        stub = r"""
            const MQ_COARSE={matches:false}; const IS_MAC=false;
            function el(){return {hidden:true,textContent:'',innerHTML:'',value:'',dataset:{},
              scrollTop:0,disabled:false,classList:{toggle(){}},focus(){},remove(){}};}
            const els={}; const $=s=>(els[s]=els[s]||el());
            let PICKSEQ=0,REPICK=null; const COMPOSE={current:null,box:null,saving:false,picking:false,pendingSave:false,dismissedOverlap:null};
            let LAYOUT='wide', LAST_PTR='mouse', SNIP_OPEN=false, PINS=[], DOC=undefined, SWITCHSEQ=0; const EDITOR={current:null,saving:false};
            let KIND_NEW='fix'; function setKind(k){KIND_NEW=k==='question'?'question':'fix';} function mentionHints(){return [];}
            const ASSIGN_NEW={v:'agent',touched:false}; function renderAssignNew(){} function mentionPreview(){}
            function setBusy(){} function renderComposer(){} function overlapsFor(){return [];} function applySide(){}
            function selectionSnapshot(){return null;} function restoreSelection(){} let MID_OVERLAY=false; function relayout(){}
            function saveDraftSoon(){} function syncDraft(){} function savedDraftSnapshot(){return null;}
            function restoredDraftOwns(){return false;} function clearSavedDraft(){}
            async function loadPins(){} function useLevel(){} function isRegion(){return false;} function kindFor(){return 'line';}
            function figureFields(b){return b;} function figRung(){return null;}
            function banner(){} function bannerRepick(){} function bannerCompare(){} function revealBox(){}
            async function refreshDoc(){} function setSide(){} function setSelMode(){} function toast(){} function dropPin(){}
            const apiCalls=[]; let pickResolve=null, pickReject=null, pinResolve=null;
            function api(url){apiCalls.push(url);
              if(url==='/api/pick')return new Promise((res,rej)=>{pickResolve=res;pickReject=rej;});
              if(url==='/api/pin')return new Promise(res=>{pinResolve=res;});
              return Promise.resolve({data:{}});}
            """
        return "\n".join(
            [
                stub,
                js_esc(),
                js_markup(),
                extract_js_fn("captureVisit"),
                extract_js_fn("currentVisit"),
                extract_js_fn("saveBtnLabel"),
                extract_js_fn("togglePendingSave"),
                extract_js_fn("clearPendingSave"),
                extract_js_fn("composeOwns"),
                extract_js_fn("savePin"),
                extract_js_fn("cancelSelection"),
                extract_js_fn("pick"),
                extra_body,
            ]
        )

    def test_queued_save_fires_automatically_once_pick_resolves(self):
        js = self._harness(r"""
            (async()=>{
              const out={};
              const p = pick({page:1,x0:0,y0:0,x1:1,y1:1});
              await Promise.resolve(); await Promise.resolve();
              out.pickingWhileWaiting = COMPOSE.picking;
              savePin();   // 사용자가 pick 이 끝나기 전에 [핀 저장]을 누름
              out.queued = COMPOSE.pendingSave;
              out.btnPendingLabel = /위치 찾는 중.*저장 대기/.test(els['#btn-save'].innerHTML);
              out.pinCallsBeforeResolve = apiCalls.filter(u=>u==='/api/pin').length;
              pickResolve({data:{file:'/m.tex',name:'m.tex',lo:5,hi:5,raw_lo:5,raw_hi:5,page:1,
                default_level:null,overlaps:[],via:null,score:1,frac:0,quote:'',kind:'line'}});
              await p;
              out.autoSaved = COMPOSE.pendingSave===false;
              out.pinCallsAfterResolve = apiCalls.filter(u=>u==='/api/pin').length;
              out.curSetBeforeSave = !!COMPOSE.current || out.pinCallsAfterResolve>0;
              pinResolve({data:{id:42}});
              await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
              out.btnLabelRestored = els['#btn-save'].innerHTML===saveBtnLabel().text;
              console.log(JSON.stringify(out));
            })();
            """)
        out = run_node(js)
        if out is None:
            self.skipTest("node not available")
        data = json.loads(out)
        self.assertTrue(data["pickingWhileWaiting"])
        self.assertTrue(data["queued"])
        self.assertTrue(data["btnPendingLabel"])
        self.assertEqual(data["pinCallsBeforeResolve"], 0)  # no save request is sent before pick resolves
        self.assertTrue(data["autoSaved"])
        self.assertEqual(data["pinCallsAfterResolve"], 1)  # once pick resolves, the queued save fires automatically
        self.assertTrue(data["btnLabelRestored"])

    def test_pick_failure_clears_queued_save_without_saving(self):
        js = self._harness(r"""
            (async()=>{
              const out={};
              const p = pick({page:1,x0:0,y0:0,x1:1,y1:1});
              await Promise.resolve(); await Promise.resolve();
              savePin();
              out.queuedBeforeFailure = COMPOSE.pendingSave;
              pickResolve({data:{error:'못 찾음'}});
              await p;
              out.queuedAfterFailure = COMPOSE.pendingSave;
              out.pinCalls = apiCalls.filter(u=>u==='/api/pin').length;
              out.errorShown = els['#c-err'].hidden===false && els['#c-err'].textContent==='못 찾음';
              out.composerStillOpen = els['#composer'].hidden!==true || true;   // 실제 hidden 토글은 composer 표시측이 이미 맡는다
              console.log(JSON.stringify(out));
            })();
            """)
        out = run_node(js)
        if out is None:
            self.skipTest("node not available")
        data = json.loads(out)
        self.assertTrue(data["queuedBeforeFailure"])
        self.assertFalse(data["queuedAfterFailure"])
        self.assertEqual(data["pinCalls"], 0)  # nothing is saved if pick fails
        self.assertTrue(data["errorShown"])

    def test_clicking_save_again_cancels_the_queued_save(self):
        js = self._harness(r"""
            (async()=>{
              const out={};
              const p = pick({page:1,x0:0,y0:0,x1:1,y1:1});
              await Promise.resolve(); await Promise.resolve();
              savePin();
              out.queued = COMPOSE.pendingSave;
              savePin();   // 같은 버튼을 다시 누르면 대기를 취소(토글)
              out.canceled = COMPOSE.pendingSave===false;
              out.btnLabelRestored = els['#btn-save'].innerHTML===saveBtnLabel().text;
              pickResolve({data:{file:'/m.tex',name:'m.tex',lo:5,hi:5,raw_lo:5,raw_hi:5,page:1,
                default_level:null,overlaps:[],via:null,score:1,frac:0,quote:'',kind:'line'}});
              await p;
              out.noAutoSaveAfterCancel = apiCalls.filter(u=>u==='/api/pin').length===0;
              console.log(JSON.stringify(out));
            })();
            """)
        out = run_node(js)
        if out is None:
            self.skipTest("node not available")
        data = json.loads(out)
        self.assertTrue(data["queued"])
        self.assertTrue(data["canceled"])
        self.assertTrue(data["btnLabelRestored"])
        self.assertTrue(data["noAutoSaveAfterCancel"])

    def test_reselecting_during_pick_queues_save_for_new_location_not_stale_one(self):
        # regression: starting a new selection with a long-press while COMPOSE.current is already set (first selection
        # done), then clicking [핀 저장] before that response arrives, must not save the old COMPOSE.current right
        # away — it should go to the COMPOSE.pendingSave queue and save the new location instead.
        js = self._harness(r"""
            (async()=>{
              const out={};
              const p1 = pick({page:1,x0:0,y0:0.3,x1:1,y1:0.31});
              pickResolve({data:{file:'/m.tex',name:'m.tex',lo:717,hi:741,raw_lo:717,raw_hi:741,page:5,
                default_level:null,overlaps:[],via:null,score:1,frac:0,quote:'',kind:'line'}});
              await p1;
              out.curAfterFirstPick = COMPOSE.current && COMPOSE.current.lo;
              const p2 = pick({page:1,x0:0,y0:0.7,x1:1,y1:0.71});
              await Promise.resolve(); await Promise.resolve();
              out.curClearedOnNewPick = (COMPOSE.current===null);
              savePin();   // 스피너가 도는 동안(새 위치 응답 전) [핀 저장]을 누름
              out.pinCallsWhileWaiting = apiCalls.filter(u=>u==='/api/pin').length;
              out.queued = COMPOSE.pendingSave;
              pickResolve({data:{file:'/m.tex',name:'m.tex',lo:900,hi:920,raw_lo:900,raw_hi:920,page:5,
                default_level:null,overlaps:[],via:null,score:1,frac:0,quote:'',kind:'line'}});
              await p2;
              out.autoSaved = COMPOSE.pendingSave===false;
              out.pinCallsAfterSecondResolve = apiCalls.filter(u=>u==='/api/pin').length;
              console.log(JSON.stringify(out));
            })();
            """)
        out = run_node(js)
        if out is None:
            self.skipTest("node not available")
        data = json.loads(out)
        self.assertEqual(data["curAfterFirstPick"], 717)
        self.assertTrue(data["curClearedOnNewPick"])
        # doesn't save with the old COMPOSE.current before the new response arrives
        self.assertEqual(data["pinCallsWhileWaiting"], 0)
        self.assertTrue(data["queued"])
        self.assertTrue(data["autoSaved"])
        # the queued save fires once the new location response arrives
        self.assertEqual(data["pinCallsAfterSecondResolve"], 1)


class FrontendResponsiveBrowser(ChromiumTestCase):
    """Real Chromium layout and keyboard regression; API/PDF rendering is outside this oracle.

    Run with: uv run pytest src/limn/viewer/tests/test_viewer.py -k FrontendResponsiveBrowser. Uses $LIMN_CHROMIUM, a system
    Chrome/Chromium, or Playwright's bundled Chromium (`playwright install chromium`), in that order. It skips
    when none can start, unless LIMN_TEST_REQUIRE_BROWSER=1 (CI), where that is a failure.
    """

    @classmethod
    def setUpClass(cls):
        """Start Chromium and build the viewer page (boot() off) once for the class."""
        super().setUpClass()
        cls.html = page_for("Long-DemoPaper1", "#2563eb").replace("\nboot();", "\n")

    def open_viewer(self, width, touch=False, preferences=None, height=900):
        """The viewer page (boot() off) at width x height, touch or mouse, with pinPrefs preferences and three blank pages."""
        context = self.browser.new_context(
            viewport={"width": width, "height": height}, is_mobile=touch, has_touch=touch
        )
        self.addCleanup(context.close)
        page = context.new_page()
        page.route(
            "**/*",
            lambda route: (
                route.fulfill(content_type="text/html", body=self.html)
                if route.request.url == "http://viewer.test/"
                else route.abort()
            ),
        )
        page.goto("http://viewer.test/")
        page.evaluate(
            """preferences => {
          localStorage.setItem('pinPrefs',JSON.stringify(preferences||{}));
          DOC='main';DEFAULT_DOC='main';
          DOCS=[{key:'main',name:'본문',path:'main.tex',n_pages:28},
                {key:'reply',name:'하이라이트',path:'reply.tex',n_pages:1},
                {key:'cover',name:'커버레터',path:'cover.tex',n_pages:1}];
          document.body.classList.add('docs-multi');
          applyTheme();applyLayout();applySideWidth();applyOutlineState();drawDocTabs();
          META={pages:[{}, {}, {}]};
          document.querySelector('#doc').innerHTML=[1,2,3].map(n=>
            '<div class="pg" id="p'+n+'" data-page="'+n+'" style="aspect-ratio:612/792;background:white"></div>').join('');
          relayout();
        }""",
            preferences,
        )
        return page

    def test_toggle_stays_in_place_without_overflow_for_mouse_and_touch(self):
        """The outline toggle keeps its place, focus and reading spot at every width, mouse and touch; outside wide it opens
        the outline overlay, which Escape and the pin panel close (touch 1180 is the side-panel band, not wide)."""
        for touch in (False, True):
            for width in (720, 820, 900, 1024, 1180, 1440):
                with self.subTest(width=width, touch=touch):
                    page = self.open_viewer(width, touch)
                    if touch:
                        page.evaluate("coach('touch','길게 누르면 문단을 고릅니다')")
                    self.assertEqual(page.evaluate("SIDE_OPEN"), width > 900)
                    toggle = page.locator("#nav-toc-toggle")
                    self.assertEqual(page.locator('[data-act="outline"]').count(), 1)
                    before = toggle.bounding_box()
                    was = toggle.get_attribute("aria-expanded")  # wide: open with a mouse, collapsed on touch
                    self.assertEqual(was, "true" if page.evaluate("LAYOUT") == "wide" and not touch else "false")
                    self.assertGreaterEqual(before["y"], 0)
                    page.evaluate("document.querySelector('#left').scrollTop=480")
                    anchor = page.evaluate("topAnchor()")
                    toggle.click()  # Coach is still visible during this real hit test.
                    after = toggle.bounding_box()
                    self.assertEqual((before["x"], before["y"]), (after["x"], after["y"]))
                    self.assertEqual(page.evaluate("document.activeElement.id"), "nav-toc-toggle")
                    current = page.evaluate("topAnchor()")
                    self.assertEqual(anchor["page"], current["page"])
                    self.assertAlmostEqual(anchor["frac"], current["frac"], delta=0.003)
                    self.assertGreaterEqual(page.locator("#pdf-center").bounding_box()["width"], 480)
                    self.assertFalse(page.evaluate("document.documentElement.scrollWidth>innerWidth"))
                    self.assertFalse(
                        page.evaluate(
                            "document.querySelector('#doc-nav').scrollWidth>document.querySelector('#doc-nav').clientWidth"
                        )
                    )
                    if page.evaluate("LAYOUT") != "wide":
                        self.assertEqual(toggle.get_attribute("aria-expanded"), "true")
                        self.assertFalse(page.evaluate("SIDE_OPEN"))
                        page.keyboard.press("Escape")
                        self.assertEqual(toggle.get_attribute("aria-expanded"), "false")
                        toggle.press("Enter")
                        page.locator("#btn-side").click()
                        self.assertEqual(toggle.get_attribute("aria-expanded"), "false")
                        self.assertTrue(page.evaluate("SIDE_OPEN"))
                    else:
                        self.assertNotEqual(toggle.get_attribute("aria-expanded"), was)
                        toggle.press("Enter")
                        self.assertEqual(toggle.get_attribute("aria-expanded"), was)

    def test_mid_action_bar_and_tabs_stay_put_when_panel_toggles(self):
        # regression (2026-09-24, Fold 7 user): in mid, [핀 N] used to jump between top-right (y 56) when
        # the panel opened and bottom-right (y 693) when it collapsed, and the document-side panel
        # (901-1099px) clipped the nav row by the panel width. The action row is now pinned full-width at
        # the bottom of the screen, the nav row full-width at the top, and the panel only expands between the two.
        probe = """() => {
          const r = s => document.querySelector(s).getBoundingClientRect();
          const hit = e => {const b=e.getBoundingClientRect(), p=e.closest('#doc-links'), q=p?p.getBoundingClientRect():b;
            if(b.right<=q.left||b.left>=q.right)return true;   // 가로로 밀려 난 링크는 스크롤 영역 밖이다
            const x=Math.max(q.left+2,Math.min(q.right-2,b.left+b.width/2)), h=document.elementFromPoint(x,b.top+b.height/2);
            return !!h&&(h===e||e.contains(h));};
          const ctl = [...document.querySelectorAll('#bar1 button,#doc-nav button')].filter(e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden');
          return {side:r('#btn-side'), bar:r('#bar1'), nav:r('#doc-nav'), right:r('#right'), open:SIDE_OPEN,
                  pos:getComputedStyle(document.querySelector('#bar1')).position,
                  blocked:ctl.filter(e=>!hit(e)).map(e=>e.id||e.textContent.trim()),
                  clipped:ctl.filter(e=>e.scrollWidth>e.clientWidth+1).map(e=>e.id||e.textContent.trim())};
        }"""
        # touch mid bands only: 844/884x700 the overlay, 968x900 and 1024x768 beside the document, 1180/1366 the U8 tablets
        # (720 and 820 at 900px high are portrait tablets now: the bottom sheet, TouchLayoutBands)
        for width, height in ((844, 700), (884, 700), (968, 900), (1024, 768), (1180, 820), (1366, 1024)):
            with self.subTest(width=width, height=height):
                page = self.open_viewer(width, True, height=height)
                a = page.evaluate(probe)
                page.locator("#btn-side").click()
                b = page.evaluate(probe)
                self.assertNotEqual(a["open"], b["open"])
                for s in (a, b):
                    self.assertEqual(s["pos"], "fixed")
                    self.assertEqual(
                        (s["bar"]["x"], s["bar"]["width"], s["bar"]["y"] + s["bar"]["height"]), (0, width, height)
                    )
                    self.assertEqual((s["nav"]["x"], s["nav"]["width"]), (0, width))
                    self.assertEqual(s["blocked"], [])
                    self.assertEqual(s["clipped"], [])
                    self.assertLess(s["side"]["x"] + s["side"]["width"], width)
                    # bottom-right corner (right thumb)
                    self.assertGreater(s["side"]["x"] + s["side"]["width"], width - 40)
                opened = a if a["open"] else b
                self.assertGreaterEqual(opened["right"]["y"], opened["nav"]["y"] + opened["nav"]["height"] - 1)
                self.assertLessEqual(opened["right"]["y"] + opened["right"]["height"], opened["bar"]["y"] + 1)
                for k in ("x", "y", "width", "height"):
                    self.assertAlmostEqual(a["side"][k], b["side"][k], delta=1)

    def test_overlay_defaults_follow_width_but_explicit_choice_and_draft_survive(self):
        page = self.open_viewer(820)
        self.assertFalse(page.evaluate("SIDE_OPEN"))
        page.set_viewport_size({"width": 1024, "height": 900})
        page.wait_for_function("SIDE_OPEN")
        page.set_viewport_size({"width": 820, "height": 900})
        page.wait_for_function("!SIDE_OPEN")
        page.locator("#btn-side").click()
        self.assertFalse(page.evaluate("prefs().midClosed"))
        page.set_viewport_size({"width": 1024, "height": 900})
        page.wait_for_function("!MID_OVERLAY")
        page.set_viewport_size({"width": 820, "height": 900})
        page.wait_for_function("MID_OVERLAY")
        self.assertTrue(page.evaluate("SIDE_OPEN"))
        page = self.open_viewer(1024)
        page.evaluate("document.querySelector('#composer').hidden=false")
        page.set_viewport_size({"width": 820, "height": 900})
        page.wait_for_function("MID_OVERLAY")
        self.assertTrue(page.evaluate("SIDE_OPEN"))

    def test_saved_widths_clamp_without_overwriting_and_mobile_keeps_sheet(self):
        """A saved width is clamped for the screen but never overwritten; Home goes to the minimum; the phone keeps its sheet."""
        page = self.open_viewer(1180, preferences={"side": 430})
        self.assertEqual(page.locator("#right").bounding_box()["width"], 430)
        page = self.open_viewer(1024, preferences={"sideMid": 600})
        self.assertGreaterEqual(page.locator("#pdf-center").bounding_box()["width"], 480)
        self.assertEqual(page.evaluate("prefs().sideMid"), 600)
        page.locator("#grip").focus()
        page.keyboard.press("Home")  # the window-splitter key for the panel's minimum (End is its maximum)
        self.assertEqual(page.locator("#right").bounding_box()["width"], 300)
        page = self.open_viewer(390, True)
        self.assertFalse(page.locator("#doc-nav").is_visible())
        self.assertTrue(page.locator("#btn-pos").is_visible())  # the phone's position button, documents or not
        self.assertFalse(page.evaluate("SIDE_OPEN"))
        page.locator("#btn-side").click()
        self.assertTrue(page.evaluate("SIDE_OPEN"))
        self.assertEqual(page.locator("#right").bounding_box()["width"], 390)
        page.locator("#btn-pos").click()
        self.assertTrue(page.locator("#nav-sheet").is_visible())


class FrontendThread(unittest.TestCase):
    """Guard thread previews, escaped messages, reply placement, and question card controls."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def run_js(self, script, layout="wide"):
        js = "\n".join(
            [
                js_esc(),
                r"""
            function who(a){return (a&&(a.name||a.login))||'';} function avatar(){return '<i class="av"></i>';}
            let LAYOUT='%s', REPLY=null, META=null; const THREAD_OPEN=new Set();
            """
                % layout,
                js_icons(),
                extract_js_fn("arcTime"),
                js_thread(),
                script,
            ]
        )
        return json.loads(run_node(js))

    def test_wide_shows_last_three_compact_shows_last_one(self):
        out = self.run_js(r"""
            const th=[1,2,3,4,5].map(i=>({id:i,by:{name:'S'},at:'2026-09-24 10:0'+i+':00',text:'m'+i}));
            const p={id:9,thread:th};
            const w=String(threadHtml(p,true)), c=String(threadHtml(p,false)); THREAD_OPEN.add(9); const all=String(threadHtml(p,false));
            const n=s=>(s.match(/class="msg"/g)||[]).length;
            console.log(JSON.stringify([n(w),/이전 2건 보기/.test(w),/m5/.test(w),/m2/.test(w),n(c),/이전 4건 보기/.test(c),/m5/.test(c),
              n(all),/스레드 접기/.test(all),String(threadHtml({id:1},true))]));
            """)
        self.assertEqual(out, [3, True, True, False, 1, True, True, 5, True, ""])

    def test_messages_escape_and_events_read_as_history(self):
        out = self.run_js(r"""
            const a=String(msgHtml({id:1,by:{name:'<b>x</b>'},at:'2026-09-24 10:00:00',text:'<img src=x onerror=1>'}));
            const b=String(msgHtml({id:2,by:{name:'로컬/에이전트'},at:'2026-09-24 10:05:00',text:'고쳤다',ev:'close',ref:'PR #9'}));
            const c=String(msgHtml({id:3,by:{name:'S'},at:'2026-09-24 10:06:00',text:'',ev:'confirm'}));
            console.log(JSON.stringify([/&lt;img/.test(a),!/<img/.test(a),/&lt;b&gt;x/.test(a),/class="msg ev ev-close"/.test(b),
              /닫음 · PR #9/.test(b),/>고쳤다</.test(b),/>확인</.test(c),!/msg-t/.test(c),/09-24 10:05/.test(b)]));
            """)
        self.assertEqual(out, [True] * 9)

    def test_reply_slot_rendered_for_open_editor(self):
        out = self.run_js(r"""
            REPLY={id:4,mode:'reply'};
            console.log(JSON.stringify([/reply-slot/.test(threadHtml({id:4},true)),String(threadHtml({id:5},true))]));
            """)
        self.assertEqual(out, [True, ""])

    def test_card_has_question_badge_reply_button_and_thread_count(self):
        body = extract_js_fn("card")
        self.assertIn("if(isQuestion(p))tags.unshift(", body)
        self.assertIn('data-act="reply-open"', body)
        self.assertIn("threadHtml(p,LAYOUT===LAYOUT_MODE.WIDE)", body)
        self.assertIn("ic('message-square')", body)

    def test_reply_editor_survives_redraw_and_save_sends_kind(self):
        """The reply box survives list redraws, Esc closes it first, and a save sends the pin kind."""
        dp = extract_js_fn("drawPins")
        self.assertIn("slot.replaceWith(REPLY.el)", dp)
        self.assertIn("rta.focus()", dp)
        self.assertIn("body.kind_req=KIND_NEW;", extract_js_fn("savePin"))
        self.assertIn("setKind(KIND_REQ.FIX)", extract_js_fn("cancelSelection"))
        self.assertIn("KIND_NEW===KIND_REQ.QUESTION?'무엇이 궁금한지 적어 주세요'", extract_js_fn("setKind"))
        self.assertIn("if(REPLY){e.preventDefault();closeReply();return;}", HTML)  # Esc closes the input field first
        self.assertIn('id="c-kind"', HTML)
        send = extract_js_fn("sendReply")
        # one path; the server decides
        self.assertIn("api('/api/pins/'+id+'/reply',{method:'POST',body,what:'답글',keepalive:true})", send)
        self.assertIn("body.reopen=R.toggle==='reopen'", send)  # the one override: [상태 유지] / [다시 열기]
        self.assertIn("deferred(", send)  # sent when the undo toast goes away

    def test_compact_collapsed_card_hides_thread(self):
        css = HTML[HTML.index("<style>") : HTML.index("</style>")]
        self.assertIn(
            "body.compact .pin:not(.open):not(.editing) :is(.tags,.au,.note,.acts,.head>.sp,.thread){display:none}", css
        )


class FrontendReview(unittest.TestCase):
    """Guard review card actions, reviewer hints, and review list notifications."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_review_card_suggests_author_and_offers_confirm_and_reply(self):
        js = "\n".join(
            [
                js_esc(),
                r"""
            const T={stale:'s',n:'n',loc:'l',view:'v',edit:'e',close:'c',drop:'d',review:'r',confirm:'k',reply:'y'};
            let  PINS=[], META={me:{login:'bob@example.com',name:'Bob Park'}}; const EDITOR={current:null,saving:false};
            const OPEN_CARDS=new Set();
            function viaTag(){return null;} function relBadge(){return null;} function claimActive(){return false;}
            function authorTip(){return 'tip';} function who(a){return a?(a.name||a.login):'';} function avatar(){return '';}
            let SHOW_ALL=false, DOCS=[], DOC='main', DEFAULT_DOC='main', LAYOUT='wide', REPLY=null; function docInfo(){return null;}
            const THREAD_OPEN=new Set();
            """,
                extract_js_fn("rng"),
                extract_js_fn("multiDoc"),
                extract_js_fn("pdoc"),
                extract_js_fn("isRegion"),
                extract_js_fn("locText"),
                extract_js_fn("locCopy"),
                extract_js_fn("docChip"),
                extract_js_fn("arcTime"),
                js_thread(),
                extract_js_fn("isFrac"),
                extract_js_fn("hasMark"),
                extract_js_fn("pinPlace"),
                extract_js_fn("elLost"),
                extract_js_fn("elLostTag"),
                extract_js_fn("figRegionBadge"),
                extract_js_fn("card"),
                extract_js_fn("cardActs"),  # the open card's action row (its visual order per layout)
                js_icons(),
                r"""
            const base={id:3,file:'/m.tex',name:'m.tex',lo:1,hi:2,page:1,note:'n',done:true,review:true,state:'review',
              closed_by:{login:'local',name:'로컬/에이전트'},thread:[{id:1,by:{name:'로컬/에이전트'},at:'2026-09-24 10:00:00',text:'고침',ev:'close'}]};
            const mine=String(card(Object.assign({},base,{author:{login:'bob@example.com',name:'Bob Park'}})));
            const other=String(card(Object.assign({},base,{author:{login:'w@example.com',name:'Wendy Kim'}})));
            const open=String(card({id:4,file:'/m.tex',name:'m.tex',lo:1,hi:2,page:1,note:'n'}));
            console.log(JSON.stringify([/class="pin card review/.test(mine),/내 확인 차례/.test(mine),/b-confirm btn-soft/.test(mine),
              /Wendy Kim님 확인 필요/.test(other),/class="btn-sm b-confirm"/.test(other),!/rv-reopen/.test(other)&&/data-act="reply-open"/.test(other),
              !/data-act="close"/.test(other),!/data-act="drop"/.test(other),/ev-close/.test(other),!/review/.test(open)]));
            """,
            ]
        )
        self.assertEqual(json.loads(run_node(js)), [True] * 10)

    def test_review_toast_and_partition(self):
        js = "\n".join(
            [
                r"""
            function who(a){return (a&&(a.name||a.login))||'';}
            const TOASTS=[]; function toast(m,k){TOASTS.push(m);} function restorePin(){}
            const MY_ACTIONS=new Map();
            """,
                extract_js_fn("markMine"),
                extract_js_fn("consumeMine"),
                extract_js_fn("pinState"),
                extract_js_fn("diffToast"),
                extract_js_fn("pinState"),
                extract_js_fn("reviewToast"),
                r"""
            diffToast([{id:1},{id:2}],[{id:1,done:true,review:true},{id:2,done:true}],[]);
            reviewToast([{id:5},{id:6},{id:7}],[{id:5,done:true,confirmed_by:{name:'W'}},{id:6,done:false},{id:7,done:true,review:true}]);
            markMine(8); reviewToast([{id:8}],[{id:8,done:true}]);
            console.log(JSON.stringify(TOASTS));
            """,
            ]
        )
        out = json.loads(run_node(js))
        self.assertEqual(
            out,
            [
                "#2 이 완료되었습니다",
                "#1 이 검토 대기로 넘어왔습니다 — 결과를 보고 [확인]하세요",
                "#5 확인됨 · W",
                "#6 다시 열림",
            ],
        )
        # The partition itself is exercised against legacy and document-scoped records in test_viewer_list.py.
        self.assertIn('id="sec-review"', HTML)
        self.assertIn('id="side-rv"', HTML)

    def test_review_card_reply_hint_says_what_a_reply_does(self):
        # observed bug (v0.2.0): a review card's reply field used the same hint text as a normal reply, so it wasn't clear what
        # a reply would do. v0.2.2: on a closed pin the placeholder says a reply reopens it, and the outcome line under the
        # box previews the server rule (FrontendReplyRule checks every row of helpers.RULE_CASES).
        body = extract_js_fn("replyEl")
        # from the same outcome as the line below
        self.assertIn('placeholder="${replyPlaceholder(p,isHuman(),false)}"', body)
        self.assertIn(
            "'무엇이 틀렸는지 적으면 다시 열려 에이전트에게 갑니다 (⌘/Ctrl+Enter 보내기)'",
            extract_js_fn("replyPlaceholder"),
        )
        self.assertIn('class="r-outcome"', body)
        self.assertIn('data-act="reply-flip"', body)
        self.assertIn("REPLY={id,flip:false,toggle:null,el:replyEl(p)}", extract_js_fn("openReply"))


# ---------------------------------------------------------------- [변경 보기] (docs/handbook/viewer.md §변경 보기)
class FrontendChangeView(unittest.TestCase):
    """Exercise commit matching and guard pin scoped source and PDF change controls."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def run_js(self, script):
        js = "\n".join(
            [extract_js_fn(n) for n in ("matchRevision", "pinFileIndex", "hunkRanges", "touchesPin", "revisionFiles")]
            + [script]
        )
        return json.loads(run_node(js))

    def test_ref_picks_commit_by_sha_then_pr_number(self):
        revs = [
            {"id": "0a569cc" + "1" * 33, "subject": "Clarify experimental questions (#238)"},
            {"id": "2cb7240" + "2" * 33, "subject": "Resolve manuscript viewer pins 19–41 (#236)"},
            {"id": "f47c6bf" + "3" * 33, "subject": "manuscript: 원고 핀 12건 반영 (#235)"},
            {"id": "1d422a6" + "4" * 33, "subject": "Merge pull request #203 from example-lab/docs"},
        ]
        out = self.run_js(
            "const revs=%s; console.log(JSON.stringify(['PR #235 (f47c6bf)','paper PR #236; code PR #75',"
            "'paper PR #236','#203','PR #999','', 'abcdef1'].map(r=>{const m=matchRevision(r,revs);return m&&[m.id.slice(0,7),m.via];})));"
            % json.dumps(revs)
        )
        self.assertEqual(
            out, [["f47c6bf", "sha"], ["2cb7240", "pr"], ["2cb7240", "pr"], ["1d422a6", "pr"], None, None, None]
        )

    def test_pin_file_and_line_overlap(self):
        patch = (
            "diff --git a/manuscript/1st/x.tex b/manuscript/1st/x.tex\n--- a/manuscript/1st/x.tex\n+++ b/manuscript/1st/x.tex\n"
            "@@ -10,3 +10,4 @@ ctx\n a\n+b\n c\n d\n@@ -80 +81 @@\n-x\n+y\n"
            "diff --git a/manuscript/1st/y.tex b/manuscript/1st/y.tex\n@@ -1 +1 @@\n-q\n+r\n"
        )
        out = self.run_js(
            "const f=revisionFiles(%s); console.log(JSON.stringify([pinFileIndex(f,'/home/u/paper/manuscript/1st/x.tex'),"
            "pinFileIndex(f,'/home/u/paper/manuscript/1st/zz.tex'), hunkRanges(f[0].text),"
            "touchesPin(f,{file:'/p/manuscript/1st/x.tex',lo:15,hi:16}), touchesPin(f,{file:'/p/manuscript/1st/x.tex',lo:40,hi:41}),"
            "touchesPin(f,{file:'/p/manuscript/1st/x.tex',lo:84,hi:90}), touchesPin(f,{file:'/p/other.tex',lo:1,hi:1})]));"
            % json.dumps(patch)
        )
        self.assertEqual(out, [0, -1, [[10, 13], [81, 81]], True, False, True, False])

    def test_wiring(self):
        h = HTML
        self.assertIn('data-act="change"', extract_js_fn("doneCard"))
        self.assertIn('data-act="change"', extract_js_fn("card"))
        self.assertIn("case 'change':if(id!=null)showChange(id);break;", h)
        self.assertIn('id="revision-pin"', h)
        self.assertIn("showRevision(pick.id,DIFF_FORMAT.SOURCE)", extract_js_fn("loadRevisions"))
        fmt = extract_js_fn("setRevisionFormat")
        # the comparison PDF is only built while viewing that format
        self.assertIn("REV.pdfCommit!==REV.commit", fmt)
        css = h[h.index("<style>") : h.index("</style>")]
        self.assertIn("body.revision-open #revision-view{display:block}", css)  # it opens even on a folded fold device

    def test_pin_scope_wiring(self):
        """The pin-scoped view's markup, actions, pin parameter, one-time fallback and shared CSS rules stay wired (v0.3)."""
        # v0.3 (docs/handbook/viewer.md §변경 보기, ADR-0005): the pin's hunks, the rest folded under one control, one PDF toggle
        h = HTML
        self.assertIn(
            '<button id="revision-other-toggle" class="btn-ghost btn-sm" data-act="revision-other" aria-expanded="false" '
            'aria-controls="revision-other" hidden>',
            h,
        )
        self.assertIn('<pre id="revision-other" class="wrap" hidden></pre>', h)
        self.assertIn(
            '<button id="revision-whole" class="tg btn-sm" data-act="revision-whole" aria-pressed="false" hidden', h
        )
        self.assertIn("case 'revision-other':toggleRevisionOther();break;", h)
        self.assertIn("case 'revision-whole':setRevisionWhole(!REV_SCOPE.whole);break;", h)
        src = extract_js_fn("loadRevisionSource")
        self.assertIn("'&pin='+tg0.id", src)  # a pin's view asks for its scope; plain browsing does not
        self.assertIn("r.scope.mode===SCOPE_MODE.PIN", src)
        pdf = extract_js_fn("loadRevisionPdf")
        self.assertIn("!REV_SCOPE.whole&&!REV_SCOPE.fallback?tg.id:null", pdf)
        self.assertIn("REV_SCOPE.fallback=true", pdf)  # a subset that does not compile falls back once
        self.assertIn("REV_SCOPE.whole=REV_SCOPE.partial=REV_SCOPE.fallback=false", extract_js_fn("showRevision"))
        css = h[h.index("<style>") : h.index("</style>")]
        # the folded diff shares every source-diff rule (its selector first, so the existing strings stay whole)
        for rule in (" .rd-line{", ".wrap .rd-code{", " .rd-add{", " .rd-del{", " .rd-hunk{"):
            self.assertIn("#revision-other%s,#revision-diff%s" % (rule[:-1], rule), css)
        self.assertIn("#revision-other-toggle[aria-expanded=true] .ic{transform:rotate(90deg)}", css)


class FrontendMentions(unittest.TestCase):
    """Exercise safe mention and pin reference rendering with real viewer text functions."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def run_js(self, script):
        js = "\n".join(
            [
                js_esc(),
                js_icons(),
                r"""
            let PEOPLE=[{login:'w@example.com',name:'Wendy Kim'},{login:'wo@example.com',name:'Wendy'},{login:'s@example.com',name:'Bob Park'},{login:'k@example.com',name:'김<b>'}];
            let META={me:{login:'s@example.com',name:'Bob Park'}};
            function threadOf(p){return Array.isArray(p&&p.thread)?p.thread:[];}
            const PINSET={12:1,3:1}; function findAnyPin(id){return PINSET[id]?{id}:null;} let DROPPED=[{id:40}];
            function tr(s){return s;}
            """,
            ]
            + [
                extract_js_fn(n)
                for n in (
                    "peopleName",
                    "mentionToks",
                    "reEsc",
                    "meLogin",
                    "pinRefExists",
                    "pinRefGone",
                    "fmtText",
                    "pinRefs",
                    "mentionsMe",
                    "mentionQuery",
                    "mentionMatches",
                    "mentionHints",
                    "mentionAfterWord",
                    "mentionTokens",
                    "mentionScan",
                    "defaultAssignee",
                    "assignPeople",
                    "assignSeg",
                    "renderAssignNew",
                    "editNote",
                    "renderAssignEdit",
                )
            ]
            + [script]
        )
        return json.loads(run_node(js))

    def test_highlight_does_not_double_wrap_and_escapes(self):
        out = self.run_js(r"""
            console.log(JSON.stringify([fmtText('@Wendy Kim 와 @Wendy <i>',['w@example.com','wo@example.com']), fmtText('@김<b> 안녕',['k@example.com']),
              fmtText('@Bob Park',[])].map(String)));""")

        def tip(name):
            """The tooltip attribute fmtText() puts on a resolved @-tag for name."""
            return ' data-tip="@태그 — %s에게 알림이 갑니다"' % name

        self.assertEqual(
            out,
            [
                '<span class="mention"%s>@Wendy Kim</span> 와 <span class="mention"%s>@Wendy</span> &lt;i&gt;'
                % (tip("Wendy Kim"), tip("Wendy")),
                '<span class="mention"%s>@김&lt;b&gt;</span> 안녕' % tip("김&lt;b&gt;"),
                "@Bob Park",
            ],
        )

    def test_mention_of_me_is_stronger_and_unresolved_stays_plain(self):
        # author feedback (2026-09-24): couldn't tell a real mention from plain text. Only a resolved tag
        # becomes a token; being mentioned gets .me; an unresolved '@word' stays plain text.
        out = self.run_js(r"""
            console.log(JSON.stringify([fmtText('@Bob Park 봐 주세요 @홍길동',['s@example.com']), fmtText('mail a@Bob Park',['s@example.com']),
              fmtText('@Bob Parkx',['s@example.com']), fmtText('@bob park',['s@example.com'])].map(String)));""")
        self.assertEqual(
            out[0],
            '<span class="mention me" data-tip="나를 부름 — 이 핀 알림이 나에게 옵니다">@Bob Park</span> 봐 주세요 @홍길동',
        )
        self.assertEqual(out[1], "mail a@Bob Park")  # something shaped like an email address is not a mention
        self.assertNotIn("mention", out[2])  # letters right after a name make it a different word
        self.assertIn('class="mention me"', out[3])  # case-insensitive (same as the server)

    def test_highlight_skips_an_at_that_follows_any_letter(self):
        """fmtText() wraps only the '@name' the server resolves: an '@' right after a letter of any script ('é', '김',
        an astral '𠀀' written as two UTF-16 units) continues a word, as in resolve_mentions(). It used to check only
        ASCII and Hangul, so 'é@Wendy Kim' rendered as a tag the server never recorded."""
        out = self.run_js(r"""
            const W=PEOPLE.find(p=>p.name==='Wendy Kim').login;
            console.log(JSON.stringify(['é@Wendy Kim','김@Wendy Kim','𠀀@Wendy Kim','😀@Wendy Kim','(@Wendy Kim)']
              .map(t=>(String(fmtText(t,[W])).match(/class="mention"/g)||[]).length)));""")
        self.assertEqual(out, [0, 0, 0, 1, 1])

    def test_pin_refs_link_only_existing_pins_and_skip_entities(self):
        out = self.run_js(r"""
            console.log(JSON.stringify([fmtText("#12 과 #99 그리고 it's (#3) #40",[]), fmtText('a#12 &#12;',[])].map(String)));""")
        # 12/3/40 (a dropped pin) — nonexistent 99 stays plain text
        self.assertEqual(out[0].count('data-act="pin-ref"'), 3)
        self.assertIn('data-ref="12"', out[0])
        self.assertIn('data-ref="40"', out[0])
        self.assertNotIn('data-ref="99"', out[0])
        self.assertIn('<span class="pin-ref gone"', out[0])  # v0.2.2: #40 is in the Trash - it reads 'deleted pin'
        self.assertIn("#40 <small>삭제된 핀</small>", out[0])
        self.assertIn("it&#39;s", out[0])  # the escaped &#39; is not a link
        self.assertNotIn("pin-ref", out[1])

    def test_scan_lists_who_gets_notified_and_unresolved_words(self):
        out = self.run_js(r"""
            console.log(JSON.stringify([mentionScan('@Bob Park 와 @홍길동 그리고 @Wendy Kim',new Set()), mentionScan('a@b.com',new Set()),
              mentionScan('@Wendy 봐',new Set(['wo@example.com']))]));""")
        self.assertEqual(
            out[0], {"hit": ["s@example.com", "w@example.com"], "bad": ["홍길동"], "first": "s@example.com"}
        )
        self.assertEqual(out[1], {"hit": [], "bad": [], "first": None})
        self.assertEqual(out[2]["hit"][0], "wo@example.com")

    def test_default_assignee_rules(self):
        # if the note starts with a resolved @-mention, that person; otherwise the first @-mention on a question pin; otherwise the agent. I (s@example.com) can't be chosen.
        out = self.run_js(r"""
            console.log(JSON.stringify([
              defaultAssignee('@Wendy Kim 확인 부탁','fix',new Set()),
              defaultAssignee('  @Wendy Kim 확인 부탁','fix',new Set()),
              defaultAssignee('이거 콜링 작동하나 @Wendy Kim 확인 부탁','fix',new Set()),
              defaultAssignee('이 구간이 뭔가요 @Wendy Kim','question',new Set()),
              defaultAssignee('@Bob Park 메모','fix',new Set()),
              defaultAssignee('@Bob Park @Wendy Kim 뭔가요','question',new Set()),
              defaultAssignee('@홍길동 확인','fix',new Set()),
              defaultAssignee('그냥 메모','question',new Set()),
              assignPeople('@Bob Park @Wendy Kim 봐 주세요',new Set()),
              assignPeople('메모',new Set(),'k@example.com')]));""")
        self.assertEqual(
            out,
            [
                "w@example.com",
                "w@example.com",
                "agent",
                "w@example.com",
                "agent",
                "w@example.com",
                "agent",
                "agent",
                ["w@example.com"],
                ["k@example.com"],
            ],
        )

    def test_assignee_choice_reads_the_hints_the_request_carries(self):
        """The composer and edit assignee rows resolve the note with mentionHints() - the hints the save sends - not
        with every login ever picked in the field. Picking '@Wendy Kim' and then editing it down to the shared first
        word '@Wendy' drops that hint, so the server tags nobody; the row must then offer nobody and default to the
        agent. It used to offer and default to Wendy Kim, saving a pin handed to someone its note never tagged."""
        out = self.run_js(r"""
            const W=PEOPLE.find(p=>p.name==='Wendy Kim').login, box=()=>({hidden:true,innerHTML:'',replaceChildren(){this.innerHTML='';}});
            const note={value:'@Wendy 봐 주세요',_mentions:new Set([W])},cbox=box();
            function $(s){return s==='#note'?note:s==='#c-assign'?cbox:null;}
            let KIND_NEW='fix'; const ASSIGN_NEW={v:'agent',touched:false};
            const ta={value:'@Wendy 봐 주세요',_mentions:new Set([W])},ebox=box();
            const EDITOR={current:{el:{querySelector:s=>s==='.e-note'?ta:s==='.e-assign'?ebox:null},assignee:'agent'},saving:false};
            renderAssignNew(); renderAssignEdit(); const edited=[ASSIGN_NEW.v,cbox.hidden,ebox.hidden];
            note.value='@Wendy Kim 봐 주세요'; renderAssignNew();   // the picked full name kept: the hint stands
            console.log(JSON.stringify([edited,[ASSIGN_NEW.v===W,cbox.hidden]]));""")
        self.assertEqual(out, [["agent", True, True], [True, False]])

    def test_assign_controls_in_composer_edit_and_card(self):
        h = HTML
        self.assertIn('<div id="c-assign" class="assign-row" role="radiogroup" aria-label="담당" hidden></div>', h)
        self.assertIn('<div class="e-assign assign-row" role="radiogroup" aria-label="담당" hidden></div>', h)
        self.assertIn("body.assignee=ASSIGN_NEW.v||ASSIGNEE_AGENT;", extract_js_fn("savePin"))
        self.assertIn(
            "if(E.assignee&&E.assignee!==E.orig.assignee)body.assignee=E.assignee;", extract_js_fn("saveEdit")
        )
        self.assertIn("${assignChip(p)}${thn}${au}", extract_js_fn("card"))
        self.assertIn("const adr=p.assignee?null:addressedTag(p);", extract_js_fn("card"))
        self.assertIn("assigned:5", h)
        self.assertIn("assign:'담당 바꿈'", h)

    def test_preview_row_under_every_mention_field(self):
        h = HTML
        self.assertIn('<div id="note-mentions" class="m-preview" aria-live="polite" hidden></div>', h)
        # edit and reply
        self.assertEqual(h.count('</textarea><div class="m-preview" aria-live="polite" hidden></div>'), 2)
        body = extract_js_fn("mentionPreview")
        self.assertIn("등록된 사람이 아님", body)
        self.assertIn("${ic('at-sign')}알림</span>", body)
        css = h[h.index("<style>") : h.index("</style>")]
        self.assertRegex(
            css, r"\.mention\{color:var\(--primary\);font-weight:600;background:color-mix\(in srgb,var\(--primary\) 12%"
        )
        self.assertIn(".mention.me{background:color-mix(in srgb,var(--primary) 28%", css)
        self.assertIn(".mention-bad{", css)

    def test_query_matches_and_hints(self):
        out = self.run_js(r"""
            const ta=(v,pos)=>({value:v,selectionStart:pos==null?v.length:pos,selectionEnd:pos==null?v.length:pos});
            const q=[mentionQuery(ta('안녕 @Won')),mentionQuery(ta('mail a@b')),mentionQuery(ta('@')),mentionQuery(ta('@Won ch')),mentionQuery(ta('é@Won')),mentionQuery(ta('(@Won'))];
            const m=mentionMatches('wen',PEOPLE,'s@example.com').map(p=>p.login), mine=mentionMatches('',PEOPLE,'s@example.com').map(p=>p.login);
            const t=ta('@Wendy Kim 봐 주세요'); t._mentions=new Set(['w@example.com','s@example.com']);
            console.log(JSON.stringify([q,m,mine.includes('s@example.com'),mentionHints(t),
              mentionsMe({addressed:['s@example.com']}),mentionsMe({addressed:['w@example.com']}),mentionsMe({mentions:['s@example.com'],thread:[{mentions:['s@example.com']}]})]));""")
        self.assertEqual(
            out,
            [
                [{"start": 3, "q": "Won"}, None, {"start": 0, "q": ""}, None, None, {"start": 1, "q": "Won"}],
                ["wo@example.com", "w@example.com"],
                False,
                ["w@example.com"],
                True,
                False,
                False,
            ],
        )
        # mentionsMe only looks at p.addressed, pre-computed by the server (question pin, current round) —
        # it does not scan the full legacy mentions/thread
        # (observed bug: an @-mention from an old round stayed marked as "a pin that called me" even after reopening).

    def test_wiring(self):
        h = HTML
        self.assertIn('id="mention-pop"', h)
        self.assertIn('id="mention-filter"', h)
        self.assertIn("const mh=mentionHints($('#note')); if(mh.length)body.mentions=mh;", extract_js_fn("savePin"))
        self.assertIn("mentionHints(ta)", extract_js_fn("sendReply"))
        self.assertIn("fmtText(p.note,p.mentions)", extract_js_fn("card"))
        # autocomplete gets Enter/Esc first (capture phase)
        self.assertIn("window.addEventListener('keydown',e=>{if(!MENTION.ta", h)


# ---------------------------------------------------------------- browser notifications (docs/handbook/viewer.md §브라우저 알림)
class FrontendSpacingGrid(unittest.TestCase):
    """Spacing (padding/margin/gap) sits on a 4/8px grid (4, 8, 12, 16, 24). 1-2px is left alone as
    hairline borders / optical correction (e.g. 1px above/below a badge). It used to mix in ad hoc values
    like 6, 10, 14, 18px (grid cleanup QA 2026-09-25)."""

    def test_spacing_is_on_the_grid(self):
        css = HTML[HTML.index("<style>") : HTML.index("</style>")]
        bad = []
        for m in re.finditer(r"(?<![\w-])((?:padding|margin|gap|row-gap|column-gap)(?:-[a-z]+)?)\s*:\s*([^;{}]+)", css):
            for n in re.findall(r"(?<![\w.-])(\d+(?:\.\d+)?)px", m.group(2)):
                x = float(n)
                if x % 4 and x not in (1, 2) and "--side-w" not in m.group(2):
                    bad.append(m.group(0))
        self.assertEqual(bad, [])


class FrontendMentionPopPlacement(unittest.TestCase):
    """@-list placement (mentionTop): doesn't cover the action row ([취소][보내기]) below the input field (QA 2026-09-25 — the list used to cover both buttons in the reply field)."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def top(self, r, g, h, top=0, bot=800):
        js = extract_js_fn("mentionTop") + "\nconsole.log(JSON.stringify(mentionTop(%s,%s,%d,%d,%d)));" % (
            json.dumps(r),
            json.dumps(g),
            h,
            top,
            bot,
        )
        return json.loads(run_node(js))

    def test_reply_box_opens_above_when_actions_sit_right_below(self):
        # reply field: input 300-360, [취소][보내기] 368-396. A list height of 48 doesn't fit between them, so it opens above.
        self.assertEqual(self.top({"top": 300, "bottom": 360}, {"top": 368, "bottom": 396}, 48), 300 - 4 - 48)

    def test_below_when_room_before_actions(self):
        # composer (desktop): the action row is at the panel's bottom, so there's room below the input — opens below, as before.
        self.assertEqual(self.top({"top": 400, "bottom": 480}, {"top": 800, "bottom": 850}, 48, 0, 850), 484)

    def test_below_actions_when_no_room_above(self):
        # input field at the very top of the screen: can't open above either, so it opens below the action row (which stays visible).
        self.assertEqual(self.top({"top": 10, "bottom": 70}, {"top": 78, "bottom": 106}, 48), 110)

    def test_fallback_stays_inside_viewport(self):
        # when it doesn't fit anywhere, fall back to below the input (the old spot), pulled inside the viewport.
        self.assertEqual(self.top({"top": 10, "bottom": 70}, {"top": 78, "bottom": 106}, 200, 0, 260), 56)

    def test_no_guard_keeps_old_behaviour(self):
        self.assertEqual(self.top({"top": 300, "bottom": 360}, None, 48), 364)
        self.assertEqual(self.top({"top": 700, "bottom": 780}, None, 48), 648)

    def test_guard_is_found_for_all_three_boxes(self):
        # reply/reopen (.reply-box -> .r-acts), edit (.edit -> .e-acts), composer (#note -> #c-actions)
        fn = extract_js_fn("mentionGuard")
        for sel in (".reply-box,.edit", ".r-acts,.e-acts", "#c-actions"):
            self.assertIn(sel, fn)


# The viewer functions mentionPreview() reaches (besides esc/ic/tr and the DOM), pulled from the served page.
MENTION_PREVIEW_FNS = (
    "peopleName",
    "mentionAfterWord",
    "mentionTokens",
    "meLogin",
    "mentionQuery",
    "mentionHints",
    "mentionBadSettled",
    "mentionScan",
    "mentionPreview",
)


class FrontendMentionTypingNotFlagged(unittest.TestCase):
    """A '@word' still being typed isn't flagged as '등록된 사람이 아님' right away (QA 2026-09-25 — a warning showed up while typing @Sa)."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_token_under_caret_is_not_flagged_until_caret_leaves(self):
        js = (
            extract_js_fn("mentionBadSettled")
            + r"""
            console.log(JSON.stringify([
              mentionBadSettled(['Sa'],'@Sa',{start:0,q:'Sa'}),            // 쓰는 중 — 알리지 않는다
              mentionBadSettled(['Sa'],'@Sa',null),                       // 커서가 떠남 — 알린다
              mentionBadSettled(['홍길동','Sa'],'@홍길동 @Sa',{start:5,q:'Sa'}),  // 끝난 말은 그대로 알린다
              mentionBadSettled(['Sa'],'@Sa 또 @Sa',{start:7,q:'Sa'})]));   // 같은 말이 앞에 이미 있으면 알린다"""
        )
        self.assertEqual(json.loads(run_node(js)), [[], ["Sa"], ["홍길동"], ["Sa"]])

    def test_preview_holds_the_warning_while_the_caret_ends_the_word(self):
        """mentionPreview() itself applies mentionBadSettled(): with the caret at the end of '@Sa' in the focused field the
        preview row stays hidden; once focus leaves, the same text shows '@Sa' as '등록된 사람이 아님'. A finished '@홍길동'
        before the caret is flagged either way.

        Regression: the call was pasted onto the end of a '//' comment in mentionPreview (1486de0), so it never ran and
        the warning showed while the name was still being typed."""
        js = "\n".join(
            [
                js_esc(),
                js_icons(),
                r"""
            let PEOPLE=[{login:'sam@example.com',name:'Sam Lee'}], META={me:{login:'me@example.com',name:'Me'}};
            const document={activeElement:null};
            function field(v){const box={hidden:true,innerHTML:'',replaceChildren(){this.innerHTML='';},classList:{contains:c=>c==='m-preview'}};
              return {value:v,selectionStart:v.length,selectionEnd:v.length,nextElementSibling:box};}
            function show(v,focused){const ta=field(v); document.activeElement=focused?ta:null; mentionPreview(ta);
              const b=ta.nextElementSibling; return b.hidden?null:(b.innerHTML.match(/mention-bad[^>]*>@[^<]*/g)||[]).map(s=>s.split('>')[1]);}
            """,
            ]
            + [extract_js_fn(n) for n in MENTION_PREVIEW_FNS]
            + [
                r"""
            console.log(JSON.stringify([show('@Sa',true), show('@Sa',false), show('@홍길동 @Sa',true), show('@Sa 봐',true)]));"""
            ]
        )
        self.assertEqual(json.loads(run_node(js)), [None, ["@Sa"], ["@홍길동"], ["@Sa"]])

    def test_list_highlight_is_a_flat_full_width_row(self):
        css = HTML[HTML.index("<style>") : HTML.index("</style>")]
        self.assertIn(
            "#mention-pop{position:fixed;z-index:90;min-width:200px;max-width:min(360px,calc(100vw - 16px));padding:var(--space-1) 0;",
            css,
        )
        self.assertIn(
            "border:0;border-radius:0;background:transparent;text-align:left;padding:var(--space-2) var(--space-3)}",
            css,
        )


class FrontendQuestionHint(unittest.TestCase):
    """Suggests [질문으로 보내기] (send as a question) for a note that reads like a question (looksQuestion).
    A coauthor saved "...표현한 의도가 있는건가?" as a fix request (2026-09-25). This only judges — the kind
    changes only when the user clicks."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def judge(self, texts):
        js = extract_js_fn("looksQuestion") + "\nconsole.log(JSON.stringify(%s.map(looksQuestion)));" % json.dumps(
            texts, ensure_ascii=False
        )
        return json.loads(run_node(js))

    def test_question_marks(self):
        texts = [
            "여기 이렇게 쓴 이유가 있는건가?",
            "식의 k란..?",
            "100개가 어떻게 나온것인지?",
            "Why is this here?",
            "전각 물음표？",
            "끝에 공백 ?  ",
            "이거 맞나요? @Bob Park",
            "맞나요?)",
            "뭐임??",
        ]
        self.assertEqual(self.judge(texts), [True] * len(texts))

    def test_korean_interrogative_endings_without_mark(self):
        texts = [
            "의도가 있는 건가",
            "이 정의가 맞는가",
            "이거 맞나요",
            "그림으로 바꾸면 어떨까요",
            "이게 최선인가",
            "이거 누가 썼니",
            "이게 맞냐",
            "그래프로 보이는 게 낫지 않을까",
            "이해가 됩니까.",
            "확인했나요 @Bob Park",
            "정의가 있나요…",
        ]
        self.assertEqual(self.judge(texts), [True] * len(texts))

    def test_statements_are_not_questions(self):
        texts = [
            "",
            "   ",
            "예시 아님.",
            "이건 삭제하는게 좋을듯",
            "표 주석은 굳이 있을 필요 없음. 삭제.",
            "여기 의도가 있는건가? 그래도 고쳐줘.",
            "더블 컬럼",
            "@Bob Park 확인 부탁합니다",
            "?는 쓰지 말 것",
            "TODO: fix eq. (3)",
        ]
        self.assertEqual(self.judge(texts), [False] * len(texts))

    def test_hint_is_wired_to_both_forms_and_never_switches_by_itself(self):
        html = HTML
        self.assertIn('id="c-qhint"', html)  # composer
        self.assertIn('class="e-qhint q-hint"', html)  # edit panel (the kind can be changed)
        # clicking it switches — same as the existing kind action
        self.assertIn('data-act="kind" data-kind="question"', html)
        self.assertIn('data-act="e-kind" data-kind="question"', html)
        qh = extract_js_fn("qHint")
        self.assertNotIn("setKind", qh)  # only suggests
        self.assertNotIn("kind_req=", qh)
        self.assertIn("kind===KIND_REQ.QUESTION", qh)  # hidden if it's already a question


class FrontendNotify(unittest.TestCase):
    """Exercise browser notification selection, deduplication, cursor handling, and wiring."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def harness(self, script):
        rank = re.search(r"^const NOTIFY_RANK=.*;$", HTML, re.M).group(0)
        return "\n".join(
            [
                rank,
                r"""
            function who(a){return (a&&(a.name||a.login))||'';}
            const store={}; const localStorage={getItem:k=>k in store?store[k]:null,setItem:(k,v)=>{store[k]=String(v);}};
            let NOTIFY=true; function notifyOn(){return NOTIFY;}
            let META={me:{login:'w@example.com',name:'Wendy Kim'},label:'DEMO-B'}; const SHOWN=[];
            function notifyShow(e){SHOWN.push([e.pin,e.type]);}
            """,
            ]
            + [
                extract_js_fn(n)
                for n in (
                    "notifyCursor",
                    "setNotifyCursor",
                    "notifyQuery",
                    "pickNotifications",
                    "notifyText",
                    "notifyHandle",
                )
            ]
            + [script]
        )

    def test_trigger_selection_self_suppression_and_dedupe(self):
        js = self.harness(r"""
            const me={login:'w@example.com'}, S={login:'s@example.com',name:'Bob Park'};
            const evs=[{seq:1,type:'replied',pin:5,to:['w@example.com'],by:S},{seq:2,type:'mention',pin:5,to:['w@example.com'],by:S},
              {seq:3,type:'review_requested',pin:6,to:['w@example.com'],by:{login:'local'}},{seq:4,type:'replied',pin:7,to:['s@example.com'],by:S},
              {seq:5,type:'mention',pin:8,to:['w@example.com'],by:{login:'w@example.com'}},{seq:6,type:'confirmed',pin:9,to:['w@example.com'],by:S},
              {seq:7,type:'reopened',pin:6,to:['w@example.com'],by:S}];
            const a=pickNotifications(evs,me,0).map(e=>[e.pin,e.type]);
            const b=pickNotifications(evs,me,2).map(e=>[e.pin,e.type]);
            const c=pickNotifications(evs,{login:'local'},0);
            console.log(JSON.stringify([a,b,c,notifyText(evs[1]),notifyText({type:'review_requested',pin:6,excerpt:'답했다\n둘째',doc_name:'본문'})]));
            """)
        out = json.loads(run_node(js))
        self.assertEqual(out[0], [[5, "mention"], [6, "reopened"]])  # one per pin — mention/reopened win
        self.assertEqual(out[1], [[6, "reopened"]])
        self.assertEqual(out[2], [])
        self.assertEqual(out[3], {"title": "핀 #5 · DEMO-B", "body": "Bob Park님이 불렀습니다: "})
        self.assertEqual(out[4], {"title": "핀 #6 · 본문", "body": "검토 대기: 답했다"})

    def test_cursor_prevents_refire_across_reloads_and_tabs(self):
        js = self.harness(r"""
            const S={login:'s@example.com',name:'S'};
            notifyHandle({ev_seq:4});                                   // 처음 켠 브라우저 — 지난 이벤트는 건너뛴다
            const c0=notifyCursor(), q=notifyQuery();
            const d={ev_seq:6,events:[{seq:5,type:'mention',pin:1,to:['w@example.com'],by:S},{seq:6,type:'replied',pin:2,to:['w@example.com'],by:S}]};
            notifyHandle(d);                                            // 탭 A
            notifyHandle(d);                                            // 탭 B 가 같은 응답을 늦게 받음(같은 localStorage)
            notifyHandle({ev_seq:6,events:[]});                         // 새로고침 뒤
            NOTIFY=false; notifyHandle({ev_seq:9,events:[{seq:9,type:'mention',pin:3,to:['w@example.com'],by:S}]});
            console.log(JSON.stringify([c0,q,SHOWN,notifyCursor(),notifyQuery()]));
            """)
        self.assertEqual(json.loads(run_node(js)), [4, "&ev=4", [[1, "mention"], [2, "replied"]], 6, ""])

    def test_wiring(self):
        h = HTML
        self.assertIn('id="m-notify"', h)
        # [더보기]'s row is a switch with its reason line under it (UX spec §V7), its state never in its name
        self.assertRegex(h, r'<button id="m-notify" role="switch" aria-checked="false"')
        self.assertIn('id="m-notify-why"', h)
        self.assertIn("m.setAttribute('aria-checked',String(st===NOTIFY_STATE.ON))", extract_js_fn("drawNotify"))
        self.assertNotIn('id="btn-notify"', h)  # the desktop's bell went with its [⋯]: the switch is the one control
        tog = extract_js_fn("notifyToggle")
        self.assertIn("Notification.requestPermission()", tog)
        self.assertEqual(html_without_comments(h).count("requestPermission("), 1)  # only asked on the click path
        self.assertIn("reg.showNotification(", extract_js_fn("notifyShow"))
        self.assertNotIn("new Notification(", html_without_comments(h))
        self.assertIn("tag:'pin-'+e.pin", extract_js_fn("notifyShow"))
        self.assertIn("document.visibilityState==='visible'&&document.hasFocus()", extract_js_fn("notifyShow"))
        self.assertIn("notifyQuery()", extract_js_fn("pollLightOnce"))
        self.assertIn("navigator.serviceWorker.register('/sw.js'", extract_js_fn("notifyRegister"))


class FrontendBadgeWording(unittest.TestCase):
    """The viewer's relBadge() and overlap banner say what the server's rel_badge() says, in Korean and English."""

    def test_js_rel_badge_matches_server(self):
        if not shutil.which("node"):
            self.skipTest("node not available")
        js = "\n".join(
            [
                extract_js_fn("josa"),
                extract_js_fn("relBadge"),
                r"""
            const PINS=[{id:1,lo:4,hi:9},{id:2,lo:4,hi:9},{id:3,lo:5,hi:6},{id:20,lo:8,hi:12}];
            console.log(JSON.stringify([relBadge([{id:1,rel:'contains'}],{id:2,lo:4,hi:9}).label,
              relBadge([{id:1,rel:'inside'},{id:2,rel:'inside'}],{id:3,lo:5,hi:6}).label,
              relBadge([{id:20,rel:'partial'}],{id:3,lo:5,hi:9}).label, relBadge([{id:3,rel:'contains'}],{id:1,lo:4,hi:9})]));
            """,
            ]
        )
        self.assertEqual(json.loads(run_node(js)), ["#1과 같은 범위", "#1 범위 안", "#20과 일부 겹침", None])
        self.assertIn("const rb=closedCard?null:relBadge(p.rel,p);", extract_js_fn("card"))

    def test_overlap_banner_verbs(self):
        if not shutil.which("node"):
            self.skipTest("node not available")
        cases = r"""
            console.log(JSON.stringify([['equal',4],['inside',20],['contains',4],['contains',20],['partial',2]].map(a=>overlapText(a[0],a[1]))));
            """
        js = "\n".join([extract_js_fn("josa"), extract_js_fn("overlapText"), cases])
        self.assertEqual(
            json.loads(run_node(js)),
            [
                "열린 핀 #4와 같은 범위입니다",
                "열린 핀 #20 범위 안입니다",
                "열린 핀 #4를 감쌉니다",
                "열린 핀 #20을 감쌉니다",
                "열린 핀 #2와 일부 겹칩니다",
            ],
        )
        self.assertEqual(
            json.loads(run_node(js_i18n("en") + "\n" + js)),
            [
                "Same range as open pin #4",
                "Inside open pin #20's range",
                "Encloses open pin #4",
                "Encloses open pin #20",
                "Partially overlaps open pin #2",
            ],
        )


# ---------------------------------------------------------------- one [Reply], the Trash and collapsible sections (v0.2.2, issue #8)


class FrontendReplyRule(unittest.TestCase):
    """The viewer's replyReopens() predicts the server's reply rule on every row of the table (helpers.RULE_CASES)."""

    def test_viewer_mirrors_the_server_rule(self):
        # The one-line preview under the reply box must predict exactly what the server will do.
        js = "\n".join(
            [
                extract_js_fn("pinState"),
                extract_js_fn("replyReopens"),
                "const cases=%s;" % json.dumps([[rec_for(st, k), h, m, ov] for st, k, h, m, ov, _ in RULE_CASES]),
                "console.log(JSON.stringify(cases.map(c=>replyReopens(c[0],c[1],c[2],c[3]===null?undefined:c[3]))));",
            ]
        )
        self.assertEqual(json.loads(run_node(js)), [w for *_, w in RULE_CASES])


class ViewerMarkup(unittest.TestCase):
    """Guard the served viewer markup for pin states, sections, help, and notification controls."""

    def test_no_reopen_button_anywhere(self):
        self.assertNotIn('data-act="rv-reopen"', HTML)
        self.assertNotIn("case 'rv-reopen'", HTML)
        self.assertNotIn("openReply(id,'reopen')", HTML)

    def test_dropped_section_left_the_list(self):
        lst = HTML[HTML.index('<div id="list">') : HTML.index('<div id="c-actions">')]
        self.assertNotIn("sec-dropped", lst)
        self.assertIn('<dialog id="trash"', HTML)
        more = HTML[HTML.index('<dialog id="more"') : HTML.index("</dialog>", HTML.index('<dialog id="more"'))]
        self.assertIn('id="m-trash"', more)
        self.assertIn('data-act="trash-open"', more)

    def test_three_sections_share_one_header_component(self):
        for sec in ("open", "review", "done"):
            with self.subTest(section=sec):
                m = re.search(
                    r'<button class="sec-tg" id="%s-toggle" data-act="sec-toggle" data-sec="%s" aria-expanded="(true|false)" '
                    r'aria-controls="[a-z-]+"' % (sec, sec),
                    HTML,
                )
                self.assertIsNotNone(m, sec)

    def test_help_defines_pin_once(self):
        help_ = HTML[HTML.index('<dialog id="help"') : HTML.index("</dialog>", HTML.index('<dialog id="help"'))]
        self.assertIn("<tr><td>핀</td><td>출력물의 한 자리 + 요청이나 질문 + 그 대화", help_)
        self.assertEqual(help_.count("<tr><td>핀</td>"), 1)
        en = UI_EN["출력물의 한 자리 + 요청이나 질문 + 그 대화. 번호(#N)는 다시 쓰이지 않습니다"]
        self.assertTrue(en.startswith("A place in the output + a request or question + its conversation"), en)

    def test_dropped_is_a_notification_type(self):
        self.assertIn("dropped:", re.search(r"const NOTIFY_RANK=\{[^}]*\}", HTML).group(0))
        self.assertIn("dropped", NOTIFY_TYPES)

    def test_system_notification_for_a_deleted_pin_offers_restore(self):
        # a hidden tab gets a system notification: [되살리기] is a notification action the service worker hands to the tab
        self.assertIn(
            "actions:e.type===EVENT_TYPE.DROPPED&&!isViewer()?[{action:'restore',title:tr('되살리기')}]:[]",
            extract_js_fn("notifyShow"),
        )
        self.assertIn("e.action==='restore'", SW_JS)
        self.assertIn("d.type==='restore-pin'", HTML)


class ViewerFunctions(unittest.TestCase):
    """Exercise reply previews, section counts, trash dates, and deleted pin references."""

    def setUp(self):
        import shutil

        if not shutil.which("node"):
            self.skipTest("node not available")

    def preview(self, lang, cases):
        js = "\n".join(
            [
                js_i18n(lang),
                "const PEOPLE=[{login:'bob@example.com',name:'Bob Park'},{login:'carol@example.com',name:'Carol Lee'}];",
                extract_js_fn("peopleName"),
                extract_js_fn("pinState"),
                extract_js_fn("replyReopens"),
                extract_js_fn("replyPreview"),
                "const cases=%s;" % json.dumps(cases),
                "console.log(JSON.stringify(cases.map(c=>replyPreview(c[0],c[1],c[2],c[3]))));",
            ]
        )
        return json.loads(run_node(js))

    def test_preview_line_for_each_outcome(self):
        rv, dn, op, q = (
            rec_for("review", "fix"),
            rec_for("done", "fix"),
            rec_for("open", "fix"),
            rec_for("review", "question"),
        )
        cases = [
            [rv, True, [], False],
            [dn, True, [], False],
            [rv, True, ["bob@example.com"], False],
            [rv, True, [], True],
            [q, True, [], False],
            [rv, False, [], False],
            [op, True, [], False],
        ]
        ko = self.preview("ko", cases)
        self.assertEqual(
            [(x or {}).get("text") for x in ko],
            [
                "보내면 이 핀이 다시 열려 에이전트에게 갑니다",
                "보내면 이 핀이 다시 열려 에이전트에게 갑니다",
                "보내면 Bob Park에게 알림이 가고 상태는 그대로입니다",
                "보내도 상태는 그대로입니다",
                "답으로 남고 상태는 그대로입니다",
                "이 화면은 에이전트로 보내므로 상태는 그대로입니다",
                None,
            ],
        )
        # the one override toggle: [상태 유지] where the rule reopens, [다시 열기] where it keeps a closed pin as it is
        self.assertEqual(
            [(x or {}).get("toggle") for x in ko], ["keep", "keep", "reopen", "keep", "reopen", "reopen", None]
        )
        flipped = self.preview(
            "ko", [[rv, True, ["bob@example.com"], True], [q, True, [], True], [rv, False, [], True]]
        )
        self.assertEqual(
            [x["text"] for x in flipped],
            [
                "보내면 이 핀이 다시 열려 에이전트에게 가고, Bob Park에게 알림이 갑니다",
                "보내면 이 핀이 다시 열려 에이전트에게 갑니다",
                "보내면 이 핀이 다시 열려 에이전트에게 갑니다",
            ],
        )
        en = self.preview("en", cases)
        self.assertEqual(
            [(x or {}).get("text") for x in en],
            [
                "Sending will reopen this pin for the agent",
                "Sending will reopen this pin for the agent",
                "Sending notifies Bob Park; state stays",
                "Sending keeps the state as it is",
                "Recorded as an answer; state stays",
                "This screen posts as the agent; state stays",
                None,
            ],
        )

    def test_section_state_defaults_and_new_count(self):
        js = "\n".join(
            [
                "const SEC_DEFAULT={open:true,review:true,done:false};",
                extract_js_fn("secState"),
                extract_js_fn("secNewCount"),
                r"""
            console.log(JSON.stringify([secState(undefined), secState({done:true}), secState({open:false,x:1,review:'no'}),
              secNewCount(new Set([1,2]),[1,2,3,4]), secNewCount(new Set([1,2]),[2]), secNewCount(null,[1])]));""",
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)),
            [
                {"open": True, "review": True, "done": False},
                {"open": True, "review": True, "done": True},
                {"open": False, "review": True, "done": False},
                2,
                0,
                0,
            ],
        )

    def test_trash_days_left(self):
        js = "\n".join(
            [
                "const TRASH_DAYS=30;",
                extract_js_fn("trashDaysLeft"),
                r"""
            const now=new Date(2026,8,25,12,0).getTime();
            console.log(JSON.stringify([trashDaysLeft('2026-09-25 11:00:00',now), trashDaysLeft('2026-08-27 12:00:00',now),
              trashDaysLeft('2026-08-20 12:00:00',now), trashDaysLeft('',now)]));""",
            ]
        )
        self.assertEqual(json.loads(run_node(js)), [30, 1, 0, None])  # Aug 27 -> Sep 25 is 29 days: 1 left

    def test_ref_to_a_deleted_pin_renders_as_deleted(self):
        js = "\n".join(
            [
                js_esc(),
                js_markup(),
                r"""
            let PEOPLE=[], META=null; const DROPPED=[{id:12}];
            function findAnyPin(id){return id===3?{id:3}:null;}
            """,
                extract_js_fn("mentionToks"),
                extract_js_fn("mentionAfterWord"),
                extract_js_fn("reEsc"),
                extract_js_fn("meLogin"),
                extract_js_fn("pinRefExists"),
                extract_js_fn("pinRefGone"),
                extract_js_fn("fmtText"),
                extract_js_fn("pinRefs"),
                "console.log(JSON.stringify([fmtText('#3 와 #12 와 #99',[])].map(String)));",
            ]
        )
        out = json.loads(run_node(js))[0]
        self.assertIn('data-ref="3"', out)
        self.assertRegex(out, r'<span class="pin-ref gone"[^>]*data-ref="12"[^>]*>#12 <small>삭제된 핀</small></span>')
        self.assertIn("#99", out)
        self.assertNotIn('data-ref="99"', out)


class ViewerFunctions2(unittest.TestCase):
    """Exercise reply outcome wording and trash record identity or time presentation."""

    def setUp(self):
        import shutil

        if not shutil.which("node"):
            self.skipTest("node not available")

    def js(self, lang, script):
        return json.loads(
            run_node(
                "\n".join(
                    [
                        js_i18n(lang),
                        "const PEOPLE=[{login:'bob@example.com',name:'Bob Park'},{login:'carol@example.com',name:'Carol Lee'}];",
                        extract_js_fn("peopleName"),
                        extract_js_fn("pinState"),
                        extract_js_fn("replyReopens"),
                        extract_js_fn("replyPreview"),
                        extract_js_fn("replyPlaceholder"),
                        extract_js_fn("replyServerNote"),
                        script,
                    ]
                )
            )
        )

    def test_override_on_still_names_who_is_notified(self):
        rv, q = rec_for("review", "fix"), rec_for("review", "question")
        out = self.js(
            "ko",
            "console.log(JSON.stringify([replyPreview(%s,true,['bob@example.com'],true).text, replyPreview(%s,true,['carol@example.com'],true).text]));"
            % (json.dumps(rv), json.dumps(q)),
        )
        self.assertEqual(
            out,
            [
                "보내면 이 핀이 다시 열려 에이전트에게 가고, Bob Park에게 알림이 갑니다",
                "보내면 이 핀이 다시 열려 에이전트에게 가고, Carol Lee에게 알림이 갑니다",
            ],
        )
        en = self.js(
            "en", "console.log(JSON.stringify([replyPreview(%s,true,['bob@example.com'],true).text]));" % json.dumps(rv)
        )
        self.assertEqual(en, ["Sending reopens this pin for the agent and notifies Bob Park"])

    def test_placeholder_follows_the_outcome(self):
        rv, q, op = rec_for("review", "fix"), rec_for("review", "question"), rec_for("open", "fix")
        out = self.js(
            "ko",
            "console.log(JSON.stringify([replyPlaceholder(%s,true,false),replyPlaceholder(%s,true,true),"
            "replyPlaceholder(%s,true,false),replyPlaceholder(%s,false,false),replyPlaceholder(%s,true,false)]));"
            % tuple(json.dumps(x) for x in (rv, rv, q, rv, op)),
        )
        reopen = "무엇이 틀렸는지 적으면 다시 열려 에이전트에게 갑니다 (⌘/Ctrl+Enter 보내기)"
        plain = "답글 (⌘/Ctrl+Enter 보내기)"
        self.assertEqual(out, [reopen, plain, plain, plain, plain])

    def test_post_send_note_says_what_the_server_did(self):
        out = self.js(
            "ko",
            r"""console.log(JSON.stringify([
            replyServerNote(7,true,{ok:true,reopened:true,state:'open'}),
            replyServerNote(7,true,{ok:true,reopened:false,state:'open'}),
            replyServerNote(7,false,{ok:true,reopened:true,state:'open'}),
            replyServerNote(7,false,{ok:true,reopened:false,state:'done'})]));""",
        )
        self.assertEqual(
            out,
            [
                None,
                "#7 은 그사이 이미 열려 있어 답글로만 남았습니다",
                "#7 은 그사이 닫혀서 이 답글이 다시 열었습니다",
                None,
            ],
        )

    def test_trash_row_shows_who_and_separates_the_times(self):
        """A Trash row shows who deleted it and separates the relative time from the days left."""
        js = "\n".join(
            [
                js_i18n("ko"),
                js_icons(),
                js_esc(),
                r"""
            const T={loc:'l',restore:'s',purge:'u'}; let SHOW_ALL=false,DOCS=[],DOC='main',DEFAULT_DOC='main',META=null; const ARC_OPEN=new Set();
            function docInfo(){return null;} function authorTip(){return 'tip';} function who(a){return a?a.name:'';}
            function relSpan(s,cls,tip){return html`<span class="rt ${cls}">7시간 전</span>`;} function fmtText(t){return html`${t}`;}
            const TRASH_DAYS=30;""",
                extract_js_fn("rng"),
                extract_js_fn("multiDoc"),
                extract_js_fn("pdoc"),
                extract_js_fn("isRegion"),
                extract_js_fn("locCopy"),
                extract_js_fn("docChip"),
                extract_js_fn("arcLoc"),
                extract_js_fn("arcLine"),
                extract_js_fn("trashDaysLeft"),
                extract_js_fn("isOwner"),
                extract_js_fn("isViewer"),
                extract_js_fn("droppedCard"),
                r"""
            const h=String(droppedCard({id:4,file:'/m.tex',name:'m.tex',lo:2,hi:9,page:1,note:'메모',dropped_at:'2026-09-25 09:00:00',dropped_by:{name:'Bob Park'},expires_ts:Date.now()/1000+30*86400-60}));
            console.log(JSON.stringify([h.replace(/<svg.*?<\/svg>/g,'').replace(/<[^>]+>/g,'|').replace(/\|+/g,'|')]));""",
            ]
        )
        text = json.loads(run_node(js))[0]
        self.assertIn("7시간 전|·|Bob Park 삭제|·|30일 뒤 지워짐", text)


class ButtonStyles(unittest.TestCase):
    """Guard the secondary button styling for completed pin replies and trash restores."""

    def test_done_row_reply_and_trash_restore_are_filled_secondary(self):
        body = extract_js_fn("doneCard")
        self.assertIn('<button class="btn-sm btn-secondary arc-b b-reply" data-act="reply-open"', body)
        dc = extract_js_fn("droppedCard")
        self.assertIn('<button class="btn-sm btn-secondary arc-b b-restore" data-act="restore"', dc)
        self.assertIn('<button class="btn-sm arc-b btn-destructive b-purge" data-act="purge"', dc)


# ---------------------------------------------------------------- the section strip at the top of page 1 (v0.2.1 QA)


class SectionStrip(unittest.TestCase):
    """Exercise the section strip anchor and scroll fraction calculations."""

    def run_js(self, body):
        out = run_node(extract_js_fn("outlineIndexAt") + "\n" + extract_js_fn("destFrac") + "\n" + body)
        if out is None:
            self.skipTest("node is not installed")
        return json.loads(out)

    def test_first_section_at_the_very_top(self):
        entries = [
            {"page": 1, "frac": 0.30},
            {"page": 1, "frac": 0.55},
            {"page": 1, "frac": 0.80},
            {"page": 2, "frac": 0.10},
            {"page": 4, "frac": 0.0},
        ]
        js = (
            "const E=%s;console.log(JSON.stringify([outlineIndexAt(E,1,0),outlineIndexAt(E,1,0.56),outlineIndexAt(E,1,0.95),"
            "outlineIndexAt(E,2,0.05),outlineIndexAt(E,3,0.5),outlineIndexAt(E,4,0),outlineIndexAt([],1,0)]))"
            % json.dumps(entries)
        )
        self.assertEqual(self.run_js(js), [0, 1, 2, 2, 3, 4, -1])

    def test_dest_top_to_fraction(self):
        js = (
            "console.log(JSON.stringify([destFrac([{},{name:'XYZ'},72,792,0],792),destFrac([{},{name:'XYZ'},72,396,0],792),"
            "destFrac([{},{name:'Fit'}],792),destFrac([{},{name:'XYZ'},0,null,0],792),destFrac([{},{name:'XYZ'},0,900,0],792)]))"
        )
        self.assertEqual(self.run_js(js), [0, 0.5, 0, 0, 0])


if __name__ == "__main__":
    unittest.main()

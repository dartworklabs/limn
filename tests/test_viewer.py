"""The viewer page (src/limn/viewer): its scripts run under node, its HTML and CSS read as the page the server serves
(ps.HTML), and its layout measured in a real Chromium.

Most classes check the served page for the fixed pattern and the absence of the old bug pattern. The ...Logic classes
pull pure functions out of the page with extract_js_fn and run them under node (skipped without node).
FrontendResponsiveBrowser drives Chromium ($LIMN_CHROMIUM, then a system Chrome/Chromium, then Playwright's bundled one;
skipped when none starts, a failure under LIMN_TEST_REQUIRE_BROWSER=1). How the page is assembled from its parts is
tests/test_viewer_files.py and tests/test_viewer_assemble.py; input and gestures are tests/test_viewer_input.py.

Run: uv run pytest tests/test_viewer.py
"""
import json
import os
import re
import shutil
import unittest
from pathlib import Path

from limn.pins import position, render as md_render
from limn.viewer import assemble as viewer_assemble

from helpers import DOCS_DIR, PKG, SKILL_KO, SKILL_MD, extract_js_fn, js_icons, js_thread, ps, run_node

# ---------------------------------------------------------------- frontend pure logic (run the real source under node)
#
# The server only uses the standard library and 127.0.0.1, but these tests run the client JS as-is under
# node for regression verification (they don't change the server itself). Skipped in environments without node.

class FrontendLogic(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_is_estimated_draws_server_est_only_regardless_of_timezone(self):
        # design 1: the viewer draws the est the server gave it as-is — it never re-judges via timezone/edited_at/sync.
        js = "\n".join([
            extract_js_fn("isEstimated"),
            r"""
            const out=[isEstimated({est:true}), isEstimated({est:false,sync:'moved +3',at:'2026-01-01 00:00:00'}),
                       isEstimated({}), isEstimated({est:'true'})];
            console.log(JSON.stringify(out));
            """,
        ])
        seoul = json.loads(run_node(js, tz="Asia/Seoul"))
        ny = json.loads(run_node(js, tz="America/New_York"))
        self.assertEqual(seoul, [True, False, False, False])
        self.assertEqual(seoul, ny)

    def test_sel_rel_matches_python_selection_rel(self):
        # design 2: the viewer recounts overlaps every time the range changes, without a round trip to the server — the rule must match the server's.
        cases = [(lo, hi, 4, 7) for lo in range(1, 10) for hi in range(lo, 11)]
        js = "\n".join([extract_js_fn("selRel"),
                        "console.log(JSON.stringify(%s.map(c=>selRel(c[0],c[1],c[2],c[3]))));" % json.dumps(cases)])
        got = json.loads(run_node(js))
        self.assertEqual(got, [position.selection_rel(*c) for c in cases])

    def test_overlaps_for_filters_by_file_and_skips_done(self):
        js = "\n".join([extract_js_fn("selRel"), extract_js_fn("overlapsFor"), r"""
            const PINS=[{id:1,file:'/a.tex',lo:4,hi:9},{id:2,file:'/b.tex',lo:4,hi:9},{id:3,file:'/a.tex',lo:4,hi:9,done:true},
                        {id:4,file:'/a.tex',lo:5,hi:5},{id:5,file:'/a.tex',lo:20,hi:30}];
            console.log(JSON.stringify(overlapsFor({file:'/a.tex',lo:4,hi:9},PINS)));
            """])
        self.assertEqual(json.loads(run_node(js)),
                         [{"id": 1, "lo": 4, "hi": 9, "rel": "equal"}, {"id": 4, "lo": 5, "hi": 5, "rel": "contains"}])

    def test_pick_overlap_priority_equal_inside_contains_partial(self):
        js = "\n".join([
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
        ])
        self.assertEqual(json.loads(run_node(js)), [6, 2, 2, 7, 8])

    def test_overlap_banner_follows_level_change_and_dismiss_resets(self):
        # must-1 live path: drag (default level = env, wraps the pin) -> switch to [paragraph] level to
        # match an existing pin's range -> the banner switches to "same range". [Save as separate pin]
        # only turns off that relation and comes back on a fresh drag (pick's reset).
        js = "\n".join([
            r"""
            const box={hidden:true,dataset:{},innerHTML:''};
            const $=s=>box;
            let CUR=null, PINS=[{id:5,file:'/m.tex',lo:405,hi:406}];
            """,
            extract_js_fn("selRel"), extract_js_fn("overlapsFor"), extract_js_fn("pickOverlap"),
            extract_js_fn("josa"), extract_js_fn("overlapText"), "let OVERLAP_DISMISSED=null;", extract_js_fn("recomputeOverlap"),
            extract_js_fn("renderOverlapBanner"), extract_js_fn("lvOf"), extract_js_fn("useLevel"),
            r"""
            const out=[];
            CUR={file:'/m.tex',lo:401,hi:413,levels:[{level:'para',lo:405,hi:406},{level:'env',lo:401,hi:413}]};
            recomputeOverlap(); renderOverlapBanner(); out.push([box.hidden, box.dataset.rel]);
            useLevel(CUR,'para'); recomputeOverlap(); renderOverlapBanner(); out.push([box.hidden, box.dataset.rel, /같은 범위/.test(box.innerHTML)]);
            OVERLAP_DISMISSED='5:equal'; renderOverlapBanner(); out.push([box.hidden]);
            useLevel(CUR,'env'); recomputeOverlap(); renderOverlapBanner(); out.push([box.hidden, box.dataset.rel]);   // 관계가 바뀌면 다시 알림
            OVERLAP_DISMISSED=null;                        // pick() 의 리셋(새 선택)
            useLevel(CUR,'para'); recomputeOverlap(); renderOverlapBanner(); out.push([box.hidden, box.dataset.rel]);
            console.log(JSON.stringify(out));
            """,
        ])
        out = json.loads(run_node(js))
        self.assertEqual(out[0], [False, "contains"])
        self.assertEqual(out[1], [False, "equal", True])
        self.assertEqual(out[2], [True])
        self.assertEqual(out[3], [False, "contains"])
        self.assertEqual(out[4], [False, "equal"])

    def test_poll_build_single_flight_and_once_per_seq(self):
        # design 4: pollBuild is single-flight — no matter how many times it's called concurrently,
        # /api/build fires once and completion (one seq) is handled once. A freshly opened tab shows an
        # already-failed build in the panel only, with no toast.
        js = "\n".join([
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
            let BUILD_TIMER=null,LAST_BUILD_ERR=null,LAST_BUILD_SEQ=3,BUILD_BOOTED=false,BUILD_INFLIGHT=null;
            // 여러 문서(§Multiple documents) 전역 — 단일 문서 뷰어와 같은 값
            const DOC='main', DOC_SEQ=new Map(), BUILD_ERR_BY=new Map(); function dq(u){return u;}
            """,
            extract_js_fn("buildChipText"), extract_js_fn("pullSuffix"), extract_js_fn("pollBuild"),
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
        ])
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
        js = "\n".join([
            extract_js_fn("josa"), extract_js_fn("relBadge"),
            r"""
            const PINS=[{id:1,lo:1,hi:100},{id:2,lo:10,hi:20},{id:3,lo:5,hi:50}];
            // rel 배열은 실제 서버 순서를 흉내내 일부러 '가장 작은 것'을 뒤에 둔다.
            const rel=[{id:1,rel:'inside'},{id:3,rel:'inside'},{id:2,rel:'inside'}];
            console.log(JSON.stringify(relBadge(rel)));
            """,
        ])
        out = json.loads(run_node(js))
        self.assertEqual(out["id"], 2)     # id=2 (range 10-20, length 11) is the smallest outer pin

        # compare the same rule with the same by_id on the Python side (rel_badge, pins.md).
        by_id = {1: {"lo": 1, "hi": 100}, 2: {"lo": 10, "hi": 20}, 3: {"lo": 5, "hi": 50}}
        rel = [{"id": 1, "rel": "inside"}, {"id": 3, "rel": "inside"}, {"id": 2, "rel": "inside"}]
        self.assertEqual(md_render.rel_badge(rel, by_id), "#2 범위 안")

    def test_jump_to_card_sets_cur_and_clears_highlight_after_timeout(self):
        # bug: clicking the badge only added .flash (no .cur), and since the box-shadow was static, the highlight never went away.
        js = "\n".join([
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
        ])
        out = json.loads(run_node(js))
        self.assertEqual(out["mid"], [True, True])     # right after clicking: both .cur and .flash are present
        self.assertEqual(out["after"], [False, False])  # after 1.2s: the highlight clears (static box-shadow bug fixed)

    def test_diff_toast_distinguishes_dropped_from_closed(self):
        # §A: the old implementation reported every pin that disappeared from the open list as "done" —
        # even a pin a coauthor dropped showed up on the author's screen as '#N 이 완료되었습니다' (observed).
        # id 2 is dropped because it's absent from d (open+closed) entirely; id 3 is done because it's in d with done:true.
        js = "\n".join([
            r"""
            function who(a){return (a&&(a.name||a.login))||'';}
            const TOASTS=[]; const RESTORED=[];
            function toast(msg,kind,action){TOASTS.push({msg,kind,hasAction:!!action});}
            function restorePin(id){RESTORED.push(id);}
            const MY_ACTIONS=new Map();
            """,
            extract_js_fn("markMine"),
            extract_js_fn("consumeMine"),
            extract_js_fn("diffToast"),
            r"""
            const prev=[{id:1},{id:2},{id:3}];
            const d=[{id:1,done:false},{id:3,done:true}];
            const dropped=[{id:2,dropped_by:{name:'Bob'}}];
            diffToast(prev,d,dropped);
            console.log(JSON.stringify(TOASTS));
            """,
        ])
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
        self.assertTrue(dropped[0]["hasAction"])          # the [되살리기] (restore) action is attached

    def test_diff_toast_dropped_action_calls_restore_pin(self):
        js = "\n".join([
            r"""
            function who(a){return (a&&(a.name||a.login))||'';}
            let CAPTURED=null; const RESTORED=[];
            function toast(msg,kind,action){if(action)CAPTURED=action;}
            function restorePin(id){RESTORED.push(id);}
            const MY_ACTIONS=new Map();
            """,
            extract_js_fn("markMine"),
            extract_js_fn("consumeMine"),
            extract_js_fn("diffToast"),
            r"""
            diffToast([{id:9}],[],[{id:9,dropped_by:{login:'x'}}]);
            CAPTURED.fn();
            console.log(JSON.stringify(RESTORED));
            """,
        ])
        self.assertEqual(json.loads(run_node(js)), [9])

    def test_diff_toast_unknown_dropper_falls_back_to_generic_label(self):
        js = "\n".join([
            r"""
            function who(a){return (a&&(a.name||a.login))||'';}
            const TOASTS=[]; function toast(msg,kind,action){TOASTS.push(msg);}
            function restorePin(id){}
            const MY_ACTIONS=new Map();
            """,
            extract_js_fn("markMine"),
            extract_js_fn("consumeMine"),
            extract_js_fn("diffToast"),
            r"""
            diffToast([{id:5}],[],[]);   // dropped 목록에도 없음(폴링 경합) — 그래도 삭제로는 알린다
            console.log(JSON.stringify(TOASTS));
            """,
        ])
        out = json.loads(run_node(js))
        self.assertEqual(len(out), 1)
        self.assertIn("#5 을", out[0])
        self.assertIn("삭제함", out[0])

    def test_diff_toast_suppresses_own_recent_action_but_not_others(self):
        # bug: a pin the same tab just closed or dropped would also flow straight through diffToast
        # without markMine, doubling up with the local toast. An id marked via markMine(id) should be
        # swallowed exactly once; an unmarked id (= done by another tab) must still be reported.
        js = "\n".join([
            r"""
            function who(a){return (a&&(a.name||a.login))||'';}
            const TOASTS=[]; function toast(msg,kind,action){TOASTS.push(msg);}
            function restorePin(id){}
            const MY_ACTIONS=new Map();
            """,
            extract_js_fn("markMine"),
            extract_js_fn("consumeMine"),
            extract_js_fn("diffToast"),
            r"""
            markMine(1); markMine(2);   // 이 탭이 방금 #1 을 완료, #2 를 삭제했다
            const prev=[{id:1},{id:2},{id:3},{id:4}];
            const d=[{id:1,done:true},{id:3,done:true}];   // #2,#4 는 d 에 없음=삭제
            const dropped=[{id:2,dropped_by:{login:'me'}},{id:4,dropped_by:{name:'Coauthor'}}];
            diffToast(prev,d,dropped);
            console.log(JSON.stringify(TOASTS));
            """,
        ])
        out = json.loads(run_node(js))
        joined = " | ".join(out)
        self.assertNotIn("#1", joined)                 # own action — suppressed
        self.assertNotIn("#2", joined)                  # own action — suppressed
        self.assertIn("#3 이 완료되었습니다", joined)     # another tab's completion — shown as-is
        self.assertTrue(any("#4" in t and "삭제함" in t and "Coauthor" in t for t in out))  # another tab's drop — shown as-is


# ---------------------------------------------------------------- frontend structure (source-string inspection)
#
# Running the full polling loop and automatic panel display, which spans timers, fetch, and visibility,
# under node would require faking fetch/document.hidden/setInterval entirely (this project's hard
# constraint is stdlib-only, so we can't add such a shim to the server) — so instead we check the actual
# deployed ps.HTML source string for the fixed pattern and the absence of the pre-fix pattern. This isn't
# execution verification, but it does catch regressions (reverting to the original bug pattern).

class FrontendStructure(unittest.TestCase):
    def test_build_polling_is_conditional_not_permanent(self):
        # bug: startBuildPolling() used to unconditionally set setInterval(pollBuild,1000), calling
        # /api/build every second even when the tab was hidden or there was nothing to do.
        m = re.search(r"function startBuildPolling\(\)\{(.*?)\n\}", ps.HTML, re.S)
        self.assertIsNotNone(m)
        self.assertNotIn("setInterval(pollBuild", m.group(1))
        self.assertIn("pollBuild()", m.group(1))
        m1 = re.search(r"\nfunction pollBuild\(\)\{(.*?)\n\}", ps.HTML, re.S)
        self.assertIn("if(document.hidden)returnPromise.resolve()", m1.group(1).replace(" ", ""))
        self.assertIn("if(BUILD_INFLIGHT)returnBUILD_INFLIGHT", m1.group(1).replace(" ", ""))
        m2 = re.search(r"async function pollBuildOnce\(\)\{(.*?)\n\}", ps.HTML, re.S)
        body = m2.group(1)
        self.assertIn("if(!BUILD_TIMER)BUILD_TIMER=setInterval(pollBuild,1000)", body.replace(" ", ""))
        self.assertIn("clearInterval(BUILD_TIMER)", body)

    def test_light_poll_kicks_off_build_polling_when_running_or_seq_changed(self):
        m = re.search(r"async function pollLightOnce\(\)\{(.*?)\n\}", ps.HTML, re.S)
        body = m.group(1).replace(" ", "")
        self.assertIn("d.build&&d.build.state==='running'", body)
        self.assertIn("d.build_seq!==LAST_BUILD_SEQ", body)
        self.assertIn("pollBuild()", body)

    def test_light_poll_is_single_flight(self):
        # bug: when visibilitychange and focus overlapped, pollLight() would call /api/meta·loadPins
        # fresh each time, firing loadPins up to 3 times. It needs the same single-flight pattern as pollBuild.
        m = re.search(r"\nfunction pollLight\(\)\{(.*?)\n\}", ps.HTML, re.S)
        self.assertIsNotNone(m)
        body = m.group(1).replace(" ", "")
        self.assertIn("if(document.hidden)returnPromise.resolve()", body)
        self.assertIn("if(LIGHT_INFLIGHT)returnLIGHT_INFLIGHT", body)
        self.assertIn("LIGHT_INFLIGHT=pollLightOnce()", body)

    def test_build_err_reopen_affordance_exists(self):
        self.assertIn('id="build-err-chip"', ps.HTML)
        self.assertIn('data-act="build-err-reopen"', ps.HTML)
        self.assertIn("case 'build-err-reopen'", ps.HTML)
        self.assertIn("function hideBuildErr()", ps.HTML)
        self.assertIn("case 'err-close':hideBuildErr()", ps.HTML)

    def test_doc_menu_closes_even_when_switch_doc_is_synchronous_and_cached(self):
        # regression: when switchDoc() runs synchronously through drawDocTabs->drawDocsMenu for a cached
        # document, it redraws the open #docs-menu, detaching the clicked <a> from the DOM. Calling
        # a.closest() after switchDoc() then returns null and the menu stays open — inMenu must always
        # be determined *before* calling switchDoc().
        m = re.search(r"case 'doc':\{(.*?)\}", ps.HTML, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        js = ("""
            (async()=>{
              const out={};
              const docsMenu={closed:false,close(){this.closed=true;}};
              function $(sel){return sel==='#docs-menu'?docsMenu:{};}
              let detached=false;
              function switchDoc(k){detached=true;}   // 캐시된 문서: 동기로 끝나며 a 를 떼어낸 것을 흉내
              const a={dataset:{doc:'ms'},closest(sel){return (!detached&&sel==='#docs-menu')?{}:null;}};
              switch('doc'){case 'doc':{%s}}
              out.closed=docsMenu.closed;
              console.log(JSON.stringify(out));
            })();
            """ % body)
        out = run_node(js)
        if out is None:
            self.skipTest("node not available")
        data = json.loads(out)
        self.assertTrue(data["closed"], "#docs-menu must close even when the selected document is cached")

    def test_pick_resets_overlap_dismissed_and_recounts(self):
        m = re.search(r"async function pick\(r\)\{(.*?)\n\}", ps.HTML, re.S)
        body = m.group(1)
        cur_idx = body.index("CUR=d;")
        self.assertGreater(body.index("OVERLAP_DISMISSED=null"), cur_idx)
        self.assertGreater(body.index("CUR.overlaps=overlapsFor(CUR,PINS)"), cur_idx)

    def test_level_and_nudge_recount_overlap_only_for_composer(self):
        for act in ("level", "nudge"):
            m = re.search(r"case '%s':\{(.*?)\}\s*\n" % act, ps.HTML)
            self.assertIsNotNone(m)
            self.assertIn("if(!inEdit)recomputeOverlap()", m.group(1).replace(" ", ""))

    def test_pdf_build_travels_drag_to_pick_to_save_and_repick(self):
        self.assertIn("pdf_build:META.pages_build", ps.HTML)                  # drag -> /api/pick
        self.assertIn("quote:d.quote,pdf_build:d.pdf_build", ps.HTML)         # pick response -> /api/pin
        self.assertIn("frac:c.frac,pdf_build:c.pdf_build", ps.HTML)           # relocate -> loc

    def test_no_wall_clock_estimate_left_in_viewer(self):
        self.assertNotIn("pinAtEpoch", ps.HTML)
        self.assertNotIn("frac_build", ps.HTML)
        self.assertNotIn("LAST_SEEN_BUILD", ps.HTML)

    def test_trash_ui_exists(self):
        # §B, v0.2.2: deleted pins live in the Trash dialog ([⋯] -> 휴지통 N, or the link under the list) with a restore button -
        # not in a section of the list.
        self.assertIn('<dialog id="trash"', ps.HTML)
        self.assertIn('id="trash-list"', ps.HTML)
        self.assertIn("case 'trash-open':openTrash();break;", ps.HTML)
        self.assertNotIn('id="dropped-toggle"', ps.HTML)
        self.assertIn("function droppedCard(", ps.HTML)
        self.assertIn("data-act=\"restore\"", ps.HTML)
        self.assertIn("case 'restore':restorePin(id)", ps.HTML)

    def test_load_pins_fetches_dropped_list_for_diff_and_panel(self):
        m = re.search(r"async function loadPins\(\)\{(.*?)\n\}", ps.HTML, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn("/api/pins/dropped", body)
        self.assertIn("DROPPED=dropped", body)
        self.assertIn("diffToast(prevOpen,d,dropped)", body)

    def test_draw_pins_counts_the_trash(self):
        body = extract_js_fn("drawPins")
        self.assertIn("LDROP.filter(p=>!PURGING.has(p.id)).length", body)   # LDROP = listDropped() (current document or all documents)
        self.assertIn("tl('휴지통 {n}',{n:nTrash})", body)
        self.assertIn("if($('#trash').open)drawTrash();", body)
        self.assertIn("map(droppedCard)", extract_js_fn("drawTrash"))

    def test_done_card_shows_close_reply_and_ref(self):
        # §C: a closed card shows the reply/ref left at close time (both go through esc).
        m = re.search(r"function doneCard\(p\)\{(.*?)\n\}", ps.HTML, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn("p.close_ref", body)
        self.assertIn("p.close_reply", body)
        self.assertIn("arcLine('r:'+p.id,p.close_reply", body)        # the reply line is drawn by arcLine, going through esc
        self.assertIn("fmtText(text,logins)", extract_js_fn("arcLine"))   # fmtText goes through esc first
        self.assertIn("esc(p.close_ref)", body)

    def test_close_curl_example_in_skill_md_documents_reply_and_ref(self):
        # whether the close example in SKILL.md's '핀 소비 절차' section was updated to leave reply/ref (§C).
        skill = SKILL_MD.read_text(encoding="utf-8")
        self.assertIn('"reply"', skill)
        self.assertIn('"ref"', skill)
        self.assertIn("/close", skill)


# ---------------------------------------------------------------- viewer structure — claim UI · log=1

class FrontendClaimUI(unittest.TestCase):
    def test_claim_badge_and_unclaim_button_wired(self):
        self.assertIn("function claimActive(", ps.HTML)
        self.assertIn("function claimLabel(", ps.HTML)
        self.assertIn('data-act="unclaim"', ps.HTML)
        self.assertIn("case 'unclaim':unclaimPin(id)", ps.HTML)
        self.assertIn("function unclaimPin(", ps.HTML)
        self.assertIn("/api/pins/'+id+'/unclaim'", ps.HTML)

    def test_no_claim_button_offered_to_viewer(self):
        # the viewer never claims (agent-only) — there must be no 'claim' action button.
        self.assertNotIn('data-act="claim"', ps.HTML)

    def test_build_status_fetch_requests_full_log(self):
        self.assertIn("/api/build?log=1", ps.HTML)

    def test_pull_chip_and_toast_wiring(self):
        self.assertIn("원격 main 당겨오는 중", ps.HTML)
        self.assertIn("function pullSuffix(", ps.HTML)
        self.assertIn("pullSuffix(b)", ps.HTML)


# Mobile (Galaxy Z Fold 7 etc.) — docs/handbook/viewer.md §모바일 레이아웃. Measured live with Playwright; here we
# check that the deployed HTML has the required elements/copy/CSS/event paths, and run the pure-logic
# functions under node.
class FrontendMobileStructure(unittest.TestCase):
    def test_viewport_meta_allows_zoom_and_handles_keyboard_and_notch(self):
        m = re.search(r'<meta name="viewport" content="([^"]*)"', ps.HTML)
        self.assertIsNotNone(m)
        v = m.group(1)
        for part in ("width=device-width", "initial-scale=1", "viewport-fit=cover", "interactive-widget=resizes-content"):
            self.assertIn(part, v)
        # pinch-zoom is not blocked — you need to zoom to read the manuscript
        self.assertNotIn("user-scalable=no", v)
        self.assertNotIn("maximum-scale", v)

    def test_rebuild_label_is_short_everywhere(self):
        self.assertIn('data-act="rebuild"', ps.HTML)
        self.assertRegex(ps.HTML, r'id="btn-rebuild"[^>]*aria-label="PDF 재빌드"[^>]*><svg class="ic ic-refresh-cw"[^>]*>(?:(?!</svg>).)*</svg><span class="lbl">PDF 재빌드</span></button>')
        self.assertNotIn("다시 만들기", ps.HTML)
        self.assertNotIn("다시 만들기", Path(ps.__file__).read_text(encoding="utf-8"))
        for doc in [SKILL_MD, SKILL_KO] + sorted(DOCS_DIR.glob("*.md")):
            self.assertFalse("PDF 다시 만들기" in doc.read_text(encoding="utf-8"), doc.name)

    def test_compact_toolbar_elements_and_more_menu(self):
        for el in ('id="btn-side"', 'id="side-n"', 'id="btn-select"', 'id="btn-more"', '<dialog id="more"',
                   'id="coach"', 'id="more-info"', 'id="m-theme"', 'id="m-done"', 'id="m-trash"', 'id="m-jump"'):
            self.assertIn(el, ps.HTML)
        self.assertIn('aria-pressed="false"', re.search(r'<button id="btn-select"[^>]*>', ps.HTML).group(0))
        # less important buttons are hidden in compact mode (.sec) and live inside [⋯] with the same data-act
        for bid, act in (("btn-reload", "reload"), ("btn-zoom-out", "zoom-out"), ("btn-zoom-in", "zoom-in"),
                         ("btn-fit", "fit"), ("btn-theme", "theme"), ("btn-help", "help")):
            tag = re.search(r'<button id="%s"[^>]*>' % bid, ps.HTML).group(0)
            self.assertRegex(tag, r'class="sec( btn-[a-z]+)*"')
            more = ps.HTML[ps.HTML.index('<dialog id="more"'):ps.HTML.index('<dialog id="help"')]
            self.assertIn('data-act="%s"' % act, more)
        self.assertRegex(ps.HTML, r'<input class="n sec" id="jump"')
        self.assertIn("body.compact .sec{display:none}", ps.HTML)
        for act in ("side", "selmode", "more", "more-close", "m-jump", "coach-close", "card-toggle"):
            self.assertIn("case '%s':" % act, ps.HTML)

    def test_touch_css_targets_inputs_safe_area_and_selection_touch_action(self):
        """Touch CSS: 44px controls, 16px inputs, safe areas, and exactly which rules set touch-action (PDF, grips, panel, sheet bar)."""
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        coarse = css[css.index("@media (pointer:coarse){"):]
        coarse = coarse[:coarse.index("\n}")]
        self.assertIn("min-height:44px", coarse)
        self.assertIn("input,textarea,select{font-size:var(--text-xl)}", coarse)   # prevents iOS zoom-in — 16px or larger
        self.assertIn("--text-xl:16px", css)
        self.assertIn("env(safe-area-inset-bottom)", css)
        self.assertIn("var(--kb,0px)", css)
        # touch-action: the PDF area (#left) allows only scroll and blocks browser pinch (two fingers do
        # app-level zoom, §PDF 영역 전용 확대). A page in selection mode is none (one-finger drag = select).
        # The width/height grips are none so they don't fight scroll while dragging. The panel is pan-y pinch-zoom
        # (a horizontal drag stays a pointer stream for the overlay's swipe; pinch keeps the browser's zoom), and
        # the narrow sheet's tool bar is none - the whole bar drags the sheet (input review 2026-09-26).
        css_nc = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        self.assertEqual([x.strip() for x in re.findall(r"([^{}]*)\{[^{}]*touch-action", css_nc)],
                     ["#left", "#outline-grip", "#grip", "#right", "body.selmode .pg", "body.lay-narrow #sheet-grip", "body.lay-narrow #bar1"])
        self.assertRegex(css_nc, r"\n#right\{[^}]*touch-action:pan-y pinch-zoom\}")
        self.assertRegex(css_nc, r"\n#left\{[^}]*touch-action:pan-x pan-y\}")
        self.assertIn("body.selmode .pg{touch-action:none", css)
        self.assertNotIn("touch-action:pinch-zoom", css)
        # toasts move to a spot that doesn't overlap the sheet/panel toolbar row
        self.assertIn("body.lay-narrow #toasts{", css)
        self.assertIn("body.lay-mid #toasts{", css)

    def test_selection_uses_pointer_events_one_path(self):
        self.assertIn("$('#doc').addEventListener('pointerdown'", ps.HTML)
        for ev in ("pointermove", "pointerup", "pointercancel"):
            self.assertIn("window.addEventListener('%s'" % ev, ps.HTML)
        self.assertIn("if(mouse||SELMODE)", ps.HTML)            # mouse still drags like before, regardless of mode
        self.assertIn("if(!e.isPrimary){cancelDrag()", ps.HTML)  # a second finger (pinch) drops the selection
        self.assertNotIn("window.addEventListener('mouseup',e=>{if(!DRAG)", ps.HTML)   # no old mouse-only path remains
        self.assertIn("function quickPick(", ps.HTML)
        self.assertIn("LONGPRESS_MS", ps.HTML)

    def test_touch_does_not_autofocus_note_or_pop_hover_tips(self):
        m = re.search(r"async function pick\(r\)\{(.*?)\n\}", ps.HTML, re.S)
        self.assertIn("if(LAST_PTR==='mouse')$('#note').focus(", m.group(1))
        self.assertIn("if(touchRecent()||MQ_NOHOVER.matches)return; armTip(", ps.HTML)
        # devices without hover don't show the focus tooltip either (QA phone: the tooltip stayed stuck over the list after a tap). The card as a whole gets no tooltip.
        self.assertIn("||touchRecent()||MQ_NOHOVER.matches){if(Date.now()>=SWALLOW_CLICK)hideTip();return;}", ps.HTML)
        self.assertNotIn('data-doc="\'+esc(pdoc(p))+\'" data-tip="\'+tip+\'"', extract_js_fn("card"))
        self.assertIn("document.addEventListener('contextmenu'", ps.HTML)

    def test_keyboard_and_resize_hooks(self):
        self.assertIn("visualViewport.addEventListener('resize',onViewport)", ps.HTML)
        self.assertIn("new ResizeObserver(", ps.HTML)
        m = re.search(r"\nfunction relayout\(\)\{(.*?)\}\n", ps.HTML, re.S)
        self.assertIn("topAnchor()", m.group(1))
        self.assertIn("restoreAnchor(a)", m.group(1))

    def test_page_images_lazy(self):
        self.assertIn('<img loading="lazy"', ps.HTML)


# Vector rendering (docs/handbook/viewer.md §벡터 렌더링) — checks the deployed HTML for the PDF.js path, fallback, visible-area rendering, and the pixel cap.
class FrontendVector(unittest.TestCase):
    def fn(self, name):
        m = re.search(r"\n(?:async )?function %s\([^)]*\)\{(.*?)\n\}" % name, ps.HTML, re.S)
        self.assertIsNotNone(m, name)
        return m.group(1)

    def test_loads_vendored_pdfjs_same_origin_with_version(self):
        self.assertNotIn("__PDFJS_VERSION__", ps.HTML)
        self.assertIn("const PDFJS_V='%s'" % viewer_assemble.PDFJS_VERSION, ps.HTML)
        self.assertIn("import('/vendor/pdfjs/pdf.min.mjs?v='+PDFJS_V)", ps.HTML)
        self.assertIn("workerSrc='/vendor/pdfjs/pdf.worker.min.mjs?v='+PDFJS_V", ps.HTML)
        for cdn in ("cdn.jsdelivr", "unpkg.com", "cdnjs", "mozilla.github.io/pdf.js/build"):
            self.assertNotIn(cdn, ps.HTML)                   # runs only inside the tailnet — no external CDN
        self.assertIn("isEvalSupported:false", ps.HTML)
        self.assertIn("useWasm:false", ps.HTML)              # wasm isn't in vendor (vendor/pdfjs/README.md)

    def test_pdf_is_the_screen_build(self):
        body = self.fn("vecOpen")
        self.assertIn("'/pdf?build='+encodeURIComponent(build)", body)
        self.assertIn("build=META.pages_build", body)
        self.assertIn("doc.numPages!==n", body)                 # not used if the page count differs
        # close the old document after a rebuild. PDFDocumentProxy has no destroy (observed: 'old.destroy is not a function').
        self.assertIn("vecClose(old)", body)
        self.assertIn("doc.loadingTask.destroy()", self.fn("vecClose"))
        self.assertNotRegex(ps.HTML, r"\b(doc|old|VEC\.doc)\.destroy\(")

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
        self.assertIn("RenderingCancelledException", run)       # a cancellation is not a failure
        self.assertIn("vecFail('쪽을 그리지 못했습니다'", run)
        fail = self.fn("vecFail")
        self.assertIn("vecReleaseAll()", fail)                  # removing the canvas reveals the PNG underneath
        self.assertIn("$('#vec-chip')", fail)
        self.assertIn('id="vec-chip" class="badge badge-warning" hidden', ps.HTML)
        self.assertIn('<img loading="lazy"', ps.HTML)          # PNG remains as the first paint / fallback
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn(".pg.drawn>img{visibility:hidden}", css)
        self.assertIn(".pg>canvas{position:absolute;display:block;pointer-events:none}", css)   # .pg receives the drag

    def test_visible_pages_only_and_release(self):
        obs = self.fn("vecObserve")
        self.assertIn("new IntersectionObserver(", obs)
        self.assertIn("root:$('#left'),rootMargin:VEC_KEEP", obs)
        self.assertIn("vecRelease(n)", obs)
        self.assertIn("cv.width=0; cv.height=0", self.fn("vecDrop"))
        self.assertIn("vecObserve()", self.fn("buildDoc"))
        ref = self.fn("refreshDoc")
        self.assertIn("vecReleaseAll()", ref)                   # canvases drawn from the old PDF are removed
        self.assertIn("vecOpen()", ref)                         # reopen the PDF from the new build
        self.assertIn("vecInvalidate()", self.fn("setW"))       # redraw when the zoom changes

    def test_no_text_layer(self):
        for s in ("getTextContent", "TextLayer", "textLayer"):
            self.assertNotIn(s, ps.HTML)


class FrontendVectorLogic(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_backing_size_is_css_times_k_until_the_pixel_cap(self):
        js = "\n".join([
            extract_js_fn("vecTarget"),
            "const cap=16777216; const out=[];",
            "for(const [cw,ch,k] of [[898,1270,2],[370,523,2.6],[1796,2540,2],[3592,5080,2],[4490,6350,2]]){",
            "  const t=vecTarget(cw,ch,k,cap); out.push([t.bw,t.bh,t.capped,t.bw*t.bh<=cap,+(t.bw/(cw*k)).toFixed(3)]);}",
            "console.log(JSON.stringify(out));",
        ])
        out = json.loads(run_node(js))
        self.assertEqual(out[0][:3], [1796, 2540, False])
        self.assertEqual(out[1][:3], [962, 1360, False])
        for row in out[:2]:
            self.assertGreaterEqual(row[4], 1.0)               # within the cap, it's at least CSS x DPR
        for row in out[2:]:                                    # 1796x2540 CSS x DPR 2 = 18.2M pixels > 16.8M
            self.assertTrue(row[2])                            # scaled down past the cap (the detail canvas fills the visible area)
            self.assertTrue(row[3])

    def test_vecopen_stale_doc_not_touched_while_new_pdf_is_fetching(self):
        # reproducing the observed case: if vecOpen is called for a new 27-page document while VEC.doc
        # still points at the old document (1 page), VEC.doc must be null before the fetch finishes
        # (so vecNextJob can't pull any work), and a vecRun queued in the meantime must not call the old
        # doc.getPage (it throws here if it does).
        js = "\n".join([
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
        ])
        out = json.loads(run_node(js))
        self.assertNotIn("error", out, out)
        self.assertTrue(out["docNulledBeforeFetch"])
        self.assertTrue(out["oldClosedImmediately"])
        self.assertTrue(out["noJobWhileDocNull"])
        self.assertTrue(out["newDocInstalled"])

    def test_detail_region_cover_check(self):
        js = "\n".join([
            extract_js_fn("vecCovers"),
            "const reg={x:0.1,y:0.2,w:0.5,h:0.3}; const out=[];",
            "out.push(vecCovers(reg,{x:100,y:200,w:500,h:300,cw:1000,ch:1000}));",
            "out.push(vecCovers(reg,{x:150,y:250,w:100,h:100,cw:1000,ch:1000}));",
            "out.push(vecCovers(reg,{x:50,y:250,w:100,h:100,cw:1000,ch:1000}));",
            "out.push(vecCovers(reg,{x:150,y:250,w:100,h:300,cw:1000,ch:1000}));",
            "out.push(vecCovers(null,{x:0,y:0,w:1,h:1,cw:10,ch:10}));",
            "console.log(JSON.stringify(out));",
        ])
        self.assertEqual(json.loads(run_node(js)), [True, True, False, False, False])


# PDF-area-only zoom (docs/handbook/viewer.md §PDF 영역 전용 확대) — whether browser zoom input is intercepted to change only the page width.
class FrontendZoom(unittest.TestCase):
    def test_ctrl_wheel_on_pdf_area_is_intercepted_non_passive(self):
        self.assertIn("L.addEventListener('wheel',e=>{if(!(e.ctrlKey||e.metaKey))return; e.preventDefault();", ps.HTML)
        i = ps.HTML.index("L.addEventListener('wheel'")
        self.assertIn("{passive:false}", ps.HTML[i:i + 300])
        self.assertIn("const L=$('#left')", ps.HTML[i - 200:i])     # PDF area only — sidebar wheel scrolling is left alone
        self.assertIn("zoomTo(W*f,pt[0],pt[1])", ps.HTML)            # anchored to the pointer

    def test_safari_gesture_and_touch_pinch(self):
        for ev in ("gesturestart", "gesturechange", "gestureend", "touchstart", "touchmove", "touchend", "touchcancel"):
            self.assertIn("L.addEventListener('%s'" % ev, ps.HTML)
        i = ps.HTML.index("L.addEventListener('touchstart'")
        blk = ps.HTML[i:i + 400]
        self.assertIn("e.touches.length!==2", blk)
        self.assertIn("cancelDrag(); cancelLP();", blk)            # a pinch discards the in-progress selection/long-press
        self.assertIn("{passive:false}", blk)

    def test_keyboard_zoom_skips_inputs(self):
        m = re.search(r"document\.addEventListener\('keydown',e=>\{(.*?)\n\}\);", ps.HTML, re.S)
        body = m.group(1)
        self.assertIn("if((e.ctrlKey||e.metaKey)&&!e.altKey&&!inField){const z=zoomKey(e);", body)
        self.assertIn("e.preventDefault(); if(z==='fit')fitW(); else zoom(z==='in'?1:-1)", body)
        self.assertLess(body.index("inField="), body.index("zoomKey(e)"))

    def test_zoom_bounds_and_anchor(self):
        self.assertIn("const ZOOM_MIN=0.5,ZOOM_MAX=5", ps.HTML)
        setw = re.search(r"\nfunction setW\(w,save\)\{(.*?)\}\n", ps.HTML, re.S).group(1)
        self.assertIn("wBounds(fitWidth())", setw)
        self.assertNotIn("2200", setw)
        zt = re.search(r"\nfunction zoomTo\(w,cx,cy\)\{(.*?)\}\n", ps.HTML, re.S).group(1)
        self.assertLess(zt.index("zoomAnchor(cx,cy)"), zt.index("setW(w)"))
        self.assertLess(zt.index("setW(w)"), zt.index("zoomRestore(a)"))


class FrontendZoomLogic(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_zoom_key_map(self):
        js = "\n".join([
            extract_js_fn("zoomKey"),
            "const ks=[['=','Equal'],['+','Equal'],['-','Minus'],['_','Minus'],['0','Digit0'],['+','NumpadAdd'],",
            " ['Process','Equal'],['Process','Minus'],['Process','Digit0'],['1','Digit1'],['Enter','Enter'],['a','KeyA']];",
            "console.log(JSON.stringify(ks.map(([key,code])=>zoomKey({key,code}))));",
        ])
        self.assertEqual(json.loads(run_node(js)),
                         ["in", "in", "out", "out", "fit", "in", "in", "out", "fit", None, None, None])

    def test_wheel_factor_mouse_notch_vs_trackpad_pinch(self):
        js = "\n".join([
            "const ZOOM_STEP=1.2;", extract_js_fn("wheelFactor"),
            "console.log(JSON.stringify([wheelFactor(-100,0),wheelFactor(100,0),wheelFactor(-3,1),wheelFactor(0,0),",
            " wheelFactor(-10,0),wheelFactor(10,0),wheelFactor(-49,0)].map(v=>+v.toFixed(4))));",
        ])
        out = json.loads(run_node(js))
        self.assertEqual(out[:4], [1.2, 0.8333, 1.2, 1])
        self.assertAlmostEqual(out[4], 1.1052, places=3)          # pinch dy=-10 -> zoom in slightly
        self.assertAlmostEqual(out[4] * out[5], 1.0, places=3)     # spreading then pinching returns to the same spot
        self.assertLess(out[6], 1.2)                               # dy split into small increments never exceeds one step per event

    def test_width_bounds_are_half_to_five_times_fit(self):
        js = "\n".join([
            "const ZOOM_MIN=0.5,ZOOM_MAX=5;", extract_js_fn("wBounds"),
            "console.log(JSON.stringify([wBounds(956),wBounds(370),wBounds(100)]));",
        ])
        self.assertEqual(json.loads(run_node(js)), [[478, 4780], [185, 1850], [160, 800]])


class FrontendMobileLogic(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_layout_for_breakpoints(self):
        cases = [(412, True), (700, True), (701, True), (880, True), (1099, True), (1100, True), (1440, True),
                 (412, False), (880, False), (1440, False)]
        js = "\n".join([
            "let innerWidth=0; const MQ_COARSE={matches:false};",
            extract_js_fn("layoutFor"),
            "console.log(JSON.stringify(%s.map(c=>{innerWidth=c[0];MQ_COARSE.matches=c[1];return layoutFor();})));" % json.dumps(cases),
        ])
        self.assertEqual(json.loads(run_node(js)),
                         ["narrow", "narrow", "mid", "mid", "mid", "wide", "wide", "narrow", "mid", "wide"])

    def test_quick_pick_box_is_small_and_clamped(self):
        js = "\n".join([
            r"""
            const c01=v=>Math.min(1,Math.max(0,v)); const QUICK_W=0.07,QUICK_H=0.006; const out=[];
            const pg={getBoundingClientRect:()=>({left:100,top:50,width:400,height:600})};
            function newBox(){return {};} function finishRect(pg,box,x0,y0,x1,y1){out.push([x0,y0,x1,y1].map(v=>+v.toFixed(4)));}
            """,
            extract_js_fn("fracAt"), extract_js_fn("quickPick"),
            "quickPick(pg,300,350); quickPick(pg,90,40); quickPick(pg,510,660); console.log(JSON.stringify(out));",
        ])
        self.assertEqual(json.loads(run_node(js)),
                         [[0.43, 0.494, 0.57, 0.506], [0, 0, 0.07, 0.006], [0.93, 0.994, 1, 1]])

    def test_keyboard_inset_ignores_pinch_zoom_and_desktop(self):
        # only the keyboard (visualViewport shrinking) is counted as --kb. Pinch-zoom (scale>1), small differences, and mouse devices all give 0.
        js = "\n".join([
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
        ])
        self.assertEqual(json.loads(run_node(js)),
                         [["515px", "400px"], ["0px", "915px"], ["0px", "915px"], ["0px", "915px"], ["0px", "915px"]])

    def test_card_accordion_summary_is_first_note_line(self):
        js = "\n".join([
            r"""
            const esc=t=>String(t==null?'':t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
            const T={stale:'s',n:'n',loc:'l',view:'v',edit:'e',close:'c',drop:'d'}; let EDIT=null, PINS=[];
            const OPEN_CARDS=new Set([2]);
            function viaTag(){return null;} function relBadge(){return null;} function claimActive(){return false;}
            function claimLabel(){return '';} function authorTip(){return 'tip';} function who(a){return a?a.name:'';}
            function avatar(){return '';}
            let SHOW_ALL=false, DOCS=[], DOC='main', DEFAULT_DOC='main'; function docInfo(){return null;}
            let LAYOUT='mid', REPLY=null, META=null; const THREAD_OPEN=new Set();
            """,
            extract_js_fn("rng"), extract_js_fn("multiDoc"), extract_js_fn("pdoc"), extract_js_fn("isRegion"),
            extract_js_fn("locText"), extract_js_fn("locCopy"), extract_js_fn("docChip"), js_thread(), extract_js_fn("card"), js_icons(),
            r"""
            const a=card({id:1,file:'/m.tex',name:'m.tex',lo:3,hi:5,page:2,note:'첫 줄 <b>\n둘째 줄'});
            const b=card({id:2,file:'/m.tex',name:'m.tex',lo:3,hi:5,page:2,note:''});
            const sum=s=>(/<div class="sum" data-act="card-toggle">((?:[^<]|<span class="dim">|<\/span>)*)<\/div>/.exec(s)||[])[1];
            console.log(JSON.stringify([sum(a), / open"/.test(a), sum(b), / open"/.test(b), /class="tags"/.test(a),
              /data-act="card-toggle" aria-expanded="false"/.test(a), /aria-expanded="true"/.test(b)]));
            """,
        ])
        self.assertEqual(json.loads(run_node(js)),
                         ["첫 줄 &lt;b&gt;", False, '<span class="dim">(메모 없음)</span>', True, True, True, True])


# Panel tidy-up / width adjustment (docs/handbook/viewer.md §패널 정리). Measured live with Playwright
# (expanded 880x790, collapsed 412x915, desktop 1440x900); here we check pure logic like bounds/steps/
# labels under node, and layout/wiring via the HTML string.
class FrontendPanelWidthLogic(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_side_bounds_per_layout(self):
        js = "\n".join([extract_js_fn("sideBounds"), r"""
            console.log(JSON.stringify([sideBounds('mid',880),sideBounds('mid',760),sideBounds('mid',701),
                                        sideBounds('wide',1440),sideBounds('wide',1100),sideBounds('wide',700)]));"""])
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
        js = "\n".join([extract_js_fn("clampSide"), extract_js_fn("nextPreset"), extract_js_fn("presetIndex"), r"""
            const b={min:300,max:528},P=[300,334,440];
            console.log(JSON.stringify([[100,300.4,420,999].map(w=>clampSide(w,b)),
              [300,334,420,440,500,302].map(w=>nextPreset(P,w)), [300,331,338,420,440].map(w=>presetIndex(P,w))]));"""])
        self.assertEqual(json.loads(run_node(js)),
                         [[300, 300, 420, 528], [334, 440, 440, 300, 300, 334], [0, 1, 1, -1, 2]])

    def test_level_name_is_short_and_disambiguates_nested_same_env(self):
        js = "\n".join([extract_js_fn("levelName"), extract_js_fn("levelLabel"), extract_js_fn("rng"), r"""
            const A=[{level:'para',label:'문단'},{level:'env',label:'환경 abstract',env:'abstract'},
                     {level:'env2',label:'환경 frontmatter (바깥)',env:'frontmatter'}];
            const B=[{level:'env',label:'환경 itemize',env:'itemize'},{level:'env2',label:'환경 itemize (바깥)',env:'itemize'}];
            console.log(JSON.stringify([A.map(l=>levelName(l,A)),B.map(l=>levelName(l,B)),rng(159,159),rng(155,173)]));"""])
        self.assertEqual(json.loads(run_node(js)),
                         [["문단", "abstract", "frontmatter"], ["itemize", "itemize (바깥)"], "L159", "L155-L173"])

    def test_via_tag_hides_confident_matches_and_flags_uncertain(self):
        # 90% and above hides the badge; below that shows '위치 불확실' (below 30% gets the warning color). Method/match rate/next step go in the tooltip.
        js = "\n".join(["const T={synctex:'S',text:'X'};", extract_js_fn("viaTag"), r"""
            const V="const VIA_HIDE=90,VIA_WARN=30;";
            console.log(JSON.stringify([viaTag({via:'synctex',score:0.934}),viaTag({via:'synctex',score:0.884}),
              viaTag({via:'text',score:0.2}),viaTag({via:'synctex',score:1}),viaTag({})]));"""])
        js = js.replace("function viaTag(", "const VIA_HIDE=90,VIA_WARN=30;\nfunction viaTag(", 1)
        got = json.loads(run_node(js))
        self.assertIsNone(got[0])
        self.assertEqual(got[1], {"t": "위치 불확실", "tip": "좌표로 찾음 · 일치 88% — S", "low": False})
        self.assertEqual(got[2], {"t": "위치 불확실", "tip": "글자로 찾음 · 일치 20% — X 많이 어긋났을 수 있습니다.", "low": True})
        self.assertIsNone(got[3])
        self.assertIsNone(got[4])
        self.assertIn("const VIA_HIDE=90,VIA_WARN=30;", ps.HTML)


class FrontendPanelTidyStructure(unittest.TestCase):
    def test_grip_is_one_pointer_events_separator(self):
        tag = re.search(r'<div id="grip"[^>]*>', ps.HTML).group(0)
        for part in ('role="separator"', 'aria-orientation="vertical"', 'tabindex="0"', 'aria-controls="right"'):
            self.assertIn(part, tag)
        self.assertIn("$('#grip'); let D=null;", ps.HTML)
        self.assertIn("g.setPointerCapture(e.pointerId)", ps.HTML)
        self.assertNotIn("$('#grip').addEventListener('mousedown'", ps.HTML)   # no old mouse-only path remains
        self.assertNotIn("body.compact #grip{display:none}", ps.HTML)          # still visible in mid too
        self.assertIn("body.lay-narrow #grip,body.lay-mid:not(.side-open) #grip{display:none}", ps.HTML)

    def test_width_is_remembered_per_layout_and_relayout_keeps_anchor(self):
        self.assertIn("function sideKey(){return LAYOUT==='mid'?'sideMid':'side';}", ps.HTML)
        m = re.search(r"\nfunction setSideWidth\(w\)\{(.*?)\}\n", ps.HTML, re.S)
        self.assertIsNotNone(m)
        self.assertIn("savePrefs({[sideKey()]:w})", m.group(1))
        self.assertIn("relayout()", m.group(1))
        m = re.search(r"\nfunction relayout\(\)\{(.*?)\}\n", ps.HTML, re.S)
        body = m.group(1)
        self.assertLess(body.index("applySideWidth()"), body.index("autoW()"))   # the panel width must be settled first for the page width to match
        # ResizeObserver doesn't re-fit every frame while dragging
        self.assertIn("!document.body.classList.contains('resizing'))scheduleRelayout()", ps.HTML)
        self.assertIn("body.lay-mid.side-open #right{width:var(--side-w,", ps.HTML)

    def test_sheet_grip_and_size_presets_in_more(self):
        tag = re.search(r'<div id="sheet-grip"[^>]*>', ps.HTML).group(0)
        self.assertIn('role="separator"', tag)
        self.assertIn('aria-orientation="horizontal"', tag)
        self.assertIn(":not(#sheet-grip){display:none}", ps.HTML)   # the grip stays even on a collapsed sheet
        self.assertIn("var(--sheet-f,.64)", ps.HTML)
        more = ps.HTML[ps.HTML.index('<dialog id="more"'):ps.HTML.index('<dialog id="help"')]
        self.assertIn('id="m-size"', more)
        self.assertIn("case 'size-preset':sizePreset(+a.dataset.i)", ps.HTML)
        self.assertIn("renderSizeSeg(); d.showModal()", ps.HTML)

    def test_actions_row_is_fixed_at_panel_bottom_outside_composer(self):
        right = ps.HTML[ps.HTML.index('<div id="right">'):ps.HTML.index('<div id="tip"')]
        comp = right[right.index('<div id="composer"'):right.index('<div id="list">')]
        self.assertNotIn('id="btn-save"', comp)
        acts = right.index('<div id="c-actions">')
        self.assertGreater(acts, right.index('<div id="list">'))
        # cancel comes first, the primary action (save pin) is wide on the right
        self.assertLess(right.index('id="btn-cancel"', acts), right.index('id="btn-save"', acts))
        self.assertRegex(right, r'<button class="btn-default" id="btn-save"')   # primary action = the default variant
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn("#composer[hidden]~#c-actions{display:none}", css)
        self.assertIn("grid-template-columns:1fr 2fr", css)
        self.assertIn("body.compact #c-actions{position:sticky;bottom:0", css)
        self.assertIn("#composer:not([hidden])~#list #empty{display:none}", css)   # the help paragraph is hidden while selecting

    def test_composer_is_one_loc_line_segmented_ladder_and_folded_snippet(self):
        self.assertNotIn('id="c-meta"', ps.HTML)            # location info repeated 3x -> now one line
        self.assertNotIn("드래그한 줄 L'+d.raw_lo", ps.HTML)
        row = ps.HTML[ps.HTML.index('<div class="c-loc-row">'):ps.HTML.index('<div id="c-warn"')]
        for el in ('id="c-loc"', 'id="c-page"', 'id="c-tag"', 'id="c-copy"'):
            self.assertIn(el, row)
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        seg = re.search(r"\n\.seg\{([^}]*)\}", css).group(1)
        self.assertIn("flex-wrap:nowrap", seg)
        self.assertIn("overflow-x:auto", seg)
        self.assertIn('<div class="step" role="group"', ps.HTML)
        self.assertIn("#c-snip:not(.open){max-height:calc(6em + 16px);overflow:hidden}", css)   # 4 lines + 8px top/bottom padding
        m = re.search(r"\nfunction renderComposer\(\)\{(.*?)\n\}", ps.HTML, re.S)
        self.assertIn("pre.scrollHeight>pre.clientHeight", m.group(1))
        # on a narrow sheet the note field sits above the source snippet (so it doesn't hide under the action row)
        self.assertIn("body.lay-narrow #note{order:1", css)

    def test_card_head_tags_row_and_action_grid(self):
        m = re.search(r"\nfunction card\(p\)\{(.*?)\n\}", ps.HTML, re.S)
        body = m.group(1)
        self.assertNotIn('<span class="tags">', body)                        # badges are not inside the head row
        self.assertGreater(body.index('<div class="tags">'), body.index("b-fold"))   # one line after the head (fold button)
        self.assertLess(body.index('b-drop'), body.index('b-close'))         # done (primary) sits at the far right
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn(".pin .acts{display:grid;grid-auto-flow:column;grid-auto-columns:1fr", css)
        self.assertIn('class="btn-sm btn-soft b-close"', body)               # done = soft (pale blue, author-specified 09-23), drop = destructive
        self.assertNotIn('btn-secondary b-close', body)
        self.assertIn("button.btn-soft{background:color-mix(in srgb,var(--primary) 14%,transparent);color:var(--primary)", css)
        self.assertIn('class="btn-sm btn-destructive b-drop"', body)

    def test_compact_toolbar_is_one_even_row(self):
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn("body.compact #bar1 .sp{display:none}", css)
        self.assertIn("body.compact #bar1 #btn-more{flex:0 0 44px", css)

    def test_mid_layout_pins_nav_top_and_action_bar_bottom(self):
        # unfolded fold devices / tablets (mid): the action row doesn't follow the panel — it's pinned
        # full-width at the bottom of the screen, and the nav row is pinned full-width at the top
        # (docs/handbook/viewer.md §펼친 화면 레이아웃). Live browser measurements are in FrontendResponsiveBrowser.
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        css_nc = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        self.assertIn("body.lay-mid #bar1{position:fixed;left:0;right:0;top:auto;bottom:var(--kb,0px);", css)
        self.assertIn("body.lay-mid #doc-nav{position:fixed;top:0;left:0;right:0;", css)
        self.assertIn("padding-top:var(--mid-top);padding-bottom:var(--mbar-h)}", css)     # the body/panel only occupy the space between the two
        self.assertIn("@media (pointer:coarse){body.lay-mid{--mbar-tb:var(--control-h-touch)}}", css)
        # thumb order: [select] at the far left, [pin N] at the far right. DOM is shared with the narrow sheet, so only order changes.
        self.assertIn("body.lay-mid #btn-select{order:1}", css)
        self.assertIn("body.lay-mid #bar1 #btn-side{order:5;", css)
        # the toolbar is a fixed child of #right — giving #right a containing-block-creating property would make the action row move with the panel
        for sel, body in re.findall(r"([^{}]*#right[^{}]*)\{([^{}]*)\}", css_nc):
            if "lay-mid" in sel:
                self.assertIsNone(re.search(r"(?:^|;)(?:transform|translate|filter|opacity|contain|will-change|perspective)\s*:", body), sel)
        self.assertRegex(css_nc, r"@keyframes mid-panel-in\{from\{right:")      # the opening animation moves only via right
        # the first-run coach mark sits above the action row ([select] above), not over the nav row. Toasts sit right above the action row, panel side (FrontendToasts).
        self.assertIn("body.lay-mid #coach{top:auto;bottom:calc(var(--mbar-h)", css)
        self.assertIn("body.lay-mid #toasts{", css)
        # an overflowing document-link row fades at the edge instead of showing a scrollbar
        self.assertIn("body.lay-mid #doc-links.fade-r{mask-image:", css)
        self.assertIn("function docLinksFade(){", ps.HTML)
        self.assertIn("$('#doc-links').addEventListener('scroll',docLinksFade,{passive:true});", ps.HTML)


# ---------------------------------------------------------------- design token guard (docs/handbook/viewer.md §디자인 토큰과 컴포넌트)
# Colors, radii, and font sizes used to vary per rule (54 color literals, 14 radii, 12 font sizes) — now
# collected into a token layer. This blocks any rule from reintroducing a literal going forward. The one
# exception is the allowlist below; if it grows, update design.md's table too.
TOKEN_SELECTORS = (":root", ":root[data-theme=light]")            # the only place a color literal may live


COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(|"
                      r"\b(?:white|black|red|green|blue|gray|grey|yellow|orange|purple|pink|silver)\b", re.I)


RADIUS_OK = re.compile(r"^(?:var\(--radius(?:-sm|-lg)?\)|0|50%)$")


INLINE_STYLE_OK = {"background:__ACCENT__"}                         # the instance label color — the server fills it in via the --accent value


def css_rules():
    """The (selector, [(property, value)]) list inside <style>. Strips comments and flattens @media rules too."""
    css = ps.HTML[ps.HTML.index("<style>") + len("<style>"):ps.HTML.index("</style>")]
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


class FrontendDesignTokens(unittest.TestCase):
    def test_colour_literals_only_in_token_blocks(self):
        bad = []
        for sel, decls in css_rules():
            for k, v in decls:
                if sel in TOKEN_SELECTORS and k.startswith("--"):
                    continue                                          # a token definition
                if COLOR_RE.search(v):
                    bad.append("%s { %s:%s }" % (sel, k, v))
        self.assertEqual(bad, [])

    def test_both_themes_define_every_colour_token(self):
        blocks = {sel: dict(decls) for sel, decls in css_rules() if sel in TOKEN_SELECTORS and any(k == "color-scheme" for k, _ in decls)}
        dark, light = blocks[":root"], blocks[":root[data-theme=light]"]
        def lit(block):
            """Custom properties in a theme block whose value is a color."""
            return {k for k, v in block.items() if k.startswith("--") and COLOR_RE.search(v)}
        self.assertEqual(lit(dark) - set(light), set())               # dark colors don't leak into light
        self.assertEqual(set(light) - set(dark), set())               # light only overrides tokens that exist in dark
        for k in ("--background", "--foreground", "--card", "--card-foreground", "--muted", "--muted-foreground",
                  "--border", "--input", "--ring", "--primary", "--primary-foreground", "--secondary",
                  "--secondary-foreground", "--destructive", "--destructive-foreground", "--status-open",
                  "--status-claimed", "--status-closed", "--status-dropped", "--status-warning"):
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
        defs = {k: v for sel, decls in css_rules() if sel == ":root" for k, v in decls}
        self.assertEqual([defs["--text-" + n] for n in ("xs", "sm", "base", "lg", "xl")], ["11px", "12px", "13px", "14px", "16px"])

    def test_inline_styles_and_scripts_carry_no_design_literals(self):
        body = ps.HTML[ps.HTML.index("</style>"):]
        for st in re.findall(r'style="([^"]*)"', body):
            self.assertTrue(st in INLINE_STYLE_OK or not (COLOR_RE.search(st) or re.search(r"font-size|radius", st)), st)
        # JS never sets color or font size directly on an element's style (only width/height/coordinates/token variables)
        self.assertEqual(re.findall(r"\.style\.(?:color|background\w*|fontSize|borderRadius|borderColor)\s*=", body), [])
        self.assertIsNone(re.search(r"['\"]#[0-9a-fA-F]{3,8}['\"]", body))

    def test_every_var_is_defined(self):
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        runtime = set(re.findall(r"setProperty\('(--[a-z0-9-]+)'", ps.HTML))    # values JS measures and sets (--kb, --side-w, etc.)
        used = set(re.findall(r"var\((--[a-z0-9-]+)", css))
        defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", css))
        self.assertEqual(used - defined - runtime, set())             # no old tokens left over from a rename (--acc, --dim, ...)

    def test_component_variants_exist(self):
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        for cls in ("button.btn-default{", "button.btn-secondary{", "button.btn-soft{", "button.btn-ghost{", "button.btn-destructive{",
                    "button.btn-sm{", "button.btn-icon{", ".badge{", ".badge-default{", ".badge-secondary{",
                    ".badge-destructive{", ".badge-claimed{", ".badge-warning{", ".card{"):
            self.assertIn(cls, css)
        for old in ("button.p{", "button.x{", "button.ghost{", "button.ib{", "button.ico{", ".tag{", ".tag.t{"):
            self.assertNotIn(old, css)                                # old display-only classes were removed


# ---------------------------------------------------------------- toasts — docs/handbook/viewer.md §알림(토스트)
# author feedback (2026-09-24): saving a pin used to pop an "undo" toast at the bottom-left, far from the
# right-hand panel (1,100px+ away), with a tacky left color stripe. It now appears sonner-style right
# where you just clicked (bottom-right of the panel column, just above the action row; on narrow, above the sheet).
class FrontendToasts(unittest.TestCase):
    css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]

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
            self.assertIn("%s:()=>ic('%s')" % (kind, icon), ps.HTML)
        self.assertIn(".toast.warn>.ic{color:var(--warning)}", self.css)
        self.assertIn(".toast.err>.ic{color:var(--destructive)}", self.css)

    def test_toast_anchored_per_layout_near_the_action(self):
        box = dict(self.rules(r"^#toasts$")[0][1])
        self.assertEqual(box["right"], "var(--toast-r,var(--space-3))")
        self.assertEqual(box["bottom"], "var(--toast-b,var(--space-3))")
        self.assertNotIn("left", box)                                  # formerly: pinned bottom-left
        self.assertIn("body.lay-narrow #toasts{", self.css)
        self.assertIn("body.lay-mid #toasts{", self.css)
        self.assertNotRegex(self.css, r"body\.lay-mid #toasts\{[^}]*top:")   # formerly: top-left of the body
        body = extract_js_fn("placeToasts")
        self.assertIn("'#c-actions'", body)                           # doesn't cover the save/cancel buttons
        self.assertIn("LAYOUT==='mid'?['#bar1']", body)               # doesn't cover the bottom toolbar
        self.assertIn("right.getBoundingClientRect().top", body)      # narrow: above the sheet
        self.assertIn("innerWidth-rr.right+12", body)                 # right edge inside the panel column
        self.assertIn("if(top<vh*0.3){top=vh; const ca=$('#c-actions');", body)   # a nearly-full sheet: drop down so it doesn't cover the toolbar
        self.assertIn("@media (pointer:coarse){.toast{pointer-events:none}.toast button{pointer-events:auto}}", self.css)
        for v in ("--toast-b", "--toast-r", "--toast-w"):
            self.assertIn("setProperty('%s'" % v, body)

    def test_toast_stacks_newest_on_top_and_collapses_after_three(self):
        """Newest toast on top, 6s life, more than three fold (hover, focus or the '+N' button opens them), no motion when reduced."""
        body = extract_js_fn("toast")
        self.assertIn("box.insertBefore(t,box.firstChild)", body)
        self.assertIn("setTimeout(kill,6000)", body)
        self.assertIn("#toasts:not(:hover):not(:focus-within):not(.expanded) .toast:nth-child(n+4){display:none}", self.css)   # + the '+N' button on touch
        self.assertIn("@keyframes toast-in", self.css)
        self.assertIn("@media (prefers-reduced-motion: reduce){*{animation:none!important", self.css)

    def test_toast_title_and_description_split(self):
        if not shutil.which("node"):
            self.skipTest("node not available")
        js = extract_js_fn("toastSplit") + "\nconsole.log(JSON.stringify(['핀 #3 저장됨 · pins.md 갱신','빌드 실패 — 화면은 이전 PDF입니다','복사함','핀 #10 · 본문 — 서준님이 불렀습니다: 봐 주세요'].map(toastSplit)));"
        self.assertEqual(json.loads(run_node(js)), [["핀 #3 저장됨", "pins.md 갱신"], ["빌드 실패", "화면은 이전 PDF입니다"], ["복사함", ""],
                                                          ["핀 #10 · 본문", "서준님이 불렀습니다: 봐 주세요"]])


# ---------------------------------------------------------------- no outline inside an outline (docs/handbook/viewer.md §한 겹 담기)
# author feedback (2026-09-24): drawing a bordered box inside another bordered box looks tacky. There is
# exactly one containing layer — a card (one thin border) or a floating surface (dialog/toast/@-list).
# Everything inside it — badges, buttons, segmented controls, steppers, source, overlap banner, thread —
# is separated only by fill, spacing, and dividers.
class FrontendNoNestedOutlines(unittest.TestCase):
    INNER = re.compile(r"^(?:\.badge|\.seg|\.step|pre\b|#c-overlap|\.thread|\.edit\b|\.arc-thread|\.arc-orig|\.arc-row|\.msg|\.reply-box)")
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
                    if re.fullmatch(r"border-(?:top|right|bottom|left)", k) and self.SEPARATORS.get(part) != k and v not in ("0", "none"):
                        bad.append("%s { %s:%s }" % (part, k, v))
                    if k == "border-color" and v != "transparent" and not part.startswith("button.badge"):
                        bad.append("%s { %s:%s }" % (part, k, v))
        self.assertEqual(bad, [])

    def test_card_buttons_are_filled_and_destructive_is_quiet(self):
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn(".pin :is(.acts,.e-acts,.r-acts) button:not(.btn-soft):not(.btn-destructive):not(.btn-default){background:var(--secondary);"
                      "color:var(--secondary-foreground);border-color:transparent}", css)
        self.assertIn(".pin .acts button.btn-destructive{background:transparent}", css)
        self.assertIn(".seg button.on{background:var(--popover);border-color:transparent;", css)
        more = ps.HTML[ps.HTML.index('<div class="more-grid">'):]
        more = more[:more.index("</dialog>")]
        for tag in re.findall(r"<button[^>]*>", more):
            self.assertIn("btn-secondary", tag)                      # dialog buttons are filled, borderless too

    def test_floating_surfaces_are_the_only_shadows_with_hairlines(self):
        for sel in ("dialog", "#mention-pop"):
            d = dict(dict(css_rules())[sel])
            self.assertEqual(d["border"], "1px solid var(--border)", sel)
            self.assertEqual(d["box-shadow"], "var(--shadow-lg)", sel)


# ---------------------------------------------------------------- meaning/function check (docs/handbook/viewer.md §뜻과 모양) + UX QA (2026-09-24)
class FrontendSemanticAudit(unittest.TestCase):
    css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]

    def test_relative_time_with_absolute_on_hover(self):
        if not shutil.which("node"):
            self.skipTest("node not available")
        js = "\n".join(["const esc=t=>String(t==null?'':t);", extract_js_fn("relTime"), extract_js_fn("relSpan"), r"""
            const now=new Date(2026,8,24,15,0).getTime();
            console.log(JSON.stringify(['2026-09-24 15:00:10','2026-09-24 14:57:00','2026-09-24 11:00:00','2026-09-21 10:00:00','2026-09-01 10:00:00','x']
              .map(s=>relTime(s,now)).concat([relSpan('2026-09-01 10:00','arc-t','닫은 시각')])));"""])
        out = json.loads(run_node(js))
        self.assertEqual(out[:6], ["방금", "3분 전", "4시간 전", "3일 전", "9-1", "x"])
        self.assertIn('data-tip="닫은 시각 2026-09-01 10:00"', out[6])
        self.assertIn("setInterval(tickRel,60000);", ps.HTML)
        self.assertIn(".arc-t{flex:none;font-size:var(--text-xs);white-space:nowrap}", self.css)   # formerly: it could wrap to '09-24 1…'

    def test_one_toast_per_event_notify_wins(self):
        if not shutil.which("node"):
            self.skipTest("node not available")
        js = "\n".join(["const TOAST_KEYS=[];", extract_js_fn("toastDup"), r"""
            const el=()=>({isConnected:true,removed:false,remove(){this.removed=true;this.isConnected=false;}});
            const a=el(); TOAST_KEYS.push({keys:['review_requested:37'],rank:1,el:a,t:Date.now()});
            const r1=toastDup({keys:['review_requested:37'],rank:2});           // 알림 경로가 이긴다 — 옛 것을 걷고 띄운다
            const b=el(); TOAST_KEYS.push({keys:['review_requested:37'],rank:2,el:b,t:Date.now()});
            const r2=toastDup({keys:['review_requested:37'],rank:1});           // 뒤늦은 목록 비교 알림은 띄우지 않는다
            const r3=toastDup({keys:['reopened:37'],rank:1}), r4=toastDup(null);
            const r5=toastDup({keys:['review_requested:37'],rank:2});           // 같은 경로의 다음 사건(두 번째 검토 대기)은 막지 않는다
            console.log(JSON.stringify([r1,a.removed,r2,r3,r4,r5]));"""])
        self.assertEqual(json.loads(run_node(js)), [False, True, True, False, False, False])
        self.assertIn("{keys:[e.type+':'+e.pin],rank:2}", extract_js_fn("notifyShow"))
        self.assertIn("{keys:reviewed.map(i=>'review_requested:'+i)}", extract_js_fn("diffToast"))
        self.assertIn("{keys:['reopened:'+p.id]}", extract_js_fn("reviewToast"))

    def test_closed_cards_drop_position_badges_and_thread_count_opens_reply(self):
        body = extract_js_fn("card")
        self.assertIn("const rb=closedCard?null:relBadge(p.rel,p);", body)
        self.assertIn("const v=closedCard?null:viaTag(p);", body)
        self.assertIn('class="th-n" role="button" tabindex="0" data-act="reply-open"', body)

    def test_long_messages_clamp_and_identity_marks(self):
        self.assertIn(".msg-t.clamp{display:-webkit-box;-webkit-line-clamp:6;", self.css)
        self.assertIn("data-act=\"msg-more\"", extract_js_fn("msgBody"))
        self.assertIn("if(isAgent(a))return '<span class=\"av i agent\" aria-hidden=\"true\">'+ic('bot')+'</span>';", extract_js_fn("avatar"))
        self.assertIn("(나)", extract_js_fn("msgHtml"))
        self.assertIn("(나)", extract_js_fn("card"))

    def test_touch_targets_in_archive_rows(self):
        coarse = self.css[self.css.index("@media (pointer:coarse){"):]
        coarse = coarse[:coarse.index("\n}")]
        self.assertIn("button.arc-orig-t{min-height:44px;min-width:44px;", coarse)
        self.assertIn(".arc-reply{min-height:44px;", coarse)
        self.assertIn(".th-n{min-height:44px;min-width:44px;", coarse)

    def test_review_count_labels_scope_and_filter_is_compact(self):
        self.assertIn("' '+tl('(이 문서 {n})',{n:here})", extract_js_fn("updateReviewCount"))
        body = extract_js_fn("drawPins")
        self.assertIn("mf.innerHTML=ic('at-sign')+MINE.length; mf.setAttribute('aria-label',tl('나를 부른 핀 {n}',{n:MINE.length}));", body)

    def test_revision_note_wraps_and_returns_to_previous_doc(self):
        self.assertIn("#revision-pin button{flex:none;margin-left:auto}", self.css)
        self.assertIn("data-act=\"rev-back\"", extract_js_fn("revTargetNote"))
        self.assertIn("REV_BACK=DOC", extract_js_fn("showChange"))
        self.assertIn("case 'rev-back':", ps.HTML)

    def test_source_diff_wrap_toggle_defaults_on_touch(self):
        self.assertIn('id="revision-wrap" class="tg btn-sm" data-act="diff-wrap"', ps.HTML)
        self.assertIn("setDiffWrap(typeof v==='boolean'?v:MQ_COARSE.matches)", extract_js_fn("initDiffWrap"))
        self.assertIn("#revision-diff.wrap .rd-code{flex:1;min-width:0;white-space:pre-wrap", self.css)

    def test_change_view_on_fold_and_phone(self):
        # [변경 보기] phone/fold QA (2026-09-25): on a fold (701-900px), the pin panel floats on top,
        # hiding the right half of the diff and the [원고로] button — only the change view yields space
        # equal to the panel width. Commit picking / build-warning expand are 44px on touch.
        self.assertIn("body.lay-mid.side-open #revision-view{padding-right:var(--side-w,330px)}", self.css)
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
        self.assertIn(":is(.loc,.pg-link,.pin .n.go,.pin-ref):is(:hover,:focus-visible){text-decoration:underline}", self.css)
        for rule in (".pin .n.go{cursor:pointer;color:var(--primary);", ".pin-ref{color:var(--primary);", ".pg-link{color:var(--primary);"):
            self.assertIn(rule, self.css)
        dotted = [r for r in re.findall(r"[^{}]+\{[^}]*underline dotted[^}]*\}", self.css)]
        self.assertEqual([r.split("{")[0].strip() for r in dotted], [".mention-bad"])
        self.assertIn("button[data-pending]{cursor:progress;", self.css)


class PinNumberJump(unittest.TestCase):
    """Clicking the #number in a card's header jumps to that pin's spot in the PDF (same data-act="view" as [보기]/page N)."""

    def test_number_is_a_button_that_jumps(self):
        src = ps.HTML
        self.assertIn('<span class="n go" role="button" tabindex="0" data-act="view"', src)
        self.assertIn("누르면 PDF에서 이 핀 자리로 갑니다", src)

    def test_number_is_keyboard_and_touch_reachable(self):
        src = ps.HTML
        self.assertIn("/^(button|link)$/.test(t.getAttribute('role')||'')&&t.dataset&&t.dataset.act", src)
        self.assertIn(".loc,.pg-link,.pin .n.go{display:inline-flex;align-items:center;min-height:44px}", src)
        # regression: #N used to render at only its text width (26-35px), falling short of the 44px
        # minimum touch hit area (observed). The visual size stays the same; a fixed 44x44 ::before hit
        # area is centered on top of it — it must be fixed width/height, not the inset approach
        # (proportional to the parent's width), to guarantee 44 even for a short number (e.g. one digit).
        # position:relative is given only to .n.go — giving it to .loc/.pg-link too would let .loc, which
        # comes later in DOM order, rise above the ::before in positioned stacking and steal the hit test
        # for the right half (a regression found and reverted via live browser testing).
        css = src[src.index("<style>"):src.index("</style>")]
        self.assertIn(".pin .n.go{position:relative}", css)
        self.assertIn(".pin .n.go::before{content:'';position:absolute;left:50%;top:50%;"
                      "width:var(--control-h-touch);height:var(--control-h-touch);transform:translate(-50%,-50%)}", css)

    def test_view_action_still_routes_to_jumppin(self):
        self.assertIn("case 'view':jumpPin(id);break;", ps.HTML)

    def test_touch_media_query_wins_over_btn_icon_btn_sm_specificity(self):
        # regression: button.btn-icon.btn-sm{width:var(--control-h-sm)} (base rule, 0-0-2-1) is more
        # specific than the touch rule button.btn-icon{width:var(--control-h-touch)} (0-0-1-1), so the
        # card fold button (.b-fold) and the toast close button stayed at 24px even on touch (observed).
        # It has to be pinned again at the same specificity (.btn-icon.btn-sm) inside @media(pointer:coarse) to win.
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        coarse = css[css.index("@media (pointer:coarse){"):]
        coarse = coarse[:coarse.index("\n}\n") + 3]
        self.assertIn("button.btn-icon.btn-sm{width:var(--control-h-touch);min-width:var(--control-h-touch);"
                      "height:var(--control-h-touch)}", coarse)
        # real usage: both the card fold button and the toast close button use the .btn-icon.btn-sm combination.
        self.assertIn('btn-icon btn-sm btn-ghost cmp b-fold', ps.HTML)
        self.assertIn("c.className='btn-icon btn-sm btn-ghost'", ps.HTML)

    def test_compact_bar1_buttons_keep_touch_min_width_despite_shrink_to_fit(self):
        # regression: body.compact #bar1 button{min-width:0} (specific due to the id) beat the touch rule
        # button{min-width:44px}, so on a narrow screen like lay-mid the [select] button shrank to 40px
        # (observed). The same selector is pinned again inside @media(pointer:coarse) to keep the 44px floor.
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn("body.compact #bar1 button{flex:1 1 auto;min-width:0;", css)
        self.assertIn("@media (pointer:coarse){body.compact #bar1 button{min-width:44px}}", css)
        # this override must come after the min-width:0 rule in source order to win at equal specificity.
        self.assertGreater(css.index("@media (pointer:coarse){body.compact #bar1 button{min-width:44px}}"),
                            css.index("body.compact #bar1 button{flex:1 1 auto;min-width:0;"))


class HtmlTemplateStructure(unittest.TestCase):
    """Whether ps.HTML, as of module load (before main() runs), has the label placeholder and markup —
    structural verification must always hold regardless of the actual substituted value."""

    def test_title_has_label_placeholder(self):
        self.assertIn("<title>Limn · __LABEL__</title>", ps.HTML)

    def test_favicon_placeholder(self):
        """The SVG favicon placeholder, next to its PNG fallbacks keyed by the accent (test_brand.py)."""
        self.assertIn('<link rel="icon" type="image/svg+xml" href="__FAVICON_HREF__">', ps.HTML)
        self.assertIn('href="/favicon-32.png?c=__ACCENT_KEY__"', ps.HTML)

    def test_brand_stripe_present(self):
        self.assertIn('id="brand-stripe"', ps.HTML)
        self.assertIn("#brand-stripe{position:fixed;top:0;left:0;right:0;height:4px", ps.HTML)

    def test_identity_crumb_precedes_desktop_doc_links_and_not_right_toolbar(self):
        self.assertLess(ps.HTML.index('id="paper-identity"'), ps.HTML.index('id="doc-links"'))
        self.assertLess(ps.HTML.index('id="paper-identity"'), ps.HTML.index('id="right"'))
        self.assertNotIn('id="brand-chip"', ps.HTML)

    def test_identity_crumb_does_not_take_mobile_space(self):
        self.assertIn('body.lay-narrow #paper-identity{display:none}', ps.HTML)
        self.assertIn('body:not(.lay-narrow) #doc-nav{display:flex}', ps.HTML)

    def test_document_title_prefixes_label(self):
        # with multiple documents, the document name (META.doc_name) is used instead of the main filename — the label prefix stays the same.
        self.assertIn(
            "document.title='Limn · '+(META.label?META.label+' · ':'')+(multiDoc()?META.doc_name||META.main:META.main)"
            "+' · '+tl('열린 {n}',{n:PINS.length})",
            extract_js_fn("docTitle"))
        self.assertIn("docTitle(true);", extract_js_fn("loadPins"))


class FrontendDocs(unittest.TestCase):
    """Distinguishes the desktop document selector from the mobile document menu."""

    def test_document_selector_and_mobile_button(self):
        css = ps.HTML
        self.assertIn("#doc-select-wrap{display:none;", css)
        self.assertIn("#doc-links{display:none;", css)
        self.assertIn("body.docs-multi:not(.lay-narrow) #doc-links{display:flex}", css)
        self.assertIn("body:not(.lay-narrow) #doc-nav{display:flex}", css)
        self.assertIn("#btn-doc{display:none;", css)
        self.assertIn("body.lay-narrow.docs-multi #btn-doc{display:inline-flex}", css)
        self.assertIn("body.view-only #btn-rebuild{display:none}", css)
        self.assertIn('id="all-docs"', css)
        self.assertIn("$('#all-docs').hidden=!multiDoc()", ps.HTML)
        self.assertIn("document.body.classList.toggle('docs-multi',multiDoc())", ps.HTML)

    def test_selector_views_and_outline_are_in_pdf_area(self):
        self.assertIn('<select id="doc-select" aria-label="문서 선택">', ps.HTML)
        self.assertIn('<div id="doc-links" role="group" aria-label="문서 선택">', ps.HTML)
        self.assertIn('id="view-manuscript" data-act="view-mode"', ps.HTML)
        self.assertIn('id="view-revisions" data-act="view-mode"', ps.HTML)
        self.assertIn('<nav id="outline" aria-label="원고 목차">', ps.HTML)
        self.assertIn('body.outline-collapsed #outline{display:none}', ps.HTML)
        self.assertIn('id="nav-toc-toggle" data-act="outline"', ps.HTML)
        self.assertLess(ps.HTML.index('id="doc-nav"'), ps.HTML.index('id="right"'))
        body = extract_js_fn("drawDocTabs")
        self.assertIn("box.value=DOC", body)
        self.assertIn("DOCS.map", body)
        self.assertIn('aria-current="', body)

    def test_default_theme_is_light(self):
        self.assertIn('<html lang="ko" data-theme="light">', ps.HTML)
        self.assertIn("p={theme:'light'}", ps.HTML)
        self.assertIn("prefs().theme||'light'", ps.HTML)

    def test_outline_labels_only_attach_to_matching_pdf_entries(self):
        js = "\n".join([extract_js_fn("mergeOutlineLabels"), r"""
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
            console.log(JSON.stringify(mergeOutlineLabels(entries,labels).map(x=>[x.number,x.pageLabel])));"""])
        self.assertEqual(json.loads(run_node(js)),
                         [["4", "9"], ["", ""], ["4.3", "11"], ["", ""]])

    def test_outline_labels_require_matching_section_depth_when_supported(self):
        js = "\n".join([extract_js_fn("mergeOutlineLabels"), r"""
            const entries=[{title:'Overview',page:1,depth:0},{title:'Overview',page:1,depth:1}];
            const labels=[{number:'0.9',title:'Overview',page:'1',level:'subsection'},
                          {number:'1',title:'Overview',page:'1',level:'section'},
                          {number:'1.1',title:'Overview',page:'1',level:'subsection'}];
            console.log(JSON.stringify(mergeOutlineLabels(entries,labels).map(x=>x.number)));"""])
        self.assertEqual(json.loads(run_node(js)), ["1", "1.1"])

    def test_revision_async_result_is_ignored_after_doc_commit_or_view_change(self):
        js = "\n".join(["let REVISION_SEQ=8,DOC='ms',REVISION_COMMIT='abc';",
                        "const document={body:{classList:{contains:x=>x==='revision-open'}}};",
                        extract_js_fn("revisionCurrent"), r"""
            console.log(JSON.stringify([
              revisionCurrent(8,'ms','abc'),revisionCurrent(7,'ms','abc'),
              revisionCurrent(8,'hl','abc'),revisionCurrent(8,'ms','def')]));"""])
        self.assertEqual(json.loads(run_node(js)), [True, False, False, False])

    def test_pin_actions_restore_pdf_from_revision_view(self):
        self.assertIn("setViewMode('manuscript')", extract_js_fn("jumpPin"))
        self.assertIn("jumpPin(id)", extract_js_fn("openEdit"))

    def test_revision_diff_rows_have_line_semantics_and_escape_source(self):
        patch = ("diff --git a/ms/main.tex b/ms/main.tex\n"
                 "index 123..456 100644\n--- a/ms/main.tex\n+++ b/ms/main.tex\n"
                 "@@ -3,2 +3,2 @@ heading\n-old <script>alert(1)</script>\n"
                 "+new <img src=x onerror=alert(1)>\n context\n")
        esc = re.search(r"^const esc=.*;$", ps.HTML, re.M).group(0)
        js = "\n".join([esc, extract_js_fn("renderRevisionDiff"),
                        "console.log(JSON.stringify(renderRevisionDiff(%s)));" % json.dumps(patch)])
        out = run_node(js)
        if out is None:
            self.skipTest("node not available")
        rendered = json.loads(out)
        self.assertRegex(rendered, r'rd-hunk[^>]*>.*?@@ -3,2 \+3,2 @@')
        self.assertRegex(rendered, r'rd-del[^>]*>.*?rd-no[^>]*>3</span>')
        self.assertRegex(rendered, r'rd-add[^>]*>.*?rd-no[^>]*>3</span>')
        self.assertRegex(rendered, r'rd-context[^>]*>.*?rd-no[^>]*>4</span>')
        self.assertIn('&lt;script&gt;', rendered)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', rendered)
        self.assertNotIn('<script>', rendered)
        self.assertNotIn('<img ', rendered)
        self.assertIn('rd-meta', rendered)

    def test_revision_file_selection_renders_only_selected_patch(self):
        esc = re.search(r"^const esc=.*;$", ps.HTML, re.M).group(0)
        js = "\n".join([esc, extract_js_fn("renderRevisionDiff"), extract_js_fn("renderRevisionFile"), r"""
            let REVISION_WHOLE='+from first\n+from second', REVISION_FILES=[
              {text:'+from first'}, {text:'+from second'}];
            const nodes={'#revision-file':{value:'1'},'#revision-diff':{innerHTML:''}};
            function $(selector){return nodes[selector];}
            renderRevisionFile(); console.log(JSON.stringify(nodes['#revision-diff'].innerHTML));"""])
        out = run_node(js)
        if out is None:
            self.skipTest("node not available")
        rendered = json.loads(out)
        self.assertIn('from second', rendered)
        self.assertNotIn('from first', rendered)
        self.assertIn('rd-add', rendered)

    def test_hash_dq_and_initial_doc(self):
        js = "\n".join([r"""
            const DOCS=[{key:'ms'},{key:'rr'},{key:'rv'}]; let DOC='ms'; let _prefs={}; function prefs(){return _prefs;}
            const location={hash:''};
            """, extract_js_fn("docInfo"), extract_js_fn("dq"), extract_js_fn("hashDoc"), extract_js_fn("initialDoc"), r"""
            const out=[];
            out.push(dq('/api/meta'), dq('/api/meta?light=1'), dq('/pdf?build=x','rr'));
            location.hash='#doc=rr'; out.push(initialDoc());
            location.hash='#doc=Nope'; _prefs={lastDoc:'rv'}; out.push(initialDoc());       // 해시가 틀리면 마지막 문서
            location.hash='#doc=zz'; _prefs={lastDoc:'gone'}; out.push(initialDoc());      // 둘 다 없으면 첫 문서
            location.hash='#x=1&doc=rv'; _prefs={}; out.push(hashDoc());
            console.log(JSON.stringify(out));
            """])
        out = run_node(js)
        if out is None:
            self.skipTest("node not available")
        self.assertEqual(json.loads(out), ["/api/meta?doc=ms", "/api/meta?light=1&doc=ms", "/pdf?build=x&doc=rr",
                                           "rr", "rv", "ms", "rv"])

    def test_switch_shortcuts_skip_input_fields(self):
        m = re.search(r"document\.addEventListener\('keydown',e=>\{(.*?)\n\}\);", ps.HTML, re.S)
        body = m.group(1)
        i = body.index("if(multiDoc()&&!inField){")
        self.assertIn("e.key==='PageUp'||e.key==='PageDown'", body[i:])
        self.assertIn("/^Digit[1-9]$/.test(e.code||'')", body[i:])
        self.assertLess(body.index("const t=e.target,inField="), i)

    def test_view_memory_and_pdfjs_cache_are_bounded(self):
        self.assertIn("const VEC_CACHE_MAX=3;", ps.HTML)
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
        self.assertIn("function jumpPin(id){if(viaDoc(id,jumpPin))return;", ps.HTML)
        self.assertIn("function openEdit(id){if(viaDoc(id,openEdit))return;", ps.HTML)
        js = "\n".join([r"""
            const OPEN_ALL=[{id:1,doc:'ms'},{id:2,doc:'rr'},{id:3}]; let DOC='ms'; const DEFAULT_DOC='ms';
            const DOCS=[{key:'ms'},{key:'rr'}]; const seen=[];
            function switchDoc(k){seen.push('switch:'+k); DOC=k; return Promise.resolve();}
            """, extract_js_fn("docInfo"), extract_js_fn("pdoc"), extract_js_fn("viaDoc"), r"""
            (async()=>{const out=[viaDoc(1,()=>{}), viaDoc(3,()=>{}), viaDoc(2,id=>seen.push('then:'+id))];
              await Promise.resolve(); await Promise.resolve(); out.push(seen); console.log(JSON.stringify(out));})();
            """])
        out = run_node(js)
        if out is None:
            self.skipTest("node not available")
        self.assertEqual(json.loads(out), [False, False, True, ["switch:rr", "then:2"]])

    def test_region_selection_saves_page_and_frac_only(self):
        body = extract_js_fn("savePin")
        self.assertIn("if(isRegion(d))body={page:d.page,frac:d.frac,note:note,quote:d.quote,pdf_build:d.pdf_build||undefined};", body)
        self.assertIn("body.doc=d.doc||DOC||undefined;", body)
        self.assertIn("if(!o||!o.file)return out;", extract_js_fn("overlapsFor"))
        self.assertIn("#composer.region #c-levels", ps.HTML)


# ---------------------------------------------------------------- icons: Lucide only, no emoji/symbol glyphs
# Emoji/basic-character icons (⏳ ▾ ☾ ✎ etc.) looked ugly because they render differently per
# device/font (author feedback 2026-09-23). Icons only use inline SVG elements from Lucide
# (vendor/lucide/README.md). Arrows in prose (→) and key names (⌘) remain as plain characters.
ICON_GLYPHS = re.compile("[⏳⌛▲-◃◐-◓☀☼☾✓✔✎✏⚠"
                         "⧉⋯＋×↵⊂∩★☆●○"
                         "\U0001F000-\U0001FFFF✀-➿️]")


def html_without_comments(h: str) -> str:
    h = re.sub(r"/\*.*?\*/", "", h, flags=re.S)
    return "\n".join(ln for ln in h.split("\n") if not ln.strip().startswith("//"))


class FrontendIcons(unittest.TestCase):
    VENDOR = PKG / "vendor" / "lucide"

    def test_vendor_license_and_readme_record_version_and_icons(self):
        lic = (self.VENDOR / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("ISC License", lic)
        self.assertIn("Lucide Icons and Contributors", lic)
        readme = (self.VENDOR / "README.md").read_text(encoding="utf-8")
        self.assertIn("lucide-static@%s" % viewer_assemble.LUCIDE_VERSION, readme)
        table = readme[readme.index("## Icons in use"):readme.index("## Updating")]
        names = set()
        for row in re.findall(r"^\| (`[^|]+) \|", table, flags=re.M):
            names |= set(re.findall(r"`([a-z0-9-]+)`", row))
        self.assertEqual(names, set(viewer_assemble.LUCIDE))

    def test_icon_markup_is_plain_svg_elements(self):
        for name, body in viewer_assemble.LUCIDE.items():
            els = re.findall(r"<[^>]+>", body)
            self.assertTrue(els, name)
            for el in els:
                self.assertRegex(el, r'^<(path|circle|rect|line|polyline|polygon|ellipse)( [a-z-]+="[^"<>]*")+/>$', name)
        svg = viewer_assemble.icon_svg("check")
        for attr in ('viewBox="0 0 24 24"', 'fill="none"', 'stroke="currentColor"', 'stroke-width="2"', 'aria-hidden="true"'):
            self.assertIn(attr, svg)

    def test_every_used_icon_exists_and_every_icon_is_used(self):
        h = ps.HTML
        self.assertNotIn("{{ic:", h)
        self.assertNotIn("__LUCIDE_JSON__", h)
        used = set(re.findall(r"ic\('([a-z0-9-]+)'\)", h)) | set(re.findall(r'class="ic ic-([a-z0-9-]+)"', h))
        used |= set(re.findall(r"'(chevron-(?:up|down|left|right))'", h))
        used |= set(re.findall(r"THEME_ICON=\{system:'([a-z-]+)',light:'([a-z-]+)',dark:'([a-z-]+)'\}", h)[0])
        self.assertEqual(used - set(viewer_assemble.LUCIDE), set())
        self.assertEqual(set(viewer_assemble.LUCIDE) - used, set())

    def test_no_emoji_or_symbol_glyph_icons_in_viewer(self):
        found = sorted(set(ICON_GLYPHS.findall(html_without_comments(ps.HTML))))
        self.assertEqual(found, [])

    def test_js_ic_matches_server_icon_svg(self):
        if not shutil.which("node"):
            self.skipTest("node not available")
        js = js_icons() + "\nconsole.log(JSON.stringify(['check','clock','x'].map(ic).concat([ic('nope')])));"
        self.assertEqual(json.loads(run_node(js)), [viewer_assemble.icon_svg("check"), viewer_assemble.icon_svg("clock"), viewer_assemble.icon_svg("x"), ""])

    def test_toolbar_icon_buttons_keep_accessible_names(self):
        for bid, label in (("btn-zoom-out", "축소"), ("btn-zoom-in", "확대"), ("btn-help", "도움말"), ("btn-more", "더보기"),
                           ("c-copy", "위치 복사")):
            tag = re.search(r'<button[^>]*id="%s"[^>]*>' % bid, ps.HTML).group(0)
            self.assertIn('aria-label="%s"' % label, tag)
        self.assertIn("b.innerHTML=ic(THEME_ICON[t]);", ps.HTML)


# ---------------------------------------------------------------- status stripe / archive (closed, dropped pins)
# expanding closed/dropped pins used to look identical to open cards, so the boundary between them was
# unclear (author feedback 2026-09-23). Now there's a full-width sticky section header after the open
# list ('완료 N ─── 펼치기'), and below it are flat, dimmed rows instead of cards. Status is distinguished
# via the card's left stripe color.
class FrontendArchive(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def run_rows(self, script: str):
        js = "\n".join([r"""
            const esc=t=>String(t==null?'':t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
            const T={loc:'l',reply:'y',restore:'s',purge:'u',n:'n',change:'c'}; let SHOW_ALL=false, DOCS=[], DOC='main', DEFAULT_DOC='main';
            function docInfo(){return null;} function authorTip(){return 'tip';} function who(a){return a?a.name:'';}
            """, js_icons(), extract_js_fn("rng"), extract_js_fn("multiDoc"), extract_js_fn("pdoc"), extract_js_fn("isRegion"),
            extract_js_fn("locCopy"), extract_js_fn("docChip"),
            "const ARC_OPEN=new Set(); let LAYOUT='wide', REPLY=null, META=null; const THREAD_OPEN=new Set(); function avatar(){return '';}",
            extract_js_fn("arcTime"), extract_js_fn("arcLoc"), extract_js_fn("arcLine"), js_thread(),
            "const TRASH_DAYS=30;", extract_js_fn("trashDaysLeft"), extract_js_fn("isOwner"), extract_js_fn("isViewer"),
            extract_js_fn("doneCard"), extract_js_fn("droppedCard"), script])
        return json.loads(run_node(js))

    def test_done_row_is_flat_with_reply_line_and_hidden_original_request(self):
        out = self.run_rows(r"""
            const p={id:7,file:'/m.tex',name:'m.tex',lo:3,hi:5,page:2,done:true,done_at:'2026-09-23 20:40:11',
              closed_by:{name:'에이전트'},close_reply:'제목을 <b>바꿈</b>',close_ref:'PR #227',note:'원래 <메모>'};
            const a=doneCard(p); ARC_OPEN.add('o:7'); ARC_OPEN.add('r:7'); const b=doneCard(p);
            console.log(JSON.stringify([/class="arc-row done"/.test(a), !/class="pin/.test(a), /ic-check/.test(a),
              /data-act="reply-open"[^>]*>답글</.test(a), /PR #227/.test(a), /class="rt arc-t" data-at="2026-09-23 20:40:11" data-tip="닫은 사람 에이전트 · 닫은 시각 2026-09-23 20:40:11">[^<]+</.test(a),
              /<span class="arc-reply" [^>]*>제목을 &lt;b&gt;바꿈&lt;\/b&gt;<\/span>/.test(a), /arc-orig"/.test(a), /원래 요청<\/button>/.test(a),
              /arc-reply open/.test(b), /class="arc-orig"><b>원래 요청<\/b>원래 &lt;메모&gt;/.test(b)]));
            """)
        self.assertEqual(out, [True, True, True, True, True, True, True, False, True, True, True])

    def test_done_row_reply_opens_the_reply_box_in_the_thread(self):
        # observed bug (v0.2.0): [다시 열기] on a done row called /reopen directly without asking for a reason. v0.2.2 has no
        # [다시 열기] at all: the row's [답글] opens the same reply box as a card (openReply), slotted into .reply-slot inside the
        # expanded thread, and a person's reply reopens the pin by the server rule.
        out = self.run_rows(r"""
            const p={id:9,file:'/m.tex',name:'m.tex',lo:3,hi:5,page:2,done:true,done_at:'2026-09-23 20:40:11',
              closed_by:{name:'에이전트'},close_reply:'고침',thread:[{id:1,by:{name:'에이전트'},at:'2026-09-23 20:40:11',text:'고침',ev:'close'}]};
            const idle=doneCard(p);
            REPLY={id:9,el:null};
            const replying=doneCard(p);
            console.log(JSON.stringify([!/data-act="reopen"/.test(idle), !/rv-reopen/.test(idle), /data-act="reply-open"/.test(idle),
              /class="reply-slot"/.test(idle), /class="reply-slot"/.test(replying), /class="arc-thread"/.test(replying)]));
            """)
        self.assertEqual(out, [True, True, True, False, True, True])

    def test_placeholder_ref_dash_is_hidden(self):
        # observed bug: when a QA script or an old caller put '-' in the ref slot, a meaningless reference like '닫음 · -' would show.
        out = self.run_rows(r"""
            const dash=doneCard({id:1,file:'/m.tex',name:'m.tex',lo:1,hi:1,page:1,done:true,done_at:'2026-09-23 08:05:00',close_ref:'-'});
            const real=doneCard({id:2,file:'/m.tex',name:'m.tex',lo:1,hi:1,page:1,done:true,done_at:'2026-09-23 08:05:00',close_ref:'PR #9'});
            const evDash=msgHtml({id:1,by:{name:'에이전트'},at:'2026-09-23 08:05:00',text:'답',ev:'close',ref:'-'});
            const evReal=msgHtml({id:1,by:{name:'에이전트'},at:'2026-09-23 08:05:00',text:'답',ev:'close',ref:'abc1234'});
            console.log(JSON.stringify([/arc-ref/.test(dash), /arc-ref/.test(real), /PR #9/.test(real),
              / · -</.test(evDash), evDash.includes(' · -'), evReal.includes(' · abc1234')]));
            """)
        self.assertEqual(out, [False, True, True, False, False, True])

    def test_done_row_without_reply_says_so_and_dropped_row_restores(self):
        out = self.run_rows(r"""
            const a=doneCard({id:3,file:'/m.tex',name:'m.tex',lo:1,hi:1,page:1,done:true,done_at:'2026-09-23 08:05:00'});
            const d=droppedCard({id:4,file:'/m.tex',name:'m.tex',lo:2,hi:9,page:1,note:'잘못 찍음',dropped_at:'2026-09-23 09:00:00',dropped_by:{name:'김'}});
            console.log(JSON.stringify([/설명 없이 닫힘/.test(a), /원래 요청/.test(a), /class="arc-row dropped"/.test(d), /ic-trash-2/.test(d),
              /data-act="restore"[^>]*>되살리기</.test(d), />잘못 찍음</.test(d), /L2-L9/.test(d), /data-act="reopen"/.test(d),
              /data-act="purge"/.test(d)]));
            """)
        self.assertEqual(out, [True, False, True, True, True, True, True, False, False])   # [영구 삭제] is the owner's only

    def test_section_head_reads_label_count_and_fold_state(self):
        # One header component for open / awaiting review / done (v0.2.2): chevron, name, count, and 'new N' while collapsed.
        js = "\n".join([js_icons(), r"""
            const esc=t=>String(t==null?'':t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
            const els={}; function el(id,ctl){return els[id]=els[id]||{id,innerHTML:'',hidden:false,attrs:{'aria-controls':ctl},
              setAttribute(k,v){this.attrs[k]=v;},getAttribute(k){return this.attrs[k];}};}
            el('done-toggle','done-list'); el('done-list');
            const document={getElementById:id=>els[id]||null};
            const SEC_DEFAULT={open:true,review:true,done:false}; let SEC={open:true,review:true,done:false};
            const SEC_SEEN={open:null,review:null,done:new Set([1,2])}; const SEC_NAME_ID={open:'list-h',review:'review-h',done:'done-h'};
            """, extract_js_fn("secNewCount"), extract_js_fn("secHead"), r"""
            const strip=s=>s.replace(/<svg.*?<\/svg>/g,'').replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').trim();
            const out=[]; const b=els['done-toggle'];
            secHead('done','완료',[1,2,3],[1,2,3,4]); out.push([strip(b.innerHTML),b.attrs['aria-expanded'],els['done-list'].hidden,/ic-chevron-right/.test(b.innerHTML)]);
            SEC.done=true; secHead('done','완료',[1,2,3],[1,2,3,4]); out.push([strip(b.innerHTML),b.attrs['aria-expanded'],els['done-list'].hidden,/ic-chevron-down/.test(b.innerHTML)]);
            SEC.done=false; secHead('done','완료',[1,2,3,4,5],[1,2,3,4,5]); out.push([strip(b.innerHTML)]);
            console.log(JSON.stringify(out));"""])
        out = json.loads(run_node(js))
        self.assertEqual(out, [["완료 3 새 1", "false", True, True], ["완료 3", "true", False, True], ["완료 5 새 1"]])

    def test_sections_are_sticky_and_wired(self):
        h = ps.HTML
        for sid in ("sec-open", "sec-review", "sec-done"):
            self.assertIn('id="%s"' % sid, h)
        self.assertNotIn('id="sec-dropped"', h)                              # v0.2.2: deleted pins are in the Trash dialog
        css = h[h.index("<style>"):h.index("</style>")]
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
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        for sel, decls in css_rules():
            if re.search(r"\.pin\b|\.arc-row|\.toast|#revision-pin|\.dm-item", sel):
                keys = [k for k, _ in decls]
                self.assertFalse([k for k in keys if k.startswith("border-left")], sel)
                self.assertNotIn("::before", sel.replace(".pin .n.go::before", ""))   # no overlaid stripe either
                for _k, v in decls:
                    self.assertNotRegex(v, r"inset \d+px 0 0", sel)          # no box-shadow-drawn stripe either
        self.assertNotIn(".strip{", css)
        for st in ("claimed", "review", "lost", "done", "dropped"):
            self.assertIn(".st-dot.%s{background:var(--status-" % st, css)
        self.assertEqual(css.count("--status-claimed:"), 2)             # both dark and light
        body = extract_js_fn("card")
        self.assertIn("(claimed?' claimed':'')", body)
        self.assertIn("stDot(rv?'review':p.stale?'lost':claimed?'claimed':'open')", body)
        self.assertIn("tl('상태: {name}',{name:tr(ST_NAME[st])})", extract_js_fn("stDot"))
        self.assertIn("role=\"img\" aria-label=\"'+t+'\"", extract_js_fn("stDot"))   # not distinguished by color alone
        self.assertIn("ic('rotate-ccw')+'다시 열림", body)
        self.assertIn(".arc-row+.arc-row{border-top:1px solid var(--border)}", css)


class FrontendClaimEta(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def run_info(self, script: str, tz="Asia/Seoul"):
        js = "\n".join(["function who(a){return a?a.name:'';}", extract_js_fn("ceil5"), extract_js_fn("hhmm"),
                        extract_js_fn("claimInfo"), extract_js_fn("claimLabel"), script])
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
        self.assertIn("setInterval(tickClaims,30000);", ps.HTML)
        self.assertNotIn("toLocaleTimeString", extract_js_fn("claimInfo"))


class FrontendToolbarOneRow(unittest.TestCase):
    """On a 1400px desktop (default 430px panel), the toolbar stays one row even with a long label
    ('Long-DemoPaper1') (measured live with Playwright, docs/handbook/viewer.md §디자인 토큰과 컴포넌트). [핀 다시 읽기]
    moved to the open-pin-list header, and lives inside [더보기] in compact mode."""

    def test_reload_lives_in_list_head_not_toolbar(self):
        bar = ps.HTML[ps.HTML.index('<div class="bar" id="bar1"'):ps.HTML.index('<div class="bar" id="bar2"')]
        self.assertNotIn('id="btn-reload"', bar)
        head = ps.HTML[ps.HTML.index('<div class="sec-head">'):ps.HTML.index('<div id="pins">')]
        self.assertRegex(head, r'<button id="btn-reload" class="sec btn-sm" data-act="reload" aria-label="핀 다시 읽기"')

    def test_label_chip_truncates_and_tip_has_full_label(self):
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn("#bar1 .chip{height:var(--control-h-sm);display:block;", css)
        self.assertIn("flex:0 1 auto;min-width:40px}", css)
        self.assertIn("text-overflow:ellipsis", re.search(r"\n\.chip\{[^}]*\}", css).group(0))
        self.assertIn("body.compact #bar1 .chip{flex:0 50 auto;min-width:28px}", css)   # in compact, the label yields space first
        out = ps.build_html("Long-DemoPaper1", "#1d4ed8")
        self.assertIn('data-tip="Long-DemoPaper1 — 이 창이 다루는 논문', out)

    def test_fold_closed_moves_label_into_more_and_keeps_doc_name(self):
        # on a folded fold device (344px), the label shrank to 'C…' and the document button to '본..', unreadable (2026-09-23).
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn("body.lay-narrow #bar1 .chip,body.lay-mid #bar1 .chip{display:none}", css)
        self.assertIn("body.lay-narrow #bar1 #btn-doc{flex:none;overflow:visible}", css)
        self.assertIn("body.lay-narrow #btn-doc .nm{overflow:visible;text-overflow:clip", css)
        more = ps.HTML[ps.HTML.index('<dialog id="more"'):ps.HTML.index("</dialog>", ps.HTML.index('<dialog id="more"'))]
        self.assertIn('<span id="more-label" class="chip" data-tip="__LABEL__ — ', more)
        out = ps.build_html("Long-DemoPaper1", "#1d4ed8")
        self.assertIn('<dialog id="more" aria-label="더보기 · Long-DemoPaper1">', out)
        self.assertIn("#more .more-head .chip{background:var(--brand);", css)

    def test_fold_open_also_hides_toolbar_chip_and_relies_on_more(self):
        # regression: an unfolded fold device (884px) also puts #bar1 under flex-wrap:nowrap pressure,
        # shrinking the label to 'CE-iTra…' (71px), unreadable (observed in touch QA). Same fix as narrow —
        # hide the toolbar chip and show the full name only via #more-label inside [더보기]. #more is
        # layout-condition-free shared markup, so it works as-is in mid too.
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn("body.lay-narrow #bar1 .chip,body.lay-mid #bar1 .chip{display:none}", css)
        self.assertIn('id="btn-more" class="cmp btn-icon"', ps.HTML)   # [더보기] is shared across compact (= mid/narrow)


class FrontendToolbarSize(unittest.TestCase):
    """Whether the toolbar's 쪽 (page) field matches the buttons' height/font size (desktop 28px, touch 44px). Measured live with Playwright."""

    def test_page_field_matches_toolbar_buttons(self):
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn("#bar1{flex-wrap:wrap;gap:var(--space-1);padding:var(--space-2);--tb-h:var(--control-h)}", css)
        self.assertIn("--control-h:28px", css)
        self.assertIn("--control-h-touch:44px", css)
        self.assertIn("#bar1>button,#bar1>input{height:var(--tb-h)}", css)
        # the single-character '쪽' field used to read as a button (QA 2026-09-24) — now left-aligned like a real input, placeholder '쪽 이동'. Height/font size match the buttons.
        # basis 40px, growing first to 54px: the English toolbar ('Rebuild PDF') still fits one row (FrontendEnglishChrome)
        self.assertIn("#bar1 input.n{width:54px;flex:100 1 40px;min-width:40px;max-width:54px;padding:0 var(--space-1);font-size:var(--text-base);", css)
        self.assertIn("#bar1 button.btn-icon{padding:0;width:var(--tb-h);min-width:var(--tb-h)}", css)
        coarse = css[css.index("@media (pointer:coarse){"):]
        self.assertIn("#bar1{flex-wrap:wrap;--tb-h:var(--control-h-touch)}", coarse)
        self.assertIn("#bar1 input.n{width:84px;flex:0 0 84px;max-width:none;font-size:var(--text-xl)}", coarse)
        self.assertRegex(ps.HTML, r'<input class="n sec" id="jump" placeholder="쪽 이동"')
        self.assertIn('id="m-jump" inputmode="numeric" placeholder="쪽"', ps.HTML)


class FrontendSaveWhilePicking(unittest.TestCase):
    """Save while picking (docs/handbook/viewer.md §패널 정리): clicking [핀 저장] right after a drag, before the
    SyncTeX pick finishes (~1.1s), used to find CUR still unset, so savePin() silently did nothing and the note was lost (observed). It now
    queues that request and auto-saves once pick finishes. Verified both structurally (the old silent
    early return is gone) and behaviorally, by running the real savePin()/pick() source under node
    through queuing, auto-save, cancel-on-failure, and toggle-cancel."""

    def test_save_pin_no_longer_silently_drops_missing_cur(self):
        body = extract_js_fn("savePin")
        self.assertNotIn("if(!CUR||SAVING)return;", body)
        self.assertIn("if(SAVING)return;", body)
        self.assertIn("if(!CUR){if(PICKING)togglePendingSave(); return;}", body)

    def test_pick_triggers_queued_save_on_success_and_clears_on_error(self):
        pick_body = extract_js_fn("pick")
        self.assertIn("if(PEND_SAVE){clearPendingSave(); savePin();}", pick_body)
        # the failure path (catch/d.error) also clears the pending save — it never saves silently.
        self.assertIn("clearPendingSave();", pick_body)
        self.assertRegex(pick_body, r"catch\(e\)\{if\(seq!==PICKSEQ\)return; setBusy\(false\); if\(!rp\)\{PICKING=false; clearPendingSave\(\);\}")

    def _harness(self, extra_body):
        stub = r"""
            const MQ_COARSE={matches:false}; const IS_MAC=false;
            function el(){return {hidden:true,textContent:'',innerHTML:'',value:'',dataset:{},
              scrollTop:0,disabled:false,classList:{toggle(){}},focus(){},remove(){}};}
            const els={}; const $=s=>(els[s]=els[s]||el());
            let PICKSEQ=0, PENDING=null, CUR=null, SAVING=false, PICKING=false, PEND_SAVE=false, REPICK=null;
            let LAYOUT='wide', LAST_PTR='mouse', OVERLAP_DISMISSED=null, SNIP_OPEN=false, PINS=[], EDIT=null, DOC=undefined;
            let KIND_NEW='fix'; function setKind(k){KIND_NEW=k==='question'?'question':'fix';} function mentionHints(){return [];}
            const ASSIGN_NEW={v:'agent',touched:false}; function renderAssignNew(){} function mentionPreview(){}
            function setBusy(){} function renderComposer(){} function overlapsFor(){return [];} function applySide(){}
            function selectionSnapshot(){return null;} function restoreSelection(){} let MID_OVERLAY=false; function relayout(){}
            function saveDraftSoon(){} function syncDraft(){}
            async function loadPins(){} function useLevel(){} function isRegion(){return false;} function kindFor(){return 'line';}
            function banner(){} function bannerRepick(){} function bannerCompare(){} function revealBox(){}
            async function refreshDoc(){} function setSide(){} function setSelMode(){} function toast(){} function dropPin(){}
            const apiCalls=[]; let pickResolve=null, pickReject=null, pinResolve=null;
            function api(url){apiCalls.push(url);
              if(url==='/api/pick')return new Promise((res,rej)=>{pickResolve=res;pickReject=rej;});
              if(url==='/api/pin')return new Promise(res=>{pinResolve=res;});
              return Promise.resolve({data:{}});}
            """
        return "\n".join([
            stub,
            extract_js_fn("saveBtnLabel"), extract_js_fn("togglePendingSave"), extract_js_fn("clearPendingSave"),
            extract_js_fn("savePin"), extract_js_fn("cancelSelection"), extract_js_fn("pick"),
            extra_body,
        ])

    def test_queued_save_fires_automatically_once_pick_resolves(self):
        js = self._harness(r"""
            (async()=>{
              const out={};
              const p = pick({page:1,x0:0,y0:0,x1:1,y1:1});
              await Promise.resolve(); await Promise.resolve();
              out.pickingWhileWaiting = PICKING;
              savePin();   // 사용자가 pick 이 끝나기 전에 [핀 저장]을 누름
              out.queued = PEND_SAVE;
              out.btnPendingLabel = /위치 찾는 중.*저장 대기/.test(els['#btn-save'].innerHTML);
              out.pinCallsBeforeResolve = apiCalls.filter(u=>u==='/api/pin').length;
              pickResolve({data:{file:'/m.tex',name:'m.tex',lo:5,hi:5,raw_lo:5,raw_hi:5,page:1,
                default_level:null,overlaps:[],via:null,score:1,frac:0,quote:'',kind:'line'}});
              await p;
              out.autoSaved = PEND_SAVE===false;
              out.pinCallsAfterResolve = apiCalls.filter(u=>u==='/api/pin').length;
              out.curSetBeforeSave = !!CUR || out.pinCallsAfterResolve>0;
              pinResolve({data:{id:42}});
              await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
              out.btnLabelRestored = els['#btn-save'].innerHTML===saveBtnLabel();
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
        self.assertEqual(data["pinCallsBeforeResolve"], 0)   # no save request is sent before pick resolves
        self.assertTrue(data["autoSaved"])
        self.assertEqual(data["pinCallsAfterResolve"], 1)    # once pick resolves, the queued save fires automatically
        self.assertTrue(data["btnLabelRestored"])

    def test_pick_failure_clears_queued_save_without_saving(self):
        js = self._harness(r"""
            (async()=>{
              const out={};
              const p = pick({page:1,x0:0,y0:0,x1:1,y1:1});
              await Promise.resolve(); await Promise.resolve();
              savePin();
              out.queuedBeforeFailure = PEND_SAVE;
              pickResolve({data:{error:'못 찾음'}});
              await p;
              out.queuedAfterFailure = PEND_SAVE;
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
        self.assertEqual(data["pinCalls"], 0)   # nothing is saved if pick fails
        self.assertTrue(data["errorShown"])

    def test_clicking_save_again_cancels_the_queued_save(self):
        js = self._harness(r"""
            (async()=>{
              const out={};
              const p = pick({page:1,x0:0,y0:0,x1:1,y1:1});
              await Promise.resolve(); await Promise.resolve();
              savePin();
              out.queued = PEND_SAVE;
              savePin();   // 같은 버튼을 다시 누르면 대기를 취소(토글)
              out.canceled = PEND_SAVE===false;
              out.btnLabelRestored = els['#btn-save'].innerHTML===saveBtnLabel();
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
        # regression: starting a new selection with a long-press while CUR is already set (first selection
        # done), then clicking [핀 저장] before that response arrives, must not save the old CUR right
        # away — it should go to the PEND_SAVE queue and save the new location instead.
        js = self._harness(r"""
            (async()=>{
              const out={};
              const p1 = pick({page:1,x0:0,y0:0.3,x1:1,y1:0.31});
              pickResolve({data:{file:'/m.tex',name:'m.tex',lo:717,hi:741,raw_lo:717,raw_hi:741,page:5,
                default_level:null,overlaps:[],via:null,score:1,frac:0,quote:'',kind:'line'}});
              await p1;
              out.curAfterFirstPick = CUR && CUR.lo;
              const p2 = pick({page:1,x0:0,y0:0.7,x1:1,y1:0.71});
              await Promise.resolve(); await Promise.resolve();
              out.curClearedOnNewPick = (CUR===null);
              savePin();   // 스피너가 도는 동안(새 위치 응답 전) [핀 저장]을 누름
              out.pinCallsWhileWaiting = apiCalls.filter(u=>u==='/api/pin').length;
              out.queued = PEND_SAVE;
              pickResolve({data:{file:'/m.tex',name:'m.tex',lo:900,hi:920,raw_lo:900,raw_hi:920,page:5,
                default_level:null,overlaps:[],via:null,score:1,frac:0,quote:'',kind:'line'}});
              await p2;
              out.autoSaved = PEND_SAVE===false;
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
        self.assertEqual(data["pinCallsWhileWaiting"], 0)   # doesn't save with the old CUR before the new response arrives
        self.assertTrue(data["queued"])
        self.assertTrue(data["autoSaved"])
        self.assertEqual(data["pinCallsAfterSecondResolve"], 1)   # the queued save fires once the new location response arrives


class FrontendResponsiveBrowser(unittest.TestCase):
    """Real Chromium layout and keyboard regression; API/PDF rendering is outside this oracle.

    Run with: uv run pytest tests/test_viewer.py -k FrontendResponsiveBrowser. Uses $LIMN_CHROMIUM, a system
    Chrome/Chromium, or Playwright's bundled Chromium (`playwright install chromium`), in that order. It skips
    when none can start, unless LIMN_TEST_REQUIRE_BROWSER=1 (CI), where that is a failure.
    """

    @classmethod
    def setUpClass(cls):
        required = os.environ.get("LIMN_TEST_REQUIRE_BROWSER") == "1"
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            if required:
                raise
            raise unittest.SkipTest("Playwright unavailable") from None
        chrome = os.environ.get("LIMN_CHROMIUM") or shutil.which("google-chrome") or shutil.which("chromium")
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch(executable_path=chrome or None, args=["--no-sandbox"])
        except Exception as e:
            cls.pw.stop()
            if required:
                raise
            raise unittest.SkipTest("Chromium unavailable: %s" % e) from e
        cls.html = ps.build_html("Long-DemoPaper1", "#2563eb").replace("\nboot();", "\n")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def open_viewer(self, width, touch=False, preferences=None):
        context = self.browser.new_context(viewport={"width": width, "height": 900},
                                           is_mobile=touch, has_touch=touch)
        self.addCleanup(context.close)
        page = context.new_page()
        page.route("**/*", lambda route: route.fulfill(content_type="text/html", body=self.html)
                   if route.request.url == "http://viewer.test/" else route.abort())
        page.goto("http://viewer.test/")
        page.evaluate("""preferences => {
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
        }""", preferences)
        return page

    def test_toggle_stays_in_place_without_overflow_for_mouse_and_touch(self):
        for touch in (False, True):
            for width in (720, 820, 900, 1024, 1180, 1440):
                with self.subTest(width=width, touch=touch):
                    page = self.open_viewer(width, touch)
                    if touch:
                        page.evaluate("coach('touch','길게 누르면 문단을 고릅니다')")
                    self.assertEqual(page.evaluate("SIDE_OPEN"), width > 900)
                    toggle = page.locator('#nav-toc-toggle')
                    self.assertEqual(page.locator('[data-act="outline"]').count(), 1)
                    before = toggle.bounding_box()
                    self.assertGreaterEqual(before['y'], 0)
                    page.evaluate("document.querySelector('#left').scrollTop=480")
                    anchor = page.evaluate("topAnchor()")
                    toggle.click()  # Coach is still visible during this real hit test.
                    after = toggle.bounding_box()
                    self.assertEqual((before['x'], before['y']), (after['x'], after['y']))
                    self.assertEqual(page.evaluate("document.activeElement.id"), 'nav-toc-toggle')
                    current = page.evaluate("topAnchor()")
                    self.assertEqual(anchor['page'], current['page'])
                    self.assertAlmostEqual(anchor['frac'], current['frac'], delta=.003)
                    self.assertGreaterEqual(page.locator('#pdf-center').bounding_box()['width'], 480)
                    self.assertFalse(page.evaluate("document.documentElement.scrollWidth>innerWidth"))
                    self.assertFalse(page.evaluate("document.querySelector('#doc-nav').scrollWidth>document.querySelector('#doc-nav').clientWidth"))
                    if width < 1100:
                        self.assertEqual(toggle.get_attribute('aria-expanded'), 'true')
                        self.assertFalse(page.evaluate("SIDE_OPEN"))
                        page.keyboard.press('Escape')
                        self.assertEqual(toggle.get_attribute('aria-expanded'), 'false')
                        toggle.press('Enter')
                        page.locator('#btn-side').click()
                        self.assertEqual(toggle.get_attribute('aria-expanded'), 'false')
                        self.assertTrue(page.evaluate("SIDE_OPEN"))
                    else:
                        self.assertEqual(toggle.get_attribute('aria-expanded'), 'false')
                        toggle.press('Enter')
                        self.assertEqual(toggle.get_attribute('aria-expanded'), 'true')

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
        for width in (720, 820, 884, 968, 1024):
            with self.subTest(width=width):
                page = self.open_viewer(width, True)
                a = page.evaluate(probe)
                page.locator('#btn-side').click()
                b = page.evaluate(probe)
                self.assertNotEqual(a['open'], b['open'])
                for s in (a, b):
                    self.assertEqual(s['pos'], 'fixed')
                    self.assertEqual((s['bar']['x'], s['bar']['width'], s['bar']['y'] + s['bar']['height']), (0, width, 900))
                    self.assertEqual((s['nav']['x'], s['nav']['width']), (0, width))
                    self.assertEqual(s['blocked'], [])
                    self.assertEqual(s['clipped'], [])
                    self.assertLess(s['side']['x'] + s['side']['width'], width)
                    self.assertGreater(s['side']['x'] + s['side']['width'], width - 40)   # bottom-right corner (right thumb)
                opened = a if a['open'] else b
                self.assertGreaterEqual(opened['right']['y'], opened['nav']['y'] + opened['nav']['height'] - 1)
                self.assertLessEqual(opened['right']['y'] + opened['right']['height'], opened['bar']['y'] + 1)
                for k in ('x', 'y', 'width', 'height'):
                    self.assertAlmostEqual(a['side'][k], b['side'][k], delta=1)

    def test_overlay_defaults_follow_width_but_explicit_choice_and_draft_survive(self):
        page = self.open_viewer(820)
        self.assertFalse(page.evaluate("SIDE_OPEN"))
        page.set_viewport_size({'width': 1024, 'height': 900})
        page.wait_for_function("SIDE_OPEN")
        page.set_viewport_size({'width': 820, 'height': 900})
        page.wait_for_function("!SIDE_OPEN")
        page.locator('#btn-side').click()
        self.assertFalse(page.evaluate("prefs().midClosed"))
        page.set_viewport_size({'width': 1024, 'height': 900})
        page.wait_for_function("!MID_OVERLAY")
        page.set_viewport_size({'width': 820, 'height': 900})
        page.wait_for_function("MID_OVERLAY")
        self.assertTrue(page.evaluate("SIDE_OPEN"))
        page = self.open_viewer(1024)
        page.evaluate("document.querySelector('#composer').hidden=false")
        page.set_viewport_size({'width': 820, 'height': 900})
        page.wait_for_function("MID_OVERLAY")
        self.assertTrue(page.evaluate("SIDE_OPEN"))

    def test_saved_widths_clamp_without_overwriting_and_mobile_keeps_sheet(self):
        """A saved width is clamped for the screen but never overwritten; Home goes to the minimum; the phone keeps its sheet."""
        page = self.open_viewer(1180, preferences={'side': 430})
        self.assertEqual(page.locator('#right').bounding_box()['width'], 430)
        page = self.open_viewer(1024, preferences={'sideMid': 600})
        self.assertGreaterEqual(page.locator('#pdf-center').bounding_box()['width'], 480)
        self.assertEqual(page.evaluate("prefs().sideMid"), 600)
        page.locator('#grip').focus()
        page.keyboard.press('Home')   # the window-splitter key for the panel's minimum (End is its maximum)
        self.assertEqual(page.locator('#right').bounding_box()['width'], 300)
        page = self.open_viewer(390, True)
        self.assertFalse(page.locator('#doc-nav').is_visible())
        self.assertTrue(page.locator('#btn-doc').is_visible())
        self.assertFalse(page.evaluate("SIDE_OPEN"))
        page.locator('#btn-side').click()
        self.assertTrue(page.evaluate("SIDE_OPEN"))
        self.assertEqual(page.locator('#right').bounding_box()['width'], 390)
        page.locator('#btn-doc').click()
        self.assertTrue(page.locator('#docs-menu').is_visible())


class FrontendThread(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def run_js(self, script, layout="wide"):
        js = "\n".join([r"""
            const esc=t=>String(t==null?'':t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
            function who(a){return (a&&(a.name||a.login))||'';} function avatar(){return '<i class="av"></i>';}
            let LAYOUT='%s', REPLY=null, META=null; const THREAD_OPEN=new Set();
            """ % layout, js_icons(), extract_js_fn("arcTime"), js_thread(), script])
        return json.loads(run_node(js))

    def test_wide_shows_last_three_compact_shows_last_one(self):
        out = self.run_js(r"""
            const th=[1,2,3,4,5].map(i=>({id:i,by:{name:'S'},at:'2026-09-24 10:0'+i+':00',text:'m'+i}));
            const p={id:9,thread:th};
            const w=threadHtml(p,true), c=threadHtml(p,false); THREAD_OPEN.add(9); const all=threadHtml(p,false);
            const n=s=>(s.match(/class="msg"/g)||[]).length;
            console.log(JSON.stringify([n(w),/이전 2건 보기/.test(w),/m5/.test(w),/m2/.test(w),n(c),/이전 4건 보기/.test(c),/m5/.test(c),
              n(all),/스레드 접기/.test(all),threadHtml({id:1},true)]));
            """)
        self.assertEqual(out, [3, True, True, False, 1, True, True, 5, True, ""])

    def test_messages_escape_and_events_read_as_history(self):
        out = self.run_js(r"""
            const a=msgHtml({id:1,by:{name:'<b>x</b>'},at:'2026-09-24 10:00:00',text:'<img src=x onerror=1>'});
            const b=msgHtml({id:2,by:{name:'로컬/에이전트'},at:'2026-09-24 10:05:00',text:'고쳤다',ev:'close',ref:'PR #9'});
            const c=msgHtml({id:3,by:{name:'S'},at:'2026-09-24 10:06:00',text:'',ev:'confirm'});
            console.log(JSON.stringify([/&lt;img/.test(a),!/<img/.test(a),/&lt;b&gt;x/.test(a),/class="msg ev ev-close"/.test(b),
              /닫음 · PR #9/.test(b),/>고쳤다</.test(b),/>확인</.test(c),!/msg-t/.test(c),/09-24 10:05/.test(b)]));
            """)
        self.assertEqual(out, [True] * 9)

    def test_reply_slot_rendered_for_open_editor(self):
        out = self.run_js(r"""
            REPLY={id:4,mode:'reply'};
            console.log(JSON.stringify([/reply-slot/.test(threadHtml({id:4},true)),threadHtml({id:5},true)]));
            """)
        self.assertEqual(out, [True, ""])

    def test_card_has_question_badge_reply_button_and_thread_count(self):
        body = extract_js_fn("card")
        self.assertIn("if(isQuestion(p))tags.unshift(", body)
        self.assertIn('data-act="reply-open"', body)
        self.assertIn("threadHtml(p,LAYOUT==='wide')", body)
        self.assertIn("ic('message-square')", body)

    def test_reply_editor_survives_redraw_and_save_sends_kind(self):
        """The reply box survives list redraws, Esc closes it first, and a save sends the pin kind."""
        dp = extract_js_fn("drawPins")
        self.assertIn("slot.replaceWith(REPLY.el)", dp)
        self.assertIn("rta.focus()", dp)
        self.assertIn("body.kind_req=KIND_NEW;", extract_js_fn("savePin"))
        self.assertIn("setKind('fix')", extract_js_fn("cancelSelection"))
        self.assertIn("KIND_NEW==='question'?'무엇이 궁금한지 적어 주세요'", extract_js_fn("setKind"))
        self.assertIn("if(REPLY){e.preventDefault();closeReply();return;}", ps.HTML)   # Esc closes the input field first
        self.assertIn('id="c-kind"', ps.HTML)
        send = extract_js_fn("sendReply")
        self.assertIn("api('/api/pins/'+id+'/reply',{method:'POST',body,what:'답글',keepalive:true})", send)   # one path; the server decides
        self.assertIn("body.reopen=R.toggle==='reopen'", send)               # the one override: [상태 유지] / [다시 열기]
        self.assertIn("deferred(", send)                                      # sent when the undo toast goes away

    def test_compact_collapsed_card_hides_thread(self):
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn("body.compact .pin:not(.open):not(.editing) :is(.tags,.au,.note,.acts,.head>.sp,.thread){display:none}", css)


class FrontendReview(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_review_card_suggests_author_and_offers_confirm_and_reply(self):
        js = "\n".join([r"""
            const esc=t=>String(t==null?'':t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
            const T={stale:'s',n:'n',loc:'l',view:'v',edit:'e',close:'c',drop:'d',review:'r',confirm:'k',reply:'y'};
            let EDIT=null, PINS=[], META={me:{login:'bob@example.com',name:'Bob Park'}};
            const OPEN_CARDS=new Set();
            function viaTag(){return null;} function relBadge(){return null;} function claimActive(){return false;}
            function authorTip(){return 'tip';} function who(a){return a?(a.name||a.login):'';} function avatar(){return '';}
            let SHOW_ALL=false, DOCS=[], DOC='main', DEFAULT_DOC='main', LAYOUT='wide', REPLY=null; function docInfo(){return null;}
            const THREAD_OPEN=new Set();
            """, extract_js_fn("rng"), extract_js_fn("multiDoc"), extract_js_fn("pdoc"), extract_js_fn("isRegion"),
            extract_js_fn("locText"), extract_js_fn("locCopy"), extract_js_fn("docChip"), extract_js_fn("arcTime"), js_thread(),
            extract_js_fn("card"), js_icons(), r"""
            const base={id:3,file:'/m.tex',name:'m.tex',lo:1,hi:2,page:1,note:'n',done:true,review:true,state:'review',
              closed_by:{login:'local',name:'로컬/에이전트'},thread:[{id:1,by:{name:'로컬/에이전트'},at:'2026-09-24 10:00:00',text:'고침',ev:'close'}]};
            const mine=card(Object.assign({},base,{author:{login:'bob@example.com',name:'Bob Park'}}));
            const other=card(Object.assign({},base,{author:{login:'w@x',name:'Wendy Kim'}}));
            const open=card({id:4,file:'/m.tex',name:'m.tex',lo:1,hi:2,page:1,note:'n'});
            console.log(JSON.stringify([/class="pin card review/.test(mine),/내 확인 차례/.test(mine),/b-confirm btn-soft/.test(mine),
              /Wendy Kim님 확인 필요/.test(other),/class="btn-sm b-confirm"/.test(other),!/rv-reopen/.test(other)&&/data-act="reply-open"/.test(other),
              !/data-act="close"/.test(other),!/data-act="drop"/.test(other),/ev-close/.test(other),!/review/.test(open)]));
            """])
        self.assertEqual(json.loads(run_node(js)), [True] * 10)

    def test_review_toast_and_partition(self):
        js = "\n".join([r"""
            function who(a){return (a&&(a.name||a.login))||'';}
            const TOASTS=[]; function toast(m,k){TOASTS.push(m);} function restorePin(){}
            const MY_ACTIONS=new Map();
            """, extract_js_fn("markMine"), extract_js_fn("consumeMine"), extract_js_fn("diffToast"), extract_js_fn("pinState"),
            extract_js_fn("reviewToast"), r"""
            diffToast([{id:1},{id:2}],[{id:1,done:true,review:true},{id:2,done:true}],[]);
            reviewToast([{id:5},{id:6},{id:7}],[{id:5,done:true,confirmed_by:{name:'W'}},{id:6,done:false},{id:7,done:true,review:true}]);
            markMine(8); reviewToast([{id:8}],[{id:8,done:true}]);
            console.log(JSON.stringify(TOASTS));
            """])
        out = json.loads(run_node(js))
        self.assertEqual(out, ["#2 이 완료되었습니다", "#1 이 검토 대기로 넘어왔습니다 — 결과를 보고 [확인]하세요",
                               "#5 확인됨 · W", "#6 다시 열림"])
        body = extract_js_fn("loadPins")
        self.assertIn("REVIEW_ALL=d.filter(p=>pinState(p)==='review')", body)
        self.assertIn("DONE_ALL=d.filter(p=>pinState(p)==='done')", body)
        self.assertIn('id="sec-review"', ps.HTML)
        self.assertIn('id="side-rv"', ps.HTML)

    def test_review_card_reply_hint_says_what_a_reply_does(self):
        # observed bug (v0.2.0): a review card's reply field used the same hint text as a normal reply, so it wasn't clear what
        # a reply would do. v0.2.2: on a closed pin the placeholder says a reply reopens it, and the outcome line under the
        # box previews the server rule (tests/test_v022.py covers every row).
        body = extract_js_fn("replyEl")
        self.assertIn("placeholder=\"'+esc(replyPlaceholder(p,isHuman(),false))+'\"", body)   # from the same outcome as the line below
        self.assertIn("'무엇이 틀렸는지 적으면 다시 열려 에이전트에게 갑니다 (⌘/Ctrl+Enter 보내기)'", extract_js_fn("replyPlaceholder"))
        self.assertIn('class="r-outcome"', body)
        self.assertIn('data-act="reply-flip"', body)
        self.assertIn("REPLY={id,flip:false,toggle:null,el:replyEl(p)}", extract_js_fn("openReply"))


# ---------------------------------------------------------------- [변경 보기] (docs/handbook/viewer.md §변경 보기)
class FrontendChangeView(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def run_js(self, script):
        js = "\n".join([extract_js_fn(n) for n in ("matchRevision", "pinFileIndex", "hunkRanges", "touchesPin", "revisionFiles")]
                       + [script])
        return json.loads(run_node(js))

    def test_ref_picks_commit_by_sha_then_pr_number(self):
        revs = [{"id": "0a569cc" + "1" * 33, "subject": "Clarify experimental questions (#238)"},
                {"id": "2cb7240" + "2" * 33, "subject": "Resolve manuscript viewer pins 19–41 (#236)"},
                {"id": "f47c6bf" + "3" * 33, "subject": "manuscript: 원고 핀 12건 반영 (#235)"},
                {"id": "1d422a6" + "4" * 33, "subject": "Merge pull request #203 from example-lab/docs"}]
        out = self.run_js("const revs=%s; console.log(JSON.stringify(['PR #235 (f47c6bf)','paper PR #236; code PR #75',"
                          "'paper PR #236','#203','PR #999','', 'abcdef1'].map(r=>{const m=matchRevision(r,revs);return m&&[m.id.slice(0,7),m.via];})));"
                          % json.dumps(revs))
        self.assertEqual(out, [["f47c6bf", "sha"], ["2cb7240", "pr"], ["2cb7240", "pr"], ["1d422a6", "pr"], None, None, None])

    def test_pin_file_and_line_overlap(self):
        patch = ("diff --git a/manuscript/1st/x.tex b/manuscript/1st/x.tex\n--- a/manuscript/1st/x.tex\n+++ b/manuscript/1st/x.tex\n"
                 "@@ -10,3 +10,4 @@ ctx\n a\n+b\n c\n d\n@@ -80 +81 @@\n-x\n+y\n"
                 "diff --git a/manuscript/1st/y.tex b/manuscript/1st/y.tex\n@@ -1 +1 @@\n-q\n+r\n")
        out = self.run_js("const f=revisionFiles(%s); console.log(JSON.stringify([pinFileIndex(f,'/home/u/paper/manuscript/1st/x.tex'),"
                          "pinFileIndex(f,'/home/u/paper/manuscript/1st/zz.tex'), hunkRanges(f[0].text),"
                          "touchesPin(f,{file:'/p/manuscript/1st/x.tex',lo:15,hi:16}), touchesPin(f,{file:'/p/manuscript/1st/x.tex',lo:40,hi:41}),"
                          "touchesPin(f,{file:'/p/manuscript/1st/x.tex',lo:84,hi:90}), touchesPin(f,{file:'/p/other.tex',lo:1,hi:1})]));"
                          % json.dumps(patch))
        self.assertEqual(out, [0, -1, [[10, 13], [81, 81]], True, False, True, False])

    def test_wiring(self):
        h = ps.HTML
        self.assertIn('data-act="change"', extract_js_fn("doneCard"))
        self.assertIn('data-act="change"', extract_js_fn("card"))
        self.assertIn("case 'change':if(id!=null)showChange(id);break;", h)
        self.assertIn('id="revision-pin"', h)
        self.assertIn("showRevision(pick.id,'source')", extract_js_fn("loadRevisions"))
        fmt = extract_js_fn("setRevisionFormat")
        self.assertIn("REVISION_PDF_COMMIT!==REVISION_COMMIT", fmt)       # the comparison PDF is only built while viewing that format
        css = h[h.index("<style>"):h.index("</style>")]
        self.assertIn("body.revision-open #revision-view{display:block}", css)   # it opens even on a folded fold device

    def test_pin_scope_wiring(self):
        """The pin-scoped view's markup, actions, pin parameter, one-time fallback and shared CSS rules stay wired (v0.3)."""
        # v0.3 (docs/handbook/viewer.md §변경 보기, ADR-0005): the pin's hunks, the rest folded under one control, one PDF toggle
        h = ps.HTML
        self.assertIn('<button id="revision-other-toggle" class="btn-ghost btn-sm" data-act="revision-other" aria-expanded="false" '
                      'aria-controls="revision-other" hidden>', h)
        self.assertIn('<pre id="revision-other" class="nowrap" hidden></pre>', h)
        self.assertIn('<button id="revision-whole" class="tg btn-sm" data-act="revision-whole" aria-pressed="false" hidden', h)
        self.assertIn("case 'revision-other':toggleRevisionOther();break;", h)
        self.assertIn("case 'revision-whole':setRevisionWhole(!REV_SCOPE.whole);break;", h)
        src = extract_js_fn("loadRevisionSource")
        self.assertIn("'&pin='+tg0.id", src)                            # a pin's view asks for its scope; plain browsing does not
        self.assertIn("r.scope.mode==='pin'", src)
        pdf = extract_js_fn("loadRevisionPdf")
        self.assertIn("!REV_SCOPE.whole&&!REV_SCOPE.fallback?tg.id:null", pdf)
        self.assertIn("REV_SCOPE.fallback=true", pdf)                   # a subset that does not compile falls back once
        self.assertIn("REV_SCOPE.whole=REV_SCOPE.partial=REV_SCOPE.fallback=false", extract_js_fn("showRevision"))
        css = h[h.index("<style>"):h.index("</style>")]
        # the folded diff shares every source-diff rule (its selector first, so the existing strings stay whole)
        for rule in (" .rd-line{", ".wrap .rd-code{", " .rd-add{", " .rd-del{", " .rd-hunk{"):
            self.assertIn("#revision-other%s,#revision-diff%s" % (rule[:-1], rule), css)
        self.assertIn("#revision-other-toggle[aria-expanded=true] .ic{transform:rotate(90deg)}", css)


class FrontendMentions(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def run_js(self, script):
        js = "\n".join([r"""
            const esc=t=>String(t==null?'':t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
            let PEOPLE=[{login:'w@x',name:'Wendy Kim'},{login:'wo@x',name:'Wendy'},{login:'s@x',name:'Bob Park'},{login:'k@x',name:'김<b>'}];
            let META={me:{login:'s@x',name:'Bob Park'}};
            function threadOf(p){return Array.isArray(p&&p.thread)?p.thread:[];}
            const PINSET={12:1,3:1}; function findAnyPin(id){return PINSET[id]?{id}:null;} let DROPPED=[{id:40}];
            function tr(s){return s;}
            function ic(n){return '<svg class="ic ic-'+n+'"></svg>';}
            """] + [extract_js_fn(n) for n in ("peopleName", "mentionToks", "reEsc", "meLogin", "pinRefExists", "pinRefGone", "fmtText", "mentionsMe",
                                               "mentionQuery", "mentionMatches", "mentionHints", "mentionScan", "defaultAssignee", "assignPeople")]
            + [script])
        return json.loads(run_node(js))

    def test_highlight_does_not_double_wrap_and_escapes(self):
        out = self.run_js(r"""
            console.log(JSON.stringify([fmtText('@Wendy Kim 와 @Wendy <i>',['w@x','wo@x']), fmtText('@김<b> 안녕',['k@x']),
              fmtText('@Bob Park',[])]));""")
        def tip(name):
            """The tooltip attribute fmtText() puts on a resolved @-tag for name."""
            return ' data-tip="@태그 — %s에게 알림이 갑니다"' % name
        self.assertEqual(out, ['<span class="mention"%s>@Wendy Kim</span> 와 <span class="mention"%s>@Wendy</span> &lt;i&gt;' % (tip("Wendy Kim"), tip("Wendy")),
                               '<span class="mention"%s>@김&lt;b&gt;</span> 안녕' % tip("김&lt;b&gt;"), '@Bob Park'])

    def test_mention_of_me_is_stronger_and_unresolved_stays_plain(self):
        # author feedback (2026-09-24): couldn't tell a real mention from plain text. Only a resolved tag
        # becomes a token; being mentioned gets .me; an unresolved '@word' stays plain text.
        out = self.run_js(r"""
            console.log(JSON.stringify([fmtText('@Bob Park 봐 주세요 @홍길동',['s@x']), fmtText('mail a@Bob Park',['s@x']),
              fmtText('@Bob Parkx',['s@x']), fmtText('@bob park',['s@x'])]));""")
        self.assertEqual(out[0], '<span class="mention me" data-tip="나를 부름 — 이 핀 알림이 나에게 옵니다">@Bob Park</span> 봐 주세요 @홍길동')
        self.assertEqual(out[1], 'mail a@Bob Park')                       # something shaped like an email address is not a mention
        self.assertNotIn("mention", out[2])                                   # letters right after a name make it a different word
        self.assertIn('class="mention me"', out[3])                          # case-insensitive (same as the server)

    def test_pin_refs_link_only_existing_pins_and_skip_entities(self):
        out = self.run_js(r"""
            console.log(JSON.stringify([fmtText("#12 과 #99 그리고 it's (#3) #40",[]), fmtText('a#12 &#12;',[])]));""")
        self.assertEqual(out[0].count('data-act="pin-ref"'), 3)             # 12/3/40 (a dropped pin) — nonexistent 99 stays plain text
        self.assertIn('data-ref="12"', out[0])
        self.assertIn('data-ref="40"', out[0])
        self.assertNotIn('data-ref="99"', out[0])
        self.assertIn('<span class="pin-ref gone"', out[0])                  # v0.2.2: #40 is in the Trash - it reads 'deleted pin'
        self.assertIn('#40 <small>삭제된 핀</small>', out[0])
        self.assertIn("it&#39;s", out[0])                                     # the escaped &#39; is not a link
        self.assertNotIn("pin-ref", out[1])

    def test_scan_lists_who_gets_notified_and_unresolved_words(self):
        out = self.run_js(r"""
            console.log(JSON.stringify([mentionScan('@Bob Park 와 @홍길동 그리고 @Wendy Kim',new Set()), mentionScan('a@b.com',new Set()),
              mentionScan('@Wendy 봐',new Set(['wo@x']))]));""")
        self.assertEqual(out[0], {"hit": ["s@x", "w@x"], "bad": ["홍길동"], "first": "s@x"})
        self.assertEqual(out[1], {"hit": [], "bad": [], "first": None})
        self.assertEqual(out[2]["hit"][0], "wo@x")

    def test_default_assignee_rules(self):
        # if the note starts with a resolved @-mention, that person; otherwise the first @-mention on a question pin; otherwise the agent. I (s@x) can't be chosen.
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
              assignPeople('메모',new Set(),'k@x')]));""")
        self.assertEqual(out, ["w@x", "w@x", "agent", "w@x", "agent", "w@x", "agent", "agent", ["w@x"], ["k@x"]])

    def test_assign_controls_in_composer_edit_and_card(self):
        h = ps.HTML
        self.assertIn('<div id="c-assign" class="assign-row" role="radiogroup" aria-label="담당" hidden></div>', h)
        self.assertIn("'<div class=\"e-assign assign-row\" role=\"radiogroup\" aria-label=\"담당\" hidden></div>'", h)
        self.assertIn("body.assignee=ASSIGN_NEW.v||'agent';", extract_js_fn("savePin"))
        self.assertIn("if(E.assignee&&E.assignee!==E.orig.assignee)body.assignee=E.assignee;", extract_js_fn("saveEdit"))
        self.assertIn("assignChip(p)+thn+au", extract_js_fn("card"))
        self.assertIn("const adr=p.assignee?'':addressedTag(p);", extract_js_fn("card"))
        self.assertIn("assigned:5", h)
        self.assertIn("assign:'담당 바꿈'", h)

    def test_preview_row_under_every_mention_field(self):
        h = ps.HTML
        self.assertIn('<div id="note-mentions" class="m-preview" aria-live="polite" hidden></div>', h)
        self.assertEqual(h.count('</textarea><div class="m-preview" aria-live="polite" hidden></div>'), 2)   # edit and reply
        body = extract_js_fn("mentionPreview")
        self.assertIn("등록된 사람이 아님", body)
        self.assertIn("ic('at-sign')+'알림</span>'", body)
        css = h[h.index("<style>"):h.index("</style>")]
        self.assertRegex(css, r"\.mention\{color:var\(--primary\);font-weight:600;background:color-mix\(in srgb,var\(--primary\) 12%")
        self.assertIn(".mention.me{background:color-mix(in srgb,var(--primary) 28%", css)
        self.assertIn(".mention-bad{", css)

    def test_query_matches_and_hints(self):
        out = self.run_js(r"""
            const ta=(v,pos)=>({value:v,selectionStart:pos==null?v.length:pos,selectionEnd:pos==null?v.length:pos});
            const q=[mentionQuery(ta('안녕 @Won')),mentionQuery(ta('mail a@b')),mentionQuery(ta('@')),mentionQuery(ta('@Won ch'))];
            const m=mentionMatches('wen',PEOPLE,'s@x').map(p=>p.login), mine=mentionMatches('',PEOPLE,'s@x').map(p=>p.login);
            const t=ta('@Wendy Kim 봐 주세요'); t._mentions=new Set(['w@x','s@x']);
            console.log(JSON.stringify([q,m,mine.includes('s@x'),mentionHints(t),
              mentionsMe({addressed:['s@x']}),mentionsMe({addressed:['w@x']}),mentionsMe({mentions:['s@x'],thread:[{mentions:['s@x']}]})]));""")
        self.assertEqual(out, [[{"start": 3, "q": "Won"}, None, {"start": 0, "q": ""}, None], ["wo@x", "w@x"], False,
                               ["w@x"], True, False, False])
        # mentionsMe only looks at p.addressed, pre-computed by the server (question pin, current round) —
        # it does not scan the full legacy mentions/thread
        # (observed bug: an @-mention from an old round stayed marked as "a pin that called me" even after reopening).

    def test_wiring(self):
        h = ps.HTML
        self.assertIn('id="mention-pop"', h)
        self.assertIn('id="mention-filter"', h)
        self.assertIn("const mh=mentionHints($('#note')); if(mh.length)body.mentions=mh;", extract_js_fn("savePin"))
        self.assertIn("mentionHints(ta)", extract_js_fn("sendReply"))
        self.assertIn("fmtText(p.note,p.mentions)", extract_js_fn("card"))
        self.assertIn("window.addEventListener('keydown',e=>{if(!MENTION.ta", h)   # autocomplete gets Enter/Esc first (capture phase)


# ---------------------------------------------------------------- browser notifications (docs/handbook/viewer.md §브라우저 알림)
class FrontendSpacingGrid(unittest.TestCase):
    """Spacing (padding/margin/gap) sits on a 4/8px grid (4, 8, 12, 16, 24). 1-2px is left alone as
    hairline borders / optical correction (e.g. 1px above/below a badge). It used to mix in ad hoc values
    like 6, 10, 14, 18px (grid cleanup QA 2026-09-25)."""
    def test_spacing_is_on_the_grid(self):
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
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
            json.dumps(r), json.dumps(g), h, top, bot)
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


class FrontendMentionTypingNotFlagged(unittest.TestCase):
    """A '@word' still being typed isn't flagged as '등록된 사람이 아님' right away (QA 2026-09-25 — a warning showed up while typing @Sa)."""
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_token_under_caret_is_not_flagged_until_caret_leaves(self):
        js = extract_js_fn("mentionBadSettled") + r"""
            console.log(JSON.stringify([
              mentionBadSettled(['Sa'],'@Sa',{start:0,q:'Sa'}),            // 쓰는 중 — 알리지 않는다
              mentionBadSettled(['Sa'],'@Sa',null),                       // 커서가 떠남 — 알린다
              mentionBadSettled(['홍길동','Sa'],'@홍길동 @Sa',{start:5,q:'Sa'}),  // 끝난 말은 그대로 알린다
              mentionBadSettled(['Sa'],'@Sa 또 @Sa',{start:7,q:'Sa'})]));   // 같은 말이 앞에 이미 있으면 알린다"""
        self.assertEqual(json.loads(run_node(js)), [[], ["Sa"], ["홍길동"], ["Sa"]])

    def test_list_highlight_is_a_flat_full_width_row(self):
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn("#mention-pop{position:fixed;z-index:90;min-width:200px;max-width:min(360px,calc(100vw - 16px));padding:var(--space-1) 0;", css)
        self.assertIn("border:0;border-radius:0;background:transparent;text-align:left;padding:var(--space-2) var(--space-3)}", css)


class FrontendQuestionHint(unittest.TestCase):
    """Suggests [질문으로 보내기] (send as a question) for a note that reads like a question (looksQuestion).
    A coauthor saved "...표현한 의도가 있는건가?" as a fix request (2026-09-25). This only judges — the kind
    changes only when the user clicks."""
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def judge(self, texts):
        js = extract_js_fn("looksQuestion") + "\nconsole.log(JSON.stringify(%s.map(looksQuestion)));" % json.dumps(texts, ensure_ascii=False)
        return json.loads(run_node(js))

    def test_question_marks(self):
        texts = ["여기 이렇게 쓴 이유가 있는건가?", "식의 k란..?", "100개가 어떻게 나온것인지?", "Why is this here?",
                 "전각 물음표？", "끝에 공백 ?  ", "이거 맞나요? @Bob Park", "맞나요?)", "뭐임??"]
        self.assertEqual(self.judge(texts), [True] * len(texts))

    def test_korean_interrogative_endings_without_mark(self):
        texts = ["의도가 있는 건가", "이 정의가 맞는가", "이거 맞나요", "그림으로 바꾸면 어떨까요", "이게 최선인가", "이거 누가 썼니",
                 "이게 맞냐", "그래프로 보이는 게 낫지 않을까", "이해가 됩니까.", "확인했나요 @Bob Park", "정의가 있나요…"]
        self.assertEqual(self.judge(texts), [True] * len(texts))

    def test_statements_are_not_questions(self):
        texts = ["", "   ", "예시 아님.", "이건 삭제하는게 좋을듯", "표 주석은 굳이 있을 필요 없음. 삭제.",
                 "여기 의도가 있는건가? 그래도 고쳐줘.", "더블 컬럼", "@Bob Park 확인 부탁합니다", "?는 쓰지 말 것", "TODO: fix eq. (3)"]
        self.assertEqual(self.judge(texts), [False] * len(texts))

    def test_hint_is_wired_to_both_forms_and_never_switches_by_itself(self):
        html = ps.HTML
        self.assertIn('id="c-qhint"', html)                                   # composer
        self.assertIn('class="e-qhint q-hint"', html)                         # edit panel (the kind can be changed)
        self.assertIn('data-act="kind" data-kind="question"', html)           # clicking it switches — same as the existing kind action
        self.assertIn('data-act="e-kind" data-kind="question"', html)
        qh = extract_js_fn("qHint")
        self.assertNotIn("setKind", qh)                                      # only suggests
        self.assertNotIn("kind_req=", qh)
        self.assertIn("kind==='question'", qh)                                # hidden if it's already a question


class FrontendNotify(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def harness(self, script):
        rank = re.search(r"^const NOTIFY_RANK=.*;$", ps.HTML, re.M).group(0)
        return "\n".join([rank, r"""
            function who(a){return (a&&(a.name||a.login))||'';}
            const store={}; const localStorage={getItem:k=>k in store?store[k]:null,setItem:(k,v)=>{store[k]=String(v);}};
            let NOTIFY=true; function notifyOn(){return NOTIFY;}
            let META={me:{login:'w@x',name:'Wendy Kim'},label:'DEMO-B'}; const SHOWN=[];
            function notifyShow(e){SHOWN.push([e.pin,e.type]);}
            """] + [extract_js_fn(n) for n in ("notifyCursor", "setNotifyCursor", "notifyQuery", "pickNotifications",
                                               "notifyText", "notifyHandle")] + [script])

    def test_trigger_selection_self_suppression_and_dedupe(self):
        js = self.harness(r"""
            const me={login:'w@x'}, S={login:'s@x',name:'Bob Park'};
            const evs=[{seq:1,type:'replied',pin:5,to:['w@x'],by:S},{seq:2,type:'mention',pin:5,to:['w@x'],by:S},
              {seq:3,type:'review_requested',pin:6,to:['w@x'],by:{login:'local'}},{seq:4,type:'replied',pin:7,to:['s@x'],by:S},
              {seq:5,type:'mention',pin:8,to:['w@x'],by:{login:'w@x'}},{seq:6,type:'confirmed',pin:9,to:['w@x'],by:S},
              {seq:7,type:'reopened',pin:6,to:['w@x'],by:S}];
            const a=pickNotifications(evs,me,0).map(e=>[e.pin,e.type]);
            const b=pickNotifications(evs,me,2).map(e=>[e.pin,e.type]);
            const c=pickNotifications(evs,{login:'local'},0);
            console.log(JSON.stringify([a,b,c,notifyText(evs[1]),notifyText({type:'review_requested',pin:6,excerpt:'답했다\n둘째',doc_name:'본문'})]));
            """)
        out = json.loads(run_node(js))
        self.assertEqual(out[0], [[5, "mention"], [6, "reopened"]])          # one per pin — mention/reopened win
        self.assertEqual(out[1], [[6, "reopened"]])
        self.assertEqual(out[2], [])
        self.assertEqual(out[3], {"title": "핀 #5 · DEMO-B", "body": "Bob Park님이 불렀습니다: "})
        self.assertEqual(out[4], {"title": "핀 #6 · 본문", "body": "검토 대기: 답했다"})

    def test_cursor_prevents_refire_across_reloads_and_tabs(self):
        js = self.harness(r"""
            const S={login:'s@x',name:'S'};
            notifyHandle({ev_seq:4});                                   // 처음 켠 브라우저 — 지난 이벤트는 건너뛴다
            const c0=notifyCursor(), q=notifyQuery();
            const d={ev_seq:6,events:[{seq:5,type:'mention',pin:1,to:['w@x'],by:S},{seq:6,type:'replied',pin:2,to:['w@x'],by:S}]};
            notifyHandle(d);                                            // 탭 A
            notifyHandle(d);                                            // 탭 B 가 같은 응답을 늦게 받음(같은 localStorage)
            notifyHandle({ev_seq:6,events:[]});                         // 새로고침 뒤
            NOTIFY=false; notifyHandle({ev_seq:9,events:[{seq:9,type:'mention',pin:3,to:['w@x'],by:S}]});
            console.log(JSON.stringify([c0,q,SHOWN,notifyCursor(),notifyQuery()]));
            """)
        self.assertEqual(json.loads(run_node(js)), [4, "&ev=4", [[1, "mention"], [2, "replied"]], 6, ""])

    def test_wiring(self):
        h = ps.HTML
        self.assertIn('id="m-notify"', h)
        self.assertIn('id="btn-notify"', h)
        tog = extract_js_fn("notifyToggle")
        self.assertIn("Notification.requestPermission()", tog)
        self.assertEqual(html_without_comments(h).count("requestPermission("), 1)   # only asked on the click path
        self.assertIn("reg.showNotification(", extract_js_fn("notifyShow"))
        self.assertNotIn("new Notification(", html_without_comments(h))
        self.assertIn("tag:'pin-'+e.pin", extract_js_fn("notifyShow"))
        self.assertIn("document.visibilityState==='visible'&&document.hasFocus()", extract_js_fn("notifyShow"))
        self.assertIn("notifyQuery()", extract_js_fn("pollLightOnce"))
        self.assertIn("navigator.serviceWorker.register('/sw.js'", extract_js_fn("notifyRegister"))


if __name__ == "__main__":
    unittest.main()

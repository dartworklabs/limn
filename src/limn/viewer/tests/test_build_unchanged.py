"""The viewer's answer to a rebuild that kept the pages (docs/handbook/build-sync.md §따뜻한 LaTeX와 변경 없는 재빌드).

An unchanged rebuild counts no build, so the seq-driven completion of pollBuildOnce never runs for it. A rebuild this
tab asked for (BUILD.asked) that reads `unchanged: true` with the same seq gets one "변경 없음" answer, with a
[그래도 빌드] action that forces a cold rebuild (POST /api/rebuild?async=1&force=1), and no refresh (buildUnchanged).
On every band - the desktop's line under its status chips too (#167: no toast) - the answer is the status line's item
for STATUS_TRANSIENT_MS. Run under node with the real pollBuildOnce, buildUnchanged, statusText, statusAct and rebuild
and stand-ins for the rest.

Run: uv run pytest -q src/limn/viewer/tests/test_build_unchanged.py
"""

import json
import os
import re
import shutil
import unittest

from helpers import HTML, UI_EN, extract_js_fn, js_i18n, js_markup, run_node

UNCHANGED = {"ko": "변경 없음", "en": "No changes"}


def transient_ms() -> str:
    """The viewer's `const STATUS_TRANSIENT_MS=...;` (status.js) as the page declares it."""
    found = re.search(r"^const STATUS_TRANSIENT_MS=\d+;", HTML, re.M)
    assert found is not None, "status.js no longer declares `const STATUS_TRANSIENT_MS=<ms>;` at line start"
    return found.group(0)


def tooltip_table() -> str:
    """The viewer's `const T={...};` (core.js) as the page declares it."""
    found = re.search(r"^const T=\{.*?^\};$", HTML, re.S | re.M)
    assert found is not None, "core.js no longer declares `const T={...};` at line start"
    return found.group(0)


class UnchangedAnswer(unittest.TestCase):
    """pollBuildOnce after an unchanged rebuild, and the status line item it leaves."""

    def setUp(self):
        """Skip without node, unless LIMN_TEST_REQUIRE_NODE=1 makes that a failure."""
        if not shutil.which("node"):
            if os.environ.get("LIMN_TEST_REQUIRE_NODE") == "1":
                self.fail("node required (LIMN_TEST_REQUIRE_NODE=1) but not installed")
            self.skipTest("node not available")

    def polls(self, lang: str, steps: str, layout: str = "wide") -> dict:
        """Run `steps` (JS awaiting poll(reply, asked)) against the real pollBuildOnce on a `layout` screen; returns what
        it logged (the status line's messages as said), with the line's redraws and the timers set."""
        js = "\n".join(
            [
                js_i18n(lang),
                tooltip_table(),
                transient_ms(),
                "let LAYOUT=%s;" % json.dumps(layout),
                r"""
            let DOC='a', SWITCHSEQ=1, META={kind:'tex',pages:[1,2]}; const SAID=[]; let REPLY, REFRESHES=0;
            let DRAWS=0; const TIMERS=[]; const drawStatus=()=>{DRAWS++;};
            const setTimeout=(f,ms)=>{TIMERS.push([f,ms]); return TIMERS.length;}, clearTimeout=()=>{};
            const BUILD={timer:null,error:null,lastSeq:5,booted:true,inflight:null,asked:false};
            const DOC_SEQ=new Map(), BUILD_ERR_BY=new Map();
            const chip={hidden:false,textContent:''}, btn={disabled:false}; const $=s=>s==='#build-chip'?chip:btn;
            const dq=u=>u; const pullSuffix=()=>''; const hideBuildErr=()=>{}; const showBuildErr=()=>{};
            const api=async()=>REPLY; const refreshDoc=async()=>{REFRESHES++;};
            const lineNote=(m,k,a)=>{SAID.push([m,k,a?a.label:null]);};
            const setInterval=()=>1, clearInterval=()=>{}, pollBuild=()=>{};
            async function poll(reply, asked){REPLY={data:reply}; if(asked)BUILD.asked=true; await pollBuildOnce();}""",
                *[extract_js_fn(n) for n in ("buildsFromSource", "buildChipText", "pollBuildOnce", "buildUnchanged")],
                "(async()=>{" + steps + "console.log(JSON.stringify({said:SAID,refreshes:REFRESHES,"
                "asked:BUILD.asked,seq:BUILD.lastSeq,line:!!BUILD.unchanged,draws:DRAWS,"
                "timers:TIMERS.map(t=>t[1])}));})();",
            ]
        )
        return json.loads(run_node(js))

    def test_an_asked_rebuild_that_kept_the_pages_is_answered_on_the_status_line_on_every_band(self):
        """The tab asked, the build state is ok with unchanged true and the seq it already processed: on the desktop and
        on the compact bands alike the status line is redrawn with BUILD.unchanged set, one timer of STATUS_TRANSIENT_MS
        clears it and redraws, nothing else is said and no page is refreshed; the same reply again says nothing more."""
        for layout in ("wide", "mid", "narrow"):
            with self.subTest(layout=layout):
                out = self.polls(
                    "ko",
                    "await poll({state:'ok',seq:5,unchanged:true,elapsed_s:0.3},true); const before=!!BUILD.unchanged;"
                    "await poll({state:'ok',seq:5,unchanged:true,elapsed_s:0.3},false);"
                    "TIMERS[0][0](); if(!before)throw Error('no line');",
                    layout=layout,
                )
                self.assertEqual((out["said"], out["refreshes"], out["asked"], out["seq"]), ([], 0, False, 5))
                self.assertEqual((out["timers"], out["line"], out["draws"]), ([6000], False, 2))

    def test_the_line_item_says_no_changes_with_build_anyway(self):
        """The item the answer leaves reads '변경 없음' / 'No changes' and its one action is [그래도 빌드]
        (data-act rebuild-force, a cold build) with the tip on what a cold build is for; without the right to rebuild it
        has no action."""
        for lang in ("ko", "en"):
            with self.subTest(lang=lang):
                js = "\n".join(
                    [
                        js_i18n(lang),
                        tooltip_table(),
                        js_markup(),
                        re.search(r"^const esc=.*;$", HTML, re.M).group(0),
                        "const ICONS={};",
                        *[extract_js_fn(n) for n in ("statusProgress", "statusList", "statusText", "statusAct")],
                        r"""const base={notices:[],build:null,buildErr:null,offline:false,sync:null,stale:false,png:false,unchanged:{pull:''}};
                        const L=statusList({...base,canRebuild:true}),N=statusList({...base,canRebuild:false});
                        console.log(JSON.stringify([statusText(L[0],'long')[0],String(statusAct(L[0])),String(statusAct(N[0]))]));""",
                    ]
                )
                text, act, none = json.loads(run_node(js))
                self.assertEqual(text, UNCHANGED[lang])
                self.assertIn('data-act="rebuild-force"', act)
                self.assertIn(">%s<" % (UI_EN["그래도 빌드"] if lang == "en" else "그래도 빌드"), act)
                self.assertEqual(none, "")
        self.assertEqual(UI_EN["그래도 빌드"], "Build anyway")

    def test_build_anyway_forces_a_cold_rebuild(self):
        """rebuild(true) - what the line's [그래도 빌드] calls - posts ?async=1&force=1, while a plain rebuild() posts
        ?async=1 only."""
        js = "\n".join(
            [
                js_i18n("ko"),
                r"""
            let DOC='a', SWITCHSEQ=1; const URLS=[]; const BUILD={inflight:null,asked:false};
            const dq=u=>u; const lineNote=()=>{}; const $=()=>({hidden:false}); let polls=0;
            const api=async(u,o)=>{URLS.push([u,o.method]); return {status:202};}; const pollBuild=async()=>{polls++;};""",
                extract_js_fn("rebuild"),
                "(async()=>{await rebuild(true); await rebuild(); console.log(JSON.stringify({urls:URLS,polls}));})();",
            ]
        )
        got = json.loads(run_node(js))
        self.assertEqual(
            got, {"urls": [["/api/rebuild?async=1&force=1", "POST"], ["/api/rebuild?async=1", "POST"]], "polls": 2}
        )

    def test_an_unchanged_mark_this_tab_did_not_ask_for_is_silent(self):
        """Another tab's or an agent's unchanged rebuild, or a running one, says nothing here: no line item, no message."""
        out = self.polls(
            "ko",
            "await poll({state:'ok',seq:5,unchanged:true},false);"
            "await poll({state:'running',phase:'copy',seq:5,elapsed_s:0},true);",
        )
        self.assertEqual((out["said"], out["line"], out["refreshes"], out["asked"]), ([], False, 0, True))

    def test_a_real_build_after_asking_is_the_usual_completion(self):
        """When the asked rebuild did build (a new seq), the usual completion runs and the ask is spent: one passing
        message on the status line saying the build finished, not 'no changes'."""
        out = self.polls("ko", "await poll({state:'ok',seq:6,elapsed_s:3},true);")
        self.assertEqual((out["refreshes"], out["asked"], out["seq"], out["line"]), (1, False, 6, False))
        self.assertEqual(len(out["said"]), 1)
        self.assertTrue(out["said"][0][0].startswith("PDF 재빌드 완료"))
        self.assertEqual(out["said"][0][1], "ok")


if __name__ == "__main__":
    unittest.main()

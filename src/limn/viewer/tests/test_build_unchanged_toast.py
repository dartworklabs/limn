"""The viewer's answer to a rebuild that kept the pages (docs/handbook/build-sync.md §따뜻한 LaTeX와 변경 없는 재빌드).

An unchanged rebuild counts no build, so the seq-driven completion of pollBuildOnce never runs for it. A rebuild this
tab asked for (BUILD.asked) that reads `unchanged: true` with the same seq gets one "변경 없음" toast, with a
[그래도 빌드] action that forces a cold rebuild (POST /api/rebuild?async=1&force=1), and no refresh. Run under node with
the real pollBuildOnce and rebuild and stand-ins for the rest.

Run: uv run pytest -q src/limn/viewer/tests/test_build_unchanged_toast.py
"""

import json
import os
import re
import shutil
import unittest

from helpers import HTML, UI_EN, extract_js_fn, js_i18n, run_node

UNCHANGED = {"ko": "변경 없음", "en": "No changes"}


def tooltip_table() -> str:
    """The viewer's `const T={...};` (core.js) as the page declares it."""
    found = re.search(r"^const T=\{.*?^\};$", HTML, re.S | re.M)
    assert found is not None, "core.js no longer declares `const T={...};` at line start"
    return found.group(0)


class UnchangedToast(unittest.TestCase):
    """pollBuildOnce after an unchanged rebuild."""

    def setUp(self):
        """Skip without node, unless LIMN_TEST_REQUIRE_NODE=1 makes that a failure."""
        if not shutil.which("node"):
            if os.environ.get("LIMN_TEST_REQUIRE_NODE") == "1":
                self.fail("node required (LIMN_TEST_REQUIRE_NODE=1) but not installed")
            self.skipTest("node not available")

    def polls(self, lang: str, steps: str) -> dict:
        """Run `steps` (JS awaiting poll(reply, asked)) against the real pollBuildOnce; returns what it logged."""
        js = "\n".join(
            [
                js_i18n(lang),
                tooltip_table(),
                r"""
            let DOC='a', SWITCHSEQ=1, META={kind:'tex',pages:[1,2]}; const TOASTS=[]; let REPLY, REFRESHES=0;
            const BUILD={timer:null,error:null,lastSeq:5,booted:true,inflight:null,asked:false};
            const DOC_SEQ=new Map(), BUILD_ERR_BY=new Map();
            const chip={hidden:false,textContent:''}, btn={disabled:false}; const $=s=>s==='#build-chip'?chip:btn;
            const dq=u=>u; const pullSuffix=()=>''; const hideBuildErr=()=>{}; const showBuildErr=()=>{};
            const api=async()=>REPLY; const refreshDoc=async()=>{REFRESHES++;};
            const toast=(m,k,a)=>{TOASTS.push([m,k,a?a.label:null]); ACTIONS.push(a);}; const ACTIONS=[], FORCED=[];
            const rebuild=f=>FORCED.push(f); const setInterval=()=>1, clearInterval=()=>{}, pollBuild=()=>{};
            async function poll(reply, asked){REPLY={data:reply}; if(asked)BUILD.asked=true; await pollBuildOnce();}""",
                *[extract_js_fn(n) for n in ("buildsFromSource", "buildChipText", "pollBuildOnce")],
                "(async()=>{" + steps + "console.log(JSON.stringify({toasts:TOASTS,refreshes:REFRESHES,"
                "asked:BUILD.asked,seq:BUILD.lastSeq,forced:FORCED}));})();",
            ]
        )
        return json.loads(run_node(js))

    def test_an_asked_rebuild_that_kept_the_pages_says_so_once(self):
        """The tab asked, the build state is ok with unchanged true and the seq it already processed: one 'no change'
        toast of kind ok, in Korean and English, no page refresh; the same reply again says nothing more."""
        for lang in ("ko", "en"):
            with self.subTest(lang=lang):
                out = self.polls(
                    lang,
                    "await poll({state:'ok',seq:5,unchanged:true,elapsed_s:0.3},true);"
                    "await poll({state:'ok',seq:5,unchanged:true,elapsed_s:0.3},false);",
                )
                self.assertEqual(out["toasts"], [[UNCHANGED[lang], "ok", "그래도 빌드"]])
                self.assertEqual((out["refreshes"], out["asked"], out["seq"]), (0, False, 5))
        self.assertEqual(UI_EN["그래도 빌드"], "Build anyway")

    def test_build_anyway_forces_a_cold_rebuild(self):
        """The toast's action calls rebuild(true), and rebuild(true) posts ?async=1&force=1 while a plain rebuild()
        posts ?async=1 only."""
        out = self.polls("ko", "await poll({state:'ok',seq:5,unchanged:true},true); ACTIONS[0].fn();")
        self.assertEqual(out["forced"], [True])
        js = "\n".join(
            [
                js_i18n("ko"),
                r"""
            let DOC='a', SWITCHSEQ=1; const URLS=[]; const BUILD={inflight:null,asked:false};
            const dq=u=>u; const toast=()=>{}; const $=()=>({hidden:false}); let polls=0;
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
        """Another tab's or an agent's unchanged rebuild, or a running one, toasts nothing here."""
        out = self.polls(
            "ko",
            "await poll({state:'ok',seq:5,unchanged:true},false);"
            "await poll({state:'running',phase:'copy',seq:5,elapsed_s:0},true);",
        )
        self.assertEqual((out["toasts"], out["refreshes"], out["asked"]), ([], 0, True))

    def test_a_real_build_after_asking_is_the_usual_completion(self):
        """When the asked rebuild did build (a new seq), the usual completion runs and the ask is spent."""
        out = self.polls("ko", "await poll({state:'ok',seq:6,elapsed_s:3},true);")
        self.assertEqual((out["refreshes"], out["asked"], out["seq"]), (1, False, 6))
        self.assertEqual(len(out["toasts"]), 1)
        self.assertNotEqual(out["toasts"][0][0], UNCHANGED["ko"])


if __name__ == "__main__":
    unittest.main()

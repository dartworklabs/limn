"""Mouse and touch input of the viewer: collapsing the pin panel, touch gestures, and the usability fixes of 0.3.x.

The owner-approved findings of the 2026-09-26 input review (docs/handbook/viewer.md §패널 폭과 시트 높이, §펼친 화면 레이아웃,
§모바일 레이아웃, §알림(토스트), §뜻과 모양). Two kinds of test:

- ``...Logic`` classes run the pure decision functions of ``app.js`` under node (skipped without node), in the style of
  ``test_viewer.FrontendPanelWidthLogic``: where a handle drag lands, which keys do what, how a swipe or a sheet drag ends.
- The browser classes drive the real viewer against the in-process server (``helpers_browser.BrowserBase``) at desktop
  1400x850 and 1280x720 (mouse), an unfolded Fold 842x758 and a phone 384x832 (touch, CDP touch events), in Korean and
  English, light and dark, and with reduced motion.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_input.py
"""

import base64
import json
import re
import time
import unittest
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from limn import __version__
from limn.pins.lifecycle.rules import CloseRequest
from limn.security.access import LOCAL_ACTOR

import helpers_figure
from helpers import HTML, UI_EN, add_pin, extract_js_fn, ps, run_node
from helpers_access import ALICE, BOB, actor
from helpers_authority import post_authority
from helpers_browser import BrowserBase, booted, nothing_follows, settle, watch_idle

HANGUL = re.compile(r"[가-힣]")
# boot() has finished on the ViewerBase fixture (three open pins).
BOOTED = booted(3)
DESK = {"viewport": {"width": 1400, "height": 850}}
LAP = {"viewport": {"width": 1280, "height": 720}}
FOLD = {"viewport": {"width": 842, "height": 758}, "is_mobile": True, "has_touch": True}
SIDE_BY_SIDE = {"viewport": {"width": 968, "height": 842}, "is_mobile": True, "has_touch": True}
PHONE = {"viewport": {"width": 384, "height": 832}, "is_mobile": True, "has_touch": True}

# What the panel looks like right now: width, the handle's cues, the collapse preview and the toggles.
PROBE = """() => {
  const r = s => {const e = document.querySelector(s); if (!e || !e.getClientRects().length) return null;
    const b = e.getBoundingClientRect(); return {x: b.x, y: b.y, w: b.width, h: b.height, r: b.right, b: b.bottom};};
  const g = document.querySelector('#grip'), cs = getComputedStyle(g), b = document.body.classList;
  return {open: SIDE_OPEN, w: Math.round(document.querySelector('#right').getBoundingClientRect().width),
    gripMin: g.classList.contains('snap-min'), preview: b.contains('side-snap-collapse'), blocked: b.contains('side-snap-blocked'),
    gripCursor: cs.cursor, listOpacity: getComputedStyle(document.querySelector('#list')).opacity,
    grip: r('#grip'), nav: r('#nav-side'), list: r('#list'), bar1: r('#bar1'), bar2: r('#bar2'), right: r('#right'),
    valuenow: g.getAttribute('aria-valuenow'), label: g.getAttribute('aria-label'), prefs: prefs(),
    closing: b.contains('side-closing'), vw: innerWidth, vh: innerHeight};
}"""
# Records every click that reaches the page (a ghost click after a touch shows up here).
CLICKS = """() => {window.__clicks = []; document.addEventListener('click', e => {const t = e.target.closest('[data-act]') || e.target;
  window.__clicks.push((t.id || t.className || t.tagName) + (t.dataset && t.dataset.act ? '[' + t.dataset.act + ']' : ''));}, true);}"""
NO_CLOSE_WATCHER = "delete window.CloseWatcher;"
# The test build's PDF copies are stubs, so PDF.js falls back to PNG and shows the 'PNG 보기' status chip, which a real build never
# shows; hidden where a test measures the status row's absence.
NO_PNG_CHIP = """document.addEventListener('DOMContentLoaded',()=>{const v=document.getElementById('vec-chip'); if(!v)return; v.hidden=true;
  new MutationObserver(()=>{if(!v.hidden)v.hidden=true;}).observe(v,{attributes:true});});"""


def node_or_skip(test, js):
    """Run js under node, or skip the calling test when node is missing."""
    out = run_node(js)
    if out is None:
        test.skipTest("node not available")
    return json.loads(out)


# ---------------------------------------------------------------- pure decisions (node)


class PanelSnapLogic(unittest.TestCase):
    """snapSide(wRaw, bounds, composing): where a panel-handle drag lands. T = floor(min/2)."""

    WIDE = {"min": 280, "max": 954}
    MID = {"min": 300, "max": 440}

    def snap(self, cases):
        """[(wRaw, bounds, composing)] -> [snapSide(...)] from the shipped source."""
        js = extract_js_fn(
            "snapSide"
        ) + "\nconsole.log(JSON.stringify(%s.map(c=>snapSide(c[0],c[1],c[2]))));" % json.dumps(cases)
        return node_or_skip(self, js)

    def test_width_follows_the_pointer_when_at_or_above_the_minimum(self):
        """At or above the minimum the width follows the pointer, up to the maximum."""
        got = self.snap(
            [(500, self.WIDE, False), (280, self.WIDE, False), (1200, self.WIDE, False), (500.4, self.WIDE, True)]
        )
        self.assertEqual(
            got,
            [
                {"w": 500, "zone": "follow"},
                {"w": 280, "zone": "follow"},
                {"w": 954, "zone": "follow"},
                {"w": 500, "zone": "follow"},
            ],
        )

    def test_width_stops_at_the_minimum_between_half_and_minimum(self):
        """Between T (inclusive) and the minimum the width stays at the minimum: the handle turns primary."""
        got = self.snap([(279, self.WIDE, False), (140, self.WIDE, False), (140, self.WIDE, True)])
        self.assertEqual(got, [{"w": 280, "zone": "min"}] * 3)

    def test_release_collapses_when_the_pointer_asks_for_less_than_half_the_minimum(self):
        """Below T a release collapses the panel; the width shown stays at the minimum meanwhile."""
        self.assertEqual(
            self.snap([(139, self.WIDE, False), (-80, self.WIDE, False)]), [{"w": 280, "zone": "collapse"}] * 2
        )

    def test_collapse_zone_is_blocked_while_a_draft_is_open(self):
        """Composing, editing, replying or relocating: the drag stops at the minimum instead of collapsing."""
        self.assertEqual(
            self.snap([(139, self.WIDE, True), (0, self.MID, True)]),
            [{"w": 280, "zone": "blocked"}, {"w": 300, "zone": "blocked"}],
        )

    def test_mid_threshold_is_half_of_its_300px_minimum(self):
        """The unfolded layout's minimum is 300px, so its threshold is 150px."""
        self.assertEqual(
            [s["zone"] for s in self.snap([(150, self.MID, False), (149, self.MID, False)])], ["min", "collapse"]
        )


class GripKeyLogic(unittest.TestCase):
    """gripKey(key, w, bounds, collapsed): the handle's keys as a WAI-ARIA window splitter."""

    B = {"min": 280, "max": 954}

    def keys(self, cases):
        """[(key, w, collapsed)] -> [gripKey(...)] from the shipped source."""
        js = "\n".join(
            [
                extract_js_fn("clampSide"),
                extract_js_fn("gripKey"),
                "const B=%s;console.log(JSON.stringify(%s.map(c=>gripKey(c[0],c[1],B,c[2]))));"
                % (json.dumps(self.B), json.dumps(cases)),
            ]
        )
        return node_or_skip(self, js)

    def test_home_goes_to_the_minimum_and_end_to_the_maximum(self):
        """Home = the panel's smallest size, End = its largest (they were reversed)."""
        self.assertEqual(
            self.keys([("Home", 348, False), ("End", 348, False)]),
            [{"act": "width", "w": 280}, {"act": "width", "w": 954}],
        )

    def test_enter_collapses_and_space_cycles_the_presets(self):
        """Enter collapses an open panel (it used to cycle); Space cycles narrow/normal/wide."""
        self.assertEqual(self.keys([("Enter", 348, False), (" ", 348, False)]), [{"act": "collapse"}, {"act": "cycle"}])

    def test_arrows_step_16px_and_never_collapse(self):
        """Left widens and Right narrows by 16px, clamped to the bounds; collapsing stays Enter's job."""
        self.assertEqual(
            self.keys(
                [
                    ("ArrowLeft", 348, False),
                    ("ArrowRight", 348, False),
                    ("ArrowRight", 284, False),
                    ("ArrowLeft", 950, False),
                    ("x", 348, False),
                ]
            ),
            [
                {"act": "width", "w": 364},
                {"act": "width", "w": 332},
                {"act": "width", "w": 280},
                {"act": "width", "w": 954},
                None,
            ],
        )

    def test_every_key_but_arrow_right_opens_a_collapsed_panel(self):
        """Collapsed: Enter/Space open to the saved width, Home/Left to the minimum, End to the maximum."""
        self.assertEqual(
            self.keys(
                [
                    ("Enter", 0, True),
                    (" ", 0, True),
                    ("Home", 0, True),
                    ("ArrowLeft", 0, True),
                    ("End", 0, True),
                    ("ArrowRight", 0, True),
                ]
            ),
            [
                {"act": "open"},
                {"act": "open"},
                {"act": "width", "w": 280},
                {"act": "width", "w": 280},
                {"act": "width", "w": 954},
                None,
            ],
        )


class GestureLogic(unittest.TestCase):
    """The touch gestures' pure decisions: swipe direction, rubber band, dismissal, sheet release, double-tap, back layer."""

    def run_js(self, names, expr, pre=""):
        """Evaluate expr (JSON) with the named functions from the shipped source."""
        js = "\n".join([pre] + [extract_js_fn(n) for n in names] + ["console.log(JSON.stringify(%s));" % expr])
        return node_or_skip(self, js)

    def test_swipe_axis_waits_10px_then_locks_rightward_horizontal_drags(self):
        """Undecided below 10px; 'x' only for a rightward drag with |dx| > 1.5|dy|; anything else is not a swipe."""
        got = self.run_js(["swipeAxis"], "[[6,4],[12,2],[15,10],[15,9],[-20,0],[3,-30]].map(c=>swipeAxis(c[0],c[1]))")
        self.assertEqual(got, [None, "x", "none", "x", "none", "none"])

    def test_panel_follows_the_finger_but_rubber_bands_while_composing(self):
        """Composing: a quarter of the drag, at most 24px - the panel never closes on a draft."""
        got = self.run_js(
            ["swipeFollow"], "[swipeFollow(120,false),swipeFollow(-5,false),swipeFollow(40,true),swipeFollow(400,true)]"
        )
        self.assertEqual(got, [120, 0, 10, 24])

    def test_dismiss_closes_past_35_percent_or_on_a_fling(self):
        """Past 35% of the size, or more than 24px at 0.5px/ms or faster, closes; otherwise it springs back."""
        got = self.run_js(
            ["dismissOutcome"],
            "[dismissOutcome(116,330,0),dismissOutcome(115,330,0.49),dismissOutcome(25,330,0.5),"
            "dismissOutcome(24,330,3),dismissOutcome(60,330,0.2)]",
        )
        self.assertEqual(got, ["close", "back", "close", "back", "back"])

    def test_sheet_release_collapses_low_or_flung_down_and_steps_up_on_an_upward_fling(self):
        """Below 25% or a downward fling collapses (30% while composing); an upward fling goes to the next stop."""
        pre = re.search(
            r"const SHEET_F=\[[^\]]*\],SHEET_MIN_F=[\d.]+,SHEET_CLOSE_F=[\d.]+(?:,SHEET_COMPOSE_F=[\d.]+)?;", HTML
        ).group(0)
        got = self.run_js(
            ["sheetRelease"],
            "[sheetRelease(0.2,300,0.1,false),sheetRelease(0.2,300,0.1,true),"
            "sheetRelease(0.5,40,0.8,false),sheetRelease(0.5,40,0.8,true),sheetRelease(0.5,-40,-0.8,false),"
            "sheetRelease(0.9,-40,-0.8,false),sheetRelease(0.5,-40,-0.2,false),sheetRelease(0.27,80,0.1,false)]",
            pre,
        )
        self.assertEqual(
            got,
            [{"close": True}, {"f": 0.3}, {"close": True}, {"f": 0.3}, {"f": 0.64}, {"f": 1}, {"f": 0.5}, {"f": 0.3}],
        )

    def test_double_tap_is_two_taps_within_300ms_and_24px_and_toggles_fit_and_2x(self):
        """A second tap near the first zooms: fit width -> 2x, any other width -> fit width."""
        got = self.run_js(
            ["isDoubleTap", "doubleTapWidth"],
            "[isDoubleTap({t:0,x:10,y:10},{t:250,x:20,y:25}),isDoubleTap({t:0,x:10,y:10},{t:350,x:10,y:10}),"
            "isDoubleTap({t:0,x:10,y:10},{t:100,x:40,y:10}),isDoubleTap(null,{t:0,x:0,y:0}),"
            "doubleTapWidth(800,800),doubleTapWidth(830,800),doubleTapWidth(1600,800),doubleTapWidth(500,800)]",
        )
        self.assertEqual(got, [True, False, False, False, 1600, 1600, 800, 800])

    def test_tablet_sheet_lift_rises_only_as_far_as_needed_and_never_past_60_percent(self):
        """sheetLift(f, need): the tablet sheet's height while composing with the keyboard up - its own height when the
        location line, the note and the save row fit, else just what they need, at most 60%; a higher chosen height stays."""
        pre = re.search(r"^const SHEET_TAB_LIFT_MAX=.*;", HTML, re.M).group(0)
        got = self.run_js(
            ["sheetLift"], "[sheetLift(0.45,0.39),sheetLift(0.45,0.52),sheetLift(0.45,0.8),sheetLift(0.64,0.8)]", pre
        )
        self.assertEqual(got, [0.45, 0.52, 0.6, 0.64])

    def test_back_layer_is_the_sheet_the_overlay_panel_or_the_outline_overlay(self):
        """backLayer(band, overlay, sideOpen, outlineOpen, dialogOpen): only a layer that covers the document - a sheet
        (phone, tablet), the overlay panel (mid-overlay, or a short band up to 900px), the outline overlay (mid bands and
        the tablet sheet; with both open the outline is on top), and above them all an open bottom-sheet dialog (the
        navigation sheet, [더보기], help, the Trash; the caller passes it only without CloseWatcher, where a modal dialog
        takes the close request itself). The side panel beside the document and anything wide are not layers."""
        cases = [
            ("phone", False, True, False, False, "side"),
            ("phone", False, False, False, False, None),
            ("phone", False, False, True, False, None),
            ("phone", False, False, False, True, "dialog"),
            ("phone", False, True, False, True, "dialog"),
            ("tablet-sheet", False, True, False, False, "side"),
            ("tablet-sheet", False, False, True, False, "outline"),
            ("tablet-sheet", False, True, True, False, "outline"),
            ("tablet-sheet", False, False, False, False, None),
            ("tablet-sheet", False, False, True, True, "dialog"),
            ("mid-overlay", True, True, False, False, "side"),
            ("mid-overlay", True, False, True, False, "outline"),
            ("short", True, True, False, False, "side"),
            ("short", False, True, False, False, None),
            ("short", False, False, True, False, "outline"),
            ("short", False, False, False, True, "dialog"),
            ("mid-side", False, True, False, False, None),
            ("mid-side", False, False, True, False, "outline"),
            ("mid-side", False, False, False, True, "dialog"),
            ("wide", False, True, True, False, None),
            ("wide", False, False, False, True, None),
        ]
        got = self.run_js(
            ["backLayer"], "%s.map(c=>backLayer(c[0],c[1],c[2],c[3],c[4]))" % json.dumps([c[:5] for c in cases])
        )
        self.assertEqual([c[:5] + (g,) for c, g in zip(cases, got, strict=True)], cases)


class NavLogic(unittest.TestCase):
    """The navigation sheet's pure decisions (docs/handbook/viewer.md §모바일 레이아웃): which page a typed number goes to,
    and what the phone's [본문 3/25 ▾] says."""

    def run_js(self, names, expr, lang="ko"):
        """Evaluate expr (JSON) with the named shipped functions and the viewer's tr/tl in lang."""
        js = "\n".join(
            ["var LANG=%s,I18N_EN=%s;" % (json.dumps(lang), json.dumps(UI_EN, ensure_ascii=False))]
            + [extract_js_fn(n) for n in ["tr", "tl"] + names]
            + ["console.log(JSON.stringify(%s));" % expr]
        )
        return node_or_skip(self, js)

    def test_a_typed_page_is_clamped_to_the_document_and_nothing_is_no_page(self):
        """clampPage(v, n): a number below 1 goes to the first page, past the last to the last; an empty or non-number
        entry is null - nothing happens (goPage did nothing for a page out of range)."""
        got = self.run_js(
            ["clampPage"],
            "[clampPage('3',25),clampPage('0',25),clampPage('99',25),clampPage('',25),clampPage('abc',25),clampPage(' 7 ',25),clampPage('-4',25)]",
        )
        self.assertEqual(got, [3, 1, 25, None, None, 7, 1])

    def test_the_position_button_names_the_document_only_where_it_helps(self):
        """posLabel(doc, page, n, multi, wide, mode): the document's name with several documents on a 400px-or-wider phone,
        else the pages only; '–/–' before the page is known; '변경사항' in the changes view. Its accessible name says where
        it goes."""
        got = self.run_js(
            ["posLabel"],
            "[posLabel('본문',3,25,true,true,'manuscript'),posLabel('본문',3,25,true,false,'manuscript'),"
            "posLabel('본문',3,25,false,true,'manuscript'),posLabel('본문',0,0,true,true,'manuscript'),"
            "posLabel('본문',3,25,true,true,'revisions')]",
        )
        self.assertEqual(
            got,
            [
                {"name": "본문", "pages": "3/25", "label": "이동 · 본문 · 3 / 25쪽"},
                {"name": "", "pages": "3/25", "label": "이동 · 3 / 25쪽"},
                {"name": "", "pages": "3/25", "label": "이동 · 3 / 25쪽"},
                {"name": "본문", "pages": "–/–", "label": "이동 · 본문 · – / –쪽"},
                {"name": "", "pages": "변경사항", "label": "이동 · 변경사항"},
            ],
        )
        en = self.run_js(["posLabel"], "posLabel('본문',3,25,true,true,'manuscript')", lang="en")
        self.assertEqual(en, {"name": "본문", "pages": "3/25", "label": "Go to · 본문 · 3 / 25"})

    def test_zoom_percent_is_the_page_width_over_the_fitted_width(self):
        """zoomPct(W, fit): [더보기]'s zoom figure, rounded - the fitted width is 100%, one step in 120%, two 144%."""
        got = self.run_js(
            ["zoomPct"], "[zoomPct(387,387),zoomPct(464,387),zoomPct(557,387),zoomPct(194,387),zoomPct(400,0)]"
        )
        self.assertEqual(got, [100, 120, 144, 50, 100])


class StatusLogic(unittest.TestCase):
    """The status line's pure decisions (docs/handbook/viewer.md §모바일 레이아웃 상태는 한 줄이다): which items show, in
    which order, with which action, and their long and short text in Korean and English."""

    S0 = {
        "build": None,
        "buildErr": None,
        "offline": False,
        "sync": None,
        "stale": False,
        "png": False,
        "canRebuild": True,
        "unchanged": False,
    }

    def items(self, **s):
        """statusList() of the empty input S0 with s over it."""
        return node_or_skip(
            self,
            "\n".join(
                [extract_js_fn("statusProgress"), extract_js_fn("statusList")]
                + ["console.log(JSON.stringify(statusList(%s)));" % json.dumps(dict(self.S0, **s))]
            ),
        )

    def kinds(self, **s):
        """The kinds of statusList() for s, in order."""
        return [i["kind"] for i in self.items(**s)]

    def test_one_item_per_state_in_priority_order(self):
        """Nothing shows nothing; a stale PDF is [stale]; a running build hides the staleness it is about to clear; a
        failed build comes before the stale PDF, the lost connection before a running build."""
        running = {"state": "running", "phase": "latex", "elapsed_s": 20, "last_s": 67}
        failed = {"state": "fail", "errors": []}
        self.assertEqual(self.kinds(), [])
        self.assertEqual(self.kinds(stale=True), ["stale"])
        self.assertEqual(self.kinds(stale=True, build=running), ["building"])
        self.assertEqual(self.kinds(stale=True, buildErr=failed), ["failed", "stale"])
        self.assertEqual(self.kinds(offline=True, build=running), ["offline", "building"])
        self.assertEqual(
            self.kinds(png=True, sync={"state": "checking"}, stale=True),
            ["stale", "sync", "png"],
        )
        self.assertEqual(
            self.kinds(sync={"state": "blocked", "reason": "dirty"}, stale=True), ["sync-blocked", "stale"]
        )
        self.assertEqual(self.kinds(buildErr={"state": "ok_errors", "errors": [{}, {}]}), ["errors"])
        self.assertEqual(self.kinds(sync={"state": "current"}), [])

    def test_the_page_render_counts_pages_only_with_a_well_formed_progress(self):
        """The render phase is 'rendering'; its progress is used only when done and total are integers, total > 0 and
        0 <= done <= total - anything else is as if there were none (an indeterminate bar)."""
        render = {"state": "running", "phase": "render", "elapsed_s": 30, "last_s": 67}
        got = self.items(build=dict(render, progress={"done": 12, "total": 25}))
        self.assertEqual((got[0]["kind"], got[0]["progress"]), ("rendering", {"done": 12, "total": 25}))
        for bad in (
            {"done": 30, "total": 25},
            {"done": -1, "total": 25},
            {"done": 0, "total": 0},
            {"done": "3", "total": 5},
            "12/25",
        ):
            with self.subTest(progress=bad):
                got = self.items(build=dict(render, progress=bad))
                self.assertEqual((got[0]["kind"], got[0]["progress"]), ("rendering", None))

    def test_a_rebuild_that_changed_nothing_says_so_with_build_anyway(self):
        """After this tab's rebuild ended unchanged (0.4.5: ok, unchanged, the same seq), the line says so with [그래도 빌드]
        (rebuild-force, a cold build). Meanwhile it does not also call the PDF stale - the rebuild just found nothing new -
        and it never shows while a build runs, which is the answer to that action; without rebuild rights, no action."""
        running = {"state": "running", "phase": "copy", "elapsed_s": 0, "last_s": 8}
        self.assertEqual(self.kinds(unchanged=True), ["unchanged"])
        self.assertEqual(self.items(unchanged=True)[0]["act"], "rebuild-force")
        self.assertIsNone(self.items(unchanged=True, canRebuild=False)[0]["act"])
        self.assertEqual(self.kinds(unchanged=True, stale=True), ["unchanged"])
        self.assertEqual(self.kinds(unchanged=True, png=True), ["unchanged", "png"])
        self.assertEqual(self.kinds(unchanged=True, build=running), ["building"])

    def test_only_a_rebuildable_document_offers_rebuild(self):
        """The stale item's [재빌드] is there for a LaTeX document and a person who may rebuild; a figure document or the
        viewer role sees the line without the action. A failed build's action reopens the error; blocked sync's says why."""
        self.assertEqual(self.items(stale=True)[0]["act"], "rebuild")
        self.assertIsNone(self.items(stale=True, canRebuild=False)[0]["act"])
        self.assertEqual(self.items(buildErr={"state": "fail"})[0]["act"], "build-err-reopen")
        self.assertEqual(self.items(sync={"state": "error", "reason": "x"})[0]["act"], "status-why")
        self.assertIsNone(self.items(offline=True)[0]["act"])

    def test_long_and_short_texts_in_korean_and_english(self):
        """statusText(item, fit) is [label, tail]: the label is what a screen reader hears, the tail the ticking numbers.
        LaTeX errors take the plural forms in English."""
        cases = {
            "stale": {"kind": "stale"},
            "build": {"kind": "building", "phase": "latex", "el": 20, "last": 67},
            "render": {"kind": "rendering", "progress": {"done": 12, "total": 25}, "el": 30, "last": 67},
            "err1": {"kind": "errors", "n": 1},
            "err2": {"kind": "errors", "n": 2},
            "off": {"kind": "offline"},
            "same": {"kind": "unchanged"},
        }
        out = {}
        for lang in ("ko", "en"):
            js = "\n".join(
                [
                    "var LANG=%s,I18N_EN=%s;" % (json.dumps(lang), json.dumps(UI_EN, ensure_ascii=False)),
                    extract_js_fn("tr"),
                    extract_js_fn("tl"),
                    extract_js_fn("statusSplit"),
                    extract_js_fn("statusText"),
                    "const C=%s; const o={}; for(const k in C)o[k]=[statusText(C[k],'long'),statusText(C[k],'short')];"
                    " console.log(JSON.stringify(o));" % json.dumps(cases),
                ]
            )
            out[lang] = node_or_skip(self, js)
        self.assertEqual(out["ko"]["stale"], [["원고가 PDF보다 새롭습니다", ""], ["원고 수정됨", ""]])
        self.assertEqual(
            out["ko"]["build"], [["LaTeX 컴파일 중", " · 20초 (지난번 67초)"], ["LaTeX 컴파일 중", " 20초"]]
        )
        self.assertEqual(out["ko"]["render"], [["쪽 그리는 중", " · 12/25쪽"], ["쪽", " 12/25"]])
        self.assertEqual(out["ko"]["err1"], [["LaTeX 오류 1건 · 새 PDF", ""], ["LaTeX 오류 1", ""]])
        self.assertEqual(out["ko"]["off"], [["연결 끊김 · 다시 잇는 중", ""], ["연결 끊김", ""]])
        self.assertEqual(out["en"]["stale"], [["The manuscript is newer than the PDF", ""], ["Manuscript edited", ""]])
        self.assertEqual(out["en"]["err1"], [["1 LaTeX error · new PDF", ""], ["1 LaTeX error", ""]])
        self.assertEqual(out["en"]["err2"], [["2 LaTeX errors · new PDF", ""], ["2 LaTeX errors", ""]])
        self.assertEqual(out["en"]["render"], [["Rendering pages", " · 12/25"], ["Pages", " 12/25"]])
        self.assertEqual(out["ko"]["same"], [["변경 없음", ""], ["변경 없음", ""]])  # 0.4.5's words
        self.assertEqual(out["en"]["same"], [["No changes", ""], ["No changes", ""]])
        self.assertFalse(any(HANGUL.search(a + b) for pair in out["en"].values() for a, b in pair))


class MarkBadgeLogic(unittest.TestCase):
    """Where a mark's number badge goes (docs/handbook/viewer.md §모바일 레이아웃, UX audit R4): outside the mark's left
    edge, unless the room left of the mark - the page's left margin plus the mark's offset in the page - is smaller than
    the badge's reach (28px on touch, 24px with a mouse), where it would be clipped."""

    def test_the_badge_goes_inside_only_when_the_margin_and_the_offset_leave_no_room(self):
        """Touch, 12px margin: a mark at 0 or 15.9px in has no room (inside); 16px in has (outside). The manuscript's text
        at 6.4% of a 387px (411) or 336px (360) page keeps its badge outside - it went inside and covered the text when
        the margin was not counted. A mouse's 44px desktop margin never moves a badge inside, even at the page edge."""
        js = "\n".join(
            [
                extract_js_fn("markBadgeIn"),
                "console.log(JSON.stringify([markBadgeIn(0,387,12,28),markBadgeIn(15.9/336,336,12,28),markBadgeIn(16/336,336,12,28),"
                "markBadgeIn(0.064,387,12,28),markBadgeIn(0.064,336,12,28),markBadgeIn(0,780,44,24),markBadgeIn(0,780,23,24)]));",
            ]
        )
        self.assertEqual(node_or_skip(self, js), [True, True, False, False, False, False, True])


class DraftLogic(unittest.TestCase):
    """draftKey()/draftRestore(): where a composer draft is kept per tab (sessionStorage) and what a reload brings back."""

    def run_js(self, expr):
        """Evaluate expr (JSON) with draftKey and draftRestore from the shipped source."""
        js = "\n".join(
            [extract_js_fn("draftKey"), extract_js_fn("draftRestore"), "console.log(JSON.stringify(%s));" % expr]
        )
        return node_or_skip(self, js)

    def test_key_is_per_instance_label_and_document(self):
        """Two instances (labels) and two documents never share a draft."""
        self.assertEqual(
            self.run_js("[draftKey('A-DEMO','ms'),draftKey('A:B','hl'),draftKey('','ms')]"),
            ["limnDraft:A-DEMO:ms", "limnDraft:A%3AB:hl", "limnDraft::ms"],
        )

    def test_restore_is_full_on_the_same_build_note_only_on_another_and_nothing_for_another_doc(self):
        """The box's coordinates only mean something on the build it was drawn on; a note is worth keeping anyway."""
        rec = "{v:1,doc:'ms',build:'p1',cur:{lo:3},note:'메모'}"
        got = self.run_js(
            "[draftRestore(%s,'ms','p1'),draftRestore(%s,'ms','p2'),draftRestore(%s,'hl','p1'),"
            "draftRestore({v:1,doc:'ms',build:'p1',cur:null,note:'메모'},'ms','p1'),"
            "draftRestore({v:1,doc:'ms',build:'p2',cur:{lo:3},note:'  '},'ms','p1'),"
            "draftRestore(null,'ms','p1'),draftRestore({v:2,doc:'ms',build:'p1',cur:{},note:'x'},'ms','p1')]"
            % (rec, rec, rec)
        )
        self.assertEqual(got, ["full", "note", None, "note", None, None, None])


# ---------------------------------------------------------------- browser harness


class ViewerBase(BrowserBase):
    """BrowserBase with device presets, saved preferences, reduced motion and touch helpers. Three open pins with marks on
    page 1 and one pin awaiting review, so the list, the marks and the review pill are all there."""

    def setUp(self):
        """Place multiple page-one pins and a page-two review pin for spatial selection and input interactions."""
        super().setUp()
        for lo, y in ((4, 0.2), (8, 0.35), (12, 0.5)):
            add_pin(
                {
                    "file": str(self.main),
                    "lo": lo,
                    "hi": lo + 1,
                    "page": 1,
                    "note": "메모 %d" % lo,
                    "frac": [0.15, y, 0.5, 0.04],
                },
                actor(ALICE),
            )
        rid = add_pin(
            {"file": str(self.main), "lo": 20, "hi": 21, "page": 2, "note": "검토할 핀", "frac": [0.2, 0.3, 0.4, 0.04]},
            actor(ALICE),
        ).record["id"]  # add_pin returns the new OpenPin (limn.pins.editing.rules)
        ps.APP.pin_lifecycle.close_pin(
            rid,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", rid),
            CloseRequest(reply="고침"),
        )

    def view(self, device, lang="ko", prefs=None, reduced=False, init=None, dark=False, hash_=""):
        """Open the viewer on a device preset and return the page once boot() has finished and the page has settled.
        prefs = pinPrefs before boot (coach marks are pre-seen unless given)."""
        p = {"coach": {"touch": 1, "mouse": 1, "sel": 1}}
        p.update(prefs or {})
        if dark:
            p["theme"] = "dark"
        context = self.browser.new_context(**device, reduced_motion="reduce" if reduced else "no-preference")
        self.addCleanup(context.close)
        context.add_init_script(
            "try{if(!sessionStorage.getItem('__t')){sessionStorage.setItem('__t','1');"
            "localStorage.setItem('pinPrefs',%s);}}catch(e){}" % json.dumps(json.dumps(p))
        )
        if init:
            context.add_init_script(init)
        watch_idle(context)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/*", self.route)
        page.goto("http://viewer.test/?lang=%s%s" % (lang, hash_))
        page.wait_for_function(BOOTED, timeout=20000)
        settle(page)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page

    @staticmethod
    def cdp(page):
        """A CDP session for touch input."""
        return page.context.new_cdp_session(page)

    @staticmethod
    def touch(cdp, kind, pts):
        """One CDP touch event (touchStart/touchMove/touchEnd) at the given points."""
        cdp.send(
            "Input.dispatchTouchEvent",
            {"type": kind, "touchPoints": [{"x": x, "y": y, "id": i} for i, (x, y) in enumerate(pts)]},
        )

    def swipe(self, cdp, x0, y0, x1, y1, steps=12, dt=0.016, hold=0.0):
        """A one-finger drag from (x0,y0) to (x1,y1) in steps, dt seconds apart (hold = still time before moving).

        The sleeps are the finger's timing, not waits for the page: dt sets the drag's speed and hold a still press, and
        only their lower bound matters - a loaded machine stretches them, the way a slower finger would."""
        self.touch(cdp, "touchStart", [(x0, y0)])
        if hold:
            time.sleep(hold)
        for i in range(1, steps + 1):
            self.touch(cdp, "touchMove", [(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps)])
            time.sleep(dt)
        self.touch(cdp, "touchEnd", [])

    def tap(self, cdp, x, y, hold=0.05):
        """A short tap (hold = how long the finger stays down - the finger's timing, as in swipe(), not a wait)."""
        self.touch(cdp, "touchStart", [(x, y)])
        time.sleep(hold)
        self.touch(cdp, "touchEnd", [])

    @staticmethod
    def before_next_tap(page):
        """The finger's pause before tapping the same spot again: 500ms, past the browser's double-tap window and the
        viewer's 400ms swallow window (SWALLOW_CLICK), so the next tap is a new single tap, as a person's would be. Like
        swipe()'s dt this is input timing, not a wait for the page: only its lower bound matters (each CDP touch event
        returns once the page has handled it, so the pause starts after the previous tap landed)."""
        page.wait_for_timeout(500)

    @staticmethod
    def center(page, sel):
        """The center of an element's box."""
        b = page.locator(sel).first.bounding_box()
        return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2

    @staticmethod
    def on_page(page, fx, fy, n=1):
        """A point on page n at fractions (fx, fy) of its box - the test pins' marks sit at y 0.2/0.35/0.5, x 0.15-0.65."""
        b = page.locator("#p%d" % n).bounding_box()
        return b["x"] + b["width"] * fx, b["y"] + b["height"] * fy

    def long_press_pick(self, cdp, page, x=None, y=None):
        """A long-press quick selection at (x, y) (default: a clear spot near the top of page 1); waits for the composer.

        The finger stays down until the long-press timer has picked (LP_PICKED is its pointer), as a person holds until
        the selection appears. A fixed 0.6s hold raced the 450ms timer on a loaded machine: the lift could reach the page
        before the late timer ran and cancel the press."""
        if x is None:
            x, y = self.on_page(page, 0.3, 0.1)
        self.touch(cdp, "touchStart", [(x, y)])
        page.wait_for_function("LP===null&&LP_PICKED!==null", timeout=8000)
        self.touch(cdp, "touchEnd", [])
        page.wait_for_function(
            "COMPOSE.current&&COMPOSE.current.lo&&!document.querySelector('#composer').hidden", timeout=8000
        )
        settle(page)

    def mouse_pick(self, page):
        """A mouse drag on page 1 (clear of the marks) through the real pick path; the in-process server answers /api/pick."""
        page.evaluate("document.querySelector('#left').scrollTop=0")
        x0, y0 = self.on_page(page, 0.3, 0.07)
        x1, y1 = self.on_page(page, 0.7, 0.12)
        page.mouse.move(x0, y0)
        page.mouse.down()
        page.mouse.move(x1, y1, steps=5)
        page.mouse.up()
        page.wait_for_function(
            "COMPOSE.current&&COMPOSE.current.lo&&!document.querySelector('#composer').hidden", timeout=8000
        )
        settle(page)


# ---------------------------------------------------------------- A. collapsing the panel with a mouse (wide)


class DesktopPanelCollapse(ViewerBase):
    """Wide (1100px and up): the panel collapses by dragging its handle past half its minimum and comes back from the rail,
    the nav bar's [핀 N], Ctrl+\\, the handle's keys, or anything that needs the panel (a pick, a mark, a link)."""

    def drag_grip(self, page, dx_list, release=True):
        """Mouse-drag the handle right by each dx in turn (from its start), probing after each step."""
        g = page.locator("#grip").bounding_box()
        gx, gy = g["x"] + g["width"] / 2, min(300, g["height"] / 2)
        page.mouse.move(gx, gy)
        page.mouse.down()
        out = []
        for dx in dx_list:
            page.mouse.move(gx + dx, gy, steps=3)
            out.append(page.evaluate(PROBE))
        if release:
            page.mouse.up()
        return out

    def collapse(self, page):
        """Collapse by a drag and wait for the slide to finish."""
        self.drag_grip(page, [page.evaluate(PROBE)["w"]])
        page.wait_for_function("!SIDE_OPEN&&!document.body.classList.contains('side-closing')")

    def test_drag_below_half_the_minimum_collapses_and_the_rail_reopens_to_the_saved_width(self):
        """The three zones while dragging, the collapsed wide layout, and a double-click on the rail."""
        for dev in (DESK, LAP):
            with self.subTest(width=dev["viewport"]["width"]):
                page = self.view(dev, prefs={"side": 400})
                # wRaw 200 (min zone), 100 (collapse preview), 200 (back above T), 100 again and release
                mid, pre, back, _ = self.drag_grip(page, [200, 300, 200, 300])
                self.assertEqual((mid["w"], mid["gripMin"], mid["preview"]), (280, True, False))
                self.assertEqual(
                    (pre["w"], pre["preview"], pre["listOpacity"], pre["gripCursor"]), (280, True, "0.4", "w-resize")
                )
                self.assertFalse(back["preview"])  # back above T restores at once
                page.wait_for_function("!SIDE_OPEN&&!document.body.classList.contains('side-closing')")
                s = page.evaluate(PROBE)
                self.assertIsNone(s["list"])
                self.assertIsNone(s["bar1"])  # the tools hide with the panel
                self.assertAlmostEqual(s["grip"]["r"], s["vw"], delta=1)  # the rail sits at the right edge
                self.assertEqual(s["grip"]["w"], 6)
                self.assertIsNotNone(s["nav"])
                # saved width untouched
                self.assertEqual((s["prefs"].get("sideClosed"), s["prefs"].get("side")), (True, 400))
                self.assertEqual((s["valuenow"], s["label"]), ("0", "패널 폭 · 접힘"))
                nav = page.locator("#nav-side")
                self.assertEqual(nav.get_attribute("aria-expanded"), "false")
                self.assertEqual(nav.locator(".side-n").inner_text(), "3")
                self.assertTrue(nav.locator(".rv-n").is_visible())  # the purple review pill
                self.assertGreater(s["nav"]["x"], s["vw"] - 200)  # right end of the nav bar
                self.assertLess(s["nav"]["y"], 50)
                page.mouse.dblclick(s["grip"]["x"] + 3, 400)
                page.wait_for_function("SIDE_OPEN")
                s = page.evaluate(PROBE)
                self.assertEqual((s["w"], s["prefs"].get("sideClosed")), (400, False))
                self.assertIsNone(s["nav"])

    def test_rail_drag_opens_at_the_minimum_once_past_half_and_then_follows(self):
        """From the rail: below T nothing opens, from T the panel shows at its minimum, above it the width follows."""
        page = self.view(DESK, prefs={"sideClosed": True, "side": 420})
        self.assertFalse(page.evaluate("SIDE_OPEN"))
        g = page.locator("#grip").bounding_box()
        gx = g["x"] + 3
        page.mouse.move(gx, 400)
        page.mouse.down()
        page.mouse.move(gx - 100, 400, steps=3)
        self.assertIsNone(page.evaluate(PROBE)["list"])
        page.mouse.move(gx - 200, 400, steps=3)
        s = page.evaluate(PROBE)
        self.assertEqual((s["w"], s["gripMin"]), (280, True))
        self.assertIsNotNone(s["list"])
        page.mouse.move(gx - 360, 400, steps=3)
        page.mouse.up()
        page.wait_for_function("SIDE_OPEN")
        s = page.evaluate(PROBE)
        self.assertAlmostEqual(s["w"], 360, delta=2)
        self.assertEqual(s["prefs"].get("sideClosed"), False)
        self.assertAlmostEqual(s["prefs"].get("side"), 360, delta=2)

    def test_a_draft_stops_the_drag_at_the_minimum_without_collapsing(self):
        """Composing: past T the cursor says not-allowed, the release keeps the panel open at its minimum, no toast."""
        page = self.view(DESK)
        self.mouse_pick(page)
        (s,) = self.drag_grip(page, [300], release=False)
        self.assertEqual((s["blocked"], s["preview"], s["gripCursor"], s["w"]), (True, False, "not-allowed", 280))
        page.mouse.up()
        settle(page)
        s = page.evaluate(PROBE)
        self.assertEqual((s["open"], s["w"]), (True, 280))
        self.assertEqual(page.locator("#toasts .toast").count(), 0)

    def test_pointercancel_restores_the_width_and_state_from_before_the_drag(self):
        """A cancelled drag (the browser took the pointer) leaves the panel as it was."""
        page = self.view(DESK, prefs={"side": 380})
        page.evaluate("document.querySelector('#grip').addEventListener('pointerdown',e=>{window.__pid=e.pointerId;})")
        self.drag_grip(page, [300], release=False)
        page.evaluate(
            "document.querySelector('#grip').dispatchEvent(new PointerEvent('pointercancel',{pointerId:window.__pid,bubbles:true}))"
        )
        page.mouse.up()
        settle(page)
        s = page.evaluate(PROBE)
        self.assertEqual((s["open"], s["w"], s["preview"]), (True, 380, False))

    def test_handle_keys_follow_the_window_splitter_pattern(self):
        """Home = minimum, End = maximum, Enter collapses and reopens to the saved width, Space cycles the presets."""
        page = self.view(DESK, prefs={"side": 400})
        grip = page.locator("#grip")
        grip.focus()
        page.keyboard.press("Home")
        self.assertEqual(page.evaluate(PROBE)["w"], 280)
        page.keyboard.press("End")
        self.assertEqual(page.evaluate(PROBE)["w"], 914)  # min(80%, 1400 - 486)
        page.keyboard.press("ArrowRight")
        self.assertEqual(page.evaluate(PROBE)["w"], 898)
        page.keyboard.press("Enter")
        page.wait_for_function("!SIDE_OPEN&&!document.body.classList.contains('side-closing')")
        s = page.evaluate(PROBE)
        self.assertEqual((s["valuenow"], s["label"], s["prefs"].get("side")), ("0", "패널 폭 · 접힘", 898))
        self.assertEqual(page.evaluate("document.activeElement.id"), "grip")  # the rail stays in the tab order
        page.keyboard.press("Enter")
        page.wait_for_function("SIDE_OPEN")
        self.assertEqual(page.evaluate(PROBE)["w"], 898)
        page.keyboard.press(" ")
        self.assertEqual(page.evaluate(PROBE)["w"], 300)  # the next preset wraps to the narrowest

    def test_ctrl_backslash_toggles_the_panel_and_moves_focus_to_the_pin_toggle(self):
        """Ctrl+\\ outside text fields; a focus inside the collapsing panel lands on [핀 N]."""
        page = self.view(DESK)
        page.locator("#btn-reload").focus()
        page.keyboard.press("Control+Backslash")
        page.wait_for_function("!SIDE_OPEN")
        self.assertEqual(page.evaluate("document.activeElement.id"), "nav-side")
        page.keyboard.press("Control+Backslash")
        page.wait_for_function("SIDE_OPEN")
        self.mouse_pick(page)
        page.locator("#note").focus()
        page.keyboard.press("Control+Backslash")
        settle(page)
        self.assertTrue(page.evaluate("SIDE_OPEN"))  # ignored inside a text field

    def test_ctrl_backslash_works_at_every_width(self):
        """The same shortcut toggles the unfolded panel and the phone sheet."""
        for dev in (FOLD, PHONE):
            with self.subTest(width=dev["viewport"]["width"]):
                page = self.view(dev)
                was = page.evaluate("SIDE_OPEN")
                page.keyboard.press("Control+Backslash")
                page.wait_for_function("SIDE_OPEN===%s" % ("false" if was else "true"))

    def test_collapsed_panel_floats_status_chips_and_toasts_at_the_pdf_bottom_right(self):
        """Collapsed wide: #bar2's chips become a floating card at the PDF area's bottom-right, toasts sit above it."""
        page = self.view(DESK, prefs={"sideClosed": True})
        page.evaluate("updateStaleBadge({stale_build:true,src_age_s:120})")
        s = page.evaluate(PROBE)
        self.assertIsNotNone(s["bar2"])
        self.assertLessEqual(s["bar2"]["r"], s["grip"]["x"])
        self.assertGreater(s["bar2"]["b"], s["vh"] - 40)
        self.assertFalse(page.locator("#meta-txt").is_visible())
        page.evaluate("toast('핀 #1 저장됨 · pins.md 갱신','ok')")
        t = page.locator("#toasts .toast").bounding_box()
        left = page.evaluate(
            "(()=>{const L=document.querySelector('#left'),r=L.getBoundingClientRect();return r.left+L.clientLeft+L.clientWidth;})()"
        )
        self.assertLessEqual(t["x"] + t["width"], left)
        self.assertLessEqual(t["y"] + t["height"], s["bar2"]["y"])
        self.assertFalse(page.locator("#rv-chip").is_visible())  # the review count rides on [핀 N]

    def test_whatever_needs_the_panel_opens_a_collapsed_one_without_remembering(self):
        """A new pick, a mark badge, a pin link, the review list and an in-text #N all open it; the saved choice stays."""
        page = self.view(DESK, prefs={"sideClosed": True})
        steps = [
            ("pick", lambda: self.mouse_pick(page)),
            ("mark", lambda: page.locator(".mark b").first.click()),
            ("link", lambda: page.evaluate("openPinFromLink(DOC,1)")),
            ("review", lambda: page.evaluate("gotoReview()")),
            ("ref", lambda: page.evaluate("gotoPinRef(2)")),
        ]
        for name, act in steps:
            with self.subTest(trigger=name):
                page.evaluate("cancelSelection(true); setSide(false)")
                page.wait_for_function("!SIDE_OPEN&&!document.body.classList.contains('side-closing')")
                act()
                page.wait_for_function("SIDE_OPEN")
                self.assertTrue(page.evaluate("prefs().sideClosed"))

    def test_boot_with_a_pin_link_opens_a_collapsed_panel(self):
        """A #pin= link (a notification clicked with no tab open) shows its card even if the panel was collapsed."""
        page = self.view(DESK, prefs={"sideClosed": True}, hash_="#pin=2")
        page.wait_for_function("SIDE_OPEN")

    def test_first_drag_collapse_explains_how_to_reopen_once(self):
        """One coach mark, the first time only: [핀 N] (top right) or Ctrl+\\."""
        for lang, needle in (("ko", "Ctrl+\\"), ("en", "Ctrl+\\")):
            with self.subTest(lang=lang):
                page = self.view(DESK, lang=lang)
                self.collapse(page)
                text = page.locator("#coach-t").inner_text()
                self.assertIn(needle, text)
                self.assertEqual(bool(HANGUL.search(text)), lang == "ko")
                page.evaluate("document.querySelector('#coach').hidden=true; setSide(true,true)")
                self.collapse(page)
                self.assertTrue(page.locator("#coach").is_hidden())

    def test_tooltip_hides_as_soon_as_the_handle_is_pressed(self):
        """The handle's description no longer stays over the PDF while dragging."""
        page = self.view(DESK)
        g = page.locator("#grip").bounding_box()
        page.mouse.move(g["x"] + 3, 400)
        page.wait_for_function("!document.querySelector('#tip').hidden")
        page.mouse.down()
        self.assertTrue(page.evaluate("document.querySelector('#tip').hidden"))
        page.mouse.up()

    def test_reduced_motion_keeps_the_threshold_and_preview_but_not_the_slide(self):
        """prefers-reduced-motion: the same zones and the 40% preview, then an instant collapse."""
        page = self.view(DESK, reduced=True)
        (s,) = self.drag_grip(page, [300], release=False)
        self.assertEqual((s["preview"], s["listOpacity"]), (True, "0.4"))
        page.mouse.up()
        s = page.evaluate(PROBE)
        self.assertEqual((s["open"], s["closing"]), (False, False))

    def test_nav_toggle_carries_count_review_pill_and_a_draft_dot(self):
        """Collapsed while composing: [핀 N] shows a dot and says so to screen readers, in both languages and themes."""
        for lang, dark in (("ko", False), ("en", True)):
            with self.subTest(lang=lang, dark=dark):
                page = self.view(DESK, lang=lang, dark=dark)
                self.mouse_pick(page)
                page.evaluate("setSide(false,true)")
                page.wait_for_function("!SIDE_OPEN")
                nav = page.locator("#nav-side")
                self.assertTrue(nav.locator(".c-dot").is_visible())
                label = nav.get_attribute("aria-label")
                self.assertIn("작성 중" if lang == "ko" else "draft", label)
                self.assertEqual(
                    bool(HANGUL.search(label + page.locator("#grip").get_attribute("aria-label"))), lang == "ko"
                )


class ReviewRegressions(ViewerBase):
    """Findings of the code review of this change (fail before their fix): interrupted slides, a second finger mid-gesture,
    the back layer's history entry surviving a hash rewrite, and focus when reopening from the nav bar."""

    def test_a_handle_press_mid_slide_settles_the_collapsed_panel(self):
        """Ctrl+\\ starts the 0.18s slide; a click on the handle during it used to leave side-open on a collapsed panel."""
        page = self.view(DESK)
        page.evaluate("""() => {const g = document.querySelector('#grip'), r = g.getBoundingClientRect(),
          o = {pointerId: 7, pointerType: 'mouse', button: 0, bubbles: true, clientX: r.left + 3, clientY: 300};
          toggleSide(); g.dispatchEvent(new PointerEvent('pointerdown', o)); g.dispatchEvent(new PointerEvent('pointerup', o));}""")
        settle(page)
        self.assertEqual(page.evaluate("[SIDE_OPEN, document.body.classList.contains('side-open')]"), [False, False])
        self.assertTrue(page.locator("#nav-side").is_visible())

    def test_reopening_right_after_a_drag_collapse_shows_the_saved_width(self):
        """A drag-collapse leaves the panel at the minimum while it slides out; reopening within the slide used to keep it."""
        page = self.view(DESK, prefs={"side": 400})
        g = page.locator("#grip").bounding_box()
        page.mouse.move(g["x"] + 3, 300)
        page.mouse.down()
        page.mouse.move(g["x"] + 350, 300, steps=4)
        page.mouse.up()
        page.keyboard.press("Control+Backslash")
        page.wait_for_function("SIDE_OPEN&&!document.body.classList.contains('side-opening')")
        self.assertEqual(page.evaluate(PROBE)["w"], 400)

    def test_opening_from_the_nav_toggle_moves_focus_to_the_handle(self):
        """[핀 N] in the nav bar hides as the panel opens; the keyboard focus used to fall to <body>."""
        page = self.view(DESK, prefs={"sideClosed": True})
        page.locator("#nav-side").focus()
        page.keyboard.press("Enter")
        page.wait_for_function("SIDE_OPEN")
        self.assertEqual(page.evaluate("document.activeElement.id"), "grip")

    def test_a_hash_rewrite_keeps_the_back_layers_history_entry(self):
        """setHash() used replaceState(null): after a document switch the pushed entry was no longer recognized as ours."""
        page = self.view(PHONE, init=NO_CLOSE_WATCHER)
        cdp = self.cdp(page)
        self.tap(cdp, *self.center(page, "#btn-side"))
        page.wait_for_function("SIDE_OPEN&&BACK&&BACK.kind==='history'")
        page.evaluate("DOCS=[{key:'main',name:'A',path:'a.tex'},{key:'other',name:'B',path:'b.tex'}]; setHash('other')")
        self.assertTrue(page.evaluate("!!(history.state&&history.state.limnLayer)"))

    def test_a_second_finger_ends_a_pull_down_and_an_overlay_swipe_cleanly(self):
        """A second finger mid-gesture used to leave body.resizing on (a dead PDF) or the overlay offset by --swipe-x."""
        page = self.view(PHONE)
        cdp = self.cdp(page)
        self.tap(cdp, *self.center(page, "#btn-side"))
        page.wait_for_function("SIDE_OPEN")
        settle(page)
        y = page.locator("#list").bounding_box()["y"] + 40
        self.touch(cdp, "touchStart", [(190, y)])
        for i in range(1, 6):
            self.touch(cdp, "touchMove", [(190, y + 20 * i)])
            time.sleep(0.02)  # the finger's timing, as in swipe()
        self.touch(cdp, "touchStart", [(190, y + 100), (300, y + 60)])
        self.touch(cdp, "touchEnd", [])
        settle(page)
        self.assertFalse(page.evaluate("document.body.classList.contains('resizing')"))
        page = self.view(FOLD)
        cdp = self.cdp(page)
        self.tap(cdp, *self.center(page, "#btn-side"))
        page.wait_for_function("SIDE_OPEN&&MID_OVERLAY")
        settle(page)
        r = page.locator("#right").bounding_box()
        x, y = r["x"] + 40, r["y"] + 150
        self.touch(cdp, "touchStart", [(x, y)])
        for i in range(1, 8):
            self.touch(cdp, "touchMove", [(x + 12 * i, y)])
            time.sleep(0.02)  # the finger's timing, as in swipe()
        self.touch(cdp, "touchStart", [(x + 84, y), (x + 20, y + 200)])
        self.touch(cdp, "touchEnd", [])
        settle(page)
        self.assertEqual(
            page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--swipe-x').trim()||'0px'"),
            "0px",
        )
        if page.evaluate("SIDE_OPEN"):
            self.assertEqual(
                page.evaluate("Math.round(document.querySelector('#right').getBoundingClientRect().right)"), 842
            )


DRAFT_KEYS = "Object.keys(sessionStorage).filter(k=>k.startsWith('limnDraft:'))"
# The debounced draft save has run and stored a draft whose note is the argument (no save left pending).
DRAFT_SAVED = "n=>DRAFT.timer===0&&%s.some(k=>JSON.parse(sessionStorage.getItem(k)).note===n)" % DRAFT_KEYS


class DraftPersistence(ViewerBase):
    """A composer draft survives leaving the tab's page (reload, history back, the second back gesture): it is kept in
    sessionStorage per instance and document on every edit and restored with '작성 중이던 메모를 되살렸습니다 · [버리기]'.
    Saving clears it; discarding clears it once the undo window is over (coordinator decision 2026-09-26)."""

    def reload(self, page):
        """Reload and wait for the viewer to boot again (its draft restored) and settle."""
        page.reload()
        page.wait_for_function(BOOTED, timeout=20000)
        settle(page)

    def draft(self, page, note, question=False):
        """Pick with the mouse, write a note (and switch to a question), then wait for the debounced save to store it."""
        self.mouse_pick(page)
        page.locator("#note").fill(note)
        if question:
            page.locator('#c-kind [data-kind="question"]').click()
        page.wait_for_function(DRAFT_SAVED, arg=note)
        return page.evaluate("COMPOSE.current.lo")

    def restored(self, page):
        """[composer shown, COMPOSE.current.lo, note, kind, pending box, the restore toast's text]."""
        return page.evaluate("""() => [!document.querySelector('#composer').hidden, COMPOSE.current&&COMPOSE.current.lo, document.querySelector('#note').value,
          KIND_NEW, !!document.querySelector('.sel.pending'),
          [...document.querySelectorAll('#toasts .toast .t-title')].map(t=>t.textContent).join('|')]""")

    def test_a_reload_restores_the_selection_note_kind_and_box_with_a_discard_toast(self):
        """Korean and English: everything comes back, and the toast offers [버리기] / [Discard]."""
        for lang, title, button in (("ko", "작성 중이던 메모를 되살렸습니다", "버리기"), ("en", None, None)):
            with self.subTest(lang=lang):
                page = self.view(DESK, lang=lang)
                lo = self.draft(page, "다시 올 메모", question=True)
                self.reload(page)
                got = self.restored(page)
                self.assertEqual(got[:5], [True, lo, "다시 올 메모", "question", True])
                if lang == "ko":
                    self.assertIn(title, got[5])
                    self.assertTrue(page.locator("#toasts .toast button", has_text=button).is_visible())
                else:
                    self.assertTrue(got[5])
                    self.assertFalse(HANGUL.search(got[5]), got[5])

    def test_leaving_by_the_second_back_and_coming_back_restores_the_draft(self):
        """Phone, history fallback: the first back closes the sheet, the second leaves Limn; forward brings the draft back."""
        page = self.view(PHONE, init=NO_CLOSE_WATCHER)
        cdp = self.cdp(page)
        self.long_press_pick(cdp, page)
        lo = page.evaluate("COMPOSE.current.lo")
        page.locator("#note").fill("폰에서 쓰던 메모")
        page.wait_for_function(DRAFT_SAVED, arg="폰에서 쓰던 메모")
        page.go_back()
        page.wait_for_function("!SIDE_OPEN")
        page.go_back()
        page.wait_for_url(lambda url: "viewer.test" not in url)
        self.assertNotIn("viewer.test", page.url)
        page.go_forward()
        page.wait_for_function(BOOTED, timeout=20000)
        settle(page)
        got = self.restored(page)
        self.assertEqual(got[:3], [True, lo, "폰에서 쓰던 메모"])
        self.assertTrue(page.evaluate("SIDE_OPEN"))  # a restored draft opens the collapsed sheet

    def test_discard_on_the_restore_toast_clears_the_draft_after_its_undo_window(self):
        """[버리기] goes through the usual discard (with its own undo); once that toast is gone nothing is kept."""
        page = self.view(DESK)
        self.draft(page, "버릴 메모")
        self.reload(page)
        page.locator("#toasts button", has_text="버리기").click()
        self.assertEqual(
            page.evaluate("[document.querySelector('#composer').hidden, document.querySelector('#note').value]"),
            [True, ""],
        )
        undo = page.locator("#toasts .toast", has_text="선택 취소됨")
        self.assertTrue(undo.is_visible())
        self.assertEqual(len(page.evaluate(DRAFT_KEYS)), 1)  # still restorable during the undo window
        undo.locator("button[aria-label]").click()  # [x] ends the window
        settle(page)
        self.assertEqual(page.evaluate(DRAFT_KEYS), [])
        self.reload(page)
        self.assertEqual(self.restored(page)[:3], [False, None, ""])

    def test_a_discard_left_within_its_undo_window_comes_back_but_not_after_it(self):
        """Esc with a note, then reload at once: the draft is back. Esc again and let the window end: gone."""
        page = self.view(DESK)
        lo = self.draft(page, "되돌릴 수 있던 메모")
        page.keyboard.press("Escape")
        self.reload(page)
        self.assertEqual(self.restored(page)[:3], [True, lo, "되돌릴 수 있던 메모"])
        page.locator("#note").focus()
        page.keyboard.press("Escape")
        page.locator("#toasts .toast", has_text="선택 취소됨").locator("button[aria-label]").click()
        settle(page)
        self.reload(page)
        self.assertEqual(self.restored(page)[:3], [False, None, ""])

    def test_a_saved_pin_leaves_no_draft(self):
        """Save and reload right away: no composer, no toast, nothing in sessionStorage."""
        page = self.view(DESK)
        self.draft(page, "저장할 메모")
        page.keyboard.press("Control+Enter")
        page.wait_for_function("OPEN_ALL.length===4")
        self.assertEqual(page.evaluate(DRAFT_KEYS), [])
        self.reload(page)
        self.assertEqual(self.restored(page), [False, None, "", "fix", False, ""])

    def test_a_draft_from_another_build_brings_back_only_the_note(self):
        """After a rebuild the box would point at the wrong spot: the note returns for the next pick, and the toast says so."""
        page = self.view(DESK)
        self.draft(page, "빌드가 바뀐 메모")
        page.evaluate(
            "COMPOSE.current.pdf_build='pages-old'; syncDraft()"
        )  # a draft drawn on a build that has since been replaced
        self.assertIn('"build":"pages-old"', page.evaluate("sessionStorage.getItem(%s[0])" % DRAFT_KEYS))
        self.reload(page)
        got = self.restored(page)
        self.assertEqual(got[:3], [False, None, "빌드가 바뀐 메모"])
        self.assertIn("작성 중이던 메모를 되살렸습니다", got[5])
        self.mouse_pick(page)
        self.assertEqual(page.evaluate("document.querySelector('#note').value"), "빌드가 바뀐 메모")

    def test_a_restored_draft_opens_a_collapsed_wide_panel_without_remembering(self):
        """Wide with the panel collapsed: the restored draft opens it; pinPrefs.sideClosed stays true."""
        page = self.view(DESK)
        self.draft(page, "접힌 패널의 메모")
        page.evaluate("savePrefs({sideClosed:true})")
        self.reload(page)
        self.assertEqual(page.evaluate("[SIDE_OPEN, prefs().sideClosed]"), [True, True])


class DesktopPersistence(ViewerBase):
    """The collapsed state is a per-device choice (pinPrefs.sideClosed) that survives a reload; the width is separate."""

    def test_reload_keeps_the_collapsed_panel_and_the_saved_width(self):
        """Collapse, reload, reopen: still the width from before."""
        page = self.view(DESK, prefs={"side": 410})
        page.keyboard.press("Control+Backslash")
        page.wait_for_function("!SIDE_OPEN")
        page.reload()
        page.wait_for_function("typeof OPEN_ALL!=='undefined'&&OPEN_ALL.length>=3&&META")
        self.assertFalse(page.evaluate("SIDE_OPEN"))
        page.locator("#nav-side").click()
        page.wait_for_function("SIDE_OPEN")
        self.assertEqual(page.evaluate(PROBE)["w"], 410)

    def test_mid_drag_collapse_is_remembered_like_the_toggle(self):
        """Unfolded side-by-side (901-1099px) with a mouse: a drag-collapse stores midClosed, sideMid stays."""
        page = self.view({"viewport": {"width": 1000, "height": 800}}, prefs={"sideMid": 360})
        g = page.locator("#grip").bounding_box()
        page.mouse.move(g["x"] + 4, 300)
        page.mouse.down()
        page.mouse.move(g["x"] + 300, 300, steps=4)
        page.mouse.up()
        page.wait_for_function("!SIDE_OPEN")
        p = page.evaluate("prefs()")
        self.assertEqual((p.get("midClosed"), p.get("sideMid")), (True, 360))


# ---------------------------------------------------------------- A. the unfolded overlay (701-900px, touch)


class FoldOverlay(ViewerBase):
    """842x758 touch: the overlay panel dismisses with a right swipe, Esc, or the back gesture; drafts are protected."""

    def open_panel(self, page, cdp):
        """Tap [핀 N] and wait for the overlay."""
        self.tap(cdp, *self.center(page, "#btn-side"))
        page.wait_for_function("SIDE_OPEN&&MID_OVERLAY")
        settle(page)

    def panel_point(self, page):
        """A point on the list inside the panel, clear of buttons."""
        r = page.locator("#right").bounding_box()
        return r["x"] + 40, r["y"] + 120

    def test_right_swipe_past_35_percent_closes_and_is_remembered(self):
        """The panel follows the finger via right, then slides out; midClosed remembers it."""
        page = self.view(FOLD)
        cdp = self.cdp(page)
        self.open_panel(page, cdp)
        x, y = self.panel_point(page)
        self.touch(cdp, "touchStart", [(x, y)])
        for i in range(1, 7):
            self.touch(cdp, "touchMove", [(x + 10 * i, y + 1)])
            time.sleep(0.03)  # the finger's timing, as in swipe()
        followed = page.evaluate("document.querySelector('#right').getBoundingClientRect().right")
        self.assertGreater(followed, 842 + 40)  # right: -dx, not a transform
        for i in range(7, 16):
            self.touch(cdp, "touchMove", [(x + 10 * i, y + 1)])
            time.sleep(0.03)
        self.touch(cdp, "touchEnd", [])
        page.wait_for_function("!SIDE_OPEN&&!document.body.classList.contains('side-closing')")
        self.assertTrue(page.evaluate("prefs().midClosed"))

    def test_short_slow_swipe_springs_back_and_a_quick_flick_closes(self):
        """60px slowly stays open; the same 60px flicked closes (velocity)."""
        page = self.view(FOLD)
        cdp = self.cdp(page)
        self.open_panel(page, cdp)
        x, y = self.panel_point(page)
        self.swipe(cdp, x, y, x + 60, y, steps=12, dt=0.06)
        settle(page)
        self.assertTrue(page.evaluate("SIDE_OPEN"))
        self.assertEqual(
            page.evaluate("Math.round(document.querySelector('#right').getBoundingClientRect().right)"), 842
        )
        self.swipe(cdp, x, y, x + 60, y, steps=2, dt=0)  # CDP moves land ~30ms apart: ~0.9px/ms
        page.wait_for_function("!SIDE_OPEN")

    def test_a_draft_rubber_bands_the_swipe_and_never_closes(self):
        """Composing: at most 24px of follow, then back."""
        page = self.view(FOLD)
        cdp = self.cdp(page)
        self.long_press_pick(cdp, page)
        x, y = self.center(page, "#c-page")
        self.touch(cdp, "touchStart", [(x, y)])
        for i in range(1, 16):
            self.touch(cdp, "touchMove", [(x + 15 * i, y)])
            time.sleep(0.02)  # the finger's timing, as in swipe()
        shift = page.evaluate("842-document.querySelector('#right').getBoundingClientRect().right")
        self.assertGreaterEqual(shift, -24.5)
        self.assertLess(shift, 0)
        self.touch(cdp, "touchEnd", [])
        settle(page)
        self.assertTrue(page.evaluate("SIDE_OPEN&&!document.querySelector('#composer').hidden"))

    def follow_during(self, page, cdp, x, y, dx, dy=0, hold=0.0):
        """Drag from (x,y) by (dx,dy) and report how far the panel's right edge moved before the finger lifts (hold = a
        still press before moving; the sleeps are the finger's timing, as in swipe())."""
        self.touch(cdp, "touchStart", [(x, y)])
        if hold:
            time.sleep(hold)
        for i in range(1, 11):
            self.touch(cdp, "touchMove", [(x + dx * i / 10, y + dy * i / 10)])
            time.sleep(0.02)  # the finger's timing, as in swipe()
        moved = page.evaluate("Math.round(document.querySelector('#right').getBoundingClientRect().right-innerWidth)")
        self.touch(cdp, "touchEnd", [])
        settle(page)
        return moved

    def test_swipes_starting_on_scrollers_fields_or_after_a_still_press_are_ignored(self):
        """.seg and text fields keep their own horizontal scrolling (the panel does not even rubber-band); a 450ms still
        press is a text selection and a mostly vertical drag is a scroll - neither dismisses the panel."""
        page = self.view(FOLD)
        cdp = self.cdp(page)
        self.long_press_pick(cdp, page)
        for sel in ("#c-levels", "#note"):
            with self.subTest(start=sel):
                page.evaluate(
                    "s=>document.querySelector(s).scrollIntoView({block:'center'})", sel
                )  # under the range excerpt
                settle(page)
                x, y = self.center(page, sel)
                self.assertEqual(self.follow_during(page, cdp, x - 60, y, 150), 0)
                self.assertTrue(page.evaluate("SIDE_OPEN"))
        page.keyboard.press("Escape")  # no draft from here on
        x, y = self.panel_point(page)
        self.assertEqual(self.follow_during(page, cdp, x, y, 150, hold=0.55), 0)
        self.assertEqual(self.follow_during(page, cdp, x, y + 200, 40, -300), 0)
        self.assertTrue(page.evaluate("SIDE_OPEN"))

    def test_escape_closes_the_overlay_after_cancelling_a_selection(self):
        """Esc: first the selection, then the overlay panel."""
        page = self.view(FOLD)
        cdp = self.cdp(page)
        self.long_press_pick(cdp, page)
        page.keyboard.press("Escape")
        self.assertTrue(page.evaluate("SIDE_OPEN&&document.querySelector('#composer').hidden"))
        page.keyboard.press("Escape")
        page.wait_for_function("!SIDE_OPEN")

    def test_a_pick_in_the_right_column_stays_visible_beside_the_overlay(self):
        """While composing in the overlay the PDF gets padding-right: the selection is left of the panel (s10)."""
        page = self.view(FOLD)
        cdp = self.cdp(page)
        page.evaluate("document.querySelector('#left').scrollTop=0")
        p1 = page.locator("#p1").bounding_box()
        self.long_press_pick(cdp, page, p1["x"] + p1["width"] * 0.78, p1["y"] + 300)
        settle(page)
        box = page.locator(".sel.pending").bounding_box()
        panel = page.locator("#right").bounding_box()
        self.assertLessEqual(box["x"] + box["width"], panel["x"])

    def test_tapping_the_handle_never_clicks_what_lands_under_the_finger(self):
        """s07: a tap cycles the width, and the ghost click that followed opened edits and cards."""
        page = self.view(FOLD)
        cdp = self.cdp(page)
        self.open_panel(page, cdp)
        page.evaluate(CLICKS)
        widths = []
        for i in range(4):
            if i:
                self.before_next_tap(page)
            g = page.locator("#grip").bounding_box()
            self.tap(cdp, g["x"] + g["width"] / 2, 240)
            settle(page)
            widths.append(page.evaluate(PROBE)["w"])
        nothing_follows(page)  # the taps' ghost clicks
        self.assertEqual(len(set(widths)), 3)
        self.assertEqual([c for c in page.evaluate("window.__clicks") if c != "grip"], [])
        self.assertEqual(page.evaluate("[...document.querySelectorAll('.pin.editing')].length"), 0)

    def test_select_mode_tap_pick_never_clicks_the_panel_that_opens_under_it(self):
        """s12: a tap-pick in [선택] mode opened the panel under the finger and its ghost click (and ghost focus) hit it."""
        for dev, (x, y) in ((FOLD, (650, 300)), (FOLD, (700, 500)), (PHONE, (190, 600)), (PHONE, (100, 700))):
            with self.subTest(width=dev["viewport"]["width"], at=(x, y)):
                page = self.view(dev)
                cdp = self.cdp(page)
                self.tap(cdp, *self.center(page, "#btn-select"))
                page.wait_for_function("SELMODE")  # the tap's click reached [선택]
                settle(page)
                page.evaluate(CLICKS)
                self.tap(cdp, x, y)
                page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo", timeout=8000)
                nothing_follows(page)  # the tap-pick's ghost click and focus
                self.assertEqual(page.evaluate("window.__clicks"), [])
                self.assertEqual(page.evaluate("KIND_NEW"), "fix")
                self.assertNotEqual(page.evaluate("document.activeElement.id"), "note")

    def test_pin_toggle_while_composing_collapses_with_a_draft_dot(self):
        """[핀] while composing still collapses (explicit), and [핀 N] shows the hidden draft."""
        page = self.view(FOLD)
        cdp = self.cdp(page)
        self.long_press_pick(cdp, page)
        self.tap(cdp, *self.center(page, "#btn-side"))
        page.wait_for_function("!SIDE_OPEN")
        self.assertTrue(page.locator("#btn-side .c-dot").is_visible())
        self.assertIn("작성 중", page.locator("#btn-side").get_attribute("aria-label"))

    def test_right_swipe_never_navigates_back(self):
        """s05e: a right swipe on the PDF or the panel used to go back in history and leave Limn."""
        page = self.view(FOLD)
        navs = []
        page.on("framenavigated", lambda f: navs.append(f.url))
        cdp = self.cdp(page)
        for start in ((200, 300), (20, 300)):
            self.swipe(cdp, start[0], start[1], start[0] + 250, start[1] + 10)
            nothing_follows(page)  # a back navigation the swipe would start
        self.open_panel(page, cdp)
        self.swipe(cdp, 200, 300, 450, 310)
        nothing_follows(page)
        self.assertEqual(navs, [])
        css = page.evaluate(
            "[getComputedStyle(document.documentElement).overscrollBehaviorX,getComputedStyle(document.body).overscrollBehaviorX,"
            "getComputedStyle(document.querySelector('#right')).touchAction]"
        )
        self.assertEqual(css[:2], ["none", "none"])
        self.assertIn("pan-y", css[2])

    def test_double_tap_on_the_pdf_toggles_fit_width_and_2x_around_the_point(self):
        """Outside [선택] mode: fit -> 2x keeping the tapped spot under the finger, then back to fit.

        The page clock is paused around the taps. The viewer counts a double tap by performance.now() (second pointerup
        within 300ms of the first), and each CDP touch event is a synchronous round trip from this process: under CPU load
        the two taps used to land more than 300ms apart on the page's clock, so the second tap started a new double tap and
        W never changed (about 1 run in 5 with 80 busy processes). The 300ms/24px window itself is GestureLogic's test;
        this one checks the wiring - tap to zoom around the point - so it holds the page's time still and waits for W."""
        page = self.view(FOLD)
        cdp = self.cdp(page)
        w0 = page.evaluate("W")
        at = "(()=>{const a=zoomAnchor(300,400);return [a.pg.id,+a.fx.toFixed(3),+a.fy.toFixed(3)];})()"
        before = page.evaluate(at)
        page.clock.install()
        page.clock.pause_at(time.time() * 1000 + 1000)  # performance.now() and the long-press timer stand still
        self.tap(cdp, 300, 400)
        self.tap(cdp, 300, 400)
        page.wait_for_function("w=>Math.abs(W-w)<=2", arg=w0 * 2, timeout=10000)
        after = page.evaluate(at)
        self.assertEqual(after[0], before[0])
        self.assertAlmostEqual(after[1], before[1], delta=0.01)
        self.tap(cdp, 300, 400)
        self.tap(cdp, 300, 400)
        page.wait_for_function("w=>Math.abs(W-w)<=2", arg=w0, timeout=10000)
        self.assertFalse(page.evaluate("ZOOMED"))

    def test_back_gesture_closes_the_overlay_first_without_leaving(self):
        """Without CloseWatcher: one history entry per open overlay; back closes it and Limn stays."""
        page = self.view(FOLD, init=NO_CLOSE_WATCHER)
        boot = page.evaluate("window.__pinViewerBoot")
        cdp = self.cdp(page)
        self.open_panel(page, cdp)
        page.go_back()
        page.wait_for_function("!SIDE_OPEN")
        self.assertEqual(page.evaluate("window.__pinViewerBoot"), boot)

    def test_side_by_side_panel_has_no_swipe(self):
        """901-1099px: the panel sits beside the document, so only the handle changes it."""
        page = self.view(SIDE_BY_SIDE)
        self.assertTrue(page.evaluate("SIDE_OPEN&&!MID_OVERLAY"))
        cdp = self.cdp(page)
        r = page.locator("#right").bounding_box()
        self.swipe(cdp, r["x"] + 30, r["y"] + 150, r["x"] + 330, r["y"] + 150, steps=6, dt=0.01)
        settle(page)
        self.assertTrue(page.evaluate("SIDE_OPEN"))


# ---------------------------------------------------------------- A. the phone sheet (384x832, touch)


class PhoneSheet(ViewerBase):
    """The bottom sheet moves by its whole tool bar and by pulling down content that is scrolled to the top."""

    SH = "(()=>{const r=document.querySelector('#right').getBoundingClientRect();return {top:r.top,h:r.height,open:SIDE_OPEN};})()"

    def test_dragging_the_tool_bar_moves_the_sheet_and_swallows_the_button_click(self):
        """A vertical move over 8px on a tool-bar button is a sheet drag; that button does not fire."""
        page = self.view(PHONE)
        cdp = self.cdp(page)
        page.evaluate(CLICKS)
        x, y = self.center(page, "#btn-select")
        self.swipe(cdp, x, y, x, y - 350, steps=10)
        settle(page)
        s = page.evaluate(self.SH)
        self.assertTrue(s["open"])
        self.assertLess(s["top"], 500)
        self.assertFalse(page.evaluate("SELMODE"))
        self.assertEqual(page.evaluate("window.__clicks"), [])
        x, y = self.center(page, "#btn-select")
        self.swipe(cdp, x, y, x, 820, steps=10)
        page.wait_for_function("!SIDE_OPEN")

    def test_pulling_down_content_at_its_top_lowers_the_sheet(self):
        """Nested scroll hand-off: at scrollTop 0 a downward drag in the list moves the sheet, not the list."""
        page = self.view(PHONE)
        cdp = self.cdp(page)
        self.tap(cdp, *self.center(page, "#btn-side"))
        page.wait_for_function("SIDE_OPEN")
        settle(page)
        top0 = page.evaluate(self.SH)["top"]
        y = page.locator("#list").bounding_box()["y"] + 60
        self.swipe(cdp, 190, y, 190, y + 120, steps=12, dt=0.03)
        settle(page)
        s = page.evaluate(self.SH)
        self.assertTrue(s["open"])
        self.assertGreater(s["top"], top0 + 80)
        y = page.locator("#list").bounding_box()["y"] + 40
        self.swipe(cdp, 190, y, 190, 830, steps=12, dt=0.02)
        page.wait_for_function("!SIDE_OPEN")

    def test_a_downward_fling_collapses_and_an_upward_fling_steps_up(self):
        """A fast pull-down collapses and a fast flick up steps up, even when the test runner is delayed."""
        page = self.view(PHONE, prefs={"sheetF": 0.45})
        cdp = self.cdp(page)
        self.tap(cdp, *self.center(page, "#btn-side"))
        page.wait_for_function("SIDE_OPEN")
        settle(page)
        # The rule uses dragSample timestamps to judge velocity. Give this gesture 10 ms between samples so a loaded
        # runner cannot turn the intended fast input into a slow drag while CDP dispatches the same touch points.
        page.evaluate("""() => {
          const sample = dragSample;
          dragSample = (pts, _t, pos) => sample(pts, pts.length ? pts[pts.length - 1][0] + 10 : 0, pos);
        }""")
        x, y = self.center(page, "#sheet-grip")
        self.swipe(cdp, x, y, x, y - 60, steps=2, dt=0)
        settle(page)
        self.assertAlmostEqual(page.evaluate("prefs().sheetF"), 0.64, delta=0.01)
        x, y = self.center(page, "#sheet-grip")
        self.swipe(cdp, x, y, x, y + 70, steps=3, dt=0.01)
        page.wait_for_function("!SIDE_OPEN")

    def test_a_draft_stops_the_sheet_at_30_percent_instead_of_collapsing(self):
        """phone_05: dragging the sheet down while composing collapsed it and hid the note."""
        page = self.view(PHONE)
        cdp = self.cdp(page)
        self.long_press_pick(cdp, page)
        x, y = self.center(page, "#sheet-grip")
        self.swipe(cdp, x, y, x, 825, steps=14)
        settle(page)
        s = page.evaluate(self.SH)
        self.assertTrue(s["open"])
        self.assertAlmostEqual(s["h"] / 832, 0.3, delta=0.02)
        self.assertFalse(page.evaluate("document.querySelector('#composer').hidden"))

    def test_tapping_the_sheet_handle_never_clicks_what_lands_under_the_finger(self):
        """s07 phone: each tap moved the sheet and the ghost click hit a card, the note or the PDF."""
        page = self.view(PHONE)
        cdp = self.cdp(page)
        page.evaluate(CLICKS)
        for i in range(5):
            if i:
                self.before_next_tap(page)
            settle(page)  # the sheet has stopped where the last tap moved it
            x, y = self.center(page, "#sheet-grip")
            self.tap(cdp, x, y)
        nothing_follows(page)  # the taps' ghost clicks
        self.assertEqual([c for c in page.evaluate("window.__clicks") if c != "sheet-grip"], [])

    def test_right_swipe_on_the_pdf_never_navigates_back(self):
        """s05e phone: a right swipe across the PDF (200 -> 450, as the diagnosis did) used to go back and leave Limn."""
        page = self.view(PHONE)
        navs = []
        page.on("framenavigated", lambda f: navs.append(f.url))
        self.swipe(self.cdp(page), 200, 300, 450, 310)
        nothing_follows(page)  # a back navigation the swipe would start
        self.assertEqual(navs, [])

    def test_back_gesture_closes_the_sheet_first_and_toggling_adds_no_history(self):
        """History fallback: back closes the open sheet and stays; opening/closing by button leaves one entry at most."""
        page = self.view(PHONE, init=NO_CLOSE_WATCHER)
        cdp = self.cdp(page)
        n0 = page.evaluate("history.length")
        for _ in range(3):
            self.tap(cdp, *self.center(page, "#btn-side"))
            page.wait_for_function("SIDE_OPEN")
            self.tap(cdp, *self.center(page, "#btn-side"))
            page.wait_for_function("!SIDE_OPEN")
            # closing pops the layer's history entry with history.back(), which lands later (popstate clears BACK_SKIP)
            page.wait_for_function("!BACK_SKIP&&!(history.state&&history.state.limnLayer)")
            settle(page)
        self.assertLessEqual(page.evaluate("history.length"), n0 + 1)
        boot = page.evaluate("window.__pinViewerBoot")
        self.tap(cdp, *self.center(page, "#btn-side"))
        page.wait_for_function("SIDE_OPEN")
        page.go_back()
        page.wait_for_function("!SIDE_OPEN")
        self.assertEqual(page.evaluate("window.__pinViewerBoot"), boot)

    def test_close_watcher_closes_the_sheet_on_a_close_request(self):
        """With CloseWatcher (Chrome on Android), the sheet listens for the system back; Esc is the desktop close request."""
        page = self.view(PHONE)
        if not page.evaluate("'CloseWatcher' in window"):
            self.skipTest("no CloseWatcher in this Chromium")
        cdp = self.cdp(page)
        self.tap(cdp, *self.center(page, "#btn-side"))
        page.wait_for_function("SIDE_OPEN")
        self.assertEqual(page.evaluate("BACK&&BACK.kind"), "watcher")
        page.keyboard.press("Escape")
        page.wait_for_function("!SIDE_OPEN")

    def test_docs_sheet_closes_on_an_outside_tap_and_a_pull_down(self):
        """The navigation sheet (the documents sheet before it) behaves like [더보기]: outside tap closes it, and it follows
        a pull down."""
        page = self.view(PHONE)
        cdp = self.cdp(page)
        page.evaluate("openNavSheet()")
        self.tap(cdp, 190, 100)
        page.wait_for_function("!document.querySelector('#nav-sheet').open")
        page.evaluate("openNavSheet()")
        r = page.locator("#nav-sheet").bounding_box()
        self.swipe(cdp, 190, r["y"] + 20, 190, r["y"] + 20 + r["height"] * 0.6, steps=10, dt=0.02)
        page.wait_for_function("!document.querySelector('#nav-sheet').open")

    def test_stacked_toasts_open_on_a_tap(self):
        """More than three toasts: a '+N' button under the stack opens it on touch (hover/focus only did before)."""
        page = self.view(PHONE)
        page.evaluate("for(let i=1;i<=5;i++)toast('알림 '+i,'ok')")
        visible = "[...document.querySelectorAll('#toasts .toast')].filter(t=>t.getClientRects().length).length"
        self.assertEqual(page.evaluate(visible), 3)
        more = page.locator("#toasts-more")
        self.assertTrue(more.is_visible())
        self.tap(self.cdp(page), *self.center(page, "#toasts-more"))
        page.wait_for_function(visible + "===5")


# Every visible element matching the selector whose tap area is under 44px wide or high, as "name WxH(hit wxh)": from its
# centre, the px that still answer it going left/right/up/down (each side counted to 60px), as the diagnosis measured them - the
# touch twin of DesktopMisc's 24px probe. A hit area may sit off-centre (the sheet's tool bar reaches only downwards).
MISSES_44 = """sel => {
  const out = [];
  const own = (e, x, y) => { if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) return false;
    const h = document.elementFromPoint(x, y); return !!h && (h === e || e.contains(h)); };
  for (const e of document.querySelectorAll(sel)) {
    const r = e.getBoundingClientRect(); if (!r.width || !r.height || getComputedStyle(e).visibility === 'hidden') continue;
    if (r.top < 0 || r.bottom > innerHeight || r.left < 0 || r.right > innerWidth) continue;
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2; let l = 0, ri = 0, u = 0, d = 0;
    if (own(e, cx, cy)) { while (l < 60 && own(e, cx - l - 1, cy)) l++; while (ri < 60 && own(e, cx + ri + 1, cy)) ri++;
      while (u < 60 && own(e, cx, cy - u - 1)) u++; while (d < 60 && own(e, cx, cy + d + 1)) d++; }
    const w = l + ri + 1, h = u + d + 1;
    if (w < 44 || h < 44) out.push((e.id ? '#' + e.id : e.className) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height) + '(hit ' + w + 'x' + h + ')');
  }
  return out; }"""


# A mouse window in the mid layout, and a wide desktop window.
MOUSE_MID = {"viewport": {"width": 1000, "height": 800}}
MOUSE_WIDE = {"viewport": {"width": 1440, "height": 900}}


class LayoutNotPointer(ViewerBase):
    """The compact arrangement follows the layout mode, not the pointer that draws it (docs/handbook/viewer.md §모바일 레이아웃): a
    mouse window in a mid band gets the compact card and the [더보기] sheet too. Only the wide layout with a mouse is the
    unchanged desktop."""

    def test_a_mouse_at_mid_width_gets_the_compact_card_and_the_more_sheet(self):
        """1000x800 with a mouse: the head's '#N · L… · N쪽' link, the icon row without [보기], [더보기] on the bottom edge."""
        page = self.view(MOUSE_MID)
        self.assertTrue(page.evaluate("document.body.classList.contains('lay-mid')&&!MQ_COARSE.matches"))
        pid = page.evaluate("PINS[0].id")
        page.evaluate("id=>{setSide(true); OPEN_CARDS.add(id); drawPins();}", pid)
        settle(page)
        card = '#pins .pin[data-id="%d"]' % pid
        got = page.evaluate(
            """s => {const c = document.querySelector(s), vis = e => !!e && e.getClientRects().length > 0;
              return {link: vis(c.querySelector('.go-all')), view: vis(c.querySelector('.acts .b-view')),
                acts: [...c.querySelectorAll('.acts button')].filter(vis).map(b => b.dataset.act),
                icons: [...c.querySelectorAll('.acts :is(.b-edit,.b-drop) .ic')].every(vis)}; }""",
            card,
        )
        self.assertEqual(
            got, {"link": True, "view": False, "acts": ["drop", "edit", "reply-open", "close"], "icons": True}
        )
        page.evaluate("openMore()")
        settle(page)
        box = page.locator("#more").bounding_box()
        self.assertAlmostEqual(box["y"] + box["height"], 800, delta=1)

    def test_the_helps_range_step_is_the_excerpts_on_every_layout(self):
        """The tour's range step names the excerpt on every layout: a mouse at 1000x800 (mid) and at 1440x900 (wide - it
        read the stepper's '위 +' sentence until the stepper went) and a phone read the dimmed-line sentence."""
        for device in (MOUSE_MID, MOUSE_WIDE, phone(411, 908)):
            with self.subTest(w=device["viewport"]["width"]):
                page = self.view(device)
                page.evaluate("openHelp()")
                settle(page)
                got = page.evaluate("document.querySelectorAll('#help .help-steps li')[1].innerText")
                self.assertIn("흐린 줄", got)
                self.assertNotIn("위 +", got)

    def test_a_mouse_at_wide_width_sees_the_desktop_unchanged(self):
        """1440x900 with a mouse: the panel, card and tool bar are as they were before the compact work - a 348px panel,
        28px tool bar, the section strip, the card's #N / range / N쪽 and its named grid and the 36px save row; the composer
        has the one order of every layout (location, note, kind, the range block with its excerpt; the cross-resolution
        pass, 1b)."""
        page = self.view(MOUSE_WIDE)
        self.mouse_pick(page)
        got = page.evaluate(
            """() => {const q = s => document.querySelector(s), R = s => q(s).getBoundingClientRect(), vis = e => !!e && e.getClientRects().length > 0;
              const c = q('#pins .pin'), acts = [...c.querySelectorAll('.acts button')].filter(vis);
              const tops = s => [...document.querySelectorAll(s)].filter(vis).sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top).map(e => e.id || e.className);
              return {panel: Math.round(R('#right').width), tool: Math.round(R('#btn-rebuild').height), strip: Math.round(R('#section-strip').height),
                head: [vis(c.querySelector('.n.go')), vis(c.querySelector('.loc')), vis(c.querySelector('.pg-link')), vis(c.querySelector('.go-all'))],
                acts: acts.map(b => b.innerText.trim()), even: new Set(acts.map(b => Math.round(b.getBoundingClientRect().width))).size,
                rowTop: new Set(acts.map(b => Math.round(b.getBoundingClientRect().top))).size,
                composer: tops('#composer .c-loc-row,#composer #c-levels,#composer #c-xp,#composer #c-snip,#composer #c-kind,#composer #note'),
                save: Math.round(R('#btn-save').height), lift: document.body.classList.contains('sheet-up')}; }"""
        )
        self.assertEqual(
            got,
            {
                "panel": 348,
                "tool": 28,
                "strip": 38,
                "head": [True, True, True, False],
                "acts": ["보기", "수정", "답글", "삭제", "완료"],
                "even": 1,
                "rowTop": 1,
                "composer": ["c-loc-row", "note", "c-kind", "c-levels", "c-xp"],
                "save": 36,
                "lift": False,
            },
        )

    def test_a_mouse_at_1440_keeps_badges_outside_even_at_the_page_edge(self):
        """1440x900 with a mouse: the 44px desktop margin leaves the badge room, so marks at the page's edge, at the text
        (6.4%) and further in all keep it 22px left of the mark's border box, as before the inside rule (UX audit R4)."""
        for fx, lo in ((0.0, 30), (0.064, 32)):
            add_pin(
                {
                    "file": str(self.main),
                    "lo": lo,
                    "hi": lo + 1,
                    "page": 1,
                    "note": "왼쪽",
                    "frac": [fx, 0.6 + fx, 0.4, 0.04],
                },
                actor(ALICE),
            )
        page = self.view(MOUSE_WIDE)
        got = page.evaluate(MARK_BADGES)
        self.assertEqual(
            {(g["fx"], g["inside"], g["shown"], g["gap"]) for g in got},
            {(0.0, False, True, 22), (0.064, False, True, 22), (0.15, False, True, 22)},
        )

    def test_a_mouse_at_1440_keeps_the_desktop_geometry_to_the_pixel(self):
        """1440x900 with a mouse: the page's margins and box, its first mark's badge, the panel's tool bar, section head and
        first card, and the help and Trash dialogs sit where they sat before the touch edge grid (UX audit V2/V6): the
        desktop layout is unchanged. (The documents sheet, which only the phone opened, is the phone's navigation sheet.)
        What CSS lengths, the viewport or the page size is compared to the pixel. What a label or a wrapped note sizes is
        compared by where it starts and ends, how tall it is and its order, never by its width or by the height its text
        makes - those follow the installed fonts (a tool-bar button was 71px wide here and 79px on CI), so desk_shape()
        leaves them out."""
        page = self.view(MOUSE_WIDE)
        page.evaluate("document.querySelector('#left').scrollTop=0")
        settle(page)
        got = page.evaluate(DESK_GEOMETRY)
        for opener, dlg in (("openHelp()", "#help"), ("openTrash()", "#trash")):
            page.evaluate(opener)
            settle(page)
            got[dlg] = page.evaluate(DESK_DIALOG, dlg)
            page.evaluate("s=>document.querySelector(s).close()", dlg)
        self.maxDiff = None  # the whole shape is one dict: show which entries moved
        self.assertEqual(desk_shape(got), DESK_1440)


# Where the desktop's chrome sits at 1440x900 with a mouse on the ViewerBase fixture, as measured in the page: boxes are
# [x, y, width, height] (rounded), paddings [top, right, bottom, left] (computed). A tool-bar item also carries its left edge
# from the panel's left edge (start), its right edge from the panel's right edge (end) and whether it follows the spacer
# (after: the right-aligned group), both taken from the unrounded boxes.
DESK_GEOMETRY = """() => {const q = s => document.querySelector(s), R = Math.round, panel = q('#right').getBoundingClientRect(),
    B = e => {const r = e.getBoundingClientRect(); return [R(r.x), R(r.y), R(r.width), R(r.height)];},
    P = e => {const c = getComputedStyle(e); return [c.paddingTop, c.paddingRight, c.paddingBottom, c.paddingLeft];},
    spacer = q('#bar1 .sp'), card = q('#pins .pin');
  return {left: P(q('#left')), page: B(q('#p1')), badge: B(q('.mark b')), right: B(q('#right')), tool: B(q('#bar1')),
    bar: [...q('#bar1').children].filter(e => e.getClientRects().length).map(e => {const r = e.getBoundingClientRect();
      return {id: e.id || e.className, box: B(e), start: R(r.left - panel.left), end: R(panel.right - r.right),
        after: !!(spacer.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING)};}),
    head: B(q('#sec-open .sec-head')), toggle: B(q('#open-toggle')), chevron: B(q('#open-toggle svg')), card: B(card), card_pad: P(card),
    dot: B(q('#pins .pin .st-dot')), list: P(q('#list'))};}"""
# One open dialog: its box and paddings, its computed max-height, and how it is anchored in the viewport - its middle and the
# gap under it, from the unrounded box.
DESK_DIALOG = """s => {const e = document.querySelector(s), r = e.getBoundingClientRect(), c = getComputedStyle(e), R = Math.round;
  return {box: [R(r.x), R(r.y), R(r.width), R(r.height)], pad: [c.paddingTop, c.paddingRight, c.paddingBottom, c.paddingLeft],
    max_height: c.maxHeight, mid: R((r.top + r.bottom) / 2), below: R(innerHeight - r.bottom)};}"""
# Tool-bar items whose width a label sets (the spacer's, the free room); the others are icon buttons of a CSS length.
BAR_LABEL_SIZED = ("btn-rebuild", "sp", "jump")
# How each dialog is anchored: a centred one by its middle (its text-made height moves both edges), a bottom sheet by the gap
# under it.
DIALOG_ANCHOR = {"#help": "mid", "#trash": "mid"}


def desk_shape(got: dict[str, Any]) -> dict[str, Any]:
    """DESK_GEOMETRY and DESK_DIALOG's answers reduced to what the installed fonts do not move. Kept as measured: every
    box and padding that a CSS length, the viewport or the page sizes, and each dialog's x, width, paddings, max-height and
    anchor. Reduced: the tool bar to its items' order, y and height, the icon buttons' width, the first item's left edge and
    the right-aligned group's right edges (both from the panel's edges); the section toggle to x, y and height; the card to
    x, y and width and its paddings; a dialog's own height and, for a centred one, its y to its middle."""
    shape = {
        k: got[k] for k in ("left", "page", "badge", "right", "tool", "head", "chevron", "card_pad", "dot", "list")
    }
    bar = got["bar"]
    shape["bar"] = [
        [b["id"], b["box"][1], b["box"][3], None if b["id"] in BAR_LABEL_SIZED else b["box"][2]] for b in bar
    ]
    shape["bar_start"] = bar[0]["start"]
    shape["bar_ends"] = {b["id"]: b["end"] for b in bar if b["after"]}
    x, y, _, height = got["toggle"]
    shape["toggle"] = [x, y, height]
    x, y, width, _ = got["card"]
    shape["card"] = [x, y, width]
    for dlg, anchor in DIALOG_ANCHOR.items():
        d = got[dlg]
        shape[dlg] = {
            "x": d["box"][0],
            "width": d["box"][2],
            "pad": d["pad"],
            "max_height": d["max_height"],
            anchor: d[anchor],
        }
    return shape


DESK_1440 = {
    "left": ["16px", "16px", "540px", "44px"],
    "page": [290, 98, 780, 1009],
    "badge": [386, 300, 22, 22],
    "right": [1092, 0, 348, 900],
    "tool": [1093, 0, 347, 45],
    "bar": [
        ["btn-rebuild", 8, 28, None],
        ["sp", 22, 0, None],
        ["jump", 8, 28, None],
        ["btn-zoom-out", 8, 28, 28],
        ["btn-zoom-in", 8, 28, 28],
        ["btn-fit", 8, 28, 28],
        ["btn-notify", 8, 28, 28],
        ["btn-theme", 8, 28, 28],
        ["btn-help", 8, 28, 28],
    ],
    "bar_start": 9,
    "bar_ends": {
        "jump": 200,
        "btn-zoom-out": 168,
        "btn-zoom-in": 136,
        "btn-fit": 104,
        "btn-notify": 72,
        "btn-theme": 40,
        "btn-help": 8,
    },
    "head": [1093, 108, 347, 31],
    "toggle": [1101, 112, 22],
    "chevron": [1106, 116, 14, 14],
    "card": [1105, 143, 323],
    "card_pad": ["8px", "12px", "8px", "12px"],
    "dot": [1118, 162, 8, 8],
    "list": ["0px", "12px", "32px", "12px"],
    "#help": {"x": 380, "width": 680, "pad": ["16px", "24px", "16px", "24px"], "max_height": "792px", "mid": 450},
    "#trash": {"x": 440, "width": 560, "pad": ["16px", "24px", "16px", "24px"], "max_height": "792px", "mid": 450},
}


class PhoneTouchSizes(ViewerBase):
    """Touch sizes on the phone sheet: every control answers a tap in a 44x44 box, whatever its drawn size - the assignee
    chip, the card head's links, the tool bar under the sheet handle (input diagnosis P6) - and no text is below 12px (P7)."""

    def setUp(self):
        """One more open pin, assigned to Bob, so its card head carries the assignee chip."""
        super().setUp()
        ps.APP.people_directory.record(actor(BOB))
        add_pin(
            {
                "file": str(self.main),
                "lo": 30,
                "hi": 31,
                "page": 1,
                "note": "담당 있는 핀",
                "assignee": BOB["Tailscale-User-Login"],
            },
            actor(ALICE),
        )

    def open_card(self, page):
        """The phone sheet open at its top, with the assigned pin's card expanded; returns that card's selector."""
        pid = page.evaluate("OPEN_ALL.find(p=>p.assignee).id")
        page.evaluate(
            "id=>{setSide(true); OPEN_CARDS.add(id); drawPins(); document.querySelector('#right').scrollTop=0;}", pid
        )
        settle(page)
        card = '.pin[data-id="%d"]' % pid
        page.evaluate(
            "s=>document.querySelector(s).scrollIntoView({block:'center'})", card
        )  # clear of the scroll box's edges
        settle(page)
        return card

    def test_the_review_count_is_its_own_half_of_the_chip(self):
        """411x908, 384 and 360: the review count is the chip's right half [검토 1] (#btn-rv) - a bare '1' after the open
        count read as '4 1' (UX audit P10), and the pill with its eye left the sheet bar for the words-first chip - while the
        pins half's pill is hidden. The sheet's toggle has no arrow at any width: the grabber says it is a sheet."""
        for device in (phone(411, 908), PHONE, PHONE_360):
            with self.subTest(width=device["viewport"]["width"]):
                page = self.view(device)
                got = page.evaluate(
                    "()=>{const v=e=>e.getClientRects().length>0, r=document.querySelector('#btn-rv');"
                    " return [r.innerText.replace(/\\s+/g,' ').trim(), v(r), v(document.querySelector('#btn-side .rv-n')),"
                    " !!document.querySelector('#side-arrow')];}"
                )
                self.assertEqual(got, ["검토 1", True, False, False])

    def test_card_head_controls_and_the_tool_bar_answer_a_44px_box(self):
        """The assignee chip answered 72x20 (its overflow clipped the hit area), '1쪽' 16x38 and 'L4-L5' 33x38 (neighbours took
        their halves), and the sheet handle took the top 8px of every tool-bar button (36px high)."""
        page = self.view(PHONE)
        card = self.open_card(page)
        self.assertTrue(page.is_visible(card + " .as-chip"))
        misses = page.evaluate(
            MISSES_44,
            "%s .head [data-act],%s .head [data-copy],%s .head button,#bar1 button" % (card, card, card),
        )
        self.assertEqual(misses, [])

    def test_the_sheet_header_is_92px_and_its_handle_and_section_tools_answer_44px(self):
        """The sheet's stuck header was the handle row 24 + the tool bar 53 + the section head 52 = 129px (diagnosis P3); the handle
        now sits in the tool bar's row, so the header (below the sheet's 1px edge, as the diagnosis measured it) is the 52px row
        (its 28px controls 12px under the edge and 12px above the row's end) and the 40px section head, and every control in it -
        the handle included (it answered 121x32) - still answers a 44x44 box."""
        page = self.view(PHONE, prefs={"sec": {"open": True, "review": True, "done": True}}, init=NO_PNG_CHIP)
        page.evaluate("()=>{setSide(true); document.querySelector('#right').scrollTop=0;}")
        settle(page)
        head = page.evaluate(
            "Math.round(document.querySelector('#sec-open .sec-head').getBoundingClientRect().bottom"
            "-document.querySelector('#bar1').getBoundingClientRect().top)"
        )
        self.assertLessEqual(head, 92)  # 80 before the row's 12px insets over and under its 28px controls
        self.assertTrue(
            page.evaluate("document.querySelector('#bar1').contains(document.querySelector('#sheet-grip'))")
        )
        misses = page.evaluate(MISSES_44, "#bar1 button,#sheet-grip,#sec-open .sec-head button")
        self.assertEqual(misses, [])

    def test_the_card_row_is_three_icons_and_two_names_and_the_head_is_one_link(self):
        """An open card's six equal buttons were 40px wide in a tablet panel (diagnosis P4): [보기] is now the head's
        '#N · L… · N쪽' link (one tap, the same place), [삭제][수정][풀기] are icons with names for screen readers and tooltips,
        [답글][완료] keep their names; every one still answers a 44px box and keeps its data-act."""
        page = self.view(PHONE)
        card = self.open_card(page)
        page.evaluate(
            "s=>{const id=+document.querySelector(s).dataset.id; OPEN_ALL.concat(PINS).filter(p=>p.id===id)"
            ".forEach(p=>{p.claim_until=Date.now()/1000+600;}); drawPins();}",
            card,
        )
        settle(page)
        row = page.evaluate(
            """s => [...document.querySelectorAll(s + ' .acts button')].filter(b => b.getClientRects().length)
                 .map(b => [b.dataset.act, b.innerText.trim(), b.getAttribute('aria-label') || '', Math.round(b.getBoundingClientRect().height)])""",
            card,
        )
        order = page.evaluate(
            "s=>[...document.querySelectorAll(s+' .acts button')].filter(b=>b.getClientRects().length)"
            ".sort((a,b)=>a.getBoundingClientRect().left-b.getBoundingClientRect().left).map(b=>b.dataset.act)",
            card,
        )
        self.assertEqual(order, ["drop", "edit", "unclaim", "reply-open", "close"])
        names = {a: (t, lab, h) for a, t, lab, h in row}
        for act, label in (("drop", "삭제"), ("edit", "수정"), ("unclaim", "풀기")):
            self.assertEqual(names[act], ("", label, 32), act)
        for act, text in (("reply-open", "답글"), ("close", "완료")):
            self.assertEqual(names[act][:2], (text, ""), act)
        head = page.evaluate(
            "s=>[...document.querySelectorAll(s+' .head [data-act=view]')].filter(e=>e.getClientRects().length).map(e=>e.innerText)",
            card,
        )
        self.assertEqual(len(head), 1)
        self.assertRegex(head[0], r"^#\d+ · L30-L31 · 1쪽$")
        self.assertEqual(page.evaluate(MISSES_44, card + " .acts button," + card + " .head [data-act=view]"), [])

    def test_the_card_row_sits_one_step_under_the_note_and_its_icons_match(self):
        """Controller review of the after-shots: a 22-60px band sat between the note and the row (the note's 44px min-height),
        [삭제] had no fill while [수정] and [풀기] did, and [풀기] was a circled x that reads as close. Now the row is one spacing
        step (8px) under the note, the three icons share the neutral fill and size with only the delete glyph red, [삭제] keeps one
        more step from [수정], and [풀기] is an open lock."""
        page = self.view(PHONE)
        card = self.open_card(page)
        page.evaluate(
            "s=>{const id=+document.querySelector(s).dataset.id; OPEN_ALL.concat(PINS).filter(p=>p.id===id)"
            ".forEach(p=>{p.claim_until=Date.now()/1000+600;}); drawPins();}",
            card,
        )
        settle(page)
        got = page.evaluate(
            """s => {
              const c = document.querySelector(s), q = x => c.querySelector(x), R = x => q(x).getBoundingClientRect();
              const cs = x => getComputedStyle(q(x));
              const g = document.createRange(); g.selectNodeContents(q('.note'));
              const text = Math.max(...[...g.getClientRects()].filter(r => r.height > 0).map(r => r.bottom));   // the note's last line, not its box
              return {gap: Math.round(R('.acts').top - text), boxGap: Math.round(R('.acts').top - R('.note').bottom),
                fills: ['.b-drop', '.b-edit', '.b-unclaim'].map(x => cs(x).backgroundColor),
                sizes: ['.b-drop', '.b-edit', '.b-unclaim'].map(x => Math.round(R(x).width) + 'x' + Math.round(R(x).height)),
                glyphs: [cs('.b-drop').color, cs('.b-edit').color],
                apart: [Math.round(R('.b-edit').left - R('.b-drop').right), Math.round(R('.b-unclaim').left - R('.b-edit').right)],
                lock: !!q('.b-unclaim svg.ic-lock-open')}; }""",
            card,
        )
        self.assertLessEqual(
            got["gap"], 12
        )  # the 8px step plus the last line's half-leading (21.7px line, ~14px glyphs)
        self.assertEqual(got["boxGap"], 8)
        self.assertEqual(len(set(got["fills"])), 1, got["fills"])
        self.assertNotIn(got["fills"][0], ("rgba(0, 0, 0, 0)", "transparent"))
        self.assertEqual(len(set(got["sizes"])), 1, got["sizes"])
        self.assertNotEqual(got["glyphs"][0], got["glyphs"][1])
        self.assertEqual(got["apart"][0] - got["apart"][1], 8)
        self.assertTrue(got["lock"])

    def test_a_tap_anywhere_on_a_collapsed_card_opens_it(self):
        """The collapsed card opened only from its 20px preview line or the chevron; now any spot that is not a link does."""
        page = self.view(PHONE)
        page.evaluate(
            "()=>{setSide(true); OPEN_CARDS.clear(); drawPins(); document.querySelector('#right').scrollTop=0;}"
        )
        settle(page)
        # the collapsed head's link and chevron keep their 44px boxes over the preview line below them
        self.assertEqual(page.evaluate(MISSES_44, "#pins .pin .head [data-act]"), [])
        card = page.locator("#pins .pin").first
        b = card.bounding_box()
        pid = int(card.get_attribute("data-id"))
        self.tap(self.cdp(page), b["x"] + b["width"] * 0.6, b["y"] + b["height"] - 4)
        page.wait_for_function("id=>OPEN_CARDS.has(id)", arg=pid)

    def test_tab_walks_the_card_row_from_left_to_right(self):
        """The row's markup order is its visual order: it was edit, reply, release, delete, done in the DOM and delete, edit,
        release, reply, done on screen (CSS order), so Tab jumped back and forth."""
        page = self.view(PHONE)
        card = self.open_card(page)
        page.evaluate(
            "s=>{const id=+document.querySelector(s).dataset.id; OPEN_ALL.concat(PINS).filter(p=>p.id===id)"
            ".forEach(p=>{p.claim_until=Date.now()/1000+600;}); drawPins();}",
            card,
        )
        settle(page)
        seen = page.evaluate(
            "s=>[...document.querySelectorAll(s+' .acts button')].filter(b=>b.getClientRects().length)"
            ".sort((a,b)=>a.getBoundingClientRect().left-b.getBoundingClientRect().left).map(b=>b.dataset.act)",
            card,
        )
        page.evaluate("s=>document.querySelector(s+' .acts button').focus()", card)
        tabbed = [page.evaluate("document.activeElement.dataset.act")]
        for _ in range(len(seen) - 1):
            page.keyboard.press("Tab")
            tabbed.append(page.evaluate("document.activeElement.dataset.act"))
        self.assertEqual(seen, ["drop", "edit", "unclaim", "reply-open", "close"])
        self.assertEqual(tabbed, seen)

    def test_no_text_on_a_touch_screen_is_below_12px(self):
        """Badges, the assignee chip, the reply count, avatar initials and page numbers were 11px (--text-xs) on a phone."""
        page = self.view(PHONE)
        page.evaluate("()=>{setSide(true); OPEN_ALL.forEach(p=>OPEN_CARDS.add(p.id)); drawPins();}")
        settle(page)
        small = page.evaluate("""() => {
          const out = [];
          for (const e of document.querySelectorAll('body *')) {
            if (![...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue;
            if (!e.getClientRects().length || getComputedStyle(e).visibility === 'hidden') continue;
            const fs = parseFloat(getComputedStyle(e).fontSize);
            if (fs < 12) out.push((e.id ? '#' + e.id : e.className || e.tagName) + ' ' + fs);
          }
          return [...new Set(out)]; }""")
        self.assertEqual(small, [])

    def test_a_mouse_keeps_the_named_card_buttons(self):
        """The desktop card is unchanged: [보기][수정][답글][삭제][완료] by name, and no merged head link."""
        page = self.view(DESK)
        texts = page.evaluate(
            "[...document.querySelectorAll('#pins .pin')[0].querySelectorAll('.acts button')].filter(b=>b.getClientRects().length).map(b=>b.innerText.trim())"
        )
        self.assertEqual(texts, ["보기", "수정", "답글", "삭제", "완료"])
        self.assertFalse(
            page.evaluate("[...document.querySelectorAll('.pin .go-all')].some(e=>e.getClientRects().length)")
        )

    def test_a_mouse_keeps_the_drawn_card_head(self):
        """The 44px boxes are touch only: a mouse sees the card head links at their text size (24px hit areas, DesktopMisc)."""
        page = self.view(DESK)
        w = page.evaluate("Math.round(document.querySelector('.pin .pg-link').getBoundingClientRect().width)")
        self.assertLess(w, 30)


# The narrowest phone of the diagnosis and its keyboard (Chrome on Android shrinks the layout by it: resizes-content).
PHONE_360 = {"viewport": {"width": 360, "height": 780}, "is_mobile": True, "has_touch": True}
KEYBOARD_360 = 300
# How much of an element is visible and on top: the px rows of its centre column whose topmost element is it, and the rows its
# box covers (on screen or not), counted the same way - its height rounded disagreed by one row when the box started on a whole
# pixel and ended on a fraction.
SHOWN = """sel => {
  const e = document.querySelector(sel), r = e.getBoundingClientRect(), x = r.left + r.width / 2; let n = 0;
  for (let y = Math.max(0, Math.ceil(r.top)); y < Math.min(innerHeight, r.bottom); y++) {
    const t = document.elementFromPoint(x, y); if (t && (t === e || e.contains(t))) n++; }
  return [n, Math.ceil(r.bottom) - Math.ceil(r.top)]; }"""


class PhoneComposer(ViewerBase):
    """The phone sheet's composer (input diagnosis P2): the note comes right after the location line, the overlap notice is one
    line, the sheet rises to 80% while composing without remembering it, and the save row is 56px - so the note field is
    whole above [취소][핀 저장], and with the keyboard up the location line is still above it."""

    def compose(self, page):
        """A touch selection through the real pick path (the computed answer overlaps the open pin at L4-L5)."""
        page.evaluate("()=>{LAST_PTR='touch'; pick({page:1,x0:10,y0:10,x1:200,y1:60});}")
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
        settle(page)

    def test_the_note_is_whole_above_the_save_row_with_the_overlap_notice(self):
        """360x780: the note was the fourth block and the save row covered 64 of its 92px."""
        page = self.view(PHONE_360)
        self.compose(page)
        self.assertTrue(page.is_visible("#c-overlap"))
        self.assertLessEqual(page.locator("#c-overlap").bounding_box()["height"], 44)
        seen, h = page.evaluate(SHOWN, "#note")
        self.assertEqual(seen, h)
        self.assertEqual(round(page.locator("#c-actions").bounding_box()["height"]), 56)
        order = page.evaluate(
            "[...document.querySelectorAll('.c-loc-row,#note,#c-overlap,#c-levels,#c-kind,#c-xp')]"
            ".map(e=>[e.id||e.className,Math.round(e.getBoundingClientRect().top)]).sort((a,b)=>a[1]-b[1]).map(a=>a[0])"
        )
        self.assertEqual(order, ["c-loc-row", "note", "c-kind", "c-overlap", "c-levels", "c-xp"])

    def test_with_the_keyboard_up_the_note_and_the_location_line_stay_in_view(self):
        """The keyboard shrinks the layout by 300px: the location line scrolled to y -35 above the note."""
        page = self.view(PHONE_360)
        self.compose(page)
        page.focus("#note")
        page.set_viewport_size({"width": 360, "height": 780 - KEYBOARD_360})
        settle(page)
        seen, h = page.evaluate(SHOWN, "#note")
        self.assertEqual(seen, h)
        seen, h = page.evaluate(SHOWN, "#c-loc")
        self.assertEqual(seen, h)

    def test_the_sheet_rises_to_80_percent_while_composing_and_goes_back_after(self):
        """The lift is not remembered: cancelling returns the sheet to its saved height."""
        page = self.view(PHONE_360)
        page.evaluate("setSide(true)")
        settle(page)
        self.assertAlmostEqual(page.locator("#right").bounding_box()["height"] / 780, 0.64, delta=0.01)
        self.compose(page)
        self.assertAlmostEqual(page.locator("#right").bounding_box()["height"] / 780, 0.8, delta=0.01)
        page.evaluate("document.querySelector('#btn-cancel').click(); setSide(true)")
        settle(page)
        self.assertAlmostEqual(page.locator("#right").bounding_box()["height"] / 780, 0.64, delta=0.01)
        self.assertNotIn("sheetF", page.evaluate("prefs()"))

    def test_a_height_the_user_sets_while_composing_wins_over_the_lift(self):
        """A preset chosen while composing applies at once (the lift never overrides the user)."""
        page = self.view(PHONE_360)
        self.compose(page)
        page.evaluate("sizePreset(0)")
        settle(page)
        self.assertAlmostEqual(page.locator("#right").bounding_box()["height"] / 780, 0.45, delta=0.01)


# The bottom rows as drawn: the composer's save row, the edit card's row, the sheet or panel, the tool bar (the mid action
# row), the open edit card, and whether the sheet's content fits it without scrolling.
FOOTERS = """() => {const R = s => {const e = document.querySelector(s); if (!e || !e.getClientRects().length) return null;
  const b = e.getBoundingClientRect(); return {top: b.top, bottom: b.bottom, left: b.left, right: b.right};};
  const r = document.querySelector('#right');
  return {save: R('#c-actions'), edit: R('.edit .e-acts'), card: R('.pin.editing'), sheet: R('#right'), bar: R('#bar1'),
    fits: r.scrollHeight <= r.clientHeight + 1, vh: innerHeight};}"""
# Every list section shut, so the pin sheet's content is shorter than the sheet raised to its top.
SECTIONS_SHUT = {"sec": {"open": False, "review": False, "done": False}}
# A soft keyboard that shrinks only the visual viewport (iOS Safari, a Chrome without interactive-widget): the layout keeps
# its height, visualViewport.height drops by window.__setKb(n)'s n and a resize event follows.
KB_VISUAL_ONLY = """window.__kb = 0;
(() => {const vv = window.visualViewport; if (!vv) return;
  const real = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(vv), 'height');
  Object.defineProperty(vv, 'height', {configurable: true, get() {return window.__kb ? document.documentElement.clientHeight - window.__kb : real.get.call(vv);}});
  window.__setKb = n => {window.__kb = n; vv.dispatchEvent(new Event('resize'));};})();"""


class BottomActionRow(ViewerBase):
    """The compact bands' bottom action rows (docs/handbook/viewer.md §패널 정리 동작 줄): on the owner's 411x908 phone the
    composer's [취소][핀 저장] followed a short list up the raised sheet and sat 80% down the screen over blank sheet. The
    row - and the edit card's [위치 다시 잡기][취소][저장] - is on the screen's bottom edge whatever the sheet's height,
    while the sheet is dragged and with the keyboard up; in mid it is the panel's bottom, on the action row."""

    def compose(self, page):
        """A touch selection through the real pick path; waits for the composer."""
        page.evaluate("()=>{LAST_PTR='touch'; pick({page:1,x0:10,y0:10,x1:200,y1:60});}")
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
        settle(page)

    def edit_first(self, page):
        """Opens the edit card on the first open pin with the sheet or panel open, the keyboard down."""
        page.evaluate("()=>{setSide(true); openEdit(OPEN_ALL[0].id);}")
        page.wait_for_function("EDITOR.current&&EDITOR.current.levels.length>0")
        page.evaluate("document.activeElement.blur()")
        settle(page)

    def test_the_save_row_is_on_the_screen_bottom_under_a_short_list(self):
        """411x908 phone and 768x1024 tablet sheet, every section shut and the sheet raised to its top, so its content is
        shorter than the sheet: the save row ends on the screen's bottom edge, not under the list."""
        for w, h in ((411, 908), (768, 1024)):
            with self.subTest(w=w):
                page = self.view(phone(w, h), prefs=SECTIONS_SHUT)
                self.compose(page)
                page.evaluate("setSheetF(1)")
                settle(page)
                f = page.evaluate(FOOTERS)
                self.assertTrue(f["fits"], f)  # the case the owner met: no scrolling, room under the list
                self.assertAlmostEqual(f["save"]["bottom"], h, delta=1)

    def test_the_save_row_stays_on_the_screen_bottom_while_the_sheet_is_dragged(self):
        """411x908, a short list: the grabber held and pulled down 160px, then up 300px - the row is on the bottom edge at
        each point of the drag, and after the release."""
        page = self.view(phone(411, 908), prefs=SECTIONS_SHUT)
        self.compose(page)
        g = page.locator("#sheet-grip").bounding_box()
        x, y = g["x"] + g["width"] / 2, g["y"] + 6
        page.mouse.move(x, y)
        page.mouse.down()
        for to in (y + 160, y - 140):
            page.mouse.move(x, to, steps=6)
            settle(page)
            with self.subTest(at=round(to)):
                self.assertAlmostEqual(page.evaluate(FOOTERS)["save"]["bottom"], 908, delta=1)
        page.mouse.up()
        settle(page)
        self.assertAlmostEqual(page.evaluate(FOOTERS)["save"]["bottom"], 908, delta=1)

    def test_the_save_row_sits_on_the_keyboard(self):
        """411x908 with the note focused and the keyboard up (the layout shrinks by 330px, resizes-content): the row ends on
        the new bottom edge, the keyboard's top."""
        page = self.view(phone(411, 908), prefs=SECTIONS_SHUT)
        self.compose(page)
        page.focus("#note")
        page.set_viewport_size({"width": 411, "height": 908 - 330})
        settle(page)
        f = page.evaluate(FOOTERS)
        self.assertAlmostEqual(f["save"]["bottom"], 908 - 330, delta=1)

    def test_the_save_row_sits_on_a_keyboard_that_shrinks_only_the_visual_viewport(self):
        """411x908, the note focused, a browser that keeps the layout and shrinks only the visual viewport by 330px (iOS
        Safari, a Chrome without interactive-widget; stubbed): onViewport sets --kb to 330px and the row ends on the
        keyboard's top; the keyboard down, --kb is 0 and the row is back on the screen's bottom."""
        page = self.view(phone(411, 908), prefs=SECTIONS_SHUT, init=KB_VISUAL_ONLY)
        self.compose(page)
        page.focus("#note")
        for kb in (330, 0):
            with self.subTest(kb=kb):
                page.evaluate("n=>window.__setKb(n)", kb)
                settle(page)
                self.assertEqual(
                    page.evaluate("[innerHeight, document.documentElement.style.getPropertyValue('--kb')]"),
                    [908, "%dpx" % kb],
                )
                self.assertAlmostEqual(page.evaluate(FOOTERS)["save"]["bottom"], 908 - kb, delta=1)

    def test_the_edit_cards_row_is_the_bottom_row_and_the_list_scrolls_clear_of_it(self):
        """411x908 and 768x1024, no selection: the edit card's row ends on the screen's bottom edge, outside its card, and
        the list's end scrolls to above it."""
        for w, h in ((411, 908), (768, 1024)):
            with self.subTest(w=w):
                page = self.view(phone(w, h))
                self.edit_first(page)
                f = page.evaluate(FOOTERS)
                self.assertAlmostEqual(f["edit"]["bottom"], h, delta=1)
                page.evaluate("()=>{const r=document.querySelector('#right'); r.scrollTop=r.scrollHeight;}")
                settle(page)
                last = page.evaluate(
                    "(()=>{const s=[...document.querySelectorAll('#list .lsec:not([hidden]) .sec-head')];"
                    " return s[s.length-1].getBoundingClientRect().bottom;})()"
                )
                self.assertLessEqual(last, page.evaluate(FOOTERS)["edit"]["top"])

    def test_with_a_selection_open_too_the_edit_card_keeps_its_row(self):
        """One bottom row: while a selection is being composed, the save row is the bottom row and the open edit card's row
        stays inside its card."""
        page = self.view(phone(411, 908))
        self.edit_first(page)
        self.compose(page)
        f = page.evaluate(FOOTERS)
        self.assertAlmostEqual(f["save"]["bottom"], 908, delta=1)
        self.assertGreaterEqual(f["edit"]["top"], f["card"]["top"])
        self.assertLessEqual(f["edit"]["bottom"], f["card"]["bottom"])

    def test_in_mid_both_rows_are_the_panels_bottom_on_the_action_row(self):
        """1024x768 touch (the side panel): the save row under a short list and the edit card's row end on the action
        row's top edge, inside the panel's width."""
        page = self.view(touch_device(1024, 768), prefs=SECTIONS_SHUT)
        self.compose(page)
        f = page.evaluate(FOOTERS)
        self.assertAlmostEqual(f["save"]["bottom"], f["bar"]["top"], delta=1)
        page = self.view(touch_device(1024, 768))  # the open pins' section open: the card is in it
        self.edit_first(page)
        f = page.evaluate(FOOTERS)
        self.assertAlmostEqual(f["edit"]["bottom"], f["bar"]["top"], delta=1)
        self.assertAlmostEqual(f["edit"]["left"], f["sheet"]["left"], delta=1)
        self.assertAlmostEqual(f["edit"]["right"], f["sheet"]["right"], delta=1)

    def test_a_mouse_desktop_keeps_both_rows_where_they_were(self):
        """1400x850 mouse (wide, unchanged): the save row is the panel's bottom row and the edit card's row is inside its
        card."""
        page = self.view(DESK)
        self.mouse_pick(page)
        f = page.evaluate(FOOTERS)
        self.assertAlmostEqual(f["save"]["bottom"], f["sheet"]["bottom"], delta=1)
        page.evaluate("cancelSelection(true)")
        settle(page)
        self.edit_first(page)
        f = page.evaluate(FOOTERS)
        self.assertLessEqual(f["edit"]["bottom"], f["card"]["bottom"])
        self.assertGreaterEqual(f["edit"]["top"], f["card"]["top"])


class JsonPatched:
    """A Playwright route whose fulfil passes the JSON body the handler answered through fn (the rest passes through)."""

    def __init__(self, route, fn) -> None:
        """Wrap route; fn takes the answer's object and returns the one to send."""
        self._route, self._fn = route, fn

    def __getattr__(self, name: str):
        """Everything but fulfill is the route's own (the handler reads its request)."""
        return getattr(self._route, name)

    def fulfill(self, status: int, headers: dict[str, str], body: bytes | str) -> None:
        """Fulfil the route with fn applied to the handler's JSON answer."""
        self._route.fulfill(status=status, headers=headers, body=json.dumps(self._fn(json.loads(body))))


def one_rung_pick(d: dict[str, Any]) -> dict[str, Any]:
    """The pick answer for a one-line paragraph: the server merges the dragged line into the paragraph rung, so the
    ladder is that one rung (level para, merged raw) and the selection is its line."""
    raw = next(lv for lv in d["levels"] if lv["level"] == "raw")
    rung = dict(raw, level="para", label="문단", merged=["raw"])
    return dict(d, levels=[rung], default_level="para", lo=raw["lo"], hi=raw["hi"], kind="paragraph")


def one_rung_snippet(d: dict[str, Any]) -> dict[str, Any]:
    """The snippet answer of an edit card whose ladder is the pin's own lines only (as for a figure pin, P1b)."""
    return dict(d, levels=[lv for lv in d.get("levels", []) if lv["level"] == "raw"])


# The composer's and the edit card's range block as drawn: the caption's text and the copy text of its line range, whether
# the ladder shows, its accessible name and its segments' names, and the location line's page.
RANGE_BLOCK = """root => {const q = s => document.querySelector(root + ' ' + s), vis = e => !!e && e.getClientRects().length > 0;
  const lad = q('.seg[data-rungs]'), cap = q('.rg-cap'), copy = cap && cap.querySelector('[data-copy]');
  return {cap: cap && vis(cap) ? cap.innerText.replace(/\\s+/g, ' ').trim() : null, copy: copy ? copy.dataset.copy : null,
    ladder: vis(lad), name: lad && lad.getAttribute('aria-label'), rungs: lad ? [...lad.querySelectorAll('button')].map(b => b.innerText.replace(/\\s+/g, ' ').trim()) : [],
    page: (document.querySelector('#c-page') || {}).innerText};}"""


class RangeLadderAndCaption(ViewerBase):
    """The range ladder and its caption (docs/handbook/viewer.md §패널 정리 범위 사다리): the owner read the one-segment ladder
    '문단 · 1줄' as noise and '1쪽 · 줄 직접 지정' as nothing. The ladder shows only with two or more rungs, under its label
    '범위'; the caption under the label says the lines and their count, and with one rung what that rung is; a range set line
    by line is told by its lines - '줄 직접 지정' is gone."""

    ONE_RUNG = False

    def route(self, route):
        """With ONE_RUNG, the pick answers a one-line paragraph and an edit card's ladder is its own lines only."""
        u = urlparse(route.request.url)
        if self.ONE_RUNG and u.path == "/api/pick":
            return super().route(JsonPatched(route, one_rung_pick))
        if self.ONE_RUNG and u.path == "/api/snippet" and "levels=1" in u.query:
            return super().route(JsonPatched(route, one_rung_snippet))
        return super().route(route)

    def compose(self, page):
        """A touch selection through the real pick path; waits for the composer."""
        page.evaluate("()=>{LAST_PTR='touch'; pick({page:1,x0:10,y0:10,x1:200,y1:60});}")
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
        settle(page)

    def test_one_rung_hides_the_ladder_and_the_caption_names_the_rung(self):
        """411x908 touch and 1400x850 mouse: a one-line paragraph's single rung shows no segment control; the caption reads
        '범위 L5 · 1줄 · 문단' and the location line's page is just '1쪽'."""
        self.ONE_RUNG = True
        for device in (phone(411, 908), DESK):
            with self.subTest(width=device["viewport"]["width"]):
                page = self.view(device)
                self.compose(page)
                got = page.evaluate(RANGE_BLOCK, "#composer")
                self.assertEqual((got["cap"], got["ladder"], got["page"]), ("범위 L5 · 1줄 · 문단", False, "1쪽"))

    def test_a_range_set_line_by_line_is_told_by_its_lines(self):
        """One line added below the paragraph: the caption reads '범위 L5-L6 · 2줄' (no rung matches, so none is named), the
        page stays '1쪽', and '직접' is nowhere in the composer."""
        self.ONE_RUNG = True
        page = self.view(phone(411, 908))
        self.compose(page)
        page.evaluate("()=>{const o=COMPOSE.current; setLines(o,o.lo,o.hi+1); renderComposer();}")
        settle(page)
        got = page.evaluate(RANGE_BLOCK, "#composer")
        self.assertEqual((got["cap"], got["page"]), ("범위 L5-L6 · 2줄", "1쪽"))
        self.assertNotIn("직접", page.inner_text("#composer"))

    def test_two_rungs_show_the_ladder_named_range_and_the_caption_leaves_the_name_to_it(self):
        """The fixture's pick (dragged line L5, paragraph L1-L40): the ladder shows under the caption, named '범위', its
        segments '드래그한 줄 · 1줄' and '문단 · 40줄'; the caption does not repeat the pressed segment's name."""
        page = self.view(phone(411, 908))
        self.compose(page)
        got = page.evaluate(RANGE_BLOCK, "#composer")
        self.assertEqual((got["ladder"], got["name"]), (True, "범위"))
        self.assertEqual(got["rungs"], ["드래그한 줄 · 1줄", "문단 · 40줄"])
        self.assertRegex(got["cap"], r"^범위 L\d+(-L\d+)? · \d+줄$")
        lad, cap = (page.locator("#composer " + s).bounding_box() for s in (".seg[data-rungs]", ".rg-cap"))
        self.assertGreaterEqual(lad["y"], cap["y"] + cap["height"] - 1)

    def test_an_edit_card_with_one_rung_shows_its_caption_and_no_ladder(self):
        """An edit card whose ladder is the pin's own lines only: no segment control; the caption reads '범위 L4-L5 · 2줄'
        and its line range copies as 'main.tex L4-L5'. With the fixture's two rungs the ladder is back."""
        self.ONE_RUNG = True
        page = self.view(phone(411, 908))
        page.evaluate("()=>{setSide(true); openEdit(OPEN_ALL.find(p=>p.lo===4).id);}")
        page.wait_for_function("EDITOR.current&&EDITOR.current.levels.length>0")
        settle(page)
        got = page.evaluate(RANGE_BLOCK, ".edit")
        self.assertEqual((got["cap"], got["ladder"], got["copy"]), ("범위 L4-L5 · 2줄", False, "main.tex L4-L5"))
        # the copyable range keeps the caption one line of text (as a 44px box it spread the line apart) and answers 44px
        self.assertLessEqual(page.locator(".edit .e-cap").bounding_box()["height"], 24)
        self.assertEqual(page.evaluate(MISSES_44, ".edit .e-cap .loc"), [])
        self.ONE_RUNG = False
        page = self.view(phone(411, 908))
        page.evaluate("()=>{setSide(true); openEdit(OPEN_ALL.find(p=>p.lo===4).id);}")
        page.wait_for_function("EDITOR.current&&EDITOR.current.levels.length>0")
        settle(page)
        got = page.evaluate(RANGE_BLOCK, ".edit")
        self.assertEqual((got["ladder"], got["name"]), (True, "범위"))

    def test_the_caption_is_english_in_english(self):
        """The same one-rung pick in English: 'Range L5 · 1 line · Paragraph', page 'p. 1'."""
        self.ONE_RUNG = True
        page = self.view(phone(411, 908), lang="en")
        self.compose(page)
        got = page.evaluate(RANGE_BLOCK, "#composer")
        self.assertEqual((got["cap"], got["page"]), ("Range L5 · 1 line · Paragraph", "p. 1"))


# The phone composer's blocks as drawn, top to bottom: each visible flex item of #composer (and of the range block #c-range)
# with its top and bottom - a ladder's drawn track, not its scroll box (which keeps its hits' room) - so a test reads their
# order and the gaps between them.
COMPOSER_BLOCKS = """sel => [...document.querySelector(sel).children].flatMap(e => getComputedStyle(e).display === 'contents' ? [...e.children] : [e])
  .filter(e => e.getClientRects().length && getComputedStyle(e).position !== 'absolute')
  .map(e => {const r = (e.querySelector(':scope>.lad-t') || e).getBoundingClientRect(); return [e.id || e.className, r.top, r.bottom];})
  .sort((a, b) => a[1] - b[1])"""
# The pending box's badge: its box, the pending box's, the page's left edge, the badge's visible text and its spoken name.
PENDING_BADGE = """() => {const s = document.querySelector('.sel.pending'), i = s.querySelector('i'), R = e => e.getBoundingClientRect();
  return {badge: R(i), box: R(s), page: R(s.closest('.pg')), seen: i.innerText.trim(), name: s.textContent.trim()};}"""


class ComposerSamePass(ViewerBase):
    """The rest of the composer and edit card on a phone, in the same pass as the owner's four points (UX audit rules R1/R2,
    one 8px step): the '새 핀' tag covered the line above the box, the copy button was a 44px bordered box, the blocks sat
    0-20px apart, the kind control split the range controls from the source they change, and the composer was a grey card
    inside the white sheet (a box of its own in the tablet's 640px column)."""

    def compose(self, page):
        """A touch selection through the real pick path; waits for the composer."""
        page.evaluate("()=>{LAST_PTR='touch'; pick({page:1,x0:10,y0:10,x1:200,y1:60});}")
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
        settle(page)

    def test_the_phone_order_puts_the_kind_by_the_note_and_the_range_block_last(self):
        """411x908 with the overlap notice: location, note, kind, overlap, then the range block - caption, ladder, line
        buttons, source and its foot - so what changes the range sits with the source it changes."""
        page = self.view(phone(411, 908))
        self.compose(page)
        top = [b[0] for b in page.evaluate(COMPOSER_BLOCKS, "#composer")]
        self.assertEqual(top, ["c-loc-row", "note", "c-kind", "c-overlap", "c-range"], top)
        inner = [b[0] for b in page.evaluate(COMPOSER_BLOCKS, "#c-range")]
        self.assertEqual(inner, ["c-cap", "c-levels", "c-xp", "snip-foot"], inner)

    def test_tab_follows_the_screen_on_every_band(self):
        """The markup follows the order on screen, so Tab does (it went location, overlap, range, kind, note on the phone,
        whose screen shows the note second): on a 411x908 phone, with a mouse at 1000x800 (mid) and at 1440x900 (wide, the
        owner's pick 1b of the cross-resolution pass) the location, the note, the kind, the overlap notice and the range
        block. Each Tab lands on or below the one before. The markup is in that order on every band - nothing moves when the
        band changes - and a hidden #c-body (a failed pick) hides the range block after it too."""
        tab = """() => {const c = document.querySelector('#composer'), a = document.activeElement; if (!c.contains(a)) return null;
          const r = a.getBoundingClientRect();
          return [['.c-loc-row', '#c-kind', '#c-overlap', '#c-range'].find(s => a.closest(s)) || '#note', r.top + r.height / 2 - c.getBoundingClientRect().top];}"""
        phone_order = [".c-loc-row", "#note", "#c-kind", "#c-overlap", "#c-range"]
        for device, touch, order in (
            (phone(411, 908), True, phone_order),
            (MOUSE_MID, False, phone_order),
            (MOUSE_WIDE, False, phone_order),
        ):
            with self.subTest(w=device["viewport"]["width"]):
                page = self.view(device)
                if touch:
                    self.compose(page)
                else:
                    self.mouse_pick(page)
                page.focus("#c-loc")
                seen = [page.evaluate(tab)]
                for _ in range(40):
                    page.keyboard.press("Tab")
                    got = page.evaluate(tab)
                    if got is None:
                        break
                    seen.append(got)
                blocks = [b for i, (b, _) in enumerate(seen) if i == 0 or seen[i - 1][0] != b]
                self.assertEqual(blocks, [b for b in order if b in blocks], seen)
                self.assertTrue({".c-loc-row", "#note", "#c-kind", "#c-range"} <= set(blocks), seen)
                ys = [y for _, y in seen]
                self.assertTrue(all(b >= a - 4 for a, b in zip(ys, ys[1:], strict=False)), seen)
        page = self.view(phone(411, 908))
        self.compose(page)
        page.evaluate("document.querySelector('#c-body').hidden=true")
        self.assertFalse(page.evaluate("document.querySelector('#c-range').getClientRects().length>0"))
        page.evaluate("document.querySelector('#c-body').hidden=false")
        page.set_viewport_size({"width": 1440, "height": 900})
        page.wait_for_function("BAND==='wide'")  # a touch band settles after 200ms (settleBand)
        settle(page)
        self.assertEqual(
            page.evaluate(
                "[document.querySelector('#c-range').parentNode.id, document.querySelector('#note').previousElementSibling.id]"
            ),
            ["composer", "c-body"],
        )

    def test_the_phone_composers_blocks_are_one_8px_step_apart(self):
        """411x908 and 768x1024: every gap between the composer's blocks, and inside the range block, is 8px (the kind
        control sat flush on the source, the ladder 20px under the note)."""
        for w, h in ((411, 908), (768, 1024)):
            with self.subTest(w=w):
                page = self.view(phone(w, h))
                self.compose(page)
                for sel in ("#composer", "#c-range"):
                    b = page.evaluate(COMPOSER_BLOCKS, sel)
                    gaps = [round(n[1] - p[2]) for p, n in zip(b, b[1:], strict=False)]
                    self.assertEqual(set(gaps), {8}, (sel, list(zip([x[0] for x in b], gaps, strict=False))))

    def test_the_copy_button_is_a_borderless_icon_answering_44px(self):
        """411x908: [⧉] beside the location line was a 44px bordered box; it is a ghost icon drawn at 36px whose tap
        still answers a 44px box. The mouse desktop's is the same ghost, at its 28px (ComposerOneBorder)."""
        page = self.view(phone(411, 908))
        self.compose(page)
        got = page.evaluate(
            "(()=>{const b=document.querySelector('#c-copy'),cs=getComputedStyle(b),r=b.getBoundingClientRect();"
            " return [cs.borderTopColor, cs.backgroundColor, Math.round(r.width), Math.round(r.height)];})()"
        )
        self.assertEqual(got, ["rgba(0, 0, 0, 0)", "rgba(0, 0, 0, 0)", 36, 36])
        self.assertEqual(page.evaluate(MISSES_44, "#c-copy"), [])
        page = self.view(DESK)
        self.mouse_pick(page)
        self.assertEqual(
            page.evaluate("getComputedStyle(document.querySelector('#c-copy')).borderTopColor"), "rgba(0, 0, 0, 0)"
        )

    def test_the_new_pin_badge_sits_left_of_the_box_not_over_the_line_above(self):
        """411x908, a long press on the text: the pending box's badge is a 26px '+' outside its left edge at its top -
        where a saved mark's number goes - with no visible word, and is named '새 핀' for screen readers. The old tag sat
        21px above the box, over the line above it."""
        page = self.view(phone(411, 908))
        self.long_press_pick(self.cdp(page), page)
        got = page.evaluate(PENDING_BADGE)
        b, box = got["badge"], got["box"]
        self.assertLessEqual(b["right"], box["left"] + 0.5)
        self.assertGreaterEqual(b["top"], box["top"] - 2.5)
        self.assertEqual((round(b["width"]), round(b["height"]), got["seen"], got["name"]), (26, 26, "", "새 핀"))

    def test_the_new_pin_badge_goes_inside_a_box_at_the_page_edge(self):
        """A box starting at the page's left edge has no room for the badge outside (it would be cut at the PDF column):
        the badge is in the box's top-left corner, as a mark's is (markBadgeIn)."""
        page = self.view(phone(411, 908))
        p1 = page.locator("#p1").bounding_box()
        self.long_press_pick(self.cdp(page), page, p1["x"] + 4, p1["y"] + p1["height"] * 0.1)
        got = page.evaluate(PENDING_BADGE)
        self.assertGreaterEqual(got["badge"]["left"], got["box"]["left"] - 0.5)
        self.assertGreaterEqual(got["badge"]["left"], got["page"]["left"] - 0.5)

    def test_the_composer_is_on_the_sheet_not_a_grey_card(self):
        """411x908, 768x1024 and the 1400x850 mouse desktop: the composer has the panel's own background (it was --card, a
        grey box in the white sheet - in the tablet's 640px column a box of its own - and the desktop kept it until the
        cross-resolution pass gave every layout one composer)."""
        bg = "getComputedStyle(document.querySelector('#composer')).backgroundColor"
        for w, h in ((411, 908), (768, 1024)):
            with self.subTest(w=w):
                page = self.view(phone(w, h))
                self.compose(page)
                self.assertEqual(page.evaluate(bg), "rgba(0, 0, 0, 0)")
        page = self.view(DESK)
        self.mouse_pick(page)
        self.assertEqual(page.evaluate(bg), "rgba(0, 0, 0, 0)")


# Every visible segmented control under root, as drawn: its drawn track (a ladder's .lad-t, else the .seg itself), the track's
# height and radius, the selected thumb's insets from the track (top, bottom) and the end segments' (left, right), the thumb's
# radius, and its shadow's reach below it (y offset + blur, px).
SEGMENTS = """root => [...document.querySelectorAll(root + ' .seg')].filter(s => s.getClientRects().length).map(s => {
  const t = s.querySelector(':scope>.lad-t') || s, T = t.getBoundingClientRect(), bs = [...t.querySelectorAll(':scope>button')];
  const on = t.querySelector(':scope>button.on') || bs[0], O = on.getBoundingClientRect(), cs = getComputedStyle(on);
  const sh = cs.boxShadow === 'none' ? [0, 0] : cs.boxShadow.replace(/rgba?\\([^)]*\\)/, '').trim().split(/\\s+/).map(parseFloat).slice(1, 3);
  const r1 = v => Math.round(v * 10) / 10;
  return {id: s.id || s.className, h: r1(T.height), top: r1(O.top - T.top), bottom: r1(T.bottom - O.bottom),
    left: r1(bs[0].getBoundingClientRect().left - T.left), right: r1(T.right - bs[bs.length - 1].getBoundingClientRect().right),
    rTrack: parseFloat(getComputedStyle(t).borderTopLeftRadius), rThumb: parseFloat(cs.borderTopLeftRadius), reach: sh[0] + sh[1]};})"""
# The open [더보기]'s view group, drawn: each row's control (the zoom row's buttons, else its segment track) top and bottom.
MORE_ROWS = """() => [...document.querySelectorAll('#more .m-row .m-c, #more .m-row .seg')].filter(e => e.getClientRects().length)
  .map(e => {const r = (e.matches('.m-c') ? e.querySelector('button') : e).getBoundingClientRect(); return [r.top, r.bottom];})"""


class SegmentedControl(ViewerBase):
    """One segmented control (docs/handbook/viewer.md §컴포넌트): the owner saw [더보기]'s sheet-height, theme and language
    tracks touching each other (44px tracks in 44px rows) and the navigation sheet's [원고 | 변경사항] thumb running into its
    track's edge (the sheet's padding rule took the track's side inset). Every track - [더보기], the navigation sheet, the
    composer's and the edit card's kind and ladder - is drawn at 36px on touch, its thumb inset 4px all round with the radius
    the track's less that inset, its shadow inside the inset; rows of them stand 8px apart; every segment answers 44px."""

    def compose(self, page):
        """A touch selection through the real pick path; waits for the composer."""
        page.evaluate("()=>{LAST_PTR='touch'; pick({page:1,x0:10,y0:10,x1:200,y1:60});}")
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
        settle(page)

    def every_control(self, page):
        """[(where, SEGMENTS answer)] for the composer, the edit card, [더보기] and the navigation sheet, each opened in turn."""
        out = []
        self.compose(page)
        out.append(("composer", page.evaluate(SEGMENTS, "#composer")))
        page.evaluate("()=>{setSide(true); openEdit(OPEN_ALL[0].id);}")
        page.wait_for_function("EDITOR.current&&EDITOR.current.levels.length>0")
        settle(page)
        out.append(("edit", page.evaluate(SEGMENTS, ".edit")))
        page.evaluate("()=>{cancelEdit(); cancelSelection(true); openMore();}")
        settle(page)
        out.append(("more", page.evaluate(SEGMENTS, "#more")))
        page.evaluate("()=>{document.querySelector('#more').close(); openNavSheet();}")
        settle(page)
        out.append(("nav", page.evaluate(SEGMENTS, "#nav-sheet")))
        page.evaluate("document.querySelector('#nav-sheet').close()")
        return out

    def test_every_track_is_36px_with_its_thumb_inset_4px_and_the_radius_rule(self):
        """411x908: each control's track is 36px high, its thumb and end segments 4px in from every edge (the navigation
        sheet's [변경사항] touched the right edge), and the thumb's radius is the track's (10) less 4 (6)."""
        page = self.view(phone(411, 908))
        for where, segs in self.every_control(page):
            self.assertTrue(segs, where)
            for s in segs:
                with self.subTest(where=where, seg=s["id"]):
                    got = [s["h"], s["top"], s["bottom"], s["left"], s["right"], s["rTrack"] - s["rThumb"]]
                    self.assertEqual(got, [36, 4, 4, 4, 4, 4], s)

    def test_more_rows_stand_8px_apart(self):
        """411x908 [더보기]: the zoom buttons and the sheet-height, theme and language tracks have 8px between each other
        (the tracks touched: 0px)."""
        page = self.view(phone(411, 908))
        page.evaluate("openMore()")
        settle(page)
        rows = page.evaluate(MORE_ROWS)
        self.assertEqual(len(rows), 4)
        self.assertEqual([round(b[0] - a[1], 1) for a, b in zip(rows, rows[1:], strict=False)], [8, 8, 8])

    def test_every_segment_answers_44px(self):
        """411x908: drawn at 28px, every segment of every control still answers a 44px tap."""
        page = self.view(phone(411, 908))
        self.compose(page)
        self.assertEqual(page.evaluate(MISSES_44, "#composer .seg button"), [])
        page.evaluate("openMore()")
        settle(page)
        self.assertEqual(page.evaluate(MISSES_44, "#more .seg button"), [])
        page.evaluate("()=>{document.querySelector('#more').close(); openNavSheet();}")
        settle(page)
        self.assertEqual(page.evaluate(MISSES_44, "#nav-sheet .seg button"), [])

    def test_the_thumb_shadow_stays_inside_the_inset_in_both_themes(self):
        """Light and dark: the selected thumb's shadow reaches at most 4px below it (it reached 5px, past the inset, where
        the track's edge clipped it)."""
        for dark in (False, True):
            with self.subTest(dark=dark):
                page = self.view(phone(411, 908), dark=dark)
                page.evaluate("openMore()")
                settle(page)
                for s in page.evaluate(SEGMENTS, "#more"):
                    self.assertLessEqual(s["reach"], 4, s)


# The open [더보기]'s foot, for an ink measure: the clip round the foot (CSS px) and, inside it, the boxes of the wordmark,
# the version, [도움말]'s text and its chevron, each with its ink colour's luminance, and the sheet's - plus the wordmark's height.
FOOT_BOXES = """() => {const f = document.querySelector('#more-foot'), F = f.getBoundingClientRect(), clip = {x: 0, y: F.top - 8, width: innerWidth, height: F.height + 16};
  const lum = c => {const m = c.match(/[\\d.]+/g).map(Number); return 0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2];};
  const box = (r, color, pad) => [r.left - clip.x, r.top - clip.y - pad, r.right - clip.x, r.bottom - clip.y + pad, lum(color)];
  const h = f.querySelector('[data-act=help]'), t = [...h.childNodes].find(n => n.nodeType === 3 && n.nodeValue.trim()), rg = document.createRange();
  rg.selectNodeContents(t); const w = f.querySelector('svg.limn-mark-word'), v = f.querySelector('.m-ver'), ch = h.querySelector('svg');
  return {clip, bg: lum(getComputedStyle(document.querySelector('#more')).backgroundColor), height: w.getBoundingClientRect().height,
    boxes: {word: box(w.getBoundingClientRect(), getComputedStyle(w.querySelector('.limn-mark-stroke')).fill, 2),
      version: box(v.getBoundingClientRect(), getComputedStyle(v).color, 4), help: box(rg.getBoundingClientRect(), getComputedStyle(h).color, 4),
      chevron: box(ch.getBoundingClientRect(), getComputedStyle(h).color, 2)}};}"""
# Reads the ink of each box from a screenshot (base64 PNG at the device pixel ratio): per pixel row the strongest coverage
# (luminance against the sheet's, over the ink colour's), and the ink's top and bottom edges in CSS px, the partial edge rows
# counted by their coverage.
INK = """async ([b64, dpr, boxes, bg]) => {const img = new Image(); img.src = 'data:image/png;base64,' + b64; await img.decode();
  const c = document.createElement('canvas'); c.width = img.width; c.height = img.height; const x = c.getContext('2d'); x.drawImage(img, 0, 0);
  const D = x.getImageData(0, 0, c.width, c.height).data, W = c.width, out = {};
  for (const [k, b] of Object.entries(boxes)) {const X0 = Math.max(0, Math.floor(b[0] * dpr)), X1 = Math.min(W, Math.ceil(b[2] * dpr));
    const Y0 = Math.max(0, Math.floor(b[1] * dpr)), Y1 = Math.min(c.height, Math.ceil(b[3] * dpr)), cov = [];
    for (let y = Y0; y < Y1; y++) {let m = 0; for (let xx = X0; xx < X1; xx++) {const i = (y * W + xx) * 4;
        const l = 0.2126 * D[i] + 0.7152 * D[i + 1] + 0.0722 * D[i + 2]; m = Math.max(m, Math.abs(l - bg) / Math.abs(b[4] - bg));} cov.push(Math.min(1, m));}
    let first = -1, last = -1; cov.forEach((v, i) => {if (v > 0.05) {if (first < 0) first = i; last = i;}});
    out[k] = {top: (Y0 + first + 1 - cov[first]) / dpr, bottom: (Y0 + last + cov[last]) / dpr};}
  return out;}"""


class MoreFoot(ViewerBase):
    """[더보기]'s foot (docs/handbook/viewer.md §모바일 레이아웃): the owner found the version beside the 20px wordmark neither
    bottom- nor centre-aligned and the wordmark large, then asked for the wordmark at 16px and the logo and version aligned to
    the bottom of [도움말]. On one baseline the Hangul label reads lower - its glyphs reach below the Latin baseline - so the
    three are aligned by their ink: the wordmark and the version drop by the label's ink descent (footInk), and the chevron
    sits on the label's ink centre."""

    def ink(self, page, dpr):
        """The foot's measured ink edges (CSS px): open [더보기], screenshot the foot, read each box's ink."""
        page.evaluate("openMore()")
        settle(page)
        f = page.evaluate(FOOT_BOXES)
        b64 = base64.b64encode(page.screenshot(clip=f["clip"])).decode()
        return f, page.evaluate(INK, [b64, dpr, f["boxes"], f["bg"]])

    def test_the_wordmark_the_version_and_help_end_on_one_ink_line(self):
        """411x908 at DPR 2.625 and 1, light and dark: the ink bottoms of the wordmark, the version and [도움말] are within
        0.5px of each other (on one baseline the label's ink sat about 1px lower)."""
        for dpr in (2.625, 1):
            for dark in (False, True):
                with self.subTest(dpr=dpr, dark=dark):
                    page = self.view(phone(411, 908, dpr), dark=dark)
                    _, ink = self.ink(page, dpr)
                    bottoms = [ink[k]["bottom"] for k in ("word", "version", "help")]
                    self.assertLessEqual(max(bottoms) - min(bottoms), 0.5, ink)

    def test_the_chevron_sits_on_the_labels_ink_centre(self):
        """411x908 at DPR 2.625, light and dark: the chevron's ink centre is within 0.5px of [도움말]'s."""
        for dark in (False, True):
            with self.subTest(dark=dark):
                page = self.view(phone(411, 908), dark=dark)
                _, ink = self.ink(page, 2.625)
                mid = {k: (ink[k]["top"] + ink[k]["bottom"]) / 2 for k in ("help", "chevron")}
                self.assertLessEqual(abs(mid["help"] - mid["chevron"]), 0.5, ink)

    def test_the_wordmark_is_the_foot_word_token_tall_and_english_does_not_drop(self):
        """The wordmark is --foot-word (16px) tall on touch and with a mouse; in English 'Help' has no descent, so the
        wordmark stays on the baseline (no drop)."""
        for device in (phone(411, 908), MOUSE_MID):
            with self.subTest(width=device["viewport"]["width"]):
                page = self.view(device)
                page.evaluate("openMore()")
                settle(page)
                self.assertEqual(page.evaluate(FOOT_BOXES)["height"], 16)
        page = self.view(phone(411, 908), lang="en")
        page.evaluate("openMore()")
        settle(page)
        self.assertAlmostEqual(
            page.evaluate("parseFloat(document.querySelector('#more-foot').style.getPropertyValue('--ink-word'))"),
            0,
            delta=0.3,
        )


class RangeExcerptLogic(unittest.TestCase):
    """The range excerpt's pure decisions (docs/handbook/viewer.md §패널 정리 범위 발췌), run from the served source under node:
    widening to a tapped line, dropping an end line, and which rows the excerpt draws round a range."""

    def run_js(self, expr):
        """expr evaluated with widenTo, dropLine and excerptRows from the page; its JSON value."""
        js = "\n".join(extract_js_fn(n) for n in ("widenTo", "dropLine", "excerptRows"))
        return node_or_skip(self, js + "\nconsole.log(JSON.stringify(%s));" % expr)

    def test_a_tapped_line_widens_the_range_to_it_on_either_side(self):
        """L5 widened to L4 is L4-L5, to L6 is L5-L6; a line inside the range leaves it as it is."""
        self.assertEqual(self.run_js("[widenTo(5,5,4),widenTo(5,5,6),widenTo(4,9,6)]"), [[4, 5], [5, 6], [4, 9]])

    def test_a_dropped_end_line_narrows_the_range_and_one_line_cannot_be_dropped(self):
        """L4-L5 less L4 is L5, less L5 is L4; a one-line range and a line that is not an end give null (nothing to do)."""
        self.assertEqual(
            self.run_js("[dropLine(4,5,4),dropLine(4,5,5),dropLine(5,5,5),dropLine(4,9,6)]"),
            [[5, 5], [4, 4], None, None],
        )

    def test_the_rows_are_a_dimmed_neighbour_each_side_and_none_past_the_file(self):
        """L5 in a 40-line file: a dimmed L4, L5 (both ends), a dimmed L6. L1-L2: no line above line 1. L39-L40: none
        below the last line. L1-L40 folds its middle (first two, '36 more', last two) unless opened."""
        got = self.run_js(
            "[excerptRows(5,5,40,false),excerptRows(1,2,40,false),excerptRows(39,40,40,false),"
            "excerptRows(1,40,40,false).map(r=>r.kind==='fold'?'fold'+r.n:r.k),excerptRows(1,40,40,true).length]"
        )
        self.assertEqual(
            got[0],
            [
                {"k": 4, "kind": "ctx", "edge": False},
                {"k": 5, "kind": "on", "edge": False},
                {"k": 6, "kind": "ctx", "edge": False},
            ],
        )
        self.assertEqual(
            [(r["k"], r["kind"], r["edge"]) for r in got[1]], [(1, "on", True), (2, "on", True), (3, "ctx", False)]
        )
        self.assertEqual(
            [(r["k"], r["kind"], r["edge"]) for r in got[2]], [(38, "ctx", False), (39, "on", True), (40, "on", True)]
        )
        self.assertEqual(got[3], [1, 2, "fold36", 39, 40])
        self.assertEqual(got[4], 40)


# The composer's or edit card's excerpt as drawn: its rows' line numbers and kinds ('ctx', 'on', 'fold'), which rows carry '−',
# the caption, and whether the stepper and the plain source show.
EXCERPT = """root => {const q = s => document.querySelector(root + ' ' + s), vis = e => !!e && e.getClientRects().length > 0;
  const rows = [...document.querySelectorAll(root + ' .xp-list > *')].filter(vis)
    .map(r => r.classList.contains('xp-fold') ? 'fold' : (r.classList.contains('ctx') ? '(' + r.dataset.line + ')' : r.dataset.line));
  return {rows, drops: [...document.querySelectorAll(root + ' .xp-drop')].filter(vis).map(b => +b.dataset.line),
    cap: (q('.rg-cap') || {}).innerText, step: vis(q('.step')), pre: vis(q('pre'))};}"""


class RangeExcerpt(ViewerBase):
    """The range excerpt on the compact bands (docs/handbook/viewer.md §패널 정리 범위 발췌): the owner read '위 + − 아래 + −' as
    moving the pin. The source itself adjusts the range - a tap on a dimmed line above or below widens the range to it, the
    '−' on the band's first or last line drops that line - in the composer and the edit card alike; the band never jumps
    under the finger. The mouse desktop sets its range the same way (the owner's pick 1b): the stepper is gone."""

    def compose(self, page):
        """A touch selection through the real pick path (the paragraph L1-L40 of the fixture); waits for the composer."""
        page.evaluate("()=>{LAST_PTR='touch'; pick({page:1,x0:10,y0:10,x1:200,y1:60});}")
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
        settle(page)

    def tap_row(self, page, sel):
        """A finger tap on the centre of sel's first match, the row scrolled into view first."""
        page.evaluate("s=>document.querySelector(s).scrollIntoView({block:'center'})", sel)
        settle(page)
        self.tap(self.cdp(page), *self.center(page, sel))
        settle(page)

    def test_a_tap_on_a_dimmed_line_widens_the_range_and_minus_narrows_it(self):
        """411x908, the dragged line L5: dimmed L4 and L6 round it, no stepper, no plain source. A tap on L4 makes L4-L5 with
        '−' on both ends; '−' on L4 makes L5 again; a tap on L6 makes L5-L6."""
        page = self.view(phone(411, 908))
        self.compose(page)
        page.click('#c-levels [data-level="raw"]')
        settle(page)
        got = page.evaluate(EXCERPT, "#composer")
        self.assertEqual((got["rows"], got["drops"], got["step"], got["pre"]), (["(4)", "5", "(6)"], [], False, False))
        self.tap_row(page, '#c-xp .xp-row.ctx[data-line="4"]')
        got = page.evaluate(EXCERPT, "#composer")
        self.assertEqual(
            (got["rows"], got["drops"], got["cap"]), (["(3)", "4", "5", "(6)"], [4, 5], "범위 L4-L5 · 2줄")
        )
        self.tap_row(page, '#c-xp .xp-drop[data-line="4"]')
        self.assertEqual(page.evaluate("[COMPOSE.current.lo,COMPOSE.current.hi]"), [5, 5])
        self.tap_row(page, '#c-xp .xp-row.ctx[data-line="6"]')
        self.assertEqual(
            page.evaluate("[COMPOSE.current.lo,COMPOSE.current.hi,COMPOSE.current.scope]"), [5, 6, "lines"]
        )

    def test_line_one_and_the_last_line_have_no_dimmed_neighbour(self):
        """The paragraph L1-L40 is the whole 40-line file: no dimmed line above line 1 or below line 40, its middle folded;
        '−' on L1 makes L2-L40 and a dimmed L1 comes back above it."""
        page = self.view(phone(411, 908))
        self.compose(page)
        page.click('#c-levels [data-level="para"]')
        settle(page)
        got = page.evaluate(EXCERPT, "#composer")
        self.assertEqual((got["rows"], got["drops"]), (["1", "2", "fold", "39", "40"], [1, 40]))
        self.tap_row(page, '#c-xp .xp-drop[data-line="1"]')
        got = page.evaluate(EXCERPT, "#composer")
        self.assertEqual(got["rows"][:2], ["(1)", "2"])
        self.assertEqual(page.evaluate("[COMPOSE.current.lo,COMPOSE.current.hi]"), [2, 40])

    def test_widening_above_keeps_the_band_where_it_was(self):
        """A tap on the dimmed line above adds a row above the band: L5's row stays at the same height on screen (within 1px)
        - the sheet scrolls by the row that came - so the band does not jump under the finger."""
        page = self.view(phone(411, 908))
        self.compose(page)
        page.click('#c-levels [data-level="raw"]')
        settle(page)
        page.evaluate("document.querySelector('#c-xp .xp-row[data-line=\"5\"]').scrollIntoView({block:'center'})")
        settle(page)
        y0 = page.evaluate("document.querySelector('#c-xp .xp-row[data-line=\"5\"]').getBoundingClientRect().top")
        self.tap(self.cdp(page), *self.center(page, '#c-xp .xp-row.ctx[data-line="4"]'))
        settle(page)
        y1 = page.evaluate("document.querySelector('#c-xp .xp-row[data-line=\"5\"]').getBoundingClientRect().top")
        self.assertEqual(page.evaluate("[COMPOSE.current.lo,COMPOSE.current.hi]"), [4, 5])
        self.assertLessEqual(abs(y1 - y0), 1)

    def test_its_rows_and_minus_answer_44px(self):
        """411x908, L4-L5: the dimmed rows and the two '−' answer a 44px tap."""
        page = self.view(phone(411, 908))
        self.compose(page)
        page.click('#c-levels [data-level="raw"]')
        settle(page)
        self.tap_row(page, '#c-xp .xp-row.ctx[data-line="4"]')
        self.assertEqual(page.evaluate(MISSES_44, "#c-xp .xp-row.ctx,#c-xp .xp-drop"), [])

    def test_the_edit_card_takes_the_same_excerpt_and_saves_its_lines(self):
        """411x908, the pin at L4-L5: its edit card shows dimmed L3 and L6; a tap on L6 and [저장] store L4-L6 (scope
        'lines')."""
        page = self.view(phone(411, 908))
        pid = page.evaluate("OPEN_ALL.find(p=>p.lo===4).id")
        page.evaluate("id=>{setSide(true); openEdit(id);}", pid)
        page.wait_for_function("EDITOR.current&&EDITOR.current.levels.length>0")
        page.evaluate("document.activeElement.blur()")
        settle(page)
        self.assertEqual(page.evaluate(EXCERPT, ".edit")["rows"], ["(3)", "4", "5", "(6)"])
        self.tap_row(page, '.edit .xp-row.ctx[data-line="6"]')
        page.evaluate("document.querySelector('.edit .b-esave').click()")
        page.wait_for_function("EDITOR.current===null")
        settle(page)
        self.assertEqual(
            page.evaluate("id=>{const p=OPEN_ALL.find(x=>x.id===id); return [p.lo,p.hi,p.scope];}", pid),
            [4, 6, "lines"],
        )

    def test_every_layout_sets_the_range_in_the_source_and_no_stepper_is_left(self):
        """1400x850 with a mouse (wide) kept '위 + − 아래 + −' and its plain source; it draws the excerpt like 1000x800 (mid),
        in the composer and the edit card, and no page holds a stepper any more."""
        for device in (DESK, MOUSE_MID):
            with self.subTest(width=device["viewport"]["width"]):
                page = self.view(device)
                self.mouse_pick(page)
                got = page.evaluate(EXCERPT, "#composer")
                self.assertEqual((bool(got["rows"]), got["step"], got["pre"]), (True, False, False))
                page.evaluate("()=>{cancelSelection(true); setSide(true); openEdit(OPEN_ALL[0].id);}")
                page.wait_for_function("EDITOR.current&&EDITOR.current.levels.length>0")
                settle(page)
                got = page.evaluate(EXCERPT, ".edit")
                self.assertEqual((bool(got["rows"]), got["step"], got["pre"]), (True, False, False))
                self.assertEqual(page.evaluate("document.querySelectorAll('.step,[data-act=nudge]').length"), 0)

    def test_a_mouse_and_a_keyboard_set_the_wide_range_in_the_source(self):
        """1400x850 from the dragged line L5: a click on dimmed L4 widens to L4-L5 and the polite caption says so; Enter on
        the dimmed line now above (L3) widens again with the focus kept on the next dimmed line (L2); a click on '−' of L3
        narrows back to L4-L5."""
        page = self.view(DESK)
        self.mouse_pick(page)
        page.click('#c-levels [data-level="raw"]')
        settle(page)
        lo = page.evaluate("COMPOSE.current.lo")
        page.click('#c-xp .xp-row.ctx[data-line="%d"]' % (lo - 1))
        settle(page)
        self.assertEqual(page.evaluate("[COMPOSE.current.lo,COMPOSE.current.hi]"), [lo - 1, lo])
        self.assertEqual(
            page.evaluate("document.querySelector('#c-cap').innerText"), "범위 L%d-L%d · 2줄" % (lo - 1, lo)
        )
        page.focus('#c-xp .xp-row.ctx[data-line="%d"]' % (lo - 2))
        page.keyboard.press("Enter")
        settle(page)
        self.assertEqual(page.evaluate("[COMPOSE.current.lo,COMPOSE.current.hi]"), [lo - 2, lo])
        self.assertEqual(
            page.evaluate("[document.activeElement.dataset.act,+document.activeElement.dataset.line]"),
            ["xp-to", lo - 3],
        )
        page.click('#c-xp .xp-drop[data-line="%d"]' % (lo - 2))
        settle(page)
        self.assertEqual(page.evaluate("[COMPOSE.current.lo,COMPOSE.current.hi]"), [lo - 1, lo])

    def test_a_keyboard_keeps_its_place_and_hears_the_new_range(self):
        """411x908 from L5 with a keyboard: the redraw used to drop the focus to the page after every press. Two Enters on
        dimmed L4 widen the range twice (L3-L5), the focus each time on the dimmed line now above, in view; two Enters on the
        first line's '−' narrow it twice, the focus on the band's new first '−' and then, the band one line with no '−', on
        the dimmed line where it was. The caption above is a polite live region that names the range."""
        page = self.view(phone(411, 908))
        self.compose(page)
        page.click('#c-levels [data-level="raw"]')
        settle(page)
        self.assertEqual(
            page.evaluate("['aria-live','aria-atomic'].map(a=>document.querySelector('#c-cap').getAttribute(a))"),
            ["polite", "true"],
        )
        focus = "(()=>{const a=document.activeElement,r=a.getBoundingClientRect(); return [a.dataset.act||a.id,+a.dataset.line,r.top>=0&&r.bottom<=innerHeight];})()"
        page.focus('#c-xp .xp-row.ctx[data-line="4"]')
        for lo, at in ((4, ["xp-to", 3, True]), (3, ["xp-to", 2, True])):
            page.keyboard.press("Enter")
            settle(page)
            self.assertEqual(page.evaluate("[COMPOSE.current.lo,COMPOSE.current.hi]"), [lo, 5])
            self.assertEqual(page.evaluate(focus), at)
        self.assertEqual(page.evaluate("document.querySelector('#c-cap').innerText"), "범위 L3-L5 · 3줄")
        page.focus('#c-xp .xp-drop[data-line="3"]')
        for lo, at in ((4, ["xp-drop", 4, True]), (5, ["xp-to", 4, True])):
            page.keyboard.press("Enter")
            settle(page)
            self.assertEqual(page.evaluate("[COMPOSE.current.lo,COMPOSE.current.hi]"), [lo, 5])
            self.assertEqual(page.evaluate(focus), at)

    def test_the_hint_breaks_between_words_and_names_minus_only_when_there_is_one(self):
        """360x800: a one-line band has no '−', so its hint is only the widening half; with two lines it names '−' too, and
        it wraps between words - its last line holds a word, not one syllable left over."""
        page = self.view(phone(360, 800, 3))
        self.compose(page)
        page.click('#c-levels [data-level="raw"]')
        settle(page)
        self.assertEqual(
            page.evaluate("document.querySelector('#c-xp .xp-hint').innerText"), "흐린 줄을 누르면 그 줄까지 넓어집니다"
        )
        self.tap_row(page, '#c-xp .xp-row.ctx[data-line="4"]')
        got = page.evaluate(
            """() => {const h = document.querySelector('#c-xp .xp-hint'), r = document.createRange(); r.selectNodeContents(h);
              const lines = new Map(); for (const b of r.getClientRects()) {const k = Math.round(b.top); lines.set(k, (lines.get(k) || 0) + b.width);}
              return {text: h.innerText, last: [...lines.values()].pop(), em: parseFloat(getComputedStyle(h).fontSize)};}"""
        )
        self.assertIn("−", got["text"])
        self.assertGreater(got["last"], 1.5 * got["em"], got)


# The phone sheet's tool row as drawn: the row's insets from the sheet's top edge (inside its 1px border), the grabber's,
# the controls' height and the gaps in each cell, the grabber's centre against the bar's, the first and last boxes'
# distance from the bar's edges, and how far the select icon's and the chevron's centres sit from the counts' cap centre.
CHIP_ROW = """() => {const q = s => document.querySelector(s), R = e => e.getBoundingClientRect(), vis = e => !!e && e.getClientRects().length > 0;
  const r2 = v => Math.round(v * 100) / 100, cy = e => {const r = R(e); return r.top + r.height / 2;};
  const bar = q('#bar1'), B = R(bar), grip = q('#sheet-grip'), g = R(grip), gTop = g.top + parseFloat(getComputedStyle(grip).paddingTop);
  const items = [...bar.querySelectorAll(':scope>.bar-l>*,:scope>.bar-r>*')].filter(vis), I = items.map(R);
  const top = Math.min(...I.map(b => b.top)), bottom = Math.max(...I.map(b => b.bottom)), gaps = [];
  for (const cell of bar.querySelectorAll(':scope>.bar-l,:scope>.bar-r')) {const k = [...cell.children].filter(vis).map(R);
    for (let i = 1; i < k.length; i++) gaps.push(r2(k[i].left - k[i - 1].right));}
  const n = cy(q('#side-n')), pos = vis(q('#btn-pos'));
  return {insetTop: r2(top - B.top), insetBottom: r2(B.bottom - bottom), height: r2(bottom - top), grabber: [r2(gTop - B.top), r2(top - gTop - 4)],
    centre: r2(g.left + g.width / 2 - (B.left + B.width / 2)), gaps, edges: [r2(I[0].left - B.left), r2(B.right - I[I.length - 1].right)],
    off: [r2(cy(q('#btn-select svg')) - n), r2(cy(q('#btn-rv .rv-c')) - n)].concat(pos ? [r2(cy(q('#btn-pos svg')) - n), r2(cy(q('#btn-pos b')) - n)] : []),
    words: [q('#btn-side').innerText.replace(/\\s+/g, ' ').trim(), q('#btn-rv').innerText.replace(/\\s+/g, ' ').trim()]};}"""


class BarChip(ViewerBase):
    """The phone and tablet sheet's tool row (docs/handbook/viewer.md §모바일 레이아웃, the owner's pick E2): the pin glyph sat
    lopsided on its count and the row's fills touched the sheet's edge. The row is words first - one split chip [핀 5 | 검토
    1], whose right half goes to the review list - with the select icon on the same 28px fill, the controls 12px under the
    sheet's edge with the grabber in that inset, every icon and count on one centre line."""

    def test_the_pins_half_opens_the_sheet_and_the_review_half_goes_to_the_review_list(self):
        """411x908: a tap on [핀 3] opens the sheet and another closes it; a tap on [검토 1] opens it at the review section."""
        page = self.view(phone(411, 908))
        cdp = self.cdp(page)
        self.tap(cdp, *self.center(page, "#btn-side"))
        page.wait_for_function("SIDE_OPEN")
        self.before_next_tap(page)
        self.tap(cdp, *self.center(page, "#btn-side"))
        page.wait_for_function("!SIDE_OPEN")
        settle(page)
        self.before_next_tap(page)
        self.tap(cdp, *self.center(page, "#btn-rv"))
        page.wait_for_function("SIDE_OPEN")
        settle(page)
        top, sheet = page.evaluate(
            "[document.querySelector('#sec-review').getBoundingClientRect().top, document.querySelector('#right').getBoundingClientRect()]"
        )
        self.assertGreaterEqual(top, sheet["top"])
        self.assertLess(top, sheet["bottom"] - 44)

    def test_the_halves_select_page_and_more_answer_44px(self):
        """411x908 and 360x800: each control of the row answers a 44px tap."""
        for device in (phone(411, 908), phone(360, 800, 3)):
            with self.subTest(width=device["viewport"]["width"]):
                page = self.view(device)
                self.assertEqual(page.evaluate(MISSES_44, "#btn-side,#btn-rv,#btn-select,#btn-pos,#btn-more"), [])

    def test_the_row_has_12px_over_and_under_its_controls_and_every_centre_on_one_line(self):
        """411x908 (phone, edges 12) and 768x1024 (tablet sheet, 16), light and dark: the controls are 28px high, 12px under
        the sheet's edge and 12px above the row's end (4px before the cross-resolution pass); the grabber 4px from the edge and 4px from the controls, on the centre
        within 1px; gaps 8px (the chip's halves meet); the select icon, the review count and (the phone's) chevron and page
        figures within 0.5px of the open count's cap-height centre; the words '핀 3' and '검토 1'."""
        for (w, h), edge in (((411, 908), 12), ((768, 1024), 16)):
            for dark in (False, True):
                with self.subTest(w=w, dark=dark):
                    page = self.view(phone(w, h), dark=dark)
                    page.evaluate("setSide(true)")
                    settle(page)
                    got = page.evaluate(CHIP_ROW)
                    self.assertEqual(
                        (got["insetTop"], got["insetBottom"], got["height"], got["grabber"]), (12, 12, 28, [4, 4]), got
                    )
                    self.assertLessEqual(abs(got["centre"]), 1)
                    self.assertEqual(got["gaps"][0], 0)
                    self.assertEqual(set(got["gaps"][1:]), {8})
                    self.assertEqual(got["edges"], [edge, edge])
                    self.assertTrue(all(abs(o) <= 0.5 for o in got["off"]), got["off"])
                    self.assertEqual(got["words"], ["핀 3", "검토 1"])

    def test_each_half_always_says_what_it_counts_and_nothing_spills(self):
        """344, 360, 411 and 430 wide, Korean and English, the fixture's counts and the fullest (123 | 12): each half shows
        its word or its dot - never a bare count (English at 411 read '3 | 1') - every control stays inside its cell and
        answers 44px. The cell steps down only as far as it must: Korean keeps its words from 360 (snug on the 344 cover),
        English keeps them at 411 and 430 (snug) and takes the dots at 360 and 344; a dot is green for the pins, purple for
        the review, centred on its count."""
        want = {(344, "ko"): "bar-snug", (360, "ko"): "", (411, "ko"): "", (430, "ko"): "", (344, "en"): "bar-tight",
                (360, "en"): "bar-tight", (411, "en"): "bar-snug", (430, "en"): "bar-snug"}  # fmt: skip
        for w, h in ((344, 882), (360, 800), (411, 908), (430, 932)):
            for lang in ("ko", "en"):
                page = self.view(phone(w, h, 3), lang=lang)
                for full in (False, True):
                    with self.subTest(w=w, lang=lang, full=full):
                        if full:
                            page.evaluate(FULL_BAR)
                            settle(page)
                        got = page.evaluate(BAR_IDS)
                        if not full:
                            self.assertEqual(got["step"], want[(w, lang)])
                        self.assertEqual(
                            got["ids"], [["word"], ["word"]] if got["step"] != "bar-tight" else [["dot"], ["dot"]]
                        )
                        if got["step"] == "bar-tight":
                            self.assertEqual(got["dots"], got["want"])
                            self.assertTrue(all(abs(o) <= 0.5 for o in got["off"]), got["off"])
                        self.assertEqual(page.evaluate(BAR)["spill"], [])
                        self.assertEqual(page.evaluate(MISSES_44, "#bar1 button,#sheet-grip"), [])

    def test_each_half_answers_44px_whatever_the_fonts_draw(self):
        """CI's fonts drew [핀 3] at its 44px floor and [검토 1] 55.8px wide, and [핀 3] answered 43px: the review half's hit,
        centred by translating half its fractional width, was rounded out a pixel into the pins half. Independent of the
        fonts: with the pins half at its floor and the review half every fractional width from 44 to 46px, each half, [⬚],
        the page and [⋯] answer 44px in every step - words, snug, dots - at 344, 360, 411 and 430, Korean and English;
        and the halves' hits are their own boxes, set by their edges (no horizontal translate), the pins half's reaching
        4px outwards."""
        base = "#bar1 :is(.side-l,.side-n,.rv-c){font-size:4px!important} #bar1 #btn-rv{min-width:var(--rvw)!important}"
        for w, h in ((344, 882), (360, 800), (411, 908), (430, 932)):
            for lang in ("ko", "en"):
                page = self.view(phone(w, h, 3), lang=lang)
                page.add_style_tag(content=base)
                for step in ("", "bar-snug", "bar-snug bar-tight"):
                    with self.subTest(w=w, lang=lang, step=step):
                        page.evaluate(
                            "s=>{const b=document.querySelector('#bar1'); b.classList.remove('bar-snug','bar-tight');"
                            " if(s)b.classList.add(...s.split(' '));}",
                            step,
                        )
                        for rvw in (44, 44.2, 44.5, 44.8, 45.3, 45.8):
                            page.evaluate("v=>document.documentElement.style.setProperty('--rvw',v+'px')", rvw)
                            settle(page)
                            self.assertEqual(page.evaluate(HALF_HITS)["side"], 44)
                            self.assertEqual(
                                page.evaluate(MISSES_44, "#btn-side,#btn-rv,#btn-select,#btn-pos,#btn-more"), [], rvw
                            )
                        self.assertEqual(page.evaluate(HALF_HITS)["after"], [[-4, 0], [0, 0]])

    def test_each_half_is_named_by_what_it_shows_first(self):
        """411x908: [검토 1]'s name starts with its words ('검토 1 · 검토 대기 핀으로 가기', 'Review 1 · …'), and [핀 3]'s starts with
        its own and leaves the review count to the other half, in the mid bar too (the same chip there since 2b of the
        cross-resolution pass). A keyboard's ring on [핀 3] is drawn over the review half that meets it."""
        for lang, side, rv in (("ko", "핀 3 · ", "검토 1 · "), ("en", "Pin 3 · ", "Review 1 · ")):
            with self.subTest(lang=lang):
                page = self.view(phone(411, 908), lang=lang)
                names = page.evaluate(
                    "['#btn-side','#btn-rv'].map(s=>document.querySelector(s).getAttribute('aria-label'))"
                )
                self.assertTrue(names[0].startswith(side), names)
                self.assertNotIn("1", names[0].replace(side, ""), names)
                self.assertTrue(names[1].startswith(rv), names)
        page = self.view(phone(411, 908))
        page.focus("#btn-rv")
        page.keyboard.press("Shift+Tab")
        self.assertEqual(
            page.evaluate("[document.activeElement.id, document.activeElement.matches(':focus-visible'),"
                          " getComputedStyle(document.activeElement).zIndex]"),
            ["btn-side", True, "1"],
        )  # fmt: skip
        page = self.view(MOUSE_MID)
        names = page.evaluate("['#btn-side','#btn-rv'].map(s=>document.querySelector(s).getAttribute('aria-label'))")
        self.assertTrue(names[0].startswith("핀 3 · ") and names[1].startswith("검토 1 · "), names)


# The chip's halves: the pins half's drawn width, and each half's hit box against its own box - [left, right] offsets in px
# (negative reaches outside), read from the ::after's computed left, right and horizontal translate.
HALF_HITS = """() => {const q = s => document.querySelector(s);
  const after = e => {const a = getComputedStyle(e, '::after'), tx = new DOMMatrix(a.transform === 'none' ? undefined : a.transform).m41;
    const r = e.getBoundingClientRect(), left = parseFloat(a.left) + tx, width = parseFloat(a.width);
    return [Math.round(left * 100) / 100, Math.round((r.width - left - width) * 100) / 100];};
  return {side: Math.round(q('#btn-side').getBoundingClientRect().width), after: [after(q('#btn-side')), after(q('#btn-rv'))]};}"""
# The sheet bar's left cell: its width step (bar-snug, bar-tight or ''), what identifies each visible half ('word' and/or
# 'dot'), the dots' colours and the colours they should be (--status-open, --status-review), and how far each dot's centre
# sits from its count's.
BAR_IDS = """() => {const q = s => document.querySelector(s), vis = e => !!e && e.getClientRects().length > 0, b = q('#bar1');
  const cy = e => {const r = e.getBoundingClientRect(); return r.top + r.height / 2;};
  const colour = v => {const i = document.createElement('i'); i.style.color = v; document.body.append(i); const c = getComputedStyle(i).color; i.remove(); return c;};
  const halves = ['#btn-side', '#btn-rv'].map(q).filter(vis);
  return {step: ['bar-tight', 'bar-snug'].find(c => b.classList.contains(c)) || '',
    ids: halves.map(h => [['.side-l', 'word'], ['.side-d', 'dot']].filter(([s]) => vis(h.querySelector(s))).map(([, n]) => n)),
    dots: halves.map(h => getComputedStyle(h.querySelector('.side-d')).backgroundColor), want: [colour('var(--status-open)'), colour('var(--status-review)')],
    off: halves.map(h => Math.round((cy(h.querySelector('.side-d')) - cy(h.querySelector('b'))) * 100) / 100)};}"""


class SheetFocus(ViewerBase):
    """A sheet opened by a tap focuses itself, not its [닫기] (review of #130: the owner's phone drew the focus ring on [닫기]
    each time [더보기] opened, by the browser's own heuristic, where the emulator's :focus-visible did not). [더보기], the
    navigation sheet, the help and the Trash are tabindex=-1 dialogs that take the first focus with no outline; Tab goes
    on to [닫기]."""

    STATE = """() => {const a = document.activeElement; return [a.id || a.dataset.act, getComputedStyle(a).outlineStyle];}"""

    def test_a_tapped_sheet_focuses_itself_and_tab_reaches_close(self):
        """411x908: a tap on [⋯] and on [본문 1/2 ▾], a tap on [도움말] in [더보기], and the Trash opened: each sheet is the
        focused element, drawn with no outline, and one Tab lands on its [닫기]."""
        page = self.view(phone(411, 908))
        cdp = self.cdp(page)
        for opener, sheet, close in (
            ("#btn-more", "more", "more-close"),
            ("#btn-pos", "nav-sheet", "nav-sheet-close"),
            ("#more [data-act=help]", "help", "help-close"),
            (None, "trash", "trash-close"),
        ):
            with self.subTest(sheet=sheet):
                if sheet == "help":
                    page.evaluate("openMore()")
                    settle(page)
                if opener:
                    self.tap(cdp, *self.center(page, opener))
                else:
                    page.evaluate("openTrash()")
                page.wait_for_function("id=>document.getElementById(id).open", arg=sheet)
                settle(page)
                self.assertEqual(page.evaluate(self.STATE), [sheet, "none"])
                page.keyboard.press("Tab")
                self.assertEqual(page.evaluate("document.activeElement.dataset.act"), close)
                page.keyboard.press("Escape")
                settle(page)
                self.before_next_tap(page)


# A landscape tablet in the mid layout (the side panel). A portrait tablet is the tablet sheet (TouchLayoutBands).
TAB_LANDSCAPE = {"viewport": {"width": 1024, "height": 768}, "is_mobile": True, "has_touch": True}


class MidChrome(ViewerBase):
    """The mid layout's fixed chrome (input diagnosis P4): nav bar 48 + section strip 38 + action row 61 = 147px. The strip
    repeated the nav bar's 원고 tab and goes; its page count moves to the nav bar's right end; the action row is drawn at 40px."""

    def test_the_section_strip_goes_and_the_action_row_is_at_most_52px(self):
        """1024x768: no section strip, the page count in the nav bar, an action row of 52px or less whose buttons answer 44px."""
        page = self.view(TAB_LANDSCAPE)
        self.assertTrue(page.evaluate("document.body.classList.contains('lay-mid')"))
        self.assertFalse(page.is_visible("#section-strip"))
        self.assertTrue(page.is_visible("#nav-page"))
        self.assertRegex(page.inner_text("#nav-page"), r"^1 / 2쪽$")
        self.assertLessEqual(round(page.locator("#bar1").bounding_box()["height"]), 52)
        self.assertEqual(page.evaluate(MISSES_44, "#bar1 button"), [])

    def test_the_open_panel_keeps_out_of_a_right_notch(self):
        """A landscape phone with its notch on the right: the panel's buttons sat in the 47px inset (#c-copy at x 788-832)."""
        page = self.view(FOLD)
        self.cdp(page).send("Emulation.setSafeAreaInsetsOverride", {"insets": {"right": 47}})
        page.evaluate("()=>{LAST_PTR='touch'; pick({page:1,x0:10,y0:10,x1:200,y1:60});}")
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
        settle(page)
        out = page.evaluate(
            "[...document.querySelectorAll('#right button')].filter(b=>b.getClientRects().length&&b.closest('#composer,#c-actions'))"
            ".filter(b=>b.getBoundingClientRect().right>innerWidth-47).map(b=>b.id||b.className)"
        )
        self.assertEqual(out, [])


def touch_device(w: int, h: int) -> dict[str, object]:
    """A touch viewport of w x h CSS px (Playwright's isMobile and hasTouch)."""
    return {"viewport": {"width": w, "height": h}, "is_mobile": True, "has_touch": True}


# A landscape phone (the short band) beside the overlay limit and past it, and a mouse window as low as the first.
LAND_PHONE = touch_device(844, 390)
LAND_PHONE_WIDE = touch_device(932, 430)
MOUSE_LOW = {"viewport": {"width": 820, "height": 390}}
# The band and layout classes on body, sorted.
BODY_BANDS = "[...document.body.classList].filter(c=>/^(lay-|band-|mid-overlay$)/.test(c)).sort()"
# The top row of the short band: the nav bar's and the tool bar's boxes, and the visible controls of the tool bar with
# whether a tap at their centre reaches them.
TOP_ROW = """() => {
  const R = s => { const e = document.querySelector(s); if (!e || !e.getClientRects().length) return null;
    const b = e.getBoundingClientRect(); return {x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height)}; };
  const vis = e => !!e && e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
  const tools = [...document.querySelectorAll('#bar1 button')].filter(vis).map(b => { const r = b.getBoundingClientRect();
    const t = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return [b.id, Math.round(r.top), !!t && (t === b || b.contains(t))]; });
  const bottom = document.elementFromPoint(innerWidth / 2, innerHeight - 4);
  return {nav: R('#doc-nav'), bar: R('#bar1'), strip: vis(document.querySelector('#section-strip')), tools,
    bottomIsPdf: !!bottom && !!bottom.closest('#left'), overflow: document.documentElement.scrollWidth > innerWidth}; }"""


# Resolves after two animation frames: a resize the page has seen has also been through scheduleRelayout's frame.
TWO_FRAMES = "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
# Records the body's band changes from now on in window.__bands (a MutationObserver on body's class: one entry per new band).
COUNT_BANDS = """() => {const band = () => [...document.body.classList].find(c => c.startsWith('band-')); let last = band(); window.__bands = [];
  new MutationObserver(() => {const b = band(); if (b !== last) {window.__bands.push(b); last = b;}}).observe(document.body, {attributes: true, attributeFilter: ['class']});}"""


class TouchLayoutBands(ViewerBase):
    """The touch layout bands (docs/handbook/viewer.md §모바일 레이아웃): a landscape phone gets one top row (the short band),
    a touch tablet up to 1366px wide the side panel, and a mouse window of the same size keeps the width-only layout."""

    def compose(self, page):
        """A touch selection through the real pick path; waits for the composer."""
        page.evaluate("()=>{LAST_PTR='touch'; pick({page:1,x0:10,y0:10,x1:200,y1:60});}")
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
        settle(page)

    def test_a_landscape_phone_has_one_top_row_and_no_bottom_row(self):
        """844x390: nav bar 48 + action row 49 left the page 293px. The short band has one 48px row on top (44px before
        the cross-resolution pass) holding the nav bar and [선택] [⋯] [핀 N | 검토 M] at its right end, nothing at the
        bottom, and the overlay panel collapsed."""
        page = self.view(LAND_PHONE)
        self.assertEqual(page.evaluate(BODY_BANDS), ["band-short", "lay-mid", "mid-overlay"])
        self.assertFalse(page.evaluate("SIDE_OPEN"))
        row = page.evaluate(TOP_ROW)
        self.assertEqual((row["nav"]["y"], row["bar"]["y"]), (0, 0))
        self.assertLessEqual(max(row["nav"]["h"], row["bar"]["h"]), 48)
        self.assertLessEqual(row["nav"]["x"] + row["nav"]["w"], row["bar"]["x"])  # the links end where the tools begin
        self.assertEqual(row["bar"]["x"] + row["bar"]["w"], 844)
        self.assertEqual(sorted(t[0] for t in row["tools"]), ["btn-more", "btn-rv", "btn-select", "btn-side"])
        self.assertTrue(all(top < 48 and hit for _, top, hit in row["tools"]), row["tools"])
        self.assertFalse(row["strip"])
        self.assertTrue(row["bottomIsPdf"])
        self.assertFalse(row["overflow"])
        self.assertEqual(page.evaluate(MISSES_44, "#bar1 button,#nav-toc-toggle"), [])

    def test_past_900px_the_short_band_opens_its_panel_beside_the_document(self):
        """932x430: the same one 48px row; the panel is open beside the document (no overlay) from the top row to the
        bottom."""
        page = self.view(LAND_PHONE_WIDE)
        self.assertEqual(page.evaluate(BODY_BANDS), ["band-short", "lay-mid"])
        self.assertTrue(page.evaluate("SIDE_OPEN"))
        right = page.locator("#right").bounding_box()
        self.assertEqual((round(right["y"]), round(right["y"] + right["height"])), (48, 430))
        row = page.evaluate(TOP_ROW)
        self.assertLessEqual(row["bar"]["h"], 48)
        self.assertTrue(all(top < 48 and hit for _, top, hit in row["tools"]), row["tools"])

    def test_focusing_the_note_hides_the_top_row_until_the_focus_leaves(self):
        """With the keyboard up a landscape phone has about 200px: the row hides while a note field has focus, and the
        panel starts under the 48px row again once it leaves."""
        page = self.view(LAND_PHONE)
        self.compose(page)
        page.focus("#note")
        settle(page)
        self.assertTrue(page.evaluate("document.body.classList.contains('typing')"))
        self.assertFalse(page.is_visible("#doc-nav"))
        self.assertFalse(page.is_visible("#bar1"))
        self.assertEqual(round(page.locator("#right").bounding_box()["y"]), 0)
        page.evaluate("document.activeElement.blur()")
        settle(page)
        self.assertTrue(page.is_visible("#doc-nav"))
        self.assertEqual(round(page.locator("#right").bounding_box()["y"]), 48)

    def test_with_the_keyboard_up_the_whole_note_is_visible(self):
        """844x390 with a 190px keyboard (Chrome on Android shrinks the layout to 844x200): 41 of the note's 92px showed."""
        page = self.view(LAND_PHONE)
        self.compose(page)
        page.focus("#note")
        page.set_viewport_size({"width": 844, "height": 200})
        page.wait_for_function("innerHeight===200")
        settle(page)
        self.assertEqual(page.evaluate(BODY_BANDS), ["band-short", "lay-mid", "mid-overlay"])
        seen, h = page.evaluate(SHOWN, "#note")
        self.assertEqual(seen, h)

    def test_a_touch_tablet_up_to_1366px_wide_gets_the_side_panel_band(self):
        """1180x820 and 1366x1024 touch were the desktop with 44px buttons: a two-line tool bar, a 240px outline and
        always-open cards left the page 580px at 1180. Now: the side panel between the nav bar and a bottom action row,
        330px wide, the outline collapsed and the cards folded."""
        for w, h in ((1180, 820), (1366, 1024)):
            with self.subTest(w=w, h=h):
                page = self.view(touch_device(w, h))
                self.assertEqual(page.evaluate(BODY_BANDS), ["band-mid-side", "lay-mid"])
                self.assertTrue(page.evaluate("SIDE_OPEN"))
                bar = page.locator("#bar1").bounding_box()
                self.assertEqual((bar["x"], bar["width"], round(bar["y"] + bar["height"])), (0, w, h))
                self.assertEqual(round(page.locator("#right").bounding_box()["width"]), 330)
                if w == 1180:
                    self.assertGreaterEqual(page.locator("#pdf-center").bounding_box()["width"], 840)
                self.assertTrue(page.evaluate("document.body.classList.contains('outline-collapsed')"))
                self.assertTrue(page.is_visible("#pins .pin .sum"))
                self.assertFalse(page.is_visible("#pins .pin .acts"))

    def test_a_wide_touch_screen_starts_with_its_outline_collapsed_unless_saved_open(self):
        """1440x900 touch is still wide, but the 240px outline starts collapsed; a saved choice wins either way."""
        page = self.view(touch_device(1440, 900))
        self.assertEqual(page.evaluate(BODY_BANDS), ["band-wide", "lay-wide"])
        self.assertTrue(page.evaluate("document.body.classList.contains('outline-collapsed')"))
        page = self.view(touch_device(1440, 900), prefs={"outlineClosed": False})
        self.assertFalse(page.evaluate("document.body.classList.contains('outline-collapsed')"))

    def test_a_phone_keeps_its_sheet_at_64_percent_without_a_nav_bar(self):
        """390x844: the phone sheet as before - collapsed, 64% of the height once opened, no nav bar, height kept in sheetF."""
        page = self.view(touch_device(390, 844))
        self.assertEqual(page.evaluate(BODY_BANDS), ["band-phone", "lay-narrow"])
        self.assertFalse(page.evaluate("SIDE_OPEN"))
        self.assertFalse(page.is_visible("#doc-nav"))
        page.evaluate("setSide(true)")
        settle(page)
        self.assertAlmostEqual(page.locator("#right").bounding_box()["height"], 0.64 * 844, delta=1)

    def test_a_portrait_tablet_gets_a_bottom_sheet_under_the_nav_bar(self):
        """768x1024, 600x900 and 820x1180 touch: the overlay panel covered the right 43% of the page (768) and a small
        tablet stretched the phone sheet to 64% with 218px buttons (600). Now a sheet at 45% under the nav bar: the whole
        page width stays in view, the tool bar keeps its buttons at their natural width, and the list is at most 640px."""
        for w, h in ((768, 1024), (600, 900), (820, 1180)):
            with self.subTest(w=w, h=h):
                page = self.view(touch_device(w, h))
                self.assertEqual(page.evaluate(BODY_BANDS), ["band-tablet-sheet", "lay-narrow"])
                self.assertFalse(page.evaluate("SIDE_OPEN"))
                self.assertTrue(page.is_visible("#doc-nav"))
                self.assertTrue(page.is_visible("#nav-toc-toggle"))
                self.tap(self.cdp(page), *self.center(page, "#btn-side"))
                page.wait_for_function("SIDE_OPEN")
                settle(page)
                got = page.evaluate(
                    """() => {const R = s => document.querySelector(s).getBoundingClientRect(), vis = e => e.getClientRects().length > 0;
                      const marks = [...document.querySelectorAll('.mark')].map(m => m.getBoundingClientRect());
                      return {right: [R('#right').x, R('#right').width, R('#right').height], page: R('#p1').right,
                        marksIn: marks.every(m => m.left >= 0 && m.right <= innerWidth), marks: marks.length,
                        list: R('#list').width, grow: [...document.querySelectorAll('#bar1 button')].filter(vis).map(b => getComputedStyle(b).flexGrow),
                        side: R('#btn-side').width}; }"""
                )
                self.assertEqual(got["right"][:2], [0, w])
                self.assertAlmostEqual(got["right"][2], 0.45 * h, delta=1)
                self.assertLessEqual(got["page"], w)
                self.assertTrue(got["marks"] and got["marksIn"])
                self.assertLessEqual(got["list"], 640)
                self.assertEqual(set(got["grow"]), {"0"})
                self.assertLess(got["side"], 120)

    def test_the_tablet_sheet_and_its_outline_open_one_at_a_time(self):
        """768x1024: the outline is an overlay over the document; opening it collapses the sheet and opening the sheet closes
        it, as in the mid layout."""
        page = self.view(touch_device(768, 1024))
        page.evaluate("setSide(true)")
        settle(page)
        page.locator("#nav-toc-toggle").click()
        settle(page)
        self.assertEqual(
            page.evaluate("[OUTLINE_MID_OPEN, SIDE_OPEN, document.body.classList.contains('outline-collapsed')]"),
            [True, False, False],
        )
        self.assertTrue(page.is_visible("#outline"))
        page.locator("#btn-side").click()
        settle(page)
        self.assertEqual(page.evaluate("[OUTLINE_MID_OPEN, SIDE_OPEN]"), [False, True])
        self.assertFalse(page.is_visible("#outline"))

    def test_the_tablet_sheet_remembers_its_own_height_and_rises_to_under_the_nav_bar(self):
        """A height chosen on the tablet sheet goes to sheetFTab and leaves the phone's sheetF alone; its highest step ends
        under the nav bar instead of 48px from the top."""
        page = self.view(touch_device(768, 1024))
        page.evaluate("sizePreset(1)")
        settle(page)
        self.assertAlmostEqual(page.locator("#right").bounding_box()["height"], 0.64 * 1024, delta=1)
        prefs = page.evaluate("prefs()")
        self.assertEqual(prefs.get("sheetFTab"), 0.64)
        self.assertNotIn("sheetF", prefs)
        page.evaluate("sizePreset(2)")
        settle(page)
        nav = page.locator("#doc-nav").bounding_box()
        self.assertAlmostEqual(page.locator("#right").bounding_box()["y"], nav["y"] + nav["height"], delta=1)

    def test_between_phone_and_tablet_widths_the_open_sheet_stays_open_at_its_own_height(self):
        """A split-screen window dragged from 500 to 700px wide: still a sheet, still open, now at the tablet's 45%."""
        page = self.view(touch_device(500, 900))
        page.evaluate("setSide(true)")
        settle(page)
        page.set_viewport_size({"width": 700, "height": 900})
        page.wait_for_function("BAND==='tablet-sheet'")
        settle(page)
        self.assertTrue(page.evaluate("SIDE_OPEN"))
        self.assertAlmostEqual(page.locator("#right").bounding_box()["height"], 0.45 * 900, delta=1)

    def test_a_mouse_composing_at_1000px_scrolls_the_panel_as_before(self):
        """1000x800 with a mouse: picking focuses the note and the panel scrolls it into view as in 0.4.1, with no scroll
        padding - the touch save-row padding scrolled the composer 32px further than a focus does. Where the composer's top
        lands is the browser's own focus scroll (11 in 0.4.6; the caption and the range excerpt above the note move it), so
        the check is the note whole between the panel's top and the save row."""
        page = self.view(MOUSE_MID)
        self.mouse_pick(page)
        page.mouse.move(5, 5)
        settle(page)
        got = page.evaluate(
            "(()=>{const R=s=>document.querySelector(s).getBoundingClientRect(),n=R('#note'),r=R('#right'),a=R('#c-actions');"
            " return [document.activeElement.id, n.top>=r.top-0.5&&n.bottom<=a.top+0.5,"
            " getComputedStyle(document.querySelector('#right')).scrollPaddingBottom,"
            " getComputedStyle(document.querySelector('#right')).scrollPaddingTop];})()"
        )
        self.assertEqual(got, ["note", True, "auto", "auto"])

    def test_a_mouse_keeps_the_width_only_layouts_at_640_1000_and_1440(self):
        """A fine pointer gets the layouts it had before the bands: 640 the phone sheet (collapsed, no nav bar), 1000 the side
        panel open beside the document over a bottom action row, 1440 the desktop with its outline open; and 820x390,
        820x900, 1180x820 and 1366x1024 the overlay, overlay, wide and wide - never short or tablet-sheet."""
        want = {
            (640, 900): ["band-phone", "lay-narrow"],
            (1000, 800): ["band-mid-side", "lay-mid"],
            (1440, 900): ["band-wide", "lay-wide"],
            (820, 390): ["band-mid-overlay", "lay-mid", "mid-overlay"],
            (820, 900): ["band-mid-overlay", "lay-mid", "mid-overlay"],
            (1180, 820): ["band-wide", "lay-wide"],
            (1366, 1024): ["band-wide", "lay-wide"],
        }
        for (w, h), bands in want.items():
            with self.subTest(w=w, h=h):
                page = self.view({"viewport": {"width": w, "height": h}})
                self.assertEqual(page.evaluate(BODY_BANDS), bands)
                self.assertFalse(page.evaluate("MQ_COARSE.matches"))
                if (w, h) == (640, 900):
                    self.assertFalse(page.evaluate("SIDE_OPEN"))
                    self.assertFalse(page.is_visible("#doc-nav"))
                if (w, h) == (1000, 800):
                    self.assertTrue(page.evaluate("SIDE_OPEN"))
                    bar = page.locator("#bar1").bounding_box()
                    self.assertEqual(round(bar["y"] + bar["height"]), 800)
                if w >= 1100:
                    self.assertFalse(page.evaluate("document.body.classList.contains('outline-collapsed')"))
                    self.assertEqual(round(page.locator("#right").bounding_box()["width"]), 348)

    def resize(self, page, w, h):
        """Resize the touch viewport, as a rotation or a keyboard does, and wait until the page has handled it."""
        page.set_viewport_size({"width": w, "height": h})
        page.wait_for_function("([w,h])=>innerWidth===w&&innerHeight===h", arg=[w, h])
        settle(page)

    def test_rotating_a_tablet_while_composing_changes_the_band_once_and_keeps_the_note_and_the_spot(self):
        """768x1024 -> 1024x768 with a note written (the keyboard down): tablet-sheet to mid-side in one change, the composer
        still open with its note, the same page and spot on it."""
        page = self.view(touch_device(768, 1024))
        self.compose(page)
        page.locator("#note").fill("회전 전에 쓴 메모")
        page.evaluate("document.activeElement.blur(); document.querySelector('#left').scrollTop=600")
        settle(page)
        anchor = page.evaluate("topAnchor()")
        page.evaluate(COUNT_BANDS)
        self.resize(page, 1024, 768)
        page.wait_for_function("BAND==='mid-side'")
        settle(page)
        self.assertEqual(page.evaluate("window.__bands"), ["band-mid-side"])
        self.assertTrue(page.is_visible("#note"))
        self.assertEqual(page.input_value("#note"), "회전 전에 쓴 메모")
        now = page.evaluate("topAnchor()")
        self.assertEqual(now["page"], anchor["page"])
        self.assertAlmostEqual(now["frac"], anchor["frac"], delta=0.003)

    def test_unfolding_and_folding_again_go_phone_overlay_phone_with_the_sheet_collapsed(self):
        """344x882 -> 842x758 -> 344x882: one change each way; back on the folded screen the sheet starts collapsed."""
        page = self.view(touch_device(344, 882))
        page.evaluate(COUNT_BANDS)
        self.resize(page, 842, 758)
        page.wait_for_function("BAND==='mid-overlay'")
        self.resize(page, 344, 882)
        page.wait_for_function("BAND==='phone'")
        settle(page)
        self.assertEqual(page.evaluate("window.__bands"), ["band-mid-overlay", "band-phone"])
        self.assertFalse(page.evaluate("SIDE_OPEN"))

    def test_a_flickering_rotation_changes_the_band_exactly_once(self):
        """Seven sizes between 768x1024 and 1024x768, each one handled by the page (its resize seen, two animation frames
        run) and well within the 200ms settle of the one before: the band waits them out and changes once, to where the
        window stays. Without the wait (settleBand settling at once) it changes seven times."""
        page = self.view(touch_device(768, 1024))
        page.evaluate(COUNT_BANDS)
        for w, h in ((1024, 768), (768, 1024)) * 3 + ((1024, 768),):
            page.set_viewport_size({"width": w, "height": h})
            page.wait_for_function("w=>innerWidth===w", arg=w, polling="raf")
            page.evaluate(TWO_FRAMES)
        page.wait_for_function("BAND==='mid-side'")
        settle(page)
        self.assertEqual(page.evaluate("window.__bands"), ["band-mid-side"])

    def test_the_address_bar_moving_the_height_by_56px_keeps_the_band(self):
        """A height change under 96px from the settled one keeps the band - also where it crosses the 480px boundary
        (844x450 is short, 844x506 would not be)."""
        for w, low, high in ((844, 390, 446), (844, 450, 506)):
            with self.subTest(low=low, high=high):
                page = self.view(touch_device(w, low))
                page.evaluate(COUNT_BANDS)
                self.resize(page, w, high)
                self.assertEqual(page.evaluate("BAND"), "short")
                self.resize(page, w, low)
                self.assertEqual(page.evaluate("window.__bands"), [])

    def test_the_keyboard_on_a_landscape_tablet_keeps_the_band(self):
        """1024x768 with the note focused: Chrome on Android shrinks the layout to 1024x388, which alone would be the short band;
        the band stays mid-side while the note has focus, and when the keyboard closes and the focus leaves."""
        page = self.view(touch_device(1024, 768))
        self.compose(page)
        page.focus("#note")
        page.evaluate(COUNT_BANDS)
        self.resize(page, 1024, 388)
        self.assertEqual(page.evaluate("BAND"), "mid-side")
        self.resize(page, 1024, 768)
        page.evaluate("document.activeElement.blur()")
        settle(page)
        self.assertEqual(page.evaluate("[BAND, window.__bands]"), ["mid-side", []])

    def test_while_the_note_has_focus_a_rotation_waits_for_the_focus_to_leave(self):
        """768x1024 rotated with the note focused (the keyboard up): the band and the note's focus stay; once the focus leaves,
        the band changes to mid-side."""
        page = self.view(touch_device(768, 1024))
        self.compose(page)
        page.locator("#note").fill("쓰는 중")
        page.evaluate(COUNT_BANDS)
        self.resize(page, 1024, 768)
        self.assertEqual(
            page.evaluate("[BAND, document.activeElement.id, window.__bands]"), ["tablet-sheet", "note", []]
        )
        page.evaluate("document.activeElement.blur()")
        page.wait_for_function("BAND==='mid-side'")
        settle(page)
        self.assertEqual(page.evaluate("window.__bands"), ["band-mid-side"])
        self.assertEqual(page.input_value("#note"), "쓰는 중")

    def test_a_text_field_focused_during_the_settle_wait_holds_the_band(self):
        """768x1024 rotated with nothing focused: the band waits 200ms. The note gets the focus inside that wait (the timer
        is pending): when the wait runs out the band still holds, and it changes once the focus leaves."""
        page = self.view(touch_device(768, 1024))
        self.compose(page)
        page.evaluate(COUNT_BANDS)
        page.set_viewport_size({"width": 1024, "height": 768})
        page.wait_for_function("BAND_T!==0", polling="raf")
        page.focus("#note")
        settle(page)
        self.assertEqual(page.evaluate("[BAND, window.__bands]"), ["tablet-sheet", []])
        page.evaluate("document.activeElement.blur()")
        page.wait_for_function("BAND==='mid-side'")
        settle(page)
        self.assertEqual(page.evaluate("window.__bands"), ["band-mid-side"])

    def test_a_pick_in_the_short_band_shows_the_note_without_scrolling(self):
        """844x390, a real long-press pick: the composer put the note ninth (the mid order) and it was off screen (0/92); the
        short band takes the phone order, so the note comes right after the location line and is whole."""
        page = self.view(LAND_PHONE)
        self.long_press_pick(self.cdp(page), page)
        self.assertEqual(page.evaluate("document.querySelector('#right').scrollTop"), 0)
        seen, h = page.evaluate(SHOWN, "#note")
        self.assertEqual(seen, h)
        # the phone order and spacing: the note one 8px step under the location line, its question hint under it (not over it)
        page.locator("#note").fill("이 문장은 왜 이렇게 썼나요?")
        settle(page)
        order = page.evaluate(
            "[...document.querySelectorAll('#composer .c-loc-row,#c-qhint,#c-overlap,#c-levels,#c-kind,#c-xp,#note')]"
            ".filter(e=>e.getClientRects().length).map(e=>[e.id||e.className,Math.round(e.getBoundingClientRect().top)])"
            ".sort((a,b)=>a[1]-b[1]).map(a=>a[0])"
        )
        self.assertEqual(order, ["c-loc-row", "note", "c-qhint", "c-kind", "c-overlap", "c-levels", "c-xp"])
        gap = page.evaluate(
            "Math.round(document.querySelector('#note').getBoundingClientRect().top"
            "-document.querySelector('#composer .c-loc-row').getBoundingClientRect().bottom)"
        )
        self.assertEqual(gap, 8)
        overlap = page.evaluate(
            "Math.round(document.querySelector('#note').getBoundingClientRect().bottom"
            "-document.querySelector('#c-qhint').getBoundingClientRect().top)"
        )
        self.assertLessEqual(overlap, 0)  # the hint sits under the note's 8px bottom margin, never over its last line

    def test_with_a_bottom_safe_area_the_short_bands_note_is_whole_above_the_keyboard(self):
        """844x390 with a 21px bottom inset (and 47px side notches), the keyboard up (844x200): the save row grows by the
        inset, and the note's bottom 14px sat under it."""
        page = self.view(LAND_PHONE)
        cdp = self.cdp(page)
        cdp.send("Emulation.setSafeAreaInsetsOverride", {"insets": {"left": 47, "right": 47, "bottom": 21}})
        settle(page)
        self.long_press_pick(cdp, page)
        page.focus("#note")
        page.keyboard.insert_text("가로 휴대폰 메모")
        settle(page)  # the focus has scrolled the note into view before the keyboard comes up
        self.resize(page, 844, 200)
        seen, h = page.evaluate(SHOWN, "#note")
        self.assertEqual(seen, h)

    def test_the_panel_handles_hit_leaves_the_page_edge_to_scroll_and_pick(self):
        """1024x768 and 1180x820 touch: the handle's 44px hit lies on the PDF side and covered the page's right 28px, where a
        vertical swipe widened the panel (330 -> 512) instead of scrolling. The PDF scroller's right padding keeps the page
        clear of it: a swipe 10px inside the page's right edge scrolls the PDF with the panel width unchanged, and a long
        press there picks."""
        for w, h in ((1024, 768), (1180, 820)):
            with self.subTest(w=w, h=h):
                page = self.view(touch_device(w, h))
                cdp = self.cdp(page)
                pg = page.locator("#p1").bounding_box()
                grip = page.locator("#grip").bounding_box()
                self.assertLessEqual(pg["x"] + pg["width"], grip["x"] + grip["width"] - 44)  # the hit is off the page
                width = page.evaluate("Math.round(document.querySelector('#right').getBoundingClientRect().width)")
                x, y = pg["x"] + pg["width"] - 10, h / 2
                self.swipe(cdp, x, y + 120, x, y - 120)
                settle(page)
                self.assertGreater(page.evaluate("document.querySelector('#left').scrollTop"), 100)
                self.assertEqual(
                    page.evaluate("Math.round(document.querySelector('#right').getBoundingClientRect().width)"), width
                )
                page.evaluate("document.querySelector('#left').scrollTop=0")
                settle(page)
                self.long_press_pick(cdp, page, x, pg["y"] + 120)

    def test_on_a_wide_touch_screen_both_handles_hits_stay_off_the_page(self):
        """1440x900 touch with the outline open: the outline handle's hit (to its right) ends inside the PDF scroller's 44px
        left padding, and the panel handle's (to its left) inside the margin beside the 900px page."""
        page = self.view(touch_device(1440, 900), prefs={"outlineClosed": False})
        pg = page.locator("#p1").bounding_box()
        og = page.locator("#outline-grip").bounding_box()
        grip = page.locator("#grip").bounding_box()
        self.assertGreaterEqual(pg["x"], og["x"] + 44)
        self.assertLessEqual(pg["x"] + pg["width"], grip["x"] + grip["width"] - 44)

    def page_clear_of_grip(self, page):
        """[page right, the panel handle's hit left, page left, the outline handle's hit right or None] for page 1 now."""
        return page.evaluate(
            """() => {const R = s => { const e = document.querySelector(s); return e && e.getClientRects().length ? e.getBoundingClientRect() : null; };
              const p = R('#p1'), g = R('#grip'), o = R('#outline-grip');
              return [p.right, g ? g.right - 44 : null, p.left, o ? o.left + 44 : null]; }"""
        )

    def test_composing_over_the_overlay_panel_keeps_the_page_clear_of_the_handle(self):
        """842x758 composing: the page is fitted left of the overlay panel. The padding was the panel width + 40px and missed the
        8px bar, so the page's right edge (472) lay 4px inside the handle's hit (468-512)."""
        page = self.view(FOLD)
        self.compose(page)
        right, hit, _, _ = self.page_clear_of_grip(page)
        self.assertLess(right, hit)

    def test_fit_width_on_a_wide_touch_screen_keeps_the_page_clear_of_both_handles(self):
        """1440x900 touch: [폭 맞춤] (fitW) fitted 32px less than the width and the 48px padding, leaving the page 2px over the
        panel handle's hit; the fit now leaves exactly the padding. Also with the outline open and with the panel collapsed
        to its rail at the screen's edge."""
        for name, prefs in (("plain", {}), ("outline", {"outlineClosed": False}), ("rail", {"sideClosed": True})):
            with self.subTest(case=name):
                page = self.view(touch_device(1440, 900), prefs=prefs)
                page.evaluate("fitW()")
                settle(page)
                right, hit, left, ohit = self.page_clear_of_grip(page)
                self.assertLess(right, hit)
                if ohit is not None:
                    self.assertGreaterEqual(left, ohit)
                pad = page.evaluate("parseFloat(getComputedStyle(document.querySelector('#left')).paddingRight)")
                self.assertAlmostEqual(
                    page.evaluate("document.querySelector('#left').getBoundingClientRect().right") - right, pad, delta=1
                )

    def test_zoomed_and_scrolled_to_the_right_end_the_page_stays_clear_of_the_handle(self):
        """1024x768 touch at 300%, scrolled fully right: the right padding was not part of the scroll extent, so the page's
        edge came flush with the scroller under the handle's hit. The padding now counts."""
        page = self.view(touch_device(1024, 768))
        page.evaluate("()=>{zoomTo(W*3); const L=document.querySelector('#left'); L.scrollLeft=L.scrollWidth;}")
        settle(page)
        right, hit, _, _ = self.page_clear_of_grip(page)
        self.assertLess(right, hit)

    def test_a_tap_on_a_cards_left_edge_opens_the_card_not_the_panel_handle(self):
        """1024x768 touch: the handle's 44px hit reached 19px into the panel, so a tap on the leftmost 6px of a collapsed card
        cycled the panel width. The hit now lies on the PDF side of the bar; the card's edge opens the card."""
        page = self.view(touch_device(1024, 768))
        card = page.locator("#pins .pin").first
        b = card.bounding_box()
        pid = int(card.get_attribute("data-id"))
        width = page.evaluate("Math.round(document.querySelector('#right').getBoundingClientRect().width)")
        self.tap(self.cdp(page), b["x"] + 1, b["y"] + b["height"] / 2)
        page.wait_for_function("id=>OPEN_CARDS.has(id)", arg=pid)
        settle(page)
        self.assertEqual(
            page.evaluate("Math.round(document.querySelector('#right').getBoundingClientRect().width)"), width
        )
        grip = page.locator("#grip").bounding_box()
        self.assertEqual(
            page.evaluate(
                "([x,y])=>!!document.elementFromPoint(x,y).closest('#right')",
                [grip["x"] + grip["width"] + 1, grip["y"] + grip["height"] / 2],
            ),
            True,
        )  # one px right of the bar is the panel, not the handle

    def test_a_primary_pointer_turning_fine_and_back_switches_wide_and_side_panel(self):
        """1180x820: touch is mid-side; a mouse becoming the primary pointer (CDP turns touch emulation off, so pointer:coarse
        stops matching) makes it wide after the settle, and back; the note written meanwhile stays."""
        page = self.view(touch_device(1180, 820))
        self.compose(page)
        page.locator("#note").fill("포인터를 바꿔도 남는 메모")
        page.evaluate("document.activeElement.blur()")
        settle(page)
        page.evaluate(COUNT_BANDS)
        cdp = self.cdp(page)
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": False})
        page.wait_for_function("BAND==='wide'")
        settle(page)
        self.assertFalse(page.evaluate("MQ_COARSE.matches"))
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
        page.wait_for_function("BAND==='mid-side'")
        settle(page)
        self.assertEqual(page.evaluate("window.__bands"), ["band-wide", "band-mid-side"])
        self.assertEqual(page.input_value("#note"), "포인터를 바꿔도 남는 메모")

    def test_composing_on_a_tablet_sheet_keeps_it_at_45_percent_with_the_box_in_view(self):
        """768x1024 and 820x1180 with the keyboard down: the phone's 80% lift would hide the page just dragged on. The tablet
        sheet stays at 45% (the note is second, so the location line, the note and the save row fit) and the pending box is
        on screen between the nav bar and the sheet."""
        for w, h in ((768, 1024), (820, 1180)):
            with self.subTest(w=w, h=h):
                page = self.view(touch_device(w, h))
                self.long_press_pick(self.cdp(page), page)  # a real touch selection, with its pending box
                got = page.evaluate(
                    """() => {const R = s => document.querySelector(s).getBoundingClientRect(), box = R('.sel.pending');
                      return {sheet: [R('#right').top, R('#right').height], nav: R('#doc-nav').bottom, box: [box.top, box.bottom],
                        lift: document.body.classList.contains('sheet-up')}; }"""
                )
                self.assertAlmostEqual(got["sheet"][1], 0.45 * h, delta=1)
                self.assertFalse(got["lift"])
                self.assertGreaterEqual(got["box"][0], got["nav"])
                self.assertLessEqual(got["box"][1], got["sheet"][0])
                for sel in ("#c-loc", "#note", "#btn-save"):
                    seen, hh = page.evaluate(SHOWN, sel)
                    self.assertEqual(seen, hh, sel)

    def test_with_the_keyboard_up_the_tablet_sheet_shows_the_location_note_and_save_row_under_60_percent(self):
        """The keyboard shrinks the layout (Chrome on Android, resizes-content) by 330 and 380px: the location line, the note
        and the save row are all on screen, and the sheet is at most 60% of what is left. At 45% they fit there; a 600x900
        tablet with a 400px keyboard (500px left) needs more, and the sheet rises just past 45%, never past 60%."""
        for w, h, kb in ((768, 1024, 330), (820, 1180, 380), (600, 900, 400)):
            with self.subTest(w=w, h=h):
                page = self.view(touch_device(w, h))
                self.compose(page)
                page.focus("#note")
                self.resize(page, w, h - kb)
                for sel in ("#c-loc", "#note", "#btn-save"):
                    seen, hh = page.evaluate(SHOWN, sel)
                    self.assertEqual(seen, hh, sel)
                sheet = page.locator("#right").bounding_box()["height"]
                self.assertLessEqual(sheet, 0.6 * (h - kb) + 1)
                if kb == 400:
                    self.assertGreater(sheet, 0.45 * (h - kb) + 1)  # lifted only because they did not fit
                self.assertEqual(page.evaluate("BAND"), "tablet-sheet")

    def test_a_mouse_window_as_low_as_a_landscape_phone_keeps_the_width_layout(self):
        """820x390 with a mouse: the overlay layout with its nav bar and bottom action row, never the short band."""
        page = self.view(MOUSE_LOW)
        self.assertEqual(page.evaluate(BODY_BANDS), ["band-mid-overlay", "lay-mid", "mid-overlay"])
        bar = page.locator("#bar1").bounding_box()
        self.assertEqual(round(bar["y"] + bar["height"]), 390)


# The edit card's note in the opened panel or sheet: focus it, write, and select characters 3-5 (as a person mid-edit).
EDIT_FOCUS = """() => {setSide(true); openEdit(PINS[0].id); const ta = document.querySelector('.edit .e-note'); ta.focus();
  ta.value = '고치는 중인 메모'; ta.setSelectionRange(3, 5); }"""
# Where the focus is and what is selected in the edit card's note.
EDIT_STATE = """() => {const ta = document.querySelector('.edit .e-note');
  return [document.activeElement === ta, ta.selectionStart, ta.selectionEnd, ta.value]; }"""


class RedrawKeepsTheEditCard(ViewerBase):
    """A redraw of the card list re-inserts the open edit card: its note kept the text but lost the focus and the selection,
    which the reply box already restored (docs/handbook/viewer.md §모바일 레이아웃)."""

    def test_a_layout_change_keeps_the_edit_notes_focus_and_selection(self):
        """A mouse window going from wide (1400) to the side panel (1000): the layout changes, the cards are redrawn in their
        compact row, and the edit card's note still has the focus and characters 3-5 selected."""
        page = self.view(DESK)
        page.evaluate(EDIT_FOCUS)
        settle(page)
        page.set_viewport_size({"width": 1000, "height": 850})
        page.wait_for_function("LAYOUT==='mid'")
        settle(page)
        self.assertEqual(page.evaluate(EDIT_STATE), [True, 3, 5, "고치는 중인 메모"])

    def test_a_list_redraw_keeps_the_edit_notes_focus_and_selection(self):
        """The same for any redraw (a poll that brings another pin's change): drawPins() while the note is being edited."""
        page = self.view(touch_device(1024, 768))
        page.evaluate(EDIT_FOCUS)
        settle(page)
        page.evaluate("drawPins()")
        self.assertEqual(page.evaluate(EDIT_STATE), [True, 3, 5, "고치는 중인 메모"])

    def test_rotating_with_the_edit_note_focused_keeps_its_focus_and_selection(self):
        """768x1024 rotated to 1024x768 while the edit card's note has focus: the band holds (settleBand) and the note keeps
        its focus and selection; when the focus leaves, the band follows the rotation."""
        page = self.view(touch_device(768, 1024))
        page.evaluate(EDIT_FOCUS)
        settle(page)
        page.set_viewport_size({"width": 1024, "height": 768})
        page.wait_for_function("innerWidth===1024")
        settle(page)
        self.assertEqual(page.evaluate(EDIT_STATE), [True, 3, 5, "고치는 중인 메모"])
        self.assertEqual(page.evaluate("BAND"), "tablet-sheet")
        page.evaluate("document.activeElement.blur()")
        page.wait_for_function("BAND==='mid-side'")


# A mid handle's or outline handle's hit width, drawn width and pseudo-element width (the mouse keeps its own).
GRIP_BOX = """sel => {const g = document.querySelector(sel); return [Math.round(g.getBoundingClientRect().width),
  getComputedStyle(g, '::after').width]; }"""


# Page 1's gaps to the PDF scroller's visible box (inside its border, without a scroll bar): [left, right], to 0.1px.
PAGE_GAPS = """() => {const L = document.querySelector('#left'), lr = L.getBoundingClientRect(), p = document.querySelector('#p1').getBoundingClientRect();
  const x0 = lr.left + L.clientLeft, R = v => Math.round(v * 10) / 10; return [R(p.left - x0), R(x0 + L.clientWidth - p.right)];}"""


class EvenPageMargins(ViewerBase):
    """The fitted page sits in the middle of the PDF column (docs/handbook/viewer.md §모바일 레이아웃, UX audit P1/R3): on every
    compact band its left margin was 32px (a gutter for the mark badges) against 8px on the right - the owner's 'the left
    margin is bigger than the right'. Both are now --edge; beside the side panel both are the handle's 40px."""

    def test_the_fitted_page_has_equal_margins_on_phones_the_tablet_sheet_and_beside_the_side_panel(self):
        """360, 411 and 430 phones: 12 and 12; a 768 tablet sheet: 16 and 16; 1024x768 with the side panel open: 40 and 40
        (the right one keeps the panel handle's touch hit off the page)."""
        for (w, h), edge in (
            ((360, 800), 12),
            ((411, 908), 12),
            ((430, 932), 12),
            ((768, 1024), 16),
            ((1024, 768), 40),
        ):
            with self.subTest(w=w, h=h):
                page = self.view(touch_device(w, h))
                if w == 1024:
                    page.evaluate("setSide(true)")
                    settle(page)
                left, right = page.evaluate(PAGE_GAPS)
                self.assertAlmostEqual(left, right, delta=1)
                self.assertAlmostEqual(left, edge, delta=1)

    def test_a_mark_at_the_page_edge_takes_its_badge_inside_and_a_mark_at_the_text_keeps_it_outside(self):
        """411 and 360 phones (12px margins): a pin marked from the page's very edge has its badge in the mark's top-left
        corner, wholly in the PDF column; marks where the manuscript's text starts (6.4% in, the owner's #60) and further in
        keep the badge outside their left edge, also wholly shown - inside it covered the text they mark."""
        for fx, lo in ((0.0, 30), (0.064, 32)):
            add_pin(
                {
                    "file": str(self.main),
                    "lo": lo,
                    "hi": lo + 1,
                    "page": 1,
                    "note": "왼쪽",
                    "frac": [fx, 0.6 + fx, 0.4, 0.04],
                },
                actor(ALICE),
            )
        for w, h in ((411, 908), (360, 800)):
            with self.subTest(w=w):
                page = self.view(touch_device(w, h))
                got = page.evaluate(MARK_BADGES)
                self.assertEqual(
                    {(g["fx"], g["inside"], g["shown"], g["within"]) for g in got},
                    {(0.0, True, True, True), (0.064, False, True, False), (0.15, False, True, False)},
                )


# Each page-1 mark: its fraction x, whether its badge is inside (.in), wholly in the PDF column, and within the mark's box.
MARK_BADGES = """() => {const L = document.querySelector('#left'), lr = L.getBoundingClientRect(), x0 = lr.left + L.clientLeft;
  return [...document.querySelectorAll('#p1 .mark')].map(m => {const b = m.querySelector('b').getBoundingClientRect(), r = m.getBoundingClientRect();
    return {fx: +m.dataset.fx, inside: m.classList.contains('in'), shown: b.left >= x0 && b.right <= x0 + L.clientWidth,
      within: b.left >= r.left && b.top >= r.top, gap: Math.round(r.left - b.left)};}); }"""


# Where a sheet's lines start, against its reference box (the sheet, or the pin list's column): for each [selector, kind] the
# first visible match's 'box' (border-box left), 'content' (content-box left), 'ink' (left of its first drawn leaf - a text run,
# an icon or an empty box such as a status dot) or 'end' (the gap from its border-box right to the reference's right).
SHEET_LINES = """([ref, items]) => {const R = document.querySelector(ref).getBoundingClientRect(), r1 = v => Math.round(v * 10) / 10;
  const vis = e => !!e && e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
  const ink = e => {const w = document.createTreeWalker(e, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT); let n;
    while ((n = w.nextNode())) {
      if (n.nodeType === 3) {if (!n.nodeValue.trim()) continue; const g = document.createRange(); g.selectNodeContents(n); const b = g.getBoundingClientRect(); if (b.width) return b.left;}
      else if (vis(n) && (n.tagName.toLowerCase() === 'svg' || !n.childNodes.length)) {const b = n.getBoundingClientRect(); if (b.width) return b.left;}}
    return null;};
  return items.map(([sel, kind]) => {const e = [...document.querySelectorAll(sel)].find(vis); if (!e) return [sel, kind, null];
    const b = e.getBoundingClientRect(), cs = getComputedStyle(e);
    const x = kind === 'box' ? b.left - R.left : kind === 'content' ? b.left + parseFloat(cs.borderLeftWidth) + parseFloat(cs.paddingLeft) - R.left
      : kind === 'ink' ? ink(e) - R.left : R.right - b.right;
    return [sel, kind, r1(x)];});}"""
# The lines each sheet draws, as [reference, opener, [[selector, kind]...]] (SHEET_LINES).
SHEETS = (
    (
        "#list",
        "()=>{setSide(true); document.querySelector('#right').scrollTop=0;}",
        [
            ["#open-toggle", "ink"],
            ["#pins .pin", "box"],
            ["#pins .pin", "end"],
            ["#pins .pin .head", "ink"],
            ["#review-pins .pin", "box"],
        ],
    ),
    (
        "#more",
        "openMore()",
        [
            ["#more-label", "ink"],
            ["#more-info", "ink"],
            ["#m-zoom-l", "ink"],
            ["#m-size-l", "ink"],
            ["#m-size", "end"],
            ["#m-theme", "end"],
            ["#more .more-grid button", "box"],
            ["#more .more-grid button", "end"],
            ["#more .more-grid button", "ink"],
            ["#more-foot", "ink"],
            ["#more [data-act=more-close]", "end"],
        ],
    ),
    (
        "#nav-sheet",
        "openNavSheet()",
        [
            ["#nav-sheet-h", "ink"],
            ["#ns-view", "box"],
            ["#ns-view", "end"],
            ["#ns-page label", "ink"],
            ["#nav-sheet [data-act=nav-sheet-close]", "end"],
        ],
    ),
    (
        "#help",
        "openHelp()",
        [
            ["#help-h", "ink"],
            ["#help h4", "ink"],
            ["#help .help-steps li", "ink"],
            ["#help table", "box"],
            ["#help table", "end"],
            ["#help td", "content"],
            ["#help .help-legend", "content"],
            ["#help-pins-md", "ink"],
            ["#help [data-act=help-close]", "end"],
        ],
    ),
    (
        "#trash",
        "openTrash()",
        [
            ["#trash-h", "ink"],
            ["#trash-note", "ink"],
            ["#trash .arc-row", "box"],
            ["#trash .arc-row .arc-l1", "ink"],
            ["#trash .arc-row .arc-l2", "ink"],
            ["#trash .arc-acts", "end"],
            ["#trash [data-act=trash-close]", "end"],
        ],
    ),
)


class SheetEdgeGrid(ViewerBase):
    """One edge grid and one sheet (docs/handbook/viewer.md §패널 정리, §휴지통, UX audit P8/P9, R1/R2): in a compact sheet
    every box starts and ends on --edge (12px on a phone, 16px from the tablet sheet up) and every line without a box
    starts its text on --ink (--edge + 12). Box and text lines were spread over 8, 12, 13, 16, 17, 25, 26, 30 and 33px.
    Help and the Trash are bottom sheets like [더보기] and the documents sheet; Trash rows are two lines."""

    def drop_one(self):
        """Add one more pin by Alice and delete it, so the Trash has a row (the three open pins stay)."""
        pid = add_pin(
            {"file": str(self.main), "lo": 30, "hi": 31, "page": 2, "note": "지운 핀", "frac": [0.2, 0.6, 0.4, 0.04]},
            actor(ALICE),
        ).record["id"]
        ps.APP.pin_trash.drop_pin(pid, post_authority(ps.APP.pin_trash.context().store, actor(ALICE), "drop", pid))

    def test_every_sheet_puts_its_boxes_on_edge_and_its_text_on_ink(self):
        """411x908 phone (12/24) and 768x1024 tablet sheet (16/28): the pin list, [더보기], the documents sheet, help and
        the Trash."""
        self.drop_one()
        for (w, h), edge in (((411, 908), 12), ((768, 1024), 16)):
            page = self.view(touch_device(w, h))
            for ref, opener, items in SHEETS:
                with self.subTest(w=w, sheet=ref):
                    page.evaluate(opener)
                    settle(page)
                    got = page.evaluate(SHEET_LINES, [ref, items])
                    want = {"box": edge, "end": edge, "ink": edge + 12, "content": edge + 12}
                    off = [g for g in got if g[2] is None or abs(g[2] - want[g[1]]) > 1.5]
                    self.assertEqual(off, [])
                    page.evaluate(
                        "()=>{for(const d of document.querySelectorAll('dialog[open]'))d.close(); setSide(false);}"
                    )
                    settle(page)

    def test_help_and_the_trash_are_bottom_sheets_on_compact_bands(self):
        """Like [더보기] and the documents sheet: on the bottom edge, the phone's whole width, the tablet sheet's 640px
        column (they were centred cards 92vw and 100vw - 16px wide)."""
        for (w, h), width in (((411, 908), 411), ((768, 1024), 640)):
            page = self.view(touch_device(w, h))
            for opener, dlg in (("openHelp()", "#help"), ("openTrash()", "#trash"), ("openMore()", "#more")):
                with self.subTest(w=w, dialog=dlg):
                    page.evaluate(opener)
                    settle(page)
                    b = page.locator(dlg).bounding_box()
                    self.assertAlmostEqual(b["y"] + b["height"], h, delta=1)
                    self.assertAlmostEqual(b["width"], width, delta=1)
                    self.assertAlmostEqual(b["x"], (w - width) / 2, delta=1)
                    page.evaluate("s=>document.querySelector(s).close()", dlg)

    def test_help_and_the_trash_close_on_an_outside_tap_a_pull_down_and_the_back_gesture(self):
        """Phone: a tap above the sheet, a pull down past 35% of it, and the system back (history fallback) with the pin
        sheet open below - which stays open - each close it."""
        for opener, dlg in (("openHelp()", "#help"), ("openTrash()", "#trash")):
            with self.subTest(dialog=dlg):
                page = self.view(PHONE, init=NO_CLOSE_WATCHER)
                cdp = self.cdp(page)
                is_open = "s=>document.querySelector(s).open"
                page.evaluate(opener)
                settle(page)
                self.tap(cdp, 190, 20)
                page.wait_for_function("s=>!document.querySelector(s).open", arg=dlg)
                page.evaluate(opener)
                settle(page)
                r = page.locator(dlg).bounding_box()
                self.swipe(cdp, 190, r["y"] + 30, 190, r["y"] + 30 + r["height"] * 0.6, steps=10, dt=0.02)
                page.wait_for_function("s=>!document.querySelector(s).open", arg=dlg)
                self.tap(cdp, *self.center(page, "#btn-side"))
                page.wait_for_function("SIDE_OPEN")
                page.evaluate(opener)
                settle(page)
                self.assertTrue(page.evaluate(is_open, dlg))
                page.go_back()
                page.wait_for_function("s=>!document.querySelector(s).open", arg=dlg)
                settle(page)
                self.assertTrue(page.evaluate("SIDE_OPEN"))

    def test_a_trash_row_is_two_lines_with_its_buttons_beside_the_note_on_a_phone(self):
        """411x908: a row was the meta line, then [되살리기] alone on a line, then the note (the button away from its note).
        Now the meta line, then the note with [되살리기] at its right end: two 44px touch lines and the row's 16px padding."""
        self.drop_one()
        page = self.view(touch_device(411, 908))
        page.evaluate("openTrash()")
        settle(page)
        got = page.evaluate(
            """() => {const row = document.querySelector('#trash .arc-row'), B = s => row.querySelector(s).getBoundingClientRect();
              const l1 = B('.arc-l1'), l2 = B('.arc-l2'), a = B('.arc-acts'), r = row.getBoundingClientRect();
              return {lines: l2.top >= l1.bottom - 1, besideNote: a.top < l2.bottom && a.bottom > l2.top && a.left >= l2.right - 1,
                height: Math.round(r.height)}; }"""
        )
        self.assertEqual({k: got[k] for k in ("lines", "besideNote")}, {"lines": True, "besideNote": True})
        self.assertLessEqual(got["height"], 2 * 44 + 16)

    def test_touch_help_starts_with_a_long_press_and_a_mouse_with_a_drag(self):
        """The tour's first step taught 'drag on the PDF' and '⌘ Enter' on a phone; touch gets the long press and [선택],
        and no shortcut, while a mouse keeps the drag."""
        steps = "[...document.querySelectorAll('#help .help-steps li')].map(li=>li.innerText)"
        page = self.view(PHONE)
        page.evaluate("openHelp()")
        settle(page)
        touch = page.evaluate(steps)
        self.assertIn("길게 누르", touch[0])
        self.assertNotIn("드래그", touch[0])
        self.assertFalse([s for s in touch if "⌘" in s or "Ctrl" in s])
        page = self.view(DESK)
        page.evaluate("openHelp()")
        settle(page)
        mouse = page.evaluate(steps)
        self.assertIn("드래그", mouse[0])
        self.assertNotIn("길게 누르", mouse[0])
        self.assertIn("⌘ Enter", mouse[2])


class TouchHandleHits(ViewerBase):
    """The mid panel handle (25px) and the wide outline handle (24px) answered a tap narrower than 44px on touch; through the
    .hit utility they answer a 44px box, and their drawn bars keep their width. A mouse keeps its 12px and 24px."""

    def test_the_mid_panel_handle_answers_44px_beside_and_over_the_document(self):
        """1024x768 (the side panel) and 842x758 (the overlay panel, opened): the handle's 8px bar answers 44px."""
        for device in (touch_device(1024, 768), FOLD):
            with self.subTest(width=device["viewport"]["width"]):
                page = self.view(device)
                page.evaluate("setSide(true)")
                settle(page)
                self.assertEqual(page.evaluate(MISSES_44, "#grip"), [])
                self.assertEqual(page.evaluate(GRIP_BOX, "#grip")[0], 8)

    def test_the_wide_outline_handle_answers_44px_on_touch(self):
        """1440x900 touch with the outline open: the 6px handle answers 44px."""
        page = self.view(touch_device(1440, 900), prefs={"outlineClosed": False})
        self.assertEqual(page.evaluate(MISSES_44, "#outline-grip"), [])
        self.assertEqual(page.evaluate(GRIP_BOX, "#outline-grip")[0], 6)

    def test_a_mouse_keeps_its_handle_hit_widths(self):
        """1400x850 with a mouse: the panel handle reaches 3px each side (12px, clear of the scrollbar), the outline's 9px."""
        page = self.view(DESK, prefs={"outlineClosed": False})
        self.assertEqual(page.evaluate(GRIP_BOX, "#grip"), [6, "12px"])
        self.assertEqual(page.evaluate(GRIP_BOX, "#outline-grip"), [6, "24px"])


class PhoneMoreAndHelp(ViewerBase):
    """[더보기] and help on a phone (input diagnosis P10): [더보기] was a 600px centred dialog whose 2-column grid left 'English' on
    a row of its own and wrapped English labels onto two lines; help showed the desktop shortcut table on a touch screen."""

    def test_more_is_a_bottom_sheet_of_one_line_rows(self):
        """360x780 and 411x908, Korean and English: a sheet on the bottom edge, at most the screen less 48px high (the new
        structure - two meta lines, the view and pin groups, the foot - outgrew the old 460px cap), no label on two lines,
        44px targets for the segments, the switch and the rows, and no Limn icon in the label."""
        for w, h in ((360, 780), (411, 908)):
            for lang in ("ko", "en"):
                with self.subTest(w=w, lang=lang):
                    page = self.view(touch_device(w, h), lang=lang)
                    page.evaluate("openMore()")
                    settle(page)
                    box = page.locator("#more").bounding_box()
                    self.assertLessEqual(box["height"], h - 48)
                    self.assertAlmostEqual(box["y"] + box["height"], h, delta=1)
                    two = page.evaluate(
                        """() => [...document.querySelectorAll('#more button')].filter(b => b.getClientRects().length).filter(b => {
                          const w = document.createTreeWalker(b, NodeFilter.SHOW_TEXT), tops = new Set(); let n;
                          while ((n = w.nextNode())) {if (!n.nodeValue.trim()) continue; const r = document.createRange(); r.selectNodeContents(n);
                            for (const q of r.getClientRects()) if (q.width > 1) tops.add(Math.round(q.top));}
                          return tops.size > 1;
                        }).map(b => b.id || b.textContent.trim())"""
                    )
                    self.assertEqual(two, [])
                    self.assertEqual(page.evaluate(MISSES_44, "#more button,#more input"), [])
                    self.assertFalse(page.evaluate("!!document.querySelector('#more-label svg')"))

    def test_a_tapped_row_keeps_no_hover_fill_while_a_mouse_still_gets_one(self):
        """360x780 touch: a tap on [테마] in [더보기] left the row grey (a sticky :hover, the owner's 'Theme: System', UX
        audit P4.6); the hover fill answers a mouse only. The theme is a segment control now: after a tap on [어둡게] and
        one back on [밝게], [어둡게] has no fill. A mouse at 1000x800 (the same sheet) still gets --accent on it."""
        bg = "getComputedStyle(document.querySelector('#m-theme [data-theme=dark]')).backgroundColor"
        page = self.view(PHONE_360)
        page.evaluate("openMore()")
        settle(page)
        self.tap(self.cdp(page), *self.center(page, "#m-theme [data-theme=dark]"))
        settle(page)
        self.tap(self.cdp(page), *self.center(page, "#m-theme [data-theme=light]"))
        settle(page)
        self.assertEqual(page.evaluate(bg), "rgba(0, 0, 0, 0)")
        page = self.view(MOUSE_MID)
        page.evaluate("openMore()")
        settle(page)
        page.hover("#m-theme [data-theme=dark]")
        settle(page)
        accent = page.evaluate(
            "(()=>{const e=document.createElement('i'); e.style.background='var(--accent)'; document.body.append(e);"
            " const c=getComputedStyle(e).backgroundColor; e.remove(); return c;})()"
        )
        self.assertEqual(page.evaluate(bg), accent)

    def test_help_on_a_touch_screen_leaves_out_the_shortcut_table(self):
        """Ctrl, the wheel and Alt+1…9 mean nothing on a phone; a mouse still gets the table."""
        page = self.view(PHONE_360)
        page.evaluate("openHelp()")
        settle(page)
        self.assertFalse(page.locator("#help .kbd-only").first.is_visible())
        page = self.view(DESK)
        page.evaluate("openHelp()")
        settle(page)
        self.assertTrue(page.locator("#help .kbd-only").first.is_visible())


# A touch tablet wide enough for the desktop layout (wider than 1366px: a 13-inch iPad in landscape), as an iPad home-screen
# app or full screen. A 1180x820 tablet is the side-panel band (TouchLayoutBands).
TAB_WIDE = {"viewport": {"width": 1376, "height": 1032}, "is_mobile": True, "has_touch": True}


class WideSafeArea(ViewerBase):
    """The wide layout keeps its controls out of the safe-area insets (input diagnosis P9): in an iPad home-screen app or full
    screen the nav links and tool-bar buttons sat under the status bar and [취소][핀 저장] on the home indicator."""

    INSETS = {"top": 24, "bottom": 20}

    def test_wide_controls_stay_inside_the_safe_area(self):
        """Nav bar, tool bar and the composer's action row lie between the top and bottom insets."""
        page = self.view(TAB_WIDE)
        self.assertTrue(page.evaluate("document.body.classList.contains('lay-wide')"))
        self.cdp(page).send("Emulation.setSafeAreaInsetsOverride", {"insets": self.INSETS})
        page.evaluate("()=>{LAST_PTR='touch'; pick({page:1,x0:10,y0:10,x1:200,y1:60});}")
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
        settle(page)
        out = page.evaluate(
            """ins => {
              const bad = [];
              for (const e of document.querySelectorAll('#doc-nav button,#bar1 button,#c-actions button')) {
                const r = e.getBoundingClientRect(); if (!r.width || !r.height) continue;
                if (r.top < ins.top || r.bottom > innerHeight - ins.bottom) bad.push((e.id || e.className) + ' ' + Math.round(r.top) + '-' + Math.round(r.bottom));
              }
              return bad; }""",
            self.INSETS,
        )
        self.assertEqual(out, [])


# ---------------------------------------------------------------- B. the rest of the approved findings


class DesktopMisc(ViewerBase):
    """Undo for a discarded selection and after saving, Esc in the change view, dialogs, hit targets, the first hint."""

    def test_escape_or_cancel_with_a_note_offers_undo_that_brings_it_all_back(self):
        """Discarding a selection with a written note is undoable for the toast's 6 seconds: selection, note and box."""
        for how in ("escape", "cancel"):
            with self.subTest(how=how):
                page = self.view(DESK)
                self.mouse_pick(page)
                lo = page.evaluate("COMPOSE.current.lo")
                page.locator("#note").fill("길게 쓴 메모")
                if how == "escape":
                    page.keyboard.press("Escape")
                else:
                    page.locator("#btn-cancel").click()
                self.assertTrue(page.evaluate("document.querySelector('#composer').hidden&&!COMPOSE.current"))
                page.locator("#toasts .toast", has_text="선택 취소됨").locator("button", has_text="되돌리기").click()
                self.assertEqual(
                    page.evaluate(
                        "[!document.querySelector('#composer').hidden, COMPOSE.current&&COMPOSE.current.lo, "
                        "document.querySelector('#note').value, !!document.querySelector('.sel.pending')]"
                    ),
                    [True, lo, "길게 쓴 메모", True],
                )

    def test_escape_with_an_empty_note_needs_no_undo(self):
        """Nothing written, nothing to lose: no toast."""
        page = self.view(DESK)
        self.mouse_pick(page)
        page.keyboard.press("Escape")
        self.assertEqual(page.locator("#toasts .toast").count(), 0)

    def test_undo_right_after_saving_reopens_the_composer_with_the_same_selection_and_note(self):
        """[되돌리기] on '핀 #N 저장됨' takes the pin back and hands the selection and note back for another try."""
        page = self.view(DESK)
        self.mouse_pick(page)
        lo = page.evaluate("COMPOSE.current.lo")
        page.locator("#note").fill("저장 뒤 되돌리기")
        page.keyboard.press("Control+Enter")
        page.wait_for_function("OPEN_ALL.length===4")
        page.locator("#toasts button", has_text="되돌리기").first.click()
        page.wait_for_function("OPEN_ALL.length===3&&!document.querySelector('#composer').hidden")
        self.assertEqual(
            page.evaluate("[COMPOSE.current&&COMPOSE.current.lo, document.querySelector('#note').value]"),
            [lo, "저장 뒤 되돌리기"],
        )

    def test_escape_in_the_change_view_returns_to_the_manuscript(self):
        """Esc = [원고로]."""
        page = self.view(DESK)
        page.evaluate("setViewMode('revisions')")
        page.keyboard.press("Escape")
        self.assertFalse(page.evaluate("document.body.classList.contains('revision-open')"))

    def test_an_outside_click_closes_help_and_the_documents_menu_like_the_others(self):
        """[더보기] and the Trash closed on a backdrop click; help and the documents menu (now the navigation sheet) do too."""
        page = self.view(DESK)
        for opener, dlg in (("openHelp()", "#help"), ("openNavSheet()", "#nav-sheet")):
            with self.subTest(dialog=dlg):
                page.evaluate(opener)
                page.mouse.click(8, 8)
                page.wait_for_function("!document.querySelector('%s').open" % dlg)

    def test_desktop_hit_targets_are_at_least_24px(self):
        """WCAG 2.5.8: each control answers a click anywhere in a 24x24 box around its center (visual size unchanged)."""
        page = self.view(DESK)
        page.evaluate("SEC.done=true; drawPins()")
        bad = page.evaluate("""() => {
          const sel = 'button,[data-act],[role=button],[data-copy],.mark b';
          const out = [];
          for (const e of document.querySelectorAll(sel)) {
            if (e.closest('#more,#help,#trash,#nav-sheet,#revision-view,#outline') || e.matches('.note,.sum,.arc-reply,.pin-ref,#grip,#outline-grip,textarea'))
              continue;
            const r = e.getBoundingClientRect(); if (!r.width || !r.height || getComputedStyle(e).visibility === 'hidden') continue;
            if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
            const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
            const hit = [[-11.5, 0], [11.5, 0], [0, -11.5], [0, 11.5]].every(([dx, dy]) => {
              const h = document.elementFromPoint(cx + dx, cy + dy); return !!h && (h === e || e.contains(h)); });
            if (!hit) out.push((e.id ? '#' + e.id : e.className || e.tagName) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height));
          }
          return out; }""")
        self.assertEqual(bad, [])

    def test_mouse_users_get_a_crosshair_and_a_one_time_hint(self):
        """The PDF shows a crosshair, and the first visit says how to pin (Korean and English)."""
        for lang in ("ko", "en"):
            with self.subTest(lang=lang):
                page = self.view(DESK, lang=lang, prefs={"coach": {}})
                self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('.pg')).cursor"), "crosshair")
                text = page.locator("#coach-t").inner_text()
                self.assertTrue(text)
                self.assertEqual(bool(HANGUL.search(text)), lang == "ko")
                self.assertEqual(page.evaluate("prefs().coach.mouse"), 1)


# ---------------------------------------------------------------- the bottom bar, the status line and the sheets (PR D)


def phone(w: int, h: int, dpr: float = 2.625) -> dict[str, object]:
    """A touch phone of w x h CSS px at the UX audit's device pixel ratio (touch_device plus the ratio)."""
    return dict(touch_device(w, h), device_scale_factor=dpr)


# The phone band's widths of the UX audit (the owner's 411, the narrowest phones and the folded cover) and the tablet sheet.
BAR_PHONES = (phone(411, 908), phone(360, 800, 3), phone(393, 852, 3), phone(430, 932, 3), phone(344, 882))
BAR_TABLETS = (phone(820, 1180, 2), phone(884, 1104, 2.5))
# The bottom bar as drawn: the grabber's centre minus the screen's, the children that spill out of their cell, the bar buttons
# that draw a border, the text [⬚] shows, whether [📍 N] shows a word, the collapsed sheet's chrome under the PDF, the visible
# ids of the right cell, and the left cell's gap and [📍]'s side padding.
BAR = """() => {const q = s => document.querySelector(s), R = e => e.getBoundingClientRect(), vis = e => !!e && e.getClientRects().length > 0;
  const bar = q('#bar1'), g = R(q('#sheet-grip')), r1 = v => Math.round(v * 10) / 10;
  const spill = [];
  for (const c of bar.querySelectorAll(':scope>.bar-l,:scope>.bar-r')) {const cr = R(c);
    for (const e of [...c.children].filter(vis)) {const r = R(e); if (r.left < cr.left - 0.5 || r.right > cr.right + 0.5) spill.push(e.id);}
    if (cr.left < R(bar).left - 0.5 || cr.right > R(bar).right + 0.5) spill.push(c.className);}
  const buttons = [...bar.querySelectorAll('button')].filter(vis);
  return {off: r1(g.left + g.width / 2 - innerWidth / 2), spill,
    borders: buttons.filter(b => ['Top', 'Right', 'Bottom', 'Left'].some(s => parseFloat(getComputedStyle(b)['border' + s + 'Width']))).map(b => b.id),
    select: q('#btn-select').innerText.trim(), sideWord: /[A-Za-z\\uac00-\\ud7a3]/.test(q('#btn-side').innerText),
    chrome: Math.round(innerHeight - R(q('#right')).top), right: [...q('#bar1 .bar-r').children].filter(vis).map(e => e.id),
    gap: getComputedStyle(q('#bar1 .bar-l')).columnGap, pad: getComputedStyle(q('#btn-side')).paddingLeft,
    eye: vis(q('#btn-side .rv-n svg.ic'))};}"""
# The status line as drawn: the id of its parent (where placeStatus put it), the dock's and the sheet's boxes, the visible
# text, the data-act of its buttons, and its progress bar's role and value.
STATUS_LINE = """() => {const q = s => document.querySelector(s), B = e => {const r = e.getBoundingClientRect();
    return {x: r.x, y: r.y, w: r.width, h: r.height, b: r.bottom};}, s = q('#status'), bar = s.querySelector('.st-bar');
  return {parent: s.parentElement.id, dock: B(q('#status-dock')), sheet: B(q('#right')),
    text: (s.querySelector('.st-tx') || {}).textContent || '', acts: [...s.querySelectorAll('button')].map(b => b.dataset.act),
    bar: bar ? {role: bar.getAttribute('role'), now: bar.getAttribute('aria-valuenow')} : null};}"""
# The bar's optical ends: [📍]'s gaps from its fill to the pin's ink and from the pill (else the count) to the fill's end,
# and the room right of [⋯]'s ink to the bar's column edge. Ink = the shapes' boxes widened by half the stroke.
OPTICAL = """() => {const q = s => document.querySelector(s), b = q('#btn-side').getBoundingClientRect();
  const ink = svg => {const sc = svg.getBoundingClientRect().width / 24, half = (parseFloat(getComputedStyle(svg).strokeWidth) || 2) * sc / 2;
    const rs = [...svg.querySelectorAll('path,circle,line,rect,polyline')].map(e => e.getBoundingClientRect());
    return {l: Math.min(...rs.map(r => r.left)) - half, r: Math.max(...rs.map(r => r.right)) + half};};
  const pill = q('#btn-side .rv-n'), t = document.createRange(); t.selectNodeContents(q('#side-n'));
  const end = pill && !pill.hidden ? pill.getBoundingClientRect().right : t.getBoundingClientRect().right;
  const pin = ink(q('#btn-side .pin-ic svg')), more = ink(q('#btn-more svg'));
  return {gapL: pin.l - b.left, gapR: b.right - end, moreInk: q('#bar1').getBoundingClientRect().right - more.r};}"""
# The notification switch made switchable and off: its track's contrast against the [더보기] sheet (WCAG ratio).
SWITCH_OFF = """() => {const b = document.getElementById('m-notify'); b.disabled = false; b.setAttribute('aria-checked', 'false');
  const rgb = e => getComputedStyle(e).backgroundColor.match(/[\\d.]+/g).slice(0, 3).map(Number);
  const lum = c => {const v = c.map(x => {x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);});
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];};
  const a = lum(rgb(b.querySelector('.sw-track'))), m = lum(rgb(document.getElementById('more')));
  return (Math.max(a, m) + 0.05) / (Math.min(a, m) + 0.05);}"""
# An outline of three headings over the fixture's two pages (its PDFs carry none), drawn into both outline lists.
OUTLINE3 = """() => {OUTLINE_ENTRIES = [{title: '서론', page: 1, depth: 0, frac: 0, number: '1', pageLabel: '1'},
  {title: '연구 배경', page: 1, depth: 1, frac: 0.5, number: '1.1', pageLabel: '1'}, {title: '방법', page: 2, depth: 0, frac: 0, number: '2', pageLabel: '2'}];
  renderOutline();}"""
# [본문 3/25 ▾] as drawn: the document name's text, the pages' text and whether the name shows.
POS = "[document.querySelector('#btn-pos-n').textContent, document.querySelector('#btn-pos-p').textContent, document.querySelector('#btn-pos-n').getClientRects().length>0]"
# The open navigation sheet: its visible sections top to bottom, the visible controls that spill out of its box, and the
# focused control (a document row's key, a view radio's mode, else its id).
NAV_SHEET = """() => {const d = document.querySelector('#nav-sheet'), R = d.getBoundingClientRect(), vis = e => !!e && e.getClientRects().length > 0;
  const order = ['ns-docs', 'ns-view', 'ns-page', 'ns-outline'].map(id => document.getElementById(id)).filter(vis)
    .map(e => [e.id, e.getBoundingClientRect().top]).sort((a, b) => a[1] - b[1]);
  const spill = [...d.querySelectorAll('button,input')].filter(vis).filter(e => {const r = e.getBoundingClientRect();
    return r.left < R.left - 0.5 || r.right > R.right + 0.5;}).map(e => e.id || e.className);
  const a = document.activeElement, cur = [d.querySelector('.dm-item.on'), d.querySelector('#ns-view [aria-checked=true]')].find(vis);
  return {order, spill, focus: a.id, current: cur.dataset.doc || cur.dataset.mode};}"""
# The open [더보기]: whether a Limn icon is in the label, the label dot's fill and the instance colour, the meta's distinct line
# tops and the pieces that break across lines, the foot (wordmark, version text, [도움말]) and the rows that are gone.
MORE = """() => {const q = s => document.querySelector(s), colour = v => {const e = document.createElement('i'); e.style.background = v;
    document.body.append(e); const c = getComputedStyle(e).backgroundColor; e.remove(); return c;};
  const tops = e => {const r = document.createRange(); r.selectNodeContents(e);
    return new Set([...r.getClientRects()].filter(x => x.width > 1).map(x => Math.round(x.top)));};
  const pieces = [...document.querySelectorAll('#more-info .mc')];
  return {iconInLabel: !!q('#more-label svg'), dot: getComputedStyle(q('#more-label .more-dot')).backgroundColor, brand: colour('var(--brand)'),
    lines: new Set(pieces.map(p => Math.round(p.getBoundingClientRect().top))).size, broken: pieces.filter(p => tops(p).size > 1).map(p => p.textContent),
    foot: [!!q('#more-foot svg.limn-mark-word'), q('#more-foot .m-ver').textContent, !!q('#more-foot [data-act=help]')],
    gone: [!!q('#m-done'), !!q('#m-jump')]};}"""
# The fullest bar the width budget plans for: 123 open pins, 12 awaiting review and a draft dot (UX spec §V4 폭 예산).
FULL_BAR = """() => {document.querySelector('#side-n').textContent = '123'; const p = document.querySelector('#side-rv');
  p.hidden = false; p.innerHTML = ic('eye') + '12'; document.querySelector('#btn-side .c-dot').hidden = false;
  const r = document.querySelector('#btn-rv'); r.hidden = false; r.querySelector('.rv-c').textContent = '12'; fitBarWords();}"""


class MetaPatched:
    """A Playwright route whose fulfil merges patch into the JSON body the handler answered (the rest passes through)."""

    def __init__(self, route, patch: dict[str, object]) -> None:
        """Wrap route; patch is merged into the answer's top-level object."""
        self._route, self._patch = route, patch

    def __getattr__(self, name: str):
        """Everything but fulfill is the route's own (forward() reads its request)."""
        return getattr(self._route, name)

    def fulfill(self, status: int, headers: dict[str, str], body: bytes) -> None:
        """Fulfil the route with the handler's JSON answer, patch merged in."""
        data = json.loads(body)
        data.update(self._patch)
        self._route.fulfill(status=status, headers=headers, body=json.dumps(data))


class BarAndSheets(ViewerBase):
    """The bottom bar, the status line and the navigation and [더보기] sheets (docs/handbook/viewer.md §모바일 레이아웃, the
    PR D design): the phone and tablet-sheet bar is a three-column grid whose middle column, the grabber, is the screen's
    centre whatever the language, the counts or the document; its buttons draw no border, and [⬚] is an icon."""

    def test_the_grabber_is_at_the_screen_centre_on_every_phone_and_tablet_sheet(self):
        """The grabber was 31-89px right of the centre (UX audit P2: a flex item centred in the space left between unequal
        groups). On every phone and tablet-sheet width, in Korean and English, with the default counts and the fullest
        bar, it is the centre within 1px and nothing spills out of its cell."""
        for device in BAR_PHONES + BAR_TABLETS:
            for lang in ("ko", "en") if device["viewport"]["width"] in (411, 884) else ("ko",):
                with self.subTest(width=device["viewport"]["width"], lang=lang):
                    page = self.view(device, lang=lang)
                    bar = page.evaluate(BAR)
                    self.assertLessEqual(abs(bar["off"]), 1, bar)
                    self.assertEqual(bar["spill"], [])
                    page.evaluate(FULL_BAR)
                    bar = page.evaluate(BAR)
                    self.assertLessEqual(abs(bar["off"]), 1, bar)
                    self.assertEqual(bar["spill"], [])

    def test_the_phone_bar_draws_no_border_and_its_select_is_an_icon(self):
        """411 and 360: three bordered boxes and two ghosts were mixed (UX audit P3). Now no bar button draws a border (the
        split chip's seam is a shadow), [⬚] shows no word (its name is aria-label), the pins half says 핀 (words first, the
        owner's pick), the collapsed sheet is its 1px edge and 12 + 28 + 12px under the PDF, and every bar control still
        answers a 44px box."""
        for device in (BAR_PHONES[0], BAR_PHONES[1]):
            with self.subTest(width=device["viewport"]["width"]):
                page = self.view(device, init=NO_PNG_CHIP)
                bar = page.evaluate(BAR)
                self.assertEqual(bar["borders"], [])
                self.assertEqual(bar["select"], "")
                self.assertTrue(bar["sideWord"])
                self.assertAlmostEqual(bar["chrome"], 53, delta=1)
                self.assertEqual(page.get_attribute("#btn-select", "aria-label"), "선택")
                self.assertEqual(page.evaluate(MISSES_44, "#bar1 button,#sheet-grip"), [])

    def test_the_width_budget_pads_8px_under_400_and_keeps_8px_before_the_select(self):
        """The chip's halves pad 12px from 400px and 8px under it, then one 4px step less when the cell is snug (344, Korean);
        the left cell's gap stays 8px at every width - [⬚]'s 44px hit reaches 8px into it - and under 360px only the right
        cell's gap is 4px (UX spec §V4 폭 예산). BarChip checks the steps."""
        for device, pad, right in (
            (BAR_PHONES[0], "12px", "8px"),
            (BAR_PHONES[2], "8px", "8px"),
            (BAR_PHONES[1], "8px", "8px"),
            (BAR_PHONES[4], "4px", "4px"),
        ):
            with self.subTest(width=device["viewport"]["width"]):
                page = self.view(device)
                bar = page.evaluate(BAR)
                self.assertEqual((bar["pad"], bar["gap"]), (pad, "8px"))
                self.assertEqual(
                    page.evaluate("getComputedStyle(document.querySelector('#bar1 .bar-r')).columnGap"), right
                )

    def test_the_tablet_sheet_bar_has_only_more_in_its_right_cell(self):
        """820x1180: documents, view, page and outline are the nav bar's, so the right cell holds [⋯] alone."""
        page = self.view(BAR_TABLETS[0])
        self.assertEqual(page.evaluate(BAR)["right"], ["btn-more"])

    # ---- the status line (V8)

    def route(self, route):
        """The fixture's routes, with GET /api/build answered from self.fake_build while one is set (a running build) and
        GET /api/meta (full and light) saying stale_build while self.stale is set."""
        path = urlparse(route.request.url).path
        fake = getattr(self, "fake_build", None)
        if path == "/api/rebuild" and hasattr(
            self, "rebuilds"
        ):  # a rebuild asked for: recorded, accepted, nothing runs
            self.rebuilds.append(urlparse(route.request.url).query)
            return route.fulfill(status=202, headers={"content-type": "application/json"}, body='{"ok":true}')
        if fake and path == "/api/build":
            return route.fulfill(status=200, headers={"content-type": "application/json"}, body=json.dumps(fake))
        if getattr(self, "stale", False) and path == "/api/meta":
            return self.forward(MetaPatched(route, {"stale_build": True, "src_age_s": 120}))
        return super().route(route)

    def stale_view(self, device, **kw):
        """A view of device with a stale PDF (meta says stale_build), once the status line shows it."""
        self.stale = True
        page = self.view(device, init=NO_PNG_CHIP, **kw)
        page.wait_for_function("!document.querySelector('#status').hidden")
        settle(page)
        return page

    def test_a_stale_pdf_puts_a_24px_status_line_on_the_sheet_with_rebuild(self):
        """411x908: the 38px chip row over the bar (83px of chrome, UX audit P3) is a 24px line on the sheet's top edge -
        no gap, 77px of chrome with the sheet's 53 - saying the manuscript is newer, with [재빌드] whose 44px hit reaches up over the PDF. The
        bar has no [PDF 재빌드] and the desktop chip row is not drawn."""
        page = self.stale_view(BAR_PHONES[0])
        got = page.evaluate(STATUS_LINE)
        self.assertEqual(got["parent"], "status-dock")
        self.assertAlmostEqual(got["dock"]["b"], got["sheet"]["y"], delta=0.5)
        self.assertEqual(round(got["dock"]["h"]), 24)
        self.assertAlmostEqual(908 - got["dock"]["y"], 77, delta=1)
        self.assertEqual(got["text"], "원고가 PDF보다 새롭습니다")
        self.assertEqual(got["acts"], ["rebuild"])
        self.assertEqual(page.evaluate(MISSES_44, "#status button"), [])
        self.assertFalse(page.is_visible("#btn-rebuild"))
        self.assertFalse(page.is_visible("#bar2"))

    def test_a_running_build_shows_its_phase_and_an_indeterminate_or_counted_bar(self):
        """A LaTeX pass shows its seconds and the last build's, over a bar with no value (the last time is a reference, not
        a forecast); the page render with a progress field fills the bar to its share (12/25 = 48%)."""
        page = self.view(BAR_PHONES[0], init=NO_PNG_CHIP)
        self.fake_build = {"state": "running", "phase": "latex", "elapsed_s": 20, "last_s": 67, "seq": 0}
        page.evaluate("pollBuild()")
        page.wait_for_function("!!document.querySelector('#status .st-bar')")
        got = page.evaluate(STATUS_LINE)
        self.assertEqual(got["text"], "LaTeX 컴파일 중 · 20초 (지난번 67초)")
        self.assertEqual(got["bar"], {"role": "progressbar", "now": None})
        self.fake_build = dict(self.fake_build, phase="render", elapsed_s=30, progress={"done": 12, "total": 25})
        page.wait_for_function("document.querySelector('#status .st-bar').getAttribute('aria-valuenow')==='48'")
        self.assertEqual(page.evaluate(STATUS_LINE)["text"], "쪽 그리는 중 · 12/25쪽")
        self.fake_build = None
        page.wait_for_function("document.querySelector('#status').hidden")

    def test_a_rebuild_that_changed_nothing_says_so_on_the_line_with_build_anyway(self):
        """411x908, a stale PDF: [재빌드] on the line, and the build answers ok, unchanged, the same seq (0.4.5). On compact
        bands the line, where rebuild lives, says '변경 없음' with [그래도 빌드] - no toast. That posts force=1 and the line
        moves on. Left alone, the answer goes after a toast's six seconds and the stale PDF shows again."""
        self.rebuilds = []
        page = self.stale_view(BAR_PHONES[0])
        self.fake_build = {"state": "ok", "seq": page.evaluate("BUILD.lastSeq"), "unchanged": True, "elapsed_s": 0.2}
        page.click("#status [data-act=rebuild]")
        page.wait_for_selector("#status [data-act=rebuild-force]")
        got = page.evaluate(STATUS_LINE)
        self.assertEqual((got["text"], got["acts"]), ("변경 없음", ["rebuild-force"]))
        self.assertEqual(page.locator("#toasts .toast").count(), 0)
        self.assertEqual(page.evaluate(MISSES_44, "#status button"), [])
        self.fake_build = None
        page.click("#status [data-act=rebuild-force]")
        page.wait_for_function("!document.querySelector('#status [data-act=rebuild-force]')")
        settle(page)
        self.assertEqual(self.rebuilds, ["async=1&doc=main", "async=1&force=1&doc=main"])
        self.fake_build = {"state": "ok", "seq": page.evaluate("BUILD.lastSeq"), "unchanged": True}
        page.click("#status [data-act=rebuild]")
        page.wait_for_selector("#status [data-act=rebuild-force]")
        shown = time.monotonic()
        page.wait_for_selector("#status [data-act=rebuild]", timeout=10000)
        self.assertGreaterEqual(time.monotonic() - shown, 5.5)

    def test_typing_hides_the_status_line_and_a_toast_floats_over_its_hit(self):
        """While the note has focus the line steps aside for the keyboard; a toast sits above the line's action hit (20px
        over the line), never on it."""
        page = self.stale_view(BAR_PHONES[0])
        page.evaluate("toast('핀 #1 저장됨 · pins.md 갱신','ok')")
        settle(page)
        t = page.locator("#toasts .toast").bounding_box()
        dock = page.locator("#status-dock").bounding_box()
        self.assertLessEqual(t["y"] + t["height"], dock["y"] - 20)
        self.long_press_pick(self.cdp(page), page)
        page.focus("#note")
        page.wait_for_function("!document.querySelector('#status-dock').getClientRects().length")

    def test_every_compact_band_moves_rebuild_into_more(self):
        """[PDF 재빌드] leaves every compact bar for a row in [⋯] - a landscape phone, an unfolded foldable, a phone and a
        tablet sheet; a view-only or figure document and the viewer role have no row."""
        for device in (LAND_PHONE, FOLD, PHONE, BAR_TABLETS[0]):
            with self.subTest(width=device["viewport"]["width"]):
                page = self.view(device)
                self.assertFalse(page.is_visible("#btn-rebuild"))
                page.evaluate("openMore()")
                settle(page)
                self.assertTrue(page.is_visible("#more [data-act=rebuild]"))
                page.evaluate(
                    "()=>{document.querySelector('#more').close(); META=Object.assign({},META,{kind:'pdf'}); drawMeta();}"
                )
                page.evaluate("openMore()")
                settle(page)
                self.assertFalse(page.is_visible("#more [data-act=rebuild]"))
        page = self.view(PHONE)
        page.evaluate(
            "()=>{META=Object.assign({},META,{me:Object.assign({},META.me,{role:'viewer'})}); drawMeta(); openMore();}"
        )
        settle(page)
        self.assertFalse(page.is_visible("#more [data-act=rebuild]"))

    def test_the_mid_bar_puts_status_between_select_and_more(self):
        """842x758 and 1180x820: the action row is [⬚ 선택] · status · [⋯] [📍 N ›] with no [PDF 재빌드]; [📍] stays put
        when the panel opens and closes, and a collapsed panel floats no status card."""
        for device in (FOLD, phone(1180, 820, 2)):
            with self.subTest(width=device["viewport"]["width"]):
                page = self.stale_view(device)
                order = page.evaluate(
                    "[...document.querySelectorAll('#bar1 #btn-select,#bar1 #status-slot,#bar1 #btn-more,#bar1 #btn-side,#bar1 #btn-rebuild')]"
                    ".filter(e=>e.getClientRects().length).sort((a,b)=>a.getBoundingClientRect().left-b.getBoundingClientRect().left).map(e=>e.id)"
                )
                self.assertEqual(order, ["btn-select", "status-slot", "btn-more", "btn-side"])
                self.assertEqual(page.evaluate(STATUS_LINE)["parent"], "status-slot")
                x0 = page.locator("#btn-side").bounding_box()["x"]
                page.evaluate("setSide(!SIDE_OPEN)")
                settle(page)
                self.assertEqual(page.locator("#btn-side").bounding_box()["x"], x0)
                page.evaluate("setSide(false)")
                settle(page)
                self.assertFalse(page.is_visible("#bar2"))

    def test_the_short_band_keeps_the_page_beside_a_short_status(self):
        """844x390: the one 48px row keeps its page count while the PDF is stale; the short status sits between the view
        switch and the page count, and there is no [PDF 재빌드]."""
        page = self.stale_view(LAND_PHONE)
        row = page.evaluate(TOP_ROW)
        self.assertLessEqual(row["nav"]["h"], 48)
        self.assertTrue(page.is_visible("#nav-page"))
        got = page.evaluate(STATUS_LINE)
        self.assertEqual((got["parent"], got["text"]), ("doc-nav", "원고 수정됨"))
        xs = page.evaluate(
            "['#view-switch','#status','#nav-page'].map(s=>document.querySelector(s).getBoundingClientRect().left)"
        )
        self.assertEqual(xs, sorted(xs))
        self.assertFalse(page.is_visible("#btn-rebuild"))

    def test_the_tablet_sheet_line_stays_in_its_640_column(self):
        """The status line and the changes view's thumb row share the bar's edges: their boxes start where the bar's left
        cell starts and end where its right cell ends, within 1px - on the tablet sheet's 640px column at 768, 820 and 884
        (edge 16) and on a phone (edge 12). Review of PR D: at 768 the line's box was the whole column, so its icon sat
        4px left of [📍]'s fill and [재빌드] 16px past [⋯]; the thumb row's [확인] ended at 704 with the bar at 688."""
        edges = """(sel) => {const r = e => e.getBoundingClientRect(), q = s => document.querySelector(s);
          return {box: [r(q(sel)).left, r(q(sel)).right], bar: [r(q('#bar1 .bar-l')).left, r(q('#bar1 .bar-r')).right]};}"""
        for device in (phone(768, 1024, 2), BAR_TABLETS[0], BAR_TABLETS[1], BAR_PHONES[0]):
            with self.subTest(width=device["viewport"]["width"]):
                page = self.stale_view(device)
                line = page.evaluate(edges, "#status")
                self.assertAlmostEqual(line["box"][0], line["bar"][0], delta=1, msg=line)
                self.assertAlmostEqual(line["box"][1], line["bar"][1], delta=1, msg=line)
                page.evaluate("showChange(REVIEW_ALL[0].id)")
                page.wait_for_selector("#revision-acts .rp-acts [data-act=confirm]")
                settle(page)
                row = page.evaluate(edges, "#revision-acts .rp-acts")
                self.assertAlmostEqual(row["box"][0], row["bar"][0], delta=1, msg=row)
                self.assertAlmostEqual(row["box"][1], row["bar"][1], delta=1, msg=row)
                last = page.evaluate(
                    "document.querySelector('#revision-acts [data-act=confirm]').getBoundingClientRect().right"
                )
                self.assertAlmostEqual(last, row["bar"][1], delta=1)  # [확인] ends where [⋯] ends

    def test_the_line_keeps_its_spoken_label_through_band_changes_and_new_items(self):
        """The line's spoken label (.st-sr, the live region) always holds the item on screen - also after placeStatus()
        draws the line again for a rotation and after a second item adds '+1'. Review of PR D: it came
        back empty, as the label was filled only when it changed. It is announced only when the item changes: the live
        node stays and its text is not touched while the item is the same (a second item, main sync, adds '+1')."""
        page = self.stale_view(BAR_PHONES[0])
        say = "document.querySelector('#status .st-sr').textContent"
        self.assertEqual(page.evaluate(say), "원고가 PDF보다 새롭습니다")
        page.evaluate(
            "()=>{window.SR=document.querySelector('#status .st-sr'); window.SR_CHANGES=0;"
            "new MutationObserver(m=>{window.SR_CHANGES+=m.length;}).observe(window.SR,{childList:true,characterData:true,subtree:true});}"
        )
        for size, band in (((908, 411), "short"), ((411, 908), "phone")):
            page.set_viewport_size({"width": size[0], "height": size[1]})
            page.wait_for_function("document.body.classList.contains('band-%s')" % band)
            settle(page)
            self.assertEqual(page.evaluate(say), "원고가 PDF보다 새롭습니다", band)
        page.evaluate("()=>{STATUS_SYNC={state:'checking'}; drawStatus();}")  # a second item: '+1
        page.wait_for_selector("#status .st-more")
        self.assertEqual(page.evaluate(say), "원고가 PDF보다 새롭습니다")
        self.assertEqual(
            page.evaluate("[document.querySelector('#status .st-sr')===window.SR, window.SR_CHANGES]"), [True, 0]
        )
        self.fake_build = {"state": "running", "phase": "latex", "elapsed_s": 3, "last_s": 9, "seq": 0}
        page.evaluate("pollBuild()")
        page.wait_for_function(say + "==='LaTeX 컴파일 중'")
        self.assertGreater(page.evaluate("window.SR_CHANGES"), 0)  # a new item is spoken
        self.fake_build = None

    def test_a_mouse_desktop_keeps_its_rebuild_button_and_chips(self):
        """1440x900 with a mouse: [PDF 재빌드] in the tool bar and the chip row, no status line."""
        page = self.stale_view(MOUSE_WIDE)
        self.assertTrue(page.is_visible("#btn-rebuild"))
        self.assertTrue(page.is_visible("#meta-stale"))
        self.assertFalse(page.is_visible("#status"))

    def test_two_states_show_the_first_and_a_plus_that_lists_both(self):
        """A failed build and a stale PDF: the line shows the failure with [보기] and '+1'; '+1' lists both as 44px rows
        with their actions, and Esc folds the list."""
        page = self.stale_view(BAR_PHONES[0])
        page.evaluate("showBuildErr({state:'fail',errors:[],log:''}); hideBuildErr();")
        page.wait_for_function("document.querySelector('#status .st-more')")
        got = page.evaluate(STATUS_LINE)
        self.assertEqual(
            (got["text"], got["acts"]), ("빌드 실패 · 이전 PDF를 보는 중", ["status-more", "build-err-reopen"])
        )
        page.click("#status .st-more")
        page.wait_for_function("document.querySelector('#status-list').open")
        rows = page.evaluate(
            "[...document.querySelectorAll('#status-list .st-row')].map(r=>[Math.round(r.getBoundingClientRect().height),"
            "r.querySelector('button')&&r.querySelector('button').dataset.act])"
        )
        self.assertEqual(rows, [[44, "build-err-reopen"], [44, "rebuild"]])
        page.keyboard.press("Escape")
        page.wait_for_function("!document.querySelector('#status-list').open")

    # ---- the phone's navigation sheet and the nav bar's page field (V9)

    def docs_view(self, device, init="", **kw):
        """A view with three documents (the manuscript, a figure and a view-only PDF of two pages each) and an outline of
        three headings (the test PDFs carry none), once booted."""
        helpers_figure.viewer_docs(ps.APP, ps.APP.C.src)
        self.addCleanup(ps.APP.set_docs, None)
        page = self.view(device, init=NO_PNG_CHIP + init, **kw)
        page.evaluate(OUTLINE3)
        settle(page)
        return page

    def open_nav(self, page):
        """Tap [본문 1/2 ▾] and wait for the navigation sheet."""
        self.tap(self.cdp(page), *self.center(page, "#btn-pos"))
        page.wait_for_function("document.querySelector('#nav-sheet').open")
        settle(page)

    def test_the_current_documents_check_stands_apart_from_its_name(self):
        """The current document's row in the navigation sheet: 4-6px between its name and the check (review of PR D: they
        touched, '본문✓')."""
        page = self.docs_view(BAR_PHONES[0])
        self.open_nav(page)
        gap = page.evaluate(
            "(()=>{const nm=document.querySelector('#ns-docs-list .dm-item.on .nm'),t=document.createRange();"
            "t.selectNodeContents(nm.firstChild);return nm.querySelector('svg').getBoundingClientRect().left-t.getBoundingClientRect().right;})()"
        )
        self.assertGreaterEqual(gap, 4)
        self.assertLessEqual(gap, 6)

    def test_the_bars_right_end_is_optically_even(self):
        """[⋯]'s ink ends on the ink line (--ink: 24px from a phone's edge, 28 from the tablet column's), within R2's 2px, as
        the left end's chip starts on the edge line. (The pin glyph's side-bearing correction is gone with the glyph: the
        sheet bar is words first, and BarChip measures its centres.)"""
        for device, ink in ((BAR_PHONES[0], 24), (BAR_PHONES[1], 24), (BAR_TABLETS[1], 28)):
            with self.subTest(width=device["viewport"]["width"]):
                page = self.view(device, init=NO_PNG_CHIP)
                got = page.evaluate(OPTICAL)
                self.assertAlmostEqual(got["moreInk"], ink, delta=2, msg=got)

    def test_the_notification_switch_shows_when_off_and_names_its_reason(self):
        """The switch's off track reaches 3:1 against the sheet where it can be switched (review of PR D: 1.48:1 light,
        1.7:1 dark); the reason line under it is its description (aria-describedby)."""
        for dark in (False, True):
            with self.subTest(dark=dark):
                page = self.view(BAR_PHONES[0], dark=dark)
                page.evaluate("openMore()")
                settle(page)
                self.assertGreaterEqual(page.evaluate(SWITCH_OFF), 3)
                self.assertEqual(page.get_attribute("#m-notify", "aria-describedby"), "m-notify-why")

    def test_the_touch_help_names_the_bars_icon_buttons(self):
        """The help's touch table shows the bar's controls as they are drawn: the words-first pair [핀 N] [검토 M] and [⬚]'s
        four-corner icon (it showed the pin glyph and the dashed square the sheet bar no longer draws)."""
        src = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
        self.assertIn("<kbd>핀 N</kbd> <kbd>검토 M</kbd>", src)
        self.assertIn("<kbd>{{ic:focus}}</kbd>", src)
        self.assertNotIn("<kbd>{{ic:pin}} N</kbd>", src)
        self.assertNotIn("<kbd>선택</kbd>", src)

    def test_the_position_button_opens_documents_view_page_and_outline_in_that_order(self):
        """411 and 344: [본문 1/2 ▾] - the document's name from 400px - opens one sheet whose sections run documents, the
        view switch, the page field and the outline, all inside the sheet, the sheet itself focused (SheetFocus) and the
        current document's row marked. P5: the phone had no way to the outline or the changes view."""
        for device, name in ((BAR_PHONES[0], "본문"), (BAR_PHONES[4], "")):
            with self.subTest(width=device["viewport"]["width"]):
                page = self.docs_view(device)
                self.assertEqual(page.evaluate(POS), [name, "1/2", bool(name)])
                self.open_nav(page)
                got = page.evaluate(NAV_SHEET)
                self.assertEqual([s for s, _ in got["order"]], ["ns-docs", "ns-view", "ns-page", "ns-outline"])
                self.assertEqual(got["spill"], [])
                self.assertEqual((got["focus"], got["current"]), ("nav-sheet", "ms"))
                self.assertEqual(page.evaluate(MISSES_44, "#nav-sheet button,#nav-sheet input"), [])

    def test_the_current_section_scrolls_up_only_as_far_as_the_focused_row_stays_under_the_head(self):
        """The sheet brings the outline's current section towards the middle of the space under its sticky head, but never
        so far that the current document's row goes under the head (the evidence run at 411 found the row 37px under it, a
        cut-off highlighted row). A section already in view stays where it is; a deep one comes as close as that allows."""
        for selected in (2, 25):
            with self.subTest(selected=selected):
                page = self.docs_view(BAR_PHONES[0])
                page.evaluate(
                    "n=>{OUTLINE_ENTRIES=Array.from({length:30},(_,i)=>({title:'절 '+(i+1),page:1+(i%2),depth:i%3?1:0,"
                    "frac:0,number:String(i+1),pageLabel:String(1+(i%2))})); updateSectionStrip=()=>{}; OUTLINE_SELECTED=n;"
                    " renderOutline();}",
                    selected,
                )  # an outline longer than the sheet, its current section fixed (the reading line would move it)
                self.open_nav(page)
                got = page.evaluate(
                    "(()=>{const d=document.getElementById('nav-sheet'),h=d.querySelector('.ns-head').getBoundingClientRect(),"
                    "f=d.querySelector('.dm-item.on').getBoundingClientRect(),a=d.querySelector('#ns-outline-items .ol-active')"
                    ".getBoundingClientRect(),D=d.getBoundingClientRect();"
                    "return {gap:Math.round(f.top-h.bottom),st:d.scrollTop,active:[Math.round(a.top),Math.round(a.bottom)],"
                    "head:Math.round(h.bottom),bottom:Math.round(D.bottom),focus:d.querySelector('.dm-item.on').dataset.doc};})()"
                )
                self.assertEqual(got["focus"], "ms", got)
                self.assertGreaterEqual(got["gap"], 0, got)  # the current row is whole, under the head
                if selected == 2:
                    self.assertEqual(got["st"], 0, got)  # in view already: the sheet opens at its top
                else:
                    self.assertGreater(got["st"], 0, got)  # a deep section: the sheet scrolls towards it
                    self.assertEqual(got["gap"], 0, got)  # ...exactly as far as the current row allows

    def test_every_choice_goes_there_and_closes_the_sheet(self):
        """Picking is going: [변경사항] opens the changes view (the button then reads 변경사항), a page past the end goes to
        the last page, an outline entry to its section, a document row switches - and each closes the sheet. An empty page
        field does nothing."""
        page = self.docs_view(BAR_PHONES[0])
        closed = "!document.querySelector('#nav-sheet').open"
        self.open_nav(page)
        page.click("#ns-view [data-mode=revisions]")
        page.wait_for_function(closed + "&&document.body.classList.contains('revision-open')")
        self.assertEqual(page.inner_text("#btn-pos-p"), "변경사항")
        self.open_nav(page)
        page.click("#ns-view [data-mode=manuscript]")
        page.wait_for_function(closed + "&&!document.body.classList.contains('revision-open')")
        self.open_nav(page)
        page.press("#ns-page-in", "Enter")
        self.assertTrue(page.evaluate("document.querySelector('#nav-sheet').open"))
        page.fill("#ns-page-in", "99")
        page.press("#ns-page-in", "Enter")
        page.wait_for_function(closed + "&&topAnchor().page===2")
        self.open_nav(page)
        page.click("#ns-outline-items [data-index='0']")
        page.wait_for_function(closed + "&&OUTLINE_SELECTED===0&&topAnchor().page===1")
        self.open_nav(page)
        page.click("#nav-sheet .dm-item[data-doc=rv]")
        page.wait_for_function(closed + "&&DOC==='rv'")

    def test_close_esc_an_outside_tap_a_pull_and_back_close_it_and_change_nothing(self):
        """[닫기], Esc (Chrome's close request for the back gesture), a tap outside and a pull down past 35% close the sheet
        and do nothing else; the focus returns to [본문 1/2 ▾]. Without CloseWatcher the back gesture closes it and stays in
        Limn."""
        page = self.docs_view(BAR_PHONES[0])
        cdp = self.cdp(page)
        state = "[DOC, document.body.classList.contains('revision-open'), topAnchor().page, SIDE_OPEN]"
        before = page.evaluate(state)
        closed = "!document.querySelector('#nav-sheet').open"
        for way in ("close", "esc", "outside", "pull"):
            with self.subTest(way=way):
                self.open_nav(page)
                if way == "close":
                    page.click("#nav-sheet [data-act=nav-sheet-close]")
                elif way == "esc":
                    page.keyboard.press("Escape")
                elif way == "outside":
                    self.tap(cdp, 200, 30)
                else:
                    r = page.locator("#nav-sheet").bounding_box()
                    self.swipe(cdp, 200, r["y"] + 6, 200, r["y"] + 6 + r["height"] * 0.6, steps=10, dt=0.02)
                page.wait_for_function(closed)
                settle(page)
                self.assertEqual(page.evaluate(state), before)
                if way in ("close", "esc"):
                    self.assertEqual(page.evaluate("document.activeElement.id"), "btn-pos")
        page = self.docs_view(BAR_PHONES[0], init=NO_CLOSE_WATCHER)
        boot = page.evaluate("window.__pinViewerBoot")
        self.open_nav(page)
        page.wait_for_function("BACK&&BACK.kind==='history'")
        page.go_back()
        page.wait_for_function(closed)
        self.assertEqual(page.evaluate("window.__pinViewerBoot"), boot)

    def test_one_document_and_no_outline_leave_their_sections_out(self):
        """One document: nothing to switch to, so no documents section and no name on the button; a PDF without an outline:
        no outline section. The view switch's checked radio is then the current row."""
        page = self.view(BAR_PHONES[0], init=NO_PNG_CHIP)
        self.assertEqual(page.evaluate(POS), ["", "1/2", False])
        self.open_nav(page)
        got = page.evaluate(NAV_SHEET)
        self.assertEqual([s for s, _ in got["order"]], ["ns-view", "ns-page"])
        self.assertEqual((got["focus"], got["current"]), ("nav-sheet", "manuscript"))

    def test_unfolding_with_the_sheet_open_closes_it_and_keeps_the_note_and_the_spot(self):
        """A folded 344x882 with a note being written and the sheet open, unfolded to 884x1104 (the tablet sheet, whose nav
        bar does this job): the sheet closes, and the note and the reading spot stay (s10_fold_cover)."""
        page = self.docs_view(BAR_PHONES[4])
        self.long_press_pick(self.cdp(page), page)
        page.fill("#note", "펼치기 전 메모")
        page.evaluate("document.activeElement.blur()")
        page.evaluate("openNavSheet()")
        settle(page)
        spot = page.evaluate("topAnchor().page")
        page.set_viewport_size({"width": 884, "height": 1104})
        page.wait_for_function("BAND==='tablet-sheet'&&!document.querySelector('#nav-sheet').open")
        settle(page)
        self.assertEqual(
            page.evaluate("[document.querySelector('#note').value, topAnchor().page]"), ["펼치기 전 메모", spot]
        )

    def test_the_nav_bars_page_count_becomes_a_page_field(self):
        """820x1180: the nav bar's '1 / 2쪽' is a button named for what it does; a tap turns it into a page field with the
        page selected, Enter goes there, and Esc gives the count back without moving."""
        page = self.view(BAR_TABLETS[0], init=NO_PNG_CHIP)
        self.assertEqual(page.get_attribute("#nav-page", "aria-label"), "쪽 번호로 이동 · 1 / 2쪽")
        self.tap(self.cdp(page), *self.center(page, "#nav-page"))
        page.wait_for_function("document.activeElement.id==='nav-page-in'")
        self.assertEqual(page.evaluate("[document.activeElement.value, document.activeElement.selectionEnd]"), ["1", 1])
        page.keyboard.type("2")
        page.keyboard.press("Enter")
        page.wait_for_function("topAnchor().page===2&&document.querySelector('#nav-page-in').hidden")
        self.assertTrue(page.is_visible("#nav-page"))
        self.tap(self.cdp(page), *self.center(page, "#nav-page"))
        page.wait_for_function("document.activeElement.id==='nav-page-in'")
        page.keyboard.press("Escape")
        page.wait_for_function("document.querySelector('#nav-page-in').hidden")
        self.assertEqual(page.evaluate("topAnchor().page"), 2)

    # ---- [더보기] (V7)

    def more_view(self, device, **kw):
        """A view of device with [더보기] open."""
        page = self.view(device, init=NO_PNG_CHIP, **kw)
        page.evaluate("openMore()")
        settle(page)
        return page

    def test_more_has_a_dot_label_two_meta_lines_and_the_brand_at_its_foot(self):
        """411x908, Korean and English: the label is the instance colour's dot and the name, with no Limn icon in it (the
        icon read as the label's decoration, UX audit P4.1); the meta is two lines and no piece breaks inside (it was one
        line cut at '…', P4.2); the foot is the Limn wordmark, 'v' and the version, and [도움말]. The closed-pins row and the
        page field are gone."""
        for lang in ("ko", "en"):
            with self.subTest(lang=lang):
                got = self.more_view(BAR_PHONES[0], lang=lang).evaluate(MORE)
                self.assertFalse(got["iconInLabel"])
                self.assertEqual(got["dot"], got["brand"])
                self.assertEqual(got["lines"], 2)
                self.assertEqual(got["broken"], [])
                self.assertEqual(got["foot"], [True, "v" + __version__, True])
                self.assertEqual(got["gone"], [False, False])

    def test_theme_and_language_are_segments_that_show_the_current_value(self):
        """The theme was a cycle whose next value was unknown until pressed (P4.5): [시스템 | 밝게 | 어둡게] checks the current
        one and a tap applies its value at once; under 시스템 a line says what it is now. The language showed the other
        language's name (P4.4): [한국어 | English] checks the current one; the checked one does nothing, the other saves the
        choice (limnLang) and reloads in it, the tab's draft kept."""
        page = self.more_view(BAR_PHONES[0])
        checked = "s=>document.querySelector(s+' [aria-checked=true]').dataset"
        self.assertEqual(page.evaluate(checked, "#m-theme")["theme"], "light")
        self.tap(self.cdp(page), *self.center(page, "#m-theme [data-theme=dark]"))
        page.wait_for_function("document.documentElement.dataset.theme==='dark'")
        self.assertEqual(page.evaluate(checked, "#m-theme")["theme"], "dark")
        self.tap(self.cdp(page), *self.center(page, "#m-theme [data-theme=system]"))
        page.wait_for_function("!document.querySelector('#m-theme-now').hidden")
        self.assertEqual(page.inner_text("#m-theme-now"), "지금 밝게")
        self.assertEqual(page.evaluate(checked, "#m-lang")["lang"], "ko")
        boot = page.evaluate("window.__pinViewerBoot")
        page.evaluate("sessionStorage.setItem('limnDraft:test','{\"note\":\"쓰던 메모\"}')")
        self.tap(self.cdp(page), *self.center(page, "#m-lang [data-lang=ko]"))
        nothing_follows(page)
        self.assertEqual(page.evaluate("window.__pinViewerBoot"), boot)
        with page.expect_navigation():
            self.tap(self.cdp(page), *self.center(page, "#m-lang [data-lang=en]"))
        page.wait_for_function(BOOTED, timeout=20000)
        self.assertEqual(
            page.evaluate(
                "[document.documentElement.lang, localStorage.getItem('limnLang'), sessionStorage.getItem('limnDraft:test')]"
            ),
            ["en", "en", '{"note":"쓰던 메모"}'],
        )

    def test_zoom_shows_its_percentage(self):
        """[더보기]'s zoom had no feedback but the 449px of page above the sheet (P11): the figure between [−] and [+] says
        it - 100% fitted, 144% after two steps."""
        page = self.more_view(BAR_PHONES[0])
        self.assertEqual(page.inner_text("#m-zoom"), "100%")
        for _ in range(2):
            page.click("#more [data-act=zoom-in]")
        page.wait_for_function("document.querySelector('#m-zoom').textContent==='144%'")

    def test_notifications_are_a_switch_with_its_reason_underneath(self):
        """The row mixed the state into its name ('Notifications: Not available on this address', P4.7): it is a switch
        named 브라우저 알림, and where it cannot turn on - here not a secure address, or a local identity - it is off and
        disabled with the reason on a line under it."""
        page = self.more_view(BAR_PHONES[0])
        sw = (
            "()=>{const s=document.querySelector('#m-notify'),w=document.querySelector('#m-notify-why');"
            "return [s.getAttribute('role'),s.getAttribute('aria-checked'),s.disabled,s.querySelector('.lbl').textContent,w.hidden?null:w.textContent];}"
        )
        self.assertEqual(
            page.evaluate(sw),
            ["switch", "false", True, "브라우저 알림", "https 테일넷 주소나 http://127.0.0.1에서만 됩니다"],
        )
        page.evaluate("()=>{META=Object.assign({},META,{me:{login:'local'}}); drawNotify();}")
        self.assertEqual(page.evaluate(sw)[4], "테일넷 주소로 열면 켤 수 있습니다")

    def test_a_landscape_phone_scrolls_more_under_its_sticky_head(self):
        """908x411: three rows were cut below a 360px sheet (P4.9). The sheet is at most the screen less 48px; scrolled to
        its end the head (label and [닫기]) is still at its top and the foot is inside it."""
        page = self.more_view(touch_device(908, 411))
        box = page.locator("#more").bounding_box()
        self.assertLessEqual(box["height"], 411 - 48 + 1)
        page.evaluate("document.querySelector('#more').scrollTop=1e6")
        settle(page)
        got = page.evaluate(
            "()=>{const d=document.querySelector('#more').getBoundingClientRect(),h=document.querySelector('#more .more-top').getBoundingClientRect(),"
            "f=document.querySelector('#more-foot').getBoundingClientRect(); return [h.top-d.top<=1.5, f.bottom<=d.bottom+0.5, document.querySelector('#more').scrollTop>0];}"
        )
        self.assertEqual(got, [True, True, True])


# ---------------------------------------------------------------- the cross-resolution pass (after 0.4.8)


# The four sheets and dialogs, by the function that opens each, and its element.
OPENERS = (
    ("openMore()", "#more"),
    ("openNavSheet()", "#nav-sheet"),
    ("openHelp()", "#help"),
    ("openTrash()", "#trash"),
)


# The open help's head, for an ink measure as FOOT_BOXES: the clip round it and, inside it, the boxes of the wordmark and of the
# title's text ('— 사용법'), each with its ink colour's luminance, and the dialog's.
HELP_HEAD = """() => {const h = document.querySelector('#help-h'), H = h.getBoundingClientRect(), clip = {x: 0, y: H.top - 8, width: innerWidth, height: H.height + 16};
  const lum = c => {const m = c.match(/[\\d.]+/g).map(Number); return 0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2];};
  const box = (r, color, pad) => [r.left - clip.x, r.top - clip.y - pad, r.right - clip.x, r.bottom - clip.y + pad, lum(color)];
  const w = h.querySelector('svg.limn-mark-word'), t = h.querySelector('span'), rg = document.createRange(); rg.selectNodeContents(t);
  return {clip, bg: lum(getComputedStyle(document.querySelector('#help')).backgroundColor), height: w.getBoundingClientRect().height,
    boxes: {word: box(w.getBoundingClientRect(), getComputedStyle(w.querySelector('.limn-mark-stroke')).fill, 2),
      title: box(rg.getBoundingClientRect(), getComputedStyle(t).color, 4)}};}"""


class HelpHeadInk(ViewerBase):
    """Help's head (docs/handbook/viewer.md §마크와 파비콘): the same rule as [더보기]'s foot - the wordmark ends on the ink line
    of the words beside it. Its 20px box was centred on the row and "limn" stood 3.3px below '— 사용법'; now it drops by the
    title's Hangul ink descent (headInk) onto the title's ink bottom."""

    def ink(self, page, dpr):
        """The head's measured ink edges (CSS px): open help, screenshot the head, read each box's ink."""
        page.evaluate("openHelp()")
        settle(page)
        f = page.evaluate(HELP_HEAD)
        b64 = base64.b64encode(page.screenshot(clip=f["clip"])).decode()
        return f, page.evaluate(INK, [b64, dpr, f["boxes"], f["bg"]])

    def test_the_wordmark_and_the_title_end_on_one_ink_line(self):
        """411x908 at DPR 2.625 and the 1400x850 mouse dialog at DPR 2, light and dark: the wordmark's and the title's ink
        bottoms are within 0.5px (3.3px apart before); the wordmark stays 20px tall. A 1x screen is left out: there the
        glyphs are hinted to whole pixels, and how far a fallback Hangul font's ink then reaches below its measured descent
        depends on the font (1.2px under CI-like fonts, where the measure itself is a pixel coarse)."""
        for device, dpr in ((phone(411, 908), 2.625), (dict(DESK, device_scale_factor=2), 2)):
            for dark in (False, True):
                with self.subTest(width=device["viewport"]["width"], dpr=dpr, dark=dark):
                    page = self.view(device, dark=dark)
                    f, ink = self.ink(page, dpr)
                    self.assertLessEqual(abs(ink["word"]["bottom"] - ink["title"]["bottom"]), 0.5, ink)
                    self.assertEqual(f["height"], 20)


# An open sheet's head: the grab band's top and its centre's offset from the sheet's (null without one), and, scrolled to its
# end, how far [닫기] is from the sheet's top and whether it scrolled at all.
SHEET_HEAD = """sel => {const d = document.querySelector(sel), D = d.getBoundingClientRect(), g = d.querySelector('.ns-grab');
  const G = g && g.getClientRects().length ? g.getBoundingClientRect() : null;
  const close = [...d.querySelectorAll('button')].find(b => /^(닫기|Close)$/.test(b.textContent.trim()));
  d.scrollTop = 1e6; const scrolled = d.scrollTop > 0, C = close.getBoundingClientRect(); d.scrollTop = 0;
  return {grab: G ? [Math.round(G.top - D.top), Math.round(G.left + G.width / 2 - (D.left + D.width / 2))] : null,
    close: Math.round(C.top - D.top), scrolled};}"""


class OneSheetHead(ViewerBase):
    """One bottom sheet (docs/handbook/viewer.md §모바일 레이아웃): [더보기] and the navigation sheet open under a grab band
    whose head (title and [닫기]) stays as the sheet scrolls; help and the Trash, bottom sheets too, had neither - no band,
    and help's [닫기] scrolled away with its long tour. Every compact sheet now has the band and the sticky head; the mouse
    desktop's centred dialogs draw no band."""

    def test_every_compact_sheet_has_the_grab_band_and_a_head_that_stays(self):
        """411x908 and 768x1024: [더보기], the navigation sheet, help and the Trash start with the band right under their
        1px top border, centred; help scrolled to its end still has [닫기] at its top (it had scrolled 1192px away)."""
        self.drop_one()
        for w, h in ((411, 908), (768, 1024)):
            page = self.view(touch_device(w, h))
            for opener, sel in OPENERS:
                with self.subTest(w=w, sheet=sel):
                    page.evaluate(opener)
                    settle(page)
                    got = page.evaluate(SHEET_HEAD, sel)
                    self.assertEqual(got["grab"], [1, 0], got)
                    if sel == "#help":
                        self.assertTrue(got["scrolled"])
                    self.assertLessEqual(got["close"], 24, got)
                    page.evaluate("s=>document.querySelector(s).close()", sel)
                    settle(page)

    def test_the_desktop_dialogs_draw_no_band(self):
        """1400x850 mouse: help and the Trash stay centred dialogs without the band."""
        page = self.view(DESK)
        for opener, sel in OPENERS[2:]:
            with self.subTest(sheet=sel):
                page.evaluate(opener)
                settle(page)
                self.assertIsNone(page.evaluate(SHEET_HEAD, sel)["grab"])
                page.evaluate("s=>document.querySelector(s).close()", sel)

    def drop_one(self):
        """One deleted pin, so the Trash has a row (SheetEdgeGrid.drop_one)."""
        SheetEdgeGrid.drop_one(self)


class SegmentedControlMouse(ViewerBase):
    """The one segmented control with a mouse (docs/handbook/viewer.md §컴포넌트): the touch rule drew the track at 36px with
    a 28px thumb, but a mouse kept the old segments sized by their text - a 34.8px track round 26.8px thumbs - on the
    desktop composer and edit card and in the mouse-window [더보기] and navigation sheet. Every track is 36px on every
    pointer; the thumb is the desktop control height (28px)."""

    compose = SegmentedControl.compose
    every_control = SegmentedControl.every_control

    def test_every_mouse_track_is_36px_with_its_thumb_inset_4px_and_the_radius_rule(self):
        """1400x850 (the composer and the edit card) and 1000x800 ([더보기] and the navigation sheet too): 36px tracks, the
        thumb 4px in all round, its radius the track's less 4 (it was 34.8px round 26.8px thumbs)."""
        for device in (DESK, MOUSE_MID):
            page = self.view(device)
            for where, segs in self.every_control(page):
                for s in segs:
                    with self.subTest(width=device["viewport"]["width"], where=where, seg=s["id"]):
                        got = [s["h"], s["top"], s["bottom"], s["left"], s["right"], s["rTrack"] - s["rThumb"]]
                        self.assertEqual(got, [36, 4, 4, 4, 4, 4], s)


class MidComposerOrder(ViewerBase):
    """The composer's order on the mid bands (docs/handbook/viewer.md §패널 정리): the phone, tablet sheet and landscape phone
    put the note under the location line and the range block last, but the unfolded Fold and the side-panel tablets kept the
    old order - the range block, the source and the kind before the note, which sat at the panel's foot. Every compact band
    now draws the one order."""

    compose = ComposerSamePass.compose

    def test_every_compact_band_puts_the_note_second_and_the_range_block_last(self):
        """880x790 (overlay), 1180x820 (side panel, touch) and 1000x800 (a mouse window): location, note, kind, overlap,
        range block, each one 8px step from the next."""
        for device in (touch_device(880, 790), touch_device(1180, 820), MOUSE_MID):
            with self.subTest(width=device["viewport"]["width"]):
                page = self.view(device)
                self.compose(page)
                b = page.evaluate(COMPOSER_BLOCKS, "#composer")
                self.assertEqual([x[0] for x in b], ["c-loc-row", "note", "c-kind", "c-overlap", "c-range"], b)
                self.assertEqual({round(n[1] - p[2]) for p, n in zip(b, b[1:], strict=False)}, {8}, b)


# The visible buttons and fields of the composer and its save row that draw a border (one that differs from their fill), by id
# or class.
COMPOSER_BORDERS = """() => [...document.querySelectorAll('#composer button,#composer input,#composer textarea,#c-actions button')]
  .filter(e => e.getClientRects().length).filter(e => {const c = getComputedStyle(e);
    return parseFloat(c.borderTopWidth) > 0 && c.borderTopStyle !== 'none' && c.borderTopColor !== 'rgba(0, 0, 0, 0)' && c.borderTopColor !== c.backgroundColor;})
  .map(e => e.id || e.className)"""


class ComposerOneBorder(ViewerBase):
    """One border in the composer (docs/handbook/viewer.md §한 겹 담기 - the note field's): the save row's [취소] was an
    outlined box beside the edit card's filled one in the same bottom row, the overlap notice's [덧붙이기] [따로 저장] were
    outlined, and the mouse desktop kept [⧉] as a bordered box beside the location line. Every band: [취소] and the overlap
    actions are the secondary fill the edit card's [취소] has, [⧉] a ghost icon."""

    def test_only_the_note_field_draws_a_border_on_every_band(self):
        """411x908, 1180x820 (touch) and 1400x850 (mouse): of the composer's and its save row's controls only the note
        field draws a border; [취소] is filled with --secondary (it and the overlap actions were outlined everywhere, and
        [⧉] on the desktop)."""
        sec = "(()=>{const e=document.createElement('i'); e.style.background='var(--secondary)'; document.body.append(e); const c=getComputedStyle(e).backgroundColor; e.remove(); return c;})()"
        for device in (phone(411, 908), touch_device(1180, 820), DESK):
            with self.subTest(width=device["viewport"]["width"]):
                page = self.view(device)
                if device is DESK:
                    self.mouse_pick(page)
                else:
                    ComposerSamePass.compose(self, page)
                self.assertEqual(page.evaluate(COMPOSER_BORDERS), ["note"])
                self.assertEqual(
                    page.evaluate("getComputedStyle(document.querySelector('#btn-cancel')).backgroundColor"),
                    page.evaluate(sec),
                )


class TouchFieldsAnswer44(ViewerBase):
    """Text fields on touch (docs/handbook/viewer.md §모바일 레이아웃 터치 기기 크기): the 44px floor held for buttons, but the
    navigation sheet's page field was 43px (16px text, 8px padding), the nav bar's page field 36px and the outline overlay's
    search 37px."""

    def test_the_page_fields_and_the_outline_searches_answer_44px(self):
        """411x908: the navigation sheet's page field and outline search; 820x1180: the nav bar's page field once tapped
        open, and the outline overlay's search."""
        page = self.view(phone(411, 908))
        page.evaluate("openNavSheet()")
        settle(page)
        self.assertEqual(page.evaluate(MISSES_44, "#ns-page-in,#ns-outline-search"), [])
        page = self.view(phone(820, 1180, 2))
        self.tap(self.cdp(page), *self.center(page, "#nav-page"))
        page.wait_for_function("document.activeElement===document.querySelector('#nav-page-in')")
        settle(page)
        self.assertEqual(page.evaluate(MISSES_44, "#nav-page-in"), [])
        page.keyboard.press("Escape")
        page.evaluate("toggleOutline&&toggleOutline()")
        settle(page)
        self.assertEqual(page.evaluate(MISSES_44, "#outline-search"), [])


class KeyModalityLogic(unittest.TestCase):
    """keyNavigates(): which key presses make the keyboard the input the focus ring answers (docs/handbook/viewer.md §뜻과
    모양) - any key outside a text field, and in one only a key that leaves or acts (Tab, Escape, or with Ctrl/⌘/Alt); typing,
    a touch keyboard's letters and an IME's composing key included, is not."""

    def test_typing_in_a_field_is_not_navigation_but_tab_escape_and_shortcuts_are(self):
        """Outside a field '?', Tab and Shift count; in a field 'a', Enter and a composing key do not, Tab, Escape and
        Ctrl+Enter do; an 'Unidentified' key (Android's touch keyboard) never counts."""
        js = "\n".join(
            [
                extract_js_fn("keyNavigates"),
                "console.log(JSON.stringify([keyNavigates('?',false,false),keyNavigates('Tab',false,false),"
                "keyNavigates('Shift',false,false),keyNavigates('a',true,false),keyNavigates('Enter',true,false),"
                "keyNavigates('Process',true,false),keyNavigates('Tab',true,false),keyNavigates('Escape',true,false),"
                "keyNavigates('Enter',true,true),keyNavigates('Unidentified',false,false)]));",
            ]
        )
        self.assertEqual(node_or_skip(self, js), [True, True, True, False, False, False, True, True, True, False])


class SheetCloseFocus(ViewerBase):
    """The focus a sheet gives back draws no ring after a press (docs/handbook/viewer.md §뜻과 모양). A sheet now takes the
    first focus itself (SheetFocus), but closing one still hands the focus back by script - the navigation sheet to
    [본문 1/2 ▾], help to what had it - and Chrome rings a script focus whenever the last input it counted was a key, which a
    tap on Android did not reset: the owner's ring on [닫기], one step later. html[data-input] says which input the ring
    answers: after a press no control draws it (a text field excepted); after a key it does."""

    STATE = SheetFocus.STATE

    def press_off_the_controls(self, page, cdp):
        """A tap on the PDF's top margin: a press that moves no focus, as a tap on Android's bar does not."""
        x, y = self.on_page(page, 0.9, 0.02)
        self.tap(cdp, x, y)
        settle(page)

    def given_back(self, page, opener, sheet):
        """Opens sheet by opener and closes it: [what has the focus then, its outline style]."""
        page.evaluate(opener)
        settle(page)
        page.evaluate("id=>document.getElementById(id).close()", sheet)
        settle(page)
        return page.evaluate(self.STATE)

    def test_the_focus_given_back_after_a_press_draws_no_ring(self):
        """411x908: a key press, a tap that moves no focus, then the navigation sheet opens and closes - [본문 1/2 ▾] gets
        the focus back with no outline (it was solid); the same after help, which gives it back to [본문 1/2 ▾] too."""
        page = self.view(phone(411, 908), init=NO_PNG_CHIP)
        cdp = self.cdp(page)
        for opener, sheet in (("openNavSheet()", "nav-sheet"), ("openHelp()", "help")):
            with self.subTest(sheet=sheet):
                page.keyboard.press("Shift")
                self.press_off_the_controls(page, cdp)
                self.assertEqual(self.given_back(page, opener, sheet), ["btn-pos", "none"])

    def test_the_focus_given_back_after_a_key_keeps_the_ring(self):
        """A guard, 411x908: a tap, then Tab - the keyboard is the input again - then the navigation sheet opens and closes:
        [본문 1/2 ▾] is ringed."""
        page = self.view(phone(411, 908), init=NO_PNG_CHIP)
        self.press_off_the_controls(page, self.cdp(page))
        page.keyboard.press("Tab")
        self.assertEqual(self.given_back(page, "openNavSheet()", "nav-sheet"), ["btn-pos", "solid"])

    def test_a_tapped_text_field_keeps_its_ring(self):
        """411x908: the note field tapped after a pick keeps its ring - it shows where the typing goes."""
        page = self.view(phone(411, 908), init=NO_PNG_CHIP)
        cdp = self.cdp(page)
        self.long_press_pick(cdp, page)
        self.tap(cdp, *self.center(page, "#note"))
        settle(page)
        self.assertEqual(page.evaluate(self.STATE), ["note", "solid"])


class DesktopDialogClose(ViewerBase):
    """One [닫기] (docs/handbook/viewer.md §한 겹 담기): every compact sheet's [닫기] is a ghost, but the mouse desktop's help
    and Trash kept an outlined [닫기] inside their bordered dialog - an outline inside an outline."""

    def test_the_desktop_help_and_trash_close_are_ghosts(self):
        """1400x850: help's and the Trash's [닫기] draw no border and no fill (they drew the --input border)."""
        page = self.view(DESK)
        for opener, sel in OPENERS[2:]:
            with self.subTest(sheet=sel):
                page.evaluate(opener)
                settle(page)
                got = page.evaluate(
                    "s=>{const b=document.querySelector(s+' [data-act$=close]'),c=getComputedStyle(b); return [c.borderTopColor,c.backgroundColor];}",
                    sel,
                )
                self.assertEqual(got, ["rgba(0, 0, 0, 0)", "rgba(0, 0, 0, 0)"])
                page.evaluate("s=>document.querySelector(s).close()", sel)


# A long unbreakable token (a URL), as one source line would hold it.
LONG_TOKEN = "https://example.com/" + "a" * 400
# Each listed box's horizontal overflow (scrollWidth - clientWidth, CSS px) and its computed overflow-wrap, for the visible ones.
OVERFLOW = """sels => sels.map(s => {const e = document.querySelector(s); if (!e || !e.getClientRects().length) return [s, null, null];
  const c = getComputedStyle(e); return [s, e.scrollWidth - e.clientWidth, c.overflowWrap];})"""


class SourceAlwaysWraps(ViewerBase):
    """The source always wraps (the owner's decision after asking what [줄바꿈] was for): the composer's and the changes
    view's [줄바꿈] toggles, their pinPrefs keys and their words are gone. A long unbreakable token - a URL, a long command -
    breaks inside the excerpt, the edit card and the source diff rather than run past their right edge."""

    def test_no_wrap_toggle_or_its_stored_key_is_left(self):
        """411x908 and 1400x850, with pinPrefs.wrap false and pinPrefs.diffWrap false stored by an older release: no
        [줄바꿈] control on the page, both keys gone from pinPrefs after boot, and the source diff wraps."""
        for device in (phone(411, 908), DESK):
            with self.subTest(width=device["viewport"]["width"]):
                page = self.view(device, prefs={"wrap": False, "diffWrap": False})
                got = page.evaluate(
                    "(()=>{const p=JSON.parse(localStorage.getItem('pinPrefs')); return [document.querySelectorAll("
                    "'[data-act=wrap],[data-act=diff-wrap],#c-wrap,#revision-wrap').length, 'wrap' in p, 'diffWrap' in p,"
                    " document.querySelector('#revision-diff').className, document.querySelector('#revision-other').className];})()"
                )
                self.assertEqual(got, [0, False, False, "wrap", "wrap"])

    def test_a_long_unbreakable_token_breaks_instead_of_running_past_the_edge(self):
        """411x908 and 1400x850: a 420-character URL as the band's line breaks inside the composer's excerpt and the edit
        card's (no horizontal overflow, overflow-wrap anywhere); the source diff's code cells and a plain source break the
        same way."""
        for device in (phone(411, 908), DESK):
            with self.subTest(width=device["viewport"]["width"]):
                page = self.view(device)
                page.evaluate("()=>{LAST_PTR='touch'; pick({page:1,x0:10,y0:10,x1:200,y1:60});}")
                page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
                settle(page)
                page.click('#c-levels [data-level="raw"]')
                settle(page)
                page.evaluate(
                    "t=>{const o=COMPOSE.current; excerptLines(o).set(o.lo,t); renderComposer();}", LONG_TOKEN
                )
                settle(page)
                got = page.evaluate(OVERFLOW, ["#c-xp .xp-list", "#right", "#composer"])
                self.assertEqual(
                    [g[1] for g in got if g[1] is not None], [0] * len([g for g in got if g[1] is not None]), got
                )
                self.assertEqual(
                    page.evaluate("getComputedStyle(document.querySelector('#c-xp .xp-row .tx')).overflowWrap"),
                    "anywhere",
                )
                page.evaluate("()=>{cancelSelection(true); setSide(true); openEdit(OPEN_ALL[0].id);}")
                page.wait_for_function("EDITOR.current&&EDITOR.current.levels.length>0")
                settle(page)
                page.evaluate("t=>{const o=EDITOR.current; excerptLines(o).set(o.lo,t); renderEdit();}", LONG_TOKEN)
                settle(page)
                got = page.evaluate(OVERFLOW, [".edit .xp-list", ".edit"])
                self.assertEqual([g[1] for g in got], [0, 0], got)
                styles = page.evaluate(
                    "(()=>{const s=document.createElement('pre'); s.className='wrap'; document.body.append(s); const c=getComputedStyle(s);"
                    " const r=[c.whiteSpace,c.overflowWrap]; s.remove(); return r;})()"
                )
                self.assertEqual(styles, ["pre-wrap", "anywhere"])


class MetaWithoutCommit(ViewerBase):
    """The meta line of a manuscript outside Git (docs/handbook/viewer.md §모바일 레이아웃): the server names no commit ('-'),
    and [더보기] read 'main.tex · 2쪽 · -' and the desktop chip row 'main.tex · 2쪽 · - · <built>'. The empty piece goes, with
    its separator."""

    head = "-"

    def route(self, route):
        """The fixture's routes, with GET /api/meta saying self.head ('-': a manuscript outside Git)."""
        if urlparse(route.request.url).path == "/api/meta":
            return self.forward(MetaPatched(route, {"head": self.head}))
        return super().route(route)

    def test_more_and_the_desktop_meta_leave_out_a_missing_commit(self):
        """411x908 [더보기]: the first meta line is the file and the pages, no '-' piece; 1400x850: the chip row's text has
        no ' · - ' and no doubled separator."""
        page = self.view(phone(411, 908))
        page.evaluate("openMore()")
        settle(page)
        pieces = page.evaluate("[...document.querySelectorAll('#more-info .mc')].map(e=>e.textContent)")
        self.assertNotIn("-", pieces)
        self.assertEqual(pieces[:2], ["main.tex", "2쪽"])
        page = self.view(DESK)
        txt = page.evaluate("document.querySelector('#meta-txt').innerText")
        self.assertNotIn(" - ", txt)
        self.assertNotIn("·  ·", txt)
        self.assertEqual(txt.count("·"), 2, txt)

    def test_a_commit_still_shows_in_both(self):
        """A guard: with a commit (abc1234) [더보기]'s first line and the chip row still name it."""
        self.head = "abc1234"
        page = self.view(phone(411, 908))
        page.evaluate("openMore()")
        settle(page)
        self.assertIn(
            "abc1234", page.evaluate("[...document.querySelectorAll('#more-info .mc')].map(e=>e.textContent)")
        )
        page = self.view(DESK)
        self.assertIn("· abc1234 ·", page.evaluate("document.querySelector('#meta-txt').innerText"))


# The compact tool row's spacing as drawn: the row's box - inside its borders and above the bottom safe area; the sheet's row
# ends at the bar, whose safe area is the sheet's own padding under it - the space between it and the controls' fills, the
# safe area, what is under the bar, and the box of each control drawn: the chip's halves, [⬚], [⋯] and the status line's icon,
# text and action (fill: the box is a tonal or primary fill, not a ghost).
ROW_BOXES = """() => {const q = s => document.querySelector(s), vis = e => !!e && e.getClientRects().length > 0, R = e => e.getBoundingClientRect();
  const bar = q('#bar1'), B = R(bar), cs = getComputedStyle(bar), sheet = document.body.classList.contains('lay-narrow');
  const probe = document.createElement('div'); probe.style.cssText = 'position:fixed;bottom:0;height:env(safe-area-inset-bottom)';
  document.body.append(probe); const safe = probe.getBoundingClientRect().height; probe.remove();
  const top = B.top + parseFloat(cs.borderTopWidth), bottom = sheet ? B.bottom : B.bottom - parseFloat(cs.borderBottomWidth) - safe;
  const items = [['pins', '#btn-side', 1], ['review', '#btn-rv', 1], ['select', '#btn-select', 1], ['more', '#btn-more', 0],
    ['icon', '#bar1 #status .st-ic', 0], ['text', '#bar1 #status .st-tx', 0], ['action', '#bar1 #status .st-act', 1]]
    .filter(([, s]) => vis(q(s))).map(([k, s, fill]) => {const r = R(q(s)); return {k, fill: !!fill, box: [r.left, r.top, r.right, r.bottom]};});
  const fills = items.filter(i => i.fill);
  return {top, bottom, safe, under: innerHeight - B.bottom, above: Math.min(...fills.map(i => i.box[1])) - top,
    below: bottom - Math.max(...fills.map(i => i.box[3])), items};}"""
# The ink of each box in a screenshot (base64 PNG at the device pixel ratio, boxes in the shot's CSS px): the pixels that differ
# from the box's own background - read at its left edge, at mid height in a fill, at the top corner of a ghost - each pixel row's
# and column's coverage the strongest difference over the box's strongest; the ink's vertical centre and its left and right
# edges, the partial rows and columns counted by their coverage. A fill is read 6px in from every edge (its rounded corners,
# the halves' seam), a ghost 3px in from its sides, an icon's box (ix: 0) from its own edges.
ROW_INK = """async ([b64, dpr, items]) => {const img = new Image(); img.src = 'data:image/png;base64,' + b64; await img.decode();
  const c = document.createElement('canvas'); c.width = img.width; c.height = img.height; const x = c.getContext('2d'); x.drawImage(img, 0, 0);
  const D = x.getImageData(0, 0, c.width, c.height).data, W = c.width, out = {};
  const lum = (X, Y) => {const i = (Y * W + X) * 4; return 0.2126 * D[i] + 0.7152 * D[i + 1] + 0.0722 * D[i + 2];};
  const edges = (cov, base) => {let f = -1, la = -1; cov.forEach((v, i) => {if (v > 0.12) {if (f < 0) f = i; la = i;}});
    return f < 0 ? null : [(base + f + 1 - cov[f]) / dpr, (base + la + cov[la]) / dpr];};
  for (const it of items) {const [l, t, r, b] = it.box, iy = it.fill ? 6 : 0, ix = it.ix ?? (it.fill ? 6 : 3);
    const X0 = Math.round((l + ix) * dpr), X1 = Math.round((r - ix) * dpr), Y0 = Math.round((t + iy) * dpr), Y1 = Math.round((b - iy) * dpr);
    const bg = lum(X0, it.fill ? Math.round((Y0 + Y1) / 2) : Y0);
    let mx = 0; for (let y = Y0; y < Y1; y++) for (let xx = X0; xx < X1; xx++) mx = Math.max(mx, Math.abs(lum(xx, y) - bg));
    const rows = [], cols = new Array(X1 - X0).fill(0);
    for (let y = Y0; y < Y1; y++) {let m = 0; for (let xx = X0; xx < X1; xx++) {const v = Math.abs(lum(xx, y) - bg) / mx; m = Math.max(m, v);
      cols[xx - X0] = Math.max(cols[xx - X0], v);} rows.push(m);}
    const vy = mx < 8 ? null : edges(rows, Y0), vx = mx < 8 ? null : edges(cols, X0);
    out[it.k] = vy && vx ? {mid: (vy[0] + vy[1]) / 2, left: vx[0], right: vx[1]} : null;}
  return out;}"""


class CompactRowCentre(ViewerBase):
    """The compact tool row's spacing (docs/handbook/viewer.md §모바일 레이아웃, 2b of the cross-resolution pass): the owner
    took the sheet's split chip [핀 N | 검토 M] to the rows of the unfolded Fold and the landscape tablets and asked for the
    space under the controls to be checked by eye - it did not match. The space above the row's fills equals the space below
    them, a bottom safe area is added under that, and the ink of every control - the chip's halves, [⬚], [⋯] and the status
    line's icon, text and [재빌드] - is centred on the row's centre line."""

    def route(self, route):
        """The fixture's routes, with GET /api/meta (full and light) saying stale_build, so the status line shows [재빌드]."""
        if urlparse(route.request.url).path == "/api/meta":
            return self.forward(MetaPatched(route, {"stale_build": True, "src_age_s": 120}))
        return super().route(route)

    def row(self, device, dark=False, safe=0, open_=None):
        """The row's geometry (ROW_BOXES) with each control's ink centre minus the row's (CSS px), on device with a stale
        PDF, a bottom safe area of safe px and, if open_ is given, the panel set to it."""
        page = self.view(device, init=NO_PNG_CHIP, dark=dark)
        page.wait_for_function("!document.querySelector('#status').hidden")
        if safe:
            self.cdp(page).send("Emulation.setSafeAreaInsetsOverride", {"insets": {"bottom": safe}})
        if open_ is not None:
            page.evaluate("setSide(%s)" % ("true" if open_ else "false"))
        settle(page)
        g = page.evaluate(ROW_BOXES)
        y0 = max(0, min([g["top"]] + [i["box"][1] for i in g["items"]]) - 4)
        y1 = max([g["bottom"]] + [i["box"][3] for i in g["items"]]) + 4
        shot = page.screenshot(clip={"x": 0, "y": y0, "width": device["viewport"]["width"], "height": y1 - y0})
        items = [dict(i, box=[i["box"][0], i["box"][1] - y0, i["box"][2], i["box"][3] - y0]) for i in g["items"]]
        ink = page.evaluate(ROW_INK, [base64.b64encode(shot).decode(), device["device_scale_factor"], items])
        mid = (g["top"] + g["bottom"]) / 2
        g["off"] = {k: None if v is None else round(v["mid"] + y0 - mid, 2) for k, v in ink.items()}
        return g

    def assert_centred(self, g, controls):
        """Every control in controls is drawn and its ink centre is within 0.5px of the row's; above and below equal within 0.5px."""
        self.assertEqual(set(g["off"]), set(controls), g)
        self.assertTrue(all(v is not None and abs(v) <= 0.5 for v in g["off"].values()), g["off"])
        self.assertLessEqual(abs(g["above"] - g["below"]), 0.5, g)

    def test_the_mid_rows_have_equal_space_round_their_controls_and_one_centre_line(self):
        """The unfolded Fold on its side (1104x884), 1180x820 and 1024x768, at DPR 2 and 1, light and dark, a stale PDF on
        the status line: the fills are as far from the row's top as from its end (4px, within 0.5px) and the ink centres of
        the chip's halves, [⬚], [⋯], the status icon, its text and [재빌드] are within 0.5px of the row's centre line
        ([재빌드]'s label sat 1.9px high)."""
        for w, h in ((1104, 884), (1180, 820), (1024, 768)):
            for dpr in (2, 1):
                for dark in (False, True):
                    with self.subTest(w=w, dpr=dpr, dark=dark):
                        g = self.row(phone(w, h, dpr), dark=dark)
                        self.assert_centred(g, {"pins", "review", "select", "more", "icon", "text", "action"})
                        self.assertEqual((round(g["above"], 2), round(g["below"], 2)), (4, 4), g)

    def test_the_tablet_sheets_row_has_12px_above_and_below_open_or_collapsed(self):
        """The unfolded Fold upright (884x1104, the tablet sheet) at DPR 2 and 1, light and dark, collapsed and open: 12px
        from the sheet's edge to the fills and 12px from them to the row's end (12 over 8 collapsed and 12 over 4 open
        before); the ink centres of the chip's halves, [⬚] and [⋯] within 0.5px of the row's."""
        for dpr in (2, 1):
            for dark in (False, True):
                for open_ in (False, True):
                    with self.subTest(dpr=dpr, dark=dark, open=open_):
                        g = self.row(phone(884, 1104, dpr), dark=dark, open_=open_)
                        self.assert_centred(g, {"pins", "review", "select", "more"})
                        self.assertEqual((round(g["above"], 2), round(g["below"], 2)), (12, 12), g)

    def test_a_bottom_safe_area_goes_under_the_row(self):
        """A 20px bottom safe area (a home indicator), DPR 2: the mid row (1180x820) keeps 4px over and under its fills and
        the area is added under them, inside the bar; the collapsed tablet sheet (884x1104) keeps 12 and 12 and the area is
        the sheet's, under the bar. The ink stays centred."""
        g = self.row(phone(1180, 820, 2), safe=20)
        self.assert_centred(g, {"pins", "review", "select", "more", "icon", "text", "action"})
        self.assertEqual((g["safe"], round(g["above"], 2), round(g["below"], 2), g["under"]), (20, 4, 4, 0), g)
        g = self.row(phone(884, 1104, 2), safe=20, open_=False)
        self.assert_centred(g, {"pins", "review", "select", "more"})
        self.assertEqual(
            (g["safe"], round(g["above"], 2), round(g["below"], 2), round(g["under"], 2)), (20, 12, 12, 20), g
        )


# The short band's top row as drawn: the stripe's bottom and the row's line (inside the nav bar's bottom border), the two bars'
# heights and the seam between them, the edge and ink lines, and every control left to right - its box, whether it is a fill,
# and its icon's box and stroke width. The status line's icon, text and action count as controls.
SHORT_ROW = """() => {const q = s => document.querySelector(s), R = e => e.getBoundingClientRect(), box = r => [r.left, r.top, r.right, r.bottom];
  const vis = e => !!e && e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
  const px = v => {const d = document.createElement('div'); d.style.width = v; document.body.append(d); const w = R(d).width; d.remove(); return w;};
  const nav = q('#doc-nav'), N = R(nav), B = R(q('#bar1')), links = [...document.querySelectorAll('#doc-links button')];
  const els = [...nav.querySelectorAll(':scope>button,#doc-links button,#view-switch button,#status .st-ic,#status .st-tx,#status button'),
    ...q('#bar1').querySelectorAll('button')].filter(vis);
  const items = els.map(e => {const s = e.querySelector(':scope>svg');
    return {k: e.id || (links.includes(e) ? 'link' + links.indexOf(e) : e.className.split(' ')[0]), box: box(R(e)),
      fill: !/^(rgba\\(0, 0, 0, 0\\)|transparent)$/.test(getComputedStyle(e).backgroundColor),
      icon: s ? box(R(s)) : null, stroke: s ? s.getAttribute('stroke-width') : null};}).sort((a, b) => a.box[0] - b.box[0]);
  return {stripe: R(q('#brand-stripe')).bottom, line: N.bottom - parseFloat(getComputedStyle(nav).borderBottomWidth), heights: [N.height, B.height],
    seam: B.left - N.right, edge: px('var(--edge)'), ink: px('var(--ink)'), vw: innerWidth, items};}"""


class ShortRow(ViewerBase):
    """The landscape phone's one top row (docs/handbook/viewer.md §모바일 레이아웃 짧은 화면, 5b of the cross-resolution pass): it
    was 44px and its 40px controls stood from 2px down, so the 4px instance stripe cut the tops of [재빌드] and the chip. It is
    the touch nav bar's 48px and centres every control between the stripe and its line; its icons are 18px Lucide (stroke 2),
    each centred in its box; its neighbours are 8px apart; the chip's fill ends on the edge line and the outline toggle's
    glyph starts on the ink line, as the panel and the page under the row do."""

    def route(self, route):
        """The fixture's routes, with GET /api/meta (full and light) saying stale_build, so the row shows [재빌드]."""
        if urlparse(route.request.url).path == "/api/meta":
            return self.forward(MetaPatched(route, {"stale_build": True, "src_age_s": 120}))
        return super().route(route)

    def row(self, device, dark=False, two_docs=False):
        """The row (SHORT_ROW) on device with a stale PDF - and, with two_docs, a second document's link (DOCS as two) - and the
        ink (ROW_INK) of each control, read between the stripe and the current tab's 2px underline over the line, and of each
        icon, keyed 'icon:<control>'; with the row's centre (mid)."""
        page = self.view(device, init=NO_PNG_CHIP, dark=dark)
        page.wait_for_function("!document.querySelector('#status').hidden")
        if two_docs:
            page.evaluate(
                "()=>{DOCS=[DOCS[0],{key:'reply',name:'답변서',path:'reply.tex',n_pages:1}];"
                " document.body.classList.add('docs-multi'); drawDocTabs();}"
            )
        settle(page)
        g = page.evaluate(SHORT_ROW)
        top, line = g["stripe"], g["line"]
        clip = [
            dict(
                k=i["k"],
                fill=i["fill"],
                box=[i["box"][0], max(i["box"][1], top + 0.5), i["box"][2], min(i["box"][3], line - 3)],
            )
            for i in g["items"]
        ]
        clip += [dict(k="icon:" + i["k"], fill=False, ix=0, box=i["icon"]) for i in g["items"] if i["icon"]]
        shot = page.screenshot(clip={"x": 0, "y": 0, "width": g["vw"], "height": line + 2})
        g["inkOf"] = page.evaluate(ROW_INK, [base64.b64encode(shot).decode(), device["device_scale_factor"], clip])
        g["mid"] = (top + line) / 2
        return g

    def test_the_row_is_48px_and_its_controls_clear_the_stripe_on_one_centre_line(self):
        """844x390 at DPR 3 and 908x411 at 2.625, light and dark, a stale PDF: the nav bar and the tool bar are 48px; every
        fill ([재빌드], [⬚ 선택], the chip's halves) starts under the stripe and ends above the row's line; every control's box
        centre and ink centre are within 0.5px of the centre between the stripe and the line."""
        for device in (phone(844, 390, 3), phone(908, 411)):
            for dark in (False, True):
                with self.subTest(w=device["viewport"]["width"], dark=dark):
                    g = self.row(device, dark=dark)
                    self.assertEqual([round(h, 2) for h in g["heights"]], [48, 48], g)
                    fills = [i for i in g["items"] if i["fill"]]
                    self.assertEqual({i["k"] for i in fills}, {"btn-sm", "btn-select", "btn-side", "btn-rv"}, g)
                    self.assertTrue(all(i["box"][1] >= g["stripe"] and i["box"][3] <= g["line"] for i in fills), fills)
                    off = {i["k"]: round((i["box"][1] + i["box"][3]) / 2 - g["mid"], 2) for i in g["items"]}
                    self.assertTrue(all(abs(v) <= 0.5 for v in off.values()), off)
                    ink = {i["k"]: g["inkOf"][i["k"]] for i in g["items"]}
                    self.assertTrue(all(v is not None for v in ink.values()), ink)
                    off = {k: round(v["mid"] - g["mid"], 2) for k, v in ink.items()}
                    self.assertTrue(all(abs(v) <= 0.5 for v in off.values()), off)

    def test_its_icons_are_18px_with_stroke_2_and_centred_in_their_boxes(self):
        """844x390 at DPR 3, light and dark: the outline toggle's, [⬚]'s and [⋯]'s icons are 18px Lucide with stroke 2 and
        each glyph's ink is centred in its icon box within 0.5px both ways; the toggle's and [⋯]'s icon box is centred in the
        button's, and the status dot in its 16px box within 0.5px both ways."""
        for dark in (False, True):
            with self.subTest(dark=dark):
                g = self.row(phone(844, 390, 3), dark=dark)
                icons = {i["k"]: i for i in g["items"] if i["icon"]}
                self.assertEqual(set(icons), {"nav-toc-toggle", "btn-select", "btn-more"}, g)
                for k, i in icons.items():
                    b, ink = i["icon"], g["inkOf"]["icon:" + k]
                    self.assertEqual((round(b[2] - b[0], 2), round(b[3] - b[1], 2), i["stroke"]), (18, 18, "2"), k)
                    self.assertLessEqual(abs((ink["left"] + ink["right"]) / 2 - (b[0] + b[2]) / 2), 0.5, (k, ink, b))
                    self.assertLessEqual(abs(ink["mid"] - (b[1] + b[3]) / 2), 0.5, (k, ink, b))
                for k in ("nav-toc-toggle", "btn-more"):
                    b, i = icons[k]["box"], icons[k]["icon"]
                    self.assertLessEqual(abs((i[0] + i[2]) / 2 - (b[0] + b[2]) / 2), 0.5, k)
                dot = next(i for i in g["items"] if i["k"] == "st-ic")
                ink, b = g["inkOf"]["st-ic"], dot["box"]
                self.assertEqual(round(b[2] - b[0], 2), 16)
                self.assertLessEqual(abs((ink["left"] + ink["right"]) / 2 - (b[0] + b[2]) / 2), 0.5, ink)
                self.assertLessEqual(abs(ink["mid"] - (b[1] + b[3]) / 2), 0.5, ink)

    def test_its_neighbours_are_8px_apart_and_its_ends_are_on_the_edge_and_ink_lines(self):
        """844x390 at DPR 3 and 908x411 at 2.625, with one document and with two: neighbouring controls are 8px apart - but
        the free space before the page count, the view switch's separator after the document links (8px each side of its 1px
        line; one document has no links and no line, and the switch's 8px inset made 16) and the chip's halves (they meet);
        the chip's fill ends on the edge line, 16px from the screen's right; the outline toggle's box starts on it at the
        left, its glyph's ink on the ink line (28px) - at 28.5, as the panel-left glyph's ink starts 1.5px into its box and
        icons are drawn at whole pixels; the nav bar and the tool bar meet with no seam (the PDF showed through 0.5px between
        them)."""
        for device in (phone(844, 390, 3), phone(908, 411)):
            for two in (False, True):
                with self.subTest(w=device["viewport"]["width"], two_docs=two):
                    g = self.row(device, two_docs=two)
                    items = g["items"]
                    gaps = {b["k"]: round(b["box"][0] - a["box"][2], 2) for a, b in zip(items, items[1:], strict=False)}
                    self.assertGreater(gaps.pop("nav-page"), 8)
                    self.assertEqual(("link1" in gaps), two, gaps)
                    want = {"view-manuscript": 17 if two else 8, "btn-rv": 0}
                    self.assertEqual(gaps, {k: want.get(k, 8) for k in gaps}, gaps)
                    self.assertEqual((g["edge"], g["ink"]), (16, 28))
                    self.assertEqual(round(g["vw"] - items[-1]["box"][2], 2), g["edge"])
                    self.assertEqual((items[0]["k"], round(items[0]["box"][0], 2)), ("nav-toc-toggle", g["edge"]))
                    toc = g["inkOf"]["icon:nav-toc-toggle"]["left"]
                    self.assertLessEqual(
                        abs(toc - g["ink"] - 0.5), 0.25, g["inkOf"]
                    )  # the glyph's 1.5px bearing, whole pixels
                    self.assertEqual(round(g["seam"], 2), 0)


if __name__ == "__main__":
    unittest.main()

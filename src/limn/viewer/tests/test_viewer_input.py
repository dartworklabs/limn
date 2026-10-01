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

import json
import re
import time
import unittest

from limn.pins.lifecycle.rules import CloseRequest
from limn.security.access import LOCAL_ACTOR

from helpers import HTML, add_pin, extract_js_fn, ps, run_node
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
        """backLayer(band, overlay, sideOpen, outlineOpen): only a layer that covers the document - a sheet (phone, tablet),
        the overlay panel (mid-overlay, or a short band up to 900px), the outline overlay (mid bands and the tablet sheet;
        with both open the outline is on top). The side panel beside the document and anything wide are not layers."""
        cases = [
            ("phone", False, True, False, "side"),
            ("phone", False, False, False, None),
            ("phone", False, False, True, None),
            ("tablet-sheet", False, True, False, "side"),
            ("tablet-sheet", False, False, True, "outline"),
            ("tablet-sheet", False, True, True, "outline"),
            ("tablet-sheet", False, False, False, None),
            ("mid-overlay", True, True, False, "side"),
            ("mid-overlay", True, False, True, "outline"),
            ("short", True, True, False, "side"),
            ("short", False, True, False, None),
            ("short", False, False, True, "outline"),
            ("mid-side", False, True, False, None),
            ("mid-side", False, False, True, "outline"),
            ("wide", False, True, True, None),
        ]
        got = self.run_js(
            ["backLayer"], "%s.map(c=>backLayer(c[0],c[1],c[2],c[3]))" % json.dumps([c[:4] for c in cases])
        )
        self.assertEqual([c[:4] + (g,) for c, g in zip(cases, got, strict=True)], cases)


class MarkBadgeLogic(unittest.TestCase):
    """Where a mark's number badge goes (docs/handbook/viewer.md §모바일 레이아웃, UX audit R4): outside the mark's left
    edge, unless the mark starts less than 28px from the page's left edge, where the even page margin (12px on a phone) has
    no room for it."""

    def test_the_badge_goes_inside_a_mark_that_starts_under_28px_from_the_page_edge(self):
        """At a 336px page: 0px and 27.9px are inside, 28px and more outside; the same fraction flips with the page width."""
        js = "\n".join(
            [
                extract_js_fn("markBadgeIn"),
                "console.log(JSON.stringify([markBadgeIn(0,336),markBadgeIn(27.9/336,336),markBadgeIn(28/336,336),"
                "markBadgeIn(0.15,336),markBadgeIn(0.05,336),markBadgeIn(0.05,900)]));",
            ]
        )
        self.assertEqual(node_or_skip(self, js), [True, True, False, False, True, False])


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
        """The documents sheet behaves like [더보기]: outside tap closes it, and it follows a pull down."""
        page = self.view(PHONE)
        cdp = self.cdp(page)
        page.evaluate("openDocsMenu()")
        self.tap(cdp, 190, 100)
        page.wait_for_function("!document.querySelector('#docs-menu').open")
        page.evaluate("openDocsMenu()")
        r = page.locator("#docs-menu").bounding_box()
        self.swipe(cdp, 190, r["y"] + 20, 190, r["y"] + 20 + r["height"] * 0.6, steps=10, dt=0.02)
        page.wait_for_function("!document.querySelector('#docs-menu').open")

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

    def test_a_mouse_at_wide_width_sees_the_desktop_unchanged(self):
        """1440x900 with a mouse: the panel, card, composer and tool bar are as they were before the compact work - a 348px
        panel, 28px tool bar, the section strip, the card's #N / range / N쪽 and its named grid, the composer's order and its
        36px save row. (The same checks pass on 809fc9a.)"""
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
                composer: tops('#composer .c-loc-row,#composer #c-levels,#composer .c-tools,#composer #c-snip,#composer #c-kind,#composer #note'),
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
                "composer": ["c-loc-row", "c-levels", "c-tools", "c-snip", "c-kind", "note"],
                "save": 36,
                "lift": False,
            },
        )

    def test_a_mouse_at_1440_keeps_the_desktop_geometry_to_the_pixel(self):
        """1440x900 with a mouse: the page's margins and box, its first mark's badge, the panel's tool bar, section head and
        first card, and the help, Trash and documents dialogs sit where they sat before the touch edge grid (UX audit V2/V6):
        the desktop layout is unchanged."""
        page = self.view(MOUSE_WIDE)
        page.evaluate("document.querySelector('#left').scrollTop=0")
        settle(page)
        got = page.evaluate(DESK_GEOMETRY)
        for opener, dlg in (("openHelp()", "#help"), ("openTrash()", "#trash"), ("openDocsMenu()", "#docs-menu")):
            page.evaluate(opener)
            settle(page)
            got[dlg] = page.evaluate(
                "s=>{const r=document.querySelector(s).getBoundingClientRect(),c=getComputedStyle(document.querySelector(s));"
                "return [Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height),c.paddingLeft,c.paddingRight];}",
                dlg,
            )
            page.evaluate("s=>document.querySelector(s).close()", dlg)
        self.assertEqual(got, DESK_1440)


# Where the desktop's chrome sits at 1440x900 with a mouse on the ViewerBase fixture: [x, y, width, height] boxes (rounded).
DESK_GEOMETRY = """() => {const q = s => document.querySelector(s), B = e => {const r = e.getBoundingClientRect();
    return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)];}, L = getComputedStyle(q('#left'));
  return {left: [L.paddingLeft, L.paddingRight], page: B(q('#p1')), badge: B(q('.mark b')), right: B(q('#right')),
    bar: [...q('#bar1').children].filter(e => e.getClientRects().length).map(e => (e.id || e.className) + '@' + B(e).join(',')),
    head: B(q('#sec-open .sec-head')), toggle: B(q('#open-toggle')), chevron: B(q('#open-toggle svg')), card: B(q('#pins .pin')),
    dot: B(q('#pins .pin .st-dot')), list: [getComputedStyle(q('#list')).paddingLeft, getComputedStyle(q('#list')).paddingRight]};}"""
DESK_1440 = {
    "left": ["44px", "16px"],
    "page": [290, 98, 780, 1009],
    "badge": [386, 300, 22, 22],
    "right": [1092, 0, 348, 900],
    "bar": [
        "btn-rebuild@1101,8,71,28",
        "sp@1176,22,6,0",
        "jump@1186,8,54,28",
        "btn-zoom-out@1244,8,28,28",
        "btn-zoom-in@1276,8,28,28",
        "btn-fit@1308,8,28,28",
        "btn-notify@1340,8,28,28",
        "btn-theme@1372,8,28,28",
        "btn-help@1404,8,28,28",
    ],
    "head": [1093, 108, 347, 31],
    "toggle": [1101, 112, 88, 22],
    "chevron": [1106, 116, 14, 14],
    "card": [1105, 143, 323, 102],
    "dot": [1118, 162, 8, 8],
    "list": ["12px", "12px"],
    "#help": [380, 54, 680, 792, "24px", "24px"],
    "#trash": [440, 388, 560, 124, "24px", "24px"],
    "#docs-menu": [440, 780, 560, 120, "12px", "12px"],
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

    def test_the_review_pill_shows_an_eye_beside_its_count(self):
        """384x832: [핀 N]'s purple pill reads 'eye 1' - a bare '1' after the open count read as '4 1' (UX audit P10). On a
        360px phone, where [선택] already drops its label, the eye goes too and the count stays."""
        for device, eye in ((PHONE, True), (PHONE_360, False)):
            with self.subTest(width=device["viewport"]["width"]):
                page = self.view(device)
                got = page.evaluate(
                    "()=>{const p=document.querySelector('#btn-side .rv-n'), i=p.querySelector('svg.ic');"
                    " return [p.textContent, !!i&&i.getClientRects().length>0];}"
                )
                self.assertEqual(got, ["1", eye])

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

    def test_the_sheet_header_is_80px_and_its_handle_and_section_tools_answer_44px(self):
        """The sheet's stuck header was the handle row 24 + the tool bar 53 + the section head 52 = 129px (diagnosis P3); the handle
        now sits in the tool bar's row, so the header (below the sheet's 1px edge, as the diagnosis measured it) is the 40px row
        and the 40px section head, and every control in it -
        the handle included (it answered 121x32) - still answers a 44x44 box."""
        page = self.view(PHONE, prefs={"sec": {"open": True, "review": True, "done": True}}, init=NO_PNG_CHIP)
        page.evaluate("()=>{setSide(true); document.querySelector('#right').scrollTop=0;}")
        settle(page)
        head = page.evaluate(
            "Math.round(document.querySelector('#sec-open .sec-head').getBoundingClientRect().bottom"
            "-document.querySelector('#bar1').getBoundingClientRect().top)"
        )
        self.assertLessEqual(head, 80)
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
# How much of an element is visible and on top: the px of its centre column whose topmost element is it, and its height.
SHOWN = """sel => {
  const e = document.querySelector(sel), r = e.getBoundingClientRect(), x = r.left + r.width / 2; let n = 0;
  for (let y = Math.max(0, Math.ceil(r.top)); y < Math.min(innerHeight, r.bottom); y++) {
    const t = document.elementFromPoint(x, y); if (t && (t === e || e.contains(t))) n++; }
  return [n, Math.round(r.height)]; }"""


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
            "[...document.querySelectorAll('.c-loc-row,#note,#c-overlap,#c-levels,#c-kind,#c-snip')]"
            ".map(e=>[e.id||e.className,Math.round(e.getBoundingClientRect().top)]).sort((a,b)=>a[1]-b[1]).map(a=>a[0])"
        )
        self.assertEqual(order, ["c-loc-row", "note", "c-overlap", "c-levels", "c-kind", "c-snip"])

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
        """844x390: nav bar 48 + action row 49 left the page 293px. The short band has one 44px row on top holding the nav
        bar and [선택] [⋯] [핀 N] at its right end, nothing at the bottom, and the overlay panel collapsed."""
        page = self.view(LAND_PHONE)
        self.assertEqual(page.evaluate(BODY_BANDS), ["band-short", "lay-mid", "mid-overlay"])
        self.assertFalse(page.evaluate("SIDE_OPEN"))
        row = page.evaluate(TOP_ROW)
        self.assertEqual((row["nav"]["y"], row["bar"]["y"]), (0, 0))
        self.assertLessEqual(max(row["nav"]["h"], row["bar"]["h"]), 44)
        self.assertLessEqual(row["nav"]["x"] + row["nav"]["w"], row["bar"]["x"])  # the links end where the tools begin
        self.assertEqual(row["bar"]["x"] + row["bar"]["w"], 844)
        self.assertEqual(sorted(t[0] for t in row["tools"]), ["btn-more", "btn-select", "btn-side"])
        self.assertTrue(all(top < 44 and hit for _, top, hit in row["tools"]), row["tools"])
        self.assertFalse(row["strip"])
        self.assertTrue(row["bottomIsPdf"])
        self.assertFalse(row["overflow"])
        self.assertEqual(page.evaluate(MISSES_44, "#bar1 button,#nav-toc-toggle"), [])

    def test_past_900px_the_short_band_opens_its_panel_beside_the_document(self):
        """932x430: the same one row; the panel is open beside the document (no overlay) from the top row to the bottom."""
        page = self.view(LAND_PHONE_WIDE)
        self.assertEqual(page.evaluate(BODY_BANDS), ["band-short", "lay-mid"])
        self.assertTrue(page.evaluate("SIDE_OPEN"))
        right = page.locator("#right").bounding_box()
        self.assertEqual((round(right["y"]), round(right["y"] + right["height"])), (44, 430))
        row = page.evaluate(TOP_ROW)
        self.assertLessEqual(row["bar"]["h"], 44)
        self.assertTrue(all(top < 44 and hit for _, top, hit in row["tools"]), row["tools"])

    def test_the_short_band_moves_rebuild_into_more(self):
        """[PDF 재빌드] leaves the row for [⋯]; the overlay layout of a taller screen keeps it in its action row."""
        page = self.view(LAND_PHONE)
        self.assertFalse(page.is_visible("#btn-rebuild"))
        page.evaluate("openMore()")
        settle(page)
        self.assertTrue(page.is_visible("#more [data-act=rebuild]"))
        page = self.view(FOLD)
        self.assertTrue(page.is_visible("#btn-rebuild"))
        page.evaluate("openMore()")
        settle(page)
        self.assertFalse(page.is_visible("#more [data-act=rebuild]"))

    def test_focusing_the_note_hides_the_top_row_until_the_focus_leaves(self):
        """With the keyboard up a landscape phone has about 200px: the row hides while a note field has focus."""
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
        self.assertEqual(round(page.locator("#right").bounding_box()["y"]), 44)

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
        """1000x800 with a mouse: picking focuses the note and the panel scrolls it into view as in 0.4.1 - the composer's top
        at y 11 (the same check passes on 2bdef90); the touch save-row padding scrolled it 32px further (y -21)."""
        page = self.view(MOUSE_MID)
        self.mouse_pick(page)
        page.mouse.move(5, 5)
        settle(page)
        got = page.evaluate(
            "[document.activeElement.id, Math.round(document.querySelector('#composer').getBoundingClientRect().top),"
            " getComputedStyle(document.querySelector('#right')).scrollPaddingBottom,"
            " getComputedStyle(document.querySelector('#right')).scrollPaddingTop]"
        )
        self.assertEqual(got, ["note", 11, "auto", "auto"])

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
            "[...document.querySelectorAll('#composer .c-loc-row,#c-qhint,#c-overlap,#c-levels,#c-kind,#c-snip,#note')]"
            ".filter(e=>e.getClientRects().length).map(e=>[e.id||e.className,Math.round(e.getBoundingClientRect().top)])"
            ".sort((a,b)=>a[1]-b[1]).map(a=>a[0])"
        )
        self.assertEqual(order, ["c-loc-row", "note", "c-qhint", "c-overlap", "c-levels", "c-kind", "c-snip"])
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

    def test_a_mark_at_the_page_edge_shows_its_whole_badge_inside_and_the_others_keep_theirs_outside(self):
        """360x800: a pin marked from the page's left edge has its badge in the mark's top-left corner, wholly inside the
        PDF column (outside, it would hang 16px past the 12px margin and be clipped); a mark 50px in keeps the badge
        outside its left edge."""
        add_pin(
            {"file": str(self.main), "lo": 30, "hi": 31, "page": 1, "note": "왼쪽 끝", "frac": [0.0, 0.65, 0.4, 0.04]},
            actor(ALICE),
        )
        page = self.view(touch_device(360, 800))
        got = page.evaluate(
            """() => {const L = document.querySelector('#left'), lr = L.getBoundingClientRect(), x0 = lr.left + L.clientLeft;
              return [...document.querySelectorAll('#p1 .mark')].map(m => {const b = m.querySelector('b').getBoundingClientRect(),
                r = m.getBoundingClientRect(); return {inside: m.classList.contains('in'), shown: b.left >= x0 && b.right <= x0 + L.clientWidth,
                within: b.left >= r.left && b.top >= r.top, off: Math.round(r.left - document.querySelector('#p1').getBoundingClientRect().left)};}); }"""
        )
        edge = [g for g in got if g["off"] <= 1]  # the light page's 1px border
        self.assertEqual([dict(g, off=0) for g in edge], [{"inside": True, "shown": True, "within": True, "off": 0}])
        rest = [g for g in got if g["off"] > 1]
        self.assertTrue(rest)
        self.assertEqual({(g["inside"], g["shown"], g["within"]) for g in rest}, {(False, True, False)})


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
        """360x780, Korean and English: a sheet on the bottom edge, at most 460px high, no label on two lines, 44px targets."""
        for lang in ("ko", "en"):
            with self.subTest(lang=lang):
                page = self.view(PHONE_360, lang=lang)
                page.evaluate("openMore()")
                settle(page)
                box = page.locator("#more").bounding_box()
                self.assertLessEqual(box["height"], 460)
                self.assertAlmostEqual(box["y"] + box["height"], 780, delta=1)
                two = page.evaluate(
                    """() => [...document.querySelectorAll('#more button')].filter(b => b.getClientRects().length).filter(b => {
                      const r = document.createRange(); r.selectNodeContents(b);
                      return new Set([...r.getClientRects()].filter(q => q.width > 1).map(q => Math.round(q.top))).size > 1;
                    }).map(b => b.id || b.textContent.trim())"""
                )
                self.assertEqual(two, [])
                self.assertEqual(page.evaluate(MISSES_44, "#more button,#more input"), [])

    def test_a_tapped_row_keeps_no_hover_fill_while_a_mouse_still_gets_one(self):
        """360x780 touch: a tap on [테마] in [더보기] left the row grey (a sticky :hover, the owner's 'Theme: System', UX
        audit P4.6); the hover fill answers a mouse only. A mouse at 1000x800 (the same sheet) still gets --accent."""
        bg = "getComputedStyle(document.querySelector('#m-theme')).backgroundColor"
        page = self.view(PHONE_360)
        page.evaluate("openMore()")
        settle(page)
        self.tap(self.cdp(page), *self.center(page, "#m-theme"))
        settle(page)
        self.assertEqual(page.evaluate(bg), "rgba(0, 0, 0, 0)")
        page = self.view(MOUSE_MID)
        page.evaluate("openMore()")
        settle(page)
        page.hover("#m-theme")
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
        """[더보기] and the Trash closed on a backdrop click; help and the documents menu now do too."""
        page = self.view(DESK)
        for opener, dlg in (("openHelp()", "#help"), ("openDocsMenu()", "#docs-menu")):
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
            if (e.closest('#more,#help,#trash,#docs-menu,#revision-view,#outline') || e.matches('.note,.sum,.arc-reply,.pin-ref,#grip,#outline-grip,textarea'))
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


if __name__ == "__main__":
    unittest.main()

"""Mouse and touch input of the viewer: collapsing the pin panel, touch gestures, and the usability fixes of 0.3.x.

The owner-approved findings of the 2026-09-26 input review (docs/handbook/viewer.md §패널 폭과 시트 높이, §펼친 화면 레이아웃,
§모바일 레이아웃, §알림(토스트), §뜻과 모양). Two kinds of test:

- ``...Logic`` classes run the pure decision functions of ``app.js`` under node (skipped without node), in the style of
  ``test_server.FrontendPanelWidthLogic``: where a handle drag lands, which keys do what, how a swipe or a sheet drag ends.
- The browser classes drive the real viewer against the in-process server (``test_qa_021.BrowserBase``) at desktop
  1400x850 and 1280x720 (mouse), an unfolded Fold 842x758 and a phone 384x832 (touch, CDP touch events), in Korean and
  English, light and dark, and with reduced motion.

Run: uv run pytest -q tests/test_viewer_input.py
"""
import json
import re
import time
import unittest

from test_qa_021 import BrowserBase, actor
from test_access import ALICE
from test_server import extract_js_fn, ps, run_node

HANGUL = re.compile(r"[가-힣]")
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
        js = extract_js_fn("snapSide") + "\nconsole.log(JSON.stringify(%s.map(c=>snapSide(c[0],c[1],c[2]))));" % json.dumps(cases)
        return node_or_skip(self, js)

    def test_width_follows_the_pointer_when_at_or_above_the_minimum(self):
        """At or above the minimum the width follows the pointer, up to the maximum."""
        got = self.snap([(500, self.WIDE, False), (280, self.WIDE, False), (1200, self.WIDE, False), (500.4, self.WIDE, True)])
        self.assertEqual(got, [{"w": 500, "zone": "follow"}, {"w": 280, "zone": "follow"}, {"w": 954, "zone": "follow"},
                               {"w": 500, "zone": "follow"}])

    def test_width_stops_at_the_minimum_between_half_and_minimum(self):
        """Between T (inclusive) and the minimum the width stays at the minimum: the handle turns primary."""
        got = self.snap([(279, self.WIDE, False), (140, self.WIDE, False), (140, self.WIDE, True)])
        self.assertEqual(got, [{"w": 280, "zone": "min"}] * 3)

    def test_release_collapses_when_the_pointer_asks_for_less_than_half_the_minimum(self):
        """Below T a release collapses the panel; the width shown stays at the minimum meanwhile."""
        self.assertEqual(self.snap([(139, self.WIDE, False), (-80, self.WIDE, False)]),
                         [{"w": 280, "zone": "collapse"}] * 2)

    def test_collapse_zone_is_blocked_while_a_draft_is_open(self):
        """Composing, editing, replying or relocating: the drag stops at the minimum instead of collapsing."""
        self.assertEqual(self.snap([(139, self.WIDE, True), (0, self.MID, True)]),
                         [{"w": 280, "zone": "blocked"}, {"w": 300, "zone": "blocked"}])

    def test_mid_threshold_is_half_of_its_300px_minimum(self):
        """The unfolded layout's minimum is 300px, so its threshold is 150px."""
        self.assertEqual([s["zone"] for s in self.snap([(150, self.MID, False), (149, self.MID, False)])], ["min", "collapse"])


class GripKeyLogic(unittest.TestCase):
    """gripKey(key, w, bounds, collapsed): the handle's keys as a WAI-ARIA window splitter."""

    B = {"min": 280, "max": 954}

    def keys(self, cases):
        """[(key, w, collapsed)] -> [gripKey(...)] from the shipped source."""
        js = "\n".join([extract_js_fn("clampSide"), extract_js_fn("gripKey"),
                        "const B=%s;console.log(JSON.stringify(%s.map(c=>gripKey(c[0],c[1],B,c[2]))));" % (json.dumps(self.B), json.dumps(cases))])
        return node_or_skip(self, js)

    def test_home_goes_to_the_minimum_and_end_to_the_maximum(self):
        """Home = the panel's smallest size, End = its largest (they were reversed)."""
        self.assertEqual(self.keys([("Home", 348, False), ("End", 348, False)]),
                         [{"act": "width", "w": 280}, {"act": "width", "w": 954}])

    def test_enter_collapses_and_space_cycles_the_presets(self):
        """Enter collapses an open panel (it used to cycle); Space cycles narrow/normal/wide."""
        self.assertEqual(self.keys([("Enter", 348, False), (" ", 348, False)]), [{"act": "collapse"}, {"act": "cycle"}])

    def test_arrows_step_16px_and_never_collapse(self):
        """Left widens and Right narrows by 16px, clamped to the bounds; collapsing stays Enter's job."""
        self.assertEqual(self.keys([("ArrowLeft", 348, False), ("ArrowRight", 348, False), ("ArrowRight", 284, False),
                                    ("ArrowLeft", 950, False), ("x", 348, False)]),
                         [{"act": "width", "w": 364}, {"act": "width", "w": 332}, {"act": "width", "w": 280},
                          {"act": "width", "w": 954}, None])

    def test_every_key_but_arrow_right_opens_a_collapsed_panel(self):
        """Collapsed: Enter/Space open to the saved width, Home/Left to the minimum, End to the maximum."""
        self.assertEqual(self.keys([("Enter", 0, True), (" ", 0, True), ("Home", 0, True), ("ArrowLeft", 0, True),
                                    ("End", 0, True), ("ArrowRight", 0, True)]),
                         [{"act": "open"}, {"act": "open"}, {"act": "width", "w": 280}, {"act": "width", "w": 280},
                          {"act": "width", "w": 954}, None])


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
        got = self.run_js(["swipeFollow"], "[swipeFollow(120,false),swipeFollow(-5,false),swipeFollow(40,true),swipeFollow(400,true)]")
        self.assertEqual(got, [120, 0, 10, 24])

    def test_dismiss_closes_past_35_percent_or_on_a_fling(self):
        """Past 35% of the size, or more than 24px at 0.5px/ms or faster, closes; otherwise it springs back."""
        got = self.run_js(["dismissOutcome"], "[dismissOutcome(116,330,0),dismissOutcome(115,330,0.49),dismissOutcome(25,330,0.5),"
                                              "dismissOutcome(24,330,3),dismissOutcome(60,330,0.2)]")
        self.assertEqual(got, ["close", "back", "close", "back", "back"])

    def test_sheet_release_collapses_low_or_flung_down_and_steps_up_on_an_upward_fling(self):
        """Below 25% or a downward fling collapses (30% while composing); an upward fling goes to the next stop."""
        pre = re.search(r"const SHEET_F=\[[^\]]*\],SHEET_MIN_F=[\d.]+,SHEET_CLOSE_F=[\d.]+;", ps.HTML).group(0)
        got = self.run_js(["sheetRelease"], "[sheetRelease(0.2,300,0.1,false),sheetRelease(0.2,300,0.1,true),"
                          "sheetRelease(0.5,40,0.8,false),sheetRelease(0.5,40,0.8,true),sheetRelease(0.5,-40,-0.8,false),"
                          "sheetRelease(0.9,-40,-0.8,false),sheetRelease(0.5,-40,-0.2,false),sheetRelease(0.27,80,0.1,false)]", pre)
        self.assertEqual(got, [{"close": True}, {"f": 0.3}, {"close": True}, {"f": 0.3}, {"f": 0.64}, {"f": 1}, {"f": 0.5},
                               {"f": 0.3}])

    def test_double_tap_is_two_taps_within_300ms_and_24px_and_toggles_fit_and_2x(self):
        """A second tap near the first zooms: fit width -> 2x, any other width -> fit width."""
        got = self.run_js(["isDoubleTap", "doubleTapWidth"],
                          "[isDoubleTap({t:0,x:10,y:10},{t:250,x:20,y:25}),isDoubleTap({t:0,x:10,y:10},{t:350,x:10,y:10}),"
                          "isDoubleTap({t:0,x:10,y:10},{t:100,x:40,y:10}),isDoubleTap(null,{t:0,x:0,y:0}),"
                          "doubleTapWidth(800,800),doubleTapWidth(830,800),doubleTapWidth(1600,800),doubleTapWidth(500,800)]")
        self.assertEqual(got, [True, False, False, False, 1600, 1600, 800, 800])

    def test_back_layer_is_the_sheet_the_overlay_panel_or_the_mid_outline(self):
        """Only a layer that covers the document: narrow sheet, 701-900px overlay panel, mid outline overlay."""
        got = self.run_js(["backLayer"], "[backLayer('narrow',false,true,false),backLayer('narrow',false,false,false),"
                          "backLayer('mid',true,true,false),backLayer('mid',false,true,false),backLayer('mid',false,false,true),"
                          "backLayer('wide',false,true,true)]")
        self.assertEqual(got, ["side", None, "side", None, "outline", None])


# ---------------------------------------------------------------- browser harness

class ViewerBase(BrowserBase):
    """BrowserBase with device presets, saved preferences, reduced motion and touch helpers. Three open pins with marks on
    page 1 and one pin awaiting review, so the list, the marks and the review pill are all there."""

    def setUp(self):
        super().setUp()
        for lo, y in ((4, 0.2), (8, 0.35), (12, 0.5)):
            ps.add_pin({"file": str(self.main), "lo": lo, "hi": lo + 1, "page": 1, "note": "메모 %d" % lo,
                        "frac": [0.15, y, 0.5, 0.04]}, actor(ALICE))
        rid = ps.add_pin({"file": str(self.main), "lo": 20, "hi": 21, "page": 2, "note": "검토할 핀", "frac": [0.2, 0.3, 0.4, 0.04]},
                         actor(ALICE))
        ps.set_done(rid, True, dict(ps.LOCAL_ACTOR), reply="고침")

    def view(self, device, lang="ko", prefs=None, reduced=False, init=None, dark=False, hash_=""):
        """Open the viewer on a device preset. prefs = pinPrefs before boot (coach marks are pre-seen unless given)."""
        p = {"coach": {"touch": 1, "mouse": 1, "sel": 1}}
        p.update(prefs or {})
        if dark:
            p["theme"] = "dark"
        context = self.browser.new_context(**device, reduced_motion="reduce" if reduced else "no-preference")
        self.addCleanup(context.close)
        context.add_init_script("try{if(!sessionStorage.getItem('__t')){sessionStorage.setItem('__t','1');"
                                "localStorage.setItem('pinPrefs',%s);}}catch(e){}" % json.dumps(json.dumps(p)))
        if init:
            context.add_init_script(init)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/*", self.route)
        page.goto("http://viewer.test/?lang=%s%s" % (lang, hash_))
        page.wait_for_function("typeof OPEN_ALL!=='undefined'&&OPEN_ALL.length>=3&&META", timeout=20000)
        page.wait_for_timeout(300)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page

    @staticmethod
    def cdp(page):
        """A CDP session for touch input."""
        return page.context.new_cdp_session(page)

    @staticmethod
    def touch(cdp, kind, pts):
        """One CDP touch event (touchStart/touchMove/touchEnd) at the given points."""
        cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": [{"x": x, "y": y, "id": i} for i, (x, y) in enumerate(pts)]})

    def swipe(self, cdp, x0, y0, x1, y1, steps=12, dt=0.016, hold=0.0):
        """A one-finger drag from (x0,y0) to (x1,y1) in steps, dt seconds apart (hold = still time before moving)."""
        self.touch(cdp, "touchStart", [(x0, y0)])
        if hold:
            time.sleep(hold)
        for i in range(1, steps + 1):
            self.touch(cdp, "touchMove", [(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps)])
            time.sleep(dt)
        self.touch(cdp, "touchEnd", [])

    def tap(self, cdp, x, y, hold=0.05):
        """A short tap (hold = how long the finger stays down)."""
        self.touch(cdp, "touchStart", [(x, y)])
        time.sleep(hold)
        self.touch(cdp, "touchEnd", [])

    @staticmethod
    def center(page, sel):
        """The center of an element's box."""
        b = page.locator(sel).first.bounding_box()
        return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2

    @staticmethod
    def on_page(page, fx, fy, n=1):
        """A point on page n at fractions (fx, fy) of its box - the test pins' marks sit at y 0.2/0.35/0.5, x 0.15-0.65."""
        b = page.locator('#p%d' % n).bounding_box()
        return b["x"] + b["width"] * fx, b["y"] + b["height"] * fy

    def long_press_pick(self, cdp, page, x=None, y=None):
        """A long-press quick selection at (x, y) (default: a clear spot near the top of page 1); waits for the composer."""
        if x is None:
            x, y = self.on_page(page, 0.3, 0.1)
        self.touch(cdp, "touchStart", [(x, y)])
        time.sleep(0.6)
        self.touch(cdp, "touchEnd", [])
        page.wait_for_function("CUR&&CUR.lo&&!document.querySelector('#composer').hidden", timeout=8000)
        page.wait_for_timeout(300)

    def mouse_pick(self, page):
        """A mouse drag on page 1 (clear of the marks) through the real pick path; the in-process server answers /api/pick."""
        page.evaluate("document.querySelector('#left').scrollTop=0")
        x0, y0 = self.on_page(page, 0.3, 0.07)
        x1, y1 = self.on_page(page, 0.7, 0.12)
        page.mouse.move(x0, y0)
        page.mouse.down()
        page.mouse.move(x1, y1, steps=5)
        page.mouse.up()
        page.wait_for_function("CUR&&CUR.lo&&!document.querySelector('#composer').hidden", timeout=8000)
        page.wait_for_timeout(100)


# ---------------------------------------------------------------- A. collapsing the panel with a mouse (wide)

class DesktopPanelCollapse(ViewerBase):
    """Wide (1100px and up): the panel collapses by dragging its handle past half its minimum and comes back from the rail,
    the nav bar's [핀 N], Ctrl+\\, the handle's keys, or anything that needs the panel (a pick, a mark, a link)."""

    def drag_grip(self, page, dx_list, release=True):
        """Mouse-drag the handle right by each dx in turn (from its start), probing after each step."""
        g = page.locator('#grip').bounding_box()
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
                self.assertEqual((pre["w"], pre["preview"], pre["listOpacity"], pre["gripCursor"]), (280, True, "0.4", "w-resize"))
                self.assertFalse(back["preview"])                                   # back above T restores at once
                page.wait_for_function("!SIDE_OPEN&&!document.body.classList.contains('side-closing')")
                s = page.evaluate(PROBE)
                self.assertIsNone(s["list"])
                self.assertIsNone(s["bar1"])                                         # the tools hide with the panel
                self.assertAlmostEqual(s["grip"]["r"], s["vw"], delta=1)             # the rail sits at the right edge
                self.assertEqual(s["grip"]["w"], 6)
                self.assertIsNotNone(s["nav"])
                self.assertEqual((s["prefs"].get("sideClosed"), s["prefs"].get("side")), (True, 400))   # saved width untouched
                self.assertEqual((s["valuenow"], s["label"]), ("0", "패널 폭 · 접힘"))
                nav = page.locator('#nav-side')
                self.assertEqual(nav.get_attribute("aria-expanded"), "false")
                self.assertEqual(nav.locator('.side-n').inner_text(), "3")
                self.assertTrue(nav.locator('.rv-n').is_visible())                  # the purple review pill
                self.assertGreater(s["nav"]["x"], s["vw"] - 200)                    # right end of the nav bar
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
        g = page.locator('#grip').bounding_box()
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
        page.wait_for_timeout(400)
        s = page.evaluate(PROBE)
        self.assertEqual((s["open"], s["w"]), (True, 280))
        self.assertEqual(page.locator('#toasts .toast').count(), 0)

    def test_pointercancel_restores_the_width_and_state_from_before_the_drag(self):
        """A cancelled drag (the browser took the pointer) leaves the panel as it was."""
        page = self.view(DESK, prefs={"side": 380})
        page.evaluate("document.querySelector('#grip').addEventListener('pointerdown',e=>{window.__pid=e.pointerId;})")
        self.drag_grip(page, [300], release=False)
        page.evaluate("document.querySelector('#grip').dispatchEvent(new PointerEvent('pointercancel',{pointerId:window.__pid,bubbles:true}))")
        page.mouse.up()
        page.wait_for_timeout(300)
        s = page.evaluate(PROBE)
        self.assertEqual((s["open"], s["w"], s["preview"]), (True, 380, False))

    def test_handle_keys_follow_the_window_splitter_pattern(self):
        """Home = minimum, End = maximum, Enter collapses and reopens to the saved width, Space cycles the presets."""
        page = self.view(DESK, prefs={"side": 400})
        grip = page.locator('#grip')
        grip.focus()
        page.keyboard.press("Home")
        self.assertEqual(page.evaluate(PROBE)["w"], 280)
        page.keyboard.press("End")
        self.assertEqual(page.evaluate(PROBE)["w"], 914)                         # min(80%, 1400 - 486)
        page.keyboard.press("ArrowRight")
        self.assertEqual(page.evaluate(PROBE)["w"], 898)
        page.keyboard.press("Enter")
        page.wait_for_function("!SIDE_OPEN&&!document.body.classList.contains('side-closing')")
        s = page.evaluate(PROBE)
        self.assertEqual((s["valuenow"], s["label"], s["prefs"].get("side")), ("0", "패널 폭 · 접힘", 898))
        self.assertEqual(page.evaluate("document.activeElement.id"), "grip")    # the rail stays in the tab order
        page.keyboard.press("Enter")
        page.wait_for_function("SIDE_OPEN")
        self.assertEqual(page.evaluate(PROBE)["w"], 898)
        page.keyboard.press(" ")
        self.assertEqual(page.evaluate(PROBE)["w"], 300)                         # the next preset wraps to the narrowest

    def test_ctrl_backslash_toggles_the_panel_and_moves_focus_to_the_pin_toggle(self):
        """Ctrl+\\ outside text fields; a focus inside the collapsing panel lands on [핀 N]."""
        page = self.view(DESK)
        page.locator('#btn-reload').focus()
        page.keyboard.press("Control+Backslash")
        page.wait_for_function("!SIDE_OPEN")
        self.assertEqual(page.evaluate("document.activeElement.id"), "nav-side")
        page.keyboard.press("Control+Backslash")
        page.wait_for_function("SIDE_OPEN")
        self.mouse_pick(page)
        page.locator('#note').focus()
        page.keyboard.press("Control+Backslash")
        page.wait_for_timeout(200)
        self.assertTrue(page.evaluate("SIDE_OPEN"))                               # ignored inside a text field

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
        self.assertFalse(page.locator('#meta-txt').is_visible())
        page.evaluate("toast('핀 #1 저장됨 · pins.md 갱신','ok')")
        t = page.locator('#toasts .toast').bounding_box()
        left = page.evaluate("(()=>{const L=document.querySelector('#left'),r=L.getBoundingClientRect();return r.left+L.clientLeft+L.clientWidth;})()")
        self.assertLessEqual(t["x"] + t["width"], left)
        self.assertLessEqual(t["y"] + t["height"], s["bar2"]["y"])
        self.assertFalse(page.locator('#rv-chip').is_visible())                  # the review count rides on [핀 N]

    def test_whatever_needs_the_panel_opens_a_collapsed_one_without_remembering(self):
        """A new pick, a mark badge, a pin link, the review list and an in-text #N all open it; the saved choice stays."""
        page = self.view(DESK, prefs={"sideClosed": True})
        steps = [("pick", lambda: self.mouse_pick(page)),
                 ("mark", lambda: page.locator('.mark b').first.click()),
                 ("link", lambda: page.evaluate("openPinFromLink(DOC,1)")),
                 ("review", lambda: page.evaluate("gotoReview()")),
                 ("ref", lambda: page.evaluate("gotoPinRef(2)"))]
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
                text = page.locator('#coach-t').inner_text()
                self.assertIn(needle, text)
                self.assertEqual(bool(HANGUL.search(text)), lang == "ko")
                page.evaluate("document.querySelector('#coach').hidden=true; setSide(true,true)")
                self.collapse(page)
                self.assertTrue(page.locator('#coach').is_hidden())

    def test_tooltip_hides_as_soon_as_the_handle_is_pressed(self):
        """The handle's description no longer stays over the PDF while dragging."""
        page = self.view(DESK)
        g = page.locator('#grip').bounding_box()
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
                nav = page.locator('#nav-side')
                self.assertTrue(nav.locator('.c-dot').is_visible())
                label = nav.get_attribute("aria-label")
                self.assertIn("작성 중" if lang == "ko" else "draft", label)
                self.assertEqual(bool(HANGUL.search(label + page.locator('#grip').get_attribute("aria-label"))), lang == "ko")


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
        page.locator('#nav-side').click()
        page.wait_for_function("SIDE_OPEN")
        self.assertEqual(page.evaluate(PROBE)["w"], 410)

    def test_mid_drag_collapse_is_remembered_like_the_toggle(self):
        """Unfolded side-by-side (901-1099px) with a mouse: a drag-collapse stores midClosed, sideMid stays."""
        page = self.view({"viewport": {"width": 1000, "height": 800}}, prefs={"sideMid": 360})
        g = page.locator('#grip').bounding_box()
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
        self.tap(cdp, *self.center(page, '#btn-side'))
        page.wait_for_function("SIDE_OPEN&&MID_OVERLAY")
        page.wait_for_timeout(250)

    def panel_point(self, page):
        """A point on the list inside the panel, clear of buttons."""
        r = page.locator('#right').bounding_box()
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
            time.sleep(0.03)
        followed = page.evaluate("document.querySelector('#right').getBoundingClientRect().right")
        self.assertGreater(followed, 842 + 40)                                    # right: -dx, not a transform
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
        page.wait_for_timeout(400)
        self.assertTrue(page.evaluate("SIDE_OPEN"))
        self.assertEqual(page.evaluate("Math.round(document.querySelector('#right').getBoundingClientRect().right)"), 842)
        self.swipe(cdp, x, y, x + 60, y, steps=2, dt=0)                            # CDP moves land ~30ms apart: ~0.9px/ms
        page.wait_for_function("!SIDE_OPEN")

    def test_a_draft_rubber_bands_the_swipe_and_never_closes(self):
        """Composing: at most 24px of follow, then back."""
        page = self.view(FOLD)
        cdp = self.cdp(page)
        self.long_press_pick(cdp, page)
        x, y = self.center(page, '#c-page')
        self.touch(cdp, "touchStart", [(x, y)])
        for i in range(1, 16):
            self.touch(cdp, "touchMove", [(x + 15 * i, y)])
            time.sleep(0.02)
        shift = page.evaluate("842-document.querySelector('#right').getBoundingClientRect().right")
        self.assertGreaterEqual(shift, -24.5)
        self.assertLess(shift, 0)
        self.touch(cdp, "touchEnd", [])
        page.wait_for_timeout(400)
        self.assertTrue(page.evaluate("SIDE_OPEN&&!document.querySelector('#composer').hidden"))

    def follow_during(self, page, cdp, x, y, dx, dy=0, hold=0.0):
        """Drag from (x,y) by (dx,dy) and report how far the panel's right edge moved before the finger lifts."""
        self.touch(cdp, "touchStart", [(x, y)])
        if hold:
            time.sleep(hold)
        for i in range(1, 11):
            self.touch(cdp, "touchMove", [(x + dx * i / 10, y + dy * i / 10)])
            time.sleep(0.02)
        moved = page.evaluate("Math.round(document.querySelector('#right').getBoundingClientRect().right-innerWidth)")
        self.touch(cdp, "touchEnd", [])
        page.wait_for_timeout(350)
        return moved

    def test_swipes_starting_on_scrollers_fields_or_after_a_still_press_are_ignored(self):
        """.seg and text fields keep their own horizontal scrolling (the panel does not even rubber-band); a 450ms still
        press is a text selection and a mostly vertical drag is a scroll - neither dismisses the panel."""
        page = self.view(FOLD)
        cdp = self.cdp(page)
        self.long_press_pick(cdp, page)
        for sel in ('#c-levels', '#note'):
            with self.subTest(start=sel):
                x, y = self.center(page, sel)
                self.assertEqual(self.follow_during(page, cdp, x - 60, y, 150), 0)
                self.assertTrue(page.evaluate("SIDE_OPEN"))
        page.keyboard.press("Escape")                                              # no draft from here on
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
        p1 = page.locator('#p1').bounding_box()
        self.long_press_pick(cdp, page, p1["x"] + p1["width"] * 0.78, p1["y"] + 300)
        page.wait_for_timeout(400)
        box = page.locator('.sel.pending').bounding_box()
        panel = page.locator('#right').bounding_box()
        self.assertLessEqual(box["x"] + box["width"], panel["x"])

    def test_tapping_the_handle_never_clicks_what_lands_under_the_finger(self):
        """s07: a tap cycles the width, and the ghost click that followed opened edits and cards."""
        page = self.view(FOLD)
        cdp = self.cdp(page)
        self.open_panel(page, cdp)
        page.evaluate(CLICKS)
        widths = []
        for _ in range(4):
            g = page.locator('#grip').bounding_box()
            self.tap(cdp, g["x"] + g["width"] / 2, 240)
            page.wait_for_timeout(500)
            widths.append(page.evaluate(PROBE)["w"])
        self.assertEqual(len(set(widths)), 3)
        self.assertEqual([c for c in page.evaluate("window.__clicks") if c != "grip"], [])
        self.assertEqual(page.evaluate("[...document.querySelectorAll('.pin.editing')].length"), 0)

    def test_select_mode_tap_pick_never_clicks_the_panel_that_opens_under_it(self):
        """s12: a tap-pick in [선택] mode opened the panel under the finger and its ghost click (and ghost focus) hit it."""
        for dev, (x, y) in ((FOLD, (650, 300)), (FOLD, (700, 500)), (PHONE, (190, 600)), (PHONE, (100, 700))):
            with self.subTest(width=dev["viewport"]["width"], at=(x, y)):
                page = self.view(dev)
                cdp = self.cdp(page)
                self.tap(cdp, *self.center(page, '#btn-select'))
                page.wait_for_timeout(300)
                page.evaluate(CLICKS)
                self.tap(cdp, x, y)
                page.wait_for_function("CUR&&CUR.lo", timeout=8000)
                page.wait_for_timeout(400)
                self.assertEqual(page.evaluate("window.__clicks"), [])
                self.assertEqual(page.evaluate("KIND_NEW"), "fix")
                self.assertNotEqual(page.evaluate("document.activeElement.id"), "note")

    def test_pin_toggle_while_composing_collapses_with_a_draft_dot(self):
        """[핀] while composing still collapses (explicit), and [핀 N] shows the hidden draft."""
        page = self.view(FOLD)
        cdp = self.cdp(page)
        self.long_press_pick(cdp, page)
        self.tap(cdp, *self.center(page, '#btn-side'))
        page.wait_for_function("!SIDE_OPEN")
        self.assertTrue(page.locator('#btn-side .c-dot').is_visible())
        self.assertIn("작성 중", page.locator('#btn-side').get_attribute("aria-label"))

    def test_right_swipe_never_navigates_back(self):
        """s05e: a right swipe on the PDF or the panel used to go back in history and leave Limn."""
        page = self.view(FOLD)
        navs = []
        page.on("framenavigated", lambda f: navs.append(f.url))
        cdp = self.cdp(page)
        for start in ((200, 300), (20, 300)):
            self.swipe(cdp, start[0], start[1], start[0] + 250, start[1] + 10)
            page.wait_for_timeout(500)
        self.open_panel(page, cdp)
        self.swipe(cdp, 200, 300, 450, 310)
        page.wait_for_timeout(500)
        self.assertEqual(navs, [])
        css = page.evaluate("[getComputedStyle(document.documentElement).overscrollBehaviorX,getComputedStyle(document.body).overscrollBehaviorX,"
                            "getComputedStyle(document.querySelector('#right')).touchAction]")
        self.assertEqual(css[:2], ["none", "none"])
        self.assertIn("pan-y", css[2])

    def test_double_tap_on_the_pdf_toggles_fit_width_and_2x_around_the_point(self):
        """Outside [선택] mode: fit -> 2x keeping the tapped spot under the finger, then back to fit."""
        page = self.view(FOLD)
        cdp = self.cdp(page)
        w0 = page.evaluate("W")
        at = "(()=>{const a=zoomAnchor(300,400);return [a.pg.id,+a.fx.toFixed(3),+a.fy.toFixed(3)];})()"
        before = page.evaluate(at)
        self.tap(cdp, 300, 400)
        time.sleep(0.1)
        self.tap(cdp, 300, 400)
        page.wait_for_timeout(400)
        self.assertAlmostEqual(page.evaluate("W"), w0 * 2, delta=2)
        after = page.evaluate(at)
        self.assertEqual(after[0], before[0])
        self.assertAlmostEqual(after[1], before[1], delta=0.01)
        self.tap(cdp, 300, 400)
        time.sleep(0.1)
        self.tap(cdp, 300, 400)
        page.wait_for_timeout(400)
        self.assertAlmostEqual(page.evaluate("W"), w0, delta=2)
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
        r = page.locator('#right').bounding_box()
        self.swipe(cdp, r["x"] + 30, r["y"] + 150, r["x"] + 330, r["y"] + 150, steps=6, dt=0.01)
        page.wait_for_timeout(400)
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
        x, y = self.center(page, '#btn-select')
        self.swipe(cdp, x, y, x, y - 350, steps=10)
        page.wait_for_timeout(400)
        s = page.evaluate(self.SH)
        self.assertTrue(s["open"])
        self.assertLess(s["top"], 500)
        self.assertFalse(page.evaluate("SELMODE"))
        self.assertEqual(page.evaluate("window.__clicks"), [])
        x, y = self.center(page, '#btn-select')
        self.swipe(cdp, x, y, x, 820, steps=10)
        page.wait_for_function("!SIDE_OPEN")

    def test_pulling_down_content_at_its_top_lowers_the_sheet(self):
        """Nested scroll hand-off: at scrollTop 0 a downward drag in the list moves the sheet, not the list."""
        page = self.view(PHONE)
        cdp = self.cdp(page)
        self.tap(cdp, *self.center(page, '#btn-side'))
        page.wait_for_function("SIDE_OPEN")
        page.wait_for_timeout(300)
        top0 = page.evaluate(self.SH)["top"]
        y = page.locator('#list').bounding_box()["y"] + 60
        self.swipe(cdp, 190, y, 190, y + 120, steps=12, dt=0.03)
        page.wait_for_timeout(300)
        s = page.evaluate(self.SH)
        self.assertTrue(s["open"])
        self.assertGreater(s["top"], top0 + 80)
        y = page.locator('#list').bounding_box()["y"] + 40
        self.swipe(cdp, 190, y, 190, 830, steps=12, dt=0.02)
        page.wait_for_function("!SIDE_OPEN")

    def test_a_downward_fling_collapses_and_an_upward_fling_steps_up(self):
        """Velocity counts: a short fast pull-down collapses (it used to only lower the sheet), a flick up goes to the next stop."""
        page = self.view(PHONE, prefs={"sheetF": 0.45})
        cdp = self.cdp(page)
        self.tap(cdp, *self.center(page, '#btn-side'))
        page.wait_for_function("SIDE_OPEN")
        page.wait_for_timeout(300)
        x, y = self.center(page, '#sheet-grip')
        self.swipe(cdp, x, y, x, y - 60, steps=2, dt=0)
        page.wait_for_timeout(300)
        self.assertAlmostEqual(page.evaluate("prefs().sheetF"), 0.64, delta=0.01)
        x, y = self.center(page, '#sheet-grip')
        self.swipe(cdp, x, y, x, y + 70, steps=3, dt=0.01)
        page.wait_for_function("!SIDE_OPEN")

    def test_a_draft_stops_the_sheet_at_30_percent_instead_of_collapsing(self):
        """phone_05: dragging the sheet down while composing collapsed it and hid the note."""
        page = self.view(PHONE)
        cdp = self.cdp(page)
        self.long_press_pick(cdp, page)
        x, y = self.center(page, '#sheet-grip')
        self.swipe(cdp, x, y, x, 825, steps=14)
        page.wait_for_timeout(400)
        s = page.evaluate(self.SH)
        self.assertTrue(s["open"])
        self.assertAlmostEqual(s["h"] / 832, 0.3, delta=0.02)
        self.assertFalse(page.evaluate("document.querySelector('#composer').hidden"))

    def test_tapping_the_sheet_handle_never_clicks_what_lands_under_the_finger(self):
        """s07 phone: each tap moved the sheet and the ghost click hit a card, the note or the PDF."""
        page = self.view(PHONE)
        cdp = self.cdp(page)
        page.evaluate(CLICKS)
        for _ in range(5):
            x, y = self.center(page, '#sheet-grip')
            self.tap(cdp, x, y)
            page.wait_for_timeout(500)
        self.assertEqual([c for c in page.evaluate("window.__clicks") if c != "sheet-grip"], [])

    def test_right_swipe_on_the_pdf_never_navigates_back(self):
        """s05e phone."""
        page = self.view(PHONE)
        navs = []
        page.on("framenavigated", lambda f: navs.append(f.url))
        self.swipe(self.cdp(page), 200, 300, 380, 310)
        page.wait_for_timeout(500)
        self.assertEqual(navs, [])

    def test_back_gesture_closes_the_sheet_first_and_toggling_adds_no_history(self):
        """History fallback: back closes the open sheet and stays; opening/closing by button leaves one entry at most."""
        page = self.view(PHONE, init=NO_CLOSE_WATCHER)
        cdp = self.cdp(page)
        n0 = page.evaluate("history.length")
        for _ in range(3):
            self.tap(cdp, *self.center(page, '#btn-side'))
            page.wait_for_function("SIDE_OPEN")
            self.tap(cdp, *self.center(page, '#btn-side'))
            page.wait_for_function("!SIDE_OPEN")
            page.wait_for_timeout(200)
        self.assertLessEqual(page.evaluate("history.length"), n0 + 1)
        boot = page.evaluate("window.__pinViewerBoot")
        self.tap(cdp, *self.center(page, '#btn-side'))
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
        self.tap(cdp, *self.center(page, '#btn-side'))
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
        r = page.locator('#docs-menu').bounding_box()
        self.swipe(cdp, 190, r["y"] + 20, 190, r["y"] + 20 + r["height"] * 0.6, steps=10, dt=0.02)
        page.wait_for_function("!document.querySelector('#docs-menu').open")

    def test_stacked_toasts_open_on_a_tap(self):
        """More than three toasts: a '+N' button under the stack opens it on touch (hover/focus only did before)."""
        page = self.view(PHONE)
        page.evaluate("for(let i=1;i<=5;i++)toast('알림 '+i,'ok')")
        visible = "[...document.querySelectorAll('#toasts .toast')].filter(t=>t.getClientRects().length).length"
        self.assertEqual(page.evaluate(visible), 3)
        more = page.locator('#toasts-more')
        self.assertTrue(more.is_visible())
        self.tap(self.cdp(page), *self.center(page, '#toasts-more'))
        page.wait_for_function(visible + "===5")


# ---------------------------------------------------------------- B. the rest of the approved findings

class DesktopMisc(ViewerBase):
    """Undo for a discarded selection and after saving, Esc in the change view, dialogs, hit targets, the first hint."""

    def test_escape_or_cancel_with_a_note_offers_undo_that_brings_it_all_back(self):
        """Discarding a selection with a written note is undoable for the toast's 6 seconds: selection, note and box."""
        for how in ("escape", "cancel"):
            with self.subTest(how=how):
                page = self.view(DESK)
                self.mouse_pick(page)
                lo = page.evaluate("CUR.lo")
                page.locator('#note').fill("길게 쓴 메모")
                if how == "escape":
                    page.keyboard.press("Escape")
                else:
                    page.locator('#btn-cancel').click()
                self.assertTrue(page.evaluate("document.querySelector('#composer').hidden&&!CUR"))
                page.locator("#toasts .toast", has_text="선택 취소됨").locator("button", has_text="되돌리기").click()
                self.assertEqual(page.evaluate("[!document.querySelector('#composer').hidden, CUR&&CUR.lo, "
                                               "document.querySelector('#note').value, !!document.querySelector('.sel.pending')]"),
                                 [True, lo, "길게 쓴 메모", True])

    def test_escape_with_an_empty_note_needs_no_undo(self):
        """Nothing written, nothing to lose: no toast."""
        page = self.view(DESK)
        self.mouse_pick(page)
        page.keyboard.press("Escape")
        self.assertEqual(page.locator('#toasts .toast').count(), 0)

    def test_undo_right_after_saving_reopens_the_composer_with_the_same_selection_and_note(self):
        """[되돌리기] on '핀 #N 저장됨' takes the pin back and hands the selection and note back for another try."""
        page = self.view(DESK)
        self.mouse_pick(page)
        lo = page.evaluate("CUR.lo")
        page.locator('#note').fill("저장 뒤 되돌리기")
        page.keyboard.press("Control+Enter")
        page.wait_for_function("OPEN_ALL.length===4")
        page.locator("#toasts button", has_text="되돌리기").first.click()
        page.wait_for_function("OPEN_ALL.length===3&&!document.querySelector('#composer').hidden")
        self.assertEqual(page.evaluate("[CUR&&CUR.lo, document.querySelector('#note').value]"), [lo, "저장 뒤 되돌리기"])

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
                text = page.locator('#coach-t').inner_text()
                self.assertTrue(text)
                self.assertEqual(bool(HANGUL.search(text)), lang == "ko")
                self.assertEqual(page.evaluate("prefs().coach.mouse"), 1)


if __name__ == "__main__":
    unittest.main()

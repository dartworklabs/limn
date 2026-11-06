"""Where the phone and tablet sheet stands when a slow drag lets it go (docs/handbook/viewer.md §패널 폭과 시트 높이, issue #456).

Let go without a fling, the sheet stays at the height it was let go at (sheetRelease). It took that height as the shown
height over the screen, saved at 1/1000, and CSS draws the saved fraction rounded down to a whole pixel: pulled by the
grabber up to the document bar, where the sheet is held at the visible height less --sheet-gap (976 of 1024), it saved
0.953 and stood 1px below the bar (top 49); with the keyboard up it saved the shorter held height and stayed that short
when the keyboard went; let go anywhere else, it came back 1px lower about every other time. Only a fling reached the
highest stop. By the grabber with a mouse pointer, the drag's samples 100ms apart (dragSample), so the release is never a
fling however fast the runner delivers the moves, at 768 x 1024 (the tablet sheet) and 390 x 844 (the phone) by touch, and
let go below the bar at 800 x 1280 too (a fraction at 1/1000 is more than a pixel there), in Chromium and Firefox; pulled
down by the list at its top (pullDown, touch events) in Chromium. The keyboard is a visual viewport shrunk by 300px (test_viewer_input.py's KB_VISUAL_ONLY).

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_sheet_release.py
"""

from helpers import add_pin
from helpers_access import ALICE, actor
from helpers_browser import BrowserBase, Finger, settle, touch_line

# A soft keyboard that shrinks only the visual viewport: visualViewport.height drops by window.__setKb(n)'s n and a resize
# event follows (the viewer's onViewport sets --kb and --vvh from it).
KB = """window.__kb = 0;
(() => {const vv = window.visualViewport; if (!vv) return;
  const real = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(vv), 'height');
  Object.defineProperty(vv, 'height', {configurable: true, get() {return window.__kb ? document.documentElement.clientHeight - window.__kb : real.get.call(vv);}});
  window.__setKb = n => {window.__kb = n; vv.dispatchEvent(new Event('resize'));};})();"""
# Every drag sample 100ms after the one before it, whenever it came; and each release's speed kept (window.__v, px/ms).
SLOW = """() => {const sample = dragSample, release = sheetRelease;
  dragSample = (pts, _t, pos) => sample(pts, pts.length ? pts[pts.length - 1][0] + 100 : 0, pos);
  sheetRelease = (...a) => {window.__v = a[2]; return release(...a);};}"""
# The sheet's top and height, and the band's saved height.
SHEET = """() => {const r = document.querySelector('#right').getBoundingClientRect(), p = prefs();
  return {top: r.top, h: r.height, f: BAND === LAYOUT_BAND.TABLET_SHEET ? p.sheetFTab : p.sheetF};}"""
TABLET, PHONE, TALL = (768, 1024), (390, 844), (800, 1280)


class SheetDrag(BrowserBase):
    """The sheet open on a touch screen, its drags slow."""

    def setUp(self):
        """One open pin, so the sheet has a list."""
        super().setUp()
        add_pin(
            {"file": str(self.main), "lo": 4, "hi": 4, "page": 1, "note": "p", "frac": [0.1, 0.2, 0.3, 0.02]},
            actor(ALICE),
        )

    def sheet(self, size, kb=0):
        """The viewer by touch at size (w, h), the sheet open at 64% and its drags slow; the keyboard kb px up."""
        device = {"viewport": {"width": size[0], "height": size[1]}, "has_touch": True, "device_scale_factor": 2}
        if self.BROWSER_ENGINE == "chromium":
            device["is_mobile"] = True  # Firefox has no such mode
        page = self.open(1, init=KB, **device)
        page.tap("#btn-side")
        page.evaluate("setSheetF(0.64)")
        settle(page)
        if kb:
            page.evaluate("n => __setKb(n)", kb)
            settle(page)
        page.evaluate(SLOW)
        return page

    def drag(self, page, y1, steps=12):
        """Drag the grabber to y1 in steps equal moves and let go: the sheet as it was held, and as it stands."""
        g = page.locator("#sheet-grip").bounding_box()
        x, y = g["x"] + g["width"] / 2, g["y"] + g["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        for _, py in touch_line(x, y, x, y1, steps)[1:]:
            page.mouse.move(x, py)
        held = page.evaluate(SHEET)
        page.mouse.up()
        settle(page)
        self.assertGreater(page.evaluate("window.__v"), -0.5)  # not an upward fling
        return held, page.evaluate(SHEET)


class GrabberRelease(SheetDrag):
    """In Chromium: the sheet let go after a slow drag by its grabber."""

    def test_pulled_slowly_up_to_the_bar_it_stays_on_the_bar(self):
        """Pulled past the document bar and let go slowly, the sheet stands at its highest stop: its top on the bar's
        foot (48px), as it was held, and the height saved is 1."""
        for size in (TABLET, PHONE):
            with self.subTest(size=size):
                page = self.sheet(size)
                held, shown = self.drag(page, 20)
                self.assertEqual(round(held["top"]), 48, held)  # held at its highest
                self.assertEqual((round(shown["top"]), shown["h"], shown["f"]), (48, held["h"], 1), shown)
                page.context.close()

    def test_pulled_up_with_the_keyboard_up_it_stays_highest_when_the_keyboard_goes(self):
        """With the keyboard up the highest the sheet goes is shorter (the visible height less the gap). Let go there, it
        is still the highest stop: on the bar while the keyboard is up, and on the bar when it goes."""
        for size in (TABLET, PHONE):
            with self.subTest(size=size):
                page = self.sheet(size, kb=300)
                held, shown = self.drag(page, 20)
                self.assertEqual((round(held["top"]), held["h"]), (48, size[1] - 300 - 48), held)
                self.assertEqual((round(shown["top"]), shown["h"], shown["f"]), (48, held["h"], 1), shown)
                page.evaluate("__setKb(0)")
                settle(page)
                down = page.evaluate(SHEET)
                self.assertEqual((round(down["top"]), down["h"]), (48, size[1] - 48), down)
                page.context.close()

    def test_let_go_below_the_bar_it_stays_at_the_height_it_was_let_go_at(self):
        """Its grabber let go anywhere from 30% to 70% down the screen, every 23px, the sheet keeps the whole pixel it was
        held at."""
        for size in (TABLET, PHONE, TALL):
            with self.subTest(size=size):
                page = self.sheet(size)
                for y1 in range(int(size[1] * 0.3), int(size[1] * 0.7), 23):
                    held, shown = self.drag(page, y1, steps=8)
                    self.assertEqual(shown["h"], held["h"], (y1, held, shown))
                page.context.close()

    def test_the_close_and_fling_thresholds_are_judged_on_the_height_it_shows(self):
        """The half pixel the sheet keeps when it stays is not counted where its release is judged. A fling up from 30% to
        440px on the tablet goes to the next stop above the height it shows (45%), not past it; let go slowly at 211px of
        846 (under 25%), the sheet closes. Mutation: the kept height (shown + 0.5px) judged instead -> the fling skips to
        64% and the slow release comes back at 30%, fails (found in review)."""
        page = self.sheet(TABLET)
        page.evaluate("setSheetF(0.3)")
        settle(page)
        # samples 10ms apart, however the moves arrive: the release reads as a fling
        page.evaluate(
            "() => {dragSample = (pts, _t, pos) => {pts.push([pts.length ? pts[pts.length - 1][0] + 10 : 0, pos]);"
            " while (pts.length > 2 && pts[pts.length - 1][0] - pts[0][0] > 100) pts.shift();};}"
        )
        g = page.locator("#sheet-grip").bounding_box()
        x, y = g["x"] + g["width"] / 2, g["y"] + g["height"] / 2
        h = page.evaluate(SHEET)["h"]
        page.mouse.move(x, y)
        page.mouse.down()
        for _, py in touch_line(x, y, x, y - (440 - h), 12)[1:]:
            page.mouse.move(x, py)
        page.mouse.up()
        settle(page)
        self.assertEqual(page.evaluate(SHEET)["f"], 0.45)
        page.context.close()
        page = self.sheet((390, 846))
        g = page.locator("#sheet-grip").bounding_box()
        y = g["y"] + g["height"] / 2
        h = page.evaluate(SHEET)["h"]
        self.drag(page, y + (h - 211), steps=50)
        self.assertFalse(page.evaluate("SIDE_OPEN"), "let go under 25% of the screen, the sheet closes")


class GrabberReleaseFirefox(GrabberRelease):
    """The same releases in Firefox."""

    BROWSER_ENGINE = "firefox"


class ListPullRelease(SheetDrag):
    """In Chromium (touch events through CDP): the sheet let go after a slow pull down by its list."""

    def test_pulled_down_by_its_list_it_stays_at_the_height_it_was_let_go_at(self):
        """The list at its top pulled down by a finger lowers the sheet (pullDown); let go slowly, every 9px of pull from
        40px to 130px, the sheet keeps the whole pixel it was held at."""
        page = self.sheet(TABLET)
        page.evaluate("setSheetF(1)")
        settle(page)
        cdp = page.context.new_cdp_session(page)
        for pull in range(40, 131, 9):
            page.evaluate("setSheetF(1)")
            settle(page)
            y = page.locator("#list").bounding_box()["y"] + 40
            finger = Finger(cdp).down(TABLET[0] / 2, y).glide(TABLET[0] / 2, y + pull, 8)
            held = page.evaluate(SHEET)
            finger.up()
            settle(page)
            shown = page.evaluate(SHEET)
            self.assertLess(page.evaluate("window.__v"), 0.5)  # not a downward fling
            self.assertLess(held["h"], 976, (pull, held))  # the pull moved the sheet
            self.assertEqual(shown["h"], held["h"], (pull, held, shown))

"""A mark badge a cover is over is no Tab stop, and Tab shows the badge it rests on (docs/handbook/viewer.md §모바일 레이아웃,
issue #418).

Tab put the focus ring on a badge under the tablet's sheet, where nobody could see it, and its tooltip floated over the sheet.
Read as the keyboard meets it - which badges a Tab walk through the page stops on - in Chromium and Firefox: a badge under the
open sheet is passed over, one above it is not; closing the sheet gives the passed-over badges back (but for the one under its
bar) and opening it takes them away again; a badge scrolled out of the pages' box stays a stop - one scrolled above the pages
on the tablet, one zoomed past the pages' right edge on the desktop, where the panel stands beside it. The pass also stays
cheap with hundreds of badges, since a scroll runs it every frame.

The covers are not the panel alone: the status line standing on the sheet (the first visit's line on the tablet's closed
sheet) and the closed sheet's bar hid badges Tab still rested on, and a badge Tab brought in from out of view was scrolled by
the browser to the pages' edge, under the sheet, where its focus and description stayed. Every badge a walk rests on is read
as seen - the topmost element at its centre, a press area drawn past its element's box aside (the status line's and the
bar's reach 44px over the pages) - forwards and backwards, with the status line up, zoomed in, the sheet at its three heights
and dragged to the top, the phone's sheet open at a 200% browser zoom; and a focused badge a cover comes over loses its
description and keeps the focus, or is brought out again when the cover is the sheet a key opened.
"""

from helpers import add_pin
from helpers_access import ALICE, actor
from helpers_browser import BrowserBase, settle

TABLET = {"viewport": {"width": 768, "height": 1024}, "is_mobile": True, "has_touch": True, "device_scale_factor": 2}
DESKTOP = {"viewport": {"width": 1440, "height": 900}}
# Each badge as [pin id, its centre's y, whether that centre is inside the panel's box, whether it is inside the pages' box].
BADGES = """() => {const v = document.querySelector('#left').getBoundingClientRect(), p = document.querySelector('#right').getBoundingClientRect();
  const inside = (r, x, y) => x >= r.left && x < r.right && y >= r.top && y < r.bottom;
  return [...document.querySelectorAll('.mark button.mark-jump')].map(b => {const r = b.getBoundingClientRect(),
    x = r.left + r.width / 2, y = r.top + r.height / 2; return [Number(b.dataset.id), Math.round(y), inside(p, x, y), inside(v, x, y)];});}"""
# The pin id of the focused badge, or null when the focus is elsewhere.
FOCUSED = "(() => {const a = document.activeElement; return a && a.matches('.mark button.mark-jump') ? Number(a.dataset.id) : null;})()"
# The focused badge two frames on (after any scroll the focus set off), or null when the focus is not on one: its pin id, its
# centre's y, whether it is seen there - the topmost element at its centre whose own box holds that point is the badge (an
# element answering past its box is a press area drawn out from it, and is passed through) - what is there instead, its
# tabIndex, and whether the description box stands over it.
SEEN = """async () => {await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  const a = document.activeElement; if (!a || !a.matches('.mark button.mark-jump')) return null;
  const r = a.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
  const own = e => {const q = e.getBoundingClientRect(); return x >= q.left && x < q.right && y >= q.top && y < q.bottom;};
  const h = x >= 0 && y >= 0 && x < innerWidth && y < innerHeight ? document.elementsFromPoint(x, y).find(own) || null : null;
  return {id: Number(a.dataset.id), y: Math.round(y), seen: !!h && (h === a || a.contains(h)), at: h ? h.id || h.className : null,
    tab: a.tabIndex, tip: !document.querySelector('#tip').hidden && !!TIP_AT && TIP_AT.el === a};}"""
# Whether the description box is showing.
TIP_UP = "!document.querySelector('#tip').hidden"
PHONE_390 = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True, "device_scale_factor": 3}


def touch(w, h):
    """A w x h touch screen at twice the CSS pixel (Firefox opens it without is_mobile: open_device)."""
    return {"viewport": {"width": w, "height": h}, "is_mobile": True, "has_touch": True, "device_scale_factor": 2}


class CoveredMarks(BrowserBase):
    """In Chromium: the badges a Tab walk meets with the sheet open, closed and reopened, and after a scroll or a zoom."""

    def pins(self, ys, x=0.1):
        """One open pin on page 1 per y fraction in ys, its region a line at x; their ids, top to bottom."""
        return [
            add_pin(
                {
                    "file": str(self.main),
                    "lo": 4 + i,
                    "hi": 4 + i,
                    "page": 1,
                    "note": "pin %d" % i,
                    "frac": [x, y, 0.3, 0.02],
                },
                actor(ALICE),
            ).record["id"]
            for i, y in enumerate(ys)
        ]

    def walk(self, page, presses=60):
        """The pin ids of the badges Tab stops on, in the order met, pressing Tab presses times from the document bar's
        first control - the pages' badges come after the bar and before the panel."""
        page.focus("#nav-toc-toggle")
        met = []
        for _ in range(presses):
            page.keyboard.press("Tab")
            pid = page.evaluate(FOCUSED)
            if pid is not None and pid not in met:
                met.append(pid)
        return met

    def test_a_badge_under_the_open_sheet_is_no_tab_stop_until_the_sheet_closes(self):
        """The tablet with five badges down page 1 and the sheet open: Tab stops on those above the sheet and passes over
        those under it. Closing the sheet with [핀 N] gives them back but for any under the bar left at the bottom;
        opening it again takes them away."""
        ids = self.pins((0.05, 0.25, 0.45, 0.65, 0.85))
        page = self.open(len(ids), **TABLET)
        page.tap("#btn-side")
        settle(page)
        self.assertTrue(page.evaluate("SIDE_OPEN"))
        badges = page.evaluate(BADGES)
        under = [b[0] for b in badges if b[2] and b[3]]
        shown = [b[0] for b in badges if b[3] and not b[2]]
        self.assertTrue(under and shown, badges)  # the sheet covers some badges and leaves others
        self.assertEqual(self.walk(page), shown)
        page.tap("#btn-side")
        settle(page)
        self.assertFalse(page.evaluate("SIDE_OPEN"))
        badges = page.evaluate(BADGES)
        self.assertEqual(self.walk(page), [b[0] for b in badges if b[3] and not b[2]])
        self.assertTrue(set(under) & set(self.walk(page)), badges)  # the closed sheet uncovers what it covered
        page.tap("#btn-side")
        settle(page)
        self.assertEqual(self.walk(page), shown)

    def test_the_stops_follow_a_scroll_and_a_badge_scrolled_above_the_pages_stays_one(self):
        """With the sheet open, the pages scrolled until the fourth badge stands 40 px above the sheet: it has come out
        from under the sheet and is a stop again, the fifth is still under it and is not, and the first - scrolled above
        the pages' box, under the document bar - stays a stop: it is the first badge Tab meets."""
        ids = self.pins((0.05, 0.25, 0.45, 0.65, 0.85))
        page = self.open(len(ids), **TABLET)
        page.tap("#btn-side")
        settle(page)
        stops = "[...document.querySelectorAll('.mark button.mark-jump')].map(b=>b.tabIndex)"
        self.assertEqual(page.evaluate(stops)[3], -1)
        sheet = page.evaluate("document.querySelector('#right').getBoundingClientRect().top")
        page.evaluate("d=>{document.querySelector('#left').scrollTop+=d}", page.evaluate(BADGES)[3][1] - (sheet - 40))
        settle(page)
        badges = page.evaluate(BADGES)
        self.assertEqual([b[3] for b in badges[:4]], [False, True, True, True], badges)  # the first is out of the pages
        self.assertTrue(badges[4][2] and badges[4][3], badges)  # the fifth is still under the sheet
        self.assertEqual(page.evaluate(stops), [0, 0, 0, 0, -1])
        self.assertEqual(self.walk(page, presses=30)[0], ids[0])

    def test_on_the_desktop_a_badge_zoomed_past_the_pages_edge_stays_a_tab_stop(self):
        """The wide desktop, panel beside the pages, page 1 zoomed in and scrolled so one badge's centre lies past the
        pages' right edge, inside the panel's column: no badge leaves the tab order, that one included."""
        ids = self.pins((0.2, 0.3), x=0.55)
        page = self.open(len(ids), **DESKTOP)
        page.evaluate("zoomTo(3)")
        settle(page)
        x = page.evaluate(
            "id=>{const b=document.querySelector('.mark button.mark-jump[data-id=\"'+id+'\"]').getBoundingClientRect(),"
            "p=document.querySelector('#right').getBoundingClientRect();return b.left+b.width/2-(p.left+p.right)/2}",
            ids[1],
        )
        page.evaluate("d=>{document.querySelector('#left').scrollLeft+=d}", x)
        settle(page)
        badges = {b[0]: b for b in page.evaluate(BADGES)}
        self.assertTrue(badges[ids[1]][2] and not badges[ids[1]][3], badges)  # in the panel's column, out of the pages
        self.assertEqual(
            page.evaluate("[...document.querySelectorAll('.mark button.mark-jump')].map(b=>b.tabIndex)"), [0, 0]
        )

    def test_the_pass_stays_cheap_with_three_hundred_badges(self):
        """300 badges on two pages, about half of them on screen around the open tablet sheet: a pass, run as a scroll
        runs it, takes at most 4 ms in the median of 40 (a hit test per badge took 15 ms in Chromium, the box comparison
        0.2). The badges are copies of one real pin's mark spread over the pages - the pass reads only their boxes - so
        the fixture does not save 300 pins."""
        self.pins((0.5,))
        page = self.open(1, **TABLET)
        page.tap("#btn-side")
        settle(page)
        took = page.evaluate(
            """() => {const m = document.querySelector('.mark'), pages = [...document.querySelectorAll('#p1,#p2')];
              let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
              for (let i = 0; i < 299; i++) {const c = m.cloneNode(true); c.style.left = (5 + rnd() * 75) + '%';
                c.style.top = (2 + rnd() * 93) + '%'; c.querySelector('button').dataset.id = String(1000 + i);
                pages[i % 2].append(c);}
              const L = document.querySelector('#left'), runs = [];
              for (let k = 0; k < 40; k++) {L.scrollTop += k % 2 ? -7 : 7; const t = performance.now(); markCoverSkip();
                runs.push(performance.now() - t);}
              const on = [...document.querySelectorAll('.mark button.mark-jump')].filter(b => {const r = b.getBoundingClientRect();
                return r.top >= 0 && r.bottom <= innerHeight;}).length;
              return {n: document.querySelectorAll('.mark button.mark-jump').length, on, median: runs.sort((a, b) => a - b)[20]};}"""
        )
        self.assertEqual(took["n"], 300)
        self.assertGreaterEqual(took["on"], 100, took)
        self.assertLessEqual(took["median"], 4.0, took)


class CoveredMarksSeen(BrowserBase):
    """In Chromium: every badge a Tab walk rests on is seen, whatever covers the pages' edges."""

    def setUp(self):
        """Sixty open pins, three across and ten down each of the two pages, so badges stand at every height: under the
        status line, under a closed bar, out of view below the sheet."""
        super().setUp()
        spots = [
            (pg, x, y)
            for pg in (1, 2)
            for y in (0.03, 0.13, 0.23, 0.33, 0.43, 0.53, 0.63, 0.73, 0.83, 0.93)
            for x in (0.08, 0.5, 0.8)
        ]
        self.ids = [
            add_pin(
                {
                    "file": str(self.main),
                    "lo": 4 + i % 30,
                    "hi": 4 + i % 30,
                    "page": pg,
                    "note": "pin %d" % i,
                    "frac": [x, y, 0.3, 0.02],
                },
                actor(ALICE),
            ).record["id"]
            for i, (pg, x, y) in enumerate(spots)
        ]

    def open_device(self, device):
        """The viewer on device with every pin drawn (is_mobile dropped in Firefox, which has no such mode)."""
        if self.BROWSER_ENGINE != "chromium":
            device = {k: v for k, v in device.items() if k != "is_mobile"}
        return self.open(len(self.ids), **device)

    def walk(self, page, key="Tab", presses=90):
        """Press key presses times from where the focus is; each badge it rests on, as SEEN reads it."""
        met = []
        for _ in range(presses):
            page.keyboard.press(key)
            s = page.evaluate(SEEN)
            if s:
                met.append(s)
        return met

    def walk_to(self, page, until, presses=60):
        """Press Tab until it rests on a badge for which until(SEEN) holds; that reading (the test fails without one)."""
        for _ in range(presses):
            page.keyboard.press("Tab")
            s = page.evaluate(SEEN)
            if s and until(s):
                return s
        self.fail("no badge for the condition in %d presses" % presses)

    def from_start(self, page):
        """Put the walk's start at the document's start: the body takes the focus for a moment, so the next Tab goes to
        the first stop in the page (a blur alone leaves the browser's starting point on the control last focused)."""
        page.evaluate("document.body.tabIndex = -1; document.body.focus(); document.body.removeAttribute('tabindex')")

    def walks(self, page):
        """A walk forwards from the document's start and one backwards from the panel's first control with the pages
        scrolled to their end: the badges each rests on."""
        self.from_start(page)
        ahead = self.walk(page)
        page.evaluate("document.querySelector('#left').scrollTop = 1e6")
        settle(page)
        page.focus("#btn-side")
        return ahead, self.walk(page, "Shift+Tab")

    def assert_all_seen(self, met, least=1):
        """Every badge met seen, and at least least of them met."""
        self.assertEqual([m for m in met if not m["seen"]], [])
        self.assertGreaterEqual(len({m["id"] for m in met}), least, met)

    def tab_onto_the_line(self, page):
        """With the pages at their top, take the first badge of the left column standing below the status line and scroll
        the pages down until its centre is on the line's; put the focus on the badge before it without a scroll and press
        Tab: the badge Tab rests on, as SEEN reads it, else None."""
        page.evaluate("document.querySelector('#left').scrollTop = 0")
        settle(page)
        k = page.evaluate(
            """ids => {const d = document.querySelector('#status-dock').getBoundingClientRect(), dc = (d.top + d.bottom) / 2;
              const at = id => document.querySelector('.mark button.mark-jump[data-id="' + id + '"]').getBoundingClientRect();
              const k = ids.findIndex((id, i) => i % 3 === 0 && i > 0 && (at(id).top + at(id).bottom) / 2 > dc), b = at(ids[k]);
              document.querySelector('#left').scrollTop += (b.top + b.bottom) / 2 - dc; return k;}""",
            self.ids,
        )
        settle(page)
        page.evaluate(
            "id => document.querySelector('.mark button.mark-jump[data-id=\"' + id + '\"]').focus({preventScroll: true})",
            self.ids[k - 1],
        )
        page.keyboard.press("Tab")
        return page.evaluate(SEEN)

    def zoom_in(self, page, steps=3):
        """Press [+] steps times, as the bar's and [더보기]'s zoom-in does."""
        for _ in range(steps):
            page.evaluate("document.querySelector('[data-act=zoom-in]').click()")
            settle(page)

    def test_tab_rests_on_no_badge_the_status_line_or_a_bar_covers(self):
        """With the status line up - the first visit's line on the tablet's closed sheet - and zoomed in: on the tablet
        (673 x 841, 768 x 1024 zoomed in), the 1024 x 768 touch screen, the phone (390, 320 zoomed in), every badge Tab or
        Shift+Tab rests on is seen. Where the line stands over the pages (the sheets'), a badge scrolled to its middle is
        no stop: the Tab from the badge before it rests on one that is seen."""
        for name, device, zoom in (
            ("tablet 673", touch(673, 841), 0),
            ("tablet 768 zoomed", touch(768, 1024), 3),
            ("touch 1024 x 768", touch(1024, 768), 0),
            ("phone 390", PHONE_390, 0),
            ("phone 320 zoomed", touch(320, 720), 3),
        ):
            with self.subTest(device=name):
                page = self.open_device(device)
                self.zoom_in(page, zoom)
                self.assertTrue(page.evaluate("document.body.classList.contains('has-status')"))  # the line is up
                ahead, back = self.walks(page)
                self.assert_all_seen(ahead, least=10)
                self.assert_all_seen(back, least=10)
                if page.evaluate("document.querySelector('#status-dock').getClientRects().length > 0"):
                    s = self.tab_onto_the_line(page)
                    self.assertTrue(s is None or s["seen"], s)

    def test_tab_brings_a_badge_out_from_under_the_sheet_at_every_height(self):
        """The tablet's sheet open at 45% and 64%: the badges Tab brings in from out of view below stand above the sheet,
        seen, and their description stands over them, not over the sheet. Dragged by its grabber from 64% to the document
        bar, the sheet leaves no room to show a badge: none is a stop, and Tab passes from the bar into the panel."""
        for f in (0.45, 0.64):
            with self.subTest(sheet=f):
                page = self.open_device(touch(768, 1024))
                page.tap("#btn-side")
                page.evaluate("f => setSheetF(f)", f)
                settle(page)
                ahead, back = self.walks(page)
                self.assert_all_seen(ahead, least=10)
                self.assert_all_seen(back, least=10)
                page.evaluate("document.querySelector('#left').scrollTop = 0")
                settle(page)
                self.from_start(page)
                below = self.walk_to(
                    page, lambda m: m["id"] > self.ids[29]
                )  # page 2's first: out of view below the sheet
                page.wait_for_timeout(450)  # the description's 300 ms
                s = page.evaluate(SEEN)
                self.assertEqual(s["id"], below["id"])
                self.assertTrue(s["seen"] and s["tip"], s)
                tip, sheet = page.evaluate(
                    "[document.querySelector('#tip').getBoundingClientRect().bottom,"
                    " document.querySelector('#status-dock').getBoundingClientRect().top]"
                )
                self.assertLessEqual(tip, sheet)  # over the badge, not over the sheet or its status line
        page = self.open_device(touch(768, 1024))
        page.tap("#btn-side")
        page.evaluate("setSheetF(0.64)")
        settle(page)
        g = page.locator("#sheet-grip").bounding_box()
        x, y = g["x"] + g["width"] / 2, g["y"] + g["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        for i in range(1, 10):
            page.mouse.move(x, y - 20 * i)
        page.mouse.up()
        settle(page)
        self.assertEqual(page.evaluate("Math.round(document.querySelector('#right').getBoundingClientRect().top)"), 48)
        self.assertEqual(
            page.evaluate(
                "[...document.querySelectorAll('.mark button.mark-jump')].filter(b => b.tabIndex >= 0).length"
            ),
            0,
        )
        ahead, back = self.walks(page)
        self.assertEqual((ahead, back), ([], []))

    def test_the_phone_sheet_at_a_200_percent_zoom(self):
        """1024 x 768 at a 200% browser zoom is a 512 x 384 window with a mouse: the phone's sheet open leaves a strip above
        its status line. Tab from badge #3, at the top, rests only on badges seen in that strip."""
        page = self.open_device({"viewport": {"width": 512, "height": 384}})
        page.click("#btn-side")
        settle(page)
        page.focus('.mark button.mark-jump[data-id="%d"]' % self.ids[2])
        self.assert_all_seen(self.walk(page, presses=30), least=10)

    def test_a_focused_badge_a_cover_comes_over(self):
        """The tablet, the sheet open, the focus and its description on a badge Tab brought up from below it. The pages
        scrolled back until the badge is under the sheet: its description goes and does not come back, the focus stays on
        it, and the next Tab rests on a badge that is seen. With the sheet closed, Enter on a badge low on the screen opens
        the sheet over it: it is brought out above the sheet, still focused."""
        page = self.open_device(touch(768, 1024))
        page.tap("#btn-side")
        settle(page)
        self.from_start(page)
        s = self.walk_to(page, lambda m: m["id"] > self.ids[29])  # page 2's first, the pages scrolled down to it
        page.wait_for_timeout(450)
        self.assertTrue(page.evaluate(SEEN)["tip"])
        sheet = page.evaluate("document.querySelector('#right').getBoundingClientRect().top")
        page.evaluate("d => {document.querySelector('#left').scrollTop -= d}", sheet + 60 - s["y"])
        settle(page)
        page.wait_for_timeout(450)
        under = page.evaluate(SEEN)
        self.assertEqual((under["id"], under["seen"], under["tab"]), (s["id"], False, -1), under)
        self.assertFalse(page.evaluate(TIP_UP))
        page.keyboard.press("Tab")
        nxt = page.evaluate(SEEN)
        self.assertTrue(nxt is None or nxt["seen"], nxt)
        page = self.open_device(touch(768, 1024))
        self.from_start(page)
        low = self.walk_to(page, lambda m: m["y"] > 700)
        page.keyboard.press("Enter")
        settle(page)
        self.assertTrue(page.evaluate("SIDE_OPEN"))
        out = page.evaluate(SEEN)
        self.assertEqual((out["id"], out["seen"]), (low["id"], True), out)

    def test_a_script_focus_on_a_covered_badge_stays_where_it_is(self):
        """The tablet, the sheet open: a script puts the focus on a badge under the sheet without a scroll (as focusPlace
        does after a save): the pages do not move - only Tab's walk brings a badge out - and no description floats over
        the sheet for it."""
        page = self.open_device(touch(768, 1024))
        page.tap("#btn-side")
        settle(page)
        bid = page.evaluate(
            """() => {const p = document.querySelector('#right').getBoundingClientRect();
              const b = [...document.querySelectorAll('.mark button.mark-jump')].find(b => {const r = b.getBoundingClientRect();
                return r.top > p.top + 20 && r.bottom < innerHeight;});
              return Number(b.dataset.id);}"""
        )
        top = page.evaluate("document.querySelector('#left').scrollTop")
        page.keyboard.press("Shift")  # the keyboard is the input: a focus description would show
        page.evaluate(
            "id => document.querySelector(`.mark button.mark-jump[data-id='${id}']`).focus({preventScroll: true})", bid
        )
        page.wait_for_timeout(450)
        s = page.evaluate(SEEN)
        self.assertEqual((s["id"], s["seen"], s["tab"]), (bid, False, -1), s)
        self.assertEqual(page.evaluate("document.querySelector('#left').scrollTop"), top)
        self.assertFalse(page.evaluate(TIP_UP))

    def test_a_focused_badges_description_goes_when_the_sheet_leaves_it_no_room(self):
        """The tablet, the sheet open: the keyboard's focus and its description on a badge above the sheet. The sheet raised
        to the document bar covers it and leaves nowhere to bring it: its description goes, the focus stays on it."""
        page = self.open_device(touch(768, 1024))
        page.tap("#btn-side")
        settle(page)
        self.from_start(page)
        s = self.walk_to(page, lambda m: m["y"] > 200)
        page.wait_for_timeout(450)
        self.assertTrue(page.evaluate(SEEN)["tip"])
        page.evaluate("setSheetF(1)")
        settle(page)
        page.wait_for_timeout(450)
        under = page.evaluate(SEEN)
        self.assertEqual((under["id"], under["seen"], under["tab"]), (s["id"], False, -1), under)
        self.assertFalse(page.evaluate(TIP_UP))

    def test_a_badges_description_goes_when_the_panel_comes_over_it(self):
        """768 x 1024 with a mouse, the overlay panel closed: the description of a badge on the right of the page, under the
        mouse, shows; the panel opened over the pages (Ctrl+\\ or [핀 N]) covers the badge, and its description goes."""
        page = self.open_device({"viewport": {"width": 768, "height": 1024}})
        page.evaluate("setSide(false)")
        settle(page)
        bid = self.ids[5]  # page 1, the right column
        box = page.locator('.mark button.mark-jump[data-id="%d"]' % bid).bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.wait_for_timeout(450)
        self.assertTrue(page.evaluate(TIP_UP))
        page.evaluate("setSide(true)")
        settle(page)
        self.assertEqual(
            page.evaluate("id => document.querySelector(`.mark button.mark-jump[data-id='${id}']`).tabIndex", bid), -1
        )
        self.assertFalse(page.evaluate(TIP_UP))


class CoveredMarksFirefox(CoveredMarks):
    """The same Tab walks in Firefox."""

    BROWSER_ENGINE = "firefox"


class CoveredMarksSeenFirefox(CoveredMarksSeen):
    """The same walks in Firefox."""

    BROWSER_ENGINE = "firefox"

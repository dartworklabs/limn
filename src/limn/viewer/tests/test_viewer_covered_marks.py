"""Tab passes over only a mark badge no scroll can show, and shows the badge it rests on (docs/handbook/viewer.md §모바일
레이아웃, issue #418).

Tab put the focus ring on a badge under the tablet's sheet, where nobody could see it, and its tooltip floated over the sheet.
Passing over every badge a cover was over then lost badges the pages could show: with the sheet open, Tab from #3 went to #6,
past #4 and #5 under the sheet, and the scroll that brought #6 up showed the two it had passed. A badge is a stop while the
pages can scroll it - up or down, within their ends - to where it stands whole in the pages' box clear of every cover in its
columns, and Tab brings it there; one under the overlay panel, which runs the pages' height, or at the last page's foot under
the sheet is passed over. Read as the keyboard meets it, in Chromium and Firefox: Tab and Shift+Tab from #3 meet the badges in
turn, each seen, on the 200% phone sheet (512 x 384) and the tablet's sheet at 45% and 64%; the sheet open, closed and open
again; a scroll moves no stop; the badges under the overlay panel; the last page's foot; the desktop zoomed past the pages'
edge. The pass also stays cheap with hundreds of badges, since a scroll runs it every frame.

The covers are not the panel alone: the status line standing on the sheet (the first visit's line on the tablet's closed
sheet) and the closed sheet's bar hid badges Tab still rested on, and a badge Tab brought in from out of view was scrolled by
the browser to the pages' edge, under the sheet, where its focus and description stayed. Every badge a walk rests on is read
as seen - the topmost element at its centre, a press area drawn past its element's box aside (the status line's and the
bar's reach 44px over the pages) - forwards and backwards, with the status line up, zoomed in, the sheet at its three heights
and dragged to the top; and a focused badge a cover comes over loses its description and keeps the focus, or is brought out
again when the cover is the sheet a key opened.
"""

from helpers import add_pin
from helpers_access import ALICE, actor
from helpers_browser import BrowserBase, settle, touch_line

TABLET = {"viewport": {"width": 768, "height": 1024}, "is_mobile": True, "has_touch": True, "device_scale_factor": 2}
DESKTOP = {"viewport": {"width": 1440, "height": 900}}
# Each badge as [pin id, its centre's y, whether that centre is inside the panel's box, whether it is inside the pages' box].
BADGES = """() => {const v = document.querySelector('#left').getBoundingClientRect(), p = document.querySelector('#right').getBoundingClientRect();
  const inside = (r, x, y) => x >= r.left && x < r.right && y >= r.top && y < r.bottom;
  return [...document.querySelectorAll('.mark button.mark-jump')].map(b => {const r = b.getBoundingClientRect(),
    x = r.left + r.width / 2, y = r.top + r.height / 2; return [Number(b.dataset.id), Math.round(y), inside(p, x, y), inside(v, x, y)];});}"""
# The focused badge two frames on (after any scroll the focus set off), or null when the focus is not on one: its pin id, its
# centre's y, whether it is seen there - the topmost element at its centre whose own box holds that point is the badge (an
# element answering past its box is a press area drawn out from it, and is passed through) - what is there instead, its
# tabIndex, whether the description box stands over it, and whether its whole box is clear: inside the pages' box and the
# window and off the boxes of the panel (#right) and the status line (#status-dock).
SEEN = """async () => {await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  const a = document.activeElement; if (!a || !a.matches('.mark button.mark-jump')) return null;
  const r = a.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
  const own = e => {const q = e.getBoundingClientRect(); return x >= q.left && x < q.right && y >= q.top && y < q.bottom;};
  const h = x >= 0 && y >= 0 && x < innerWidth && y < innerHeight ? document.elementsFromPoint(x, y).find(own) || null : null;
  const v = document.querySelector('#left').getBoundingClientRect(), off = s => {const e = document.querySelector(s);
    if (!e || !e.getClientRects().length) return true; const c = e.getBoundingClientRect();
    return r.bottom <= c.top || r.top >= c.bottom || r.right <= c.left || r.left >= c.right;};
  const clear = r.top >= Math.max(v.top, 0) && r.bottom <= Math.min(v.bottom, innerHeight) && r.left >= Math.max(v.left, 0)
    && r.right <= Math.min(v.right, innerWidth) && off('#right') && off('#status-dock');
  return {id: Number(a.dataset.id), y: Math.round(y), seen: !!h && (h === a || a.contains(h)), at: h ? h.id || h.className : null,
    tab: a.tabIndex, tip: !document.querySelector('#tip').hidden && !!TIP_AT && TIP_AT.el === a, clear};}"""
# The pin ids of the badges in the document's order, the order Tab walks them in.
ORDER = "[...document.querySelectorAll('.mark button.mark-jump')].map(b => Number(b.dataset.id))"
# The pin ids of the badges whose centre lies inside the pages' box and inside the panel's (#right) or the status line's
# (#status-dock) box.
UNDER = """() => {const v = document.querySelector('#left').getBoundingClientRect();
  const cs = ['#right', '#status-dock'].map(s => document.querySelector(s)).filter(e => e && e.getClientRects().length)
    .map(e => e.getBoundingClientRect());
  const inside = (r, x, y) => x >= r.left && x < r.right && y >= r.top && y < r.bottom;
  return [...document.querySelectorAll('.mark button.mark-jump')].filter(b => {const r = b.getBoundingClientRect(),
    x = r.left + r.width / 2, y = r.top + r.height / 2; return inside(v, x, y) && cs.some(c => inside(c, x, y));})
    .map(b => Number(b.dataset.id));}"""
# Each badge's tabIndex, in the document's order.
STOPS = "[...document.querySelectorAll('.mark button.mark-jump')].map(b => b.tabIndex)"
# Whether each badge, in the document's order, can stand whole above every cover in its columns, below the pages' top, at a
# scroll the pages reach - the tablet's and the phone's covers (the sheet, its bar, the status line on it) rise from the
# window's foot, so a cover's top is all that bounds a badge from below. Read independently of list.js.
REACHABLE = """() => {const L = document.querySelector('#left'), v = L.getBoundingClientRect(), top = Math.max(v.top, 0),
    max = L.scrollHeight - L.clientHeight;
  const cs = ['#right', '#status-dock'].map(s => document.querySelector(s)).filter(e => e && e.getClientRects().length)
    .map(e => e.getBoundingClientRect());
  return [...document.querySelectorAll('.mark button.mark-jump')].map(b => {const r = b.getBoundingClientRect();
    const floor = Math.min(Math.min(v.bottom, innerHeight), ...cs.filter(c => c.left < r.right && c.right > r.left).map(c => c.top));
    const lo = Math.max(r.bottom + L.scrollTop - floor, 0), hi = Math.min(r.top + L.scrollTop - top, max);
    return lo <= hi + 0.5;});}"""
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
        first control - the pages' badges come after the bar and before the panel. Each is seen where it rests (SEEN)."""
        page.focus("#nav-toc-toggle")
        met, unseen = [], []
        for _ in range(presses):
            page.keyboard.press("Tab")
            s = page.evaluate(SEEN)
            if s is None:
                continue
            if not s["seen"]:
                unseen.append(s)
            if s["id"] not in met:
                met.append(s["id"])
        self.assertEqual(unseen, [])
        return met

    def test_tab_meets_every_badge_with_the_sheet_open_closed_and_open_again(self):
        """The tablet with five badges down page 1 and the sheet open over some of them: Tab meets all five in turn and
        brings each where it is seen - page 2 below lets the pages scroll every one above the sheet. So it does with the
        sheet closed by [핀 N], a badge under its bar included, and opened again."""
        ids = self.pins((0.05, 0.25, 0.45, 0.65, 0.85))
        page = self.open(len(ids), **TABLET)
        page.tap("#btn-side")
        settle(page)
        self.assertTrue(page.evaluate("SIDE_OPEN"))
        badges = page.evaluate(BADGES)
        self.assertTrue([b for b in badges if b[2] and b[3]], badges)  # the sheet covers some badges
        self.assertEqual(self.walk(page), ids)
        page.tap("#btn-side")
        settle(page)
        self.assertFalse(page.evaluate("SIDE_OPEN"))
        self.assertEqual(self.walk(page), ids)
        page.tap("#btn-side")
        settle(page)
        self.assertEqual(self.walk(page), ids)

    def test_a_scroll_moves_no_stop(self):
        """With the sheet open, the pages scrolled until the fourth badge stands 40 px above the sheet, the fifth still
        under it and the first above the pages' box, under the document bar: all five are stops, as before the scroll -
        what decides is where a scroll can bring a badge, not where it stands - and Tab meets the first first."""
        ids = self.pins((0.05, 0.25, 0.45, 0.65, 0.85))
        page = self.open(len(ids), **TABLET)
        page.tap("#btn-side")
        settle(page)
        self.assertEqual(page.evaluate(STOPS), [0] * 5)
        sheet = page.evaluate("document.querySelector('#right').getBoundingClientRect().top")
        page.evaluate("d=>{document.querySelector('#left').scrollTop+=d}", page.evaluate(BADGES)[3][1] - (sheet - 40))
        settle(page)
        badges = page.evaluate(BADGES)
        self.assertEqual([b[3] for b in badges[:4]], [False, True, True, True], badges)  # the first is out of the pages
        self.assertTrue(badges[4][2] and badges[4][3], badges)  # the fifth is under the sheet
        self.assertEqual(page.evaluate(STOPS), [0] * 5)
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
        Tab: that badge's pin id, and the badge Tab rests on, as SEEN reads it, else None."""
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
        return self.ids[k], page.evaluate(SEEN)

    def zoom_in(self, page, steps=3):
        """Press [+] steps times, as the bar's and [더보기]'s zoom-in does."""
        for _ in range(steps):
            page.evaluate("document.querySelector('[data-act=zoom-in]').click()")
            settle(page)

    def test_every_badge_tab_rests_on_is_seen_with_the_status_line_up(self):
        """With the status line up - the first visit's line on the tablet's closed sheet - and zoomed in: on the tablet
        (673 x 841, 768 x 1024 zoomed in), the 1024 x 768 touch screen, the phone (390, 320 zoomed in), every badge Tab or
        Shift+Tab rests on is seen. Where the line stands over the pages (the sheets'), a badge scrolled to its middle is
        a stop all the same: the Tab from the badge before it rests on it, brought out above the line."""
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
                    bid, s = self.tab_onto_the_line(page)
                    self.assertEqual((s["id"], s["seen"], s["clear"]), (bid, True, True), s)

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
        # The grabber pulled up past the document bar: the sheet stands at its tallest whether the release reads as a
        # fling (sheetRelease's next stop, its top on the bar at 48px) or as let go there (the height it was let go at,
        # rounded down: 49px, issue #456). Nine 20px moves (180px) reached the bar only as a fling, when the runner
        # delivered them fast enough; on a slow one the sheet stayed where they left it (top 190).
        page.mouse.move(x, y)
        page.mouse.down()
        for _, py in touch_line(x, y, x, 20, 10)[1:]:
            page.mouse.move(x, py)
        page.mouse.up()
        settle(page)
        top = page.evaluate("Math.round(document.querySelector('#right').getBoundingClientRect().top)")
        self.assertIn(top, (48, 49))
        self.assertEqual(
            page.evaluate(
                "[...document.querySelectorAll('.mark button.mark-jump')].filter(b => b.tabIndex >= 0).length"
            ),
            0,
        )
        ahead, back = self.walks(page)
        self.assertEqual((ahead, back), ([], []))

    def steps(self, page, key, n, presses=60):
        """Press key until it has rested on n badges (other stops between them pass); each, as SEEN reads it."""
        met = []
        for _ in range(presses):
            page.keyboard.press(key)
            s = page.evaluate(SEEN)
            if s:
                met.append(s)
                if len(met) == n:
                    break
        return met

    def test_tab_and_shift_tab_from_3_meet_the_badges_in_turn_with_the_sheet_open(self):
        """The sheet open over the pages' lower part, the pages at their top and the focus on badge #3: Tab, pressed again
        and again, meets the badges in the document's order with none passed over - those under the sheet included - and
        Shift+Tab meets them back to #3; each brought where it stands whole clear of the sheet and its status line, and
        seen. 1024 x 768 at a 200% browser zoom is a 512 x 384 window with a mouse and the phone's sheet, which leaves a
        strip above its status line; the tablet's sheet at 45% and 64%. Passing over the badges a cover was over, the phone
        sheet's walk went from #6 to #19."""
        for name, device, f in (
            ("512 x 384, 200%", {"viewport": {"width": 512, "height": 384}}, None),
            ("tablet, 45%", touch(768, 1024), 0.45),
            ("tablet, 64%", touch(768, 1024), 0.64),
        ):
            with self.subTest(device=name):
                page = self.open_device(device)
                if f is None:
                    page.click("#btn-side")
                else:
                    page.tap("#btn-side")
                    page.evaluate("f => setSheetF(f)", f)
                settle(page)
                self.assertTrue(page.evaluate("SIDE_OPEN"))
                page.evaluate("document.querySelector('#left').scrollTop = 0")
                settle(page)
                order = page.evaluate(ORDER)
                k = order.index(self.ids[2])
                under = page.evaluate(UNDER)
                self.assertTrue(set(under) & set(order[k + 1 : k + 25]), under)  # the walk meets badges under a cover
                page.focus('.mark button.mark-jump[data-id="%d"]' % self.ids[2])
                ahead = self.steps(page, "Tab", 24)
                self.assertEqual([m["id"] for m in ahead], order[k + 1 : k + 25])
                back = self.steps(page, "Shift+Tab", 24)
                self.assertEqual([m["id"] for m in back], order[k : k + 24][::-1])
                self.assertEqual([m for m in ahead + back if not (m["seen"] and m["clear"])], [])

    def test_a_badge_no_scroll_brings_above_the_sheet_is_passed_over(self):
        """The tablet's sheet at 64%: the pages end before the badges at the last page's foot can come above the sheet, and
        only those are no stops - every badge's stop is what a scroll within the pages' ends allows (REACHABLE). Shift+Tab
        from the panel, the pages at their end, rests first on the last badge a scroll brings out, seen."""
        page = self.open_device(touch(768, 1024))
        page.tap("#btn-side")
        page.evaluate("setSheetF(0.64)")
        settle(page)
        reach = page.evaluate(REACHABLE)
        self.assertTrue(any(reach) and not all(reach), reach)
        self.assertEqual([t >= 0 for t in page.evaluate(STOPS)], reach)
        order = page.evaluate(ORDER)
        last = max(i for i, r in enumerate(reach) if r)
        self.assertGreater(len(order) - 1, last)  # the last badges are passed over
        page.evaluate("document.querySelector('#left').scrollTop = 1e6")
        settle(page)
        page.focus("#btn-side")
        s = self.steps(page, "Shift+Tab", 1)[0]
        self.assertEqual((s["id"], s["seen"], s["clear"]), (order[last], True, True), s)

    def test_tab_passes_over_the_badges_under_the_overlay_panel(self):
        """A 860 x 900 window with a mouse, the overlay panel open over the pages' right side down their whole height: no
        scroll up or down brings out the badges in its columns, and Tab passes over them; it meets every other badge in
        the document's order, each seen."""
        page = self.open_device({"viewport": {"width": 860, "height": 900}})
        page.evaluate("setSide(true)")
        settle(page)
        self.assertTrue(page.evaluate("document.body.classList.contains('mid-overlay')"))
        under = set(
            page.evaluate(
                """() => {const p = document.querySelector('#right').getBoundingClientRect();
                  return [...document.querySelectorAll('.mark button.mark-jump')].filter(b => {const r = b.getBoundingClientRect();
                    return r.right > p.left && r.left < p.right;}).map(b => Number(b.dataset.id));}"""
            )
        )
        order = page.evaluate(ORDER)
        self.assertTrue(under and len(under) < len(order), under)
        self.from_start(page)
        met = self.walk(page, presses=80)
        self.assertEqual(list(dict.fromkeys(m["id"] for m in met)), [i for i in order if i not in under])
        self.assert_all_seen(met)

    def test_a_focused_badge_a_cover_comes_over(self):
        """The tablet, the sheet open, the focus and its description on a badge Tab brought up from below it. The pages
        scrolled back until the badge is under the sheet: its description goes and does not come back, the focus stays on
        it - still a stop, since a scroll can show it - and the next Tab rests on the next badge, brought out and seen. With
        the sheet closed, Enter on a badge low on the screen opens the sheet over it: it is brought out above the sheet,
        still focused."""
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
        self.assertEqual((under["id"], under["seen"], under["tab"]), (s["id"], False, 0), under)
        self.assertFalse(page.evaluate(TIP_UP))
        order = page.evaluate(ORDER)
        page.keyboard.press("Tab")
        nxt = page.evaluate(SEEN)
        self.assertEqual((nxt["id"], nxt["seen"]), (order[order.index(s["id"]) + 1], True), nxt)
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
        the sheet for it, though the badge is a stop."""
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
        self.assertEqual((s["id"], s["seen"], s["tab"]), (bid, False, 0), s)
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

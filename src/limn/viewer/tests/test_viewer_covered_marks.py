"""A mark badge the panel or the sheet covers is no Tab stop (docs/handbook/viewer.md §모바일 레이아웃, issue #418).

Tab put the focus ring on a badge under the tablet's sheet, where nobody could see it, and its tooltip floated over the sheet.
Read as the keyboard meets it - which badges a Tab walk through the page stops on - in Chromium and Firefox: a badge under the
open sheet is passed over, one above it is not; closing the sheet gives the passed-over badges back (but for the one under its
bar) and opening it takes them away again; a badge scrolled out of the pages' box stays a stop - one scrolled above the pages
on the tablet, one zoomed past the pages' right edge on the desktop, where the panel stands beside it. The pass also stays
cheap with hundreds of badges, since a scroll runs it every frame.
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


class CoveredMarksFirefox(CoveredMarks):
    """The same Tab walks in Firefox."""

    BROWSER_ENGINE = "firefox"

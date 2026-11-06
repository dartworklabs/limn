"""A page list row's focus ring is whole (docs/handbook/viewer.md §쪽 목록, issue #418).

The page list (.pl-list: the page count's popover, #page-pop-list, and the phone's navigation sheet, #ns-pages) scrolls, so it
clips whatever passes its sides, and its rows (.pl-row) fill its width. The ring every control draws (2px, 1px out) stood 3px
outside the row, so the list cut its sides on every row and the top of the first row and the bottom of the last. Read by the
keyboard on twenty pages - the desktop's popover, a touch tablet's and the phone's sheet - on the first row, the last and one
between: the focused row draws the 2px --ring outline, and the box that outline covers (the row's grown by the outline's width
and offset) and the row itself lie inside every ancestor that clips (its padding box, without a scroll bar).

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_list_focus_ring.py
"""

from helpers import blank_png, ps
from helpers_browser import BrowserBase, settle

PAGES = 20

# The focused element's ring against what clips it: its class, the outline's style, width and colour beside --ring's, the
# ring's box (the border box grown by the outline's width and offset), the row's box, and the box every ancestor that clips
# (overflow other than visible) leaves - each one's padding box, without its scroll bar - with how far the ring and the row
# pass each side of it (0 when inside).
RING = """() => {const e = document.activeElement, cs = getComputedStyle(e), r = e.getBoundingClientRect();
  const probe = document.createElement('i'); probe.style.color = 'var(--ring)'; document.body.append(probe);
  const ring = getComputedStyle(probe).color; probe.remove();
  const g = cs.outlineStyle === 'none' ? 0 : parseFloat(cs.outlineWidth) + parseFloat(cs.outlineOffset);
  const box = {l: r.left - g, t: r.top - g, r: r.right + g, b: r.bottom + g}, row = {l: r.left, t: r.top, r: r.right, b: r.bottom};
  let clip = {l: -1e9, t: -1e9, r: 1e9, b: 1e9};
  for (let p = e.parentElement; p; p = p.parentElement) {const s = getComputedStyle(p);
    if (s.overflowX === 'visible' && s.overflowY === 'visible') continue;
    const q = p.getBoundingClientRect(), l = q.left + p.clientLeft, t = q.top + p.clientTop;
    clip = {l: Math.max(clip.l, l), t: Math.max(clip.t, t), r: Math.min(clip.r, l + p.clientWidth), b: Math.min(clip.b, t + p.clientHeight)};}
  const past = b => [clip.l - b.l, clip.t - b.t, b.r - clip.r, b.b - clip.b].map(v => Math.max(0, Math.round(v * 100) / 100));
  return {cls: e.className, page: e.dataset.page, style: cs.outlineStyle, width: cs.outlineWidth, colour: cs.outlineColor, ring,
    ringPast: past(box), rowPast: past(row)};}"""


class ListFocusRing(BrowserBase):
    """In Chromium: twenty pages."""

    def setUp(self):
        """Pages 3 to 20 beside BrowserBase's two, so each list scrolls."""
        super().setUp()
        pages = ps.APP.C.state / (ps.APP.C.state / "pages.cur").read_text()
        for i in range(3, PAGES + 1):
            (pages / ("page-%d.png" % i)).write_bytes(blank_png(1275, 1650))

    def device(self, viewport, touch):
        """The context options for a viewport, by touch or by a mouse (bundled Firefox has no mobile emulation)."""
        d = {"viewport": viewport}
        if touch:
            d["has_touch"] = True
            if self.BROWSER_ENGINE == "chromium":
                d["is_mobile"] = True
        return d

    def view(self, viewport, touch=False):
        """The viewer with its twenty pages drawn."""
        page = self.open(0, **self.device(viewport, touch))
        page.wait_for_function("n => document.querySelectorAll('#doc .pg').length === n", arg=PAGES)
        settle(page)
        return page

    def assert_rings_whole(self, page, where):
        """On the focused row, then after End, ↑ and Home: a row of the list has the focus, draws the 2px --ring outline,
        and neither the ring nor the row passes what clips them."""
        seen = []
        for key in (None, "End", "ArrowUp", "Home"):
            if key:
                page.keyboard.press(key)
            got = page.evaluate(RING)
            self.assertIn("pl-row", got["cls"], (where, key, got))
            self.assertEqual(
                (got["style"], got["width"], got["colour"]), ("solid", "2px", got["ring"]), (where, key, got)
            )
            self.assertEqual(got["rowPast"], [0, 0, 0, 0], (where, key, got))
            self.assertEqual(got["ringPast"], [0, 0, 0, 0], (where, key, got))
            seen.append(got["page"])
        self.assertEqual(seen, ["1", str(PAGES), str(PAGES - 1), "1"], where)

    def test_the_popovers_rows_keep_their_rings_on_a_desktop_and_a_tablet(self):
        """The desktop's page count (mouse): Enter opens the list with the field focused and ↓ goes to the current row. The
        landscape tablet's nav bar page count (touch): Enter opens it on the current row."""
        for viewport, touch, opener in (
            ({"width": 1440, "height": 900}, False, "#section-page"),
            ({"width": 1024, "height": 768}, True, "#nav-page"),
        ):
            with self.subTest(opener=opener):
                page = self.view(viewport, touch)
                page.focus(opener)
                page.keyboard.press("Enter")
                page.wait_for_function("!document.querySelector('#page-pop').hidden")
                if not touch:
                    page.keyboard.press("ArrowDown")
                self.assertTrue(
                    page.evaluate("document.querySelector('#page-pop-list').scrollHeight > innerHeight / 2")
                )
                self.assert_rings_whole(page, opener)

    def test_the_phone_sheets_rows_keep_their_rings(self):
        """The phone's [본문 1/20 ▾] opens the navigation sheet by Enter; the current page's row, its list's one Tab stop,
        takes the focus."""
        page = self.view({"width": 390, "height": 844}, touch=True)
        page.focus("#btn-pos")
        page.keyboard.press("Enter")
        page.wait_for_function("document.querySelector('#nav-sheet').open")
        settle(page)
        page.focus("#ns-pages [aria-selected=true]")
        self.assertGreater(
            page.evaluate("(l => l.scrollHeight - l.clientHeight)(document.querySelector('#ns-pages'))"), 0
        )
        self.assert_rings_whole(page, "#ns-pages")


class ListFocusRingFirefox(ListFocusRing):
    """The same lists in bundled Firefox."""

    BROWSER_ENGINE = "firefox"

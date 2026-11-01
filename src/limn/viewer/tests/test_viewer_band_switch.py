"""A band switch keeps the reading page where it stands (docs/handbook/viewer.md §모바일 레이아웃; issue #356).

Widening a foldable to a desktop, or narrowing it back, changes the top bars, the page lines (under every page, or beside the
pages with a one-row summary under each) and so the space between the pages. The page read stays at the same place under the
PDF area's top, also while the top edge or the reading line stands in that space: a spot's fraction of a page is 0 there, and
the re-fit lost how far above the page it was and put the page's top on the line - up to 200 px off.

The space above the reading page does change, so a page above the reading line moves by that much (12 px between a foldable's
line and a touch desktop's summary): the page read is the one held, as when the lines move on a wide screen (§판정 패널).

The fixture is a figure document of N_PAGES portrait pages whose word file gives every page a line. Pages NARROW wide fit
every window here, so the scale stays and whole pages can be compared; WIDE ones are fitted to narrower windows, so the scale
changes and only the spot at the top edge can stay. Chromium only: the re-fit does not depend on the engine.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_band_switch.py
"""

import json
from unittest import mock

from limn.pins.location import source as pick_source

import helpers_figure
from helpers import blank_png, ps
from helpers_browser import BrowserBase, settle

N_PAGES = 16
PAGE = 9  # a page with pages above it, whose blocks change height, and below it
WORDS = {"format": "limn-verdicts/1", "verdicts": [{"key": "채택"}, {"key": "보류"}], "page": True}
NARROW = (1000, 1300)  # page image px at 150 dpi: 640 CSS px wide at 100%
WIDE = (1275, 1650)  # 816 CSS px wide at 100%
TOUCH = {"is_mobile": True, "has_touch": True}
FOLD = {"width": 841, "height": 673}
FOLD_TALL = {"width": 673, "height": 841}
TABLET = {"width": 768, "height": 1024}
DESK_TOUCH = {"width": 1920, "height": 1024}
DESK_LOW = {"width": 1920, "height": 673}
MOUSE_MID = {"width": 800, "height": 850}
MOUSE_WIDE = {"width": 1920, "height": 850}
# Where the page read stands against the PDF area's top, by what the top edge and the reading line (at depth) fall on.
SPOTS = {
    "both on the page": lambda depth: -200,
    "the top edge in the space above it": lambda depth: 10,
    "the reading line in the space above it": lambda depth: depth + 10,
    "the top edge on the page above it": lambda depth: depth - 10,
}
DEPTH = "()=>readingDepth(document.querySelector('#left'))"
# Puts page n's top y px under the PDF area's top.
PLACE = """([n, y]) => {const L = document.querySelector('#left'), r = document.getElementById('p' + n).getBoundingClientRect();
  L.scrollTop += r.top - L.getBoundingClientRect().top - y;}"""
# Page n's top under the PDF area's top, the page read, and the band.
STANDS = """n => {const L = document.querySelector('#left'), r = document.getElementById('p' + n).getBoundingClientRect();
  return {y: r.top - L.getBoundingClientRect().top, read: pvReadingAt(), band: BAND, beside: PV_SIDE};}"""
# The point of the page at the top edge: its page and how far down it, in px at the page's height now.
TOP_SPOT = "()=>{const a=topAnchor(); return {page: a.page, at: a.frac * a.h};}"
HEIGHT = "n=>document.getElementById('p'+n).getBoundingClientRect().height"
# Resolves once the PDF area has not scrolled for 30 frames in a row.
RESTED = """() => new Promise(done => {const L = document.querySelector('#left'); let last = -1, same = 0;
  const look = () => {same = L.scrollTop === last ? same + 1 : 0; last = L.scrollTop; if (same >= 30) done(); else requestAnimationFrame(look);};
  look();})"""


class BandBase(BrowserBase):
    """helpers_figure.viewer_docs with the figure rebuilt as N_PAGES pages of one image size, each taking a page verdict."""

    IMAGE = NARROW

    def setUp(self):
        super().setUp()
        self.ms, self.fig, self.rv = helpers_figure.viewer_docs(ps.APP, ps.APP.C.src)
        words = self.fig.main.parent / "figures.limnverdicts.json"
        words.write_text(json.dumps(WORDS, ensure_ascii=False), encoding="utf-8")
        pages = [
            {
                "page": i,
                "figure": "F%03d" % i,
                "title": "PL%d" % i,
                "elements": [{"id": "F%03d" % i, "frac": [0, 0, 1, 1]}],
            }
            for i in range(1, N_PAGES + 1)
        ]
        fmap = {"format": "limn-figure-map/1", "pdf": "figures.pdf", "pdf_sha256": "0" * 64, "pages": pages}
        d = helpers_figure.write_build(self.fig, helpers_figure.BUILD2, fmap, pages=N_PAGES)
        for i in range(1, N_PAGES + 1):
            (d / ("page-%d.png" % i)).write_bytes(blank_png(*self.IMAGE))
        patch = mock.patch.object(pick_source, "region_text", return_value="")  # pdftotext answers no text
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(ps.APP.set_docs, None)

    def on(self, size, **device):
        """The figure document open in a window of size, its pages laid out."""
        page = self.open(0, viewport=size, **device)
        page.evaluate("k=>switchDoc(k)", "fig")
        page.wait_for_function("n=>DOC==='fig'&&META&&META.doc==='fig'&&document.getElementById('p'+n)", arg=N_PAGES)
        settle(page)
        return page

    def resize(self, page, size, band):
        """The window at size and the band settled on band (a touch window waits for it), all moves over."""
        page.set_viewport_size(size)
        page.wait_for_function("b=>innerWidth===%d&&BAND===b" % size["width"], arg=band)
        settle(page)
        page.evaluate(RESTED)
        settle(page)

    def place(self, page, y):
        """Page PAGE's top y px under the PDF area's top, at rest."""
        page.evaluate(PLACE, [PAGE, y])
        page.evaluate(RESTED)
        settle(page)


class ReadingPageHolds(BandBase):
    """The scale stays: at every spot, both ways, the page read is the same one at the same place."""

    def check(self, a, band_a, b, band_b, device):
        page = self.on(a, **device)
        self.assertEqual(page.evaluate("BAND"), band_a)
        for name, y in SPOTS.items():
            for to, band in ((b, band_b), (a, band_a)):
                with self.subTest(spot=name, to=band):
                    self.place(page, y(page.evaluate(DEPTH)))
                    was = page.evaluate(STANDS, PAGE)
                    self.assertEqual(was["read"], PAGE, was)
                    self.resize(page, to, band)
                    got = page.evaluate(STANDS, PAGE)
                    self.assertEqual(got["read"], PAGE, (was, got))
                    self.assertLessEqual(abs(got["y"] - was["y"]), 1, (was, got))

    def test_a_foldable_and_a_touch_desktop(self):
        """841 x 673 and 1920 x 673 by touch, the band and the lines changing: the issue's switch."""
        self.check(FOLD, "mid-overlay", DESK_LOW, "wide", TOUCH)

    def test_a_tablet_and_a_touch_desktop(self):
        """768 x 1024 and 1920 x 1024 by touch: the sheet, its one nav bar, against the desktop with the panel on."""
        self.check(TABLET, "tablet-sheet", DESK_TOUCH, "wide", TOUCH)

    def test_a_mouse_window(self):
        """800 and 1920 wide by mouse, where the band follows at once."""
        self.check(MOUSE_MID, "mid-overlay", MOUSE_WIDE, "wide", {})


class TopSpotHolds(BandBase):
    """The scale changes with the band: the point at the top edge stays there, or the space that stood above a page."""

    IMAGE = WIDE

    def on_the_page(self, page, to, band):
        """The point at the top edge, inside page PAGE, is there after the switch, at the page's new height."""
        self.place(page, -200)
        was, high = page.evaluate(TOP_SPOT), page.evaluate(HEIGHT, PAGE)
        self.resize(page, to, band)
        got, now = page.evaluate(TOP_SPOT), page.evaluate(HEIGHT, PAGE)
        self.assertEqual(got["page"], was["page"])
        self.assertLessEqual(abs(got["at"] - was["at"] * now / high), 1, (was, got))

    def above_the_page(self, page, to, band):
        """The top edge 10 px above page PAGE stays 10 px above it."""
        self.place(page, 10)
        was = page.evaluate(STANDS, PAGE)
        self.resize(page, to, band)
        got = page.evaluate(STANDS, PAGE)
        self.assertLessEqual(abs(got["y"] - was["y"]), 1, (was, got))

    def check(self, a, band_a, b, band_b):
        page = self.on(a, **TOUCH)
        for spot in (self.on_the_page, self.above_the_page):
            for to, band in ((b, band_b), (a, band_a)):
                with self.subTest(spot=spot.__name__, to=band):
                    spot(page, to, band)

    def test_a_tablet_and_a_touch_desktop(self):
        """768 x 1024, the pages fitted to the sheet's width, and 1920 x 1024."""
        self.check(TABLET, "tablet-sheet", DESK_TOUCH, "wide")

    def test_a_turned_foldable(self):
        """841 x 673 and 673 x 841, as turning it does: the overlay panel's band and the sheet."""
        self.check(FOLD, "mid-overlay", FOLD_TALL, "tablet-sheet")


class LinesFollowTheWindow(BandBase):
    """The lines wait for a band settling, and still move when it has settled without changing."""

    def test_a_touch_window_narrowed_within_the_wide_band_moves_the_lines_once_it_settles(self):
        """A touch desktop narrowed from 1920 to 1400: the same band, too little room beside the pages. A new width waits
        BAND_SETTLE_MS, the lines with it: they go under the pages when it has settled, with the page read where it stood."""
        page = self.on(DESK_TOUCH, **TOUCH)
        self.assertTrue(page.evaluate(STANDS, PAGE)["beside"])
        self.place(page, page.evaluate(DEPTH) - 10)
        was = page.evaluate(STANDS, PAGE)
        self.resize(page, {"width": 1400, "height": 1024}, "wide")
        got = page.evaluate(STANDS, PAGE)
        self.assertFalse(got["beside"])
        self.assertEqual(got["read"], PAGE)
        self.assertLessEqual(abs(got["y"] - was["y"]), 1, (was, got))

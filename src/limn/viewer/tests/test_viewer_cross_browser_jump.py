"""A far jump through a long document in bundled Firefox and WebKit (docs/handbook/viewer.md §판정 핀; issue #343).

A jump to a page (goPage: the page field, the phone's position sheet, the outline, a card's [보기]) glides there smoothly. On
the way the page lines are drawn again as each page passes under the reading line, and WebKit ended the smooth scroll at the
scroll anchoring adjustment that came with it: on a phone a jump from page 1 to page 105 rested at page 4 of this generated
document (page 89 of a real 105-page figure document). Chromium and Firefox arrive either way. The fixture is a figure document
of N_PAGES portrait one-figure pages (612 x 792 pt, blank page images) whose word file gives every page a line, at 390 x 844
by touch and at CI's 1400 x 850. Desktop WebKit does not stand for a physical iPhone.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_cross_browser_jump.py
"""

import json
from unittest import mock
from urllib.parse import urlparse

from limn.pins.location import source as pick_source

import helpers_figure
from helpers import blank_png, ps
from helpers_browser import BrowserBase, settle

N_PAGES = 105
WORDS = {"format": "limn-verdicts/1", "verdicts": [{"key": "채택"}, {"key": "보류"}]}
PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
DESKTOP = {"viewport": {"width": 1400, "height": 850}}
# Resolves once the PDF area has not scrolled for 30 frames in a row: a glide is over, wherever it stopped.
RESTED = """() => new Promise(done => {const L = document.querySelector('#left'); let last = -1, same = 0;
  const look = () => {same = L.scrollTop === last ? same + 1 : 0; last = L.scrollTop; if (same >= 30) done(); else requestAnimationFrame(look);};
  look();})"""
# Where page n stands against the PDF area's top, the page read, and whether a jump is still said to be on its way.
AT = """n => {const L = document.querySelector('#left'), r = document.getElementById('p' + n).getBoundingClientRect();
  return {off: Math.round(r.top - L.getBoundingClientRect().top - L.clientTop), read: pvReadingAt(), jump: PV_JUMP !== null,
    anchoring: getComputedStyle(L).overflowAnchor};}"""


class JumpBase(BrowserBase):
    """helpers_figure.viewer_docs with the figure rebuilt as N_PAGES portrait pages, each taking a page verdict; picks on the
    figure reach the real handler."""

    def setUp(self):
        super().setUp()
        self.ms, self.fig, self.rv = helpers_figure.viewer_docs(ps.APP, ps.APP.C.src)
        words = self.fig.main.parent / "figures.limnverdicts.json"
        words.write_text(json.dumps({**WORDS, "page": True}, ensure_ascii=False), encoding="utf-8")
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
            (d / ("page-%d.png" % i)).write_bytes(blank_png(1275, 1650))
        patch = mock.patch.object(pick_source, "region_text", return_value="")  # pdftotext answers no text
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(ps.APP.set_docs, None)

    def route(self, route):
        rq = route.request
        if urlparse(rq.url).path == "/api/pick" and json.loads(rq.post_data or "{}").get("doc") == "fig":
            return self.forward(route)
        return super().route(route)

    def on(self, device):
        page = self.open(0, **device)
        page.evaluate("k=>switchDoc(k)", "fig")
        page.wait_for_function("n=>DOC==='fig'&&META&&META.doc==='fig'&&document.getElementById('p'+n)", arg=N_PAGES)
        settle(page)
        return page

    def jump(self, page, n):
        """goPage(n) and a digit in the same task, while the glide has just begun; then the rest. What stood at the end."""
        page.evaluate(
            """n => {searchToPage(); goPage(n); document.body.dispatchEvent(new KeyboardEvent('keydown', {key: '1', bubbles: true}));}""",
            n,
        )
        page.evaluate(RESTED)
        settle(page)
        return page.evaluate(AT, n)


class JumpFlows:
    """A far jump lands on its page, with the digits refused on the way, on a phone and on a desktop."""

    def check(self, device):
        page = self.on(device)
        for n in (N_PAGES, 60, 1):
            with self.subTest(page=n):
                got = self.jump(page, n)
                self.assertLessEqual(abs(got["off"]), 2, got)
                self.assertEqual((got["read"], got["jump"], got["anchoring"]), (n, False, "auto"), got)
                self.assertEqual(page.evaluate("OPEN_ALL.length"), 0, "a digit during the glide saved a verdict")
        page.keyboard.press("1")
        page.wait_for_function("OPEN_ALL.length===1&&!PV_BUSY.size", timeout=10000)
        self.assertEqual(page.evaluate("OPEN_ALL[0].page"), 1)

    def test_a_far_jump_on_a_phone_lands_on_its_page(self):
        """390 x 844: pages 105, 60 and 1 in turn, each from the last."""
        self.check(PHONE)

    def test_a_far_jump_on_a_desktop_lands_on_its_page(self):
        """1400 x 850, the same jumps."""
        self.check(DESKTOP)


class WebKitJump(JumpFlows, JumpBase):
    """Far jumps in desktop WebKit (touch emulation on the phone), without claiming a physical iPhone."""

    BROWSER_ENGINE = "webkit"


class FirefoxJump(JumpFlows, JumpBase):
    """The same jumps in Playwright's bundled desktop Firefox."""

    BROWSER_ENGINE = "firefox"

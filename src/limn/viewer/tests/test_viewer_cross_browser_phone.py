"""The page verdict line on a phone in bundled Firefox and WebKit (docs/handbook/viewer.md §판정 핀).

pvFit measures every line as the reading line (#doc.pv-measure), which grows a line above the reading page for the length of
the pass. WebKit's scroll anchoring followed that growth on the next page's block and not the shrink after it, so a key save
on a phone moved the pages 39px; Chromium's nets out (test_viewer_verdicts.py's EdgeKeys pins the same flow there). The
fixture is VerdictBase's: helpers_figure.viewer_docs with word files on all three documents, page lines on the figure (two
landscape pages), at 390 x 844 by touch. Desktop WebKit does not stand for a physical iPhone.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_cross_browser_phone.py
"""

import json
from unittest import mock
from urllib.parse import urlparse

from limn.pins.location import source as pick_source

import helpers_figure
from helpers import ps
from helpers_browser import BrowserBase, settle

WORDS = {"format": "limn-verdicts/1", "verdicts": [{"key": "채택"}, {"key": "보류"}, {"key": "삭제", "confirm": True}]}
PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
TOP = "()=>document.querySelector('#left').scrollTop"
# Focuses page n's first Tab stop without scrolling to it; whether it took the focus.
FIRST_STOP = """n=>{const b=[...document.querySelector('#doc .pgw[data-page="'+n+'"]').querySelectorAll(PV_TABBABLE)].find(pvTabStop);
  b.focus({preventScroll:true}); return document.activeElement===b;}"""


class PhoneBase(BrowserBase):
    """VerdictBase's documents (test_viewer_verdicts.py): word files on all three, page lines on the figure and the PDF;
    picks on the figure and the PDF reach the real handler."""

    def setUp(self):
        super().setUp()
        self.ms, self.fig, self.rv = helpers_figure.viewer_docs(ps.APP, ps.APP.C.src)
        src = ps.APP.C.src
        for key, path in (
            ("ms", src / "main.limnverdicts.json"),
            ("fig", self.fig.main.parent / "figures.limnverdicts.json"),
            ("rv", src / "reviewer.limnverdicts.json"),
        ):
            path.write_text(json.dumps({**WORDS, "page": key != "ms"}, ensure_ascii=False), encoding="utf-8")
        patch = mock.patch.object(pick_source, "region_text", return_value="")  # pdftotext answers no text
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(ps.APP.set_docs, None)

    def route(self, route):
        rq = route.request
        if urlparse(rq.url).path == "/api/pick" and json.loads(rq.post_data or "{}").get("doc") in ("fig", "rv"):
            return self.forward(route)
        return super().route(route)


class PhoneLineFlows:
    """The phone's line flows whose engine part differs."""

    def test_a_key_save_and_shift_tab_leave_the_pages_where_they_are(self):
        """390 x 844, page 2 zoomed and read, its top at the area's top: Shift+Tab from its first stop goes to the position
        button, 1 pressed on the tool bar's [더보기] saves 채택 there, and Shift+Tab from the line goes back to [더보기]. The
        pages stay within 1px throughout - the save's measuring pass grew page 1's line, which WebKit anchored on."""
        page = self.open(0, **PHONE)
        page.evaluate("k=>switchDoc(k)", "fig")
        page.wait_for_function("k=>DOC===k&&META&&META.doc===k&&document.querySelector('#p2')", arg="fig")
        page.evaluate("setSide(false)")
        page.evaluate("()=>{setK(K*2.5,false); ZOOMED=true;}")
        settle(page)
        page.evaluate(
            "()=>{const L=document.querySelector('#left'); L.scrollTop+=document.getElementById('p2').getBoundingClientRect().top-L.getBoundingClientRect().top;}"
        )
        settle(page)
        self.assertEqual(page.evaluate("[PV_READ, pvEdgeStop(false)]"), [2, None])
        top = page.evaluate(TOP)
        self.assertTrue(page.evaluate(FIRST_STOP, 2))
        page.keyboard.press("Shift+Tab")
        self.assertEqual(page.evaluate("document.activeElement.id"), "btn-pos")
        self.assertAlmostEqual(page.evaluate(TOP), top, delta=1)
        page.focus("#btn-more")
        page.keyboard.press("1")
        page.wait_for_function("OPEN_ALL.length===1&&!PV_BUSY.size", timeout=10000)
        settle(page)
        self.assertAlmostEqual(page.evaluate(TOP), top, delta=1, msg="the key save moved the pages")
        page.evaluate("()=>NOTICES.forEach(n=>{if(n.place==='chip')endNotice(n,false);})")
        settle(page)
        self.assertTrue(page.evaluate(FIRST_STOP, 2))
        page.keyboard.press("Shift+Tab")
        self.assertEqual(page.evaluate("document.activeElement.id"), "btn-more")
        self.assertAlmostEqual(page.evaluate(TOP), top, delta=1)
        self.assertEqual(page.evaluate("PV_READ"), 2)


class WebKitPhoneLine(PhoneLineFlows, PhoneBase):
    """The phone's line in desktop WebKit with touch emulation, without claiming a physical iPhone."""

    BROWSER_ENGINE = "webkit"


class FirefoxPhoneLine(PhoneLineFlows, PhoneBase):
    """The same flow in Playwright's bundled desktop Firefox (no mobile emulation: the 390px band and touch only)."""

    BROWSER_ENGINE = "firefox"

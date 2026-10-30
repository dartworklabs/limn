"""Page verdict lines while the PDF area scrolls (docs/handbook/viewer.md §판정 핀, issue #322).

Each page PDF.js draws for the first time adds its embedded fonts to document.fonts, and every font added makes the
browser lay out all the text in the page again. With the far pin cards already skipped (#305) that was every page verdict
line: the 88 lines of a 91-page figure document were about 4,300 of the 7,400 objects laid out at each font, and the
first wheel scroll through it still had 8-9 long tasks. The lines more than a view's height from the PDF area's view are
now left for the browser to skip (content-visibility:auto) at the height each is drawn at (verdict.js pvFarSort).

The cost is held by a count, not a duration, as test_viewer_list_scroll holds the cards' (helpers_trace): the layout
objects the browser lays out after a font is added, read from a Chrome trace, against the same with every line drawn and
the nodes the lines hold. What skipping must not change is held too, for the line's rules are strict: no line in or near
the view is skipped, nor the reading line, which floats, nor one holding the focus; every line stands at the height it is
drawn at, so no page moves as lines are skipped and drawn again, at any place in the document; and a line that changes
far from the view - its page's verdict saved elsewhere, its width - is measured drawn and stands at its new height, and
shows what it holds when it comes in.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_verdict_scroll.py
"""

import json
from unittest import mock

from limn.pins.location import source as pick_source

import helpers_figure
from helpers import blank_png, ps, split_resp
from helpers_access import ALICE, talk_to
from helpers_browser import BrowserBase, settle
from helpers_trace import SCROLL_ADDING_FONTS, laid_out, traced

N_PAGES = 60  # each a figure with its line; the issue's document had 88
WORDS = {
    "format": "limn-verdicts/1",
    "page": True,
    "verdicts": [{"key": "채택"}, {"key": "보류"}, {"key": "삭제", "confirm": True}],
}
PAGE_PNG = blank_png(1500, 1000)  # a 3:2 figure page at 150 dpi
# The page verdict lines the browser skips now: their content is not drawn.
SKIPPED = """() => [...document.querySelectorAll('#doc .pv')]
  .filter(l => !l.querySelector(':scope>.pv-t').checkVisibility({contentVisibilityAuto: true})).length"""
# The DOM nodes (elements and text) the lines hold: the layout objects a layout of every line walks, near enough.
LINE_NODES = """() => {let n = 0; for (const l of document.querySelectorAll('#doc .pv')) {
  const w = document.createTreeWalker(l); n++; while (w.nextNode()) n++;} return n;}"""
# The pages of the lines the browser may skip (content-visibility not visible) that are in the PDF area's view or are the
# reading line, which floats: none should be. Skipping contains a line, which draws its parts on whole pixels and clips
# what reaches past its box.
HELD_IN_VIEW = """() => {const r = document.querySelector('#left').getBoundingClientRect();
  return [...document.querySelectorAll('#doc .pv')].filter(l => {const b = l.getBoundingClientRect();
    return (l.classList.contains('reading') || b.bottom > r.top && b.top < r.bottom) && getComputedStyle(l).contentVisibility !== 'visible';})
    .map(l => +l.dataset.page);}"""
# The lines whose height as they stand now is not the one they are drawn at (read with the skipping taken off every line,
# then put back): [page, standing, drawn].
HEIGHTS = """() => {const ls = [...document.querySelectorAll('#doc .pv')], at = ls.map(l => l.getBoundingClientRect().height);
  ls.forEach(l => { l.style.contentVisibility = 'visible'; }); const drawn = ls.map(l => l.getBoundingClientRect().height);
  ls.forEach(l => { l.style.contentVisibility = ''; });
  return ls.map((l, i) => [+l.dataset.page, at[i], drawn[i]]).filter(r => Math.abs(r[1] - r[2]) > 0.01);}"""
# Where every page's block stands in the document (px from the document's top).
PAGE_TOPS = """() => {const d = document.querySelector('#doc').getBoundingClientRect().top;
  return [...document.querySelectorAll('#doc .pgw')].map(w => w.getBoundingClientRect().top - d);}"""
# Scrolls the PDF area to fraction f of its range.
SCROLL_TO = "f => {const L = document.querySelector('#left'); L.scrollTop = (L.scrollHeight - L.clientHeight) * f;}"
# Whether page n's line is drawn (not skipped).
DRAWN = "n => document.querySelector('#doc .pv[data-page=\"' + n + '\"]>.pv-t').checkVisibility({contentVisibilityAuto: true})"


class ManyLinesWhileThePdfScrolls(BrowserBase):
    """A figure document of sixty pages, each a figure with its page verdict line, every other one with Alice's verdict,
    on a 1400x850 desktop with the pin panel open."""

    WHO = ALICE

    def setUp(self):
        """The three viewer documents, the figure's build replaced by sixty one-figure pages, its word file asking for
        page lines, and a verdict of Alice's on every odd page."""
        super().setUp()
        _ms, self.fig, _rv = helpers_figure.viewer_docs(ps.APP, ps.APP.C.src)
        (self.fig.main.parent / "figures.limnverdicts.json").write_text(json.dumps(WORDS, ensure_ascii=False), "utf-8")
        fmap = {
            "format": "limn-figure-map/1",
            "pdf": "figures.pdf",
            "pdf_sha256": "0" * 64,
            "pages": [
                {
                    "page": i,
                    "figure": "F%02d" % i,
                    "title": "[후보] F%02d · 다섯 비교 쌍의 월별 효과" % i,
                    "elements": [
                        {
                            "id": "F%02d" % i,
                            "frac": [0, 0, 1, 1],
                            "src": {"file": "src/B2_calendar.py", "lo": 12, "hi": 140},
                        }
                    ],
                }
                for i in range(1, N_PAGES + 1)
            ],
        }
        d = helpers_figure.write_build(self.fig, helpers_figure.BUILD2, fmap, pages=N_PAGES)
        for i in range(1, N_PAGES + 1):
            (d / ("page-%d.png" % i)).write_bytes(PAGE_PNG)
        patch = mock.patch.object(pick_source, "region_text", return_value="")  # pdftotext answers no text
        patch.start()
        self.addCleanup(patch.stop)
        self.verdicts = [self.verdict(n, "채택") for n in range(1, N_PAGES + 1, 2)]

    def call(self, method, path, body=None):
        """One request to the handler as Alice -> (status, JSON)."""
        data = json.dumps(body).encode() if body is not None else b""
        h = {"Host": "127.0.0.1:18999", **ALICE}
        if data:
            h.update({"Content-Type": "application/json", "Content-Length": str(len(data))})
        if method == "POST":
            h["Origin"] = "http://127.0.0.1:18999"
        raw = ("%s %s HTTP/1.1\r\n" % (method, path) + "".join("%s: %s\r\n" % kv for kv in h.items()) + "\r\n").encode()
        code, _, out = split_resp(talk_to(ps, raw + data))
        return code, json.loads(out or b"null")

    def verdict(self, n, key):
        """A verdict of Alice's on page n's whole figure, made through the API as the page line makes it; its id."""
        meta = self.call("GET", "/api/meta?doc=fig")[1]
        pg = meta["pages"][n - 1]
        pick = {"doc": "fig", "page": n, "x0": 0, "y0": 0, "x1": pg["pt_w"], "y1": pg["pt_h"], "frac": [0, 0, 1, 1]}
        code, d = self.call("POST", "/api/pick", {**pick, "pdf_build": meta["pages_build"]})
        self.assertEqual(code, 200, d)
        body = {k: d[k] for k in helpers_figure.SAVE_LINE if d.get(k) is not None}
        body.update(scope=d["default_level"], doc="fig", note="", verdict=key)
        code, made = self.call("POST", "/api/pin", body)
        self.assertEqual(code, 200, made)
        return made["id"]

    def on_fig(self, must_skip=True):
        """The viewer showing the figure document from its top, settled, once most lines are skipped - or, unless
        must_skip, once 8s have passed without that."""
        from playwright.sync_api import TimeoutError as PlaywrightTimeout  # the module loads without Playwright

        page = self.open(len(self.verdicts))
        page.evaluate("k=>switchDoc(k)", "fig")
        page.wait_for_function("META&&META.doc==='fig'&&document.querySelectorAll('#doc .pv').length===%d" % N_PAGES)
        settle(page)
        try:
            page.wait_for_function("(%s)() > %d" % (SKIPPED, N_PAGES // 2), timeout=8000)
        except PlaywrightTimeout:
            if must_skip:
                self.fail("the lines far from the view are drawn")
        return page

    def test_a_font_added_while_the_pdf_scrolls_lays_out_the_lines_near_the_view_only(self):
        """Eight fonts added as the PDF area scrolls, then eight more with every line drawn (as before the fix): the
        largest layout of the first eight walks fewer objects than that of the second by more than half of what the
        lines hold. The rest of the page - the pages, the open panel's thirty cards, the bars - is as large as the lines
        here, so the bound is on what skipping takes out, not on the whole. Before the fix the two were the same (2,913
        objects; 1,569 with it)."""
        page = self.on_fig(must_skip=False)  # with nothing skipped the bound says what a font cost
        nodes = page.evaluate(LINE_NODES)
        long, events = traced(page, SCROLL_ADDING_FONTS, 8)
        laid = laid_out(events)
        self.assertTrue(laid, "no layout in the trace")
        page.add_style_tag(content="#doc .pv{content-visibility:visible!important}")
        settle(page)
        _, events = traced(page, SCROLL_ADDING_FONTS, 8)
        drawn = laid_out(events)
        self.assertLess(
            max(laid),
            max(drawn) - nodes // 2,
            "a font added while the PDF area scrolled laid out %d objects, %d with every line drawn; the lines hold %d nodes"
            " (layouts %s, long tasks %s ms)" % (max(laid), max(drawn), nodes, sorted(laid, reverse=True)[:8], long),
        )

    def test_through_the_document_no_page_moves_and_no_line_near_the_view_is_skipped(self):
        """From the top to the end in steps: at each, lines are skipped, none in the view nor the reading line is, every
        line stands at the height it is drawn at, and every page stands where it stood at the top."""
        page = self.on_fig()
        tops = page.evaluate(PAGE_TOPS)
        for at in (0, 0.2, 0.45, 0.7, 1):
            with self.subTest(at=at):
                page.evaluate(SCROLL_TO, at)
                settle(page)
                self.assertGreater(page.evaluate(SKIPPED), N_PAGES // 2, "the lines far from the view are drawn")
                self.assertEqual(page.evaluate(HELD_IN_VIEW), [], "lines in view or reading that the browser may skip")
                self.assertEqual(
                    page.evaluate(HEIGHTS), [], "lines that stand at another height than they are drawn at"
                )
                moved = [
                    (i + 1, a, b)
                    for i, (a, b) in enumerate(zip(tops, page.evaluate(PAGE_TOPS), strict=True))
                    if abs(a - b) > 0.01
                ]
                self.assertEqual(moved, [], "pages that moved")

    def skipped(self, page, n):
        """Wait until page n's line is skipped: a line drawn for a measure (HEIGHTS, pvFit) is skipped again a frame
        after the browser has seen it out of view, so its standing height is the one it is skipped at."""
        from playwright.sync_api import TimeoutError as PlaywrightTimeout  # the module loads without Playwright

        try:
            page.wait_for_function("!(%s)(%d)" % (DRAWN, n), timeout=8000)
        except PlaywrightTimeout:
            self.fail("page %d's line, far from the view, is drawn" % n)

    def test_a_line_changed_far_from_the_view_stands_at_its_new_height_and_shows_it(self):
        """Far below the view: a verdict saved elsewhere on an empty page's line, then the line made narrow enough to
        stack - each time it is measured drawn and, skipped, stands at its new height; scrolled to, it shows the
        verdict. A line holding the focus is drawn wherever it is."""
        page = self.on_fig()
        n = N_PAGES - 2  # an even page: no verdict yet
        line = '#doc .pv[data-page="%d"]' % n
        self.skipped(page, n)
        made = self.verdict(n, "보류")
        self.assertTrue(page.evaluate("loadPins()"))
        settle(page)
        self.skipped(page, n)
        self.assertEqual(page.evaluate(HEIGHTS), [], "lines that stand at another height than they are drawn at")
        self.skipped(page, n)
        before = page.evaluate("s => document.querySelector(s).getBoundingClientRect().height", line)
        page.evaluate("s => {const l = document.querySelector(s); l.style.width = '300px'; pvFit([l]);}", line)
        settle(page)
        self.skipped(page, n)
        got = page.evaluate(
            "s => {const l = document.querySelector(s); return [l.classList.contains('pv-stack'), l.getBoundingClientRect().height];}",
            line,
        )
        self.assertEqual(got[0], True, "a 300px line did not stack")
        self.assertGreater(got[1], before + 8, "the stacked line stands at its old height")
        self.assertEqual(page.evaluate(HEIGHTS), [], "lines that stand at another height than they are drawn at")
        page.evaluate("s => document.querySelector(s + ' button.vd-b').focus({preventScroll: true})", line)
        self.assertEqual(
            page.evaluate("s => getComputedStyle(document.querySelector(s)).contentVisibility", line), "visible"
        )
        page.evaluate("document.activeElement.blur()")
        page.evaluate("sizePv()")
        page.evaluate("s => document.querySelector(s).parentElement.scrollIntoView({block: 'center'})", line)
        settle(page)
        self.assertTrue(page.evaluate(DRAWN, n), "the line scrolled to is skipped")
        self.assertIn("#%d" % made, page.evaluate("s => document.querySelector(s + ' .pv-ref').textContent", line))
        self.assertEqual(page.evaluate(HELD_IN_VIEW), [], "lines in view or reading that the browser may skip")
        self.assertEqual(page.evaluate(HEIGHTS), [], "lines that stand at another height than they are drawn at")

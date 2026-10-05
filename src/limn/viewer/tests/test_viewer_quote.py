"""The PDF text a drag chose (the pick's `quote`) beside the source lines of a LaTeX document (issue #185, variant B).

The composer shows it as one line right under the location line, and a pin card as the same line above its note
(docs/handbook/viewer.md §패널 정리). The line is cut to one line with an ellipsis, the whole text is its tooltip, and a press
opens it in full. A pick or pin without that text draws no line; a view-only PDF's region already shows its text as the
source, and a figure document's quote is the element's name, so neither gets the line. The text is the manuscript's, never
translated.

- ``QuoteLogic`` runs the pure decision (shownQuote) under node.
- ``QuoteLine`` drives the real viewer in Chromium: desktop, a phone sheet, English.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_quote.py
"""

import json
import shutil
import unittest

from helpers import add_pin, extract_js_fn, run_node
from helpers_access import ALICE, actor
from helpers_browser import BrowserBase, settle

DESK = {"viewport": {"width": 1400, "height": 850}}
PHONE_360 = {"viewport": {"width": 360, "height": 780}, "is_mobile": True, "has_touch": True}
# A dragged sentence longer than one line of the composer at any panel width.
LONG = (
    "Each meter reports hourly load, outdoor temperature and a calendar index, and the sample is small on purpose "
    "so that every figure fits."
)
# The composer's quote line, the location row above it and the note below it, as drawn.
GEOMETRY = """() => {const r = s => {const e = document.querySelector(s); if (!e || !e.getClientRects().length) return null;
  const b = e.getBoundingClientRect(); return {top: b.top, bottom: b.bottom, height: b.height, left: b.left, right: b.right};};
  const q = document.querySelector('#c-quote'), t = q && q.querySelector('.q-t');
  return {quote: r('#c-quote'), row: r('.c-loc-row'), note: r('#note'), actions: r('#c-actions'),
    text: t ? t.textContent : null, tip: q ? q.dataset.tip || null : null, cut: t ? t.scrollWidth > t.clientWidth : null,
    expanded: q ? q.getAttribute('aria-expanded') : null, translate: q ? q.getAttribute('translate') : null};}"""


class QuoteLogic(unittest.TestCase):
    """shownQuote decides which pick or pin shows its quote line and with what text."""

    def setUp(self):
        """The decision runs the served functions under node."""
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_only_a_latex_line_pick_with_text_shows_its_quote(self):
        """A LaTeX line pick shows its quote trimmed; an empty or blank quote, a region (view-only PDF or a figure
        region) and a figure document's line pick (its quote is the element's name) show nothing."""
        js = "\n".join(
            [
                extract_js_fn("isRegion"),
                extract_js_fn("isFigureKind"),
                extract_js_fn("shownQuote"),
                r"""
                const line = {file: '/ms/main.tex', lo: 4, hi: 5};
                console.log(JSON.stringify([
                  shownQuote({...line, quote: '  Each meter reports  '}, DOC_KIND.TEX),
                  shownQuote({...line, quote: ''}, DOC_KIND.TEX),
                  shownQuote({...line, quote: '   '}, DOC_KIND.TEX),
                  shownQuote({...line}, DOC_KIND.TEX),
                  shownQuote({kind: 'region', pdf: '/ms/r.pdf', page: 1, quote: 'Region text'}, DOC_KIND.PDF),
                  shownQuote({...line, quote: '7월'}, DOC_KIND.FIGURE),
                  shownQuote({...line, quote: 'Body'}, undefined),
                  shownQuote(null, DOC_KIND.TEX),
                ]));
                """,
            ]
        )
        self.assertEqual(json.loads(run_node(js)), ["Each meter reports", "", "", "", "", "", "Body", ""])


class QuoteLine(BrowserBase):
    """The quote line in the real viewer: under the location line, above a card's note, folded to one line until pressed."""

    WHO = ALICE

    def pick_with(self, page, quote, pointer="mouse"):
        """Answer the next pick with quote and select through the real pick path with pointer; wait for the composer."""
        self.PICK = {"quote": quote}
        page.evaluate("p=>{LAST_PTR=p; pick({page:1,x0:10,y0:10,x1:200,y1:60});}", pointer)
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking", timeout=8000)
        settle(page)
        return page.evaluate(GEOMETRY)

    def test_a_drag_shows_the_dragged_text_on_one_line_under_the_location_line(self):
        """The line sits between the location row and the note, holds the whole text (cut by CSS, so it ellipsizes),
        carries it as its tooltip and is not translated."""
        page = self.open(0, **DESK)
        g = self.pick_with(page, LONG)
        self.assertIsNotNone(g["quote"], "no quote line")
        self.assertEqual((g["text"], g["tip"], g["translate"], g["expanded"]), (LONG, LONG, "no", "false"))
        self.assertTrue(g["cut"], "the long quote is not cut to one line")
        self.assertLessEqual(g["quote"]["height"], 24)
        self.assertGreaterEqual(g["quote"]["top"], g["row"]["bottom"] - 0.5)
        self.assertLessEqual(g["quote"]["bottom"], g["note"]["top"] + 0.5)

    def test_an_empty_quote_draws_no_line(self):
        """A tap or a long press finds no text: an empty or blank quote leaves no line and no gap."""
        page = self.open(0, **DESK)
        for quote in ("", "   "):
            with self.subTest(quote=quote):
                g = self.pick_with(page, quote)
                self.assertIsNone(g["quote"])
                self.assertEqual(page.eval_on_selector("#c-quote", "e=>e.childElementCount"), 0)

    def test_a_press_opens_the_line_in_full_and_another_folds_it(self):
        """Clicking the line (or Enter on it) wraps the whole text and drops the tooltip that would repeat it; a range
        change keeps it open; a new pick starts folded."""
        page = self.open(0, **DESK)
        folded = self.pick_with(page, LONG)["quote"]["height"]
        page.click("#c-quote")
        g = page.evaluate(GEOMETRY)
        self.assertEqual(g["expanded"], "true")
        self.assertGreater(g["quote"]["height"], folded + 8)
        self.assertFalse(g["cut"])
        self.assertIsNone(g["tip"])
        page.evaluate("renderComposer()")
        self.assertEqual(page.evaluate(GEOMETRY)["expanded"], "true")
        page.focus("#c-quote")
        page.keyboard.press("Enter")
        g = page.evaluate(GEOMETRY)
        self.assertEqual((g["expanded"], g["tip"]), ("false", LONG))
        self.assertAlmostEqual(g["quote"]["height"], folded, delta=0.5)
        page.click("#c-quote")
        self.assertEqual(self.pick_with(page, LONG)["expanded"], "false")

    def test_a_view_only_region_keeps_its_text_as_the_source_only(self):
        """A region answer already shows '영역 글자: …' in the source: no second line of the same text."""
        page = self.open(0, **DESK)
        self.PICK = {"kind": "region", "view_only": True, "lo": None, "hi": None, "file": None, "quote": "Region text"}
        page.evaluate("()=>{LAST_PTR='mouse'; pick({page:1,x0:10,y0:10,x1:200,y1:60});}")
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking", timeout=8000)
        settle(page)
        self.assertIsNone(page.evaluate(GEOMETRY)["quote"])
        self.assertIn("Region text", page.text_content("#c-snip"))

    def test_a_saved_card_shows_the_line_above_its_note_and_a_pin_without_text_none(self):
        """The card of a pin with a quote has the same line right above its note; a pin without one has none."""
        quoted = add_pin(
            {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "줄여 주세요", "quote": LONG}, actor(ALICE)
        ).record["id"]
        bare = add_pin({"file": str(self.main), "lo": 8, "hi": 9, "page": 1, "note": "오타"}, actor(ALICE)).record["id"]
        page = self.open(2, **DESK)
        card = '.pin.card[data-id="%d"]' % quoted
        got = page.eval_on_selector(
            card,
            "c=>{const q=c.querySelector('.quote'),n=c.querySelector('.note');"
            "return {text:q&&q.querySelector('.q-t').textContent,tip:q&&q.dataset.tip,translate:q&&q.getAttribute('translate'),"
            "before:!!q&&q.nextElementSibling===n,cut:q&&q.querySelector('.q-t').scrollWidth>q.querySelector('.q-t').clientWidth};}",
        )
        self.assertEqual(got, {"text": LONG, "tip": LONG, "translate": "no", "before": True, "cut": True})
        self.assertEqual(page.locator('.pin.card[data-id="%d"] .quote' % bare).count(), 0)
        # Opened, the card's line stays open across the list's redraws.
        page.click(card + " .quote")
        page.evaluate("drawPins()")
        self.assertEqual(page.get_attribute(card + " .quote", "aria-expanded"), "true")

    def test_on_a_phone_the_line_and_the_note_fit_the_sheets_first_screen_and_a_tap_opens_it(self):
        """360x780: the risen sheet shows the location line, the quote line and the whole note above [취소][핀 저장]; the
        line answers a 44px target that ends where the location row and the note begin, and a tap opens it."""
        page = self.open(0, **PHONE_360)
        g = self.pick_with(page, LONG, pointer="touch")
        self.assertIsNotNone(g["quote"])
        q = g["quote"]
        mid = (q["top"] + q["bottom"]) / 2
        hits = page.evaluate(
            "([x,ys])=>ys.map(y=>{const e=document.elementFromPoint(x,y); return !!e&&!!e.closest('#c-quote');})",
            [(q["left"] + q["right"]) / 2, [mid - 21.5, mid + 21.5, g["row"]["bottom"] - 1, g["note"]["top"] + 1]],
        )
        self.assertEqual(hits, [True, True, False, False])
        self.assertLessEqual(g["note"]["bottom"], g["actions"]["top"])
        self.assertGreaterEqual(g["row"]["top"], page.locator("#right").bounding_box()["y"])
        box = page.locator("#c-quote").bounding_box()
        page.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        settle(page)
        self.assertEqual(page.evaluate(GEOMETRY)["expanded"], "true")

    def test_in_english_the_text_stays_as_dragged_and_its_name_is_english(self):
        """The quote is the manuscript's own text: a Korean sentence stays Korean on an English screen, while the
        screen-reader name drawn with it is English."""
        page = self.open(0, lang="en", **DESK)
        g = self.pick_with(page, "완료 표를 보세요")
        self.assertEqual(g["text"], "완료 표를 보세요")
        self.assertEqual(page.text_content("#c-quote .sr-only").strip(), "Text chosen in the PDF:")

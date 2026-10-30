"""A long pin list while the PDF area scrolls (docs/handbook/viewer.md §목록 구획, issue #305).

Each page PDF.js draws for the first time adds its embedded fonts to document.fonts, and every font added makes the
browser lay out all the text in the page again. With the pin panel open that was every card in it: 127 cards made the
first wheel scroll through a 91-page figure document 77-84 long tasks (4.4-4.9s), and none with the panel folded. The
cards more than a view's height from the list's view are now left for the browser to skip (content-visibility:auto) at
the height each was drawn at (list.js lazyCards).

The cost is held by a count, not a duration: the layout objects the browser lays out after a font is added, read from a
Chrome trace (the Layout event's dirtyObjects), against the nodes the cards hold. The test adds fonts as PDF.js does (a
FontFace from bytes, a family no text uses) while it scrolls the PDF area, so it needs no PDF with embedded fonts. The
long tasks are only reported. What skipping must not change is held too: no card in view is skipped (it would be drawn
on whole pixels and clipped), every card stands at its drawn height (on the phone too, whose sheet opens after the first
draw), the view stays where it stands across a redraw that changed a card above it or took the card at its top to
another section or away, and a card changed while out of view shows what it holds now when it comes in.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_list_scroll.py
"""

import base64
import json
import time

from limn.pins.lifecycle.rules import CloseRequest
from limn.security.access import LOCAL_ACTOR

from helpers import add_pin, edit_pin, ps, record_of
from helpers_access import ALICE, actor
from helpers_authority import post_authority
from helpers_browser import BrowserBase, settle

DESKTOP = {"viewport": {"width": 1400, "height": 850}}
PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
NO_COACH = "try{localStorage.setItem('pinPrefs',JSON.stringify({coach:{touch:1,mouse:1,sel:1}}))}catch(e){}"

N_PINS = 300  # "hundreds of pins": more than twice the 127 the issue measured
TRACE_FLUSH_S = 30
NOTES = (
    "문단을 줄입니다",
    "이 식의 번호가 본문과 다릅니다. 앞 절의 정의를 따라 다시 매깁니다",
    "그림 3의 축 이름이 표와 다릅니다. 단위도 함께 적어 주세요. 범례는 아래로 내립니다",
    "오타",
)
# Scrolls the PDF area in steps and, at each, adds one font the way PDF.js does for a page it draws first (a FontFace from
# the font file's bytes under a name of its own, added to document.fonts), waits for it and for two frames. Returns the
# long tasks' durations (ms) seen meanwhile.
SCROLL_ADDING_FONTS = """async (steps) => {
  const L = document.querySelector('#left'), frames = () => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  const bytes = await (await fetch('/vendor/pretendard/PretendardVariable.subset.0.woff2')).arrayBuffer();
  const long = [], po = new PerformanceObserver(l => { for (const e of l.getEntries()) long.push(Math.round(e.duration)); });
  po.observe({type: 'longtask'});
  for (let i = 0; i < steps; i++) {
    L.scrollTop += 120;
    const f = new FontFace('limn-test-pdf-font-' + i, bytes.slice(0)); document.fonts.add(f); await f.loaded;
    await frames();
  }
  po.disconnect();
  return long;
}"""
# The DOM nodes (elements and text) the cards hold: the layout objects a layout of every card walks, near enough.
CARD_NODES = """() => {let n = 0; for (const c of document.querySelectorAll('#list .pin.card')) {
  const w = document.createTreeWalker(c); while (w.nextNode()) n++;} return n;}"""
# The card at the middle of the list's view: its id, its top in that view and whether it is drawn (not skipped). After a jump the browser
# draws the cards it brought into view a frame or two later; till then they stand at their guessed height.
AT_READING_POINT = """() => {const r = listScroller().getBoundingClientRect(), mid = (Math.max(r.top, 0) + Math.min(r.bottom, innerHeight)) / 2;
  const c = [...document.querySelectorAll('#list .pin.card')].find(c => c.getBoundingClientRect().bottom > mid);
  return [c.dataset.id, c.getBoundingClientRect().top - r.top, c.firstElementChild.checkVisibility({contentVisibilityAuto: true})];}"""
# Where the card of pin id stands in the list's view: its top less the scroller's (a chip the poll brings to the tool bar
# moves the whole panel, not the list in it).
IN_VIEW_TOP = """id => document.querySelector('#list .pin[data-id="' + id + '"]').getBoundingClientRect().top
  - listScroller().getBoundingClientRect().top"""
# The id of the first card whose bottom is below the top of the list's view.
TOP_CARD = """() => {const t = listScroller().getBoundingClientRect().top;
  return +[...document.querySelectorAll('#list .pin.card')].find(c => c.getBoundingClientRect().bottom > t).dataset.id;}"""
# How many cards the browser skips now: their content is not drawn.
SKIPPED = """() => [...document.querySelectorAll('#list .pin.card')]
  .filter(c => !c.firstElementChild.checkVisibility({contentVisibilityAuto: true})).length"""
# The cards in the list's view the browser may skip (content-visibility not visible): none should be. Skipping contains a
# card, which draws its parts on whole pixels and clips what reaches past its edge.
HELD_IN_VIEW = """() => {const r = listScroller().getBoundingClientRect();
  return [...document.querySelectorAll('#list .pin.card')].filter(c => {const b = c.getBoundingClientRect();
    return b.bottom > r.top && b.top < r.bottom && getComputedStyle(c).contentVisibility !== 'visible';}).map(c => c.dataset.id);}"""
# The cards whose height as they stand now is not the one they are drawn at (read with the skipping taken off every card,
# then put back): [id, standing, drawn].
HEIGHTS = """() => {const cs = [...document.querySelectorAll('#list .pin.card')], at = cs.map(c => c.getBoundingClientRect().height);
  cs.forEach(c => { c.style.contentVisibility = 'visible'; }); const drawn = cs.map(c => c.getBoundingClientRect().height);
  cs.forEach(c => { c.style.contentVisibility = ''; });
  return cs.map((c, i) => [c.dataset.id, at[i], drawn[i]]).filter(r => Math.abs(r[1] - r[2]) > 0.01);}"""


def traced(page, script, arg):
    """Run the async page function script(arg) under a Chrome trace of the devtools timeline; return its value and the
    trace's events."""
    cdp = page.context.new_cdp_session(page)
    cdp.send("Tracing.start", {"categories": "devtools.timeline", "transferMode": "ReturnAsStream"})
    value = page.evaluate(script, arg)
    done = []
    cdp.on("Tracing.tracingComplete", lambda e: done.append(e))
    cdp.send("Tracing.end")
    # Wait for tracingComplete - the trace flushed to its stream - up to TRACE_FLUSH_S. The sync session delivers an event
    # only while it waits on a command, so it waits on cheap ones until the event has come or the time is out.
    until = time.monotonic() + TRACE_FLUSH_S
    while not done and time.monotonic() < until:
        cdp.send("Runtime.evaluate", {"expression": "0"})
    assert done, "Tracing.tracingComplete did not come within %ds" % TRACE_FLUSH_S
    chunks = []
    while True:
        part = cdp.send("IO.read", {"handle": done[0]["stream"], "size": 1 << 20})
        chunks.append(base64.b64decode(part["data"]).decode() if part.get("base64Encoded") else part["data"])
        if part.get("eof"):
            break
    cdp.send("IO.close", {"handle": done[0]["stream"]})
    cdp.detach()
    data = json.loads("".join(chunks))
    return value, data["traceEvents"] if isinstance(data, dict) else data


class ManyCardsWhileThePdfScrolls(BrowserBase):
    """Three hundred open pins in the open panel of a 1400x850 desktop."""

    WHO = ALICE

    def setUp(self):
        """Three hundred open pins over the demo manuscript's lines, their notes one to three lines long."""
        super().setUp()
        who = actor(ALICE)
        self.pins = [
            add_pin(
                {
                    "file": str(self.main),
                    "lo": 3 + i % 30,
                    "hi": 4 + i % 30,
                    "page": 1 + i % 2,
                    "note": NOTES[i % len(NOTES)] + " (%d)" % i,
                },
                who,
            ).record
            for i in range(N_PINS)
        ]

    def skipping(self, page, cond, msg):
        """Wait until cond holds: the browser skips a card a frame after the observer's report that marks it, itself a
        task after the frame that drew it, so a draw's skipping can still be on its way once the page has settled."""
        from playwright.sync_api import TimeoutError as PlaywrightTimeout  # the module loads without Playwright

        try:
            page.wait_for_function(cond, timeout=8000)
        except PlaywrightTimeout:
            self.fail(msg)

    def test_a_font_added_while_the_pdf_scrolls_lays_out_the_cards_in_view_only(self):
        """Eight fonts added as the PDF area scrolls: no layout walks more than a third of what the cards hold. Before the
        fix every one of them laid out all 300 cards again (all their nodes and the rest of the page)."""
        page = self.open(N_PINS)
        self.assertEqual(page.evaluate("document.querySelectorAll('#list .pin.card').length"), N_PINS)
        nodes = page.evaluate(CARD_NODES)
        long, events = traced(page, SCROLL_ADDING_FONTS, 8)
        laid = [
            e["args"]["beginData"]["dirtyObjects"]
            for e in events
            if e.get("name") == "Layout" and "beginData" in e.get("args", {})
        ]
        self.assertTrue(laid, "no layout in the trace")
        self.assertLess(
            max(laid),
            nodes // 3,
            "a font added while the PDF area scrolled laid out %d objects; the cards hold %d nodes (layouts %s, long tasks %s ms)"
            % (max(laid), nodes, sorted(laid, reverse=True)[:8], long),
        )

    def test_a_redraw_leaves_the_list_where_it_stands(self):
        """Down the list - on the phone in the sheet opened after the boot's draw - every card stands at the height it is
        drawn at, and after someone makes the note of a card above the view twelve times as long, the list read again
        leaves the card at the reading point where it was (the draw makes new cards, so the browser's own scroll anchoring
        cannot hold it)."""
        rev = {p["id"]: p["rev"] for p in self.pins}
        for name, device in (("desktop", DESKTOP), ("phone", PHONE)):
            with self.subTest(band=name):
                page = self.open(N_PINS, init=NO_COACH, **device)
                page.evaluate("setSide(true)")
                settle(page)
                self.skipping(page, "(%s)() > %d" % (SKIPPED, N_PINS // 2), "the cards out of view are drawn")
                self.assertEqual(page.evaluate(HELD_IN_VIEW), [], "cards in view that the browser may skip")
                self.assertEqual(
                    page.evaluate(HEIGHTS), [], "cards that stand at another height than they are drawn at"
                )
                page.evaluate("() => {const S = listScroller(); S.scrollTop = S.scrollHeight * 0.6;}")
                page.wait_for_function("(%s)()[2]" % AT_READING_POINT, timeout=8000)
                settle(page)
                pid, top, _ = page.evaluate(AT_READING_POINT)
                above = page.evaluate(
                    """() => {const t = listScroller().getBoundingClientRect().top;
                      return +[...document.querySelectorAll('#list .pin.card')].filter(c => c.getBoundingClientRect().bottom < t).pop().dataset.id;}"""
                )
                longer = ("%s님이 고친 메모입니다. " % name * 12).strip()
                rec = record_of(edit_pin(above, {"note": longer, "base_rev": rev[above]}, actor(ALICE)))
                rev[above] = rec["rev"]
                self.assertTrue(page.evaluate("loadPins()"))
                settle(page)
                self.assertEqual(
                    page.evaluate(IN_VIEW_TOP, pid),
                    top,
                    "the list moved under the reading point at a redraw",
                )
                self.assertEqual(
                    page.evaluate(HEIGHTS), [], "cards that stand at another height than they are drawn at"
                )
                self.assertEqual(page.evaluate(HELD_IN_VIEW), [], "cards in view that the browser may skip")

    def test_a_poll_that_takes_the_top_card_away_leaves_the_view_where_it_stands(self):
        """Down the list, the card at the top of the view leaves it with a poll - first an agent closes its pin, which goes
        to 검토 대기 below every open card, then the next top card's pin is deleted. Each time the view stays where it
        stood, held by the next card in view of the same section: followed into 검토 대기, it jumped past every open card."""
        page = self.open(N_PINS, init=NO_COACH, **DESKTOP)
        page.evaluate("() => {const S = listScroller(); S.scrollTop = S.scrollHeight * 0.6;}")
        page.wait_for_function("(%s)()[2]" % AT_READING_POINT, timeout=8000)
        settle(page)
        for how in ("closed by an agent", "deleted"):
            with self.subTest(how=how):
                pid, top, _ = page.evaluate(AT_READING_POINT)
                first = page.evaluate(TOP_CARD)
                self.assertNotEqual(first, int(pid))
                if how == "deleted":
                    ps.APP.pin_trash.drop_pin(
                        first, post_authority(ps.APP.pin_trash.context().store, actor(ALICE), "drop", first)
                    )
                else:
                    store = ps.APP.pin_lifecycle.context().store
                    ps.APP.pin_lifecycle.close_pin(
                        first, post_authority(store, dict(LOCAL_ACTOR), "close", first), CloseRequest(reply="고침")
                    )
                self.assertTrue(page.evaluate("loadPins()"))
                settle(page)
                self.assertEqual(
                    page.evaluate(IN_VIEW_TOP, pid),
                    top,
                    "the view moved when the card at its top was %s" % how,
                )

    def test_a_card_changed_out_of_view_comes_in_with_what_it_holds_now(self):
        """A card near the end of the list, out of view and skipped, gets a note twelve times as long from someone else; the
        list is read again. Scrolled into view, it is drawn with the new note, at the new note's height."""
        page = self.open(N_PINS)
        self.assertEqual(page.evaluate(HEIGHTS), [], "cards that stand at another height than they are drawn at")
        far = self.pins[-3]["id"]  # near the end, out of view
        longer = ("다른 사람이 고친 메모입니다. " * 12).strip()
        self.assertEqual(
            record_of(edit_pin(far, {"note": longer, "base_rev": self.pins[-3]["rev"]}, actor(ALICE)))["note"], longer
        )
        self.assertTrue(page.evaluate("loadPins()"))
        settle(page)
        self.assertEqual(page.evaluate(HEIGHTS), [], "cards that stand at another height than they are drawn at")
        card = "#list .pin[data-id='%d']" % far
        self.skipping(
            page,
            "!document.querySelector(%s).firstElementChild.checkVisibility({contentVisibilityAuto: true})"
            % json.dumps(card),
            "the card out of view is drawn: cards are not skipped",
        )
        page.evaluate("s => document.querySelector(s).scrollIntoView({block: 'center'})", card)
        settle(page)
        drawn = page.evaluate(
            """s => {const c = document.querySelector(s), n = c.querySelector('.note'), h = c.getBoundingClientRect().height;
              c.style.contentVisibility = 'visible'; const d = c.getBoundingClientRect().height; c.style.contentVisibility = '';
              return [c.firstElementChild.checkVisibility({contentVisibilityAuto: true}), n.textContent, h, d];}""",
            card,
        )
        self.assertEqual(drawn[:2], [True, longer])
        self.assertAlmostEqual(drawn[2], drawn[3], delta=0.01)

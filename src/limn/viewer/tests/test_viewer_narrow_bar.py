"""The narrowest phone's sheet bar keeps every press area whole (docs/handbook/viewer.md §모바일 레이아웃, issue #418).

At 320px with a pin awaiting review the bar's left cell holds the chip's two 44px halves and [⬚], whose 44px hit is the 8px
gap and its 36px icon: 132px, more than the cell the centred grabber left at 12px edges. [⬚] stood 6px in the grabber's
column and answered 38px; narrowing the gap and the icon instead (the first attempt) moved its hit 8px over the chip's review
half. Read by touch in Korean and English, with a pin awaiting review and without, at 320px and round the 332px step (330,
331, 332, 334: the review half's width is its words', and an odd width puts the grabber's column on a half pixel), in
Chromium and Firefox (the words' widths are the fonts'): [⬚]'s drawn box ends before the grabber's column, its hit box
neither reaches the grabber's box nor the chip, every bar control and the grabber answer 44px round their centre - by whole
pixels and, for [⬚] and the grabber, along their centre line in 0.05px steps (a hit test rounded a transformed box's
fractional edge, and in Firefox [⬚] answered 43.6px at 331) - nothing spills out of its cell or the bar, the gap stays 8px
and the icon 36px, and under 332px the bar's edges are what gives.
"""

from limn.pins.lifecycle.rules import CloseRequest
from limn.security.access import LOCAL_ACTOR

from helpers import add_pin, ps
from helpers_access import ALICE, actor
from helpers_authority import post_authority
from helpers_browser import MISSES_44, BrowserBase


def phone(w):
    """A w x 720 phone, by touch at twice the CSS pixel."""
    return {"viewport": {"width": w, "height": 720}, "is_mobile": True, "has_touch": True, "device_scale_factor": 2}


# How wide el answers along its centre line: from the first to the last x, in 0.05px steps across its box and 30px on either
# side, at which the topmost element is el or inside it.
SPAN = """sel => {const e = document.querySelector(sel), r = e.getBoundingClientRect(), y = r.top + r.height / 2;
  const own = x => {const h = document.elementFromPoint(x, y); return !!h && (h === e || e.contains(h));};
  let a = null, b = null; for (let x = r.left - 30; x <= r.right + 30; x += 0.05) if (own(x)) {if (a === null) a = x; b = x;}
  return a === null ? 0 : b - a + 0.05;}"""
# The bar as drawn: boxes as [left, right] in CSS px - [⬚]'s drawn box and its hit box (its ::after, from the computed box and
# transform), the grabber's 44px box, the chip's halves, the left cell - the bar's overflow, the children that spill out of
# their cell, the cell's gap, [⬚]'s width and the bar's edge padding.
BAR = """() => {const q = s => document.querySelector(s), X = e => {const r = e.getBoundingClientRect(); return [r.left, r.right];};
  const sel = q('#btn-select'), a = getComputedStyle(sel, '::after'), m = new DOMMatrix(a.transform === 'none' ? undefined : a.transform);
  const hl = sel.getBoundingClientRect().left + sel.clientLeft + parseFloat(a.left) + m.e, bar = q('#bar1'), l = bar.querySelector('.bar-l');
  const shown = e => e.getClientRects().length > 0, spill = [];
  for (const c of bar.querySelectorAll(':scope>.bar-l,:scope>.bar-r')) {const [cl, cr] = X(c);
    for (const e of [...c.children].filter(shown)) {const [el, er] = X(e); if (el < cl - 0.5 || er > cr + 0.5) spill.push(e.id);}}
  return {select: X(sel), hit: [hl, hl + parseFloat(a.width)], grip: X(q('#sheet-grip')), side: X(q('#btn-side')),
    review: shown(q('#btn-rv')) ? X(q('#btn-rv')) : null, cell: X(l), over: bar.scrollWidth - bar.clientWidth, spill,
    gap: getComputedStyle(l).columnGap, icon: sel.getBoundingClientRect().width, edge: getComputedStyle(bar).paddingLeft,
    words: !bar.classList.contains('bar-tight')};}"""


class NarrowBar(BrowserBase):
    """In Chromium: the 320px sheet bar with open pins and one awaiting review."""

    def setUp(self):
        """Two open pins."""
        super().setUp()
        for i in range(2):
            add_pin(
                {
                    "file": str(self.main),
                    "lo": 4 + i,
                    "hi": 4 + i,
                    "page": 1,
                    "note": "p",
                    "frac": [0.1, 0.2, 0.3, 0.02],
                },
                actor(ALICE),
            )

    def await_review(self):
        """A third pin, closed by the agent, so the chip shows its review half."""
        rid = add_pin(
            {"file": str(self.main), "lo": 20, "hi": 21, "page": 2, "note": "r", "frac": [0.2, 0.3, 0.4, 0.04]},
            actor(ALICE),
        ).record["id"]
        ps.APP.pin_lifecycle.close_pin(
            rid,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", rid),
            CloseRequest(reply="done"),
        )

    def test_every_press_area_of_the_bar_is_whole_round_the_332px_step(self):
        """Korean and English, without a pin awaiting review and with one, at 320, 330, 331, 332 and 334px: [⬚] ends before
        the grabber's column and its hit box between the chip and the grabber, no bar control or the grabber answers under
        44px, [⬚] and the grabber answer 44px along their centre line, nothing spills, the gap is 8px and [⬚] 36px, the
        edges 4px under 332px and 12px from it. In Korean at 320 the chip keeps its words (핀 2 / 검토 1)."""
        for review in (0, 1):
            if review:
                self.await_review()
            for w in (320, 330, 331, 332, 334):
                for lang in ("ko", "en"):
                    with self.subTest(review=review, width=w, lang=lang):
                        page = self.open(2, lang=lang, **phone(w))
                        bar = page.evaluate(BAR)
                        self.assertEqual(bar["review"] is not None, bool(review), bar)
                        self.assertLessEqual(
                            bar["select"][1], bar["grip"][0], bar
                        )  # the drawn [⬚] is out of the grabber's column
                        self.assertLessEqual(
                            bar["hit"][1], bar["grip"][0] + 0.05, bar
                        )  # its hit does not reach the grabber's box
                        chip = bar["review"] or bar["side"]
                        self.assertGreaterEqual(bar["hit"][0], chip[1] - 0.05, bar)  # nor the chip
                        self.assertEqual(page.evaluate(MISSES_44, "#bar1 button,#sheet-grip"), [])
                        for sel in ("#btn-select", "#sheet-grip"):
                            self.assertGreaterEqual(page.evaluate(SPAN, sel), 43.95, sel)
                        self.assertEqual((bar["over"], bar["spill"]), (0, []), bar)
                        edge = "4px" if w < 332 else "12px"
                        self.assertEqual((bar["gap"], bar["icon"], bar["edge"]), ("8px", 36, edge), bar)
                        if lang == "ko" and w == 320:
                            self.assertTrue(bar["words"], bar)


class NarrowBarFirefox(NarrowBar):
    """The same bar in Firefox."""

    BROWSER_ENGINE = "firefox"

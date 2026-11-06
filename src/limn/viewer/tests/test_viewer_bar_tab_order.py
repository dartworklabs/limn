"""Tab crosses each bar from left to right as it is drawn (docs/handbook/viewer.md §모바일 레이아웃, issue #418).

The tool bar (#bar1) is one markup that each band draws in its own order: the phone and tablet sheet's grid as the markup
stands ([핀 N | 검토 M] [⬚] | the grabber | [⋯]), the wide row with [⋯] last, the mid and short rows [⬚] ··· [⋯] [핀 N | 검토 M]
(CSS order). Tab follows the markup, so the wide row went [⋯] → [PDF 재빌드] and the mid and short rows [핀] → [⬚] → [⋯] → the
status line's actions, right to left. Read on the desktop, the landscape and portrait tablets, the unfolded foldable both ways,
the phone, the landscape phone and a mouse at the mid widths, with a pin awaiting review (the chip's second half) and the first
visit's hint on the status line (with its two actions, the mid row's middle): in the tool bar and in the nav bar, the visible Tab stops as read - line by line, each left to
right by its centre (the touch desktop's wide row wraps) - are the stops Tab reaches one after another from the first. The band also changes under an open page - a mouse window resized
through the wide, mid, overlay and phone bands and back - and the order holds in each, with the focus left on [⋯].

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_bar_tab_order.py
"""

from limn.pins.lifecycle.rules import CloseRequest
from limn.security.access import LOCAL_ACTOR

from helpers import add_pin, ps
from helpers_access import ALICE, actor
from helpers_authority import post_authority
from helpers_browser import BrowserBase, settle

_TOUCH = {"has_touch": True, "is_mobile": True}
# name -> (viewport, touch, the body class of the band it should land in)
BANDS = {
    "desktop 1440x900": ({"width": 1440, "height": 900}, False, "band-wide"),
    "touch desktop 1440x900": ({"width": 1440, "height": 900}, True, "band-wide"),
    "tablet 1024x768": ({"width": 1024, "height": 768}, True, "band-mid-side"),
    "fold 841x673": ({"width": 841, "height": 673}, True, "band-mid-overlay"),
    "tablet 768x1024": ({"width": 768, "height": 1024}, True, "band-tablet-sheet"),
    "fold 673x841": ({"width": 673, "height": 841}, True, "band-tablet-sheet"),
    "phone 390x844": ({"width": 390, "height": 844}, True, "band-phone"),
    "landscape phone 844x390": ({"width": 844, "height": 390}, True, "band-short"),
    "mouse 1024x768": ({"width": 1024, "height": 768}, False, "band-mid-side"),
    "mouse 841x673": ({"width": 841, "height": 673}, False, "band-mid-overlay"),
}

# The visible Tab stops of the bar sel in reading order (kept as window.__row), as [name, centre x, centre y]: focusable, not
# disabled, drawn and not hidden; grouped into lines by their centre (12px apart or less is one line), the lines top to bottom
# and each line left to right - the touch desktop's wide row wraps to a second line. Each is named by its id, else its class
# and label.
ROW = """sel => {const root = document.querySelector(sel);
  const shown = e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden' && !e.closest('[hidden],[inert]');
  const at = e => {const r = e.getBoundingClientRect(); return [e, r.left + r.width / 2, r.top + r.height / 2];};
  const stops = [...root.querySelectorAll('button,input,select,textarea,a[href],[tabindex]')]
    .filter(e => e.tabIndex >= 0 && !e.disabled && shown(e)).map(at).sort((a, b) => a[2] - b[2]);
  const lines = []; for (const s of stops) {const l = lines[lines.length - 1]; if (l && s[2] - l[0][2] <= 12) l.push(s); else lines.push([s]);}
  const read = lines.flatMap(l => l.sort((a, b) => a[1] - b[1])); window.__row = read.map(s => s[0]);
  return read.map(([e, x, y]) => [e.id || (e.className + ' ' + (e.getAttribute('aria-label') || e.textContent.trim())).trim(), x, y]);}"""
# Where the focus is in window.__row: its index, or -1 outside it (a name for the message).
AT = """() => {const a = document.activeElement, i = window.__row.indexOf(a);
  return [i, a && a !== document.body ? (a.id || a.className || a.tagName) : null];}"""


class BarTabOrder(BrowserBase):
    """In Chromium: two open pins, one awaiting review, and the first visit's hint on the status line."""

    def setUp(self):
        """Two open pins on page 1 and a third closed by the agent, so the chip shows its review half."""
        super().setUp()
        for i in range(2):
            add_pin(
                {
                    "file": str(self.main),
                    "lo": 4 + i,
                    "hi": 4 + i,
                    "page": 1,
                    "note": "p",
                    "frac": [0.1, 0.2 + 0.1 * i, 0.3, 0.02],
                },
                actor(ALICE),
            )
        rid = add_pin(
            {"file": str(self.main), "lo": 20, "hi": 21, "page": 2, "note": "r", "frac": [0.2, 0.3, 0.4, 0.04]},
            actor(ALICE),
        ).record["id"]
        ps.APP.pin_lifecycle.close_pin(
            rid,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", rid),
            CloseRequest(reply="done"),
        )

    def device(self, viewport, touch):
        """The context options for a viewport, by touch or by a mouse (bundled Firefox has no mobile emulation)."""
        d = {"viewport": viewport}
        if touch:
            d.update(_TOUCH)
            if self.BROWSER_ENGINE != "chromium":
                d.pop("is_mobile")
        return d

    def assert_rows_read_left_to_right(self, page, where):
        """In the tool bar and the nav bar: from the first visible Tab stop as read, each Tab goes to the next one - to its
        right on its line, else the first of the next line."""
        for sel in ("#bar1", "#doc-nav"):
            row = page.evaluate(ROW, sel)
            if not row:
                continue
            page.evaluate("() => window.__row[0].focus()")
            got = [page.evaluate(AT)]
            for _ in row[1:]:
                page.keyboard.press("Tab")
                got.append(page.evaluate(AT))
            self.assertEqual(
                [i for i, _ in got],
                list(range(len(row))),
                "%s %s: Tab reached %s for the stops %s" % (where, sel, [n for _, n in got], [n for n, _, _ in row]),
            )

    def test_tab_crosses_the_bars_left_to_right_in_every_band(self):
        """Each band, with the panel as it opens and then toggled: the tool bar's and the nav bar's Tab stops in the order
        they are drawn. The tool bar has [⋯] in every band and the chip on touch outside the desktop."""
        for name, (viewport, touch, band) in BANDS.items():
            with self.subTest(name):
                page = self.open(2, **self.device(viewport, touch))
                self.assertIn(band, page.evaluate("document.body.className"))
                names = [n for n, _, _ in page.evaluate(ROW, "#bar1")]
                self.assertIn("btn-more", names)
                if touch and band != "band-wide":
                    self.assertTrue({"btn-side", "btn-rv", "btn-select"} <= set(names), names)
                if band in ("band-mid-side", "band-mid-overlay"):  # the status line's actions in the row's middle
                    self.assertTrue(any("st-more" in n for n in names) and any("nt-x" in n for n in names), names)
                for state in ("as opened", "toggled"):
                    if state == "toggled":
                        page.evaluate("document.querySelector('#btn-side').click()")
                        settle(page)
                    self.assert_rows_read_left_to_right(page, "%s, panel %s" % (name, state))

    def test_the_order_follows_the_band_as_the_window_changes(self):
        """A mouse window resized from the desktop through the mid side panel, the overlay panel and the phone and back:
        in each band the bars read left to right, and [⋯] keeps the focus it had through every change."""
        page = self.open(2, viewport={"width": 1440, "height": 900})
        for w, h, band in (
            (1000, 760, "band-mid-side"),
            (820, 700, "band-mid-overlay"),
            (600, 800, "band-phone"),
            (1000, 760, "band-mid-side"),
            (1440, 900, "band-wide"),
        ):
            with self.subTest(band=band, width=w):
                page.focus("#btn-more")
                page.set_viewport_size({"width": w, "height": h})
                page.wait_for_function("b => document.body.classList.contains(b)", arg=band)
                settle(page)
                self.assertEqual(page.evaluate("document.activeElement.id"), "btn-more")
                self.assert_rows_read_left_to_right(page, "%s at %d" % (band, w))

    def test_a_turned_foldable_keeps_the_chip_and_the_select_button_in_order(self):
        """By touch, an unfolded foldable turned between landscape (the overlay panel) and portrait (the tablet sheet), then
        held as a landscape phone (the short band) and turned back: in each band the chip's two halves and [⬚] are drawn on
        the tool bar - [⬚] back in the sheet's left cell after the mid row had it first - and the bars read left to right."""
        page = self.open(2, **self.device({"width": 841, "height": 673}, True))
        for w, h, band in (
            (673, 841, "band-tablet-sheet"),
            (841, 673, "band-mid-overlay"),
            (844, 390, "band-short"),
            (673, 841, "band-tablet-sheet"),
        ):
            with self.subTest(band=band, width=w):
                page.set_viewport_size({"width": w, "height": h})
                page.wait_for_function("b => document.body.classList.contains(b)", arg=band)
                settle(page)
                names = [n for n, _, _ in page.evaluate(ROW, "#bar1")]
                self.assertTrue({"btn-side", "btn-rv", "btn-select", "btn-more"} <= set(names), (band, names))
                self.assert_rows_read_left_to_right(page, "%s at %d" % (band, w))


class BarTabOrderFirefox(BarTabOrder):
    """The same bars in bundled Firefox."""

    BROWSER_ENGINE = "firefox"

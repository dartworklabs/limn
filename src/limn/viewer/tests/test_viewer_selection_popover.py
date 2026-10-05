"""The note popover by the selection box (issue #192, variant A): desktop and mouse layouts only.

When a mouse drag ends, a popover anchors under the dashed box with the location, a note field, [자세히 →] and [저장]
(docs/handbook/viewer.md §패널 정리 '선택 상자 곁 메모'). Its note field is the composer's note - one value both ways - and
[저장] and Cmd/Ctrl+Enter take the existing save path, so the chip with its 6 s undo follows unchanged. [자세히 →] hands over
to the full composer in the panel. Esc and a short click off the box cancel the selection as before; a press on the popover
is a press inside the box. The popover flips above the box when there is no room below, shifts left at the right edge, and
stays in the part of the PDF area nothing covers (never over the select mode's bar or the panel and its save row). Touch
picks keep the composer alone.

- ``PopoverLogic`` runs the pure placement (popPlace) under node.
- ``SelectionPopover`` drives the real viewer in Chromium.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_selection_popover.py
"""

import json
import shutil
import unittest

from helpers import extract_js_fn, ps, records, run_node
from helpers_access import ALICE
from helpers_browser import BrowserBase, fonts_ready, nothing_follows, settle

DESK = {"viewport": {"width": 1400, "height": 850}}
MOUSE_MID = {"viewport": {"width": 1000, "height": 800}}
PHONE = {"viewport": {"width": 384, "height": 832}, "is_mobile": True, "has_touch": True}
NO_SELECTION = "COMPOSE.current===null&&COMPOSE.box===null&&document.querySelector('#composer').hidden"
# The popover, the box, the free PDF area and the things it must not cover, as drawn.
GEOMETRY = """() => {const r = e => {if (!e || !e.getClientRects().length) return null; const b = e.getBoundingClientRect();
    return {left: b.left, top: b.top, right: b.right, bottom: b.bottom, width: b.width, height: b.height};};
  const q = s => document.querySelector(s), pop = q('#sel-pop');
  const shown = !!pop && !pop.hidden && getComputedStyle(pop).visibility !== 'hidden';
  return {pop: shown ? r(pop) : null, box: r(COMPOSE.box), left: r(q('#left')), area: r(q('#sel-mode')), bar: r(q('#sel-bar')),
    right: r(q('#right')), save: r(q('#c-actions')), side: pop ? pop.dataset.side || null : null,
    loc: pop ? (pop.querySelector('.sp-loc') || {}).textContent || '' : '', focus: document.activeElement && document.activeElement.id,
    field: pop ? pop.querySelector('textarea').value : null, note: q('#note').value};}"""
# The popover's inner edges and the vertical centres of its text, for the 0.5px alignment check.
ALIGN = """() => {const p = document.querySelector('#sel-pop'), b = e => e.getBoundingClientRect();
  const ink = e => {const g = document.createRange(); g.selectNodeContents(e); return g.getBoundingClientRect();};
  const loc = p.querySelector('.sp-loc'), kbd = p.querySelector('kbd'), f = p.querySelector('textarea');
  const more = p.querySelector('[data-act=pop-more]'), save = p.querySelector('[data-act=pop-save]');
  const label = e => ink(e.querySelector('.lbl') || e);
  return {pop: b(p), loc: ink(loc), kbd: b(kbd), kbdText: ink(kbd), field: b(f), more: b(more), moreText: label(more),
    save: b(save), saveText: label(save), pad: parseFloat(getComputedStyle(p).paddingLeft)};}"""


def overlaps(a, b):
    """Whether rectangles a and b ({left, top, right, bottom}) share any area."""
    return a["left"] < b["right"] and b["left"] < a["right"] and a["top"] < b["bottom"] and b["top"] < a["bottom"]


class PopoverLogic(unittest.TestCase):
    """popPlace puts the popover below the box, above it when below has no room, and keeps it in the free area."""

    def setUp(self):
        """The placement runs the served function under node."""
        if not shutil.which("node"):
            self.skipTest("node not available")

    def place(self, box, area, w=320, h=140):
        """popPlace for a box and an area given as [left, top, right, bottom]."""
        js = "\n".join(
            [
                extract_js_fn("popPlace"),
                "const R=a=>({left:a[0],top:a[1],right:a[2],bottom:a[3]});",
                "console.log(JSON.stringify(popPlace(R(%s),R(%s),%d,%d,8)));"
                % (json.dumps(box), json.dumps(area), w, h),
            ]
        )
        return json.loads(run_node(js))

    def test_below_the_box_with_its_left_edge(self):
        """Room below: 8px under the box, left edges aligned."""
        self.assertEqual(
            self.place([100, 100, 300, 140], [0, 0, 1000, 800]),
            {"left": 100, "top": 148, "side": "below", "shown": True},
        )

    def test_flips_above_when_below_has_no_room(self):
        """The box is 100px off the area's bottom: the popover goes 8px above it."""
        self.assertEqual(
            self.place([100, 600, 300, 700], [0, 0, 1000, 800]),
            {"left": 100, "top": 452, "side": "above", "shown": True},
        )

    def test_shifts_left_at_the_right_edge_and_never_past_the_left(self):
        """A box near the right edge pulls the popover left to stay 8px inside; a narrow area pins it to the left."""
        self.assertEqual(self.place([900, 100, 980, 140], [0, 0, 1000, 800])["left"], 672)
        self.assertEqual(self.place([900, 100, 980, 140], [200, 0, 400, 800])["left"], 208)

    def test_no_room_either_side_stays_inside_the_area_below(self):
        """A box taller than the area leaves no room above or below: the popover keeps inside the area, at its foot."""
        got = self.place([100, 20, 300, 790], [0, 0, 1000, 800])
        self.assertEqual((got["top"], got["side"]), (652, "below"))

    def test_a_box_off_the_area_hides_the_popover(self):
        """Scrolled off the free area (above it or below it), the box has no popover to anchor."""
        self.assertFalse(self.place([100, -200, 300, -10], [0, 50, 1000, 800])["shown"])
        self.assertFalse(self.place([100, 810, 300, 900], [0, 0, 1000, 800])["shown"])


class SelectionPopover(BrowserBase):
    """The popover in the real viewer: shown for a mouse drag on desktop and mid, one note with the composer, the existing
    save path, the panel for the rest, and its place at the edges."""

    WHO = ALICE

    @staticmethod
    def on_page(page, fx, fy, n=1):
        """The viewport point at fractions (fx, fy) of page n's box."""
        b = page.locator("#p%d" % n).bounding_box()
        return b["x"] + b["width"] * fx, b["y"] + b["height"] * fy

    def drag_on(self, page, fx0, fy0, fx1, fy1):
        """A mouse drag on page 1 between page fractions through the real pick path; waits for the resolved pick."""
        x0, y0 = self.on_page(page, fx0, fy0)
        x1, y1 = self.on_page(page, fx1, fy1)
        page.mouse.move(x0, y0)
        page.mouse.down()
        page.mouse.move(x1, y1, steps=5)
        page.mouse.up()
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo&&!COMPOSE.picking", timeout=8000)
        settle(page)
        return page.evaluate(GEOMETRY)

    def test_a_mouse_drag_opens_the_popover_under_the_box_with_the_location_and_the_focus(self):
        """Desktop: the popover sits 8px under the box with its left edge, reads the location, and takes the focus."""
        page = self.open(0, **DESK)
        g = self.drag_on(page, 0.3, 0.1, 0.6, 0.14)
        self.assertIsNotNone(g["pop"], "no popover")
        self.assertEqual(g["side"], "below")
        self.assertAlmostEqual(g["pop"]["top"], g["box"]["bottom"] + 8, delta=1)
        self.assertAlmostEqual(g["pop"]["left"], g["box"]["left"], delta=1)
        self.assertEqual(g["loc"], "main.tex " + page.evaluate("rng(COMPOSE.current.lo,COMPOSE.current.hi)"))
        self.assertEqual(page.evaluate("document.activeElement.closest('#sel-pop')!==null"), True)

    def test_the_note_is_one_value_with_the_composer_both_ways(self):
        """Typing in the popover writes the composer's note (and its draft); typing in the composer shows in the popover."""
        page = self.open(0, **DESK)
        self.drag_on(page, 0.3, 0.1, 0.6, 0.14)
        page.keyboard.type("문장을 나눠 주세요")
        self.assertEqual(page.evaluate(GEOMETRY)["note"], "문장을 나눠 주세요")
        page.locator("#note").fill("다르게 고친 메모")
        g = page.evaluate(GEOMETRY)
        self.assertEqual((g["field"], g["note"]), ("다르게 고친 메모", "다르게 고친 메모"))

    def test_save_in_the_popover_saves_the_pin_with_the_chip_and_its_undo(self):
        """[저장] is [핀 저장]: the pin is stored with the note, the popover goes with the selection, the mark's chip offers
        [되돌리기], and the undo drops the pin and brings the selection and note back."""
        page = self.open(0, **DESK)
        self.drag_on(page, 0.3, 0.1, 0.6, 0.14)
        page.keyboard.type("팝오버에서 저장")
        page.click("#sel-pop [data-act=pop-save]")
        page.wait_for_selector(".mark .nt-chip", timeout=8000)
        settle(page)
        saved = [r for r in records(ps.APP.snapshot_pins()) if r.get("note") == "팝오버에서 저장"]
        self.assertEqual(len(saved), 1)
        self.assertIsNone(page.evaluate(GEOMETRY)["pop"])
        self.assertTrue(page.evaluate(NO_SELECTION))
        page.locator(".mark .nt-chip [data-act=notice-act]").click()
        page.wait_for_function("!!COMPOSE.current", timeout=8000)
        settle(page)
        self.assertEqual(page.evaluate("document.querySelector('#note').value"), "팝오버에서 저장")
        self.assertEqual([r for r in records(ps.APP.snapshot_pins()) if r.get("note") == "팝오버에서 저장"], [])

    def test_ctrl_enter_in_the_popover_saves_like_the_composer(self):
        """Ctrl+Enter in the popover's field is the composer's ⌘/Ctrl+Enter: one pin with the typed note."""
        page = self.open(0, **DESK)
        self.drag_on(page, 0.3, 0.1, 0.6, 0.14)
        page.keyboard.type("단축키로 저장")
        page.keyboard.press("Control+Enter")
        page.wait_for_selector(".mark .nt-chip", timeout=8000)
        self.assertEqual(len([r for r in records(ps.APP.snapshot_pins()) if r.get("note") == "단축키로 저장"]), 1)

    def test_more_hands_over_to_the_composer_in_the_panel(self):
        """[자세히 →] closes the popover and puts the focus in the panel's note, the typed text kept, the selection open."""
        page = self.open(0, **DESK)
        self.drag_on(page, 0.3, 0.1, 0.6, 0.14)
        page.keyboard.type("자세히 볼 메모")
        page.click("#sel-pop [data-act=pop-more]")
        settle(page)
        g = page.evaluate(GEOMETRY)
        self.assertIsNone(g["pop"])
        self.assertEqual((g["focus"], g["note"]), ("note", "자세히 볼 메모"))
        self.assertFalse(page.evaluate(NO_SELECTION))

    def test_esc_cancels_and_a_press_on_the_popover_is_inside_the_box(self):
        """A press on the popover's padding is no click-off (the selection stays); Esc in its field cancels the selection
        as everywhere, with the note's undo."""
        page = self.open(0, **DESK)
        g = self.drag_on(page, 0.3, 0.1, 0.6, 0.14)
        p = g["pop"]
        page.mouse.click(p["left"] + 3, p["bottom"] - 3)
        nothing_follows(page, 500)
        self.assertFalse(page.evaluate(NO_SELECTION))
        self.assertIsNotNone(page.evaluate(GEOMETRY)["pop"])
        page.focus("#sel-pop textarea")
        page.keyboard.type("버릴 메모")
        page.keyboard.press("Escape")
        page.wait_for_function(NO_SELECTION, timeout=5000)
        settle(page)
        self.assertIsNone(page.evaluate(GEOMETRY)["pop"])
        page.locator("#status", has_text="선택 취소됨").wait_for()

    def test_at_the_bottom_it_flips_above_and_at_the_right_it_shifts_left(self):
        """A box near the PDF area's foot gets the popover above it; one at the right edge, a popover moved left to stay
        8px inside the area. Neither covers the box."""
        page = self.open(0, **DESK)
        page.evaluate("document.querySelector('#left').scrollTop=0")
        settle(page)
        area = page.evaluate(GEOMETRY)["area"]
        b = page.locator("#p1").bounding_box()
        fy = (area["bottom"] - 60 - b["y"]) / b["height"]
        g = self.drag_on(page, 0.3, fy, 0.6, fy + 0.02)
        self.assertEqual(g["side"], "above")
        self.assertAlmostEqual(g["pop"]["bottom"], g["box"]["top"] - 8, delta=1)
        self.assertFalse(overlaps(g["pop"], g["box"]))
        page.keyboard.press("Escape")
        settle(page)
        g = self.drag_on(page, 0.9, 0.1, 0.99, 0.13)
        self.assertLessEqual(g["pop"]["right"], min(g["area"]["right"], g["left"]["right"]) - 8 + 0.5)
        self.assertLess(g["pop"]["left"], g["box"]["left"])
        self.assertFalse(overlaps(g["pop"], g["box"]))

    def test_it_never_covers_the_select_bar_or_the_panel_and_its_save_row(self):
        """Mid with a mouse (the panel over the PDF) and desktop with the select mode's bar: the popover stays off the bar,
        the panel and [취소][핀 저장]."""
        page = self.open(0, **MOUSE_MID)
        g = self.drag_on(page, 0.55, 0.1, 0.95, 0.14)
        self.assertIsNotNone(g["pop"])
        for what in ("right", "save"):
            if g[what]:
                self.assertFalse(overlaps(g["pop"], g[what]), what)
        page = self.open(0, **DESK)
        page.evaluate("setSelMode(true)")
        settle(page)
        bar = page.evaluate(GEOMETRY)["bar"]
        self.assertIsNotNone(bar)
        b = page.locator("#p1").bounding_box()
        fy0 = max(0.01, (bar["bottom"] + 4 - b["y"]) / b["height"])  # page 1 starts under the bar's reserve
        fy1 = (page.evaluate(GEOMETRY)["area"]["bottom"] - 20 - b["y"]) / b["height"]
        g = self.drag_on(page, 0.3, fy0, 0.6, fy1)  # no room above or below: it keeps inside the area under the bar
        self.assertIsNotNone(g["pop"])
        self.assertFalse(overlaps(g["pop"], g["bar"]))
        self.assertGreaterEqual(g["pop"]["top"], g["bar"]["bottom"] + 8 - 0.5)

    def test_the_dragged_text_stays_in_the_panel_and_out_of_the_popover(self):
        """A drag with text: the composer's quote line (#185) shows it under the location line while the popover, right
        under the box that holds that text, shows only the location; neither covers the other."""
        self.PICK = {"quote": "Each meter reports hourly load, outdoor temperature and a calendar index."}
        page = self.open(0, **DESK)
        g = self.drag_on(page, 0.3, 0.1, 0.6, 0.14)
        self.assertIsNotNone(g["pop"])
        got = page.evaluate(
            "[document.querySelector('#c-quote').hidden, document.querySelector('#c-quote .q-t').textContent,"
            " document.querySelectorAll('#sel-pop .quote, #sel-pop .q-t').length,"
            " document.querySelector('#sel-pop').textContent.includes('Each meter')]"
        )
        self.assertEqual(got, [False, self.PICK["quote"], 0, False])
        q = page.locator("#c-quote").bounding_box()
        line = {"left": q["x"], "top": q["y"], "right": q["x"] + q["width"], "bottom": q["y"] + q["height"]}
        self.assertFalse(overlaps(g["pop"], line))

    def test_a_touch_pick_keeps_the_composer_alone(self):
        """Phone: the sheet's composer is the place to write; no popover."""
        page = self.open(0, **PHONE)
        page.evaluate("()=>{LAST_PTR='touch'; pick({page:1,x0:10,y0:10,x1:200,y1:60});}")
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking", timeout=8000)
        settle(page)
        self.assertIsNone(page.evaluate(GEOMETRY)["pop"])

    def test_its_edges_and_text_centres_line_up_within_half_a_pixel(self):
        """Light and dark, Korean: the location's ink, the field's box and [자세히]'s ink share the left edge at the padding;
        [저장], the field and Esc share the right edge; each row's text centres agree; the hits are 24px or more."""
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                page = self.open(0, **DESK)
                page.evaluate("t=>setTheme(t)", theme)
                self.drag_on(page, 0.3, 0.1, 0.6, 0.14)
                fonts_ready(page)
                a = page.evaluate(ALIGN)
                left = a["pop"]["left"] + 1 + a["pad"]
                right = a["pop"]["right"] - 1 - a["pad"]
                for what, x in (
                    ("loc", a["loc"]["left"]),
                    ("field", a["field"]["left"]),
                    ("more", a["moreText"]["left"]),
                ):
                    self.assertAlmostEqual(x, left, delta=0.5, msg=what)
                for what, x in (
                    ("kbd", a["kbd"]["right"]),
                    ("field", a["field"]["right"]),
                    ("save", a["save"]["right"]),
                ):
                    self.assertAlmostEqual(x, right, delta=0.5, msg=what)
                c = lambda r: r["top"] + r["height"] / 2  # noqa: E731
                self.assertAlmostEqual(c(a["loc"]), c(a["kbdText"]), delta=0.5)
                self.assertAlmostEqual(c(a["moreText"]), c(a["saveText"]), delta=0.5)
                self.assertAlmostEqual(c(a["more"]), c(a["save"]), delta=0.5)
                for what in ("more", "save"):
                    self.assertGreaterEqual(a[what]["height"], 24, what)

    def test_in_english_its_words_are_english(self):
        """The popover's own words follow the screen language; the location stays as written."""
        page = self.open(0, lang="en", **DESK)
        self.drag_on(page, 0.3, 0.1, 0.6, 0.14)
        texts = page.evaluate(
            "[...document.querySelectorAll('#sel-pop [data-act]')].map(b=>b.textContent.trim())"
            ".concat([document.querySelector('#sel-pop textarea').placeholder])"
        )
        self.assertEqual(texts[:2], ["Details", "Save"])
        self.assertNotRegex(" ".join(texts), "[가-힣]")

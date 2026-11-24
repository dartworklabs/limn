"""A LaTeX line pin's mark is drawn as the pieces of its range (docs/adr/0049-pin-marks-follow-the-range.md).

The server answers such a pin with `boxes` - where its own lines print on the build on screen, already filtered, padded,
merged and measured against each piece's own page, ordered by page and then down the page. The viewer draws one
`.mark[data-pin=N]` per piece. The first piece is the reference for everything else: the number badge is on it alone, and
so are the undo chip, [보기]'s scroll and flash, and the badge's tooltip. A pin the server answers no `boxes` for is drawn
from its stored `frac` on its stored `page`, exactly as before, with nothing on screen to tell the two apart - unless its
mark is an estimate (`est`): then the dragged box is where it was pinned on an older PDF and may lie on other text, so
the line pin is not drawn at all and its card says '과거 위치' (PastLocation, docs/adr/0057-line-boxes-where-the-anchor-stands.md).

The drawing itself is read under node from the served `marks()` (MarkPieces): what it appends to which page, in which
order, with which classes. What only a browser can say - the marks taken off with H, the chip and [보기] finding the
first piece, a badge still opening its card and a drag across a piece still starting a selection - is read in the real
viewer (MarkBoxesOnScreen), whose pin list is given the pieces the fixture's build cannot compute.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_mark_boxes.py
"""

import json
import shutil
import unittest
from urllib.parse import urlparse

from helpers import add_pin, extract_js_fn, js_i18n, js_markup, js_seams_wired, run_node
from helpers_access import ALICE, actor
from helpers_browser import BrowserBase, settle

A = actor(ALICE)
PIN_SEAMS = "pins/state-seams.ts"
DESKTOP = {"viewport": {"width": 1440, "height": 900}}
# First-visit hints off: their line would stand over the pages the marks are read from.
NO_COACH = "try{localStorage.setItem('pinPrefs',JSON.stringify({coach:{touch:1,mouse:1,sel:1,side:1}}))}catch(e){}"
# The fractions these tests place pieces at are halves, quarters and eighths: they and their percentages are exact in
# binary, so the style the viewer writes ('12.5%') is the number the test gave it.
FIRST = [0.125, 0.25, 0.5, 0.0625]
SECOND = [0.125, 0.5, 0.5, 0.0625]

# The marks() harness: the pins' marks land in `drawn` instead of in a page, one entry per appended element.
MARKS_HARNESS = r"""
const DOC='d', DEFAULT_DOC='d', markBadgeSides=()=>{}, drawChips=()=>{}; let PINS=[], REVIEW_ALL=[]; const drawn=[];
const movingPin=()=>null;   // no badge is under a hand here (pdf/input-selection.ts)
const drawPageVerdicts=()=>{}, isShownOnLine=()=>false;   // no page verdict line on this document (verdict/flow-line.ts)
const isMarkdownDoc=()=>false;   // and it has pages (documents/state.ts)
const $$=()=>[]; const esc=s=>String(s);
const pages={};
for (const id of %s) pages[id] = {appendChild: m => drawn.push({page: id, pin: m.dataset.pin, fx: m.dataset.fx,
  cls: m.className, box: [m.style.left, m.style.top, m.style.width, m.style.height], badge: m.html || ''})};
const document={getElementById:id=>pages[id]||null,
  createElement:()=>({dataset:{},style:{},className:'',set innerHTML(v){this.html=v}})};"""


class MarkPieces(unittest.TestCase):
    """What the served marks() appends for pins with and without pieces, run under node."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def draw(self, pins, pages=("p1", "p2")):
        """What marks() draws for pins with those pages on screen, in the order it appends them."""
        js = "\n".join(
            [
                MARKS_HARNESS % json.dumps(list(pages)),
                js_markup(),
                js_i18n(),
                js_seams_wired(PIN_SEAMS),  # the pin list's seams, wired as js/main.ts does
                *[
                    extract_js_fn(name)
                    for name in (
                        "isFrac",
                        "hasMark",
                        "pinPlace",
                        "isPiece",
                        "pinPieces",
                        "pastPlace",
                        "isElementLost",
                        "isEstimated",
                        "pinState",
                        "pdoc",
                        "marks",
                    )
                ],
                "PINS=%s; marks(); console.log(JSON.stringify(drawn));" % json.dumps(pins),
            ]
        )
        return json.loads(run_node(js))

    def lines_pin(self, **more):
        """An open LaTeX line pin on page 1, dragged over a box of its own."""
        return {"id": 1, "file": "main.tex", "page": 1, "lo": 4, "hi": 6, "frac": [0.25, 0.75, 0.5, 0.0625], **more}

    def test_a_pin_with_two_boxes_draws_two_marks(self):
        """Both pieces are drawn as marks of the same pin, each at its own box - not one box around the two."""
        drawn = self.draw([self.lines_pin(boxes=[{"page": 1, "frac": FIRST}, {"page": 1, "frac": SECOND}])])
        self.assertEqual([mark["pin"] for mark in drawn], ["1", "1"])
        self.assertEqual(
            [mark["box"] for mark in drawn],
            [["12.5%", "25%", "50%", "6.25%"], ["12.5%", "50%", "50%", "6.25%"]],
        )
        self.assertEqual([mark["fx"] for mark in drawn], ["0.125", "0.125"])

    def test_only_the_first_box_carries_the_badge(self):
        """One badge for the pin, on its first piece: its number, its label and its press action."""
        drawn = self.draw([self.lines_pin(boxes=[{"page": 1, "frac": FIRST}, {"page": 1, "frac": SECOND}])])
        self.assertEqual([bool(mark["badge"]) for mark in drawn], [True, False])
        self.assertIn('data-act="mark-jump"', drawn[0]["badge"])
        self.assertIn('data-id="1"', drawn[0]["badge"])

    def test_a_pin_without_boxes_still_draws_its_frac(self):
        """No boxes from the server (an absent field, never an empty one): the pin is drawn where it was dragged, on
        the page it was dragged on, with its badge - what it drew before any of this."""
        drawn = self.draw([self.lines_pin()])
        self.assertEqual(len(drawn), 1)
        self.assertEqual(
            (drawn[0]["page"], drawn[0]["cls"], drawn[0]["box"]),
            ("p1", "mark", ["25%", "75%", "50%", "6.25%"]),
        )
        self.assertTrue(drawn[0]["badge"])

    def test_boxes_on_another_page_draw_on_that_page(self):
        """A range that runs over a page break: each piece is appended to the page it names, and a piece on a page that
        is not on screen draws nothing (Review Focus 1)."""
        drawn = self.draw(
            [
                self.lines_pin(
                    boxes=[
                        {"page": 1, "frac": SECOND},
                        {"page": 2, "frac": FIRST},
                        {"page": 9, "frac": FIRST},
                    ]
                )
            ]
        )
        self.assertEqual([(mark["page"], mark["box"][1]) for mark in drawn], [("p1", "50%"), ("p2", "25%")])

    def test_the_pieces_stand_in_the_order_the_server_gave_them_and_the_badge_on_the_first(self):
        """The server orders the pieces by page and then down the page, so the first is the topmost block of the lowest
        page: the marks are appended in that order and that piece - not merely one of them - carries the badge."""
        drawn = self.draw(
            [
                self.lines_pin(
                    boxes=[
                        {"page": 1, "frac": [0.125, 0.75, 0.5, 0.0625]},
                        {"page": 2, "frac": [0.125, 0.125, 0.5, 0.0625]},
                        {"page": 2, "frac": [0.125, 0.5, 0.5, 0.0625]},
                    ]
                )
            ]
        )
        self.assertEqual(
            [(mark["page"], mark["box"][1], bool(mark["badge"])) for mark in drawn],
            [("p1", "75%", True), ("p2", "12.5%", False), ("p2", "50%", False)],
        )

    def test_an_estimated_pin_with_boxes_keeps_its_dotted_outline(self):
        """The dotted outline says a rebuild may have moved the pin, which is a different fact from the range still
        standing: every piece of an estimated pin is dotted."""
        drawn = self.draw([self.lines_pin(est=True, boxes=[{"page": 1, "frac": FIRST}, {"page": 1, "frac": SECOND}])])
        self.assertEqual([mark["cls"] for mark in drawn], ["mark est", "mark est"])

    def test_a_line_pin_without_boxes_on_another_build_is_not_drawn(self):
        """No boxes and an estimate: the box it was dragged on is where it was pinned on an older PDF, which may now be
        other text, so neither an awaiting-review pin nor a lost open pin is drawn - and the pin beside them still is."""
        drawn = self.draw(
            [
                self.lines_pin(id=1, est=True, done=True, review=True),
                self.lines_pin(id=2, est=True, stale=True, sync="lost"),
                self.lines_pin(id=3, est=True, boxes=[{"page": 1, "frac": FIRST}]),
            ]
        )
        self.assertEqual([(mark["pin"], mark["cls"]) for mark in drawn], [("3", "mark est")])

    def test_a_line_pin_without_boxes_on_its_own_build_draws_where_it_was_dragged(self):
        """No boxes but no estimate either: the PDF on screen is the one the pin was dragged on, so the dragged box is
        where its text prints there - an awaiting-review pin whose stored lines no longer hold its text included."""
        drawn = self.draw([self.lines_pin(est=False, done=True, review=True)])
        self.assertEqual([(mark["cls"], mark["box"]) for mark in drawn], [("mark rv", ["25%", "75%", "50%", "6.25%"])])

    def test_a_region_or_figure_pin_without_boxes_is_still_drawn_as_an_estimate(self):
        """A region pin has no line range and a figure pin's mark comes from its element: neither is a line pin whose
        lines could not be placed, so an estimated one keeps its dotted box where it was pinned."""
        drawn = self.draw(
            [
                {"id": 4, "page": 1, "frac": [0.25, 0.75, 0.5, 0.0625], "pdf": "/ms/review.pdf", "est": True},
                {**self.lines_pin(id=5, est=True), "el": {"id": "cell", "path": ["cell"]}},
            ]
        )
        self.assertEqual([(mark["pin"], mark["cls"]) for mark in drawn], [("4", "mark est"), ("5", "mark est")])

    def test_a_figure_pin_is_drawn_from_its_element_mark_alone(self):
        """A figure pin carries mark/mark_page and no boxes: it is drawn as one mark where the server found its element,
        and a found element is no estimate."""
        drawn = self.draw(
            [
                {
                    "id": 2,
                    "page": 1,
                    "frac": [0.25, 0.75, 0.5, 0.0625],
                    "est": True,
                    "mark": [0.125, 0.25, 0.5, 0.0625],
                    "mark_page": 2,
                    "el_sync": "moved",
                }
            ]
        )
        self.assertEqual(len(drawn), 1)
        self.assertEqual(
            (drawn[0]["page"], drawn[0]["cls"], drawn[0]["box"]),
            ("p2", "mark", ["12.5%", "25%", "50%", "6.25%"]),
        )

    def test_a_piece_the_server_could_not_answer_well_is_left_out(self):
        """A piece that is no object at all, one whose box is not four finite numbers and one whose page is no page of a
        build each draw nothing; the good piece beside them is drawn, and so is the next pin's mark.

        The last of those is the one that matters: the draw removes every mark on the document before it builds them
        again, so a malformed row that threw out of the loop would leave the whole document without marks - and without
        the badge sides and undo chips that are placed after it - not merely without its own.
        """
        drawn = self.draw(
            [
                self.lines_pin(
                    boxes=[
                        None,
                        {"page": 1, "frac": None},
                        {"page": 1, "frac": [0.125, "x", 0.5, 0.0625]},
                        {"page": 0, "frac": FIRST},
                        {"page": 1, "frac": [0.125, 0.25, 0.5]},
                        {"page": 1, "frac": SECOND},
                    ]
                ),
                self.lines_pin(id=2),
            ]
        )
        self.assertEqual(
            [(mark["pin"], mark["page"], mark["box"][1], bool(mark["badge"])) for mark in drawn],
            [("1", "p1", "50%", True), ("2", "p1", "75%", True)],
        )


class MarkBoxesOnScreen(BrowserBase):
    """Two open pins of the manuscript in the real viewer, one of them answered with two pieces.

    The fixture's build has page images but no PDF to measure a range against, so the server answers no `boxes` for
    either pin: this class stands in for that answer, adding the pieces to the pin list on its way to the browser, by
    the note each pin was saved with.
    """

    BOXES: dict = {}

    def setUp(self):
        """One pin whose range prints as two pieces - page 1 then page 2 - and one the server answers no pieces for."""
        super().setUp()
        body = {"file": str(self.main), "page": 1}
        self.piecewise = add_pin(
            {**body, "lo": 4, "hi": 5, "note": "두 조각", "frac": [0.25, 0.75, 0.25, 0.0625]}, A
        ).record["id"]
        self.whole = add_pin(
            {**body, "lo": 8, "hi": 9, "note": "한 조각", "frac": [0.625, 0.75, 0.25, 0.0625]}, A
        ).record["id"]
        self.BOXES = {"두 조각": [{"page": 1, "frac": FIRST}, {"page": 2, "frac": [0.125, 0.125, 0.5, 0.0625]}]}

    def route(self, route):
        """The fixture's routes, with the pin list given the pieces this class stands in for."""
        request = route.request
        if urlparse(request.url).path == "/api/pins":
            answer = self.answer(request)
            rows = json.loads(answer["body"])
            for row in rows:
                pieces = self.BOXES.get(row.get("note"))
                if pieces:
                    row["boxes"] = pieces
            answer["body"] = json.dumps(rows)
            return route.fulfill(**answer)
        return super().route(route)

    def view(self, n_marks=3):
        """The viewer with every mark drawn."""
        page = self.open(2, init=NO_COACH, **DESKTOP)
        page.wait_for_function("n=>document.querySelectorAll('.mark').length===n", arg=n_marks, timeout=8000)
        settle(page)
        return page

    def marks_of(self, page, pin):
        """Each mark of that pin, in document order: its page, whether it is drawn, and whether it has a badge."""
        return page.evaluate(
            """id => [...document.querySelectorAll('.mark[data-pin="' + id + '"]')].map(m => ({
                 page: m.parentElement.id, shown: getComputedStyle(m).visibility === 'visible',
                 badge: !!m.querySelector('button.mark-jump')}))""",
            pin,
        )

    def test_a_pin_with_two_pieces_is_drawn_on_both_its_pages_with_one_badge(self):
        """The pieces stand on the pages they name, the badge on the first alone; the pin beside them, which the server
        answered no pieces for, is one mark on the page it was pinned on."""
        page = self.view()
        self.assertEqual(
            [(mark["page"], mark["badge"]) for mark in self.marks_of(page, self.piecewise)],
            [("p1", True), ("p2", False)],
        )
        self.assertEqual([(mark["page"], mark["badge"]) for mark in self.marks_of(page, self.whole)], [("p1", True)])

    def test_hiding_the_marks_hides_every_piece(self):
        """H takes every piece off, not only the one with the badge; H again brings them all back."""
        page = self.view()
        page.keyboard.press("h")
        settle(page)
        self.assertEqual([mark["shown"] for mark in self.marks_of(page, self.piecewise)], [False, False])
        self.assertEqual(page.locator('.mark[data-pin="%d"]:visible' % self.piecewise).count(), 0)
        page.keyboard.press("h")
        settle(page)
        self.assertEqual([mark["shown"] for mark in self.marks_of(page, self.piecewise)], [True, True])

    def test_view_scrolls_to_the_first_piece_and_flashes_it(self):
        """[보기] from the far end of the document goes to the pin's first piece: that piece is brought into the pages'
        view and flashes, and the piece on the next page does not flash."""
        page = self.view()
        page.evaluate("()=>{const pane=document.querySelector('#left'); pane.scrollTop=pane.scrollHeight;}")
        settle(page)
        page.evaluate("id=>jumpPin(id)", self.piecewise)
        settle(page)
        self.assertEqual(
            page.evaluate(
                """id => [...document.querySelectorAll('.mark[data-pin="' + id + '"]')]
                     .map(m => m.classList.contains('flash'))""",
                self.piecewise,
            ),
            [True, False],
        )
        self.assertTrue(
            page.evaluate(
                """id => {const m = document.querySelector('.mark[data-pin="' + id + '"]').getBoundingClientRect(),
                     view = document.querySelector('#left').getBoundingClientRect();
                   return m.top >= view.top && m.bottom <= view.bottom;}""",
                self.piecewise,
            )
        )

    def test_a_saves_undo_chip_sits_on_the_first_piece(self):
        """A pin saved with pieces gets its undo chip on its first piece, where the person was looking, and not on the
        piece below it."""
        page = self.view()
        self.BOXES["새 핀"] = [{"page": 1, "frac": FIRST}, {"page": 1, "frac": SECOND}]
        box = page.evaluate(
            "(()=>{const r=document.getElementById('p1').getBoundingClientRect();return [r.left,r.top,r.width,r.height];})()"
        )
        x, y = box[0] + box[2] * 0.25, box[1] + box[3] * 0.75
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + box[2] * 0.3, y + box[3] * 0.05, steps=6)
        page.mouse.up()
        page.wait_for_function("!!COMPOSE.current", timeout=8000)
        page.locator("#note").fill("새 핀")
        page.click("#btn-save")
        page.wait_for_function("OPEN_ALL.some(p=>p.note==='새 핀')", timeout=8000)
        settle(page)
        saved = page.evaluate("OPEN_ALL.find(p=>p.note==='새 핀').id")
        self.assertEqual([mark["badge"] for mark in self.marks_of(page, saved)], [True, False])
        self.assertEqual(
            page.evaluate(
                """id => [...document.querySelectorAll('.mark[data-pin="' + id + '"]')]
                     .map(m => !!m.querySelector(':scope > .nt-chip'))""",
                saved,
            ),
            [True, False],
        )

    def test_a_badge_opens_its_card_and_a_drag_over_a_piece_still_starts_a_selection(self):
        """Pressing the badge scrolls to that pin's card and marks it current; a drag that crosses a piece without a
        badge is a new selection, since every piece ignores the pointer."""
        page = self.view()
        page.click('.mark[data-pin="%d"] button.mark-jump' % self.piecewise)
        page.wait_for_selector('.pin[data-id="%d"].cur' % self.piecewise, timeout=8000)
        settle(page)
        self.assertEqual(
            page.evaluate(
                """id => [...document.querySelectorAll('.mark[data-pin="' + id + '"]')]
                     .map(m => getComputedStyle(m).pointerEvents)""",
                self.piecewise,
            ),
            ["none", "none"],
        )
        page.evaluate(
            """id => document.querySelectorAll('.mark[data-pin="' + id + '"]')[1]
                 .scrollIntoView({block: 'center'})""",
            self.piecewise,
        )
        settle(page)
        piece = page.evaluate(
            """id => {const m = document.querySelectorAll('.mark[data-pin="' + id + '"]')[1],
                   r = m.getBoundingClientRect();
               return {box: [r.left, r.top, r.width, r.height], badge: !!m.querySelector('button.mark-jump')};}""",
            self.piecewise,
        )
        self.assertFalse(piece["badge"])  # the piece the drag crosses has no badge to swallow the press
        left, top, width, height = piece["box"]
        page.mouse.move(left + 2, top + height / 2)
        page.mouse.down()
        page.mouse.move(left + width - 2, top + height / 2, steps=6)
        page.mouse.up()
        page.wait_for_function("!!COMPOSE.current", timeout=8000)
        self.assertFalse(page.evaluate("document.querySelector('#composer').hidden"))

    def test_hovering_a_card_highlights_every_piece_of_its_mark(self):
        """A card's mark is all of its pieces: pointing at the card thickens each of them, and leaving it takes the
        highlight off each."""
        page = self.view()
        highlighted = """id => [...document.querySelectorAll('.mark[data-pin="' + id + '"]')]
             .map(m => m.classList.contains('hi'))"""
        page.hover('.pin[data-id="%d"]' % self.piecewise)
        self.assertEqual(page.evaluate(highlighted, self.piecewise), [True, True])
        page.mouse.move(4, 4)  # off the card, onto the window's corner
        self.assertEqual(page.evaluate(highlighted, self.piecewise), [False, False])


class PastLocationOnScreen(BrowserBase):
    """Line pins the server answers no `boxes` for, in the real viewer: an estimated one is not drawn on the page and its
    card says '과거 위치'; a lost one says '위치 잃음' alone; one on the build it was dragged on is drawn as before.

    The fixture's build answers no pieces for any pin, so this class sets each row's `est` (and `stale`) on the pin list's
    way to the browser, by the note it was saved with - the server's answer for a pin whose lines no longer hold it."""

    ROWS = {"과거": {"est": True}, "잃음": {"est": True, "stale": True, "sync": "lost"}, "제자리": {"est": False}}

    def setUp(self):
        """Three open line pins on page 1, one per row of ROWS."""
        super().setUp()
        body = {"file": str(self.main), "page": 1, "frac": [0.25, 0.75, 0.25, 0.0625]}
        self.ids = {
            note: add_pin({**body, "lo": lo, "hi": lo, "note": note}, A).record["id"]
            for note, lo in (("과거", 4), ("잃음", 8), ("제자리", 9))
        }

    def route(self, route):
        """The fixture's routes, with the pin list's rows given ROWS' fields."""
        request = route.request
        if urlparse(request.url).path == "/api/pins":
            answer = self.answer(request)
            rows = json.loads(answer["body"])
            for row in rows:
                row.update(self.ROWS.get(row.get("note"), {}))
                row.pop("boxes", None)
            answer["body"] = json.dumps(rows)
            return route.fulfill(**answer)
        return super().route(route)

    def test_an_estimated_pin_without_boxes_is_off_the_page_and_its_card_says_so(self):
        """The page draws the pin on its own build alone; the estimated pin's card carries '과거 위치' with a description,
        and the lost pin's card keeps '위치 잃음' without a second badge."""
        page = self.open(3, init=NO_COACH, **DESKTOP)
        page.wait_for_function("document.querySelectorAll('.mark').length===1", timeout=8000)
        settle(page)
        drawn = page.evaluate("[...document.querySelectorAll('.mark')].map(m => Number(m.dataset.pin))")
        self.assertEqual(drawn, [self.ids["제자리"]])
        badges = page.evaluate(
            """ids => Object.fromEntries(Object.entries(ids).map(([note, id]) => [note,
                 [...document.querySelectorAll('.pin[data-id="' + id + '"] .tags .badge')].map(b => ({
                   text: b.firstChild ? b.textContent.trim() : '', tip: b.getAttribute('data-tip') || ''}))]))""",
            self.ids,
        )
        past = [b for b in badges["과거"] if b["text"].startswith("과거 위치")]
        self.assertEqual(len(past), 1)
        self.assertIn("쪽 위에 표시하지 않습니다", past[0]["tip"])
        self.assertEqual([b["text"][:5] for b in badges["잃음"]], ["위치 잃음"])
        self.assertFalse([b for b in badges["제자리"] if b["text"].startswith("과거 위치")])

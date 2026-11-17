"""The selection being composed is drawn over the lines it covers, not the rectangle that was dragged.

A drag's pick answers where its default rung's lines print (`boxes`, docs/adr/0045-pin-marks-follow-the-range.md), and
the dashed '새 핀' box is drawn on those pieces - one box per piece, each on the page its piece names, the first piece
keeping everything that is the selection's one place: the note popover's anchor and the identity a click-off compares.
Moving up the range ladder or setting the lines in the range excerpt asks GET /api/snippet?levels=1 for the pieces of
the range now chosen and redraws from them. A range the server answers no pieces for leaves the dragged rectangle
exactly as it was.

The drawing itself is read under node from the served snapSelectionBox and rangeBoxes (SelectionPieces): what they put
on which page, in which order, and what they leave alone. What only a browser can say - the box following the ladder and
the excerpt, a press on a second piece not cancelling the selection, the popover by the first piece - is read in the
real viewer (SelectionBoxesOnScreen), whose pick and snippet answers carry the pieces the fixture's build cannot
compute.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_selection_boxes.py
"""

import json
import shutil
import unittest
from urllib.parse import parse_qs, urlparse

from helpers import extract_js_fn, run_node
from helpers_browser import BrowserBase, settle

DESKTOP = {"viewport": {"width": 1440, "height": 900}}
# First-visit hints off: their line would stand over the pages the boxes are read from.
NO_COACH = "try{localStorage.setItem('pinPrefs',JSON.stringify({coach:{touch:1,mouse:1,sel:1,side:1}}))}catch(e){}"
# The fractions these tests place pieces at are halves, quarters and eighths: they and their percentages are exact in
# binary, so the style the viewer writes ('12.5%') is the number the test gave it.
FIRST = [0.125, 0.25, 0.5, 0.0625]
SECOND = [0.125, 0.5, 0.5, 0.0625]
# What BrowserBase's pick answers as the dragged rectangle, and the style that rectangle is drawn with.
DRAGGED = [0.1, 0.1, 0.3, 0.05]
DRAGGED_STYLE = ["10%", "10%", "30%", "5%"]

# The snapSelectionBox harness: the pages are stand-ins that collect what is appended to them, and every element made
# is kept so the parts of a selection can be found again (document.querySelectorAll).
SNAP_HARNESS = r"""
const MADE = [];
function markBadgeRoom(){ return null; }   // no page width on a stand-in page: the badge keeps the side it has
function element(cls, id) {
  const el = {dataset: {}, style: {}, className: cls, id: id || '', parentElement: null, kids: [], gone: false,
    classList: {toggle(){}, add(){}, remove(){}},
    remove() { const owner = el.parentElement;
      if (owner) owner.kids.splice(owner.kids.indexOf(el), 1);
      el.parentElement = null; el.gone = true; },
    appendChild(kid) { if (kid.parentElement) kid.remove();
      kid.parentElement = el; kid.gone = false; el.kids.push(kid); return kid; },
    querySelectorAll() { return []; }};
  MADE.push(el);
  return el;
}
const pages = {};
for (const id of %s) pages[id] = element('pg', id);
const document = {
  getElementById: id => pages[id] || null,
  createElement: () => element(''),
  querySelectorAll: sel => MADE.filter(el => !el.gone && ('.' + el.className.split(' ').join('.')).includes(sel)),
};
function drawn() {
  return MADE.filter(el => !el.gone && el.parentElement && el.className.indexOf('sel') === 0)
    .map(el => ({page: el.parentElement.id, cls: el.className, snap: el.dataset.snap || '',
      box: [el.style.left, el.style.top, el.style.width, el.style.height]}));
}"""


class SelectionPieces(unittest.TestCase):
    """What the served snapSelectionBox draws for a selection with and without pieces, and what rangeBoxes reads."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def snap(self, calls, pages=("p1", "p2")):
        """The boxes on the pages after snapSelectionBox has been called once per entry of calls, each
        {pieces, dragged}: the page each stands on, its classes and its inline box, in the order they were appended."""
        js = "\n".join(
            [
                SNAP_HARNESS % json.dumps(list(pages)),
                *[
                    extract_js_fn(name)
                    for name in (
                        "drawBox",
                        "boxOnFrac",
                        "boxOnPage",
                        "pendingBadgeSide",
                        "newSelectionPart",
                        "selectionParts",
                        "clearSelectionParts",
                        "snapSelectionBox",
                    )
                ],
                "const box = element('sel pending');",
                "pages['p1'].appendChild(box);",
                "box.style.left='10%'; box.style.top='10%'; box.style.width='30%'; box.style.height='5%';",
                "for (const call of %s) snapSelectionBox(box, call.pieces, call.dragged);" % json.dumps(calls),
                "console.log(JSON.stringify(drawn()));",
            ]
        )
        return json.loads(run_node(js))

    def dragged(self):
        """The drag this harness starts from: the rectangle on page 1 BrowserBase's pick answers."""
        return {"page": 1, "frac": DRAGGED}

    def test_a_range_of_two_pieces_draws_two_boxes(self):
        """Both pieces are drawn, each at its own box - not one box around the two - and the selection's own box is the
        first of them, so what anchors to it anchors to the piece the person's eye is on."""
        drawn = self.snap([{"pieces": [{"page": 1, "frac": FIRST}, {"page": 1, "frac": SECOND}], "dragged": None}])
        self.assertEqual(
            [piece["box"] for piece in drawn],
            [["12.5%", "25%", "50%", "6.25%"], ["12.5%", "50%", "50%", "6.25%"]],
        )
        self.assertEqual([piece["page"] for piece in drawn], ["p1", "p1"])

    def test_pieces_on_another_page_draw_on_that_page(self):
        """A range that runs over a page break: each piece is appended to the page it names, and a piece on a page that
        is not drawn gets nothing."""
        drawn = self.snap(
            [
                {
                    "pieces": [
                        {"page": 2, "frac": FIRST},
                        {"page": 1, "frac": SECOND},
                        {"page": 9, "frac": FIRST},
                    ],
                    "dragged": None,
                }
            ]
        )
        self.assertEqual([(piece["page"], piece["box"][1]) for piece in drawn], [("p2", "25%"), ("p1", "50%")])

    def test_a_range_with_no_pieces_leaves_the_dragged_rectangle(self):
        """Nothing was answered for these lines: the box keeps the rectangle the person dragged, and no second box is
        made - what the selection drew before marks followed the range."""
        drawn = self.snap([{"pieces": [], "dragged": self.dragged()}])
        self.assertEqual(len(drawn), 1)
        self.assertEqual((drawn[0]["page"], drawn[0]["cls"], drawn[0]["box"]), ("p1", "sel pending", DRAGGED_STYLE))

    def test_moving_to_a_range_with_no_pieces_puts_the_drag_back(self):
        """Up the ladder to a range the server answered pieces for, then to one it answered none for: the box goes back
        to the dragged rectangle on the page it was dragged on, and the piece beside it is taken off - a box left
        standing would say the pin covers lines it does not."""
        drawn = self.snap(
            [
                {"pieces": [{"page": 2, "frac": FIRST}, {"page": 2, "frac": SECOND}], "dragged": self.dragged()},
                {"pieces": [], "dragged": self.dragged()},
            ]
        )
        self.assertEqual(len(drawn), 1)
        self.assertEqual((drawn[0]["page"], drawn[0]["box"]), ("p1", DRAGGED_STYLE))

    def test_a_narrower_range_leaves_no_box_from_the_wider_one(self):
        """Up the ladder and back down: the boxes of the wider range are gone and only the narrower range's piece
        stands, so the box says the lines that will be saved."""
        drawn = self.snap(
            [
                {"pieces": [{"page": 1, "frac": FIRST}, {"page": 2, "frac": SECOND}], "dragged": self.dragged()},
                {"pieces": [{"page": 1, "frac": FIRST}], "dragged": self.dragged()},
            ]
        )
        self.assertEqual(len(drawn), 1)
        self.assertEqual((drawn[0]["page"], drawn[0]["box"]), ("p1", ["12.5%", "25%", "50%", "6.25%"]))

    def test_a_selection_that_never_left_the_drag_is_not_redrawn(self):
        """A range with no pieces does not touch a box that was never put on a piece: the element, its classes and the
        geometry the drag wrote stay exactly as they were, also when there is no answer about the drag itself."""
        drawn = self.snap([{"pieces": [], "dragged": None}])
        self.assertEqual(len(drawn), 1)
        self.assertEqual((drawn[0]["cls"], drawn[0]["box"], drawn[0]["snap"]), ("sel pending", DRAGGED_STYLE, ""))

    def test_a_piece_the_server_could_not_answer_well_is_left_out(self):
        """rangeBoxes drops a piece that is no object at all, one whose box is not four finite numbers and one whose
        page is no page of a build, and keeps the rest: one malformed row must not take the whole selection's box with
        it, as it must not take a saved pin's mark."""
        js = "\n".join(
            [
                "const RANGE_BOXES = new WeakMap();",
                *[extract_js_fn(name) for name in ("isFrac", "isPiece", "rangeKey", "boxedRung", "rangeBoxes")],
                "const owner = {lo: 4, hi: 6, levels: [{level: 'para', lo: 4, hi: 6, boxes: %s}]};"
                % json.dumps(
                    [
                        None,
                        {"page": 1, "frac": None},
                        {"page": 1, "frac": [0.125, "x", 0.5, 0.0625]},
                        {"page": 0, "frac": FIRST},
                        {"page": 1, "frac": [0.125, 0.25, 0.5]},
                        {"page": 1, "frac": SECOND},
                    ]
                ),
                "console.log(JSON.stringify(rangeBoxes(owner)));",
            ]
        )
        self.assertEqual(json.loads(run_node(js)), [{"page": 1, "frac": SECOND}])

    def test_the_pieces_are_read_from_the_rung_that_covers_the_chosen_lines(self):
        """The answer read is the one for the lines the selection now has: the rung whose range is those lines. A rung
        the person has moved away from is not what the box shows, and lines no rung covers have no answer at all - not
        an answer of no pieces, which would mean something quite different (null here, undefined in the browser)."""
        js = "\n".join(
            [
                "const RANGE_BOXES = new WeakMap();",
                *[extract_js_fn(name) for name in ("isFrac", "isPiece", "rangeKey", "boxedRung", "rangeBoxes")],
                "const levels = [{level: 'raw', lo: 5, hi: 5, boxes: [{page: 1, frac: %s}]},"
                " {level: 'para', lo: 3, hi: 8, boxes: [{page: 2, frac: %s}]}];"
                % (json.dumps(FIRST), json.dumps(SECOND)),
                "console.log(JSON.stringify([rangeBoxes({lo: 5, hi: 5, levels}), rangeBoxes({lo: 3, hi: 8, levels}),"
                " rangeBoxes({lo: 2, hi: 9, levels})]));",
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)),
            [[{"page": 1, "frac": FIRST}], [{"page": 2, "frac": SECOND}], None],
        )

    def test_one_answer_is_held_for_every_rung_of_the_ladder_it_carries(self):
        """A snippet answers the whole ladder round the range it was asked about, and every rung of it is held under
        its own lines - so a rung moved to next is already answered. The range asked about is held even when the answer
        carries no ladder at all, or lines with no mark would be asked about again on every redraw."""
        js = "\n".join(
            [
                "const RANGE_BOXES = new WeakMap();",
                *[
                    extract_js_fn(name)
                    for name in ("isFrac", "isPiece", "rangeKey", "boxedRung", "rangeBoxes", "takeRangeBoxes")
                ],
                "const owner = {lo: 3, hi: 9, levels: []};",
                "takeRangeBoxes(owner, {lo: 3, hi: 9, levels: [{lo: 3, hi: 9, boxes: [{page: 1, frac: %s}]},"
                " {lo: 1, hi: 40, boxes: [{page: 2, frac: %s}]}, {lo: 5, hi: 5}]});"
                % (json.dumps(FIRST), json.dumps(SECOND)),
                # the owner is the selection itself, moving from rung to rung; its answers are held under it
                "const read = (lo, hi) => {owner.lo = lo; owner.hi = hi; return rangeBoxes(owner);};",
                "const bare = {lo: 2, hi: 2, levels: []}; takeRangeBoxes(bare, {lo: 2, hi: 2});",
                "console.log(JSON.stringify([read(3, 9), read(1, 40), read(5, 5), read(4, 4),"
                " rangeBoxes({lo: 3, hi: 9, levels: []}), rangeBoxes(bare)]));",
            ]
        )
        asked, outer, without, unasked, other, ladderless = json.loads(run_node(js))
        self.assertEqual(asked, [{"page": 1, "frac": FIRST}])
        self.assertEqual(outer, [{"page": 2, "frac": SECOND}])  # the rung beside it, held by the same answer
        self.assertEqual(without, [])  # a rung the server found no mark for: answered, and answered nothing
        self.assertIsNone(unasked)  # lines the answer said nothing about
        self.assertIsNone(other)  # the same lines under another owner: one selection's answers are not another's
        self.assertEqual(ladderless, [])  # asked about, answered without a ladder: still answered


# The ladder the pick answers: a dragged line, the paragraph it is in (the default) and the environment around it. The
# fixture's build has page images but no PDF to measure a range against, so the server answers no pieces for any of
# them; this class stands in for that answer by the range each rung covers.
LEVELS = [
    {
        "level": "raw",
        "lo": 5,
        "hi": 5,
        "n": 1,
        "label": "드래그한 줄",
        "snippet": "    5  Line 5 of the demo manuscript.",
    },
    {"level": "para", "lo": 4, "hi": 6, "n": 3, "label": "문단", "snippet": "    4  Line 4 of the demo manuscript."},
    {"level": "env", "lo": 3, "hi": 9, "n": 7, "label": "환경 figure", "env": "figure", "snippet": "    3  Line 3."},
    # The whole file, which is also the paragraph rung of every ladder the fixture's server builds (its manuscript has
    # no blank line), so one answer about any range holds this one too.
    {
        "level": "env2",
        "lo": 1,
        "hi": 40,
        "n": 40,
        "label": "환경 figure (바깥)",
        "env": "figure",
        "snippet": "    1  x",
    },
]
# What each range prints as, by its lines: the paragraph one piece, the environment two and a taller first one, the
# dragged line a short piece of its own.
PIECES = {
    (5, 5): [{"page": 1, "frac": [0.125, 0.25, 0.5, 0.03125]}],
    (4, 6): [{"page": 1, "frac": [0.125, 0.25, 0.5, 0.125]}],
    (3, 9): [{"page": 1, "frac": [0.125, 0.25, 0.5, 0.25]}, {"page": 2, "frac": SECOND}],
    (4, 7): [{"page": 1, "frac": [0.125, 0.25, 0.5, 0.1875]}],
    (1, 40): [{"page": 1, "frac": [0.125, 0.125, 0.5, 0.5]}],
}
# Presses a control and reads the selection's boxes in the same task, before any answer to that press can arrive: what
# the person sees the instant they press, which settling would hide.
PRESS_AND_READ = """selector => {
  document.querySelector(selector).click();
  return [...document.querySelectorAll('.sel')].map(box => {
    const page = box.parentElement.getBoundingClientRect(), own = box.getBoundingClientRect();
    return {page: box.parentElement.id, height: own.height / page.height};});}"""


class SelectionBoxesOnScreen(BrowserBase):
    """A drag in the real viewer whose pick and snippet answers carry the pieces its ranges print as."""

    PICK = {"lo": 4, "hi": 6, "kind": "paragraph", "levels": LEVELS, "default_level": "para"}
    # The ranges this run answers pieces for; a test narrows it to read the fallback.
    PIECES: dict = {}

    def setUp(self):
        super().setUp()
        self.PICK = {**SelectionBoxesOnScreen.PICK, "levels": [dict(rung) for rung in LEVELS]}
        self.PICK["levels"][1]["boxes"] = PIECES[(4, 6)]
        self.PIECES = dict(PIECES)
        self.asked = []  # the lines of each ladder the viewer asked where they print

    def route(self, route):
        """The fixture's routes, with every snippet ladder given the pieces this class stands in for."""
        request = route.request
        parts = urlparse(request.url)
        query = parse_qs(parts.query)
        if parts.path == "/api/snippet" and query.get("levels"):
            self.asked.append((int(query["lo"][0]), int(query["hi"][0])))
            answer = self.answer(request)
            body = json.loads(answer["body"])
            for rung in body.get("levels", []):
                pieces = self.PIECES.get((rung["lo"], rung["hi"]))
                if pieces:
                    rung["boxes"] = pieces
            answer["body"] = json.dumps(body)
            return route.fulfill(**answer)
        return super().route(route)

    def drag(self, page):
        """A drag on page 1 that opens the composer, and the page box it was made in."""
        box = page.evaluate(
            "(()=>{const r=document.getElementById('p1').getBoundingClientRect();"
            "return [r.left,r.top,r.width,r.height];})()"
        )
        x, y = box[0] + box[2] * 0.1, box[1] + box[3] * 0.1
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + box[2] * 0.3, y + box[3] * 0.05, steps=6)
        page.mouse.up()
        page.wait_for_function("!!COMPOSE.current", timeout=8000)
        settle(page)
        return box

    def view(self):
        """The viewer with the pages drawn and nothing in flight."""
        page = self.open(0, init=NO_COACH, **DESKTOP)
        settle(page)
        return page

    def boxes(self, page):
        """Every selection box on the pages, in document order: its page, classes and box in page fractions."""
        return page.evaluate(
            """() => [...document.querySelectorAll('.sel')].map(box => {
                 const page = box.parentElement.getBoundingClientRect(), own = box.getBoundingClientRect();
                 return {page: box.parentElement.id, cls: box.className, own: box === COMPOSE.box,
                   frac: [(own.left - page.left) / page.width, (own.top - page.top) / page.height,
                          own.width / page.width, own.height / page.height]};})"""
        )

    def height(self, page):
        """The height of the selection's own box, as a fraction of its page."""
        return self.boxes(page)[0]["frac"][3]

    def rung(self, page, level):
        """Press the range ladder's rung and let the box follow it."""
        page.click('#c-levels [data-act=level][data-level="%s"]' % level)
        settle(page)

    def test_the_new_pin_box_snaps_to_the_default_level(self):
        """The drag is one text line high; the pick's default rung is its paragraph, and the box is drawn over the
        paragraph's pieces - taller than what was dragged - so the person sees the range the pin will carry."""
        page = self.view()
        self.drag(page)
        drawn = self.boxes(page)
        self.assertEqual(len(drawn), 1)
        self.assertAlmostEqual(drawn[0]["frac"][3], 0.125, places=3)
        self.assertGreater(drawn[0]["frac"][3], 0.05)

    def test_changing_the_ladder_rung_moves_the_box(self):
        """Up to the environment rung: the box is redrawn over that range's pieces, taller than the paragraph's, and
        the piece on the next page is drawn there too."""
        page = self.view()
        self.drag(page)
        paragraph = self.height(page)
        self.rung(page, "env")
        drawn = self.boxes(page)
        self.assertGreater(drawn[0]["frac"][3], paragraph)
        self.assertEqual([piece["page"] for piece in drawn], ["p1", "p2"])
        self.assertEqual([piece["own"] for piece in drawn], [True, False])

    def test_a_malformed_piece_in_a_snippet_answer_is_left_out(self):
        """The other way a piece reaches the box - a rung of a snippet's ladder - is read as warily as a pick's: the
        unreadable row is dropped and the good piece beside it still draws the range moved to."""
        self.PIECES[(3, 9)] = [{"page": 1, "frac": [0.125, None, 0.5, 0.25]}, *PIECES[(3, 9)]]
        page = self.view()
        self.drag(page)
        self.rung(page, "env")
        drawn = self.boxes(page)
        self.assertEqual([piece["page"] for piece in drawn], ["p1", "p2"])
        self.assertAlmostEqual(drawn[0]["frac"][3], 0.25, places=2)  # the environment's height, not the paragraph's

    def test_the_box_waits_on_its_answer_rather_than_showing_the_drag_again(self):
        """Pressing a rung whose pieces are not known yet leaves the box on the range it is showing until the answer
        comes. It must not fall back to the dragged rectangle on the way: for the length of that request the person
        would be looking at the span they dragged as if it were the pin's range, which is the very thing the box is
        drawn this way to stop. The press and the measurement run in one task, since settling would hide it."""
        page = self.view()
        self.drag(page)
        paragraph = self.height(page)
        at_once = page.evaluate(PRESS_AND_READ, "#c-levels [data-act=level][data-level=env]")
        self.assertEqual(len(at_once), 1)
        self.assertAlmostEqual(at_once[0]["height"], paragraph, places=3)
        self.assertGreater(at_once[0]["height"], 0.1)  # the paragraph's pieces, not the one-line drag
        settle(page)
        self.assertGreater(self.height(page), paragraph)

    def test_widening_in_the_excerpt_also_waits_on_its_answer(self):
        """The same on the other way of changing the range: a '+' in the range excerpt keeps the box where it is until
        the lines it widened to are answered, so widening a line at a time never blinks back to the drag."""
        page = self.view()
        self.drag(page)
        paragraph = self.height(page)
        at_once = page.evaluate(PRESS_AND_READ, '#c-xp [data-act=xp-to][data-line="7"]')
        self.assertEqual(len(at_once), 1)
        self.assertAlmostEqual(at_once[0]["height"], paragraph, places=3)
        page.wait_for_function("COMPOSE.current.hi===7", timeout=8000)
        settle(page)
        self.assertGreater(self.height(page), paragraph)

    def test_a_walk_up_the_ladder_asks_once_for_what_one_answer_holds(self):
        """One ladder answers every rung around the range it was asked about, and those are kept. So a walk over three
        rungs asks once: the default rung came answered with the pick, the environment is asked for, and the rung it
        answers beside it - and the environment again - are drawn from what is already here."""
        page = self.view()
        self.drag(page)
        self.assertEqual(self.asked, [])  # the pick answered its own default rung
        self.rung(page, "env")
        self.assertEqual(self.asked, [(3, 9)])
        self.rung(page, "env2")  # the whole file: the (3, 9) ladder carried it
        self.rung(page, "env")
        self.rung(page, "para")
        self.assertEqual(self.asked, [(3, 9)])
        drawn = self.boxes(page)
        self.assertEqual([piece["page"] for piece in drawn], ["p1"])
        self.assertAlmostEqual(drawn[0]["frac"][3], 0.125, places=3)

    def test_moving_up_the_ladder_and_back_leaves_no_box_behind(self):
        """Back down to the paragraph: its one piece is drawn and the environment's second piece is gone, so no box
        stands for lines the pin no longer covers."""
        page = self.view()
        self.drag(page)
        self.rung(page, "env")
        self.assertEqual(len(self.boxes(page)), 2)
        self.rung(page, "para")
        drawn = self.boxes(page)
        self.assertEqual([piece["page"] for piece in drawn], ["p1"])
        self.assertAlmostEqual(drawn[0]["frac"][3], 0.125, places=3)

    def test_adjusting_lines_in_the_excerpt_moves_the_box(self):
        """Widening the range by one line in the range excerpt: the box follows the lines that will be saved, from the
        snippet answer the viewer fetches for them."""
        page = self.view()
        self.drag(page)
        before = self.height(page)
        page.click('#c-xp [data-act=xp-to][data-line="7"]')
        page.wait_for_function("COMPOSE.current.hi===7", timeout=8000)
        settle(page)
        self.assertGreater(self.height(page), before)

    def test_the_box_falls_back_when_the_answer_has_no_boxes(self):
        """No pieces for any range - a build with no PDF to measure against: the box is the rectangle that was dragged,
        the same element with the same classes, and the ladder leaves it alone."""
        self.PIECES = {}
        del self.PICK["levels"][1]["boxes"]
        page = self.view()
        self.drag(page)
        page.evaluate("COMPOSE.box.dataset.probe='1'")
        drawn = self.boxes(page)
        self.assertEqual(len(drawn), 1)
        self.assertEqual(drawn[0]["cls"], "sel pending")
        for index, value in enumerate(DRAGGED):
            self.assertAlmostEqual(drawn[0]["frac"][index], value, places=2)
        self.rung(page, "env")
        self.assertEqual(len(self.boxes(page)), 1)
        self.assertEqual(page.evaluate("COMPOSE.box.dataset.probe"), "1")

    def test_a_malformed_piece_is_left_out_and_the_rest_is_drawn(self):
        """One unreadable row of a pick's answer does not blank the selection: the good piece beside it is drawn and the
        composer opens on the range as usual."""
        self.PICK["levels"][1]["boxes"] = [None, {"page": 1, "frac": [0.125, "x", 0.5, 0.25]}, *PIECES[(4, 6)]]
        page = self.view()
        self.drag(page)
        drawn = self.boxes(page)
        self.assertEqual(len(drawn), 1)
        self.assertAlmostEqual(drawn[0]["frac"][3], 0.125, places=3)
        self.assertFalse(page.evaluate("document.querySelector('#composer').hidden"))

    def test_a_press_on_a_second_piece_does_not_cancel_the_selection(self):
        """Every piece is inside the selection: a short press on the piece without the popover leaves the selection
        standing, while a press on the page clear of every piece cancels it."""
        page = self.view()
        self.drag(page)
        self.rung(page, "env")
        drawn = self.boxes(page)
        self.assertEqual(len(drawn), 2)
        page.evaluate("()=>document.querySelectorAll('.sel')[1].scrollIntoView({block:'center'})")
        settle(page)
        spot = page.evaluate(
            "()=>{const r=document.querySelectorAll('.sel')[1].getBoundingClientRect();"
            "return [r.left + r.width/2, r.top + r.height/2];}"
        )
        page.mouse.click(spot[0], spot[1])
        settle(page)
        self.assertTrue(page.evaluate("!!COMPOSE.current"))
        away = page.evaluate(
            "()=>{const r=document.querySelectorAll('.sel')[1].getBoundingClientRect(),"
            "p=document.getElementById('p2').getBoundingClientRect();"
            "return [p.left + p.width*0.9, r.bottom + 60];}"
        )
        page.mouse.click(away[0], away[1])
        page.wait_for_function("COMPOSE.current===null", timeout=8000)

    def test_the_popover_anchors_to_the_first_piece(self):
        """With several pieces the note popover stands under the first - the topmost block of the lowest page, where the
        person was reading - not under the piece on the next page."""
        page = self.view()
        self.drag(page)
        self.rung(page, "env")
        place = page.evaluate(
            """() => {const pop = document.querySelector('#sel-pop'), pieces = document.querySelectorAll('.sel');
                 const rect = e => {const b = e.getBoundingClientRect(); return {left: b.left, top: b.top, bottom: b.bottom};};
                 return {shown: !pop.hidden, pop: rect(pop), first: rect(pieces[0]), second: rect(pieces[1])};}"""
        )
        self.assertTrue(place["shown"])
        self.assertAlmostEqual(place["pop"]["left"], place["first"]["left"], delta=1)
        self.assertGreaterEqual(place["pop"]["top"], place["first"]["bottom"])
        self.assertLess(place["pop"]["top"], place["second"]["top"])

    def test_cancelling_the_selection_takes_every_piece_off(self):
        """Esc on a selection of several pieces leaves no box on the pages."""
        page = self.view()
        self.drag(page)
        self.rung(page, "env")
        self.assertEqual(len(self.boxes(page)), 2)
        page.keyboard.press("Escape")
        page.wait_for_function("COMPOSE.current===null", timeout=8000)
        settle(page)
        self.assertEqual(page.evaluate("document.querySelectorAll('.sel').length"), 0)

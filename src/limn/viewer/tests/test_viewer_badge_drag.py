"""A pin's number badge is the handle that places the pin again (docs/adr/0050-pin-badge-drag-reposition.md).

A mouse drag from the badge of an open pin without a verdict turns the re-place mode on for that pin and sends the
place it is dropped on to POST /api/pick; the '새 위치' box then stands on the pieces that range prints as, and the
banner's [이 위치로 바꾸기] saves it. A finger may drag the badge only inside the re-place mode for that very pin, so
the long-press tooltip and the box a badge drag starts in [선택] mode both stay as they are. What the drag sends is not
the pin's own box but the probe a tap and a long-press already send - one text line at the pointer - because a line
pin's first piece is as tall as its whole paragraph; a region pin, whose area is itself what the pin points at, moves
its box whole.

The judgements and the geometry are read under node from the served source (MovablePins, DroppedBox). What only a
browser can say - the drag turning the mode on, the box snapping, the confirm saving, a press under the slop staying
the badge's click, a finger outside the mode - is read in the real viewer (BadgeDragOnScreen), whose pin list and
snippet answers carry the pieces the fixture's build cannot compute.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_badge_drag.py
"""

import json
import shutil
import unittest
from urllib.parse import parse_qs, urlparse

from helpers import add_pin, edit_pin, extract_js_fn, js_const, run_node
from helpers_access import ALICE, actor
from helpers_browser import BrowserBase, settle

A = actor(ALICE)
DESKTOP = {"viewport": {"width": 1440, "height": 900}}
PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
# First-visit hints off: their line would stand over the pages the badges are dragged on.
NO_COACH = "try{localStorage.setItem('pinPrefs',JSON.stringify({coach:{touch:1,mouse:1,sel:1,side:1}}))}catch(e){}"
# The pieces this run stands in for, in halves and eighths so their percentages are exact in binary.
PIECE = [0.125, 0.5, 0.75, 0.0625]
SECOND_PIECE = [0.125, 0.125, 0.75, 0.0625]


class MovablePins(unittest.TestCase):
    """Which pins a badge may place again (markMovable), read from the served rule."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def movable(self, pins):
        js = "\n".join(
            [
                extract_js_fn("pinState"),
                extract_js_fn("verdictOf"),
                extract_js_fn("markMovable"),
                "console.log(JSON.stringify(%s.map(markMovable)));" % json.dumps(pins),
            ]
        )
        return json.loads(run_node(js))

    def test_only_an_open_pin_without_a_verdict_may_be_placed_again(self):
        """The same judgement the edit card makes of [위치 다시 잡기]: a verdict pin keeps the place it fixed, and a
        closed or awaiting-review pin keeps where it points. A badge that said otherwise would end its drag in a
        refusal (400 verdict_fixed, 409)."""
        self.assertEqual(
            self.movable(
                [
                    {"id": 1, "state": "open"},
                    {"id": 2, "state": "open", "verdict": "take"},
                    {"id": 3, "state": "review"},
                    {"id": 4, "state": "done"},
                    {"id": 5, "done": True},
                    {"id": 6, "done": True, "review": True},
                ]
            ),
            [True, False, False, False, False, False],
        )

    def test_nothing_is_movable(self):
        """A badge whose pin this tab no longer has (the list was read again mid-press) moves nothing, rather than
        throwing where the press is read."""
        self.assertEqual(self.movable([None]), [False])


class DroppedBox(unittest.TestCase):
    """The rectangle a badge drag sends, read from the served geometry (badgeDrop, badgeAt)."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def drop(self, place, move_x, move_y):
        js = "\n".join(
            [
                extract_js_fn("badgeDrop"),
                "console.log(JSON.stringify(badgeDrop(%s, %r, %r)));" % (json.dumps(place), move_x, move_y),
            ]
        )
        return json.loads(run_node(js))

    def at(self, move, start, pointer, page=(100.0, 200.0, 400.0, 500.0)):
        """What badgeAt asks the server about: the two corners, for a drag of `move` that began at `start` (client
        px) with the pointer now at `pointer`, on a page laid out at `page` (left, top, width, height)."""
        js = "\n".join(
            [
                js_const("TAP_SLOP"),  # and the halves quickBox measures its probe with
                js_const("clampUnit"),
                extract_js_fn("fracAt"),
                extract_js_fn("quickBox"),
                extract_js_fn("badgeDrop"),
                extract_js_fn("fracMove"),
                extract_js_fn("badgeAt"),
                "const pageElement = {getBoundingClientRect: () => ({left: %r, top: %r, width: %r, height: %r})};"
                % page,
                "const drag = {pg: pageElement, cx: %r, cy: %r, move: %s};" % (start[0], start[1], json.dumps(move)),
                "console.log(JSON.stringify(badgeAt(drag, %r, %r)));" % pointer,
            ]
        )
        return json.loads(run_node(js))

    def test_a_region_pin_keeps_its_size_and_stays_on_the_page(self):
        """A region pin's box moves whole, and a drop that would push an edge past the page slides it back inside: a
        drag places the pin within its page, so no drop is off it."""
        self.assertEqual(self.drop([0.2, 0.3, 0.25, 0.125], 0.1, -0.1), [0.3, 0.2, 0.25, 0.125])
        self.assertEqual(self.drop([0.8, 0.9, 0.25, 0.125], 0.5, 0.5), [0.75, 0.875, 0.25, 0.125])
        self.assertEqual(self.drop([0.2, 0.3, 0.25, 0.125], -0.5, -0.5), [0, 0, 0.25, 0.125])

    def test_a_box_put_back_where_it_was_reads_as_the_fractions_it_came_with(self):
        """Six places is under a thousandth of a pixel on any page, so a box dropped where it was carries the numbers
        it came with and not their floating-point dust."""
        place = [0.123456, 0.654321, 0.25, 0.125]
        self.assertEqual(self.drop(place, 0, 0), place)

    def test_a_box_wider_than_its_page_is_not_pushed_off_it(self):
        """A box as wide as the page, or wider than it, has nowhere to slide: it stays at the page's edge rather than
        at a negative one."""
        self.assertEqual(self.drop([0, 0, 1.5, 1.5], 0.4, 0.4), [0, 0, 1.5, 1.5])

    def test_a_line_pin_sends_the_probe_a_tap_sends(self):
        """One text line at the pointer - the page's width +-7% and its height +-0.6%, which is what quickBox answers
        for a tap and a long-press. The pin's own first piece is as tall as its paragraph, and moved by less than its
        own height it would cover the old paragraph and the new one alike."""
        corners = self.at({"id": 7, "frac": [0.1, 0.1, 0.8, 0.2], "region": False}, (110.0, 220.0), (300.0, 450.0))
        self.assertEqual([round(value, 6) for value in corners], [0.43, 0.494, 0.57, 0.506])

    def test_the_probe_stays_on_the_page(self):
        """A pointer dragged past the page's edge clamps to it: the probe never names a place off the page, and never
        one on another."""
        self.assertEqual(
            self.at({"id": 7, "frac": [0.1, 0.1, 0.8, 0.2], "region": False}, (110.0, 220.0), (-900.0, -900.0)),
            [0, 0, 0.07, 0.006],
        )

    def test_a_region_pin_sends_its_moved_box(self):
        """The same box, moved by how far the pointer came - as two corners, which is the shape finishRect takes."""
        self.assertEqual(
            self.at({"id": 7, "frac": [0.25, 0.25, 0.25, 0.125], "region": True}, (100.0, 200.0), (200.0, 300.0)),
            [0.5, 0.45, 0.75, 0.575],
        )

    def test_a_press_that_moves_nothing_asks_about_nothing(self):
        """A drag whose move is gone (the mode ended under the hand) has no rectangle to ask about."""
        self.assertEqual(self.at(None, (100.0, 200.0), (200.0, 300.0)), [0, 0, 0, 0])


class BadgeDragOnScreen(BrowserBase):
    """Two open pins of the manuscript in the real viewer, with the pieces their ranges print as.

    The fixture's build has page images but no PDF to measure a range against, so the server answers no `boxes`: this
    class stands in for that answer in the pin list (by each pin's note) and in the snippet ladders a re-place reads,
    which is where the '새 위치' box gets its pieces.
    """

    # The state this run stands in for on a pin, by its note - a record the server can send that the fixture cannot
    # reach through its own service.
    STATES: dict = {}

    def setUp(self):
        """One pin to place again, one awaiting review whose badge must not be a handle, and one saved without a box
        of its own - what an agent writes, and what an older client wrote."""
        super().setUp()
        body = {"file": str(self.main), "page": 1}
        saved = add_pin({**body, "lo": 4, "hi": 5, "note": "옮길 핀", "frac": [0.25, 0.3, 0.2, 0.05]}, A).record
        self.movable, self.movable_rev = saved["id"], saved.get("rev") or 0
        self.fixed = add_pin({**body, "lo": 8, "hi": 9, "note": "검토 대기", "frac": [0.6, 0.3, 0.2, 0.05]}, A).record[
            "id"
        ]
        self.boxless = add_pin({**body, "lo": 12, "hi": 13, "note": "상자 없이 저장된 핀"}, A).record["id"]
        self.STATES = {"검토 대기": "review"}
        self.asked = []  # the ladders the viewer asked where they print

    def route(self, route):
        """The fixture's routes, with the pin list given the state this class stands in for and every snippet ladder
        given the pieces the re-place box stands on."""
        request = route.request
        parts = urlparse(request.url)
        if parts.path == "/api/pins":
            answer = self.answer(request)
            rows = json.loads(answer["body"])
            for row in rows:
                state = self.STATES.get(row.get("note"))
                if state:
                    row["state"] = state
                # the pin saved without a box of its own is marked from its range, as the server marks one
                if row.get("note") == "상자 없이 저장된 핀":
                    row["boxes"] = [{"page": 1, "frac": SECOND_PIECE}]
            answer["body"] = json.dumps(rows)
            return route.fulfill(**answer)
        query = parse_qs(parts.query)
        if parts.path == "/api/snippet" and query.get("boxes") == ["1"]:
            self.asked.append((int(query["lo"][0]), int(query["hi"][0])))
            answer = self.answer(request)
            body = json.loads(answer["body"])
            for rung in body.get("levels", []):
                rung["boxes"] = [{"page": 1, "frac": PIECE}, {"page": 1, "frac": SECOND_PIECE}]
            body["boxes_build"] = body.get("boxes_build") or ""
            answer["body"] = json.dumps(body)
            return route.fulfill(**answer)
        return super().route(route)

    def view(self, **device):
        """The viewer with both marks drawn. One of the two pins is awaiting review, so only one is open."""
        page = self.open(1, init=NO_COACH, **(device or DESKTOP))
        page.wait_for_function("()=>document.querySelectorAll('.mark button.mark-jump').length===3", timeout=8000)
        settle(page)
        return page

    def badge(self, page, pin):
        """The centre of that pin's number badge, in client px."""
        return page.evaluate(
            """id => {const r = document.querySelector('.mark[data-pin="' + id + '"] button.mark-jump')
                 .getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2];}""",
            pin,
        )

    def drag_badge(self, page, pin, by=(0, 140), rest=True):
        """Press that pin's badge with the mouse and move `by` px before letting go. rest=False returns before the
        page has settled, for a check on something the viewer takes back on a timer (a card's .cur, 1.2s)."""
        start = self.badge(page, pin)
        page.mouse.move(start[0], start[1])
        page.mouse.down()
        page.mouse.move(start[0] + by[0], start[1] + by[1], steps=8)
        page.mouse.up()
        if rest:
            settle(page)
        return start

    def test_a_mouse_drag_from_a_badge_offers_the_place_it_was_dropped_on(self):
        """The drag turns the re-place mode on for that pin without an edit card, the banner compares the places and
        offers [이 위치로 바꾸기], and the box stands on the pieces the new range prints as - the place that will be
        saved, not the probe that was dropped."""
        page = self.view()
        self.drag_badge(page, self.movable)
        page.wait_for_selector("#banner [data-act=rp-apply]", timeout=8000)
        self.assertEqual(page.evaluate("()=>REPICK && REPICK.id"), self.movable)
        boxes = page.evaluate(
            """()=>[REPICK.box, ...document.querySelectorAll('.sel-part[data-owner=repick]')]
                 .map(el => [el.style.left, el.style.top, el.style.width, el.style.height])"""
        )
        self.assertEqual(boxes, [["12.5%", "50%", "75%", "6.25%"], ["12.5%", "12.5%", "75%", "6.25%"]])

    def test_confirming_moves_the_pin_and_takes_the_pieces_off(self):
        """[이 위치로 바꾸기] saves against the pin's own revision, there being no edit card to read one from, and the
        pin's range becomes the candidate's; the box and the pieces beside it go with the banner."""
        page = self.view()
        self.drag_badge(page, self.movable)
        page.wait_for_selector("#banner [data-act=rp-apply]", timeout=8000)
        was = page.evaluate("id=>{const p=PINS.find(p=>p.id===id); return [p.lo, p.hi];}", self.movable)
        page.click("#banner [data-act=rp-apply]")
        page.wait_for_function("()=>!REPICK", timeout=8000)
        settle(page)
        self.assertNotEqual(
            page.evaluate("id=>{const p=PINS.find(p=>p.id===id); return [p.lo, p.hi];}", self.movable), was
        )
        self.assertEqual(page.locator(".sel-part[data-owner=repick]").count(), 0)

    def test_a_second_drag_on_the_same_badge_drops_the_place_it_was_offering(self):
        """Dragging the badge again is choosing another place, so the one the banner was offering goes the moment the
        drag passes the slop: through the whole second drag there is nothing to confirm, and the banner asks for the
        new place. Left standing, [이 위치로 바꾸기] would save the place before this drag - a place the person has
        moved on from (docs/adr/0050-pin-badge-drag-reposition.md D6)."""
        page = self.view()
        self.drag_badge(page, self.movable)
        page.wait_for_selector("#banner [data-act=rp-apply]", timeout=8000)
        # the answer itself is kept, not its lines: this fixture's document is one paragraph, so both drops resolve
        # to the same range and only the answer's identity tells the places apart
        page.evaluate("()=>{window.firstPlace = REPICK.cand;}")
        start = self.badge(page, self.movable)
        page.mouse.move(start[0], start[1])
        page.mouse.down()
        page.mouse.move(start[0], start[1] + 60, steps=6)
        settle(page)
        self.assertIsNone(page.evaluate("()=>REPICK.cand"))
        self.assertEqual(page.locator("#banner [data-act=rp-apply]").count(), 0)
        page.mouse.up()
        page.wait_for_selector("#banner [data-act=rp-apply]", timeout=8000)
        settle(page)
        self.assertFalse(page.evaluate("()=>REPICK.cand === window.firstPlace"))

    def test_a_press_under_the_slop_is_still_the_badge_s_click(self):
        """Six pixels is a click: the card is scrolled to and highlighted as before, and no re-place begins."""
        page = self.view()
        self.drag_badge(page, self.movable, by=(0, 6), rest=False)
        page.wait_for_function(
            "id=>!!document.querySelector('.pin.card.cur[data-id=\"'+id+'\"]')", arg=self.movable, timeout=8000
        )
        self.assertIsNone(page.evaluate("()=>REPICK"))
        settle(page)

    def test_an_awaiting_review_pin_s_badge_is_not_a_handle(self):
        """A pin whose place is fixed keeps the badge it had: the press is its click, no box is drawn and no re-place
        begins, so the drag never ends in a refusal the person did not ask for."""
        page = self.view()
        self.drag_badge(page, self.fixed)
        self.assertIsNone(page.evaluate("()=>REPICK"))
        self.assertEqual(page.locator(".sel:not(.mark)").count(), 0)

    def test_ending_the_mode_under_the_hand_moves_nothing(self):
        """Esc while the button is still down ends the re-place: the drag drops its box and nothing else - no pin
        moved, and no '새 핀' composer over the pin the person was moving."""
        page = self.view()
        start = self.badge(page, self.movable)
        page.mouse.move(start[0], start[1])
        page.mouse.down()
        page.mouse.move(start[0], start[1] + 60, steps=4)
        page.keyboard.press("Escape")
        page.mouse.move(start[0], start[1] + 120, steps=4)
        page.mouse.up()
        settle(page)
        self.assertIsNone(page.evaluate("()=>REPICK"))
        self.assertIsNone(page.evaluate("()=>COMPOSE.current"))
        self.assertTrue(page.locator("#composer").is_hidden())

    def test_the_pin_being_placed_again_stands_back_while_the_hand_carries_it(self):
        """The probe the hand carries is one text line and the pin's own mark is as tall as its paragraph, so while
        the badge is down that pin's marks stand back (.mark.moving) and the place it is leaving reads as the place it
        is leaving. Only that pin's, and only while the hand is on it: on release they are at their own strength
        again, moved or not."""
        page = self.view()
        start = self.badge(page, self.movable)
        page.mouse.move(start[0], start[1])
        page.mouse.down()
        page.mouse.move(start[0], start[1] + 140, steps=8)
        settle(page)
        self.assertEqual(page.locator('.mark.moving[data-pin="%d"]' % self.movable).count(), 1)
        self.assertEqual(page.locator(".mark.moving").count(), 1)  # the pins beside it are untouched
        self.assertAlmostEqual(
            float(page.evaluate('()=>getComputedStyle(document.querySelector(".mark.moving")).opacity')), 0.4, 2
        )
        page.mouse.up()
        settle(page)
        self.assertEqual(page.locator(".mark.moving").count(), 0)

    def test_a_pin_saved_without_a_box_of_its_own_is_dragged_like_any_other(self):
        """A line pin needs no stored box to be placed again: what its drag sends is the probe at the pointer, and the
        box it leaves is its range's, which the pin list answers. A pin an agent saved carries no `frac`, and its
        badge is a handle all the same."""
        page = self.view()
        self.drag_badge(page, self.boxless)
        page.wait_for_selector("#banner [data-act=rp-apply]", timeout=8000)
        self.assertEqual(page.evaluate("()=>REPICK && REPICK.id"), self.boxless)

    def test_a_pin_lost_mid_drag_becomes_the_rectangle_the_drag_would_have_been(self):
        """The list was read again while the button was down and that pin is gone (another person deleted it): there
        is no mode to turn on and nothing to place, so the drag goes on as the drawn rectangle it would have been and
        nothing throws where the press is read."""
        page = self.view()
        start = self.badge(page, self.movable)
        page.mouse.move(start[0], start[1])
        page.mouse.down()
        page.evaluate("()=>{OPEN_ALL.length = 0; REVIEW_ALL.length = 0; DONE_ALL.length = 0;}")
        page.mouse.move(start[0] + 30, start[1] + 120, steps=6)
        page.mouse.up()
        settle(page)
        self.assertIsNone(page.evaluate("()=>REPICK"))
        self.assertEqual(page.locator("#banner:visible").count(), 0)
        # the drawn rectangle it would have been: a new selection, with the composer open on it
        self.assertTrue(page.evaluate("()=>!!COMPOSE.current && !!COMPOSE.box"))
        self.assertTrue(page.locator("#composer").is_visible())

    def test_a_drag_past_the_page_asks_about_a_place_on_that_page(self):
        """The badge dragged far below the page: the probe clamps to the page the badge stands on, so the candidate is
        a place on that page and the pin never lands on another one."""
        page = self.view()
        self.drag_badge(page, self.movable, by=(0, 4000))
        page.wait_for_selector("#banner [data-act=rp-apply]", timeout=8000)
        self.assertEqual(page.evaluate("()=>REPICK.cand.page"), 1)

    def test_a_pin_changed_since_the_drag_is_refused_and_stays_where_it_is(self):
        """The confirm saves against the pin's own revision, so a pin another writer moved or closed in between is a
        409: a warning says why, the pins are read again and the pin keeps its range."""
        page = self.view()
        self.drag_badge(page, self.movable)
        page.wait_for_selector("#banner [data-act=rp-apply]", timeout=8000)
        was = page.evaluate("id=>{const p=PINS.find(p=>p.id===id); return [p.lo, p.hi];}", self.movable)
        edit_pin(self.movable, {"note": "다른 사람이 먼저 고쳤다", "base_rev": self.movable_rev}, A)
        page.click("#banner [data-act=rp-apply]")
        page.wait_for_function("()=>!REPICK", timeout=8000)
        settle(page)
        self.assertEqual(
            page.evaluate("id=>{const p=PINS.find(p=>p.id===id); return [p.lo, p.hi];}", self.movable), was
        )
        self.assertIn(
            "먼저 바꿨습니다",
            " ".join(page.evaluate("()=>[...NOTICES.values()].map(notice=>notice.title + ' ' + notice.kind)")),
        )

    def test_a_finger_inside_the_mode_for_that_pin_places_it(self):
        """Inside the re-place mode for that very pin a finger may drag its badge, which is the only way touch reaches
        this shortcut. [위치 다시 잡기] on a coarse pointer turns selection mode on with the mode (startRepick), and
        this stands in for both; where the mode came from is not what the rule is about."""
        page = self.view(**PHONE)
        page.evaluate("id=>{repickFromBadge(id); setSelectMode(true);}", self.movable)
        settle(page)
        start = self.badge(page, self.movable)
        page.touchscreen.tap(start[0], start[1])  # a tap stays the badge's: it is under the slop
        settle(page)
        self.assertEqual(page.evaluate("()=>REPICK && REPICK.id"), self.movable)
        page.evaluate(
            """([x, y]) => {const target = document.elementFromPoint(x, y);
                 const send = (type, to) => target.dispatchEvent(new PointerEvent(type, {bubbles: true,
                   pointerId: 2, isPrimary: true, pointerType: 'touch', clientX: to[0], clientY: to[1]}));
                 send('pointerdown', [x, y]); send('pointermove', [x, y + 60]);
                 window.dispatchEvent(new PointerEvent('pointerup', {bubbles: true, pointerId: 2, isPrimary: true,
                   pointerType: 'touch', clientX: x, clientY: y + 60}));}""",
            list(start),
        )
        page.wait_for_selector("#banner [data-act=rp-apply]", timeout=8000)
        self.assertEqual(page.evaluate("()=>REPICK.id"), self.movable)

    def test_a_finger_outside_the_mode_leaves_the_badge_alone(self):
        """Touch keeps the two gestures the badge already has: outside the re-place mode a finger's drag on it is no
        re-place, and in [선택] mode it starts a box as it did before - on a small page the badges' press areas cover
        much of the left edge, where no drag could start otherwise."""
        page = self.view(**PHONE)
        start = self.badge(page, self.movable)
        page.touchscreen.tap(start[0], start[1])
        settle(page)
        self.assertIsNone(page.evaluate("()=>REPICK"))
        page.evaluate("()=>setSelectMode(true)")
        settle(page)
        page.evaluate(
            """([x, y]) => {const target = document.elementFromPoint(x, y);
                 const send = (type, to) => target.dispatchEvent(new PointerEvent(type, {bubbles: true,
                   pointerId: 1, isPrimary: true, pointerType: 'touch', clientX: to[0], clientY: to[1]}));
                 send('pointerdown', [x, y]); send('pointermove', [x, y + 40]);}""",
            list(start),
        )
        self.assertIsNone(page.evaluate("()=>REPICK"))
        self.assertEqual(page.locator("#doc .sel:not(.mark)").count(), 1)

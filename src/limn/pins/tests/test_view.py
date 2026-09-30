"""limn.pins.listing.projection - the computed fields of GET /api/pins and the Trash list, called directly with explicit collaborators.

The answers through the HTTP handler are pinned in test_server.py, test_reply.py and test_trash.py; at the end of
this file, through server.py: the Trash list (DroppedList), a legacy claim's start (LegacyClaimStart) and a legacy
done pin's state (LegacyDoneState). Above it the pure functions get their record display, documents, estimation
facts and clock as arguments, and must never call a collaborator they do not need.

Run: uv run pytest -q src/limn/pins/tests/test_view.py
"""

import json
import math
import time
import unittest

from limn.builds.figure_map import FigureMap, MapElement, MapPage
from limn.builds.queries import element_follower
from limn.pins.listing.projection import (
    dropped_payload,
    element_marks,
    pin_state,
    pin_view,
    pins_payload,
    public_record,
)
from limn.pins.location import position
from limn.pins.location.position import EstContext
from limn.pins.model import TrashedPin, parse_pin
from limn.pins.store import find_pin
from limn.security.access import LOCAL_ACTOR

from helpers import Base, find_record, fits, ps, records, req, write_records
from helpers_authority import post_authority

NOW = 1790000000.0
CUR = EstContext("b2", frozenset({"b2"}), None, None)


def shown(r):
    """A stand-in for server.public(): a copy with a marker field, so the tests see that show's output is used."""
    return dict(r, shown=True)


class PinState(unittest.TestCase):
    """pin_state names the state type parse_pin gives - one rule for the API and the transitions."""

    RECORDS = (
        {},
        {"done": False, "review": True},
        {"done": True},
        {"done": True, "review": False},
        {"done": True, "review": True},
        {"done": 1, "review": "yes"},
        {"review": True},
    )

    def test_the_names_of_every_shape(self):
        """Not done is open (a stray review flag is meaningless); done with review true is review; else done."""
        self.assertEqual(
            [pin_state(r) for r in self.RECORDS], ["open", "open", "done", "done", "review", "done", "open"]
        )

    def test_the_name_is_the_parsed_state_types(self):
        """For every shape, the name is the `state` of the type the transitions parse the record into."""
        for r in self.RECORDS:
            self.assertEqual(pin_state(r), type(parse_pin(r)).state, r)


class PinView(unittest.TestCase):
    """pin_view: one record of GET /api/pins."""

    def test_computed_fields_follow_the_shown_record_in_order(self):
        """shown's fields come first, then rel, est, doc, state, addressed, fyi; neither input changes."""
        r = {"id": 4, "note": "n", "kind_req": "question", "note_mentions": ["bob@example.com"]}
        before, show = dict(r), shown(r)
        rec = pin_view(r, show, [{"id": 2, "rel": "inside"}], False, "main", NOW)
        self.assertEqual(
            list(rec),
            ["id", "note", "kind_req", "note_mentions", "shown", "rel", "est", "doc", "state", "addressed", "fyi"],
        )
        self.assertEqual(
            (rec["rel"], rec["est"], rec["doc"], rec["state"]), ([{"id": 2, "rel": "inside"}], False, "main", "open")
        )
        self.assertEqual((r, show), (before, shown(before)))

    def test_a_computed_name_already_in_the_record_is_overwritten_in_place(self):
        """A stored `state` or `rel` (an old or foreign writer) keeps its position and gets the computed value."""
        rec = pin_view({"id": 1, "done": True}, {"id": 1, "state": "stale", "done": True}, [], True, "main", NOW)
        self.assertEqual(list(rec)[:3], ["id", "state", "done"])
        self.assertEqual(rec["state"], "done")

    def test_a_holding_legacy_claim_gets_its_start_epoch(self):
        """A claim that holds at now but has no claim_ts gets claim_ts from claimed_at (local time)."""
        r = {"id": 1, "claimed_by": {"login": "a"}, "claimed_at": "2026-09-26 10:00:00", "claim_until": NOW + 60}
        rec = pin_view(r, shown(r), [], False, "main", NOW)
        self.assertIsInstance(rec["claim_ts"], float)

    def test_a_closed_pin_with_live_claim_fields_gets_its_start_epoch_too(self):
        """Pinned on purpose: a hand-edited done or review pin that still carries a live claim_until (no claim_ts)
        gets claim_ts, as an open one does - GET /api/pins reads the record (lifecycle.claim_holds), not the lifted
        claim, which only an open pin has. Changing this changes the agent contract and must be deliberate."""
        claim = {"claimed_by": {"login": "a"}, "claimed_at": "2026-09-26 10:00:00", "claim_until": NOW + 60}
        for state in ({"done": True}, {"done": True, "review": True}):
            r = {"id": 1, **state, **claim}
            rec = pin_view(r, shown(r), [], False, "main", NOW)
            self.assertIsInstance(rec["claim_ts"], float, state)

    def test_no_claim_start_when_not_needed_or_not_known(self):
        """No claim_ts added for an expired claim, a claim that has one, or an unreadable claimed_at."""
        base = {"id": 1, "claimed_by": {"login": "a"}, "claimed_at": "2026-09-26 10:00:00", "claim_until": NOW + 60}
        for r in (dict(base, claim_until=NOW), dict(base, claim_ts=5), dict(base, claimed_at="soon")):
            rec = pin_view(r, shown(r), [], False, "main", NOW)
            self.assertEqual(rec.get("claim_ts"), r.get("claim_ts"), r)


class PinsPayload(unittest.TestCase):
    """pins_payload: the listed pins, with each document's estimation facts read at most once."""

    def setUp(self):
        """Three pins of two documents (one done) and a recording est_context."""
        self.rows = [
            {"id": 1, "doc": "a", "pdf_build": "b1"},
            {"id": 2, "doc": "b", "pdf_build": "b2"},
            {"id": 3, "doc": "a", "done": True, "pdf_build": "b2"},
            {"id": 4, "doc": "a", "pdf_build": "b2"},
        ]
        self.asked = []

    def est_context(self, key):
        """Estimation facts for document a; b is no longer served (None). Records each question."""
        self.asked.append(key)
        return CUR if key == "a" else None

    def payload(self, allp):
        """pins_payload over self.rows with a fixed rel and doc field."""
        return pins_payload(
            self.rows, allp, {1: [{"id": 4, "rel": "partial"}]}, shown, lambda r: r["doc"], self.est_context, NOW
        )

    def test_open_pins_only_unless_all(self):
        """Without allp a done pin is left out; with it every row comes, in row order."""
        self.assertEqual([r["id"] for r in self.payload(False)], [1, 2, 4])
        self.assertEqual([r["id"] for r in self.payload(True)], [1, 2, 3, 4])

    def test_est_by_build_and_true_for_a_document_no_longer_served(self):
        """Another build of a different manuscript is estimated, the current build is not; unknown document: True."""
        got = {r["id"]: (r["est"], r["rel"], r["doc"], r["shown"]) for r in self.payload(False)}
        self.assertEqual(
            got,
            {1: (True, [{"id": 4, "rel": "partial"}], "a", True), 2: (True, [], "b", True), 4: (False, [], "a", True)},
        )

    def test_each_listed_document_is_asked_once(self):
        """est_context reads a document's build history: once per document, and never for one with no listed pin."""
        self.payload(True)
        self.assertEqual(self.asked, ["a", "b"])
        self.asked.clear()
        self.rows = [r for r in self.rows if r["doc"] == "a"]
        self.payload(False)
        self.assertEqual(self.asked, ["a"])


class DroppedPayload(unittest.TestCase):
    """dropped_payload: the Trash ordered by dropped_at, with its expiry."""

    def test_order_expiry_and_show(self):
        """Ordered by dropped_at (missing first, ties in row order); expires_ts rounded to ms, absent when unknown."""
        rows = [
            {"id": 1, "dropped_at": "2026-09-26 10:00:00"},
            {"id": 2},
            {"id": 3, "dropped_at": "2026-09-25 09:00:00"},
            {"id": 4, "dropped_at": "2026-09-25 09:00:00"},
        ]
        expiry = {1: 100.12345, 3: 50.0, 4: None}
        entries = [TrashedPin.from_record(r) for r in rows]
        out = dropped_payload(entries, shown, lambda e: expiry.get(e.pin.core.id))
        self.assertEqual([r["id"] for r in out], [2, 3, 4, 1])
        self.assertEqual([r.get("expires_ts") for r in out], [None, 50.0, None, 100.123])
        self.assertTrue(all(r["shown"] for r in out))
        self.assertEqual(rows[0], {"id": 1, "dropped_at": "2026-09-26 10:00:00"})


FIG = FigureMap(
    "figures.pdf",
    "0" * 64,
    (
        MapPage(
            1,
            "B2",
            None,
            (
                MapElement("B2", None, (0.0, 0.0, 1.0, 1.0), None, None, None, None),
                MapElement("B2/m07", "B2", (0.47, 0.18, 0.07, 0.12), None, None, "MonthCell", "7월"),
            ),
        ),
    ),
)
EL = {"id": "B2/m07", "path": ["B2", "B2/m07"], "frac": [0.47, 0.18, 0.07, 0.12]}
HUGE = 10**400  # a JSON integer no float can hold: is_num accepts it, float() raises OverflowError


class ElementMarks(unittest.TestCase):
    """element_marks: where a figure pin's element is on its document's current map."""

    def test_an_element_where_it_was_pinned_is_ok_with_its_mark(self):
        """The same page and box as el.frac: ok, with the box as mark and the page."""
        r = {"id": 1, "page": 1, "frac": [0.48, 0.2, 0.04, 0.07], "el": EL}
        self.assertEqual(
            element_marks(r, element_follower(FIG)), {"mark": [0.47, 0.18, 0.07, 0.12], "mark_page": 1, "el_sync": "ok"}
        )

    def test_a_moved_element_gives_its_new_box_and_a_gone_one_only_lost(self):
        """Pinned at another box: moved, with the box it has now; an id the map lacks: lost and no mark."""
        r = {"id": 1, "page": 1, "el": {**EL, "frac": [0.4, 0.18, 0.07, 0.12]}}
        self.assertEqual(element_marks(r, element_follower(FIG))["el_sync"], "moved")
        self.assertEqual(
            element_marks(
                {"id": 1, "page": 1, "el": {"id": "B2/gone", "path": ["B2", "B2/gone"]}}, element_follower(FIG)
            ),
            {"el_sync": "lost"},
        )

    def test_without_the_elements_box_the_pins_own_frac_is_compared_and_never_ok_by_default(self):
        """An agent's el has no frac and its pin no frac either: the element is found, but never ok."""
        self.assertEqual(
            element_marks({"id": 1, "el": {"id": "B2/m07", "path": ["B2", "B2/m07"]}}, element_follower(FIG)),
            {"mark": [0.47, 0.18, 0.07, 0.12], "mark_page": 1, "el_sync": "moved"},
        )

    def test_nothing_without_a_well_formed_el_or_a_map(self):
        """No el, a malformed el or no loadable map: no fields at all."""
        self.assertEqual(element_marks({"id": 1, "page": 1, "frac": [0, 0, 1, 1]}, element_follower(FIG)), {})
        self.assertEqual(element_marks({"id": 1, "el": {"id": ""}}, element_follower(FIG)), {})
        self.assertEqual(element_marks({"id": 1, "el": EL}, None), {})

    def test_an_el_frac_that_is_not_usable_falls_back_to_the_pins_own_frac(self):
        """el.frac a NaN, an infinity or an oversized integer (shapes the store keeps): the pin's own frac is the box
        it is compared with - here equal to the element's, so ok - and nothing raises."""
        own = [0.47, 0.18, 0.07, 0.12]
        for bad in ([float("nan"), 0.18, 0.07, 0.12], [float("inf"), 0, 1, 1], [HUGE, 0.18, 0.07, 0.12]):
            r = {"id": 1, "page": 1, "frac": own, "el": {**EL, "frac": bad}}
            self.assertEqual(element_marks(r, element_follower(FIG))["el_sync"], "ok", bad)

    def test_an_el_frac_that_is_absent_falls_back_to_the_pins_own_frac(self):
        """el.frac missing: the pin's own frac decides - the element's box means ok, another box moved."""
        el = {"id": "B2/m07", "path": ["B2", "B2/m07"]}
        at = {"id": 1, "page": 1, "frac": [0.47, 0.18, 0.07, 0.12], "el": el}
        away = {"id": 1, "page": 1, "frac": [0.1, 0.1, 0.1, 0.1], "el": el}
        self.assertEqual(
            (
                element_marks(at, element_follower(FIG))["el_sync"],
                element_marks(away, element_follower(FIG))["el_sync"],
            ),
            ("ok", "moved"),
        )

    def test_no_usable_frac_anywhere_is_moved_and_never_raises(self):
        """Neither el.frac nor the pin's frac is a usable box (NaN, an oversized integer, a wrong length, a string, a
        boolean): the element is found and is never ok."""
        hostile = ([float("nan"), 0, 1, 1], [HUGE, 0, 1, 1], [0.47, 0.18, 0.07], "0.47,0.18,0.07,0.12", [True, 0, 1, 1])
        for bad in hostile:
            r = {"id": 1, "page": 1, "frac": bad, "el": {**EL, "frac": [float("nan"), 0, 1, 1]}}
            self.assertEqual(element_marks(r, element_follower(FIG))["el_sync"], "moved", bad)

    def test_a_tiny_element_at_the_page_origin_is_never_ok_for_a_pin_without_any_frac(self):
        """A pin on page 1 with an el but no el.frac and no frac is compared with NO_FRAC: an element at the page origin
        whose box is within FOLLOW_EPS of zero size must not read as where it was. Moved, with its box as the mark."""
        for w in (0.00005, 0.001):
            with self.subTest(size=w):
                tiny = FigureMap(
                    "figures.pdf",
                    "0" * 64,
                    (
                        MapPage(
                            1,
                            "B2",
                            None,
                            (
                                MapElement("B2", None, (0.0, 0.0, 1.0, 1.0), None, None, None, None),
                                MapElement("B2/dot", "B2", (0.0, 0.0, w, w), None, None, "Dot", None),
                            ),
                        ),
                    ),
                )
                r = {"id": 1, "page": 1, "el": {"id": "B2/dot", "path": ["B2", "B2/dot"]}}
                self.assertEqual(
                    element_marks(r, element_follower(tiny)),
                    {"mark": [0.0, 0.0, w, w], "mark_page": 1, "el_sync": "moved"},
                )

    def test_a_page_that_is_not_an_integer_is_compared_as_page_zero_and_never_raises(self):
        """A missing, boolean, string or oversized page cannot be the element's page: moved, with the element's own."""
        for bad in (None, True, "1", HUGE, 1.0):
            r = {"id": 1, "page": bad, "el": EL}
            got = element_marks(r, element_follower(FIG))
            self.assertEqual((got["el_sync"], got["mark_page"]), ("moved", 1), bad)

    def test_the_pin_on_another_page_than_its_element_is_moved(self):
        """The element is on page 1 now while the pin was placed on page 2 with the same box: moved."""
        self.assertEqual(element_marks({"id": 1, "page": 2, "el": EL}, element_follower(FIG))["el_sync"], "moved")

    def test_the_record_and_the_element_are_not_changed(self):
        """element_marks is a read: neither r nor its el changes."""
        r = {"id": 1, "page": 1, "frac": [0.1, 0.1, 0.1, 0.1], "el": {"id": "B2/m07", "path": ["B2", "B2/m07"]}}
        before = json.dumps(r, sort_keys=True)
        element_marks(r, element_follower(FIG))
        self.assertEqual(json.dumps(r, sort_keys=True), before)


class FigurePayload(unittest.TestCase):
    """pins_payload with figure maps: the fields follow the computed ones, each document's map asked once."""

    def test_marks_come_last_and_each_documents_map_is_asked_once_and_only_for_element_pins(self):
        """Two element pins of fig ask its map once; a pin without el and a LaTeX pin get nothing and ask nothing."""
        rows = [
            {"id": 1, "doc": "fig", "page": 1, "el": EL},
            {"id": 2, "doc": "fig", "el": EL},
            {"id": 3, "doc": "ms"},
            {"id": 4, "doc": "fig"},
        ]
        asked = []

        def figure_map(key):
            """Record the question; fig's map."""
            asked.append(key)
            return element_follower(FIG)

        out = pins_payload(rows, False, {}, shown, lambda r: r["doc"], lambda k: CUR, NOW, figure_map)
        self.assertEqual(asked, ["fig"])
        self.assertEqual(list(out[0])[-3:], ["mark", "mark_page", "el_sync"])
        self.assertNotIn("el_sync", out[2])
        self.assertNotIn("el_sync", out[3])

    def test_each_figure_document_is_asked_once_however_its_pins_are_interleaved(self):
        """Pins of two figure documents in an alternating order: each document's map is asked once, in the order the
        documents first appear, and each pin is followed on its own document's map."""
        other = FigureMap(
            "other.pdf",
            "0" * 64,
            (MapPage(1, "C1", None, (MapElement("C1", None, (0, 0, 1, 1), None, None, None, None),)),),
        )
        rows = [{"id": i, "doc": "fig" if i % 2 else "fig2", "page": 1, "el": EL} for i in range(1, 7)]
        asked = []

        def figure_map(key):
            """Record the question; fig's map for fig, another figure's map (without the element) for fig2."""
            asked.append(key)
            return element_follower(FIG if key == "fig" else other)

        out = pins_payload(rows, False, {}, shown, lambda r: r["doc"], lambda k: CUR, NOW, figure_map)
        self.assertEqual(asked, ["fig", "fig2"])
        self.assertEqual([o["el_sync"] for o in out], ["ok", "lost"] * 3)

    def test_a_document_whose_map_does_not_load_is_asked_once_and_its_pins_get_no_fields(self):
        """figure_map answers None for fig: asked once for both element pins, neither gets a field."""
        rows = [{"id": 1, "doc": "fig", "el": EL}, {"id": 2, "doc": "fig", "el": EL}]
        asked = []

        def figure_map(key):
            """Record the question; no map."""
            asked.append(key)

        out = pins_payload(rows, False, {}, shown, lambda r: r["doc"], lambda k: CUR, NOW, figure_map)
        self.assertEqual(asked, ["fig"])
        self.assertEqual([("mark" in o, "el_sync" in o) for o in out], [(False, False), (False, False)])

    def test_a_malformed_el_asks_nothing(self):
        """A pin whose el is not a well-formed element (a stored shape the record check lets through is one thing;
        a wrong shape another) does not ask for its document's map."""
        rows = [{"id": 1, "doc": "fig", "el": {"id": ""}}, {"id": 2, "doc": "fig", "el": "B2/m07"}]
        asked = []

        def figure_map(key):
            """Record the question; fig's map."""
            asked.append(key)
            return FIG

        out = pins_payload(rows, False, {}, shown, lambda r: r["doc"], lambda k: CUR, NOW, figure_map)
        self.assertEqual(asked, [])
        self.assertTrue(all("el_sync" not in o for o in out))

    def test_the_default_gives_no_document_a_map(self):
        """Without a figure_map argument no pin gets a field, whatever its el."""
        out = pins_payload(
            [{"id": 1, "doc": "fig", "el": EL}], False, {}, shown, lambda r: r["doc"], lambda k: CUR, NOW
        )
        self.assertNotIn("el_sync", out[0])

    def test_a_pin_view_with_a_map_changes_neither_the_record_nor_the_shown_copy(self):
        """pin_view of an element pin on a map that moved it: the record and its shown copy are the same afterwards,
        so the fields exist only in the answer (a render never writes)."""
        r = {"id": 1, "page": 1, "el": {**EL, "frac": [0.4, 0.18, 0.07, 0.12]}}
        show = shown(r)
        before = (json.dumps(r, sort_keys=True), json.dumps(show, sort_keys=True))
        rec = pin_view(r, show, [], False, "fig", NOW, element_follower(FIG))
        self.assertEqual(rec["el_sync"], "moved")
        self.assertEqual((json.dumps(r, sort_keys=True), json.dumps(show, sort_keys=True)), before)

    def test_a_pin_view_without_a_map_keeps_exactly_its_current_keys(self):
        """pin_view with no fmap (the Trash list and a change request's echo never pass one) adds no key, el or not."""
        rec = pin_view({"id": 1, "el": EL}, {"id": 1, "el": EL}, [], False, "fig", NOW)
        self.assertEqual(list(rec), ["id", "el", "rel", "est", "doc", "state", "addressed", "fyi"])


# ---------------------------------------------------------------- through server.py's wiring
#
# The Trash list (dropped_payload and GET /api/pins/dropped). These classes load server.py (helpers.ps) and drive the
# module through its bindings; the tests above call the module on its own.


class DroppedList(Base):
    """§B: GET /api/pins/dropped — returns dropped pins read-only, together with dropped_at/dropped_by."""

    def test_dropped_payload_includes_dropped_at_and_by(self):
        """A dropped pin retains its identifier, actor, and removal time in the list."""
        pid = self.add(note="oops")
        ps.APP.pin_trash.drop_pin(
            pid, post_authority(ps.APP.pin_trash.context().store, {"login": "alice", "name": "Wendy"}, "drop", pid)
        )
        out = ps.APP.pin_listing.dropped_payload()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], pid)
        self.assertEqual(out[0]["dropped_by"]["login"], "alice")
        self.assertIn("dropped_at", out[0])

    def test_dropped_payload_empty_when_nothing_dropped(self):
        """Live pins do not appear in the Trash list."""
        self.add()
        self.assertEqual(ps.APP.pin_listing.dropped_payload(), [])

    def test_dropped_payload_excludes_restored_pins(self):
        """Restoring a pin removes it from the Trash list."""
        pid = self.add()
        ps.APP.pin_trash.drop_pin(pid, post_authority(ps.APP.pin_trash.context().store, dict(LOCAL_ACTOR), "drop", pid))
        ps.APP.pin_trash.restore_pin(
            pid, post_authority(ps.APP.pin_trash.context().store, dict(LOCAL_ACTOR), "restore", pid)
        )
        self.assertEqual(ps.APP.pin_listing.dropped_payload(), [])

    def test_get_pins_dropped_endpoint_http(self):
        """The HTTP Trash response includes a dropped pin and its original note."""
        pid = self.add(note="secret-drop-note")
        ps.APP.pin_trash.drop_pin(
            pid, post_authority(ps.APP.pin_trash.context().store, {"login": "alice", "name": "Wendy"}, "drop", pid)
        )
        out = self.talk(req("GET", "/api/pins/dropped"))
        self.assertIn(b" 200 ", out)
        payload = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(len(payload["dropped"]), 1)
        self.assertEqual(payload["dropped"][0]["id"], pid)
        self.assertEqual(payload["dropped"][0]["note"], "secret-drop-note")

    def test_get_pins_dropped_respects_origin_check(self):
        """The Trash endpoint rejects a request with a foreign Host."""
        pid = self.add()
        ps.APP.pin_trash.drop_pin(pid, post_authority(ps.APP.pin_trash.context().store, dict(LOCAL_ACTOR), "drop", pid))
        out = self.talk(req("GET", "/api/pins/dropped", headers={"Host": "evil.example"}))
        self.assertIn(b" 403 ", out)


class PublicRecord(unittest.TestCase):
    """public_record: a stored record as the API returns it, placed where the composition root finds its file now."""

    def test_placed_record_gets_file_and_rel_path_and_loses_file_rel(self):
        """With a place, file and rel_path are the place's; the stored file_rel and rel_path never go out."""
        r = {"id": 1, "file": "/old/ms/sec/a.tex", "file_rel": "sec/a.tex", "rel_path": "stale", "rev": 3, "lo": 2}
        out = public_record(r, ("/new/ms/sec/a.tex", "sec/a.tex"))
        self.assertEqual(out, {"id": 1, "file": "/new/ms/sec/a.tex", "rev": 3, "lo": 2, "rel_path": "sec/a.tex"})
        self.assertEqual(list(out), ["id", "file", "rev", "lo", "rel_path"])
        self.assertEqual(r["rel_path"], "stale")  # r itself is never changed

    def test_unplaced_record_keeps_its_file_and_has_no_rel_path(self):
        """Without a place (a region pin, or a file not found) the stored file stays; rev defaults to 0."""
        for rev in (None, "2", True):
            r = {"id": 2, "pdf": "/ms/r.pdf", "file_rel": "x"} | ({} if rev is None else {"rev": rev})
            self.assertEqual(public_record(r, None), {"id": 2, "pdf": "/ms/r.pdf", "rev": 0}, rev)


class PublicRecordNumbers(unittest.TestCase):
    """public_record never lets a NaN, an Infinity or an oversized integer of any stored number reach the wire."""

    NAN, INF = float("nan"), float("inf")

    def test_a_frac_or_el_frac_with_any_non_finite_entry_reads_as_null_as_a_whole(self):
        """One non-finite entry (NaN, both infinities, an integer no float holds) makes the whole frac None - in the
        pin's own frac and in the element's - so no mark is drawn at a position made up from the finite entries; the
        element's other keys stay, in order."""
        for bad in (self.NAN, self.INF, -self.INF, HUGE):
            with self.subTest(bad=bad):
                r = {"id": 1, "rev": 0, "frac": [bad, 0.1, 0.2, 0.3], "el": {**EL, "frac": [0.0, 0.1, bad, 0.5]}}
                out = public_record(r, None)
                self.assertIsNone(out["frac"])
                self.assertIsNone(out["el"]["frac"])
                self.assertEqual(list(out["el"]), list(EL))

    def test_each_number_field_a_record_stores_reads_as_null_when_it_is_non_finite(self):
        """synced_at, score, claim_until, claim_ts and eta_ts (epoch seconds and scores the record check keeps as any
        JSON number) read None when NaN, an Infinity or an oversized integer, and come back as stored when finite."""
        for key in ("synced_at", "score", "claim_until", "claim_ts", "eta_ts"):
            for bad in (self.NAN, self.INF, -self.INF, HUGE):
                with self.subTest(key=key, bad=bad):
                    self.assertIsNone(public_record({"id": 1, key: bad}, None)[key])
            with self.subTest(key=key, finite=True):
                self.assertEqual(public_record({"id": 1, key: 12.5}, None)[key], 12.5)
                self.assertEqual(public_record({"id": 1, key: 0}, None)[key], 0)

    def test_a_non_finite_number_nested_in_any_other_field_reads_as_null(self):
        """A number the store keeps inside an anchor, a thread entry, a change or a field this version does not know
        (every one passes the record check untouched) is None when non-finite; its neighbours stay as stored."""
        r = {
            "id": 1,
            "anchor": {"score": self.NAN, "n": 3},
            "thread": [{"at": "t", "x": [self.INF, 1.5]}],
            "changes": [{"file": "a.tex", "lo": 1, "hi": 2, "w": -self.INF}],
            "future": {"deep": [{"v": self.NAN}, 0.25]},
        }
        out = public_record(r, None)
        self.assertEqual(out["anchor"], {"score": None, "n": 3})
        self.assertEqual(out["thread"], [{"at": "t", "x": [None, 1.5]}])
        self.assertEqual(out["changes"], [{"file": "a.tex", "lo": 1, "hi": 2, "w": None}])
        self.assertEqual(out["future"], {"deep": [{"v": None}, 0.25]})

    def test_the_answer_is_strict_json(self):
        """The encoded answer parses with a parser that refuses NaN and Infinity, as the browser's JSON.parse does."""
        r = {
            "id": 1,
            "frac": [self.NAN, 0, 0, 0],
            "el": {**EL, "frac": [self.INF, 0, 0, 0]},
            "score": self.NAN,
            "claim_until": -self.INF,
            "anchor": {"x": self.INF},
        }
        strict = json.loads(json.dumps(public_record(r, None)), parse_constant=self.refuse)
        self.assertEqual((strict["frac"], strict["el"]["frac"], strict["score"]), (None, None, None))
        self.assertEqual((strict["claim_until"], strict["anchor"]), (None, {"x": None}))

    @staticmethod
    def refuse(name):
        """parse_constant for json.loads: any NaN or Infinity token is an error."""
        raise AssertionError("non-finite constant on the wire: " + name)

    def test_finite_numbers_including_the_bounds_are_echoed_unchanged(self):
        """0.0, 1.0, 0 and 1 are finite: frac and el.frac come back equal, and the answer shares no list with r."""
        r = {"id": 1, "frac": [0.0, 1.0, 0, 1], "el": {**EL, "frac": [0.0, 1.0, 1, 0]}}
        out = public_record(r, None)
        self.assertEqual((out["frac"], out["el"]["frac"]), ([0.0, 1.0, 0, 1], [0.0, 1.0, 1, 0]))
        self.assertIsNot(out["frac"], r["frac"])

    def test_a_frac_that_is_not_a_list_or_not_a_number_is_left_as_stored(self):
        """Only non-finite numbers change: a string, a boolean, a wrong length and a non-object el pass as they are."""
        for frac in ("0.1,0.2", [True, 0, 1, 1], [0.1, 0.2], None):
            with self.subTest(frac=frac):
                self.assertEqual(public_record({"id": 1, "frac": frac}, None)["frac"], frac)
        self.assertEqual(public_record({"id": 1, "el": "B2/m07"}, None)["el"], "B2/m07")
        self.assertEqual(public_record({"id": 1, "el": {"id": "x"}}, None)["el"], {"id": "x"})

    def test_the_stored_record_is_not_changed(self):
        """r keeps its NaN, its nested el and its nested anchor number: the read never writes back."""
        r = {"id": 1, "frac": [self.NAN, 0, 0, 0], "el": {**EL, "frac": [self.INF, 0, 0, 0]}, "anchor": {"x": self.NAN}}
        public_record(r, None)
        self.assertTrue(math.isnan(r["frac"][0]) and math.isinf(r["el"]["frac"][0]) and math.isnan(r["anchor"]["x"]))


class LegacyClaimStart(Base):
    """A claim written before eta_min (claimed_at only) gets its claim_ts computed in GET /api/pins, never stored."""

    A = {"login": "alice@example.com", "name": "Wendy"}

    def test_pins_payload_fills_start_for_legacy_claims(self):
        """Legacy claims gain a read-only start epoch without rewriting their record."""
        pid = self.add()
        with ps.APP.RT.pin_lock:  # a claim shape written by a pre-eta server
            rows = records(ps.APP.read_pins()[0])
            r = find_pin(rows, pid)
            r.update(claimed_by=dict(self.A), claimed_at="2026-09-23 20:02:00", claim_until=time.time() + 3600)
            write_records(rows)
        rec = [x for x in ps.APP.pin_listing.pins_payload(ps.APP.snapshot_pins(), False) if x["id"] == pid][0]
        self.assertAlmostEqual(rec["claim_ts"], position.epoch("2026-09-23 20:02:00"), delta=0.01)
        self.assertNotIn("claim_ts", find_record(ps.APP.read_pins()[0], pid))  # a computed field — not stored


class InvalidReviewState(Base):
    """The store rejects a non-boolean review flag on an otherwise valid pin."""

    def test_non_boolean_review_is_refused_by_store(self):
        """A string review flag cannot become a stored pin state."""
        self.assertFalse(fits({"id": 1, "file": str(self.main), "lo": 1, "hi": 1, "review": "y"}))


if __name__ == "__main__":
    unittest.main()

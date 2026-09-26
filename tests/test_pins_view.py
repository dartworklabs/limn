"""limn.pins.view - the computed fields of GET /api/pins and the Trash list, called directly with explicit collaborators.

The answers through the HTTP handler are pinned in test_server.py, test_v022.py and, for the Trash list, DroppedList at
the end of this file (through server.py). Above it the pure functions get their record display, documents, estimation
facts and clock as arguments, and must never call a collaborator they do not need.

Run: uv run pytest -q tests/test_pins_view.py
"""
import json
import unittest

from limn.access import LOCAL_ACTOR
from limn.pins.model import parse_pin
from limn.pins.position import EstContext
from limn.pins.view import dropped_payload, pin_state, pin_view, pins_payload

from helpers import Base, ps, req

NOW = 1790000000.0
CUR = EstContext("b2", {"b1": {"build": "b1", "src_hash": "h1"}, "b2": {"build": "b2", "src_hash": "h2"}}, None, None)


def shown(r):
    """A stand-in for server.public(): a copy with a marker field, so the tests see that show's output is used."""
    return dict(r, shown=True)


class PinState(unittest.TestCase):
    """pin_state names the state type parse_pin gives - one rule for the API and the transitions."""

    RECORDS = ({}, {"done": False, "review": True}, {"done": True}, {"done": True, "review": False},
               {"done": True, "review": True}, {"done": 1, "review": "yes"}, {"review": True})

    def test_the_names_of_every_shape(self):
        """Not done is open (a stray review flag is meaningless); done with review true is review; else done."""
        self.assertEqual([pin_state(r) for r in self.RECORDS], ["open", "open", "done", "done", "review", "done", "open"])

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
        self.assertEqual(list(rec), ["id", "note", "kind_req", "note_mentions", "shown", "rel", "est", "doc", "state",
                                     "addressed", "fyi"])
        self.assertEqual((rec["rel"], rec["est"], rec["doc"], rec["state"]), ([{"id": 2, "rel": "inside"}], False,
                                                                              "main", "open"))
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
        self.rows = [{"id": 1, "doc": "a", "pdf_build": "b1"}, {"id": 2, "doc": "b", "pdf_build": "b2"},
                     {"id": 3, "doc": "a", "done": True, "pdf_build": "b2"}, {"id": 4, "doc": "a", "pdf_build": "b2"}]
        self.asked = []

    def est_context(self, key):
        """Estimation facts for document a; b is no longer served (None). Records each question."""
        self.asked.append(key)
        return CUR if key == "a" else None

    def payload(self, allp):
        """pins_payload over self.rows with a fixed rel and doc field."""
        return pins_payload(self.rows, allp, {1: [{"id": 4, "rel": "partial"}]}, shown, lambda r: r["doc"],
                            self.est_context, NOW)

    def test_open_pins_only_unless_all(self):
        """Without allp a done pin is left out; with it every row comes, in row order."""
        self.assertEqual([r["id"] for r in self.payload(False)], [1, 2, 4])
        self.assertEqual([r["id"] for r in self.payload(True)], [1, 2, 3, 4])

    def test_est_by_build_and_true_for_a_document_no_longer_served(self):
        """Another build of a different manuscript is estimated, the current build is not; unknown document: True."""
        got = {r["id"]: (r["est"], r["rel"], r["doc"], r["shown"]) for r in self.payload(False)}
        self.assertEqual(got, {1: (True, [{"id": 4, "rel": "partial"}], "a", True), 2: (True, [], "b", True),
                               4: (False, [], "a", True)})

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
        rows = [{"id": 1, "dropped_at": "2026-09-26 10:00:00"}, {"id": 2}, {"id": 3, "dropped_at": "2026-09-25 09:00:00"},
                {"id": 4, "dropped_at": "2026-09-25 09:00:00"}]
        expiry = {1: 100.12345, 3: 50.0, 4: None}
        out = dropped_payload(rows, shown, lambda r: expiry.get(r["id"]))
        self.assertEqual([r["id"] for r in out], [2, 3, 4, 1])
        self.assertEqual([r.get("expires_ts") for r in out], [None, 50.0, None, 100.123])
        self.assertTrue(all(r["shown"] for r in out))
        self.assertEqual(rows[0], {"id": 1, "dropped_at": "2026-09-26 10:00:00"})


# ---------------------------------------------------------------- through server.py's wiring
#
# The Trash list (dropped_payload and GET /api/pins/dropped). These classes load server.py (helpers.ps) and drive the
# module through its bindings; the tests above call the module on its own.

class DroppedList(Base):
    """§B: GET /api/pins/dropped — returns dropped pins read-only, together with dropped_at/dropped_by."""

    def test_dropped_payload_includes_dropped_at_and_by(self):
        pid = self.add(note="oops")
        ps.drop_pin(pid, {"login": "alice", "name": "Wendy"})
        out = ps.dropped_payload()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], pid)
        self.assertEqual(out[0]["dropped_by"]["login"], "alice")
        self.assertIn("dropped_at", out[0])

    def test_dropped_payload_empty_when_nothing_dropped(self):
        self.add()
        self.assertEqual(ps.dropped_payload(), [])

    def test_dropped_payload_excludes_restored_pins(self):
        pid = self.add()
        ps.drop_pin(pid, dict(LOCAL_ACTOR))
        ps.restore_pin(pid, dict(LOCAL_ACTOR))
        self.assertEqual(ps.dropped_payload(), [])

    def test_get_pins_dropped_endpoint_http(self):
        pid = self.add(note="secret-drop-note")
        ps.drop_pin(pid, {"login": "alice", "name": "Wendy"})
        out = self.talk(req("GET", "/api/pins/dropped"))
        self.assertIn(b" 200 ", out)
        payload = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(len(payload["dropped"]), 1)
        self.assertEqual(payload["dropped"][0]["id"], pid)
        self.assertEqual(payload["dropped"][0]["note"], "secret-drop-note")

    def test_get_pins_dropped_respects_origin_check(self):
        pid = self.add()
        ps.drop_pin(pid, dict(LOCAL_ACTOR))
        out = self.talk(req("GET", "/api/pins/dropped", headers={"Host": "evil.example"}))
        self.assertIn(b" 403 ", out)



if __name__ == "__main__":
    unittest.main()

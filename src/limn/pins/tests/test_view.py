"""limn.pins.listing.projection - the computed fields of GET /api/pins and the Trash list, called directly with explicit collaborators.

The answers through the HTTP handler are pinned in test_server.py, test_reply.py and test_trash.py; at the end of
this file, through server.py: the Trash list (DroppedList), a legacy claim's start (LegacyClaimStart) and a legacy
done pin's state (LegacyDoneState). Above it the pure functions get their record display, documents, estimation
facts and clock as arguments, and must never call a collaborator they do not need.

Run: uv run pytest -q src/limn/pins/tests/test_view.py
"""

import json
import time
import unittest

from limn.pins.listing.projection import dropped_payload, pin_state, pin_view, pins_payload, public_record
from limn.pins.location import position
from limn.pins.location.position import EstContext
from limn.pins.model import TrashedPin, parse_pin
from limn.pins.store import find_pin
from limn.security.access import LOCAL_ACTOR

from helpers import Base, find_record, fits, ps, records, req, write_records
from helpers_authority import post_authority

NOW = 1790000000.0
CUR = EstContext("b2", {"b1": {"build": "b1", "src_hash": "h1"}, "b2": {"build": "b2", "src_hash": "h2"}}, None, None)


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

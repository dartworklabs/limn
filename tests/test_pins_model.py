"""limn.pins.model - the state types lift the shared core and the fields only their state has, and write every record
back unchanged.

The round trip is the contract that lets the store parse records into typed states without a migration: a record
parsed and written back must give the same JSON line, byte for byte, with the store's own json.dumps settings
(limn.store.dump_jsonl) - unknown fields, field order, legacy and malformed values included
(docs/handbook/code-style-roadmap.md §R2).

The corpus tests/data/pin_records.jsonl holds one record for every distinct record shape (field names, order and
value kinds) that the full test suite read from or wrote to pins.jsonl and pins.dropped.jsonl, temp paths replaced.
The legacy shapes below add what the suite does not write any more.

Run: uv run pytest -q tests/test_pins_model.py
"""

import json
import unittest
from pathlib import Path

from limn.pins.model import (
    Claim,
    Close,
    Confirmation,
    DonePin,
    Dropped,
    LineSpan,
    OpenPin,
    PinCore,
    Region,
    ReviewPin,
    ThreadEntry,
    TrashedPin,
    parse_pin,
)

CORPUS = Path(__file__).parent / "data" / "pin_records.jsonl"
BY = {"login": "alice@example.com", "name": "Alice Kim"}
AGENT = {"login": "local", "name": "로컬/에이전트"}

# Record shapes older versions wrote or a hand edit can leave, each named for what it exercises.
LEGACY = {
    "done without a review field (before review existed)": {
        "file": "/ms/main.tex",
        "lo": 1,
        "hi": 2,
        "note": "n",
        "id": 1,
        "done": True,
    },
    "no doc (before several documents)": {"file": "/ms/main.tex", "lo": 1, "hi": 2, "note": "n", "id": 2},
    "old frac_build instead of pdf_build": {
        "file": "/ms/main.tex",
        "lo": 1,
        "hi": 2,
        "page": 1,
        "frac": [0.1, 0.2, 0.3, 0.4],
        "frac_build": "b1",
        "id": 3,
    },
    "claim without claim_ts (before eta)": {
        "id": 4,
        "claimed_by": BY,
        "claimed_at": "2026-09-22 10:00:00",
        "claim_until": 1790000000,
    },
    "string rev": {"id": 5, "rev": "3", "done": True, "review": True, "done_at": "2026-09-25 10:00:00"},
    "malformed claim_until": {"id": 6, "claimed_by": BY, "claim_until": "tomorrow", "claim_ts": 1.5, "eta_ts": None},
    "claim fields without claimed_by": {"id": 7, "claim_until": 1790000000.0, "eta_ts": 1790000100},
    "claimed_by that is not an object": {"id": 8, "claimed_by": "alice", "claim_until": 1790000000},
    "claim left on a closed pin (hand edit)": {"id": 9, "done": True, "claimed_by": BY, "claim_until": 1.0},
    "reopened pin keeping the last close's done_at/closed_by": {
        "id": 10,
        "done": False,
        "done_at": "2026-09-25 10:00:00",
        "closed_by": AGENT,
        "reopened_at": "2026-09-25 11:00:00",
        "reopened_by": BY,
    },
    "0.2.2 reopen that kept changes": {
        "id": 11,
        "done": False,
        "changes": [{"file": "/ms/main.tex", "lo": 1, "hi": 2}],
        "changes_at": "t",
    },
    "review false written out": {"id": 12, "done": True, "review": False, "done_at": "t", "closed_by": BY},
    "review that is not a boolean": {"id": 13, "done": True, "review": "yes"},
    "done that is truthy but not true": {"id": 14, "done": 1, "review": True},
    "confirmed_by without confirmed_at": {"id": 15, "done": True, "confirmed_by": BY},
    "close fields of the wrong kind": {
        "id": 16,
        "done": True,
        "done_at": 17,
        "closed_by": "local",
        "close_reply": ["x"],
        "close_ref": None,
        "changes": [1, 2],
        "changes_at": False,
    },
    "confirmation on an open pin (hand edit)": {"id": 17, "confirmed_by": BY, "confirmed_at": "t"},
    "unicode and floats as written": {"id": 18, "note": "수식 ∑ — é", "synced_at": 1.0, "score": 0.5e-7},
    "unknown future fields between known ones": {
        "id": 19,
        "x_future": {"nested": [1, {"a": None}]},
        "done": True,
        "y": True,
        "done_at": "t",
        "z": None,
    },
    "Trash copy": {
        "id": 20,
        "note": "n",
        "done": True,
        "done_at": "t",
        "closed_by": BY,
        "dropped_at": "2026-09-26 10:00:00",
        "dropped_by": BY,
    },
    "Trash copy with dropped_at in the middle": {"id": 21, "dropped_at": "t", "note": "n", "dropped_by": BY, "rev": 1},
    "Trash copy without dropped_by": {"id": 22, "dropped_at": "2026-09-26 10:00:00"},
    "Trash copy with an unreadable dropped_at": {"id": 23, "dropped_at": 5, "dropped_by": BY},
    "empty object": {},
    "region pin (view-only PDF)": {
        "pdf": "/ms/scan.pdf",
        "name": "scan.pdf",
        "kind": "region",
        "page": 2,
        "frac": [0.1, 0.2, 0.3, 0.05],
        "quote": "q",
        "note": "n",
        "id": 24,
        "file": None,
    },
    "region pin with a three-number frac": {"pdf": "/ms/scan.pdf", "page": 2, "frac": [0.1, 0.2, 0.3], "id": 25},
    "line pin with a string lo": {"file": "/ms/main.tex", "lo": "4", "hi": 5, "id": 26},
    "line pin with an empty file": {"file": "", "lo": 1, "hi": 1, "id": 27},
    "shared fields of the wrong kind": {
        "id": "28",
        "doc": 3,
        "note": None,
        "at": 5,
        "author": "alice",
        "rev": "3",
        "kind_req": "task",
        "assignee": ["alice"],
        "mentions": ["bob", 1],
        "anchor": [],
        "synced_at": "1",
        "stale": "yes",
        "sync": False,
    },
    "rev null and note null": {"id": 29, "rev": None, "note": None, "thread": None},
    "thread with an entry that is not an object": {"id": 30, "thread": [{"id": 1, "text": "a"}, "junk"]},
    "thread entries with unknown fields, odd order and malformed parts": {
        "id": 31,
        "thread": [
            {"text": "t", "id": 2, "x": [1], "at": "t", "by": AGENT},
            {"id": True, "by": "local", "at": 1, "text": None, "ev": "vote", "ref": 3, "mentions": "bob"},
            {"id": 3, "by": BY, "at": "t", "text": "", "ev": None, "mentions": ["bob"]},
            {},
        ],
    },
    "shared fields scattered between state fields": {
        "thread": [],
        "done": True,
        "rev": 2,
        "done_at": "t",
        "id": 32,
        "review": True,
        "hi": 3,
        "closed_by": BY,
        "lo": 1,
        "file": "/ms/a.tex",
    },
}


def line(record):
    """A record as the store writes it: dump_jsonl's json.dumps settings."""
    return json.dumps(record, ensure_ascii=False)


def corpus():
    """Every record of the captured corpus, as parsed JSON objects."""
    return [json.loads(text) for text in CORPUS.read_text(encoding="utf-8").splitlines() if text.strip()]


class RoundTrip(unittest.TestCase):
    """Parsing a record into its state and writing it back changes nothing, byte for byte."""

    def assert_round_trip(self, record):
        """The live parse and the Trash parse both write the record back as the same line."""
        self.assertEqual(line(parse_pin(record).record), line(record))
        self.assertEqual(line(TrashedPin.from_record(record).record), line(record))

    def test_every_corpus_record_comes_back_byte_identical(self):
        """Every shape the test suite reads or writes survives parse and write-back unchanged."""
        records = corpus()
        for index, record in enumerate(records):
            with self.subTest(index=index, id=record.get("id")):
                self.assert_round_trip(record)

    def test_the_corpus_covers_every_state_and_the_trash(self):
        """The corpus is not vacuous: it holds open, review and done pins, a claim, a confirmation and Trash copies."""
        records = corpus()
        states = {type(parse_pin(record)) for record in records}
        self.assertEqual(states, {OpenPin, ReviewPin, DonePin})
        self.assertTrue(any(isinstance(p, OpenPin) and p.claim for p in map(parse_pin, records)))
        self.assertTrue(any(isinstance(p, DonePin) and p.confirmation for p in map(parse_pin, records)))
        self.assertTrue(any(TrashedPin.from_record(record).dropped for record in records))
        cores = [parse_pin(record).core for record in records]
        self.assertTrue(any(isinstance(core.place, LineSpan) for core in cores))
        self.assertTrue(any(isinstance(core.place, Region) for core in cores))
        self.assertTrue(any(entry.ev and entry.ref for core in cores for entry in core.thread or ()))
        self.assertTrue(any(core.mentions and core.kind_req and core.assignee and core.anchor for core in cores))

    def test_every_legacy_shape_comes_back_byte_identical(self):
        """Shapes the suite no longer writes, malformed values included, survive unchanged and never fail to parse."""
        for name, record in LEGACY.items():
            with self.subTest(name):
                self.assert_round_trip(record)


class Lifting(unittest.TestCase):
    """Which state holds which field, and how a missing or malformed value is represented."""

    def test_an_open_pin_lifts_its_claim(self):
        """claimed_by makes a claim; its other fields come along, as stored."""
        pin = parse_pin({"id": 1, "claimed_by": BY, "claimed_at": "t", "claim_ts": 5, "claim_until": 9.5, "eta_ts": 7})
        self.assertEqual(pin, OpenPin(PinCore(id=1), Claim(BY, "t", 5, 9.5, 7), {}))

    def test_a_legacy_claim_has_no_start_and_a_malformed_part_stays_among_the_fields(self):
        """A claim before claim_ts has start None; an unusable claim_until reads as absent and is kept as stored."""
        pin = parse_pin(LEGACY["malformed claim_until"])
        self.assertEqual(pin, OpenPin(PinCore(id=6), Claim(BY, start=1.5), {"claim_until": "tomorrow", "eta_ts": None}))
        assert isinstance(pin, OpenPin) and pin.claim is not None
        self.assertFalse(pin.claim.holds(0))
        self.assertIsNone(parse_pin(LEGACY["claim without claim_ts (before eta)"]).claim.start)

    def test_claim_fields_without_a_claimed_by_object_are_no_claim(self):
        """Without a claimed_by object nothing is lifted: the fields are kept, and the pin is not claimed."""
        for name in ("claim fields without claimed_by", "claimed_by that is not an object"):
            with self.subTest(name):
                pin = parse_pin(LEGACY[name])
                kept = {key: value for key, value in LEGACY[name].items() if key != "id"}
                self.assertEqual(pin, OpenPin(PinCore(id=LEGACY[name]["id"]), None, kept))

    def test_closed_pins_lift_the_close_and_never_a_claim(self):
        """A review pin holds the close; stray claim fields on a closed pin are kept as stored, not as a claim."""
        record = {
            "id": 1,
            "done": True,
            "review": True,
            "done_at": "t",
            "closed_by": AGENT,
            "close_reply": "r",
            "close_ref": "c",
            "changes": [{"file": "/ms/a.tex", "lo": 1, "hi": 1}],
            "changes_at": "t",
        }
        self.assertEqual(
            parse_pin(record),
            ReviewPin(
                PinCore(id=1), Close("t", AGENT, "r", "c", record["changes"], "t"), {"done": True, "review": True}
            ),
        )
        stray = parse_pin(LEGACY["claim left on a closed pin (hand edit)"])
        self.assertEqual(
            stray, DonePin(PinCore(id=9), Close(), None, {"done": True, "claimed_by": BY, "claim_until": 1.0})
        )

    def test_a_legacy_close_lacks_its_parts_and_wrong_kinds_stay_among_the_fields(self):
        """A done record from before done_at has an empty close; close values of the wrong kind are not lifted."""
        self.assertEqual(parse_pin({"done": True}), DonePin(PinCore(), Close(), None, {"done": True}))
        record = LEGACY["close fields of the wrong kind"]
        kept = {key: value for key, value in record.items() if key != "id"}
        self.assertEqual(parse_pin(record), DonePin(PinCore(id=16), Close(), None, kept))

    def test_a_done_pin_lifts_a_whole_confirmation_only(self):
        """confirmed_by and confirmed_at are lifted together; one without the other stays among the fields."""
        pin = parse_pin({"id": 1, "done": True, "confirmed_by": BY, "confirmed_at": "t"})
        self.assertEqual(pin, DonePin(PinCore(id=1), Close(), Confirmation(BY, "t"), {"done": True}))
        half = LEGACY["confirmed_by without confirmed_at"]
        self.assertEqual(parse_pin(half), DonePin(PinCore(id=15), Close(), None, {"done": True, "confirmed_by": BY}))

    def test_an_open_pin_keeps_an_earlier_close_and_a_confirmation_as_plain_fields(self):
        """A reopened pin's done_at/closed_by and a hand-written confirmation are no close or confirmation of it."""
        for name in (
            "reopened pin keeping the last close's done_at/closed_by",
            "confirmation on an open pin (hand edit)",
        ):
            with self.subTest(name):
                kept = {key: value for key, value in LEGACY[name].items() if key != "id"}
                self.assertEqual(parse_pin(LEGACY[name]), OpenPin(PinCore(id=LEGACY[name]["id"]), None, kept))

    def test_a_trash_copy_lifts_the_drop_and_parses_the_pin_it_was(self):
        """dropped_at/dropped_by become the drop; the remaining fields are the pin in its state."""
        trashed = TrashedPin.from_record(LEGACY["Trash copy"])
        self.assertEqual(trashed.dropped, Dropped("2026-09-26 10:00:00", BY))
        self.assertEqual(trashed.pin, DonePin(PinCore(id=20, note="n"), Close("t", BY), None, {"done": True}))
        for name in ("Trash copy without dropped_by", "Trash copy with an unreadable dropped_at"):
            with self.subTest(name):
                self.assertIsNone(TrashedPin.from_record(LEGACY[name]).dropped)


class Core(unittest.TestCase):
    """The fields every state shares are typed on `core`; what does not have its stored kind stays among the fields."""

    def test_a_line_pin_lifts_its_shared_fields_and_keeps_the_rest(self):
        """id, doc, place, note, at, author, rev, kind_req, assignee, mentions, thread and the line-matching state are
        lifted in one PinCore; the location details, pdf_build and the edit marker stay among the fields."""
        anchor = {"head": "a", "tail": "b", "head_off": 0, "tail_off": 0}
        entry = {"id": 1, "by": BY, "at": "t", "text": "fixed", "ev": "close", "ref": "PR #1"}
        record = {
            "file": "/ms/main.tex",
            "name": "main.tex",
            "lo": 4,
            "hi": 5,
            "page": 1,
            "note": "n @bob",
            "at": "t0",
            "id": 7,
            "author": BY,
            "kind_req": "question",
            "mentions": ["bob@example.com"],
            "assignee": "agent",
            "anchor": anchor,
            "synced_at": 1790000000.0,
            "pdf_build": "b1",
            "doc": "main",
            "rev": 3,
            "stale": True,
            "sync": "lost",
            "thread": [entry],
            "edited_at": "t1",
        }
        pin = parse_pin(record)
        self.assertEqual(
            pin.core,
            PinCore(
                id=7,
                doc="main",
                place=LineSpan("/ms/main.tex", 4, 5),
                note="n @bob",
                at="t0",
                author=BY,
                rev=3,
                kind_req="question",
                assignee="agent",
                mentions=["bob@example.com"],
                thread=(ThreadEntry(1, BY, "t", "fixed", "close", "PR #1"),),
                anchor=anchor,
                synced_at=1790000000.0,
                stale=True,
                sync="lost",
            ),
        )
        self.assertEqual(pin.fields, {"name": "main.tex", "page": 1, "pdf_build": "b1", "edited_at": "t1"})

    def test_a_region_pin_is_placed_by_pdf_page_and_frac_lifted_whole(self):
        """A view-only PDF pin's place is its PDF, page and frac; a frac that is not four numbers lifts none of them,
        and a string lo lifts no line span either."""
        region = parse_pin(LEGACY["region pin (view-only PDF)"])
        self.assertEqual(region.core.place, Region("/ms/scan.pdf", 2, [0.1, 0.2, 0.3, 0.05]))
        self.assertEqual(region.fields["file"], None)
        for name, kept in (
            ("region pin with a three-number frac", {"pdf", "page", "frac"}),
            ("line pin with a string lo", {"file", "lo", "hi"}),
            ("line pin with an empty file", {"file", "lo", "hi"}),
        ):
            with self.subTest(name):
                pin = parse_pin(LEGACY[name])
                self.assertIsNone(pin.core.place)
                self.assertLessEqual(kept, pin.fields.keys())

    def test_shared_fields_of_the_wrong_kind_are_not_lifted(self):
        """A string id or rev, an unknown kind_req, a mention that is not a string ... read as absent, kept as stored."""
        wrong = parse_pin(LEGACY["shared fields of the wrong kind"])
        self.assertEqual((wrong.core, wrong.fields), (PinCore(), LEGACY["shared fields of the wrong kind"]))
        nulls = parse_pin(LEGACY["rev null and note null"])
        self.assertEqual((nulls.core, nulls.fields), (PinCore(id=29), {"rev": None, "note": None, "thread": None}))

    def test_thread_entries_are_lifted_one_by_one(self):
        """Each thread object is a ThreadEntry; its unknown or malformed parts (an ev outside THREAD_EVENTS too) stay
        among the entry's fields. A thread holding a non-object is not lifted at all."""
        pin = parse_pin(LEGACY["thread entries with unknown fields, odd order and malformed parts"])
        first, odd, empty_ev, empty = pin.core.thread
        self.assertEqual(first, ThreadEntry(2, AGENT, "t", "t", fields={"x": [1]}))
        self.assertEqual(
            odd,
            ThreadEntry(
                fields={"id": True, "by": "local", "at": 1, "text": None, "ev": "vote", "ref": 3, "mentions": "bob"}
            ),
        )
        self.assertEqual(empty_ev, ThreadEntry(3, BY, "t", "", mentions=["bob"], fields={"ev": None}))
        self.assertEqual(empty, ThreadEntry())
        junk = parse_pin(LEGACY["thread with an entry that is not an object"])
        self.assertIsNone(junk.core.thread)
        self.assertIn("thread", junk.fields)


class BuiltInCode(unittest.TestCase):
    """A state built directly, not parsed, writes its fields first and its lifted ones after; contradictions raise."""

    def test_a_built_state_writes_the_kept_fields_then_the_lifted_ones(self):
        """Without a stored order, kept fields come first in their own order, then the core and the state's group,
        each in stored-key order."""
        pin = OpenPin(PinCore(id=1, rev=0), Claim(BY, "t", until=9), {"name": "a.tex"})
        self.assertEqual(
            list(pin.record.items()),
            [("name", "a.tex"), ("id", 1), ("rev", 0), ("claimed_by", BY), ("claimed_at", "t"), ("claim_until", 9)],
        )

    def test_a_state_whose_stored_done_or_review_names_another_state_is_a_defect(self):
        """done/review stay among the fields as stored, and they must name the state that holds them."""
        with self.assertRaises(ValueError):
            OpenPin(PinCore(), None, {"done": True})
        with self.assertRaises(ValueError):
            ReviewPin(PinCore(), Close(), {"done": True})
        with self.assertRaises(ValueError):
            DonePin(PinCore(), Close(), None, {"done": True, "review": True})
        with self.assertRaises(ValueError):
            DonePin.from_record({"id": 1})

    def test_a_field_held_both_lifted_and_kept_is_a_defect(self):
        """Writing back would have to pick one of the two values, so such a state cannot be built."""
        with self.assertRaises(ValueError):
            OpenPin(PinCore(), Claim(BY), {"claimed_by": BY})
        with self.assertRaises(ValueError):
            OpenPin(PinCore(rev=1), None, {"rev": 2})
        with self.assertRaises(ValueError):
            OpenPin(PinCore(place=LineSpan("/ms/a.tex", 1, 2)), None, {"lo": 3})
        with self.assertRaises(ValueError):
            TrashedPin(OpenPin(PinCore(), None, {"dropped_at": "t"}), Dropped("t", BY))
        with self.assertRaises(ValueError):
            ThreadEntry(id=1, fields={"id": 2})


if __name__ == "__main__":
    unittest.main()

"""limn.pins - pin states and the confirm transition, tested directly with records and no store, clock or HTTP.

The HTTP contract of POST /api/pins/{id}/confirm (statuses, bodies, the stored line) is pinned in
test_server.py; here the pure decisions are checked on their own (coding rule R1).

Run: uv run pytest -q tests/test_pins_lifecycle.py
"""
import ast
import unittest
from pathlib import Path

import limn.pins
from limn.pins.lifecycle import AgentCannotConfirm, AlreadyDone, PinStillOpen, confirm, confirmer, thread_message
from limn.pins.model import Agent, DonePin, OpenPin, Person, ReviewPin, parse_pin

PINS_DIR = Path(limn.pins.__file__).parent
PURE_IMPORTS = {"__future__", "collections.abc", "dataclasses", "typing", "limn.pins.model"}
ALICE = Person("alice@example.com", "Alice Kim", "https://example.com/a.png")
AT = "2026-09-26 10:00:00"


def review_record(**extra):
    """A pin an agent closed: done and review are true, with one earlier thread entry."""
    record = {"id": 7, "file": "main.tex", "lo": 3, "hi": 4, "note": "fix", "done": True, "review": True,
              "thread": [{"id": 1, "by": {"login": "local", "name": "agent"}, "at": "t0", "text": "done", "ev": "close"}],
              "rev": 2}
    record.update(extra)
    return record


class Purity(unittest.TestCase):
    """The pin package must stay free of files, processes, the clock and the server."""

    def test_modules_import_only_pure_modules(self):
        """A file, subprocess, time or HTTP import would put an effect inside the domain (architecture.md stop signal)."""
        for path in PINS_DIR.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported |= {a.name for a in node.names}
                elif isinstance(node, ast.ImportFrom):
                    imported.add(node.module or "")
            self.assertLessEqual(imported, PURE_IMPORTS, path.name)


class States(unittest.TestCase):
    """parse_pin() follows pin_state(): the state is computed from done/review, never stored."""

    def test_open_when_not_done(self):
        """A record without done, or with done false, is open."""
        self.assertIsInstance(parse_pin({"id": 1}), OpenPin)
        self.assertIsInstance(parse_pin({"id": 1, "done": False, "review": True}), OpenPin)

    def test_review_only_when_done_and_review_is_true(self):
        """review must be the boolean true; a truthy string does not make a pin await review."""
        self.assertIsInstance(parse_pin({"done": True, "review": True}), ReviewPin)
        self.assertIsInstance(parse_pin({"done": True, "review": "yes"}), DonePin)

    def test_legacy_done_without_review_is_done(self):
        """A done record from before review existed stays done - reading it never migrates it."""
        self.assertIsInstance(parse_pin({"done": True}), DonePin)


class Confirmer(unittest.TestCase):
    """Who may confirm is decided before any pin is loaded."""

    def test_person_may_confirm(self):
        """A person comes back as the confirmer."""
        self.assertEqual(confirmer(ALICE), ALICE)

    def test_agent_is_refused(self):
        """An agent gets the refusal value, not an exception."""
        self.assertEqual(confirmer(Agent("local", "agent")), AgentCannotConfirm())


class Confirm(unittest.TestCase):
    """confirm() on each state, and what confirming a pin awaiting review writes."""

    def test_open_pin_is_refused_with_the_pin(self):
        """An open pin has nothing to confirm; the pin comes back for the 409 body."""
        pin = OpenPin({"id": 1, "done": False})
        self.assertEqual(confirm(pin, ALICE, AT), PinStillOpen(pin))

    def test_done_pin_comes_back_unchanged(self):
        """Confirming a done pin again is not an error and changes nothing."""
        pin = DonePin({"id": 1, "done": True})
        self.assertEqual(confirm(pin, ALICE, AT), AlreadyDone(pin))

    def test_review_pin_becomes_done_with_who_and_when(self):
        """The review flag goes, confirmed_by/confirmed_at are recorded, and rev goes up by one."""
        done = confirm(ReviewPin(review_record()), ALICE, AT)
        self.assertIsInstance(done, DonePin)
        self.assertNotIn("review", done.record)
        self.assertEqual(done.record["confirmed_by"], {"login": "alice@example.com", "name": "Alice Kim"})
        self.assertEqual(done.record["confirmed_at"], AT)
        self.assertEqual(done.record["rev"], 3)
        self.assertIsInstance(parse_pin(done.record), DonePin)

    def test_confirm_appends_one_confirm_entry_with_the_next_id(self):
        """The thread gains an ev=confirm entry by the confirmer (with avatar), numbered after the last entry."""
        done = confirm(ReviewPin(review_record()), ALICE, AT)
        self.assertEqual(done.record["thread"][-1], {"id": 2, "by": {"login": "alice@example.com", "name": "Alice Kim",
                                                                     "pic": "https://example.com/a.png"},
                                                     "at": AT, "text": "", "ev": "confirm"})
        self.assertEqual(len(done.record["thread"]), 2)

    def test_confirm_keeps_field_order_and_unknown_fields(self):
        """Existing fields keep their places and fields this version does not model survive; new ones go last."""
        record = review_record(future_field={"x": 1})
        done = confirm(ReviewPin(record), ALICE, AT)
        kept = [k for k in record if k != "review"]
        self.assertEqual(list(done.record)[:len(kept)], kept)
        self.assertEqual(list(done.record)[len(kept):], ["confirmed_by", "confirmed_at"])
        self.assertEqual(done.record["future_field"], {"x": 1})

    def test_confirm_does_not_touch_the_input_record(self):
        """A pure transition: the loaded record is left as it was."""
        record = review_record()
        before = repr(record)
        confirm(ReviewPin(record), ALICE, AT)
        self.assertEqual(repr(record), before)

    def test_missing_rev_counts_as_zero(self):
        """The store's rule for rev: missing or empty is 0, so the first change makes it 1."""
        record = review_record()
        del record["rev"]
        self.assertEqual(confirm(ReviewPin(record), ALICE, AT).record["rev"], 1)


class ThreadMessage(unittest.TestCase):
    """Thread entry ids are one past the largest integer id and never reused."""

    def test_id_skips_non_integer_ids(self):
        """Booleans and strings are not ids; the next id follows the largest real one."""
        thread = [{"id": 3}, {"id": True}, {"id": "9"}, "junk"]
        self.assertEqual(thread_message(thread, {"login": "a", "name": "A"}, AT)["id"], 4)

    def test_optional_fields_only_when_given(self):
        """ref and mentions appear only when passed; an empty text is stored as ''."""
        msg = thread_message(None, {"login": "a", "name": "A"}, AT, text="", ref="PR #1 (abc)", mentions=["b"])
        self.assertEqual(msg, {"id": 1, "by": {"login": "a", "name": "A"}, "at": AT, "text": "", "ref": "PR #1 (abc)",
                               "mentions": ["b"]})


if __name__ == "__main__":
    unittest.main()

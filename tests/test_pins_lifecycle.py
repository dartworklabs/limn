"""limn.pins - pin states and the confirm transition, tested directly with records and no store, clock or HTTP.

The HTTP contract of POST /api/pins/{id}/confirm (statuses, bodies, the stored line) is pinned in
test_server.py; here the pure decisions are checked on their own (coding rule R1).

Run: uv run pytest -q tests/test_pins_lifecycle.py
"""
import ast
import unittest
from pathlib import Path

import limn.pins
from limn.pins.lifecycle import (
    AgentCannotConfirm, AlreadyClosed, AlreadyDone, CloseRequest, PinClosed, PinReopened, PinStillOpen, Replied, ThreadFull,
    confirm, confirmer, decide_close, decide_reopen, decide_reply, evolve_close, evolve_reopen, evolve_reply,
    reopen_request, reopens_on_reply, thread_message,
)
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


AGENT = Agent("local", "agent")


def open_record(**extra):
    """An open pin with a claim in progress and one earlier reply."""
    record = {"id": 9, "file": "main.tex", "lo": 1, "hi": 2, "note": "n", "done": False,
              "claimed_by": {"login": "local"}, "claim_until": 1.0,
              "thread": [{"id": 4, "by": {"login": "x", "name": "X"}, "at": "t0", "text": "hi"}], "rev": 5}
    record.update(extra)
    return record


class Close(unittest.TestCase):
    """decide_close/evolve_close: who closes decides review; a closed pin is left alone."""

    def test_agent_close_awaits_review(self):
        """An agent's close without a review choice goes to review; a person's is done."""
        pin = OpenPin(open_record())
        self.assertTrue(decide_close(pin, AGENT, AT, CloseRequest()).review)
        self.assertFalse(decide_close(pin, ALICE, AT, CloseRequest()).review)

    def test_request_review_overrides_the_closer(self):
        """A remote agent arriving with a person's identity sends review=true; an agent may send false."""
        pin = OpenPin(open_record())
        self.assertTrue(decide_close(pin, ALICE, AT, CloseRequest(review=True)).review)
        self.assertFalse(decide_close(pin, AGENT, AT, CloseRequest(review=False)).review)

    def test_closed_pin_is_already_closed(self):
        """Closing again changes nothing, so the first closer stays on record."""
        for pin in (ReviewPin(review_record()), DonePin({"id": 1, "done": True})):
            self.assertEqual(decide_close(pin, ALICE, AT, CloseRequest(reply="again")), AlreadyClosed(pin))

    def test_evolve_close_records_the_close_and_clears_the_claim(self):
        """done/done_at/closed_by, reply/ref/changes with changes_at = done_at, an ev=close entry, no claim, rev + 1."""
        pin = OpenPin(open_record())
        event = PinClosed(ALICE, AT, "fixed", "PR #3 (abc)", ({"file": "/m/main.tex", "lo": 1, "hi": 1},), review=False)
        closed = evolve_close(pin, event)
        self.assertIsInstance(closed, DonePin)
        r = closed.record
        self.assertEqual((r["done"], r["done_at"], r["closed_by"]), (True, AT, {"login": "alice@example.com", "name": "Alice Kim"}))
        self.assertEqual((r["close_reply"], r["close_ref"], r["changes_at"]), ("fixed", "PR #3 (abc)", AT))
        self.assertEqual(r["changes"], [{"file": "/m/main.tex", "lo": 1, "hi": 1}])
        self.assertNotIn("claimed_by", r)
        self.assertNotIn("claim_until", r)
        self.assertEqual(r["thread"][-1]["id"], 5)
        self.assertEqual((r["thread"][-1]["ev"], r["thread"][-1]["text"], r["thread"][-1]["ref"]), ("close", "fixed", "PR #3 (abc)"))
        self.assertEqual(r["rev"], 6)

    def test_evolve_close_into_review(self):
        """review=True yields a ReviewPin with the review flag stored."""
        closed = evolve_close(OpenPin(open_record()), PinClosed(AGENT, AT, None, None, (), review=True))
        self.assertIsInstance(closed, ReviewPin)
        self.assertIs(closed.record["review"], True)
        self.assertNotIn("close_reply", closed.record)


class Reopen(unittest.TestCase):
    """decide_reopen/evolve_reopen: a reopen forgets the last close; only a closed pin gets a thread entry."""

    def test_reopening_a_closed_pin_records_reason_and_mentions(self):
        """Close fields, review and confirmation go; an ev=reopen entry carries the reason and its mentions."""
        pin = DonePin({**review_record(), "review": False, "close_reply": "x", "close_ref": "y",
                       "changes": [], "changes_at": "t", "confirmed_by": {"login": "b"}, "confirmed_at": "t"})
        event = decide_reopen(pin, ALICE, AT, "still wrong @Bob", ("bob@example.com",))
        self.assertEqual(event, PinReopened(ALICE, AT, "still wrong @Bob", ("bob@example.com",), was_closed=True))
        r = evolve_reopen(pin, event).record
        for key in ("close_reply", "close_ref", "changes", "changes_at", "review", "confirmed_by", "confirmed_at"):
            self.assertNotIn(key, r)
        self.assertEqual((r["done"], r["reopened_at"], r["reopened_by"]["login"]), (False, AT, "alice@example.com"))
        self.assertEqual((r["thread"][-1]["ev"], r["thread"][-1]["mentions"]), ("reopen", ["bob@example.com"]))
        self.assertEqual(r["rev"], 2)                     # evolve_reopen leaves rev to the caller

    def test_reopening_an_open_pin_adds_no_entry_but_the_request_bumps_rev(self):
        """An open pin gets who/when but no thread entry; POST /reopen still bumps rev, as before."""
        pin = OpenPin(open_record())
        event = decide_reopen(pin, ALICE, AT, "why", ())
        self.assertFalse(event.was_closed)
        self.assertEqual(len(evolve_reopen(pin, event).record["thread"]), 1)
        self.assertEqual(reopen_request(pin, event).record["rev"], 6)


class Reply(unittest.TestCase):
    """reopens_on_reply/decide_reply/evolve_reply: when a reply reopens, when the thread is full, what a reply writes."""

    def test_open_pin_never_reopens(self):
        """Nothing a reply says reopens an open pin, not even an explicit reopen."""
        self.assertFalse(reopens_on_reply(OpenPin(open_record()), True, [], True))

    def test_explicit_flag_decides_on_a_closed_pin(self):
        """reopen true/false from the request wins over the default rule."""
        pin = ReviewPin(review_record())
        self.assertTrue(reopens_on_reply(pin, False, ["b"], True))
        self.assertFalse(reopens_on_reply(pin, True, [], False))

    def test_default_rule_person_without_tags_on_a_non_question(self):
        """A person's untagged reply reopens; an agent's, a tagged one, or an answer to a question does not."""
        pin = ReviewPin(review_record())
        self.assertTrue(reopens_on_reply(pin, True, [], None))
        self.assertFalse(reopens_on_reply(pin, False, [], None))
        self.assertFalse(reopens_on_reply(pin, True, ["bob@example.com"], None))
        self.assertFalse(reopens_on_reply(ReviewPin(review_record(kind_req="question")), True, [], None))

    def test_decide_reply_reopens_or_refuses_or_replies(self):
        """A reopening reply is a PinReopened with the text as reason; a full thread refuses only a plain reply."""
        pin = ReviewPin(review_record())
        self.assertEqual(decide_reply(pin, ALICE, AT, "redo", ("b",), True, 0),
                         PinReopened(ALICE, AT, "redo", ("b",), was_closed=True))
        self.assertEqual(decide_reply(pin, ALICE, AT, "hi", (), False, 0), ThreadFull(0))
        self.assertEqual(decide_reply(pin, ALICE, AT, "hi", (), False, 5), Replied(ALICE, AT, "hi", ()))

    def test_transition_entries_do_not_count_toward_the_limit(self):
        """The close entry in the thread is not a reply, so a limit of 1 still allows the first reply."""
        self.assertIsInstance(decide_reply(ReviewPin(review_record()), ALICE, AT, "hi", (), False, 1), Replied)

    def test_evolve_reply_keeps_the_state_and_bumps_rev(self):
        """A plain reply adds one entry with its mentions and bumps rev; the pin stays in its state type."""
        pin = ReviewPin(review_record())
        replied = evolve_reply(pin, Replied(ALICE, AT, "looks good @Bob", ("bob@example.com",)))
        self.assertIsInstance(replied, ReviewPin)
        self.assertEqual(replied.record["thread"][-1]["mentions"], ["bob@example.com"])
        self.assertNotIn("ev", replied.record["thread"][-1])
        self.assertEqual(replied.record["rev"], 3)


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

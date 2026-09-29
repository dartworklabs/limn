"""Lifecycle commands preserve decisions, records and reply policy without effects."""

import unittest

from limn.features.pins.lifecycle.rules import (
    AgentCannotConfirm,
    AlreadyClosed,
    AlreadyDone,
    CloseRequest,
    PinClosed,
    PinReopened,
    PinStillOpen,
    Replied,
    ThreadFull,
    confirm,
    confirmer,
    decide_close,
    decide_reopen,
    decide_reply,
    evolve_close,
    evolve_reopen,
    evolve_reply,
    reopen_request,
    reopens_on_reply,
)
from limn.pins.model import Agent, DonePin, OpenPin, ReviewPin, parse_pin

from helpers import RULE_CASES, rec_for
from helpers_pin_rules import AGENT, ALICE_PERSON, AT, open_record, review_record


class Confirmer(unittest.TestCase):
    """Who may confirm is decided before any pin is loaded."""

    def test_person_may_confirm(self):
        """A person comes back as the confirmer."""
        self.assertEqual(confirmer(ALICE_PERSON), ALICE_PERSON)

    def test_agent_is_refused(self):
        """An agent gets the refusal value, not an exception."""
        self.assertEqual(confirmer(Agent("local", "agent")), AgentCannotConfirm())


class Confirm(unittest.TestCase):
    """confirm() on each state, and what confirming a pin awaiting review writes."""

    def test_open_pin_is_refused_with_the_pin(self):
        """An open pin has nothing to confirm; the pin comes back for the 409 body."""
        pin = OpenPin.from_record({"id": 1, "done": False})
        self.assertEqual(confirm(pin, ALICE_PERSON, AT), PinStillOpen(pin))

    def test_done_pin_comes_back_unchanged(self):
        """Confirming a done pin again is not an error and changes nothing."""
        pin = DonePin.from_record({"id": 1, "done": True})
        self.assertEqual(confirm(pin, ALICE_PERSON, AT), AlreadyDone(pin))

    def test_review_pin_becomes_done_with_who_and_when(self):
        """The review flag goes, confirmed_by/confirmed_at are recorded, and rev goes up by one."""
        done = confirm(ReviewPin.from_record(review_record()), ALICE_PERSON, AT)
        self.assertIsInstance(done, DonePin)
        self.assertNotIn("review", done.record)
        self.assertEqual(done.record["confirmed_by"], {"login": "alice@example.com", "name": "Alice Kim"})
        self.assertEqual(done.record["confirmed_at"], AT)
        self.assertEqual(done.record["rev"], 3)
        self.assertIsInstance(parse_pin(done.record), DonePin)

    def test_confirm_appends_one_confirm_entry_with_the_next_id(self):
        """The thread gains an ev=confirm entry by the confirmer (with avatar), numbered after the last entry."""
        done = confirm(ReviewPin.from_record(review_record()), ALICE_PERSON, AT)
        self.assertEqual(
            done.record["thread"][-1],
            {
                "id": 2,
                "by": {"login": "alice@example.com", "name": "Alice Kim", "pic": "https://example.com/a.png"},
                "at": AT,
                "text": "",
                "ev": "confirm",
            },
        )
        self.assertEqual(len(done.record["thread"]), 2)

    def test_confirm_keeps_field_order_and_unknown_fields(self):
        """Existing fields keep their places and fields this version does not model survive; new ones go last."""
        record = review_record(future_field={"x": 1})
        done = confirm(ReviewPin.from_record(record), ALICE_PERSON, AT)
        kept = [k for k in record if k != "review"]
        self.assertEqual(list(done.record)[: len(kept)], kept)
        self.assertEqual(list(done.record)[len(kept) :], ["confirmed_by", "confirmed_at"])
        self.assertEqual(done.record["future_field"], {"x": 1})

    def test_confirm_does_not_touch_the_input_record(self):
        """A pure transition: the loaded record is left as it was."""
        record = review_record()
        before = repr(record)
        confirm(ReviewPin.from_record(record), ALICE_PERSON, AT)
        self.assertEqual(repr(record), before)

    def test_missing_rev_counts_as_zero(self):
        """The store's rule for rev: missing or empty is 0, so the first change makes it 1."""
        record = review_record()
        del record["rev"]
        self.assertEqual(confirm(ReviewPin.from_record(record), ALICE_PERSON, AT).record["rev"], 1)


class Close(unittest.TestCase):
    """decide_close/evolve_close: who closes decides review; a closed pin is left alone."""

    def test_close_request_rejects_malformed_changes(self):
        """An internal close cannot write a changes shape that the store quarantines on its next read."""
        for changes in (({"file": "/ms/a.tex"},), ({"file": "/ms/a.tex", "lo": True, "hi": 3},)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                CloseRequest(changes=changes)

    def test_close_request_keeps_validated_changes_after_source_mutation(self):
        """Mutating the caller's range after validation cannot turn an accepted close into a broken stored pin."""
        source = {"file": "/ms/a.tex", "lo": 1, "hi": 3}
        request = CloseRequest(changes=(source,))
        source["lo"] = True
        self.assertIs(type(request.changes[0]["lo"]), int)
        with self.assertRaises(TypeError):
            request.changes[0]["lo"] = True

    def test_agent_close_awaits_review(self):
        """An agent's close without a review choice goes to review; a person's is done."""
        pin = OpenPin.from_record(open_record())
        self.assertTrue(decide_close(pin, AGENT, AT, CloseRequest()).review)
        self.assertFalse(decide_close(pin, ALICE_PERSON, AT, CloseRequest()).review)

    def test_request_review_overrides_the_closer(self):
        """A remote agent arriving with a person's identity sends review=true; an agent may send false."""
        pin = OpenPin.from_record(open_record())
        self.assertTrue(decide_close(pin, ALICE_PERSON, AT, CloseRequest(review=True)).review)
        self.assertFalse(decide_close(pin, AGENT, AT, CloseRequest(review=False)).review)

    def test_closed_pin_is_already_closed(self):
        """Closing again changes nothing, so the first closer stays on record."""
        for pin in (ReviewPin.from_record(review_record()), DonePin.from_record({"id": 1, "done": True})):
            self.assertEqual(decide_close(pin, ALICE_PERSON, AT, CloseRequest(reply="again")), AlreadyClosed(pin))

    def test_evolve_close_records_the_close_and_clears_the_claim(self):
        """done/done_at/closed_by, reply/ref/changes with changes_at = done_at, an ev=close entry, no claim, rev + 1."""
        pin = OpenPin.from_record(open_record())
        event = PinClosed(
            ALICE_PERSON, AT, "fixed", "PR #3 (abc)", ({"file": "/m/main.tex", "lo": 1, "hi": 1},), review=False
        )
        closed = evolve_close(pin, event)
        self.assertIsInstance(closed, DonePin)
        r = closed.record
        self.assertEqual(
            (r["done"], r["done_at"], r["closed_by"]), (True, AT, {"login": "alice@example.com", "name": "Alice Kim"})
        )
        self.assertEqual((r["close_reply"], r["close_ref"], r["changes_at"]), ("fixed", "PR #3 (abc)", AT))
        self.assertEqual(r["changes"], [{"file": "/m/main.tex", "lo": 1, "hi": 1}])
        self.assertNotIn("claimed_by", r)
        self.assertNotIn("claim_until", r)
        self.assertEqual(r["thread"][-1]["id"], 5)
        self.assertEqual(
            (r["thread"][-1]["ev"], r["thread"][-1]["text"], r["thread"][-1]["ref"]), ("close", "fixed", "PR #3 (abc)")
        )
        self.assertEqual(r["rev"], 6)

    def test_evolve_close_into_review(self):
        """review=True yields a ReviewPin with the review flag stored."""
        closed = evolve_close(OpenPin.from_record(open_record()), PinClosed(AGENT, AT, None, None, (), review=True))
        self.assertIsInstance(closed, ReviewPin)
        self.assertIs(closed.record["review"], True)
        self.assertNotIn("close_reply", closed.record)

    def test_evolve_close_rejects_a_pin_already_closed(self):
        """Applying a close event directly to a closed state cannot overwrite its first closer or time."""
        event = PinClosed(ALICE_PERSON, AT, "again", None, (), review=False)
        for pin in (ReviewPin.from_record(review_record()), DonePin.from_record({"id": 1, "done": True})):
            with self.subTest(state=pin.state), self.assertRaises(ValueError):
                evolve_close(pin, event)


class Reopen(unittest.TestCase):
    """decide_reopen/evolve_reopen: a reopen forgets the last close; only a closed pin gets a thread entry."""

    def test_reopening_a_closed_pin_records_reason_and_mentions(self):
        """Close fields, review and confirmation go; an ev=reopen entry carries the reason and its mentions."""
        pin = DonePin.from_record(
            {
                **review_record(),
                "review": False,
                "close_reply": "x",
                "close_ref": "y",
                "changes": [],
                "changes_at": "t",
                "confirmed_by": {"login": "b"},
                "confirmed_at": "t",
            }
        )
        event = decide_reopen(pin, ALICE_PERSON, AT, "still wrong @Bob", ("bob@example.com",))
        self.assertEqual(
            event, PinReopened(ALICE_PERSON, AT, "still wrong @Bob", ("bob@example.com",), was_closed=True)
        )
        r = evolve_reopen(pin, event).record
        for key in ("close_reply", "close_ref", "changes", "changes_at", "review", "confirmed_by", "confirmed_at"):
            self.assertNotIn(key, r)
        self.assertEqual((r["done"], r["reopened_at"], r["reopened_by"]["login"]), (False, AT, "alice@example.com"))
        self.assertEqual((r["thread"][-1]["ev"], r["thread"][-1]["mentions"]), ("reopen", ["bob@example.com"]))
        self.assertEqual(r["rev"], 2)  # evolve_reopen leaves rev to the caller

    def test_reopening_an_open_pin_adds_no_entry_but_the_request_bumps_rev(self):
        """An open pin gets who/when but no thread entry; POST /reopen still bumps rev, as before."""
        pin = OpenPin.from_record(open_record())
        event = decide_reopen(pin, ALICE_PERSON, AT, "why", ())
        self.assertFalse(event.was_closed)
        self.assertEqual(len(evolve_reopen(pin, event).record["thread"]), 1)
        self.assertEqual(reopen_request(pin, event).record["rev"], 6)


class Reply(unittest.TestCase):
    """reopens_on_reply/decide_reply/evolve_reply: when a reply reopens, when the thread is full, what a reply writes."""

    def test_open_pin_never_reopens(self):
        """Nothing a reply says reopens an open pin, not even an explicit reopen."""
        self.assertFalse(reopens_on_reply(OpenPin.from_record(open_record()), True, [], True))

    def test_explicit_flag_decides_on_a_closed_pin(self):
        """reopen true/false from the request wins over the default rule."""
        pin = ReviewPin.from_record(review_record())
        self.assertTrue(reopens_on_reply(pin, False, ["b"], True))
        self.assertFalse(reopens_on_reply(pin, True, [], False))

    def test_default_rule_person_without_tags_on_a_non_question(self):
        """A person's untagged reply reopens; an agent's, a tagged one, or an answer to a question does not."""
        pin = ReviewPin.from_record(review_record())
        self.assertTrue(reopens_on_reply(pin, True, [], None))
        self.assertFalse(reopens_on_reply(pin, False, [], None))
        self.assertFalse(reopens_on_reply(pin, True, ["bob@example.com"], None))
        self.assertFalse(reopens_on_reply(ReviewPin.from_record(review_record(kind_req="question")), True, [], None))

    def test_decide_reply_reopens_or_refuses_or_replies(self):
        """A reopening reply is a PinReopened with the text as reason; a full thread refuses only a plain reply."""
        pin = ReviewPin.from_record(review_record())
        self.assertEqual(
            decide_reply(pin, ALICE_PERSON, AT, "redo", ("b",), True, 0),
            PinReopened(ALICE_PERSON, AT, "redo", ("b",), was_closed=True),
        )
        self.assertEqual(decide_reply(pin, ALICE_PERSON, AT, "hi", (), False, 0), ThreadFull(0))
        self.assertEqual(decide_reply(pin, ALICE_PERSON, AT, "hi", (), False, 5), Replied(ALICE_PERSON, AT, "hi", ()))

    def test_transition_entries_do_not_count_toward_the_limit(self):
        """The close entry in the thread is not a reply, so a limit of 1 still allows the first reply."""
        self.assertIsInstance(
            decide_reply(ReviewPin.from_record(review_record()), ALICE_PERSON, AT, "hi", (), False, 1), Replied
        )

    def test_evolve_reply_keeps_the_state_and_bumps_rev(self):
        """A plain reply adds one entry with its mentions and bumps rev; the pin stays in its state type."""
        pin = ReviewPin.from_record(review_record())
        replied = evolve_reply(pin, Replied(ALICE_PERSON, AT, "looks good @Bob", ("bob@example.com",)))
        self.assertIsInstance(replied, ReviewPin)
        self.assertEqual(replied.record["thread"][-1]["mentions"], ["bob@example.com"])
        self.assertNotIn("ev", replied.record["thread"][-1])
        self.assertEqual(replied.record["rev"], 3)


class ReplyRule(unittest.TestCase):
    """Every row of the reply rule table through stored-state parsing and reopens_on_reply()."""

    def test_every_row_of_the_rule_table(self):
        for st, kind, human, ment, ov, want in RULE_CASES:
            with self.subTest(state=st, kind=kind, human=human, mentioned=ment, override=ov):
                self.assertIs(reopens_on_reply(parse_pin(rec_for(st, kind)), human, ment, ov), want)

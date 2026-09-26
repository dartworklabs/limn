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
    AgentCannotConfirm, AlreadyClosed, AlreadyDone, AlreadyLive, ClaimClosedPin, ClaimedByOther, ClaimRequest, CloseRequest, NotClaimed,
    PinClosed, PinReopened, PinStillOpen, Replied, ThreadFull, claim, claim_holds, confirm, confirmer, decide_close, decide_reopen, decide_reply, evolve_close, evolve_reopen, evolve_reply,
    reopen_request, reopens_on_reply, thread_message, unclaim, drop, find_trashed, restore, NotInTrash,
)
from limn.pins.model import Agent, DonePin, OpenPin, Person, ReviewPin, TrashedPin, parse_pin

PINS_DIR = Path(limn.pins.__file__).parent
# datetime only parses stored times (limn.pins.position.epoch - never now()); limn.mapping is pure (tests/test_mapping.py).
PURE_IMPORTS = {"__future__", "collections.abc", "dataclasses", "datetime", "math", "typing", "limn.pins.model",
                "limn.pins.lifecycle", "limn.guidance", "limn.mapping"}   # the last two: pure text modules render.py uses (checked below)
# What the non-pins modules the package imports may import in turn - string work only, no files, processes or clock.
# pathlib is there for PurePath alone (guidance.shell_path); Path would reach the file system.
PURE_TEXT_IMPORTS = {"__future__", "collections.abc", "typing", "re", "shlex", "pathlib"}
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

    def test_text_modules_the_package_imports_are_pure_too(self):
        """limn.guidance and limn.mapping (imported by render.py) do string work only; from pathlib only PurePath."""
        for path in (PINS_DIR.parent / "guidance.py", PINS_DIR.parent / "mapping.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported, from_pathlib = set(), set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported |= {a.name for a in node.names}
                elif isinstance(node, ast.ImportFrom):
                    imported.add(node.module or "")
                    if node.module == "pathlib":
                        from_pathlib |= {a.name for a in node.names}
            self.assertLessEqual(imported, PURE_TEXT_IMPORTS, path.name)
            self.assertLessEqual(from_pathlib, {"PurePath"}, path.name)
            self.assertNotIn("pathlib", {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names})


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
        pin = OpenPin.from_record({"id": 1, "done": False})
        self.assertEqual(confirm(pin, ALICE, AT), PinStillOpen(pin))

    def test_done_pin_comes_back_unchanged(self):
        """Confirming a done pin again is not an error and changes nothing."""
        pin = DonePin.from_record({"id": 1, "done": True})
        self.assertEqual(confirm(pin, ALICE, AT), AlreadyDone(pin))

    def test_review_pin_becomes_done_with_who_and_when(self):
        """The review flag goes, confirmed_by/confirmed_at are recorded, and rev goes up by one."""
        done = confirm(ReviewPin.from_record(review_record()), ALICE, AT)
        self.assertIsInstance(done, DonePin)
        self.assertNotIn("review", done.record)
        self.assertEqual(done.record["confirmed_by"], {"login": "alice@example.com", "name": "Alice Kim"})
        self.assertEqual(done.record["confirmed_at"], AT)
        self.assertEqual(done.record["rev"], 3)
        self.assertIsInstance(parse_pin(done.record), DonePin)

    def test_confirm_appends_one_confirm_entry_with_the_next_id(self):
        """The thread gains an ev=confirm entry by the confirmer (with avatar), numbered after the last entry."""
        done = confirm(ReviewPin.from_record(review_record()), ALICE, AT)
        self.assertEqual(done.record["thread"][-1], {"id": 2, "by": {"login": "alice@example.com", "name": "Alice Kim",
                                                                     "pic": "https://example.com/a.png"},
                                                     "at": AT, "text": "", "ev": "confirm"})
        self.assertEqual(len(done.record["thread"]), 2)

    def test_confirm_keeps_field_order_and_unknown_fields(self):
        """Existing fields keep their places and fields this version does not model survive; new ones go last."""
        record = review_record(future_field={"x": 1})
        done = confirm(ReviewPin.from_record(record), ALICE, AT)
        kept = [k for k in record if k != "review"]
        self.assertEqual(list(done.record)[:len(kept)], kept)
        self.assertEqual(list(done.record)[len(kept):], ["confirmed_by", "confirmed_at"])
        self.assertEqual(done.record["future_field"], {"x": 1})

    def test_confirm_does_not_touch_the_input_record(self):
        """A pure transition: the loaded record is left as it was."""
        record = review_record()
        before = repr(record)
        confirm(ReviewPin.from_record(record), ALICE, AT)
        self.assertEqual(repr(record), before)

    def test_missing_rev_counts_as_zero(self):
        """The store's rule for rev: missing or empty is 0, so the first change makes it 1."""
        record = review_record()
        del record["rev"]
        self.assertEqual(confirm(ReviewPin.from_record(record), ALICE, AT).record["rev"], 1)


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
        pin = OpenPin.from_record(open_record())
        self.assertTrue(decide_close(pin, AGENT, AT, CloseRequest()).review)
        self.assertFalse(decide_close(pin, ALICE, AT, CloseRequest()).review)

    def test_request_review_overrides_the_closer(self):
        """A remote agent arriving with a person's identity sends review=true; an agent may send false."""
        pin = OpenPin.from_record(open_record())
        self.assertTrue(decide_close(pin, ALICE, AT, CloseRequest(review=True)).review)
        self.assertFalse(decide_close(pin, AGENT, AT, CloseRequest(review=False)).review)

    def test_closed_pin_is_already_closed(self):
        """Closing again changes nothing, so the first closer stays on record."""
        for pin in (ReviewPin.from_record(review_record()), DonePin.from_record({"id": 1, "done": True})):
            self.assertEqual(decide_close(pin, ALICE, AT, CloseRequest(reply="again")), AlreadyClosed(pin))

    def test_evolve_close_records_the_close_and_clears_the_claim(self):
        """done/done_at/closed_by, reply/ref/changes with changes_at = done_at, an ev=close entry, no claim, rev + 1."""
        pin = OpenPin.from_record(open_record())
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
        closed = evolve_close(OpenPin.from_record(open_record()), PinClosed(AGENT, AT, None, None, (), review=True))
        self.assertIsInstance(closed, ReviewPin)
        self.assertIs(closed.record["review"], True)
        self.assertNotIn("close_reply", closed.record)


class Reopen(unittest.TestCase):
    """decide_reopen/evolve_reopen: a reopen forgets the last close; only a closed pin gets a thread entry."""

    def test_reopening_a_closed_pin_records_reason_and_mentions(self):
        """Close fields, review and confirmation go; an ev=reopen entry carries the reason and its mentions."""
        pin = DonePin.from_record({**review_record(), "review": False, "close_reply": "x", "close_ref": "y",
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
        pin = OpenPin.from_record(open_record())
        event = decide_reopen(pin, ALICE, AT, "why", ())
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
        self.assertEqual(decide_reply(pin, ALICE, AT, "redo", ("b",), True, 0),
                         PinReopened(ALICE, AT, "redo", ("b",), was_closed=True))
        self.assertEqual(decide_reply(pin, ALICE, AT, "hi", (), False, 0), ThreadFull(0))
        self.assertEqual(decide_reply(pin, ALICE, AT, "hi", (), False, 5), Replied(ALICE, AT, "hi", ()))

    def test_transition_entries_do_not_count_toward_the_limit(self):
        """The close entry in the thread is not a reply, so a limit of 1 still allows the first reply."""
        self.assertIsInstance(decide_reply(ReviewPin.from_record(review_record()), ALICE, AT, "hi", (), False, 1), Replied)

    def test_evolve_reply_keeps_the_state_and_bumps_rev(self):
        """A plain reply adds one entry with its mentions and bumps rev; the pin stays in its state type."""
        pin = ReviewPin.from_record(review_record())
        replied = evolve_reply(pin, Replied(ALICE, AT, "looks good @Bob", ("bob@example.com",)))
        self.assertIsInstance(replied, ReviewPin)
        self.assertEqual(replied.record["thread"][-1]["mentions"], ["bob@example.com"])
        self.assertNotIn("ev", replied.record["thread"][-1])
        self.assertEqual(replied.record["rev"], 3)


NOW = 1_790_000_000.0


class Claim(unittest.TestCase):
    """claim/unclaim: who holds the in-progress marker, for how long, and what a new claim forgets."""

    def test_closed_pin_cannot_be_claimed(self):
        """Claiming a review or done pin is refused with the pin."""
        pin = ReviewPin.from_record(review_record())
        self.assertEqual(claim(pin, ALICE, NOW, AT, ClaimRequest(30), None), ClaimClosedPin(pin))

    def test_new_claim_replaces_every_earlier_claim_field(self):
        """An expired claim by someone else is dropped whole - its estimate must not survive into the new claim."""
        record = open_record(claimed_by={"login": "x"}, claim_until=NOW - 1, eta_ts=NOW - 100, claimed_at="old", claim_ts=1.0)
        r = claim(OpenPin.from_record(record), ALICE, NOW, AT, ClaimRequest(30), None).record
        self.assertEqual((r["claimed_at"], r["claim_ts"], r["claim_until"]), (AT, NOW, NOW + 1800))
        self.assertEqual(r["claimed_by"], {"login": "alice@example.com", "name": "Alice Kim"})
        self.assertNotIn("eta_ts", r)
        self.assertEqual(r["rev"], 6)

    def test_live_claim_by_someone_else_is_refused_with_its_details(self):
        """The refusal says who holds it, until when, and their estimate."""
        record = open_record(claimed_by={"login": "bob@example.com"}, claim_until=NOW + 60, eta_ts=NOW + 30)
        self.assertEqual(claim(OpenPin.from_record(record), ALICE, NOW, AT, ClaimRequest(30), None),
                         ClaimedByOther({"login": "bob@example.com"}, NOW + 60, NOW + 30))

    def test_same_identity_extends_and_keeps_the_start(self):
        """Extending keeps claimed_at/claim_ts, re-measures claim_until, and keeps the estimate unless a new one is given."""
        record = open_record(claimed_by={"login": "alice@example.com"}, claim_until=NOW + 60, claimed_at="start",
                             claim_ts=NOW - 600, eta_ts=NOW + 10)
        r = claim(OpenPin.from_record(record), ALICE, NOW, AT, ClaimRequest(20), None).record
        self.assertEqual((r["claimed_at"], r["claim_ts"], r["claim_until"], r["eta_ts"]), ("start", NOW - 600, NOW + 1200, NOW + 10))
        r = claim(OpenPin.from_record(record), ALICE, NOW, AT, ClaimRequest(20, eta_min=5), None).record
        self.assertEqual(r["eta_ts"], NOW + 300)

    def test_extending_a_legacy_claim_backfills_its_start(self):
        """A claim written before claim_ts existed gets claim_ts from its claimed_at, or from now if that is unreadable."""
        record = open_record(claimed_by={"login": "alice@example.com"}, claim_until=NOW + 60, claimed_at="x")
        del record["claim_until"]
        record["claim_until"] = NOW + 60
        self.assertEqual(claim(OpenPin.from_record(record), ALICE, NOW, AT, ClaimRequest(20), NOW - 99).record["claim_ts"], NOW - 99)
        self.assertEqual(claim(OpenPin.from_record(record), ALICE, NOW, AT, ClaimRequest(20), None).record["claim_ts"], NOW)

    def test_claim_holds_only_until_claim_until(self):
        """A claim holds while claim_until is a number in the future."""
        self.assertTrue(claim_holds({"claim_until": NOW + 1}, NOW))
        self.assertFalse(claim_holds({"claim_until": NOW}, NOW))
        self.assertFalse(claim_holds({"claim_until": True}, NOW))

    def test_unclaim_clears_and_bumps_rev_only_when_there_was_a_claim(self):
        """Unclaiming a claimed pin writes; an unclaimed pin comes back as NotClaimed with any stray field cleared."""
        cleared = unclaim(OpenPin.from_record({"id": 1, "claimed_by": {"login": "a"}, "claim_until": 1.0, "rev": 2}))
        self.assertEqual(cleared, OpenPin.from_record({"id": 1, "rev": 3}))
        self.assertEqual(unclaim(OpenPin.from_record({"id": 1, "claim_until": 1.0})), NotClaimed(OpenPin.from_record({"id": 1})))

    def test_a_closed_pin_has_no_claim_to_clear(self):
        """Every close clears the claim, so claim fields on a closed pin (a hand-edited line) are not a claim: unclaim
        answers NotClaimed with them cleared from the shown pin, and nothing is written, rev included."""
        stray = {"id": 1, "done": True, "claimed_by": {"login": "a"}, "claim_until": 1.0, "rev": 2}
        self.assertEqual(unclaim(DonePin.from_record(stray)),
                         NotClaimed(DonePin.from_record({"id": 1, "done": True, "rev": 2})))


class Trash(unittest.TestCase):
    """drop/find_trashed/restore: what the Trash keeps, which copy comes back, and when it cannot."""

    def test_drop_keeps_the_record_without_its_claim_and_stamps_who_and_when(self):
        """A claim is never left behind in the Trash; dropped_at/dropped_by go last."""
        trashed = drop(OpenPin.from_record(open_record()), ALICE, AT)
        self.assertNotIn("claimed_by", trashed.record)
        self.assertEqual(list(trashed.record)[-2:], ["dropped_at", "dropped_by"])
        self.assertEqual(trashed.record["dropped_by"], {"login": "alice@example.com", "name": "Alice Kim"})

    def test_find_trashed_takes_the_newest_copy(self):
        """A pin deleted twice comes back as its last copy; an id with no copy is NotInTrash."""
        trash = [{"id": 3, "note": "old"}, {"id": 4}, {"id": 3, "note": "new"}]
        self.assertEqual(find_trashed(trash, 3), TrashedPin.from_record({"id": 3, "note": "new"}))
        self.assertEqual(find_trashed(trash, 9), NotInTrash(9))

    def test_restore_brings_back_the_state_and_bumps_rev(self):
        """dropped_at/by go, restored_at/by are recorded, rev goes up, and the pin is in the state it had."""
        trashed = TrashedPin.from_record({**review_record(), "dropped_at": "t", "dropped_by": {"login": "x"}})
        restored = restore(trashed, False, ALICE, AT)
        self.assertIsInstance(restored, ReviewPin)
        self.assertNotIn("dropped_at", restored.record)
        self.assertEqual((restored.record["restored_at"], restored.record["rev"]), (AT, 3))

    def test_restore_refuses_an_id_that_is_live(self):
        """If the id is already among the live pins, nothing is restored."""
        self.assertEqual(restore(TrashedPin.from_record({"id": 5}), True, ALICE, AT), AlreadyLive(5))


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

"""Pin claims decisions preserve records and return explicit refusals without I/O."""

import unittest

from limn.features.pins.claims.rules import ClaimClosedPin, ClaimedByOther, ClaimRequest, NotClaimed, claim, unclaim
from limn.pins.model import DonePin, OpenPin, ReviewPin

from helpers_pin_rules import ALICE_PERSON, AT, NOW, open_record, review_record


class ClaimTransitions(unittest.TestCase):
    """claim/unclaim: who holds the in-progress marker, for how long, and what a new claim forgets."""

    def test_claim_request_rejects_invalid_ttl(self):
        """A claim command made outside HTTP cannot carry an expired or non-integer lifetime."""
        for ttl in (0, -1, True, 1.5):
            with self.subTest(ttl=ttl), self.assertRaises(ValueError):
                ClaimRequest(ttl)

    def test_claim_request_rejects_invalid_estimate(self):
        """A claim command cannot carry a non-positive or non-integer estimate."""
        for eta in (0, -1, True, 1.5):
            with self.subTest(eta=eta), self.assertRaises(ValueError):
                ClaimRequest(30, eta)

    def test_closed_pin_cannot_be_claimed(self):
        """Claiming a review or done pin is refused with the pin."""
        pin = ReviewPin.from_record(review_record())
        self.assertEqual(claim(pin, ALICE_PERSON, NOW, AT, ClaimRequest(30), None), ClaimClosedPin(pin))

    def test_new_claim_replaces_every_earlier_claim_field(self):
        """An expired claim by someone else is dropped whole - its estimate must not survive into the new claim."""
        record = open_record(
            claimed_by={"login": "x"}, claim_until=NOW - 1, eta_ts=NOW - 100, claimed_at="old", claim_ts=1.0
        )
        r = claim(OpenPin.from_record(record), ALICE_PERSON, NOW, AT, ClaimRequest(30), None).record
        self.assertEqual((r["claimed_at"], r["claim_ts"], r["claim_until"]), (AT, NOW, NOW + 1800))
        self.assertEqual(r["claimed_by"], {"login": "alice@example.com", "name": "Alice Kim"})
        self.assertNotIn("eta_ts", r)
        self.assertEqual(r["rev"], 6)

    def test_live_claim_by_someone_else_is_refused_with_its_details(self):
        """The refusal says who holds it, until when, and their estimate."""
        record = open_record(claimed_by={"login": "bob@example.com"}, claim_until=NOW + 60, eta_ts=NOW + 30)
        self.assertEqual(
            claim(OpenPin.from_record(record), ALICE_PERSON, NOW, AT, ClaimRequest(30), None),
            ClaimedByOther({"login": "bob@example.com"}, NOW + 60, NOW + 30),
        )

    def test_same_identity_extends_and_keeps_the_start(self):
        """Extending keeps claimed_at/claim_ts, re-measures claim_until, and keeps the estimate unless a new one is given."""
        record = open_record(
            claimed_by={"login": "alice@example.com"},
            claim_until=NOW + 60,
            claimed_at="start",
            claim_ts=NOW - 600,
            eta_ts=NOW + 10,
        )
        r = claim(OpenPin.from_record(record), ALICE_PERSON, NOW, AT, ClaimRequest(20), None).record
        self.assertEqual(
            (r["claimed_at"], r["claim_ts"], r["claim_until"], r["eta_ts"]), ("start", NOW - 600, NOW + 1200, NOW + 10)
        )
        r = claim(OpenPin.from_record(record), ALICE_PERSON, NOW, AT, ClaimRequest(20, eta_min=5), None).record
        self.assertEqual(r["eta_ts"], NOW + 300)

    def test_extending_a_legacy_claim_backfills_its_start(self):
        """A claim written before claim_ts existed gets claim_ts from its claimed_at, or from now if that is unreadable."""
        record = open_record(claimed_by={"login": "alice@example.com"}, claim_until=NOW + 60, claimed_at="x")
        del record["claim_until"]
        record["claim_until"] = NOW + 60
        self.assertEqual(
            claim(OpenPin.from_record(record), ALICE_PERSON, NOW, AT, ClaimRequest(20), NOW - 99).record["claim_ts"],
            NOW - 99,
        )
        self.assertEqual(
            claim(OpenPin.from_record(record), ALICE_PERSON, NOW, AT, ClaimRequest(20), None).record["claim_ts"], NOW
        )

    def test_unclaim_clears_and_bumps_rev_only_when_there_was_a_claim(self):
        """Unclaiming a claimed pin writes; an unclaimed pin comes back as NotClaimed with any stray field cleared."""
        cleared = unclaim(OpenPin.from_record({"id": 1, "claimed_by": {"login": "a"}, "claim_until": 1.0, "rev": 2}))
        self.assertEqual(cleared, OpenPin.from_record({"id": 1, "rev": 3}))
        self.assertEqual(
            unclaim(OpenPin.from_record({"id": 1, "claim_until": 1.0})), NotClaimed(OpenPin.from_record({"id": 1}))
        )

    def test_a_closed_pin_has_no_claim_to_clear(self):
        """Every close clears the claim, so claim fields on a closed pin (a hand-edited line) are not a claim: unclaim
        answers NotClaimed with them cleared from the shown pin, and nothing is written, rev included."""
        stray = {"id": 1, "done": True, "claimed_by": {"login": "a"}, "claim_until": 1.0, "rev": 2}
        self.assertEqual(
            unclaim(DonePin.from_record(stray)), NotClaimed(DonePin.from_record({"id": 1, "done": True, "rev": 2}))
        )

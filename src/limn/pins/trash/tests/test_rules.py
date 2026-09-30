"""Pin trash decisions preserve records and return explicit refusals without I/O."""

import unittest

from limn.pins.model import OpenPin, ReviewPin, TrashedPin
from limn.pins.trash.rules import AlreadyLive, NotInTrash, drop, find_trashed, restore

from helpers_pin_rules import ALICE_PERSON, AT, open_record, review_record


class TrashTransitions(unittest.TestCase):
    """drop/find_trashed/restore: what the Trash keeps, which copy comes back, and when it cannot."""

    def test_drop_keeps_the_record_without_its_claim_and_stamps_who_and_when(self):
        """A claim is never left behind in the Trash; dropped_at/dropped_by go last."""
        trashed = drop(OpenPin.from_record(open_record()), ALICE_PERSON, AT)
        self.assertNotIn("claimed_by", trashed.record)
        self.assertEqual(list(trashed.record)[-2:], ["dropped_at", "dropped_by"])
        self.assertEqual(trashed.record["dropped_by"], {"login": "alice@example.com", "name": "Alice Kim"})

    def test_find_trashed_takes_the_newest_copy(self):
        """A pin deleted twice comes back as its last copy; an id with no copy is NotInTrash."""
        trash = [TrashedPin.from_record(r) for r in ({"id": 3, "note": "old"}, {"id": 4}, {"id": 3, "note": "new"})]
        self.assertIs(find_trashed(trash, 3), trash[2])
        self.assertEqual(find_trashed(trash, 9), NotInTrash(9))

    def test_restore_brings_back_the_state_and_bumps_rev(self):
        """dropped_at/by go, restored_at/by are recorded, rev goes up, and the pin is in the state it had."""
        trashed = TrashedPin.from_record({**review_record(), "dropped_at": "t", "dropped_by": {"login": "x"}})
        restored = restore(trashed, False, ALICE_PERSON, AT)
        self.assertIsInstance(restored, ReviewPin)
        self.assertNotIn("dropped_at", restored.record)
        self.assertEqual((restored.record["restored_at"], restored.record["rev"]), (AT, 3))

    def test_restore_refuses_an_id_that_is_live(self):
        """If the id is already among the live pins, nothing is restored."""
        self.assertEqual(restore(TrashedPin.from_record({"id": 5}), True, ALICE_PERSON, AT), AlreadyLive(5))

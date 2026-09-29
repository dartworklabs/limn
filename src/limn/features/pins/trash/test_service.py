"""Trash service and HTTP behavior over real pin storage and explicit collaborators."""

from limn.features.pins.trash import service as trash
from limn.features.pins.trash.rules import AlreadyLive, NotInTrash
from limn.features.pins.trash.service import PinTrash
from limn.pins import trash as trash_rules
from limn.pins.model import OpenPin, TrashedPin

from helpers_access import ALICE_ACTOR, BOB_ACTOR
from helpers_authority import post_authority
from helpers_pin_service import STAMP, ServiceBase, T


class Trash(ServiceBase):
    """drop, restore, the expiry rule, purge and clear."""

    def old_entry(self, pid, days_ago):
        """A Trash entry of pin pid dropped days_ago days before T (local time)."""
        import time as clock

        return {
            "id": pid,
            "file": str(self.tex),
            "lo": 1,
            "hi": 1,
            "dropped_at": clock.strftime("%Y-%m-%d %H:%M:%S", clock.localtime(T - days_ago * 86400)),
        }

    def test_expiry_is_counted_from_dropped_at(self):
        """An entry expires trash_days after dropped_at; one without a readable dropped_at never expires."""
        fresh, old, unknown = (
            TrashedPin.from_record(r) for r in (self.old_entry(1, 29), self.old_entry(2, 31), {"id": 3})
        )
        self.assertEqual(trash_rules.unexpired([fresh, old, unknown], 30, T), [fresh, unknown])
        self.assertIsNone(trash_rules.expires_ts(unknown, 30))
        self.assertFalse(trash_rules.expired(unknown, 30, T + 10**9))

    def test_drop_moves_the_pin_to_the_trash_and_restore_brings_it_back(self):
        """drop takes the pin out of pins.jsonl into the Trash and tells its author; restore puts it back, removes it
        from the Trash, and refuses a second restore (NotInTrash) without touching the Trash file."""
        pid = self.add()
        self.assertIsInstance(
            PinTrash(lambda: self.ctx).drop_pin(
                pid, post_authority(PinTrash(lambda: self.ctx).context().store, BOB_ACTOR, "drop", pid)
            ),
            TrashedPin,
        )
        self.assertIsNone(self.pin(pid))
        self.assertEqual([e.pin.core.id for e in self.store.read_dropped()[0]], [pid])
        self.assertEqual(self.rec.emitted[-1], [{"type": "dropped", "pin": pid, "to": ["alice@example.com"]}])
        self.assertIsInstance(
            PinTrash(lambda: self.ctx).restore_pin(
                pid, post_authority(PinTrash(lambda: self.ctx).context().store, ALICE_ACTOR, "restore", pid)
            ),
            OpenPin,
        )
        self.assertEqual(self.store.read_dropped()[0], [])
        trash_before = self.store.files.dropped.read_bytes()
        self.assertEqual(
            PinTrash(lambda: self.ctx).restore_pin(
                pid, post_authority(PinTrash(lambda: self.ctx).context().store, ALICE_ACTOR, "restore", pid)
            ),
            NotInTrash(pid),
        )
        self.assertEqual(self.store.files.dropped.read_bytes(), trash_before)

    def test_restore_of_a_pin_that_is_live_again_is_refused(self):
        """A live pin refuses restore while its interrupted Trash shadow is removed."""
        pid = self.add()
        self.store.write_dropped([TrashedPin.from_record(dict(self.pin(pid), dropped_at=STAMP))])
        pins = self.pins_bytes()
        self.assertEqual(
            PinTrash(lambda: self.ctx).restore_pin(
                pid, post_authority(PinTrash(lambda: self.ctx).context().store, ALICE_ACTOR, "restore", pid)
            ),
            AlreadyLive(pid),
        )
        self.assertEqual(self.pins_bytes(), pins)
        self.assertEqual(self.store.read_dropped()[0], [])

    def test_purge_trash_drops_expired_entries_and_restarts_the_hourly_clock(self):
        """purge_trash rewrites the Trash without expired entries and returns how many went; maybe_purge_trash waits
        TRASH_CHECK_EVERY_S after any check."""
        self.store.write_dropped(
            [TrashedPin.from_record(self.old_entry(1, 31)), TrashedPin.from_record(self.old_entry(2, 1))]
        )
        self.assertEqual(PinTrash(lambda: self.ctx).purge_trash(), 1)
        self.assertEqual([e.pin.core.id for e in self.store.read_dropped()[0]], [2])
        self.assertEqual(self.checked, [T])
        self.assertEqual(PinTrash(lambda: self.ctx).maybe_purge_trash(), 0)
        later = self.context(epoch=lambda: T + trash.TRASH_CHECK_EVERY_S + 2 * 86400 * 30)
        self.assertEqual(PinTrash(lambda: later).maybe_purge_trash(), 1)

    def test_purge_pin_is_audited_outside_the_pin_lock(self):
        """A permanent delete removes the entry, emits `purged` and appends the audit line after releasing the lock;
        a pin not in the Trash is NotInTrash with no audit."""
        pid = self.add()
        PinTrash(lambda: self.ctx).drop_pin(
            pid, post_authority(PinTrash(lambda: self.ctx).context().store, ALICE_ACTOR, "drop", pid)
        )
        self.assertIsInstance(
            PinTrash(lambda: self.ctx).purge_pin(
                pid, post_authority(PinTrash(lambda: self.ctx).context().store, ALICE_ACTOR, "purge", pid)
            ),
            TrashedPin,
        )
        self.assertEqual(self.store.read_dropped()[0], [])
        self.assertEqual(
            self.rec.emitted[-1], [{"type": "purged", "to": [], "pin": pid, "by": {"login": "alice@example.com"}}]
        )
        self.assertEqual(self.rec.audits, [("purged", "alice@example.com", {"pin": pid}, True)])
        self.assertEqual(
            PinTrash(lambda: self.ctx).purge_pin(
                pid, post_authority(PinTrash(lambda: self.ctx).context().store, ALICE_ACTOR, "purge", pid)
            ),
            NotInTrash(pid),
        )
        self.assertEqual(len(self.rec.audits), 1)

    def test_clear_archives_and_is_audited_as_the_authorized_owner(self):
        """clear_pins archives pins.jsonl, emits `cleared` and audits it outside the lock with an explicit owner capability."""
        self.add()
        out = PinTrash(lambda: self.ctx).clear_pins(
            post_authority(
                PinTrash(lambda: self.ctx).context().store,
                {"login": "local", "name": "Owner"},
                "clear",
                None,
                role="owner",
            )
        )
        self.assertEqual(out["cleared"], 1)
        self.assertTrue((self.state / out["archive"]).exists())
        self.assertFalse(self.store.files.pins_jsonl.exists())
        self.assertEqual(self.rec.audits, [("cleared", "local", {"n": 1, "archive": out["archive"]}, True)])

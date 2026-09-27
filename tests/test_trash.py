"""The Trash and the bulk clear through server.py (limn.service.trash): delete, restore, purge, expiry, clear.

v0.2.2 (issue #8) replaced the dropped section with a Trash: a deleted pin is kept 30 days, then purged - on startup,
on a drop, and on normal reads at most once an hour (never on a light poll). Someone else's delete notifies the
author, only the owner deletes permanently, and pins.md never lists the Trash. ClearEndpoint is POST /api/clear, the
one bulk-destructive operation (the v0.2.1 QA, finding B): owner only, behind a confirmation phrase, archived to a
backup and recorded as an event. The audit lines of clear and purge are test_audit.py; the Trash in the viewer is
test_viewer_browser.py.

Run: uv run pytest -q tests/test_trash.py
"""

import json
import time

from limn import store as limn_store
from limn.events import NOTIFY_TYPES
from limn.files import atomic_write
from limn.pins import position
from limn.store import dump_jsonl

from helpers import Base, ps, trash_records
from helpers_access import ALICE, BOB, CAROL, CLEAR_BODY, DAVE, TS_HOST, AccessBase, actor, token_create

A, B = actor(ALICE), actor(BOB)


class TrashApi(AccessBase):
    def setUp(self):
        super().setUp()
        ps._EVENTS_CACHE.clear()
        for h in (ALICE, BOB, CAROL):
            ps.record_person(actor(h))

    def dropped_file(self):
        return trash_records()

    def put_dropped(self, pid, days_ago, **extra):
        rec = {
            "id": pid,
            "file": str(self.main),
            "lo": 4,
            "hi": 5,
            "page": 1,
            "note": "old %d" % pid,
            "author": A,
            "dropped_by": B,
            **extra,
        }
        if days_ago is not None:
            rec["dropped_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - days_ago * 86400))
        atomic_write(ps.C.dropped, dump_jsonl(self.dropped_file() + [rec]))

    def test_retention_is_thirty_days(self):
        self.assertEqual(ps.TRASH_DAYS, 30)

    def test_trash_listing_carries_the_purge_time(self):
        self.put_dropped(70, 10)
        rec = ps.dropped_payload()[0]
        self.assertAlmostEqual(rec["expires_ts"], position.epoch(rec["dropped_at"]) + 30 * 86400, delta=1)
        self.assertNotIn("expires_ts", trash_records()[0])  # computed, never stored

    def test_iso_timestamps_with_an_offset_expire_too(self):
        self.put_dropped(71, None, dropped_at="2026-01-01T10:00:00+09:00")
        self.assertEqual(ps.purge_trash(), 1)

    def test_unreadable_trash_lines_are_kept_in_a_backup(self):
        atomic_write(ps.C.dropped, "{not json\n")
        pid = self.pin_id(ALICE)
        self.call("POST", "/api/pins/%d/drop" % pid, None, ALICE)
        baks = list(ps.C.state.glob("pins.dropped.jsonl.corrupt-*.bak"))
        self.assertEqual(len(baks), 1)
        self.assertIn("{not json", baks[0].read_text(encoding="utf-8"))

    def test_a_failing_purge_never_stops_the_server(self):
        from unittest import mock

        self.put_dropped(72, 40)
        with mock.patch.object(limn_store, "atomic_write", side_effect=OSError("read-only")):  # the Trash writer's
            self.assertEqual(ps.purge_trash(), 0)

    def test_someone_elses_delete_notifies_the_author(self):
        pid = self.pin_id(ALICE)
        n = len(ps._read_events()[0])
        code, d = self.call("POST", "/api/pins/%d/drop" % pid, None, BOB)
        self.assertEqual((code, d["ok"]), (200, True))
        evs = ps._read_events()[0][n:]
        self.assertEqual(
            [(e["type"], e["to"], e["by"]["login"], e["pin"]) for e in evs],
            [("dropped", ["alice@example.com"], "bob@example.com", pid)],
        )
        self.assertIn("dropped", NOTIFY_TYPES)
        m = self.call("GET", "/api/meta?light=1&ev=%d" % (evs[0]["seq"] - 1), headers=ALICE)[1]
        self.assertEqual([e["type"] for e in m["events"]], ["dropped"])

    def test_deleting_your_own_pin_notifies_nobody(self):
        pid = self.pin_id(ALICE)
        n = len(ps._read_events()[0])
        self.call("POST", "/api/pins/%d/drop" % pid, None, ALICE)
        self.assertEqual(ps._read_events()[0][n:], [])

    def test_agent_delete_notifies_the_author(self):
        pid = self.pin_id(ALICE)
        n = len(ps._read_events()[0])
        self.call("POST", "/api/pins/%d/drop" % pid)
        self.assertEqual([(e["type"], e["to"]) for e in ps._read_events()[0][n:]], [("dropped", ["alice@example.com"])])

    def test_expired_pins_are_hidden_then_purged(self):
        self.put_dropped(50, 31)
        self.put_dropped(51, 29)
        self.put_dropped(52, None)  # no timestamp (hand-edited): kept, never guessed
        ids = sorted(r["id"] for r in ps.dropped_payload())
        self.assertEqual(ids, [51, 52])  # a read never shows an expired pin...
        self.assertEqual(sorted(r["id"] for r in self.dropped_file()), [50, 51, 52])  # ...and never writes
        self.assertEqual(ps.purge_trash(), 1)
        self.assertEqual(sorted(r["id"] for r in self.dropped_file()), [51, 52])
        self.assertEqual(ps.purge_trash(now=time.time() + 2 * 86400), 1)  # two days later #51 is 31 days old
        self.assertEqual([r["id"] for r in self.dropped_file()], [52])

    def test_a_drop_purges_expired_pins(self):
        self.put_dropped(60, 40)
        pid = self.pin_id(ALICE)
        self.call("POST", "/api/pins/%d/drop" % pid, None, ALICE)
        self.assertEqual([r["id"] for r in self.dropped_file()], [pid])

    def test_an_expired_pin_cannot_be_restored(self):
        self.put_dropped(61, 45)
        code, _ = self.call("POST", "/api/pins/61/restore", None, ALICE)
        self.assertEqual(code, 404)

    def test_owner_deletes_permanently(self):
        self.set_people([{"login": "alice@example.com", "name": "Alice Kim", "role": "owner"}])
        pid = self.pin_id(BOB)
        self.call("POST", "/api/pins/%d/drop" % pid, None, BOB)
        n = len(ps._read_events()[0])
        code, d = self.call("POST", "/api/pins/%d/purge" % pid, None, ALICE)
        self.assertEqual((code, d["ok"], d["purged"]), (200, True, pid))
        self.assertEqual(self.dropped_file(), [])
        self.assertEqual([(e["type"], e["to"], e["pin"]) for e in ps._read_events()[0][n:]], [("purged", [], pid)])
        code, _ = self.call("POST", "/api/pins/%d/restore" % pid, None, ALICE)
        self.assertEqual(code, 404)
        code, _ = self.call("POST", "/api/pins/%d/purge" % pid, None, ALICE)
        self.assertEqual(code, 404)
        nid = self.pin_id(ALICE)
        self.assertGreater(nid, pid)  # an id is never reused, even after a purge

    def test_only_the_owner_may_delete_permanently(self):
        self.set_people(
            [
                {"login": "alice@example.com", "name": "Alice Kim", "role": "owner"},
                {"login": "carol@example.com", "name": "Carol Lee", "role": "viewer"},
            ]
        )
        pid = self.pin_id(BOB)
        self.call("POST", "/api/pins/%d/drop" % pid, None, BOB)
        _, tok = token_create(ps.C.state, "bot")
        for who, kw in (
            ("editor", {"headers": BOB}),
            ("viewer", {"headers": CAROL}),
            ("loopback agent", {}),
            ("token", {"token": tok}),
        ):
            with self.subTest(who=who):
                code, _ = self.call("POST", "/api/pins/%d/purge" % pid, None, **kw)
                self.assertEqual(code, 403)
        self.assertEqual([r["id"] for r in self.dropped_file()], [pid])

    def test_purge_of_an_open_pin_is_refused(self):
        self.set_people([{"login": "alice@example.com", "name": "Alice Kim", "role": "owner"}])
        pid = self.pin_id(ALICE)
        code, _ = self.call("POST", "/api/pins/%d/purge" % pid, None, ALICE)
        self.assertEqual(code, 404)
        self.assertIsNotNone(self.pin(pid))

    def test_pins_md_never_lists_trash(self):
        pid = self.pin_id(ALICE)
        self.call("POST", "/api/pins/%d/drop" % pid, None, BOB)
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertNotRegex(md, r"\n\| %d[ ·|]" % pid)


class LazyTrashExpiry(AccessBase):
    """A long-running server drops expired Trash entries during normal reads, at most once an hour, never on a light poll."""

    def setUp(self):
        super().setUp()
        ps._TRASH_CHECKED[0] = 0.0

    def put_dropped(self, pid, dropped_epoch):
        rec = {
            "id": pid,
            "file": str(self.main),
            "lo": 4,
            "hi": 5,
            "page": 1,
            "note": "old",
            "dropped_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(dropped_epoch)),
        }
        atomic_write(ps.C.dropped, dump_jsonl(trash_records() + [rec]))

    def ids(self):
        return sorted(r["id"] for r in trash_records())

    def test_hourly_purge_on_reads_with_a_fake_clock(self):
        from unittest import mock

        t0 = time.time()
        self.put_dropped(80, t0 - 31 * 86400)
        with mock.patch.object(ps.time, "time", return_value=t0):
            self.assertEqual(self.call("GET", "/api/meta?light=1")[0], 200)  # a light poll never writes
            self.assertEqual(self.ids(), [80])
            self.assertEqual(self.call("GET", "/api/pins")[0], 200)  # a normal read purges
            self.assertEqual(self.ids(), [])
            self.put_dropped(81, t0 - 31 * 86400)
            self.call("GET", "/api/pins?all=1")  # within the hour: no second check
            self.assertEqual(self.ids(), [81])
        with mock.patch.object(ps.time, "time", return_value=t0 + 3601):
            self.call("GET", "/pins.md")  # an hour later: checked again
            self.assertEqual(self.ids(), [])

    def test_an_entry_expiring_while_the_server_runs(self):
        from unittest import mock

        t0 = time.time()
        self.put_dropped(82, t0 - 29.99 * 86400)
        with mock.patch.object(ps.time, "time", return_value=t0):
            self.call("GET", "/api/pins")
            self.assertEqual(self.ids(), [82])  # not yet 30 days old
        with mock.patch.object(ps.time, "time", return_value=t0 + 2 * 3600):
            self.call("GET", "/api/pins")
            self.assertEqual(self.ids(), [])


class TrashClockStart(Base):
    def test_startup_purge_starts_the_hourly_clock(self):
        ps._TRASH_CHECKED[0] = 0.0
        ps.purge_trash()
        self.assertGreater(ps._TRASH_CHECKED[0], time.time() - 5)


# ---------------------------------------------------------------- POST /api/clear: owner only, a confirmation phrase, a backup (v0.2.1 QA B)


class ClearEndpoint(AccessBase):
    def setUp(self):
        super().setUp()
        ps._EVENTS_CACHE.clear()
        self.set_people(
            [
                {"login": "alice@example.com", "name": "Alice Kim", "role": "owner"},
                {"login": "bob@example.com", "name": "Bob Park"},
                {"login": "carol@example.com", "name": "Carol Lee", "role": "viewer"},
                {"login": "dave@example.com", "name": "Dave Choi", "role": "agent"},
            ]
        )
        self.add()
        self.add(8, 9)

    def backups(self):
        return sorted(p.name for p in ps.C.state.glob("pins_*.jsonl.bak"))

    def assert_untouched(self):
        self.assertEqual(len(ps.snapshot_pins()), 2)
        self.assertEqual(self.backups(), [])

    def test_only_the_owner_may_clear(self):
        _, tok = token_create(ps.C.state, "ci")
        refused = [
            ("editor", dict(headers=BOB)),
            ("viewer", dict(headers=CAROL)),
            ("agent-role person", dict(headers=DAVE)),
            ("token agent", dict(token=tok)),
            ("loopback agent", {}),
            ("token over tailnet", dict(token=tok, headers={"Host": TS_HOST})),
        ]
        for label, kw in refused:
            code, d = self.call("POST", "/api/clear", CLEAR_BODY, **kw)
            self.assertEqual(code, 403, (label, d))
        self.assert_untouched()

    def test_owner_needs_the_confirmation_phrase(self):
        for body in (None, {}, {"confirm": True}, {"confirm": "yes"}, {"confirm": "Clear All Pins"}):
            code, d = self.call("POST", "/api/clear", body, ALICE)
            self.assertEqual(code, 400, (body, d))
            self.assertIn("clear all pins", d["error"])
        self.assert_untouched()

    def test_owner_clear_keeps_a_backup_and_records_the_actor(self):
        code, d = self.call("POST", "/api/clear", CLEAR_BODY, ALICE)
        self.assertEqual(code, 200, d)
        self.assertTrue(d["ok"])
        self.assertEqual(d["cleared"], 2)
        self.assertEqual(ps.snapshot_pins(), [])
        self.assertEqual(self.backups(), [d["archive"]])
        rows = [json.loads(ln) for ln in (ps.C.state / d["archive"]).read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["id"] for r in rows], [1, 2])
        ev = ps._read_events()[0][-1]
        self.assertEqual(
            (ev["type"], ev["by"]["login"], ev["n"], ev["archive"]), ("cleared", "alice@example.com", 2, d["archive"])
        )
        self.assertEqual(ev["to"], [])
        self.assertEqual(self.add(), 3)  # ids keep counting

    def test_local_owner_may_clear(self):
        ps.C.auth, ps.C.agent_loopback, ps.C.local_user = "local", False, "alice"
        code, d = self.call("POST", "/api/clear", CLEAR_BODY)
        self.assertEqual((code, d.get("cleared")), (200, 2), d)

"""The Trash and bulk clear through the feature slice: delete, restore, purge, expiry, clear.

v0.2.2 (issue #8) replaced the dropped section with a Trash: a deleted pin is kept 30 days, then purged - on startup,
on a drop, and on normal reads at most once an hour (never on a light poll). Someone else's delete notifies the
author, only the owner deletes permanently, and pins.md never lists the Trash. ClearEndpoint is POST /api/clear, the
one bulk-destructive operation (the v0.2.1 QA, finding B): owner only, behind a confirmation phrase, archived to a
backup and recorded as an event. The audit lines of clear and purge are test_audit.py; the Trash in the viewer is
test_viewer_browser.py.

Run: uv run pytest -q tests/test_trash.py
"""

import io
import json
import threading
import time
from contextlib import redirect_stderr
from unittest import mock

from limn import store as limn_store
from limn.events import NOTIFY_TYPES
from limn.features.pins.trash.rules import AlreadyLive, NotInTrash
from limn.files import atomic_write
from limn.pins import position
from limn.pins.model import PinNotFound
from limn.store import dump_jsonl

from helpers import Base, ps, set_config, trash_records
from helpers_access import ALICE, BOB, CAROL, CLEAR_BODY, DAVE, TS_HOST, AccessBase, actor, token_create

A, B = actor(ALICE), actor(BOB)


class TrashApi(AccessBase):
    """Trash routes retain deleted pins, notify authors, and enforce purge ownership."""

    def setUp(self):
        super().setUp()
        for h in (ALICE, BOB, CAROL):
            ps.APP.people_directory.record(actor(h))

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
        atomic_write(ps.APP.C.dropped, dump_jsonl(self.dropped_file() + [rec]))

    def test_retention_is_thirty_days(self):
        self.assertEqual(ps.TRASH_DAYS, 30)

    def test_trash_listing_carries_the_purge_time(self):
        self.put_dropped(70, 10)
        rec = ps.APP.pin_listing.dropped_payload()[0]
        self.assertAlmostEqual(rec["expires_ts"], position.epoch(rec["dropped_at"]) + 30 * 86400, delta=1)
        self.assertNotIn("expires_ts", trash_records()[0])  # computed, never stored

    def test_iso_timestamps_with_an_offset_expire_too(self):
        self.put_dropped(71, None, dropped_at="2026-01-01T10:00:00+09:00")
        self.assertEqual(ps.APP.pin_trash.purge_trash(), 1)

    def test_unreadable_trash_lines_are_kept_in_a_backup(self):
        """A later drop saves unreadable original Trash bytes before replacing the file."""
        atomic_write(ps.APP.C.dropped, "{not json\n")
        pid = self.pin_id(ALICE)
        self.call("POST", "/api/pins/%d/drop" % pid, None, ALICE)
        baks = list(ps.APP.C.state.glob("pins.dropped.jsonl.corrupt-*.bak"))
        self.assertEqual(len(baks), 1)
        self.assertIn("{not json", baks[0].read_text(encoding="utf-8"))

    def test_a_failing_purge_never_stops_the_server(self):
        """A failed retention write warns without advancing the clock, so the next read retries it."""
        from unittest import mock

        self.put_dropped(72, 40)
        ps.APP.RT.trash_checked[0] = 0
        with mock.patch.object(limn_store, "atomic_write", side_effect=OSError("read-only")):  # the Trash writer's
            self.assertEqual(ps.APP.pin_trash.maybe_purge_trash(), 0)
        self.assertEqual(ps.APP.RT.trash_checked[0], 0)
        self.assertEqual(ps.APP.pin_trash.maybe_purge_trash(), 1)
        self.assertEqual(self.dropped_file(), [])

    def test_someone_elses_delete_notifies_the_author(self):
        """Deleting another person's pin emits one addressed event visible to that author."""
        pid = self.pin_id(ALICE)
        n = len(ps.APP.notices.read()[0])
        code, d = self.call("POST", "/api/pins/%d/drop" % pid, None, BOB)
        self.assertEqual((code, d["ok"]), (200, True))
        evs = ps.APP.notices.read()[0][n:]
        self.assertEqual(
            [(e["type"], e["to"], e["by"]["login"], e["pin"]) for e in evs],
            [("dropped", ["alice@example.com"], "bob@example.com", pid)],
        )
        self.assertIn("dropped", NOTIFY_TYPES)
        m = self.call("GET", "/api/meta?light=1&ev=%d" % (evs[0]["seq"] - 1), headers=ALICE)[1]
        self.assertEqual([e["type"] for e in m["events"]], ["dropped"])

    def test_deleting_your_own_pin_notifies_nobody(self):
        pid = self.pin_id(ALICE)
        n = len(ps.APP.notices.read()[0])
        self.call("POST", "/api/pins/%d/drop" % pid, None, ALICE)
        self.assertEqual(ps.APP.notices.read()[0][n:], [])

    def test_agent_delete_notifies_the_author(self):
        pid = self.pin_id(ALICE)
        n = len(ps.APP.notices.read()[0])
        self.call("POST", "/api/pins/%d/drop" % pid)
        self.assertEqual(
            [(e["type"], e["to"]) for e in ps.APP.notices.read()[0][n:]], [("dropped", ["alice@example.com"])]
        )

    def test_expired_pins_are_hidden_then_purged(self):
        """Reads hide expired copies without writing; cleanup removes only copies of known age."""
        self.put_dropped(50, 31)
        self.put_dropped(51, 29)
        self.put_dropped(52, None)  # no timestamp (hand-edited): kept, never guessed
        ids = sorted(r["id"] for r in ps.APP.pin_listing.dropped_payload())
        self.assertEqual(ids, [51, 52])  # a read never shows an expired pin...
        self.assertEqual(sorted(r["id"] for r in self.dropped_file()), [50, 51, 52])  # ...and never writes
        self.assertEqual(ps.APP.pin_trash.purge_trash(), 1)
        self.assertEqual(sorted(r["id"] for r in self.dropped_file()), [51, 52])
        self.assertEqual(
            ps.APP.pin_trash.purge_trash(now=time.time() + 2 * 86400), 1
        )  # two days later #51 is 31 days old
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
        """An owner purge leaves an event, prevents restore, and never reuses the id."""
        self.set_people([{"login": "alice@example.com", "name": "Alice Kim", "role": "owner"}])
        pid = self.pin_id(BOB)
        self.call("POST", "/api/pins/%d/drop" % pid, None, BOB)
        n = len(ps.APP.notices.read()[0])
        code, d = self.call("POST", "/api/pins/%d/purge" % pid, None, ALICE)
        self.assertEqual((code, d["ok"], d["purged"]), (200, True, pid))
        self.assertEqual(self.dropped_file(), [])
        self.assertEqual([(e["type"], e["to"], e["pin"]) for e in ps.APP.notices.read()[0][n:]], [("purged", [], pid)])
        code, _ = self.call("POST", "/api/pins/%d/restore" % pid, None, ALICE)
        self.assertEqual(code, 404)
        code, _ = self.call("POST", "/api/pins/%d/purge" % pid, None, ALICE)
        self.assertEqual(code, 404)
        nid = self.pin_id(ALICE)
        self.assertGreater(nid, pid)  # an id is never reused, even after a purge

    def test_only_the_owner_may_delete_permanently(self):
        """Editors, viewers, and both agent identities cannot erase a Trash entry."""
        self.set_people(
            [
                {"login": "alice@example.com", "name": "Alice Kim", "role": "owner"},
                {"login": "carol@example.com", "name": "Carol Lee", "role": "viewer"},
            ]
        )
        pid = self.pin_id(BOB)
        self.call("POST", "/api/pins/%d/drop" % pid, None, BOB)
        _, tok = token_create(ps.APP.C.state, "bot")
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
        """Even an owner must drop a live pin before requesting permanent deletion."""
        self.set_people([{"login": "alice@example.com", "name": "Alice Kim", "role": "owner"}])
        pid = self.pin_id(ALICE)
        code, _ = self.call("POST", "/api/pins/%d/purge" % pid, None, ALICE)
        self.assertEqual(code, 404)
        self.assertIsNotNone(self.pin(pid))

    def test_pins_md_never_lists_trash(self):
        pid = self.pin_id(ALICE)
        self.call("POST", "/api/pins/%d/drop" % pid, None, BOB)
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertNotRegex(md, r"\n\| %d[ ·|]" % pid)


class TrashRecovery(AccessBase):
    """A partially written move always has one authoritative, visible copy of its pin."""

    def setUp(self):
        """Start each failure case with a fresh state and known people."""
        super().setUp()
        for h in (ALICE, BOB, CAROL):
            ps.APP.people_directory.record(actor(h))

    def dropped_file(self):
        """The readable Trash records currently on disk."""
        return trash_records()

    def put_dropped(self, pid, days_ago):
        """Make a readable Trash shadow of a live pin."""
        rec = {
            "id": pid,
            "file": str(self.main),
            "lo": 4,
            "hi": 5,
            "page": 1,
            "note": "old %d" % pid,
            "author": A,
            "dropped_by": B,
            "dropped_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - days_ago * 86400)),
        }
        atomic_write(ps.APP.C.dropped, dump_jsonl(self.dropped_file() + [rec]))

    def fail_after_write(self, filename):
        """Replace a requested file, then model process failure before the next store write."""
        real = limn_store.atomic_write

        def write(path, data):
            """Persist the file, then interrupt exactly after the selected replacement."""
            real(path, data)
            if path.name == filename:
                raise OSError("interrupted after " + filename)

        return mock.patch.object(limn_store, "atomic_write", side_effect=write)

    def test_live_shadow_is_hidden_read_only_and_cannot_be_purged(self):
        """A completed Trash write cannot expose or permanently purge a still-live pin."""
        self.set_people([{"login": "alice@example.com", "name": "Alice Kim", "role": "owner"}])
        pid = self.pin_id(ALICE)
        self.put_dropped(pid, 0)
        before = ps.APP.C.dropped.read_bytes()
        n_events = len(ps.APP.notices.read()[0])
        audit_path = ps.APP.C.audit_file
        before_audit = audit_path.read_bytes() if audit_path.exists() else b""

        self.assertEqual(ps.APP.pin_listing.dropped_payload(), [])
        self.assertEqual(self.call("GET", "/api/pins/dropped", headers=ALICE), (200, {"dropped": []}))
        self.assertEqual(ps.APP.C.dropped.read_bytes(), before)
        self.assertEqual(self.call("POST", "/api/pins/%d/purge" % pid, None, BOB)[0], 403)
        self.assertEqual(self.call("POST", "/api/pins/%d/purge" % pid, None, ALICE)[0], 404)
        self.assertEqual(ps.APP.C.dropped.read_bytes(), before)
        self.assertEqual(len(ps.APP.notices.read()[0]), n_events)
        self.assertEqual(audit_path.read_bytes() if audit_path.exists() else b"", before_audit)
        self.assertIsNotNone(self.pin(pid))

    def test_dropped_listing_waits_for_one_locked_snapshot(self):
        """A concurrent state change cannot interleave the live and Trash reads."""
        pid = self.pin_id(ALICE)
        self.put_dropped(pid, 0)
        started = threading.Event()
        done = threading.Event()
        result = []

        def read():
            """Signal entry, then capture the response after the store lock becomes available."""
            started.set()
            result.extend(ps.APP.pin_listing.dropped_payload())
            done.set()

        with ps.APP.RT.pin_lock:
            thread = threading.Thread(target=read)
            thread.start()
            self.assertTrue(started.wait(1))
            self.assertFalse(done.wait(0.02))
        thread.join(1)
        self.assertTrue(done.is_set())
        self.assertEqual(result, [])

    def test_startup_style_prune_preserves_unreadable_trash_in_backup(self):
        """Shadow pruning keeps a malformed original line in the existing corrupt backup."""
        pid = self.pin_id(ALICE)
        self.put_dropped(pid, 31)
        ps.APP.C.dropped.write_bytes(ps.APP.C.dropped.read_bytes() + b"{broken\n")

        output = io.StringIO()
        with redirect_stderr(output):
            self.assertEqual(ps.APP.pin_trash.purge_trash(), 0)
        self.assertNotIn("trash: purged", output.getvalue())
        self.assertIn("trash: reconciled 1 live shadow(s)", output.getvalue())
        self.assertEqual(self.dropped_file(), [])
        backups = list(ps.APP.C.state.glob("pins.dropped.jsonl.corrupt-*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertIn(b"{broken\n", backups[0].read_bytes())
        self.assertIsNotNone(self.pin(pid))

    def test_cleanup_counts_expiry_separately_from_live_shadows(self):
        """Retention count and log exclude even an expired copy of a still-live pin."""
        pid = self.pin_id(ALICE)
        self.put_dropped(pid, 31)
        self.put_dropped(900, 31)
        output = io.StringIO()
        with redirect_stderr(output):
            self.assertEqual(ps.APP.pin_trash.purge_trash(), 1)
        self.assertIn("trash: purged 1 pin(s)", output.getvalue())
        self.assertIn("trash: reconciled 1 live shadow(s)", output.getvalue())
        self.assertEqual(self.dropped_file(), [])

    def test_startup_ignores_trash_read_error(self):
        """A cleanup read error warns and does not prevent startup from rendering live pins."""
        pid = self.pin_id(ALICE)
        fresh = ps.ServerApplication(ps.APP.C, ps.new_runtime(ps.APP.RT.viewer))
        output = io.StringIO()
        with (
            mock.patch.object(limn_store.PinStore, "read_dropped", side_effect=OSError("unreadable")),
            mock.patch.object(ps.build_run, "needs_build", return_value=False),
            redirect_stderr(output),
        ):
            self.assertIsNone(fresh.prepare(None, True))
        self.assertIn("warning: could not purge the Trash: unreadable", output.getvalue())
        self.assertRegex(fresh.C.pins_md.read_text(encoding="utf-8"), r"\n\| %d[ ·|]" % pid)

    def test_failed_cleanup_retries_without_waiting_an_hour(self):
        """A failed Trash read leaves the last successful check time so the next read can retry."""
        pid = self.pin_id(ALICE)
        self.put_dropped(pid, 31)
        ps.APP.RT.trash_checked[0] = 0
        with mock.patch.object(limn_store.PinStore, "read_dropped", side_effect=OSError("unreadable")):
            self.assertEqual(ps.APP.pin_trash.maybe_purge_trash(), 0)
        self.assertEqual(ps.APP.RT.trash_checked[0], 0)
        self.assertEqual(ps.APP.pin_trash.maybe_purge_trash(), 0)
        self.assertEqual(self.dropped_file(), [])

    def test_drop_and_restore_render_before_the_first_file_replacement(self):
        """A renderer failure keeps the only durable copy in its original file for either move."""
        pid = self.pin_id(ALICE)
        before_live = ps.APP.C.pins_jsonl.read_bytes()
        with (
            mock.patch.object(ps.APP.pin_markdown, "pins_md_text", side_effect=RuntimeError("render failed")),
            self.assertRaisesRegex(RuntimeError, "render failed"),
        ):
            ps.APP.pin_trash.drop_pin(pid, B)
        self.assertEqual(ps.APP.C.pins_jsonl.read_bytes(), before_live)
        self.assertEqual(self.dropped_file(), [])

        ps.APP.pin_trash.drop_pin(pid, B)
        before_trash = ps.APP.C.dropped.read_bytes()
        with (
            mock.patch.object(ps.APP.pin_markdown, "pins_md_text", side_effect=RuntimeError("render failed")),
            self.assertRaisesRegex(RuntimeError, "render failed"),
        ):
            ps.APP.pin_trash.restore_pin(pid, A)
        self.assertEqual(ps.APP.C.dropped.read_bytes(), before_trash)
        self.assertFalse(any(pin.core.id == pid for pin in ps.APP.read_pins()[0]))

    def test_drop_serializes_live_jsonl_before_writing_trash(self):
        """A live serialization defect leaves the original pin and no premature Trash copy."""
        pid = self.pin_id(ALICE)
        self.pin_id(BOB, lo=8, hi=9)
        before_live = ps.APP.C.pins_jsonl.read_bytes()
        real_dump = limn_store.dump_jsonl

        def fail_live(rows):
            """Fail only the live replacement, while a Trash replacement could still serialize."""
            records = list(rows)
            if records and all("dropped_at" not in row for row in records):
                raise TypeError("cannot serialize live pins")
            return real_dump(records)

        with (
            mock.patch.object(limn_store, "dump_jsonl", side_effect=fail_live),
            self.assertRaisesRegex(TypeError, "cannot serialize live pins"),
        ):
            ps.APP.pin_trash.drop_pin(pid, B)
        self.assertEqual(ps.APP.C.pins_jsonl.read_bytes(), before_live)
        self.assertEqual(self.dropped_file(), [])

    def test_drop_failure_after_each_write_keeps_one_visible_copy(self):
        """Retries never duplicate a Trash row or send a notice for an interrupted drop."""
        for stage in ("pins.dropped.jsonl", "pins.jsonl", "pins.md"):
            with self.subTest(stage=stage):
                pid = self.pin_id(ALICE)
                before_events = len(ps.APP.notices.read()[0])
                before_md = ps.APP.C.pins_md.read_bytes()
                with self.fail_after_write(stage), self.assertRaises(OSError):
                    ps.APP.pin_trash.drop_pin(pid, B)
                live = any(pin.core.id == pid for pin in ps.APP.read_pins()[0])
                self.assertEqual(live, stage == "pins.dropped.jsonl")
                self.assertEqual(sum(row["id"] == pid for row in self.dropped_file()), 1)
                self.assertEqual(
                    [row["id"] for row in ps.APP.pin_listing.dropped_payload() if row["id"] == pid],
                    [] if live else [pid],
                )
                self.assertEqual(len(ps.APP.notices.read()[0]), before_events)
                if stage == "pins.jsonl":
                    self.assertEqual(ps.APP.C.pins_md.read_bytes(), before_md)
                if live:
                    self.assertNotIsInstance(ps.APP.pin_trash.drop_pin(pid, B), PinNotFound)
                else:
                    self.assertIsInstance(ps.APP.pin_trash.drop_pin(pid, B), PinNotFound)
                self.assertEqual(sum(row["id"] == pid for row in self.dropped_file()), 1)

    def test_restore_failure_after_each_write_and_retry(self):
        """A committed live copy wins over its remaining Trash row until retry cleans it."""
        for stage in ("pins.jsonl", "pins.md", "pins.dropped.jsonl"):
            with self.subTest(stage=stage):
                pid = self.pin_id(ALICE)
                ps.APP.pin_trash.drop_pin(pid, A)
                before_md = ps.APP.C.pins_md.read_bytes()
                with self.fail_after_write(stage), self.assertRaises(OSError):
                    ps.APP.pin_trash.restore_pin(pid, A)
                self.assertIsNotNone(self.pin(pid))
                self.assertEqual(ps.APP.pin_listing.dropped_payload(), [])
                if stage == "pins.jsonl":
                    self.assertEqual(ps.APP.C.pins_md.read_bytes(), before_md)
                refusal = ps.APP.pin_trash.restore_pin(pid, A)
                self.assertIsInstance(refusal, NotInTrash if stage == "pins.dropped.jsonl" else AlreadyLive)
                self.assertEqual(sum(row["id"] == pid for row in self.dropped_file()), 0)

    def test_restart_recovers_shadow_and_stale_md(self):
        """Startup prunes a shadow and rerenders pins.md after a committed live write fails next."""
        pid = self.pin_id(ALICE)
        ps.APP.pin_trash.drop_pin(pid, A)
        with self.fail_after_write("pins.jsonl"), self.assertRaises(OSError):
            ps.APP.pin_trash.restore_pin(pid, A)
        self.assertEqual(sum(row["id"] == pid for row in self.dropped_file()), 1)
        self.assertNotRegex(ps.APP.C.pins_md.read_text(encoding="utf-8"), r"\n\| %d[ ·|]" % pid)
        fresh = ps.ServerApplication(ps.APP.C, ps.new_runtime(ps.APP.RT.viewer))
        with mock.patch.object(ps.build_run, "needs_build", return_value=False):
            self.assertIsNone(fresh.prepare(None, True))
        self.assertEqual(fresh.read_dropped()[0], [])
        self.assertRegex(fresh.C.pins_md.read_text(encoding="utf-8"), r"\n\| %d[ ·|]" % pid)
        self.assertIsInstance(fresh.pin_trash.restore_pin(pid, A), NotInTrash)
        self.assertIsInstance(fresh.pin_trash.purge_pin(pid, A), NotInTrash)

    def test_restart_repairs_md_after_drop_commit_without_a_notice(self):
        """The live file remains authoritative if the drop commits before pins.md fails."""
        pid = self.pin_id(ALICE)
        before_events = len(ps.APP.notices.read()[0])
        with self.fail_after_write("pins.jsonl"), self.assertRaises(OSError):
            ps.APP.pin_trash.drop_pin(pid, B)
        self.assertIsNone(next((pin for pin in ps.APP.read_pins()[0] if pin.core.id == pid), None))
        self.assertRegex(ps.APP.C.pins_md.read_text(encoding="utf-8"), r"\n\| %d[ ·|]" % pid)
        self.assertEqual(len(ps.APP.notices.read()[0]), before_events)
        fresh = ps.ServerApplication(ps.APP.C, ps.new_runtime(ps.APP.RT.viewer))
        with mock.patch.object(ps.build_run, "needs_build", return_value=False):
            self.assertIsNone(fresh.prepare(None, True))
        self.assertNotRegex(fresh.C.pins_md.read_text(encoding="utf-8"), r"\n\| %d[ ·|]" % pid)
        self.assertEqual([row["id"] for row in fresh.pin_listing.dropped_payload()], [pid])
        self.assertEqual(len(fresh.notices.read()[0]), before_events)


class LazyTrashExpiry(AccessBase):
    """A long-running server drops expired Trash entries during normal reads, at most once an hour, never on a light poll."""

    def setUp(self):
        super().setUp()

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
        atomic_write(ps.APP.C.dropped, dump_jsonl(trash_records() + [rec]))

    def ids(self):
        return sorted(r["id"] for r in trash_records())

    def test_hourly_purge_on_reads_with_a_fake_clock(self):
        """Normal reads prune once per hour while light polls leave the Trash file alone."""
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
    """Startup Trash cleanup starts the hourly retention clock."""

    def test_startup_purge_starts_the_hourly_clock(self):
        ps.APP.pin_trash.purge_trash()
        self.assertGreater(ps.APP.RT.trash_checked[0], time.time() - 5)


# ---------------------------------------------------------------- POST /api/clear: owner only, a confirmation phrase, a backup (v0.2.1 QA B)


class ClearEndpoint(AccessBase):
    """Bulk clear requires owner confirmation and archives every live pin."""

    def setUp(self):
        super().setUp()
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
        return sorted(p.name for p in ps.APP.C.state.glob("pins_*.jsonl.bak"))

    def assert_untouched(self):
        self.assertEqual(len(ps.APP.snapshot_pins()), 2)
        self.assertEqual(self.backups(), [])

    def test_only_the_owner_may_clear(self):
        _, tok = token_create(ps.APP.C.state, "ci")
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
        self.assertEqual(ps.APP.snapshot_pins(), [])
        self.assertEqual(self.backups(), [d["archive"]])
        rows = [json.loads(ln) for ln in (ps.APP.C.state / d["archive"]).read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["id"] for r in rows], [1, 2])
        ev = ps.APP.notices.read()[0][-1]
        self.assertEqual(
            (ev["type"], ev["by"]["login"], ev["n"], ev["archive"]), ("cleared", "alice@example.com", 2, d["archive"])
        )
        self.assertEqual(ev["to"], [])
        self.assertEqual(self.add(), 3)  # ids keep counting

    def test_clear_removes_live_shadows_before_archive(self):
        """Archived live pins cannot reappear in Trash while unrelated deleted pins stay restorable."""
        live_id = 1
        dropped_id = 2
        ps.APP.pin_trash.drop_pin(dropped_id, dict(A))
        old, _ = ps.APP.read_dropped()
        shadow = dict(ps.APP.read_pins()[0][0].record)
        shadow.update(dropped_by=B, dropped_at=time.strftime("%Y-%m-%d %H:%M:%S"))
        atomic_write(ps.APP.C.dropped, dump_jsonl([entry.record for entry in old] + [shadow]) + "{broken\n")
        self.assertEqual(self.call("POST", "/api/clear", CLEAR_BODY, ALICE)[0], 200)
        self.assertEqual([row["id"] for row in trash_records()], [dropped_id])
        self.assertEqual([row["id"] for row in ps.APP.pin_listing.dropped_payload()], [dropped_id])
        self.assertEqual(self.call("POST", "/api/pins/%d/restore" % live_id, None, ALICE)[0], 404)
        backups = list(ps.APP.C.state.glob("pins.dropped.jsonl.corrupt-*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertIn(b"{broken\n", backups[0].read_bytes())

    def test_clear_aborts_before_archive_when_shadow_cleanup_fails(self):
        """A failed Trash cleanup leaves live pins, their work list, and event and audit logs unchanged."""
        live_id = 1
        shadow = dict(ps.APP.read_pins()[0][0].record)
        shadow.update(dropped_by=B, dropped_at=time.strftime("%Y-%m-%d %H:%M:%S"))
        atomic_write(ps.APP.C.dropped, dump_jsonl([shadow]))
        before_live = ps.APP.C.pins_jsonl.read_bytes()
        before_md = ps.APP.C.pins_md.read_bytes()
        before_events = len(ps.APP.notices.read()[0])
        audit = ps.APP.C.audit_file
        before_audit = audit.read_bytes() if audit.exists() else b""
        with (
            mock.patch.object(limn_store.PinStore, "write_dropped", side_effect=OSError("read-only")),
            self.assertRaises(OSError),
        ):
            ps.APP.pin_trash.clear_pins(dict(A))
        self.assertEqual(ps.APP.C.pins_jsonl.read_bytes(), before_live)
        self.assertEqual(ps.APP.C.pins_md.read_bytes(), before_md)
        self.assertEqual([row["id"] for row in trash_records()], [live_id])
        self.assertEqual(self.backups(), [])
        self.assertEqual(len(ps.APP.notices.read()[0]), before_events)
        self.assertEqual(audit.read_bytes() if audit.exists() else b"", before_audit)

    def test_clear_render_failure_preserves_shadow_until_archive_can_start(self):
        """Empty Markdown preparation fails before any shadow cleanup or live archive."""
        shadow = dict(ps.APP.read_pins()[0][0].record)
        shadow.update(dropped_by=B, dropped_at=time.strftime("%Y-%m-%d %H:%M:%S"))
        atomic_write(ps.APP.C.dropped, dump_jsonl([shadow]))
        before_trash = ps.APP.C.dropped.read_bytes()
        before_live = ps.APP.C.pins_jsonl.read_bytes()
        with (
            mock.patch.object(ps.APP.pin_markdown, "pins_md_text", side_effect=RuntimeError("render failed")),
            self.assertRaisesRegex(RuntimeError, "render failed"),
        ):
            ps.APP.pin_trash.clear_pins(dict(A))
        self.assertEqual(ps.APP.C.dropped.read_bytes(), before_trash)
        self.assertEqual(ps.APP.C.pins_jsonl.read_bytes(), before_live)
        self.assertEqual(self.backups(), [])

    def test_clear_markdown_write_failure_keeps_archive_and_restart_repairs_list(self):
        """After archive rename, a Markdown failure keeps pin bytes in backup and startup clears stale work text."""
        shadow = dict(ps.APP.read_pins()[0][0].record)
        shadow.update(dropped_by=B, dropped_at=time.strftime("%Y-%m-%d %H:%M:%S"))
        atomic_write(ps.APP.C.dropped, dump_jsonl([shadow]))
        before_live = ps.APP.C.pins_jsonl.read_bytes()
        before_md = ps.APP.C.pins_md.read_bytes()
        before_events = len(ps.APP.notices.read()[0])
        audit = ps.APP.C.audit_file
        before_audit = audit.read_bytes() if audit.exists() else b""
        real_write = limn_store.atomic_write

        def fail_markdown(path, text):
            """Fail the first Markdown replacement after the live file has moved to its archive."""
            if path == ps.APP.C.pins_md:
                raise OSError("markdown unavailable")
            real_write(path, text)

        with (
            mock.patch.object(limn_store, "atomic_write", side_effect=fail_markdown),
            self.assertRaisesRegex(OSError, "markdown unavailable"),
        ):
            ps.APP.pin_trash.clear_pins(dict(A))
        self.assertFalse(ps.APP.C.pins_jsonl.exists())
        archives = self.backups()
        self.assertEqual(len(archives), 1)
        self.assertEqual((ps.APP.C.state / archives[0]).read_bytes(), before_live)
        self.assertEqual(ps.APP.C.pins_md.read_bytes(), before_md)
        self.assertEqual(trash_records(), [])
        self.assertEqual(len(ps.APP.notices.read()[0]), before_events)
        self.assertEqual(audit.read_bytes() if audit.exists() else b"", before_audit)

        fresh = ps.ServerApplication(ps.APP.C, ps.new_runtime(ps.APP.RT.viewer))
        with mock.patch.object(ps.build_run, "needs_build", return_value=False):
            self.assertIsNone(fresh.prepare(None, True))
        self.assertEqual(fresh.C.pins_md.read_text(encoding="utf-8"), fresh.pin_markdown.pins_md_text([]))
        self.assertEqual((fresh.C.state / archives[0]).read_bytes(), before_live)

    def test_local_owner_may_clear(self):
        set_config(auth="local", agent_loopback=False, local_user="alice")
        code, d = self.call("POST", "/api/clear", CLEAR_BODY)
        self.assertEqual((code, d.get("cleared")), (200, 2), d)

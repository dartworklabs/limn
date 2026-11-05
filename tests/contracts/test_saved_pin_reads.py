"""Saved revisions bind HTTP positions to durable state, independent of upkeep and runtime recreation."""

import json
import os
import threading
import time
from pathlib import Path
from unittest import mock

from limn.platform.files import ManuscriptFile

from helpers import Base, req, split_resp
from helpers_access import ALICE, configure


class TestSavedPinReads(Base):
    """Real HTTP requests and real files reproduce the stale-position edit without a fake store."""

    def response(self, method, path, body=None):
        """Dispatch one authenticated request, preserving the status and decoded response."""
        raw = b"" if body is None else json.dumps(body).encode()
        status, _, content = split_resp(
            self.talk(req(method, path, raw, {**ALICE, "Content-Type": "application/json"}))
        )
        return status, content

    def move(self):
        """Move every source line once with a reliably newer manuscript timestamp."""
        stamp = self.main.stat().st_mtime + 1
        self.main.write_text("% inserted\n" + self.main.read_text())
        os.utime(self.main, (stamp, stamp))

    def test_two_unsaved_moves_reject_old_position_even_after_runtime_recreation(self):
        """A revision observed after the first move cannot authorize an edit after the second, including restart."""
        from helpers import ps

        original = self.main.read_text()
        for restart in (False, "runtime", "startup"):
            with self.subTest(restart=restart):
                self.main.write_text(original)
                pid = self.add(lo=4, hi=4, actor={"login": "alice@example.com", "name": "Alice"})
                self.move()
                status, body = self.response("GET", f"/api/pins/{pid}")
                self.assertEqual(status, 200)
                seen = json.loads(body)["pin"]
                self.move()
                if restart:
                    configure(ps, self.src, self.main, ps.APP.C.state)
                    if restart == "startup":
                        ps.APP.assembly.pins.startup.maintain()
                self.assertEqual(self.response("GET", f"/api/pins/{pid}")[0], 200)
                status, body = self.response(
                    "POST", f"/api/pins/{pid}/edit", {"base_rev": seen["rev"], "lo": seen["lo"], "hi": seen["hi"]}
                )
                self.assertEqual(status, 409, body)
                # Re-sync is durable even when the edit is stale; a fresh view can edit normally.
                current = json.loads(self.response("GET", f"/api/pins/{pid}")[1])["pin"]
                self.assertGreater(current["rev"], seen["rev"])
                self.assertEqual(current["lo"], seen["lo"] + 2)
                ps.APP.assembly.pins.startup.maintain()
                self.assertEqual(
                    self.response("POST", f"/api/pins/{pid}/edit", {"base_rev": current["rev"], "note": "fresh"})[0],
                    200,
                )

    def test_read_routes_keep_saved_positions_and_revisions_without_writes(self):
        """Pins, Markdown, overlaps, counts and people never re-sync, while computed fields remain present."""
        from tests.contracts.test_get_write_guard import tree

        from helpers import ps

        pid = self.add(lo=4, hi=4)
        saved = json.loads(self.response("GET", f"/api/pins/{pid}")[1])["pin"]
        self.move()
        before = tree(ps.APP.C.state)
        for route in (
            "/api/pins",
            "/pins.md",
            f"/api/pins/{pid}",
            "/api/meta",
            "/api/people",
            f"/api/overlaps?file={self.main}&lo=4&hi=4",
        ):
            with self.subTest(route=route):
                status, body = self.response("GET", route)
                self.assertEqual(status, 200, body)
                if route == "/api/pins" or route == f"/api/pins/{pid}":
                    row = json.loads(body)[0] if route == "/api/pins" else json.loads(body)["pin"]
                    self.assertEqual((row["lo"], row["hi"], row["rev"]), (saved["lo"], saved["hi"], saved["rev"]))
                    self.assertTrue({"rel", "est", "state"} <= row.keys())
                if route == "/pins.md":
                    self.assertIn(b"L4-L4", body)
                if route.startswith("/api/overlaps"):
                    self.assertEqual(json.loads(body)["overlaps"][0]["lo"], 4)
                self.assertEqual(tree(ps.APP.C.state), before)

    def test_manuscript_change_runs_upkeep_without_a_request_and_shutdown_wakes_checker(self):
        """Startup's checker notices a non-main pinned source within one tick and stops promptly when idle."""
        from limn.pins.maintenance import CHECK_INTERVAL

        from helpers import add_pin, ps

        other = self.src / "section.tex"
        other.write_text(self.main.read_text())
        add_pin(
            {"file": str(other), "lo": 4, "hi": 4, "note": "section"}, {"login": "alice@example.com", "name": "Alice"}
        )
        startup = ps.APP.assembly.pins.startup
        startup.maintain()
        stop = threading.Event()
        worker = threading.Thread(target=startup.watch, args=(stop,))
        worker.start()
        try:
            other.write_text("% moved\n" + other.read_text())
            stamp = other.stat().st_mtime + 1
            os.utime(other, (stamp, stamp))
            deadline = time.monotonic() + CHECK_INTERVAL + 1.5
            while time.monotonic() < deadline:
                if json.loads(ps.APP.C.pins_jsonl.read_text())["lo"] == 5:
                    break
                stop.wait(0.02)
            self.assertEqual(json.loads(ps.APP.C.pins_jsonl.read_text())["lo"], 5)
        finally:
            started = time.monotonic()
            stop.set()
            worker.join(0.5)
            self.assertFalse(worker.is_alive())
            self.assertLess(time.monotonic() - started, 0.5)

    def test_a_moved_checkout_watches_a_missing_pinned_source_by_its_relative_name(self):
        """A checkout moved to another path without one pinned source yet: upkeep watches that source where its stored
        relative name puts it under the new root, so recreating it there moves the pin within one tick of the checker,
        not only on the 60 s pass (review of #404)."""
        import shutil

        from limn.pins.maintenance import CHECK_INTERVAL

        from helpers import add_pin, ps, set_config

        other = self.src / "section.tex"
        other.write_text(self.main.read_text())
        add_pin(
            {"file": str(other), "lo": 4, "hi": 4, "note": "section"}, {"login": "alice@example.com", "name": "Alice"}
        )
        moved = Path(self.tmp.name) / "moved"
        shutil.copytree(self.src, moved)
        (moved / "section.tex").unlink()
        set_config(src=moved, main=moved / self.main.name)
        startup = ps.APP.assembly.pins.startup
        startup.maintain()
        stop = threading.Event()
        worker = threading.Thread(target=startup.watch, args=(stop,))
        worker.start()
        try:
            again = moved / "section.tex"
            again.write_text("% moved\n" + other.read_text())
            stamp = again.stat().st_mtime + 1
            os.utime(again, (stamp, stamp))
            deadline = time.monotonic() + CHECK_INTERVAL + 1.5
            while time.monotonic() < deadline:
                if json.loads(ps.APP.C.pins_jsonl.read_text())["lo"] == 5:
                    break
                stop.wait(0.02)
            saved = json.loads(ps.APP.C.pins_jsonl.read_text())
            # Compare resolved paths: on macOS the temp folder /var/... is a link to /private/var/....
            self.assertEqual((saved["lo"], Path(saved["file"]).resolve()), (5, again.resolve()))
        finally:
            stop.set()
            worker.join(0.5)
            self.assertFalse(worker.is_alive())

    def test_unchanged_ticks_only_stat_and_do_not_read_files_or_run_a_pass(self):
        """Unchanged manuscripts incur no content reads or writes between the full sixty-second passes."""
        from tests.contracts.test_get_write_guard import tree

        from helpers import ps

        self.add()
        startup = ps.APP.assembly.pins.startup
        startup.maintain()
        before = tree(ps.APP.C.state)
        stop = threading.Event()
        with (
            mock.patch.object(stop, "wait", side_effect=[False, False, True]),
            mock.patch.object(Path, "read_text", side_effect=AssertionError("idle checker read text")) as text_reads,
            mock.patch.object(Path, "read_bytes", side_effect=AssertionError("idle checker read bytes")) as byte_reads,
            mock.patch.object(
                ManuscriptFile, "snapshot_checked", side_effect=AssertionError("idle checker read source")
            ) as source_reads,
        ):
            startup.watch(stop)
            text_reads.assert_not_called()
            byte_reads.assert_not_called()
            source_reads.assert_not_called()
        self.assertEqual(tree(ps.APP.C.state), before)

    def test_new_pin_registry_refreshes_watched_sources_without_a_request(self):
        """A pin saved after startup adds its non-main source to subsequent metadata checks."""
        from limn.pins.maintenance import CHECK_INTERVAL

        from helpers import add_pin, ps

        startup = ps.APP.assembly.pins.startup
        startup.maintain()
        other = self.src / "new-section.tex"
        other.write_text(self.main.read_text())
        add_pin(
            {"file": str(other), "lo": 4, "hi": 4, "note": "section"},
            {"login": "alice@example.com", "name": "Alice"},
        )
        other.write_text("% new\n" + other.read_text())
        stamp = other.stat().st_mtime + 1
        os.utime(other, (stamp, stamp))
        stop = threading.Event()
        worker = threading.Thread(target=startup.watch, args=(stop,))
        worker.start()
        try:
            deadline = time.monotonic() + CHECK_INTERVAL + 1.5
            while time.monotonic() < deadline:
                if json.loads(ps.APP.C.pins_jsonl.read_text())["lo"] == 5:
                    break
                stop.wait(0.02)
            self.assertEqual(json.loads(ps.APP.C.pins_jsonl.read_text())["lo"], 5)
        finally:
            stop.set()
            worker.join(1)
            self.assertFalse(worker.is_alive())

    def test_change_during_a_pass_remains_pending_for_the_next_check(self):
        """An edit after the source read cannot be mistaken for the last completed pass's baseline."""
        from limn.pins import store

        from helpers import ps

        self.add(lo=4, hi=4)
        startup = ps.APP.assembly.pins.startup
        startup.maintain()
        self.move()
        replace_files = store.replace_files

        def publish_then_edit(contents):
            """Publish real prepared files, then simulate an external author editing during the pass."""
            replace_files(contents)
            self.move()

        with mock.patch.object(store, "replace_files", side_effect=publish_then_edit):
            startup.maintain()
        self.assertEqual(json.loads(ps.APP.C.pins_jsonl.read_text())["lo"], 5)
        stop = threading.Event()
        with mock.patch.object(stop, "wait", side_effect=[False, True]):
            startup.watch(stop)
        self.assertEqual(json.loads(ps.APP.C.pins_jsonl.read_text())["lo"], 6)

    def test_failed_change_pass_keeps_the_successful_baseline_and_retries(self):
        """A failed change-driven pass preserves bytes; the next tick retries even without another edit."""
        from tests.contracts.test_get_write_guard import tree

        from helpers import ps

        self.add(lo=4, hi=4)
        startup = ps.APP.assembly.pins.startup
        startup.maintain()
        before = tree(ps.APP.C.state)
        self.move()
        stop = threading.Event()
        with (
            mock.patch.object(stop, "wait", side_effect=[False, True]),
            mock.patch("limn.pins.store.replace_files", side_effect=OSError("publication unavailable")),
        ):
            startup.watch(stop)
        self.assertEqual(tree(ps.APP.C.state), before)
        with mock.patch.object(stop, "wait", side_effect=[False, True]):
            startup.watch(stop)
        self.assertEqual(json.loads(ps.APP.C.pins_jsonl.read_text())["lo"], 5)

    def test_periodic_pass_prunes_trash_even_without_source_changes(self):
        """Time-based retention still converges after sixty seconds even if every stat is unchanged."""
        from datetime import datetime, timezone

        from helpers import ps

        self.add(lo=4, hi=4)
        row = json.loads(ps.APP.C.pins_jsonl.read_text())
        trash = ps.APP.C.state / "pins.dropped.jsonl"
        trash.write_text(json.dumps(dict(row, id=99, dropped_at=datetime.now(timezone.utc).isoformat())) + "\n")
        startup = ps.APP.assembly.pins.startup
        startup.maintain()
        self.assertNotEqual(trash.read_text(), "")
        later = time.time() + 31 * 86400
        next_period = time.monotonic() + 61
        stop = threading.Event()
        with (
            mock.patch.object(stop, "wait", side_effect=[False, True]),
            mock.patch("limn.pins.maintenance.time.monotonic", return_value=next_period),
            mock.patch("limn.pins.maintenance.time.time", return_value=later),
        ):
            startup.watch(stop)
        self.assertEqual(trash.read_text(), "")

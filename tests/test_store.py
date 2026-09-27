"""limn.store - the pin store's lock, write order and corrupt-line safety, driven directly with no server.

The store is built here from its explicit parts: a temp state directory, a fresh lock, a small record check, a fake
re-sync and a fake renderer. These tests pin the durable invariants of docs/handbook/architecture.md (불변식 4, 6)
and domain.md §저장소 안전성 at the store itself; the same behaviour through server.py (render failure, restore order,
concurrent saves, quarantined lines) is Store at the end of this file, and after it the reads that must never
rewrite a legacy record (LegacyPinsNotRewritten, LegacyMentionsNotRewritten).

Run: uv run pytest -q tests/test_store.py
"""

import ast
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from limn import build as limn_build, files, mapping, store
from limn.access import LOCAL_ACTOR
from limn.pins.edit import PinOutsideTree
from limn.pins.model import TrashedPin, parse_pin
from limn.pins.record import Broken
from limn.store import PinFiles, PinStore, dump_jsonl, find_pin
from limn.web.errors import InputRejected

from helpers import TEX, Base, add_pin, edit_pin, ps, record_of, records, req, trash_records, write_records

STORE_PY = Path(store.__file__)


def valid(r: object) -> bool:
    """The test's record check: a JSON object with an integer id."""
    return isinstance(r, dict) and isinstance(r.get("id"), int) and not isinstance(r.get("id"), bool)


def parse_rec(r: object):
    """The test's record parse: a record valid() lets through, parsed into its state; anything else Broken."""
    return parse_pin(r) if valid(r) else Broken()


def parse_trash(r: object):
    """The test's Trash parse: a record valid() lets through, parsed into its Trash copy; anything else Broken."""
    return TrashedPin.from_record(r) if valid(r) else Broken()


def render(pins: list) -> str:
    """A stand-in pins.md: one line per pin id, so the file shows exactly which pins it was rendered from."""
    return "".join("#%d\n" % p.core.id for p in pins)


class StoreBase(unittest.TestCase):
    """A store over a fresh temp state directory; sync() re-syncs nothing unless a test sets self.sync_result."""

    def setUp(self):
        """Fresh state directory, fresh lock, and a sync that reports self.sync_result (and records its calls)."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name)
        self.sync_result = False
        self.sync_calls = 0
        self.store = PinStore(PinFiles(self.state), threading.RLock(), parse_rec, parse_trash, self.sync, render)

    def sync(self, pins: list) -> bool:
        """Fake anchor re-sync: replaces every pin with one marked synced when self.sync_result is true, and says so."""
        self.sync_calls += 1
        if self.sync_result:
            for i, pin in enumerate(pins):
                pins[i] = parse_pin(dict(pin.record, synced=True))
        return self.sync_result

    def read(self):
        """(stored records, broken line numbers) of pins.jsonl as the store reads it."""
        pins, bad = self.store.read_pins()
        return records(pins), bad

    def put(self, text: str) -> None:
        """Writes pins.jsonl's raw text."""
        self.store.files.pins_jsonl.write_text(text, encoding="utf-8")

    def add(self, pid: int):
        """A transaction step that appends pin pid -> (pid, True)."""

        def fn(pins):
            """Appends the pin {id: pid} and reports a change."""
            pins.append(parse_pin({"id": pid}))
            return pid, True

        return fn


class ModuleBoundaryTest(unittest.TestCase):
    """The store is below the server: it must not reach back into server.py or the HTTP layer."""

    def test_imports_only_the_standard_library_and_limn_files(self):
        """store.py imports stdlib modules, limn.files and the pin types it hands out (limn.pins.model, and Broken from
        limn.pins.record) - its collaborators arrive as PinStore fields."""
        tree = ast.parse(STORE_PY.read_text(encoding="utf-8"))
        modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        modules |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        limn = {m for m in modules if m == "limn" or m.startswith("limn.")}
        self.assertEqual(limn, {"limn.files", "limn.pins.model", "limn.pins.record"})
        self.assertFalse({"http", "http.server", "urllib", "subprocess"} & modules)

    def test_reads_no_server_global(self):
        """No name of the server's run arguments or lock appears in store.py (they come in as fields)."""
        tree = ast.parse(STORE_PY.read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"C", "PIN_LOCK", "HTTPError", "sync_all", "pins_md_text", "parse_record", "cur_doc"})


class WriteOrderTest(StoreBase):
    """read -> sync -> change -> pins.jsonl -> pins.md, and nothing when the render fails."""

    def test_pins_md_is_written_after_pins_jsonl(self):
        """A transaction replaces pins.jsonl first and pins.md second, and pins.md shows the rows just written."""
        order = []
        real = store.atomic_write

        def spy(path, text, mode=None):
            """Records which file was replaced, then replaces it."""
            order.append(path.name)
            real(path, text, mode)

        with mock.patch.object(store, "atomic_write", side_effect=spy):
            self.store.transact(self.add(1))
        self.assertEqual(order, ["pins.jsonl", "pins.md"])
        self.assertEqual(self.store.files.pins_jsonl.read_text(encoding="utf-8"), '{"id": 1}\n')
        self.assertEqual(self.store.files.pins_md.read_text(encoding="utf-8"), "#1\n")

    def test_change_is_applied_after_sync(self):
        """fn sees rows the sync already changed, so its own change is never undone by the re-sync."""
        self.put('{"id": 1}\n')
        self.sync_result = True
        seen = []
        self.store.transact(lambda pins: (seen.append(pins[0].record), False))
        self.assertEqual(seen, [{"id": 1, "synced": True}])

    def test_failed_render_writes_nothing(self):
        """If pins.md cannot be rendered, neither file changes - a 500 after committing pins.jsonl makes a retry
        duplicate the pin."""
        self.put('{"id": 1}\n')

        def boom(rows):
            """A renderer that fails."""
            raise RuntimeError("boom")

        broken = PinStore(self.store.files, self.store.lock, parse_rec, parse_trash, self.sync, boom)
        with self.assertRaises(RuntimeError):
            broken.transact(self.add(2))
        self.assertEqual(self.store.files.pins_jsonl.read_text(encoding="utf-8"), '{"id": 1}\n')
        self.assertFalse(self.store.files.pins_md.exists())

    def test_returns_the_rows_and_the_step_result(self):
        """transact returns (rows as written, fn's result)."""
        rows, result = self.store.transact(self.add(7))
        self.assertEqual((records(rows), result), ([{"id": 7}], 7))


class WhenWrittenTest(StoreBase):
    """A step that changes nothing writes only when the re-sync changed rows; a refusal still writes the re-sync."""

    def test_unchanged_read_writes_nothing(self):
        """(result, False) with no re-sync change leaves the files untouched (pins.md is not even created)."""
        self.put('{"id": 1}\n')
        before = self.store.files.pins_jsonl.stat().st_mtime_ns
        rows, result = self.store.transact(lambda rows: ("r", False))
        self.assertEqual((records(rows), result), ([{"id": 1}], "r"))
        self.assertEqual(self.store.files.pins_jsonl.stat().st_mtime_ns, before)
        self.assertFalse(self.store.files.pins_md.exists())
        self.assertEqual(self.sync_calls, 1)

    def test_read_writes_when_sync_changed_rows(self):
        """(result, False) after a re-sync that moved rows writes the re-synced rows and pins.md."""
        self.put('{"id": 1}\n')
        self.sync_result = True
        self.assertEqual(records(self.store.snapshot()), [{"id": 1, "synced": True}])
        self.assertEqual(self.store.files.pins_jsonl.read_text(encoding="utf-8"), '{"id": 1, "synced": true}\n')
        self.assertEqual(self.store.files.pins_md.read_text(encoding="utf-8"), "#1\n")

    def test_an_infrastructure_error_after_a_resync_writes_nothing(self):
        """A step failing with an I/O error after a re-sync change writes nothing, not even the re-sync, and the error
        propagates. A refused request is a returned result, so no exception type is written through any more."""
        self.put('{"id": 1}\n')
        self.sync_result = True

        def fail(rows):
            """Fails the way a file read inside the step can."""
            raise OSError("io")

        with self.assertRaises(OSError):
            self.store.transact(fail)
        self.assertEqual(self.store.files.pins_jsonl.read_text(encoding="utf-8"), '{"id": 1}\n')
        self.assertFalse(self.store.files.pins_md.exists())

    def test_an_infrastructure_error_without_resync_writes_nothing(self):
        """The same error when the re-sync changed nothing leaves pins.jsonl untouched."""
        self.put('{"id": 1}\n')
        before = self.store.files.pins_jsonl.stat().st_mtime_ns

        def fail(rows):
            """Fails the way a file read inside the step can."""
            raise OSError("io")

        with self.assertRaises(OSError):
            self.store.transact(fail)
        self.assertEqual(self.store.files.pins_jsonl.stat().st_mtime_ns, before)

    def test_defect_writes_nothing_even_after_a_resync(self):
        """Any other exception writes nothing, not even the re-sync - the step may have left rows half-changed."""
        self.put('{"id": 1}\n')
        self.sync_result = True

        def defect(rows):
            """Half-changes rows, then fails."""
            rows[0] = parse_pin(dict(rows[0].record, half=True))
            raise KeyError("bug")

        with self.assertRaises(KeyError):
            self.store.transact(defect)
        self.assertEqual(self.store.files.pins_jsonl.read_text(encoding="utf-8"), '{"id": 1}\n')


class CorruptLineTest(StoreBase):
    """An unreadable line is skipped on read and its original bytes are backed up before the first rewrite."""

    CORRUPT = '{"id": 1}\n{not json\n{"id": "2"}\n\n{"id": 3}\n'

    def test_read_skips_bad_lines_and_numbers_them(self):
        """Unparseable and invalid lines are skipped with their 1-based numbers; blank lines are not counted as bad."""
        self.put(self.CORRUPT)
        self.assertEqual(self.read(), ([{"id": 1}, {"id": 3}], [2, 3]))

    def test_rewrite_backs_up_the_original_bytes(self):
        """The first write after a corrupt read copies the original file to pins.jsonl.corrupt-<time>.bak, byte for
        byte, and then writes only the readable rows (plus the change)."""
        self.put(self.CORRUPT)
        with mock.patch("time.strftime", return_value="20260926-100000"):
            self.store.transact(self.add(4))
        bak = self.state / "pins.jsonl.corrupt-20260926-100000.bak"
        self.assertEqual(bak.read_text(encoding="utf-8"), self.CORRUPT)
        self.assertEqual(self.store.files.pins_jsonl.read_text(encoding="utf-8"), '{"id": 1}\n{"id": 3}\n{"id": 4}\n')

    def test_second_backup_in_the_same_second_gets_a_new_name(self):
        """Two corrupt rewrites in one second keep both originals (-1 suffix), never overwriting the first."""
        self.put(self.CORRUPT)
        with mock.patch("time.strftime", return_value="20260926-100000"):
            self.store.transact(self.add(4))
            self.put("junk\n")
            self.store.transact(self.add(5))
        self.assertEqual(
            sorted(p.name for p in self.state.glob("*.bak")),
            ["pins.jsonl.corrupt-20260926-100000-1.bak", "pins.jsonl.corrupt-20260926-100000.bak"],
        )
        self.assertEqual((self.state / "pins.jsonl.corrupt-20260926-100000-1.bak").read_text(), "junk\n")

    def test_read_only_request_with_a_corrupt_line_writes_nothing(self):
        """A corrupt file is not rewritten (nor backed up) by a read that changes nothing."""
        self.put(self.CORRUPT)
        self.store.snapshot()
        self.assertEqual(list(self.state.glob("*.bak")), [])
        self.assertEqual(self.store.files.pins_jsonl.read_text(encoding="utf-8"), self.CORRUPT)

    def test_trash_rewrite_backs_up_the_original_bytes(self):
        """write_dropped keeps a corrupt Trash as pins.dropped.jsonl.corrupt-<time>.bak before rewriting it."""
        self.store.files.dropped.write_text('{"id": 1}\nbroken\n', encoding="utf-8")
        rows, bad = self.store.read_dropped()
        self.assertEqual((records(rows), bad), ([{"id": 1}], [2]))
        with mock.patch("time.strftime", return_value="20260926-100000"):
            self.store.write_dropped(rows, bad)
        self.assertEqual(
            (self.state / "pins.dropped.jsonl.corrupt-20260926-100000.bak").read_text(), '{"id": 1}\nbroken\n'
        )
        self.assertEqual(self.store.files.dropped.read_text(encoding="utf-8"), '{"id": 1}\n')

    def test_missing_file_reads_empty(self):
        """No pins.jsonl yet is an empty store, not an error."""
        self.assertEqual(self.read(), ([], []))


class LockTest(StoreBase):
    """One re-entrant lock orders every change; nested use under it works and excludes other threads."""

    def test_nested_transact_under_the_lock(self):
        """A caller holding the lock can run a transaction and more writes inside it (restore_pin does)."""
        with self.store.lock:
            self.store.transact(self.add(1))
            self.store.write_dropped([])
        self.assertEqual(records(self.store.read_pins()[0]), [{"id": 1}])

    def test_other_thread_waits_for_the_holder(self):
        """While one caller holds the lock, another thread's transaction does not read or write until it is
        released - so a bundle of transaction + Trash write is seen by others as one step."""
        started, done = threading.Event(), threading.Event()

        def other():
            """Runs a transaction from another thread."""
            started.set()
            self.store.transact(self.add(2))
            done.set()

        with self.store.lock:
            self.store.transact(self.add(1))
            t = threading.Thread(target=other)
            t.start()
            self.assertTrue(started.wait(5))
            self.assertFalse(done.wait(0.3))  # blocked on the lock
            self.assertEqual(records(self.store.read_pins()[0]), [{"id": 1}])
        t.join(5)
        self.assertTrue(done.is_set())
        self.assertEqual(records(self.store.read_pins()[0]), [{"id": 1}, {"id": 2}])

    def test_concurrent_saves_all_survive_with_unique_ids(self):
        """30 threads each add a pin with next_id at once: all 30 are kept with ids 1..30 (without the lock, 2 of
        30 survived - observed)."""
        barrier = threading.Barrier(30)

        def save():
            """Waits for the others, then appends one pin with a fresh id."""
            barrier.wait(5)
            self.store.transact(lambda pins: (pins.append(parse_pin({"id": self.store.next_id(pins)})), True))

        threads = [threading.Thread(target=save) for _ in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(sorted(p.core.id for p in self.store.read_pins()[0]), list(range(1, 31)))
        self.assertEqual(self.store.files.seq.read_text(), "30")


class IdTest(StoreBase):
    """Pin ids come from pins.seq and are never reused."""

    def test_next_id_is_past_both_seq_and_rows(self):
        """next_id is one more than the larger of pins.seq and the largest id in rows, and is recorded."""
        self.store.files.seq.write_text("9")
        self.assertEqual(self.store.next_id([parse_pin({"id": 3})]), 10)
        self.assertEqual(self.store.next_id([parse_pin({"id": 20})]), 21)
        self.assertEqual(self.store.files.seq.read_text(), "21")

    def test_unreadable_seq_counts_as_zero(self):
        """A garbled pins.seq falls back to the rows' largest id."""
        self.store.files.seq.write_text("x")
        self.assertEqual(self.store.next_id([parse_pin({"id": 4})]), 5)

    def test_init_seq_takes_the_max_over_live_archived_and_dropped(self):
        """A state directory without pins.seq gets it once from the largest id anywhere; an existing one is kept."""
        self.put('{"id": 2}\n')
        (self.state / "pins_260101_000000.jsonl.bak").write_text('{"id": 8}\n')
        self.store.files.dropped.write_text('{"id": 5}\n')
        self.store.init_seq()
        self.assertEqual(self.store.files.seq.read_text(), "8")
        self.store.files.seq.write_text("40")
        self.store.init_seq()
        self.assertEqual(self.store.files.seq.read_text(), "40")

    def test_clear_archives_and_keeps_the_seq(self):
        """clear moves pins.jsonl to pins_<time>.jsonl.bak (a second one the same second gets -1), renders an empty
        pins.md and leaves pins.seq alone, so ids keep going up."""
        self.store.transact(lambda pins: (pins.append(parse_pin({"id": self.store.next_id(pins)})), True))
        with mock.patch("time.strftime", return_value="260926_100000"):
            self.assertEqual(self.store.clear(), (1, "pins_260926_100000.jsonl.bak"))
            self.store.transact(self.add(9))
            self.assertEqual(self.store.clear(), (1, "pins_260926_100000-1.jsonl.bak"))
        self.assertFalse(self.store.files.pins_jsonl.exists())
        self.assertEqual(self.store.files.pins_md.read_text(), "")
        self.assertEqual(self.store.next_id([]), 2)

    def test_clear_without_pins_has_no_archive(self):
        """Clearing an empty store archives nothing."""
        self.assertEqual(self.store.clear(), (0, None))

    def test_clear_keeps_live_pins_when_empty_markdown_render_fails(self):
        """A failed empty-list render leaves the live file and work list intact, with no archive."""
        self.store.transact(self.add(1))
        before_pins = self.store.files.pins_jsonl.read_bytes()
        before_md = self.store.files.pins_md.read_bytes()

        def fail_render(_pins):
            """Simulate a renderer defect before clear changes any file."""
            raise RuntimeError("render failed")

        broken = PinStore(self.store.files, self.store.lock, parse_rec, parse_trash, self.sync, fail_render)
        with self.assertRaisesRegex(RuntimeError, "render failed"):
            broken.clear()
        self.assertEqual(self.store.files.pins_jsonl.read_bytes(), before_pins)
        self.assertEqual(self.store.files.pins_md.read_bytes(), before_md)
        self.assertEqual(list(self.state.glob("pins_*.jsonl.bak")), [])


class HelperTest(unittest.TestCase):
    """The two pure helpers: the stored line format and lookup by id."""

    def test_dump_jsonl_keeps_non_ascii_and_ends_each_line(self):
        """Each record is one compact JSON line with non-ASCII kept as is."""
        self.assertEqual(dump_jsonl([{"id": 1, "note": "고쳐"}, {"id": 2}]), '{"id": 1, "note": "고쳐"}\n{"id": 2}\n')

    def test_find_pin_returns_the_row_itself(self):
        """find_pin returns the stored row (so a step can change it in place), or None for a missing id."""
        rows = [{"id": 1}, {"id": 2}]
        self.assertIs(find_pin(rows, 2), rows[1])
        self.assertIsNone(find_pin(rows, 3))


# ---------------------------------------------------------------- through server.py's wiring
#
# The store under the running server's add, edit, clear and Trash. These classes load server.py (helpers.ps) and drive
# the module through its bindings; the tests above call the module on its own.


class Store(Base):
    """The server store keeps concurrent writes, malformed lines, and legacy pins safe."""

    def test_concurrent_adds_all_kept(self):
        """Thirty simultaneous adds retain thirty distinct ids and records under the store lock."""
        ids, errs = [], []

        def go(i):
            try:
                ids.append(self.add(note="c%d" % i))
            except Exception as e:  # noqa: BLE001
                errs.append(e)

        ts = [threading.Thread(target=go, args=(i,)) for i in range(30)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(errs, [])
        self.assertEqual(len(set(ids)), 30)
        self.assertEqual(len(ps.APP.snapshot_pins()), 30)

    def test_bad_record_is_quarantined_not_500(self):
        """A malformed stored pin is skipped and its original bytes survive the next transaction's rewrite."""
        self.add()
        with open(ps.APP.C.pins_jsonl, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": 900, "file": str(self.main), "lo": "5", "hi": None}) + "\n")
            fh.write(json.dumps({"id": 950, "lo": 3, "hi": 3}) + "\n")
        original = ps.APP.C.pins_jsonl.read_bytes()
        self.assertEqual([p.core.id for p in ps.APP.snapshot_pins()], [1])
        nid = self.add()
        self.assertEqual(nid, 2)
        backups = list(ps.APP.C.state.glob("pins.jsonl.corrupt-*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)

    def test_mistyped_fields_are_quarantined(self):
        """Invalid optional and required field types are skipped with the original file backed up."""
        self.add()
        good = {"file": str(self.main), "lo": 4, "hi": 4}
        bad = [
            dict(good, id=960, file="main.tex"),  # relative path
            dict(good, id=961, author="str"),
            dict(good, id=962, frac="bad"),
            dict(good, id=963, edited_by=5),
            dict(good, id=964, rev="x"),
            dict(good, id=965, synced_at="x"),
            dict(good, id=966, edited_at=5),
            dict(good, id=967, done="yes"),
            dict(good, id=968, frac=[0, 0, 1]),
            dict(good, id=969, author={"name": 3}),
        ]
        with open(ps.APP.C.pins_jsonl, "a", encoding="utf-8") as fh:
            for r in bad:
                fh.write(json.dumps(r) + "\n")
        os.utime(self.main, (time.time() + 5, time.time() + 5))  # so sync_all compares synced_at
        self.assertEqual([p.core.id for p in ps.APP.snapshot_pins()], [1])
        self.assertEqual(len(list(ps.APP.C.state.glob("pins.jsonl.corrupt-*.bak"))), 1)

    def test_out_of_tree_file_is_not_read(self):
        """Editing a pin outside the manuscript refuses access without leaking its file content."""
        outside = Path(self.tmp.name) / "outside.tex"
        outside.write_text("line one outsidesecret\nline two\n", encoding="utf-8")
        with open(ps.APP.C.pins_jsonl, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": 970, "file": str(outside), "lo": 1, "hi": 1, "anchor": {}}) + "\n")
        self.assertEqual(edit_pin(970, {"lo": 1, "hi": 2, "base_rev": 0}, dict(LOCAL_ACTOR)), PinOutsideTree())
        self.assertNotIn("outsidesecret", json.dumps(records(ps.APP.snapshot_pins())))

    def test_lines_edit_drops_via_score(self):
        pid = add_pin(
            {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "via": "synctex", "score": 0.74}, dict(LOCAL_ACTOR)
        ).record["id"]
        p = record_of(edit_pin(pid, {"lo": 4, "hi": 6, "scope": "lines", "base_rev": 0}, dict(LOCAL_ACTOR)))
        self.assertNotIn("via", p)
        self.assertNotIn("score", p)

    def test_stale_term_in_pins_md(self):
        pid = self.add(8, 9)
        self.main.write_text(
            TEX.replace("Body line seven betaunique.", "rewritten").replace(
                "Body line eight gammaunique.", "rewritten2"
            ),
            encoding="utf-8",
        )
        os.utime(self.main, (time.time() + 5, time.time() + 5))
        self.assertTrue(self.pin(pid).get("stale"))
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("%d · 위치 잃음" % pid, md)  # "위치 잃음" is spelled out in the number column (formerly ⚠)
        self.assertIn("'위치 잃음' = 위치를 되찾지 못함", md)  # the legend line
        self.assertNotIn("원문에서 사라짐", md)

    def test_render_failure_does_not_commit(self):
        """An in-memory pins.md render error leaves the live JSONL bytes unchanged."""
        self.add()
        before = ps.APP.C.pins_jsonl.read_text()
        with (
            mock.patch.object(ps.APP, "pins_md_text", side_effect=RuntimeError("boom")),
            self.assertRaises(RuntimeError),
        ):
            self.add(note="x")
        self.assertEqual(ps.APP.C.pins_jsonl.read_text(), before)

    def test_two_clears_same_second_keep_both(self):
        """Archive names remain unique when two clear operations share one timestamp."""
        self.add(note="FIRST")
        ps.APP.pin_trash.clear_pins()
        self.add(note="SECOND")
        ps.APP.pin_trash.clear_pins()
        baks = list(ps.APP.C.state.glob("pins_*.jsonl.bak"))
        self.assertEqual(len(baks), 2)
        blob = "".join(p.read_text() for p in baks)
        self.assertIn("FIRST", blob)
        self.assertIn("SECOND", blob)

    def test_restore_survives_failed_pins_write(self):
        """A failed live write keeps the Trash copy available for a later restore."""
        pid = self.add()
        ps.APP.pin_trash.drop_pin(pid, dict(LOCAL_ACTOR))
        # the transaction's own write
        with (
            mock.patch.object(PinStore, "write_prepared", side_effect=OSError("disk full")),
            self.assertRaises(OSError),
        ):
            ps.APP.pin_trash.restore_pin(pid, dict(LOCAL_ACTOR))
        self.assertIn(pid, [r["id"] for r in trash_records()])
        self.assertEqual(record_of(ps.APP.pin_trash.restore_pin(pid, dict(LOCAL_ACTOR)))["id"], pid)
        self.assertEqual(trash_records(), [])

    def test_edit_loc_keeps_page_frac_and_defaults_kind(self):
        pid = add_pin(
            {"file": str(self.main), "lo": 4, "hi": 5, "page": 3, "frac": [0.1, 0.2, 0.3, 0.4]}, dict(LOCAL_ACTOR)
        ).record["id"]
        p = record_of(
            edit_pin(pid, {"loc": {"file": str(self.main), "lo": 8, "hi": 9}, "base_rev": 0}, dict(LOCAL_ACTOR))
        )
        self.assertEqual((p["lo"], p["hi"], p["page"], p["kind"]), (8, 9, 3, "lines"))
        self.assertEqual(p["frac"], [0.1, 0.2, 0.3, 0.4])

    def test_add_pin_stamps_pdf_build(self):
        # design 1: pin the coordinate system frac points into by "which build it was" (pdf_build), not the wall clock.
        pid = self.add()
        self.assertEqual(self.pin(pid)["pdf_build"], limn_build.cur_pages(ps.APP.docs[0]).name)

    def test_add_pin_keeps_client_pdf_build(self):
        """A pin keeps the pdf_build the viewer sends; a bad name is refused as bad_pdf_build."""
        # the viewer sends back pdf_build from the pick response as-is (the build on screen at drag time) —
        # a drag made right after a rebuild, before the screen updates, must stay tagged with the old build.
        (ps.APP.C.state / "pages-20260101000000").mkdir()
        ps.APP.C.pages_ptr.write_text("pages-20260101000000")
        pid = add_pin(
            {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "pdf_build": "pages"}, dict(LOCAL_ACTOR)
        ).record["id"]
        self.assertEqual(self.pin(pid)["pdf_build"], "pages")
        self.assertEqual(
            add_pin({"file": str(self.main), "lo": 4, "hi": 5, "pdf_build": "../pins"}, dict(LOCAL_ACTOR)),
            InputRejected("pdf_build 는 쪽 디렉토리 이름(pages 또는 pages-<시각>)이어야 합니다.", "bad_pdf_build"),
        )

    def _new_build(self, name="pages-20260101000000"):
        (ps.APP.C.state / name).mkdir(exist_ok=True)
        ps.APP.C.pages_ptr.write_text(name)
        return name

    def test_edit_loc_with_new_frac_restamps_pdf_build(self):
        pid = add_pin(
            {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "frac": [0, 0, 1, 1]}, dict(LOCAL_ACTOR)
        ).record["id"]
        old_build = self.pin(pid)["pdf_build"]
        nb = self._new_build()
        p = record_of(
            edit_pin(
                pid,
                {"loc": {"file": str(self.main), "lo": 4, "hi": 5, "frac": [0.1, 0.1, 0.2, 0.2]}, "base_rev": 0},
                dict(LOCAL_ACTOR),
            )
        )
        self.assertNotEqual(p["pdf_build"], old_build)
        self.assertEqual(p["pdf_build"], nb)

    def test_edit_loc_without_frac_keeps_pdf_build_even_if_sent(self):
        pid = self.add()
        old_build = self.pin(pid)["pdf_build"]
        nb = self._new_build()
        p = record_of(
            edit_pin(
                pid,
                {"loc": {"file": str(self.main), "lo": 8, "hi": 9, "pdf_build": nb}, "base_rev": 0},
                dict(LOCAL_ACTOR),
            )
        )
        self.assertEqual(p["pdf_build"], old_build)

    def test_edit_loc_replaces_legacy_frac_build_field(self):
        pid = self.add()
        rows = records(ps.APP.read_pins()[0])
        rows[0].pop("pdf_build")
        rows[0]["frac_build"] = "pages"
        write_records(rows)
        nb = self._new_build()
        p = record_of(
            edit_pin(
                pid,
                {"loc": {"file": str(self.main), "lo": 4, "hi": 5, "frac": [0, 0, 1, 1]}, "base_rev": 0},
                dict(LOCAL_ACTOR),
            )
        )
        self.assertEqual(p["pdf_build"], nb)
        self.assertNotIn("frac_build", p)

    def test_edit_note_only_does_not_touch_pdf_build(self):
        # bug (must-2, branch a): editing just the note used to bump edited_at to now (old logic), turning off the "estimated" flag.
        pid = self.add()
        old_build = self.pin(pid)["pdf_build"]
        self._new_build()
        p = record_of(edit_pin(pid, {"note": "고친 메모", "base_rev": 0}, dict(LOCAL_ACTOR)))
        self.assertEqual(p["pdf_build"], old_build)

    def test_note_append_does_not_touch_pdf_build(self):
        pid = self.add()
        old_build = self.pin(pid)["pdf_build"]
        self._new_build()
        p = record_of(edit_pin(pid, {"note_append": "덧붙임"}, dict(LOCAL_ACTOR)))
        self.assertEqual(p["pdf_build"], old_build)

    def test_lo_hi_only_edit_does_not_touch_pdf_build(self):
        # moving lo/hi by hand without frac doesn't re-stamp the frac coordinates themselves, so pdf_build stays put too.
        pid = self.add()
        old_build = self.pin(pid)["pdf_build"]
        self._new_build()
        p = record_of(edit_pin(pid, {"lo": 4, "hi": 6, "base_rev": 0}, dict(LOCAL_ACTOR)))
        self.assertEqual(p["pdf_build"], old_build)

    def test_meta_exposes_pages_build(self):
        d = ps.APP.meta(ps.APP.docs[0], dict(LOCAL_ACTOR), light=True)
        self.assertEqual(d["pages_build"], limn_build.cur_pages(ps.APP.docs[0]).name)


class LegacyPinsNotRewritten(Base):
    """A record from before kinds and threads is read as it is: reads (the payload, GET /api/pins, GET /pins.md)
    never rewrite pins.jsonl."""

    def test_legacy_records_are_not_rewritten_by_reads(self):
        """Payload and HTTP reads preserve legacy JSONL bytes and mtime while deriving state."""
        legacy = {
            "id": 7,
            "file": str(self.main),
            "name": "main.tex",
            "lo": 4,
            "hi": 5,
            "page": 1,
            "note": "옛 핀",
            "at": "2026-09-21 20:00:00",
            "done": True,
            "done_at": "2026-09-21 21:00:00",
            "close_reply": "고침",
            "anchor": mapping.anchor_of(files.tex_lines(self.main), 4, 5),
            "synced_at": self.main.stat().st_mtime + 10,
        }
        ps.APP.C.pins_jsonl.write_text(json.dumps(legacy, ensure_ascii=False) + "\n", encoding="utf-8")
        before = ps.APP.C.pins_jsonl.read_bytes()
        mtime = ps.APP.C.pins_jsonl.stat().st_mtime_ns
        rows = ps.APP.pins_payload(ps.APP.snapshot_pins(), True)
        self.talk(req("GET", "/api/pins?all=1"))
        self.talk(req("GET", "/pins.md"))
        self.assertEqual(ps.APP.C.pins_jsonl.read_bytes(), before)
        self.assertEqual(ps.APP.C.pins_jsonl.stat().st_mtime_ns, mtime)
        self.assertEqual(rows[0]["state"], "done")
        self.assertNotIn("thread", rows[0])


class LegacyMentionsNotRewritten(Base):
    """A pin stored without mentions or assignee is read as it is: reads never rewrite pins.jsonl to add them."""

    S = {"login": "bob@example.com", "name": "Bob Park"}

    W = {"login": "wendy@example.com", "name": "Wendy Kim"}

    def setUp(self):
        super().setUp()

    def test_legacy_pins_read_without_rewrite(self):
        """Mention inference on old records remains a read-time view, not a stored migration."""
        ps.APP.record_person(dict(self.S))
        pid = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "@Bob Park 확인 부탁"}, dict(self.W)).record[
            "id"
        ]
        f = ps.APP.C.pins_jsonl
        before = f.read_bytes()
        for _ in range(2):
            ps.APP.pins_payload(ps.APP.snapshot_pins(), True)
            self.talk(req("GET", "/api/pins?all=1"))
            self.talk(req("GET", "/pins.md"))
        self.assertEqual(f.read_bytes(), before)
        self.assertNotIn("assignee", self.pin(pid))


if __name__ == "__main__":
    unittest.main()

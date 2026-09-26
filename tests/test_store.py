"""limn.store - the pin store's lock, write order and corrupt-line safety, driven directly with no server.

The store is built here from its explicit parts: a temp state directory, a fresh lock, a small record check, a fake
re-sync and a fake renderer. These tests pin the durable invariants of docs/handbook/architecture.md (불변식 4, 6)
and domain.md §저장소 안전성 at the store itself; the same behaviour through the HTTP API is pinned in
test_server.py (render failure, restore order, concurrent saves).

Run: uv run pytest -q tests/test_store.py
"""
import ast
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from limn import store
from limn.store import PinFiles, PinStore, dump_jsonl, find_pin

STORE_PY = Path(store.__file__)


class Refused(Exception):
    """The refusal a transaction step raises in these tests (the server passes its HTTPError)."""


def valid(r: object) -> bool:
    """The test's record check: a JSON object with an integer id."""
    return isinstance(r, dict) and isinstance(r.get("id"), int) and not isinstance(r.get("id"), bool)


def render(rows: list) -> str:
    """A stand-in pins.md: one line per pin id, so the file shows exactly which rows it was rendered from."""
    return "".join("#%d\n" % r["id"] for r in rows)


class StoreBase(unittest.TestCase):
    """A store over a fresh temp state directory; sync() re-syncs nothing unless a test sets self.sync_result."""

    def setUp(self):
        """Fresh state directory, fresh lock, and a sync that reports self.sync_result (and records its calls)."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name)
        self.sync_result = False
        self.sync_calls = 0
        self.store = PinStore(PinFiles(self.state), threading.RLock(), valid, self.sync, render, Refused)

    def sync(self, rows: list) -> bool:
        """Fake anchor re-sync: marks every row synced when self.sync_result is true, and says so."""
        self.sync_calls += 1
        if self.sync_result:
            for r in rows:
                r["synced"] = True
        return self.sync_result

    def put(self, text: str) -> None:
        """Writes pins.jsonl's raw text."""
        self.store.files.pins_jsonl.write_text(text, encoding="utf-8")

    def add(self, pid: int):
        """A transaction step that appends pin pid -> (pid, True)."""
        def fn(rows):
            """Appends {id: pid} and reports a change."""
            rows.append({"id": pid})
            return pid, True
        return fn


class ModuleBoundaryTest(unittest.TestCase):
    """The store is below the server: it must not reach back into server.py or the HTTP layer."""

    def test_imports_only_the_standard_library_and_limn_files(self):
        """store.py imports stdlib modules and limn.files only - its collaborators arrive as PinStore fields."""
        tree = ast.parse(STORE_PY.read_text(encoding="utf-8"))
        modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        modules |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        limn = {m for m in modules if m == "limn" or m.startswith("limn.")}
        self.assertEqual(limn, {"limn.files"})
        self.assertFalse({"http", "http.server", "urllib", "subprocess"} & modules)

    def test_reads_no_server_global(self):
        """No name of the server's run arguments or lock appears in store.py (they come in as fields)."""
        tree = ast.parse(STORE_PY.read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"C", "PIN_LOCK", "HTTPError", "sync_all", "pins_md_text", "valid_rec", "cur_doc"})


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
        self.store.transact(lambda rows: (seen.append(dict(rows[0])), False))
        self.assertEqual(seen, [{"id": 1, "synced": True}])

    def test_failed_render_writes_nothing(self):
        """If pins.md cannot be rendered, neither file changes - a 500 after committing pins.jsonl makes a retry
        duplicate the pin."""
        self.put('{"id": 1}\n')

        def boom(rows):
            """A renderer that fails."""
            raise RuntimeError("boom")
        broken = PinStore(self.store.files, self.store.lock, valid, self.sync, boom, Refused)
        with self.assertRaises(RuntimeError):
            broken.transact(self.add(2))
        self.assertEqual(self.store.files.pins_jsonl.read_text(encoding="utf-8"), '{"id": 1}\n')
        self.assertFalse(self.store.files.pins_md.exists())

    def test_returns_the_rows_and_the_step_result(self):
        """transact returns (rows as written, fn's result)."""
        rows, result = self.store.transact(self.add(7))
        self.assertEqual((rows, result), ([{"id": 7}], 7))


class WhenWrittenTest(StoreBase):
    """A step that changes nothing writes only when the re-sync changed rows; a refusal still writes the re-sync."""

    def test_unchanged_read_writes_nothing(self):
        """(result, False) with no re-sync change leaves the files untouched (pins.md is not even created)."""
        self.put('{"id": 1}\n')
        before = self.store.files.pins_jsonl.stat().st_mtime_ns
        rows, result = self.store.transact(lambda rows: ("r", False))
        self.assertEqual((rows, result), ([{"id": 1}], "r"))
        self.assertEqual(self.store.files.pins_jsonl.stat().st_mtime_ns, before)
        self.assertFalse(self.store.files.pins_md.exists())
        self.assertEqual(self.sync_calls, 1)

    def test_read_writes_when_sync_changed_rows(self):
        """(result, False) after a re-sync that moved rows writes the re-synced rows and pins.md."""
        self.put('{"id": 1}\n')
        self.sync_result = True
        self.assertEqual(self.store.snapshot(), [{"id": 1, "synced": True}])
        self.assertEqual(self.store.files.pins_jsonl.read_text(encoding="utf-8"), '{"id": 1, "synced": true}\n')
        self.assertEqual(self.store.files.pins_md.read_text(encoding="utf-8"), "#1\n")

    def test_refusal_still_writes_the_resync(self):
        """A step raising the refusal type after a re-sync change: the re-sync is written, the refusal propagates."""
        self.put('{"id": 1}\n')
        self.sync_result = True

        def refuse(rows):
            """Refuses the request."""
            raise Refused("no")
        with self.assertRaises(Refused):
            self.store.transact(refuse)
        self.assertEqual(self.store.files.pins_jsonl.read_text(encoding="utf-8"), '{"id": 1, "synced": true}\n')

    def test_refusal_without_resync_writes_nothing(self):
        """A refusal when the re-sync changed nothing leaves pins.jsonl as it was."""
        self.put('{"id": 1}\n')
        before = self.store.files.pins_jsonl.stat().st_mtime_ns

        def refuse(rows):
            """Refuses the request."""
            raise Refused("no")
        with self.assertRaises(Refused):
            self.store.transact(refuse)
        self.assertEqual(self.store.files.pins_jsonl.stat().st_mtime_ns, before)

    def test_defect_writes_nothing_even_after_a_resync(self):
        """Any other exception writes nothing, not even the re-sync - the step may have left rows half-changed."""
        self.put('{"id": 1}\n')
        self.sync_result = True

        def defect(rows):
            """Half-changes rows, then fails."""
            rows[0]["half"] = True
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
        self.assertEqual(self.store.read_pins(), ([{"id": 1}, {"id": 3}], [2, 3]))

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
        self.assertEqual(sorted(p.name for p in self.state.glob("*.bak")),
                         ["pins.jsonl.corrupt-20260926-100000-1.bak", "pins.jsonl.corrupt-20260926-100000.bak"])
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
        self.assertEqual((rows, bad), ([{"id": 1}], [2]))
        with mock.patch("time.strftime", return_value="20260926-100000"):
            self.store.write_dropped(rows, bad)
        self.assertEqual((self.state / "pins.dropped.jsonl.corrupt-20260926-100000.bak").read_text(),
                         '{"id": 1}\nbroken\n')
        self.assertEqual(self.store.files.dropped.read_text(encoding="utf-8"), '{"id": 1}\n')

    def test_missing_file_reads_empty(self):
        """No pins.jsonl yet is an empty store, not an error."""
        self.assertEqual(self.store.read_pins(), ([], []))


class LockTest(StoreBase):
    """One re-entrant lock orders every change; nested use under it works and excludes other threads."""

    def test_nested_transact_under_the_lock(self):
        """A caller holding the lock can run a transaction and more writes inside it (restore_pin does)."""
        with self.store.lock:
            self.store.transact(self.add(1))
            self.store.write_dropped([])
        self.assertEqual(self.store.read_pins()[0], [{"id": 1}])

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
            self.assertFalse(done.wait(0.3))           # blocked on the lock
            self.assertEqual(self.store.read_pins()[0], [{"id": 1}])
        t.join(5)
        self.assertTrue(done.is_set())
        self.assertEqual(self.store.read_pins()[0], [{"id": 1}, {"id": 2}])

    def test_concurrent_saves_all_survive_with_unique_ids(self):
        """30 threads each add a pin with next_id at once: all 30 are kept with ids 1..30 (without the lock, 2 of
        30 survived - observed)."""
        barrier = threading.Barrier(30)

        def save():
            """Waits for the others, then appends one pin with a fresh id."""
            barrier.wait(5)
            self.store.transact(lambda rows: (rows.append({"id": self.store.next_id(rows)}), True))
        threads = [threading.Thread(target=save) for _ in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(sorted(r["id"] for r in self.store.read_pins()[0]), list(range(1, 31)))
        self.assertEqual(self.store.files.seq.read_text(), "30")


class IdTest(StoreBase):
    """Pin ids come from pins.seq and are never reused."""

    def test_next_id_is_past_both_seq_and_rows(self):
        """next_id is one more than the larger of pins.seq and the largest id in rows, and is recorded."""
        self.store.files.seq.write_text("9")
        self.assertEqual(self.store.next_id([{"id": 3}]), 10)
        self.assertEqual(self.store.next_id([{"id": 20}]), 21)
        self.assertEqual(self.store.files.seq.read_text(), "21")

    def test_unreadable_seq_counts_as_zero(self):
        """A garbled pins.seq falls back to the rows' largest id."""
        self.store.files.seq.write_text("x")
        self.assertEqual(self.store.next_id([{"id": 4}]), 5)

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
        self.store.transact(lambda rows: (rows.append({"id": self.store.next_id(rows)}), True))
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


if __name__ == "__main__":
    unittest.main()

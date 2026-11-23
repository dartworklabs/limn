"""limn.pins.store - what a stored line parses to, kept between reads by the line's own text (KeptLines, KeptPinReader).

Three things are pinned here (docs/handbook/domain.md §저장소 안전성, architecture.md §HTTP 읽기 능력과 유지 실행):

- a reader that keeps answers exactly what a reader that does not keep answers, whatever was written in between;
- a line already read is not parsed again - work is counted in parse calls and in executed lines, never timed
  (docs/handbook/verification.md §불안정한 테스트);
- a writer never reads what is kept and never fills it, so nothing kept can reach a pin file.

The first part builds the readers from their explicit parts over a temporary state folder, as test_store.py builds a
store; the second goes through the run's composition (Base).

Run: uv run pytest -q src/limn/pins/tests/test_kept_lines.py
"""

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from hypothesis import given, settings, strategies as st

from limn.pins import record as record_module
from limn.pins.model import TrashedPin, parse_pin
from limn.pins.record import Broken
from limn.pins.store import KeptLines, KeptPinReader, PinFiles, PinLines, PinReader, PinStore, dump_jsonl, line_value
from limn.security.access import LOCAL_ACTOR
from limn.viewer.assemble import ServedViewer

from helpers import Base, edit_pin, forget_kept_lines, fresh_runtime, ps, records, write_records
from helpers_access import A_LOGIN, ALICE, CLEAR_BODY, LOOPBACK_AGENT, AccessBase
from helpers_authority import post_authority

DEEP = "[" * 100_000 + "]" * 100_000  # more nesting than json.loads takes on any supported interpreter


def valid(r: object) -> bool:
    """The test's record check: a JSON object with an integer id."""
    return isinstance(r, dict) and isinstance(r.get("id"), int) and not isinstance(r.get("id"), bool)


def line(pid: int, note: str = "n") -> str:
    """One stored line: the compact JSON of a record with this id and note."""
    return json.dumps({"id": pid, "note": note}, ensure_ascii=False)


def shown(read: tuple[list, list[int]]) -> tuple[list[dict], list[int]]:
    """A read as plain data: the stored record of each value in order, and the broken line numbers."""
    values, bad = read
    return records(values), bad


class Readers(unittest.TestCase):
    """A keeping reader, a plain reader and a store over one temporary state folder, with a parse that counts."""

    def setUp(self):
        """Fresh folder, fresh lock, fresh kept lines; self.calls counts every record handed to either parse."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.files = PinFiles(Path(self.tmp.name))
        self.calls = 0
        self.lines = PinLines()
        lock = threading.RLock()
        self.plain = PinReader(self.files, lock, self.parse, self.parse_trashed)
        self.kept = KeptPinReader(self.files, lock, self.parse, self.parse_trashed, self.lines)
        self.store = PinStore(self.files, lock, self.parse, self.parse_trashed, lambda pins: False, lambda pins: "md\n")

    def parse(self, r: object):
        """The live parse, counted: a record valid() lets through as its state, anything else Broken."""
        self.calls += 1
        return parse_pin(r) if valid(r) else Broken()

    def parse_trashed(self, r: object):
        """The Trash parse, counted: a record valid() lets through as its Trash copy, anything else Broken."""
        self.calls += 1
        return TrashedPin.from_record(r) if valid(r) else Broken()

    def put(self, *lines: str) -> None:
        """Write pins.jsonl as these lines, each ended by a newline."""
        self.files.pins_jsonl.write_text("".join(t + "\n" for t in lines), encoding="utf-8")

    def parses(self, call) -> int:
        """How many records the parses were handed while call() ran."""
        before = self.calls
        call()
        return self.calls - before


# What a pin file may hold line by line: readable records, one of them twice over, a non-ASCII note, a blank line,
# text that is not JSON, JSON the record check refuses, and a record that differs from another by one character.
POOL = [
    line(1),
    line(2, "two"),
    line(2, "twp"),
    line(3, "메모 — 비ASCII ✓"),
    "",
    "   ",
    "{not json",
    '{"id": "x"}',
    "[1, 2]",
    line(7, "x" * 300),
]


class KeptReadsAnswerAsPlainReads(Readers):
    """Whatever is written between reads, a reader that keeps answers what a reader that parses every line does."""

    @settings(max_examples=150)
    @given(st.lists(st.lists(st.sampled_from(POOL), max_size=12), min_size=1, max_size=6))
    def test_every_read_of_every_version_is_the_plain_read(self, versions):
        """For any sequence of file contents - lines repeated, changed, added, removed, reordered, blank, broken -
        each version's live and Trash reads through the keeping reader equal the plain reader's, values and broken
        line numbers alike."""
        for version in versions:
            text = "".join(t + "\n" for t in version)
            self.files.pins_jsonl.write_text(text, encoding="utf-8")
            self.files.dropped.write_text(text, encoding="utf-8")
            self.assertEqual(shown(self.kept.read_pins()), shown(self.plain.read_pins()))
            self.assertEqual(shown(self.kept.read_dropped()), shown(self.plain.read_dropped()))

    def test_a_file_rewritten_in_place_at_the_same_size_is_read_as_it_is_now(self):
        """A file changed in place - same inode, same size, its times put back - is answered from its text now: a
        stat cannot tell these two versions apart, and the keeping reader does not ask one."""
        self.put(line(1, "aaa"), line(2))
        before = os.stat(self.files.pins_jsonl)
        self.assertEqual(shown(self.kept.read_pins())[0][0]["note"], "aaa")
        with open(self.files.pins_jsonl, "r+", encoding="utf-8") as fh:
            fh.write(line(1, "bbb"))
        os.utime(self.files.pins_jsonl, ns=(before.st_atime_ns, before.st_mtime_ns))
        after = os.stat(self.files.pins_jsonl)
        self.assertEqual(
            (after.st_ino, after.st_size, after.st_mtime_ns), (before.st_ino, before.st_size, before.st_mtime_ns)
        )
        self.assertEqual(shown(self.kept.read_pins()), ([{"id": 1, "note": "bbb"}, {"id": 2, "note": "n"}], []))

    def test_duplicate_and_reordered_lines_keep_their_places(self):
        """A line that is in the file twice is answered at both places, and lines that swapped places are answered in
        the file's order with the broken ones numbered where they are now."""
        self.put(line(1), "{not json", line(2), line(1))
        self.assertEqual(shown(self.kept.read_pins()), shown(self.plain.read_pins()))
        self.put(line(2), line(1), line(1), "{not json")
        self.assertEqual(shown(self.kept.read_pins()), ([{"id": 2, "note": "n"}] + [{"id": 1, "note": "n"}] * 2, [4]))

    def test_live_and_trash_lines_are_kept_apart(self):
        """The same text in both files is a pin in one and a Trash copy in the other: neither read is answered with
        what the other kept."""
        self.put(line(1))
        self.files.dropped.write_text(line(1) + "\n", encoding="utf-8")
        self.kept.read_pins()
        self.kept.read_dropped()
        self.assertNotIsInstance(self.kept.read_pins()[0][0], TrashedPin)
        self.assertIsInstance(self.kept.read_dropped()[0][0], TrashedPin)

    def test_each_read_hands_out_its_own_list(self):
        """A caller that empties or reorders the list it was handed changes nothing for the next read."""
        self.put(line(1), line(2))
        first, bad = self.kept.read_pins()
        first.clear()
        bad.append(99)
        self.assertEqual(shown(self.kept.read_pins()), shown(self.plain.read_pins()))

    def test_the_snapshot_reads_through_what_is_kept(self):
        """snapshot() of a keeping reader is its read_pins(): the same pins, and no parse for lines already read."""
        self.put(line(1), line(2))
        self.kept.read_pins()
        self.assertEqual(
            self.parses(lambda: self.assertEqual(records(self.kept.snapshot()), records(self.plain.snapshot()))), 2
        )


class ALineIsParsedOnce(Readers):
    """The parse runs for the lines that changed since the last read, not for the lines of the file."""

    def test_an_unchanged_file_is_not_parsed_again(self):
        """The first read parses every line; a second read of the same file parses none."""
        self.put(*(line(i) for i in range(1, 41)))
        self.assertEqual(self.parses(self.kept.read_pins), 40)
        self.assertEqual(self.parses(self.kept.read_pins), 0)

    def test_one_changed_line_is_one_parse(self):
        """After one of eighty lines is rewritten, the next read parses that line alone."""
        rows = [line(i) for i in range(1, 81)]
        self.put(*rows)
        self.kept.read_pins()
        rows[40] = line(41, "changed")
        self.put(*rows)
        self.assertEqual(self.parses(self.kept.read_pins), 1)

    def test_rereading_costs_no_parse_whatever_the_number_of_lines(self):
        """Reading a file again costs the same number of parses for 40 lines as for 80: none."""
        self.put(*(line(i) for i in range(1, 41)))
        self.kept.read_pins()
        small = self.parses(self.kept.read_pins)
        self.put(*(line(i) for i in range(1, 81)))
        self.kept.read_pins()
        large = self.parses(self.kept.read_pins)
        self.assertEqual((small, large), (0, 0))

    def test_a_line_that_repeats_is_parsed_once(self):
        """A line that is in the file three times is parsed once at the first read."""
        self.put(line(1), line(2), line(1), line(1))
        self.assertEqual(self.parses(self.kept.read_pins), 2)

    def test_a_broken_line_is_kept_and_numbered_at_each_read(self):
        """A line the parse calls Broken is not parsed again, and its number is the place it has in the file now."""
        self.put(line(1), "{not json", '{"id": "x"}')
        self.assertEqual(self.kept.read_pins()[1], [2, 3])
        self.assertEqual(self.parses(self.kept.read_pins), 0)
        self.put(line(9), line(1), "{not json", '{"id": "x"}')
        self.assertEqual(self.parses(lambda: self.assertEqual(self.kept.read_pins()[1], [3, 4])), 1)

    def test_a_line_at_the_nesting_limit_is_judged_at_each_read(self):
        """A line json.loads gives up on for its depth is Broken at every read and is never kept: that verdict
        depends on the reader's stack, not on the text alone."""
        self.put(line(1), DEEP)
        self.assertEqual(shown(self.kept.read_pins()), ([{"id": 1, "note": "n"}], [2]))
        self.assertEqual(self.parses(lambda: self.assertEqual(self.kept.read_pins()[1], [2])), 1)
        self.assertEqual(set(self.lines.live.held()), {line(1)})

    def test_a_missing_file_empties_what_was_kept(self):
        """With pins.jsonl gone a read answers nothing and keeps nothing; when the file is back its lines are parsed
        afresh."""
        self.put(line(1), line(2))
        self.kept.read_pins()
        self.files.pins_jsonl.unlink()
        self.assertEqual(self.kept.read_pins(), ([], []))
        self.assertEqual(dict(self.lines.live.held()), {})
        self.put(line(1), line(2))
        self.assertEqual(self.parses(self.kept.read_pins), 2)

    def test_lines_that_left_the_file_leave_what_is_kept(self):
        """What is kept is the lines of the latest read: a line no longer in the file is dropped by the next read."""
        self.put(line(1), line(2), line(3))
        self.kept.read_pins()
        self.put(line(1), line(3))
        self.kept.read_pins()
        self.assertEqual(set(self.lines.live.held()), {line(1), line(3)})

    def test_what_is_kept_stays_within_the_limit(self):
        """Kept lines never add up to more characters than the limit: the file's first lines are kept, the rest is
        parsed at every read, and the answer is the plain one."""
        lines = PinLines(live=KeptLines(limit=3 * len(line(10))))
        kept = KeptPinReader(self.files, threading.RLock(), self.parse, self.parse_trashed, lines)
        self.put(*(line(i) for i in range(10, 20)))
        self.assertEqual(shown(kept.read_pins()), shown(self.plain.read_pins()))
        self.assertEqual(list(lines.live.held()), [line(10), line(11), line(12)])
        self.assertEqual(
            self.parses(lambda: self.assertEqual(shown(kept.read_pins()), shown(self.plain.read_pins()))), 7 + 10
        )

    def test_a_line_longer_than_the_limit_ends_the_keeping(self):
        """Once a line does not fit, no later line is kept either, however short: what is kept is a prefix of the
        file, so which lines are kept does not depend on their sizes further down."""
        lines = PinLines(live=KeptLines(limit=len(line(1)) + len(line(2))))
        kept = KeptPinReader(self.files, threading.RLock(), self.parse, self.parse_trashed, lines)
        self.put(line(1), line(5, "x" * 500), line(2))
        kept.read_pins()
        self.assertEqual(list(lines.live.held()), [line(1)])


class AWriterKeepsNothing(Readers):
    """A store beside a keeping reader parses every line of every read and neither reads nor fills what is kept."""

    def test_a_store_parses_every_time_and_keeps_nothing(self):
        """A store's reads parse the whole file each time and leave no line kept."""
        self.put(line(1), line(2), line(3))
        self.assertEqual(self.parses(self.store.read_pins), 3)
        self.assertEqual(self.parses(self.store.read_pins), 3)
        self.assertEqual(self.parses(lambda: self.store.transact(lambda pins: (None, False))), 3)
        self.assertEqual(dict(self.lines.live.held()), {})

    def test_a_store_does_not_read_what_a_reader_kept(self):
        """After a reader kept every line, a store still parses them all."""
        self.put(line(1), line(2), line(3))
        self.kept.read_pins()
        self.assertEqual(self.parses(self.store.read_pins), 3)
        self.assertEqual(self.parses(self.store.read_dropped), 0)  # no Trash file

    def test_what_a_transaction_changes_is_not_what_is_kept(self):
        """A transaction step that changes the pins it was handed, inside and out, leaves the kept values equal to a
        fresh parse of their lines."""
        self.put(line(1), line(2))
        self.kept.read_pins()

        def step(pins):
            """Change a nested value of the first pin in place, drop the second, and report a change."""
            pins[0].fields["note"] = "rewritten in place"
            del pins[1]
            return None, True

        self.store.transact(step)
        for text, value in self.lines.live.held().items():
            self.assertEqual(value.record, json.loads(text))


class ReadersRacingAWriter(Readers):
    """Readers that share what is kept each answer one whole version of the file while it is being replaced."""

    def test_readers_racing_a_writer_each_answer_the_text_they_read(self):
        """Four threads read while a fifth replaces the file atomically with the other of two versions. Every read is
        the plain parse of one of the two versions, never a mixture and never a stale third. All five leave a barrier
        together each round, so readers and the writer overlap without a sleep or a poll; which of them runs first
        within a round is the scheduler's, and the assertion holds for every order."""
        one = [line(i, "one") for i in range(1, 31)]
        two = [line(i, "two") for i in range(1, 31)] + [line(99, "two")]
        answers = {tuple(json.dumps(r) for r in map(json.loads, version)) for version in (one, two)}
        self.put(*one)
        rounds, readers = 40, 4
        barrier = threading.Barrier(readers + 1)
        seen: list[tuple[str, ...]] = []
        failures: list[BaseException] = []
        gather = threading.Lock()

        def read():
            """Read once per round, as soon as the round's barrier lets go."""
            try:
                for _ in range(rounds):
                    barrier.wait(timeout=60)
                    pins, bad = self.kept.read_pins()
                    with gather:
                        seen.append(tuple(json.dumps(pin.record) for pin in pins))
                        if bad:
                            failures.append(AssertionError("broken lines %s" % bad))
            except BaseException as error:  # noqa: BLE001 - reported by the test thread below
                failures.append(error)
                barrier.abort()

        def write():
            """Replace the file once per round with the version it does not hold, by rename."""
            try:
                for turn in range(rounds):
                    barrier.wait(timeout=60)
                    tmp = self.files.pins_jsonl.with_name("next")
                    tmp.write_text("".join(t + "\n" for t in (two if turn % 2 == 0 else one)), encoding="utf-8")
                    os.replace(tmp, self.files.pins_jsonl)
            except BaseException as error:  # noqa: BLE001 - reported by the test thread below
                failures.append(error)
                barrier.abort()

        threads = [threading.Thread(target=read) for _ in range(readers)] + [threading.Thread(target=write)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(120)
        self.assertEqual(failures, [])
        self.assertEqual(len(seen), rounds * readers)
        self.assertLessEqual(set(seen), answers)
        self.assertEqual(shown(self.kept.read_pins()), shown(self.plain.read_pins()))


class LineValue(unittest.TestCase):
    """line_value: what one line parses to, and whether that is a function of its text alone."""

    def test_a_readable_line_and_a_line_that_is_not_json_are_settled(self):
        """A record and a syntax error are both verdicts about the text: settled."""
        self.assertEqual(line_value(line(1), lambda r: r), ({"id": 1, "note": "n"}, True))
        self.assertEqual(line_value("{not json", lambda r: Broken() if r is None else r), (Broken(), True))

    def test_a_line_past_the_nesting_limit_is_broken_and_not_settled(self):
        """A line json.loads cannot descend is handed to the parse as nothing (so it is Broken) and is not settled."""
        self.assertEqual(line_value(DEEP, lambda r: Broken() if r is None else r), (Broken(), False))


def lines_run(module, call):
    """How many lines of `module` run while call() does: a count of work that a busy machine does not change, where
    a clock would (docs/handbook/verification.md §불안정한 테스트). Returns (count, call's result)."""
    wanted = module.__file__
    count = 0

    def tracer(frame, event, _arg):
        """Count line events of the wanted file; follow no other frame."""
        nonlocal count
        if frame.f_code.co_filename != wanted:
            return None
        count += event == "line"
        return tracer

    sys.settrace(tracer)
    try:
        result = call()
    finally:
        sys.settrace(None)
    return count, result


def reply(pid: int) -> None:
    """Add the reply "ok" to pin pid as the local agent, through the pin service's transaction."""
    store = ps.APP.pin_lifecycle.context().store
    ps.APP.pin_lifecycle.reply_pin(pid, "ok", post_authority(store, dict(LOCAL_ACTOR), "reply", pid))


class ARunParsesAStoredLineOnce(Base):
    """Through the run's composition: every way of reading the pins checks a stored record once per run, not once
    per request."""

    def fill(self, count):
        """Leave `count` open line pins on main.tex (ids 1..count), each with a note."""
        rows = records(ps.APP.pin_store().read_pins()[0])
        if not rows:
            self.add()
            rows = records(ps.APP.pin_store().read_pins()[0])
        base = dict(rows[0])
        write_records(
            [{**base, "id": i, "lo": 4 + i % 3, "hi": 5 + i % 3, "note": "request %d" % i} for i in range(1, count + 1)]
        )

    def reads(self):
        """Every read of the pins a request can cause, by name."""
        app = ps.APP
        return {
            "the list": lambda: app.pin_listing.list_payload(True),
            "one pin": lambda: app.pin_listing.pin_payload(7),
            "pins.md": lambda: app.pin_markdown.current_text("http://127.0.0.1:1", LOOPBACK_AGENT),
            "the state counts of meta": lambda: app.assembly.pins.counts.state_counts(),
            "the open counts of docs": lambda: app.assembly.pins.counts.counts_by_document({app.docs[0].key}),
            "the Trash": lambda: app.pin_listing.dropped_payload(),
        }

    def checked(self, call) -> int:
        """The lines of the record check (limn.pins.record) that run during call()."""
        return lines_run(record_module, call)[0]

    def test_a_second_read_runs_no_line_of_the_record_check(self):
        """Each read checks the stored records the first time a run makes it and runs no line of the check when it
        is made again."""
        for name, read in self.reads().items():
            with self.subTest(read=name):
                self.fill(40)
                fresh_runtime()
                self.assertGreater(self.checked(read), 0)
                self.assertEqual(self.checked(read), 0)

    def test_what_one_read_kept_serves_the_others(self):
        """After the list was read once, no other read of the live pins runs a line of the record check."""
        self.fill(40)
        reads = self.reads()
        reads["the list"]()
        for name in ("one pin", "pins.md", "the state counts of meta", "the open counts of docs"):
            with self.subTest(read=name):
                self.assertEqual(self.checked(reads[name]), 0)

    def test_a_write_costs_the_next_read_one_line(self):
        """After a reply to one pin, the next list checks that pin's record alone: the same number of lines of the
        check whether 40 or 80 pins are stored."""
        costs = []
        for count in (40, 80):
            self.fill(count)
            ps.APP.pin_listing.list_payload(True)
            reply(7)
            costs.append(self.checked(lambda: ps.APP.pin_listing.list_payload(True)))
        self.assertGreater(costs[0], 0)
        self.assertEqual(costs[1], costs[0])

    def test_two_runs_share_nothing(self):
        """A fresh run's first read checks every record again: what one run kept is not another's."""
        self.fill(40)
        first = self.checked(lambda: ps.APP.pin_listing.list_payload(True))
        fresh_runtime()
        self.assertEqual(self.checked(lambda: ps.APP.pin_listing.list_payload(True)), first)


class EachRunHasItsOwnKeptLines(unittest.TestCase):
    """The composition root's resources of a run (limn.server.new_runtime), as a starting server makes them."""

    def test_two_runs_get_separate_kept_lines(self):
        """Two runs in one process - two servers, or a restart - share no kept lines, and within a run the live
        file and the Trash each have their own."""
        viewer = ServedViewer("<p></p>", "", {})
        one, two = ps.new_runtime(viewer).pin_lines, ps.new_runtime(viewer).pin_lines
        self.assertIsInstance(one, PinLines)
        kept = [one.live, one.dropped, two.live, two.dropped]
        self.assertEqual(len({id(lines) for lines in kept}), 4)
        self.assertTrue(all(type(lines) is KeptLines for lines in kept))


class WritersDoNotReadWhatIsKept(Base):
    """Nothing that is written to a pin file comes from what is kept: a wrong kept value never reaches the disk."""

    def tearDown(self):
        """Forget what the run keeps: these tests gave it a wrong value on purpose, which the base's audit of what
        readers changed (helpers.kept_lines_changed) would report."""
        forget_kept_lines()
        super().tearDown()

    def poison(self):
        """Two pins on disk, and the first one's line kept as if it parsed to the second pin - a wrong value that
        any reader of what is kept would hand on. Returns the state folder's pin files."""
        self.add(4, 5, note="first")
        self.add(8, 9, note="second")
        files = PinFiles(ps.APP.C.state)
        texts = [t for t in files.pins_jsonl.read_text(encoding="utf-8").splitlines() if t.strip()]
        wrong = parse_pin(json.loads(texts[1]))
        ps.APP.RT.pin_lines.live.values(texts, lambda text: (wrong, True))
        self.assertEqual([pin.core.note for pin in ps.APP.read_pins()[0]], ["second", "second"])
        return files

    def honest_md(self):
        """pins.md as rendered from a fresh parse of pins.jsonl, its minute stamp line dropped."""
        return self.unstamped(ps.APP.pin_markdown.pins_md_text(ps.APP.pin_store().read_pins()[0]))

    @staticmethod
    def unstamped(md: str) -> str:
        """pins.md without the line that carries the minute it was rendered in."""
        return "\n".join(t for t in md.splitlines() if not t.startswith("갱신:"))

    def test_pins_md_written_after_publication_comes_from_the_file(self):
        """The pins.md refresh that follows a publication renders the pins of pins.jsonl, not the kept ones."""
        files = self.poison()
        ps.APP.refresh_pins_md()
        self.assertEqual(self.unstamped(files.pins_md.read_text(encoding="utf-8")), self.honest_md())
        self.assertIn("first", files.pins_md.read_text(encoding="utf-8"))

    def test_pins_md_rendered_at_startup_comes_from_the_file(self):
        """The pins.md a starting run renders is of the pins of pins.jsonl, not the kept ones."""
        files = self.poison()
        ps.APP.assembly.pins.startup.render_markdown()
        self.assertEqual(self.unstamped(files.pins_md.read_text(encoding="utf-8")), self.honest_md())
        self.assertIn("first", files.pins_md.read_text(encoding="utf-8"))

    def test_a_transaction_reads_the_file(self):
        """A reply to the second pin rewrites pins.jsonl from the file's own records: the first pin's line keeps its
        bytes although a wrong value is kept for it."""
        files = self.poison()
        first_line = files.pins_jsonl.read_text(encoding="utf-8").splitlines()[0]
        reply(2)
        after = files.pins_jsonl.read_text(encoding="utf-8").splitlines()
        self.assertEqual(after[0], first_line)
        self.assertEqual(dump_jsonl([json.loads(after[0])]).strip(), first_line)

    def test_an_assignees_name_written_to_the_thread_comes_from_the_file(self):
        """Assigning a pin writes the assignee's display name into the pin's thread. That name is looked up among
        the people on the transaction's own pins: a name that exists only in a kept value - here a wrong author
        planted for the first pin's line - is not written to pins.jsonl or pins.md."""
        self.add(4, 5, note="first")
        self.add(8, 9, note="second")
        files = PinFiles(ps.APP.C.state)
        texts = [t for t in files.pins_jsonl.read_text(encoding="utf-8").splitlines() if t.strip()]
        planted = dict(json.loads(texts[0]), author={"login": "bob@example.com", "name": "ONLY IN MEMORY"})
        ps.APP.RT.pin_lines.live.values(texts, lambda text: (parse_pin(planted), True))
        self.assertIn("bob@example.com", ps.APP.known_people(None))
        edited = edit_pin(2, {"assignee": "bob@example.com", "base_rev": 0}, dict(LOCAL_ACTOR))
        self.assertEqual(edited.record["assignee"], "bob@example.com")
        self.assertNotIn("ONLY IN MEMORY", files.pins_jsonl.read_text(encoding="utf-8"))
        self.assertNotIn("ONLY IN MEMORY", files.pins_md.read_text(encoding="utf-8"))
        self.assertIn("bob@example.com", edited.record["thread"][-1]["text"])


MARK = "⟦only in memory⟧"


def marked(value):
    """A stored record with MARK appended to every piece of free text and every display name in it: notes, thread
    texts, quotes, close replies and the names of the people on it. Paths, ids and logins stay as they are, so the
    record still names the same pin."""
    if isinstance(value, dict):
        return {
            key: (
                item + MARK
                if key in ("note", "text", "quote", "close_reply", "name") and isinstance(item, str)
                else marked(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [marked(item) for item in value]
    return value


class NoWriteCarriesWhatIsKept(AccessBase):
    """Every write over HTTP, made while each kept value differs from its line in every free text and name: what
    reaches the three pin files is the files' own text and the request's, never a kept value."""

    def setUp(self):
        """Alice is the owner (purge and clear are the owner's); four pins by her, the first with a reply and the
        fourth in the Trash."""
        super().setUp()
        self.set_people([{"login": A_LOGIN, "name": "Alice Kim", "role": "owner"}])
        self.ids = [self.pin_id(ALICE, lo=4 + i, hi=5 + i) for i in range(4)]
        self.post("/api/pins/%d/reply" % self.ids[0], {"text": "a first reply"})
        self.post("/api/pins/%d/drop" % self.ids[3])

    def tearDown(self):
        """Forget the kept values this test marked on purpose before the base audits what readers changed."""
        forget_kept_lines()
        super().tearDown()

    def post(self, path, body=None):
        """POST as Alice (the owner); the answer must be a 200. Returns its body."""
        code, answer = self.call("POST", path, {} if body is None else body, ALICE)
        self.assertEqual(code, 200, (path, answer))
        return answer

    def mark_what_is_kept(self):
        """Keep, for every line of the live file and of the Trash, the line's value with MARK in its texts and
        names - what a reader that changed shared pins would have left behind."""
        files, lines = PinFiles(ps.APP.C.state), ps.APP.RT.pin_lines
        for path, kept, parse in (
            (files.pins_jsonl, lines.live, parse_pin),
            (files.dropped, lines.dropped, TrashedPin.from_record),
        ):
            texts = [t for t in path.read_text(encoding="utf-8").splitlines() if t.strip()] if path.exists() else []
            kept.values(texts, lambda text, parse=parse: (parse(marked(json.loads(text))), True))
        self.assertIn(MARK, json.dumps(ps.APP.pin_listing.list_payload(True), ensure_ascii=False))

    def rev(self, pid):
        """The stored rev of pin pid, read from the file."""
        return next(pin.core.rev or 0 for pin in ps.APP.pin_store().read_pins()[0] if pin.core.id == pid)

    def test_no_write_puts_a_kept_value_in_a_pin_file(self):
        """Reply, edit, assign, claim, unclaim, close, reopen, drop, restore, purge, a new pin and clear, each made
        after the kept values were marked: no pin file holds MARK afterwards."""
        one, two, three, _four = self.ids
        steps = [
            ("reply", lambda: self.post("/api/pins/%d/reply" % one, {"text": "ok @alice"})),
            (
                "edit the note",
                lambda: self.post("/api/pins/%d/edit" % one, {"note": "a new note", "base_rev": self.rev(one)}),
            ),
            ("assign", lambda: self.post("/api/pins/%d/edit" % one, {"assignee": A_LOGIN, "base_rev": self.rev(one)})),
            ("claim", lambda: self.post("/api/pins/%d/claim" % two, {"eta_min": 5})),
            ("unclaim", lambda: self.post("/api/pins/%d/unclaim" % two)),
            ("close", lambda: self.post("/api/pins/%d/close" % two, {"reply": "closed"})),
            ("reopen", lambda: self.post("/api/pins/%d/reopen" % two)),
            ("drop", lambda: self.post("/api/pins/%d/drop" % three)),
            ("restore", lambda: self.post("/api/pins/%d/restore" % three)),
            ("drop again", lambda: self.post("/api/pins/%d/drop" % three)),
            ("purge", lambda: self.post("/api/pins/%d/purge" % three)),
            ("a new pin", lambda: self.pin_id(ALICE, lo=10, hi=11)),
            ("clear", lambda: self.post("/api/clear", CLEAR_BODY)),
        ]
        files = PinFiles(ps.APP.C.state)
        for name, step in steps:
            with self.subTest(write=name):
                self.mark_what_is_kept()
                step()
                for path in (files.pins_jsonl, files.pins_md, files.dropped):
                    if path.exists():
                        self.assertNotIn(MARK, path.read_text(encoding="utf-8"), path.name)

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
import tempfile
import threading
import unittest
from pathlib import Path

from hypothesis import given, settings, strategies as st

from limn.pins.model import TrashedPin, parse_pin
from limn.pins.record import Broken
from limn.pins.store import KeptLines, KeptPinReader, PinFiles, PinLines, PinReader, PinStore, line_value

from helpers import records

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
        together each round, so the order is forced, not waited for."""
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

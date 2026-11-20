"""Who measures a document's manuscript mtime, and when a document summary may answer without measuring.

A light poll asks every LaTeX document of the run for its manuscript mtime, and measuring one walks its build root: a
listing per folder and a stat per file, each of which gives the interpreter up to whichever thread is computing. So the
walk is taken off the request: a watch measures the documents a summary asked about, and a summary answers what the
watch keeps (limn.builds.artifacts.shown_src_mtime, watch_src_mtime; docs/handbook/build-sync.md §원고 변화 감지).

Work is counted, never timed (docs/handbook/verification.md §불안정한 테스트): the file-system builtins one call made.
The order of two threads is fixed by a lock the test holds or by an event raised inside the walk, never by sleeping.

Run: uv run pytest -q src/limn/builds/tests/test_source_watch.py
"""

import contextlib
import io
import os
import shutil
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from limn.builds import artifacts
from limn.builds.service import BuildRequests
from limn.platform.diagnostics import BoundedDiagnostics
from limn.runtime.documents import ApartPaths, Doc, MemoClock, RunPaths
from limn.runtime.resources import RuntimeResources

from helpers import fs_calls


class Contended:
    """A lock for a document's mcache_measuring that calls on_wait the first time a caller has to wait for it, before
    that caller blocks - so a test can act at the moment another thread is known to be waiting, without sleeping."""

    def __init__(self, on_wait) -> None:
        """An unlocked lock; on_wait is called, on the waiting thread, each time acquire finds it held."""
        self._lock = threading.Lock()
        self._on_wait = on_wait

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        """threading.Lock.acquire, announcing a wait before it begins."""
        if self._lock.acquire(blocking=False):
            return True
        if not blocking:
            return False
        self._on_wait()
        return self._lock.acquire(True, timeout)

    def release(self) -> None:
        """Let the lock go."""
        self._lock.release()

    def locked(self) -> bool:
        """Is it held?"""
        return self._lock.locked()

    def __enter__(self) -> bool:
        """Take the lock for a with block."""
        return self.acquire()

    def __exit__(self, *exc: object) -> None:
        """Let it go at the end of the block."""
        self.release()


class HeldClock:
    """A document's pair of clocks (limn.runtime.documents.MemoClock) that a test can hold: each one runs as the real
    clock does until the test sets a value for it, and then reads that value."""

    def __init__(self) -> None:
        """Both clocks run."""
        self.wall_at: float | None = None
        self.steady_at: float | None = None

    def wall(self) -> float:
        """The wall clock: the held value, else time.time()."""
        return time.time() if self.wall_at is None else self.wall_at

    def steady(self) -> float:
        """The clock that never goes back: the held value, else time.monotonic()."""
        return time.monotonic() if self.steady_at is None else self.steady_at


class Hooked(Doc):
    """A LaTeX document that runs `hook` at the point where a measurement of its manuscript has noted the memo's
    generation and is about to walk the tree (it asks whether the document is built from source there) - so a test
    can make something happen in the middle of a measurement, or make the measurement fail, without replacing any
    function of the product."""

    hook = None

    @property
    def builds_from_source(self) -> bool:
        """True, after the hook, when one is set, has run."""
        if self.hook is not None:
            self.hook()
        return True


class Manuscript(unittest.TestCase):
    """A LaTeX document over a small manuscript (main.tex, sec/a.tex) whose files are all `old` seconds old."""

    def setUp(self):
        """Temporary manuscript and state folders; every manuscript file carries the mtime self.old."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.top = Path(tmp.name).resolve()
        self.src = self.top / "ms"
        (self.src / "sec").mkdir(parents=True)
        (self.src / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
        (self.src / "sec" / "a.tex").write_text("text\n", encoding="utf-8")
        self.state = self.top / "state"
        self.state.mkdir()
        self.old = float(int(time.time()) - 100)
        for path in (self.src / "main.tex", self.src / "sec" / "a.tex"):
            os.utime(path, (self.old, self.old))
        self.paths = RunPaths(self.src, self.src / "main.tex", self.state)
        self.clock = HeldClock()
        self.doc = self.clocked(Hooked("ms", "Body", "tex", self.src, self.src / "main.tex", paths=self.paths))

    def clocked(self, doc):
        """doc, reading its memo against this fixture's clock."""
        doc.mcache_clock = self.clock
        return doc

    @contextlib.contextmanager
    def at(self, seconds: float):
        """Hold the clock asked-at and watched-at are read from at `seconds` for a block."""
        before, self.clock.steady_at = self.clock.steady_at, seconds
        try:
            yield
        finally:
            self.clock.steady_at = before

    @contextlib.contextmanager
    def frozen(self):
        """Hold the wall clock for a block - the clock the 2 second memo is dated with - so that a read which must
        hit the memo hits it however long the test takes to get there."""
        before, self.clock.wall_at = self.clock.wall_at, time.time()
        try:
            yield
        finally:
            self.clock.wall_at = before

    def edit(self) -> float:
        """Give main.tex an mtime 50 seconds after self.old, as an edit would, and return it."""
        newer = self.old + 50
        os.utime(self.src / "main.tex", (newer, newer))
        return newer

    def in_thread(self, call):
        """Start call() on a thread under the file-system counter; returns (thread, box) where box receives
        (counts, result) when the call is over."""
        box: list = []
        thread = threading.Thread(target=lambda: box.append(fs_calls(call)))
        thread.start()
        self.addCleanup(thread.join, 10)
        return thread, box


class OneMeasurementAtATime(Manuscript):
    """src_mtime measures a document under that document's measurement lock, so two measurements of one document
    never overlap: a measurement that began earlier cannot store its answer over a later one's."""

    def test_a_miss_behind_a_running_measurement_takes_its_value_without_walking(self):
        """A read that misses the memo while another measurement runs waits for it and answers what it stored."""
        waiting = threading.Event()
        self.doc.mcache_measuring = Contended(waiting.set)
        self.doc.mcache_measuring.acquire()  # "another measurement is running"
        with self.frozen():
            thread, box = self.in_thread(lambda: artifacts.src_mtime(self.doc, self.state))
            self.assertTrue(waiting.wait(10))
            self.doc.mcache[0], self.doc.mcache[1], self.doc.mcache[2] = (str(self.src), None), 123.0, time.time()
            self.doc.mcache_measuring.release()
            thread.join(10)
        counts, answer = box[0]
        self.assertEqual((answer, counts["scandir"], counts["entry_stat"]), (123.0, 0, 0))

    def test_a_forced_measurement_waits_and_then_measures_itself(self):
        """force=True never answers another measurement's value: after its wait it walks the tree."""
        waiting = threading.Event()
        self.doc.mcache_measuring = Contended(waiting.set)
        self.doc.mcache_measuring.acquire()
        thread, box = self.in_thread(lambda: artifacts.src_mtime(self.doc, self.state, force=True))
        self.assertTrue(waiting.wait(10))
        self.doc.mcache[0], self.doc.mcache[1], self.doc.mcache[2] = (str(self.src), None), 123.0, time.time()
        self.doc.mcache_measuring.release()
        thread.join(10)
        counts, answer = box[0]
        self.assertEqual(answer, self.old)
        self.assertGreaterEqual(counts["scandir"], 1)

    def test_a_measurement_that_started_first_cannot_overwrite_a_later_one(self):
        """A measurement walked the tree before an edit and is still on its way to storing; a forced measurement
        starts after the edit. What the memo holds in the end is the later measurement's value."""
        real = artifacts.iter_sources
        walked, release, first = threading.Event(), threading.Event(), []

        def held(*args, **kwargs):
            """The real walk; the first one then waits, its files already looked at, until the test lets it go."""
            yield from real(*args, **kwargs)
            if not first:
                first.append(1)
                walked.set()
                release.wait(10)

        self.doc.mcache_measuring = Contended(release.set)  # a second measurer that has to wait lets the first go on
        with mock.patch.object(artifacts, "iter_sources", held):
            early = threading.Thread(target=lambda: artifacts.src_mtime(self.doc, self.state))
            early.start()
            self.assertTrue(walked.wait(10))
            newer = self.edit()
            late = threading.Thread(target=lambda: artifacts.src_mtime(self.doc, self.state, force=True))
            late.start()
            late.join(10)
            release.set()
            early.join(10)
        self.assertFalse(early.is_alive() or late.is_alive())
        self.assertEqual(self.doc.mcache[1], newer)

    def test_a_hit_takes_no_measurement_lock(self):
        """A read inside the 2 seconds answers while a measurement of that document is running."""

        def fail() -> None:
            """A memo hit must not wait for the measurement lock."""
            raise AssertionError("a memo hit waited for the measurement lock")

        with self.frozen():
            first = artifacts.src_mtime(self.doc, self.state)
            self.doc.mcache_measuring = Contended(fail)
            self.doc.mcache_measuring.acquire()
            self.assertEqual(artifacts.src_mtime(self.doc, self.state), first)


NEVER = float("-inf")
B1, B2 = "pages-20260101000000", "pages-20260101000001"


def walk_calls(call) -> int:
    """How many folder listings and entry stats call() made on this thread: what a walk of the manuscript costs."""
    counts, _ = fs_calls(call)
    return counts["scandir"] + counts["listdir"] + counts["entry_stat"]


def forget_memo_age(doc: Doc) -> None:
    """Make doc's 2 second memo too old to answer, without touching a clock: only what the watch keeps is left."""
    doc.mcache[2] = 0.0


class Watched(Manuscript):
    """The fixture with the two halves of the watch at hand: a summary's read and the watch's turn."""

    def read(self, doc: Doc | None = None) -> float:
        """The manuscript mtime as a document summary asks for it."""
        return artifacts.shown_src_mtime(doc or self.doc, self.state)

    def turn(self, doc: Doc | None = None) -> bool:
        """The manuscript watch's turn for one document; True when it measured."""
        return artifacts.watch_src_mtime(doc or self.doc, self.state)

    def watched_at(self, seconds: float, doc: Doc | None = None) -> None:
        """A summary asks at `seconds` and the watch then measures, so the watch keeps the document from then on."""
        with self.at(seconds):
            self.read(doc)
            self.assertTrue(self.turn(doc))
        forget_memo_age(doc or self.doc)

    def apart_doc(self) -> Doc:
        """A LaTeX document over the same manuscript that sets a figure folder apart (figs/a.pdf, 30 seconds newer
        than every manuscript file), with build B1 on screen, which read no figure."""
        (self.src / "figs").mkdir()
        (self.src / "figs" / "a.pdf").write_bytes(b"%PDF-1.4\n")
        self.figure_time = self.old + 30
        os.utime(self.src / "figs" / "a.pdf", (self.figure_time, self.figure_time))
        doc = Hooked(
            "ap",
            "Apart",
            "tex",
            self.src,
            self.src / "main.tex",
            paths=self.paths,
            apart=ApartPaths(folders=(("figs",),)),
        )
        (doc.dir / B1).mkdir(parents=True)
        (doc.dir / "pages.cur").write_text(B1, encoding="utf-8")
        return self.clocked(doc)

    def swap_to_a_build_that_read_the_figure(self, doc: Doc) -> None:
        """Put build B2 on screen, whose recorder file lists figs/a.pdf, as a build that swaps the page pointer does."""
        (doc.dir / B2).mkdir()
        (doc.dir / B2 / "main.fls").write_text("INPUT ./figs/a.pdf\n", encoding="utf-8")
        (doc.dir / "pages.cur").write_text(B2, encoding="utf-8")
        artifacts.expire_src_mtime(doc)


class SummaryReadsTheWatch(Watched):
    """shown_src_mtime: a summary answers what the watch keeps while the watch is keeping it, and measures as before
    otherwise."""

    def test_a_summary_read_after_a_watch_turn_walks_nothing_whatever_the_age_of_the_memo(self):
        """Five seconds after the watch measured, with the 2 second memo long expired, a summary asks the file system
        nothing and answers the manuscript's mtime."""
        self.watched_at(100)
        with self.at(105):
            counts, answer = fs_calls(self.read)
        self.assertEqual((answer, sum(counts.values())), (self.old, 0))

    def test_the_calls_of_a_watched_read_do_not_grow_with_the_manuscript(self):
        """What a watched read costs is the same for 2 manuscript files and for 300."""
        self.watched_at(100)
        with self.at(101):
            small = sum(fs_calls(self.read)[0].values())
        for n in range(300):
            (self.src / "sec" / ("p%03d.tex" % n)).write_text("x\n", encoding="utf-8")
        self.watched_at(102)
        with self.at(103):
            large = sum(fs_calls(self.read)[0].values())
        self.assertEqual((small, large), (0, 0))

    def test_past_the_limit_the_summary_measures_itself(self):
        """Ten seconds after the watch finished measuring, its value is no longer answered: the summary walks the tree.
        A moment before that it does not."""
        self.watched_at(100)
        with self.at(109.9):
            self.assertEqual(walk_calls(self.read), 0)
        with self.at(110):
            self.assertGreaterEqual(walk_calls(self.read), 1)

    def test_a_request_measurement_is_trusted_for_two_seconds_only(self):
        """A value a request measured, with no watch behind it, answers inside the 2 seconds and not after."""
        with self.at(100), self.frozen():
            self.read()
            self.assertEqual(walk_calls(self.read), 0)
            forget_memo_age(self.doc)
            self.assertGreaterEqual(walk_calls(self.read), 1)

    def test_a_request_measurement_expires_two_seconds_on_the_wall_clock(self):
        """The 2 second memo is dated with the wall clock: 1.9 s later a read still hits it, 2 s later it walks,
        whatever the other clock reads."""
        wall = time.time()
        self.clock.wall_at = wall
        with self.at(100):
            self.read()
            self.clock.wall_at = wall + 1.9
            self.assertEqual(walk_calls(self.read), 0)
        with self.at(100000):
            self.assertEqual(walk_calls(self.read), 0)
            self.clock.wall_at = wall + 2.0
            self.assertGreaterEqual(walk_calls(self.read), 1)

    def test_a_wall_clock_set_back_does_not_keep_the_watch_s_value_trusted(self):
        """Eleven seconds after the watch measured, with the wall clock set back an hour meanwhile, a summary no
        longer answers the watch's value: the limit is counted on the clock that never goes back."""
        self.watched_at(100)
        self.clock.wall_at = time.time() - 3600
        with self.at(111):
            self.assertGreaterEqual(walk_calls(self.read), 1)

    def test_a_document_s_own_clocks_are_the_wall_clock_and_one_that_never_goes_back(self):
        """A document made by the product dates its memo with time.time and keeps asked-at and watched-at on
        time.monotonic - two clocks that read nowhere near each other."""
        clock = MemoClock()
        self.assertIsInstance(
            Doc("x", "X", "tex", self.src, self.src / "main.tex", paths=self.paths).mcache_clock, MemoClock
        )
        self.assertLess(abs(clock.wall() - time.time()), 5)
        self.assertLess(abs(clock.steady() - time.monotonic()), 5)
        self.assertGreater(abs(clock.steady() - clock.wall()), 5)

    def test_a_page_swap_forgets_what_the_watch_measured(self):
        """After a build swapped the page pointer, the value the watch measured before it is not answered."""
        self.watched_at(100)
        artifacts.expire_src_mtime(self.doc)
        with self.at(100.5):
            self.assertGreaterEqual(walk_calls(self.read), 1)

    def test_the_swap_of_a_document_that_sets_files_apart_is_answered_against_the_new_build(self):
        """The watch measured while a build that read no figure was on screen; a build that read one takes the
        screen. The next summary answers the figure's mtime, not what the watch kept."""
        doc = self.apart_doc()
        self.watched_at(100, doc)
        with self.at(100.2):
            self.assertEqual(self.read(doc), self.old)
        self.swap_to_a_build_that_read_the_figure(doc)
        with self.at(100.4):
            self.assertEqual(self.read(doc), self.figure_time)

    def test_a_forced_measurement_ignores_what_the_watch_keeps(self):
        """A build's baseline is measured on the spot while the watch's value is still trusted - and a summary then
        answers that newer measurement, the latest the memo was given."""
        self.watched_at(100)
        newer = self.edit()
        with self.at(101):
            self.assertEqual(artifacts.src_mtime(self.doc, self.state, force=True), newer)
            forget_memo_age(self.doc)
            self.assertEqual(self.read(), newer)

    def test_a_pick_does_not_use_the_ten_second_limit(self):
        """source_newer of a named build - a pick's staleness - keeps the 2 second rule: five seconds after the watch
        measured, it walks the tree."""
        (self.doc.dir / B1).mkdir(parents=True)
        (self.doc.dir / "pages.cur").write_text(B1, encoding="utf-8")
        (self.doc.dir / "built_src_mtime.txt").write_text("%f" % self.old, encoding="utf-8")
        self.watched_at(100)
        with self.at(105):
            self.assertGreaterEqual(walk_calls(lambda: artifacts.source_newer(self.doc, self.state, B1)), 1)

    def test_a_named_measurement_in_the_memo_is_not_answered_as_the_build_on_screen(self):
        """A pick measured a document that sets files apart against a build by name, which takes the memo's one cell.
        A summary does not answer that value as the build on screen's: it measures."""
        doc = self.apart_doc()
        self.watched_at(100, doc)
        self.swap_to_a_build_that_read_the_figure(doc)
        self.watched_at(101, doc)
        with self.at(102):
            self.assertEqual(artifacts.src_mtime(doc, self.state, force=True, build=B1), self.old)
            forget_memo_age(doc)
            self.assertEqual(self.read(doc), self.figure_time)

    def test_a_document_not_built_from_source_is_neither_watched_nor_marked_asked(self):
        """A view-only PDF's mtime is one stat of its file, as before; no summary marks it asked and the watch has
        no turn for it."""
        (self.src / "review.pdf").write_bytes(b"%PDF-1.4\n")
        pdf = self.clocked(Doc("rv", "Review", "pdf", self.src, self.src / "review.pdf", paths=self.paths))
        with self.at(100):
            counts, answer = fs_calls(lambda: self.read(pdf))
            self.assertEqual(
                (answer, counts["stat"], walk_calls(lambda: self.turn(pdf))), (pdf.main.stat().st_mtime, 1, 0)
            )
            self.assertFalse(self.turn(pdf))
        self.assertEqual((pdf.mcache_asked, pdf.mcache_watched), (NEVER, NEVER))

    def test_a_document_whose_tree_is_gone_is_measured_as_nothing_and_the_watch_goes_on(self):
        """A build root that vanished measures as 0.0 for a summary and for the watch alike; neither raises."""
        shutil.rmtree(self.src)
        with self.at(100):
            self.assertEqual(self.read(), 0.0)
            self.assertTrue(self.turn())
        forget_memo_age(self.doc)
        with self.at(101):
            self.assertEqual(self.read(), 0.0)


class WatchTurn(Watched):
    """watch_src_mtime: which documents the watch measures, when it lets one go, and what it leaves in the memo."""

    def test_a_document_nobody_asked_about_is_not_measured_however_small_the_clock(self):
        """Right after boot the clock reads less than the 15 seconds; a document no summary asked about is still not
        measured, and the watch asks the file system nothing for it."""
        with self.at(0.5):
            counts, measured = fs_calls(self.turn)
        self.assertEqual((measured, sum(counts.values())), (False, 0))

    def test_a_document_is_let_go_fifteen_seconds_after_it_was_last_asked_about(self):
        """The watch measures a document until 15 seconds have passed since a summary asked; then it asks the file
        system nothing for it and drops what it kept."""
        with self.at(100):
            self.read()
        with self.at(114.9):
            self.assertTrue(self.turn())
        self.assertEqual(self.doc.mcache_watched, 114.9)
        with self.at(115):
            counts, measured = fs_calls(self.turn)
        self.assertEqual((measured, sum(counts.values()), self.doc.mcache_watched), (False, 0, NEVER))

    def test_two_reads_after_the_watch_let_go_do_not_answer_what_it_last_measured(self):
        """The watch let a document go, the manuscript was edited, and two summaries ask one after the other. Neither
        answers the value the watch measured before the edit; the second takes the first one's measurement."""
        with self.at(100):
            self.read()
        with self.at(114):
            self.assertTrue(self.turn())
        with self.at(115.5):
            self.assertFalse(self.turn())
        newer = self.edit()
        forget_memo_age(self.doc)
        with self.at(120), self.frozen():
            self.assertEqual(self.read(), newer)
            counts, second = fs_calls(self.read)
        self.assertEqual((second, counts["scandir"]), (newer, 0))

    def test_a_watch_measurement_that_spans_a_page_swap_is_dropped_and_leaves_no_stamp(self):
        """A build swapped the page pointer while the watch was measuring: the watch's value is not stored and the
        document is not marked as kept by the watch."""
        with self.at(100):
            self.read()
        forget_memo_age(self.doc)
        self.doc.hook = lambda: artifacts.expire_src_mtime(self.doc)  # a page swap lands inside the measurement
        with self.at(101):
            self.assertTrue(self.turn())
        self.assertEqual((self.doc.mcache_watched, self.doc.mcache[2]), (NEVER, 0.0))

    def test_the_watch_skips_a_document_someone_else_is_measuring(self):
        """The watch does not wait for a measurement under way: it asks the file system nothing and goes on."""

        def fail() -> None:
            """The watch must not wait for the measurement lock."""
            raise AssertionError("the watch waited for the measurement lock")

        with self.at(100):
            self.read()
        self.doc.mcache_measuring = Contended(fail)
        self.doc.mcache_measuring.acquire()
        with self.at(101):
            counts, measured = fs_calls(self.turn)
        self.assertEqual((measured, sum(counts.values())), (False, 0))

    def test_the_watch_measures_against_the_build_on_screen(self):
        """What the watch stores is the measurement a summary would make: for a document that sets files apart, the
        figure the build on screen read counts."""
        doc = self.apart_doc()
        self.swap_to_a_build_that_read_the_figure(doc)
        self.watched_at(100, doc)
        with self.at(101):
            counts, answer = fs_calls(lambda: self.read(doc))
        self.assertEqual((answer, sum(counts.values())), (self.figure_time, 0))


class Rounds:
    """A stop event that lets a watch loop run `rounds` rounds: each wait up to that count says "go on", the next one
    "stop", and is_set is true only from then on. Every timeout the loop asked to wait for is kept."""

    def __init__(self, rounds: int) -> None:
        """No wait has been asked for yet."""
        self.left = rounds
        self.timeouts: list[float] = []
        self.stopped = False

    def wait(self, timeout: float | None = None) -> bool:
        """Note the timeout; False while a round is left to run."""
        self.timeouts.append(-1.0 if timeout is None else timeout)
        if self.left == 0:
            self.stopped = True
            return True
        self.left -= 1
        return False

    def is_set(self) -> bool:
        """Has the loop been told to stop?"""
        return self.stopped


class WatchLoop(Watched):
    """BuildRequests.watch_sources: the loop that gives every document of the run its turn, round after round."""

    def requests(self, docs: list[Doc]) -> BuildRequests:
        """The build service of a run that serves docs with this fixture's state folder, reporting the watch's
        failures to a record of its own (the process-wide one remembers the causes other tests reported)."""
        requests = BuildRequests(
            lambda: SimpleNamespace(state=self.state), lambda: {}, lambda: docs, lambda: "T", lambda result: ""
        )
        requests.diagnostics = BoundedDiagnostics()
        return requests

    def second_doc(self) -> Doc:
        """Another LaTeX document, over a manuscript of its own."""
        src = self.top / "other"
        src.mkdir()
        (src / "other.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
        return self.clocked(Hooked("ot", "Other", "tex", src, src / "other.tex", paths=self.paths))

    def test_one_round_measures_the_documents_asked_about_and_no_other(self):
        """Of a LaTeX document a summary asked about, one nobody asked about and a view-only PDF, a round measures
        the first alone."""
        (self.src / "review.pdf").write_bytes(b"%PDF-1.4\n")
        pdf = self.clocked(Doc("rv", "Review", "pdf", self.src, self.src / "review.pdf", paths=self.paths))
        unasked = self.second_doc()
        with self.at(100):
            self.read()
            self.read(pdf)
        with self.at(101):
            self.requests([unasked, pdf, self.doc]).watch_sources(Rounds(1))
        self.assertEqual((self.doc.mcache_watched, unasked.mcache_watched, pdf.mcache_watched), (101, NEVER, NEVER))

    def test_a_document_that_raises_does_not_stop_the_round(self):
        """A measurement that raises is reported on standard error and the documents after it are still measured."""
        other = self.second_doc()

        def failing() -> None:
            """The first document's measurement cannot be made."""
            raise RuntimeError("cannot measure")

        errors = io.StringIO()
        with self.at(100):
            self.read()
            self.read(other)
        other.hook = failing
        requests = self.requests([other, self.doc])
        with self.at(101), redirect_stderr(errors):
            requests.watch_sources_round(threading.Event())
            requests.watch_sources_round(threading.Event())
        self.assertEqual(self.doc.mcache_watched, 101)
        self.assertEqual(errors.getvalue().count("RuntimeError: cannot measure"), 1)
        self.assertIn("document ot", errors.getvalue())

    def test_a_round_that_cannot_list_the_documents_does_not_end_the_watch(self):
        """The run's document list failing once costs that round, not the watch: the next round measures."""
        calls = []

        def docs():
            """The document list, which cannot be read the first time."""
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("no documents yet")
            return [self.doc]

        requests = BuildRequests(
            lambda: SimpleNamespace(state=self.state), lambda: {}, docs, lambda: "T", lambda result: ""
        )
        requests.diagnostics = BoundedDiagnostics()
        errors = io.StringIO()
        with self.at(100):
            self.read()
        with self.at(101), redirect_stderr(errors):
            requests.watch_sources(Rounds(2))
        self.assertEqual(self.doc.mcache_watched, 101)
        self.assertIn("RuntimeError: no documents yet", errors.getvalue())

    def test_the_round_ends_between_documents_when_the_run_stops(self):
        """Once the run is stopping, the documents not yet reached in the round are left unmeasured."""
        other = self.second_doc()
        stop = threading.Event()
        with self.at(100):
            self.read()
            self.read(other)
        self.doc.hook = stop.set  # the run is told to stop while the first document is measured
        with self.at(101):
            self.requests([self.doc, other]).watch_sources_round(stop)
        self.assertEqual((self.doc.mcache_watched, other.mcache_watched), (101, NEVER))

    def test_rounds_start_a_second_apart_and_back_to_back_when_one_takes_longer(self):
        """The loop waits out what is left of the second since a round began: 0.8 s after a round of 0.2 s, nothing
        after a round of 1.5 s. Its first round comes a full interval after the start."""
        stop = Rounds(2)
        ticks = iter([50.0, 50.2, 60.0, 61.5])
        self.requests([]).watch_sources(stop, every=1.0, clock=lambda: next(ticks))
        self.assertEqual([round(t, 6) for t in stop.timeouts], [1.0, 0.8, 0.0])

    def test_two_runs_share_no_watch_state(self):
        """Two documents over one manuscript, as two runs in one process have them: a round of one run measures its
        own document and leaves the other's asked-at, watched-at and measurement lock alone."""
        twin = self.clocked(Doc("ms", "Body", "tex", self.src, self.src / "main.tex", paths=self.paths))
        with self.at(100):
            self.read()
            self.read(twin)
        with self.at(101):
            self.requests([self.doc]).watch_sources_round(threading.Event())
        self.assertEqual((self.doc.mcache_watched, twin.mcache_watched), (101, NEVER))
        self.assertIsNot(self.doc.mcache_measuring, twin.mcache_measuring)
        with self.at(102):
            self.requests([twin]).watch_sources_round(threading.Event())
        self.assertEqual((self.doc.mcache_watched, twin.mcache_watched), (101, 102))

    def test_a_round_changes_nothing_on_disk(self):
        """The watch only reads: after a round that measured a plain document and one that sets files apart (whose
        recorder file it reads), every file and folder of the manuscript and of the state folder has the bytes,
        the inode and the mtime it had."""
        apart = self.apart_doc()
        self.swap_to_a_build_that_read_the_figure(apart)

        def snapshot() -> dict[str, tuple[int, int, bytes]]:
            """(inode, mtime in ns, content) of every file and folder below the fixture's top folder."""
            seen = {}
            for path in sorted(self.top.rglob("*")):
                st = path.lstat()
                seen[str(path)] = (st.st_ino, st.st_mtime_ns, path.read_bytes() if path.is_file() else b"")
            return seen

        with self.at(100):
            self.read()
            self.read(apart)
        before = snapshot()
        with self.at(101):
            self.requests([self.doc, apart]).watch_sources_round(threading.Event())
        self.assertEqual((self.doc.mcache_watched, apart.mcache_watched), (101, 101))
        self.assertEqual(snapshot(), before)

    def test_stop_returns_while_the_watch_is_inside_a_measurement(self):
        """A measurement that does not come back does not hold the run's shutdown: stop() gives up its wait, and the
        watch ends by itself once the measurement returns."""
        inside, release = threading.Event(), threading.Event()

        def stuck() -> None:
            """A measurement that does not go on until the test lets it."""
            inside.set()
            release.wait(10)

        runtime = RuntimeResources(*([None] * 9))
        with self.at(100):
            self.read()
            self.doc.hook = stuck
            runtime.start_thread(self.requests([self.doc]).watch_sources, runtime.stopping, 0.0)
            self.assertTrue(inside.wait(10))
            runtime.stop(timeout=0.05)
            self.assertTrue(runtime.threads[0].is_alive())
            release.set()
            runtime.threads[0].join(10)
        self.assertFalse(runtime.threads[0].is_alive())

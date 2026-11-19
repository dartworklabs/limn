"""Who measures a document's manuscript mtime, and when a document summary may answer without measuring.

A light poll asks every LaTeX document of the run for its manuscript mtime, and measuring one walks its build root: a
listing per folder and a stat per file, each of which gives the interpreter up to whichever thread is computing. So the
walk is taken off the request: a watch measures the documents a summary asked about, and a summary answers what the
watch keeps (limn.builds.artifacts.shown_src_mtime, watch_src_mtime; docs/handbook/build-sync.md §원고 변화 감지).

Work is counted, never timed (docs/handbook/verification.md §불안정한 테스트): the file-system builtins one call made.
The order of two threads is fixed by a lock the test holds or by an event raised inside the walk, never by sleeping.

Run: uv run pytest -q src/limn/builds/tests/test_source_watch.py
"""

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from limn.builds import artifacts
from limn.runtime.documents import Doc, RunPaths

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
        self.doc = Doc("ms", "Body", "tex", self.src, self.src / "main.tex", paths=self.paths)

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

        first = artifacts.src_mtime(self.doc, self.state)
        self.doc.mcache_measuring = Contended(fail)
        self.doc.mcache_measuring.acquire()
        self.assertEqual(artifacts.src_mtime(self.doc, self.state), first)

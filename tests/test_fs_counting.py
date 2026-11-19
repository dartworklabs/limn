"""The helpers that count file-system work for tests (tests/support/helpers.py: fs_calls, opened).

Tests of the light poll assert exact counts of opened files and file-system calls, so the counters must see the
measured call and nothing else: a leftover thread of an earlier test in the same worker, or a profiler some tool
installed, must not change what a test reads.

Run: uv run pytest -q tests/test_fs_counting.py
"""

import cProfile
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from helpers import fs_calls, opened


class Opened(unittest.TestCase):
    """opened(call, under): the files a call opened below one folder."""

    def setUp(self):
        """Two temporary folders: the one a test measures and one it has nothing to do with."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        self.mine, self.other = root / "mine", root / "other"
        for folder in (self.mine, self.other):
            folder.mkdir()
            (folder / "pages.cur").write_text("x", encoding="utf-8")

    def test_the_paths_opened_below_the_folder_are_returned_in_order(self):
        """Every open of the measured call is seen, with the call's result."""
        paths, result = opened(lambda: (self.mine / "pages.cur").read_text(), self.mine)
        self.assertEqual((paths, result), ([str(self.mine / "pages.cur")], "x"))

    def test_a_file_of_the_same_name_opened_elsewhere_by_another_thread_is_not_counted(self):
        """A thread an earlier test left running opens its own files while the measured call runs."""

        def measured():
            """Open nothing below the folder while another thread opens a file of the same name elsewhere."""
            stray = threading.Thread(target=lambda: (self.other / "pages.cur").read_text())
            stray.start()
            stray.join()

        paths, _ = opened(measured, self.mine)
        self.assertEqual(paths, [])

    def test_nothing_is_recorded_outside_a_call(self):
        """The audit hook stays installed for the process and is silent between recordings."""
        (self.mine / "pages.cur").read_text()
        paths, _ = opened(lambda: None, self.mine)
        self.assertEqual(paths, [])


class FsCalls(unittest.TestCase):
    """fs_calls(call): the file-system builtins one call made on this thread."""

    def test_stat_and_open_are_counted(self):
        """A read through pathlib is counted where it reaches the builtins."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "a.txt"
            target.write_text("x", encoding="utf-8")
            counts, result = fs_calls(lambda: (target.stat().st_size, target.read_text()))
        self.assertEqual(result, (1, "x"))
        self.assertEqual((counts["stat"], counts["open"]), (1, 1))

    def test_a_profiler_installed_before_the_call_is_put_back(self):
        """Counting must not switch off a profiler a tool installed (coverage, a debugger)."""

        def earlier(_frame, _event, _arg):
            """A profiler that does nothing."""

        before = sys.getprofile()
        sys.setprofile(earlier)
        try:
            fs_calls(lambda: None)
            self.assertIs(sys.getprofile(), earlier)
        finally:
            sys.setprofile(before)

    def test_under_a_profiler_that_could_not_be_put_back_the_count_is_refused(self):
        """Before Python 3.12 a running cProfile is installed from C and shows in sys.getprofile() as its Profile
        object, which sys.setprofile cannot install again: counting would switch the session off for the rest of
        the run. The count is refused with a skip that says so, and the profiler is left as it was. From 3.12 on
        cProfile does not use the profile hook and the count runs beside it."""
        profile = cProfile.Profile()
        profile.enable()
        try:
            installed = sys.getprofile()
            if installed is None:
                counts, _ = fs_calls(lambda: os.stat(os.curdir))
                self.assertEqual(counts["stat"], 1)
            else:
                with self.assertRaises(unittest.SkipTest):
                    fs_calls(lambda: os.stat(os.curdir))
                self.assertIs(sys.getprofile(), installed)
        finally:
            profile.disable()

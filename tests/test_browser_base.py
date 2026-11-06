"""Pin that the browser tests' run (helpers_browser.BrowserBase) is on the paths startup would register: under a temporary
folder reached through a link - macOS's /var -> /private/var - the run gets the resolved paths, as limn.server resolves
--manuscript, so the pins the tests write name the files the documents were registered with (#431). Linux runners keep
their temporary folder off any link, so only this test sees the macOS premise there."""

import tempfile
import unittest
from pathlib import Path

from helpers import ps
from helpers_browser import BrowserBase


class BrowserBaseRunPaths(unittest.TestCase):
    """BrowserBase's setUp, run without a browser, under a temporary folder reached through a link."""

    def test_the_run_is_on_resolved_paths_under_a_linked_temporary_folder(self):
        """With the run's temporary folder made under a link to another folder (BrowserBase.TMP_IN), the manuscript
        folder, its main file and the state folder the run serves are resolved paths below the link's target, and the
        test's own main file is the run's. With them on the link, a pin written on that main file owned none of its
        commit's lines, and the changes view offered no [커밋 전체 비교] for its comparison (test_viewer_contrast, on
        macOS)."""
        outer = tempfile.TemporaryDirectory()
        self.addCleanup(outer.cleanup)
        real, link = Path(outer.name, "real").resolve(), Path(outer.name, "link")
        real.mkdir()
        link.symlink_to(real, target_is_directory=True)
        base = BrowserBase()
        base.TMP_IN = str(link)
        base.setUp()
        self.addCleanup(base.tearDown)  # before outer's cleanup: cleanups run last added first
        C = ps.APP.C
        self.assertTrue(C.src.is_relative_to(real), C.src)
        self.assertEqual((C.src, C.main, C.state), (C.src.resolve(), C.main.resolve(), C.state.resolve()))
        self.assertEqual(base.main, C.main)

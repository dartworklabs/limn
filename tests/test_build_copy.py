"""The build's first step copies the manuscript into the build folder; a failed copy must stop the build.

Compiling an incomplete or stale copy would publish a PDF that no longer matches the manuscript while
reporting success, so a copy failure has to end the build before latexmk runs.

Run: uv run pytest -q tests/test_build_copy.py
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_server import Base, ps

# run_logged's result if latexmk ran and produced nothing - keeps a regressed build on the assertion path.
NO_PDF = (1, "", False)

FAILING_RSYNC = """#!/bin/sh
echo "rsync: [sender] send_files failed to open \\"main.tex\\": Permission denied (13)" >&2
echo "rsync error: some files/attrs were not transferred (code 23)" >&2
exit 23
"""


class ManuscriptCopy(Base):
    """What _build() does when copying the manuscript into the build folder goes wrong."""

    def setUp(self):
        """Put an rsync on PATH that fails the way a partial transfer does (exit 23)."""
        super().setUp()
        self.bin = tempfile.TemporaryDirectory()
        rsync = Path(self.bin.name) / "rsync"
        rsync.write_text(FAILING_RSYNC, encoding="utf-8")
        rsync.chmod(0o755)
        path = self.bin.name + os.pathsep + os.environ.get("PATH", "")
        env = mock.patch.dict(os.environ, {"PATH": path})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        """Remove the fake rsync."""
        self.bin.cleanup()
        super().tearDown()

    def test_build_stops_before_latexmk_when_rsync_fails(self):
        """A non-zero rsync exit fails the build with the copy error and never compiles the partial copy."""
        with mock.patch.object(ps, "run_logged", return_value=NO_PDF) as compile_step:
            res = ps._build()
        compile_step.assert_not_called()
        self.assertEqual(res["state"], "fail")
        self.assertFalse(res["ok"])
        self.assertTrue(res["log"].startswith("원고 사본을 만들지 못했습니다"), res["log"])

    def test_copy_error_names_the_rsync_exit_and_its_last_message(self):
        """The build log shows why the copy failed so the owner can fix permissions or disk space."""
        with mock.patch.object(ps, "run_logged", return_value=NO_PDF):
            res = ps._build()
        self.assertIn("23", res["log"])
        self.assertIn("some files/attrs were not transferred", res["log"])


if __name__ == "__main__":
    unittest.main()

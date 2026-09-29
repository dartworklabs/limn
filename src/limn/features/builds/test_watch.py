"""The view-only watch (limn.features.builds.service.BuildRequests.watch_pdf_docs) over real documents.

One round of the watch starts a re-render only for a document it follows (limn.documents.Doc.watches_files) whose
file changed (limn.features.builds.engine.refresh_pdf_doc). The build start is the watch's own injection point
(BuildRequests.build_async); the test records it instead of launching pdftoppm.

Run: uv run pytest -q src/limn/features/builds/test_watch.py
"""

import tempfile
import unittest
from pathlib import Path

from limn.build import BuildStarted
from limn.documents import Doc, RunPaths
from limn.features.builds.service import BuildRequests


class OneRound:
    """A stop event that lets exactly one round of a watch loop run: the first wait says "go on", every later one
    "stop"."""

    def __init__(self) -> None:
        """No round has run yet."""
        self.waits = 0

    def wait(self, timeout: float | None = None) -> bool:
        """False on the first call, True on every later one (threading.Event.wait's answer)."""
        self.waits += 1
        return self.waits > 1


class WatchMembership(unittest.TestCase):
    """Which documents one round of the watch re-renders."""

    def test_one_round_starts_a_render_for_the_changed_watched_pdf_only(self):
        """A never-rendered view-only PDF counts as changed, so the round starts its render; the LaTeX body beside it
        is never started by the watch."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "ms"
            src.mkdir()
            (src / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
            (src / "review.pdf").write_bytes(b"%PDF-1.4\n")
            paths = RunPaths(src, src / "main.tex", Path(tmp) / "state")
            docs = [
                Doc("ms", "본문", "tex", src, src / "main.tex", paths=paths),
                Doc("rv", "리뷰", "pdf", src, src / "review.pdf", paths=paths),
            ]
            requests = BuildRequests(lambda: None, lambda: {}, lambda: docs, lambda: "T", lambda r: "")
            started = []

            def start(doc):
                """Record the document the watch asked to re-render, as a started background build."""
                started.append(doc.key)
                return BuildStarted()

            requests.build_async = start
            requests.watch_pdf_docs(OneRound(), every=0)
            self.assertEqual(started, ["rv"])

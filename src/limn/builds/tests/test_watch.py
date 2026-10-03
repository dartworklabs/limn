"""The view-only watch (limn.builds.service.BuildRequests.watch_pdf_docs) over real documents.

One round of the watch starts a re-render only for a document it follows (limn.runtime.documents.Doc.watches_files) whose
file changed (limn.builds.engine.refresh_pdf_doc). The build start is the watch's own injection point
(BuildRequests.build_async); the test records it instead of launching pdftoppm.

Run: uv run pytest -q src/limn/builds/tests/test_watch.py
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from limn.builds import engine
from limn.builds.artifacts import BuildConfig, BuildOk, BuildStarted
from limn.builds.service import BuildRequests
from limn.runtime.documents import Doc, RunPaths

from helpers import MINI_PDF
from helpers_files import replace_in_same_tick, rewrite_in_place

OTHER_PDF = MINI_PDF.replace(b"Reviewer one", b"Reviewer two")  # the same size, other bytes
# pdfinfo and pdftoppm stand-ins: every PDF has one page, drawn as the 200x100 PPM named by LIMN_TEST_PAGE_PPM.
FAKE_PDFINFO = """#!/bin/sh
echo "Pages:          1"
"""
FAKE_PDFTOPPM = """#!/bin/sh
cat "$LIMN_TEST_PAGE_PPM"
"""


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


class SameTickRewrites(unittest.TestCase):
    """The watch of a view-only PDF compares (mtime_ns, size, inode) of the file with the value recorded when its pages
    were drawn (pdf_sig.txt). A second version that lands in the first one's timestamp tick with the same size is seen
    when it replaced the file atomically (a new inode), and a signature recorded in the old format redraws once."""

    def setUp(self):
        """review.pdf under a manuscript folder as view-only document rv, stand-in poppler tools first on PATH, and a
        build start that draws the pages at once (what the background build does) and records that it was asked."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        src = root / "ms"
        src.mkdir()
        self.pdf = src / "review.pdf"
        self.pdf.write_bytes(MINI_PDF)
        self.doc = Doc("rv", "리뷰", "pdf", src, self.pdf, paths=RunPaths(src, src / "main.tex", root / "state"))
        self.cfg = BuildConfig(state=root / "state", dpi=72, timeout=5)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for name, text in (("pdfinfo", FAKE_PDFINFO), ("pdftoppm", FAKE_PDFTOPPM)):
            (bin_dir / name).write_text(text, encoding="utf-8")
            (bin_dir / name).chmod(0o755)
        page = root / "page.ppm"
        page.write_bytes(b"P6\n200 100\n255\n" + b"\xff" * (200 * 100 * 3))
        env = mock.patch.dict(
            os.environ,
            {"PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""), "LIMN_TEST_PAGE_PPM": str(page)},
        )
        env.start()
        self.addCleanup(env.stop)
        self.started: list[str] = []

    def draw(self, doc: Doc) -> BuildStarted:
        """The watch's build start: note the document, then render its pages now and record their signature."""
        self.started.append(doc.key)
        self.assertIsInstance(engine.render_pdf_doc(doc, self.cfg), BuildOk)
        return BuildStarted()

    def tick(self) -> bool:
        """One watch tick of the document: whether it started a render."""
        return engine.refresh_pdf_doc(self.doc, self.draw)

    def test_a_pdf_replaced_atomically_in_the_same_tick_with_the_same_size_is_drawn_again(self):
        """The pages of review.pdf are drawn and settled; the file is then replaced by a sibling of the same size with
        the old file's mtime_ns (a new inode). The next tick starts one render of it and then settles (issue #165)."""
        self.assertEqual([self.tick(), self.tick()], [True, False])
        replace_in_same_tick(self.pdf, OTHER_PDF)
        self.assertEqual([self.tick(), self.tick()], [True, False])
        self.assertEqual(self.started, ["rv", "rv"])

    def test_a_signature_recorded_in_the_old_format_draws_once_and_then_settles(self):
        """Upgrade: pdf_sig.txt holds "<mtime_ns>:<size>" of the unchanged file. The first tick draws it once and records
        the new format "<mtime_ns>:<size>:<inode>"; the ticks after it find nothing to do."""
        st = self.pdf.stat()
        self.doc.dir.mkdir(parents=True)
        (self.doc.dir / "pdf_sig.txt").write_text("%d:%d" % (st.st_mtime_ns, st.st_size), encoding="utf-8")
        self.assertEqual([self.tick(), self.tick(), self.tick()], [True, False, False])
        self.assertEqual(self.started, ["rv"])
        recorded = (self.doc.dir / "pdf_sig.txt").read_text(encoding="utf-8")
        self.assertEqual(recorded, "%d:%d:%d" % (st.st_mtime_ns, st.st_size, st.st_ino))

    def test_reading_or_changing_the_mode_of_the_pdf_leaves_its_signature(self):
        """Only the file's version moves the signature: a read (atime) and a chmod (ctime) do not."""
        before = engine.pdf_signature(self.doc)
        self.pdf.read_bytes()
        self.pdf.chmod(0o600)
        self.assertEqual(engine.pdf_signature(self.doc), before)

    def test_a_missing_pdf_has_no_signature_and_starts_nothing(self):
        """No file, no signature: pdf_signature is None and the tick has nothing to draw."""
        self.pdf.unlink()
        self.assertIsNone(engine.pdf_signature(self.doc))
        self.assertFalse(self.tick())
        self.assertEqual(self.started, [])

    def test_an_overwrite_in_place_in_the_same_tick_is_the_known_limit(self):
        """A same-size overwrite of the same file (the same inode) within one timestamp tick keeps all three values, so the
        watch does not see it. This is the documented limit of the signature (docs/handbook/build-sync.md §보기 전용
        PDF 문서): closing it means hashing the file inside the racy window, which the handbook leaves undone. If that
        is ever done, this test changes with the handbook."""
        self.assertEqual([self.tick(), self.tick()], [True, False])
        rewrite_in_place(self.pdf, OTHER_PDF)
        self.assertFalse(self.tick())
        self.assertEqual(self.started, ["rv"])

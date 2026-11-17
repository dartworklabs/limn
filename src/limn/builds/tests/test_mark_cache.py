"""limn.builds.artifacts.RangeBoxCache and the per-document asker behind it (limn.builds.queries.BuildQueries.boxes).

GET /api/pins answers every open pin of every document at once, and a slow answer there delays every other GET in the
process: one miss reads that build's source record - up to RECORD_MAX_BYTES of JSON - and runs `synctex view` once per
line of text. So the run keeps the answers it has already computed, keyed by the build, the file, the file's version
and the range, and shares that cache across request threads.

Run: uv run pytest -q src/limn/builds/tests/test_mark_cache.py
"""

import sys
import tempfile
import threading
import unittest
from pathlib import Path

from limn.builds import built_source
from limn.builds.artifacts import MARK_CACHE_MAX, BuildMapCache, RangeBoxCache
from limn.builds.queries import BuildQueries
from limn.runtime.documents import Doc, RunPaths

import helpers_figure
from helpers import TEX
from helpers_figure import BUILD1, b2_map, figure_doc, write_build

PAGE_PX = (1500, 1000)
PIECES = ((1, (0.1, 0.2, 0.3, 0.4)),)


def key(build="pages-1", file="/ms/main.tex", version=(1, 2), lo=4, hi=5):
    """One cache key: the document's state folder, the build, the file, its (mtime_ns, size) and the line range."""
    return ("/state", build, file, version[0], version[1], lo, hi)


class RangeBoxCacheReads(unittest.TestCase):
    """An answer is computed once per key and served again; every part of the key tells two answers apart."""

    def setUp(self):
        """A fresh cache and a counter of how often the computation ran."""
        self.cache = RangeBoxCache()
        self.runs = 0

    def compute(self, pieces=PIECES):
        """A computation that counts its calls and answers pieces."""

        def once():
            """Count this call and answer."""
            self.runs += 1
            return pieces

        return once

    def test_the_same_key_is_computed_once(self):
        """The second ask is the answer the first one computed, and nothing ran again."""
        first = self.cache.answer(key(), self.compute())
        self.assertEqual(first, PIECES)
        self.assertEqual(self.cache.answer(key(), self.compute()), PIECES)
        self.assertEqual(self.runs, 1)

    def test_an_answer_of_no_pieces_is_kept_too(self):
        """A range that prints nowhere costs just as much to find out, so "no mark" is an answer the cache keeps."""
        self.assertEqual(self.cache.answer(key(), self.compute(())), ())
        self.assertEqual(self.cache.answer(key(), self.compute(())), ())
        self.assertEqual(self.runs, 1)

    def test_each_part_of_the_key_tells_two_answers_apart(self):
        """Another build, another file, another version of that file, or another range is a different question."""
        self.cache.answer(key(), self.compute())
        for other in (
            key(build="pages-2"),
            key(file="/ms/intro.tex"),
            key(version=(9, 2)),
            key(version=(1, 9)),
            key(lo=5),
            key(hi=6),
        ):
            with self.subTest(other=other):
                self.cache.answer(other, self.compute())
        self.assertEqual(self.runs, 7)

    def test_the_oldest_entry_goes_first_beyond_the_cap(self):
        """MARK_CACHE_MAX + 1 ranges asked in turn: the first is computed again, the last is still cached."""
        for i in range(MARK_CACHE_MAX + 1):
            self.cache.answer(key(lo=i, hi=i), self.compute())
        self.assertEqual(self.cache.held(), MARK_CACHE_MAX)
        self.cache.answer(key(lo=MARK_CACHE_MAX, hi=MARK_CACHE_MAX), self.compute())
        self.cache.answer(key(lo=0, hi=0), self.compute())
        self.assertEqual(self.runs, MARK_CACHE_MAX + 2)


class RangeBoxCacheThreads(unittest.TestCase):
    """Request threads share the run's one cache, so a key two of them miss at the same moment must leave each of them
    with an equal answer and the cache with one entry - the computation runs outside the lock, as parsing a map does
    (limn.builds.artifacts.BuildMapCache)."""

    THREADS = 8

    def setUp(self):
        """A fresh cache, with the interpreter switching threads every microsecond so an unguarded write shows."""
        self.cache = RangeBoxCache()
        switch = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        self.addCleanup(sys.setswitchinterval, switch)

    def test_threads_that_miss_one_key_get_equal_answers_and_a_consistent_cache(self):
        """Every thread gets the pieces of that range, nothing raises, and the cache holds the one entry.

        More than one thread may run the computation - it runs outside the lock - and that is allowed, because the
        entry is a function of its key: what they are not allowed to do is answer differently or leave the cache
        holding more than the one question they asked."""
        start = threading.Barrier(self.THREADS)
        answers: list[object] = []
        problems: list[str] = []
        runs: list[int] = []

        def compute() -> tuple[tuple[int, tuple[float, float, float, float]], ...]:
            """Count this run and answer the range's pieces."""
            runs.append(1)
            return PIECES

        def ask() -> None:
            """Ask for the one key after the barrier; keep what came back and anything raised."""
            try:
                start.wait(timeout=30)
                answers.append(self.cache.answer(key(), compute))
            except Exception as exc:
                problems.append("%s: %s" % (type(exc).__name__, exc))

        threads = [threading.Thread(target=ask) for _ in range(self.THREADS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertEqual([t.is_alive() for t in threads], [False] * self.THREADS)
        self.assertEqual(problems, [])
        self.assertEqual(answers, [PIECES] * self.THREADS)
        self.assertEqual(self.cache.held(), 1)
        self.assertTrue(1 <= len(runs) <= self.THREADS, len(runs))


class DocumentsWithoutMarks(unittest.TestCase):
    """The asker a document gets: None wherever there is nothing a forward SyncTeX pass could answer, so no listing
    pays for a process per line to find that out."""

    def setUp(self):
        """A temporary manuscript with a LaTeX document and a figure document, each with a build on screen."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        self.src = root / "ms"
        self.src.mkdir()
        self.main = self.src / "main.tex"
        self.main.write_text(TEX, encoding="utf-8")
        (root / "state").mkdir()
        self.paths = RunPaths(self.src, self.main, root / "state")
        self.ms = Doc("ms", "본문", "tex", self.src, self.main, paths=self.paths)
        self.fig = figure_doc(self.src, self.paths)
        maps = BuildMapCache()
        self.queries = BuildQueries(lambda: maps)
        pages = self.ms.dir / BUILD1
        pages.mkdir(parents=True, exist_ok=True)
        (pages / "page-1.png").write_bytes(helpers_figure.png_header(*PAGE_PX))
        (pages / self.ms.pdf_name).write_bytes(b"%PDF-1.4\n%%EOF\n")
        (self.ms.dir / "pages.cur").write_text(BUILD1, encoding="utf-8")
        record = built_source.encode({"main.tex": built_source.text_lines(TEX.encode("utf-8"))})
        (pages / built_source.SOURCE_NAME).write_text(record, encoding="utf-8")

    def test_a_latex_document_with_pages_is_asked(self):
        """The one kind whose pages a LaTeX build printed from the lines a pin points at."""
        self.assertIsNotNone(self.queries.boxes(self.ms, 150))

    def test_a_document_not_built_from_its_source_is_not_asked(self):
        """A figure document's lines are a drawing script's and its marks come from its element map."""
        write_build(self.fig, BUILD1, b2_map())
        self.assertIsNone(self.queries.boxes(self.fig, 150))

    def test_a_document_the_browser_draws_is_not_asked(self):
        """A Markdown or text document has no PDF and no page images at all - its pins take exactly the path they
        took before marks followed the range."""
        notes = self.src / "notes.md"
        notes.write_text("# Plan\n\nFirst line.\n", encoding="utf-8")
        for kind in ("markdown", "text"):
            with self.subTest(kind=kind):
                drawn = Doc("nt", "계획", kind, self.src, notes, paths=self.paths)
                self.assertIsNone(self.queries.boxes(drawn, 150))

    def test_a_document_with_no_page_is_not_asked(self):
        """Without a page there is no size to measure a mark against."""
        (self.ms.dir / BUILD1 / "page-1.png").unlink()
        self.assertIsNone(self.queries.boxes(self.ms, 150))

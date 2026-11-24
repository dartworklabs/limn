"""limn.builds.artifacts.RangeBoxCache and the per-document asker behind it (limn.builds.queries.BuildQueries.boxes).

GET /api/pins answers every open pin of every document at once, and a slow answer there delays every other GET in the
process: one miss reads that build's source record - up to RECORD_MAX_BYTES of JSON - and runs `synctex view` once per
line of text. So the run keeps the answers it has already computed, keyed by the build, the file, the dpi and the
range **in the lines that build read**, and shares that cache across request threads. The lines of the build are what
the key names because they are what the answer is a function of: an edit elsewhere in the file leaves a pin's range on
the same lines of the build, and an agent editing the manuscript is the most ordinary thing that happens here.

Run: uv run pytest -q src/limn/builds/tests/test_mark_cache.py
"""

import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from limn.builds import built_source
from limn.builds.artifacts import MARK_CACHE_MAX, BuildMapCache, RangeBoxCache
from limn.builds.queries import BuildQueries
from limn.pins import range_boxes
from limn.pins.location import source as pick_source
from limn.runtime.documents import Doc, RunPaths

import helpers_figure
from helpers import TEX
from helpers_figure import BUILD1, b2_map, figure_doc, write_build

PAGE_PX = (1500, 1000)
PIECES = ((1, (0.1, 0.2, 0.3, 0.4)),)


def key(build="pages-1", file="/ms/main.tex", dpi=150, lo=4, hi=5):
    """One cache key: the document's state folder, the build, the file, the dpi and the built line range."""
    return ("/state", build, file, dpi, lo, hi)


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
        """Another build, another file, another dpi (the page sizes a piece is a fraction of are read at it), or
        another range of the build's lines is a different question."""
        self.cache.answer(key(), self.compute())
        for other in (
            key(build="pages-2"),
            key(file="/ms/intro.tex"),
            key(dpi=300),
            key(lo=5),
            key(hi=6),
        ):
            with self.subTest(other=other):
                self.cache.answer(other, self.compute())
        self.assertEqual(self.runs, 6)

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


class EditedManuscriptStillHits(unittest.TestCase):
    """The listing that follows an edit of the manuscript: a pin whose range the edit did not move answers from the
    cache, without a process.

    An agent editing the manuscript is what Limn is for, so this is the most ordinary invalidation there is - and the
    read it holds up is GET /api/pins, which answers every open pin at once and takes one of the process's four GET
    compute slots while it runs (docs/handbook/architecture.md §HTTP 읽기 능력). Keyed by the file's version this was
    a miss for every line pin of the file, each miss one `synctex view` process per line of text; keyed by the lines
    of the build the range stands on, only a range the edit really moved misses.

    The two pins are L4-L5 (the first paragraph of the fixture manuscript) and L8-L9 (the body lines below it).
    """

    PINS = ((4, 5), (8, 9))
    BOX = (1, 60.0, 100.0, 300.0, 10.0)  # one line's box on page 1, well under the body-box height

    def setUp(self):
        """A manuscript with one build on screen - a page image to size a mark against, a PDF and the record of the
        lines that build read - and one run's cache behind the asker."""
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
        maps, marks = BuildMapCache(), RangeBoxCache()
        self.cache = marks
        self.queries = BuildQueries(lambda: maps, lambda: marks, range_boxes)
        pages = self.ms.dir / BUILD1
        pages.mkdir(parents=True, exist_ok=True)
        (pages / "page-1.png").write_bytes(helpers_figure.png_header(*PAGE_PX))
        (pages / self.ms.pdf_name).write_bytes(b"%PDF-1.4\n%%EOF\n")
        (self.ms.dir / "pages.cur").write_text(BUILD1, encoding="utf-8")
        record = built_source.encode({"main.tex": built_source.text_lines(TEX.encode("utf-8"))})
        (pages / built_source.SOURCE_NAME).write_text(record, encoding="utf-8")
        self.calls = []

    def viewed(self):
        """A stub of the forward pass that records every line it is asked about and answers that line a box."""

        def view(_pdf, _tex, line):
            """Record the line and answer its box."""
            self.calls.append(line)
            return [self.BOX]

        return mock.patch.object(pick_source, "synctex_view", view)

    def listing(self, pins):
        """One GET /api/pins' worth of marks: the document's asker, made once for the read as the listing makes it,
        asked for each pin's range in turn."""
        asker = self.queries.boxes(self.ms, 150)
        self.assertIsNotNone(asker)
        return [asker(str(self.main), lo, hi, lambda _lines: True) for lo, hi in pins]

    def test_an_edit_outside_both_ranges_runs_no_second_process(self):
        """A line below both pins reworded: the pins' numbers do not move, the lines of the build they stand on do
        not change, and the second listing answers both marks without asking SyncTeX again."""
        with self.viewed():
            first = self.listing(self.PINS)
            asked = list(self.calls)
            reworded = TEX.replace("Tail paragraph zetaunique.", "Tail paragraph, reworded.")
            self.main.write_text(reworded, encoding="utf-8")
            second = self.listing(self.PINS)
        self.assertTrue(all(first), first)
        self.assertEqual(second, first)
        self.assertEqual(sorted(asked), [4, 5, 8, 9])
        self.assertEqual(self.calls, asked)
        self.assertEqual(self.cache.held(), 2)

    def test_lines_added_above_the_pins_are_the_same_question_at_their_new_numbers(self):
        """Two lines added at the top of the file. The pins are re-synced to L6-L7 and L10-L11, and asked at those
        numbers the listing answers the same marks from the same two entries: the key is the range in the lines the
        build read, which is where both ranges still stand."""
        with self.viewed():
            first = self.listing(self.PINS)
            asked = list(self.calls)
            self.main.write_text("% added\n% added\n" + TEX, encoding="utf-8")
            moved = self.listing(((lo + 2, hi + 2) for lo, hi in self.PINS))
        self.assertEqual(moved, first)
        self.assertEqual(self.calls, asked)
        self.assertEqual(self.cache.held(), 2)


class CallersCheckOnTheLinesMeasured(EditedManuscriptStillHits):
    """The caller's check (limn.pins.needs.LinesHold) runs on the file's lines as the answer read them, before anything
    is measured: the listing checks there that a stored pin's anchor still stands on its lines, and the check and the
    mark must see one version of the file - an edit between two reads could pass one paragraph's anchor and measure
    another's lines."""

    def test_the_check_sees_the_lines_the_answer_measures(self):
        """The check is handed main.tex as it is now, the text the range is then measured on - also after an edit."""
        seen = []
        with self.viewed():
            asker = self.queries.boxes(self.ms, 150)
            self.assertTrue(asker(str(self.main), 4, 5, lambda lines: seen.append(list(lines)) or True))
            edited = "% added\n" + TEX
            self.main.write_text(edited, encoding="utf-8")
            again = self.queries.boxes(self.ms, 150)
            self.assertTrue(again(str(self.main), 5, 6, lambda lines: seen.append(list(lines)) or True))
        self.assertEqual(seen, [TEX.splitlines(), edited.splitlines()])

    def test_a_check_that_says_no_measures_nothing(self):
        """No answer, no SyncTeX process and nothing kept when the check says no; a later range of the same file that
        passes is still measured from the one read."""
        with self.viewed():
            asker = self.queries.boxes(self.ms, 150)
            self.assertEqual(asker(str(self.main), 4, 5, lambda _lines: False), ())
            self.assertEqual((self.calls, self.cache.held()), ([], 0))
            self.assertTrue(asker(str(self.main), 8, 9, lambda _lines: True))
        self.assertEqual(sorted(self.calls), [8, 9])

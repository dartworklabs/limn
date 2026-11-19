"""What one light poll reads: GET /api/meta?light=1 through limn.documents.reads and the build queries behind it.

A viewer polls every few seconds, and every file-system call a poll makes gives the interpreter up to whichever
thread is computing. So a poll reads each fact of a document once - the page pointer, the stamps - builds the
selected document's summary once, asks of the other documents only what their briefs hold, and reads what a published
page folder holds once per run (limn.builds.artifacts.PageFolderCache). The answers are the ones every poll gave
before: the keys and their order are the agent contract.

These tests count file-system calls and opened files instead of timing them
(docs/handbook/verification.md §불안정한 테스트).

Run: uv run pytest -q src/limn/documents/tests/test_light_poll_reads.py
"""

import json
import os
import shutil
import tempfile
import time
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from hypothesis import given, settings, strategies as st

from limn.builds import artifacts
from limn.builds.artifacts import BuildMapCache, PageFolderCache
from limn.builds.queries import BuildQueries
from limn.documents import reads
from limn.documents.reads import MetaSettings
from limn.runtime.documents import Doc, RunPaths, apart_paths
from limn.security.access import LOCAL_ACTOR

from helpers import Base, fresh_runtime, fs_calls, opened, ps
from helpers_figure import b2_map, figure_doc, png_header, write_build

B1, B2, B3 = "pages-20260101000000", "pages-20260101000001", "pages-20260101000002"
BRIEF_KEYS = [
    "key",
    "name",
    "kind",
    "view_only",
    "path",
    "main",
    "stale_build",
    "src_mtime",
    "building",
    "build",
    "build_seq",
    "last_state",
    "pages_build",
    "n_pages",
]


def publish(doc: Doc, name: str, pages: int, broken: int | None = None) -> Path:
    """Publish build `name` of doc as a render does - `pages` page images of 300 x 150 pixels and the PDF copy, made
    whole under a hidden name and renamed into place - and put it on screen. Image number `broken` (1-based) is cut
    short of a PNG header. Returns the page folder."""
    doc.dir.mkdir(parents=True, exist_ok=True)
    part = doc.dir / ("." + name + ".part")
    part.mkdir()
    for number in range(1, pages + 1):
        data = png_header(300, 150)
        (part / ("page-%d.png" % number)).write_bytes(data[:10] if number == broken else data)
    (part / doc.pdf_name).write_bytes(b"%PDF-1.4\n%%EOF\n")
    os.rename(part, doc.dir / name)
    (doc.dir / "pages.cur").write_text(name, encoding="utf-8")
    return doc.dir / name


def history(doc: Doc, name: str, src_mtime: float) -> None:
    """Record build `name` in doc's build history as compiled from a manuscript of that src_mtime."""
    entry = {"build": name, "seq": 1, "src_mtime": src_mtime, "src_hash": None}
    (doc.dir / "builds.json").write_text(json.dumps({"seq": 1, "last": None, "builds": [entry]}), encoding="utf-8")


def names_opened(call, under: Path) -> Counter:
    """How often each file name below folder `under` was opened while call() ran."""
    return Counter(Path(path).name for path in opened(call, under)[0])


class Fixture(unittest.TestCase):
    """A manuscript with a body (main.tex), a second LaTeX document (rr/rr.tex), a view-only PDF and a figure
    document, with one page memory behind the build queries."""

    def setUp(self):
        """Temporary manuscript and state folders; the documents have no build yet."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.root = Path(self.tmp.name).resolve()
        self.src = root / "ms"
        (self.src / "rr").mkdir(parents=True)
        (self.src / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
        (self.src / "rr" / "rr.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
        (self.src / "review.pdf").write_bytes(b"%PDF-1.4\n")
        self.state = root / "state"
        self.state.mkdir()
        self.paths = RunPaths(self.src, self.src / "main.tex", self.state)
        self.ms = Doc("ms", "Body", "tex", self.src, self.src / "main.tex", paths=self.paths)
        self.rr = Doc("rr", "Reply", "tex", self.src / "rr", self.src / "rr" / "rr.tex", paths=self.paths)
        self.rv = Doc("rv", "Review", "pdf", self.src, self.src / "review.pdf", paths=self.paths)
        self.settings = MetaSettings(
            state=self.state, pins_md=self.state / "pins.md", label="Paper", accent="#1d4ed8", repo=None, dpi=150
        )
        self.cache = PageFolderCache()
        self.maps = BuildMapCache()
        self.q = BuildQueries(lambda: self.maps, pages=lambda: self.cache).documents()

    def brief(self, doc: Doc) -> dict:
        """A document's brief as GET /api/docs and the other documents of GET /api/meta ask for it."""
        return reads.doc_brief(doc, self.state, self.q)

    def meta(self, doc: Doc, docs, builds=None) -> dict:
        """reads.meta of doc among docs, as the light poll asks it."""
        return reads.meta(doc, {}, self.settings, docs, {}, time.time(), builds or self.q)

    def names_opened(self, call) -> Counter:
        """How often each file name of this fixture's folders was opened while call() ran."""
        return names_opened(call, self.root)

    def frozen(self):
        """Stop time.time for the block - the clock the 2 second src_mtime memo is measured with - so that a second
        read is a memo hit however long the test takes to make it. The patch is the process's clock, for this
        thread's block only."""
        return mock.patch.object(artifacts.time, "time", return_value=time.time())


class BriefOnly(Fixture):
    """reads.doc_brief: a document's /api/docs entry, reading only what that entry holds."""

    def states(self):
        """Documents in the states a brief is asked in, by name."""
        publish(self.ms, B1, 3)
        history(self.ms, B1, time.time() + 60)
        publish(self.rr, B1, 2)
        (self.rr.dir / "built_src_mtime.txt").write_text("1.000000", encoding="utf-8")
        publish(self.rv, B1, 1)
        unbuilt = Doc("nb", "New", "tex", self.src / "rr", self.src / "rr" / "rr.tex", paths=self.paths)
        legacy = Doc("lg", "Old", "tex", self.src / "rr", self.src / "rr" / "rr.tex", paths=self.paths)
        (legacy.dir / "pages").mkdir(parents=True)
        (legacy.dir / "pages" / "page-1.png").write_bytes(png_header(300, 150))
        gone = Doc("gn", "Gone", "tex", self.src / "rr", self.src / "rr" / "rr.tex", paths=self.paths)
        shutil.rmtree(publish(gone, B1, 2))
        return {
            "fresh": self.ms,
            "stale": self.rr,
            "view-only": self.rv,
            "unbuilt": unbuilt,
            "legacy": legacy,
            "gone": gone,
        }

    def test_brief_equals_the_summarys_brief(self):
        """For every state a document can be in, the brief read alone is the brief of a summary whose meta is read
        too, key for key in the contract's order."""
        for label, doc in self.states().items():
            with self.subTest(state=label):
                brief = self.brief(doc)
                full = self.q.summary(doc, self.state, 150)
                self.assertEqual(full.meta["pages_build"], brief["pages_build"])
                self.assertEqual(brief, full.brief)
                self.assertEqual(list(brief), BRIEF_KEYS)

    def test_the_states_differ_where_they_should(self):
        """The fixture's states really are different answers: staleness, page folder and page count."""
        got = {label: self.brief(doc) for label, doc in self.states().items()}
        self.assertEqual(
            {label: (b["stale_build"], b["pages_build"], b["n_pages"]) for label, b in got.items()},
            {
                "fresh": (False, B1, 3),
                "stale": (True, B1, 2),
                "view-only": (False, B1, 1),
                "unbuilt": (False, "pages", 0),
                "legacy": (False, "pages", 1),
                "gone": (False, "pages", 0),
            },
        )

    def test_brief_stale_matches_between_the_swap_and_the_history(self):
        """A page swap moves the pointer before the build history names the new build: until then the baseline is
        built_src_mtime.txt, for the brief as for the summary."""
        publish(self.ms, B1, 3)
        history(self.ms, B1, time.time() + 60)
        publish(self.ms, B2, 3)
        (self.ms.dir / "built_src_mtime.txt").write_text("1.000000", encoding="utf-8")
        brief = self.brief(self.ms)
        self.assertIs(brief["stale_build"], True)
        full = self.q.summary(self.ms, self.state, 150)
        self.assertEqual((full.meta["stale_build"], full.meta["build_src_mtime"]), (True, 1.0))

    def test_brief_reads_no_stamp_and_with_a_history_entry_no_baseline_file(self):
        """A brief holds neither built_at nor head, and the history already gives its staleness baseline."""
        publish(self.ms, B1, 3)
        history(self.ms, B1, time.time() + 60)
        for name in ("built_at.txt", "head.txt", "built_src_mtime.txt"):
            (self.ms.dir / name).write_text("1.000000", encoding="utf-8")
        names = self.names_opened(lambda: self.brief(self.ms))
        self.assertEqual((names["built_at.txt"], names["head.txt"], names["built_src_mtime.txt"]), (0, 0, 0))
        self.assertEqual(names["pages.cur"], 1 + 1)  # the read, and the check before the folder is kept

    def test_without_history_or_baseline_file_the_pdf_dates_the_build_and_the_pointer_is_read_once(self):
        """The last baseline is the timestamp of the PDF beside the pages on screen, found without asking the page
        pointer which folder that is."""
        folder = publish(self.ms, B1, 2)
        os.utime(folder / self.ms.pdf_name, (1.0, 1.0))
        self.assertIs(self.brief(self.ms)["stale_build"], True)
        names = self.names_opened(lambda: self.brief(self.ms))
        self.assertEqual((names["pages.cur"], names["builds.json"], names["built_src_mtime.txt"]), (1, 1, 1))

    def test_a_document_never_built_has_its_pointer_looked_for_once(self):
        """Before a first build there is no pointer, no history and no PDF: the brief looks for the pointer once."""
        self.assertEqual(self.brief(self.rr)["pages_build"], "pages")
        self.assertEqual(self.names_opened(lambda: self.brief(self.rr))["pages.cur"], 1)

    def test_the_page_count_is_of_names_and_the_pages_are_the_ones_sized(self):
        """n_pages counts the page images a build has; pages lists the ones whose size could be read."""
        publish(self.ms, B1, 3, broken=2)
        self.assertEqual(self.brief(self.ms)["n_pages"], 3)
        built = self.q.summary(self.ms, self.state, 150)
        self.assertEqual(
            (built.brief["n_pages"], [page["name"] for page in built.meta["pages"]]), (3, ["page-1.png", "page-3.png"])
        )

    def test_a_document_not_built_from_source_is_never_stale(self):
        """A view-only PDF whose file is newer than its pages is re-rendered by the watch, not reported stale."""
        publish(self.rv, B1, 1)
        (self.rv.dir / "built_src_mtime.txt").write_text("1.000000", encoding="utf-8")
        self.assertGreater(artifacts.shown_source_newer(self.rv, self.state, self.rv.dir / B1), 2)
        self.assertIs(self.brief(self.rv)["stale_build"], False)
        self.assertIs(self.q.summary(self.rv, self.state, 150).meta["stale_build"], False)

    def test_a_second_brief_opens_no_page_image(self):
        """A document that is not the selected one is read whole once, and only listed in memory after that."""
        publish(self.rr, B1, 3)
        self.assertEqual(self.brief(self.rr)["n_pages"], 3)
        with self.frozen():
            self.brief(self.rr)
            counts, brief = fs_calls(lambda: self.brief(self.rr))
        self.assertEqual(brief["n_pages"], 3)
        self.assertEqual(counts["scandir"] + counts["listdir"] + counts["entry_stat"], 0)
        self.assertEqual(self.names_opened(lambda: self.brief(self.rr))["page-1.png"], 0)


class SummaryOnce(Fixture):
    """BuildQueries.summary and reads.meta: each fact of a document is read once per poll."""

    def test_a_summary_reads_each_fact_once(self):
        """A warm summary opens the pointer and each stamp once, and no page image."""
        publish(self.ms, B1, 3)
        history(self.ms, B1, time.time() + 60)
        for name in ("built_at.txt", "head.txt", "built_src_mtime.txt"):
            (self.ms.dir / name).write_text("1.000000", encoding="utf-8")
        with self.frozen():
            first = self.q.summary(self.ms, self.state, 150)
            self.assertEqual(len(first.meta["pages"]), 3)
            names = self.names_opened(lambda: self.q.summary(self.ms, self.state, 150).meta)
            again = self.q.summary(self.ms, self.state, 150)
            self.assertEqual((again.brief, again.meta), (first.brief, first.meta))
        self.assertEqual(
            {name: names[name] for name in ("pages.cur", "built_at.txt", "head.txt", "built_src_mtime.txt")},
            {"pages.cur": 1, "built_at.txt": 1, "head.txt": 1, "built_src_mtime.txt": 1},
        )
        self.assertEqual(sum(count for name, count in names.items() if name.endswith(".png")), 0)
        self.assertEqual(first.meta["built_at"], "1.000000")
        self.assertEqual(len(first.meta["pages"]), 3)

    def test_the_meta_of_one_summary_is_read_once(self):
        """Asking one answer for its meta again gives the same dict and reads nothing more."""
        publish(self.ms, B1, 2)
        (self.ms.dir / "head.txt").write_text("abc1234", encoding="utf-8")
        built = self.q.summary(self.ms, self.state, 150)
        first = built.meta
        (self.ms.dir / "head.txt").write_text("def5678", encoding="utf-8")
        paths, again = opened(lambda: built.meta, self.root)
        self.assertIs(again, first)
        self.assertEqual((again["head"], paths), ("abc1234", []))

    def test_meta_reads_each_documents_pointer_once(self):
        """A warm poll of three documents opens each one's page pointer once and lists no folder."""
        docs = [self.ms, self.rr, self.rv]
        for doc in docs:
            publish(doc, B1, 3)
        with self.frozen():
            first = self.meta(self.ms, docs)
            paths, again = opened(lambda: self.meta(self.ms, docs), self.root)
            counts, _ = fs_calls(lambda: self.meta(self.ms, docs))
        self.assertEqual(again, first)
        pointers = Counter(path for path in paths if path.endswith("pages.cur"))
        self.assertEqual(sorted(pointers.values()), [1, 1, 1])
        self.assertEqual([path for path in paths if path.endswith(".png")], [])
        self.assertEqual(counts["scandir"] + counts["listdir"] + counts["entry_stat"], 0)

    def test_the_second_meta_costs_the_same_for_three_pages_as_for_thirty(self):
        """What a warm poll costs does not grow with the pages on screen."""
        totals = []
        for pages in (3, 30):
            doc = Doc("p%d" % pages, "Body", "tex", self.src, self.src / "main.tex", paths=self.paths)
            publish(doc, B1, pages)
            docs = [doc, self.rv]
            with self.frozen():
                self.meta(doc, docs)
                counts, body = fs_calls(lambda doc=doc, docs=docs: self.meta(doc, docs))
            self.assertEqual(len(body["pages"]), pages)
            totals.append(sum(counts.values()))
        self.assertEqual(totals[0], totals[1])

    def test_metas_docs_carry_the_selected_documents_brief_from_the_same_read(self):
        """One body names one build of the selected document: a page swap that lands between its summary and the
        briefs of the others does not put two builds of it into one answer."""
        publish(self.ms, B1, 3)
        publish(self.rr, B1, 1)

        def summary_then_swap(doc, state, dpi):
            """The real summary, after which a build of the body finishes and swaps its pages."""
            got = self.q.summary(doc, state, dpi)
            publish(self.ms, B2, 2)
            return got

        calls = iter([summary_then_swap])
        swapping = SimpleNamespace(
            summary=lambda doc, state, dpi: next(calls, self.q.summary)(doc, state, dpi), outline=self.q.outline
        )
        body = self.meta(self.ms, [self.ms, self.rr], swapping)
        self.assertEqual((body["pages_build"], len(body["pages"])), (B1, 3))
        self.assertEqual((body["docs"][0]["pages_build"], body["docs"][0]["n_pages"]), (B1, 3))
        self.assertEqual(body["docs"][1]["key"], "rr")
        self.assertEqual(body["src_sig"].split(",")[0].split("=")[0], "ms")

    def test_meta_of_one_document_has_no_docs(self):
        """A single-document instance answers no docs list, as before."""
        publish(self.ms, B1, 1)
        body = self.meta(self.ms, [self.ms])
        self.assertNotIn("docs", body)
        self.assertEqual((body["multi"], body["pages_build"]), (False, B1))

    def test_a_document_that_sets_files_apart_scans_its_tree_once_per_poll(self):
        """The src_mtime memo is asked under one key per document. A second key - the build's name next to "the
        build on screen" - would evict the first on every summary and walk the manuscript tree each time."""
        fig = figure_doc(self.src, self.paths)
        apart = apart_paths(self.src, self.src / "main.tex", [("figure", fig.src, fig.main)])
        self.assertFalse(apart.empty)
        body = Doc("ms", "Body", "tex", self.src, self.src / "main.tex", paths=self.paths, apart=apart)
        publish(body, B1, 2)
        publish(self.rr, B1, 1)  # a document without a build lists its missing legacy folder at every read
        with self.frozen():
            self.meta(body, [body, self.rr])
            counts, _ = fs_calls(lambda: self.meta(body, [body, self.rr]))
        self.assertEqual(counts["scandir"] + counts["entry_stat"], 0)

    def test_a_figure_documents_page_facts_do_not_reach_what_is_kept(self):
        """page_facts writes each page's figure into the rows it is given: the next answer, and one at another dpi,
        start from the folder's own rows."""
        fig = figure_doc(self.src, self.paths)
        write_build(fig, B1, b2_map())
        first = self.q.summary(fig, self.state, 150).meta["pages"]
        self.assertIn("figure", first[0])
        self.assertEqual(self.q.summary(fig, self.state, 150).meta["pages"], first)
        half = self.q.summary(fig, self.state, 300).meta["pages"]
        self.assertEqual(half[0]["pt_w"], first[0]["pt_w"] / 2)
        self.assertEqual(self.cache.pages(fig, fig.dir / B1).rows(150)[0].keys(), {"name", "pt_w", "pt_h"})

    def test_a_new_build_is_answered_at_the_next_read(self):
        """A rebuild's pages are on the next poll: the pointer is read every time."""
        publish(self.ms, B1, 3)
        self.assertEqual(self.meta(self.ms, [self.ms])["pages_build"], B1)
        publish(self.ms, B2, 2)
        body = self.meta(self.ms, [self.ms])
        self.assertEqual((body["pages_build"], len(body["pages"])), (B2, 2))
        self.assertEqual(self.brief(self.ms)["n_pages"], 2)

    def test_a_folder_on_screen_that_is_gone_answers_the_legacy_name(self):
        """A page folder removed under the pointer is answered as it always was - the legacy name and no pages -
        although its pages were kept."""
        folder = publish(self.ms, B1, 3)
        self.meta(self.ms, [self.ms])
        self.assertEqual(self.cache.held(), 3)
        shutil.rmtree(folder)
        body = self.meta(self.ms, [self.ms])
        self.assertEqual((body["pages_build"], body["pages"]), ("pages", []))
        self.assertEqual(self.brief(self.ms)["n_pages"], 0)

    def test_the_stamps_are_read_at_every_poll(self):
        """built_at, head and the staleness baseline are not kept: a rewritten stamp is the next answer."""
        publish(self.ms, B1, 1)
        (self.ms.dir / "head.txt").write_text("abc1234", encoding="utf-8")
        self.assertEqual(self.meta(self.ms, [self.ms])["head"], "abc1234")
        (self.ms.dir / "head.txt").write_text("def5678", encoding="utf-8")
        (self.ms.dir / "built_at.txt").write_text("2027-01-01T00:00:00+09:00", encoding="utf-8")
        (self.ms.dir / "built_src_mtime.txt").write_text("2.500000", encoding="utf-8")
        body = self.meta(self.ms, [self.ms])
        self.assertEqual(
            (body["head"], body["built_at"], body["build_src_mtime"]), ("def5678", "2027-01-01T00:00:00+09:00", 2.5)
        )


class WatchedPoll(Fixture):
    """A poll of documents the manuscript watch keeps walks no manuscript (limn.builds.artifacts.shown_src_mtime,
    watch_src_mtime): its file-system calls do not follow the size of the manuscripts, and its body is the one a poll
    that measured them itself gives."""

    def setUp(self):
        """Both LaTeX documents and the PDF have a build on screen; the polls ask about all three."""
        super().setUp()
        publish(self.ms, B1, 2)
        history(self.ms, B1, time.time() + 60)
        publish(self.rr, B1, 1)
        history(self.rr, B1, time.time() + 60)
        publish(self.rv, B1, 1)
        self.docs = [self.ms, self.rr, self.rv]

    def at(self, seconds: float):
        """Stop the clock a document's asked-at and watched-at are read from at `seconds` for a block."""
        return mock.patch.object(artifacts, "watch_clock", return_value=seconds)

    def poll(self) -> dict:
        """One light poll of the body among the three documents."""
        return self.meta(self.ms, self.docs)

    def forget_memo_ages(self) -> None:
        """Make every document's 2 second memo too old to answer: only what the watch keeps is left."""
        for doc in self.docs:
            doc.mcache[2] = 0.0

    def watch(self, seconds: float) -> None:
        """A poll at `seconds`, then the watch's turn for every document, then the 2 second memos forgotten."""
        with self.at(seconds):
            self.poll()
            for doc in self.docs:
                artifacts.watch_src_mtime(doc, self.state)
        self.forget_memo_ages()

    def test_a_poll_of_watched_documents_walks_no_manuscript(self):
        """Four seconds after the watch measured the two LaTeX documents, a poll lists no folder and stats no entry."""
        self.watch(100)
        with self.at(104):
            counts, _ = fs_calls(self.poll)
        self.assertEqual(counts["scandir"] + counts["listdir"] + counts["entry_stat"], 0)

    def test_the_calls_of_a_watched_poll_equal_those_of_a_memo_hit_and_ignore_the_manuscript_size(self):
        """A watched poll makes as many file-system calls with 300 more manuscript files as without them: those of a
        poll that hits the 2 second memo, and the one stat of the view-only PDF, whose file the watch does not
        measure."""
        self.watch(100)
        with self.at(104):
            small = sum(fs_calls(self.poll)[0].values())
        for n in range(300):
            (self.src / ("part%03d.tex" % n)).write_text("x\n", encoding="utf-8")
        self.watch(200)
        with self.at(204):
            large = sum(fs_calls(self.poll)[0].values())
        with self.at(900), self.frozen():  # the watch's values are long past the limit: the first poll measures
            self.poll()
            hit = sum(fs_calls(self.poll)[0].values())
        self.assertEqual((small, large), (hit + 1, hit + 1))

    def test_the_first_poll_after_the_watch_let_go_walks_as_a_poll_without_a_watch_does(self):
        """Sixteen seconds after the last poll the watch lets the documents go; the poll that comes back measures
        the manuscripts itself, with the calls of a poll no watch ever served."""
        self.watch(100)
        with self.at(116):
            for doc in self.docs:
                self.assertFalse(artifacts.watch_src_mtime(doc, self.state))
        with self.at(120):
            back, _ = fs_calls(self.poll)
        self.forget_memo_ages()
        with self.at(500):
            unwatched, _ = fs_calls(self.poll)
        self.assertGreaterEqual(back["scandir"], 2)
        self.assertEqual(back, unwatched)

    def test_a_watched_poll_answers_what_an_unwatched_one_does(self):
        """The body of a poll that read the watch's values is the body of a poll that measured the manuscripts."""
        self.watch(100)
        with self.at(104):
            counts, watched = fs_calls(self.poll)
        self.assertEqual(counts["scandir"], 0)
        self.forget_memo_ages()
        with self.at(500):
            measured = self.poll()
        for body in (watched, measured):
            del body["src_age_s"]
        self.assertEqual(watched, measured)


class DisplayPath(Fixture):
    """Doc.rel_path: the path a brief, the pins.md header and a view-only pick show for a document is the one
    resolved when the document was made, at startup."""

    def test_the_display_path_asks_the_file_system_nothing(self):
        """The path is known from startup: no link is resolved to answer it."""
        counts, path = fs_calls(self.rr.rel_path)
        self.assertEqual(path, "rr/rr.tex")
        self.assertEqual(sum(counts.values()), 0)

    def test_the_display_path_is_the_one_resolved_at_startup(self):
        """A folder turned into a link to another place after startup does not change which path the document
        shows: the revision services name its files the same way (Doc.registered_main)."""
        (self.src / "rr").rename(self.src / "elsewhere")
        (self.src / "rr").symlink_to(self.src / "elsewhere")
        self.assertEqual(self.rr.rel_path(), "rr/rr.tex")
        self.assertEqual(self.brief(self.rr)["path"], "rr/rr.tex")

    def test_a_main_file_outside_the_manuscript_is_answered_as_given(self):
        """A document whose main file is not under --manuscript shows that file's own path."""
        outside = Path(self.tmp.name).resolve() / "other" / "note.tex"
        outside.parent.mkdir()
        outside.write_text("x\n", encoding="utf-8")
        doc = Doc("ot", "Other", "tex", outside.parent, outside, paths=self.paths)
        self.assertEqual(doc.rel_path(), str(outside))

    def test_a_document_registered_through_a_link_answers_the_resolved_path(self):
        """A manuscript reached through a link at startup shows the path below the real folder, as it always has."""
        root = Path(self.tmp.name).resolve()
        (root / "link").symlink_to(self.src)
        linked = root / "link"
        paths = RunPaths(linked, linked / "main.tex", self.state)
        doc = Doc("rr", "Reply", "tex", linked / "rr", linked / "rr" / "rr.tex", paths=paths)
        self.assertEqual(doc.rel_path(), "rr/rr.tex")
        legacy = Doc("main", "Body", legacy=True, paths=paths)
        self.assertEqual(legacy.rel_path(), "main.tex")

    def test_a_warm_meta_makes_no_lstat(self):
        """A poll resolves no link: with the pages kept and the manuscript's mtime remembered, it calls lstat for
        no document."""
        docs = [self.ms, self.rr, self.rv]
        for doc in docs:
            publish(doc, B1, 2)
        with self.frozen():
            self.meta(self.ms, docs)
            counts, body = fs_calls(lambda: self.meta(self.ms, docs))
        self.assertEqual([entry["path"] for entry in body["docs"]], ["main.tex", "rr/rr.tex", "review.pdf"])
        self.assertEqual(counts["lstat"] + counts["readlink"], 0)


class ThroughTheRun(Base):
    """The run's composition (limn.server): its build queries read the page memory the run owns."""

    def poll(self) -> dict:
        """One light poll of the default document, as GET /api/meta?light=1 computes it."""
        return ps.APP.document_views.meta(ps.APP.docs[0], dict(LOCAL_ACTOR), light=True)

    def images_opened(self) -> list[str]:
        """The page images one light poll opens."""
        return sorted(name for name in names_opened(self.poll, ps.APP.C.state).elements() if name.endswith(".png"))

    def test_each_run_has_its_own_page_memory(self):
        """Two runs in one process keep nothing in common."""
        viewer = ps.APP.RT.viewer
        one, two = ps.new_runtime(viewer).page_folders, ps.new_runtime(viewer).page_folders
        self.assertIsNot(one, two)
        self.assertEqual((one.held(), two.held()), (0, 0))

    def test_the_second_light_poll_opens_no_page_image(self):
        """The first poll of a build reads its page images; the polls after it read none, and say the same."""
        publish(ps.APP.docs[0], B1, 3)
        self.assertEqual(self.images_opened(), ["page-1.png", "page-2.png", "page-3.png"])
        first = self.poll()
        self.assertEqual(self.images_opened(), [])
        self.assertEqual(ps.APP.RT.page_folders.held(), 3)
        again = self.poll()
        self.assertEqual((again["pages"], again["pages_build"]), (first["pages"], B1))
        self.assertEqual(len(again["pages"]), 3)

    def test_a_restarted_run_reads_the_folder_again(self):
        """What a run kept goes with the run."""
        publish(ps.APP.docs[0], B1, 2)
        self.poll()
        fresh_runtime()
        self.assertEqual(ps.APP.RT.page_folders.held(), 0)
        self.assertEqual(self.images_opened(), ["page-1.png", "page-2.png"])


EVENTS = st.lists(
    st.one_of(
        st.tuples(st.just("publish"), st.integers(0, 4), st.one_of(st.none(), st.integers(1, 4)), st.booleans()),
        st.tuples(st.just("drop-other")),
        st.tuples(st.just("slim-other")),
        st.tuples(st.just("drop-shown")),
        st.tuples(st.just("legacy")),
    ),
    min_size=1,
    max_size=8,
)


class KeptAnswersEqualFreshOnes(unittest.TestCase):
    """Whatever the builds do, queries that keep page folders answer what queries that have just started do."""

    @settings(max_examples=60)
    @given(EVENTS)
    def test_every_summary_and_brief_equals_a_cold_one(self, events):
        """After each event - a build published and put on screen (with or without an unreadable image, with or
        without its history entry), another folder deleted or slimmed, the folder on screen deleted, the legacy
        layout put on screen and grown - the warm summary and brief equal the cold ones. A published folder is never
        written again and a slimmed one never goes back on screen: the product does neither."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            src = root / "ms"
            src.mkdir()
            (src / "main.tex").write_text("x\n", encoding="utf-8")
            (root / "state").mkdir()
            doc = Doc("ms", "Body", "tex", src, src / "main.tex", paths=RunPaths(src, src / "main.tex", root / "state"))
            maps = BuildMapCache()
            cache = PageFolderCache(max_rows=6)
            warm = BuildQueries(lambda: maps, pages=lambda: cache)
            published = 0
            for event in events:
                shown = artifacts.cur_pages(doc).name
                others = sorted(
                    entry.name
                    for entry in (doc.dir.iterdir() if doc.dir.is_dir() else ())
                    if entry.is_dir() and artifacts.valid_build_name(entry.name) and entry.name not in (shown, "pages")
                )
                if event[0] == "publish":
                    published += 1
                    name = "pages-202601010000%02d" % published
                    publish(doc, name, event[1], event[2])
                    if event[3]:
                        history(doc, name, 1.0)
                elif event[0] == "drop-other" and others:
                    shutil.rmtree(doc.dir / others[0])
                elif event[0] == "slim-other" and others:
                    artifacts.slim_pages(doc.dir / others[-1])
                elif event[0] == "drop-shown" and shown != "pages":
                    shutil.rmtree(doc.dir / shown, ignore_errors=True)
                elif event[0] == "legacy":
                    legacy = doc.dir / "pages"
                    legacy.mkdir(parents=True, exist_ok=True)
                    count = len(list(legacy.glob("page-*.png")))
                    (legacy / ("page-%d.png" % (count + 1))).write_bytes(png_header(10, 10))
                    (doc.dir / "pages.cur").write_text("pages", encoding="utf-8")
                cold = BuildQueries(lambda: maps, pages=PageFolderCache)
                kept, fresh = warm.summary(doc, root / "state", 150), cold.summary(doc, root / "state", 150)
                self.assertEqual((kept.brief, kept.meta), (fresh.brief, fresh.meta), event)
                again = BuildQueries(lambda: maps, pages=PageFolderCache).summary(doc, root / "state", 150)
                self.assertEqual(warm.summary(doc, root / "state", 150).brief, again.brief, event)
                self.assertLessEqual(cache.held(), 6)

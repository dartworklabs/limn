"""The source list of a LaTeX document and the files another document owns (docs/handbook/build-sync.md §원고 변화 감지).

A LaTeX document's source list - src_mtime and the fingerprint read the same one (limn.builds.artifacts.iter_sources) -
leaves out the figure-set files of a figure document's folder and a view-only document's PDF (Doc.apart), except the
ones the build on screen read. "Read" is the latexmk recorder file (.fls) the build keeps next to its pages: its INPUT
lines, parsed (fls_inputs), read back at query time through the document's own bounded memo (Doc.input_sets,
InputSetCache) and chosen against the scan made before latexmk (without_apart). These tests drive the functions
directly over a real tree and, for the build, fake latexmk and pdftoppm on PATH, so no TeX installation is needed; the
same rule through a real latexmk and the server is in src/limn/documents/tests/test_stale_figure_folder.py.

Run: uv run pytest -q src/limn/builds/tests/test_apart_sources.py
"""

import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from limn.builds import artifacts as build, engine as build_engine, run as build_run
from limn.builds.answer import build_failure_log
from limn.builds.artifacts import (
    NO_INPUTS,
    BuildFailed,
    BuildOk,
    fls_inputs,
)
from limn.runtime.documents import INPUT_CACHE_MAX, NO_APART, ApartPaths, Doc, InputSetCache, RunPaths

BUILD1 = "pages-20260926100000"
BUILD0 = "pages-20260926080000"
BUILD2 = "pages-20260926110000"
FIGS_AND_REVIEWER = ApartPaths(folders=(("figs",),), files=(("reviewer.pdf",),))

# The tree most tests scan: a manuscript with its own files, a figure set in figs/ (beside a .tex, a map and a script that
# are not figure-set suffixes), a reviewer PDF and other PDFs in the root, and folders a scan skips by name.
TREE = (
    "main.tex",
    "refs.bib",
    "reviewer.pdf",
    "appendix.pdf",
    "images/i.pdf",
    "figs/a.pdf",
    "figs/B.PNG",
    "figs/c.svg",
    "figs/d.eps",
    "figs/e.jpg",
    "figs/f.jpeg",
    "figs/g.tex",
    "figs/figures.limnmap.json",
    "figs/src/draw.py",
    "figs/sub/h.pdf",
    "figs2/j.pdf",
    ".hidden/k.pdf",
    "out/l.pdf",
    "diff/m.pdf",
)


def write_tree(root: Path, names: tuple[str, ...] = TREE) -> None:
    """Create every file of names under root with a little content of its own (its name)."""
    for name in names:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(name, encoding="utf-8")


class Tree(unittest.TestCase):
    """A LaTeX document ms over the manuscript folder, with the figure folder and the reviewer PDF set apart."""

    apart = FIGS_AND_REVIEWER

    def setUp(self):
        """Write TREE under a resolved manuscript folder and make the document over it (state folder beside it)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.top = Path(tmp.name).resolve()
        self.src = self.top / "ms"
        self.src.mkdir()
        write_tree(self.src)
        self.state = self.top / "state"
        self.paths = RunPaths(self.src, self.src / "main.tex", self.state)
        self.D = Doc("ms", "본문", "tex", src=self.src, main=self.src / "main.tex", paths=self.paths, apart=self.apart)

    def listed(self, root: Path | None = None, **kw) -> list[str]:
        """The relative paths iter_sources gives for self.D over root (default the manuscript folder)."""
        return [rel for rel, _ in build.iter_sources(self.D, root or self.src, self.state, **kw)]


class RecorderLines(unittest.TestCase):
    """fls_inputs reads the INPUT lines of a recorder file: only figure-set files inside the build copy, as paths below it."""

    ROOT = Path("/b/build")

    def names(self, text: str, cwd: Path | None = None, roots: tuple[Path, ...] = (ROOT,)) -> frozenset[str]:
        """fls_inputs of text with pdflatex's folder cwd (default the build root) and the build copy `roots`."""
        return fls_inputs(text, cwd or self.ROOT, roots)

    def test_a_relative_input_is_a_path_below_the_build_root(self):
        """`INPUT ./figs/panel1.pdf` run in the build root names figs/panel1.pdf."""
        self.assertEqual(self.names("PWD /b/build\nINPUT ./figs/panel1.pdf\n"), {"figs/panel1.pdf"})

    def test_every_spelling_of_one_path_is_the_same_name(self):
        """figs/x.pdf, ./figs/x.pdf, ./figs/../figs/x.pdf and the absolute path into the copy are one file."""
        for spelled in ("figs/x.pdf", "./figs/x.pdf", "./figs/../figs/x.pdf", "/b/build/figs/x.pdf"):
            with self.subTest(spelled=spelled):
                self.assertEqual(self.names("INPUT %s\n" % spelled), {"figs/x.pdf"})

    def test_a_path_is_resolved_from_the_folder_pdflatex_ran_in(self):
        """Run in paper/ (the main .tex's folder), ../figs/x.pdf is figs/x.pdf of the root and ./img/y.png is paper/img/y.png."""
        text = "INPUT ../figs/x.pdf\nINPUT ./img/y.png\n"
        self.assertEqual(self.names(text, cwd=self.ROOT / "paper"), {"figs/x.pdf", "paper/img/y.png"})

    def test_an_absolute_path_is_matched_against_each_root_form(self):
        """The copy named by its symlink-resolved path (what pdflatex's own getcwd gives) is the copy too."""
        roots = (Path("/b/build"), Path("/real/build"))
        self.assertEqual(self.names("INPUT /real/build/figs/x.pdf\n", roots=roots), {"figs/x.pdf"})

    def test_files_outside_the_copy_are_dropped(self):
        """TeX Live's files, a file in a sibling folder whose name starts with the root's, a path that climbs out of the
        root and the root itself are not inputs of the manuscript."""
        text = (
            "INPUT /usr/share/texlive/logo.pdf\n"
            "INPUT /b/build2/figs/x.pdf\n"
            "INPUT ../outside.pdf\n"
            "INPUT ./figs/../../up.pdf\n"
            "INPUT /b/build\n"
            "INPUT /b/build.pdf\n"
        )
        self.assertEqual(self.names(text), frozenset())

    def test_only_figure_set_suffixes_are_kept_in_any_case(self):
        """A .tex, .sty, .aux or .bib input is not a figure-set file; .PDF and .Png are, and keep their case."""
        text = "".join("INPUT ./f/a%s\n" % s for s in (".tex", ".sty", ".aux", ".bib", ".cls", ".PDF", ".Png", ".svg"))
        self.assertEqual(self.names(text), {"f/a.PDF", "f/a.Png", "f/a.svg"})

    def test_other_lines_are_ignored_and_a_name_keeps_its_spaces(self):
        """PWD, OUTPUT, blank and unknown lines, and CRLF line ends, change nothing; a space in a file name is part of it."""
        text = "PWD /b/build\r\nOUTPUT main.pdf\r\n\r\nGARBAGE ./figs/no.pdf\r\nINPUT ./figs/my panel.pdf\r\nINPUT\r\n"
        self.assertEqual(self.names(text), {"figs/my panel.pdf"})

    def test_a_name_with_a_nul_byte_is_dropped_and_its_neighbours_stay(self):
        """No file name holds a NUL: such a line is damage, not an input, and must never reach a system call."""
        text = "INPUT ./figs/a\x00.pdf\nINPUT ./figs/b.pdf\nINPUT ./figs\x00/c.pdf\n"
        self.assertEqual(self.names(text), {"figs/b.pdf"})

    def test_an_empty_recorder_lists_nothing(self):
        """No text, no inputs."""
        self.assertEqual(self.names(""), frozenset())


class RecorderFile(unittest.TestCase):
    """read_recorder answers text only for a plain, not too large file."""

    def setUp(self):
        """A temporary folder."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_a_plain_file_is_read(self):
        """The text of a UTF-8 recorder file comes back whole."""
        (self.dir / "main.fls").write_text("INPUT ./a.pdf\n", encoding="utf-8")
        self.assertEqual(build.read_recorder(self.dir / "main.fls"), "INPUT ./a.pdf\n")

    def test_missing_folder_symlink_and_oversized_files_are_not_read(self):
        """A path that does not exist, a folder, a symlink and a file over RECORDER_MAX_BYTES give None."""
        (self.dir / "folder.fls").mkdir()
        (self.dir / "real.txt").write_text("INPUT ./a.pdf\n", encoding="utf-8")
        (self.dir / "link.fls").symlink_to(self.dir / "real.txt")
        (self.dir / "big.fls").write_text("x" * 100, encoding="utf-8")
        with mock.patch.object(build, "RECORDER_MAX_BYTES", 99):
            got = [
                build.read_recorder(self.dir / n)
                for n in ("absent.fls", "folder.fls", "link.fls", "big.fls", "real.txt")
            ]
        self.assertEqual(got, [None, None, None, None, "INPUT ./a.pdf\n"])

    def test_bytes_that_are_not_utf8_are_replaced_not_fatal(self):
        """A damaged file keeps the lines that are intact."""
        (self.dir / "main.fls").write_bytes(b"\xff\xfe\nINPUT ./a.pdf\n")
        text = build.read_recorder(self.dir / "main.fls")
        self.assertIsNotNone(text)
        self.assertEqual(fls_inputs(text or "", Path("/b"), (Path("/b"),)), {"a.pdf"})


class Pages(Tree):
    """build_inputs reads the recorder file kept with a build's pages."""

    def pages(self, name: str, text: str | None) -> Path:
        """Page directory `name` of self.D, with main.fls `text` when it is given."""
        d = self.D.dir / name
        d.mkdir(parents=True, exist_ok=True)
        if text is not None:
            (d / "main.fls").write_text(text, encoding="utf-8")
        return d

    def put_on_screen(self, name: str) -> None:
        """pages.cur names `name`."""
        (self.D.dir / "pages.cur").write_text(name, encoding="utf-8")

    def test_the_build_on_screen_is_the_default_and_a_named_build_is_its_own(self):
        """Two builds with different recorder files: build_inputs(D) is the one pages.cur names, build_inputs(D, name) the named one."""
        self.pages(BUILD1, "INPUT ./figs/a.pdf\n")
        self.pages(BUILD2, "INPUT ./figs/c.svg\n")
        self.put_on_screen(BUILD2)
        self.assertEqual(build.build_inputs(self.D), {"figs/c.svg"})
        self.assertEqual(build.build_inputs(self.D, BUILD1), {"figs/a.pdf"})
        self.assertEqual(build.build_inputs(self.D, BUILD2), {"figs/c.svg"})

    def test_no_recorder_file_reads_nothing(self):
        """A build with no .fls, a page directory that is gone and no page directory at all read nothing."""
        self.pages(BUILD1, None)
        self.put_on_screen(BUILD1)
        self.assertEqual(build.build_inputs(self.D), NO_INPUTS)
        self.assertEqual(build.build_inputs(self.D, BUILD2), NO_INPUTS)
        self.assertEqual(build.build_inputs(self.D, "pages"), NO_INPUTS)

    def test_a_name_that_is_not_a_page_directory_is_never_looked_up(self):
        """A path-like name reads nothing - not even a recorder file that exists where the path would lead."""
        elsewhere = self.D.dir.parent / "x"
        elsewhere.mkdir(parents=True)
        (elsewhere / "main.fls").write_text("INPUT ./figs/a.pdf\n", encoding="utf-8")
        for name in ("../x", "pages-1", "", "pages-20260926100000/../../x"):
            with self.subTest(name=name):
                self.assertEqual(build.build_inputs(self.D, name), NO_INPUTS)

    def test_a_document_that_sets_nothing_apart_does_not_touch_the_disk(self):
        """With empty D.apart the answer is NO_INPUTS without a stat - the common instance pays nothing."""
        D = Doc("ms", "본문", "tex", src=self.src, main=self.src / "main.tex", paths=self.paths)
        self.pages(BUILD1, "INPUT ./figs/a.pdf\n")
        self.put_on_screen(BUILD1)
        with mock.patch.object(build.os, "lstat", side_effect=AssertionError("no stat")):
            self.assertEqual(build.build_inputs(D), NO_INPUTS)

    def test_a_symlinked_folder_or_oversized_recorder_file_reads_nothing(self):
        """A .fls that is a symlink, a folder or larger than RECORDER_MAX_BYTES is no source of inputs."""
        d = self.pages(BUILD1, None)
        self.put_on_screen(BUILD1)
        (d / "real.txt").write_text("INPUT ./figs/a.pdf\n", encoding="utf-8")
        (d / "main.fls").symlink_to(d / "real.txt")
        self.assertEqual(build.build_inputs(self.D), NO_INPUTS)
        (d / "main.fls").unlink()
        (d / "main.fls").mkdir()
        self.assertEqual(build.build_inputs(self.D), NO_INPUTS)
        (d / "main.fls").rmdir()
        (d / "main.fls").write_text("INPUT ./figs/a.pdf\n" + "x" * 50, encoding="utf-8")
        with mock.patch.object(build, "RECORDER_MAX_BYTES", 40):
            self.assertEqual(build.build_inputs(self.D), NO_INPUTS)


class Cache(Tree):
    """The memo of parsed recorder files is the document's own (Doc.input_sets): bounded, thread-safe, and keyed by what
    the parse depends on."""

    def fls(self, text: str = "INPUT ./figs/a.pdf\n") -> Path:
        """Write text as the recorder file of build BUILD1 of the document, put that build on screen, and return its path."""
        d = self.D.dir / BUILD1
        d.mkdir(parents=True, exist_ok=True)
        (self.D.dir / "pages.cur").write_text(BUILD1, encoding="utf-8")
        f = d / "main.fls"
        f.write_text(text, encoding="utf-8")
        return f

    def test_an_unchanged_file_is_parsed_once(self):
        """Two reads of the same recorder file parse it once and give the same set."""
        self.fls()
        with mock.patch.object(build, "recorded_inputs", wraps=build.recorded_inputs) as parse:
            first = build.build_inputs(self.D)
            second = build.build_inputs(self.D)
        self.assertEqual((first, second, parse.call_count), (frozenset({"figs/a.pdf"}), first, 1))

    def test_a_file_written_again_misses(self):
        """New text of another size is a new key: the new text is parsed and the answer is the new one."""
        self.fls()
        build.build_inputs(self.D)
        self.fls("INPUT ./figs/a.pdf\nINPUT ./figs/c.svg\n")
        self.assertEqual(build.build_inputs(self.D), {"figs/a.pdf", "figs/c.svg"})

    def test_a_warm_answer_equals_a_cold_one(self):
        """The memo holds a function of the file's bytes: the answer is recorded_inputs' on a cold memo and on a warm one."""
        f = self.fls("INPUT ./figs/B.PNG\nINPUT /usr/share/x.pdf\n")
        cold = build.build_inputs(self.D)
        warm = build.build_inputs(self.D)
        self.assertEqual((cold, warm), (build.recorded_inputs(self.D, f),) * 2)

    def test_the_oldest_entries_are_dropped_at_the_bound(self):
        """Past `limit` entries the oldest go first; the newest stay."""
        cache = InputSetCache(limit=3)
        seen: list[tuple[str, int, int, str, str]] = []

        def key(i: int) -> tuple[str, int, int, str, str]:
            """The i-th key; every parse is recorded in `seen`."""
            return ("/f", i, 1, "/o", "/b")

        for i in range(5):
            cache.get(key(i), lambda i=i: seen.append(key(i)) or frozenset({str(i)}))
        self.assertEqual((cache.held(), len(seen)), (3, 5))
        cache.get(key(4), lambda: frozenset())  # newest: kept, not parsed again
        cache.get(key(0), lambda: seen.append(key(0)) or frozenset())  # oldest: dropped, parsed again
        self.assertEqual(seen[5:], [key(0)])

    def test_the_default_bound_is_the_documents(self):
        """A document's memo holds at most INPUT_CACHE_MAX parsed files, however many builds ask."""
        for i in range(INPUT_CACHE_MAX + 10):
            self.D.input_sets.get(("/f", i, 1, "/o", "/b"), lambda: frozenset())
        self.assertEqual(self.D.input_sets.held(), INPUT_CACHE_MAX)

    def test_threads_sharing_one_memo_stay_within_the_bound_and_agree(self):
        """Eight threads asking for many keys at once: no exception, at most `limit` entries, every answer equal."""
        cache = InputSetCache(limit=10)
        want = frozenset({"figs/a.pdf"})
        answers: list[frozenset[str]] = []
        errors: list[BaseException] = []

        def worker(offset: int) -> None:
            """Ask for 60 keys, 20 of them shared with the other threads."""
            try:
                for i in range(60):
                    key = ("/f", i if i < 20 else offset * 100 + i, 1, "/o", "/b")
                    answers.append(cache.get(key, lambda: want))
            except BaseException as e:  # noqa: BLE001 - the test reports whatever a thread raised
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(errors, [])
        self.assertLessEqual(cache.held(), 10)
        self.assertEqual(set(answers), {want})

    def test_two_documents_never_share_parsed_recorder_files_and_no_module_keeps_one(self):
        """Each Doc has a memo of its own, and the build module holds none: two servers in one process share no state."""
        other = Doc("ms", "본문", "tex", src=self.src, main=self.src / "main.tex", paths=self.paths, apart=self.apart)
        self.fls()
        build.build_inputs(self.D)
        self.assertEqual((self.D.input_sets.held(), other.input_sets.held()), (1, 0))
        self.assertIsNot(self.D.input_sets, other.input_sets)
        self.assertFalse([n for n, v in vars(build).items() if isinstance(v, InputSetCache)])


class SourceList(Tree):
    """iter_sources with D.apart: what is left out, what stays, and that the build copy lists the same."""

    def test_a_figure_folder_and_a_reviewer_pdf_are_left_out_and_everything_else_stays(self):
        """figs/ loses its figure-set files (any depth, any suffix case) and the root loses reviewer.pdf; the .tex, .bib,
        other PDFs, images/, a folder that merely shares a name prefix (figs2/) stay."""
        self.assertEqual(
            self.listed(),
            ["appendix.pdf", "figs/g.tex", "figs2/j.pdf", "images/i.pdf", "main.tex", "refs.bib"],
        )

    def test_a_file_the_build_read_stays_in(self):
        """reads names figs/a.pdf and reviewer.pdf: both are listed again; a name that is not set apart changes nothing."""
        got = self.listed(reads=frozenset({"figs/a.pdf", "reviewer.pdf", "images/i.pdf", "nothing/here.pdf"}))
        self.assertEqual(
            got,
            [
                "appendix.pdf",
                "figs/a.pdf",
                "figs/g.tex",
                "figs2/j.pdf",
                "images/i.pdf",
                "main.tex",
                "refs.bib",
                "reviewer.pdf",
            ],
        )

    def test_a_read_name_does_not_bring_back_what_a_folder_rule_skips(self):
        """A dot folder, out/ and diff/ are skipped by name whatever the recorder file says."""
        got = self.listed(reads=frozenset({".hidden/k.pdf", "out/l.pdf", "diff/m.pdf"}))
        self.assertEqual(got, self.listed())

    def test_keep_apart_lists_every_file_the_rule_would_have_left_out(self):
        """keep_apart=True is the list of a document that sets nothing apart: the build hashes this and chooses afterwards."""
        plain = Doc("ms", "본문", "tex", src=self.src, main=self.src / "main.tex", paths=self.paths)
        self.assertEqual(self.listed(keep_apart=True), [r for r, _ in build.iter_sources(plain, self.src, self.state)])
        self.assertIn("figs/a.pdf", self.listed(keep_apart=True))

    def test_a_document_that_sets_nothing_apart_lists_what_it_always_listed(self):
        """NO_APART: the figure folder's PDFs and the reviewer PDF are in the list, as before the rule."""
        self.D = Doc("ms", "본문", "tex", src=self.src, main=self.src / "main.tex", paths=self.paths, apart=NO_APART)
        got = self.listed()
        self.assertEqual(
            [r for r in got if r.startswith("figs/") or r == "reviewer.pdf"],
            [
                "figs/B.PNG",
                "figs/a.pdf",
                "figs/c.svg",
                "figs/d.eps",
                "figs/e.jpg",
                "figs/f.jpeg",
                "figs/g.tex",
                "figs/sub/h.pdf",
                "reviewer.pdf",
            ],
        )

    def test_the_main_pdf_rule_still_holds_beside_the_set_apart_files(self):
        """main.pdf next to main.tex is not the manuscript, set apart or not; the same name elsewhere is listed."""
        (self.src / "main.pdf").write_text("x", encoding="utf-8")
        (self.src / "images" / "main.pdf").write_text("x", encoding="utf-8")
        got = self.listed()
        self.assertNotIn("main.pdf", got)
        self.assertIn("images/main.pdf", got)

    def test_the_build_copy_lists_the_same_files_as_the_manuscript(self):
        """The rule is in paths relative to the build root, so the copy the build fingerprints and the tree src_mtime scans agree."""
        self.D.build.mkdir(parents=True)
        build_engine.copy_manuscript(self.src, self.D.build, self.state)
        self.assertEqual(self.listed(self.D.build), self.listed())
        self.assertEqual(
            self.listed(self.D.build, reads=frozenset({"figs/a.pdf"})), self.listed(reads=frozenset({"figs/a.pdf"}))
        )

    def test_a_linked_file_or_folder_is_never_listed(self):
        """A symlink to a PDF in the figure folder and a linked folder are not walked or listed, as before the rule."""
        outside = self.top / "outside"
        outside.mkdir()
        (outside / "o.pdf").write_text("o", encoding="utf-8")
        (self.src / "linked").symlink_to(outside)
        (self.src / "images" / "link.pdf").symlink_to(outside / "o.pdf")
        got = self.listed()
        self.assertFalse([r for r in got if r.startswith("linked") or r.endswith("link.pdf")])

    def test_nested_figure_folders_are_each_left_out(self):
        """figs/ and figs/sub/ both set apart: figs/sub/h.pdf is left out once, figs/g.tex stays."""
        self.D = Doc(
            "ms",
            "본문",
            "tex",
            src=self.src,
            main=self.src / "main.tex",
            paths=self.paths,
            apart=ApartPaths(folders=(("figs",), ("figs", "sub"))),
        )
        got = self.listed()
        self.assertNotIn("figs/sub/h.pdf", got)
        self.assertIn("figs/g.tex", got)

    def test_a_main_in_a_subfolder_with_the_figure_folder_beside_it(self):
        """Root ms/, main ms/paper/main.tex, figure folder ms/figs/: paper's own images count, the figure PDFs do not,
        and paper/main.pdf (the build's output) is still not a source."""
        write_tree(self.src, ("paper/main.tex", "paper/img/p.pdf", "paper/main.pdf"))
        self.D = Doc(
            "ms",
            "본문",
            "tex",
            src=self.src,
            main=self.src / "paper" / "main.tex",
            paths=self.paths,
            apart=FIGS_AND_REVIEWER,
        )
        got = self.listed()
        self.assertIn("paper/img/p.pdf", got)
        self.assertNotIn("paper/main.pdf", got)
        self.assertNotIn("figs/a.pdf", got)


class Fingerprint(Tree):
    """The fingerprint and src_mtime follow the same list; the build's choice after latexmk equals a plain scan."""

    def digests(self, **kw) -> dict[str, build.ScannedSource]:
        """scan_sources of the manuscript with keep_apart (the build's scan before latexmk) unless kw says otherwise."""
        return build.scan_sources(self.D, self.src, self.state, **{"keep_apart": True, **kw})

    def test_choosing_after_latexmk_equals_scanning_with_the_same_reads(self):
        """fingerprint_of(without_apart(digests, reads)) == source_fingerprint(..., reads) for no reads, one, several and
        names that are not set apart - so the build's hash is what a later query computes over the same tree."""
        digests = self.digests()
        cases = (
            frozenset(),
            frozenset({"figs/a.pdf"}),
            frozenset({"figs/a.pdf", "reviewer.pdf", "figs/sub/h.pdf"}),
            frozenset({"images/i.pdf", "main.tex"}),
            frozenset({"figs/missing.pdf"}),
        )
        for reads in cases:
            with self.subTest(reads=sorted(reads)):
                self.assertEqual(
                    build.fingerprint_of(build.without_apart(self.D, digests, reads)),
                    build.source_fingerprint(self.D, self.src, self.state, reads),
                )

    def test_a_document_that_sets_nothing_apart_keeps_its_fingerprint(self):
        """With NO_APART the fingerprint is the one over every listed file, whatever reads say - what every instance
        without other documents inside its tree computed before."""
        plain = Doc("ms", "본문", "tex", src=self.src, main=self.src / "main.tex", paths=self.paths)
        a = build.source_fingerprint(plain, self.src, self.state)
        self.assertEqual(build.source_fingerprint(plain, self.src, self.state, frozenset({"figs/a.pdf"})), a)
        self.assertEqual(build.fingerprint_of(build.without_apart(plain, self.digests(), frozenset())), a)

    def test_rewriting_a_set_apart_file_does_not_change_it_and_a_read_one_does(self):
        """figs/a.pdf's bytes change: the fingerprint holds without reads and moves with figs/a.pdf in reads; an edit of
        main.tex moves it either way; a touch (same bytes, new mtime) moves nothing."""
        reads = frozenset({"figs/a.pdf"})
        base, base_read = (build.source_fingerprint(self.D, self.src, self.state, r) for r in (frozenset(), reads))
        (self.src / "figs" / "a.pdf").write_text("re-rendered", encoding="utf-8")
        self.assertEqual(build.source_fingerprint(self.D, self.src, self.state), base)
        self.assertNotEqual(build.source_fingerprint(self.D, self.src, self.state, reads), base_read)
        (self.src / "figs" / "a.pdf").write_text("figs/a.pdf", encoding="utf-8")
        os.utime(self.src / "figs" / "a.pdf", (1.0, 1.0))
        self.assertEqual(build.source_fingerprint(self.D, self.src, self.state, reads), base_read)
        (self.src / "main.tex").write_text("edited", encoding="utf-8")
        self.assertNotEqual(build.source_fingerprint(self.D, self.src, self.state), base)

    def aged_with_new_figures(self) -> tuple[Path, float, float]:
        """Back-date the tree, put build BUILD1 (no recorder file) on screen, then re-render figs/a.pdf and reviewer.pdf
        30 seconds ahead. Returns the page directory, the old time and the new one."""
        old = time.time() - 100
        for p in self.src.rglob("*"):
            if p.is_file():
                os.utime(p, (old, old))
        pages = self.D.dir / BUILD1
        pages.mkdir(parents=True)
        (self.D.dir / "pages.cur").write_text(BUILD1, encoding="utf-8")
        ahead = time.time() + 30
        os.utime(self.src / "figs" / "a.pdf", (ahead, ahead))
        os.utime(self.src / "reviewer.pdf", (ahead, ahead))
        return pages, old, ahead

    def test_src_mtime_skips_the_set_apart_files_unless_the_build_read_them(self):
        """A re-rendered figure PDF newer than everything leaves src_mtime where main.tex puts it; once the recorder file of
        the build on screen lists it (and the memo is read again), src_mtime follows it."""
        pages, old, ahead = self.aged_with_new_figures()
        self.assertAlmostEqual(build.src_mtime(self.D, self.state), old, places=3)
        (pages / "main.fls").write_text("INPUT ./figs/a.pdf\n", encoding="utf-8")
        build.expire_src_mtime(self.D)
        self.assertAlmostEqual(build.src_mtime(self.D, self.state), ahead, places=3)

    def test_the_memo_is_kept_per_build_when_files_are_set_apart_and_once_when_none_are(self):
        """Asked for two builds inside the 2 seconds, a document with files set apart measures each against its own
        recorder file; a document that sets nothing apart has the same answer for both and one memo key."""
        pages, old, ahead = self.aged_with_new_figures()
        (pages / "main.fls").write_text("INPUT ./figs/a.pdf\n", encoding="utf-8")
        newer = self.D.dir / BUILD2
        newer.mkdir()
        got = [build.src_mtime(self.D, self.state, build=b) for b in (BUILD1, BUILD2, BUILD1)]
        self.assertEqual([round(v, 3) for v in got], [round(v, 3) for v in (ahead, old, ahead)])
        plain = Doc("p", "p", "tex", src=self.src, main=self.src / "main.tex", paths=self.paths)
        build.src_mtime(plain, self.state, build=BUILD1)
        key = plain.mcache[0]
        build.src_mtime(plain, self.state, build=BUILD2)
        self.assertEqual(plain.mcache[0], key)

    def test_a_value_measured_before_a_new_build_took_the_screen_is_not_kept(self):
        """A slow src_mtime read the old build's recorder file, then a new build took the screen and expired the memo, and
        only then did the slow call store its answer: that answer is dropped, so the next read measures against the new
        build instead of hitting the old build's value inside the 2 seconds. The slow call itself answers what it measured."""
        _pages, old, ahead = self.aged_with_new_figures()
        real = build.build_inputs
        started, release, calls = threading.Event(), threading.Event(), []

        def slow(D, name=None):
            """The real lookup; the first call then waits until the test lets it go."""
            got = real(D, name)
            if not calls:
                calls.append(name)
                started.set()
                release.wait(10)
            return got

        answers: list[float] = []
        with mock.patch.object(build, "build_inputs", slow):
            reader = threading.Thread(target=lambda: answers.append(build.src_mtime(self.D, self.state)))
            reader.start()
            self.assertTrue(started.wait(10))
            newdir = self.D.dir / BUILD2
            newdir.mkdir()
            (newdir / "main.fls").write_text("INPUT ./figs/a.pdf\n", encoding="utf-8")
            (self.D.dir / "pages.cur").write_text(BUILD2, encoding="utf-8")
            build.expire_src_mtime(self.D)
            release.set()
            reader.join(10)
            self.assertFalse(reader.is_alive())
            self.assertAlmostEqual(build.src_mtime(self.D, self.state), ahead, places=3)
        self.assertAlmostEqual(answers[0], old, places=3)

    def test_an_expiry_that_comes_before_the_measurement_does_not_discard_it(self):
        """The generation only drops a value measured across an expiry: one measured after it is kept, and a hit follows."""
        _pages, old, _ahead = self.aged_with_new_figures()
        build.expire_src_mtime(self.D)
        first = build.src_mtime(self.D, self.state)
        with mock.patch.object(build, "build_inputs", side_effect=AssertionError("kept: a hit")):
            self.assertEqual(build.src_mtime(self.D, self.state), first)
        self.assertAlmostEqual(first, old, places=3)

    def test_commit_pages_runs_its_hook_right_after_the_pointer_swap(self):
        """The hook runs once the pointer names the new pages and before older page directories are removed and before git
        is asked for the head, which can take seconds: the memo must not outlive the swap by that long."""
        self.D.dir.mkdir(parents=True)
        for name in (BUILD0, BUILD1, BUILD2):
            (self.D.dir / name).mkdir()
        (self.D.dir / "pages.cur").write_text(BUILD1, encoding="utf-8")
        seen: list[tuple] = []

        def run_git(*_a, **_k):
            """git, recorded; the head it answers is "abc1234"."""
            seen.append(("git",))
            return subprocess.CompletedProcess([], 0, stdout="abc1234\n")

        def hook() -> None:
            """What the hook sees: the pointer and whether the oldest page directory is still there."""
            seen.append(
                ("hook", (self.D.dir / "pages.cur").read_text(encoding="utf-8"), (self.D.dir / BUILD0).exists())
            )

        with mock.patch.object(build_engine, "run_git", run_git):
            head = build_engine.commit_pages(self.D, self.D.dir / BUILD2, on_swap=hook)
        self.assertEqual(head, "abc1234")
        self.assertEqual(seen, [("hook", BUILD2, True), ("git",)])
        self.assertFalse((self.D.dir / BUILD0).exists())

    def test_a_memo_hit_does_not_look_at_the_build_again(self):
        """Within the 2 second memo the answer is the memo's: neither the recorder file nor the page pointer is read."""
        self.D.mcache[2] = 0.0
        first = build.src_mtime(self.D, self.state)
        with mock.patch.object(build, "build_inputs", side_effect=AssertionError("a memo hit reads no build")):
            self.assertEqual(build.src_mtime(self.D, self.state), first)
            self.assertEqual(build.source_newer(self.D, self.state), 0.0)

    def test_the_newest_read_apart_file_is_the_newest_plain_file_that_is_both_read_and_set_apart(self):
        """newest_read_apart takes the mtimes of the scan made before latexmk, and ignores a name that is not set apart,
        one the scan does not have (made later, or gone) and a symlink."""
        for rel, t in (("figs/a.pdf", 5000.0), ("reviewer.pdf", 7000.0), ("images/i.pdf", 9000.0)):
            os.utime(self.src / rel, (t, t))
        (self.src / "figs" / "link.pdf").symlink_to(self.src / "images" / "i.pdf")
        scan = self.digests()
        reads = frozenset({"figs/a.pdf", "reviewer.pdf", "images/i.pdf", "figs/gone.pdf", "figs/link.pdf"})
        self.assertEqual(build.newest_read_apart(self.D, scan, reads), 7000.0)
        self.assertEqual(build.newest_read_apart(self.D, scan, frozenset()), 0.0)
        os.utime(self.src / "reviewer.pdf", (8000.0, 8000.0))
        self.assertEqual(build.newest_read_apart(self.D, scan, reads), 7000.0, "the scan's mtime, not the file's now")

    def test_a_file_the_scan_did_not_have_is_not_one_of_the_builds_reads(self):
        """read_in_scan keeps a listed name only when the scan before latexmk had that file."""
        scan = self.digests()
        listed = frozenset({"figs/a.pdf", "figs/fig-eps-converted-to.pdf", "reviewer.pdf"})
        self.assertEqual(build.read_in_scan(scan, listed), {"figs/a.pdf", "reviewer.pdf"})

    def copy_in_whole_seconds(self) -> None:
        """Copy the manuscript into D.build and truncate every file of the copy to a whole second."""
        self.D.build.mkdir(parents=True)
        build_engine.copy_manuscript(self.src, self.D.build, self.state)
        for p in self.D.build.rglob("*"):
            if p.is_file():
                os.utime(p, (int(p.stat().st_mtime), int(p.stat().st_mtime)))

    def test_a_scan_of_the_copy_takes_each_files_mtime_from_the_source_when_it_agrees_to_the_second(self):
        """A copy that lost the fraction: with mtimes_from the scan has the source's mtime, fraction included; without it,
        the copy's."""
        os.utime(self.src / "figs" / "a.pdf", (1000.75, 1000.75))
        os.utime(self.src / "main.tex", (2000.25, 2000.25))
        self.copy_in_whole_seconds()
        plain = build.scan_sources(self.D, self.D.build, self.state, keep_apart=True)
        exact = build.scan_sources(self.D, self.D.build, self.state, keep_apart=True, mtimes_from=self.src)
        self.assertEqual((plain["figs/a.pdf"].mtime, plain["main.tex"].mtime), (1000.0, 2000.0))
        self.assertEqual((exact["figs/a.pdf"].mtime, exact["main.tex"].mtime), (1000.75, 2000.25))
        self.assertEqual({k: v.digest for k, v in exact.items()}, {k: v.digest for k, v in plain.items()})

    def test_a_source_that_differs_by_a_second_or_more_or_is_not_a_plain_file_gives_the_copys_mtime(self):
        """The source file changed since the copy (a second or more apart), is gone, or is a symlink: the copy's mtime,
        which is what the scan hashed, stands."""
        os.utime(self.src / "figs" / "a.pdf", (1000.75, 1000.75))
        os.utime(self.src / "figs" / "c.svg", (3000.5, 3000.5))
        os.utime(self.src / "figs" / "d.eps", (4000.5, 4000.5))
        os.utime(self.src / "figs" / "e.jpg", (5000.99, 5000.99))  # 0.99 s past its whole-second copy: the same file
        self.copy_in_whole_seconds()
        os.utime(self.src / "figs" / "a.pdf", (1002.0, 1002.0))  # written again two seconds later
        (self.src / "figs" / "c.svg").unlink()  # gone
        (self.src / "figs" / "d.eps").unlink()  # replaced by a link
        (self.src / "figs" / "d.eps").symlink_to(self.src / "main.tex")
        got = build.scan_sources(self.D, self.D.build, self.state, keep_apart=True, mtimes_from=self.src)
        self.assertEqual(
            [round(got[k].mtime, 3) for k in ("figs/a.pdf", "figs/c.svg", "figs/d.eps", "figs/e.jpg")],
            [1000.0, 3000.0, 4000.0, 5000.99],
        )

    def test_the_scan_takes_the_mtime_of_each_file_and_the_digest_of_its_bytes(self):
        """ScannedSource(digest, mtime) of a file is its content's SHA-256 and the mtime it had."""
        os.utime(self.src / "figs" / "a.pdf", (1234.0, 1234.0))
        got = self.digests()["figs/a.pdf"]
        self.assertEqual((got.digest, got.mtime), (hashlib.sha256(b"figs/a.pdf").digest(), 1234.0))


FAKE_LATEXMK = """#!/bin/sh
for a; do main=$a; done
stem=${main%.tex}
case "$LIMN_TEST_LATEXMK" in
  nopdf) ;;
  *) cp "$main" "$stem.pdf"; printf 'synctex' > "$stem.synctex.gz"; : > "$stem.log" ;;
esac
if [ -n "$LIMN_TEST_EDIT" ]; then printf '%% edited while latexmk ran\\n' >> "$LIMN_TEST_EDIT"; fi
if [ -n "$LIMN_TEST_GENERATE" ]; then mkdir -p "$(dirname "$LIMN_TEST_GENERATE")"; printf generated > "$LIMN_TEST_GENERATE"; fi
case "$LIMN_TEST_RECORDER" in
  off) ;;
  link) ln -s "$main" "$stem.fls" ;;
  *) { printf 'PWD %s\\nINPUT /usr/share/texlive/article.cls\\n' "$PWD"; printf '%b' "$LIMN_TEST_INPUTS"; } > "$stem.fls" ;;
esac
"""
FAKE_PDFTOPPM = """#!/bin/sh
cp "$4" "$5-1.png"
"""


class Compile(Tree):
    """compile_tex with a latexmk that writes a recorder file: it is kept with the pages, and the fingerprint and the
    baseline mtime are what the build read."""

    def setUp(self):
        """The fakes on PATH, a main.tex to compile and the build settings."""
        super().setUp()
        (self.src / "main.tex").write_text(
            "\\documentclass{article}\\begin{document}A\\end{document}\n", encoding="utf-8"
        )
        bin_dir = self.top / "bin"
        bin_dir.mkdir()
        for name, text in (("latexmk", FAKE_LATEXMK), ("pdftoppm", FAKE_PDFTOPPM)):
            (bin_dir / name).write_text(text, encoding="utf-8")
            (bin_dir / name).chmod(0o755)
        self.env = {"PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", "")}
        self.cfg = build.BuildConfig(state=self.state, dpi=72, timeout=10)

    def tracked(
        self, inputs: str = "", latexmk: str = "ok", recorder: str = "on", edit: Path | None = None, generate: str = ""
    ):
        """One tracked build of the document with the fake latexmk writing a recorder file that lists `inputs` (INPUT
        lines, printf %b escapes allowed). While it runs it appends a line to the file `edit` (a source edit made
        mid-build) and creates the file `generate` in the build copy (something latexmk itself makes, such as an
        epstopdf conversion)."""
        env = dict(
            self.env,
            LIMN_TEST_LATEXMK=latexmk,
            LIMN_TEST_RECORDER=recorder,
            LIMN_TEST_INPUTS=inputs,
            LIMN_TEST_EDIT=str(edit or ""),
            LIMN_TEST_GENERATE=generate,
        )
        with mock.patch.dict(os.environ, env):
            return build_run.run_tracked(
                self.D, self.state, lambda: build_engine.compile_tex(self.D, self.cfg, None), "t0", build_failure_log
            )

    def test_the_recorder_file_is_kept_with_the_pages_of_the_build(self):
        """After a build the page directory holds main.fls - the one latexmk wrote - next to the PDF, SyncTeX file and pages."""
        res = self.tracked("INPUT ./figs/a.pdf\n")
        self.assertIsInstance(res, BuildOk)
        pages = build.cur_pages(self.D)
        self.assertIn("INPUT ./figs/a.pdf", (pages / "main.fls").read_text(encoding="utf-8"))
        self.assertEqual(build.build_inputs(self.D), {"figs/a.pdf"})

    def test_a_build_without_a_recorder_file_publishes_none_and_reads_nothing(self):
        """latexmk with its recorder switched off leaves no .fls: nothing is kept, the build reads no figure-set file."""
        res = self.tracked("INPUT ./figs/a.pdf\n", recorder="off")
        self.assertIsInstance(res, BuildOk)
        self.assertFalse((build.cur_pages(self.D) / "main.fls").exists())
        self.assertEqual(build.build_inputs(self.D), NO_INPUTS)

    def test_a_recorder_file_that_is_a_symlink_is_not_published(self):
        """Only a plain file is copied into the pages."""
        res = self.tracked(recorder="link")
        self.assertIsInstance(res, BuildOk)
        self.assertFalse((build.cur_pages(self.D) / "main.fls").exists())

    def test_the_fingerprint_of_the_build_is_what_a_query_computes_over_the_same_tree(self):
        """src_hash recorded for the build == doc_fingerprint right after it, with and without a figure-set file read."""
        for inputs in ("", "INPUT ./figs/a.pdf\nINPUT ./reviewer.pdf\n"):
            with self.subTest(inputs=inputs):
                res = self.tracked(inputs)
                self.assertIsInstance(res, BuildOk)
                self.assertEqual(res.src_hash, build.doc_fingerprint(self.D, self.state))

    def test_a_rebuild_after_rewriting_a_file_it_never_reads_has_the_same_fingerprint(self):
        """figs/a.pdf is not in the recorder file: its new bytes do not change the build's fingerprint. A file it reads does."""
        first = self.tracked("INPUT ./figs/c.svg\n")
        (self.src / "figs" / "a.pdf").write_text("a new rendering", encoding="utf-8")
        same = self.tracked("INPUT ./figs/c.svg\n")
        (self.src / "figs" / "c.svg").write_text("a new rendering", encoding="utf-8")
        moved = self.tracked("INPUT ./figs/c.svg\n")
        self.assertEqual((first.src_hash == same.src_hash, same.src_hash == moved.src_hash), (True, False))

    def test_a_build_that_starts_reading_a_figure_file_takes_it_as_its_baseline(self):
        """The previous build read nothing from figs/; the .tex now includes figs/a.pdf, which was re-rendered after the
        .tex edit and before the build. The baseline of the new build covers that file, so the document is not stale
        the moment the build ends - and the fingerprint already includes it."""
        old = time.time() - 100
        for p in self.src.rglob("*"):
            if p.is_file():
                os.utime(p, (old, old))
        self.assertIsInstance(self.tracked(), BuildOk)
        newer = old + 50
        os.utime(self.src / "figs" / "a.pdf", (newer, newer))
        res = self.tracked("INPUT ./figs/a.pdf\n")
        self.assertIsInstance(res, BuildOk)
        self.assertGreaterEqual(res.src_mtime, newer - 1e-3)
        self.assertLess(build.source_newer(self.D, self.state), 1e-3)
        self.assertEqual(res.src_hash, build.doc_fingerprint(self.D, self.state))
        os.utime(self.src / "figs" / "a.pdf", (newer + 30, newer + 30))
        self.D.mcache[2] = 0.0
        self.assertAlmostEqual(build.source_newer(self.D, self.state), 30.0, places=2)

    def test_a_build_that_stops_reading_a_figure_file_no_longer_counts_it(self):
        """The previous build read figs/a.pdf, the new one does not: re-rendering it afterwards leaves the document current."""
        old = time.time() - 100
        for p in self.src.rglob("*"):
            if p.is_file():
                os.utime(p, (old, old))
        self.assertIsInstance(self.tracked("INPUT ./figs/a.pdf\n"), BuildOk)
        self.assertIsInstance(self.tracked(), BuildOk)
        ahead = time.time() + 30
        os.utime(self.src / "figs" / "a.pdf", (ahead, ahead))
        self.D.mcache[2] = 0.0
        self.assertLess(build.source_newer(self.D, self.state), 1e-3)

    def test_a_failed_build_publishes_nothing_and_keeps_the_screens_recorder_file(self):
        """latexmk makes no PDF: BuildFailed, no new page directory, and the build on screen still answers from its own .fls."""
        self.assertIsInstance(self.tracked("INPUT ./figs/a.pdf\n"), BuildOk)
        before = build.cur_pages(self.D)
        res = self.tracked("INPUT ./figs/c.svg\n", latexmk="nopdf")
        self.assertIsInstance(res, BuildFailed)
        self.assertEqual(build.cur_pages(self.D), before)
        self.assertEqual(build.build_inputs(self.D), {"figs/a.pdf"})

    def test_a_document_that_sets_nothing_apart_gets_the_fingerprint_it_always_got(self):
        """Without other documents inside its tree the build's src_hash is the plain scan of the copy."""
        self.D = Doc("ms", "본문", "tex", src=self.src, main=self.src / "main.tex", paths=self.paths)
        res = self.tracked("INPUT ./figs/a.pdf\n")
        self.assertIsInstance(res, BuildOk)
        self.assertEqual(res.src_hash, build.source_fingerprint(self.D, self.D.build, self.state))
        self.assertEqual(res.src_hash, build.doc_fingerprint(self.D, self.state))

    def age_tree(self) -> float:
        """Back-date every file of the manuscript by 100 seconds; returns that time."""
        old = time.time() - 100
        for p in self.src.rglob("*"):
            if p.is_file():
                os.utime(p, (old, old))
        return old

    def test_a_source_edited_while_latexmk_runs_still_makes_the_document_stale(self):
        """latexmk converts an EPS into figs/fig-eps-converted-to.pdf, which the .fls lists, and main.tex is edited during
        the run: the file latexmk made is not a source the build read, so the baseline stays at the measurement before
        the copy and the edit is newer than it - the document is stale, as the edit is a change the build never saw."""
        self.age_tree()
        res = self.tracked(
            "INPUT ./figs/fig-eps-converted-to.pdf\n",
            edit=self.src / "main.tex",
            generate="figs/fig-eps-converted-to.pdf",
        )
        self.assertIsInstance(res, BuildOk)
        self.D.mcache[2] = 0.0
        self.assertGreater(build.source_newer(self.D, self.state), 2)

    def test_a_file_latexmk_makes_in_a_figure_folder_does_not_raise_the_baseline(self):
        """The baseline of a build that lists a file it created itself (absent from the copy before latexmk) is the
        manuscript's mtime, not that file's - its fingerprint is the one of the sources."""
        old = self.age_tree()
        res = self.tracked("INPUT ./figs/gen-converted-to.pdf\n", generate="figs/gen-converted-to.pdf")
        made = (self.D.build / "figs" / "gen-converted-to.pdf").stat().st_mtime
        self.assertIsInstance(res, BuildOk)
        self.assertGreater(made - old, 50)
        self.assertAlmostEqual(res.src_mtime, old, places=2)
        self.assertEqual(res.src_hash, build.source_fingerprint(self.D, self.src, self.state))

    def test_a_figure_file_that_was_in_the_copy_still_raises_the_baseline_to_its_mtime(self):
        """Counterpart of the previous test: figs/a.pdf, present before latexmk and listed, sets the baseline to its mtime."""
        old = self.age_tree()
        newer = old + 50
        os.utime(self.src / "figs" / "a.pdf", (newer, newer))
        res = self.tracked("INPUT ./figs/a.pdf\n")
        self.assertIsInstance(res, BuildOk)
        self.assertAlmostEqual(res.src_mtime, newer, places=2)

    def test_a_recorder_file_shipped_with_the_manuscript_is_not_what_the_build_read(self):
        """The manuscript carries a main.fls (a committed latexmk by-product) and latexmk's recorder is off, so this run
        wrote none: the old file is not read, not published, and the fingerprint has no figure-set file in it."""
        (self.src / "main.fls").write_text("PWD /x\nINPUT ./figs/a.pdf\n", encoding="utf-8")
        self.age_tree()
        res = self.tracked(recorder="off")
        self.assertIsInstance(res, BuildOk)
        self.assertEqual(res.src_hash, build.source_fingerprint(self.D, self.src, self.state))
        self.assertFalse((build.cur_pages(self.D) / "main.fls").exists())

    def whole_second_copy(self, after_copy=None):
        """Patch the build's copy step so the copy keeps mtimes to whole seconds only, as the rsync of macOS does, and run
        `after_copy` (when given) once the copy is made. A context manager."""
        real = build_engine.copy_manuscript

        def copy(src: Path, dest: Path, state: Path) -> None:
            """The real copy, then every file of the copy truncated to a whole second."""
            real(src, dest, state)
            for p in dest.rglob("*"):
                if p.is_file() and not p.is_symlink():
                    whole = int(p.stat().st_mtime)
                    os.utime(p, (whole, whole))
            if after_copy is not None:
                after_copy()

        return mock.patch.object(build_engine, "copy_manuscript", copy)

    def test_a_copy_that_keeps_whole_seconds_does_not_cost_the_baseline_its_fraction(self):
        """On macOS the copy's mtimes lose their fraction. The baseline of a build that read figs/a.pdf is that file's mtime
        as the source tree has it, so the document is not newer than its own build by the lost fraction: src_mtime is the
        source's mtime to the microsecond, and a query right after the build finds nothing newer."""
        old = self.age_tree()
        newer = int(old) + 50.62
        os.utime(self.src / "figs" / "a.pdf", (newer, newer))
        with self.whole_second_copy():
            res = self.tracked("INPUT ./figs/a.pdf\n")
        self.assertIsInstance(res, BuildOk)
        self.assertEqual(int((self.D.build / "figs" / "a.pdf").stat().st_mtime), int(newer))
        self.assertAlmostEqual(res.src_mtime, newer, places=4)
        self.D.mcache[2] = 0.0
        self.assertLess(build.source_newer(self.D, self.state), 1e-3)
        self.assertEqual(res.src_hash, build.doc_fingerprint(self.D, self.state))

    def test_the_baseline_of_a_build_that_read_nothing_is_the_sources_mtime_whatever_the_copy_keeps(self):
        """Control: with nothing set apart read, the baseline is main.tex's mtime from the source tree (measured before
        the copy), fraction included, with a whole-second copy as with an exact one."""
        old = self.age_tree()
        os.utime(self.src / "main.tex", (old + 0.37, old + 0.37))
        with self.whole_second_copy():
            res = self.tracked()
        self.assertIsInstance(res, BuildOk)
        self.assertAlmostEqual(res.src_mtime, old + 0.37, places=4)

    def test_a_figure_file_changed_between_the_copy_and_the_scan_keeps_the_copys_mtime(self):
        """figs/a.pdf is re-rendered 10 seconds later in the source after the copy was made: the copy still holds the old
        bytes, so the baseline is the copy's mtime - not the source's - and the re-render shows as newer than the build."""
        old = self.age_tree()
        newer = int(old) + 50.62
        os.utime(self.src / "figs" / "a.pdf", (newer, newer))

        def re_render() -> None:
            """The source file is written again, 10 seconds ahead, after the copy."""
            os.utime(self.src / "figs" / "a.pdf", (newer + 10, newer + 10))

        with self.whole_second_copy(re_render):
            res = self.tracked("INPUT ./figs/a.pdf\n")
        self.assertIsInstance(res, BuildOk)
        self.assertAlmostEqual(res.src_mtime, int(newer), places=4)
        self.D.mcache[2] = 0.0
        self.assertGreater(build.source_newer(self.D, self.state), 2)

    def test_a_finished_build_expires_the_memo_so_it_is_measured_at_once(self):
        """The 2 second memo holds the answer measured against the previous build. A build whose recorder file lists
        figs/a.pdf, re-rendered since, ends: the next src_mtime already follows that file, without waiting."""
        old = self.age_tree()
        ahead = time.time() + 30
        os.utime(self.src / "figs" / "a.pdf", (ahead, ahead))
        self.D.mcache[2] = 0.0
        self.assertAlmostEqual(build.src_mtime(self.D, self.state), old, places=2)
        res = self.tracked("INPUT ./figs/a.pdf\n")
        self.assertIsInstance(res, BuildOk)
        self.assertAlmostEqual(build.src_mtime(self.D, self.state), ahead, places=2)

    def test_a_nul_in_a_recorder_input_name_does_not_crash_the_build(self):
        """A NUL byte in an INPUT name would make os.lstat raise ValueError: the name is dropped, the other inputs stay,
        and the build is BuildOk, not a crashed one."""
        old = self.age_tree()
        newer = old + 50
        os.utime(self.src / "figs" / "c.svg", (newer, newer))
        res = self.tracked("INPUT ./figs/a\\0000.pdf\nINPUT ./figs/c.svg\n")
        self.assertIsInstance(res, BuildOk, getattr(res, "detail", res))
        self.assertAlmostEqual(res.src_mtime, newer, places=2)

    def test_a_recorder_file_that_raises_when_read_does_not_fail_the_build(self):
        """Whatever OSError or ValueError reading the recorder file raises, the build that made its pages is BuildOk and
        has read no figure-set file."""
        self.age_tree()
        for error in (OSError("gone"), ValueError("embedded null byte")):
            with self.subTest(error=type(error).__name__):
                shutil.rmtree(self.D.dir, ignore_errors=True)  # no earlier build whose .fls a query would parse
                with mock.patch.object(build, "recorded_inputs", side_effect=error):
                    res = self.tracked("INPUT ./figs/a.pdf\n")
                self.assertIsInstance(res, BuildOk)
                self.assertEqual(res.src_hash, build.source_fingerprint(self.D, self.src, self.state))


class OlderBuild(Tree):
    """source_newer for a named build uses that build's recorder file, not the one on screen."""

    def test_the_named_builds_reads_decide(self):
        """BUILD1 read figs/a.pdf, BUILD2 (on screen) did not: re-rendering it makes BUILD1's pick stale and BUILD2's not."""
        old = time.time() - 100
        for p in self.src.rglob("*"):
            if p.is_file():
                os.utime(p, (old, old))
        for name, text in ((BUILD1, "INPUT ./figs/a.pdf\n"), (BUILD2, "")):
            d = self.D.dir / name
            d.mkdir(parents=True)
            (d / "main.fls").write_text(text, encoding="utf-8")
        (self.D.dir / "pages.cur").write_text(BUILD2, encoding="utf-8")
        (self.D.dir / "built_src_mtime.txt").write_text("%f" % old, encoding="utf-8")
        (self.D.dir / "builds.json").write_text(
            '{"seq": 1, "last": null, "builds": [{"build": "%s", "src_mtime": %f}]}' % (BUILD1, old), encoding="utf-8"
        )
        ahead = time.time() + 30
        os.utime(self.src / "figs" / "a.pdf", (ahead, ahead))
        self.D.mcache[2] = 0.0
        self.assertAlmostEqual(build.source_newer(self.D, self.state, BUILD1), 130.0, delta=2.0)
        self.D.mcache[2] = 0.0
        self.assertLess(build.source_newer(self.D, self.state, BUILD2), 1e-3)
        self.assertLess(build.source_newer(self.D, self.state), 1e-3)


if __name__ == "__main__":
    unittest.main()

"""Warm LaTeX and the no-change skip (docs/handbook/build-sync.md §따뜻한 LaTeX와 변경 없는 재빌드).

The build copy keeps latexmk's byproducts of the main file between builds, so latexmk runs only what changed; a rebuild
whose copy has the fingerprint and recipe of the build on screen ends as BuildUnchanged without latexmk or a render.
The fast cases drive compile_tex and run_tracked with stand-ins on PATH; the `tex` cases run the real latexmk.

Run: uv run pytest -q src/limn/builds/tests/test_warm.py
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from unittest import mock

from limn.builds import artifacts as build, engine as build_engine, run as build_run, warm
from limn.builds.answer import build_failure_log, finished_build_body, rebuild_answer
from limn.builds.artifacts import BuildFailed, BuildOk, BuildUnchanged
from limn.runtime.documents import NO_APART, ApartPaths, InputSetCache

from helpers import Base, needs_tex, req, split_resp


@dataclass
class WarmDoc:
    """A LaTeX document as the build sees it (the BuildDoc protocol), every path given: the main .tex sits in a
    sub-folder of the build root, as a --doc document's does, so the copy keeps its byproducts one level down."""

    src: Path
    main: Path
    dir: Path
    lock: threading.Lock = field(default_factory=threading.Lock)
    bstate: dict = field(default_factory=lambda: {"state": "idle", "seq": 0})
    bstate_lock: threading.Lock = field(default_factory=threading.Lock)
    builds_lock: threading.Lock = field(default_factory=threading.Lock)
    mcache: list = field(default_factory=lambda: [None, 0.0, 0.0])
    mcache_lock: threading.Lock = field(default_factory=threading.Lock)
    mcache_epoch: int = 0
    builds_from_source: bool = True
    watches_files: bool = False
    apart: ApartPaths = NO_APART
    input_sets: InputSetCache = field(default_factory=InputSetCache)

    @property
    def build(self) -> Path:
        """This document's build copy, inside its own state folder."""
        return self.dir / "build"

    @property
    def main_rel(self) -> Path:
        """The main .tex relative to the build root."""
        return self.main.relative_to(self.src)

    @property
    def out(self) -> Path:
        """latexmk runs next to the main .tex inside the copy."""
        return self.build / self.main_rel.parent

    @property
    def pdf_name(self) -> str:
        """The PDF copy's name in a page directory."""
        return self.main.stem + ".pdf"


# latexmk stand-in: appends "warm" or "cold" to $LIMN_TEST_CALLS (was main.aux there when it started?), then writes
# the PDF (the .tex), SyncTeX, log, aux, fdb_latexmk and a recorder file listing the main file and $LIMN_TEST_INPUTS
# (none when LIMN_TEST_RECORDER=off); LIMN_TEST_LATEXMK=nopdf writes nothing and fails.
FAKE_LATEXMK = """#!/bin/sh
for a; do main=$a; done
stem=${main%.tex}
if [ -f "$stem.aux" ]; then echo warm >> "$LIMN_TEST_CALLS"; else echo cold >> "$LIMN_TEST_CALLS"; fi
[ "$LIMN_TEST_LATEXMK" = nopdf ] && exit 12
cp "$main" "$stem.pdf"
printf 'synctex' > "$stem.synctex.gz"
: > "$stem.log"
echo 'relax' > "$stem.aux"
case "$LIMN_TEST_RECORDER" in
  off) rm -f "$stem.fls" ;;
  *) { printf 'PWD %s\\nINPUT %s\\n' "$PWD" "$main"; printf '%b' "$LIMN_TEST_INPUTS"; } > "$stem.fls" ;;
esac
echo fdb > "$stem.fdb_latexmk"
"""
FAKE_PDFTOPPM = """#!/bin/sh
printf 'P6\\n2 1\\n255\\n\\377\\377\\377\\0\\0\\0'
"""
FAKE_PDFINFO = """#!/bin/sh
echo "Pages:          1"
"""
BYPRODUCTS = ("main.aux", "main.fdb_latexmk", "main.fls", "main.log", "main.pdf", "main.synctex.gz")


def stand_ins(case: unittest.TestCase, root: Path) -> Path:
    """Put the latexmk, pdftoppm and pdfinfo stand-ins first on PATH for the rest of case; returns the calls file."""
    bin_dir = root / "bin"
    bin_dir.mkdir()
    for name, text in (("latexmk", FAKE_LATEXMK), ("pdftoppm", FAKE_PDFTOPPM), ("pdfinfo", FAKE_PDFINFO)):
        (bin_dir / name).write_text(text, encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    calls = root / "calls.txt"
    env = mock.patch.dict(
        os.environ,
        {
            "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
            "LIMN_TEST_CALLS": str(calls),
            "LIMN_TEST_LATEXMK": "ok",
            "LIMN_TEST_RECORDER": "on",
            "LIMN_TEST_INPUTS": "",
        },
    )
    env.start()
    case.addCleanup(env.stop)
    return calls


class KeptPaths(unittest.TestCase):
    """warm.kept_paths: what the copy leaves alone in the build copy."""

    def test_the_main_files_byproducts_and_pdf_are_kept_where_latexmk_runs(self):
        """For main.tex in 1st/ the kept paths are 1st/main.<byproduct> and 1st/main.pdf, anchored there."""
        kept = warm.kept_paths(PurePosixPath("1st"), "main", ["main.tex", "references.bib", "main.pdf"])
        self.assertIn("1st/main.aux", kept)
        self.assertIn("1st/main.fdb_latexmk", kept)
        self.assertIn("1st/main.fls", kept)
        self.assertIn("1st/main.bbl", kept)
        self.assertIn("1st/main.pdf", kept)
        self.assertTrue(all(p.startswith("1st/main.") for p in kept), kept)
        self.assertEqual(warm.kept_paths(PurePosixPath("."), "main", [])[0].count("/"), 0)

    def test_a_source_that_ships_a_byproduct_builds_cold(self):
        """A manuscript that ships main.bbl (or any byproduct name but the PDF) keeps nothing - every build is cold,
        as before - so its own file is copied and used, never a cached one."""
        for shipped in ("main.bbl", "main.aux", "main.fdb_latexmk", "main.log"):
            with self.subTest(shipped=shipped):
                self.assertEqual(warm.kept_paths(PurePosixPath("."), "main", ["main.tex", shipped]), ())
        self.assertNotEqual(warm.kept_paths(PurePosixPath("."), "main", ["main.tex", "other.bbl", "main.pdf"]), ())

    def test_the_last_up_to_date_line_names_the_target(self):
        """up_to_date_target is the target of the last 'Latexmk: All targets (X) are up-to-date' line; a line that is not
        latexmk's own, or none, is None."""
        self.assertEqual(warm.up_to_date_target("Latexmk: All targets (main.pdf) are up-to-date\n"), "main.pdf")
        two = "Latexmk: All targets (a.pdf) are up-to-date\nLatexmk: All targets (build/main.pdf) are up-to-date\n"
        self.assertEqual(warm.up_to_date_target(two), "build/main.pdf")
        self.assertIsNone(warm.up_to_date_target("% All targets (main.pdf) are up-to-date in a comment\n"))
        self.assertIsNone(warm.up_to_date_target("Latexmk: Run number 1 of rule 'pdflatex'\n"))

    def test_latexmk_vouches_only_for_an_untouched_pdf_of_its_own_target_in_a_warm_copy(self):
        """vouched needs every condition: a warm copy, exit 0, no timeout, a PDF that was there and that this run did
        not write, and the last target exactly <stem>.pdf. Dropping any one of them refuses."""
        line, sig = "Latexmk: All targets (main.pdf) are up-to-date\n", (1, 2, 3)
        self.assertTrue(warm.vouched(line, "main", True, 0, False, sig, sig))
        for name, args in (
            ("cold copy", (line, "main", False, 0, False, sig, sig)),
            ("exit 12", (line, "main", True, 12, False, sig, sig)),
            ("timed out", (line, "main", True, 0, True, sig, sig)),
            ("no PDF before", (line, "main", True, 0, False, None, sig)),
            ("PDF written", (line, "main", True, 0, False, sig, (4, 2, 3))),
            ("out_dir", ("Latexmk: All targets (build/main.pdf) are up-to-date\n", "main", True, 0, False, sig, sig)),
            ("jobname", ("Latexmk: All targets (other.pdf) are up-to-date\n", "main", True, 0, False, sig, sig)),
            ("no line", ("", "main", True, 0, False, sig, sig)),
        ):
            with self.subTest(name):
                self.assertFalse(warm.vouched(*args))


FDB = """# Fdb version 4
["bibtex main"] 1790888405.96743 "main.aux" "main.bbl" "main" 1790888406.54166 0
  "./refs.bib" 1790888404.90003 57 3449d4b2a80210a3e0b0e19846068304 ""
  "/usr/local/texlive/2025/texmf-dist/bibtex/bst/base/plain.bst" 1292289607 20613 bd3fbfa9f64872b81ac57a0dd2ed855f ""
  "main.aux" 1790888406.30505 92 b70a13514d2aff8d7f882c43a4a14612 "pdflatex"
  (generated)
  "main.bbl"
  "main.blg"
  (rewritten before read)
["pdflatex"] 1790888406.07911 "main.tex" "main.pdf" "main" 1790888406.54181 0
  "/usr/local/texlive/2025/texmf-dist/tex/latex/base/article.cls" 1748806692 20144 b966087dda3b194755eb460d32e2ef75 ""
  "data.csv" 1790888404.90003 4 3ecfad755fa825f7a17c5526ec44e651 ""
  "main.bbl" 1790888406.07504 104 16d5715921c0dd775ad1f63b83c5f64c "bibtex main"
  "main.tex" 1790888404.90003 127 dddfe0fd01b2e6b83e66a8c5a0bbd1a0 ""
  (generated)
  "main.aux"
  "main.pdf"
"""


class ReadsDigest(unittest.TestCase):
    """warm.fls_reads, warm.fdb_sources and warm.reads_digest: what a build read beyond its fingerprint."""

    def test_the_files_read_and_not_written_split_by_the_copy_whatever_their_suffix(self):
        """INPUT lines inside the copy count by name relative to it, any suffix; a file also written (OUTPUT, the .aux)
        and a name with a NUL do not; files outside the copy (TeX Live, a sibling folder) are the outside set."""
        text = (
            "PWD /state/build/1st\n"
            "INPUT ./data.csv\nINPUT /state/build/1st/main.tex\nINPUT ../shared/defs.def\n"
            "INPUT main.aux\nOUTPUT main.aux\nOUTPUT main.pdf\n"
            "INPUT /usr/share/texlive/article.cls\nINPUT bad\x00.csv\nINPUT /state/other.csv\n"
        )
        got = warm.fls_reads(text, "/state/build/1st", ["/state/build"])
        self.assertEqual(got.inside, {"1st/data.csv", "1st/main.tex", "shared/defs.def"})
        self.assertEqual(got.outside, {"/usr/share/texlive/article.cls", "/state/other.csv"})

    def test_the_database_adds_what_bibtex_read(self):
        """.fdb_latexmk's primary sources of every rule count - refs.bib and plain.bst that only bibtex read - and its
        generated files (main.aux, main.bbl, the generated lists) do not."""
        got = warm.fdb_sources(FDB, "/state/build", ["/state/build"])
        self.assertEqual(got.inside, {"refs.bib", "data.csv", "main.tex"})
        self.assertEqual(
            got.outside,
            {
                "/usr/local/texlive/2025/texmf-dist/bibtex/bst/base/plain.bst",
                "/usr/local/texlive/2025/texmf-dist/tex/latex/base/article.cls",
            },
        )

    def test_a_changed_missing_or_moved_file_changes_the_digest(self):
        """The digest follows each name and token: a changed byte, a file gone, a file renamed, an outside file whose
        stat moved all differ."""
        base = warm.reads_digest([("a.csv", b"1" * 32)], [("/t/a.sty", b"1:2")])
        self.assertEqual(base, warm.reads_digest([("a.csv", b"1" * 32)], [("/t/a.sty", b"1:2")]))
        for other in (
            warm.reads_digest([("a.csv", b"2" * 32)], [("/t/a.sty", b"1:2")]),
            warm.reads_digest([("a.csv", None)], [("/t/a.sty", b"1:2")]),
            warm.reads_digest([("b.csv", b"1" * 32)], [("/t/a.sty", b"1:2")]),
            warm.reads_digest([("a.csv", b"1" * 32)], [("/t/a.sty", b"9:2")]),
        ):
            self.assertNotEqual(base, other)

    def test_the_cold_digest_follows_rc_files_tools_and_styles(self):
        """cold_digest changes with an rc file's bytes or its appearance, a tool's real path or stat, and a side tool's
        style file; the same inputs give the same digest."""
        rc, tools, styles = [("/p/latexmkrc", None)], [("pdflatex=/tl/2025/pdflatex", b"1:2")], [("/c/s.ist", b"a")]
        base = warm.cold_digest(rc, tools, styles)
        self.assertEqual(base, warm.cold_digest(rc, tools, styles))
        for other in (
            warm.cold_digest([("/p/latexmkrc", b"x")], tools, styles),
            warm.cold_digest(rc, [("pdflatex=/tl/2026/pdflatex", b"1:2")], styles),
            warm.cold_digest(rc, [("pdflatex=/tl/2025/pdflatex", b"3:2")], styles),
            warm.cold_digest(rc, tools, [("/c/s.ist", b"b")]),
            warm.cold_digest(rc, tools, []),
        ):
            self.assertNotEqual(base, other)

    def test_the_tools_an_rc_names_and_the_styles_a_log_names(self):
        """tool_names reads the first word of a simple quoted assignment, a later rc winning; log_styles reads the style
        file makeindex's .ilg and bibtex's .blg name."""
        self.assertEqual(
            warm.tool_names(
                ["$pdflatex = 'lualatex %O %S';\n", "$pdflatex = \"xelatex %O %S\";\n$makeindex='mendex';\n"]
            ),
            {"pdflatex": "xelatex", "bibtex": "bibtex", "biber": "biber", "makeindex": "mendex"},
        )
        self.assertEqual(warm.tool_names([]), {v: v for v in warm.TOOL_VARS})
        ilg = "This is makeindex, version 2.17\nScanning style file ./out/style.ist...done (3 attributes redefined).\n"
        blg = "This is BibTeX, Version 0.99d\nThe top-level auxiliary file: main.aux\nThe style file: plain.bst\n"
        self.assertEqual(warm.log_styles(ilg, blg), ["./out/style.ist", "plain.bst"])
        one_dot = "Scanning style file ./style.ist.done (1 attributes redefined, 0 ignored).\n"  # a short style file
        self.assertEqual(warm.log_styles(one_dot, None), ["./style.ist"])
        self.assertEqual(warm.log_styles(None, None), [])

    def test_a_stored_recipe_matches_only_itself_and_an_unknown_one_goes_cold(self):
        """recipe_matches holds for the recipe as stored with the same dpi, main, switches, digest and cold digest;
        another value of any, another format or a damaged recipe refuses, and goes_cold for all of those."""
        reads = warm.Reads(frozenset({"a.csv"}), frozenset({"/t/a.sty"}))
        made = warm.recipe(150, PurePosixPath("1st/m.tex"), ("-pdf",), reads, "d", ["/c/s.ist"], "c")
        stored = json.loads(json.dumps(made))
        self.assertEqual((warm.stored_reads(stored), warm.stored_styles(stored)), (reads, ["/c/s.ist"]))
        self.assertTrue(warm.recipe_matches(stored, 150, PurePosixPath("1st/m.tex"), ("-pdf",), "d", "c"))
        self.assertFalse(warm.goes_cold(stored, "c"))
        self.assertTrue(warm.goes_cold(stored, "other"))
        for args in (
            (100, PurePosixPath("1st/m.tex"), ("-pdf",), "d", "c"),
            (150, PurePosixPath("m.tex"), ("-pdf",), "d", "c"),
            (150, PurePosixPath("1st/m.tex"), ("-pdf", "-g"), "d", "c"),
            (150, PurePosixPath("1st/m.tex"), ("-pdf",), "e", "c"),
            (150, PurePosixPath("1st/m.tex"), ("-pdf",), "d", "x"),
        ):
            self.assertFalse(warm.recipe_matches(stored, *args))
        for bad in (
            None,
            [],
            dict(stored, format=1),
            dict(stored, inside="a.csv"),
            dict(stored, outside=[1]),
            dict(stored, styles=None),
            dict(stored, cold=3),
        ):
            self.assertIsNone(warm.stored_reads(bad))
            self.assertEqual(warm.stored_styles(bad), [])
            self.assertTrue(warm.goes_cold(bad, "c"))
            self.assertFalse(warm.recipe_matches(bad, 150, PurePosixPath("1st/m.tex"), ("-pdf",), "d", "c"))


class CopyKeeps(unittest.TestCase):
    """copy_manuscript with kept paths, with rsync and with the copytree fallback."""

    def setUp(self):
        """A source with main.tex and a committed main.pdf in 1st/, and a build copy holding the last build's
        byproducts, its own PDF and a stale chapter aux."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.src, self.dest, self.state = root / "ms", root / "state" / "build", root / "state"
        (self.src / "1st").mkdir(parents=True)
        (self.src / "1st" / "main.tex").write_text("A", encoding="utf-8")
        (self.src / "1st" / "main.pdf").write_bytes(b"COMMITTED")
        (self.dest / "1st").mkdir(parents=True)
        for name in ("main.aux", "main.fdb_latexmk", "main.fls"):
            (self.dest / "1st" / name).write_text("kept " + name, encoding="utf-8")
        (self.dest / "1st" / "main.pdf").write_bytes(b"BUILT")
        (self.dest / "1st" / "chap.aux").write_text("stale", encoding="utf-8")
        (self.dest / "1st" / "gone.tex").write_text("removed from the source", encoding="utf-8")
        self.keep = warm.kept_paths(PurePosixPath("1st"), "main", os.listdir(self.src / "1st"))

    def each_copier(self):
        """Yield once with rsync and once with the copytree fallback (rsync hidden)."""
        modes = ["rsync"] if shutil.which("rsync") else []
        modes.append("copytree")
        for mode in modes:
            with self.subTest(copier=mode):
                if mode == "copytree":
                    with mock.patch.object(build_engine.shutil, "which", return_value=None):
                        yield
                else:
                    yield

    def test_byproducts_and_the_built_pdf_survive_the_copy_and_the_committed_pdf_never_lands(self):
        """The kept files keep their bytes; the committed main.pdf does not overwrite the build's; a file the source
        no longer has and a generated file not kept are removed; the source files arrive."""
        for _ in self.each_copier():
            build_engine.copy_manuscript(self.src, self.dest, self.state, self.keep)
            out = self.dest / "1st"
            self.assertEqual((out / "main.pdf").read_bytes(), b"BUILT")
            self.assertEqual((out / "main.aux").read_text(), "kept main.aux")
            self.assertEqual((out / "main.fdb_latexmk").read_text(), "kept main.fdb_latexmk")
            self.assertEqual((out / "main.tex").read_text(), "A")
            self.assertFalse((out / "gone.tex").exists())
            self.assertFalse((out / "chap.aux").exists())
            (out / "gone.tex").write_text("again", encoding="utf-8")
            (out / "chap.aux").write_text("again", encoding="utf-8")

    def test_a_same_size_edit_in_the_same_second_reaches_the_copy(self):
        """An edit that keeps the file's size and its mtime second (a one-letter change right after the last copy)
        still reaches the copy: the copy compares content, not size and mtime."""
        for _ in self.each_copier():
            build_engine.copy_manuscript(self.src, self.dest, self.state, self.keep)
            tex = self.src / "1st" / "main.tex"
            st = (self.dest / "1st" / "main.tex").stat()
            tex.write_text("B" if tex.read_text() == "A" else "A", encoding="utf-8")
            os.utime(tex, ns=(st.st_atime_ns, st.st_mtime_ns))
            build_engine.copy_manuscript(self.src, self.dest, self.state, self.keep)
            self.assertEqual((self.dest / "1st" / "main.tex").read_text(), tex.read_text())

    def test_without_kept_paths_the_copy_mirrors_the_source_as_before(self):
        """No kept paths (a cold build): byproducts go and the committed PDF is copied, as the copy always did."""
        for _ in self.each_copier():
            build_engine.copy_manuscript(self.src, self.dest, self.state)
            out = self.dest / "1st"
            self.assertFalse((out / "main.aux").exists())
            self.assertEqual((out / "main.pdf").read_bytes(), b"COMMITTED")
            (out / "main.aux").write_text("kept main.aux", encoding="utf-8")
            (out / "main.pdf").write_bytes(b"BUILT")


class Warm(unittest.TestCase):
    """compile_tex through run_tracked with stand-ins: warm builds, the skip and its limits, force and recovery."""

    def setUp(self):
        """One document whose main.tex sits in 1st/ of its build root, and the stand-ins."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.state = root / "state"
        src = root / "ms"
        (src / "1st").mkdir(parents=True)
        main = src / "1st" / "main.tex"
        main.write_text("\\documentclass{article}\\begin{document}A\\end{document}\n", encoding="utf-8")
        self.D = WarmDoc(src=src, main=main, dir=self.state / "docs" / "ms")
        self.D.dir.mkdir(parents=True)
        self.calls = stand_ins(self, root)
        self.cfg = build.BuildConfig(state=self.state, dpi=72, timeout=10)

    def tracked(self, force: bool = False, dpi: int | None = None, **env: str):
        """One tracked build of the document (run_tracked over compile_tex), the stand-ins in the given modes."""
        cfg = self.cfg if dpi is None else build.BuildConfig(state=self.state, dpi=dpi, timeout=10)
        with mock.patch.dict(os.environ, env):
            return build_run.run_tracked(
                self.D,
                self.state,
                lambda: build_engine.compile_tex(self.D, cfg, None, force=force),
                "t0",
                build_failure_log,
            )

    def latexmk_runs(self) -> list[str]:
        """How latexmk started each time it ran: "warm" (main.aux was there) or "cold"."""
        return self.calls.read_text().split() if self.calls.exists() else []

    def page_dirs(self) -> list[str]:
        """The page folders of the document, by name."""
        return sorted(p.name for p in self.D.dir.iterdir() if build.valid_build_name(p.name))

    def test_a_second_build_finds_the_first_builds_byproducts(self):
        """latexmk of an edited manuscript starts warm: the first build's aux is still in the copy."""
        self.assertIsInstance(self.tracked(), BuildOk)
        self.D.main.write_text(self.D.main.read_text().replace("A", "B"), encoding="utf-8")
        self.assertIsInstance(self.tracked(), BuildOk)
        self.assertEqual(self.latexmk_runs(), ["cold", "warm"])

    def test_an_unchanged_rebuild_runs_nothing_and_counts_no_build(self):
        """A rebuild of the same manuscript, recipe and an ok build on screen is BuildUnchanged naming that build:
        latexmk does not run, no page folder is made, pages.cur, seq and the history's builds stay, and the build
        state is ok with unchanged true."""
        first = self.tracked()
        self.assertIsInstance(first, BuildOk)
        before = (self.page_dirs(), build.load_builds(self.D))
        again = self.tracked()
        self.assertIsInstance(again, BuildUnchanged)
        self.assertEqual((again.build, again.pages, again.src_hash), (first.build, first.pages, first.src_hash))
        self.assertEqual(self.latexmk_runs(), ["cold"])
        self.assertEqual(self.page_dirs(), before[0])
        self.assertEqual(build.cur_pages(self.D).name, first.build)
        after = build.load_builds(self.D)
        self.assertEqual((after["seq"], after["last"], list(after["by"])), (1, before[1]["last"], [first.build]))
        snap = build.state_snapshot(self.D)
        self.assertEqual((snap["state"], snap["seq"], snap["unchanged"]), ("ok", 1, True))

    def test_the_next_build_clears_the_unchanged_mark(self):
        """A build that starts after an unchanged one reports no unchanged field, running or finished."""
        self.tracked()
        self.assertIsInstance(self.tracked(), BuildUnchanged)
        self.D.main.write_text(self.D.main.read_text().replace("A", "C"), encoding="utf-8")
        self.assertIsInstance(self.tracked(), BuildOk)
        self.assertNotIn("unchanged", build.state_snapshot(self.D))

    def test_a_changed_source_a_changed_dpi_or_a_failed_last_build_builds(self):
        """Each of these makes the rebuild a real one: an edited .tex, another dpi (the recipe), and a last build
        that failed even though the source is the one on screen."""
        self.tracked()
        self.D.main.write_text(self.D.main.read_text().replace("A", "D"), encoding="utf-8")
        self.assertIsInstance(self.tracked(), BuildOk)
        self.assertIsInstance(self.tracked(dpi=100), BuildOk)
        self.assertIsInstance(self.tracked(dpi=100), BuildUnchanged)
        self.D.main.write_text(self.D.main.read_text().replace("D", "E"), encoding="utf-8")
        self.assertIsInstance(self.tracked(dpi=100, LIMN_TEST_LATEXMK="nopdf"), BuildFailed)
        self.D.main.write_text(self.D.main.read_text().replace("E", "D"), encoding="utf-8")
        self.assertIsInstance(self.tracked(dpi=100), BuildOk)

    def test_a_build_on_screen_without_a_recipe_is_rebuilt(self):
        """A page folder without recipe.json (made by an older Limn, before an upgrade) is never kept: the rebuild runs.
        A new build publishes recipe.json beside its .fls and adds no field to builds.json."""
        first = self.tracked()
        recipe = self.D.dir / first.build / "recipe.json"
        self.assertEqual(json.loads(recipe.read_text())["dpi"], 72)
        self.assertNotIn("recipe", build.load_builds(self.D)["by"][first.build])
        recipe.unlink()
        again = self.tracked()
        self.assertIsInstance(again, BuildOk)
        self.assertNotEqual(again.build, first.build)

    def test_force_rebuilds_cold_even_when_nothing_changed(self):
        """force=True skips the skip and clears the kept byproducts first: latexmk runs, and starts cold."""
        self.tracked()
        res = self.tracked(force=True)
        self.assertIsInstance(res, BuildOk)
        self.assertEqual(self.latexmk_runs(), ["cold", "cold"])

    def test_a_failed_build_clears_the_byproducts_so_the_next_starts_cold(self):
        """After a build that made no PDF the copy holds none of the main file's byproducts, and the next build
        starts cold and succeeds."""
        self.tracked()
        self.D.main.write_text(self.D.main.read_text().replace("A", "F"), encoding="utf-8")
        self.assertIsInstance(self.tracked(LIMN_TEST_LATEXMK="nopdf"), BuildFailed)
        self.assertEqual([n for n in BYPRODUCTS if (self.D.out / n).exists()], [])
        self.assertIsInstance(self.tracked(), BuildOk)
        self.assertEqual(self.latexmk_runs(), ["cold", "warm", "cold"])

    def test_an_unchanged_rebuild_moves_the_baseline_and_the_published_commit(self):
        """A touched but identical source turns the 'manuscript modified' badge on; the unchanged rebuild turns it
        off (the build's baseline moves to the copy's mtime) and records the commit now checked out."""
        first = self.tracked()
        later = self.D.main.stat().st_mtime + 30
        os.utime(self.D.main, (later, later))
        self.D.mcache[2] = 0.0  # past the 2-second src_mtime memo
        self.assertGreater(build.source_newer(self.D, self.state), 2)
        with mock.patch.object(build_engine, "_published_head", return_value="abc1234"):
            again = self.tracked()
        self.assertIsInstance(again, BuildUnchanged)
        self.assertEqual(build.source_newer(self.D, self.state), 0.0)
        self.assertEqual(build.read_head(self.D), "abc1234")
        self.assertEqual(again.head, "abc1234")
        self.assertEqual(build.load_builds(self.D)["by"][first.build]["src_mtime"], later)

    def test_an_edited_file_the_build_read_is_rebuilt_even_outside_the_fingerprint(self):
        """data.csv is no source suffix, so the fingerprint does not see it; the build's .fls lists it as read. With
        nothing changed the rebuild is skipped; once data.csv changes the rebuild runs; a file the build did not read
        changing (notes.csv) is still skipped."""
        (self.D.src / "1st" / "data.csv").write_text("1,2\n", encoding="utf-8")
        (self.D.src / "1st" / "notes.csv").write_text("x\n", encoding="utf-8")
        reads = {"LIMN_TEST_INPUTS": "INPUT ./data.csv\n"}
        first = self.tracked(**reads)
        self.assertIsInstance(first, BuildOk)
        self.assertIsInstance(self.tracked(**reads), BuildUnchanged)
        (self.D.src / "1st" / "notes.csv").write_text("y\n", encoding="utf-8")
        self.assertIsInstance(self.tracked(**reads), BuildUnchanged)
        (self.D.src / "1st" / "data.csv").write_text("1,3\n", encoding="utf-8")
        again = self.tracked(**reads)
        self.assertIsInstance(again, BuildOk)
        self.assertNotEqual(again.build, first.build)

    def test_an_edited_latexmkrc_is_rebuilt(self):
        """A latexmkrc beside the main file and a .latexmkrc in the build root are read by latexmk: editing either makes
        the rebuild run; leaving both alone skips it."""
        rc, root_rc = self.D.src / "1st" / "latexmkrc", self.D.src / ".latexmkrc"
        rc.write_text("$pdf_mode = 1;\n", encoding="utf-8")
        self.assertIsInstance(self.tracked(), BuildOk)
        self.assertIsInstance(self.tracked(), BuildUnchanged)
        rc.write_text("$pdf_mode = 1; # edited\n", encoding="utf-8")
        self.assertIsInstance(self.tracked(), BuildOk)
        self.assertEqual(self.latexmk_runs()[-1], "cold")  # latexmk does not track rc files: the copy goes cold
        self.assertIsInstance(self.tracked(), BuildUnchanged)
        root_rc.write_text("$bibtex_use = 2;\n", encoding="utf-8")
        self.assertIsInstance(self.tracked(), BuildOk)
        self.assertEqual(self.latexmk_runs()[-1], "cold")
        self.assertIsInstance(self.tracked(), BuildUnchanged)
        self.D.main.write_text(self.D.main.read_text().replace("A", "G"), encoding="utf-8")
        self.assertIsInstance(self.tracked(), BuildOk)
        self.assertEqual(self.latexmk_runs()[-1], "warm")  # a source edit alone stays warm

    def test_a_new_pdflatex_on_path_goes_cold(self):
        """Another pdflatex first on PATH (a new TeX Live year beside the old one) changes the toolchain's real path:
        the next rebuild is not skipped, and latexmk starts cold."""
        self.assertIsInstance(self.tracked(), BuildOk)
        self.assertIsInstance(self.tracked(), BuildUnchanged)
        year = Path(self.tmp.name) / "texlive-next"
        year.mkdir()
        (year / "pdflatex").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (year / "pdflatex").chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": str(year) + os.pathsep + os.environ["PATH"]}):
            self.assertEqual(shutil.which("pdflatex"), str(year / "pdflatex"))
            res = self.tracked()
        self.assertIsInstance(res, BuildOk)
        self.assertEqual(self.latexmk_runs()[-1], "cold")

    def test_a_name_longer_than_the_file_system_takes_does_not_crash_the_build(self):
        """A recorder file that names a 260-character file (a \\bibliography of a long name) is a name no file system
        takes: the build reads it as a file that is not there and finishes ok, and the next rebuild is skipped."""
        long = {"LIMN_TEST_INPUTS": "INPUT ./" + "b" * 260 + ".bib\n"}
        first = self.tracked(**long)
        self.assertIsInstance(first, BuildOk)
        self.assertIsInstance(self.tracked(**long), BuildUnchanged)

    def test_a_build_that_dies_clears_the_byproducts(self):
        """A build that raises (here its render) clears the kept byproducts like any build that does not end ok, so the
        next one starts cold."""
        self.assertIsInstance(self.tracked(), BuildOk)
        self.D.main.write_text(self.D.main.read_text().replace("A", "H"), encoding="utf-8")
        with mock.patch.object(build_engine, "render_pages", side_effect=RuntimeError("render died")):
            died = self.tracked()
        self.assertEqual((type(died).__name__, died.kind), ("BuildAborted", "crashed"))
        self.assertEqual([n for n in BYPRODUCTS if (self.D.out / n).exists()], [])
        self.assertIsInstance(self.tracked(), BuildOk)
        self.assertEqual(self.latexmk_runs()[-1], "cold")

    def test_a_build_on_screen_without_a_recorder_file_is_rebuilt(self):
        """When the build on screen kept no .fls (latexmk's recorder off), what it read is unknown: the rebuild runs."""
        first = self.tracked(LIMN_TEST_RECORDER="off")
        self.assertIsInstance(first, BuildOk)
        self.assertFalse((self.D.dir / first.build / "main.fls").exists())
        self.assertFalse((self.D.dir / first.build / "recipe.json").exists())
        again = self.tracked(LIMN_TEST_RECORDER="off")
        self.assertIsInstance(again, BuildOk)
        self.assertNotEqual(again.build, first.build)

    def test_a_published_build_carries_its_recorder_file(self):
        """Every new page folder holds the main file's .fls next to its PDF, written by this build."""
        res = self.tracked()
        self.assertTrue((self.D.dir / res.build / "main.fls").is_file())


class Answers(unittest.TestCase):
    """POST /api/rebuild's body for an unchanged rebuild."""

    def test_an_unchanged_rebuild_answers_ok_with_unchanged_true_and_the_build_on_screen(self):
        """The body keeps the agent contract's key order of an ok build and adds unchanged: true last; without ?log=1
        the (empty) log is dropped as for any ok build."""
        res = BuildUnchanged(0.3, None, 12.0, "h", "abc1234", "pages-20261001120000", 25)
        body = finished_build_body(res)
        self.assertEqual(
            list(body),
            [
                "ok",
                "state",
                "errors",
                "log",
                "elapsed_s",
                "src_mtime",
                "src_hash",
                "head",
                "build",
                "pages",
                "unchanged",
            ],
        )
        self.assertEqual((body["ok"], body["state"], body["unchanged"], body["log"]), (True, "ok", True, ""))
        answer, code = rebuild_answer(res, full=False)
        self.assertEqual((code, "log" in answer, answer["build"]), (200, False, "pages-20261001120000"))


class RebuildRoute(Base):
    """POST /api/rebuild with and without ?force=1, through the handler."""

    def setUp(self):
        """The server copy's single document and the stand-ins on PATH."""
        super().setUp()
        self.calls = stand_ins(self, Path(self.tmp.name))

    def post(self, path: str) -> dict:
        """The JSON body of one POST through the handler."""
        code, _, body = split_resp(self.talk(req("POST", path)))
        self.assertEqual(code, 200, body)
        return json.loads(body)

    def test_force_one_rebuilds_what_a_plain_rebuild_skips(self):
        """A second plain rebuild answers unchanged: true with the same build; ?force=1 builds a new one."""
        first = self.post("/api/rebuild")
        self.assertNotIn("unchanged", first)
        again = self.post("/api/rebuild")
        self.assertEqual((again["state"], again["unchanged"], again["build"]), ("ok", True, first["build"]))
        forced = self.post("/api/rebuild?force=1")
        self.assertNotIn("unchanged", forced)
        self.assertNotEqual(forced["build"], first["build"])
        self.assertEqual(self.calls.read_text().split(), ["cold", "cold"])


TEX_DOC = r"""\documentclass{article}
\begin{document}
\section{One}\label{sec:a}
See section~\ref{sec:a}. WORD.
\end{document}
"""


class WarmWithLatexmk(unittest.TestCase):
    """The real latexmk on a small manuscript: one pdflatex run per edit, labels that follow a rename, a committed PDF
    that never stands in for the build's, a failure the next build recovers from, and the cases where what latexmk left
    in the copy must not stand for a build (a recorder switched off, a shipped .fls, an $out_dir)."""

    def setUp(self):
        """A manuscript with main.tex in 1st/ (and a committed main.pdf there), and its document."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.state = root / "state"
        src = root / "ms"
        (src / "1st").mkdir(parents=True)
        self.main = src / "1st" / "main.tex"
        self.main.write_text(TEX_DOC, encoding="utf-8")
        (src / "1st" / "main.pdf").write_bytes(b"%PDF-1.4 COMMITTED, not the build's\n")
        self.D = WarmDoc(src=src, main=self.main, dir=self.state / "docs" / "ms")
        self.D.dir.mkdir(parents=True)

    def tracked(self, dpi: int = 50):
        """One tracked real build at dpi."""
        cfg = build.BuildConfig(state=self.state, dpi=dpi, timeout=120)
        return build_run.run_tracked(
            self.D, self.state, lambda: build_engine.compile_tex(self.D, cfg, None), "t0", build_failure_log
        )

    def text_of(self, res) -> str:
        """The text pdftotext reads from the PDF published with build outcome res."""
        pdf = self.D.dir / res.build / "main.pdf"
        return subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True, check=True).stdout

    def pdflatex_runs(self) -> int:
        """How many times the last latexmk ran pdflatex (its build.log)."""
        return len(re.findall(r"Run number \d+ of rule 'pdflatex'", (self.D.dir / "build.log").read_text()))

    def edit(self, old: str, new: str) -> None:
        """Replace old with new in main.tex."""
        self.main.write_text(self.main.read_text().replace(old, new), encoding="utf-8")

    @needs_tex("latexmk", "pdftoppm", "pdfinfo")
    def test_a_one_word_edit_runs_pdflatex_once_and_publishes_a_fresh_recorder_file(self):
        """The cold first build runs pdflatex more than once; a one-word edit then runs it once, and the new page
        folder holds the .fls that run wrote."""
        self.assertIsInstance(self.tracked(), BuildOk)
        self.assertGreater(self.pdflatex_runs(), 1)
        self.edit("WORD", "TERM")
        started = time.time()
        res = self.tracked()
        self.assertIsInstance(res, BuildOk)
        self.assertEqual(self.pdflatex_runs(), 1)
        fls = self.D.dir / res.build / "main.fls"
        self.assertEqual(fls.read_bytes(), (self.D.out / "main.fls").read_bytes())
        self.assertGreaterEqual(fls.stat().st_mtime, started - 1)

    @needs_tex("latexmk", "pdftoppm", "pdfinfo")
    def test_a_renamed_label_resolves_in_the_warm_build(self):
        """Renaming the label and its reference leaves no undefined reference and no stale label in the aux."""
        self.assertIsInstance(self.tracked(), BuildOk)
        self.edit("sec:a", "sec:b")
        res = self.tracked()
        self.assertIsInstance(res, BuildOk)
        aux = (self.D.dir / res.build / "main.aux").read_text()
        self.assertIn("\\newlabel{sec:b}", aux)
        self.assertNotIn("sec:a", aux)
        log = (self.D.out / "main.log").read_text()
        self.assertNotIn("undefined references", log)
        self.assertNotIn("Reference `sec", log)

    @needs_tex("latexmk", "pdftoppm", "pdfinfo")
    def test_the_committed_pdf_never_stands_in_for_the_builds(self):
        """With a committed main.pdf beside main.tex, a rebuild that latexmk finds up to date (only the dpi changed)
        publishes the PDF the first build made, with its aux and .fls - never the committed file."""
        first = self.tracked()
        self.assertIsInstance(first, BuildOk)
        built = (self.D.dir / first.build / "main.pdf").read_bytes()
        self.assertNotIn(b"COMMITTED", built)
        res = self.tracked(dpi=60)
        self.assertIsInstance(res, BuildOk)
        self.assertNotEqual(res.build, first.build)
        self.assertIn("are up-to-date", (self.D.dir / "build.log").read_text())
        self.assertEqual((self.D.dir / res.build / "main.pdf").read_bytes(), built)
        self.assertTrue((self.D.dir / res.build / "main.aux").is_file())
        self.assertTrue((self.D.dir / res.build / "main.fls").is_file())

    @needs_tex("latexmk", "pdftoppm", "pdfinfo")
    def test_a_build_after_a_failed_one_is_right(self):
        """A manuscript that cannot compile fails and clears the byproducts; fixed, it builds ok with its label."""
        self.assertIsInstance(self.tracked(), BuildOk)
        self.edit("\\end{document}", "\\input{missing-file}\n\\end{document}")
        self.assertIsInstance(self.tracked(), BuildFailed)
        self.assertFalse((self.D.out / "main.aux").exists())
        self.edit("\\input{missing-file}\n", "")
        self.edit("sec:a", "sec:c")
        res = self.tracked()
        self.assertIsInstance(res, BuildOk)
        self.assertIn("\\newlabel{sec:c}", (self.D.dir / res.build / "main.aux").read_text())

    @needs_tex("latexmk", "pdftoppm", "pdfinfo")
    def test_an_edited_csv_the_manuscript_inputs_is_rebuilt(self):
        """A .csv the manuscript reads with \\input is outside the fingerprint but in the build's .fls: an unchanged
        rebuild is skipped, and after editing the .csv the rebuild runs and its PDF differs."""
        (self.main.parent / "data.csv").write_text("12,34\n", encoding="utf-8")
        self.edit("WORD.", "WORD. \\input{data.csv}")
        first = self.tracked()
        self.assertIsInstance(first, BuildOk)
        self.assertIsInstance(self.tracked(), BuildUnchanged)
        (self.main.parent / "data.csv").write_text("56,78\n", encoding="utf-8")
        res = self.tracked()
        self.assertIsInstance(res, BuildOk)
        self.assertNotEqual(
            (self.D.dir / res.build / "main.pdf").read_bytes(), (self.D.dir / first.build / "main.pdf").read_bytes()
        )

    @needs_tex("latexmk", "pdftoppm", "pdfinfo", "pdftotext")
    def test_a_recorder_switched_off_never_publishes_the_old_recorder_file(self):
        """(A) The first build reads data1.csv with the recorder on. A latexmkrc then turns the recorder off and the
        .tex switches to data2.csv: that build publishes no .fls (the copy's is the old one, naming data1.csv) and no
        recipe, so editing data2.csv afterwards rebuilds and the PDF shows the edit."""
        folder = self.main.parent
        (folder / "data1.csv").write_text("11,11\n", encoding="utf-8")
        (folder / "data2.csv").write_text("22,22\n", encoding="utf-8")
        self.edit("WORD.", "WORD. \\input{data1.csv}")
        first = self.tracked()
        self.assertTrue((self.D.dir / first.build / "main.fls").is_file())
        (folder / "latexmkrc").write_text("$recorder = 0;\n", encoding="utf-8")
        self.edit("data1.csv", "data2.csv")
        second = self.tracked()
        self.assertIsInstance(second, BuildOk)
        self.assertFalse((self.D.dir / second.build / "main.fls").exists())
        self.assertFalse((self.D.dir / second.build / "recipe.json").exists())
        (folder / "data2.csv").write_text("99,99\n", encoding="utf-8")
        third = self.tracked()
        self.assertIsInstance(third, BuildOk)
        self.assertIn("99,99", self.text_of(third))

    @needs_tex("latexmk", "pdftoppm", "pdfinfo", "pdftotext")
    def test_a_shipped_recorder_file_is_never_published(self):
        """(B) The manuscript ships an old main.fls (naming data1.csv) and turns the recorder off. Neither the cold build
        that copies it nor, once it is removed from the manuscript, the warm build that finds it left in the copy
        publishes it, and an edit of data2.csv rebuilds."""
        folder = self.main.parent
        (folder / "data1.csv").write_text("11,11\n", encoding="utf-8")
        (folder / "data2.csv").write_text("22,22\n", encoding="utf-8")
        (folder / "latexmkrc").write_text("$recorder = 0;\n", encoding="utf-8")
        (folder / "main.fls").write_text("PWD /elsewhere\nINPUT ./data1.csv\nINPUT ./main.tex\n", encoding="utf-8")
        self.edit("WORD.", "WORD. \\input{data2.csv}")
        first = self.tracked()
        self.assertIsInstance(first, BuildOk)
        self.assertFalse((self.D.dir / first.build / "main.fls").exists())
        (folder / "main.fls").unlink()
        second = self.tracked()
        self.assertIsInstance(second, BuildOk)
        self.assertFalse((self.D.dir / second.build / "main.fls").exists())
        (folder / "data2.csv").write_text("77,77\n", encoding="utf-8")
        third = self.tracked()
        self.assertIsInstance(third, BuildOk)
        self.assertIn("77,77", self.text_of(third))

    @needs_tex("latexmk", "pdftoppm", "pdfinfo")
    def test_an_out_dir_in_latexmkrc_fails_instead_of_showing_the_old_pdf(self):
        """(C) A latexmkrc that sets $out_dir sends latexmk's PDF elsewhere: an edit then fails as no_pdf and the
        screen keeps the first build, never a BuildOk that publishes the PDF left in the copy."""
        first = self.tracked()
        self.assertIsInstance(first, BuildOk)
        (self.main.parent / "latexmkrc").write_text("$out_dir = 'build';\n", encoding="utf-8")
        self.edit("WORD", "OUTDIRWORD")
        res = self.tracked()
        self.assertIsInstance(res, BuildFailed)
        self.assertEqual(res.kind, "no_pdf")
        self.assertEqual(build.cur_pages(self.D).name, first.build)

    @needs_tex("latexmk", "pdftoppm", "pdfinfo")
    def test_the_output_of_a_run_that_compiled_does_not_vouch(self):
        """latexmk's output after a run that compiled ends with its up-to-date line too; with the PDF that run wrote,
        vouched refuses. The output of a run that compiled nothing (only the dpi changed), with the PDF untouched,
        vouches."""
        self.assertIsInstance(self.tracked(), BuildOk)
        pdf = self.D.out / "main.pdf"
        before = build_engine._signature(pdf)
        self.edit("WORD", "TERM")
        self.assertIsInstance(self.tracked(), BuildOk)
        compiled, after = (self.D.dir / "build.log").read_text(), build_engine._signature(pdf)
        self.assertIn("Run number 1 of rule 'pdflatex'", compiled)
        self.assertEqual(warm.up_to_date_target(compiled), "main.pdf")
        self.assertFalse(warm.vouched(compiled, "main", True, 0, False, before, after))
        self.assertIsInstance(self.tracked(dpi=60), BuildOk)
        idle = (self.D.dir / "build.log").read_text()
        self.assertNotIn("Run number", idle)
        self.assertTrue(warm.vouched(idle, "main", True, 0, False, after, build_engine._signature(pdf)))

    @needs_tex("latexmk", "pdftoppm", "pdfinfo", "pdftotext")
    def test_a_package_outside_the_tree_on_texinputs_rebuilds_when_it_changes(self):
        """A .sty found through TEXINPUTS outside the manuscript is compared by its stat: unchanged, the rebuild is
        skipped; rewritten (as a TeX update would), the rebuild runs and the PDF shows the new package."""
        texmf = Path(self.tmp.name) / "texmf"
        texmf.mkdir()
        sty = texmf / "limnpkg.sty"
        sty.write_text("\\newcommand{\\limnword}{ALPHA}\n", encoding="utf-8")
        self.edit("\\begin{document}", "\\usepackage{limnpkg}\n\\begin{document}")
        self.edit("WORD.", "WORD. \\limnword")
        with mock.patch.dict(os.environ, {"TEXINPUTS": str(texmf) + os.pathsep}):
            first = self.tracked()
            self.assertIsInstance(first, BuildOk)
            self.assertIsInstance(self.tracked(), BuildUnchanged)
            sty.write_text("\\newcommand{\\limnword}{OMEGA}\n", encoding="utf-8")
            res = self.tracked()
        self.assertIsInstance(res, BuildOk)
        self.assertIn("OMEGA", self.text_of(res))

    @needs_tex("latexmk", "pdftoppm", "pdfinfo", "pdftotext", "bibtex")
    def test_a_bib_file_only_bibtex_reads_rebuilds_when_it_changes(self):
        """A .bib under out/ is outside the fingerprint and absent from the .fls - only bibtex reads it. The build's
        .fdb_latexmk lists it, so an unchanged rebuild is skipped and an edited .bib rebuilds with the new entry."""
        out = self.main.parent / "out"
        out.mkdir()
        bib = out / "refs.bib"
        bib.write_text("@article{k,title={FIRSTTITLE},author={A},journal={J},year={2020}}\n", encoding="utf-8")
        self.edit("WORD.", "WORD. \\cite{k}\\bibliographystyle{plain}\\bibliography{out/refs}")
        first = self.tracked()
        self.assertIsInstance(first, BuildOk)
        self.assertIsInstance(self.tracked(), BuildUnchanged)
        bib.write_text(bib.read_text().replace("FIRSTTITLE", "SECONDTITLE"), encoding="utf-8")
        res = self.tracked()
        self.assertIsInstance(res, BuildOk)
        self.assertIn("secondtitle", self.text_of(res).lower())  # the plain style sets titles in sentence case

    def producer_of(self, res) -> str:
        """The Producer pdfinfo reads from the PDF published with build outcome res."""
        info = subprocess.run(
            ["pdfinfo", str(self.D.dir / res.build / "main.pdf")], capture_output=True, text=True, check=True
        ).stdout
        return next((ln.split(":", 1)[1].strip() for ln in info.splitlines() if ln.startswith("Producer:")), "")

    @needs_tex("latexmk", "pdftoppm", "pdfinfo", "xelatex")
    def test_an_rc_that_switches_the_engine_goes_cold_and_builds_with_it(self):
        """(I1) A latexmkrc that appears with `$pdflatex = 'xelatex %O %S'` is nothing latexmk tracks: the build goes
        cold, so xelatex makes the published PDF (its Producer is xdvipdfmx), not the pdfTeX PDF left in the copy."""
        first = self.tracked()
        self.assertIsInstance(first, BuildOk)
        self.assertIn("pdfTeX", self.producer_of(first))
        (self.main.parent / "latexmkrc").write_text("$pdflatex = 'xelatex %O %S';\n", encoding="utf-8")
        res = self.tracked()
        self.assertIsInstance(res, BuildOk)
        self.assertGreater(self.pdflatex_runs(), 0)
        self.assertIn("xdvipdfmx", self.producer_of(res))

    @needs_tex("latexmk", "pdftoppm", "pdfinfo", "pdftotext", "makeindex")
    def test_an_edited_makeindex_style_goes_cold_and_shows_the_new_index(self):
        """(I2) makeindex -s style.ist, set in the latexmkrc, reads a style latexmk does not track: an unchanged rebuild
        is skipped, and once style.ist changes the build goes cold and the index shows the new preamble."""
        folder = self.main.parent
        ist = folder / "style.ist"
        ist.write_text('preamble "\\\\begin{theindex}\\nIDXONE\\n"\n', encoding="utf-8")
        (folder / "latexmkrc").write_text("$makeindex = 'makeindex -s style.ist %O -o %D %S';\n", encoding="utf-8")
        self.edit("\\begin{document}", "\\usepackage{makeidx}\n\\makeindex\n\\begin{document}")
        self.edit("WORD.", "WORD\\index{alpha}\\index{beta}.\n\\printindex")
        first = self.tracked()
        self.assertIsInstance(first, BuildOk)
        self.assertIn("IDXONE", self.text_of(first))
        self.assertIsInstance(self.tracked(), BuildUnchanged)
        ist.write_text(ist.read_text().replace("IDXONE", "IDXTWO"), encoding="utf-8")
        res = self.tracked()
        self.assertIsInstance(res, BuildOk)
        self.assertIn("IDXTWO", self.text_of(res))

    @needs_tex("latexmk", "pdftoppm", "pdfinfo")
    def test_an_unchanged_rebuild_with_latexmk_runs_nothing(self):
        """The second build of the same manuscript is BuildUnchanged and never starts latexmk."""
        self.assertIsInstance(self.tracked(), BuildOk)
        with mock.patch.object(build_engine, "run_logged", side_effect=AssertionError("latexmk ran")):
            self.assertIsInstance(self.tracked(), BuildUnchanged)


if __name__ == "__main__":
    unittest.main()

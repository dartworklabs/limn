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
# the PDF (the .tex), SyncTeX, log, aux, fls and fdb_latexmk; LIMN_TEST_LATEXMK=nopdf writes nothing and fails.
FAKE_LATEXMK = """#!/bin/sh
for a; do main=$a; done
stem=${main%.tex}
if [ -f "$stem.aux" ]; then echo warm >> "$LIMN_TEST_CALLS"; else echo cold >> "$LIMN_TEST_CALLS"; fi
[ "$LIMN_TEST_LATEXMK" = nopdf ] && exit 12
cp "$main" "$stem.pdf"
printf 'synctex' > "$stem.synctex.gz"
: > "$stem.log"
echo 'relax' > "$stem.aux"
printf 'PWD %s\\nINPUT %s\\n' "$PWD" "$main" > "$stem.fls"
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

    def test_latexmks_up_to_date_line_is_recognised_only_as_its_own_line(self):
        """'All targets (...) are up-to-date' on a Latexmk: line is up to date; a run that compiled is not."""
        self.assertTrue(warm.up_to_date("Rc files read:\nLatexmk: All targets (main.pdf) are up-to-date\n"))
        self.assertFalse(warm.up_to_date("Latexmk: Run number 1 of rule 'pdflatex'\n"))
        self.assertFalse(warm.up_to_date("% All targets (main.pdf) are up-to-date in a comment\n"))


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
        """A history entry made before the recipe existed (an older Limn) never matches: the rebuild runs."""
        first = self.tracked()
        h = json.loads((self.D.dir / "builds.json").read_text())
        for ent in h["builds"]:
            ent.pop("recipe")
        (self.D.dir / "builds.json").write_text(json.dumps(h))
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
    that never stands in for the build's, and a failure the next build recovers from."""

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
    def test_an_unchanged_rebuild_with_latexmk_runs_nothing(self):
        """The second build of the same manuscript is BuildUnchanged and never starts latexmk."""
        self.assertIsInstance(self.tracked(), BuildOk)
        with mock.patch.object(build_engine, "run_logged", side_effect=AssertionError("latexmk ran")):
            self.assertIsInstance(self.tracked(), BuildUnchanged)


if __name__ == "__main__":
    unittest.main()

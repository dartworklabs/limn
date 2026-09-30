"""limn.builds.artifacts - the manuscript build, driven by the document and settings it is given (coding rule R5).

The server-level build behaviour is pinned through server.py: the tracked build and the legacy page folder at the end
of this file (AsyncBuild, Legacy), build history in test_locate.py (Estimate), the "manuscript modified" badge in
test_meta.py (LightMeta), --git-pull in test_gitsync.py and the copy step in test_build_copy.py. The classes above
call the module directly, with no server, no run arguments and no "current document": it must not read them, and two
documents must be able to build at the same time, each into its own folders. latexmk and pdftoppm are small fakes on PATH, so no TeX installation is needed.

Run: uv run pytest -q src/limn/builds/tests/test_build.py
"""

import ast
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from unittest import mock

from limn.builds import (
    BuildView,
    artifacts as build,
    artifacts as limn_build,
    assemble_builds,
    engine as build_engine,
    figure_map as figmap,
    run as build_run,
)
from limn.builds.answer import (
    BUILD_FAILURES,
    build_failure_log,
    finished_build_body,
    rebuild_answer,
    rebuild_started_answer,
)
from limn.builds.artifacts import (
    BuildAborted,
    BuildBusy,
    BuildFailed,
    BuildOk,
    BuildOkWithErrors,
    BuildStarted,
    CopyFailed,
    PagesNotRendered,
    ViewOnlyNoRebuild,
)
from limn.documents import reads as limn_meta
from limn.platform import files
from limn.runtime.documents import Doc, RunPaths
from limn.web.errors import HTTPError

from helpers import MINI_PDF, Base, blank_png, figure_map, map_bytes, needs_tex, ps, req

BUILD_PY = Path(build.__file__)
RUN_PY = Path(build_run.__file__)
ENGINE_PY = Path(build_engine.__file__)
FILES_PY = Path(files.__file__)
SERVER_GLOBALS = {"C", "cur_doc", "using_doc", "DOCS", "LEGACY_DOC", "BUILD_STATE", "BUILD_LOCK"}

# latexmk stand-in: marks its document as started, waits until the other document's latexmk has started too
# (so the two compiles provably overlap), then writes the PDF (the .tex content, so each document's PDF differs),
# the SyncTeX file and an empty log. If the other build never shows up, it exits without a PDF - the build fails.
FAKE_LATEXMK = """#!/bin/sh
for a; do main=$a; done
stem=${main%.tex}
touch "$LIMN_TEST_RENDEZVOUS/$stem"
i=0
while [ "$(ls "$LIMN_TEST_RENDEZVOUS" | wc -l)" -lt 2 ]; do
  i=$((i + 1))
  [ "$i" -gt 200 ] && exit 1
  sleep 0.05
done
cp "$main" "$stem.pdf"
printf 'synctex' > "$stem.synctex.gz"
: > "$stem.log"
"""

# pdftoppm stand-in (pdftoppm -r DPI -png PDF PREFIX): one "page" whose bytes are the PDF's.
FAKE_PDFTOPPM = """#!/bin/sh
cp "$4" "$5-1.png"
"""


@dataclass
class PlainDoc:
    """A document as the build sees it (the BuildDoc protocol), with every path given - nothing global. LaTeX by
    default; a view-only PDF sets builds_from_source=False and watches_files=True, as limn.runtime.documents.Doc answers for
    kind "pdf"."""

    src: Path
    main: Path
    dir: Path
    lock: threading.Lock = field(default_factory=threading.Lock)
    bstate: dict = field(default_factory=lambda: {"state": "idle", "seq": 0})
    bstate_lock: threading.Lock = field(default_factory=threading.Lock)
    builds_lock: threading.Lock = field(default_factory=threading.Lock)
    mcache: list = field(default_factory=lambda: [None, 0.0, 0.0])
    mcache_lock: threading.Lock = field(default_factory=threading.Lock)
    builds_from_source: bool = True
    watches_files: bool = False

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


class NoServerState(unittest.TestCase):
    """The build module must not reach the server's run arguments or a "current document" (coding rule R5)."""

    def test_reads_no_server_global(self):
        """No name the server keeps as hidden state (C, cur_doc(), the document list, the legacy lock/state) appears."""
        for path in (BUILD_PY, RUN_PY, ENGINE_PY, FILES_PY):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            self.assertEqual(names & SERVER_GLOBALS, set(), path.name)

    def test_never_imports_the_server(self):
        """The server is the composition root; the build depends on nothing above it."""
        for path in (BUILD_PY, RUN_PY, ENGINE_PY, FILES_PY):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            modules |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
            self.assertFalse({m for m in modules if m == "limn.server" or m.startswith("server")}, path.name)

    def test_source_has_no_config_or_current_document_reference(self):
        """The plain-text proof of rule R5 (docs/handbook/code-style-roadmap.md §R5): no `C.` and no `cur_doc(`."""
        for path in (BUILD_PY, RUN_PY, ENGINE_PY):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("C.", source, path.name)
            self.assertNotIn("cur_doc(", source, path.name)

    def test_importing_build_view_does_not_load_http_adapters(self):
        """The cross-capability read contract must not initialize route or HTTP modules."""
        code = (
            "import sys; from limn.builds import BuildView; BuildView(); "
            "print(sorted(n for n in sys.modules if n in {'limn.builds.http', 'limn.builds.routes'}))"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "[]"), result.stderr)

    def test_assembler_returns_the_public_build_subsystem(self):
        """Composition receives reads, commands, routes, and the startup operation as one subsystem."""
        subsystem = assemble_builds(lambda: None, lambda: {}, lambda: [], lambda: "now")

        self.assertIsInstance(subsystem.view, BuildView)
        self.assertIs(subsystem.startup.__self__, subsystem.commands)
        self.assertEqual(subsystem.routes.post_documents[0].path, "/api/rebuild")


class DocumentMemoOwnership(unittest.TestCase):
    """A document owns its source-mtime memo and lock even when seeded with a caller's list."""

    def test_seeded_memo_is_not_shared_between_documents(self):
        """Changing one document's injected memo cannot change another document or the caller's seed."""
        paths = RunPaths(Path("manuscript"), Path("manuscript/main.tex"), Path("state"))
        seed = ["manuscript", 1.0, 2.0]
        a = Doc("a", "A", mcache=seed, paths=paths)
        b = Doc("b", "B", mcache=seed, paths=paths)
        a.mcache[1] = 3.0
        self.assertEqual((b.mcache, seed), (["manuscript", 1.0, 2.0], ["manuscript", 1.0, 2.0]))
        self.assertIsNot(a.mcache_lock, b.mcache_lock)


class LatexErrors(unittest.TestCase):
    """latex_errors turns a TeX log into the error list the viewer's error panel shows."""

    def test_error_line_and_its_line_number(self):
        """Each '! ' line is an error; the first following 'l.<n>' is its line."""
        log = "noise\n! Undefined control sequence.\nl.12 \\foo\n! Missing $ inserted.\nnothing here"
        self.assertEqual(
            build_engine.latex_errors(log),
            [{"line": 12, "msg": "Undefined control sequence."}, {"line": None, "msg": "Missing $ inserted."}],
        )

    def test_at_most_five_errors(self):
        """A runaway log is cut to five errors."""
        self.assertEqual(len(build_engine.latex_errors("! e\n" * 9)), 5)


class TwoDocumentsAtOnce(unittest.TestCase):
    """Two documents build concurrently from their own arguments and never touch each other's folders."""

    def setUp(self):
        """Two manuscripts in one repository, fake latexmk/pdftoppm on PATH, and a rendezvous folder for the fakes."""
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.state = root / "state"
        repo = root / "repo"
        (repo / "a").mkdir(parents=True)
        (repo / "b").mkdir()
        self.docs = {}
        for key in ("a", "b"):
            main = repo / key / (key + ".tex")
            main.write_text(
                "\\documentclass{article}\\begin{document}%s\\end{document}\n" % key.upper(), encoding="utf-8"
            )
            self.docs[key] = PlainDoc(src=repo / key, main=main, dir=self.state / "docs" / key)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for name, text in (("latexmk", FAKE_LATEXMK), ("pdftoppm", FAKE_PDFTOPPM)):
            (bin_dir / name).write_text(text, encoding="utf-8")
            (bin_dir / name).chmod(0o755)
        (root / "rendezvous").mkdir()
        env = mock.patch.dict(
            os.environ,
            {
                "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
                "LIMN_TEST_RENDEZVOUS": str(root / "rendezvous"),
            },
        )
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.tmp.cleanup)

    def start(self, D: PlainDoc, cfg: build.BuildConfig) -> BuildStarted | BuildBusy:
        """Start D's tracked LaTeX build on a background thread, the way POST /api/rebuild?async=1 does."""

        def tracked():
            """The tracked build of exactly D - no thread-local document involved."""
            return build_run.run_tracked(
                D, cfg.state, lambda: build_engine.compile_tex(D, cfg, None), "2026-09-26 10:00:00", build_failure_log
            )

        return build_run.build_in_background(D, tracked, "2026-09-26 10:00:00", build_failure_log)

    def test_failed_thread_start_releases_lock_and_finishes_build(self):
        """A thread that cannot start leaves a failed build and releases the document for another attempt."""
        D = self.docs["a"]
        cfg = build.BuildConfig(state=self.state, dpi=150, timeout=30)
        D.dir.mkdir(parents=True)
        with (
            mock.patch.object(build_run.threading.Thread, "start", side_effect=RuntimeError("can't start")),
            self.assertRaisesRegex(RuntimeError, "can't start"),
        ):
            self.start(D, cfg)
        self.assertFalse(D.lock.locked())
        state = build.state_snapshot(D)
        self.assertEqual((state["state"], state["seq"]), ("fail", 1))
        self.assertEqual(build.load_builds(D)["last"]["state"], "fail")

    def test_failed_running_state_update_releases_lock(self):
        """A partial running-state update cannot leave the document busy or apparently building."""
        D = self.docs["a"]
        cfg = build.BuildConfig(state=self.state, dpi=150, timeout=30)

        def fail_after_update(doc, **kw):
            """Simulate a state update that writes running before its caller sees failure."""
            with doc.bstate_lock:
                doc.bstate.update(kw)
            raise OSError("state update failed")

        with (
            mock.patch.object(build, "state_update", side_effect=fail_after_update),
            self.assertRaisesRegex(OSError, "state update failed"),
        ):
            self.start(D, cfg)
        self.assertFalse(D.lock.locked())
        self.assertEqual(build.state_snapshot(D)["state"], "fail")

    def test_failed_start_recording_releases_lock_and_marks_failure(self):
        """A failed history write during thread-start recovery still clears running and releases the lock."""
        D = self.docs["a"]
        cfg = build.BuildConfig(state=self.state, dpi=150, timeout=30)
        with (
            mock.patch.object(build_run.threading.Thread, "start", side_effect=RuntimeError("can't start")),
            mock.patch.object(build_run, "finish_build", side_effect=OSError("history failed")),
            self.assertRaisesRegex(OSError, "history failed"),
        ):
            self.start(D, cfg)
        self.assertFalse(D.lock.locked())
        self.assertEqual(build.state_snapshot(D)["state"], "fail")

    def test_failed_worker_recording_clears_running_and_releases_lock(self):
        """A worker error followed by failed history recording still ends its build and reports the recording error."""
        D = self.docs["a"]
        worker_done = threading.Event()
        errors = []

        def capture_error(args):
            """Record the background thread's uncaught error without hiding it from the test."""
            errors.append(args.exc_value)
            worker_done.set()

        with (
            mock.patch.object(build_run, "finish_build", side_effect=OSError("history failed")),
            mock.patch.object(threading, "excepthook", side_effect=capture_error),
        ):
            started = build_run.build_in_background(
                D, mock.Mock(side_effect=RuntimeError("build failed")), "t0", build_failure_log
            )
            self.assertEqual(started, BuildStarted())
            self.assertTrue(worker_done.wait(2), "worker did not report its error")
        self.assertIsInstance(errors[0], OSError)
        self.assertEqual(str(errors[0]), "history failed")
        self.assertFalse(D.lock.locked())
        self.assertEqual(build.state_snapshot(D)["state"], "fail")

    def test_both_build_at_once_into_their_own_folders(self):
        """Both compiles overlap (the fakes wait for each other), both succeed, and each result stays with its document."""
        cfg = build.BuildConfig(state=self.state, dpi=150, timeout=30)
        a, b = self.docs["a"], self.docs["b"]
        self.assertEqual(self.start(a, cfg), BuildStarted())
        self.assertEqual(self.start(b, cfg), BuildStarted())
        self.assertEqual(self.start(a, cfg), BuildBusy())  # one build at a time per document
        deadline = time.monotonic() + 30
        while (a.lock.locked() or b.lock.locked()) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(a.lock.locked() or b.lock.locked(), "builds did not finish")
        for key, D in self.docs.items():
            with self.subTest(doc=key):
                snap = build.state_snapshot(D)
                self.assertEqual(snap["state"], "ok", snap.get("log_tail"))
                self.assertEqual(snap["seq"], 1)
                pages = build.cur_pages(D)
                self.assertEqual(pages.parent, D.dir)
                self.assertEqual(build.cur_pdf(D).read_bytes(), D.main.read_bytes())  # its own PDF, not the other's
                history = build.load_builds(D)
                self.assertEqual(list(history["by"]), [pages.name])
                self.assertEqual(history["by"][pages.name]["src_hash"], build.doc_fingerprint(D, self.state))
                self.assertEqual(sorted(p.name for p in D.build.iterdir() if p.suffix == ".tex"), [key + ".tex"])
        self.assertNotEqual(
            build.load_builds(a)["by"][build.cur_pages(a).name]["src_hash"],
            build.load_builds(b)["by"][build.cur_pages(b).name]["src_hash"],
        )

    def test_source_mtime_cache_lock_is_owned_by_each_document(self):
        """A busy document's memo does not block another document's source scan."""
        a, b = self.docs["a"], self.docs["b"]
        completed = threading.Event()

        def read_other_document() -> None:
            """Measure b's source while a's memo is unavailable to the caller."""
            build.src_mtime(b, self.state, force=True)
            completed.set()

        with a.mcache_lock:
            worker = threading.Thread(target=read_other_document)
            worker.start()
            try:
                self.assertTrue(completed.wait(2), "another document's source scan was blocked")
            finally:
                worker.join(2)
        self.assertFalse(worker.is_alive())


# latexmk stand-in whose behaviour LIMN_TEST_LATEXMK picks: ok (PDF, SyncTeX, clean log), errors (the same with a
# '! ' line in the log), nopdf (output only), nosynctex (a PDF without SyncTeX) or hang (outlives the timeout).
MODAL_LATEXMK = """#!/bin/sh
for a; do main=$a; done
stem=${main%.tex}
echo "latexmk ran $stem"
case "$LIMN_TEST_LATEXMK" in
  hang) sleep 5 ;;
  nopdf) exit 12 ;;
  nosynctex) cp "$main" "$stem.pdf" ;;
  errors) cp "$main" "$stem.pdf"; printf 'synctex' > "$stem.synctex.gz"
          printf '! Undefined control sequence.\\nl.3 \\\\foo\\n' > "$stem.log" ;;
  *) cp "$main" "$stem.pdf"; printf 'synctex' > "$stem.synctex.gz"; : > "$stem.log" ;;
esac
"""

# pdftoppm stand-in that fails when LIMN_TEST_PDFTOPPM is "fail", else writes one page.
MODAL_PDFTOPPM = """#!/bin/sh
[ "$LIMN_TEST_PDFTOPPM" = fail ] && exit 1
cp "$4" "$5-1.png"
"""


class Outcomes(unittest.TestCase):
    """Every way a build ends is a value of its own type (docs/handbook/build-sync.md §빌드 결과), made by the module
    with fake latexmk/pdftoppm on PATH and no server."""

    def setUp(self):
        """One LaTeX document, one view-only PDF document and the modal fakes on PATH."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.state = root / "state"
        src = root / "ms"
        src.mkdir()
        main = src / "main.tex"
        main.write_text("\\documentclass{article}\\begin{document}A\\end{document}\n", encoding="utf-8")
        self.D = PlainDoc(src=src, main=main, dir=self.state / "docs" / "ms")
        pdf = src / "review.pdf"
        pdf.write_bytes(b"%PDF-1.4 review")
        self.P = PlainDoc(
            src=src, main=pdf, dir=self.state / "docs" / "rv", builds_from_source=False, watches_files=True
        )
        self.cfg = build.BuildConfig(state=self.state, dpi=72, timeout=1)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for name, text in (("latexmk", MODAL_LATEXMK), ("pdftoppm", MODAL_PDFTOPPM)):
            (bin_dir / name).write_text(text, encoding="utf-8")
            (bin_dir / name).chmod(0o755)
        self.env = {"PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", "")}

    def compile(self, latexmk: str = "ok", pdftoppm: str = "ok", pull=None):
        """compile_tex of the LaTeX document with the fakes in the given modes."""
        env = dict(self.env, LIMN_TEST_LATEXMK=latexmk, LIMN_TEST_PDFTOPPM=pdftoppm)
        with mock.patch.dict(os.environ, env):
            return build_engine.compile_tex(self.D, self.cfg, pull)

    def test_ok_when_a_fresh_pdf_and_synctex_come_out(self):
        """A clean build is BuildOk naming its new page directory, which pages.cur now points at."""
        res = self.compile()
        self.assertIsInstance(res, BuildOk)
        self.assertEqual(res.build, build.cur_pages(self.D).name)
        self.assertEqual((res.pages, res.pull, res.head), (1, None, "-"))
        self.assertEqual(res.src_hash, build.doc_fingerprint(self.D, self.state))
        self.assertIn("latexmk ran main", res.log)

    def test_ok_with_errors_carries_the_latex_errors(self):
        """New pages with '! ' lines in the log are BuildOkWithErrors holding those errors."""
        res = self.compile("errors")
        self.assertIsInstance(res, BuildOkWithErrors)
        self.assertEqual(res.errors, [{"line": 3, "msg": "Undefined control sequence."}])

    def test_each_failed_compile_names_its_kind(self):
        """No PDF, no SyncTeX, a timeout and a failed render are BuildFailed with that kind, latexmk's output kept."""
        for latexmk, pdftoppm, kind in (
            ("nopdf", "ok", "no_pdf"),
            ("nosynctex", "ok", "no_synctex"),
            ("hang", "ok", "timeout"),
            ("ok", "fail", "render"),
        ):
            with self.subTest(kind=kind):
                res = self.compile(latexmk, pdftoppm)
                self.assertIsInstance(res, BuildFailed)
                self.assertEqual((res.kind, res.detail), (kind, ""))
                self.assertIsNotNone(res.output)
                self.assertEqual(build_failure_log(res), BUILD_FAILURES[kind] + "\n" + res.output)

    def test_pull_record_rides_along(self):
        """The --git-pull step's record is the outcome's pull, success or failure."""
        record = {"state": "up_to_date", "reason": None, "head_before": "a", "head_after": "a"}
        self.assertEqual(self.compile(pull=lambda: record).pull, record)
        self.assertEqual(self.compile("nopdf", pull=lambda: record).pull, record)

    def test_a_rebuild_within_the_same_second_gets_a_page_directory_of_its_own(self):
        """Page directories are named by the second (pages-<YYYYmmddHHMMSS>); a rebuild within the same second takes the
        next free -<n> suffix, so every build has its own name and no test has to wait for the clock to tick over."""
        with mock.patch.object(build.time, "strftime", return_value="20260927120000"):
            names = [self.compile().build for _ in range(3)]
        self.assertEqual(names, ["pages-20260927120000", "pages-20260927120000-1", "pages-20260927120000-2"])
        self.assertEqual(build.cur_pages(self.D).name, names[-1])

    def test_pages_not_rendered_when_a_companion_cannot_be_copied(self):
        """render_pages answers pdf_copy with the OSError when a file to store next to the pages is missing."""
        pdf = self.D.src / "main.pdf"
        pdf.write_bytes(b"%PDF")
        with mock.patch.dict(os.environ, self.env):
            out = build_engine.render_pages(self.D, pdf, [self.D.src / "gone.synctex.gz"], 72)
        self.assertIsInstance(out, PagesNotRendered)
        self.assertEqual(out.kind, "pdf_copy")
        self.assertIn("gone.synctex.gz", out.detail)
        self.assertFalse(any(self.D.dir.glob("pages-*")))  # the half-made directory is gone

    def test_view_only_render_outcomes(self):
        """A view-only render is BuildOk without log, pull or src_mtime; a failed one BuildFailed with no latexmk
        output; a missing PDF BuildAborted naming it."""
        with mock.patch.dict(os.environ, dict(self.env, LIMN_TEST_PDFTOPPM="ok")):
            ok = build_engine.render_pdf_doc(self.P, self.cfg)
        self.assertIsInstance(ok, BuildOk)
        self.assertEqual((ok.log, ok.pull, ok.src_mtime), ("", None, None))
        with mock.patch.dict(os.environ, dict(self.env, LIMN_TEST_PDFTOPPM="fail")):
            failed = build_engine.render_pdf_doc(self.P, self.cfg)
        self.assertIsInstance(failed, BuildFailed)
        self.assertEqual((failed.kind, failed.output, failed.src_mtime), ("render", None, None))
        self.assertEqual(build_failure_log(failed), BUILD_FAILURES["render"])
        self.P.main.unlink()
        self.assertEqual(build_engine.render_pdf_doc(self.P, self.cfg), BuildAborted("pdf_missing", str(self.P.main)))

    def test_tracked_failure_records_its_log_text(self):
        """run_tracked hands a failure to describe: the build state's log_tail and builds.json's last.log_tail hold
        that text, and the watch's last_build_failed turns true."""
        self.assertFalse(build.last_build_failed(self.D))
        env = dict(self.env, LIMN_TEST_LATEXMK="nopdf")
        with mock.patch.dict(os.environ, env):
            res = build_run.run_tracked(
                self.D, self.state, lambda: build_engine.compile_tex(self.D, self.cfg, None), "t0", build_failure_log
            )
        text = build_failure_log(res)
        self.assertTrue(text.startswith("새 PDF 가 나오지 않았습니다.\n"), text)
        self.assertEqual(build.state_snapshot(self.D)["log_tail"], text)
        self.assertEqual(build.load_builds(self.D)["last"]["log_tail"], text)
        self.assertTrue(build.last_build_failed(self.D))

    def test_a_crash_becomes_a_failed_build(self):
        """An exception in the compile step is BuildAborted crashed with its repr; the state is fail, not running."""
        res = build_run.run_tracked(self.D, self.state, mock.Mock(side_effect=OSError("boom")), "t0", build_failure_log)
        self.assertEqual(res, BuildAborted("crashed", repr(OSError("boom"))))
        self.assertEqual(build.state_snapshot(self.D)["state"], "fail")
        self.assertEqual(build_failure_log(res), "빌드 중 예상 밖 예외가 났습니다: OSError('boom')")

    def test_source_mtime_failure_finishes_tracked_build(self):
        """A failed source scan after entering running becomes a recorded failure, leaving the document reusable."""
        self.D.dir.mkdir(parents=True)
        with mock.patch.object(build, "src_mtime", side_effect=OSError("scan failed")):
            res = build_run.build_now(
                self.D,
                lambda: build_run.run_tracked(
                    self.D, self.state, lambda: self.fail("compile ran"), "t0", build_failure_log
                ),
            )
        self.assertEqual(res, BuildAborted("crashed", repr(OSError("scan failed"))))
        self.assertFalse(self.D.lock.locked())
        self.assertEqual(build.state_snapshot(self.D)["state"], "fail")
        self.assertEqual(build.load_builds(self.D)["last"]["state"], "fail")

    def test_finalization_error_clears_running_without_hiding_error(self):
        """If result recording unexpectedly fails, the synchronous build is reusable and the error reaches its caller."""
        with (
            mock.patch.object(build_run, "finish_build", side_effect=OSError("record failed")),
            self.assertRaisesRegex(OSError, "record failed"),
        ):
            build_run.build_now(
                self.D,
                lambda: build_run.run_tracked(
                    self.D, self.state, lambda: BuildAborted("crashed", "step"), "t0", build_failure_log
                ),
            )
        self.assertFalse(self.D.lock.locked())
        state = build.state_snapshot(self.D)
        self.assertEqual((state["state"], state["phase"], self.D.bstate["start_ts"]), ("fail", None, None))

    def test_baseline_write_error_keeps_published_pages_and_clears_running(self):
        """If baseline persistence fails after page publication, keep the page pointer and report a failed state."""
        published = []

        def compile_and_remember() -> BuildOk:
            """Run the real fake-tool compile and remember the directory it published."""
            result = self.compile()
            self.assertIsInstance(result, BuildOk)
            published.append(result.build)
            return result

        with (
            mock.patch.object(build, "write_built_src_mtime", side_effect=RuntimeError("baseline failed")),
            self.assertRaisesRegex(RuntimeError, "baseline failed"),
        ):
            build_run.build_now(
                self.D,
                lambda: build_run.run_tracked(self.D, self.state, compile_and_remember, "t0", build_failure_log),
            )
        self.assertEqual(build.cur_pages(self.D).name, published[0])
        self.assertFalse(self.D.lock.locked())
        self.assertEqual(build.state_snapshot(self.D)["state"], "fail")


class RebuildAnswer(unittest.TestCase):
    """POST /api/rebuild's body is written once, at the build feature edge, in the key order and statuses of the agent contract
    (docs/handbook/build-sync.md §응답)."""

    PULL = {"state": "ok", "reason": None, "head_before": "a", "head_after": "b"}

    def keys(self, result) -> list[str]:
        """The keys of a finished build's body, in order."""
        return list(finished_build_body(result))

    def test_key_order_of_every_finished_build(self):
        """Only what the build got as far as follows the five leading keys."""
        lead = ["ok", "state", "errors", "log", "elapsed_s"]
        pages = ["src_hash", "head", "build", "pages"]
        cases = [
            (BuildOk("l", 1.0, self.PULL, 2.0, "h", "abc", "pages-1", 3), lead + ["pull", "src_mtime"] + pages),
            (BuildOk("", 1.0, None, None, None, "abc", "pages-1", 3), lead + pages),
            (
                BuildOkWithErrors([{"line": 1, "msg": "m"}], "l", 1.0, None, 2.0, "h", "a", "p", 1),
                lead + ["src_mtime"] + pages,
            ),
            (CopyFailed("rsync exit 23", 0.5, self.PULL, 2.0), lead + ["pull", "src_mtime"]),
            (BuildFailed("no_pdf", "", "tail", [], 0.5, None, 2.0, None), lead + ["src_mtime", "src_hash"]),
            (BuildFailed("render", "", None, [], 0.5, None, None, "h"), lead + ["src_hash"]),
            (BuildAborted("crashed", "RuntimeError('x')"), lead),
        ]
        for result, keys in cases:
            with self.subTest(result=type(result).__name__):
                self.assertEqual(self.keys(result), keys)

    def test_bodies_and_statuses(self):
        """ok drops the log, every other outcome keeps its last 40 lines, ?log=1 keeps it whole; busy is 409."""
        long_log = "\n".join("l%d" % i for i in range(60))
        ok = BuildOk(long_log, 1.0, None, 2.0, "h", "abc", "pages-1", 3)
        body, status = rebuild_answer(ok, full=False)
        self.assertEqual((status, "log" in body, body["state"], body["ok"]), (200, False, "ok", True))
        self.assertEqual(rebuild_answer(ok, full=True)[0]["log"], long_log)
        failed = BuildFailed("timeout", "", long_log, [], 1.0, None, 2.0, None)
        body, status = rebuild_answer(failed, full=False)
        self.assertEqual((status, body["state"], body["ok"]), (200, "fail", False))
        self.assertEqual(body["log"].splitlines(), long_log.splitlines()[-40:])
        self.assertEqual(rebuild_answer(BuildBusy(), full=False), ({"ok": False, "busy": True}, 409))
        self.assertEqual(rebuild_started_answer(BuildStarted()), ({"state": "running"}, 202))
        self.assertEqual(rebuild_started_answer(BuildBusy()), ({"state": "running", "busy": True}, 409))

    def test_a_view_only_document_is_refused_by_both_answers(self):
        """ViewOnlyNoRebuild is 400 view_only_no_rebuild naming the document, synchronous or ?async=1."""
        for answer in (lambda r: rebuild_answer(r, full=True), rebuild_started_answer):
            with self.subTest(answer=answer), self.assertRaises(HTTPError) as e:
                answer(ViewOnlyNoRebuild("rv"))
            self.assertEqual(
                (e.exception.code, e.exception.body),
                (
                    400,
                    {
                        "error": "보기 전용 문서(rv)는 재빌드하지 않습니다 — PDF 파일이 바뀌면 쪽을 저절로 다시 그립니다.",
                        "reason": "view_only_no_rebuild",
                    },
                ),
            )

    def test_failure_log_texts(self):
        """Each failure's log opens with its kind's text, the detail filled in."""
        self.assertEqual(
            build_failure_log(CopyFailed("rsync exit 23: x", 0.1, None, 1.0)),
            "원고 사본을 만들지 못했습니다: rsync exit 23: x",
        )
        self.assertEqual(
            build_failure_log(BuildFailed("pdf_copy", "disk full", "t", [], 0.1, None, 1.0, None)),
            "PDF 사본을 쪽 디렉토리에 두지 못했습니다: disk full\nt",
        )
        self.assertEqual(build_failure_log(BuildAborted("pdf_missing", "/x/a.pdf")), "PDF 가 없습니다: /x/a.pdf")
        self.assertEqual(
            build_failure_log(BuildAborted("worker_crashed", "RuntimeError('boom')")),
            "빌드 스레드에서 예상 밖 예외가 났습니다: RuntimeError('boom')",
        )


class HistoryRestore(unittest.TestCase):
    """A damaged history file cannot prevent a document from starting or leak malformed fields into build status."""

    def test_saved_errors_and_elapsed_time_survive_restart(self):
        """A valid failure's display errors, duration and pull record survive writing and restoring history."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state"
            state.mkdir()
            main = root / "main.tex"
            main.write_text("text", encoding="utf-8")
            doc = PlainDoc(root, main, state)
            errors = [{"line": 0, "msg": "first"}, {"line": None, "msg": "second"}]
            pull = {"state": "skipped", "reason": "dirty", "head_before": "a", "head_after": "a"}
            result = BuildFailed("no_pdf", "", "log", errors, 1.25, pull, 1.0, None)
            build_run.finish_build(doc, result, 1.0, build_failure_log)
            doc.bstate = {"state": "idle", "seq": 0}

            build.seed_builds(doc, state)

            status = build.state_snapshot(doc)
            self.assertEqual(status["errors"], errors)
            self.assertEqual((status["elapsed_s"], status["last_s"]), (1.25, 1.25))
            self.assertEqual(status["pull"], pull)

    def test_malformed_last_fields_restore_as_safe_values(self):
        """Keep a valid terminal state and sequence while discarding invalid saved display fields."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state"
            state.mkdir()
            main = root / "main.tex"
            main.write_text("text", encoding="utf-8")
            doc = PlainDoc(root, main, state)
            (state / "builds.json").write_text(
                json.dumps(
                    {
                        "seq": 4,
                        "builds": [],
                        "last": {
                            "state": "fail",
                            "errors": 7,
                            "log_tail": {"unexpected": "object"},
                            "started_at": [1],
                            "finished_at": [2],
                            "elapsed_s": "slow",
                            "head": {},
                            "pull": "invalid",
                        },
                    }
                ),
                encoding="utf-8",
            )

            build.seed_builds(doc, state)

            status = build.state_snapshot(doc)
            self.assertEqual((status["state"], status["seq"]), ("fail", 4))
            self.assertEqual(status["errors"], [])
            self.assertEqual(status["log_tail"], "")
            self.assertIsNone(status["last_s"])
            self.assertIsNone(status["head"])
            self.assertIsNone(status["pull"])

    def test_nonfinite_elapsed_does_not_escape_into_build_status(self):
        """A JSON parser's nonstandard NaN or Infinity cannot become an API build duration after restart."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state"
            state.mkdir()
            main = root / "main.tex"
            main.write_text("text", encoding="utf-8")
            doc = PlainDoc(root, main, state)
            for elapsed in (float("nan"), float("inf"), float("-inf")):
                with self.subTest(elapsed=elapsed):
                    (state / "builds.json").write_text(
                        json.dumps({"seq": 4, "builds": [], "last": {"state": "fail", "elapsed_s": elapsed}}),
                        encoding="utf-8",
                    )
                    doc.bstate = {"state": "idle", "seq": 0}
                    build.seed_builds(doc, state)
                    status = build.state_snapshot(doc)
                    self.assertIsNone(status["last_s"])
                    self.assertEqual(status["elapsed_s"], 0.0)
                    json.dumps(status, allow_nan=False)


class RebuildRules(unittest.TestCase):
    """request_rebuild (POST /api/rebuild) and needs_build (startup) decide on the document alone."""

    def setUp(self):
        """A LaTeX and a view-only document over one temporary tree, neither built yet."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "main.tex").write_text("x", encoding="utf-8")
        (root / "review.pdf").write_bytes(b"%PDF-1.4 x")
        self.tex = PlainDoc(root, root / "main.tex", root / "state-tex")
        self.pdf = PlainDoc(root, root / "review.pdf", root / "state-pdf", builds_from_source=False, watches_files=True)
        for D in (self.tex, self.pdf):
            D.dir.mkdir()
            D.key = "ms" if D.builds_from_source else "rv"

    def test_a_view_only_document_is_never_rebuilt_on_request(self):
        """The run is called only for a LaTeX document; a view-only one comes back as ViewOnlyNoRebuild."""
        runs = []
        self.assertEqual(build_run.request_rebuild(self.pdf, runs.append), ViewOnlyNoRebuild("rv"))
        self.assertEqual(runs, [])
        self.assertIsNone(build_run.request_rebuild(self.tex, runs.append))
        self.assertEqual(runs, [self.tex])

    def test_startup_builds_what_is_missing_or_changed(self):
        """LaTeX: always unless --no-build, then only without a PDF or pages. View-only: when its PDF changed or it
        has no pages, --no-build or not."""
        self.assertTrue(build_run.needs_build(self.tex, False, 72))
        self.assertTrue(build_run.needs_build(self.tex, True, 72))  # no PDF, no pages yet
        self.assertTrue(build_run.needs_build(self.pdf, True, 72))  # never rendered
        pages = self.tex.dir / "pages"
        pages.mkdir()
        (pages / "page-1.png").write_bytes(blank_png(10, 10))
        (pages / "main.pdf").write_bytes(b"%PDF")
        self.assertFalse(build_run.needs_build(self.tex, True, 72))
        self.assertTrue(build_run.needs_build(self.tex, False, 72))
        pdf_pages = self.pdf.dir / "pages"
        pdf_pages.mkdir()
        (pdf_pages / "page-1.png").write_bytes(blank_png(10, 10))
        files.atomic_write(self.pdf.dir / "pdf_sig.txt", build_engine.pdf_signature(self.pdf))
        self.assertFalse(build_run.needs_build(self.pdf, False, 72))
        self.pdf.main.write_bytes(b"%PDF-1.4 changed, longer")
        self.assertTrue(build_run.needs_build(self.pdf, True, 72))


class ReadsBeforeAndBetweenBuilds(unittest.TestCase):
    """What the build reads of a document, by whether it builds from source: the PDF before any page copy and the
    manuscript's newest modification time."""

    def setUp(self):
        """A LaTeX body, a view-only PDF and a second .tex in one folder, 100 s apart in that order; no build yet."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "ms"
        self.root.mkdir()
        self.state = Path(tmp.name) / "state"
        self.t = time.time() - 1000
        for name, at in (("main.tex", self.t), ("review.pdf", self.t + 100), ("other.tex", self.t + 200)):
            path = self.root / name
            path.write_bytes(b"%PDF-1.4 x" if name.endswith(".pdf") else b"x")
            os.utime(path, (at, at))
        self.tex = PlainDoc(self.root, self.root / "main.tex", self.state / "docs" / "ms")
        self.pdf = PlainDoc(
            self.root,
            self.root / "review.pdf",
            self.state / "docs" / "rv",
            builds_from_source=False,
            watches_files=True,
        )

    def test_a_document_built_from_source_reads_latexmk_output_and_any_other_its_own_file(self):
        """No page copy yet: a LaTeX document's PDF is where latexmk writes it in the build copy, even before it
        exists; a view-only document's PDF is its main file."""
        self.assertEqual(build.cur_pdf(self.tex), self.tex.out / "main.pdf")
        self.assertEqual(build.cur_pdf(self.pdf), self.pdf.main)

    def test_src_mtime_scans_the_tree_only_for_a_document_built_from_source(self):
        """A LaTeX document's manuscript time is its newest source file (other.tex); a view-only document's is its PDF
        alone, however new the .tex files beside it."""
        self.assertAlmostEqual(build.src_mtime(self.tex, self.state, force=True), self.t + 200, places=3)
        self.assertAlmostEqual(build.src_mtime(self.pdf, self.state, force=True), self.t + 100, places=3)

    def test_build_view_exposes_published_artifacts_freshness_state_and_stamps(self):
        """Consumers can read every shared build fact through one stateless contract."""
        view = BuildView()
        current = self.tex.dir / "pages-20260930120000"
        historical = self.tex.dir / "pages-20260929120000"
        for pages in (current, historical):
            pages.mkdir(parents=True)
            (pages / "page-1.png").write_bytes(blank_png(300, 600))
            (pages / "main.pdf").write_bytes(MINI_PDF)
        (self.tex.dir / "pages.cur").write_text(current.name, encoding="utf-8")
        (self.tex.dir / "built_at.txt").write_text("2026-09-30 12:00:00", encoding="utf-8")
        (self.tex.dir / "head.txt").write_text("abc1234", encoding="utf-8")
        (self.tex.dir / "built_src_mtime.txt").write_text(str(self.t), encoding="utf-8")
        self.tex.bstate.update(state="fail", phase="done")

        self.assertEqual(view.current_pages(self.tex), current)
        self.assertEqual(view.page_metadata(current, 150), [{"name": "page-1.png", "pt_w": 144.0, "pt_h": 288.0}])
        self.assertEqual(view.published_pdf(self.tex, historical.name), historical / "main.pdf")
        self.assertEqual(view.snapshot(self.tex)["state"], "fail")
        self.assertGreater(view.source_mtime(self.tex, self.state, force=True), self.t)
        self.assertGreater(view.source_newer(self.tex, self.state), 0)
        self.assertEqual(view.built_source_mtime(self.tex), self.t)
        self.assertEqual((view.built_at(self.tex), view.head(self.tex)), ("2026-09-30 12:00:00", "abc1234"))
        self.assertEqual(view.history(self.tex)["builds"], [])
        self.assertTrue(view.last_failed(self.tex))
        self.assertTrue(view.valid_name(current.name))


class FigureBuildFacts(unittest.TestCase):
    """The figure build facts limn.builds.artifacts shares with the builds and pins slices: which map paths a figure document
    accepts, the PDF a map names, and the map a published build kept (docs/handbook/code-style-roadmap.md §R10)."""

    def setUp(self):
        """A manuscript with a figure folder figs/ (out/, src/, a dot folder, a symlink src/out-link to a folder
        outside the manuscript) served as figure document fig."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.figs = root / "ms" / "figs"
        for sub in ("out", "src", ".cache"):
            (self.figs / sub).mkdir(parents=True)
        (root / "elsewhere").mkdir()
        (self.figs / "src" / "out-link").symlink_to(root / "elsewhere")
        paths = RunPaths(root / "ms", root / "ms" / "main.tex", root / "state")
        self.doc = Doc("fig", "그림", "figure", self.figs, self.figs / "out" / "figures.limnmap.json", paths=paths)
        self.inside = build.figure_source_check(self.figs)
        self.view = BuildView()

    def map_naming(self, pdf: str) -> figmap.FigureMap:
        """A map with no pages that names pdf."""
        return figmap.FigureMap(pdf, "0" * 64, ())

    def publish(self, name: str, raw: bytes) -> Path:
        """Page directory `name` of the figure document holding a map copy with bytes raw."""
        pdir = self.doc.dir / name
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / build.FIGMAP_NAME).write_bytes(raw)
        return pdir

    def test_a_source_path_is_accepted_only_inside_the_documents_folder(self):
        """Relative paths that resolve inside figs/ pass, existing or not; empty, absolute, escaping, dot-named,
        backslashed, NUL-holding, over-long and symlinked-out paths and the folder itself do not."""
        for rel in ("src/B2_calendar.py", "lib/components.py", "./src/a.py", "src/../lib/b.py"):
            self.assertTrue(self.inside(rel), rel)
        for rel in (
            "",
            "/etc/passwd",
            "../main.tex",
            "src/../../main.tex",
            ".cache/x.py",
            "src/.hidden/x.py",
            "src\\a.py",
            "src/a\x00.py",
            "src/out-link/x.py",
            "a" * 5000,
            ".",
        ):
            self.assertFalse(self.inside(rel), repr(rel[:40]))

    def test_the_pdf_a_map_names_is_resolved_from_the_maps_folder_inside_the_document(self):
        """pdf is relative to the folder holding the map and may step up, but only to a path inside figs/."""
        self.assertEqual(build.figure_pdf(self.doc, self.map_naming("figures.pdf")), self.figs / "out" / "figures.pdf")
        self.assertEqual(
            build.figure_pdf(self.doc, self.map_naming("../render/figures.pdf")), self.figs / "render" / "figures.pdf"
        )
        for pdf in ("../../outside.pdf", "/srv/paper/figures.pdf", ".figures.pdf", "../src/out-link/f.pdf"):
            self.assertIsNone(build.figure_pdf(self.doc, self.map_naming(pdf)), pdf)

    def test_a_published_build_map_is_read_back_or_absent(self):
        """A build with a map copy gives the map and the PDF it names; a build without one, a gone build and a name
        that is no page directory give None."""
        pdir = self.doc.dir / "pages-20260101000000"
        pdir.mkdir(parents=True)
        self.assertIsNone(build.load_build_map(self.doc, pdir.name))
        self.publish(pdir.name, map_bytes(figure_map(MINI_PDF)))
        self.assertIsInstance(build.load_build_map(self.doc, pdir.name), figmap.FigureMap)
        self.assertEqual(build.build_figure_pdf(self.doc, pdir.name), self.figs / "out" / "figures.pdf")
        for name in ("../pages-20260101000000", "pages-x", "", "figure-import", "pages-20260102000000"):
            self.assertIsNone(build.load_build_map(self.doc, name), name)
            self.assertIsNone(build.build_figure_pdf(self.doc, name), name)

    def test_build_view_keeps_current_and_historical_figure_pdf_facts(self):
        """The read contract resolves each build's published figure map, including the current pointer."""
        current = self.publish("pages-20260101000000", map_bytes(figure_map(MINI_PDF)))
        historical = self.publish("pages-20251231000000", map_bytes(figure_map(MINI_PDF)))
        self.doc.dir.mkdir(parents=True, exist_ok=True)
        (self.doc.dir / "pages.cur").write_text(current.name, encoding="utf-8")

        self.assertEqual(self.view.current_pages(self.doc), current)
        self.assertEqual(self.view.figure_pdf(self.doc, current.name), self.figs / "out" / "figures.pdf")
        self.assertEqual(self.view.figure_pdf(self.doc, historical.name), self.figs / "out" / "figures.pdf")

    def test_a_published_map_is_checked_again_when_read(self):
        """The copy is parsed with the document's own source check: a source outside figs/ is path_outside, a copy
        over the size cap is too_large, and neither names a PDF."""
        m = figure_map(MINI_PDF)
        m["pages"][0]["elements"][0]["src"]["file"] = "../../main.tex"
        self.publish("pages-20260101000000", map_bytes(m))
        self.assertEqual(build.load_build_map(self.doc, "pages-20260101000000").reason, "path_outside")
        self.publish("pages-20260102000000", b" " * (figmap.MAP_MAX_BYTES + 10))
        self.assertEqual(build.load_build_map(self.doc, "pages-20260102000000").reason, "too_large")
        self.assertIsNone(build.build_figure_pdf(self.doc, "pages-20260101000000"))


# ---------------------------------------------------------------- through server.py's wiring
#
# The tracked build (build_all/build_async over a stubbed _build) and the single document's legacy page folder. These
# classes load server.py (helpers.ps) and drive the module through its bindings; the tests above call the module on
# its own.


class Legacy(Base):
    """Migrating legacy page files keeps the PDF and SyncTeX paired with rendered pages."""

    def test_migrate_copies_pdf_next_to_pages(self):
        """Migration copies the old PDF and SyncTeX once, preserving the pair after the build folder changes."""
        (ps.APP.C.state / "pages").mkdir()
        (ps.APP.C.state / "pages" / "page-01.png").write_bytes(b"png")
        ps.APP.C.build.mkdir()
        (ps.APP.C.build / "main.pdf").write_bytes(b"%PDF-old")
        (ps.APP.C.build / "main.synctex.gz").write_bytes(b"syn-old")
        limn_build.migrate_pages(ps.APP.docs[0])
        self.assertEqual(limn_build.cur_pdf(ps.APP.docs[0]), ps.APP.C.state / "pages" / "main.pdf")
        (ps.APP.C.build / "main.pdf").write_bytes(b"%PDF-new")  # even though the rebuild overwrites build/
        # pick reads the PDF paired with the screen
        self.assertEqual(limn_build.cur_pdf(ps.APP.docs[0]).read_bytes(), b"%PDF-old")
        self.assertEqual((ps.APP.C.state / "pages" / "main.synctex.gz").read_bytes(), b"syn-old")
        limn_build.migrate_pages(ps.APP.docs[0])  # calling it twice doesn't overwrite either
        self.assertEqual(limn_build.cur_pdf(ps.APP.docs[0]).read_bytes(), b"%PDF-old")


# ---------------------------------------------------------------- async build (docs/handbook/build-sync.md §비동기 재빌드)


def ok_build(elapsed_s: float = 0.0) -> BuildOk:
    """A stand-in for a successful LaTeX build (what a stubbed _build returns): one page, no pull, no fingerprint and no page directory name, so no history entry."""
    return BuildOk("", elapsed_s, None, 1.0, None, "-", "", 1)


class AsyncBuild(Base):
    """Asynchronous builds expose progress, serialize rebuilds, and publish only committed results."""

    def tearDown(self):
        """Release a build lock left by a failed assertion before the shared fixture removes its state."""
        if ps.APP.docs[0].lock.locked():
            ps.APP.docs[0].lock.release()
        ps.APP.docs[0].bstate.update(state="idle", phase=None, started_at=None, start_ts=None)
        super().tearDown()

    def test_async_returns_running_then_409_while_busy(self):
        """The first background build reports running; a second request is busy until its worker releases the lock."""
        ev = threading.Event()

        def fake_build(D=None):
            """Hold the worker until the test has observed its running state and busy response."""
            ev.wait(5)
            return ok_build(elapsed_s=0.01)

        with mock.patch.object(ps.APP.build_requests, "compile", side_effect=fake_build):
            r1 = ps.APP.build_requests.build_async(ps.APP.docs[0])
            self.assertEqual(r1, BuildStarted())
            self.assertEqual(limn_build.state_snapshot(ps.APP.docs[0])["state"], "running")
            r2 = ps.APP.build_requests.build_async(ps.APP.docs[0])
            self.assertEqual(r2, BuildBusy())
            ev.set()
            for _ in range(200):
                if not ps.APP.docs[0].lock.locked():
                    break
                time.sleep(0.02)
        self.assertFalse(ps.APP.docs[0].lock.locked())
        self.assertEqual(limn_build.state_snapshot(ps.APP.docs[0])["state"], "ok")

    def test_phase_copy_observed_before_build_runs(self):
        """The tracked build publishes its copy phase before invoking the compiler and clears it afterward."""
        seen = []

        def fake_build(D=None):
            """Record the state visible inside the build step, then return a successful result."""
            seen.append(limn_build.state_snapshot(ps.APP.docs[0])["phase"])
            return ok_build()

        with mock.patch.object(ps.APP.build_requests, "compile", side_effect=fake_build):
            ps.APP.build_requests.build_all(ps.APP.docs[0])
        self.assertEqual(seen, ["copy"])
        self.assertEqual(limn_build.state_snapshot(ps.APP.docs[0])["phase"], None)  # phase is cleared when it finishes

    def test_ok_errors_state_surfaces_in_build_state(self):
        """A build with LaTeX errors publishes ok_errors and keeps the error's source line."""

        def fake_build(D=None):
            """Return a committed build carrying one LaTeX diagnostic."""
            return BuildOkWithErrors(
                [{"line": 412, "msg": "Undefined control sequence"}], "boom", 1.2, None, 1.0, None, "-", "", 3
            )

        with mock.patch.object(ps.APP.build_requests, "compile", side_effect=fake_build):
            ps.APP.build_requests.build_all(ps.APP.docs[0])
        st = limn_build.state_snapshot(ps.APP.docs[0])
        self.assertEqual(st["state"], "ok_errors")
        self.assertEqual(st["errors"][0]["line"], 412)

    def test_ok_errors_commits_built_src_mtime(self):
        """Published pages with LaTeX diagnostics still commit the manuscript mtime baseline."""

        def fake_build(D=None):
            """Return an ok_errors result whose pages were published despite a diagnostic."""
            return BuildOkWithErrors([{"line": 1, "msg": "x"}], "", 0.0, None, 1.0, None, "-", "", 1)

        with mock.patch.object(ps.APP.build_requests, "compile", side_effect=fake_build):
            ps.APP.build_requests.build_all(ps.APP.docs[0])
        self.assertIsNotNone(limn_build.read_built_src_mtime(ps.APP.docs[0]))

    def test_failed_build_does_not_commit_built_src_mtime(self):
        """A failed build preserves the last successful mtime baseline so the stale badge remains accurate."""
        # bug: built_src_mtime used to be written at build "start" and stayed even on failure — the screen
        # still showed the old PDF but the "manuscript modified" badge turned off. It should only be
        # committed on ok|ok_errors.
        self.assertIsNone(limn_build.read_built_src_mtime(ps.APP.docs[0]))

        def fake_build_fail(D=None):
            """Fail before publishing pages or a manuscript mtime baseline."""
            return BuildAborted("crashed", "boom")

        with mock.patch.object(ps.APP.build_requests, "compile", side_effect=fake_build_fail):
            ps.APP.build_requests.build_all(ps.APP.docs[0])
        self.assertIsNone(limn_build.read_built_src_mtime(ps.APP.docs[0]))  # still None because it failed
        self.assertEqual(limn_build.state_snapshot(ps.APP.docs[0])["state"], "fail")

        def fake_build_ok(D=None):
            """Publish a successful build to establish a baseline for the later failure."""
            return ok_build(elapsed_s=0.1)

        with mock.patch.object(ps.APP.build_requests, "compile", side_effect=fake_build_ok):
            ps.APP.build_requests.build_all(ps.APP.docs[0])
        first_ok = limn_build.read_built_src_mtime(ps.APP.docs[0])
        self.assertIsNotNone(first_ok)  # only committed once it succeeds

        with mock.patch.object(ps.APP.build_requests, "compile", side_effect=fake_build_fail):
            ps.APP.build_requests.build_all(ps.APP.docs[0])
        # a subsequent failure doesn't touch the committed value
        self.assertEqual(limn_build.read_built_src_mtime(ps.APP.docs[0]), first_ok)

    def test_async_worker_exception_ends_in_fail_not_stuck_running(self):
        """An uncaught worker exception records failure and frees the lock instead of leaving running forever."""
        # bug: an exception in the async build worker used to leave BUILD_STATE stuck on running forever.
        with mock.patch.object(ps.APP.build_requests, "compile", side_effect=RuntimeError("boom")):
            r = ps.APP.build_requests.build_async(ps.APP.docs[0])
            self.assertEqual(r, BuildStarted())
            for _ in range(200):
                if not ps.APP.docs[0].lock.locked():
                    break
                time.sleep(0.02)
        self.assertFalse(ps.APP.docs[0].lock.locked())
        st = limn_build.state_snapshot(ps.APP.docs[0])
        self.assertEqual(st["state"], "fail")
        self.assertIn("boom", st.get("log_tail") or "")

    def test_rebuild_async_endpoint_returns_409_while_busy(self):
        """A rebuild request while the document lock is held receives HTTP 409."""
        ps.APP.docs[0].lock.acquire()
        try:
            out = self.talk(req("POST", "/api/rebuild?async=1"))
            self.assertIn(b" 409 ", out)
        finally:
            ps.APP.docs[0].lock.release()

    def test_rebuild_async_endpoint_returns_202_when_started(self):
        """The real scheduler returns 202 while compiling, then persists its result and releases the lock."""
        doc = ps.APP.docs[0]
        entered, release = threading.Event(), threading.Event()

        def controlled_compile(cmd, cwd, timeout):
            """Hold the external compiler boundary until the HTTP running response is observed."""
            entered.set()
            if not release.wait(10):
                raise TimeoutError("test did not release compiler")
            return 1, "controlled compiler failure", False

        with mock.patch.object(build_engine, "run_logged", side_effect=controlled_compile):
            try:
                out = self.talk(req("POST", "/api/rebuild?async=1"))
                self.assertIn(b" 202 ", out.split(b"\r\n", 1)[0])
                self.assertEqual(json.loads(out.split(b"\r\n\r\n", 1)[1]), {"state": "running"})
                self.assertTrue(entered.wait(10), "scheduled build did not reach compilation")
                self.assertEqual(limn_build.state_snapshot(doc)["state"], "running")
                self.assertTrue(doc.lock.locked())
            finally:
                release.set()
                acquired = doc.lock.acquire(timeout=10)
                if acquired:
                    doc.lock.release()
                self.assertTrue(acquired, "build worker did not release its document")
        self.assertEqual(limn_build.state_snapshot(doc)["state"], "fail")
        self.assertEqual(limn_build.load_builds(doc)["seq"], 1)
        self.assertEqual((doc.dir / "build.log").read_text(), "controlled compiler failure")

    def test_get_api_build_reports_known_state(self):
        """The build endpoint returns a known state with phase and log fields for the progress viewer."""
        out = self.talk(req("GET", "/api/build"))
        self.assertIn(b" 200 ", out)
        data = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertIn(data["state"], ("idle", "running", "ok", "ok_errors", "fail"))
        self.assertIn("phase", data)
        self.assertIn("log_tail", data)

    @needs_tex("latexmk", "pdftoppm")
    def test_real_build_progresses_through_all_phases(self):
        """Run once with the real latexmk/pdftoppm and observe the copy->latex->render order."""
        seen = []
        stop = threading.Event()

        def poll():
            """Record distinct phases until the real build finishes or the test stops the observer."""
            while not stop.is_set():
                ph = limn_build.state_snapshot(ps.APP.docs[0])["phase"]
                if ph and (not seen or seen[-1] != ph):
                    seen.append(ph)
                time.sleep(0.01)

        t = threading.Thread(target=poll, daemon=True)
        t.start()
        res = ps.APP.build_requests.build_all(ps.APP.docs[0])
        stop.set()
        t.join(2)
        self.assertIsInstance(res, BuildOk)
        self.assertIn("latex", seen)
        self.assertIn("render", seen)
        self.assertTrue(limn_build.cur_pdf(ps.APP.docs[0]).exists())
        aux = limn_build.cur_pages(ps.APP.docs[0]) / "main.aux"
        self.assertTrue(aux.is_file(), "successful build must publish its matching .aux with PDF pages")
        labels = limn_meta.outline_labels(ps.APP.docs[0])
        self.assertEqual(labels["build"], res.build)
        self.assertEqual(
            [(row["number"], row["title"]) for row in labels["labels"][:2]], [("1", "Intro"), ("1.1", "Next")]
        )


if __name__ == "__main__":
    unittest.main()

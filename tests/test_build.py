"""limn.build - the manuscript build, driven by the document and settings it is given (coding rule R5).

The server-level build behaviour is pinned through server.py: the tracked build and the legacy page folder at the end
of this file (AsyncBuild, Legacy), build history in test_locate.py (Estimate), the "manuscript modified" badge in
test_meta.py (LightMeta), --git-pull in test_gitsync.py and the copy step in test_build_copy.py. The classes above
call the module directly, with no server, no run arguments and no "current document": it must not read them, and two
documents must be able to build at the same time, each into its own folders. latexmk and pdftoppm are small fakes on PATH, so no TeX installation is needed.

Run: uv run pytest -q tests/test_build.py
"""

import ast
import json
import os
import tempfile
import threading
import time
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from unittest import mock

from limn import build, build as limn_build, files, meta as limn_meta

from helpers import Base, ps, req

BUILD_PY = Path(build.__file__)
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
    """A LaTeX document as the build sees it (the BuildDoc protocol), with every path given - nothing global."""

    src: Path
    main: Path
    dir: Path
    lock: threading.Lock = field(default_factory=threading.Lock)
    bstate: dict = field(default_factory=lambda: {"state": "idle", "seq": 0})
    bstate_lock: threading.Lock = field(default_factory=threading.Lock)
    builds_lock: threading.Lock = field(default_factory=threading.Lock)
    mcache: list = field(default_factory=lambda: [None, 0.0, 0.0])
    is_pdf: bool = False

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
    """The moved build must not reach the server's run arguments or its "current document" (roadmap stage 5)."""

    def test_reads_no_server_global(self):
        """No name the server keeps as hidden state (C, cur_doc(), the document list, the legacy lock/state) appears."""
        for path in (BUILD_PY, FILES_PY):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            self.assertEqual(names & SERVER_GLOBALS, set(), path.name)

    def test_never_imports_the_server(self):
        """The server is the composition root; the build depends on nothing above it."""
        for path in (BUILD_PY, FILES_PY):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            modules |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
            self.assertFalse({m for m in modules if m == "limn.server" or m.startswith("server")}, path.name)

    def test_source_has_no_config_or_current_document_reference(self):
        """The grep the roadmap names as the proof: no `C.` and no `cur_doc(` in the module text."""
        source = BUILD_PY.read_text(encoding="utf-8")
        self.assertNotIn("C.", source)
        self.assertNotIn("cur_doc(", source)


class LatexErrors(unittest.TestCase):
    """latex_errors turns a TeX log into the error list the viewer's error panel shows."""

    def test_error_line_and_its_line_number(self):
        """Each '! ' line is an error; the first following 'l.<n>' is its line."""
        log = "noise\n! Undefined control sequence.\nl.12 \\foo\n! Missing $ inserted.\nnothing here"
        self.assertEqual(
            build.latex_errors(log),
            [{"line": 12, "msg": "Undefined control sequence."}, {"line": None, "msg": "Missing $ inserted."}],
        )

    def test_at_most_five_errors(self):
        """A runaway log is cut to five errors."""
        self.assertEqual(len(build.latex_errors("! e\n" * 9)), 5)


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

    def start(self, D: PlainDoc, cfg: build.BuildConfig) -> dict:
        """Start D's tracked LaTeX build on a background thread, the way POST /api/rebuild?async=1 does."""

        def tracked():
            """The tracked build of exactly D - no thread-local document involved."""
            return build.run_tracked(D, cfg.state, lambda: build.compile_tex(D, cfg, None), "2026-09-26 10:00:00")

        return build.build_in_background(D, tracked, "2026-09-26 10:00:00")

    def test_both_build_at_once_into_their_own_folders(self):
        """Both compiles overlap (the fakes wait for each other), both succeed, and each result stays with its document."""
        cfg = build.BuildConfig(state=self.state, dpi=150, timeout=30)
        a, b = self.docs["a"], self.docs["b"]
        self.assertEqual(self.start(a, cfg), {"state": "running"})
        self.assertEqual(self.start(b, cfg), {"state": "running"})
        self.assertTrue(self.start(a, cfg).get("busy"))  # one build at a time per document
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


# ---------------------------------------------------------------- through server.py's wiring
#
# The tracked build (build_all/build_async over a stubbed _build) and the single document's legacy page folder. These
# classes load server.py (helpers.ps) and drive the module through its bindings; the tests above call the module on
# its own.


class Legacy(Base):
    def test_migrate_copies_pdf_next_to_pages(self):
        (ps.C.state / "pages").mkdir()
        (ps.C.state / "pages" / "page-01.png").write_bytes(b"png")
        ps.C.build.mkdir()
        (ps.C.build / "main.pdf").write_bytes(b"%PDF-old")
        (ps.C.build / "main.synctex.gz").write_bytes(b"syn-old")
        limn_build.migrate_pages(ps.DOCS[0])
        self.assertEqual(limn_build.cur_pdf(ps.DOCS[0]), ps.C.state / "pages" / "main.pdf")
        (ps.C.build / "main.pdf").write_bytes(b"%PDF-new")  # even though the rebuild overwrites build/
        # pick reads the PDF paired with the screen
        self.assertEqual(limn_build.cur_pdf(ps.DOCS[0]).read_bytes(), b"%PDF-old")
        self.assertEqual((ps.C.state / "pages" / "main.synctex.gz").read_bytes(), b"syn-old")
        limn_build.migrate_pages(ps.DOCS[0])  # calling it twice doesn't overwrite either
        self.assertEqual(limn_build.cur_pdf(ps.DOCS[0]).read_bytes(), b"%PDF-old")


# ---------------------------------------------------------------- async build (docs/handbook/build-sync.md §비동기 재빌드)


class AsyncBuild(Base):
    def tearDown(self):
        if ps.BUILD_LOCK.locked():
            ps.BUILD_LOCK.release()
        ps.BUILD_STATE.update(state="idle", phase=None, started_at=None, start_ts=None)
        super().tearDown()

    def test_async_returns_running_then_409_while_busy(self):
        ev = threading.Event()

        def fake_build(D=None):
            ev.wait(5)
            return {"ok": True, "state": "ok", "errors": [], "log": "", "elapsed_s": 0.01, "pages": 1}

        with mock.patch.object(ps, "_build", side_effect=fake_build):
            r1 = ps.build_async(ps.DOCS[0])
            self.assertEqual(r1, {"state": "running"})
            self.assertEqual(limn_build.state_snapshot(ps.DOCS[0])["state"], "running")
            r2 = ps.build_async(ps.DOCS[0])
            self.assertEqual(r2, {"state": "running", "busy": True})
            ev.set()
            for _ in range(200):
                if not ps.BUILD_LOCK.locked():
                    break
                time.sleep(0.02)
        self.assertFalse(ps.BUILD_LOCK.locked())
        self.assertEqual(limn_build.state_snapshot(ps.DOCS[0])["state"], "ok")

    def test_phase_copy_observed_before_build_runs(self):
        seen = []

        def fake_build(D=None):
            seen.append(limn_build.state_snapshot(ps.DOCS[0])["phase"])
            return {"ok": True, "state": "ok", "errors": [], "log": "", "elapsed_s": 0.0, "pages": 1}

        with mock.patch.object(ps, "_build", side_effect=fake_build):
            ps.build_all(ps.DOCS[0])
        self.assertEqual(seen, ["copy"])
        self.assertEqual(limn_build.state_snapshot(ps.DOCS[0])["phase"], None)  # phase is cleared when it finishes

    def test_ok_errors_state_surfaces_in_build_state(self):
        def fake_build(D=None):
            return {
                "ok": True,
                "state": "ok_errors",
                "errors": [{"line": 412, "msg": "Undefined control sequence"}],
                "log": "boom",
                "elapsed_s": 1.2,
                "pages": 3,
            }

        with mock.patch.object(ps, "_build", side_effect=fake_build):
            ps.build_all(ps.DOCS[0])
        st = limn_build.state_snapshot(ps.DOCS[0])
        self.assertEqual(st["state"], "ok_errors")
        self.assertEqual(st["errors"][0]["line"], 412)

    def test_ok_errors_commits_built_src_mtime(self):
        def fake_build(D=None):
            return {
                "ok": True,
                "state": "ok_errors",
                "errors": [{"line": 1, "msg": "x"}],
                "log": "",
                "elapsed_s": 0.0,
                "pages": 1,
            }

        with mock.patch.object(ps, "_build", side_effect=fake_build):
            ps.build_all(ps.DOCS[0])
        self.assertIsNotNone(limn_build.read_built_src_mtime(ps.DOCS[0]))

    def test_failed_build_does_not_commit_built_src_mtime(self):
        # bug: built_src_mtime used to be written at build "start" and stayed even on failure — the screen
        # still showed the old PDF but the "manuscript modified" badge turned off. It should only be
        # committed on ok|ok_errors.
        self.assertIsNone(limn_build.read_built_src_mtime(ps.DOCS[0]))

        def fake_build_fail(D=None):
            return {"ok": False, "state": "fail", "errors": [], "log": "boom", "elapsed_s": 0.1, "pages": 0}

        with mock.patch.object(ps, "_build", side_effect=fake_build_fail):
            ps.build_all(ps.DOCS[0])
        self.assertIsNone(limn_build.read_built_src_mtime(ps.DOCS[0]))  # still None because it failed
        self.assertEqual(limn_build.state_snapshot(ps.DOCS[0])["state"], "fail")

        def fake_build_ok(D=None):
            return {"ok": True, "state": "ok", "errors": [], "log": "", "elapsed_s": 0.1, "pages": 1}

        with mock.patch.object(ps, "_build", side_effect=fake_build_ok):
            ps.build_all(ps.DOCS[0])
        first_ok = limn_build.read_built_src_mtime(ps.DOCS[0])
        self.assertIsNotNone(first_ok)  # only committed once it succeeds

        with mock.patch.object(ps, "_build", side_effect=fake_build_fail):
            ps.build_all(ps.DOCS[0])
        # a subsequent failure doesn't touch the committed value
        self.assertEqual(limn_build.read_built_src_mtime(ps.DOCS[0]), first_ok)

    def test_async_worker_exception_ends_in_fail_not_stuck_running(self):
        # bug: an exception in the async build worker used to leave BUILD_STATE stuck on running forever.
        with mock.patch.object(ps, "_build", side_effect=RuntimeError("boom")):
            r = ps.build_async(ps.DOCS[0])
            self.assertEqual(r, {"state": "running"})
            for _ in range(200):
                if not ps.BUILD_LOCK.locked():
                    break
                time.sleep(0.02)
        self.assertFalse(ps.BUILD_LOCK.locked())
        st = limn_build.state_snapshot(ps.DOCS[0])
        self.assertEqual(st["state"], "fail")
        self.assertIn("boom", st.get("log_tail") or "")

    def test_rebuild_async_endpoint_202_then_409(self):
        ps.BUILD_LOCK.acquire()
        try:
            out = self.talk(req("POST", "/api/rebuild?async=1"))
            self.assertIn(b" 409 ", out)
        finally:
            ps.BUILD_LOCK.release()

    def test_get_api_build_reports_known_state(self):
        out = self.talk(req("GET", "/api/build"))
        self.assertIn(b" 200 ", out)
        data = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertIn(data["state"], ("idle", "running", "ok", "ok_errors", "fail"))
        self.assertIn("phase", data)
        self.assertIn("log_tail", data)

    def test_real_build_progresses_through_all_phases(self):
        """Run once with the real latexmk/pdftoppm and observe the copy->latex->render order (only when the tools exist)."""
        import shutil as _sh

        if not (_sh.which("latexmk") and _sh.which("pdftoppm")):
            self.skipTest("latexmk/pdftoppm not available")
        seen = []
        stop = threading.Event()

        def poll():
            while not stop.is_set():
                ph = limn_build.state_snapshot(ps.DOCS[0])["phase"]
                if ph and (not seen or seen[-1] != ph):
                    seen.append(ph)
                time.sleep(0.01)

        t = threading.Thread(target=poll, daemon=True)
        t.start()
        res = ps.build_all(ps.DOCS[0])
        stop.set()
        t.join(2)
        self.assertEqual(res["state"], "ok")
        self.assertIn("latex", seen)
        self.assertIn("render", seen)
        self.assertTrue(limn_build.cur_pdf(ps.DOCS[0]).exists())
        aux = limn_build.cur_pages(ps.DOCS[0]) / "main.aux"
        self.assertTrue(aux.is_file(), "successful build must publish its matching .aux with PDF pages")
        labels = limn_meta.outline_labels(ps.DOCS[0])
        self.assertEqual(labels["build"], res["build"])
        self.assertEqual(
            [(row["number"], row["title"]) for row in labels["labels"][:2]], [("1", "Intro"), ("1.1", "Next")]
        )


if __name__ == "__main__":
    unittest.main()

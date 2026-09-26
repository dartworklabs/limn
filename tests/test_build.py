"""limn.build - the manuscript build, driven by the document and settings it is given (coding rule R5).

The server-level build behaviour (phases, history, the "manuscript modified" badge, --git-pull) is pinned through
the server in test_server.py and test_build_copy.py. Here the module is called directly, with no server, no run
arguments and no "current document": it must not read them, and two documents must be able to build at the same
time, each into its own folders. latexmk and pdftoppm are small fakes on PATH, so no TeX installation is needed.

Run: uv run pytest -q tests/test_build.py
"""
import ast
import os
import tempfile
import threading
import time
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from unittest import mock

from limn import build, files

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
        self.assertEqual(build.latex_errors(log), [{"line": 12, "msg": "Undefined control sequence."},
                                                   {"line": None, "msg": "Missing $ inserted."}])

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
            main.write_text("\\documentclass{article}\\begin{document}%s\\end{document}\n" % key.upper(), encoding="utf-8")
            self.docs[key] = PlainDoc(src=repo / key, main=main, dir=self.state / "docs" / key)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for name, text in (("latexmk", FAKE_LATEXMK), ("pdftoppm", FAKE_PDFTOPPM)):
            (bin_dir / name).write_text(text, encoding="utf-8")
            (bin_dir / name).chmod(0o755)
        (root / "rendezvous").mkdir()
        env = mock.patch.dict(os.environ, {"PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
                                           "LIMN_TEST_RENDEZVOUS": str(root / "rendezvous")})
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
        self.assertTrue(self.start(a, cfg).get("busy"))                 # one build at a time per document
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
                self.assertEqual(build.cur_pdf(D).read_bytes(), D.main.read_bytes())   # its own PDF, not the other's
                history = build.load_builds(D)
                self.assertEqual(list(history["by"]), [pages.name])
                self.assertEqual(history["by"][pages.name]["src_hash"], build.doc_fingerprint(D, self.state))
                self.assertEqual(sorted(p.name for p in D.build.iterdir() if p.suffix == ".tex"), [key + ".tex"])
        self.assertNotEqual(build.load_builds(a)["by"][build.cur_pages(a).name]["src_hash"],
                            build.load_builds(b)["by"][build.cur_pages(b).name]["src_hash"])


if __name__ == "__main__":
    unittest.main()

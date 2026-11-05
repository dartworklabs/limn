"""The instance shell and the server refuse the same dot-named --doc and --main paths.

Nothing under a part of the manuscript whose name starts with '.' is the manuscript (limn.platform.files.tree_part:
/api/source refuses such a file), so a document there could never be shown and its history would be a dot-named
folder's. `limn add`/`limn doc add` check a --doc path, and `limn add` a --main, before the config is written
(instance_documents.sh doc_check_path, main_check_dot); the server checks them again at startup
(limn.administration.serve_documents.parse_doc_arg's DocDotNamed, pick_documents). Both judge the path once symlinks are
resolved, the build root of the '::' form too. This test runs both on one tree and keeps their answers equal, as
test_text_suffixes.py does for the suffixes.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from limn.administration.serve_documents import (
    DocDotNamed,
    RunDocuments,
    doc_refusal_message,
    parse_doc_arg,
    pick_documents,
)

SHELL = Path(__file__).resolve().parents[2] / "src" / "limn" / "administration" / "instance_documents.sh"
TEX = "\\documentclass{article}\\begin{document}x\\end{document}\n"

# --doc paths (relative to the manuscript) and the dot-named part each is refused for (None: accepted).
DOC_PATHS = (
    ("paper/main.tex", None),
    (".::paper/main.tex", None),
    ("paper::main.tex", None),
    (".dotlink/main.tex", None),  # a dot-named link to paper/: resolved, the path has no dot-named part
    ("paper/.draft.tex", ".draft.tex"),
    (".Private/main.tex", ".Private"),
    ("a/.old/main.tex", ".old"),
    ("link/main.tex", ".Private"),  # link -> .Private
    ("paper/alias.tex", ".Private"),  # a file link into .Private
    (".Private::main.tex", ".Private"),
    ("link::main.tex", ".Private"),
    (".::.Private/main.tex", ".Private"),
    ("a::.old/main.tex", ".old"),
)
# --main names (at the top of the manuscript, as the shell requires) and the dot-named part each is refused for.
MAINS = (("top.tex", None), (".top.tex", ".top.tex"), ("alias-top.tex", ".Private"))


class DotNamedPaths(unittest.TestCase):
    """One manuscript tree with dot-named folders, files and links into them, read by the shell and the server."""

    def setUp(self):
        """paper/ and a/ with LaTeX files, .Private/main.tex, a/.old/main.tex, paper/.draft.tex, and links: link ->
        .Private, .dotlink -> paper, paper/alias.tex -> ../.Private/main.tex, alias-top.tex -> .Private/main.tex."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ms = Path(tmp.name).resolve()
        for rel in (
            "paper/main.tex",
            "paper/.draft.tex",
            ".Private/main.tex",
            "a/.old/main.tex",
            "top.tex",
            ".top.tex",
        ):
            (self.ms / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.ms / rel).write_text(TEX, encoding="utf-8")
        os.symlink(".Private", self.ms / "link")
        os.symlink("paper", self.ms / ".dotlink")
        os.symlink("../.Private/main.tex", self.ms / "paper" / "alias.tex")
        os.symlink(".Private/main.tex", self.ms / "alias-top.tex")

    def shell(self, call: str, *args: str) -> subprocess.CompletedProcess[str]:
        """Run call after sourcing instance_documents.sh with a die that prints its message and exits 3."""
        script = 'die() { echo "$*"; exit 3; }; source "$1"; shift; ' + call
        done = subprocess.run(
            ["bash", "-c", script, "bash", str(SHELL), *args], capture_output=True, text=True, timeout=30, check=False
        )
        self.assertIn(done.returncode, (0, 3), done.stderr)
        return done

    def test_a_doc_path_is_refused_alike(self):
        """Each --doc path: the server's parse_doc_arg and the shell's doc_check_path both take it, or both refuse it
        naming the same dot-named part."""
        for path, dot in DOC_PATHS:
            with self.subTest(path=path):
                server = parse_doc_arg("pp=Paper:" + path, self.ms)
                run = self.shell('DOC_KEY=pp DOC_PATH="$2" doc_check_path "$1"', str(self.ms), path)
                if dot is None:
                    self.assertIsInstance(server, dict, server)
                    self.assertEqual(run.returncode, 0, run.stdout)
                    continue
                self.assertIsInstance(server, DocDotNamed, server)
                assert isinstance(server, DocDotNamed)
                self.assertEqual(server.dot, dot)
                self.assertIn("(%s)" % dot, doc_refusal_message(server))
                self.assertEqual(run.returncode, 3, run.stdout)
                self.assertIn("has a dot-named part (%s)" % dot, run.stdout)

    def test_a_main_is_refused_alike(self):
        """Each --main: the server's pick_documents and the shell's main_check_dot both take it, or both refuse it
        naming the same dot-named part."""
        for name, dot in MAINS:
            with self.subTest(main=name):
                server = pick_documents(self.ms, [], name)
                run = self.shell('main_check_dot "$1" "$1/$2"', str(self.ms), name)
                if dot is None:
                    self.assertEqual(server, RunDocuments(None, self.ms / name))
                    self.assertEqual(run.returncode, 0, run.stdout)
                    continue
                self.assertNotIsInstance(server, RunDocuments)
                self.assertIn("has a dot-named part (%s)" % dot, str(server))
                self.assertEqual(run.returncode, 3, run.stdout)
                self.assertIn("has a dot-named part (%s)" % dot, run.stdout)


if __name__ == "__main__":
    unittest.main()

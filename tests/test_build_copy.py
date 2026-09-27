"""The build's first step copies the manuscript into the build folder; a failed copy must stop the build.

Compiling an incomplete or stale copy would publish a PDF that no longer matches the manuscript while
reporting success, so a copy failure has to end the build before latexmk runs.

Run: uv run pytest -q tests/test_build_copy.py
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from limn import build
from limn.build import CopyFailed
from limn.web.errors import build_failure_log

from helpers import Base, ps, set_config

# run_logged's result if latexmk ran and produced nothing - keeps a regressed build on the assertion path.
NO_PDF = (1, "", False)

FAILING_RSYNC = """#!/bin/sh
echo "rsync: [sender] send_files failed to open \\"main.tex\\": Permission denied (13)" >&2
echo "rsync error: some files/attrs were not transferred (code 23)" >&2
exit 23
"""


class ManuscriptCopy(Base):
    """What _build() (limn.build.compile_tex) does when copying the manuscript into the build folder goes wrong."""

    def setUp(self):
        """Put an rsync on PATH that fails the way a partial transfer does (exit 23)."""
        super().setUp()
        self.bin = tempfile.TemporaryDirectory()
        rsync = Path(self.bin.name) / "rsync"
        rsync.write_text(FAILING_RSYNC, encoding="utf-8")
        rsync.chmod(0o755)
        path = self.bin.name + os.pathsep + os.environ.get("PATH", "")
        env = mock.patch.dict(os.environ, {"PATH": path})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        """Remove the fake rsync."""
        self.bin.cleanup()
        super().tearDown()

    def test_build_stops_before_latexmk_when_rsync_fails(self):
        """A non-zero rsync exit fails the build with the copy error and never compiles the partial copy."""
        with mock.patch.object(build, "run_logged", return_value=NO_PDF) as compile_step:
            res = ps._build(ps.DOCS[0])
        compile_step.assert_not_called()
        self.assertIsInstance(res, CopyFailed)
        log = build_failure_log(res)
        self.assertTrue(log.startswith("원고 사본을 만들지 못했습니다"), log)

    def test_copy_error_names_the_rsync_exit_and_its_last_message(self):
        """The build log shows why the copy failed so the owner can fix permissions or disk space."""
        with mock.patch.object(build, "run_logged", return_value=NO_PDF):
            res = ps._build(ps.DOCS[0])
        self.assertIsInstance(res, CopyFailed)
        self.assertIn("23", res.error)
        self.assertIn("some files/attrs were not transferred", build_failure_log(res))


def tree(root: Path) -> set[str]:
    """Every file under root as a POSIX path relative to it."""
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


class StateFolderCopy(unittest.TestCase):
    """copy_manuscript leaves out the state folder when --state-dir puts it inside the copied folder: people.json,
    tokens.json and the logs are not manuscript, and the build folder usually lies in it (the copy would nest itself
    one level deeper on every build). Each case runs with rsync and with the copytree fallback."""

    def setUp(self):
        """A manuscript with main.tex and a same-named folder deeper down (sub/limn-state/keep.tex), which is
        manuscript and must be copied."""
        self.tmp = tempfile.TemporaryDirectory()
        self.src = Path(self.tmp.name).resolve() / "ms"
        (self.src / "sub" / "limn-state").mkdir(parents=True)
        (self.src / "main.tex").write_text("x\n", encoding="utf-8")
        (self.src / "sub" / "limn-state" / "keep.tex").write_text("k\n", encoding="utf-8")

    def tearDown(self):
        """Remove the manuscript."""
        self.tmp.cleanup()

    def state_at(self, rel: str) -> Path:
        """A state folder at src/rel holding people.json, tokens.json and audit.jsonl."""
        state = self.src / rel
        state.mkdir(parents=True)
        for name in ("people.json", "tokens.json", "audit.jsonl"):
            (state / name).write_text("{}\n", encoding="utf-8")
        return state

    def copies(self, state: Path, dest: Path):
        """Copy twice into dest with rsync (when installed) and then without it -> [(how, files in dest)]."""
        out = []
        ways = [("copytree", None)]
        if shutil.which("rsync"):
            ways.insert(0, ("rsync", shutil.which("rsync")))
        for how, rsync in ways:
            shutil.rmtree(dest, ignore_errors=True)
            dest.mkdir(parents=True)
            with mock.patch.object(build.shutil, "which", return_value=rsync):
                build.copy_manuscript(self.src, dest, state)
                build.copy_manuscript(self.src, dest, state)
            out.append((how, tree(dest)))
        return out

    def test_the_state_folder_and_the_build_folder_in_it_are_not_copied(self):
        """State at <ms>/limn-state with the build folder inside it: the copy holds the manuscript (the deeper
        same-named folder included) and nothing of the state folder, however often it runs."""
        state = self.state_at("limn-state")
        for how, files in self.copies(state, state / "build"):
            self.assertEqual(files, {"main.tex", "sub/limn-state/keep.tex"}, how)

    def test_a_nested_state_folder_whose_name_has_pattern_characters_is_not_copied(self):
        """State at <ms>/sub/st[a]te*? - rsync must read the name literally: that folder is left out, and sub/state-x,
        which the name read as a pattern would match, is copied."""
        state = self.state_at("sub/st[a]te*?")
        (self.src / "sub" / "state-x").mkdir()
        (self.src / "sub" / "state-x" / "b.tex").write_text("b\n", encoding="utf-8")
        for how, files in self.copies(state, Path(self.tmp.name) / "build"):
            self.assertEqual(files, {"main.tex", "sub/limn-state/keep.tex", "sub/state-x/b.tex"}, how)

    def test_a_link_into_the_state_folder_copies_none_of_it(self):
        """A linked folder that leads into the state folder brings none of its files into the copy (rsync copies the
        link itself; the fallback follows links, so it must skip the folder's contents)."""
        state = self.state_at("limn-state")
        (self.src / "figs").symlink_to(state, target_is_directory=True)
        for how, files in self.copies(state, Path(self.tmp.name) / "build"):
            self.assertFalse({f for f in files if f.endswith((".json", ".jsonl"))}, how)
            self.assertIn("main.tex", files, how)

    def test_a_state_folder_outside_the_manuscript_changes_nothing(self):
        """With the state folder elsewhere (the default), a folder named like it inside the manuscript is copied."""
        state = Path(self.tmp.name) / "state"
        state.mkdir()
        (self.src / "limn-state").mkdir()
        (self.src / "limn-state" / "a.tex").write_text("a\n", encoding="utf-8")
        for how, files in self.copies(state, state / "build"):
            self.assertEqual(files, {"main.tex", "limn-state/a.tex", "sub/limn-state/keep.tex"}, how)


class StateFolderBuild(Base):
    """compile_tex hands the run's state folder to the copy: a build of an instance whose --state-dir lies inside the
    manuscript never copies it."""

    def test_a_build_leaves_the_state_folder_out_of_its_copy(self):
        """With C.state = <ms>/limn-state (people.json in it), the build copy holds main.tex and no state file."""
        set_config(state=self.src / "limn-state")
        ps.C.state.mkdir()
        (ps.C.state / "people.json").write_text("{}\n", encoding="utf-8")
        with mock.patch.object(build, "run_logged", return_value=NO_PDF):
            ps._build(ps.DOCS[0])
        files = tree(ps.DOCS[0].build)
        self.assertIn("main.tex", files)
        self.assertFalse([f for f in files if "people.json" in f or f.startswith("limn-state")], files)


if __name__ == "__main__":
    unittest.main()

"""limn.platform.git - how every git process is started: its environment (no GIT_* of the server's, GIT_TERMINAL_PROMPT=0),
no stdin, no controlling terminal, list arguments only; and that every git call site of the package goes through it.

The call sites are driven for real against a temporary repository while a fake `git` first on PATH records what each
process was given and then runs the real git. The server's environment carries GIT_DIR, GIT_WORK_TREE and friends
pointing nowhere, so a call that leaked them would also fail its answer.

Run: uv run pytest -q src/limn/platform/tests/test_gitrun.py
"""

import ast
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from limn.administration import token_files
from limn.builds import engine as build_engine
from limn.platform import git as gitrun
from limn.platform.git import KEPT_GIT_VARS, git_command, git_env
from limn.revisions import core as revisions
from limn.runtime import startup
from limn.sync import run as gitsync
from limn.sync.rules import UpToDate

SRC = Path(gitrun.__file__).resolve().parents[1]

# The server's environment in these tests: variables that would send git elsewhere, inject configuration or prompt.
LEAKY = {
    "GIT_DIR": "/nonexistent/other.git",
    "GIT_WORK_TREE": "/nonexistent",
    "GIT_INDEX_FILE": "/nonexistent/index",
    "GIT_OBJECT_DIRECTORY": "/nonexistent/objects",
    "GIT_CONFIG_PARAMETERS": "'core.hookspath=/nonexistent'",
    "GIT_ASKPASS": "/bin/false",
    "GIT_TERMINAL_PROMPT": "1",
}
KEPT = {"GIT_SSH_COMMAND": "ssh -o BatchMode=yes", "SSH_AUTH_SOCK": "/tmp/agent.sock", "LC_MESSAGES": "C"}

FAKE_GIT = """#!{python}
import json, os, sys
st, null = os.fstat(0), os.stat(os.devnull)
record = {{
    "argv": sys.argv[1:],
    "env": dict(os.environ),
    "stdin_devnull": (st.st_dev, st.st_ino) == (null.st_dev, null.st_ino),
    "own_session": os.getsid(0) == os.getpid(),
}}
with open({log!r}, "a", encoding="utf-8") as f:
    f.write(json.dumps(record) + "\\n")
os.execv({git!r}, [{git!r}, *sys.argv[1:]])
"""


class Environment(unittest.TestCase):
    """git_env and git_command on their own."""

    def test_drops_git_variables_but_the_ssh_transport_and_turns_prompts_off(self):
        """Every GIT_* goes except KEPT_GIT_VARS; GIT_TERMINAL_PROMPT is 0 even when the server set it to 1; the rest
        of the environment and the extra variables pass as given."""
        env = git_env({**LEAKY, **KEPT, "GIT_SSH": "/usr/bin/ssh", "HOME": "/home/a", "PATH": "/bin"}, {"LC_ALL": "C"})
        self.assertEqual(
            env,
            {
                **KEPT,
                "GIT_SSH": "/usr/bin/ssh",
                "HOME": "/home/a",
                "PATH": "/bin",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C",
            },
        )
        self.assertEqual(KEPT_GIT_VARS, {"GIT_SSH_COMMAND", "GIT_SSH", "GIT_SSH_VARIANT"})

    def test_reads_the_process_environment_by_default(self):
        """Without an environ argument the server's own environment is the source."""
        with mock.patch.dict(os.environ, {"GIT_DIR": "/x", "LIMN_PROBE": "1"}):
            env = git_env()
        self.assertNotIn("GIT_DIR", env)
        self.assertEqual(env["LIMN_PROBE"], "1")

    def test_a_command_is_a_list_never_a_string(self):
        """git_command prefixes git to a list and refuses a string (a defect: nothing may build a command line)."""
        self.assertEqual(git_command(["log", "-1"]), ["git", "log", "-1"])
        with self.assertRaises(TypeError):
            git_command("log -1")


class GitOutcome(unittest.TestCase):
    """The tuple adapter preserves process output and normalizes execution failures."""

    def test_success_preserves_stdout_and_stderr(self):
        """A real successful Git command retains text output including its newline."""
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(gitrun.git(["rev-parse", "--sq-quote", "a b"], directory), (0, " 'a b'\n", ""))

    def test_nonzero_preserves_stdout_and_stderr(self):
        """A real failed Git command keeps its exit code and diagnostic text."""
        with tempfile.TemporaryDirectory() as directory:
            args = ["--no-pager", "-c", "alias.fail=!printf out; printf err >&2; exit 7", "fail"]
            self.assertEqual(gitrun.git(args, directory), (7, "out", "err"))

    def test_start_failure_returns_empty_execution_failure(self):
        """An absent working directory produces the same empty outcome as a missing executable."""
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(gitrun.git(["status"], Path(directory) / "missing"), (None, "", ""))

    def test_timeout_discards_partial_output(self):
        """Timed-out processes expose no partial output through the outcome adapter."""
        error = subprocess.TimeoutExpired(["git", "status"], 30, output="partial", stderr="partial error")
        with mock.patch.object(gitrun.subprocess, "run", side_effect=error):
            self.assertEqual(gitrun.git(["status"], Path.cwd()), (None, "", ""))

    def test_invalid_command_remains_a_programming_error(self):
        """The execution-failure outcome must not swallow command-shape defects."""
        with self.assertRaises(TypeError):
            gitrun.git("status", Path.cwd())


class NoOtherGitCall(unittest.TestCase):
    """Production modules start git only through limn.platform.git; repository setup in tests is outside this guard."""

    def test_no_module_but_gitrun_spells_a_git_command(self):
        """Production modules outside gitrun.py build git commands through git_command(...), never list literals."""
        found = []
        for path in sorted(SRC.rglob("*.py")):
            if path.relative_to(SRC).as_posix() == "platform/git.py" or "tests" in path.relative_to(SRC).parts:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                first = node.elts[0] if isinstance(node, ast.List) and node.elts else None
                if isinstance(first, ast.Constant) and first.value == "git":
                    found.append("%s:%d" % (path.relative_to(SRC), node.lineno))
        self.assertEqual(found, [])

    def test_gitrun_never_uses_a_shell(self):
        """gitrun.py's process calls pass no shell argument."""
        tree = ast.parse(Path(gitrun.__file__).read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n.func).startswith("subprocess.")]
        self.assertEqual(sorted(ast.unparse(c.func) for c in calls), ["subprocess.Popen", "subprocess.run"])
        for call in calls:
            self.assertNotIn("shell", {k.arg for k in call.keywords})


@unittest.skipUnless(shutil.which("git"), "git not available")
class CallSites(unittest.TestCase):
    """Each git call site of the package, run against a real repository through a recording fake git."""

    def setUp(self):
        """A repository with two commits of main.tex tracking a local bare origin (no network); a fake git first on
        PATH; the server's environment carrying LEAKY and KEPT; and stdin replaced by a pipe, so a child that inherited
        it would not see /dev/null."""
        real_git = shutil.which("git")
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name).resolve()
        self.repo, self.log, fake = root / "repo", root / "git.log", root / "bin"
        fake.mkdir()
        (fake / "git").write_text(FAKE_GIT.format(python=sys.executable, log=str(self.log), git=real_git))
        (fake / "git").chmod(0o755)
        self.repo.mkdir()
        self.origin = root / "origin.git"
        clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}

        def git(*args):
            """The real git in the repository, set up without the fake one or the leaky environment."""
            return subprocess.run(
                [real_git, *args], cwd=self.repo, env=clean, check=True, capture_output=True, text=True
            )

        git("init", "--quiet", "-b", "main")
        git("config", "user.email", "alice@example.com")
        git("config", "user.name", "Alice")
        self.commits = []
        for text in ("one\n", "two\n"):
            (self.repo / "main.tex").write_text(text)
            git("add", "main.tex")
            git("commit", "-qm", text)
            self.commits.append(git("rev-parse", "HEAD").stdout.strip())
        git("clone", "--quiet", "--bare", str(self.repo), str(self.origin))
        git("remote", "add", "origin", str(self.origin))
        git("fetch", "--quiet", "origin")
        git("branch", "--quiet", "--set-upstream-to=origin/main")
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.addCleanup(self.tmp.cleanup)
        stack.enter_context(
            mock.patch.dict(os.environ, {**LEAKY, **KEPT, "PATH": "%s:%s" % (fake, os.environ["PATH"])})
        )
        saved = os.dup(0)
        read, write = os.pipe()
        os.dup2(read, 0)
        os.close(read)
        stack.callback(os.close, write)
        stack.callback(os.close, saved)
        stack.callback(os.dup2, saved, 0)

    def records(self):
        """Every git process the fake git saw so far, in order."""
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def assert_hygienic(self, what, call):
        """Run call(); it must start at least one git, and every git it starts has no LEAKY variable,
        GIT_TERMINAL_PROMPT=0, the KEPT ones, /dev/null as stdin and a session of its own. Returns call's result."""
        before = len(self.records())
        result = call()
        started = self.records()[before:]
        self.assertTrue(started, "%s started no git" % what)
        for rec in started:
            with self.subTest(what, argv=rec["argv"]):
                self.assertEqual((set(LEAKY) - {"GIT_TERMINAL_PROMPT"}) & set(rec["env"]), set())
                self.assertEqual(rec["env"]["GIT_TERMINAL_PROMPT"], "0")
                self.assertEqual({k: rec["env"].get(k) for k in KEPT}, KEPT)
                self.assertTrue(rec["stdin_devnull"])
                self.assertTrue(rec["own_session"])
        return result

    def test_every_call_site_runs_a_clean_git(self):
        """run_git, gitrun.git and git_exec, the history and the streamed diff, the --git-pull steps, the build's
        head, the startup label's origin URL and the token file's repository check each start git cleanly - and,
        despite GIT_DIR pointing nowhere, read the right repository."""
        repo, (first, second) = self.repo, self.commits
        doc = SimpleNamespace(shows_revisions=True, main=repo / "main.tex", src=repo)

        done = self.assert_hygienic("run_git", lambda: gitrun.run_git(["rev-parse", "--show-toplevel"], repo, 10))
        self.assertEqual(done.stdout.strip(), str(repo))
        rc, out, _ = self.assert_hygienic("gitrun.git", lambda: gitrun.git(["rev-parse", "HEAD"], repo))
        self.assertEqual((rc, out.strip()), (0, second))
        ran = self.assert_hygienic("git_exec", lambda: revisions.git_exec(["cat-file", "-t", first], repo, 10, 4096))
        self.assertEqual(ran[:2], (0, b"commit\n"))

        history = self.assert_hygienic("revision_history", lambda: revisions.revision_history(doc))
        self.assertEqual([r["id"] for r in history["revisions"]], [second, first])
        diff = self.assert_hygienic("revision_diff", lambda: revisions.revision_diff(doc, second, None, None))
        self.assertIn("+two", diff["diff"])
        changes = self.assert_hygienic(
            "revision_changes", lambda: revisions.revision_changes(repo, first, second, ["main.tex"])
        )
        self.assertEqual([c.new_path for c in changes], ["main.tex"])

        outcome = self.assert_hygienic("gitsync.pull", lambda: gitsync.pull(repo, False, gitrun.git))
        self.assertEqual(outcome, UpToDate(second))

        state = Path(self.tmp.name) / "state"
        (state / "pages-1").mkdir(parents=True)
        head = self.assert_hygienic(
            "build_engine.commit_pages",
            lambda: build_engine.commit_pages(SimpleNamespace(dir=state, src=repo), state / "pages-1"),
        )
        self.assertEqual(head, second[: len(head)])
        url = self.assert_hygienic("startup.git_remote_url", lambda: startup.git_remote_url(repo))
        self.assertEqual(url, str(self.origin))
        held = self.assert_hygienic(
            "token_files.git_tree_holding", lambda: token_files.git_tree_holding(repo / "cfg" / "x.token")
        )
        self.assertEqual(held, (str(repo), None))

    def test_the_token_file_check_reads_messages_in_the_c_locale(self):
        """git_tree_holding still reads git's messages in the C locale (LC_ALL=C on top of the clean environment)."""
        self.assert_hygienic(
            "token_files.git_tree_holding", lambda: token_files.git_tree_holding(self.repo / "x.token")
        )
        self.assertEqual(self.records()[-1]["env"]["LC_ALL"], "C")


if __name__ == "__main__":
    unittest.main()

"""limn.sync.run - the --git-pull and remote-main watch shell: the pull against real temporary repositories, the shared
pull of several documents, and the watch's rounds and status, driven with no server.

The pure rules it applies are src/limn/sync/tests/test_pull.py. The server's wiring (a build's `pull`, GET /api/meta's sync, the
builds a round starts) is pinned through server.py at the end of this file (GitPullBuildIntegration,
AutomaticMainSync).

Run: uv run pytest -q src/limn/sync/tests/test_gitsync.py
"""

import ast
import contextlib
import inspect
import io
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from limn.builds import artifacts as limn_build, engine as build_engine
from limn.builds.artifacts import BuildOk
from limn.platform import git as gitrun
from limn.runtime.documents import Doc
from limn.security.access import LOCAL_ACTOR
from limn.sync import run as gitsync
from limn.sync.rules import Pulled, PullFailed, PullSkipped, UpToDate
from limn.sync.run import PullShare, SyncWatch, pull, repo_pull

from helpers import Base, needs_tex, ps, set_config

GITSYNC_PY = Path(gitsync.__file__)
A, B = "a" * 40, "b" * 40


class ModuleBoundary(unittest.TestCase):
    """gitsync.py sits below the server: settings, documents, runner and clock come in as arguments."""

    def test_imports_no_server_or_http_layer(self):
        """Of limn only limn.sync.rules (the rules) and common build state;
        no HTTP import. It runs git only through the runner it is given."""
        tree = ast.parse(GITSYNC_PY.read_text(encoding="utf-8"))
        modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        modules |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertEqual({m for m in modules if m.startswith("limn")}, {"limn.sync.rules"})
        self.assertFalse({"http", "http.server", "urllib", "subprocess"} & modules)

    def test_reads_no_server_global(self):
        """No run-argument object, document list or server helper is named in the module."""
        tree = ast.parse(GITSYNC_PY.read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"C", "DOCS", "cur_doc", "build_async", "multi_doc", "now_str", "_git"})

    def test_git_runs_without_a_shell(self):
        """The runner the server passes (limn.platform.git.git) goes through limn.platform.git.run_git, which takes a list and
        never a shell - the security contract of every pull step, whose arguments hold no request input
        (src/limn/platform/tests/test_gitrun.py pins run_git itself)."""
        src = inspect.getsource(gitrun.git)
        # The calls are read from the AST, not the source text, so the check does not depend on the call's layout.
        calls = {ast.unparse(n.func) for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)}
        self.assertIn("run_git", calls)
        self.assertFalse({"subprocess.run", "subprocess.Popen"} & calls)
        self.assertNotIn("shell=True", src)


class RealRepository(unittest.TestCase):
    """pull() against a temporary bare upstream and its clones - no real manuscript repository is used."""

    def setUp(self):
        """A bare upstream with one commit on main, HEAD pointing at main."""
        if not shutil.which("git"):
            self.skipTest("git not available")
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bare = self.root / "upstream.git"
        self._run(["git", "init", "--quiet", "--bare", str(self.bare)], self.root)
        seed = self.root / "_seed"
        self._run(["git", "clone", "--quiet", str(self.bare), str(seed)], self.root)
        self._configure(seed)
        self._run(["git", "checkout", "--quiet", "-b", "main"], seed)
        (seed / "f.txt").write_text("seed\n", encoding="utf-8")
        self._run(["git", "add", "-A"], seed)
        self._run(["git", "commit", "--quiet", "-m", "seed"], seed)
        self._run(["git", "push", "--quiet", "-u", "origin", "main"], seed)
        self._run(["git", "symbolic-ref", "HEAD", "refs/heads/main"], self.bare)

    def tearDown(self):
        """Remove the repositories."""
        self.tmp.cleanup()

    def _run(self, args, cwd):
        """Run a setup command; its failure fails the test with git's output."""
        r = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, timeout=30, check=False)
        if r.returncode != 0:
            raise AssertionError("%s failed:\n%s%s" % (args, r.stdout, r.stderr))
        return r.stdout

    def _configure(self, d):
        """A committer identity for clone d."""
        self._run(["git", "config", "user.email", "t@example.com"], d)
        self._run(["git", "config", "user.name", "T"], d)

    def _clone(self, name):
        """A configured clone of the upstream."""
        d = self.root / name
        self._run(["git", "clone", "--quiet", str(self.bare), str(d)], self.root)
        self._configure(d)
        return d

    def _head(self, d):
        """d's HEAD commit."""
        return self._run(["git", "rev-parse", "HEAD"], d).strip()

    def _push_change(self, name, file="f.txt"):
        """Commit and push a change from another clone; returns the new upstream commit."""
        other = self._clone(name)
        (other / file).write_text("from %s\n" % name, encoding="utf-8")
        self._run(["git", "add", "-A"], other)
        self._run(["git", "commit", "--quiet", "-m", name], other)
        self._run(["git", "push", "--quiet"], other)
        return self._head(other)

    def test_not_git_outside_a_repository(self):
        """A plain folder is skipped with no heads; its record is the contract's not_git object."""
        plain = self.root / "plain"
        plain.mkdir()
        self.assertEqual(pull(plain, False, gitrun.git), PullSkipped("not_git", None))

    def test_pulled_when_upstream_advanced(self):
        """A new upstream commit is fast-forwarded: Pulled from the old HEAD to the pushed commit."""
        d = self._clone("c1")
        before = self._head(d)
        after = self._push_change("c2")
        self.assertEqual(pull(d, False, gitrun.git), Pulled(before, after))
        self.assertEqual(self._head(d), after)

    def test_up_to_date_when_no_new_commits(self):
        """Nothing new upstream: UpToDate at HEAD."""
        d = self._clone("c3")
        self.assertEqual(pull(d, False, gitrun.git), UpToDate(self._head(d)))

    def test_main_only_skips_a_feature_branch(self):
        """The watch (main_only) never fast-forwards another branch, even one with an upstream."""
        d = self._clone("feature")
        self._run(["git", "checkout", "--quiet", "-b", "feature"], d)
        self._run(["git", "push", "--quiet", "-u", "origin", "feature"], d)
        self.assertEqual(pull(d, True, gitrun.git), PullSkipped("not_main", self._head(d)))

    def test_main_only_pulls_main(self):
        """On main tracking origin/main the watch fast-forwards like a build's pull."""
        d = self._clone("c9")
        before = self._head(d)
        after = self._push_change("c10")
        self.assertEqual(pull(d, True, gitrun.git), Pulled(before, after))

    def test_dirty_tree_is_skipped_and_left_alone(self):
        """A modified tracked file stops the pull before the merge; the file keeps its local text."""
        d = self._clone("c4")
        self._push_change("c4b")
        (d / "f.txt").write_text("locally modified\n", encoding="utf-8")
        before = self._head(d)
        self.assertEqual(pull(d, False, gitrun.git), PullSkipped("dirty", before))
        self.assertEqual((d / "f.txt").read_text(encoding="utf-8"), "locally modified\n")

    def test_diverged_history_is_skipped(self):
        """A local commit plus a different upstream commit cannot fast-forward: skipped, HEAD unchanged."""
        d = self._clone("c5")
        (d / "f.txt").write_text("local change\n", encoding="utf-8")
        self._run(["git", "add", "-A"], d)
        self._run(["git", "commit", "--quiet", "-m", "local-only"], d)
        self._push_change("c6", "g.txt")
        before = self._head(d)
        self.assertEqual(pull(d, False, gitrun.git), PullSkipped("diverged", before))
        self.assertEqual(self._head(d), before)

    def test_no_upstream_is_skipped(self):
        """A branch without @{u} is skipped."""
        d = self._clone("c7")
        self._run(["git", "checkout", "--quiet", "-b", "untracked"], d)
        self.assertEqual(pull(d, False, gitrun.git), PullSkipped("no_upstream", self._head(d)))

    def test_repo_root_found_from_a_subfolder(self):
        """--manuscript may be a folder inside the repository."""
        d = self._clone("c8")
        sub = d / "manuscript" / "1st"
        sub.mkdir(parents=True)
        self.assertEqual(pull(sub, False, gitrun.git), UpToDate(self._head(d)))

    def test_fetch_failure_when_the_remote_is_gone(self):
        """An unreachable remote is error:fetch_failed, and nothing else is tried."""
        d = self._clone("c11")
        shutil.rmtree(self.bare)
        self.assertEqual(pull(d, False, gitrun.git), PullFailed("fetch_failed", self._head(d)))


class ScriptedGit:
    """A git runner answering each subcommand from a table, recording the calls (for answers a real repository
    cannot give on demand: a timeout, a failing status)."""

    def __init__(self, answers):
        """answers: {command after "-C <dir>": (rc, stdout, stderr)}; a command missing from it fails the test."""
        self.answers, self.calls = answers, []

    def __call__(self, args, cwd):
        """The scripted answer for the command after -C <dir>."""
        command = " ".join(args[2:])
        self.calls.append(command)
        return self.answers[command]


SCRIPT = {
    "rev-parse --show-toplevel": (0, "/repo\n", ""),
    "rev-parse HEAD": (0, A + "\n", ""),
    "fetch --quiet": (0, "", ""),
    "rev-parse --abbrev-ref @{u}": (0, "origin/main\n", ""),
    "status --porcelain --untracked-files=no": (0, "", ""),
    "merge --ff-only @{u}": (0, "", ""),
}


class ScriptedPull(unittest.TestCase):
    """pull() for the git answers a temporary repository cannot produce on demand."""

    def test_fetch_timeout_stops_the_pull(self):
        """A fetch that did not finish (rc None) is error:fetch_timeout; no later step runs."""
        git = ScriptedGit(dict(SCRIPT, **{"fetch --quiet": (None, "", "")}))
        self.assertEqual(pull(Path("/repo"), False, git), PullFailed("fetch_timeout", A))
        self.assertEqual(git.calls, ["rev-parse --show-toplevel", "rev-parse HEAD", "fetch --quiet"])

    def test_status_failure_is_an_error_not_a_skip(self):
        """git status failing is error:status_failed; nothing is merged."""
        git = ScriptedGit(dict(SCRIPT, **{"status --porcelain --untracked-files=no": (128, "", "fatal")}))
        self.assertEqual(pull(Path("/repo"), False, git), PullFailed("status_failed", A))
        self.assertNotIn("merge --ff-only @{u}", git.calls)

    def test_missing_git_reads_as_not_git(self):
        """A git that cannot start (rc None everywhere) is skipped:not_git - the pull never raises."""
        self.assertEqual(pull(Path("/nowhere"), False, lambda args, cwd: (None, "", "")), PullSkipped("not_git", None))


class FakeClock:
    """A clock the test moves by hand."""

    def __init__(self, now=1000.0):
        """Start at `now` seconds."""
        self.now = now

    def __call__(self):
        """The current fake time."""
        return self.now


class SharedPull(unittest.TestCase):
    """repo_pull(): one pull per repository for several documents, every build for one."""

    def test_one_document_pulls_every_time_and_records_nothing(self):
        """Unshared: each call runs the pull; the share is untouched."""
        share, runs = PullShare(), []
        run = lambda: runs.append(1) or UpToDate(A)  # noqa: E731
        self.assertEqual(repo_pull(share, False, run, FakeClock()), repo_pull(share, False, run, FakeClock()))
        self.assertEqual(len(runs), 2)
        self.assertIsNone(share.last)

    def test_several_documents_reuse_a_recent_pull(self):
        """Within the window the last outcome is reused with shared=True; after it, a new pull runs."""
        share, runs, clock = PullShare(), [], FakeClock()
        run = lambda: runs.append(1) or Pulled(A, B)  # noqa: E731
        first = repo_pull(share, True, run, clock)
        self.assertEqual(first, {"state": "ok", "reason": None, "head_before": A, "head_after": B})
        clock.now += gitsync.PULL_SHARE_S - 1
        self.assertEqual(repo_pull(share, True, run, clock), dict(first, shared=True))
        clock.now += 1
        self.assertNotIn("shared", repo_pull(share, True, run, clock))
        self.assertEqual(len(runs), 2)


class FakeDoc:
    """A document as the watch reads it: a state folder, a build lock, a build state, and whether it builds from source
    (only such a document is pulled for and rebuilt)."""

    def __init__(self, folder, builds_from_source=True, built=None, state="idle"):
        """builds_from_source: False for a view-only PDF; built: head.txt's text, or None for no head.txt."""
        self.dir, self.builds_from_source = Path(folder), builds_from_source
        self.lock, self.bstate_lock = threading.Lock(), threading.Lock()
        self.bstate = {"state": state}
        self.dir.mkdir(parents=True, exist_ok=True)
        if built is not None:
            (self.dir / "head.txt").write_text(built, encoding="utf-8")


class Watch(unittest.TestCase):
    """SyncWatch: a round's pull, the builds it starts, its status, and the loop."""

    def setUp(self):
        """Two LaTeX documents (one built from an old commit) and a view-only PDF, in a temporary folder."""
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.ms = FakeDoc(root / "ms", built="aaaaaaa")
        self.hl = FakeDoc(root / "hl", built="bbbbbbb")
        self.pdf = FakeDoc(root / "pdf", builds_from_source=False)
        self.docs = [self.ms, self.hl, self.pdf]
        self.started = []
        self.last_failed = limn_build.last_build_failed

    def tearDown(self):
        """Remove the folder."""
        self.tmp.cleanup()

    def once(self, watch, outcome, share=None, enabled=True):
        """One round with a pull that returns `outcome`, a fixed stamp and clock; builds are recorded, not run."""
        return watch.once(
            self.docs, enabled, lambda: outcome, share or PullShare(), self.started.append, lambda: "T", FakeClock(5.0)
        )

    def test_disabled_without_git_pull(self):
        """Without --git-pull the status and a round are just "disabled"; nothing is pulled."""
        watch = SyncWatch()
        self.assertEqual(watch.status(self.docs, False, self.last_failed), {"state": "disabled"})
        self.assertEqual(watch.once(self.docs, False, None, PullShare(), None, None, None), {"state": "disabled"})

    def test_up_to_date_rebuilds_only_the_document_behind(self):
        """Nothing new upstream: only the LaTeX document built from another commit is rebuilt; the pull is shared."""
        watch, share = SyncWatch(), PullShare()
        out = self.once(watch, UpToDate(B), share)
        self.assertEqual(self.started, [self.ms])
        self.assertEqual(
            out, {"state": "updating", "reason": None, "head_before": B, "head_after": B, "checked_at": "T"}
        )
        self.assertEqual((share.last, share.at), (UpToDate(B), 5.0))
        self.assertEqual(watch.status(self.docs, True, self.last_failed)["state"], "updating")  # ms is still behind

    def test_fast_forward_rebuilds_every_latex_document(self):
        """After Pulled every LaTeX document is rebuilt, the view-only PDF never."""
        self.once(SyncWatch(), Pulled(A, B))
        self.assertEqual(self.started, [self.ms, self.hl])

    def test_one_pass_documents_rebuild_after_pull(self):
        """An iterable consumed while claiming locks still supplies documents for rebuild decisions."""
        watch = SyncWatch()
        out = watch.once(
            iter(self.docs), True, lambda: Pulled(A, B), PullShare(), self.started.append, lambda: "T", FakeClock(5.0)
        )
        self.assertEqual(self.started, [self.ms, self.hl])
        self.assertEqual(out["state"], "updating")

    def test_refusal_is_recorded_and_builds_nothing(self):
        """A refused pull replaces the status with blocked/error and its reason."""
        watch = SyncWatch()
        out = self.once(watch, PullFailed("fetch_failed", A))
        self.assertEqual(self.started, [])
        self.assertEqual(watch.status(self.docs, True, self.last_failed), out)
        self.assertEqual((out["state"], out["reason"]), ("error", "fetch_failed"))

    def test_a_running_build_defers_the_round_and_keeps_the_heads(self):
        """A held build lock defers without pulling; the previous heads stay in the status; every lock is released."""
        watch = SyncWatch()
        self.once(watch, PullSkipped("dirty", A))
        self.hl.lock.acquire()
        try:
            out = self.once(watch, None)
        finally:
            self.hl.lock.release()
        self.assertEqual(out, {"state": "deferred", "reason": "building", "checked_at": "T"})
        self.assertEqual(watch.status(self.docs, True, self.last_failed)["head_after"], A)
        self.assertFalse(self.ms.lock.locked())

    def test_status_settles_when_every_document_reached_the_commit(self):
        """ "updating" becomes "current" once each LaTeX document's head.txt names the pulled commit."""
        watch = SyncWatch()
        self.once(watch, UpToDate(B))
        (self.ms.dir / "head.txt").write_text("bbbbbbb", encoding="utf-8")
        self.assertEqual(
            (watch.status(self.docs, True, self.last_failed)["state"], watch.record["state"]), ("current", "current")
        )

    def test_status_reports_a_failed_build(self):
        """A document still behind whose build failed turns the status to error/build_failed."""
        watch = SyncWatch()
        self.once(watch, UpToDate(B))
        self.ms.bstate["state"] = "fail"
        status = watch.status(self.docs, True, self.last_failed)
        self.assertEqual((status["state"], status["reason"]), ("error", "build_failed"))

    def test_watch_survives_a_crashing_round(self):
        """A round that raises is printed and recorded as error/unexpected; the loop stops when told."""
        watch, stop = SyncWatch(), threading.Event()

        def crash():
            """Stop after this round, then fail."""
            stop.set()
            raise RuntimeError("boom")

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            watch.watch(stop, 60, crash, lambda: "T")
        self.assertIn("RuntimeError: boom", err.getvalue())
        self.assertEqual(
            watch.record,
            {"state": "error", "reason": "unexpected", "checked_at": "T", "head_before": None, "head_after": None},
        )

    def test_deferred_round_retries_soon(self):
        """A deferred round waits min(DEFERRED_RETRY_S, every) before the next, not the full interval."""
        watch, stop, rounds = SyncWatch(), threading.Event(), []

        def deferred_then_stop():
            """Deferred first, then stop the loop."""
            rounds.append(1)
            if len(rounds) == 2:
                stop.set()
            return {"state": "deferred"}

        watch.watch(stop, 0.05, deferred_then_stop, lambda: "T")
        self.assertEqual(len(rounds), 2)


# ---------------------------------------------------------------- through server.py's wiring
#
# --git-pull inside a build, and the remote-main watch as the server wires it. These classes load server.py
# (helpers.ps) and drive the module through its bindings; the tests above call the module on its own.

# ---------------------------------------------------------------- --git-pull (docs/handbook/build-sync.md §재빌드 전 원격 main 당겨오기 (`--git-pull`))

# The pull against real repositories (every outcome, main-only, a subfolder, no shell) is src/limn/sync/tests/test_gitsync.py.


class GitPullBuildIntegration(Base):
    """The server preserves pull outcomes in completed build records and stale-build metadata."""

    @needs_tex("latexmk", "pdftoppm")
    def test_pull_result_surfaces_in_build_response_and_state(self):
        """A non-repository pull refusal appears in the build result and persisted build state with the same head."""
        set_config(git_pull=True)
        res = ps.APP.build_requests.build_all(ps.APP.docs[0])
        self.assertIsInstance(res, BuildOk)
        # the temporary manuscript from Base.setUp() isn't a git repo — verify not_git actually triggers.
        self.assertEqual(res.pull, {"state": "skipped", "reason": "not_git", "head_before": None, "head_after": None})
        self.assertEqual(res.head, ps.APP.C.state.joinpath("head.txt").read_text().strip())
        snap = limn_build.state_snapshot(ps.APP.docs[0])
        self.assertEqual(snap.get("pull"), res.pull)
        self.assertEqual(snap.get("head"), res.head)

    @needs_tex("latexmk", "pdftoppm")
    def test_pull_absent_when_flag_off(self):
        """A build without --git-pull carries no pull record even when LaTeX succeeds."""
        set_config(git_pull=False)
        res = ps.APP.build_requests.build_all(ps.APP.docs[0])
        self.assertIsInstance(res, BuildOk)
        self.assertIsNone(res.pull)

    @needs_tex("latexmk", "pdftoppm")
    def test_pull_bumped_mtime_does_not_falsely_mark_stale(self):
        """A fast-forward's new source mtime becomes the build baseline, leaving a fresh PDF unmarked."""
        # bug: BuildRequests.tracked() used to commit the pre-pull value (src_mtime_at_start) as built_src_mtime,
        # so when pull pushed the .tex mtime forward (as a real fast-forward merge does), the "manuscript
        # modified" badge kept showing even though the build had just finished with that new manuscript.
        # The measurement must happen after pull (before copy).
        set_config(git_pull=True)

        def fake_pull():
            """Advance the source mtime like a fast-forward before returning its commit range."""
            # simulate a git fast-forward — pushes the .tex mtime forward like a real merge would.
            os.utime(self.main, (time.time() + 50, time.time() + 50))
            return {"state": "ok", "head_before": "aaa1111", "head_after": "bbb2222"}

        with mock.patch.object(ps.APP.sync_service, "repo_pull", side_effect=fake_pull):
            res = ps.APP.build_requests.build_all(ps.APP.docs[0])
        self.assertIsInstance(res, BuildOk)
        ps.APP.docs[0].mcache[2] = 0.0
        m = ps.APP.document_views.meta(ps.APP.docs[0], dict(LOCAL_ACTOR), light=True)
        self.assertIs(m["stale_build"], False)
        self.assertAlmostEqual(
            limn_build.read_built_src_mtime(ps.APP.docs[0]),
            limn_build.src_mtime(ps.APP.docs[0], ps.APP.C.state, force=True),
            delta=1.0,
        )

    @needs_tex("latexmk", "pdftoppm")
    def test_edit_after_copy_phase_still_marks_stale(self):
        """An edit made after source copy leaves the newly compiled PDF marked stale."""
        # even when using the post-pull mtime (or the copy-start time when there's no pull), editing the
        # source after copy (while latex is compiling) means that edit wasn't part of this build, so the
        # "manuscript modified" badge must still show.
        set_config(git_pull=True)
        original_run_logged = build_engine.run_logged

        def bump_then_run(cmd, cwd, timeout):
            """Change source mtime at the compile boundary, then run the real command."""
            # edit the source after copy finishes (during the latex phase)
            os.utime(self.main, (time.time() + 50, time.time() + 50))
            return original_run_logged(cmd, cwd, timeout)

        def fake_pull():
            """Keep HEAD unchanged so the test isolates edits after the copy phase."""
            return {"state": "up_to_date", "head_before": "aaa1111", "head_after": "aaa1111"}

        with (
            mock.patch.object(ps.APP.sync_service, "repo_pull", side_effect=fake_pull),
            mock.patch.object(build_engine, "run_logged", side_effect=bump_then_run),
        ):
            res = ps.APP.build_requests.build_all(ps.APP.docs[0])
        self.assertIsInstance(res, BuildOk)
        ps.APP.docs[0].mcache[2] = 0.0
        m = ps.APP.document_views.meta(ps.APP.docs[0], dict(LOCAL_ACTOR), light=True)
        self.assertIs(m["stale_build"], True)


class AutomaticMainSync(Base):
    """The server watch pulls a real local upstream and persists actual scheduled builds."""

    def setUp(self):
        """Track local main from the manuscript, with a second clone for upstream changes."""
        super().setUp()
        self.origin = Path(self.tmp.name) / "origin.git"
        self.upstream = Path(self.tmp.name) / "upstream"
        self._git(self.src, "init", "--quiet", "-b", "main")
        self._git(self.src, "config", "user.email", "alice@example.com")
        self._git(self.src, "config", "user.name", "Alice")
        self._git(self.src, "add", "main.tex")
        self._git(self.src, "commit", "--quiet", "-m", "Initial manuscript")
        self._git(self.src, "clone", "--quiet", "--bare", str(self.src), str(self.origin))
        self._git(self.src, "remote", "add", "origin", str(self.origin))
        self._git(self.src, "push", "--quiet", "-u", "origin", "main")
        self._git(self.src, "clone", "--quiet", str(self.origin), str(self.upstream))
        self._git(self.upstream, "config", "user.email", "alice@example.com")
        self._git(self.upstream, "config", "user.name", "Alice")
        set_config(git_pull=True)

    def _git(self, cwd, *args):
        """Run fixture Git commands without involving a network or external manuscript."""
        result = gitrun.run_git(args, cwd, 10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def _advance_upstream(self):
        """Publish a new manuscript commit while leaving the server checkout behind."""
        (self.upstream / "main.tex").write_text(self.main.read_text() + "\n% Upstream change\n", encoding="utf-8")
        self._git(self.upstream, "add", "main.tex")
        self._git(self.upstream, "commit", "--quiet", "-m", "Update manuscript")
        self._git(self.upstream, "push", "--quiet")
        return self._git(self.upstream, "rev-parse", "HEAD")

    @contextlib.contextmanager
    def _held_compiler(self):
        """Keep real workers running at the external compiler boundary, then await lock cleanup."""
        release = threading.Event()

        def compile_failure(cmd, cwd, timeout):
            """Return a deterministic compiler failure once running state has been observed."""
            if not release.wait(10):
                raise TimeoutError("test did not release compiler")
            return 1, "controlled compiler failure", False

        with mock.patch.object(build_engine, "run_logged", side_effect=compile_failure):
            try:
                yield
            finally:
                release.set()
                for doc in ps.APP.docs:
                    acquired = doc.lock.acquire(timeout=10)
                    if acquired:
                        doc.lock.release()
                    self.assertTrue(acquired, "build worker did not release its document")

    def test_new_head_schedules_each_tex_document_once(self):
        """A real fast-forward schedules one persisted build per LaTeX document and none for the PDF."""
        docs = [
            Doc("ms", "Body", src=self.src, main=self.main, paths=ps.APP.C.paths),
            Doc("hl", "Highlights", src=self.src, main=self.main, paths=ps.APP.C.paths),
            Doc("pdf", "Reference", kind="pdf", src=self.src, main=self.src / "ref.pdf", paths=ps.APP.C.paths),
        ]
        ps.APP.set_docs(docs)
        head = self._advance_upstream()
        with self._held_compiler():
            out = ps.APP.sync_service.once()
            self.assertEqual(out["state"], "updating")
            self.assertEqual(self._git(self.src, "rev-parse", "HEAD"), head)
            self.assertEqual(self.main.read_text(), (self.upstream / "main.tex").read_text())
            self.assertEqual([limn_build.state_snapshot(d)["state"] for d in docs], ["running", "running", "idle"])
        self.assertEqual([limn_build.load_builds(d)["seq"] for d in docs], [1, 1, 0])
        for doc in docs[:2]:
            self.assertEqual(limn_build.load_builds(doc)["last"]["state"], "fail")
            self.assertEqual((doc.dir / "build.log").read_text(), "controlled compiler failure")
        self.assertFalse((docs[2].dir / "builds.json").exists())

    def test_current_head_still_rebuilds_old_pdf_on_startup(self):
        """A current checkout with an older built HEAD produces a new persisted build on startup."""
        doc = ps.APP.docs[0]
        (doc.dir / "head.txt").write_text("aaaaaaa", encoding="utf-8")
        head = self._git(self.src, "rev-parse", "HEAD")
        with self._held_compiler():
            out = ps.APP.sync_service.once()
            self.assertEqual(out["state"], "updating")
            self.assertEqual(limn_build.state_snapshot(doc)["state"], "running")
            self.assertEqual(self._git(self.src, "rev-parse", "HEAD"), head)
        self.assertEqual(limn_build.load_builds(doc)["seq"], 1)
        self.assertEqual(limn_build.load_builds(doc)["last"]["state"], "fail")

    def test_dirty_checkout_is_visible_and_never_rebuilt(self):
        """A dirty checkout stays untouched, reports its refusal in meta, and creates no build history."""
        head = self._git(self.src, "rev-parse", "HEAD")
        self._advance_upstream()
        content = self.main.read_text() + "\n% Uncommitted local change\n"
        self.main.write_text(content, encoding="utf-8")
        with self._held_compiler():
            out = ps.APP.sync_service.once()
            self.assertEqual(out["state"], "blocked")
            self.assertEqual(limn_build.state_snapshot(ps.APP.docs[0])["state"], "idle")
        self.assertEqual(self._git(self.src, "rev-parse", "HEAD"), head)
        self.assertEqual(self.main.read_text(), content)
        self.assertEqual(limn_build.load_builds(ps.APP.docs[0])["seq"], 0)
        self.assertFalse((ps.APP.docs[0].dir / "builds.json").exists())
        self.assertEqual(
            ps.APP.document_views.meta(ps.APP.docs[0], dict(LOCAL_ACTOR), light=True)["sync"]["reason"], "dirty"
        )

    def test_topic_branch_is_not_pulled_or_rebuilt(self):
        """The watch's main-only policy leaves a clean topic branch and its build history untouched."""
        self._git(self.src, "checkout", "--quiet", "-b", "topic")
        self._git(self.src, "branch", "--set-upstream-to=origin/main", "topic")
        head = self._git(self.src, "rev-parse", "HEAD")
        self._advance_upstream()
        with self._held_compiler():
            out = ps.APP.sync_service.once()
            self.assertEqual((out["state"], out["reason"]), ("blocked", "not_main"))
            self.assertEqual(limn_build.state_snapshot(ps.APP.docs[0])["state"], "idle")
        self.assertEqual(self._git(self.src, "rev-parse", "HEAD"), head)
        self.assertEqual(limn_build.load_builds(ps.APP.docs[0])["seq"], 0)

    def test_updating_clears_when_pdf_reaches_synced_head(self):
        """An "updating" status turns "current" once the PDF was built from the pulled commit."""
        set_config(git_pull=True)
        with ps.APP.RT.sync_watch.lock:
            ps.APP.RT.sync_watch.record.update(state="updating", reason=None, head_after="b" * 40)
        (ps.APP.C.state / "head.txt").write_text("bbbbbbb", encoding="utf-8")
        self.assertEqual(ps.APP.sync_service.status()["state"], "current")

    def test_failed_pdf_build_reports_error(self):
        """An "updating" status turns error/build_failed when a document still behind the commit failed its build."""
        set_config(git_pull=True)
        with ps.APP.RT.sync_watch.lock:
            ps.APP.RT.sync_watch.record.update(state="updating", reason=None, head_after="b" * 40)
        (ps.APP.C.state / "head.txt").write_text("aaaaaaa", encoding="utf-8")
        with ps.APP.docs[0].bstate_lock:
            ps.APP.docs[0].bstate["state"] = "fail"
        status = ps.APP.sync_service.status()
        self.assertEqual((status["state"], status["reason"]), ("error", "build_failed"))


if __name__ == "__main__":
    unittest.main()

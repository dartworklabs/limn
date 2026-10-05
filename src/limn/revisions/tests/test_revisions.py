"""limn.revisions.core through the server: manuscript history, the pin-scoped diff, comparison builds in the sandbox, and
the outline of a revision's snapshot, over the server's revision context and its HTTP routes.

The module's boundaries, the refusal values and the attribution rules of pin scoping are src/limn/pins/tests/test_scope.py. Here the revision services run against a real temporary git repository wired as server.py wires
them (revision_context), and the routes are driven through the handler; the classes at the end are the pin-scoped
source diff and comparison PDF of v0.3 (issue #9, docs/adr/0005-pin-scoped-changes.md).

Run: uv run pytest src/limn/revisions/tests/test_revisions.py
"""

import errno
import fcntl
import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from limn.builds import engine as build_engine
from limn.documents import reads as limn_meta
from limn.pins.lifecycle import input as lifecycle_input
from limn.pins.lifecycle.rules import CloseRequest
from limn.pins.location.mapping import anchor_of
from limn.pins.store import find_pin
from limn.revisions import (
    core as revisions,
    execution as revision_execution,
    input as revision_input,
    jobs as revision_jobs,
    scope as scoping,
)
from limn.revisions.answer import scope_http_error
from limn.revisions.core import revision_history
from limn.runtime.documents import Doc
from limn.security.access import LOCAL_ACTOR
from limn.web.errors import InputRejected

from helpers import (
    TEX,
    Base,
    extract_js_fn,
    minimal_pdf,
    needs_tex,
    ps,
    records,
    req,
    revision_spec,
    run_node,
    set_config,
    split_resp,
    write_records,
)
from helpers_access import REPO_NEW as NEW, REPO_OLD as OLD, AccessBase, ScopedRepo, talk_to
from helpers_authority import post_authority

# Issue #162 (synthetic): a short reply letter. Its opening paragraph is running text; the second sits in a macro that
# typesets its argument after a label, the third in a macro that sets its argument, a list, in a quote.
REPLY_LETTER = r"""\documentclass{article}
\newcommand{\reply}[1]{\par\noindent\textbf{Reply:}\ \normalsize #1\par}
\newcommand{\revised}[1]{%
  \begin{quote}
    \textbf{Revised}\par
    \itshape #1
  \end{quote}}
\begin{document}
The opening paragraph thanks the editor for an oldopening reading.

\reply{The second paragraph answers the first comment with oldsecond evidence.}

\revised{\begin{itemize}
\item The third paragraph lists one oldthird change.
\end{itemize}}
\end{document}
"""

# A macro whose argument is a label, not text: marking inside it would not compile.
SEE_ALSO = r"""\documentclass{article}
\newcommand{\see}[1]{see Section~\ref{#1}}
\begin{document}
\section{Alpha}\label{sec:alpha}
\section{Beta}\label{sec:beta}
The paragraph mentions oldopening words, \see{sec:alpha}.
\end{document}
"""


class ManuscriptRevisions(Base):
    """Revision endpoints return scoped source changes and reject unrelated commits."""

    def setUp(self):
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        self.repo = self.src.parent
        self.secret = self.repo / "other" / "private.tex"
        self.secret.parent.mkdir()
        self.secret.write_text("private text\n", encoding="utf-8")
        for cmd in (
            ["git", "init", "--quiet"],
            ["git", "config", "user.email", "t@example.com"],
            ["git", "config", "user.name", "T"],
            ["git", "add", "ms/main.tex", "other/private.tex"],
            ["git", "commit", "--quiet", "-m", "first"],
        ):
            subprocess.run(cmd, cwd=self.repo, check=True, capture_output=True)
        self.first = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        self.main.write_text(TEX + "New manuscript sentence.\n", encoding="utf-8")
        self.secret.write_text("hidden change\n", encoding="utf-8")
        for cmd in (
            ["git", "add", "ms/main.tex", "other/private.tex"],
            ["git", "commit", "--quiet", "-m", "manuscript update"],
        ):
            subprocess.run(cmd, cwd=self.repo, check=True, capture_output=True)
        self.latest = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()

    def test_latest_revision_diff_is_real_and_scoped(self):
        history = revisions.revision_history(ps.APP.docs[0])
        self.assertTrue(history["available"])
        self.assertEqual(history["revisions"][0]["id"], self.latest)
        d = ps.APP.revision_requests.diff(ps.APP.docs[0], self.latest)
        self.assertIn("New manuscript sentence.", d["diff"])
        self.assertNotIn("hidden change", d["diff"])
        self.assertNotIn("other/private.tex", d["diff"])
        self.assertFalse(d["truncated"])

    def test_a_view_only_document_has_no_history_even_beside_committed_sources(self):
        """A PDF in the body's own folder shows no revisions: the changes view belongs to documents that show
        revisions, not to any file that happens to sit in a Git repository."""
        pdf = self.src / "review.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        rv = Doc("rv", "리뷰", "pdf", src=self.src, main=pdf, paths=ps.APP.C.paths)
        self.assertEqual(revisions.revision_history(rv), {"available": False, "revisions": []})
        self.assertTrue(revisions.revision_history(ps.APP.docs[0])["available"])

    def test_http_revision_endpoints(self):
        code, _, raw = split_resp(self.talk(req("GET", "/api/revisions")))
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)["revisions"][0]["id"], self.latest)
        code, _, raw = split_resp(self.talk(req("GET", "/api/revision-diff?commit=" + self.latest)))
        self.assertEqual(code, 200)
        self.assertIn("New manuscript sentence.", json.loads(raw)["diff"])
        code, _, _ = split_resp(self.talk(req("GET", "/api/revision-diff?commit=HEAD")))
        self.assertEqual(code, 400)

    def git(self, *args: str) -> str:
        """Run git in the repository; returns its stdout (a failure raises)."""
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout

    def merge_of_two_tex_branches(self) -> str:
        """A --no-ff merge of a branch that edits main.tex into a line that added ms/side.tex: the merge tree differs
        from both parents, so the history lists it, yet `git show` gives it a combined diff that is empty."""
        trunk = self.git("rev-parse", "--abbrev-ref", "HEAD").strip()
        self.git("checkout", "--quiet", "-b", "feature")
        self.main.write_text(TEX + "New manuscript sentence.\nMerged-in branch sentence.\n", encoding="utf-8")
        self.git("commit", "--quiet", "-am", "branch edit")
        self.git("checkout", "--quiet", trunk)
        (self.src / "side.tex").write_text("Trunk side file.\n", encoding="utf-8")
        self.git("add", "ms/side.tex")
        self.git("commit", "--quiet", "-m", "trunk adds side.tex")
        self.git("merge", "--quiet", "--no-ff", "-m", "merge feature", "feature")
        return self.git("rev-parse", "HEAD").strip()

    def test_a_merge_commit_diff_is_against_its_first_parent(self):
        """The source diff of a merge is the first-parent diff, like the comparison PDF (it was empty: `git show`
        gives a merge a combined diff)."""
        merge = self.merge_of_two_tex_branches()
        self.assertIn(merge, [r["id"] for r in revisions.revision_history(ps.APP.docs[0])["revisions"]])
        code, _, raw = split_resp(self.talk(req("GET", "/api/revision-diff?commit=" + merge)))
        self.assertEqual(code, 200)
        out = json.loads(raw)
        self.assertEqual(out["diff"], self.git("diff", "--no-renames", merge + "^1", merge, "--", "ms/"))
        self.assertIn("+Merged-in branch sentence.", out["diff"])
        self.assertIn("+++ b/ms/main.tex", out["diff"])
        self.assertNotIn("Trunk side file.", out["diff"])  # the first parent already had it
        self.assertEqual(out["diff"].count("diff --git"), 1)
        self.assertFalse(out["truncated"])

    def test_a_normal_commit_and_the_root_commit_keep_their_diffs(self):
        """A one-parent commit is diffed against its parent, a root commit against nothing, as before."""
        d = ps.APP.revision_requests.diff(ps.APP.docs[0], self.latest)
        self.assertIn("+New manuscript sentence.", d["diff"])
        self.assertEqual(d["diff"].count("diff --git"), 1)
        root = ps.APP.revision_requests.diff(ps.APP.docs[0], self.first)
        self.assertIn("--- /dev/null", root["diff"])
        self.assertIn("+\\documentclass{article}", root["diff"])
        self.assertNotIn("New manuscript sentence.", root["diff"])

    def test_rejects_arbitrary_commit_and_bad_id(self):
        """Only a full SHA-1 parses (400 bad_commit otherwise), and only a commit in the document's recent list is read:
        even a name that got past the parser is never handed to git."""
        for commit in ("HEAD", "--help"):
            self.assertEqual(
                revision_input.parse_commit(commit), InputRejected("올바른 커밋 ID가 아닙니다.", "bad_commit")
            )
        for commit in ("HEAD", "a" * 40, "--help"):
            self.assertEqual(ps.APP.revision_requests.diff(ps.APP.docs[0], commit), revisions.CommitNotRecent())

    def test_shared_build_root_keeps_document_histories_separate(self):
        heads = {"ms": self.main}
        for key in ("hl", "cl"):
            path = self.repo / key / (key + ".tex")
            path.parent.mkdir()
            path.write_text("\\documentclass{article}\n" + key + "\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", str(path.relative_to(self.repo))], cwd=self.repo, check=True, capture_output=True
            )
            subprocess.run(
                ["git", "commit", "--quiet", "-m", key + " update"], cwd=self.repo, check=True, capture_output=True
            )
            heads[key] = path
        docs = [Doc(k, k, src=self.repo, main=path, paths=ps.APP.C.paths) for k, path in heads.items()]
        for d in docs:
            history = revisions.revision_history(d)
            self.assertTrue(history["available"])
            self.assertEqual(
                history["revisions"][0]["subject"], "manuscript update" if d.key == "ms" else d.key + " update"
            )
        hl_head = revisions.revision_history(docs[1])["revisions"][0]["id"]
        self.assertEqual(ps.APP.revision_requests.diff(docs[0], hl_head), revisions.CommitNotRecent())

    def test_main_path_outside_document_source_is_unavailable(self):
        bad = Doc("bad", "bad", src=self.src, main=self.secret, paths=ps.APP.C.paths)
        self.assertFalse(revisions.revision_history(bad)["available"])
        link = self.src / "linked.tex"
        link.symlink_to(self.secret)
        linked = Doc("linked", "linked", src=self.src, main=link, paths=ps.APP.C.paths)
        self.assertFalse(revisions.revision_history(linked)["available"])

    def large_revision(self):
        """Commit a real UTF-8 change exceeding the production response limit."""
        self.main.write_text(TEX + "한" * scoping.REVISION_DIFF_MAX + "\n", encoding="utf-8")
        subprocess.run(["git", "add", "ms/main.tex"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "--quiet", "-m", "large update"], cwd=self.repo, check=True, capture_output=True
        )
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()

    def test_caps_large_diff(self):
        """A real large diff is truncated at the byte limit with complete UTF-8 output."""
        d = ps.APP.revision_requests.diff(ps.APP.docs[0], self.large_revision())
        self.assertTrue(d["truncated"])
        self.assertLessEqual(len(d["diff"].encode("utf-8")), scoping.REVISION_DIFF_MAX + 3)

    def test_large_diff_stops_the_git_process_group(self):
        """A truncated streamed diff terminates Git's whole session, including any subprocess it started."""
        commit = self.large_revision()
        processes = []
        open_git = revisions.open_git

        def observed_git(args, cwd):
            """Run the real owned process adapter and retain its OS handle for the exit oracle."""
            process = open_git(args, cwd)
            processes.append(process)
            return process

        with mock.patch.object(revisions, "open_git", side_effect=observed_git):
            result = ps.APP.revision_requests.diff(ps.APP.docs[0], commit)

        self.assertTrue(result["truncated"])
        self.assertEqual([process.poll() for process in processes], [-signal.SIGKILL])

    def test_timed_out_diff_stops_the_git_process_group(self):
        """A silent streamed Git process that exceeds its deadline is stopped as a group and reported unavailable."""

        def silent_git(_args, _cwd):
            """Start a silent command in a fresh session to exercise the stream deadline."""
            return subprocess.Popen(
                ["sleep", "10"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

        with (
            mock.patch.object(revisions, "GIT_TIMEOUT", 0.05),
            mock.patch.object(revisions, "open_git", side_effect=silent_git),
            mock.patch.object(revisions.os, "killpg", wraps=os.killpg) as kill_group,
        ):
            result = ps.APP.revision_requests.diff(ps.APP.docs[0], self.latest)

        self.assertEqual(result, revisions.DiffUnavailable())
        kill_group.assert_called_once()

    def test_revision_spec_uses_first_parent_and_rejects_root(self):
        spec = revision_spec(self.latest)
        self.assertEqual((spec.base, spec.head), (self.first, self.latest))
        self.assertEqual(revision_spec(self.first), revisions.NoParent())

    def test_revision_snapshot_uses_git_and_rejects_symlinks(self):
        self.main.write_text("uncommitted secret")
        dest = self.repo / "snapshot"
        spec = revision_spec(self.latest)
        revision_execution.revision_snapshot(spec, spec.head, dest)
        self.assertIn("New manuscript sentence.", (dest / "main.tex").read_text())
        self.assertFalse((dest / "other").exists())
        (self.src / "escape.tex").symlink_to(self.secret)
        for cmd in (["git", "add", "ms/escape.tex"], ["git", "commit", "-qm", "link"]):
            subprocess.run(cmd, cwd=self.repo, check=True, capture_output=True)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        self.assertEqual(
            revision_execution.revision_snapshot(revision_spec(head), head, self.repo / "bad-snapshot"),
            revisions.StepFailed("unsafe_snapshot"),
        )

    def test_outline_uses_only_current_pdf_aux_and_balanced_tex_groups(self):
        current = ps.APP.C.state / "pages-20260924010000"
        current.mkdir()
        (ps.APP.C.state / "pages.cur").write_text(current.name)
        (current / "main.aux").write_text(
            r"\@writefile{toc}{\contentsline {section}{\numberline {2}A \textbf{nested {title}} \& B}{iv}{section.2}}"
            + "\n"
            + r"\@writefile{toc}{\contentsline {subsection}{\numberline {2.1}Use \texorpdfstring{$x^2$}{x squared}}{8}{subsection.2.1}}"
            + "\n"
        )
        ps.APP.C.build.mkdir()
        (ps.APP.C.build / "main.aux").write_text("wrong next build")
        data = limn_meta.outline_labels(ps.APP.docs[0])
        self.assertEqual(data["build"], current.name)
        self.assertEqual(
            data["labels"],
            [
                {"number": "2", "title": "A nested title & B", "page": "iv", "level": "section", "anchor": "section.2"},
                {
                    "number": "2.1",
                    "title": "Use x squared",
                    "page": "8",
                    "level": "subsection",
                    "anchor": "subsection.2.1",
                },
            ],
        )

    def test_outline_missing_snapshot_does_not_read_mutable_build(self):
        ps.APP.C.build.mkdir()
        (ps.APP.C.build / "main.aux").write_text(
            r"\@writefile{toc}{\contentsline {section}{\numberline {9}Stale}{1}{section.9}}"
        )
        self.assertEqual(limn_meta.outline_labels(ps.APP.docs[0])["labels"], [])

    def _wait_revision(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = ps.APP.revision_requests.status(ps.APP.docs[0], self.latest)
            if status["state"] != "running":
                return status
            time.sleep(0.01)
        self.fail("revision worker did not finish")

    def test_async_revision_http_deduplicates_caches_and_preserves_current_build(self):
        """A second POST joins the running build, the PDF is served once ready and cached, the manuscript, its build
        marker and state stay as they were, and a commit git no longer lists is refused even with a cached PDF."""
        entered, release = threading.Event(), threading.Event()
        original = self.main.read_bytes()
        marker = ps.APP.C.state / "pages.cur"
        marker.write_text("pages-20260924000000")
        before = dict(ps.APP.docs[0].bstate)
        calls = []

        def compile(spec, jobdir, timeout):
            calls.append(spec)
            entered.set()
            release.wait(3)
            (jobdir / "revision.pdf").write_bytes(b"%PDF-1.4\nrevision")
            return revisions.ComparisonBuilt(["test warning"])

        body = json.dumps({"commit": self.latest}).encode()
        request = req("POST", "/api/revision-build", body, {"Content-Type": "application/json"})
        with mock.patch.object(revision_execution, "revision_compile", side_effect=compile):
            try:
                code, _, raw = split_resp(self.talk(request))
                self.assertEqual(code, 202)
                self.assertEqual(json.loads(raw)["base"], self.first)
                self.assertTrue(entered.wait(2))
                self.assertEqual(split_resp(self.talk(request))[0], 202)
                self.assertEqual(split_resp(self.talk(req("GET", "/api/revision-pdf?commit=" + self.latest)))[0], 404)
            finally:
                release.set()
                status = self._wait_revision()
            self.assertEqual(status["state"], "ready")
            self.assertEqual(status["warnings"], ["test warning"])
            self.assertEqual(split_resp(self.talk(request))[0], 200)
            self.assertEqual(len(calls), 1)
        code, headers, pdf = split_resp(self.talk(req("GET", "/api/revision-pdf?commit=" + self.latest)))
        self.assertEqual((code, headers["content-type"], pdf), (200, "application/pdf", b"%PDF-1.4\nrevision"))
        self.assertEqual(self.main.read_bytes(), original)
        self.assertEqual(marker.read_text(), "pages-20260924000000")
        self.assertEqual(ps.APP.docs[0].bstate, before)
        with mock.patch.object(
            revisions.WindowCache, "rows", return_value=[]
        ):  # the window lists nothing: no commit may be read
            self.assertEqual(split_resp(self.talk(req("GET", "/api/revision-pdf?commit=" + self.latest)))[0], 404)
            self.assertEqual(ps.APP.revision_requests.status(ps.APP.docs[0], self.latest), revisions.CommitNotRecent())

    def test_revision_failure_has_no_pdf_and_can_retry(self):
        """A retry publishes its new compiler outcome instead of reusing a cached failure."""
        with mock.patch.object(
            revision_execution,
            "revision_compile",
            side_effect=[revisions.StepFailed("timeout"), revisions.StepFailed("size")],
        ):
            ps.APP.revision_requests.start(
                ps.APP.docs[0],
                self.latest,
                authority=post_authority(ps.APP.revision_requests, dict(LOCAL_ACTOR), "revision-build", ps.APP.docs[0]),
            )
            status = self._wait_revision()
            self.assertEqual((status["state"], status["reason"]), ("error", "timeout"))
            self.assertEqual(ps.APP.revision_requests.pdf(ps.APP.docs[0], self.latest), revisions.RevisionNotReady())
            ps.APP.revision_requests.start(
                ps.APP.docs[0],
                self.latest,
                authority=post_authority(ps.APP.revision_requests, dict(LOCAL_ACTOR), "revision-build", ps.APP.docs[0]),
            )
            retried = self._wait_revision()
            self.assertEqual((retried["state"], retried["reason"]), ("error", "size_limit"))
            self.assertEqual(ps.APP.revision_requests.pdf(ps.APP.docs[0], self.latest), revisions.RevisionNotReady())

    def test_revision_requests_enforce_origin_allowlist_and_field_validation(self):
        body = json.dumps({"commit": self.latest}).encode()
        set_config(allow=frozenset({"allowed@example.com"}))
        code, _, _ = split_resp(
            self.talk(
                req(
                    "POST",
                    "/api/revision-build",
                    body,
                    {"Content-Type": "application/json", "Tailscale-User-Login": "stranger@example.com"},
                )
            )
        )
        self.assertEqual(code, 403)
        set_config(allow=frozenset())
        code, _, _ = split_resp(
            self.talk(
                req(
                    "POST",
                    "/api/revision-build",
                    body,
                    {"Content-Type": "application/json", "Origin": "https://evil.example"},
                )
            )
        )
        self.assertEqual(code, 403)
        for bad in ({"commit": []}, {"commit": "HEAD"}, {"commit": self.latest, "command": "evil"}):
            code, _, _ = split_resp(
                self.talk(
                    req("POST", "/api/revision-build", json.dumps(bad).encode(), {"Content-Type": "application/json"})
                )
            )
            self.assertEqual(code, 400)
        self.assertEqual(split_resp(self.talk(req("GET", "/api/revision-build?commit=HEAD")))[0], 400)

    def test_revision_source_limits_and_gitlinks_are_rejected(self):
        spec = revision_spec(self.latest)
        with mock.patch.object(revision_execution, "REVISION_FILE_MAX", 1):
            self.assertEqual(
                revision_execution.revision_snapshot(spec, self.latest, self.repo / "large"),
                revisions.StepFailed("snapshot_size"),
            )
        for cmd in (
            ["git", "update-index", "--add", "--cacheinfo", "160000," + self.first + ",ms/sub"],
            ["git", "commit", "-qm", "add submodule"],
        ):
            subprocess.run(cmd, cwd=self.repo, check=True, capture_output=True)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        self.assertEqual(
            revision_execution.revision_snapshot(spec, head, self.repo / "submodule-snapshot"),
            revisions.StepFailed("unsafe_snapshot"),
        )

    def test_revision_jobs_are_bounded_and_cache_expires(self):
        """Exhausted job capacity refuses work; expired ready artifacts become idle and pruning bounds cache growth."""
        with mock.patch.object(ps.APP.RT.revision_jobs, "slots", threading.BoundedSemaphore(0)):
            self.assertEqual(
                ps.APP.revision_requests.start(
                    ps.APP.docs[0],
                    self.latest,
                    authority=post_authority(
                        ps.APP.revision_requests, dict(LOCAL_ACTOR), "revision-build", ps.APP.docs[0]
                    ),
                ),
                revisions.AllSlotsBusy(),
            )
        spec = revision_spec(self.latest)
        root = revision_jobs.revision_cache_root(ps.APP.docs[0])
        jobdir = root / spec.key
        jobdir.mkdir()
        (jobdir / "revision.pdf").write_bytes(b"%PDF-1.4")
        status = jobdir / "status.json"
        status.write_text(json.dumps({"state": "ready"}))
        self.assertEqual(ps.APP.revision_requests.status(ps.APP.docs[0], self.latest)["state"], "ready")
        os.utime(status, (1, 1))
        self.assertEqual(ps.APP.revision_requests.status(ps.APP.docs[0], self.latest)["state"], "idle")
        for i in range(8):
            (root / ("%064x" % i)).mkdir()
        revision_jobs.revision_prune(root, spec.key, ps.APP.RT.revision_jobs.active)
        self.assertLessEqual(sum(p.is_dir() for p in root.iterdir()), revisions.REVISION_CACHE_KEEP)

    def test_corrupt_revision_cache_is_a_miss(self):
        spec = revision_spec(self.latest)
        root = revision_jobs.revision_cache_root(ps.APP.docs[0])
        jobdir = root / spec.key
        jobdir.mkdir()
        for content in ("[]", "null", "1", "bad JSON", '{"state":"running"}', '{"state":"ready"}'):
            (jobdir / "status.json").write_text(content)
            self.assertEqual(ps.APP.revision_requests.status(ps.APP.docs[0], self.latest)["state"], "idle")

    def test_sandbox_is_required_and_has_no_unsandboxed_fallback(self):
        with mock.patch.object(shutil, "which", return_value=None):
            self.assertEqual(
                revision_execution.revision_sandbox(self.repo, Path("."), "latexmk", []),
                revisions.StepFailed("sandbox_tools"),
            )
        with self.assertRaises(ValueError):
            revision_execution.revision_sandbox(self.repo, Path("."), "sh", [])

    def test_revision_exec_bounds_output_and_time(self):
        self.assertEqual(
            revisions.revision_exec(["python3", "-c", "print('x' * 10000)"], self.repo, 2, 100),
            revisions.StepFailed("size"),
        )
        self.assertEqual(
            revisions.revision_exec(["python3", "-c", "import time; time.sleep(20)"], self.repo, 0.1),
            revisions.StepFailed("timeout"),
        )

    def test_revision_exec_keeps_its_answer_when_the_group_holds_only_exited_processes(self):
        """The cleanup kill of the command's process group is refused with EPERM on macOS when every member has
        exited but is not reaped yet (checked: os.killpg of a group whose leader is a zombie raises PermissionError
        there, where Linux delivers or answers ESRCH). The command's result - its output, or its own refusal - is
        still what revision_exec gives. Before the fix the PermissionError escaped, and GET /api/revision-diff?pin=
        answered 500 "Operation not permitted" under load (the ScopedViewer flake)."""
        eperm = PermissionError(errno.EPERM, "Operation not permitted")
        with mock.patch.object(revisions.os, "killpg", side_effect=eperm) as killpg:
            self.assertEqual(
                revisions.revision_exec(["python3", "-c", "print('ok')"], self.repo, 10), (0, b"ok\n", b"")
            )
            self.assertEqual(
                revisions.revision_exec(["python3", "-c", "print('x' * 10000)"], self.repo, 10, 100),
                revisions.StepFailed("size"),
            )
        self.assertEqual(killpg.call_count, 2)

    def test_comparison_build_runs_exactly_these_sandbox_commands(self):
        """The bwrap argv of both comparison steps (latexdiff, then latexmk), byte for byte: the read-only system
        folders that exist, private /proc, /dev and /tmp, the job's work folder as /work, a cleared environment with
        only TeX's variables, then the tool's resolved path under /usr and its arguments. Pinned so that a refactor
        cannot loosen the sandbox unnoticed. The tools are placed in a /usr folder that does not exist (so resolve()
        keeps the path on every host), which of the bind sources exist is fixed, and git runs for real."""
        fake = "/usr/limn-test-sandbox"
        binds = (
            "/usr",
            "/bin",
            "/lib",
            "/lib64",
            "/etc/fonts",
            "/etc/texmf",
            "/var/lib/texmf",
            "/var/cache/fontconfig",
        )
        present = {"/usr", "/bin", "/lib", "/etc/fonts", "/var/lib/texmf"}
        real_which, real_exists, real_exec = shutil.which, Path.exists, revisions.revision_exec
        calls = []

        def which(name, *args, **kwargs):
            """The sandbox tools under the fake /usr folder; anything else as the host finds it."""
            return fake + "/" + name if name in ("bwrap", "latexdiff", "latexmk") else real_which(name, *args, **kwargs)

        def exists(path, *args, **kwargs):
            """The fixed set of bind sources that exist; any other path as the file system says."""
            return str(path) in present if str(path) in binds else real_exists(path, *args, **kwargs)

        def run(cmd, cwd, timeout, limit=8 * 1024 * 1024, env=None):
            """git for real; a sandboxed step recorded and answered like a successful tool."""
            if cmd[0] != fake + "/bwrap":
                return real_exec(cmd, cwd, timeout, limit, env=env)
            calls.append((cmd, cwd, timeout, env))
            if cmd[cmd.index("--") + 1].endswith("latexdiff"):
                return (0, b"\\begin{document}\\DIFaddbegin x\\DIFaddend\\end{document}", b"")
            (Path(cwd) / "new" / "pin_revision.pdf").write_bytes(b"%PDF-1.4\n")
            return (0, b"", b"")

        def sandbox(work, tool, args):
            """The expected bwrap command running tool with args on work."""
            return [
                fake + "/bwrap", "--unshare-all", "--die-with-parent", "--clearenv",
                "--ro-bind", "/usr", "/usr", "--ro-bind", "/bin", "/bin", "--ro-bind", "/lib", "/lib",
                "--ro-bind", "/etc/fonts", "/etc/fonts", "--ro-bind", "/var/lib/texmf", "/var/lib/texmf",
                "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--bind", str(work), "/work",
                "--chdir", "/work/new/.",
                "--setenv", "PATH", fake + ":/usr/bin:/bin", "--setenv", "HOME", "/tmp", "--setenv", "LANG", "C.UTF-8",
                "--setenv", "TEXMFVAR", "/tmp/texmf-var", "--setenv", "TEXMFCONFIG", "/tmp/texmf-config",
                "--setenv", "openin_any", "p", "--setenv", "openout_any", "p",
                "--", fake + "/" + tool,
            ] + args  # fmt: skip

        jobdir = self.repo / "job"
        jobdir.mkdir()
        with (
            mock.patch.object(shutil, "which", side_effect=which),
            mock.patch.object(Path, "exists", exists),
            mock.patch.object(revisions, "revision_exec", side_effect=run),
        ):
            built = revision_execution.revision_compile(revision_spec(self.latest), jobdir, 30)
        self.assertIsInstance(built, revisions.ComparisonBuilt)
        work = calls[0][1]
        latexdiff = [
            "--encoding=utf8", "--flatten", "--math-markup=off", "--add-to-config", "ARRENV=tabularx;tabular;tabular[*]",
            "--label", self.first[:8], "--label", self.latest[:8], "/work/old/main.tex", "/work/new/main.tex",
        ]  # fmt: skip
        latexmk = [
            "-norc",
            "-pdf",
            "-no-shell-escape",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "pin_revision.tex",
        ]
        self.assertEqual(
            calls,
            [
                (sandbox(work, "latexdiff", latexdiff), work, 60, None),
                (sandbox(work, "latexmk", latexmk), work, 30, None),
            ],
        )

    def assert_claims_freed(self):
        """No job is registered, both build slots are free, and nothing holds the document's build lock (a lock the
        server still held would refuse this second open file of the same process)."""
        jobs = ps.APP.RT.revision_jobs
        self.assertEqual(jobs.active, {})
        got = [jobs.slots.acquire(blocking=False) for _ in range(2)]
        for held in got:
            if held:
                jobs.slots.release()
        self.assertEqual(got, [True, True])
        with (revision_jobs.revision_cache_root(ps.APP.docs[0]) / "build.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lock, fcntl.LOCK_UN)

    def test_a_start_that_is_refused_or_fails_frees_its_slot_and_lock(self):
        """Every way revision_start can stop after claiming a build slot - the document's lock held by another
        process, a symlinked job folder, an error while preparing the job, a thread that cannot start - gives the slot
        and the lock back and leaves no job registered; so does a worker that finished."""
        root = revision_jobs.revision_cache_root(ps.APP.docs[0])
        with (root / "build.lock").open("a") as other:
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(
                ps.APP.revision_requests.start(
                    ps.APP.docs[0],
                    self.latest,
                    authority=post_authority(
                        ps.APP.revision_requests, dict(LOCAL_ACTOR), "revision-build", ps.APP.docs[0]
                    ),
                ),
                revisions.DocumentBusy(),
            )
        self.assert_claims_freed()
        jobdir = root / revision_spec(self.latest).key
        jobdir.symlink_to(self.repo)
        self.assertEqual(
            ps.APP.revision_requests.start(
                ps.APP.docs[0],
                self.latest,
                authority=post_authority(ps.APP.revision_requests, dict(LOCAL_ACTOR), "revision-build", ps.APP.docs[0]),
            ),
            revisions.UnsafeCache(),
        )
        self.assert_claims_freed()
        jobdir.unlink()
        with (
            mock.patch.object(revision_jobs, "revision_prune", side_effect=OSError("disk")),
            self.assertRaises(OSError),
        ):
            ps.APP.revision_requests.start(
                ps.APP.docs[0],
                self.latest,
                authority=post_authority(ps.APP.revision_requests, dict(LOCAL_ACTOR), "revision-build", ps.APP.docs[0]),
            )
        self.assert_claims_freed()
        with (
            mock.patch.object(revisions.threading.Thread, "start", side_effect=RuntimeError("can't start")),
            self.assertRaises(RuntimeError),
        ):
            ps.APP.revision_requests.start(
                ps.APP.docs[0],
                self.latest,
                authority=post_authority(ps.APP.revision_requests, dict(LOCAL_ACTOR), "revision-build", ps.APP.docs[0]),
            )
        self.assert_claims_freed()
        with mock.patch.object(revision_execution, "revision_compile", return_value=revisions.StepFailed("timeout")):
            self.assertEqual(
                ps.APP.revision_requests.start(
                    ps.APP.docs[0],
                    self.latest,
                    authority=post_authority(
                        ps.APP.revision_requests, dict(LOCAL_ACTOR), "revision-build", ps.APP.docs[0]
                    ),
                )["state"],
                "running",
            )
            self.assertEqual(self._wait_revision()["reason"], "timeout")
        self.assert_claims_freed()

    def test_outline_complex_titles_keep_alignment_and_http_build_identity(self):
        pages = ps.APP.C.state / "pages"
        pages.mkdir()
        (pages / "main.aux").write_text(
            r"\@writefile{toc}{\contentsline {section}{\numberline {1}Bad \unknown{macro}}{1}{section.1}}"
            + "\n"
            + r"\@writefile{toc}{\contentsline {section}{\protect\numberline {2}A \{literal\} title}{2}{section.2}}"
            + "\n"
            + r"\@writefile{toc}{\contentsline {section}{Unnumbered}{3}{section*.3}}"
            + "\n"
            + r"\@writefile{lof}{\contentsline {figure}{\numberline {1}Not a section}{4}{figure.1}}"
        )
        code, _, raw = split_resp(self.talk(req("GET", "/api/outline-labels")))
        self.assertEqual(code, 200)
        data = json.loads(raw)
        self.assertEqual(data["build"], "pages")
        self.assertEqual([r["number"] for r in data["labels"]], ["", "2", ""])
        self.assertEqual(data["labels"][1]["title"], "A {literal} title")
        self.assertEqual(data["labels"][0]["title"], "")

    def test_page_snapshot_keeps_aux_with_its_pdf(self):
        ps.APP.C.build.mkdir()
        pdf, aux = ps.APP.C.build / "main.pdf", ps.APP.C.build / "main.aux"
        pdf.write_bytes(b"%PDF-1.4")
        aux.write_text(r"\@writefile{toc}{\contentsline {section}{\numberline {1}Before}{1}{section.1}}")

        def render(cmd, **kwargs):
            """pdfinfo says one page; pdftoppm writes that page as a 1x1 PPM on stdout."""
            out = b"Pages: 1\n" if cmd[0] == "pdfinfo" else b"P6\n1 1\n255\n\xff\xff\xff"
            return subprocess.CompletedProcess(cmd, 0, out, b"")

        with mock.patch.object(subprocess, "run", side_effect=render):
            pages = build_engine.render_pages(ps.APP.docs[0], pdf, [aux], ps.APP.C.dpi)
        self.assertIsInstance(pages, Path, pages)
        (ps.APP.C.state / "pages.cur").write_text(pages.name)
        aux.write_text("changed by a failed next build")
        self.assertEqual(limn_meta.outline_labels(ps.APP.docs[0])["labels"][0]["title"], "Before")

    @needs_tex("bwrap", "latexdiff", "latexmk", "pdftotext")
    def test_actual_sandbox_build_tracks_changed_input_and_preserves_sources(self):
        self.main.write_text("\\documentclass{article}\n\\begin{document}\n\\input{section}\n\\end{document}\n")
        section = self.src / "section.tex"
        section.write_text("Old sentence.\n")
        for cmd in (["git", "add", "ms"], ["git", "commit", "-qm", "split document"]):
            subprocess.run(cmd, cwd=self.repo, check=True, capture_output=True)
        section.write_text("New sentence.\n")
        for cmd in (["git", "add", "ms"], ["git", "commit", "-qm", "change included section"]):
            subprocess.run(cmd, cwd=self.repo, check=True, capture_output=True)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        before = {p.name: p.read_bytes() for p in self.src.iterdir()}
        dest = self.repo / "actual-job"
        dest.mkdir()
        status = revision_execution.revision_compile(revision_spec(head), dest, 30)
        self.assertIsInstance(status, revisions.ComparisonBuilt)
        text = subprocess.check_output(["pdftotext", str(dest / "revision.pdf"), "-"], text=True)
        self.assertIn("Old", text)
        self.assertIn("New", text)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.src.iterdir()})
        self.assertFalse(list(dest.glob("work-*")))

    def commit_main(self, text: str, message: str) -> str:
        """Writes text as the main file, commits it and returns the commit's full SHA-1."""
        self.main.write_text(text, encoding="utf-8")
        for cmd in (["git", "add", "ms"], ["git", "commit", "-qm", message]):
            subprocess.run(cmd, cwd=self.repo, check=True, capture_output=True)
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()

    def comparison_text(self, head: str) -> str:
        """Builds the whole-commit comparison of head in the real sandbox and returns its PDF's text; fails the test
        when the build does not succeed."""
        dest = self.repo / ("job-" + head[:8])
        dest.mkdir()
        built = revision_execution.revision_compile(revision_spec(head), dest, 60)
        self.assertIsInstance(built, revisions.ComparisonBuilt, built)
        return subprocess.check_output(["pdftotext", str(dest / "revision.pdf"), "-"], text=True)

    @needs_tex("bwrap", "latexdiff", "latexmk", "pdftotext")
    def test_changes_inside_the_documents_own_text_macros_are_marked_in_every_paragraph(self):
        """Issue #162: a reply letter keeps its second and third paragraphs in its own one-argument macros. latexdiff
        took each such call as one opaque token, so the comparison PDF marked only the plain first paragraph; the old
        text of the later ones was commented out and their new text drawn unmarked. Now every changed paragraph shows
        its deleted words (struck through, so the PDF's text still has them) next to the new ones."""
        self.commit_main(REPLY_LETTER, "reply letter")
        head = self.commit_main(
            REPLY_LETTER.replace("oldopening", "newopening")
            .replace("oldsecond", "newsecond")
            .replace("oldthird", "newthird"),
            "reword every paragraph",
        )
        text = self.comparison_text(head)
        for paragraph in ("opening", "second", "third"):
            with self.subTest(paragraph=paragraph):
                self.assertIn("old" + paragraph, text)
                self.assertIn("new" + paragraph, text)

    @needs_tex("bwrap", "latexdiff", "latexmk", "pdftotext")
    def test_a_macro_whose_argument_is_a_label_stays_whole_and_the_comparison_still_builds(self):
        """The negative side of issue #162: marking inside an argument that is not text (here a cross-reference label)
        breaks the comparison's compile, so a macro that hands its argument to \\ref is not marked inside. The changed
        call stays latexdiff's opaque token and the comparison of the plain paragraph still builds."""
        self.commit_main(SEE_ALSO, "cross-reference")
        head = self.commit_main(
            SEE_ALSO.replace("oldopening", "newopening").replace("\\see{sec:alpha}", "\\see{sec:beta}"),
            "point at the other section",
        )
        text = self.comparison_text(head)
        self.assertIn("oldopening", text)
        self.assertIn("newopening", text)

    def build_comparison(self, head: str, forced: tuple[str, ...] | None = None):
        """Builds the whole-commit comparison of head in the real sandbox, in a new job folder, and returns (outcome, job
        folder). forced, when given, is the text-command list latexdiff gets instead of the classifier's
        (revision_compile's seam)."""
        dest = Path(tempfile.mkdtemp(prefix="job-", dir=self.repo))
        seam = {} if forced is None else {"text_commands_of": lambda source: forced}
        return revision_execution.revision_compile(revision_spec(head), dest, 60, **seam), dest

    @needs_tex("bwrap", "latexdiff", "latexmk", "pdftotext")
    def test_a_text_command_that_breaks_the_build_falls_back_to_plain_latexdiff(self):
        """A comparison that built before issue #162's fix never stops building because of the text-command list. The
        classifier is strict enough that no accepted macro was found whose marked argument breaks the build, so this
        forces one through the seam: \\see hands its argument to \\ref, and latexdiff's markup inside it does not
        compile. The comparison is built again with plain latexdiff, shows the plain paragraph's change, and says so
        in its warnings and its build log."""
        self.commit_main(SEE_ALSO, "cross-reference")
        head = self.commit_main(
            SEE_ALSO.replace("oldopening", "newopening").replace("\\see{sec:alpha}", "\\see{sec:beta}"),
            "point at the other section",
        )
        built, dest = self.build_comparison(head, forced=("see",))
        self.assertIsInstance(built, revisions.ComparisonBuilt, built)
        self.assertEqual(
            built.warnings[:2], [revision_execution.COMPARISON_NOTE, revision_execution.TEXT_COMMANDS_FALLBACK_NOTE]
        )
        self.assertTrue((dest / "build.log").read_text().startswith(revision_execution.TEXT_COMMANDS_FALLBACK_LOG))
        text = subprocess.check_output(["pdftotext", str(dest / "revision.pdf"), "-"], text=True)
        self.assertIn("oldopening", text)
        self.assertIn("newopening", text)

    @needs_tex("bwrap", "latexdiff", "latexmk", "pdftotext")
    def test_a_text_command_run_that_builds_is_kept_without_fallback(self):
        """When the run with the document's text commands builds, it is the comparison: no fallback note in the
        warnings or the log, and the deleted words inside the macros are there (a plain latexdiff run would hide
        them)."""
        self.commit_main(REPLY_LETTER, "reply letter")
        head = self.commit_main(
            REPLY_LETTER.replace("oldsecond", "newsecond").replace("oldthird", "newthird"), "reword the replies"
        )
        built, dest = self.build_comparison(head)
        self.assertIsInstance(built, revisions.ComparisonBuilt, built)
        self.assertNotIn(revision_execution.TEXT_COMMANDS_FALLBACK_NOTE, built.warnings)
        self.assertFalse((dest / "build.log").read_text().startswith(revision_execution.TEXT_COMMANDS_FALLBACK_LOG))
        text = subprocess.check_output(["pdftotext", str(dest / "revision.pdf"), "-"], text=True)
        self.assertIn("oldsecond", text)
        self.assertIn("oldthird", text)

    @needs_tex("bwrap", "latexdiff", "latexmk")
    def test_a_comparison_that_does_not_build_is_retried_only_after_a_text_command_run(self):
        """A new side that does not compile fails either way. Without text commands the one run is already plain
        latexdiff's, so it is not repeated (no fallback line in the log); with a list the plain run follows, and its
        failure, compile_failed, is the answer."""
        self.commit_main(SEE_ALSO, "cross-reference")
        head = self.commit_main(SEE_ALSO.replace("oldopening", "\\undefinedcommand newopening"), "break the build")
        for forced, retried in (((), False), (("see",), True)):
            with self.subTest(forced=forced):
                built, dest = self.build_comparison(head, forced=forced)
                self.assertEqual(built, revisions.StepFailed("compile_failed"))
                log = (dest / "build.log").read_text()
                self.assertEqual(log.startswith(revision_execution.TEXT_COMMANDS_FALLBACK_LOG), retried)


# ---------------------------------------------------------------- pin-scoped changes (v0.3, issue #9): the scoped source diff and comparison PDF


class ScopedSourceDiff(ScopedRepo):
    """GET /api/revision-diff?pin= over a real git repository."""

    def test_each_pin_sees_only_its_hunks_and_the_rest_folded(self):
        """The issue #9 case over HTTP: each of three pins in one commit gets only its hunk; the rest is in other_diff."""
        want = {
            self.p1: ("changes", "apples and pears", ("blueberries", "Gamma")),
            self.p2: ("inferred", "blueberries", ("pears", "Gamma")),
            self.p3: ("inferred", "Gamma", ("pears", "blueberries")),
        }
        for pid, (source, mine, others) in want.items():
            with self.subTest(pin=pid):
                code, d = self.diff(self.fix, pid)
                self.assertEqual(code, 200, d)
                s = d["scope"]
                self.assertEqual((s["pin"], s["mode"], s["source"], s["hunks"], s["other"]), (pid, "pin", source, 1, 2))
                self.assertIn(mine, s["diff"])
                for o in others:
                    self.assertNotIn(o, s["diff"])
                    self.assertIn(o, s["other_diff"])
                self.assertIn("pears", d["diff"])  # the whole-commit diff is still there, unchanged
                self.assertIn("blueberries", d["diff"])

    def test_scoped_hunk_header_keeps_the_commits_line_numbers(self):
        """The scoped hunk of a pin after an insertion carries the commit's real new-side numbers."""
        d = self.diff_ok(self.fix, self.p2)
        self.assertIn("@@ -8,7 +9,7 @@", d["scope"]["diff"])

    def test_a_commit_that_belongs_entirely_to_the_pin_is_shown_whole(self):
        """A commit that is all the pin's is mode commit: the viewer shows it as in 0.2.2 without extra controls."""
        d = self.diff_ok(self.solo, self.p4)
        s = d["scope"]
        self.assertEqual((s["mode"], s["hunks"], s["other"]), ("commit", 1, 0))
        self.assertNotIn("other_diff", s)

    def test_a_pin_the_commit_does_not_touch_gets_the_whole_commit(self):
        """A commit that touches none of the pin is mode commit with source none (0.2.2 view)."""
        d = self.diff_ok(self.solo, self.p2)
        self.assertEqual((d["scope"]["mode"], d["scope"]["source"], d["scope"]["hunks"]), ("commit", "none", 0))

    def test_revision_diff_without_pin_has_the_0_2_2_fields_only(self):
        """Backward compatibility: without ?pin= the response keys are exactly 0.2.2's."""
        code, d = self.diff(self.fix)
        self.assertEqual((code, sorted(d)), (200, ["diff", "id", "truncated"]))

    def test_diff_inter_hunk_context_config_cannot_merge_two_pins_blocks(self):
        """Review finding: a user's diff.interHunkContext must not glue two pins' blocks together."""
        # diff.interHunkContext would glue nearby -U0 hunks together and give both pins both edits
        self.git("config", "diff.interHunkContext", "10")
        ps.APP.RT.scope_cache.clear()
        d = self.diff_ok(self.fix, self.p2)
        self.assertEqual((d["scope"]["hunks"], d["scope"]["other"]), (1, 2))
        self.assertNotIn("pears", d["scope"]["diff"])

    def test_malformed_pin_is_400_and_unknown_pin_is_404(self):
        """The pin parameter is validated (400) and must be a pin of this document (404)."""
        self.assertEqual(self.diff(self.fix, "x")[0], 400)
        self.assertEqual(self.diff(self.fix, "-1")[0], 400)
        self.assertEqual(self.diff(self.fix, "999")[0], 404)

    def test_pin_on_a_file_renamed_in_the_commit_gets_its_edit_only(self):
        """A rename with an edit is attributed to a pin naming either file name; the other file's change stays other."""
        part = self.src / "part.tex"
        part.write_text("".join("Part line %d.\n" % i for i in range(1, 21)), encoding="utf-8")
        self.write(
            NEW.replace("Filler two.", "Filler two, reworded.").replace(
                "\\end{document}", "\\input{part}\n\\end{document}"
            )
        )
        self.commit("add a part")
        old_pin = self.add(lo=12, hi=12, note="part twelve")
        rows = records(ps.APP.snapshot_pins())
        find_pin(rows, old_pin)["file"] = str(part)
        find_pin(rows, old_pin)["anchor"] = anchor_of(part.read_text().split("\n"), 12, 12)
        write_records(rows)
        self.git("mv", "ms/part.tex", "ms/chapter.tex")
        chapter = self.src / "chapter.tex"
        chapter.write_text(chapter.read_text().replace("Part line 12.", "Part line twelve."), encoding="utf-8")
        self.write(self.main.read_text().replace("\\input{part}", "\\input{chapter}"))
        mv = self.commit("rename the part")
        ps.APP.pin_lifecycle.close_pin(
            old_pin,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", old_pin),
            CloseRequest(ref=mv[:8]),
        )
        new_pin = self.add(lo=12, hi=12, note="chapter twelve")
        rows = records(ps.APP.snapshot_pins())
        find_pin(rows, new_pin)["file"] = str(chapter)
        write_records(rows)
        ps.APP.pin_lifecycle.close_pin(
            new_pin,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", new_pin),
            CloseRequest(ref=mv[:8]),
        )
        for pid in (old_pin, new_pin):  # the pin may name the file before or after the rename
            with self.subTest(pin=pid):
                d = self.diff_ok(mv, pid)
                s = d["scope"]
                self.assertEqual((s["mode"], s["hunks"], s["other"]), ("pin", 1, 1))
                self.assertIn(
                    "diff --git a/ms/part.tex b/ms/chapter.tex\nrename from ms/part.tex\nrename to ms/chapter.tex\n",
                    s["diff"],
                )
                self.assertIn("+Part line twelve.", s["diff"])
                self.assertNotIn("input", s["diff"])
                self.assertIn("+\\input{chapter}", s["other_diff"])


class SquashMergedPins(AccessBase):
    """The owner's workflow (ADR-0005, accepted): a PR fixes three pins, is squash-merged into one commit on main, and
    only then does the agent close each pin with ref = "PR #7 (<squash hash>)" and `changes` in the squash commit's
    new-side numbers. Beta's fix is a sentence added two lines below the pin, which the pin's own range cannot find -
    only the recorded `changes` can. A fourth change in the same commit belongs to no pin."""

    def setUp(self):
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        self.repo = self.src.parent
        self.main.write_text(OLD, encoding="utf-8")
        for args in (
            ("init", "--quiet"),
            ("config", "user.email", "t@example.com"),
            ("config", "user.name", "T"),
            ("add", "ms"),
            ("commit", "--quiet", "-m", "first"),
        ):
            subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)
        self.pins = [
            self.add(lo=4, hi=4, note="alpha"),
            self.add(lo=11, hi=11, note="beta"),
            self.add(lo=18, hi=18, note="gamma"),
        ]
        new = (
            OLD.replace("Alpha paragraph talks about apples.", "Alpha paragraph talks about pears.")
            .replace("Filler five.\n", "Filler five.\nBeta follow-up sentence.\n")
            .replace("Filler seven.", "Filler 7.")
            .replace("Gamma paragraph talks about cherries.", "Gamma paragraph talks about plums.")
        )
        self.main.write_text(new, encoding="utf-8")
        t = time.time() + 5
        os.utime(self.main, (t, t))
        for args in (("add", "ms"), ("commit", "--quiet", "-m", "Resolve pins 1-3 (#7)")):
            subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)
        self.squash = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        self.ref = "PR #7 (%s)" % self.squash[:7]
        lines = new.split("\n")
        self.new_lines = {
            "alpha": lines.index("Alpha paragraph talks about pears.") + 1,
            "beta": lines.index("Beta follow-up sentence.") + 1,
            "gamma": lines.index("Gamma paragraph talks about plums.") + 1,
        }
        self.assertEqual(self.new_lines, {"alpha": 4, "beta": 14, "gamma": 19})
        for pid, key in zip(self.pins, ("alpha", "beta", "gamma"), strict=True):
            n = self.new_lines[key]
            code, d = self.call(
                "POST",
                "/api/pins/%d/close" % pid,
                {"reply": key, "ref": self.ref, "changes": [{"file": "main.tex", "lo": n, "hi": n}]},
            )
            self.assertEqual(code, 200, d)

    def test_each_pin_sees_its_own_change_in_the_squash_commit(self):
        """Owner workflow: squash commit of 3 pins, closed after the merge with changes in its numbers - each sees its own change."""
        want = {
            "alpha": ("+Alpha paragraph talks about pears.", ("follow-up", "plums", "Filler 7")),
            "beta": ("+Beta follow-up sentence.", ("pears", "plums", "Filler 7")),
            "gamma": ("+Gamma paragraph talks about plums.", ("pears", "follow-up", "Filler 7")),
        }
        for pid, key in zip(self.pins, ("alpha", "beta", "gamma"), strict=True):
            with self.subTest(pin=key):
                code, d = self.call("GET", "/api/revision-diff?commit=%s&pin=%d" % (self.squash, pid))
                self.assertEqual(code, 200, d)
                s = d["scope"]
                self.assertEqual((s["mode"], s["source"], s["hunks"], s["other"]), ("pin", "changes", 1, 3))
                mine, others = want[key]
                self.assertIn(mine, s["diff"])
                for o in others:
                    self.assertNotIn(o, s["diff"])
                    self.assertIn(o, s["other_diff"])
                spec = revision_spec(self.squash, pid)
                self.assertEqual(len(spec.scope), 1)

    def test_fix_next_to_the_pin_needs_changes_else_whole_commit(self):
        """Why agents always send changes: inference (overlap only) cannot find a fix placed next to the pin."""
        # the reason `changes` is what agents should send: beta's own range does not touch its fix
        rows = records(ps.APP.snapshot_pins())
        r = find_pin(rows, self.pins[1])
        r.pop("changes")
        write_records(rows)
        _, d = self.call("GET", "/api/revision-diff?commit=%s&pin=%d" % (self.squash, self.pins[1]))
        self.assertEqual((d["scope"]["mode"], d["scope"]["source"]), ("commit", "none"))

    def test_viewer_finds_the_squash_commit_from_a_pr_and_hash_ref(self):
        """The viewer's matchRevision picks the merged commit from ref = PR #N (hash)."""
        if not shutil.which("node"):
            self.skipTest("node not available")
        revs = revision_history(ps.APP.docs[0])["revisions"]
        out = run_node(
            extract_js_fn("matchRevision")
            + "\nconsole.log(JSON.stringify(matchRevision(%s,%s)));" % (json.dumps(self.ref), json.dumps(revs))
        )
        self.assertEqual(json.loads(out)["id"], self.squash)


class ScopedErrorBodies(ScopedRepo):
    """Every refusal this PR adds, with its exact status and JSON body. Error strings are part of the agent contract
    (api.md), so moving the checks between layers (coding rule R3) must not change a byte of them."""

    # Since 0.3.4 every refusal also names a reason code (additive; src/limn/web/tests/test_errors.py). The text stays byte-identical.
    PIN_MSG = {"error": "pin 은 핀 번호(양의 정수)여야 합니다.", "reason": "bad_pin"}
    NOT_HERE = {"error": "이 문서의 핀이 아닙니다.", "reason": "pin_not_in_doc"}

    def raw(self, method, path, body=None):
        """(status, parsed JSON body) for one request, without AccessBase's lenient decoding."""
        h, data = {}, b""
        if body is not None:
            data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
        code, _, out = split_resp(talk_to(ps, req(method, path, data, h)))
        return code, json.loads(out)

    def test_revision_routes_refuse_a_bad_or_foreign_pin_with_the_same_bodies(self):
        """A malformed pin is 400 and a pin of no/another document is 404, on all three GET routes and the POST."""
        for route in ("revision-diff", "revision-build", "revision-pdf"):
            with self.subTest(route=route):
                self.assertEqual(self.raw("GET", "/api/%s?commit=%s&pin=abc" % (route, self.fix)), (400, self.PIN_MSG))
                self.assertEqual(self.raw("GET", "/api/%s?commit=%s&pin=0" % (route, self.fix)), (400, self.PIN_MSG))
                self.assertEqual(self.raw("GET", "/api/%s?commit=%s&pin=999" % (route, self.fix)), (404, self.NOT_HERE))
        for body, want in (
            ({"commit": self.fix, "pin": "2"}, (400, self.PIN_MSG)),
            ({"commit": self.fix, "pin": True}, (400, self.PIN_MSG)),
            ({"commit": self.fix, "pin": 0}, (400, self.PIN_MSG)),
            ({"commit": self.fix, "pin": 999}, (404, self.NOT_HERE)),
            (
                {"commit": self.fix, "pins": 1},
                (400, {"error": "허용되지 않는 비교 PDF 요청 필드입니다.", "reason": "unknown_fields"}),
            ),
        ):
            with self.subTest(body=body):
                self.assertEqual(self.raw("POST", "/api/revision-build", body), want)

    def test_close_refuses_malformed_changes_with_the_same_bodies(self):
        """Each rejection of the close body's `changes` keeps its status and message, and names the offending item."""
        pid = self.add(lo=2, hi=2, note="for the bodies")
        ok = {"file": "main.tex", "lo": 1, "hi": 1}
        cases = (
            ("x", 'changes 는 [{"file", "lo", "hi"}] 목록이어야 합니다.', "bad_changes"),
            ([ok] * 51, "changes 는 50개 이하여야 합니다.", "too_many_changes"),
            (
                [ok, {"file": "main.tex", "lo": 1}],
                "changes[1] 는 file·lo·hi 세 필드만 가진 객체여야 합니다.",
                "bad_changes",
            ),
            (
                [{"file": " ", "lo": 1, "hi": 1}],
                "changes[0].file 은 비어 있지 않은 경로 문자열이어야 합니다.",
                "bad_changes",
            ),
            (
                [{"file": "main.tex", "lo": 3, "hi": 2}],
                "changes[0] 의 lo·hi 는 1 ≤ lo ≤ hi ≤ 1000000 인 정수여야 합니다.",
                "bad_changes",
            ),
            (
                [{"file": "../x.tex", "lo": 1, "hi": 1}],
                "changes[0].file 은 원고 폴더(--manuscript) 안의 파일이어야 합니다.",
                "change_outside_manuscript",
            ),
        )
        for changes, msg, reason in cases:
            with self.subTest(msg=msg):
                self.assertEqual(
                    self.raw("POST", "/api/pins/%d/close" % pid, {"changes": changes}),
                    (400, {"error": msg, "reason": reason}),
                )
        self.assertFalse(self.pin(pid).get("done"))

    def build_status(self, pid):
        """Start the scoped build for pid on self.fix and wait for its final status."""
        ps.APP.revision_requests.start(
            ps.APP.docs[0],
            self.fix,
            pid,
            authority=post_authority(ps.APP.revision_requests, dict(LOCAL_ACTOR), "revision-build", ps.APP.docs[0]),
        )
        end = time.time() + 30
        while time.time() < end:
            st = ps.APP.revision_requests.status(ps.APP.docs[0], self.fix, pid)
            if st["state"] != "running":
                return st
            time.sleep(0.05)
        self.fail("scoped build did not finish")

    def test_scoped_build_failures_keep_their_status_bodies(self):
        """When the pin's blocks cannot be re-read, do not all come back, or name an unsafe path, the build status says
        so with the same error text and reason as before."""
        revision_spec(self.fix, self.p2)  # warm the scope cache: the spec is not re-read below
        real = revisions.revision_changes
        cases = (
            ("unreadable", lambda *a: None, "이 핀의 변경만 골라 적용하지 못했습니다.", "scope_failed"),
            ("mismatch", lambda *a: [], "이 핀의 변경을 커밋에서 다시 찾지 못했습니다.", "scope_failed"),
        )
        for name, fake, msg, reason in cases:
            with self.subTest(case=name), mock.patch.object(revisions, "revision_changes", side_effect=fake):
                st = self.build_status(self.p2)
                self.assertEqual((st["state"], st["error"], st["reason"]), ("error", msg, reason))
                shutil.rmtree(revision_jobs.revision_cache_root(ps.APP.docs[0]))
        spec = revision_spec(self.fix, self.p2)
        bad = ("ms/../evil.tex", "ms/../evil.tex", 0, 1, 0, 1)
        evil = scoping.FileChange(bad[0], bad[1], (b"x\n",), (b"y\n",), (scoping.Block(0, 1, 0, 1),), False)
        with (
            mock.patch.object(revisions, "revision_spec", return_value=spec._replace(scope=(bad,))),
            mock.patch.object(revisions, "revision_changes", return_value=[evil]),
        ):
            st = self.build_status(self.p2)
        self.assertEqual(
            (st["state"], st["error"], st["reason"]),
            ("error", "사본에 허용되지 않는 경로가 있습니다.", "unsafe_snapshot"),
        )
        self.assertFalse((self.repo / "evil.tex").exists())
        self.assertIs(revisions.revision_changes, real)


class ScopedPdf(ScopedRepo):
    """The scoped comparison PDF: spec and cache identity, build status fields, real sandboxed builds."""

    def test_spec_key_depends_on_pin_commit_and_hunk_set(self):
        """One cached comparison per (pin, commit, hunk set); a pin owning the whole commit shares the whole-commit key."""
        whole = revision_spec(self.fix)
        s1, s2 = revision_spec(self.fix, self.p1), revision_spec(self.fix, self.p2)
        self.assertEqual(whole.scope, ())
        self.assertEqual(len({whole.key, s1.key, s2.key}), 3)
        self.assertEqual(s1.key, revision_spec(self.fix, self.p1).key)  # stable
        # a pin whose commit is entirely its own shares the whole-commit comparison (and its cache)
        self.assertEqual(revision_spec(self.solo, self.p4).key, revision_spec(self.solo).key)
        # the recorded change set is part of the identity: a different set is a different comparison
        rows = records(ps.APP.snapshot_pins())
        find_pin(rows, self.p1)["changes"] = [{"file": str(self.main.resolve()), "lo": 12, "hi": 12}]
        write_records(rows)
        self.assertNotEqual(revision_spec(self.fix, self.p1).key, s1.key)

    def test_changes_recorded_by_an_earlier_close_are_ignored(self):
        """Review finding (rollback): changes whose changes_at is not this close's done_at are ignored."""
        # 0.2.2 (after a rollback) neither clears changes on reopen nor writes them on close: a set whose changes_at is
        # not this close's done_at belongs to an older close, so inference decides (alpha's own hunk), not those lines.
        rows = records(ps.APP.snapshot_pins())
        r = find_pin(rows, self.p1)
        self.assertEqual(r["changes_at"], r["done_at"])
        r["changes"] = [{"file": str(self.main.resolve()), "lo": 12, "hi": 12}]  # beta's line
        r["done_at"] = "2026-09-26 09:00:00"
        write_records(rows)
        d = self.diff_ok(self.fix, self.p1)
        self.assertEqual((d["scope"]["source"], "pears" in d["scope"]["diff"]), ("inferred", True))

    def test_status_without_pin_never_carries_another_requests_pin_fields(self):
        """Review finding: pin fields are per request; a shared whole-commit status must not leak them to pin-less requests."""

        def compile(spec, jobdir, timeout):
            (jobdir / "revision.pdf").write_bytes(minimal_pdf("x"))
            return revisions.ComparisonBuilt([])

        with mock.patch.object(revision_execution, "revision_compile", side_effect=compile):
            # shares the whole key
            code, d = self.call("POST", "/api/revision-build", {"commit": self.solo, "pin": self.p4})
            self.assertEqual((d["scope"], d["pin"]), ("commit", self.p4))
            end = time.time() + 10
            while (
                time.time() < end
                and self.call("GET", "/api/revision-build?commit=%s" % self.solo)[1]["state"] == "running"
            ):
                time.sleep(0.05)
        for path in ("/api/revision-build?commit=%s" % self.solo,):
            code, d = self.call("GET", path)
            self.assertEqual(d["state"], "ready")
            self.assertFalse(set(d) & set(revisions.SCOPE_META), d)
        code, d = self.call("POST", "/api/revision-build", {"commit": self.solo})
        self.assertFalse(set(d) & set(revisions.SCOPE_META), d)
        code, d = self.call("GET", "/api/revision-build?commit=%s&pin=%d" % (self.solo, self.p4))
        self.assertEqual((d["scope"], d["pin"]), ("commit", self.p4))

    def test_failed_pin_subset_is_answered_from_the_cache_without_rebuilding(self):
        """Review finding: a deterministic scoped failure is not rebuilt on every visit."""
        calls = []

        def fail(spec, jobdir, timeout):
            calls.append(spec.scope)
            return revisions.StepFailed("compile_failed")

        with mock.patch.object(revision_execution, "revision_compile", side_effect=fail):
            for _ in range(2):
                self.call("POST", "/api/revision-build", {"commit": self.fix, "pin": self.p2})
                end = time.time() + 10
                while (
                    time.time() < end
                    and self.call("GET", "/api/revision-build?commit=%s&pin=%d" % (self.fix, self.p2))[1]["state"]
                    == "running"
                ):
                    time.sleep(0.05)
            code, d = self.call("POST", "/api/revision-build", {"commit": self.fix, "pin": self.p2})
            self.assertEqual((d["state"], d["reason"], d["scope"]), ("error", "compile_failed", "pin"))
        self.assertEqual(len(calls), 1)  # built once; the whole commit still retries (0.2.2 behaviour)

    def test_build_routes_accept_pin_and_report_scope_fields(self):
        """POST/GET revision-build and revision-pdf take pin and report scope, pin, hunks and other."""
        seen = []

        def compile(spec, jobdir, timeout):
            seen.append(spec.scope)
            (jobdir / "revision.pdf").write_bytes(minimal_pdf("x"))
            return revisions.ComparisonBuilt([])

        with mock.patch.object(revision_execution, "revision_compile", side_effect=compile):
            code, d = self.call("POST", "/api/revision-build", {"commit": self.fix, "pin": self.p2})
            self.assertIn(code, (200, 202), d)
            self.assertEqual((d["scope"], d["pin"], d["hunks"], d["other"]), ("pin", self.p2, 1, 2))
            end = time.time() + 10
            while (
                time.time() < end
                and self.call("GET", "/api/revision-build?commit=%s&pin=%d" % (self.fix, self.p2))[1]["state"]
                == "running"
            ):
                time.sleep(0.05)
            code, d = self.call("GET", "/api/revision-build?commit=%s&pin=%d" % (self.fix, self.p2))
            self.assertEqual((d["state"], d["scope"]), ("ready", "pin"))
            code, _ = self.call("GET", "/api/revision-pdf?commit=%s&pin=%d" % (self.fix, self.p2))
            self.assertEqual(code, 200)
            # the whole commit was not built
            self.assertEqual(self.call("GET", "/api/revision-pdf?commit=%s" % self.fix)[0], 404)
            code, d = self.call("POST", "/api/revision-build", {"commit": self.solo, "pin": self.p4})
            self.assertEqual(d["scope"], "commit")
        self.assertEqual(len(seen[0]), 1)
        for bad in (
            {"commit": self.fix, "pin": "2"},
            {"commit": self.fix, "pin": True},
            {"commit": self.fix, "pin": 999},
            {"commit": self.fix, "pins": 1},
        ):
            with self.subTest(bad=bad):
                self.assertIn(self.call("POST", "/api/revision-build", bad)[0], (400, 404))

    @needs_tex("bwrap", "latexdiff", "latexmk", "pdftotext")
    def test_real_scoped_build_marks_only_the_pins_change(self):
        """With TeX: the sandboxed scoped PDF shows the pin's change and none of the others; the checkout is untouched."""
        dest = self.repo / "job-beta"
        dest.mkdir()
        status = revision_execution.revision_compile(revision_spec(self.fix, self.p2), dest, 60)
        self.assertIsInstance(status, revisions.ComparisonBuilt, status)
        text = subprocess.check_output(["pdftotext", str(dest / "revision.pdf"), "-"], text=True)
        self.assertIn("blueberries", text)
        self.assertIn("bananas", text)
        self.assertNotIn("pears", text)  # alpha's change is not applied
        self.assertIn("cherries", text)  # gamma is still there, unmarked
        self.assertNotIn("second alpha", text)
        whole = self.repo / "job-whole"
        whole.mkdir()
        revision_execution.revision_compile(revision_spec(self.fix), whole, 60)
        self.assertIn("pears", subprocess.check_output(["pdftotext", str(whole / "revision.pdf"), "-"], text=True))
        self.assertEqual(self.main.read_text(encoding="utf-8"), NEW.replace("Filler two.", "Filler two, reworded."))

    @needs_tex("bwrap", "latexdiff", "latexmk")
    def test_scoped_build_is_an_error_when_the_subset_does_not_compile(self):
        """With TeX: half of an environment fix alone does not compile; the error lets the viewer fall back."""
        # one commit opens an environment for one pin and closes it for another: each half alone does not compile
        base = NEW.replace("Filler two.", "Filler two, reworded.")
        self.write(
            base.replace("Filler one.", "\\begin{itemize}\\item Filler one.").replace(
                "Filler eight.", "Filler eight.\\end{itemize}"
            )
        )
        both = self.commit("wrap the fillers in a list")
        opener = self.add(lo=7, hi=7, note="open")
        ps.APP.pin_lifecycle.close_pin(
            opener,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", opener),
            CloseRequest(ref=both[:8], changes=(lifecycle_input.CloseChange(str(self.main.resolve()), 7, 7).record(),)),
        )
        spec = revision_spec(both, opener)
        self.assertEqual(len(spec.scope), 1)
        dest = self.repo / "job-half"
        dest.mkdir()
        self.assertIn(
            revision_execution.revision_compile(spec, dest, 60),
            (revisions.StepFailed("compile_failed"), revisions.StepFailed("diff_failed")),
        )
        whole = self.repo / "job-both"
        whole.mkdir()
        self.assertIsInstance(
            revision_execution.revision_compile(revision_spec(both), whole, 60), revisions.ComparisonBuilt
        )


class ScopeReviewRegressions(AccessBase):
    """Findings of the independent review of PR #13 (probes in /tmp/limn-rev13/probes, kept here as regressions)."""

    BASE = "".join("Line %d of the manuscript.\n" % i for i in range(1, 41))
    DOC = "\\documentclass{article}\n\\begin{document}\n" + BASE + "\\end{document}\n"

    def setUp(self):
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        self.repo = self.src.parent
        self.main.write_text(self.DOC, encoding="utf-8")
        for args in (("init", "--quiet"), ("config", "user.email", "t@example.com"), ("config", "user.name", "T")):
            self.git(*args)
        self.commit("first")

    def git(self, *args):
        """Run git in the fixture repository and return its stdout."""
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout

    def write(self, text, path=None):
        """Write a manuscript file with an mtime in the future, so the next pin sync sees the change."""
        p = path or self.main
        p.write_text(text, encoding="utf-8")
        t = time.time() + 5
        os.utime(p, (t, t))

    def commit(self, msg):
        """Commit everything under ms/ and return the full hash."""
        self.git("add", "-A", "ms")
        self.git("commit", "--quiet", "-m", msg)
        return self.git("rev-parse", "HEAD").strip()

    def scope(self, commit, pid):
        """The scope object of GET /api/revision-diff?commit=&pin=."""
        code, d = self.call("GET", "/api/revision-diff?commit=%s&pin=%d" % (commit, pid))
        self.assertEqual(code, 200, d)
        return d["scope"]

    def test_changes_recorded_for_one_commit_do_not_select_hunks_of_another(self):
        """M1: pin A closed with changes (line 12) for commit X; a later commit Y edits line 12 for another pin. On Y
        the recorded lines are not A's, so only inference may attribute (labelled inferred); on X they still decide."""
        pa = self.add(lo=12, hi=12, note="A")
        x = self.DOC.replace("Line 10 of", "Line TEN of")
        self.write(x)
        X = self.commit("fix A")
        code, d = self.call(
            "POST",
            "/api/pins/%d/close" % pa,
            {"ref": "PR #1 (%s)" % X[:7], "changes": [{"file": "main.tex", "lo": 12, "hi": 12}]},
        )
        self.assertEqual(code, 200, d)
        Y = self.commit_y(x)
        self.assertEqual(self.scope(X, pa)["source"], "changes")
        self.assertNotEqual(self.scope(Y, pa)["source"], "changes")
        self.assertEqual(self.scope(Y, pa)["source"], "inferred")

    def commit_y(self, x):
        """Commit Y: pin B's fix on line 12 and another change on line 32."""
        self.write(x.replace("Line TEN of", "Line TEN (B) of").replace("Line 30 of", "Line 30 (C) of"))
        return self.commit("fix B and C")

    def test_a_transient_git_failure_is_not_cached_as_whole_commit(self):
        """m1: one git timeout shows the whole commit once; the next request scopes again."""
        pa, _ = self.add(lo=5, hi=5, note="A"), self.add(lo=30, hi=30, note="B")
        self.write(self.DOC.replace("Line 3 of", "Line THREE of").replace("Line 28 of", "Line 28x of"))
        X = self.commit("fix A and B")
        self.call("POST", "/api/pins/%d/close" % pa, {"ref": X[:8]})
        real, calls = revisions.revision_exec, {"n": 0}

        def flaky(cmd, *a, **k):
            if "--raw" in cmd and calls["n"] == 0:
                calls["n"] += 1
                return revisions.StepFailed("timeout")
            return real(cmd, *a, **k)

        with mock.patch.object(revisions, "revision_exec", flaky):
            first = self.scope(X, pa)["mode"]
        self.assertEqual((first, self.scope(X, pa)["mode"]), ("commit", "pin"))

    def test_scope_cache_entries_are_bounded_by_the_response_cap(self):
        """m2: a huge commit's patches are stored cut at REVISION_DIFF_MAX + 1 bytes (enough to flag truncation)."""
        n = 6000
        big = self.src / "big.tex"
        self.write(("a" * 199 + "\n") * n, big)
        self.commit("big old")
        pa = self.add(lo=5, hi=5, note="A")
        self.write("".join((("b" * 199 + "\n") if i % 2 else ("a" * 199 + "\n")) for i in range(n)), big)
        self.write(self.DOC.replace("Line 3 of", "Line THREE of"))
        X = self.commit("big change + A")
        self.call(
            "POST", "/api/pins/%d/close" % pa, {"ref": X[:8], "changes": [{"file": "main.tex", "lo": 5, "hi": 5}]}
        )
        s = self.scope(X, pa)
        self.assertEqual((s["mode"], s["other_truncated"]), ("pin", True))
        sc = next(iter(ps.APP.RT.scope_cache.values()))
        self.assertLessEqual(max(len(sc.diff), len(sc.other_diff)), scoping.REVISION_DIFF_MAX + 1)

    def test_scope_computations_run_at_most_two_at_a_time(self):
        """m3: cache misses read the commit on the request thread; at most SCOPE_SLOTS (2) do so at once.

        The commit read is held open until the test lets it go, so the two slots are provably taken together (no
        reliance on two threads happening to overlap); only with all five requests started and both slots held is
        the read released. The short wait for a third reader can only miss a defect, never fail a correct build."""
        pins = [self.add(lo=3 + i, hi=3 + i, note="p%d" % i) for i in range(5)]
        self.write(self.DOC.replace("Line 1 of", "Line ONE of"))
        X = self.commit("one change")
        base = self.git("rev-parse", X + "^").strip()
        real, cond = revisions.revision_changes, threading.Condition()
        state = {"inside": 0, "peak": 0, "started": 0, "released": False}

        def held(*a, **k):
            """The commit read, entered and counted, then held until the test releases every reader."""
            with cond:
                state["inside"] += 1
                state["peak"] = max(state["peak"], state["inside"])
                cond.notify_all()
                cond.wait_for(lambda: state["released"], timeout=20)
                state["inside"] -= 1
            return real(*a, **k)

        repo, paths = revisions.revision_scope(ps.APP.docs[0])
        revs = revision_history(ps.APP.docs[0])["revisions"]

        def request(pid):
            """One scoping request for pid, counted as started before it asks for a slot."""
            with cond:
                state["started"] += 1
                cond.notify_all()
            revisions.revision_pin_scope(
                ps.APP.docs[0], repo, tuple(paths), base, X, pid, revs, ps.APP.revision_context()
            )

        with mock.patch.object(revisions, "revision_changes", side_effect=held):
            ts = [threading.Thread(target=request, args=(pid,)) for pid in pins]
            for t in ts:
                t.start()
            try:
                with cond:
                    both = cond.wait_for(lambda: state["inside"] == 2 and state["started"] == len(pins), timeout=20)
                    third = cond.wait_for(lambda: state["inside"] > 2, timeout=0.2)
            finally:
                with cond:
                    state["released"] = True
                    cond.notify_all()
                for t in ts:
                    t.join(20)
        self.assertTrue(both, state)
        self.assertFalse(third, state)
        self.assertEqual(state["peak"], 2)
        self.assertEqual(state["inside"], 0)

    def test_pins_with_the_same_blocks_share_one_comparison_pdf(self):
        """m4: the comparison is keyed by (commit, block set), not by pin - two pins on the same fix build once."""
        pa, pb = self.add(lo=5, hi=5, note="A"), self.add(lo=5, hi=5, note="B")
        self.write(self.DOC.replace("Line 3 of", "Line THREE of").replace("Line 28 of", "Line 28x of"))
        X = self.commit("fix A and something else")
        ka, kb = (revision_spec(X, p).key for p in (pa, pb))
        self.assertEqual(ka, kb)
        self.assertNotEqual(ka, revision_spec(X).key)

    def test_scoped_comparisons_never_evict_whole_commit_ones(self):
        """m4: pin-scoped cache entries have their own limit, so many pins do not push out the whole-commit PDFs."""
        root = revision_jobs.revision_cache_root(ps.APP.docs[0])
        whole = [root / ("%064x" % i) for i in range(3)]
        scoped = [root / ("%064x" % (100 + i)) for i in range(revisions.REVISION_SCOPED_KEEP + 4)]
        for i, d in enumerate(whole + scoped):
            d.mkdir()
            if d in scoped:
                (d / revisions.SCOPED_MARK).write_text("")
            t = time.time() - 1000 + (i if d in whole else 500 + i)  # every scoped entry is newer
            os.utime(d, (t, t))
        revision_jobs.revision_prune(root, "f" * 64, ps.APP.RT.revision_jobs.active)
        self.assertTrue(all(d.exists() for d in whole))
        self.assertEqual(sum(d.exists() for d in scoped), revisions.REVISION_SCOPED_KEEP)

    def test_a_synthetic_tree_that_cannot_be_written_is_a_scope_failure(self):
        """m5: an OSError while writing the synthetic tree is the ScopeUnwritable refusal, reported as scope_failed
        (deterministic, answered from the cache) - not a generic build_failed with a traceback."""
        dest = Path(self.tmp.name) / "dest"
        dest.mkdir()
        (dest / "main.tex").write_text("x")
        spec = revisions.RevisionSpec(self.repo, "ms", Path("main.tex"), "a" * 40, "b" * 40, "k" * 64)
        with (
            mock.patch.object(revisions, "revision_changes", return_value=[]),
            mock.patch.object(
                revision_execution, "plan_scope_writes", return_value=[scoping.ScopeWrite("main.tex/x.tex", b"x")]
            ),
        ):
            refused = revision_execution.revision_apply_scope(spec, dest)
        self.assertEqual(refused, scoping.ScopeUnwritable())
        err = scope_http_error(refused)
        self.assertEqual((err.code, err.body["reason"]), (422, "scope_failed"))

    def test_a_file_that_becomes_a_symlink_is_never_applied_as_text(self):
        """m6: a file -> symlink type change has no blocks (one of the other changes, shown with its modes), and the
        synthetic tree keeps the old regular file instead of the link's target text."""
        sec = self.src / "sec.tex"
        self.write("Section text.\n", sec)
        self.write(self.DOC.replace("\\end{document}", "\\input{sec}\n\\end{document}"))
        self.commit("add sec")
        pa = self.add(lo=5, hi=5, note="A")
        sec.unlink()
        os.symlink("/etc/hostname", sec)
        self.write(self.main.read_text().replace("Line 3 of", "Line THREE of"))
        X = self.commit("typechange sec + A")
        code, d = self.call(
            "POST", "/api/pins/%d/close" % pa, {"ref": X[:8], "changes": [{"file": "main.tex", "lo": 5, "hi": 5}]}
        )
        self.assertEqual(code, 200, d)  # (a changes item naming sec.tex resolves outside the folder: 400)
        s = self.scope(X, pa)
        self.assertEqual((s["mode"], s["source"], s["hunks"], s["other"]), ("pin", "changes", 1, 1))
        self.assertIn("new mode 120000", s["other_diff"])
        spec = revision_spec(X, pa)
        dest = Path(self.tmp.name) / "dest"
        revision_execution.revision_snapshot(spec, spec.base, dest)
        revision_execution.revision_apply_scope(spec, dest)
        self.assertFalse((dest / "sec.tex").is_symlink())
        self.assertEqual((dest / "sec.tex").read_text(), "Section text.\n")


# ---------------------------------------------------------------- pure rules of the comparison build and its status


class LsTreeRows(unittest.TestCase):
    """parse_ls_tree_row reads one `git ls-tree -r -l -z` row into a file of the build root, or refuses it."""

    OID = "a" * 40

    def row(self, name: bytes, mode: bytes = b"100644", kind: bytes = b"blob", size: bytes = b"12") -> bytes:
        """A row as git writes it: mode, type, object id and size, a tab, then the name."""
        return b"%s %s %s %s\t%s" % (mode, kind, self.OID.encode(), size.rjust(7), name)

    def test_regular_files_under_the_build_root_are_read_relative_to_it(self):
        """A regular or executable blob under the prefix gives its path below the prefix, its id and its size; at the
        repository root (empty prefix) the name is the path."""
        for row, prefix, path in (
            (self.row(b"ms/main.tex"), "ms/", "main.tex"),
            (self.row(b"ms/sub/run.tex", mode=b"100755", size=b"0"), "ms/", "sub/run.tex"),
            (self.row(b"main.tex"), "", "main.tex"),
            (self.row("ms/한글 이름.tex".encode()), "ms/", "한글 이름.tex"),
        ):
            with self.subTest(row=row):
                size = 0 if b"run.tex" in row else 12
                self.assertEqual(
                    revision_execution.parse_ls_tree_row(row, prefix),
                    revision_execution.TreeFile(Path(path), self.OID, size),
                )

    def test_rows_a_snapshot_must_not_write_are_unsafe(self):
        """Symlinks, submodules, names outside the prefix or that could escape or confuse the snapshot folder, and
        rows that do not parse are all UnsafeTreeRow."""
        unsafe = revision_execution.UnsafeTreeRow()
        for row, prefix in (
            (self.row(b"ms/link.tex", mode=b"120000"), "ms/"),
            (self.row(b"ms/module", mode=b"160000", kind=b"commit", size=b"-"), "ms/"),
            (self.row(b"other/main.tex"), "ms/"),
            (self.row(b"ms/"), "ms/"),
            (self.row(b"ms/../x.tex"), "ms/"),
            (self.row(b"ms/./x.tex"), "ms/"),
            (self.row(b"ms/.git/config"), "ms/"),
            (self.row(b"/abs.tex"), ""),
            (self.row(b"ms/back\\slash.tex"), "ms/"),
            (self.row(b"ms/ctrl\x01.tex"), "ms/"),
            (self.row(b"ms/tab\tin name.tex"), "ms/"),
            (self.row(b"ms/bad\xff.tex"), "ms/"),
            (self.row(b"ms/x.tex", size=b"many"), "ms/"),
            (b"100644 blob %s 12 ms/no-tab.tex" % self.OID.encode(), "ms/"),
            (b"100644 blob 12\tms/three-fields.tex", "ms/"),
            (b"100644 blob \xff\xfe 12\tms/x.tex", "ms/"),
        ):
            with self.subTest(row=row):
                self.assertEqual(revision_execution.parse_ls_tree_row(row, prefix), unsafe)


class ComparisonStatusRules(unittest.TestCase):
    """answered_from_cache (when POST answers without building) and status_body (the JSON a status is answered
    with), both pure."""

    SPEC = revisions.RevisionSpec(Path("/repo"), "ms", Path("main.tex"), "b" * 40, "c" * 40, "k" * 64)
    META = {"scope": "pin", "pin": 7, "source": "changes", "hunks": 1, "other": 2}

    def test_a_ready_pdf_is_answered_and_a_miss_builds(self):
        """A finished PDF is answered from the cache for any spec; no entry always builds."""
        for scoped in (False, True):
            with self.subTest(scoped=scoped):
                self.assertTrue(
                    revision_jobs.answered_from_cache(revision_jobs.ReadyComparison({"state": "ready"}), scoped)
                )
                self.assertFalse(revision_jobs.answered_from_cache(revision_jobs.IdleComparison(), scoped))

    def test_only_a_pin_subsets_deterministic_failure_is_answered_from_the_cache(self):
        """compile_failed, diff_failed and scope_failed of a pin subset would fail again, so they are answered; the
        same failures of a whole commit, and any other failure of either, build again."""
        for reason in ("compile_failed", "diff_failed", "scope_failed", "timeout", "build_failed", None):
            failed = revision_jobs.FailedComparison({"state": "error", "reason": reason})
            with self.subTest(reason=reason):
                self.assertFalse(revision_jobs.answered_from_cache(failed, scoped=False))
                self.assertEqual(
                    revision_jobs.answered_from_cache(failed, scoped=True),
                    reason in revision_jobs.DETERMINISTIC_FAILURES,
                )

    def test_a_stored_status_is_answered_as_stored_with_the_specs_identity_over_it(self):
        """A finished status keeps its stored fields and their order; the spec's identity replaces what the file says
        and the request's pin fields come last."""
        stored = {"z": 1, "state": "error", "job_id": "old", "reason": "timeout", "warnings": []}
        body = revision_jobs.status_body(revision_jobs.FailedComparison(stored), self.SPEC._replace(meta=self.META))
        self.assertEqual(
            list(body.items()),
            [("z", 1), ("state", "error"), ("job_id", "k" * 64), ("reason", "timeout"), ("warnings", [])]
            + [("base", "b" * 40), ("head", "c" * 40), ("engine", "pdflatex")]
            + list(self.META.items()),
        )

    def test_a_miss_and_a_running_job_have_their_own_bodies(self):
        """A miss is "idle" with the spec's identity; a running job's stored fields get only the request's pin
        fields (a running status never carries another request's)."""
        self.assertEqual(
            revision_jobs.status_body(revision_jobs.IdleComparison(), self.SPEC),
            {"job_id": "k" * 64, "base": "b" * 40, "head": "c" * 40, "engine": "pdflatex"}
            | {"state": "idle", "warnings": [], "error": None, "reason": None},
        )
        running = revision_jobs.RunningComparison({"job_id": "k" * 64, "state": "running", "pin": 3})
        self.assertEqual(
            revision_jobs.status_body(running, self.SPEC._replace(meta=self.META)),
            {"job_id": "k" * 64, "state": "running"} | self.META,
        )


if __name__ == "__main__":
    unittest.main()

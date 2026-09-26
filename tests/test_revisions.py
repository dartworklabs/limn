"""limn.revisions through the server: manuscript history, the pin-scoped diff, comparison builds in the sandbox, and
the outline of a revision's snapshot, over the server's revision context and its HTTP routes.

The module's boundaries and the refusal values of pin scoping are tests/test_scope.py; the attribution rules are
tests/test_v03.py. Here the revision services run against a real temporary git repository wired as server.py wires
them (revision_context), and the routes are driven through the handler.

Run: uv run pytest tests/test_revisions.py
"""
import errno
import json
import os
import shutil
import subprocess
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from limn import build as limn_build, meta as limn_meta, revisions, scope as scoping
from limn.documents import Doc
from limn.web import parse
from limn.web.errors import InputRejected

from helpers import TEX, Base, ps, req, revision_spec, split_resp


class ManuscriptRevisions(Base):
    def setUp(self):
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        self.repo = self.src.parent
        self.secret = self.repo / "other" / "private.tex"
        self.secret.parent.mkdir()
        self.secret.write_text("private text\n", encoding="utf-8")
        for cmd in (["git", "init", "--quiet"], ["git", "config", "user.email", "t@example.com"],
                    ["git", "config", "user.name", "T"], ["git", "add", "ms/main.tex", "other/private.tex"],
                    ["git", "commit", "--quiet", "-m", "first"]):
            subprocess.run(cmd, cwd=self.repo, check=True, capture_output=True)
        self.first = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        self.main.write_text(TEX + "New manuscript sentence.\n", encoding="utf-8")
        self.secret.write_text("hidden change\n", encoding="utf-8")
        for cmd in (["git", "add", "ms/main.tex", "other/private.tex"],
                    ["git", "commit", "--quiet", "-m", "manuscript update"]):
            subprocess.run(cmd, cwd=self.repo, check=True, capture_output=True)
        self.latest = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()

    def test_latest_revision_diff_is_real_and_scoped(self):
        history = revisions.revision_history(ps.DOCS[0])
        self.assertTrue(history["available"])
        self.assertEqual(history["revisions"][0]["id"], self.latest)
        d = ps.revision_diff(ps.DOCS[0], self.latest)
        self.assertIn("New manuscript sentence.", d["diff"])
        self.assertNotIn("hidden change", d["diff"])
        self.assertNotIn("other/private.tex", d["diff"])
        self.assertFalse(d["truncated"])

    def test_http_revision_endpoints(self):
        code, _, raw = split_resp(self.talk(req("GET", "/api/revisions")))
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)["revisions"][0]["id"], self.latest)
        code, _, raw = split_resp(self.talk(req("GET", "/api/revision-diff?commit=" + self.latest)))
        self.assertEqual(code, 200)
        self.assertIn("New manuscript sentence.", json.loads(raw)["diff"])
        code, _, _ = split_resp(self.talk(req("GET", "/api/revision-diff?commit=HEAD")))
        self.assertEqual(code, 400)

    def test_rejects_arbitrary_commit_and_bad_id(self):
        """Only a full SHA-1 parses (400 bad_commit otherwise), and only a commit in the document's recent list is read:
        even a name that got past the parser is never handed to git."""
        for commit in ("HEAD", "--help"):
            self.assertEqual(parse.parse_commit(commit), InputRejected("올바른 커밋 ID가 아닙니다.", "bad_commit"))
        for commit in ("HEAD", "a" * 40, "--help"):
            self.assertEqual(ps.revision_diff(ps.DOCS[0], commit), revisions.CommitNotRecent())

    def test_shared_build_root_keeps_document_histories_separate(self):
        heads = {"ms": self.main}
        for key in ("hl", "cl"):
            path = self.repo / key / (key + ".tex")
            path.parent.mkdir()
            path.write_text("\\documentclass{article}\n" + key + "\n", encoding="utf-8")
            subprocess.run(["git", "add", str(path.relative_to(self.repo))], cwd=self.repo,
                           check=True, capture_output=True)
            subprocess.run(["git", "commit", "--quiet", "-m", key + " update"], cwd=self.repo,
                           check=True, capture_output=True)
            heads[key] = path
        docs = [Doc(k, k, src=self.repo, main=path, paths=ps.C) for k, path in heads.items()]
        for d in docs:
            history = revisions.revision_history(d)
            self.assertTrue(history["available"])
            self.assertEqual(history["revisions"][0]["subject"],
                             "manuscript update" if d.key == "ms" else d.key + " update")
        hl_head = revisions.revision_history(docs[1])["revisions"][0]["id"]
        self.assertEqual(ps.revision_diff(docs[0], hl_head), revisions.CommitNotRecent())

    def test_main_path_outside_document_source_is_unavailable(self):
        bad = Doc("bad", "bad", src=self.src, main=self.secret, paths=ps.C)
        self.assertFalse(revisions.revision_history(bad)["available"])
        link = self.src / "linked.tex"
        link.symlink_to(self.secret)
        linked = Doc("linked", "linked", src=self.src, main=link, paths=ps.C)
        self.assertFalse(revisions.revision_history(linked)["available"])

    def test_caps_large_diff(self):
        old = scoping.REVISION_DIFF_MAX
        scoping.REVISION_DIFF_MAX = 50
        try:
            d = ps.revision_diff(ps.DOCS[0], self.latest)
        finally:
            scoping.REVISION_DIFF_MAX = old
        self.assertTrue(d["truncated"])
        self.assertLessEqual(len(d["diff"].encode("utf-8")), 53)  # UTF-8 replacement at the byte boundary

    def test_revision_spec_uses_first_parent_and_rejects_root(self):
        spec = revision_spec(self.latest)
        self.assertEqual((spec.base, spec.head), (self.first, self.latest))
        self.assertEqual(revision_spec(self.first), revisions.NoParent())

    def test_revision_snapshot_uses_git_and_rejects_symlinks(self):
        self.main.write_text("uncommitted secret")
        dest = self.repo / "snapshot"
        spec = revision_spec(self.latest)
        revisions.revision_snapshot(spec, spec.head, dest)
        self.assertIn("New manuscript sentence.", (dest / "main.tex").read_text())
        self.assertFalse((dest / "other").exists())
        (self.src / "escape.tex").symlink_to(self.secret)
        for cmd in (["git", "add", "ms/escape.tex"], ["git", "commit", "-qm", "link"]):
            subprocess.run(cmd, cwd=self.repo, check=True, capture_output=True)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        self.assertEqual(revisions.revision_snapshot(revision_spec(head), head, self.repo / "bad-snapshot"),
                         revisions.StepFailed("unsafe_snapshot"))

    def test_outline_uses_only_current_pdf_aux_and_balanced_tex_groups(self):
        current = ps.C.state / "pages-20260924010000"
        current.mkdir()
        (ps.C.state / "pages.cur").write_text(current.name)
        (current / "main.aux").write_text(
            r"\@writefile{toc}{\contentsline {section}{\numberline {2}A \textbf{nested {title}} \& B}{iv}{section.2}}" + "\n" +
            r"\@writefile{toc}{\contentsline {subsection}{\numberline {2.1}Use \texorpdfstring{$x^2$}{x squared}}{8}{subsection.2.1}}" + "\n")
        ps.C.build.mkdir()
        (ps.C.build / "main.aux").write_text("wrong next build")
        data = limn_meta.outline_labels(ps.DOCS[0])
        self.assertEqual(data["build"], current.name)
        self.assertEqual(data["labels"], [
            {"number": "2", "title": "A nested title & B", "page": "iv", "level": "section", "anchor": "section.2"},
            {"number": "2.1", "title": "Use x squared", "page": "8", "level": "subsection", "anchor": "subsection.2.1"},
        ])

    def test_outline_missing_snapshot_does_not_read_mutable_build(self):
        ps.C.build.mkdir()
        (ps.C.build / "main.aux").write_text(r"\@writefile{toc}{\contentsline {section}{\numberline {9}Stale}{1}{section.9}}")
        self.assertEqual(limn_meta.outline_labels(ps.DOCS[0])["labels"], [])

    def _wait_revision(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = ps.revision_status(ps.DOCS[0], self.latest)
            if status["state"] != "running":
                return status
            time.sleep(.01)
        self.fail("revision worker did not finish")

    def test_async_revision_http_deduplicates_caches_and_preserves_current_build(self):
        entered, release = threading.Event(), threading.Event()
        original = self.main.read_bytes()
        marker = ps.C.state / "pages.cur"
        marker.write_text("pages-20260924000000")
        before = dict(ps.BUILD_STATE)
        calls = []
        def compile(spec, jobdir, timeout):
            calls.append(spec)
            entered.set()
            release.wait(3)
            (jobdir / "revision.pdf").write_bytes(b"%PDF-1.4\nrevision")
            return {"state": "ready", "warnings": ["test warning"], "error": None, "reason": None}
        body = json.dumps({"commit": self.latest}).encode()
        request = req("POST", "/api/revision-build", body, {"Content-Type": "application/json"})
        with mock.patch.object(revisions, "revision_compile", side_effect=compile):
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
        self.assertEqual(ps.BUILD_STATE, before)
        with mock.patch.object(revisions, "revision_history", return_value={"available": True, "revisions": []}):
            self.assertEqual(split_resp(self.talk(req("GET", "/api/revision-pdf?commit=" + self.latest)))[0], 404)
            self.assertEqual(ps.revision_status(ps.DOCS[0], self.latest), revisions.CommitNotRecent())

    def test_revision_failure_has_no_pdf_and_can_retry(self):
        with mock.patch.object(revisions, "revision_compile", return_value=revisions.StepFailed("timeout")) as run:
            ps.revision_start(ps.DOCS[0], self.latest)
            status = self._wait_revision()
            self.assertEqual((status["state"], status["reason"]), ("error", "timeout"))
            self.assertEqual(ps.revision_pdf(ps.DOCS[0], self.latest), revisions.RevisionNotReady())
            ps.revision_start(ps.DOCS[0], self.latest)
            self._wait_revision()
            self.assertEqual(run.call_count, 2)

    def test_revision_requests_enforce_origin_allowlist_and_field_validation(self):
        body = json.dumps({"commit": self.latest}).encode()
        ps.C.allow = frozenset({"allowed@example.com"})
        code, _, _ = split_resp(self.talk(req("POST", "/api/revision-build", body,
            {"Content-Type": "application/json", "Tailscale-User-Login": "stranger@example.com"})))
        self.assertEqual(code, 403)
        ps.C.allow = frozenset()
        code, _, _ = split_resp(self.talk(req("POST", "/api/revision-build", body,
            {"Content-Type": "application/json", "Origin": "https://evil.example"})))
        self.assertEqual(code, 403)
        for bad in ({"commit": []}, {"commit": "HEAD"}, {"commit": self.latest, "command": "evil"}):
            code, _, _ = split_resp(self.talk(req("POST", "/api/revision-build", json.dumps(bad).encode(),
                {"Content-Type": "application/json"})))
            self.assertEqual(code, 400)
        self.assertEqual(split_resp(self.talk(req("GET", "/api/revision-build?commit=HEAD")))[0], 400)

    def test_revision_source_limits_and_gitlinks_are_rejected(self):
        spec = revision_spec(self.latest)
        with mock.patch.object(revisions, "REVISION_FILE_MAX", 1):
            self.assertEqual(revisions.revision_snapshot(spec, self.latest, self.repo / "large"),
                             revisions.StepFailed("snapshot_size"))
        for cmd in (["git", "update-index", "--add", "--cacheinfo", "160000," + self.first + ",ms/sub"],
                    ["git", "commit", "-qm", "add submodule"]):
            subprocess.run(cmd, cwd=self.repo, check=True, capture_output=True)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        self.assertEqual(revisions.revision_snapshot(spec, head, self.repo / "submodule-snapshot"),
                         revisions.StepFailed("unsafe_snapshot"))

    def test_revision_jobs_are_bounded_and_cache_expires(self):
        with mock.patch.object(ps.REVISION_JOBS, "slots", threading.BoundedSemaphore(0)):
            self.assertEqual(ps.revision_start(ps.DOCS[0], self.latest), revisions.AllSlotsBusy())
        spec = revision_spec(self.latest)
        root = revisions.revision_cache_root(ps.DOCS[0])
        jobdir = root / spec.key
        jobdir.mkdir()
        (jobdir / "revision.pdf").write_bytes(b"%PDF-1.4")
        status = jobdir / "status.json"
        status.write_text(json.dumps({"state": "ready"}))
        self.assertEqual(ps.revision_status(ps.DOCS[0], self.latest)["state"], "ready")
        os.utime(status, (1, 1))
        self.assertEqual(ps.revision_status(ps.DOCS[0], self.latest)["state"], "idle")
        for i in range(8):
            (root / ("%064x" % i)).mkdir()
        revisions.revision_prune(root, spec.key, ps.REVISION_JOBS.active)
        self.assertLessEqual(sum(p.is_dir() for p in root.iterdir()), revisions.REVISION_CACHE_KEEP)

    def test_corrupt_revision_cache_is_a_miss(self):
        spec = revision_spec(self.latest)
        root = revisions.revision_cache_root(ps.DOCS[0])
        jobdir = root / spec.key
        jobdir.mkdir()
        for content in ("[]", "null", "1", "bad JSON", '{"state":"running"}', '{"state":"ready"}'):
            (jobdir / "status.json").write_text(content)
            self.assertEqual(ps.revision_status(ps.DOCS[0], self.latest)["state"], "idle")

    def test_sandbox_is_required_and_has_no_unsandboxed_fallback(self):
        with mock.patch.object(shutil, "which", return_value=None):
            self.assertEqual(revisions.revision_sandbox(self.repo, Path("."), "latexmk", []),
                             revisions.StepFailed("sandbox_tools"))
        with self.assertRaises(ValueError):
            revisions.revision_sandbox(self.repo, Path("."), "sh", [])

    def test_revision_exec_bounds_output_and_time(self):
        self.assertEqual(revisions.revision_exec(["python3", "-c", "print('x' * 10000)"], self.repo, 2, 100),
                         revisions.StepFailed("size"))
        self.assertEqual(revisions.revision_exec(["python3", "-c", "import time; time.sleep(20)"], self.repo, .1),
                         revisions.StepFailed("timeout"))

    def test_revision_exec_keeps_its_answer_when_the_group_holds_only_exited_processes(self):
        """The cleanup kill of the command's process group is refused with EPERM on macOS when every member has
        exited but is not reaped yet (checked: os.killpg of a group whose leader is a zombie raises PermissionError
        there, where Linux delivers or answers ESRCH). The command's result - its output, or its own refusal - is
        still what revision_exec gives. Before the fix the PermissionError escaped, and GET /api/revision-diff?pin=
        answered 500 "Operation not permitted" under load (the ScopedViewer flake)."""
        eperm = PermissionError(errno.EPERM, "Operation not permitted")
        with mock.patch.object(revisions.os, "killpg", side_effect=eperm) as killpg:
            self.assertEqual(revisions.revision_exec(["python3", "-c", "print('ok')"], self.repo, 10), (0, b"ok\n", b""))
            self.assertEqual(revisions.revision_exec(["python3", "-c", "print('x' * 10000)"], self.repo, 10, 100),
                             revisions.StepFailed("size"))
        self.assertEqual(killpg.call_count, 2)

    def test_outline_complex_titles_keep_alignment_and_http_build_identity(self):
        pages = ps.C.state / "pages"
        pages.mkdir()
        (pages / "main.aux").write_text(
            r"\@writefile{toc}{\contentsline {section}{\numberline {1}Bad \unknown{macro}}{1}{section.1}}" + "\n" +
            r"\@writefile{toc}{\contentsline {section}{\protect\numberline {2}A \{literal\} title}{2}{section.2}}" + "\n" +
            r"\@writefile{toc}{\contentsline {section}{Unnumbered}{3}{section*.3}}" + "\n" +
            r"\@writefile{lof}{\contentsline {figure}{\numberline {1}Not a section}{4}{figure.1}}")
        code, _, raw = split_resp(self.talk(req("GET", "/api/outline-labels")))
        self.assertEqual(code, 200)
        data = json.loads(raw)
        self.assertEqual(data["build"], "pages")
        self.assertEqual([r["number"] for r in data["labels"]], ["", "2", ""])
        self.assertEqual(data["labels"][1]["title"], "A {literal} title")
        self.assertEqual(data["labels"][0]["title"], "")

    def test_page_snapshot_keeps_aux_with_its_pdf(self):
        ps.C.build.mkdir()
        pdf, aux = ps.C.build / "main.pdf", ps.C.build / "main.aux"
        pdf.write_bytes(b"%PDF-1.4")
        aux.write_text(r"\@writefile{toc}{\contentsline {section}{\numberline {1}Before}{1}{section.1}}")
        def render(cmd, **kwargs):
            Path(str(cmd[-1]) + "-1.png").write_bytes(b"png")
            return subprocess.CompletedProcess(cmd, 0)
        with mock.patch.object(subprocess, "run", side_effect=render):
            pages, error = limn_build.render_pages(ps.DOCS[0], pdf, [aux], ps.C.dpi)
        self.assertIsNone(error)
        (ps.C.state / "pages.cur").write_text(pages.name)
        aux.write_text("changed by a failed next build")
        self.assertEqual(limn_meta.outline_labels(ps.DOCS[0])["labels"][0]["title"], "Before")

    @unittest.skipUnless(all(shutil.which(t) for t in ("bwrap", "latexdiff", "latexmk", "pdftotext")), "TeX sandbox tools unavailable")
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
        status = revisions.revision_compile(revision_spec(head), dest, 30)
        self.assertEqual(status["state"], "ready")
        text = subprocess.check_output(["pdftotext", str(dest / "revision.pdf"), "-"], text=True)
        self.assertIn("Old", text)
        self.assertIn("New", text)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.src.iterdir()})
        self.assertFalse(list(dest.glob("work-*")))


if __name__ == "__main__":
    unittest.main()

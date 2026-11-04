"""The changes view of a Markdown document (ADR-0025; docs/handbook/api.md §변경 보기와 비교 PDF): the Git history of its
own file alone, the source diff of those commits with a pin's own hunks, and no comparison PDF.

A LaTeX main and a Markdown document sit in one folder of a real temporary repository, one commit per file, so each
history answers exactly which commits touched its own files: the LaTeX document's suffix pathspec never names the .md,
and the Markdown document's file list never names the .tex. The Markdown file has a form feed before the pinned line,
so a pin numbered by str.splitlines() sits one line below git's number for the same text. No --doc suffix chooses the
Markdown kind yet, so the document is made directly.

Run: uv run pytest -q src/limn/revisions/tests/test_markdown_revisions.py
"""

import shutil

from limn.platform.git import run_git
from limn.runtime.documents import Doc

from helpers import ps
from helpers_access import AccessBase

FILLER = "".join("Filler %d.\n" % i for i in range(1, 11))
# Line 3 holds a form feed: str.splitlines() makes it lines 3 and 4, git keeps one line, so from there on a pin's line
# number is git's plus one ("Beta line." is pin line 7, git line 6).
PLAN = "# Plan\n\nIntro.\x0cAfter a form feed.\n\nAlpha line.\nBeta line.\n\n" + FILLER + "\nOmega line.\n"


class MarkdownHistory(AccessBase):
    """ms (LaTeX, main.tex) and nt (Markdown, plan.md) in the manuscript folder, committed in order: everything
    (initial), an edit of two separate lines of plan.md (markdown edit), an edit of main.tex (latex edit)."""

    def setUp(self):
        """Serve ms and nt over one folder and make the three commits."""
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        self.md = self.src / "plan.md"
        self.md.write_text(PLAN, encoding="utf-8")
        self.nt = Doc("nt", "계획", "markdown", self.src, self.md, paths=ps.APP.C.paths)
        ps.APP.set_docs([Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths), self.nt])
        self.addCleanup(ps.APP.set_docs, None)
        self.git("init", "--quiet", "-b", "main")
        self.git("config", "user.email", "alice@example.com")
        self.git("config", "user.name", "Alice")
        self.commits = {"initial": self.commit("initial", ".")}
        self.md.write_text(
            PLAN.replace("Beta line.", "Beta line, reworded.").replace("Omega line.", "Omega line, reworded."),
            encoding="utf-8",
        )
        self.commits["markdown edit"] = self.commit("markdown edit", "plan.md")
        self.main.write_text(self.main.read_text(encoding="utf-8") + "% latex edit\n", encoding="utf-8")
        self.commits["latex edit"] = self.commit("latex edit", "main.tex")

    def git(self, *args):
        """Run a fixture git command in the manuscript folder; its stdout, stripped."""
        done = run_git(list(args), self.src, 10)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def commit(self, subject, rel):
        """Commit rel (a path or '.') with subject; the new commit's full id."""
        self.git("add", rel)
        self.git("commit", "--quiet", "-m", subject)
        return self.git("rev-parse", "HEAD")

    def subjects(self, doc):
        """The subjects of GET /api/revisions?doc=<doc>, newest first."""
        code, body = self.call("GET", "/api/revisions?doc=" + doc)
        self.assertEqual(code, 200, body)
        return [r["subject"] for r in body["revisions"]]

    def diff(self, doc, commit, pin=None):
        """GET /api/revision-diff for doc and commit (and pin): (status, body)."""
        path = "/api/revision-diff?doc=%s&commit=%s" % (doc, commit)
        return self.call("GET", path + ("" if pin is None else "&pin=%d" % pin))

    def test_each_document_lists_only_the_commits_of_its_own_files(self):
        """A commit that touched only plan.md is in the Markdown document's history and not in the LaTeX document's; a
        commit that touched only main.tex the other way round. Both start from the commit that added both."""
        self.assertEqual(self.subjects("nt"), ["markdown edit", "initial"])
        self.assertEqual(self.subjects("ms"), ["latex edit", "initial"])

    def test_the_source_diff_of_a_markdown_commit_and_no_other_documents_commit(self):
        """The Markdown commit's diff names plan.md and its new lines and nothing of main.tex; each document's commit is
        not read through the other document (404 commit_not_recent)."""
        code, body = self.diff("nt", self.commits["markdown edit"])
        self.assertEqual(code, 200, body)
        self.assertIn("+++ b/plan.md", body["diff"])
        self.assertIn("+Beta line, reworded.", body["diff"])
        self.assertNotIn("main.tex", body["diff"])
        for doc, subject in (("nt", "latex edit"), ("ms", "markdown edit")):
            with self.subTest(doc=doc, subject=subject):
                code, body = self.diff(doc, self.commits[subject])
                self.assertEqual((code, body["reason"]), (404, "commit_not_recent"))

    def test_a_pin_on_markdown_lines_sees_only_its_own_hunk(self):
        """A pin on "Beta line, reworded." - pin line 7, git line 6 after the form feed - gets that hunk alone; the Omega
        hunk of the same commit is the rest (other_diff), and the whole-commit diff is unchanged."""
        code, made = self.call(
            "POST", "/api/pin", {"doc": "nt", "file": str(self.md), "lo": 7, "hi": 7, "note": "beta"}
        )
        self.assertEqual(code, 200, made)
        code, body = self.diff("nt", self.commits["markdown edit"], made["id"])
        self.assertEqual(code, 200, body)
        scope = body["scope"]
        self.assertEqual((scope["mode"], scope["source"], scope["hunks"], scope["other"]), ("pin", "inferred", 1, 1))
        self.assertIn("+Beta line, reworded.", scope["diff"])
        self.assertNotIn("Omega", scope["diff"])
        self.assertIn("+Omega line, reworded.", scope["other_diff"])
        self.assertIn("+Omega line, reworded.", body["diff"])

    def test_a_markdown_document_has_no_comparison_pdf(self):
        """The comparison PDF routes answer a Markdown document as they answer a document without one (404
        commit_not_recent), and nothing is built or cached for it."""
        commit = self.commits["markdown edit"]
        for method, path, body in (
            ("POST", "/api/revision-build", {"commit": commit, "doc": "nt"}),
            ("GET", "/api/revision-build?doc=nt&commit=" + commit, None),
            ("GET", "/api/revision-pdf?doc=nt&commit=" + commit, None),
        ):
            with self.subTest(method=method, path=path):
                code, answer = self.call(method, path, body)
                self.assertEqual((code, answer["reason"]), (404, "commit_not_recent"))
        self.assertFalse((self.nt.dir / "revisions").exists())

"""The changes view of a text document (docs/adr/0029-text-documents.md D1; docs/handbook/api.md §변경 보기와 비교 PDF): the
Git history of its own file alone, the source diff of those commits with a pin's own hunks, and no comparison PDF.

One folder of a real temporary repository holds a LaTeX main (main.tex), a Markdown document (plan.md), a text document
of the same stem (plan.txt) and a bibliography served as a text document too (refs.bib), each registered by its --doc
suffix. Commits touch one file each, so each history answers exactly which commits touched its own files: plan.txt's
history never names plan.md or main.tex and theirs never name plan.txt. A .bib is a manuscript file of the LaTeX
document as well - its history takes the folder's .tex, .bib, .sty, .cls and .bst files - so the bibliography's commit
is in both the LaTeX history and its own; its own names no other file.

Run: uv run pytest -q src/limn/revisions/tests/test_text_revisions.py
"""

import shutil

from limn.administration import serve_documents
from limn.platform.git import run_git

from helpers import ps
from helpers_access import AccessBase

PLAN_TXT = "Plan\n\nAlpha line.\nBeta line.\n\n" + "".join("Filler %d.\n" % i for i in range(1, 11)) + "\nOmega line.\n"
PLAN_MD = "# Plan\n\nA paragraph.\n"
REFS = "@article{a,\n  title = {A},\n}\n"


class TextHistory(AccessBase):
    """ms (main.tex), nt (plan.md), tx (plan.txt) and bib (refs.bib) in the manuscript folder, committed in order:
    everything (initial), an edit of two separate lines of plan.txt (text edit), an edit of plan.md (markdown edit), an
    edit of main.tex (latex edit) and an edit of refs.bib (bib edit)."""

    def setUp(self):
        """Serve the four documents from their --doc specs over one folder and make the five commits."""
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        self.txt, self.md, self.bib = self.src / "plan.txt", self.src / "plan.md", self.src / "refs.bib"
        self.txt.write_text(PLAN_TXT, encoding="utf-8")
        self.md.write_text(PLAN_MD, encoding="utf-8")
        self.bib.write_text(REFS, encoding="utf-8")
        docs = serve_documents.make_docs(
            ["ms=본문:main.tex", "nt=계획:plan.md", "tx=메모:plan.txt", "bib=참고문헌:refs.bib"],
            self.src,
            ps.APP.C.paths,
        )
        assert isinstance(docs, list), docs
        self.assertEqual([d.kind for d in docs], ["tex", "markdown", "text", "text"])
        self.tx = docs[2]
        ps.APP.set_docs(docs)
        self.addCleanup(ps.APP.set_docs, None)
        self.git("init", "--quiet", "-b", "main")
        self.git("config", "user.email", "alice@example.com")
        self.git("config", "user.name", "Alice")
        self.commits = {"initial": self.commit("initial", ".")}
        self.txt.write_text(
            PLAN_TXT.replace("Beta line.", "Beta line, reworded.").replace("Omega line.", "Omega line, reworded."),
            encoding="utf-8",
        )
        self.commits["text edit"] = self.commit("text edit", "plan.txt")
        self.md.write_text(PLAN_MD + "\nAnother paragraph.\n", encoding="utf-8")
        self.commits["markdown edit"] = self.commit("markdown edit", "plan.md")
        self.main.write_text(self.main.read_text(encoding="utf-8") + "% latex edit\n", encoding="utf-8")
        self.commits["latex edit"] = self.commit("latex edit", "main.tex")
        self.bib.write_text(REFS.replace("{A}", "{A, revised}"), encoding="utf-8")
        self.commits["bib edit"] = self.commit("bib edit", "refs.bib")

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
        """plan.txt's history is its own commits; plan.md's and main.tex's never hold it, though plan.md shares its folder
        and stem. The bibliography's own history is its file's; the LaTeX history takes it as a manuscript file."""
        self.assertEqual(self.subjects("tx"), ["text edit", "initial"])
        self.assertEqual(self.subjects("nt"), ["markdown edit", "initial"])
        self.assertEqual(self.subjects("bib"), ["bib edit", "initial"])
        self.assertEqual(self.subjects("ms"), ["bib edit", "latex edit", "initial"])

    def test_the_source_diff_of_a_text_commit_and_no_other_documents_commit(self):
        """The text commit's diff names plan.txt and its new lines and no other file; the Markdown and LaTeX documents'
        commits are not read through the text document, nor the text commit through them (404 commit_not_recent)."""
        code, body = self.diff("tx", self.commits["text edit"])
        self.assertEqual(code, 200, body)
        self.assertIn("+++ b/plan.txt", body["diff"])
        self.assertIn("+Beta line, reworded.", body["diff"])
        for other in ("plan.md", "main.tex", "refs.bib"):
            self.assertNotIn(other, body["diff"])
        for doc, subject in (("tx", "markdown edit"), ("tx", "latex edit"), ("nt", "text edit"), ("ms", "text edit")):
            with self.subTest(doc=doc, subject=subject):
                code, body = self.diff(doc, self.commits[subject])
                self.assertEqual((code, body["reason"]), (404, "commit_not_recent"))

    def test_a_pin_on_text_lines_sees_only_its_own_hunk(self):
        """A pin on "Beta line, reworded." (line 4) gets that hunk alone; the Omega hunk of the same commit is the rest."""
        code, made = self.call(
            "POST", "/api/pin", {"doc": "tx", "file": str(self.txt), "lo": 4, "hi": 4, "note": "beta"}
        )
        self.assertEqual(code, 200, made)
        code, body = self.diff("tx", self.commits["text edit"], made["id"])
        self.assertEqual(code, 200, body)
        scope = body["scope"]
        self.assertEqual((scope["mode"], scope["hunks"], scope["other"]), ("pin", 1, 1))
        self.assertIn("+Beta line, reworded.", scope["diff"])
        self.assertNotIn("Omega", scope["diff"])
        self.assertIn("+Omega line, reworded.", scope["other_diff"])

    def test_a_text_document_has_no_comparison_pdf(self):
        """The comparison PDF routes answer the text document as a document without one (404 commit_not_recent), and
        nothing is built or cached for it."""
        commit = self.commits["text edit"]
        for method, path, body in (
            ("POST", "/api/revision-build", {"commit": commit, "doc": "tx"}),
            ("GET", "/api/revision-build?doc=tx&commit=" + commit, None),
            ("GET", "/api/revision-pdf?doc=tx&commit=" + commit, None),
        ):
            with self.subTest(method=method, path=path):
                code, answer = self.call(method, path, body)
                self.assertEqual((code, answer.get("reason")), (404, "commit_not_recent"))
        self.assertFalse((self.tx.dir / "revisions").exists())

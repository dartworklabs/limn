"""A document's history is the history of the path it was registered with, never of where its folder leads now.

The documents are registered as `limn serve --doc` registers them (serve_documents.make_docs: a plain path's folder is
the document's src). After startup a folder on the way to a document's file is replaced by a symlink - to a dot-named
folder of the same repository whose files are committed, or to another repository's top level - as a local account or
a pushed commit under --git-pull can do. A viewer then asks every revision route of each document: no answer may carry
the linked folder's commits or text, and the document keeps its own history.

Run: uv run pytest -q src/limn/revisions/tests/test_revision_path_identity.py
"""

import os
import shutil

from limn.administration.serve_documents import make_docs
from limn.platform.git import run_git
from limn.revisions import core as revisions
from limn.runtime.documents import Doc

from helpers import ps
from helpers_access import ALICE, CAROL, AccessBase, member_add

SECRET = "SECRET-TEXT"


class RegisteredPath(AccessBase):
    """A manuscript repository with a Markdown document (notes/plan.md), a text document (notes/plan.txt) and a LaTeX
    document (paper/main.tex), each with a commit of its own, and a dot-named folder .private whose plan.md, plan.txt
    and main.tex are committed (subjects and text carry SECRET)."""

    def setUp(self):
        """Commit the documents, then .private, and register the documents as --doc does; Carol is a viewer."""
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        for folder in ("notes", "paper", ".private"):
            (self.src / folder).mkdir()
        self.write("notes", "# Plan\n\npublic line.\n", "public text\n", "")
        self.write("paper", "", "", "\\documentclass{article}\\begin{document}public\\end{document}\n")
        self.git("init", "--quiet", "-b", "main")
        self.git("config", "user.email", "alice@example.com")
        self.git("config", "user.name", "Alice")
        self.git("add", "notes", "paper", "main.tex")
        self.git("commit", "--quiet", "-m", "public documents")
        self.write(".private", "# %s\n" % SECRET, "%s\n" % SECRET, "%s\n" % SECRET)
        self.git("add", "-f", ".private")
        self.git("commit", "--quiet", "-m", "private %s" % SECRET)
        docs = make_docs(
            ["nt=계획:notes/plan.md", "tx=텍스트:notes/plan.txt", "pp=논문:paper/main.tex"], self.src, ps.APP.C.paths
        )
        self.assertIsInstance(docs, list, docs)
        self.docs = {d.key: d for d in docs}
        ps.APP.set_docs(docs)
        self.addCleanup(ps.APP.set_docs, None)
        member_add(ps.APP.C.state, ALICE["Tailscale-User-Login"], "owner")
        member_add(ps.APP.C.state, CAROL["Tailscale-User-Login"], "viewer")
        self.own = {key: self.subjects(key) for key in self.docs}

    def write(self, folder, md, txt, tex):
        """plan.md, plan.txt and main.tex in folder (an empty text leaves that file out)."""
        for name, text in (("plan.md", md), ("plan.txt", txt), ("main.tex", tex)):
            if text:
                (self.src / folder / name).write_text(text, encoding="utf-8")

    def git(self, *args, cwd=None):
        """Run a fixture git command (in the manuscript folder unless cwd); its stdout, stripped."""
        done = run_git(list(args), cwd or self.src, 10)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def subjects(self, key):
        """The subjects GET /api/revisions lists for document key, as the viewer Carol is answered."""
        code, body = self.call("GET", "/api/revisions?doc=%s" % key, headers=CAROL)
        self.assertEqual(code, 200, body)
        return [row["subject"] for row in body["revisions"]]

    def link(self, folder, target):
        """Replace folder (below the manuscript) with a symlink to target."""
        shutil.rmtree(self.src / folder)
        os.symlink(target, self.src / folder)

    def assert_nothing_linked(self, marker=SECRET):
        """Every revision route of every document, as the viewer Carol: each document lists exactly its own commits,
        and no history row, source diff (whole, a range, a pin's) or comparison status carries marker."""
        for key in self.docs:
            with self.subTest(doc=key):
                code, body = self.call("GET", "/api/revisions?doc=%s" % key, headers=CAROL)
                self.assertEqual(code, 200, body)
                self.assertEqual([row["subject"] for row in body["revisions"]], self.own[key])
                self.assertNotIn(marker, str(body))
                ids = [row["id"] for row in body["revisions"]]
                for commit in ids:
                    for query in ("", "&base=%s" % ids[-1]):
                        code, out = self.call(
                            "GET", "/api/revision-diff?doc=%s&commit=%s%s" % (key, commit, query), headers=CAROL
                        )
                        self.assertEqual(code, 200, out)
                        self.assertNotIn(marker, str(out))
                    code, out = self.call("GET", "/api/revision-build?doc=%s&commit=%s" % (key, commit), headers=CAROL)
                    self.assertNotIn(marker, str(out))

    def test_a_folder_linked_to_a_dot_named_folder_keeps_the_documents_own_history(self):
        """notes and paper are replaced by links to .private, whose files are committed: each document still lists
        only its own commit, and nothing a viewer is answered quotes .private."""
        self.assertEqual(self.own, {"nt": ["public documents"], "tx": ["public documents"], "pp": ["public documents"]})
        self.link("notes", ".private")
        self.link("paper", ".private")
        self.assert_nothing_linked()

    def test_a_link_committed_by_a_pusher_keeps_the_documents_own_history(self):
        """The same links committed (as --git-pull would check them out): the documents' histories are their own files'
        commits, the deleting commit included, and still nothing of .private."""
        self.link("notes", ".private")
        self.link("paper", ".private")
        self.git("add", "--all", "notes", "paper")
        self.git("commit", "--quiet", "-m", "links")
        self.own = {key: ["links", "public documents"] for key in self.docs}
        self.assert_nothing_linked()

    def test_a_folder_linked_to_another_repository_reads_nothing_of_it(self):
        """notes is replaced by a link to another repository's top level holding a committed plan.md: neither its
        commits nor its text reach the viewer."""
        other = self.src.parent / "other"
        other.mkdir()
        (other / "plan.md").write_text("OTHER-REPOSITORY\n", encoding="utf-8")
        self.git("init", "--quiet", "-b", "main", cwd=other)
        self.git("-c", "user.email=a@example.com", "-c", "user.name=A", "add", ".", cwd=other)
        self.git("-c", "user.email=a@example.com", "-c", "user.name=A", "commit", "-qm", "OTHER-REPOSITORY", cwd=other)
        self.link("notes", str(other))
        self.assert_nothing_linked("OTHER-REPOSITORY")

    def test_a_pin_on_the_linked_document_is_scoped_in_its_own_history(self):
        """A pin made on notes/plan.md before the link: its scoped diff, asked after the link, is its own commit's."""
        code, d = self.call(
            "POST", "/api/pin", {"doc": "nt", "file": str(self.docs["nt"].main), "lo": 3, "hi": 3, "note": "n"}
        )
        self.assertEqual(code, 200, d)
        self.link("notes", ".private")
        commit = self.git("rev-parse", "HEAD~1")
        code, body = self.call("GET", "/api/revision-diff?doc=nt&commit=%s&pin=%s" % (commit, d["id"]), headers=CAROL)
        self.assertEqual(code, 200, body)
        self.assertNotIn(SECRET, str(body))
        self.assertIn("+public line.", body["diff"])

    def test_the_comparison_build_compares_the_registered_folder(self):
        """paper replaced by a link to .private: the LaTeX document's comparison spec still builds paper/main.tex."""
        self.link("paper", ".private")
        self.git("add", "--all", "paper")
        self.git("commit", "--quiet", "-m", "links")
        head = self.git("rev-parse", "HEAD")
        spec = revisions.revision_spec(self.docs["pp"], head, None, ps.APP.revision_requests.context())
        self.assertIsInstance(spec, revisions.RevisionSpec, spec)
        self.assertEqual((spec.source, spec.main.as_posix()), ("paper", "main.tex"))

    def test_a_document_registered_through_a_linked_folder_keeps_its_history(self):
        """A document made through a link to the manuscript (as macOS's /var is one to /private/var) is registered at
        the real path, so its history is the file's."""
        linked = self.src.parent / "linked"
        linked.symlink_to(self.src, target_is_directory=True)
        doc = Doc("ln", "링크", "markdown", linked / "notes", linked / "notes" / "plan.md", paths=ps.APP.C.paths)
        self.assertEqual(doc.registered_main, self.src.resolve() / "notes" / "plan.md")
        files = (doc.main,)
        found = revisions.revision_scope(doc, files)
        self.assertIsNotNone(found)
        self.assertEqual(found[1], [":(literal)notes/plan.md"])


class DotNamedFolders(AccessBase):
    """A LaTeX document at the manuscript's top with committed .tex and .bib files under dot-named parts (.private/,
    a/.old/, .draft.tex) and no symlink anywhere."""

    def setUp(self):
        """Commit main.tex, then the dot-named files (their subject and text carry SECRET); Carol is a viewer."""
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        for rel in (".private/notes.tex", "a/.old/refs.bib", ".draft.tex", "sub/part.tex"):
            (self.src / rel).parent.mkdir(parents=True, exist_ok=True)
        for args in (("init", "--quiet", "-b", "main"), ("config", "user.email", "a@example.com")):
            self.assertEqual(run_git(list(args), self.src, 10).returncode, 0)
        self.assertEqual(run_git(["config", "user.name", "A"], self.src, 10).returncode, 0)
        (self.src / "sub" / "part.tex").write_text("public part\n", encoding="utf-8")
        self.commit("public", "main.tex", "sub/part.tex")
        for rel in (".private/notes.tex", "a/.old/refs.bib", ".draft.tex"):
            (self.src / rel).write_text("%s %s\n" % (SECRET, rel), encoding="utf-8")
        self.commit("private %s" % SECRET, "-f", ".private", "a/.old", ".draft.tex")
        member_add(ps.APP.C.state, CAROL["Tailscale-User-Login"], "viewer")

    def commit(self, subject, *paths):
        """git add paths, then commit them with subject."""
        self.assertEqual(run_git(["add", *paths], self.src, 10).returncode, 0)
        self.assertEqual(run_git(["commit", "--quiet", "-m", subject], self.src, 10).returncode, 0)

    def test_files_under_a_dot_named_part_are_not_the_documents_history(self):
        """The document lists its public commit only, and no route a viewer asks quotes a dot-named file; a public
        file in a subfolder still counts."""
        code, body = self.call("GET", "/api/revisions?doc=main", headers=CAROL)
        self.assertEqual(code, 200, body)
        self.assertEqual([row["subject"] for row in body["revisions"]], ["public"])
        commit = body["revisions"][0]["id"]
        code, out = self.call("GET", "/api/revision-diff?doc=main&commit=%s" % commit, headers=CAROL)
        self.assertEqual(code, 200, out)
        self.assertIn("+public part", out["diff"])
        head = run_git(["rev-parse", "HEAD"], self.src, 10).stdout.strip()
        for query in ("commit=%s" % head, "commit=%s&base=%s" % (commit, commit)):
            code, out = self.call("GET", "/api/revision-diff?doc=main&" + query, headers=CAROL)
            self.assertNotIn(SECRET, str(out))

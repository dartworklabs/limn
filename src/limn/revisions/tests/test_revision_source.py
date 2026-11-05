"""GET /api/revision-source: a browser-drawn document's own file on the two sides of a commit or of a range, which the
viewer draws and compares (docs/superpowers/specs/2026-11-05-markdown-rendered-compare.md).

A LaTeX main and a Markdown document sit in one folder of a real temporary repository. The Markdown file has a form feed
on line 3, so a side is numbered as GET /api/source numbers the current source (str.splitlines()), not as git counts.
Each side is read only for a commit of the document's history window, under the range's rules, and nothing is written.

Run: uv run pytest -q src/limn/revisions/tests/test_revision_source.py
"""

import os
import shutil

from limn.administration.serve_documents import make_docs
from limn.documents.source import SOURCE_MAX_BYTES
from limn.platform.git import run_git
from limn.revisions.core import REVISION_SOURCE_MAX
from limn.runtime.documents import Doc

from helpers import ps
from helpers_access import CAROL, AccessBase, member_add

PLAN = "# Plan\n\nIntro.\x0cAfter a form feed.\n\nAlpha line.\nBeta line.\n"


class RevisionSource(AccessBase):
    """ms (LaTeX, main.tex) and nt (Markdown, plan.md) in one folder, committed in order: everything (initial), an edit
    of plan.md (markdown edit), an edit of main.tex (latex edit), a side line of plan.md's history (side, on a branch
    merged back), and the deletion of plan.md (deleted)."""

    def setUp(self):
        """Serve ms and nt over one folder and make the commits."""
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
        self.c = {"initial": self.commit("initial", ".")}
        self.md.write_text(PLAN.replace("Beta line.", "Beta line, reworded."), encoding="utf-8")
        self.c["markdown edit"] = self.commit("markdown edit", "plan.md")
        self.main.write_text(self.main.read_text(encoding="utf-8") + "% latex edit\n", encoding="utf-8")
        self.c["latex edit"] = self.commit("latex edit", "main.tex")

    def git(self, *args):
        """Run a fixture git command in the manuscript folder; its stdout, stripped."""
        done = run_git(list(args), self.src, 10)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def commit(self, subject, rel):
        """Commit rel (a path or '.') with subject; the new commit's full id."""
        self.git("add", "--all", rel)
        self.git("commit", "--quiet", "-m", subject)
        return self.git("rev-parse", "HEAD")

    def sides(self, commit, base=None, doc="nt"):
        """GET /api/revision-source for doc and commit (and base): (status, body)."""
        path = "/api/revision-source?doc=%s&commit=%s" % (doc, commit)
        return self.call("GET", path + ("" if base is None else "&base=" + base))

    def tree(self):
        """Every path under the state folder and the manuscript folder (git's own folder left out), with its size and
        modification time: what a read must leave as it was."""
        out = {}
        for root in (ps.APP.C.state, self.src):
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d != ".git"]
                for name in dirnames + filenames:
                    p = os.path.join(dirpath, name)
                    st = os.lstat(p)
                    out[p] = (st.st_size, st.st_mtime_ns)
        return out

    def test_the_two_sides_of_a_commit_numbered_as_the_current_source(self):
        """The commit's first parent and the commit: each side's lines are split as GET /api/source splits them (the
        form feed ends line 3), the path is the file's repository path, and base is the parent."""
        code, body = self.sides(self.c["markdown edit"])
        self.assertEqual(code, 200, body)
        self.assertEqual(
            (body["id"], body["base"], body["path"]), (self.c["markdown edit"], self.c["initial"], "plan.md")
        )
        self.assertEqual(body["old"]["lines"], PLAN.splitlines())
        self.assertEqual(body["new"]["lines"][6], "Beta line, reworded.")
        self.assertEqual(body["new"]["lines"][2:4], ["Intro.", "After a form feed."])
        self.assertNotIn("merge_base", body)

    def test_a_side_says_where_gits_lines_start_when_the_two_count_apart(self):
        """A hunk counts git's lines (LF only), a side the screen's: the form feed on line 3 makes git's line 4 the
        screen's 5, said as git_line_starts [[1, 1], [4, 5]]; a U+2028 more on line 6 adds [6, 8]. A side whose line ends
        are all LF carries no map."""
        code, body = self.sides(self.c["markdown edit"])
        self.assertEqual(code, 200, body)
        self.assertEqual((body["old"]["git_line_starts"], body["new"]["git_line_starts"]), ([[1, 1], [4, 5]],) * 2)
        self.md.write_text(PLAN.replace("Alpha line.", "Alpha\u2028line."), encoding="utf-8")
        sep = self.commit("line separator", "plan.md")
        code, body = self.sides(sep)
        self.assertEqual(body["new"]["git_line_starts"], [[1, 1], [4, 5], [6, 8]])
        self.assertEqual(body["new"]["lines"][5:7], ["Alpha", "line."])
        self.md.write_text("# Plain\n\nNo other line end.\n", encoding="utf-8")
        plain = self.commit("plain", "plan.md")
        code, body = self.sides(plain)
        self.assertNotIn("git_line_starts", body["new"])

    def test_a_root_commit_has_no_old_side_and_a_deletion_no_new_side(self):
        """The commit that added the file has no parent: base and old are null. A commit that deletes the file is in its
        history; its new side is null."""
        code, body = self.sides(self.c["initial"])
        self.assertEqual(code, 200, body)
        self.assertIsNone(body["base"])
        self.assertIsNone(body["old"])
        self.assertEqual(body["new"]["lines"], PLAN.splitlines())
        self.md.unlink()
        gone = self.commit("deleted", "plan.md")
        code, body = self.sides(gone)
        self.assertEqual(code, 200, body)
        self.assertIsNone(body["new"])
        self.assertEqual(body["old"]["lines"][6], "Beta line, reworded.")

    def test_a_range_compares_its_old_side_and_a_side_line_its_merge_base(self):
        """With base, the old side is base; a base on another line compares from the merge base and says so. An empty
        range answers the same side twice."""
        code, body = self.sides(self.c["markdown edit"], base=self.c["initial"])
        self.assertEqual(code, 200, body)
        self.assertEqual(body["base"], self.c["initial"])
        self.assertEqual(body["old"]["lines"], PLAN.splitlines())
        self.git("checkout", "--quiet", "-b", "side", self.c["initial"])
        self.md.write_text(PLAN.replace("# Plan", "# Plan, side"), encoding="utf-8")
        side = self.commit("side", "plan.md")
        self.git("checkout", "--quiet", "main")
        self.git("merge", "--quiet", "--no-edit", "-m", "merge side", "side")
        code, body = self.sides(self.c["markdown edit"], base=side)
        self.assertEqual(code, 200, body)
        self.assertEqual((body["base"], body["merge_base"]), (self.c["initial"], self.c["initial"]))
        code, body = self.sides(self.c["markdown edit"], base=self.c["markdown edit"])
        self.assertEqual(code, 200, body)
        self.assertEqual(body["old"], body["new"])

    def test_only_commits_of_this_documents_window_are_read(self):
        """The LaTeX document's commit is not in the Markdown document's window; an unknown SHA-1 neither; a malformed
        commit or base is 400 bad_commit; a base after the head is the range's refusal."""
        for commit in (self.c["latex edit"], "f" * 40):
            with self.subTest(commit=commit):
                code, body = self.sides(commit)
                self.assertEqual((code, body.get("reason")), (404, "commit_not_recent"))
        for query in ("commit=zz", "commit=%s&base=HEAD" % self.c["markdown edit"]):
            with self.subTest(query=query):
                code, body = self.call("GET", "/api/revision-source?doc=nt&" + query)
                self.assertEqual((code, body.get("reason")), (400, "bad_commit"))
        code, body = self.sides(self.c["initial"], base=self.c["markdown edit"])
        self.assertEqual((code, body.get("reason")), (422, "base_after_head"))

    def test_a_document_the_browser_does_not_draw_has_no_sides(self):
        """A LaTeX document answers as a document without them (404 commit_not_recent), for its own commit too."""
        code, body = self.sides(self.c["latex edit"], doc="ms")
        self.assertEqual((code, body.get("reason")), (404, "commit_not_recent"))

    def test_a_side_too_large_or_not_utf8_or_a_link_carries_no_lines(self):
        """A side over the limit says its size and the limit and sends no lines; bytes that are not UTF-8 and a symlink
        at the file's path are named; the other side still comes."""
        self.assertEqual(REVISION_SOURCE_MAX, SOURCE_MAX_BYTES)
        self.md.write_bytes(b"a" * (REVISION_SOURCE_MAX + 1))
        big = self.commit("big", "plan.md")
        code, body = self.sides(big)
        self.assertEqual(code, 200, body)
        self.assertEqual(
            body["new"], {"reason": "source_too_large", "bytes": REVISION_SOURCE_MAX + 1, "limit": REVISION_SOURCE_MAX}
        )
        self.assertIn("lines", body["old"])
        self.md.write_bytes(b"\xff\xfe not utf-8\n")
        bad = self.commit("latin", "plan.md")
        code, body = self.sides(bad)
        self.assertEqual(body["new"], {"reason": "source_not_utf8"})
        self.md.unlink()
        os.symlink("main.tex", self.md)
        link = self.commit("link", "plan.md")
        code, body = self.sides(link)
        self.assertEqual(code, 200, body)
        self.assertEqual(body["new"], {"reason": "not_a_file"})

    def test_a_read_writes_nothing(self):
        """Reading both sides of a commit and of a range leaves the state and manuscript folders as they were (ADR-0027)."""
        before = self.tree()
        for base in (None, self.c["initial"]):
            code, _ = self.sides(self.c["markdown edit"], base=base)
            self.assertEqual(code, 200)
        self.assertEqual(self.tree(), before)


SECRET = "SECRET-TEXT"


class RegisteredSides(AccessBase):
    """A Markdown document registered as --doc registers it (nt=계획:notes/plan.md, its folder notes the document's src),
    a committed dot-named folder .private and a plain folder other, each holding a plan.md of its own (SECRET); Carol is a
    viewer. After startup a folder or the file on the way is replaced by a symlink: each side GET /api/revision-source
    answers is still read at the registered path notes/plan.md, never through the link."""

    def setUp(self):
        """Commit notes/plan.md, then .private/plan.md and other/plan.md; register the document."""
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        for folder in ("notes", ".private", "other"):
            (self.src / folder).mkdir()
        (self.src / "notes" / "plan.md").write_text(PLAN, encoding="utf-8")
        self.git("init", "--quiet", "-b", "main")
        self.git("config", "user.email", "alice@example.com")
        self.git("config", "user.name", "Alice")
        self.first = self.commit("public plan", "notes")
        for folder in (".private", "other"):
            (self.src / folder / "plan.md").write_text("# %s %s\n" % (SECRET, folder), encoding="utf-8")
        self.git("add", "-f", ".private", "other")
        self.git("commit", "--quiet", "-m", "private %s" % SECRET)
        self.register()
        member_add(ps.APP.C.state, CAROL["Tailscale-User-Login"], "viewer")

    def register(self):
        """Register nt as limn serve --doc nt=계획:notes/plan.md does."""
        docs = make_docs(["nt=계획:notes/plan.md"], self.src, ps.APP.C.paths)
        self.assertIsInstance(docs, list, docs)
        ps.APP.set_docs(docs)
        self.addCleanup(ps.APP.set_docs, None)

    git = RevisionSource.git
    commit = RevisionSource.commit

    def window(self):
        """The ids GET /api/revisions lists for nt, as Carol is answered."""
        code, body = self.call("GET", "/api/revisions?doc=nt", headers=CAROL)
        self.assertEqual(code, 200, body)
        return [row["id"] for row in body["revisions"]]

    def sides(self, commit, base=None):
        """GET /api/revision-source for nt as Carol: (status, body)."""
        q = "/api/revision-source?doc=nt&commit=%s" % commit + ("" if base is None else "&base=" + base)
        return self.call("GET", q, headers=CAROL)

    def assert_own_sides(self, ids):
        """The window is exactly ids, and every side of each commit (alone and as a range from the oldest) is read at
        notes/plan.md and quotes nothing of .private or other."""
        self.assertEqual(self.window(), ids)
        for commit in ids:
            for base in (None, ids[-1]):
                with self.subTest(commit=commit, base=base):
                    code, body = self.sides(commit, base)
                    self.assertEqual(code, 200, body)
                    self.assertEqual(body["path"], "notes/plan.md")
                    self.assertNotIn(SECRET, str(body))

    def link_folder(self, target):
        """Replace notes with a symlink to target (a folder name beside it)."""
        shutil.rmtree(self.src / "notes")
        os.symlink(target, self.src / "notes")

    def test_a_folder_linked_to_a_dot_named_folder_reads_the_registered_path(self):
        """notes -> .private (uncommitted, then committed as --git-pull would check it out): the window stays the
        document's own commits and no side quotes .private; the committed link's new side has no file."""
        self.link_folder(".private")
        self.assert_own_sides([self.first])
        self.git("add", "--all", "notes")
        link = self.commit("notes becomes a link", "notes")
        self.assert_own_sides([link, self.first])
        code, body = self.sides(link)
        self.assertIsNone(body["new"])
        self.assertEqual(body["old"]["lines"], PLAN.splitlines())

    def test_a_folder_linked_to_another_folder_reads_the_registered_path(self):
        """notes -> other (a plain folder whose plan.md is committed): the same - never other/plan.md."""
        self.link_folder("other")
        self.assert_own_sides([self.first])

    def test_a_file_replaced_by_a_link_is_not_a_file_on_that_side(self):
        """notes/plan.md replaced by a link to ../.private/plan.md and committed: that side is not_a_file, the old side
        the registered file's own lines."""
        md = self.src / "notes" / "plan.md"
        md.unlink()
        os.symlink("../.private/plan.md", md)
        link = self.commit("plan becomes a link", "notes")
        self.assert_own_sides([link, self.first])
        code, body = self.sides(link)
        self.assertEqual(body["new"], {"reason": "not_a_file"})
        self.assertEqual(body["old"]["lines"], PLAN.splitlines())

    def test_a_file_renamed_in_its_history_has_no_old_side_before_the_rename(self):
        """notes/plan.md removed, then draft.md renamed to it: the rename commit's old side has no file at the registered
        path (the history does not follow renames), and the draft's own commit is not in the window, so never read."""
        (self.src / "notes" / "plan.md").unlink()
        removed = self.commit("removed", "notes")
        (self.src / "draft.md").write_text("# Draft\n", encoding="utf-8")
        draft = self.commit("draft", "draft.md")
        self.git("mv", "draft.md", "notes/plan.md")
        self.git("commit", "--quiet", "-m", "rename")
        renamed = self.git("rev-parse", "HEAD")
        self.assertEqual(self.window(), [renamed, removed, self.first])
        code, body = self.sides(renamed)
        self.assertEqual(code, 200, body)
        self.assertIsNone(body["old"])
        self.assertEqual(body["new"]["lines"], ["# Draft"])
        code, body = self.sides(draft)
        self.assertEqual((code, body.get("reason")), (404, "commit_not_recent"))

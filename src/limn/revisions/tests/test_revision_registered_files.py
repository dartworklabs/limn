"""The changes view and the comparison build show a document's own registered files only (SECURITY.md).

Each class below is one way the change view or a comparison build reached a file that is not one of the document's
own - under a dot-named folder, through a folder replaced by a symlink after startup, or by a folder name Git reads as
a pattern. A viewer asks the routes, as in test_revision_path_identity.py.

Run: uv run pytest -q src/limn/revisions/tests/test_revision_registered_files.py
"""

import shutil
import subprocess

from limn.administration.serve_documents import make_docs
from limn.revisions import core

from helpers import ps
from helpers_access import CAROL, AccessBase, member_add
from helpers_figure import BUILD1, b2_map, figure_doc, write_build

SECRET = "SECRET-TEXT"


class Repository(AccessBase):
    """A Git repository at the manuscript folder (no commit yet); Carol is a viewer."""

    def setUp(self):
        """Initialise the repository and make Carol a viewer."""
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "alice@example.com")
        self.git("config", "user.name", "Alice")
        member_add(ps.APP.C.state, CAROL["Tailscale-User-Login"], "viewer")

    def git(self, *args):
        """Run a fixture git command in the manuscript folder; its stdout, stripped."""
        done = subprocess.run(["git", *args], cwd=self.src, capture_output=True, text=True, check=True)
        return done.stdout.strip()

    def commit(self, subject):
        """Commit everything (dot-named folders too) with subject; returns the new commit."""
        self.git("add", "-A")
        self.git("commit", "-qm", subject)
        return self.git("rev-parse", "HEAD")

    def serve(self, docs):
        """Serve docs for this test."""
        ps.APP.set_docs(docs)
        self.addCleanup(ps.APP.set_docs, None)

    def subjects(self, key):
        """The subjects GET /api/revisions lists for document key, as the viewer Carol is answered."""
        code, body = self.call("GET", "/api/revisions?doc=%s" % key, headers=CAROL)
        self.assertEqual(code, 200, body)
        return [row["subject"] for row in body["revisions"]]


class FigureDotNames(Repository):
    """A figure document (figs/) whose map names a file under a dot-named folder, or names more files than
    HISTORY_PATHS_MAX, so that its history is named by its folder."""

    def test_a_mapped_file_under_a_dot_named_folder_is_not_in_the_diff(self):
        """The map's root element is drawn by .Private/hidden.py (a capital: the rule is the leading dot, not a name):
        the commit adding it is the document's (its map is), but the diff a viewer is answered holds not its text."""
        fig = figure_doc(self.src, ps.APP.C.paths)
        (fig.src / ".Private").mkdir()
        (fig.src / ".Private" / "hidden.py").write_text(SECRET + "\n", encoding="utf-8")
        fmap = b2_map()
        fmap["pages"][0]["elements"][0]["src"]["file"] = ".Private/hidden.py"
        write_build(fig, BUILD1, fmap)
        self.serve([fig])
        head = self.commit("figure and its hidden source")
        code, body = self.call("GET", "/api/revision-diff?doc=fig&commit=%s" % head, headers=CAROL)
        self.assertEqual(code, 200, body)
        self.assertIn("B2_calendar.py", body["diff"])
        self.assertNotIn(SECRET, str(body))

    def test_the_folder_named_for_a_large_map_leaves_dot_named_folders_out(self):
        """A map naming 202 files is named by its folder: a later commit touching only figs/.private/hidden.py is not
        in the history, and a viewer asking its diff is refused."""
        fig = figure_doc(self.src, ps.APP.C.paths)
        fmap = b2_map()
        root = fmap["pages"][0]["elements"][0]
        fmap["pages"][0]["elements"] = [root] + [
            {"id": "B2/n%d" % i, "parent": "B2", "frac": [0.1, 0.1, 0.1, 0.1], "src": {"file": "src/part%d.py" % i}}
            for i in range(core.HISTORY_PATHS_MAX + 1)
        ]
        for el in fmap["pages"][0]["elements"][1:]:
            el["src"].update(lo=1, hi=1)
        write_build(fig, BUILD1, fmap)
        self.serve([fig])
        self.commit("figure")
        (fig.src / ".private").mkdir()
        (fig.src / ".private" / "hidden.py").write_text(SECRET + "\n", encoding="utf-8")
        head = self.commit("private %s" % SECRET)
        self.assertEqual(self.subjects("fig"), ["figure"])
        code, body = self.call("GET", "/api/revision-diff?doc=fig&commit=%s" % head, headers=CAROL)
        self.assertEqual(code, 404, body)

    def test_registered_file_refuses_a_dot_named_part(self):
        """registered_file names no file with a dot-named part below the document's folder (any case), and keeps one
        whose name merely holds a dot."""
        fig = figure_doc(self.src, ps.APP.C.paths)
        for rel in (".Private/hidden.py", "src/.old/x.py", "src/.x.py"):
            with self.subTest(rel=rel):
                self.assertIsNone(core.registered_file(fig, fig.src / rel))
        self.assertEqual(core.registered_file(fig, fig.src / "src" / "a.b.py"), fig.registered_src / "src" / "a.b.py")


class FigurePdfThroughLink(Repository):
    """A figure document whose out/ folder (holding the map and the PDF it names) is replaced by a symlink to another
    folder of the same document after startup."""

    def test_the_pdf_history_stays_at_the_registered_path(self):
        """out -> other: a commit touching only other/figures.pdf is neither in the history nor read as a diff."""
        fig = figure_doc(self.src, ps.APP.C.paths)
        write_build(fig, BUILD1, b2_map())
        self.serve([fig])
        self.commit("figure")
        (fig.src / "other").mkdir()
        (fig.src / "other" / "figures.pdf").write_text(SECRET + "\n", encoding="utf-8")
        head = self.commit("other PDF %s" % SECRET)
        shutil.rmtree(fig.src / "out")
        (fig.src / "out").symlink_to("other", target_is_directory=True)
        self.assertEqual(self.subjects("fig"), ["figure"])
        code, body = self.call("GET", "/api/revision-diff?doc=fig&commit=%s" % head, headers=CAROL)
        self.assertEqual(code, 404, body)


class GlobCharactersInTheFolder(Repository):
    """Two LaTeX folders, paper[1] (served) and paper1 (not), whose names a Git glob would confuse."""

    def test_the_folder_name_is_matched_literally(self):
        """paper[1]/main.tex's history and diff are its own: paper1/main.tex, committed with it and after it, is in
        neither."""
        for folder, text in (("paper[1]", "own\n"), ("paper1", SECRET + "\n")):
            (self.src / folder).mkdir()
            (self.src / folder / "main.tex").write_text(text, encoding="utf-8")
        docs = make_docs(["pp=논문:paper[1]/main.tex"], self.src, ps.APP.C.paths)
        self.assertIsInstance(docs, list, docs)
        self.serve(docs)
        both = self.commit("two papers")
        (self.src / "paper1" / "main.tex").write_text(SECRET + " again\n", encoding="utf-8")
        self.commit("other paper %s" % SECRET)
        self.assertEqual(self.subjects("pp"), ["two papers"])
        code, body = self.call("GET", "/api/revision-diff?doc=pp&commit=%s" % both, headers=CAROL)
        self.assertEqual(code, 200, body)
        self.assertIn("+own", body["diff"])
        self.assertNotIn(SECRET, str(body))

    def test_glob_literal_escapes_every_wildcard(self):
        """glob_literal escapes *, ?, [, ] and the backslash; dot_excludes escape the folder too."""
        self.assertEqual(core.glob_literal("a*b?c[1]\\d"), "a\\*b\\?c\\[1\\]\\\\d")
        self.assertEqual(core.glob_literal("plain/dir"), "plain/dir")
        self.assertEqual(
            core.dot_excludes("paper[1]/"),
            [":(exclude,glob)paper\\[1\\]/**/.*", ":(exclude,glob)paper\\[1\\]/**/.*/**"],
        )

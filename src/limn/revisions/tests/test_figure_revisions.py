"""The changes view of a figure document (docs/handbook/api.md §변경 보기와 비교 PDF): the Git history of the files its
current build's map names, the source diff of those commits, no comparison PDF, and the two builds the viewer's overlay
lays one over the other.

The figure folder of helpers_figure.figure_doc() is committed into a real temporary repository next to the
manuscript, one commit per kind of change, so a history answers exactly which commits touched the map's files. The
pure rules - which page folder is the previous build, which files a map names, how files become a pathspec - are tested
on values at the end.

Run: uv run pytest -q src/limn/revisions/tests/test_figure_revisions.py
"""

import shutil
from pathlib import Path

from hypothesis import given, strategies as st

from limn.administration import serve_documents
from limn.builds import artifacts
from limn.builds.figure_map import FigureMap, map_source_files, parse_map
from limn.platform.git import run_git
from limn.revisions.core import HISTORY_PATHS_MAX, files_pathspec

from helpers import map_bytes, ps
from helpers_access import AccessBase
from helpers_figure import BUILD1, BUILD2, PAGE_PT, b2_map, figure_doc, write_build

BUILD0 = "pages-20260926090000"


class FigureHistory(AccessBase):
    """A manuscript and its figure folder in one repository: the figure document's changes view through the handler."""

    def setUp(self):
        """Serve the body (ms) and figure_doc()'s figure (fig) with build BUILD1 on screen, and commit, in order:
        everything (initial), the drawing script (script), the shared component (component), a re-render of the PDF
        and the map (render), a file in the figure folder no map names (notes) and the body (manuscript)."""
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        docs = serve_documents.make_docs(["ms=본문:main.tex"], self.src, ps.APP.C.paths)
        assert isinstance(docs, list), docs
        self.fig = figure_doc(self.src, ps.APP.C.paths)
        ps.APP.set_docs([docs[0], self.fig])
        self.addCleanup(ps.APP.set_docs, None)
        write_build(self.fig, BUILD1, b2_map())
        figs = self.src / "figs"
        (figs / "notes.txt").write_text("notes\n", encoding="utf-8")
        self.git("init", "--quiet", "-b", "main")
        self.git("config", "user.email", "alice@example.com")
        self.git("config", "user.name", "Alice")
        self.commits = {"initial": self.commit("initial", ".")}
        for subject, rel, text in (
            ("script", "figs/src/B2_calendar.py", "step = redraw()\n"),
            ("component", "figs/lib/components.py", "part = reshape()\n"),
            ("render", "figs/out/figures.pdf", "%PDF-1.4\n% re-rendered\n%%EOF\n"),
            ("notes", "figs/notes.txt", "more notes\n"),
            ("manuscript", "main.tex", "\\documentclass{article}\n\\begin{document}x\\end{document}\n"),
        ):
            path = self.src / rel
            path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")
            self.commits[subject] = self.commit(subject, rel)

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

    def test_a_figure_documents_history_is_the_commits_that_touched_the_files_its_map_names(self):
        """The script and the shared component the map names, its PDF and the map are the history; a file of the same
        folder no map names and the manuscript are not."""
        self.assertEqual(self.subjects("fig"), ["render", "component", "script", "initial"])

    def test_a_latex_documents_changes_answer_keeps_its_keys_and_history(self):
        """The body's answer is unchanged: only available and revisions, its own .tex commits."""
        code, body = self.call("GET", "/api/revisions?doc=ms")
        self.assertEqual((code, sorted(body)), (200, ["available", "revisions"]))
        self.assertEqual(self.subjects("ms"), ["manuscript", "initial"])

    def test_the_source_diff_of_a_figure_commit_shows_the_script_change(self):
        """GET /api/revision-diff answers the script commit's diff, which names the script and its new line."""
        code, body = self.call("GET", "/api/revision-diff?doc=fig&commit=" + self.commits["script"])
        self.assertEqual(code, 200, body)
        self.assertIn("figs/src/B2_calendar.py", body["diff"])
        self.assertIn("+step = redraw()", body["diff"])

    def test_a_commit_outside_the_figure_history_is_not_read(self):
        """A commit that touched only files no map names is not in the figure's list: 404 commit_not_recent."""
        for subject in ("notes", "manuscript"):
            with self.subTest(subject=subject):
                code, body = self.call("GET", "/api/revision-diff?doc=fig&commit=" + self.commits[subject])
                self.assertEqual((code, body["reason"]), (404, "commit_not_recent"))

    def test_a_figure_document_has_no_comparison_pdf(self):
        """The comparison PDF routes answer a figure document as they answer a document without one (404
        commit_not_recent), and nothing is built or cached."""
        commit = self.commits["script"]
        for method, path, body in (
            ("POST", "/api/revision-build", {"commit": commit, "doc": "fig"}),
            ("GET", "/api/revision-build?doc=fig&commit=" + commit, None),
            ("GET", "/api/revision-pdf?doc=fig&commit=" + commit, None),
        ):
            with self.subTest(method=method, path=path):
                code, answer = self.call(method, path, body)
                self.assertEqual((code, answer["reason"]), (404, "commit_not_recent"))
        self.assertFalse((self.fig.dir / "revisions").exists())

    def test_the_answer_names_the_build_on_screen_and_the_one_before_it(self):
        """After a re-render the overlay is the new build (two pages) over the previous one (one page), with the page
        images' sizes in points."""
        write_build(self.fig, BUILD2, b2_map(), pages=2)
        code, body = self.call("GET", "/api/revisions?doc=fig")
        self.assertEqual(code, 200, body)
        page = {"pt_w": PAGE_PT[0], "pt_h": PAGE_PT[1]}
        self.assertEqual(
            body["overlay"],
            {
                "build": BUILD2,
                "pages": [{"name": "page-1.png", **page}, {"name": "page-2.png", **page}],
                "prev_build": BUILD1,
                "prev_pages": [{"name": "page-1.png", **page}],
            },
        )

    def test_a_first_build_has_no_previous_build(self):
        """With one build the overlay names it and no previous build."""
        code, body = self.call("GET", "/api/revisions?doc=fig")
        self.assertEqual((code, body["overlay"]["build"], body["overlay"]["prev_build"]), (200, BUILD1, None))
        self.assertEqual(body["overlay"]["prev_pages"], [])

    def test_a_page_folder_newer_than_the_one_on_screen_is_not_the_previous_build(self):
        """An import still in flight has published its folder but not moved pages.cur: the previous build is the
        older kept folder, never the newer one."""
        write_build(self.fig, BUILD0, b2_map())
        write_build(self.fig, BUILD2, b2_map())
        (self.fig.dir / "pages.cur").write_text(BUILD1, encoding="utf-8")
        code, body = self.call("GET", "/api/revisions?doc=fig")
        self.assertEqual((code, body["overlay"]["build"], body["overlay"]["prev_build"]), (200, BUILD1, BUILD0))

    def test_the_history_follows_the_files_of_the_current_builds_map(self):
        """A build whose map names a script the old one did not widens the history to that script's commits."""
        (self.src / "figs" / "src" / "B3_flow.py").write_text("flow = draw()\n", encoding="utf-8")
        self.commits["flow"] = self.commit("flow", "figs/src/B3_flow.py")
        self.assertNotIn("flow", self.subjects("fig"))
        fmap = b2_map()
        fmap["pages"][0]["elements"][1]["src"] = {"file": "src/B3_flow.py", "lo": 1, "hi": 1}
        write_build(self.fig, BUILD2, fmap)
        self.assertEqual(self.subjects("fig")[0], "flow")


class FigureOutsideGit(AccessBase):
    """A figure folder that is not in a Git repository: no history, and the overlay all the same."""

    def test_the_overlay_needs_no_history(self):
        """available is false and the revisions are empty, and the overlay names the build on screen."""
        fig = figure_doc(self.src, ps.APP.C.paths)
        ps.APP.set_docs([fig])
        self.addCleanup(ps.APP.set_docs, None)
        write_build(fig, BUILD1, b2_map())
        code, body = self.call("GET", "/api/revisions?doc=fig")
        self.assertEqual((code, body["available"], body["revisions"]), (200, False, []))
        self.assertEqual((body["overlay"]["build"], body["overlay"]["prev_build"]), (BUILD1, None))


class PreviousBuild(AccessBase):
    """artifacts.previous_build: the newest page folder name older than the one on screen (pure)."""

    def test_the_newest_older_name_wins_and_a_suffix_counts_as_later(self):
        """Names compare by their time stamp, then by the -<n> suffix as a number (-10 after -9), never as text."""
        names = ["pages-20260926100000", "pages-20260926100000-9", "pages-20260926100000-10", "pages-20260926110000"]
        self.assertEqual(artifacts.previous_build(names, "pages-20260926110000"), "pages-20260926100000-10")
        self.assertEqual(artifacts.previous_build(names, "pages-20260926100000-10"), "pages-20260926100000-9")
        self.assertIsNone(artifacts.previous_build(names, "pages-20260926100000"))

    def test_names_that_are_not_page_folders_are_ignored(self):
        """A half-made folder, the state folder's other entries and a malformed name are never a build."""
        names = [".pages-20260926100000.part", "build", "pages-2026", "revisions", BUILD1]
        self.assertIsNone(artifacts.previous_build(names, BUILD1))
        self.assertEqual(artifacts.previous_build(names + [BUILD0], BUILD1), BUILD0)

    @given(st.lists(st.integers(min_value=0, max_value=40), max_size=8), st.integers(min_value=0, max_value=40))
    def test_the_answer_is_an_older_name_with_none_between_it_and_the_current_one(self, stamps, cur):
        """For any kept names the answer is None or one of them, older than current, and no kept name lies strictly
        between the answer and current."""
        name = "pages-202609261000%02d".__mod__
        names = [name(s) for s in stamps]
        got = artifacts.previous_build(names, name(cur))
        older = [s for s in stamps if s < cur]
        self.assertEqual(got, name(max(older)) if older else None)


class MapSourceFiles(AccessBase):
    """figure_map.map_source_files: every distinct src.file and impl.file of a map, in map order (pure)."""

    def test_the_script_then_the_shared_component_each_once(self):
        """b2_map() names src/B2_calendar.py on three elements and lib/components.py once; each comes once."""
        fmap = parse_map(map_bytes(b2_map()))
        assert isinstance(fmap, FigureMap), fmap
        self.assertEqual(map_source_files(fmap), ("src/B2_calendar.py", "lib/components.py"))


class FilesPathspec(AccessBase):
    """core.files_pathspec: the history files as literal pathspecs relative to the repository (pure)."""

    def test_files_inside_the_repository_become_literal_paths_once(self):
        """Each file under the repository is one :(literal) path; a repeat is dropped; a file outside is left out."""
        repo = Path("/srv/paper")
        files = [repo / "figs/out/x.limnmap.json", repo / "figs/src/a b.py", repo / "figs/src/a b.py", Path("/srv/o")]
        self.assertEqual(
            files_pathspec(repo, files, repo / "figs"),
            [":(literal)figs/out/x.limnmap.json", ":(literal)figs/src/a b.py"],
        )

    def test_too_many_files_fall_back_to_the_figure_folder(self):
        """More than HISTORY_PATHS_MAX files are named by the folder holding them all, so the command line stays short."""
        repo = Path("/srv/paper")
        files = [repo / "figs" / ("f%d.py" % i) for i in range(HISTORY_PATHS_MAX + 1)]
        self.assertEqual(files_pathspec(repo, files, repo / "figs"), [":(literal)figs"])
        self.assertEqual(len(files_pathspec(repo, files[:-1], repo / "figs")), HISTORY_PATHS_MAX)

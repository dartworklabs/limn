"""The changes view and the comparison build show a document's own registered files only (SECURITY.md).

Each class below is one way the change view or a comparison build reached a file that is not one of the document's
own - under a dot-named folder, through a folder replaced by a symlink after startup, or by a folder name Git reads as
a pattern. A viewer asks the routes, as in test_revision_path_identity.py.

Run: uv run pytest -q src/limn/revisions/tests/test_revision_registered_files.py
"""

import shutil
import subprocess
from pathlib import Path
from unittest import mock

from limn.administration.serve_documents import make_docs
from limn.pins.location.lookup import recorded_place, recorded_root
from limn.revisions import core, execution
from limn.runtime.documents import Doc

from helpers import edit_stored, needs_tex, ps
from helpers_access import CAROL, REPO_NEW, REPO_OLD, AccessBase, ScopedRepo, member_add
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
    """A figure document (figs/) whose map names a file under a dot-named folder."""

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

    def test_registered_file_refuses_a_dot_named_part(self):
        """registered_file names no file with a dot-named part below the document's folder (any case), and keeps one
        whose name merely holds a dot."""
        fig = figure_doc(self.src, ps.APP.C.paths)
        for rel in (".Private/hidden.py", "src/.old/x.py", "src/.x.py"):
            with self.subTest(rel=rel):
                self.assertIsNone(core.registered_file(fig, fig.src / rel))
        self.assertEqual(core.registered_file(fig, fig.src / "src" / "a.b.py"), fig.registered_src / "src" / "a.b.py")


def large_map(parts):
    """b2_map() with its root element (src/B2_calendar.py) followed by parts elements, each drawn by a script of its
    own (src/part<i>.py): the figure's history files are those scripts, the root's, the map and its PDF."""
    fmap = b2_map()
    root = fmap["pages"][0]["elements"][0]
    fmap["pages"][0]["elements"] = [root] + [
        {"id": "B2/n%d" % i, "parent": "B2", "frac": [0.1, 0.1, 0.1, 0.1], "src": {"file": "src/part%d.py" % i}}
        for i in range(parts)
    ]
    for el in fmap["pages"][0]["elements"][1:]:
        el["src"].update(lo=1, hi=1)
    return fmap


class LargeFigureMap(Repository):
    """A figure document (figs/) whose map names about HISTORY_PATHS_MAX history files, and a later commit that touches
    only files no map names: figs/unlisted.txt and figs/.private/hidden.py (both carry SECRET)."""

    def history(self, count):
        """Serve the figure with a map whose history files are exactly count, commit it ("figure"), then commit the
        unlisted files; (the figure commit, the unlisted one)."""
        fig = figure_doc(self.src, ps.APP.C.paths)
        write_build(fig, BUILD1, large_map(count - 3))
        self.serve([fig])
        self.assertEqual(len(ps.APP.revision_requests.context().history_files(fig) or ()), count)
        first = self.commit("figure")
        (fig.src / "unlisted.txt").write_text(SECRET + "\n", encoding="utf-8")
        (fig.src / ".private").mkdir()
        (fig.src / ".private" / "hidden.py").write_text(SECRET + "\n", encoding="utf-8")
        return first, self.commit("unlisted %s" % SECRET)

    def test_more_history_files_than_the_limit_are_refused_never_widened_to_the_folder(self):
        """HISTORY_PATHS_MAX + 1 history files: the document has no history (too_many_files, with the limit) - its
        folder, which holds figs/unlisted.txt, is never named instead - and neither its commit diff nor a range is
        answered."""
        first, head = self.history(core.HISTORY_PATHS_MAX + 1)
        code, body = self.call("GET", "/api/revisions?doc=fig", headers=CAROL)
        self.assertEqual(code, 200, body)
        got = (body["available"], body["revisions"], body.get("reason"), body.get("limit"))
        self.assertEqual(got, (False, [], "too_many_files", core.HISTORY_PATHS_MAX))
        self.assertNotIn(SECRET, str(body))
        for query in ("", "&base=%s" % first):
            with self.subTest(query=query):
                code, out = self.call("GET", "/api/revision-diff?doc=fig&commit=%s%s" % (head, query), headers=CAROL)
                self.assertEqual((code, out.get("reason")), (404, "too_many_files"), out)
                self.assertNotIn(SECRET, str(out))

    def test_history_files_at_the_limit_are_named_one_by_one(self):
        """Exactly HISTORY_PATHS_MAX history files: the history is the figure's commit only, and the diff of the commit
        touching the unlisted files is refused as outside it."""
        _, head = self.history(core.HISTORY_PATHS_MAX)
        self.assertEqual(self.subjects("fig"), ["figure"])
        code, out = self.call("GET", "/api/revision-diff?doc=fig&commit=%s" % head, headers=CAROL)
        self.assertEqual((code, out.get("reason")), (404, "commit_not_recent"), out)
        self.assertNotIn(SECRET, str(out))


class ComparisonSnapshot(Repository):
    """A LaTeX document (main.tex) whose main file inputs .private/notes.tex, committed with it."""

    def setUp(self):
        """Commit main.tex and .private/notes.tex (BEFORE), then change both (AFTER)."""
        super().setUp()
        (self.src / ".private").mkdir()
        self.notes = self.src / ".private" / "notes.tex"

    def history(self, include):
        """Commit main.tex including .private/notes with the TeX command include, then a commit changing both; the
        whole-commit comparison spec of the second."""
        self.notes.write_text(SECRET + "BEFORE\n", encoding="utf-8")
        body = "\\documentclass{article}\n\\begin{document}\n%s\nOld public.\n\\end{document}\n" % include
        self.main.write_text(body, encoding="utf-8")
        self.commit("base")
        self.notes.write_text(SECRET + "AFTER\n", encoding="utf-8")
        self.main.write_text(body.replace("Old public", "New public"), encoding="utf-8")
        head = self.commit("visible change and hidden change")
        spec = core.revision_spec(ps.APP.docs[0], head, None, ps.APP.revision_requests.context())
        self.assertIsInstance(spec, core.RevisionSpec, spec)
        return spec

    def test_a_snapshot_leaves_dot_named_folders_out(self):
        """Both sides of the comparison are written without .private: no blob of it reaches the build copy."""
        spec = self.history("\\input{.private/notes}")
        for commit, side in ((spec.base, "old"), (spec.head, "new")):
            dest = self.src.parent / side
            self.assertIsNone(execution.revision_snapshot(spec, commit, dest))
            self.assertTrue((dest / "main.tex").is_file())
            self.assertFalse((dest / ".private").exists())

    def test_ls_tree_rows_under_dot_named_parts_are_skipped(self):
        """parse_ls_tree_row: a row under a dot-named part is DotNamedRow, whatever it is (a symlink too), while a name
        that could leave the snapshot folder is still unsafe."""
        oid = "0" * 40
        for name in (".private/notes.tex", "a/.old/refs.bib", ".draft.tex"):
            with self.subTest(name=name):
                row = ("100644 blob %s 5\t%s" % (oid, name)).encode()
                self.assertIsInstance(execution.parse_ls_tree_row(row, ""), execution.DotNamedRow)
        link = ("120000 blob %s 5\t.private" % oid).encode()
        self.assertIsInstance(execution.parse_ls_tree_row(link, ""), execution.DotNamedRow)
        for name in (".git/config", "a/../b.tex"):
            with self.subTest(name=name):
                row = ("100644 blob %s 5\t%s" % (oid, name)).encode()
                self.assertIsInstance(execution.parse_ls_tree_row(row, ""), execution.UnsafeTreeRow)
        plain = ("100644 blob %s 5\tsub/part.tex" % oid).encode()
        self.assertEqual(execution.parse_ls_tree_row(plain, ""), execution.TreeFile(Path("sub/part.tex"), oid, 5))

    def test_a_pdf_cached_before_the_snapshot_rule_is_not_served(self):
        """A ready comparison stored under the previous cache version's key (built when snapshots still copied
        dot-named folders) is not served: the commit's PDF is not ready."""
        spec = self.history("\\input{.private/notes}")
        with mock.patch.object(core, "REVISION_CACHE_VERSION", "latex-pdf-v3"):
            old = core.comparison_key(spec.repo, spec.source, spec.main, spec.base, spec.head)
        self.assertNotEqual(old, spec.key)
        entry = ps.APP.docs[0].dir / "revisions" / old
        entry.mkdir(parents=True)
        (entry / "status.json").write_text('{"state": "ready"}', encoding="utf-8")
        (entry / "revision.pdf").write_bytes(b"%PDF-1.4 " + SECRET.encode())
        code, body = self.call("GET", "/api/revision-pdf?commit=%s" % spec.head, headers=CAROL)
        self.assertNotEqual(code, 200)
        self.assertNotIn(SECRET, str(body))

    @needs_tex("bwrap", "latexdiff", "latexmk", "pdftotext")
    def test_the_comparison_pdf_holds_nothing_of_a_dot_named_input(self):
        """The comparison of a main that inputs .private/notes.tex. latexdiff --flatten reads an \\input itself, so with
        the file in the snapshot both its texts were in the PDF; now it finds no such file and the build fails without
        quoting it. \\InputIfFileExists is left to TeX, which the sandbox runs with openin_any=p (no dot-named file is
        read either way): that comparison still builds, without the text."""
        for include, built in (("\\input{.private/notes}", False), ("\\InputIfFileExists{.private/notes}{}{}", True)):
            with self.subTest(include=include):
                spec = self.history(include)
                job = self.src.parent / ("job-%s" % built)
                job.mkdir()
                result = execution.revision_compile(spec, job, 60)
                self.assertEqual(isinstance(result, core.ComparisonBuilt), built, result)
                log = (job / "build.log").read_text(encoding="utf-8") if (job / "build.log").exists() else ""
                self.assertNotIn(SECRET, log)
                if built:
                    text = subprocess.check_output(["pdftotext", str(job / "revision.pdf"), "-"], text=True)
                    self.assertIn("New", text)
                    self.assertNotIn(SECRET, text)


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


class PinAfterRootLink(ScopedRepo):
    """ScopedRepo's manuscript folder replaced, after startup, by a symlink to a dot-named folder of the repository."""

    def test_a_pin_keeps_its_scope(self):
        """Pin alpha's scoped diff of its fix commit is the same after the link: its file is still ms/main.tex."""
        before = self.diff_ok(self.fix, self.p1)
        self.assertEqual(before["scope"]["mode"], "pin")
        hidden = self.repo / ".private"
        hidden.mkdir()
        (hidden / "main.tex").write_text("hidden\n", encoding="utf-8")
        shutil.rmtree(self.src)
        self.src.symlink_to(hidden, target_is_directory=True)
        self.assertEqual(self.diff_ok(self.fix, self.p1)["scope"], before["scope"])


class PinInLinkedFolder(Repository):
    """A LaTeX document paper/main.tex whose fix commit changes three paragraphs; pin alpha (line 4) is closed on it
    with a recorded change on the beta paragraph (line 12), which decides its blocks."""

    def setUp(self):
        """Commit REPO_OLD, add pin alpha, commit REPO_NEW and close the pin with its recorded change."""
        super().setUp()
        (self.src / "paper").mkdir()
        self.paper = self.src / "paper" / "main.tex"
        self.paper.write_text(REPO_OLD, encoding="utf-8")
        docs = make_docs(["pp=논문:paper/main.tex"], self.src, ps.APP.C.paths)
        self.assertIsInstance(docs, list, docs)
        self.serve(docs)
        self.commit("first")
        code, d = self.call("POST", "/api/pin", {"doc": "pp", "file": str(self.paper), "lo": 4, "hi": 4, "note": "a"})
        self.assertEqual(code, 200, d)
        self.pin = d["id"]
        self.paper.write_text(REPO_NEW, encoding="utf-8")
        self.fix = self.commit("fix")
        code, d = self.call(
            "POST",
            "/api/pins/%d/close" % self.pin,
            {"ref": self.fix[:8], "changes": [{"file": "paper/main.tex", "lo": 12, "hi": 12}]},
        )
        self.assertEqual(code, 200, d)

    def scope(self):
        """The pin's scope of the fix commit, from the source diff and from the comparison spec."""
        code, body = self.call(
            "GET", "/api/revision-diff?doc=pp&commit=%s&pin=%d" % (self.fix, self.pin), headers=CAROL
        )
        self.assertEqual(code, 200, body)
        spec = core.revision_spec(ps.APP.docs[0], self.fix, self.pin, ps.APP.revision_requests.context())
        self.assertIsInstance(spec, core.RevisionSpec, spec)
        return body["scope"], spec.scope, spec.key

    def test_a_folder_replaced_by_a_link_keeps_the_pins_file_and_ranges(self):
        """paper -> a copy of it (a plain name, or a dot-named one): the pin is still on paper/main.tex and its
        recorded range still picks the beta paragraph, in the diff's scope and the comparison spec alike."""
        before = self.scope()
        self.assertEqual((before[0]["mode"], before[0]["hunks"]), ("pin", 1))
        self.assertTrue(before[1])
        folder = self.src / "paper"
        for name in ("copy", ".copy"):
            shutil.copytree(folder, self.src / name)
        shutil.rmtree(folder)
        for name in ("copy", ".copy"):
            with self.subTest(target=name):
                if folder.is_symlink():
                    folder.unlink()
                folder.symlink_to(name, target_is_directory=True)
                self.assertEqual(self.scope(), before)

    def test_a_moved_checkouts_pin_keeps_its_file_and_ranges_after_a_link(self):
        """The pin as a checkout at /old-checkout wrote it - its file and its recorded change there, file_rel
        paper/main.tex - is placed by its file_rel, so its recorded range still picks the beta paragraph; replacing
        paper/ by a link to a copy (a plain name, or a dot-named one) then changes neither the scope nor the
        comparison's blocks and key."""
        old = Path("/old-checkout") / "paper" / "main.tex"

        def moved(rows):
            """The pin's file and recorded change as the old checkout stored them."""
            r = next(r for r in rows if r["id"] == self.pin)
            self.assertEqual(r["file_rel"], "paper/main.tex")
            r["file"] = str(old)
            r["changes"] = [dict(c, file=str(old)) for c in r["changes"]]

        edit_stored(moved)
        before = self.scope()
        self.assertEqual((before[0]["mode"], before[0]["source"], before[0]["hunks"]), ("pin", "changes", 1))
        self.assertTrue(before[1])
        folder = self.src / "paper"
        for name in ("copy", ".copy"):
            shutil.copytree(folder, self.src / name)
        shutil.rmtree(folder)
        for name in ("copy", ".copy"):
            with self.subTest(target=name):
                if folder.is_symlink():
                    folder.unlink()
                folder.symlink_to(name, target_is_directory=True)
                self.assertEqual(self.scope(), before)

    def test_recorded_place_is_lexical_below_the_root(self):
        """recorded_place: a stored path below the root is placed where it was recorded ('..' folded), through a link
        or not; one with a dot-named part is refused."""
        root, state = ps.APP.C.src, ps.APP.C.state
        record = {"file": str(self.paper), "file_rel": "paper/main.tex"}
        target = self.src / "copy"
        shutil.copytree(self.src / "paper", target)
        shutil.rmtree(self.src / "paper")
        (self.src / "paper").symlink_to("copy", target_is_directory=True)
        self.assertEqual(recorded_place(str(self.paper), record, root, state), self.paper)
        self.assertEqual(
            recorded_place(str(root / "paper" / ".." / "copy" / "main.tex"), record, root, state),
            root / "copy" / "main.tex",
        )
        for stored in (root / ".private" / "main.tex", root / "paper" / ".old" / "main.tex"):
            with self.subTest(stored=stored):
                self.assertIsNone(recorded_place(str(stored), record, root, state))

    def test_a_moved_record_is_placed_by_its_own_file_rel(self):
        """recorded_place for a record of a checkout at /old-checkout: its file is root / file_rel and a change below
        /old-checkout goes along, whether or not the tree has those files (nothing is asked of it); a record without a
        usable file_rel, a change outside the record's root and a dot-named part place nothing."""
        root, state = ps.APP.C.src, ps.APP.C.state
        shutil.rmtree(self.src / "paper")  # placed all the same: the commit the pin was closed on still has it
        old = Path("/old-checkout")
        record = {"file": str(old / "paper" / "main.tex"), "file_rel": "paper/main.tex"}
        self.assertEqual(recorded_root(record["file"], record["file_rel"]), old)
        for stored, placed in (
            (old / "paper" / "main.tex", root / "paper" / "main.tex"),
            (old / "paper" / "sub" / "part.tex", root / "paper" / "sub" / "part.tex"),
            (old / "paper" / ".." / "refs.bib", root / "refs.bib"),
            (Path("/elsewhere") / "paper" / "main.tex", None),
            (old / ".private" / "main.tex", None),
        ):
            with self.subTest(stored=stored):
                self.assertEqual(recorded_place(str(stored), record, root, state), placed)
        for rel in (None, "", "/paper/main.tex", "../paper/main.tex", "other/main.tex", "old-checkout/paper/main.tex"):
            with self.subTest(file_rel=rel):
                self.assertIsNone(recorded_root(record["file"], rel))
                stale = dict(record, file_rel=rel)
                self.assertIsNone(recorded_place(record["file"], stale, root, state))


class DocumentPastStartup(Repository):
    """Documents that lie under a dot-named part of the manuscript, made directly as startup would refuse to
    (serve_documents.DocDotNamed): a LaTeX document and a Markdown document in .Private/, and a LaTeX document whose
    main file is the dotfile paper/.draft.tex. The dot-named files' text carries SECRET; paper/main.tex, changed by
    the same two commits, is public."""

    def setUp(self):
        """Commit the public paper, then it and the dot-named files twice (so a comparison has a parent); serve the
        three."""
        super().setUp()
        for rel in ("paper/main.tex", ".Private/main.tex", ".Private/notes.md", "paper/.draft.tex"):
            (self.src / rel).parent.mkdir(parents=True, exist_ok=True)
        tex = "\\documentclass{article}\n\\begin{document}\n%s\n\\end{document}\n"
        (self.src / "paper" / "main.tex").write_text(tex % "public", encoding="utf-8")
        self.commit("public")
        for n in (1, 2):
            for rel in (".Private/main.tex", "paper/.draft.tex"):
                (self.src / rel).write_text(tex % ("%s %d" % (SECRET, n)), encoding="utf-8")
            (self.src / ".Private" / "notes.md").write_text("# %s %d\n" % (SECRET, n), encoding="utf-8")
            (self.src / "paper" / "main.tex").write_text(tex % ("public %d" % n), encoding="utf-8")
            self.head = self.commit("private %s %d" % (SECRET, n))
        paths = ps.APP.C.paths
        self.docs = {
            "pp": Doc("pp", "논문", "tex", self.src / ".Private", self.src / ".Private" / "main.tex", paths=paths),
            "nt": Doc("nt", "노트", "markdown", self.src / ".Private", self.src / ".Private" / "notes.md", paths=paths),
            "dm": Doc("dm", "초안", "tex", self.src / "paper", self.src / "paper" / ".draft.tex", paths=paths),
        }
        self.assertTrue(all(core.dot_named_document(d) for d in self.docs.values()))
        self.serve(list(self.docs.values()))

    def test_no_route_shows_such_a_documents_history(self):
        """Each document has no history; asking a commit of its files for a diff, a range or a comparison is refused,
        and nothing a viewer is answered quotes SECRET."""
        for key in self.docs:
            with self.subTest(doc=key):
                code, body = self.call("GET", "/api/revisions?doc=%s" % key, headers=CAROL)
                self.assertEqual((code, body.get("available"), body.get("revisions") or []), (200, False, []), body)
                for query in ("", "&base=%s" % self.head):
                    code, out = self.call(
                        "GET", "/api/revision-diff?doc=%s&commit=%s%s" % (key, self.head, query), headers=CAROL
                    )
                    self.assertEqual(code, 404, out)
                    self.assertNotIn(SECRET, str(out))
                code, out = self.call("GET", "/api/revision-build?doc=%s&commit=%s" % (key, self.head), headers=CAROL)
                self.assertNotIn(SECRET, str(out))
        self.assertIsInstance(
            core.revision_spec(self.docs["pp"], self.head, None, ps.APP.revision_requests.context()),
            core.CommitNotRecent,
        )

    def test_a_snapshot_refuses_a_build_root_under_a_dot_named_part(self):
        """With the history's check out of the way (dot_named_document answering False), the comparison spec of the
        .Private document names its build root from the manuscript root, and a snapshot of it is refused before any
        file is written; so is one whose main file is a dotfile. The public folder's snapshot is written."""
        ctx = ps.APP.revision_requests.context()
        with mock.patch.object(core, "dot_named_document", return_value=False):
            specs = {key: core.revision_spec(self.docs[key], self.head, None, ctx) for key in ("pp", "dm")}
        for key, tree_source in (("pp", ".Private"), ("dm", "paper")):
            with self.subTest(doc=key):
                spec = specs[key]
                self.assertIsInstance(spec, core.RevisionSpec, spec)
                assert isinstance(spec, core.RevisionSpec)
                self.assertEqual(spec.tree_source, tree_source)
                dest = self.src.parent / ("snapshot-" + key)
                self.assertEqual(execution.revision_snapshot(spec, self.head, dest), core.StepFailed("unsafe_snapshot"))
                self.assertFalse(dest.exists())
        public = specs["dm"]._replace(main=Path("main.tex"))
        dest = self.src.parent / "snapshot-public"
        self.assertIsNone(execution.revision_snapshot(public, self.head, dest))
        self.assertEqual(sorted(p.name for p in dest.iterdir()), ["main.tex"])


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

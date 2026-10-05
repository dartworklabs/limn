"""A figure set or a view-only PDF inside a LaTeX document's folder must not make that document stale.

docs/handbook/build-sync.md §원고 변화 감지: the LaTeX document's source list leaves out the figure files of another
document's folder and another document's view-only PDF, and counts a file of those the build on screen read (its
latexmk recorder file, the .fls published with its pages). The documents come from startup_documents.make_docs, so
the rule is exercised through the production wiring. The tree is helpers_figure.write_figure_set_tree: the figure PDFs
sit in figs/, not in figs/out/, which a manuscript scan skips by name.
"""

import json
import time
import unittest
from pathlib import Path

from limn.builds import artifacts as limn_build
from limn.builds.artifacts import BuildOk, BuildUnchanged
from limn.builds.queries import BuildQueries, document_build_queries
from limn.documents import reads as meta
from limn.security.access import LOCAL_ACTOR

from helpers import Base, minimal_pdf, needs_tex, ps, req
from helpers_figure import (
    BUILD1,
    age_tree,
    make_figure_set_docs,
    rewrite_ahead,
    write_build,
    write_figure_set_tree,
)

# The build supplier for reads called directly, apart from the run's own bindings behind ps.APP.document_views.
BUILDS = document_build_queries()
FLS_HEAD = "PWD /build\n"


def fls_reading(*inputs: str) -> str:
    """The text of a latexmk recorder file whose pdflatex run opened `inputs` (paths as pdflatex writes them, relative to
    the folder it ran in) after one TeX Live file."""
    return FLS_HEAD + "INPUT /usr/share/texlive/article.cls\n" + "".join("INPUT %s\n" % p for p in inputs)


class Fixture(Base):
    """ms (LaTeX, the manuscript folder), fig (figure document, figs/) and rv (view-only reviewer.pdf in the manuscript
    folder) served together; every file aged, so what a test rewrites ahead is newer than the build baseline."""

    figure_include = ""

    def setUp(self):
        """Write the tree, serve the three documents the way startup makes them, and age every file."""
        super().setUp()
        write_figure_set_tree(self.src, self.figure_include)
        self.ms, self.fig, self.rv = make_figure_set_docs(self.src, ps.APP.C.paths)
        ps.APP.set_docs([self.ms, self.fig, self.rv])
        self.state = ps.APP.C.state
        age_tree(self.src)

    def tearDown(self):
        """Back to the single document before the fixture removes the manuscript."""
        ps.APP.set_docs(None)
        super().tearDown()

    def on_screen_without_tex(self, fls: str | None = None) -> Path:
        """Put a build of ms on screen as a finished build leaves it (no latexmk): its page directory, with the recorder
        file `fls` when given, and the baseline measured now (built_src_mtime.txt)."""
        pages = write_build(self.ms, BUILD1, None)
        if fls is not None:
            (pages / "main.fls").write_text(fls, encoding="utf-8")
        limn_build.write_built_src_mtime(self.ms, self.state)
        return pages

    def facts(self) -> dict:
        """What the viewer and the pick read about ms: its /api/docs brief, /api/meta, the pick's Publication, its
        src_mtime and its fingerprint, with the 2 second memo expired."""
        self.ms.mcache[2] = 0.0
        brief = next(b for b in meta.docs_payload(ps.APP.docs, {}, 0, self.state, BUILDS)["docs"] if b["key"] == "ms")
        light = ps.APP.document_views.meta(self.ms, dict(LOCAL_ACTOR), light=True)
        pub = BuildQueries(lambda: limn_build.BuildMapCache()).publication(
            self.ms, limn_build.cur_pages(self.ms).name, self.state
        )
        return {
            "stale_docs": brief["stale_build"],
            "stale_meta": light["stale_build"],
            "src_mtime": brief["src_mtime"],
            "pick_stale": pub.stale,
            "fingerprint": limn_build.doc_fingerprint(self.ms, self.state),
            "sources": [rel for rel, _ in limn_build.iter_sources(self.ms, self.ms.src, self.state)],
        }

    def stale(self) -> tuple[bool, bool, bool]:
        """ms's stale_build in /api/docs and in /api/meta, and the pick's stale flag, as a triple."""
        f = self.facts()
        return f["stale_docs"], f["stale_meta"], f["pick_stale"]


class FigureSetInsideManuscript(Fixture):
    """The reported bug: re-rendering the figure set must not make a LaTeX document that does not read it stale."""

    def test_rerender_of_the_figure_set_leaves_the_latex_document_current(self):
        """Rewriting figures.pdf, panel1.pdf, the map and a drawing script moves no field of ms: not stale in /api/docs,
        /api/meta or the pick, and the same src_mtime and fingerprint."""
        self.on_screen_without_tex()
        before = self.facts()
        self.assertEqual(self.stale(), (False, False, False))
        rewrite_ahead(self.src / "figs" / "figures.pdf", minimal_pdf("fig v2"))
        rewrite_ahead(self.src / "figs" / "panel1.pdf", minimal_pdf("panel v2"))
        rewrite_ahead(self.src / "figs" / "figures.limnmap.json")
        rewrite_ahead(self.src / "figs" / "src" / "B2_calendar.py")
        after = self.facts()
        keys = ("stale_docs", "stale_meta", "pick_stale", "src_mtime", "fingerprint")
        self.assertEqual({k: after[k] for k in keys}, {k: before[k] for k in keys})
        self.assertEqual(after["sources"], ["main.tex", "refs.bib"])

    def test_every_figure_extension_in_every_depth_of_the_figure_folder_is_set_apart(self):
        """png, jpg, jpeg, eps and svg under figs/render/deep/ (any case of the suffix) leave ms current, as pdf does."""
        deep = self.src / "figs" / "render" / "deep"
        deep.mkdir(parents=True)
        names = ("a.png", "b.JPG", "c.jpeg", "d.eps", "e.SVG", "f.pdf")
        for name in names:
            (deep / name).write_bytes(b"x")
        age_tree(self.src)
        self.on_screen_without_tex()
        for name in names:
            with self.subTest(name=name):
                rewrite_ahead(deep / name)
                self.assertEqual(self.stale(), (False, False, False))

    def test_the_figure_documents_own_tab_follows_its_map_not_the_latex_tab(self):
        """The figure's own src_mtime still moves with its map, so src_sig changes and the viewer re-reads the figure's
        pins - while ms's does not."""
        self.on_screen_without_tex()
        for d in ps.APP.docs:
            d.mcache[2] = 0.0
        before = {b["key"]: b["src_mtime"] for b in meta.docs_payload(ps.APP.docs, {}, 0, self.state, BUILDS)["docs"]}
        rewrite_ahead(self.src / "figs" / "figures.limnmap.json")
        for d in ps.APP.docs:
            d.mcache[2] = 0.0
        after = {b["key"]: b["src_mtime"] for b in meta.docs_payload(ps.APP.docs, {}, 0, self.state, BUILDS)["docs"]}
        self.assertGreater(after["fig"], before["fig"])
        self.assertEqual(after["ms"], before["ms"])

    def test_a_reviewer_pdf_in_the_manuscript_root_does_not_stale_the_latex_document(self):
        """rv is a view-only document whose folder is the manuscript root: re-saving reviewer.pdf leaves ms current."""
        self.on_screen_without_tex()
        rewrite_ahead(self.src / "reviewer.pdf", minimal_pdf("reviewer v2"))
        self.assertEqual(self.stale(), (False, False, False))

    def test_the_reviewer_pdf_is_set_apart_as_a_file_not_as_its_folder(self):
        """Only reviewer.pdf leaves the list: another PDF in the same root (appendix.pdf, no document) and the .tex and
        .bib there still make ms stale."""
        (self.src / "appendix.pdf").write_bytes(minimal_pdf("appendix"))
        age_tree(self.src)
        self.on_screen_without_tex()
        for name in ("appendix.pdf", "main.tex", "refs.bib"):
            with self.subTest(name=name):
                age_tree(self.src)
                limn_build.write_built_src_mtime(self.ms, self.state)
                rewrite_ahead(self.src / name)
                self.assertTrue(self.facts()["stale_docs"])

    def test_the_figure_folders_tex_still_counts(self):
        """A .tex in the figure folder (a TikZ file the manuscript \\input's) is not a figure-set suffix: editing it
        makes ms stale, while the figure PDF next to it does not."""
        (self.src / "figs" / "diagram.tex").write_text("\\relax\n", encoding="utf-8")
        age_tree(self.src)
        self.on_screen_without_tex()
        rewrite_ahead(self.src / "figs" / "figures.pdf")
        self.assertFalse(self.facts()["stale_docs"])
        rewrite_ahead(self.src / "figs" / "diagram.tex")
        self.assertTrue(self.facts()["stale_docs"])


class ManuscriptEditsStillCount(Fixture):
    """The inverse: what the build reads or may read, and what no other document owns, still makes ms stale."""

    def test_tex_edit_stales(self):
        """A .tex edit at the manuscript root makes ms stale in all three places."""
        self.on_screen_without_tex()
        rewrite_ahead(self.main)
        self.assertEqual(self.stale(), (True, True, True))

    def test_bib_edit_stales(self):
        """A .bib is read by bibtex, which the pdflatex recorder file does not list: it counts by suffix."""
        self.on_screen_without_tex()
        rewrite_ahead(self.src / "refs.bib")
        self.assertTrue(self.facts()["stale_docs"])

    def test_a_pdf_figure_outside_every_other_document_stales(self):
        """images/fig1.pdf belongs to no other document: re-exporting it is a manuscript change."""
        (self.src / "images").mkdir()
        (self.src / "images" / "fig1.pdf").write_bytes(minimal_pdf("img"))
        age_tree(self.src)
        self.on_screen_without_tex()
        rewrite_ahead(self.src / "images" / "fig1.pdf", minimal_pdf("img v2"))
        self.assertTrue(self.facts()["stale_docs"])

    def test_a_figure_folder_that_is_the_whole_root_sets_nothing_apart(self):
        """fig=그림:.::figs/figures.limnmap.json has the manuscript root as its folder: nothing is set apart, so the root's
        PDFs count as they did before."""
        self.ms, self.fig = make_figure_set_docs(
            self.src, ps.APP.C.paths, ["ms=본문:main.tex", "fig=그림:.::figs/figures.limnmap.json"]
        )
        ps.APP.set_docs([self.ms, self.fig])
        (self.src / "images").mkdir()
        (self.src / "images" / "fig1.pdf").write_bytes(minimal_pdf("img"))
        age_tree(self.src)
        self.on_screen_without_tex()
        rewrite_ahead(self.src / "images" / "fig1.pdf")
        self.assertTrue(self.facts()["stale_docs"])
        self.assertIn("figs/figures.pdf", self.facts()["sources"])

    def test_a_figure_folder_outside_the_latex_root_sets_nothing_apart(self):
        """The LaTeX build root is a subfolder (paper/); the figure folder (figs/) is beside it, outside its tree: the
        paper's own images/fig1.pdf still counts."""
        paper = self.src / "paper"
        (paper / "images").mkdir(parents=True)
        (paper / "main.tex").write_text("\\relax\n", encoding="utf-8")
        (paper / "images" / "fig1.pdf").write_bytes(minimal_pdf("img"))
        self.ms, self.fig = make_figure_set_docs(
            self.src, ps.APP.C.paths, ["ms=본문:paper/main.tex", "fig=그림:figs/figures.limnmap.json"]
        )
        ps.APP.set_docs([self.ms, self.fig])
        age_tree(self.src)
        self.on_screen_without_tex()
        rewrite_ahead(self.src / "figs" / "figures.pdf")
        self.assertFalse(self.facts()["stale_docs"])
        rewrite_ahead(paper / "images" / "fig1.pdf")
        self.assertTrue(self.facts()["stale_docs"])


class FigureSetFileTheBuildRead(Fixture):
    """A figure-set file the build on screen read (its recorder file lists it) is part of the manuscript again: its
    re-render changes the LaTeX output, so ms is stale; the files beside it that the build did not read are not."""

    def test_a_file_the_recorder_lists_stales_and_a_file_it_does_not_list_does_not(self):
        """panel1.pdf is in the .fls of the build on screen; figures.pdf is not."""
        self.on_screen_without_tex(fls_reading("./figs/panel1.pdf"))
        rewrite_ahead(self.src / "figs" / "figures.pdf", minimal_pdf("fig v2"))
        self.assertEqual(self.stale(), (False, False, False))
        rewrite_ahead(self.src / "figs" / "panel1.pdf", minimal_pdf("panel v2"))
        self.assertEqual(self.stale(), (True, True, True))

    def test_a_listed_file_is_found_however_pdflatex_spells_its_path(self):
        """The recorder file names a path relative to the folder pdflatex ran in (./figs/x, figs/x, ./figs/../figs/x) or an
        absolute path into the build copy: each is the same file."""
        build_copy = self.ms.build
        spellings = (
            "./figs/panel1.pdf",
            "figs/panel1.pdf",
            "./figs/../figs/panel1.pdf",
            "%s/figs/panel1.pdf" % build_copy,
        )
        for spelled in spellings:
            with self.subTest(spelled=spelled):
                age_tree(self.src)
                self.on_screen_without_tex(fls_reading(spelled))
                rewrite_ahead(self.src / "figs" / "panel1.pdf")
                self.assertTrue(self.facts()["stale_docs"])

    def test_without_a_recorder_file_the_figure_folder_is_set_apart(self):
        """A build with no .fls in its pages (made before the rule, or latexmk's recorder switched off) reads nothing: the
        figure folder is set apart, so even panel1.pdf's re-render leaves ms current."""
        self.on_screen_without_tex()
        rewrite_ahead(self.src / "figs" / "panel1.pdf")
        self.assertEqual(self.stale(), (False, False, False))

    def test_an_unreadable_recorder_file_is_no_exception(self):
        """A .fls that is a directory, or holds bytes that are not text, lists nothing: the rule applies without it."""
        pages = self.on_screen_without_tex()
        (pages / "main.fls").mkdir()
        rewrite_ahead(self.src / "figs" / "panel1.pdf")
        self.assertFalse(self.facts()["stale_docs"])
        (pages / "main.fls").rmdir()
        (pages / "main.fls").write_bytes(b"\xff\xfe\x00INPUT ./figs/panel1.pdf\n\x00")
        self.assertFalse(self.facts()["stale_docs"])

    def test_the_recorder_file_of_the_pick_build_decides_not_the_one_on_screen(self):
        """The pick compares the manuscript with the build it was made on (the previous build kept one generation back):
        that build's .fls says which figure files counted for it."""
        older = write_build(self.ms, "pages-20260926090000", None)
        (older / "main.fls").write_text(fls_reading("./figs/panel1.pdf"), encoding="utf-8")
        write_build(self.ms, BUILD1, None)  # on screen, with no recorder file
        limn_build.write_built_src_mtime(self.ms, self.state)
        (self.ms.dir / "builds.json").write_text(
            json.dumps(
                {"seq": 2, "last": None, "builds": [{"build": "pages-20260926090000", "src_mtime": time.time() - 50}]}
            ),
            encoding="utf-8",
        )
        rewrite_ahead(self.src / "figs" / "panel1.pdf")
        queries = BuildQueries(lambda: limn_build.BuildMapCache())
        self.ms.mcache[2] = 0.0
        self.assertTrue(queries.publication(self.ms, "pages-20260926090000", self.state).stale)
        self.ms.mcache[2] = 0.0
        self.assertFalse(queries.publication(self.ms, BUILD1, self.state).stale)


class FigureSetBuiltWithRealLatexmk(Fixture):
    """The rule with the recorder file a real latexmk leaves: the manuscript includes figs/panel1.pdf and a .bib."""

    figure_include = (
        "\\includegraphics[width=3cm]{figs/panel1.pdf}\n\\bibliographystyle{plain}\\bibliography{refs}\\nocite{a}"
    )

    @needs_tex("latexmk", "pdftoppm")
    def test_the_file_the_build_read_stales_and_the_one_it_did_not_read_does_not(self):
        """After a real build, figures.pdf (not included) re-rendered leaves ms current; panel1.pdf (included, so in the
        .fls kept with the build's pages) re-rendered makes it stale; and so does the .bib, which the .fls does not list."""
        res = ps.APP.build_requests.build_all(self.ms)
        self.assertIsInstance(res, BuildOk, getattr(res, "log", res))
        self.assertEqual(self.stale(), (False, False, False))
        rewrite_ahead(self.src / "figs" / "figures.pdf", minimal_pdf("fig v2"))
        self.assertFalse(self.facts()["stale_docs"], "figures.pdf is not read by the build")
        rewrite_ahead(self.src / "figs" / "panel1.pdf", minimal_pdf("panel v2"))
        self.assertEqual(self.stale(), (True, True, True), "panel1.pdf is read by the build")
        res = ps.APP.build_requests.build_all(self.ms)
        self.assertIsInstance(res, BuildOk, getattr(res, "log", res))
        self.assertEqual(self.stale(), (False, False, False), "a rebuild takes the re-rendered panel as its baseline")
        rewrite_ahead(self.src / "refs.bib", ahead=60.0)
        self.assertTrue(self.facts()["stale_docs"])

    @needs_tex("latexmk", "pdftoppm")
    def test_control_rebuild_without_any_figure_change_keeps_pins_solid(self):
        """Control for the next test: the same fixture, nothing re-rendered, so the pin stays solid (not an estimate)."""
        res = ps.APP.build_requests.build_all(self.ms)
        self.assertIsInstance(res, BuildOk, getattr(res, "log", res))
        pid = self.add()
        res2 = ps.APP.build_requests.build_all(self.ms, force=True)  # forced: an unforced one keeps build 1 (unchanged)
        self.assertIsInstance(res2, BuildOk)
        self.assertIs(self.est_of(pid), False)

    @needs_tex("latexmk", "pdftoppm")
    def test_rebuild_after_rerender_of_a_file_the_build_never_read_keeps_pins_solid(self):
        """Pin on build 1; re-render figures.pdf (not read); rebuild with the same .tex: the build's fingerprint does not
        include figures.pdf, so the pin is not an estimate."""
        res = ps.APP.build_requests.build_all(self.ms)
        self.assertIsInstance(res, BuildOk, getattr(res, "log", res))
        pid = self.add()
        rewrite_ahead(self.src / "figs" / "figures.pdf", minimal_pdf("fig v2"))
        self.assertIsInstance(ps.APP.build_requests.build_all(self.ms), BuildUnchanged)  # figures.pdf is not its source
        res2 = ps.APP.build_requests.build_all(self.ms, force=True)
        self.assertIsInstance(res2, BuildOk)
        self.assertIs(self.est_of(pid), False)

    @needs_tex("latexmk", "pdftoppm")
    def test_rebuild_after_rerender_of_a_file_the_build_read_makes_pins_estimates(self):
        """The reverse of the previous test: panel1.pdf is included, so its re-render changes what the build compiled and
        the pin placed before it is an estimate."""
        res = ps.APP.build_requests.build_all(self.ms)
        self.assertIsInstance(res, BuildOk, getattr(res, "log", res))
        pid = self.add()
        rewrite_ahead(self.src / "figs" / "panel1.pdf", minimal_pdf("panel v2"))
        res2 = ps.APP.build_requests.build_all(self.ms)
        self.assertIsInstance(res2, BuildOk)
        self.assertIs(self.est_of(pid), True)

    def est_of(self, pid: int) -> bool:
        """The est flag GET /api/pins?all=1 reports for pin pid."""
        rows = json.loads(self.talk(req("GET", "/api/pins?all=1")).split(b"\r\n\r\n", 1)[1])
        return {r["id"]: r["est"] for r in rows}[pid]


if __name__ == "__main__":
    unittest.main()

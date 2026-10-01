"""Startup document selection (limn.administration.serve_documents) as it depends on document kinds.

Which kind a --doc path names, and the two startup decisions made on a parsed --doc before any Doc exists - whether
a document keyed main keeps the state-folder root, and which document's main file is the run's - follow
limn.runtime.documents.kind_builds_from_source, never a kind name. Every suffix other than .tex and .pdf is refused at this
boundary (docs/handbook/code-style-roadmap.md §R10); src/limn/runtime/tests/test_startup.py DocArgs pins the full refusal list and
its messages.

Run: uv run pytest -q src/limn/administration/tests/test_serve_documents.py
"""

import tempfile
import unittest
from pathlib import Path

from limn.administration import serve_documents
from limn.administration.serve_documents import (
    DocExtendedWrongKind,
    DocFileMissing,
    DocKindUnknown,
    DocMainOutsideRoot,
    DocOutsideManuscript,
    RunDocuments,
)
from limn.runtime.documents import MAP_SUFFIX, NO_APART, RunPaths
from limn.runtime.startup import StartupRefused

TEX = "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
PDF = b"%PDF-1.4\n"


class StartupTree(unittest.TestCase):
    """A manuscript with a LaTeX body, a lower-case .pdf, an upper-case .PDF and an SVG, and a state folder beside it."""

    def setUp(self):
        """Temporary manuscript and state folders; the manuscript path is resolved as pick_documents expects."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.ms = root / "repo"
        (self.ms / "sub").mkdir(parents=True)
        (self.ms / "main.tex").write_text(TEX, encoding="utf-8")
        (self.ms / "sub" / "review.pdf").write_bytes(PDF)
        (self.ms / "sub" / "SCAN.PDF").write_bytes(PDF)
        (self.ms / "sub" / "figure.svg").write_text("<svg/>", encoding="utf-8")
        self.paths = RunPaths(self.ms, self.ms / "main.tex", root / "state")


class DocumentKindFromPath(StartupTree):
    """parse_doc_arg reads the kind from the path's suffix, case-insensitively, and refuses every other suffix."""

    def test_tex_and_pdf_suffixes_name_their_kinds_in_any_case(self):
        """main.tex is tex; review.pdf and SCAN.PDF are pdf - the suffix is compared lower-cased."""
        specs = ("ms=본문:main.tex", "rv=리뷰:sub/review.pdf", "sc=스캔:sub/SCAN.PDF")
        got = [serve_documents.parse_doc_arg(spec, self.ms) for spec in specs]
        self.assertEqual([d["kind"] for d in got], ["tex", "pdf", "pdf"])

    def test_an_svg_is_not_a_document_kind(self):
        """A vector graphic file on its own is refused with its resolved path; the server never serves SVG."""
        self.assertEqual(
            serve_documents.parse_doc_arg("fg=그림:sub/figure.svg", self.ms),
            DocKindUnknown("fg", self.ms / "sub" / "figure.svg"),
        )


class BuildsFromSourceAtStartup(StartupTree):
    """The two startup decisions on parsed --doc values ask whether the kind builds from source."""

    def test_a_view_only_document_keyed_main_does_not_take_the_state_root(self):
        """Only a document built from source keyed main inherits the single-document layout at the state-folder root;
        a view-only PDF keyed main keeps its own docs/main folder."""
        docs = serve_documents.make_docs(["main=리뷰:sub/review.pdf", "ms=본문:main.tex"], self.ms, self.paths)
        self.assertIsInstance(docs, list)
        self.assertEqual([(d.key, d.kind, d.root) for d in docs], [("main", "pdf", False), ("ms", "tex", False)])
        self.assertEqual(docs[0].dir, self.paths.state / "docs" / "main")

    def test_the_run_main_skips_view_only_documents_listed_first(self):
        """The run's main file is the first document that builds from source, even behind two view-only PDFs."""
        got = serve_documents.pick_documents(
            self.ms, ["rv=리뷰:sub/review.pdf", "sc=스캔:sub/SCAN.PDF", "ms=본문:main.tex"], None
        )
        self.assertIsInstance(got, RunDocuments)
        self.assertEqual(got.main, self.ms / "main.tex")


class SetApartAtStartup(StartupTree):
    """docs_of gives a LaTeX document what other documents inside its build root own (limn.runtime.documents.apart_paths),
    and no other kind anything (docs/handbook/build-sync.md §원고 변화 감지)."""

    def setUp(self):
        """Add a figure folder figs/ with its map, and reviewer.pdf in the manuscript root."""
        super().setUp()
        (self.ms / "figs").mkdir()
        (self.ms / "figs" / "figures.limnmap.json").write_text("{}", encoding="utf-8")
        (self.ms / "reviewer.pdf").write_bytes(PDF)
        self.specs = ["ms=본문:main.tex", "fig=그림:figs/figures.limnmap.json", "rv=리뷰:reviewer.pdf"]

    def test_the_latex_document_sets_the_figure_folder_and_the_reviewer_pdf_apart(self):
        """ms gets the folder figs and the file reviewer.pdf; the figure and the view-only document get nothing."""
        docs = serve_documents.make_docs(self.specs, self.ms, self.paths)
        self.assertIsInstance(docs, list)
        ms, fig, rv = docs
        self.assertEqual((ms.apart.folders, ms.apart.files), ((("figs",),), (("reviewer.pdf",),)))
        self.assertEqual((fig.apart, rv.apart), (NO_APART, NO_APART))

    def test_a_single_latex_document_sets_nothing_apart(self):
        """Without any other document the list is whole."""
        docs = serve_documents.make_docs(["ms=본문:main.tex"], self.ms, self.paths)
        self.assertEqual(docs[0].apart, NO_APART)

    def test_a_second_latex_document_is_not_set_apart_and_owns_only_what_is_inside_its_root(self):
        """ms sets the figure folder apart but not the LaTeX document rr/ beside it; rr's build root rr/ holds no other
        document, so it sets nothing apart."""
        (self.ms / "rr").mkdir()
        (self.ms / "rr" / "reply.tex").write_text(TEX, encoding="utf-8")
        docs = serve_documents.make_docs(
            ["ms=본문:main.tex", "rr=답변:rr/reply.tex", "fig=그림:figs/figures.limnmap.json"], self.ms, self.paths
        )
        self.assertIsInstance(docs, list)
        ms, rr, fig = docs
        self.assertEqual((ms.apart.folders, rr.apart, fig.apart), ((("figs",),), NO_APART, NO_APART))


class DocStartLine(unittest.TestCase):
    """doc_start_line is the stdout line server.prepare prints per --doc document, byte for byte as operators see it."""

    def test_a_latex_document_with_a_started_build_reads_latex(self):
        """tex prints 'LaTeX' and three spaces after the key padded to ten, then the path and the build note."""
        self.assertEqual(
            serve_documents.doc_start_line("ms", "tex", "main.tex", True),
            "doc    ms         LaTeX    main.tex  (build started)",
        )

    def test_a_view_only_document_without_a_build_reads_view_only(self):
        """pdf prints 'view-only'; a document whose startup build was skipped carries no note."""
        self.assertEqual(
            serve_documents.doc_start_line("rv", "pdf", "sub/review.pdf", False),
            "doc    rv         view-only sub/review.pdf",
        )


class FigureRegistration(unittest.TestCase):
    """A --doc path ending in documents.MAP_SUFFIX registers a figure document (docs/handbook/domain.md §여러 문서): its
    folder is the root before '::' or the map's folder, and every other suffix stays refused."""

    def setUp(self):
        """A manuscript with a body, a view-only PDF, a figure map under figs/out, a plain .json beside it, an
        upper-case map name in another folder, and a map outside the manuscript."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.ms = root / "repo"
        (self.ms / "figs" / "out").mkdir(parents=True)
        (self.ms / "figs" / "upper").mkdir()
        (self.ms / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
        (self.ms / "review.pdf").write_bytes(b"%PDF-1.4\n")
        self.map = self.ms / "figs" / "out" / "figures.limnmap.json"
        self.map.write_text("{}", encoding="utf-8")
        (self.ms / "figs" / "out" / "figures.json").write_text("{}", encoding="utf-8")
        (self.ms / "figs" / "upper" / "Figures.LIMNMAP.JSON").write_text("{}", encoding="utf-8")
        (root / "outside.limnmap.json").write_text("{}", encoding="utf-8")
        self.paths = RunPaths(self.ms, self.ms / "main.tex", root / "state")

    def test_a_map_path_is_a_figure_document_rooted_at_the_maps_folder(self):
        """Without '::' the document's folder - the base of the map's source paths - is the folder holding the map."""
        d = serve_documents.parse_doc_arg("fig=그림:figs/out/figures.limnmap.json", self.ms)
        self.assertEqual((d["kind"], d["src"], d["main"]), ("figure", self.ms / "figs" / "out", self.map))

    def test_the_root_form_roots_a_figure_document_at_the_folder_before_the_separator(self):
        """ROOT::REL/x.limnmap.json keeps the map as main and makes ROOT the document's folder."""
        d = serve_documents.parse_doc_arg("fig=그림:figs::out/figures.limnmap.json", self.ms)
        self.assertEqual((d["kind"], d["src"], d["main"]), ("figure", self.ms / "figs", self.map))

    def test_a_missing_map_refuses_startup_like_a_missing_file(self):
        """A map that does not exist is DocFileMissing, and the server refuses to start with the same words a missing
        view-only PDF gets."""
        missing = self.ms / "figs" / "out" / "none.limnmap.json"
        self.assertEqual(
            serve_documents.parse_doc_arg("fig=그림:figs/out/none.limnmap.json", self.ms),
            DocFileMissing("fig", missing),
        )
        self.assertEqual(
            serve_documents.pick_documents(self.ms, ["ms=본문:main.tex", "fig=그림:figs/out/none.limnmap.json"], None),
            StartupRefused("--doc fig: 파일이 없습니다: %s" % missing),
        )

    def test_only_the_exact_map_suffix_names_a_figure(self):
        """A plain .json and an upper-case suffix are unknown kinds, and the refusal lists every accepted suffix
        (docs/handbook/code-style-roadmap.md §R10)."""
        for rel in ("figs/out/figures.json", "figs/upper/Figures.LIMNMAP.JSON"):
            with self.subTest(rel=rel):
                got = serve_documents.parse_doc_arg("fig=그림:" + rel, self.ms)
                self.assertEqual(got, DocKindUnknown("fig", self.ms / rel))
                self.assertEqual(
                    serve_documents.doc_refusal_message(got),
                    "--doc fig: .tex(LaTeX), .pdf(보기 전용), .limnmap.json(그림)만 받습니다: %s" % (self.ms / rel),
                )

    def test_the_root_form_takes_latex_or_a_map_and_refuses_a_pdf(self):
        """'::' is for a document with a folder of its own: a LaTeX main or a figure map, never a view-only PDF."""
        got = serve_documents.parse_doc_arg("rv=코멘트:.::review.pdf", self.ms)
        self.assertEqual(got, DocExtendedWrongKind("rv", self.ms / "review.pdf"))
        self.assertEqual(
            serve_documents.doc_refusal_message(got),
            "--doc rv: '::' 표기는 LaTeX 문서(.tex)와 그림 지도(.limnmap.json)에만 씁니다: %s"
            % (self.ms / "review.pdf"),
        )

    def test_a_map_outside_the_manuscript_or_its_root_is_refused(self):
        """A map reached through ../ from the manuscript, or from the root of the '::' form, is refused before its
        existence is checked."""
        self.assertEqual(
            serve_documents.parse_doc_arg("fig=그림:../outside.limnmap.json", self.ms),
            DocOutsideManuscript("fig", "path", self.ms, self.ms.parent / "outside.limnmap.json"),
        )
        self.assertEqual(
            serve_documents.parse_doc_arg("fig=그림:figs::../main.limnmap.json", self.ms),
            DocMainOutsideRoot("fig", self.ms / "main.limnmap.json"),
        )

    def test_a_figure_document_is_watched_takes_line_pins_and_keeps_its_own_folder(self):
        """Keyed main, a figure document still gets docs/main (only a document built from source takes the state
        root); it is watched, takes line pins (so is not view-only), has an element map, and its PDF copy is named
        after the map."""
        docs = serve_documents.make_docs(
            ["main=그림:figs::out/figures.limnmap.json", "ms=본문:main.tex"], self.ms, self.paths
        )
        fig = docs[0]
        self.assertEqual(
            (fig.kind, fig.root, fig.dir, fig.pdf_name),
            ("figure", False, self.paths.state / "docs" / "main", "figures.pdf"),
        )
        self.assertEqual(
            (
                fig.builds_from_source,
                fig.watches_files,
                fig.takes_line_pins,
                fig.shows_revisions,
                fig.view_only,
                fig.has_element_map,
            ),
            (False, True, True, False, False, True),
        )

    def test_the_run_main_is_never_a_figure_map(self):
        """The run's main file is the first document built from source, even behind a figure document."""
        got = serve_documents.pick_documents(
            self.ms, ["fig=그림:figs/out/figures.limnmap.json", "ms=본문:main.tex"], None
        )
        self.assertIsInstance(got, RunDocuments)
        self.assertEqual(got.main, self.ms / "main.tex")

    def test_the_startup_line_names_a_figure(self):
        """A figure document's startup line reads 'figure' in the label column, aligned with 'view-only'."""
        self.assertEqual(
            serve_documents.doc_start_line("fig", "figure", "figs/out/figures.limnmap.json", False),
            "doc    fig        figure    figs/out/figures.limnmap.json",
        )

    def test_the_shell_mirror_accepts_the_same_suffix(self):
        """instance_documents.sh names the Python suffix in both of its case patterns, so limn add and the server agree."""
        sh = (Path(serve_documents.__file__).parent / "instance_documents.sh").read_text(encoding="utf-8")
        self.assertEqual(sh.count("*" + MAP_SUFFIX), 2)

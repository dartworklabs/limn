"""Startup document selection (limn.features.administration.serve_documents) as it depends on document kinds.

Which kind a --doc path names, and the two startup decisions made on a parsed --doc before any Doc exists - whether
a document keyed main keeps the state-folder root, and which document's main file is the run's - follow
limn.documents.kind_builds_from_source, never a kind name. Every suffix other than .tex and .pdf is refused at this
boundary (docs/handbook/code-style-roadmap.md §R10); tests/test_startup.py DocArgs pins the full refusal list and
its messages.

Run: uv run pytest -q src/limn/features/administration/test_serve_documents.py
"""

import tempfile
import unittest
from pathlib import Path

from limn.documents import RunPaths
from limn.features.administration import serve_documents
from limn.features.administration.serve_documents import DocKindUnknown, RunDocuments

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

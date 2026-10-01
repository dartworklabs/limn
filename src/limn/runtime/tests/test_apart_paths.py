"""limn.runtime.documents.apart_paths and ApartPaths: what a LaTeX document leaves out of its source list because
another document owns it (docs/handbook/build-sync.md §원고 변화 감지, domain.md §여러 문서).

The rule is a pure function of the documents' paths. A figure folder strictly inside the build root is set apart as a
folder (its figure-set files), a view-only PDF strictly inside it as that one file; nothing else is - not the PDF's folder,
not a LaTeX document's folder, not a folder equal to or holding the build root, not one that holds the document's own main
file. Symlinks are resolved on both sides. The tests build a real tree, because the rule resolves paths.

Run: uv run pytest -q src/limn/runtime/tests/test_apart_paths.py
"""

import tempfile
import unittest
from pathlib import Path

from limn.runtime.documents import NO_APART, ApartPaths, _parts_below, apart_paths


class Tree(unittest.TestCase):
    """A resolved manuscript folder ms/ with a paper folder, a figure folder, a nested one and a reviewer PDF."""

    def setUp(self):
        """Make the folders and files; self.ms is the resolved manuscript root and self.main its main .tex."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.top = Path(tmp.name).resolve()
        self.ms = self.top / "ms"
        for sub in ("figs", "figs/render", "paper", "other/figs"):
            (self.ms / sub).mkdir(parents=True)
        self.main = self.ms / "main.tex"
        self.main.write_text("\\relax\n", encoding="utf-8")
        (self.ms / "reviewer.pdf").write_bytes(b"%PDF-1.4\n")
        (self.ms / "figs" / "figures.limnmap.json").write_text("{}", encoding="utf-8")
        (self.ms / "figs" / "render" / "more.limnmap.json").write_text("{}", encoding="utf-8")
        (self.ms / "paper" / "main.tex").write_text("\\relax\n", encoding="utf-8")

    def apart(self, *others, src: Path | None = None, main: Path | None = None) -> ApartPaths:
        """apart_paths of the LaTeX document (default: build root ms/, main ms/main.tex) among `others`, each a
        (kind, src, main) tuple."""
        return apart_paths(src or self.ms, main or self.main, others)


class FigureFolders(Tree):
    """A figure document's folder is set apart when it lies strictly inside the build root."""

    def test_a_folder_strictly_inside_the_root_is_set_apart(self):
        """figs/ is a folder of ms/: its parts below the root are the folder."""
        got = self.apart(("figure", self.ms / "figs", self.ms / "figs" / "figures.limnmap.json"))
        self.assertEqual(got, ApartPaths(folders=(("figs",),)))

    def test_nested_figure_folders_are_each_set_apart(self):
        """figs/ and figs/render/ are two figure documents: both are listed, in the order given."""
        got = self.apart(
            ("figure", self.ms / "figs", self.ms / "figs" / "figures.limnmap.json"),
            ("figure", self.ms / "figs" / "render", self.ms / "figs" / "render" / "more.limnmap.json"),
        )
        self.assertEqual(got.folders, (("figs",), ("figs", "render")))
        self.assertTrue(got.covers(("figs", "render", "x.pdf")))

    def test_a_folder_equal_to_the_root_sets_nothing_apart(self):
        """A figure document whose folder is the build root itself would leave out every file of the tree."""
        got = self.apart(("figure", self.ms, self.ms / "figs" / "figures.limnmap.json"))
        self.assertEqual(got, NO_APART)

    def test_a_folder_holding_the_root_sets_nothing_apart(self):
        """A figure folder above the build root (the paper is inside it) sets nothing apart."""
        got = self.apart(
            ("figure", self.ms, self.ms / "figs" / "figures.limnmap.json"),
            src=self.ms / "paper",
            main=self.ms / "paper" / "main.tex",
        )
        self.assertEqual(got, NO_APART)

    def test_a_folder_that_holds_the_documents_own_main_file_sets_nothing_apart(self):
        """Root ms/, main ms/paper/main.tex, figure folder ms/paper/: one folder shared by both is not the figure's alone."""
        got = self.apart(
            ("figure", self.ms / "paper", self.ms / "paper" / "figures.limnmap.json"),
            main=self.ms / "paper" / "main.tex",
        )
        self.assertEqual(got, NO_APART)

    def test_a_folder_beside_the_root_or_outside_it_sets_nothing_apart(self):
        """The paper's build root is paper/; figs/ is beside it, outside its tree."""
        got = self.apart(
            ("figure", self.ms / "figs", self.ms / "figs" / "figures.limnmap.json"),
            src=self.ms / "paper",
            main=self.ms / "paper" / "main.tex",
        )
        self.assertEqual(got, NO_APART)

    def test_a_figure_folder_below_a_sibling_name_prefix_is_not_confused_with_it(self):
        """Root ms/paper/ against a figure folder ms/paper-figs/: a shared name prefix is not containment."""
        sibling = self.ms / "paper-figs"
        sibling.mkdir()
        got = self.apart(
            ("figure", sibling, sibling / "figures.limnmap.json"),
            src=self.ms / "paper",
            main=self.ms / "paper" / "main.tex",
        )
        self.assertEqual(got, NO_APART)


class ViewOnlyPdfs(Tree):
    """A view-only PDF is set apart as the one file, never as its folder."""

    def test_the_file_inside_the_root_is_set_apart_and_not_its_folder(self):
        """reviewer.pdf in the root: the file's parts are listed, no folder, and a neighbour file is not covered."""
        got = self.apart(("pdf", self.ms, self.ms / "reviewer.pdf"))
        self.assertEqual(got, ApartPaths(files=(("reviewer.pdf",),)))
        self.assertTrue(got.covers(("reviewer.pdf",)))
        self.assertFalse(got.covers(("main.tex",)))
        self.assertFalse(got.covers(("appendix.pdf",)))

    def test_a_pdf_in_a_subfolder_is_set_apart_by_its_path(self):
        """paper/rev.pdf: only that path, not other files of paper/."""
        (self.ms / "paper" / "rev.pdf").write_bytes(b"%PDF-1.4\n")
        got = self.apart(("pdf", self.ms / "paper", self.ms / "paper" / "rev.pdf"))
        self.assertEqual(got.files, (("paper", "rev.pdf"),))
        self.assertFalse(got.covers(("paper", "other.pdf")))

    def test_a_pdf_outside_the_root_sets_nothing_apart(self):
        """The reviewer PDF is in ms/, the paper's build root is ms/paper/: it is not a file of that tree."""
        got = self.apart(
            ("pdf", self.ms, self.ms / "reviewer.pdf"), src=self.ms / "paper", main=self.ms / "paper" / "main.tex"
        )
        self.assertEqual(got, NO_APART)


class OtherLatexDocuments(Tree):
    """Another LaTeX document's folder is not set apart (the rule is for figure documents and view-only PDFs)."""

    def test_a_nested_latex_document_sets_nothing_apart(self):
        """paper/ is a LaTeX document of its own: its figures are still counted by ms/ (out of this rule's scope)."""
        got = self.apart(("tex", self.ms / "paper", self.ms / "paper" / "main.tex"))
        self.assertEqual(got, NO_APART)

    def test_no_other_document_sets_nothing_apart(self):
        """An instance with one document has nothing set apart."""
        self.assertEqual(self.apart(), NO_APART)


class Symlinks(Tree):
    """Both sides are compared with symlinks resolved."""

    def test_a_root_reached_through_a_symlink_still_finds_the_resolved_figure_folder(self):
        """The build root is given as a link to ms/, the figure document by its resolved path: figs/ is inside."""
        link = self.top / "link"
        link.symlink_to(self.ms)
        got = apart_paths(
            link, link / "main.tex", [("figure", self.ms / "figs", self.ms / "figs" / "figures.limnmap.json")]
        )
        self.assertEqual(got.folders, (("figs",),))

    def test_a_figure_folder_that_resolves_outside_the_root_sets_nothing_apart(self):
        """ms/linked-figs is a symlink to a folder beside ms/: the figure document's folder, resolved, is outside the
        root. (The manuscript scan does not follow a linked folder either, so there is nothing to set apart.)"""
        elsewhere = self.top / "elsewhere"
        elsewhere.mkdir()
        (self.ms / "linked-figs").symlink_to(elsewhere)
        got = self.apart(("figure", self.ms / "linked-figs", self.ms / "linked-figs" / "x.limnmap.json"))
        self.assertEqual(got, NO_APART)

    def test_a_reviewer_pdf_that_is_a_link_to_a_file_outside_the_root_sets_nothing_apart(self):
        """The link resolves outside the tree, so it is not a file of it."""
        outside = self.top / "outside.pdf"
        outside.write_bytes(b"%PDF-1.4\n")
        (self.ms / "rev-link.pdf").symlink_to(outside)
        got = self.apart(("pdf", self.ms, self.ms / "rev-link.pdf"))
        self.assertEqual(got, NO_APART)


class PartsBelow(Tree):
    """_parts_below names a path by its parts below the root, and nothing for the root itself."""

    def test_the_root_itself_and_a_path_outside_it_have_no_parts(self):
        """An empty tuple of parts would be a folder that covers every file of the tree, so the root itself is None, like a
        path beside it or above it."""
        self.assertIsNone(_parts_below(self.ms, self.ms))
        self.assertIsNone(_parts_below(self.ms, self.top))
        self.assertIsNone(_parts_below(self.ms / "paper", self.ms / "figs"))
        self.assertEqual(_parts_below(self.ms, self.ms / "figs" / "render"), ("figs", "render"))


class Covers(unittest.TestCase):
    """ApartPaths.covers compares whole path parts."""

    def test_a_folder_covers_what_is_below_it_and_not_itself_or_a_name_with_its_prefix(self):
        """folder ("figs",): figs/a.pdf and figs/x/y.pdf are covered; figs (the folder), figs2/a.pdf and a/figs/a.pdf are not."""
        apart = ApartPaths(folders=(("figs",),))
        self.assertTrue(apart.covers(("figs", "a.pdf")))
        self.assertTrue(apart.covers(("figs", "x", "y.pdf")))
        self.assertFalse(apart.covers(("figs",)))
        self.assertFalse(apart.covers(("figs2", "a.pdf")))
        self.assertFalse(apart.covers(("a", "figs", "a.pdf")))

    def test_a_file_covers_only_itself(self):
        """file ("a", "r.pdf"): that path only, not the same name elsewhere or a longer path."""
        apart = ApartPaths(files=(("a", "r.pdf"),))
        self.assertTrue(apart.covers(("a", "r.pdf")))
        self.assertFalse(apart.covers(("r.pdf",)))
        self.assertFalse(apart.covers(("b", "r.pdf")))
        self.assertFalse(apart.covers(("a", "r.pdf", "x")))

    def test_the_empty_value_is_empty_and_covers_nothing(self):
        """NO_APART: empty, and no path is covered."""
        self.assertTrue(NO_APART.empty)
        self.assertFalse(NO_APART.covers(("figs", "a.pdf")))
        self.assertFalse(ApartPaths(folders=(("figs",),)).empty)
        self.assertFalse(ApartPaths(files=(("r.pdf",),)).empty)


if __name__ == "__main__":
    unittest.main()

"""limn.outline - the pure parser of the outline labels a LaTeX build writes to its .aux.

Reading the .aux of the build on screen (which file, symlinks, size cap) is limn.meta.outline_labels, tested in
test_meta.py and through the server in test_server.py. Here the parser is called directly on text: it stays pure
(no file, process, clock or HTTP import), and each rule of the display conversion and the row extraction holds.

Run: uv run pytest -q tests/test_outline.py
"""
import ast
import unittest
from pathlib import Path

from limn import outline
from limn.outline import tex_group, tex_plain, toc_labels

OUTLINE_PY = Path(outline.__file__)
PURE_IMPORTS = {"__future__", "re", "typing"}


def toc(level: str, body: str, page: str = "1", anchor: str | None = "a.1") -> str:
    """One .aux line as LaTeX writes it for a table-of-contents entry (anchor None: the 3-argument form without
    hyperref)."""
    tail = "" if anchor is None else "{%s}" % anchor
    return "\\@writefile{toc}{\\contentsline {%s}{%s}{%s}%s}\n" % (level, body, page, tail)


class Purity(unittest.TestCase):
    """The parser is a decision over text; reading the file is the caller's (R1)."""

    def test_imports_only_pure_standard_modules(self):
        """A file, process, clock or HTTP import would put an effect inside the parser."""
        tree = ast.parse(OUTLINE_PY.read_text(encoding="utf-8"))
        modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        modules |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertLessEqual(modules, PURE_IMPORTS)


class TexGroup(unittest.TestCase):
    """tex_group finds one balanced brace group."""

    def test_returns_content_and_end_after_leading_space(self):
        """Whitespace before the brace is skipped; the end index is just past the closing brace."""
        self.assertEqual(tex_group("  {a{b}c}rest", 0), ("a{b}c", 9))

    def test_escaped_braces_do_not_count(self):
        """\\{ and \\} inside a group are text, not nesting."""
        self.assertEqual(tex_group(r"{a\}b}x", 0), (r"a\}b", 6))

    def test_none_without_an_opening_brace_or_when_unclosed(self):
        """No group starts at pos, or it never closes: None."""
        self.assertIsNone(tex_group("x{a}", 0))
        self.assertIsNone(tex_group("{a{b}", 0))
        self.assertIsNone(tex_group("   ", 0))


class TexPlain(unittest.TestCase):
    """tex_plain converts a title for display, or refuses with ValueError."""

    def test_text_macros_are_unwrapped_and_specials_kept(self):
        """Wrappers keep their content; escaped specials keep the character; groups flatten."""
        self.assertEqual(tex_plain(r"A \textbf{nested {title}} \& B \emph{x}\_y"), "A nested title & B x_y")

    def test_texorpdfstring_takes_the_pdf_side(self):
        """The first argument (TeX) is dropped, the second (PDF string) shown."""
        self.assertEqual(tex_plain(r"Use \texorpdfstring{$x^2$}{x squared}"), "Use x squared")

    def test_spacing_ties_and_dashes(self):
        """Spacing macros and ~ become spaces, whitespace collapses, --- and -- become dashes."""
        self.assertEqual(tex_plain(r"a\quad b~c \,d  e---f--g"), "a b c d e—f–g")

    def test_ignored_macros_vanish(self):
        """\\protect, \\relax and \\ignorespaces leave nothing."""
        self.assertEqual(tex_plain(r"\protect\relax Title\ignorespaces"), "Title")

    def test_refuses_what_it_cannot_display(self):
        """Math, an unknown macro, a stray brace, a wrapper without its group, over-deep or over-long text."""
        for text in ("$x$", r"\alpha", "a}", r"\textbf", r"\texorpdfstring{a}", "{" * 14 + "}" * 14, "x" * 4001):
            with self.subTest(text=text[:20]), self.assertRaises(ValueError):
                tex_plain(text)


class TocLabels(unittest.TestCase):
    """toc_labels extracts one row per sectioning entry, in file order."""

    def test_numbered_and_unnumbered_entries(self):
        """\\numberline gives the number; without it the number is empty. The anchor is the fourth argument."""
        aux = toc("section", r"\numberline {2}Intro", "iv", "section.2") + toc("section", "Preface", "i", "section*.1")
        self.assertEqual(toc_labels(aux), [
            {"number": "2", "title": "Intro", "page": "iv", "level": "section", "anchor": "section.2"},
            {"number": "", "title": "Preface", "page": "i", "level": "section", "anchor": "section*.1"},
        ])

    def test_protected_numberline_and_three_argument_form(self):
        """\\protect\\numberline counts as a number; without hyperref there is no anchor."""
        self.assertEqual(toc_labels(toc("subsection", r"\protect \numberline {1.1}Next", "3", None)),
                         [{"number": "1.1", "title": "Next", "page": "3", "level": "subsection", "anchor": ""}])

    def test_other_lists_levels_and_malformed_lines_are_skipped(self):
        """A list of figures, a non-sectioning level, a line without \\contentsline, too few groups, and a
        \\numberline without its group give no row."""
        aux = ("\\@writefile{lof}{\\contentsline {figure}{\\numberline {1}F}{2}{figure.1}}\n"
               + toc("figure", r"\numberline {1}F")
               + "\\@writefile{toc}{\\relax }\n"
               + "\\@writefile{toc}{\\contentsline {section}{Only two}}\n"
               + toc("section", r"\numberline Bad")
               + "\\@writefile{toc}{unclosed\n")
        self.assertEqual(toc_labels(aux), [])

    def test_unconvertible_title_keeps_a_placeholder_row(self):
        """The row stays (so later rows keep their positions) with no number or title and the raw page cut to 40."""
        page = "p" * 50
        rows = toc_labels(toc("section", r"\numberline {3}$E=mc^2$", page, "s.3") + toc("section", r"\numberline {4}Next"))
        self.assertEqual(rows[0], {"number": "", "title": "", "page": "p" * 40, "level": "section", "anchor": "s.3"})
        self.assertEqual(rows[1]["number"], "4")

    def test_anchor_is_cut_and_rows_are_capped(self):
        """An anchor keeps 200 characters; at most 200 rows are read."""
        self.assertEqual(len(toc_labels(toc("section", "T", "1", "x" * 300))[0]["anchor"]), 200)
        self.assertEqual(len(toc_labels(toc("section", "T") * 250)), 200)

    def test_empty_source_has_no_rows(self):
        """Nothing written, nothing shown."""
        self.assertEqual(toc_labels(""), [])


if __name__ == "__main__":
    unittest.main()

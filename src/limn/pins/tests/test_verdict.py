"""limn.pins.verdict: which stored value is a pin's verdict, and which pins are about a whole page's target.

A stored verdict is read back only when it is a key-shaped string; anything else stays as stored and the pin has no
verdict. A whole-page target is a figure pin whose element is its page's figure (el.path == [el.id]) on a figure
document, or a region pin over the whole page (each frac value within 1e-6 of [0, 0, 1, 1]) on a view-only PDF -
never a LaTeX pin (docs/superpowers/specs/2026-10-26-verdict-pins.md §핀 레코드).

Run: uv run pytest -q src/limn/pins/tests/test_verdict.py
"""

import unittest

from hypothesis import given, strategies as st

from limn.pins.verdict import PAGE_EPSILON, verdict_of, whole_figure, whole_page_target

FIGURE_ROOT = {"file": "/ms/figs/src/B2.py", "lo": 12, "hi": 140, "page": 1, "el": {"id": "B2", "path": ["B2"]}}
FIGURE_PANEL = {**FIGURE_ROOT, "el": {"id": "B2/calendar", "path": ["B2", "B2/calendar"]}}
PDF_PAGE = {"pdf": "/ms/review.pdf", "name": "review.pdf", "kind": "region", "page": 3, "frac": [0, 0, 1, 1]}
LINE = {"file": "/ms/main.tex", "lo": 4, "hi": 5, "page": 1, "frac": [0, 0, 1, 1]}


class StoredVerdict(unittest.TestCase):
    """verdict_of on stored values."""

    def test_a_key_shaped_string_is_the_verdict(self):
        """Letters of any script, digits, '-' and '_' up to 16 characters come back as stored."""
        for v in ("채택", "accept-now", "keep_2", "x" * 16):
            with self.subTest(v=v):
                self.assertEqual(verdict_of({"verdict": v}), v)

    def test_anything_else_is_no_verdict(self):
        """No field, null, a number, a list, an empty, too long or '|'-holding string are not verdicts."""
        self.assertIsNone(verdict_of({}))
        for v in (None, 7, True, ["채택"], {"key": "채택"}, "", "x" * 17, "a|b", "a\nb", "a b"):
            with self.subTest(v=v):
                self.assertIsNone(verdict_of({"verdict": v}))

    @given(st.text(max_size=20))
    def test_a_promoted_verdict_never_breaks_a_pins_md_cell(self, v):
        """Whatever string is stored, a promoted verdict has no '|', line break or space, and is 1-16 characters."""
        got = verdict_of({"verdict": v})
        if got is not None:
            self.assertTrue(1 <= len(got) <= 16)
            self.assertFalse({"|", "\n", "\r", " "} & set(got))


class WholePage(unittest.TestCase):
    """whole_figure and whole_page_target by document kind."""

    def test_a_figure_pin_on_its_pages_figure_is_a_whole_page_target(self):
        """el.path == [el.id] names the figure itself; a panel does not, nor a pin without a well-formed el."""
        self.assertEqual(whole_figure(FIGURE_ROOT), "B2")
        self.assertIsNone(whole_figure(FIGURE_PANEL))
        self.assertIsNone(whole_figure({**FIGURE_ROOT, "el": {"id": "B2", "path": []}}))
        self.assertIsNone(whole_figure({**FIGURE_ROOT, "el": "B2"}))
        self.assertTrue(whole_page_target(FIGURE_ROOT, True, False))
        self.assertFalse(whole_page_target(FIGURE_PANEL, True, False))

    def test_a_view_only_region_over_the_whole_page_is_a_whole_page_target(self):
        """[0, 0, 1, 1] within 1e-6 per value is the page; further off, or a smaller box, is a region."""
        near = [PAGE_EPSILON / 2, 0, 1 - PAGE_EPSILON / 2, 1 + PAGE_EPSILON / 2]
        self.assertTrue(whole_page_target(PDF_PAGE, False, True))
        self.assertTrue(whole_page_target({**PDF_PAGE, "frac": near}, False, True))
        for frac in ([PAGE_EPSILON * 2, 0, 1, 1], [0, 0, 1, 0.5], [0, 0, 1], [0, 0, 1, "1"], [0, 0, True, 1]):
            with self.subTest(frac=frac):
                self.assertFalse(whole_page_target({**PDF_PAGE, "frac": frac}, False, True))

    def test_a_latex_pin_or_a_pin_of_an_unknown_document_never_is(self):
        """A LaTeX document's pin, even with a whole-page frac, and a pin whose document is not served."""
        self.assertFalse(whole_page_target(LINE, False, False))
        self.assertFalse(whole_page_target(FIGURE_ROOT, False, False))
        self.assertFalse(whole_page_target(PDF_PAGE, False, False))

    def test_the_document_kind_decides_which_rule_applies(self):
        """A whole-page region on a figure document is not a figure target; a root el on a view-only PDF is not
        its page."""
        self.assertFalse(whole_page_target(PDF_PAGE, True, False))
        self.assertFalse(whole_page_target({**FIGURE_ROOT, "frac": [0.1, 0.1, 0.2, 0.2]}, False, True))

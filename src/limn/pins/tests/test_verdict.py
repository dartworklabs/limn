"""limn.pins.verdict: which stored value is a pin's verdict, and which pins are about a whole page's target.

A stored verdict is read back only when it is a key-shaped string; anything else stays as stored and the pin has no
verdict. A whole-page target is a figure pin whose element is its page's figure (el.path == [el.id]) on a figure
document, or a region pin over the whole page (each frac value within 1e-6 of [0, 0, 1, 1]) on a view-only PDF -
never a LaTeX pin (docs/superpowers/specs/2026-10-26-verdict-pins.md §핀 레코드).

superseded_by (ADR-0023) orders the live verdict pins of one target - a figure (el.path[0], mixed element and root
verdicts alike, ADR-0022 D1), a view-only PDF page, the same lines of a LaTeX file - and names, for each pin that a newer
one overtakes, the target's current verdict: the newest pin, whoever made it and in whatever state, the pin in the Trash
excepted because it is not among the live pins.

Run: uv run pytest -q src/limn/pins/tests/test_verdict.py
"""

import unittest

from hypothesis import given, strategies as st

from limn.pins.model import parse_pin
from limn.pins.verdict import (
    PAGE_EPSILON,
    Placement,
    figure_root,
    order_target,
    same_lines,
    superseded_by,
    verdict_of,
    whole_figure,
    whole_page_target,
)

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


ANCHOR = {"head": "Intro text.", "tail": "More text.", "head_off": 0, "tail_off": 0}
FIG_DOC = Placement("fig", "figure")
RV_DOC = Placement("rv", "pdf")


def pin(pid, record, **state):
    """The stored pin pid made of record: open unless state says done and review."""
    return parse_pin({"id": pid, "verdict": "채택", **record, **state})


def figure(pid, path=("B2",), **state):
    """A figure document's verdict pin on the element at the end of path."""
    el = {"id": path[-1], "path": list(path)}
    return pin(pid, {"file": "/ms/figs/B2.py", "lo": 12, "hi": 140, "page": 1, "el": el, "doc": "fig"}, **state)


def latex(pid, lo=4, hi=5, anchor=ANCHOR, **state):
    """A LaTeX document's verdict pin on lines lo..hi of main.tex, with its anchor."""
    record = {"file": "/ms/main.tex", "lo": lo, "hi": hi, "page": 1, "doc": "ms"}
    if anchor is not None:
        record["anchor"] = anchor
    return pin(pid, record, **state)


def pdf_page(pid, page=3, frac=(0, 0, 1, 1), **state):
    """A view-only PDF's verdict pin over frac of page."""
    return pin(
        pid,
        {"pdf": "/ms/review.pdf", "name": "review.pdf", "kind": "region", "page": page, "frac": list(frac)},
        **state,
    )


def placed(pins, where=None):
    """superseded_by over pins, each placed by where (pin id -> Placement) or by the LaTeX document ms."""
    where = where or {}
    return superseded_by(pins, lambda p: where.get(p.core.pid, Placement("ms", "tex", file="/ms/main.tex")))


DONE = {"done": True}
REVIEW = {"done": True, "review": True}


class Supersession(unittest.TestCase):
    """superseded_by on figure targets: the current verdict is the newest live pin of the figure."""

    def figures(self, *pins):
        """The supersession of pins, all on the figure document fig."""
        return superseded_by(list(pins), lambda p: FIG_DOC)

    def test_a_newer_verdict_supersedes_an_older_one_and_names_the_current_one(self):
        """With three verdicts on a figure, the older two both name the newest, not the next newer one."""
        got = self.figures(figure(1), figure(2), figure(3))
        self.assertEqual(got, {1: 3, 2: 3})

    def test_the_order_is_the_number_not_the_listing_order(self):
        """Pins handed in any order give the same answer: the largest number is current."""
        self.assertEqual(self.figures(figure(3), figure(1), figure(2)), {1: 3, 2: 3})

    def test_state_does_not_matter_and_a_closed_newer_verdict_supersedes(self):
        """A verdict awaiting review or done is still the target's current verdict (ADR-0021 D4): an open older one
        is superseded by it. An open newer one supersedes a closed older one just the same."""
        self.assertEqual(self.figures(figure(1), figure(2, **REVIEW)), {1: 2})
        self.assertEqual(self.figures(figure(1), figure(2, **DONE)), {1: 2})
        self.assertEqual(self.figures(figure(1, **DONE), figure(2)), {1: 2})

    def test_a_verdict_on_the_figure_and_one_on_a_panel_of_it_are_one_target(self):
        """ADR-0022 D1: the target is el.path[0], whatever element of the figure the pin names."""
        root, panel, leaf = figure(1), figure(2, ("B2", "B2/calendar")), figure(3, ("B2", "B2/calendar", "B2/mark"))
        self.assertEqual(self.figures(root, panel), {1: 2})
        self.assertEqual(self.figures(panel, root), {1: 2})
        self.assertEqual(self.figures(root, panel, leaf), {1: 3, 2: 3})

    def test_another_figure_is_another_target(self):
        """Verdicts on B2 and on B3 do not meet, nor do the same root id on two documents."""
        self.assertEqual(self.figures(figure(1), figure(2, ("B3",))), {})
        both = superseded_by(
            [figure(1), figure(2)],
            lambda p: Placement("fig", "figure") if p.core.pid == 1 else Placement("fig2", "figure"),
        )
        self.assertEqual(both, {})

    def test_whoever_made_the_newer_verdict_it_supersedes(self):
        """The author is not part of the order: Bob's newer verdict overtakes Alice's, and the other way round."""
        alice = {"author": {"login": "alice@example.com", "name": "Alice"}}
        bob = {"author": {"login": "bob@example.com", "name": "Bob"}}
        self.assertEqual(self.figures(figure(1, **alice), figure(2, **bob)), {1: 2})
        self.assertEqual(self.figures(figure(1, **bob), figure(2, **alice)), {1: 2})

    def test_a_pin_without_a_verdict_or_a_target_is_left_out(self):
        """An ordinary pin, a stored value that is no key, and a figure pin with no element path neither supersede
        nor are superseded."""
        plain = parse_pin(
            {"id": 2, "file": "/ms/figs/B2.py", "lo": 1, "hi": 2, "page": 1, "el": {"id": "B2", "path": ["B2"]}}
        )
        no_key = pin(3, {"el": {"id": "B2", "path": ["B2"]}, "verdict": 7})
        no_el = pin(4, {"file": "/ms/figs/B2.py", "lo": 1, "hi": 2, "page": 1})
        empty = pin(5, {"file": "/ms/figs/B2.py", "lo": 1, "hi": 2, "page": 1, "el": {"id": "B2", "path": []}})
        self.assertEqual(self.figures(figure(1), plain, no_key, no_el, empty), {})

    def test_the_figure_root_is_the_first_id_of_the_path(self):
        """figure_root reads el.path[0] and nothing from a missing, empty or malformed el."""
        self.assertEqual(figure_root({"el": {"id": "B2/x", "path": ["B2", "B2/x"]}}), "B2")
        for record in (
            {},
            {"el": None},
            {"el": {"id": "B2", "path": []}},
            {"el": {"id": "B2", "path": [""]}},
            {"el": 3},
        ):
            with self.subTest(record=record):
                self.assertIsNone(figure_root(record))

    def test_a_pin_left_out_of_the_live_pins_supersedes_nothing(self):
        """The Trash is not among the live pins: with the newest verdict deleted, the one before it is current again;
        restored, it overtakes it again."""
        three = [figure(1), figure(2), figure(3)]
        self.assertEqual(self.figures(*three), {1: 3, 2: 3})
        self.assertEqual(self.figures(*three[:2]), {1: 2})
        self.assertEqual(self.figures(*three[:1], three[2]), {1: 3})
        self.assertEqual(self.figures(*three), {1: 3, 2: 3})

    def test_only_verdict_pins_are_placed(self):
        """placement_of is asked for verdict pins only, so a pin list without one reads nothing."""
        asked = []
        pins = [parse_pin({"id": 1, "file": "/ms/main.tex", "lo": 1, "hi": 1, "page": 1}), figure(2)]
        superseded_by(pins, lambda p: asked.append(p.core.pid) or FIG_DOC)
        self.assertEqual(asked, [2])

    def test_a_document_the_instance_does_not_serve_has_no_target(self):
        """placement_of answers None for such a pin: it is left out, and nothing is superseded by it."""
        pins = [figure(1), figure(2)]
        self.assertEqual(superseded_by(pins, lambda p: None if p.core.pid == 2 else FIG_DOC), {})

    @given(st.lists(st.integers(min_value=1, max_value=5), min_size=1, max_size=12, unique=True))
    def test_every_verdict_but_the_newest_of_a_figure_names_the_newest(self, ids):
        """For any ids, the pins of one figure that are not the largest each name the largest, and it names none."""
        got = self.figures(*(figure(i, ("B2",) if i % 2 else ("B2", "B2/x")) for i in ids))
        newest = max(ids)
        self.assertEqual(got, {i: newest for i in ids if i != newest})


class ViewOnlyPage(unittest.TestCase):
    """superseded_by on a view-only PDF: the target is the whole page, and only a mark that is not an estimate."""

    def pages(self, *pins, estimated=()):
        """The supersession of pins on the view-only document rv; the ids in estimated have an estimated mark."""
        return superseded_by(list(pins), lambda p: Placement("rv", "pdf", estimated=p.core.pid in estimated))

    def test_a_newer_verdict_on_the_same_page_supersedes(self):
        """The same page supersedes; another page does not."""
        self.assertEqual(self.pages(pdf_page(1), pdf_page(2)), {1: 2})
        self.assertEqual(self.pages(pdf_page(1), pdf_page(2, page=4)), {})

    def test_a_region_smaller_than_the_page_is_no_target(self):
        """A verdict over part of a page has no target, so it neither supersedes nor is superseded."""
        self.assertEqual(self.pages(pdf_page(1), pdf_page(2, frac=(0, 0, 1, 0.5))), {})

    def test_a_mark_that_is_only_an_estimate_is_no_target(self):
        """A pin whose mark is only an estimate on the PDF on screen (est) is left out, as the viewer leaves it out."""
        self.assertEqual(self.pages(pdf_page(1), pdf_page(2), estimated={1}), {})
        self.assertEqual(self.pages(pdf_page(1), pdf_page(2), estimated={2}), {})
        self.assertEqual(self.pages(pdf_page(1), pdf_page(2), pdf_page(3), estimated={2}), {1: 3})


class LinesOfLatex(unittest.TestCase):
    """superseded_by on a LaTeX document: exactly the same lines of the same file, and the same text."""

    def test_two_open_verdicts_on_the_same_lines_supersede(self):
        """Open pins' lines are matched to the text now, so the newer open one supersedes the older open one."""
        self.assertEqual(placed([latex(1), latex(2, anchor=None)]), {1: 2})

    def test_a_closed_older_verdict_needs_the_same_text(self):
        """A closed pin's numbers may be from an older text: it is superseded by a newer pin only when both carry one
        anchor, and a newer open pin with another anchor leaves it current."""
        older = {"head": "Old text.", "tail": "More text.", "head_off": 0, "tail_off": 0}
        self.assertEqual(placed([latex(1, **REVIEW), latex(2)]), {1: 2})
        self.assertEqual(placed([latex(1, anchor=older, **DONE), latex(2)]), {})
        self.assertEqual(placed([latex(1, anchor=None, **DONE), latex(2)]), {})
        self.assertEqual(placed([latex(1, **DONE), latex(2, **DONE)]), {1: 2})
        self.assertEqual(placed([latex(1, anchor=older, **DONE), latex(2, **DONE)]), {})

    def test_the_current_verdict_is_the_newest_about_the_same_text(self):
        """With a closed #1, an open #2 on another text and a closed #3 on #1's text, #1 names #3 and #2 stays current."""
        other = {"head": "Other.", "tail": "Other end.", "head_off": 0, "tail_off": 0}
        got = placed([latex(1, **DONE), latex(2, anchor=other), latex(3, **DONE)])
        self.assertEqual(got, {1: 3})

    def test_other_lines_or_files_are_other_targets(self):
        """A different range or a different file does not supersede."""
        self.assertEqual(placed([latex(1), latex(2, lo=4, hi=6)]), {})
        by_file = {2: Placement("ms", "tex", file="/ms/sections/other.tex")}
        self.assertEqual(placed([latex(1), latex(2)], by_file), {})

    def test_a_pin_that_lost_its_anchor_or_is_a_region_has_no_target(self):
        """A stale pin and a region pin are left out."""
        stale = latex(2, stale=True)
        self.assertEqual(placed([latex(1), stale]), {})
        self.assertIsNone(order_target(stale, Placement("ms", "tex", file="/ms/main.tex")))
        self.assertEqual(placed([latex(1), pdf_page(2)]), {})
        self.assertIsNone(order_target(latex(1), Placement("ms", "tex")))

    def test_same_lines_is_true_for_any_target_but_lines(self):
        """The anchor and the open state decide only between two pins about lines."""
        figure_target = order_target(figure(1), FIG_DOC)
        self.assertTrue(same_lines(figure_target, figure_target))

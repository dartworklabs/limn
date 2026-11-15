"""SyncTeX's forward lookup: where a source line is printed (source.synctex_view).

Run: uv run pytest -q src/limn/pins/location/tests/test_forward.py
"""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from limn.pins.location import (
    http as location_http,
    input as location_input,
    lookup,
    mapping,
    position,
    resolve as pick_resolve,
    source as pick_source,
)
from limn.pins.location.mapping import ViewBox
from limn.pins.model import LineSpan, OpenPin, PinCore, Region

from helpers import Base, needs_tex, ps


class SynctexView(unittest.TestCase):
    """The command asked and how its output is read."""

    def test_synctex_view_asks_by_line_and_column_zero_and_reads_every_page_record(self):
        """The input name is matched by suffix against the .synctex Input: records (the build copy's absolute paths), so it
        is manuscript-root-relative; every Page: record with its four numbers counts."""
        out = (
            "SyncTeX result begin\nOutput:main.pdf\nPage:14\nx:1\ny:2\nh:133.77\nv:349.81\nW:343.71\nH:8.86\n"
            "Page:14\nh:1\nv:2\nW:3\nH:4\n"
        )
        with mock.patch.object(pick_source.subprocess, "run", return_value=mock.Mock(stdout=out)) as run:
            got = pick_source.synctex_view(Path("/b/main.pdf"), 500, "sections/intro.tex")
        self.assertEqual(run.call_args[0][0][:4], ["synctex", "view", "-i", "500:0:sections/intro.tex"])
        self.assertEqual(got, [(14, 133.77, 349.81, 343.71, 8.86), (14, 1.0, 2.0, 3.0, 4.0)])

    def test_synctex_view_is_none_when_the_tool_is_missing_times_out_or_gives_no_page(self):
        """No answer is None, never an empty list."""
        for boom in (FileNotFoundError(), subprocess.TimeoutExpired("synctex", 10)):
            with mock.patch.object(pick_source.subprocess, "run", side_effect=boom):
                self.assertIsNone(pick_source.synctex_view(Path("/b/main.pdf"), 1, "main.tex"))
        with mock.patch.object(pick_source.subprocess, "run", return_value=mock.Mock(stdout="SyncTeX result begin\n")):
            self.assertIsNone(pick_source.synctex_view(Path("/b/main.pdf"), 1, "main.tex"))

    def test_synctex_view_drops_a_record_missing_one_of_its_four_numbers(self):
        """A Page: record without W: is not a box."""
        out = "Page:1\nh:1\nv:2\nH:4\nPage:2\nh:1\nv:2\nW:3\nH:4\n"
        with mock.patch.object(pick_source.subprocess, "run", return_value=mock.Mock(stdout=out)):
            self.assertEqual(pick_source.synctex_view(Path("/b/main.pdf"), 1, "main.tex"), [(2, 1.0, 2.0, 3.0, 4.0)])


TEX = r"""\documentclass{article}
\begin{document}
First paragraph line one of the body text,
which runs on and on for a while,
and ends here.

\begin{table}[t]
\centering
\begin{tabular}{ll}
alpha & one \\
beta & two \\
\end{tabular}
\end{table}

Last paragraph after the table.
\end{document}
"""


class RealSynctex(unittest.TestCase):
    """The real binary on a built page."""

    @needs_tex("pdflatex", "synctex")
    def test_a_body_line_and_a_table_row_get_different_boxes_on_page_one(self):
        """The body line is a full-width strip; each tabular row has its own row-high box."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(TEX, encoding="utf-8")
            subprocess.run(
                ["pdflatex", "-synctex=1", "-interaction=nonstopmode", "main.tex"],
                cwd=root,
                capture_output=True,
                timeout=120,
                check=True,
            )
            body = mapping.view_box(pick_source.synctex_view(root / "main.pdf", 3, "main.tex") or [], 1)
            row = mapping.view_box(pick_source.synctex_view(root / "main.pdf", 10, "main.tex") or [], 1)
            row2 = mapping.view_box(pick_source.synctex_view(root / "main.pdf", 11, "main.tex") or [], 1)
        self.assertIsNotNone(body)
        self.assertIsNotNone(row)
        self.assertIsNotNone(row2)
        self.assertEqual((body.page, row.page), (1, 1))
        self.assertNotEqual(body.box, row.box)
        self.assertEqual(row2.page, 1)
        # each row gets its own row box: same left edge and width, a row apart, no taller than a row
        self.assertAlmostEqual(row.box[0], row2.box[0], places=3)
        self.assertAlmostEqual(row.box[2], row2.box[2], places=3)
        self.assertLess(row.box[3] - row.box[1], 15)
        self.assertLess(row2.box[3] - row2.box[1], 15)
        self.assertGreater(row2.box[3] - row.box[3], 0)
        self.assertLess(row2.box[3] - row.box[3], 15)


class LineMark(unittest.TestCase):
    """One pin's mark: a page and the box as fractions of that page (position.line_mark)."""

    def test_line_mark_converts_points_to_that_pages_fractions(self):
        got = position.line_mark(ViewBox(2, (150.0, 100.0, 450.0, 120.0)), (600.0, 800.0), None)
        self.assertEqual((got.page, got.frac), (2, (0.25, 0.125, 0.5, 0.025)))

    def test_line_mark_uses_the_size_of_its_own_page_not_the_first(self):
        """A landscape page 2: the caller passes that page's size, so a wide page's mark is not squeezed."""
        got = position.line_mark(ViewBox(2, (0.0, 0.0, 400.0, 100.0)), (800.0, 600.0), None)
        self.assertEqual(got.frac, (0.0, 0.0, 0.5, 1.0 / 6.0))

    def test_line_mark_distrusts_a_same_build_answer_that_lands_on_another_page(self):
        span = ViewBox(5, (10.0, 10.0, 20.0, 20.0))
        self.assertIsNone(position.line_mark(span, (600.0, 800.0), 4))
        self.assertIsNotNone(position.line_mark(span, (600.0, 800.0), 5))

    def test_line_mark_is_none_without_a_span_or_a_positive_page_size(self):
        self.assertIsNone(position.line_mark(None, (600.0, 800.0), None))
        self.assertIsNone(position.line_mark(ViewBox(1, (0.0, 0.0, 1.0, 1.0)), (0.0, 800.0), None))

    def test_line_mark_clamps_the_box_to_the_page_before_dividing(self):
        """A box that overhangs the page edge is cut back to (0, 0, pw, ph) first."""
        got = position.line_mark(ViewBox(1, (-10.0, 700.0, 300.0, 900.0)), (600.0, 800.0), None)
        self.assertEqual(got.frac, (0.0, 0.875, 0.5, 0.125))

    def test_line_mark_is_none_when_clamping_leaves_no_width_or_height(self):
        """A box entirely below the page, or with its width cut to nothing, has no mark."""
        self.assertIsNone(position.line_mark(ViewBox(1, (10.0, 900.0, 50.0, 920.0)), (600.0, 800.0), None))
        self.assertIsNone(position.line_mark(ViewBox(1, (-50.0, 10.0, -5.0, 20.0)), (600.0, 800.0), None))


HIT = [(1, 10.0, 20.0, 30.0, 8.0)]


class FillMarks(unittest.TestCase):
    """The pass that fills the per-build mark cache (lookup.fill_marks)."""

    root = Path("/ms")  # the manuscript tree; the build runs in a copy elsewhere (/b), so no pin path is under it
    far = float("inf")

    def setUp(self):
        self.marks = lookup.LineMarks()

    def open_pin(self, pid, lo=3, hi=3, file=None, stale=None, **core):
        place = LineSpan(file or str(self.root / "main.tex"), lo, hi)
        return OpenPin(PinCore(id=pid, place=place, stale=stale, **core), None, {})

    def stale_pin(self, pid):
        return self.open_pin(pid, stale=True)

    def closed_pin(self, pid):
        from limn.pins.model import DonePin  # noqa: PLC0415

        pin = self.open_pin(pid)
        return mock.Mock(spec=DonePin, core=pin.core)

    def region_pin(self, pid):
        return OpenPin(PinCore(id=pid, place=Region("a.pdf", 1, [0.1, 0.1, 0.2, 0.2])), None, {})

    def locate(self, pin):
        """The repo's locator, reduced: the path below the manuscript root, or None for a file outside it."""
        try:
            rel = Path(pin.core.place.file).relative_to(self.root).as_posix()
        except ValueError:
            return None
        return lookup.PinLocation(rel, mock.Mock())

    def ctx(self, stale_src=False, sizes=((600.0, 800.0),), build="b1"):
        return lookup.MarkContext(build, sizes, Path("/b/main.pdf"), stale_src)

    def test_fill_marks_does_nothing_while_the_manuscript_is_newer_than_the_build(self):
        n = lookup.fill_marks(
            "d", [self.open_pin(1, lo=10, hi=12)], self.locate, self.ctx(stale_src=True), self.marks, 200, self.far
        )
        self.assertEqual(n, 0)
        self.assertIsNone(self.marks.get("d", "b1", 1))

    def test_fill_marks_skips_a_stale_pin_a_closed_pin_and_a_region_pin(self):
        pins = [self.stale_pin(1), self.closed_pin(2), self.region_pin(3)]
        with mock.patch.object(pick_source, "synctex_view", side_effect=AssertionError("no forward lookup")):
            self.assertEqual(lookup.fill_marks("d", pins, self.locate, self.ctx(), self.marks, 200, self.far), 0)

    def test_fill_marks_survives_a_document_whose_pages_are_gone(self):
        self.assertEqual(lookup.fill_marks("d", [self.open_pin(1)], self.locate, None, self.marks, 200, self.far), 0)

    def test_fill_marks_asks_once_for_a_one_line_pin_and_twice_for_a_span(self):
        with mock.patch.object(pick_source, "synctex_view", return_value=HIT) as view:
            lookup.fill_marks(
                "d",
                [self.open_pin(1, lo=7, hi=7), self.open_pin(2, lo=9, hi=11)],
                self.locate,
                self.ctx(),
                self.marks,
                200,
                self.far,
            )
        self.assertEqual([c[0][1] for c in view.call_args_list], [7, 9, 11])

    def test_fill_marks_passes_the_manuscript_relative_name_for_a_pin_in_a_tree_the_build_is_not_in(self):
        with mock.patch.object(pick_source, "synctex_view", return_value=HIT) as view:
            lookup.fill_marks(
                "d",
                [self.open_pin(1, file=str(self.root / "sections/intro.tex"))],
                self.locate,
                self.ctx(),
                self.marks,
                200,
                self.far,
            )
        self.assertEqual(view.call_args[0][2], "sections/intro.tex")

    def test_fill_marks_does_not_ask_again_for_a_pin_it_already_has_at_the_same_lines(self):
        with mock.patch.object(pick_source, "synctex_view", return_value=HIT) as view:
            self.assertEqual(
                lookup.fill_marks("d", [self.open_pin(1)], self.locate, self.ctx(), self.marks, 200, self.far), 1
            )
            self.assertEqual(
                lookup.fill_marks("d", [self.open_pin(1)], self.locate, self.ctx(), self.marks, 200, self.far), 0
            )
            self.assertEqual(view.call_count, 1)
            moved = [self.open_pin(1, lo=4, hi=4)]
            self.assertEqual(lookup.fill_marks("d", moved, self.locate, self.ctx(), self.marks, 200, self.far), 1)
            self.assertEqual(view.call_count, 2)

    def test_fill_marks_converts_with_the_size_of_the_hits_own_page(self):
        sizes = ((600.0, 800.0), (800.0, 600.0))
        with mock.patch.object(pick_source, "synctex_view", return_value=[(2, 100.0, 50.0, 400.0, 50.0)]):
            lookup.fill_marks("d", [self.open_pin(1)], self.locate, self.ctx(sizes=sizes), self.marks, 200, self.far)
        mark = self.marks.get("d", "b1", 1)
        self.assertEqual((mark.page, mark.frac), (2, (0.125, 0.0, 0.5, 50.0 / 600.0)))

    def test_fill_marks_gives_no_mark_for_a_page_whose_size_is_not_finite_and_positive(self):
        for size in ((float("nan"), 800.0), (600.0, 0.0), (float("inf"), 800.0)):
            with mock.patch.object(pick_source, "synctex_view", return_value=HIT):
                n = lookup.fill_marks(
                    "d", [self.open_pin(1)], self.locate, self.ctx(sizes=(size,)), self.marks, 200, self.far
                )
            self.assertEqual(n, 0)
            self.assertIsNone(self.marks.get("d", "b1", 1))

    def test_fill_marks_skips_a_pin_the_locator_cannot_place(self):
        pins = [self.open_pin(1, file="/elsewhere/x.tex")]
        with mock.patch.object(pick_source, "synctex_view", return_value=HIT) as view:
            n = lookup.fill_marks("d", pins, self.locate, self.ctx(), self.marks, 200, self.far)
        self.assertEqual((n, view.call_count), (0, 0))

    def test_fill_marks_remembers_an_empty_answer_until_the_lines_move_or_the_build_changes(self):
        pin = self.open_pin(2)
        with mock.patch.object(pick_source, "synctex_view", return_value=None) as view:
            for _ in range(3):
                self.assertEqual(lookup.fill_marks("d", [pin], self.locate, self.ctx(), self.marks, 200, self.far), 0)
            self.assertEqual(view.call_count, 1)
            self.assertTrue(self.marks.known("d", "b1", 2, 3, 3))
            self.assertIsNone(self.marks.get("d", "b1", 2))
            moved = [self.open_pin(2, lo=4, hi=4)]
            lookup.fill_marks("d", moved, self.locate, self.ctx(), self.marks, 200, self.far)
            lookup.fill_marks("d", [pin], self.locate, self.ctx(build="b2"), self.marks, 200, self.far)
            self.assertEqual(view.call_count, 3)

    def test_an_empty_answer_does_not_use_up_the_limit_so_later_pins_still_answer(self):
        pins = [self.open_pin(1), self.open_pin(2)]
        with mock.patch.object(pick_source, "synctex_view", side_effect=[None, HIT]):
            n = lookup.fill_marks("d", pins, self.locate, self.ctx(), self.marks, 1, self.far)
        self.assertEqual(n, 1)
        self.assertIsNotNone(self.marks.get("d", "b1", 2))

    def test_fill_marks_stops_at_the_limit_and_at_the_deadline(self):
        pins = [self.open_pin(i) for i in (1, 2, 3)]
        with mock.patch.object(pick_source, "synctex_view", return_value=HIT) as view:
            self.assertEqual(lookup.fill_marks("d", pins, self.locate, self.ctx(), self.marks, 2, self.far), 2)
            self.assertEqual(lookup.fill_marks("d", pins, self.locate, self.ctx(), self.marks, 200, 0.0), 0)
            self.assertEqual(view.call_count, 2)

    def test_line_marks_drop_the_oldest_entries_past_the_cap(self):
        marks = lookup.LineMarks(cap=2)
        mark = position.LineMark(1, (0.0, 0.0, 0.5, 0.5))
        for pid in (1, 2, 3):
            marks.put("d", "b", pid, 1, 1, mark)
        self.assertEqual([marks.get("d", "b", p) for p in (1, 2, 3)], [None, mark, mark])

    def test_line_marks_cap_each_document_and_build_on_its_own(self):
        marks = lookup.LineMarks(cap=2)
        mark = position.LineMark(1, (0.0, 0.0, 0.5, 0.5))
        for doc in ("a", "b"):
            for pid in (1, 2):
                marks.put(doc, "b1", pid, 1, 1, mark)
        self.assertTrue(all(marks.known(d, "b1", p, 1, 1) for d in ("a", "b") for p in (1, 2)))
        marks.put("a", "b1", 3, 1, 1, mark)
        self.assertFalse(marks.known("a", "b1", 1, 1, 1))
        self.assertTrue(marks.known("b", "b1", 1, 1, 1) and marks.known("b", "b1", 2, 1, 1))

    def test_a_pass_drops_the_documents_entries_of_other_builds_only(self):
        pins = [self.open_pin(1)]
        with mock.patch.object(pick_source, "synctex_view", return_value=HIT):
            lookup.fill_marks("d", pins, self.locate, self.ctx(build="b1"), self.marks, 200, self.far)
            lookup.fill_marks("e", pins, self.locate, self.ctx(build="b1"), self.marks, 200, self.far)
            lookup.fill_marks("d", pins, self.locate, self.ctx(build="b2"), self.marks, 200, self.far)
        self.assertIsNone(self.marks.get("d", "b1", 1))
        self.assertIsNotNone(self.marks.get("d", "b2", 1))
        self.assertIsNotNone(self.marks.get("e", "b1", 1))

    def test_fill_marks_trusts_a_stored_page_only_for_the_build_it_was_placed_on(self):
        on_screen = self.open_pin(1, pdf_build="b1", page=2)  # placed on this very build: its page is exact
        older = self.open_pin(2, pdf_build="b0", page=2)  # placed on another build: its page proves nothing
        with mock.patch.object(pick_source, "synctex_view", return_value=HIT):  # SyncTeX says page 1
            lookup.fill_marks("d", [on_screen, older], self.locate, self.ctx(), self.marks, 200, self.far)
        self.assertIsNone(self.marks.get("d", "b1", 1))
        self.assertEqual(self.marks.get("d", "b1", 2).page, 1)


class PickLevelBoxes(Base):
    """A pick answers, for every ladder level, where that level's own lines will stand on the page."""

    def setUp(self):
        """The fixture's document with a page folder; main.tex line 14 is a table row, so its ladder has two rungs: the
        line itself (14-14) and the table environment (12-16)."""
        super().setUp()
        self.D = ps.APP.docs[0]
        self.pages = self.D.dir / "pages"
        self.pages.mkdir(parents=True, exist_ok=True)
        (self.D.dir / "built_src_mtime.txt").write_text("%f" % (self.main.stat().st_mtime + 60), encoding="utf-8")

    def pick(self, lo=14, hi=14, sizes=((600.0, 800.0), (600.0, 800.0))):
        """pick_resolve.pick for a box on page 1, SyncTeX's backward answer lo..hi of the build copy's main.tex; returns
        the Picked value and the pick's body."""
        request = location_input.PickRequest(
            self.pages, 1, (10.0, 20.0, 150.0, 60.0), (600.0, 800.0), None, tuple(sizes)
        )
        with (
            mock.patch.object(pick_source, "by_synctex", return_value=(str(self.D.build / "main.tex"), lo, hi)),
            mock.patch.object(pick_source, "region_text", return_value=""),
        ):
            got = pick_resolve.pick(self.D, request, ps.APP.location_service.context())
        self.assertIsInstance(got, pick_resolve.Picked)
        return got, location_http.pick_answer(got)

    @staticmethod
    def hits_by_line(per_line):
        """A synctex_view stand-in answering from {line: [hits]}, None for any other line."""
        return lambda pdf, line, src: per_line.get(line)

    def test_every_pick_level_carries_the_box_its_range_will_actually_stand_on(self):
        """Every rung that gets an answer carries four page fractions and its page."""
        with mock.patch.object(pick_source, "synctex_view", return_value=[(2, 60.0, 120.0, 300.0, 20.0)]):
            _, answer = self.pick()
        levels = answer["levels"]
        self.assertGreaterEqual(len(levels), 2)
        for level in levels:
            self.assertEqual(level["mark_page"], 2)
            self.assertEqual(level["mark"], [0.1, 0.125, 0.5, 0.025])

    def test_each_level_is_asked_about_its_own_lines_and_not_the_default_levels(self):
        """Two rungs with different ranges get different boxes: the wider rung's box is the union of its two ends."""
        got, _ = self.pick()
        rungs = {lv["level"]: (lv["lo"], lv["hi"]) for lv in got.traced.levels}
        self.assertEqual(sorted(rungs.values()), [(12, 16), (14, 14)])
        by_line = {n: [(1, 10.0, 100.0 + 10 * n, 100.0 + n, 8.0)] for lo, hi in rungs.values() for n in (lo, hi)}
        with mock.patch.object(pick_source, "synctex_view", side_effect=self.hits_by_line(by_line)):
            got, answer = self.pick()
        for level in answer["levels"]:
            lo, hi = level["lo"], level["hi"]
            top = (100.0 + 10 * lo - 8.0) / 800.0
            bottom = (100.0 + 10 * hi) / 800.0
            self.assertAlmostEqual(level["mark"][1], top)
            self.assertAlmostEqual(level["mark"][1] + level["mark"][3], bottom)

    def test_a_level_whose_forward_lookup_fails_carries_no_box_and_the_pick_still_answers(self):
        with mock.patch.object(pick_source, "synctex_view", return_value=None):
            got, answer = self.pick()
        self.assertTrue(answer["levels"])
        for level in answer["levels"]:
            self.assertNotIn("mark", level)
            self.assertNotIn("mark_page", level)
        self.assertEqual((answer["lo"], answer["hi"]), (got.traced.lo, got.traced.hi))

    def test_only_the_level_that_fails_loses_its_box(self):
        """A lookup that answers for one rung's lines and not another's leaves exactly the other rung without a box."""
        got, _ = self.pick()
        rungs = got.traced.levels
        ends = {lv["level"]: {lv["lo"], lv["hi"]} for lv in rungs}
        first = rungs[0]["level"]
        only_first = {
            n: [(1, 10.0, 50.0, 30.0, 8.0)] for n in ends[first] if all(n not in ends[k] for k in ends if k != first)
        }
        self.assertTrue(only_first)
        with mock.patch.object(pick_source, "synctex_view", side_effect=self.hits_by_line(only_first)):
            _, answer = self.pick()
        for level in answer["levels"]:
            self.assertEqual("mark" in level, level["level"] == first, level["level"])

    def test_the_forward_lookups_are_capped_at_two_per_level(self):
        """No more than lo and hi of each level are asked, and every asked line is an end of some level."""
        got, _ = self.pick()
        levels = got.traced.levels
        with mock.patch.object(pick_source, "synctex_view", return_value=[(1, 1.0, 20.0, 3.0, 4.0)]) as view:
            self.pick()
        asked = [c[0][1] for c in view.call_args_list]
        self.assertLessEqual(len(asked), 2 * len(levels))
        self.assertEqual(set(asked), {n for lv in levels for n in (lv["lo"], lv["hi"])})

    def test_the_input_name_is_the_manuscript_relative_path(self):
        with mock.patch.object(pick_source, "synctex_view", return_value=None) as view:
            self.pick()
        self.assertEqual({c[0][2] for c in view.call_args_list}, {"main.tex"})
        self.assertTrue(view.call_args_list)

    def test_a_manuscript_edited_since_the_build_gets_no_boxes_and_no_lookup(self):
        """The build's SyncTeX numbers are not the file's numbers now, so nothing is asked."""
        (self.D.dir / "built_src_mtime.txt").write_text("%f" % (self.main.stat().st_mtime - 60), encoding="utf-8")
        with mock.patch.object(pick_source, "synctex_view", side_effect=AssertionError("no lookup")):
            _, answer = self.pick()
        self.assertTrue(all("mark" not in level for level in answer["levels"]))

    def test_a_box_on_a_page_the_request_has_no_size_for_is_dropped(self):
        with mock.patch.object(pick_source, "synctex_view", return_value=[(2, 60.0, 120.0, 300.0, 20.0)]):
            _, answer = self.pick(sizes=())
        self.assertTrue(all("mark" not in level for level in answer["levels"]))
